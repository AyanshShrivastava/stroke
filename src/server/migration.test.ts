import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  resolveIdentities,
  executeMigration,
  formatReport,
  executeRollback,
  formatRollbackReport,
  type FirebaseUserRecord,
  type ClerkUserRecord,
} from '../../scripts/migrate-identities';

test('resolveIdentities handles modern Clerk IDs, clean 1:1 verified matches, unverified emails, and conflicts', () => {
  const firebaseUsers = new Map<string, FirebaseUserRecord>([
    ['firebase-uid-alice', { uid: 'firebase-uid-alice', email: 'alice@example.com', emailVerified: true }],
    ['firebase-uid-bob', { uid: 'firebase-uid-bob', email: 'bob@example.com', emailVerified: false }], // unverified in FB
    ['firebase-uid-carol', { uid: 'firebase-uid-carol', email: 'carol@example.com', emailVerified: true }],
    ['firebase-uid-dan', { uid: 'firebase-uid-dan', email: 'dan@example.com', emailVerified: true }],
    ['firebase-uid-orphan', { uid: 'firebase-uid-orphan' }], // no email
  ]);

  const clerkUsers: ClerkUserRecord[] = [
    {
      id: 'user_clerk_alice',
      emailAddresses: [{ emailAddress: 'alice@example.com', verification: { status: 'verified' } }],
    },
    {
      id: 'user_clerk_bob',
      emailAddresses: [{ emailAddress: 'bob@example.com', verification: { status: 'verified' } }],
    },
    {
      id: 'user_clerk_carol_1',
      emailAddresses: [{ emailAddress: 'carol@example.com', verification: { status: 'verified' } }],
    },
    {
      id: 'user_clerk_carol_2',
      emailAddresses: [{ emailAddress: 'carol@example.com', verification: { status: 'verified' } }],
    },
    {
      id: 'user_clerk_dan',
      emailAddresses: [{ emailAddress: 'dan@example.com', verification: { status: 'unverified' } }], // unverified in Clerk
    },
  ];

  const uidsToTest = [
    'user_already_clerk_123',
    'firebase-uid-alice',
    'firebase-uid-bob',
    'firebase-uid-carol',
    'firebase-uid-dan',
    'firebase-uid-orphan',
  ];

  const resolved = resolveIdentities(uidsToTest, firebaseUsers, clerkUsers);

  // 1. Modern Clerk ID
  const clerkMatch = resolved.get('user_already_clerk_123')!;
  assert.equal(clerkMatch.status, 'already_clerk');
  assert.equal(clerkMatch.newClerkId, 'user_already_clerk_123');

  // 2. Alice: clean verified 1:1 match
  const aliceMatch = resolved.get('firebase-uid-alice')!;
  assert.equal(aliceMatch.status, 'mapped');
  assert.equal(aliceMatch.newClerkId, 'user_clerk_alice');
  assert.equal(aliceMatch.email, 'alice@example.com');

  // 3. Bob: unverified in Firebase -> must be rejected / unmapped
  const bobMatch = resolved.get('firebase-uid-bob')!;
  assert.equal(bobMatch.status, 'unmapped');
  assert.match(bobMatch.reason, /Firebase email is unverified/i);

  // 4. Carol: multiple Clerk accounts -> conflict (must never silently reassign)
  const carolMatch = resolved.get('firebase-uid-carol')!;
  assert.equal(carolMatch.status, 'conflict');
  assert.match(carolMatch.reason, /Multiple Clerk accounts/i);

  // 5. Dan: unverified in Clerk -> must be rejected / unmapped
  const danMatch = resolved.get('firebase-uid-dan')!;
  assert.equal(danMatch.status, 'unmapped');
  assert.match(danMatch.reason, /No verified Clerk account/i);

  // 6. Orphan: no email -> unmapped
  const orphanMatch = resolved.get('firebase-uid-orphan')!;
  assert.equal(orphanMatch.status, 'unmapped');
  assert.match(orphanMatch.reason, /No associated email/i);
});

test('executeMigration in dry-run mode inspects documents and plans updates without mutating database', async () => {
  // Mock Firestore data
  const projectDocs = [
    {
      id: 'p1',
      data: () => ({ ownerId: 'fb-user-1', name: 'Alpha' }),
      ref: {
        id: 'p1',
        collection: (sub: string) => ({
          get: async () => ({
            size: sub === 'files' ? 2 : 1,
            docs:
              sub === 'files'
                ? [
                    { id: 'f1', data: () => ({ ownerId: 'fb-user-1', path: 'src/App.tsx' }), ref: { id: 'f1' } },
                    { id: 'f2', data: () => ({ ownerId: 'fb-user-1', path: 'package.json' }), ref: { id: 'f2' } },
                  ]
                : [{ id: 'm1', data: () => ({ ownerId: 'fb-user-1', text: 'hello' }), ref: { id: 'm1' } }],
          }),
        }),
      },
    },
    {
      id: 'p2',
      data: () => ({ ownerId: 'user_already_migrated', name: 'Beta' }),
      ref: {
        id: 'p2',
        collection: () => ({ get: async () => ({ size: 0, docs: [] }) }),
      },
    },
  ];

  const deploymentDocs = [
    {
      id: 'd1',
      data: () => ({ ownerId: 'fb-user-1', slug: 'my-site' }),
      ref: { id: 'd1' },
    },
  ];

  const committedBatches: any[] = [];

  const mockDb = {
    collection: (name: string) => ({
      get: async () => {
        if (name === 'projects') return { size: projectDocs.length, docs: projectDocs };
        if (name === 'deployments') return { size: deploymentDocs.length, docs: deploymentDocs };
        if (name === 'user_preferences') {
          return {
            size: 1,
            docs: [{ id: 'fb-user-1', data: () => ({ theme: 'dark' }), ref: { id: 'fb-user-1' } }],
          };
        }
        if (name === 'vault') {
          return {
            size: 1,
            docs: [{ id: 'fb-user-1', data: () => ({ encryptedVault: 'secret' }), ref: { id: 'fb-user-1' } }],
          };
        }
        return { size: 0, docs: [] };
      },
      doc: (id: string) => ({ id, isDocRef: true }),
    }),
    batch: () => {
      const ops: any[] = [];
      return {
        update: (ref: any, data: any) => ops.push({ type: 'update', ref, data }),
        set: (ref: any, data: any, opts: any) => ops.push({ type: 'set', ref, data, opts }),
        commit: async () => {
          committedBatches.push(ops);
        },
      };
    },
  } as any;

  const mockClerkUsers: ClerkUserRecord[] = [
    {
      id: 'user_clerk_1',
      emailAddresses: [{ emailAddress: 'user1@example.com', verification: { status: 'verified' } }],
    },
  ];

  const mockFirebaseUsers: FirebaseUserRecord[] = [
    { uid: 'fb-user-1', email: 'user1@example.com', emailVerified: true },
  ];

  // 1. DRY RUN
  const dryReport = await executeMigration({
    dryRun: true,
    firestore: mockDb,
    mockClerkUsers,
    mockFirebaseUsers,
  });

  assert.equal(dryReport.dryRun, true);
  assert.equal(dryReport.applied, false);
  assert.equal(dryReport.inspectedCounts.projects, 2);
  assert.equal(dryReport.inspectedCounts.deployments, 1);
  assert.equal(dryReport.inspectedCounts.projectFiles, 2);
  assert.equal(dryReport.inspectedCounts.projectMessages, 1);
  assert.equal(dryReport.mappedIdentities.length, 1);
  assert.equal(dryReport.mappedIdentities[0]!.newClerkId, 'user_clerk_1');
  assert.equal(dryReport.alreadyClerkIdentities.length, 1);
  assert.equal(dryReport.documentsUpdated, 0, 'No documents should be updated in dry-run mode');
  assert.equal(committedBatches.length, 0, 'No batches should be committed in dry-run mode');

  // Verify formatted report contains dry run warnings
  const reportOutput = formatReport(dryReport);
  assert.match(reportOutput, /DRY RUN/);
  assert.match(reportOutput, /Zero database writes executed/);

  // 2. APPLY MODE
  const applyReport = await executeMigration({
    apply: true,
    dryRun: false,
    firestore: mockDb,
    mockClerkUsers,
    mockFirebaseUsers,
  });

  assert.equal(applyReport.dryRun, false);
  assert.equal(applyReport.applied, true);
  assert.equal(applyReport.documentsUpdated, applyReport.documentsToUpdate);
  assert.equal(applyReport.batchesCommitted, 1);
  assert.equal(committedBatches.length, 1);

  // Operations planned:
  // 1 project update + 2 file updates + 1 message update + 1 deployment update + 1 user_pref set + 1 vault set = 7
  assert.equal(applyReport.documentsUpdated, 7);
  const committedOps = committedBatches[0];
  assert.equal(committedOps.length, 7);

  // Check audit metadata is attached
  for (const op of committedOps) {
    assert.equal(op.data.migratedFromUid, 'fb-user-1');
  }
});

test('executeRollback in dry-run and apply modes inspects and reverts migrated records cleanly', async () => {
  const committedBatches: any[] = [];

  const migratedProjectDocs = [
    {
      id: 'p1',
      data: () => ({
        ownerId: 'user_clerk_1',
        migratedFromUid: 'fb-user-1',
        migratedAt: '2026-11-23T00:00:00.000Z',
      }),
      ref: {
        id: 'p1',
        collection: (sub: string) => ({
          get: async () => ({
            size: sub === 'files' ? 2 : 1,
            docs:
              sub === 'files'
                ? [
                    {
                      id: 'f1',
                      data: () => ({
                        ownerId: 'user_clerk_1',
                        migratedFromUid: 'fb-user-1',
                      }),
                      ref: { id: 'f1' },
                    },
                    {
                      id: 'f2',
                      data: () => ({
                        ownerId: 'user_clerk_1',
                        migratedFromUid: 'fb-user-1',
                      }),
                      ref: { id: 'f2' },
                    },
                  ]
                : [
                    {
                      id: 'm1',
                      data: () => ({
                        ownerId: 'user_clerk_1',
                        migratedFromUid: 'fb-user-1',
                      }),
                      ref: { id: 'm1' },
                    },
                  ],
          }),
        }),
      },
    },
    {
      id: 'p2',
      data: () => ({ ownerId: 'user_clerk_2' }), // Unmigrated project
      ref: {
        id: 'p2',
        collection: () => ({ get: async () => ({ size: 0, docs: [] }) }),
      },
    },
  ];

  const migratedDeploymentDocs = [
    {
      id: 'd1',
      data: () => ({
        ownerId: 'user_clerk_1',
        migratedFromUid: 'fb-user-1',
      }),
      ref: { id: 'd1' },
    },
  ];

  const migratedPrefsDocs = [
    {
      id: 'user_clerk_1',
      data: () => ({
        uid: 'user_clerk_1',
        migratedFromUid: 'fb-user-1',
      }),
      ref: { id: 'user_clerk_1' },
    },
  ];

  const migratedVaultDocs = [
    {
      id: 'user_clerk_1',
      data: () => ({
        ownerId: 'user_clerk_1',
        migratedFromUid: 'fb-user-1',
      }),
      ref: { id: 'user_clerk_1' },
    },
  ];

  const mockDb = {
    collection: (name: string) => ({
      get: async () => {
        if (name === 'projects') return { size: migratedProjectDocs.length, docs: migratedProjectDocs };
        if (name === 'deployments') return { size: migratedDeploymentDocs.length, docs: migratedDeploymentDocs };
        if (name === 'user_preferences') return { size: migratedPrefsDocs.length, docs: migratedPrefsDocs };
        if (name === 'vault') return { size: migratedVaultDocs.length, docs: migratedVaultDocs };
        return { size: 0, docs: [] };
      },
      doc: (id: string) => ({ id, isDocRef: true }),
    }),
    batch: () => {
      const ops: any[] = [];
      return {
        update: (ref: any, data: any) => ops.push({ type: 'update', ref, data }),
        delete: (ref: any) => ops.push({ type: 'delete', ref }),
        commit: async () => {
          committedBatches.push(ops);
        },
      };
    },
  } as any;

  // 1. DRY RUN
  const dryReport = await executeRollback({
    dryRun: true,
    firestore: mockDb,
  });

  assert.equal(dryReport.dryRun, true);
  assert.equal(dryReport.applied, false);
  assert.equal(dryReport.revertedCounts.projects, 1);
  assert.equal(dryReport.revertedCounts.projectFiles, 2);
  assert.equal(dryReport.revertedCounts.projectMessages, 1);
  assert.equal(dryReport.revertedCounts.deployments, 1);
  assert.equal(dryReport.revertedCounts.userPreferences, 1);
  assert.equal(dryReport.revertedCounts.vaults, 1);
  assert.equal(dryReport.documentsToRevert, 7);
  assert.equal(dryReport.documentsReverted, 0, 'No documents should be modified in dry-run mode');
  assert.equal(committedBatches.length, 0, 'No batches committed in dry run');

  const formattedDry = formatRollbackReport(dryReport);
  assert.match(formattedDry, /DRY RUN/);
  assert.match(formattedDry, /Zero database writes executed/);

  // 2. APPLY MODE
  const applyReport = await executeRollback({
    apply: true,
    dryRun: false,
    firestore: mockDb,
  });

  assert.equal(applyReport.dryRun, false);
  assert.equal(applyReport.applied, true);
  assert.equal(applyReport.documentsToRevert, 7);
  assert.equal(applyReport.documentsReverted, 7);
  assert.equal(applyReport.batchesCommitted, 1);
  assert.equal(committedBatches.length, 1);

  const ops = committedBatches[0];
  assert.equal(ops.length, 7);

  // Verify updates restored old Firebase UID
  const updateOps = ops.filter((o: any) => o.type === 'update');
  assert.equal(updateOps.length, 5); // 1 project + 2 files + 1 msg + 1 deployment
  for (const op of updateOps) {
    assert.equal(op.data.ownerId, 'fb-user-1');
  }

  // Verify cloned clerk docs were deleted (clean reversal)
  const deleteOps = ops.filter((o: any) => o.type === 'delete');
  assert.equal(deleteOps.length, 2); // 1 pref + 1 vault
  assert.equal(deleteOps[0].ref.id, 'user_clerk_1');
  assert.equal(deleteOps[1].ref.id, 'user_clerk_1');

  const formattedApply = formatRollbackReport(applyReport);
  assert.match(formattedApply, /APPLY COMPLETE/);
  assert.match(formattedApply, /7 documents reverted in 1 batches/);
});
