/**
 * Account-Specific Local-First Batched Sync Manager for Mist Projects.
 *
 * All modifications are saved instantly to the browser's account-scoped local cache.
 * There is NO periodic 10-second sync timer: network/cloud sync happens
 * on app exit, window blur/pagehide, visibility change, and on network reconnect.
 * On exit, pending dirty projects for the active account are dumped to backend
 * /api/projects/sync-dump with keepalive: true, scoped strictly to the verified Clerk account.
 * Anonymous drafts are safely separated and never dumped to authenticated accounts.
 */

import type { MistProject, MistUser } from '../types/mist';
import { mistApi } from '../utils/apiClient';
import { setProjectSyncRecord } from './store';

export function getProjectsStorageKey(userId?: string | null): string {
  return userId ? `mist_projects_${userId}` : 'mist_projects_anonymous';
}

export function getDirtyProjectsStorageKey(userId?: string | null): string {
  return userId ? `mist_dirty_projects_${userId}` : 'mist_dirty_projects_anonymous';
}

const accountDirtyQueues = new Map<string, Map<string, MistProject>>();
const inFlightFlushes = new Map<string, Promise<{ synced: number; remaining: number }>>();

let currentUserProvider: () => MistUser | null = () => null;

export function setBatchedSyncUserProvider(provider: () => MistUser | null): void {
  currentUserProvider = provider;
}

function getAccountKey(userId?: string | null): string {
  return userId?.trim() || 'anonymous';
}

function getOrCreateAccountQueue(userId?: string | null): Map<string, MistProject> {
  const key = getAccountKey(userId);
  let queue = accountDirtyQueues.get(key);
  if (!queue) {
    queue = new Map<string, MistProject>();
    accountDirtyQueues.set(key, queue);
    try {
      if (typeof localStorage !== 'undefined') {
        const raw = localStorage.getItem(getDirtyProjectsStorageKey(userId));
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) {
            for (const p of parsed) {
              if (p && p.id) {
                queue.set(p.id, p);
              }
            }
          }
        }
      }
    } catch {
      // ignore storage access errors
    }
  }
  return queue;
}

function persistAccountDirtyQueue(userId?: string | null): void {
  try {
    if (typeof localStorage === 'undefined') return;
    const key = getAccountKey(userId);
    const queue = accountDirtyQueues.get(key);
    const storageKey = getDirtyProjectsStorageKey(userId);
    if (!queue || queue.size === 0) {
      localStorage.removeItem(storageKey);
    } else {
      localStorage.setItem(storageKey, JSON.stringify(Array.from(queue.values())));
    }
  } catch {
    // ignore quota errors
  }
}

export function clearPendingDirtyQueue(userId?: string | null): void {
  const effectiveUid = userId !== undefined ? userId : currentUserProvider()?.uid;
  const key = getAccountKey(effectiveUid);
  accountDirtyQueues.delete(key);
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(getDirtyProjectsStorageKey(effectiveUid));
    }
  } catch {
    // ignore
  }
}

export function initLocalCacheQueue(userId?: string | null): void {
  const effectiveUid = userId !== undefined ? userId : currentUserProvider()?.uid;
  const key = getAccountKey(effectiveUid);
  const queue = new Map<string, MistProject>();
  try {
    if (typeof localStorage !== 'undefined') {
      const raw = localStorage.getItem(getDirtyProjectsStorageKey(effectiveUid));
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          for (const p of parsed) {
            if (p && p.id) {
              queue.set(p.id, p);
            }
          }
        }
      }
    }
  } catch {
    // ignore
  }
  accountDirtyQueues.set(key, queue);
}

export function queueProjectForBatchedSync(project: MistProject, userId?: string | null): void {
  const effectiveUid = userId !== undefined ? userId : currentUserProvider()?.uid;
  // If authenticated, ensure project is not owned by someone else
  if (effectiveUid && project.ownerId && project.ownerId !== effectiveUid) {
    console.warn(
      `[BatchedSync] Ownership mismatch: refusing to queue project ${project.id} (owner: ${project.ownerId}) for user ${effectiveUid}`,
    );
    return;
  }
  const queue = getOrCreateAccountQueue(effectiveUid);
  queue.set(project.id, project);
  persistAccountDirtyQueue(effectiveUid);

  // Update sync status record to local (un-synced changes)
  setProjectSyncRecord({
    projectId: project.id,
    state: 'local',
  });
}

export function dequeueProjectFromBatchedSync(projectId: string, userId?: string | null): void {
  const effectiveUid = userId !== undefined ? userId : currentUserProvider()?.uid;
  const queue = getOrCreateAccountQueue(effectiveUid);
  queue.delete(projectId);
  persistAccountDirtyQueue(effectiveUid);
}

export function getPendingDirtyCount(userId?: string | null): number {
  const effectiveUid = userId !== undefined ? userId : currentUserProvider()?.uid;
  const queue = getOrCreateAccountQueue(effectiveUid);
  return queue.size;
}

export function getPendingDirtyProjects(userId?: string | null): MistProject[] {
  const effectiveUid = userId !== undefined ? userId : currentUserProvider()?.uid;
  const queue = getOrCreateAccountQueue(effectiveUid);
  return Array.from(queue.values());
}

export async function flushBatchedSyncNow(user?: MistUser | null): Promise<{ synced: number; remaining: number }> {
  const activeUser = user !== undefined ? user : currentUserProvider();
  if (!activeUser || !activeUser.uid) {
    // Anonymous drafts remain local-only
    return { synced: 0, remaining: getPendingDirtyCount(null) };
  }

  const userUid = activeUser.uid;
  if (inFlightFlushes.has(userUid)) {
    return inFlightFlushes.get(userUid)!;
  }

  const queue = getOrCreateAccountQueue(userUid);
  if (queue.size === 0) {
    return { synced: 0, remaining: 0 };
  }

  const flushPromise = (async () => {
    const snapshot = Array.from(queue.values());
    for (const p of snapshot) {
      setProjectSyncRecord({
        projectId: p.id,
        state: 'syncing',
      });
    }

    try {
      const token = await activeUser.getIdToken();
      const res = await mistApi.syncProjects(snapshot, token);

      const successfulIds = new Set(
        res.successfulProjectIds || (res.synced === snapshot.length ? snapshot.map((p) => p.id) : []),
      );

      const now = new Date().toISOString();
      for (const p of snapshot) {
        if (successfulIds.has(p.id)) {
          queue.delete(p.id);
          setProjectSyncRecord({
            projectId: p.id,
            state: 'synced',
            cloudFileCount: p.files.length,
            lastSyncedAt: now,
          });
        } else {
          // Failed writes remain queued and are retried!
          const failure = res.failedProjects?.find((f) => f.id === p.id);
          setProjectSyncRecord({
            projectId: p.id,
            state: 'error',
            error: failure?.error || 'Write rejected by cloud',
          });
        }
      }

      return { synced: successfulIds.size, remaining: queue.size };
    } catch (err) {
      console.warn('[BatchedSync] Flush failure:', err);
      const errMsg = err instanceof Error ? err.message : 'Sync network error';
      for (const p of snapshot) {
        setProjectSyncRecord({
          projectId: p.id,
          state: 'error',
          error: errMsg,
        });
      }
      return { synced: 0, remaining: queue.size };
    } finally {
      persistAccountDirtyQueue(userUid);
      inFlightFlushes.delete(userUid);
    }
  })();

  inFlightFlushes.set(userUid, flushPromise);
  return flushPromise;
}

export async function flushBatchedSyncOnAppExit(user?: MistUser | null): Promise<void> {
  const activeUser = user !== undefined ? user : currentUserProvider();
  if (!activeUser || !activeUser.uid) return;

  const queue = getOrCreateAccountQueue(activeUser.uid);
  if (queue.size === 0) return;

  const dirtyList = Array.from(queue.values());

  try {
    const token = await activeUser.getIdToken();
    if (token) {
      void fetch('/api/projects/sync-dump', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        keepalive: true,
        body: JSON.stringify({ projects: dirtyList }),
      }).then(async (resp) => {
        if (resp.ok || resp.status === 207) {
          const data = (await resp.json()) as { successfulProjectIds?: string[] };
          if (Array.isArray(data.successfulProjectIds)) {
            for (const id of data.successfulProjectIds) {
              queue.delete(id);
            }
            persistAccountDirtyQueue(activeUser.uid);
          }
        }
      }).catch((err) => {
        console.warn('[BatchedSync] Exit sync dump beacon error:', err);
      });
    }
  } catch (tokenErr) {
    console.warn('[BatchedSync] Could not obtain token on app close:', tokenErr);
  }

  void flushBatchedSyncNow(activeUser).catch(() => {});
}

// Automatically retry queued dirty writes when browser comes back online
if (typeof window !== 'undefined') {
  window.addEventListener('online', () => {
    const active = currentUserProvider();
    if (active) {
      void flushBatchedSyncNow(active).catch(() => {});
    }
  });
}
