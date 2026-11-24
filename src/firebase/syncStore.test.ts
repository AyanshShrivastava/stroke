import test from 'node:test';
import assert from 'node:assert/strict';
import {
  clearPendingDirtyQueue,
  dequeueProjectFromBatchedSync,
  flushBatchedSyncNow,
  getDirtyProjectsStorageKey,
  getProjectsStorageKey,
  getPendingDirtyCount,
  getPendingDirtyProjects,
  initLocalCacheQueue,
  queueProjectForBatchedSync,
  setBatchedSyncUserProvider,
} from './batchedProjectSync';
import {
  getSyncRecordsSnapshot,
  setProjectSyncRecord,
  saveProjectToFirestore,
  syncLocalProjectsToFirestore,
} from './store';
import { mistApi } from '../utils/apiClient';
import { createMistApp } from '../utils/mistServerApp';
import { createMemoryDeploymentStore } from '../utils/deploymentStore';
import type { MistProject, MistUser } from '../types/mist';
import type { VerifiedFirebaseUser } from '../utils/serverSecurity';

// Minimal mock localStorage implementation for Node test environment
class MockLocalStorage {
  private store = new Map<string, string>();

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  clear(): void {
    this.store.clear();
  }

  get length(): number {
    return this.store.size;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }
}

// Install mock localStorage globally for tests
if (typeof globalThis.localStorage === 'undefined') {
  (globalThis as any).localStorage = new MockLocalStorage();
}

function createSampleProject(id: string, name: string, ownerId?: string, createdAt?: string): MistProject {
  const now = new Date().toISOString();
  return {
    id,
    ownerId,
    name,
    description: `Description for ${name}`,
    prompt: `Prompt for ${name}`,
    isPublished: false,
    files: [
      {
        id: `f_${id}`,
        path: 'src/App.tsx',
        language: 'tsx',
        content: `export default function App() { return <h1>${name}</h1>; }`,
      },
    ],
    chatHistory: [],
    createdAt: createdAt || now,
    updatedAt: now,
  };
}

test('Account-specific local project storage & safe separation of guest drafts', () => {
  localStorage.clear();

  // Storage key scoping
  assert.equal(getProjectsStorageKey('user_alice'), 'mist_projects_user_alice');
  assert.equal(getProjectsStorageKey('user_bob'), 'mist_projects_user_bob');
  assert.equal(getProjectsStorageKey(null), 'mist_projects_anonymous');
  assert.equal(getProjectsStorageKey(undefined), 'mist_projects_anonymous');

  // Alice saves local projects
  const aliceProjects = [
    createSampleProject('proj_alice_1', 'Alice Project 1', 'user_alice'),
    createSampleProject('proj_alice_2', 'Alice Project 2', 'user_alice'),
  ];
  localStorage.setItem(getProjectsStorageKey('user_alice'), JSON.stringify(aliceProjects));

  // Anonymous guest saves local draft
  const anonProjects = [
    createSampleProject('proj_anon_1', 'Anonymous Draft', undefined),
  ];
  localStorage.setItem(getProjectsStorageKey(null), JSON.stringify(anonProjects));

  // Bob saves local projects
  const bobProjects = [
    createSampleProject('proj_bob_1', 'Bob Project 1', 'user_bob'),
  ];
  localStorage.setItem(getProjectsStorageKey('user_bob'), JSON.stringify(bobProjects));

  // Verify accounts are strictly isolated in storage
  const loadedAlice = JSON.parse(localStorage.getItem(getProjectsStorageKey('user_alice'))!);
  const loadedBob = JSON.parse(localStorage.getItem(getProjectsStorageKey('user_bob'))!);
  const loadedAnon = JSON.parse(localStorage.getItem(getProjectsStorageKey(null))!);

  assert.equal(loadedAlice.length, 2);
  assert.equal(loadedAlice[0].id, 'proj_alice_1');
  assert.equal(loadedBob.length, 1);
  assert.equal(loadedBob[0].id, 'proj_bob_1');
  assert.equal(loadedAnon.length, 1);
  assert.equal(loadedAnon[0].id, 'proj_anon_1');

  // Verify Bob never reads Alice's or Anonymous projects
  assert.ok(!loadedBob.some((p: MistProject) => p.id === 'proj_alice_1'));
  assert.ok(!loadedBob.some((p: MistProject) => p.id === 'proj_anon_1'));

  // Verify Anonymous never reads Alice's or Bob's projects
  assert.ok(!loadedAnon.some((p: MistProject) => p.id === 'proj_alice_1'));
  assert.ok(!loadedAnon.some((p: MistProject) => p.id === 'proj_bob_1'));
});

test('Account-specific dirty synchronization queues and ownership enforcement', () => {
  localStorage.clear();

  assert.equal(getDirtyProjectsStorageKey('user_alice'), 'mist_dirty_projects_user_alice');
  assert.equal(getDirtyProjectsStorageKey('user_bob'), 'mist_dirty_projects_user_bob');
  assert.equal(getDirtyProjectsStorageKey(null), 'mist_dirty_projects_anonymous');

  clearPendingDirtyQueue('user_alice');
  clearPendingDirtyQueue('user_bob');
  clearPendingDirtyQueue(null);

  const pAlice = createSampleProject('p_alice', 'Alice Project', 'user_alice');
  const pBob = createSampleProject('p_bob', 'Bob Project', 'user_bob');
  const pAnon = createSampleProject('p_anon', 'Anon Project');

  // Queue dirty items under their respective accounts
  queueProjectForBatchedSync(pAlice, 'user_alice');
  queueProjectForBatchedSync(pBob, 'user_bob');
  queueProjectForBatchedSync(pAnon, null);

  assert.equal(getPendingDirtyCount('user_alice'), 1);
  assert.equal(getPendingDirtyCount('user_bob'), 1);
  assert.equal(getPendingDirtyCount(null), 1);

  // Cross-account queuing is rejected: queuing a project owned by Alice under Bob's account is blocked
  queueProjectForBatchedSync(pAlice, 'user_bob');
  assert.equal(getPendingDirtyCount('user_bob'), 1); // Still 1, pAlice was rejected!

  // Dequeueing from Alice's queue leaves Bob's and Anonymous queues intact
  dequeueProjectFromBatchedSync('p_alice', 'user_alice');
  assert.equal(getPendingDirtyCount('user_alice'), 0);
  assert.equal(getPendingDirtyCount('user_bob'), 1);
  assert.equal(getPendingDirtyCount(null), 1);

  // Persistence in localStorage
  assert.equal(localStorage.getItem('mist_dirty_projects_user_alice'), null);
  assert.ok(localStorage.getItem('mist_dirty_projects_user_bob')?.includes('p_bob'));
  assert.ok(localStorage.getItem('mist_dirty_projects_anonymous')?.includes('p_anon'));
});

test('Offline operation: failed writes remain queued, mark error state, and retry upon recovery', async () => {
  localStorage.clear();
  clearPendingDirtyQueue('user_alice');

  const mockUser: MistUser = {
    id: 'user_alice',
    uid: 'user_alice',
    email: 'alice@example.com',
    displayName: 'Alice',
    photoURL: null,
    emailVerified: true,
    getIdToken: async () => 'mock_token',
  };

  const project = createSampleProject('proj_retry_1', 'Retry Project', 'user_alice');
  queueProjectForBatchedSync(project, 'user_alice');
  assert.equal(getPendingDirtyCount('user_alice'), 1);

  // 1. Simulate network failure / offline
  const originalSync = mistApi.syncProjects;
  mistApi.syncProjects = async () => {
    throw new Error('Network connection offline');
  };

  try {
    const res = await flushBatchedSyncNow(mockUser);
    assert.equal(res.synced, 0);
    assert.equal(res.remaining, 1);

    // Project MUST remain queued for retry
    assert.equal(getPendingDirtyCount('user_alice'), 1);

    // Sync status is marked as error
    const syncStatus = getSyncRecordsSnapshot()['proj_retry_1'];
    assert.equal(syncStatus?.state, 'error');
    assert.ok(syncStatus?.error?.includes('Network connection offline'));

    // 2. Recovery: Network connection restored
    mistApi.syncProjects = async (projects) => {
      return {
        synced: projects.length,
        successfulProjectIds: projects.map((p) => p.id),
        failedProjects: [],
      };
    };

    const recoveryRes = await flushBatchedSyncNow(mockUser);
    assert.equal(recoveryRes.synced, 1);
    assert.equal(recoveryRes.remaining, 0);

    // Project is now dequeued
    assert.equal(getPendingDirtyCount('user_alice'), 0);

    // Sync status is updated to synced with timestamp
    const recoveredStatus = getSyncRecordsSnapshot()['proj_retry_1'];
    assert.equal(recoveredStatus?.state, 'synced');
    assert.ok(recoveredStatus?.lastSyncedAt);
  } finally {
    mistApi.syncProjects = originalSync;
  }
});

test('Concurrent flushes are deduplicated to prevent race conditions', async () => {
  clearPendingDirtyQueue('user_race');

  let callCount = 0;
  const originalSync = mistApi.syncProjects;
  mistApi.syncProjects = async (projects) => {
    callCount++;
    await new Promise((resolve) => setTimeout(resolve, 50));
    return {
      synced: projects.length,
      successfulProjectIds: projects.map((p) => p.id),
      failedProjects: [],
    };
  };

  const mockUser: MistUser = {
    id: 'user_race',
    uid: 'user_race',
    email: 'race@example.com',
    displayName: 'Race User',
    photoURL: null,
    emailVerified: true,
    getIdToken: async () => 'mock_token',
  };

  const project = createSampleProject('p_race_1', 'Race Project', 'user_race');
  queueProjectForBatchedSync(project, 'user_race');

  try {
    // Fire two flushes concurrently
    const [res1, res2] = await Promise.all([
      flushBatchedSyncNow(mockUser),
      flushBatchedSyncNow(mockUser),
    ]);

    // Should only trigger ONE network call
    assert.equal(callCount, 1);
    assert.equal(res1.synced, 1);
    assert.equal(res2.synced, 1);
  } finally {
    mistApi.syncProjects = originalSync;
  }
});

test('saveProjectToFirestore and syncLocalProjectsToFirestore reject ownership mismatches', async () => {
  const pAlice = createSampleProject('p_cross_1', 'Alice Project', 'user_alice');

  // Attempt to save Alice's project under Bob's UID -> rejected
  await assert.rejects(
    () => saveProjectToFirestore(pAlice, { isNew: true }, 'mock_token', 'user_bob'),
    /Project ownership mismatch/,
  );

  // syncLocalProjectsToFirestore skips projects that belong to another user
  const synced = await syncLocalProjectsToFirestore([pAlice], new Set(), 'mock_token', 'user_bob');
  assert.equal(synced, 0); // Alice's project was skipped cleanly
});

test('POST /api/projects/sync-dump: validation, size limits, createdAt preservation, and partial failures', async () => {
  const users: Record<string, VerifiedFirebaseUser> = {
    'token-alice': {
      userId: 'user-alice',
      uid: 'user-alice',
      email: 'alice@example.com',
      emailVerified: true,
      idToken: 'token-alice',
    },
    'token-bob': {
      userId: 'user-bob',
      uid: 'user-bob',
      email: 'bob@example.com',
      emailVerified: true,
      idToken: 'token-bob',
    },
  };

  const store = createMemoryDeploymentStore();
  const app = createMistApp({
    deploymentStore: store,
    skipDnsLookup: true,
    publishBaseUrl: 'https://sites.mist.me',
    verifyAuthHeader: async (header?: string) => {
      const token = header?.slice('Bearer '.length).trim();
      const u = token ? users[token] : null;
      if (!u) throw new Error('Unauthorized');
      return u;
    },
  });

  const server = app.listen(0);
  const port = (server.address() as any).port;
  const baseUrl = `http://127.0.0.1:${port}`;

  try {
    // 1. Set createdAt correctly when creating new projects & preserve client createdAt
    const explicitCreatedAt = '2025-05-10T10:30:00.000Z';
    const projAlice = createSampleProject('proj_dump_alice', 'Dump Alice', 'user-alice', explicitCreatedAt);

    const resp1 = await fetch(`${baseUrl}/api/projects/sync-dump`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ projects: [projAlice] }),
    });

    assert.equal(resp1.status, 200);
    const data1 = (await resp1.json()) as any;
    assert.equal(data1.ok, true);
    assert.equal(data1.success, true);
    assert.equal(data1.syncedProjects, 1);
    assert.deepEqual(data1.successfulProjectIds, ['proj_dump_alice']);
    assert.deepEqual(data1.failedProjects, []);

    // Verify project in database preserves createdAt
    const checkResp = await fetch(`${baseUrl}/api/projects/proj_dump_alice`, {
      headers: { Authorization: 'Bearer token-alice' },
    });
    const checkData = (await checkResp.json()) as any;
    assert.equal(checkData.project.createdAt, explicitCreatedAt);

    // 2. Subsequent update preserves existing createdAt
    const updatedAlice = {
      ...projAlice,
      name: 'Dump Alice Updated Name',
      updatedAt: '2026-11-23T00:00:00.000Z',
    };
    const resp2 = await fetch(`${baseUrl}/api/projects/sync-dump`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ projects: [updatedAlice] }),
    });
    assert.equal(resp2.status, 200);

    const checkResp2 = await fetch(`${baseUrl}/api/projects/proj_dump_alice`, {
      headers: { Authorization: 'Bearer token-alice' },
    });
    const checkData2 = (await checkResp2.json()) as any;
    assert.equal(checkData2.project.name, 'Dump Alice Updated Name');
    assert.equal(checkData2.project.createdAt, explicitCreatedAt); // Still original createdAt!

    // 3. Size limit: Batch > 50 projects rejected with 400
    const oversizedBatch = Array.from({ length: 51 }, (_, i) =>
      createSampleProject(`p_over_${i}`, `Over ${i}`, 'user-alice'),
    );
    const overResp = await fetch(`${baseUrl}/api/projects/sync-dump`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ projects: oversizedBatch }),
    });
    assert.equal(overResp.status, 400);
    const overData = (await overResp.json()) as any;
    assert.equal(overData.ok, false);
    assert.ok(overData.error.includes('maximum allowed projects (50)'));

    // 4. Payload validation: Prototype pollution rejected with 400
    const pollutedPayload = JSON.parse(
      '{"projects":[{"id":"p_pollute","name":"p","files":[],"__proto__":{"polluted":true}}]}',
    );
    const polluteResp = await fetch(`${baseUrl}/api/projects/sync-dump`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify(pollutedPayload),
    });
    const polluteData = (await polluteResp.json()) as any;
    assert.equal(polluteData.ok, false);
    assert.ok(polluteData.failedProjects.length > 0 || polluteData.error);

    // 5. Payload validation: Path traversal in files rejected with 400
    const traversalProject = {
      id: 'p_traversal',
      name: 'Traversal',
      files: [{ id: 'f1', path: '../etc/passwd', language: 'tsx', content: 'hack' }],
    };
    const traversalResp = await fetch(`${baseUrl}/api/projects/sync-dump`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ projects: [traversalProject] }),
    });
    const traversalData = (await traversalResp.json()) as any;
    assert.equal(traversalData.ok, false);
    assert.equal(traversalData.syncedProjects, 0);
    assert.ok(traversalData.failedProjects[0].error.includes('Unsafe file path'));

    // 6. Cross-account ownership and partial failure reporting:
    // Bob sends a batch containing:
    // - proj_bob_new (valid new project owned by Bob)
    // - proj_dump_alice (owned by Alice)
    const projBobNew = createSampleProject('proj_bob_valid', 'Bob Project', 'user-bob');
    const stolenAliceProj = {
      ...projAlice,
      name: 'Bob Overwrite Attempt',
    };

    const partialResp = await fetch(`${baseUrl}/api/projects/sync-dump`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-bob',
      },
      body: JSON.stringify({ projects: [projBobNew, stolenAliceProj] }),
    });

    // Partial failure: HTTP 207 Multi-Status
    assert.equal(partialResp.status, 207);
    const partialData = (await partialResp.json()) as any;

    // Never report success when Firestore rejects a write!
    assert.equal(partialData.ok, false);
    assert.equal(partialData.success, false);

    // Partial failures are visible and recoverable
    assert.equal(partialData.syncedProjects, 1);
    assert.deepEqual(partialData.successfulProjectIds, ['proj_bob_valid']);
    assert.equal(partialData.failedProjects.length, 1);
    assert.equal(partialData.failedProjects[0].id, 'proj_dump_alice');
    assert.ok(partialData.failedProjects[0].error.includes('Access denied'));

    // Verify Alice's project in database was NOT overwritten by Bob
    const checkAliceUntouched = await fetch(`${baseUrl}/api/projects/proj_dump_alice`, {
      headers: { Authorization: 'Bearer token-alice' },
    });
    const aliceData = (await checkAliceUntouched.json()) as any;
    assert.equal(aliceData.project.name, 'Dump Alice Updated Name'); // Not changed to 'Bob Overwrite Attempt'
  } finally {
    server.close();
  }
});
