import type {
  ChatMessage,
  MistProject,
  ProjectFile,
  ProjectSyncRecord,
} from '../types/mist';
import { mistApi } from '../utils/apiClient';
import { chunkOperations, FIRESTORE_SAFE_BATCH_LIMIT } from './batchOps';

export { chunkOperations, FIRESTORE_SAFE_BATCH_LIMIT };

const knownCloudProjects = new Set<string>();
const syncRecords = new Map<string, ProjectSyncRecord>();
const syncListeners = new Set<() => void>();

function notifySyncListeners() {
  for (const listener of syncListeners) {
    listener();
  }
}

export function subscribeToSyncStatus(listener: () => void): () => void {
  syncListeners.add(listener);
  return () => {
    syncListeners.delete(listener);
  };
}

export function getSyncRecordsSnapshot(): Record<string, ProjectSyncRecord> {
  const out: Record<string, ProjectSyncRecord> = {};
  for (const [id, rec] of syncRecords.entries()) {
    out[id] = rec;
  }
  return out;
}

export function setProjectSyncRecord(record: ProjectSyncRecord): void {
  syncRecords.set(record.projectId, record);
  notifySyncListeners();
}

export function clearKnownCloudProjects(): void {
  knownCloudProjects.clear();
  syncRecords.clear();
  notifySyncListeners();
}

export function isProjectSyncedToCloud(projectId: string): boolean {
  return knownCloudProjects.has(projectId);
}

export async function listUserProjectsFromFirestore(
  _uid?: string,
  token?: string | null,
): Promise<MistProject[]> {
  try {
    const projects = await mistApi.listProjects(token);
    const now = new Date().toISOString();
    for (const p of projects) {
      knownCloudProjects.add(p.id);
      setProjectSyncRecord({
        projectId: p.id,
        state: 'synced',
        cloudFileCount: p.files.length,
        lastSyncedAt: now,
      });
    }
    return projects;
  } catch (err) {
    console.warn('[Mist Store] Failed to list projects via API:', err);
    return [];
  }
}

export async function verifyUserProjectsInFirestore(
  _uid: string,
  localProjects: MistProject[],
  token?: string | null,
): Promise<{
  verifiedAt: string;
  cloudProjectCount: number;
  allSynced: boolean;
}> {
  const verifiedAt = new Date().toISOString();
  try {
    const cloudProjects = await mistApi.listProjects(token);
    const cloudCounts = new Map<string, number>();

    for (const cp of cloudProjects) {
      knownCloudProjects.add(cp.id);
      cloudCounts.set(cp.id, cp.files.length);
    }

    let allSynced = true;
    for (const p of localProjects) {
      const cloudCount = cloudCounts.get(p.id);
      if (cloudCount === undefined) {
        allSynced = false;
        knownCloudProjects.delete(p.id);
        setProjectSyncRecord({
          projectId: p.id,
          state: 'local',
          cloudFileCount: 0,
        });
      } else {
        const filesMatch = cloudCount === p.files.length;
        if (!filesMatch) allSynced = false;
        setProjectSyncRecord({
          projectId: p.id,
          state: filesMatch ? 'synced' : 'local',
          cloudFileCount: cloudCount,
          lastSyncedAt: verifiedAt,
        });
      }
    }

    return {
      verifiedAt,
      cloudProjectCount: cloudCounts.size,
      allSynced,
    };
  } catch (err) {
    console.warn('[Mist Store] Could not verify projects against cloud:', err);
    return {
      verifiedAt,
      cloudProjectCount: 0,
      allSynced: false,
    };
  }
}

const projectSaveQueue = new Map<string, Promise<void>>();

export async function saveProjectToFirestore(
  project: MistProject,
  options?: { isNew?: boolean },
  token?: string | null,
  activeUid?: string | null,
): Promise<void> {
  if (activeUid && project.ownerId && project.ownerId !== activeUid) {
    const errorMsg = `Project ownership mismatch: project ${project.id} belongs to ${project.ownerId}, not ${activeUid}`;
    console.warn(`[Mist Store] ${errorMsg}`);
    setProjectSyncRecord({
      projectId: project.id,
      state: 'error',
      error: 'Ownership mismatch: cannot update another user project',
    });
    throw new Error(errorMsg);
  }

  const prev = projectSaveQueue.get(project.id) || Promise.resolve();
  const next = prev
    .catch(() => {})
    .then(async () => {
      setProjectSyncRecord({
        projectId: project.id,
        state: 'syncing',
        cloudFileCount: syncRecords.get(project.id)?.cloudFileCount,
        lastSyncedAt: syncRecords.get(project.id)?.lastSyncedAt,
      });

      try {
        if (options?.isNew && !knownCloudProjects.has(project.id)) {
          await mistApi.createProject(project, token);
        } else {
          await mistApi.updateProject(project, token);
        }
        knownCloudProjects.add(project.id);
        setProjectSyncRecord({
          projectId: project.id,
          state: 'synced',
          cloudFileCount: project.files.length,
          lastSyncedAt: new Date().toISOString(),
        });
      } catch (error) {
        console.warn(`[Mist Store] Failed to save project ${project.id}:`, error);
        setProjectSyncRecord({
          projectId: project.id,
          state: 'error',
          error: error instanceof Error ? error.message : 'Sync failed',
        });
      }
    });

  projectSaveQueue.set(project.id, next);
  try {
    await next;
  } finally {
    if (projectSaveQueue.get(project.id) === next) {
      projectSaveQueue.delete(project.id);
    }
  }
}

export async function deleteProjectFromFirestore(
  projectId: string,
  token?: string | null,
): Promise<void> {
  knownCloudProjects.delete(projectId);
  syncRecords.delete(projectId);
  notifySyncListeners();

  try {
    await mistApi.deleteProject(projectId, token);
  } catch (err) {
    console.warn(`[Mist Store] Failed to delete project ${projectId}:`, err);
  }
}

export async function saveDeploymentToFirestore(
  params: {
    slug: string;
    projectId: string;
    title: string;
    files: ProjectFile[];
  },
  token?: string | null,
): Promise<void> {
  try {
    await mistApi.deployWebsite(params, token);
  } catch (err) {
    console.warn('[Mist Store] Failed to save deployment:', err);
  }
}

export async function syncLocalProjectsToFirestore(
  projects: MistProject[],
  cloudIds?: Set<string>,
  token?: string | null,
  activeUid?: string | null,
): Promise<number> {
  if (projects.length === 0) return 0;
  let syncedCount = 0;
  for (const project of projects) {
    // If project is owned by someone else, never sync it to active user's account
    if (activeUid && project.ownerId && project.ownerId !== activeUid) {
      continue;
    }
    const alreadyInCloud = cloudIds ? cloudIds.has(project.id) : knownCloudProjects.has(project.id);
    if (!alreadyInCloud) {
      try {
        await saveProjectToFirestore(project, { isNew: true }, token, activeUid);
        syncedCount++;
      } catch (err) {
        console.warn(`[Mist Store] Failed to sync local project ${project.id} to cloud:`, err);
      }
    }
  }
  return syncedCount;
}
