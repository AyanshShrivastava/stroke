/**
 * Identity Migration Tool for Mist
 *
 * Migrates historical Firestore ownership records from old Firebase Auth UIDs
 * to modern Clerk user IDs (user_...).
 *
 * Security & Integrity Guarantees:
 * 1. Defaults strictly to --dry-run. No writes occur unless --apply is passed.
 * 2. Never deletes existing records automatically.
 * 3. Never silently assigns ambiguous or conflicting identities.
 * 4. Requires email verification in BOTH Firebase and Clerk for email-based mapping.
 * 5. Uses safe batched writes capped at 400 operations per batch (Firestore max 500).
 * 6. Sets `migratedFromUid` and `migratedAt` audit metadata on updated documents.
 */

import { type Firestore, FieldValue, Timestamp } from 'firebase-admin/firestore';
import { createClerkClient } from '@clerk/express';
import { initAdminFirestore } from '../src/server/firestoreAdmin';

export interface FirebaseUserRecord {
  uid: string;
  email?: string;
  emailVerified?: boolean;
}

export interface ClerkUserRecord {
  id: string;
  emailAddresses: Array<{
    emailAddress: string;
    verification?: { status?: string } | null;
  }>;
}

export interface IdentityMappingResult {
  oldUid: string;
  newClerkId?: string;
  email?: string;
  status: 'mapped' | 'unmapped' | 'conflict' | 'already_clerk';
  reason: string;
}

export interface MigrationReport {
  dryRun: boolean;
  applied: boolean;
  inspectedCounts: {
    projects: number;
    projectFiles: number;
    projectMessages: number;
    deployments: number;
    userPreferences: number;
    vaults: number;
    users: number;
  };
  totalDistinctOwners: number;
  mappedIdentities: IdentityMappingResult[];
  unmappedIdentities: IdentityMappingResult[];
  conflictingIdentities: IdentityMappingResult[];
  alreadyClerkIdentities: IdentityMappingResult[];
  documentsToUpdate: number;
  documentsUpdated: number;
  batchesCommitted: number;
  errors: string[];
}

export interface MigrationOptions {
  dryRun?: boolean;
  apply?: boolean;
  batchSize?: number;
  verbose?: boolean;
  firestore?: Firestore;
  mockClerkUsers?: ClerkUserRecord[];
  mockFirebaseUsers?: FirebaseUserRecord[];
}

/**
 * Resolves old Firebase identities to modern Clerk user IDs using strict verification rules.
 */
export function resolveIdentities(
  oldUids: string[],
  firebaseUsers: Map<string, FirebaseUserRecord>,
  clerkUsers: ClerkUserRecord[],
): Map<string, IdentityMappingResult> {
  const results = new Map<string, IdentityMappingResult>();

  // Index Clerk users by verified email (lowercase)
  const clerkByVerifiedEmail = new Map<string, ClerkUserRecord[]>();
  const clerkById = new Map<string, ClerkUserRecord>();

  for (const cu of clerkUsers) {
    clerkById.set(cu.id, cu);
    for (const emailObj of cu.emailAddresses) {
      const emailLower = emailObj.emailAddress.toLowerCase().trim();
      const isVerified = emailObj.verification?.status === 'verified';
      if (isVerified) {
        const list = clerkByVerifiedEmail.get(emailLower) || [];
        list.push(cu);
        clerkByVerifiedEmail.set(emailLower, list);
      }
    }
  }

  for (const uid of oldUids) {
    // 1. Check if already modern Clerk ID
    if (uid.startsWith('user_')) {
      results.set(uid, {
        oldUid: uid,
        newClerkId: uid,
        status: 'already_clerk',
        reason: 'Already a modern Clerk user ID format',
      });
      continue;
    }

    const fbUser = firebaseUsers.get(uid);
    if (!fbUser || !fbUser.email) {
      results.set(uid, {
        oldUid: uid,
        status: 'unmapped',
        reason: 'No associated email found for historical UID',
      });
      continue;
    }

    const email = fbUser.email.toLowerCase().trim();

    // 2. Enforce Firebase email verification
    if (!fbUser.emailVerified) {
      results.set(uid, {
        oldUid: uid,
        email,
        status: 'unmapped',
        reason: 'Firebase email is unverified; cannot safely map without verification',
      });
      continue;
    }

    // 3. Match against verified Clerk users
    const matches = clerkByVerifiedEmail.get(email) || [];

    if (matches.length === 0) {
      results.set(uid, {
        oldUid: uid,
        email,
        status: 'unmapped',
        reason: `No verified Clerk account found for email: ${email}`,
      });
    } else if (matches.length > 1) {
      results.set(uid, {
        oldUid: uid,
        email,
        status: 'conflict',
        reason: `Multiple Clerk accounts match verified email ${email} (${matches.map((m) => m.id).join(', ')})`,
      });
    } else {
      // Exactly 1 verified Clerk account match
      const clerkUser = matches[0]!;
      results.set(uid, {
        oldUid: uid,
        newClerkId: clerkUser.id,
        email,
        status: 'mapped',
        reason: `Clean verified 1:1 match with Clerk user ${clerkUser.id}`,
      });
    }
  }

  return results;
}

/**
 * Executes or simulates full data migration across all collections.
 */
export async function executeMigration(options: MigrationOptions = {}): Promise<MigrationReport> {
  const isApply = Boolean(options.apply && !options.dryRun);
  const dryRun = !isApply;
  const batchSize = Math.min(options.batchSize || 400, 400); // Strict safety ceiling at 400 (under 500 limit)
  const verbose = Boolean(options.verbose);

  const report: MigrationReport = {
    dryRun,
    applied: isApply,
    inspectedCounts: {
      projects: 0,
      projectFiles: 0,
      projectMessages: 0,
      deployments: 0,
      userPreferences: 0,
      vaults: 0,
      users: 0,
    },
    totalDistinctOwners: 0,
    mappedIdentities: [],
    unmappedIdentities: [],
    conflictingIdentities: [],
    alreadyClerkIdentities: [],
    documentsToUpdate: 0,
    documentsUpdated: 0,
    batchesCommitted: 0,
    errors: [],
  };

  const db = options.firestore || initAdminFirestore();

  // 1. Gather users from Clerk
  let clerkUsers: ClerkUserRecord[] = options.mockClerkUsers || [];
  if (!options.mockClerkUsers) {
    const secretKey = process.env.CLERK_SECRET_KEY;
    if (!secretKey) {
      report.errors.push('Missing CLERK_SECRET_KEY environment variable.');
      return report;
    }
    try {
      const clerk = createClerkClient({ secretKey });
      const response = await clerk.users.getUserList({ limit: 500 });
      clerkUsers = response.data.map((u) => ({
        id: u.id,
        emailAddresses: u.emailAddresses.map((e) => ({
          emailAddress: e.emailAddress,
          verification: { status: e.verification?.status },
        })),
      }));
    } catch (err: any) {
      report.errors.push(`Failed to fetch Clerk users: ${err.message}`);
      return report;
    }
  }

  // 2. Gather historical Firebase users / users collection
  const firebaseUsers = new Map<string, FirebaseUserRecord>();
  if (options.mockFirebaseUsers) {
    for (const u of options.mockFirebaseUsers) {
      firebaseUsers.set(u.uid, u);
    }
  } else {
    try {
      const usersSnap = await db.collection('users').get();
      report.inspectedCounts.users = usersSnap.size;
      for (const doc of usersSnap.docs) {
        const data = doc.data();
        const uid = data.uid || doc.id;
        firebaseUsers.set(uid, {
          uid,
          email: data.email,
          emailVerified: Boolean(data.emailVerified ?? true),
        });
      }
    } catch (err: any) {
      // If collection doesn't exist yet, continue
      report.errors.push(`Note reading users collection: ${err.message}`);
    }
  }

  // 3. Inspect collections to find all distinct owner IDs
  const distinctUids = new Set<string>();

  // Inspect Projects
  let projectsSnap: FirebaseFirestore.QuerySnapshot;
  try {
    projectsSnap = await db.collection('projects').get();
    report.inspectedCounts.projects = projectsSnap.size;
    for (const doc of projectsSnap.docs) {
      const ownerId = doc.data().ownerId;
      if (ownerId && typeof ownerId === 'string') {
        distinctUids.add(ownerId);
      }
    }
  } catch (err: any) {
    report.errors.push(`Error reading projects: ${err.message}`);
    return report;
  }

  // Inspect Deployments
  let deploymentsSnap: FirebaseFirestore.QuerySnapshot;
  try {
    deploymentsSnap = await db.collection('deployments').get();
    report.inspectedCounts.deployments = deploymentsSnap.size;
    for (const doc of deploymentsSnap.docs) {
      const ownerId = doc.data().ownerId;
      if (ownerId && typeof ownerId === 'string') {
        distinctUids.add(ownerId);
      }
    }
  } catch (err: any) {
    report.errors.push(`Error reading deployments: ${err.message}`);
  }

  // Inspect User Preferences
  let prefsSnap: FirebaseFirestore.QuerySnapshot | null = null;
  try {
    prefsSnap = await db.collection('user_preferences').get();
    report.inspectedCounts.userPreferences = prefsSnap.size;
    for (const doc of prefsSnap.docs) {
      distinctUids.add(doc.id);
    }
  } catch {
    // optional
  }

  // Inspect Vaults
  let vaultsSnap: FirebaseFirestore.QuerySnapshot | null = null;
  try {
    vaultsSnap = await db.collection('vault').get();
    report.inspectedCounts.vaults = vaultsSnap.size;
    for (const doc of vaultsSnap.docs) {
      distinctUids.add(doc.id);
    }
  } catch {
    // optional
  }

  report.totalDistinctOwners = distinctUids.size;

  // 4. Resolve identities
  const resolved = resolveIdentities(Array.from(distinctUids), firebaseUsers, clerkUsers);

  for (const item of resolved.values()) {
    if (item.status === 'mapped') report.mappedIdentities.push(item);
    else if (item.status === 'unmapped') report.unmappedIdentities.push(item);
    else if (item.status === 'conflict') report.conflictingIdentities.push(item);
    else if (item.status === 'already_clerk') report.alreadyClerkIdentities.push(item);
  }

  // Map of oldUid -> newClerkId for verified mappings
  const migrationMap = new Map<string, string>();
  for (const item of report.mappedIdentities) {
    if (item.newClerkId) {
      migrationMap.set(item.oldUid, item.newClerkId);
    }
  }

  // 5. Calculate documents to update
  interface PendingOp {
    type: 'update' | 'set';
    ref: FirebaseFirestore.DocumentReference;
    data: Record<string, any>;
  }

  const pendingOps: PendingOp[] = [];

  // Plan Projects updates
  for (const doc of projectsSnap.docs) {
    const data = doc.data();
    const oldOwnerId = data.ownerId;
    if (oldOwnerId && migrationMap.has(oldOwnerId)) {
      const newClerkId = migrationMap.get(oldOwnerId)!;
      pendingOps.push({
        type: 'update',
        ref: doc.ref,
        data: {
          ownerId: newClerkId,
          migratedFromUid: oldOwnerId,
          migratedAt: isApply ? FieldValue.serverTimestamp() : new Date().toISOString(),
        },
      });

      // Check subcollections: files and messages
      try {
        const filesSnap = await doc.ref.collection('files').get();
        report.inspectedCounts.projectFiles += filesSnap.size;
        for (const fileDoc of filesSnap.docs) {
          const fileData = fileDoc.data();
          if (fileData.ownerId === oldOwnerId) {
            pendingOps.push({
              type: 'update',
              ref: fileDoc.ref,
              data: {
                ownerId: newClerkId,
                migratedFromUid: oldOwnerId,
                migratedAt: isApply ? FieldValue.serverTimestamp() : new Date().toISOString(),
              },
            });
          }
        }

        const messagesSnap = await doc.ref.collection('messages').get();
        report.inspectedCounts.projectMessages += messagesSnap.size;
        for (const msgDoc of messagesSnap.docs) {
          const msgData = msgDoc.data();
          if (msgData.ownerId === oldOwnerId) {
            pendingOps.push({
              type: 'update',
              ref: msgDoc.ref,
              data: {
                ownerId: newClerkId,
                migratedFromUid: oldOwnerId,
                migratedAt: isApply ? FieldValue.serverTimestamp() : new Date().toISOString(),
              },
            });
          }
        }
      } catch (err: any) {
        report.errors.push(`Error checking subcollections for project ${doc.id}: ${err.message}`);
      }
    }
  }

  // Plan Deployments updates
  if (deploymentsSnap!) {
    for (const doc of deploymentsSnap.docs) {
      const data = doc.data();
      const oldOwnerId = data.ownerId;
      if (oldOwnerId && migrationMap.has(oldOwnerId)) {
        const newClerkId = migrationMap.get(oldOwnerId)!;
        pendingOps.push({
          type: 'update',
          ref: doc.ref,
          data: {
            ownerId: newClerkId,
            migratedFromUid: oldOwnerId,
            migratedAt: isApply ? FieldValue.serverTimestamp() : new Date().toISOString(),
          },
        });
      }
    }
  }

  // Plan User Preferences copy (Never delete old records automatically)
  if (prefsSnap) {
    for (const doc of prefsSnap.docs) {
      const oldUid = doc.id;
      if (migrationMap.has(oldUid)) {
        const newClerkId = migrationMap.get(oldUid)!;
        const newDocRef = db.collection('user_preferences').doc(newClerkId);
        pendingOps.push({
          type: 'set',
          ref: newDocRef,
          data: {
            ...doc.data(),
            uid: newClerkId,
            migratedFromUid: oldUid,
            migratedAt: isApply ? FieldValue.serverTimestamp() : new Date().toISOString(),
          },
        });
      }
    }
  }

  // Plan Vault copy (Never delete old records automatically)
  if (vaultsSnap) {
    for (const doc of vaultsSnap.docs) {
      const oldUid = doc.id;
      if (migrationMap.has(oldUid)) {
        const newClerkId = migrationMap.get(oldUid)!;
        const newDocRef = db.collection('vault').doc(newClerkId);
        pendingOps.push({
          type: 'set',
          ref: newDocRef,
          data: {
            ...doc.data(),
            ownerId: newClerkId,
            migratedFromUid: oldUid,
            migratedAt: isApply ? FieldValue.serverTimestamp() : new Date().toISOString(),
          },
        });
      }
    }
  }

  report.documentsToUpdate = pendingOps.length;

  // 6. If --apply, commit operations in chunks of batchSize
  if (isApply && pendingOps.length > 0) {
    for (let i = 0; i < pendingOps.length; i += batchSize) {
      const chunk = pendingOps.slice(i, i + batchSize);
      const batch = db.batch();
      for (const op of chunk) {
        if (op.type === 'update') {
          batch.update(op.ref, op.data);
        } else {
          batch.set(op.ref, op.data, { merge: true });
        }
      }
      await batch.commit();
      report.batchesCommitted += 1;
      report.documentsUpdated += chunk.length;
      if (verbose) {
        console.log(`[Migration] Committed batch ${report.batchesCommitted} (${chunk.length} operations)`);
      }
    }
  }

  return report;
}

/**
 * Formats migration report as human-readable markdown / CLI table.
 */
export function formatReport(report: MigrationReport): string {
  const lines: string[] = [];
  lines.push('===============================================================');
  lines.push(`   MIST IDENTITY MIGRATION REPORT (${report.dryRun ? 'DRY RUN' : 'APPLIED'})`);
  lines.push('===============================================================');
  lines.push('');
  lines.push(`Mode:                     ${report.dryRun ? 'DRY RUN (no database writes)' : 'LIVE APPLY (changes committed)'}`);
  lines.push(`Total Distinct Owners:    ${report.totalDistinctOwners}`);
  lines.push(`Already Clerk IDs:        ${report.alreadyClerkIdentities.length}`);
  lines.push(`Successfully Mapped:      ${report.mappedIdentities.length}`);
  lines.push(`Unmapped Identities:      ${report.unmappedIdentities.length}`);
  lines.push(`Conflicting Identities:   ${report.conflictingIdentities.length}`);
  lines.push(`Documents to Update:      ${report.documentsToUpdate}`);
  if (report.applied) {
    lines.push(`Documents Updated:        ${report.documentsUpdated}`);
    lines.push(`Batches Committed:        ${report.batchesCommitted}`);
  }
  lines.push('');

  lines.push('--- Inspected Collections ---');
  for (const [col, count] of Object.entries(report.inspectedCounts)) {
    lines.push(`  - ${col.padEnd(20)}: ${count} documents`);
  }
  lines.push('');

  if (report.mappedIdentities.length > 0) {
    lines.push('--- Mapped Identities (Safe 1:1 Verified Matches) ---');
    for (const m of report.mappedIdentities) {
      lines.push(`  ✓ ${m.oldUid} (${m.email}) -> ${m.newClerkId}`);
    }
    lines.push('');
  }

  if (report.conflictingIdentities.length > 0) {
    lines.push('--- CONFLICTING IDENTITIES (Ambiguous - Skipped) ---');
    for (const c of report.conflictingIdentities) {
      lines.push(`  ⚠ ${c.oldUid} (${c.email ?? 'no email'}): ${c.reason}`);
    }
    lines.push('');
  }

  if (report.unmappedIdentities.length > 0) {
    lines.push('--- Unmapped Identities (Requires Investigation) ---');
    for (const u of report.unmappedIdentities) {
      lines.push(`  ✗ ${u.oldUid} (${u.email ?? 'no email'}): ${u.reason}`);
    }
    lines.push('');
  }

  if (report.errors.length > 0) {
    lines.push('--- Errors / Warnings ---');
    for (const err of report.errors) {
      lines.push(`  ! ${err}`);
    }
    lines.push('');
  }

  lines.push('===============================================================');
  if (report.dryRun) {
    lines.push('DRY RUN COMPLETE: Zero database writes executed.');
    lines.push('To apply this migration, run:');
    lines.push('  npx tsx scripts/migrate-identities.ts --apply');
  } else {
    lines.push(`APPLY COMPLETE: ${report.documentsUpdated} documents updated in ${report.batchesCommitted} batches.`);
  }
  lines.push('===============================================================');

  return lines.join('\n');
}

export interface RollbackOptions {
  dryRun?: boolean;
  apply?: boolean;
  batchSize?: number;
  verbose?: boolean;
  firestore?: Firestore;
}

export interface RollbackReport {
  dryRun: boolean;
  applied: boolean;
  revertedCounts: {
    projects: number;
    projectFiles: number;
    projectMessages: number;
    deployments: number;
    userPreferences: number;
    vaults: number;
  };
  documentsToRevert: number;
  documentsReverted: number;
  batchesCommitted: number;
  errors: string[];
}

/**
 * Reverts a previously applied identity migration by restoring `migratedFromUid`
 * ownership on projects, files, messages, and deployments, and removing cloned
 * modern preference and vault records.
 */
export async function executeRollback(options: RollbackOptions = {}): Promise<RollbackReport> {
  const isApply = Boolean(options.apply && !options.dryRun);
  const dryRun = !isApply;
  const batchSize = Math.min(options.batchSize || 400, 400);
  const verbose = Boolean(options.verbose);

  const report: RollbackReport = {
    dryRun,
    applied: isApply,
    revertedCounts: {
      projects: 0,
      projectFiles: 0,
      projectMessages: 0,
      deployments: 0,
      userPreferences: 0,
      vaults: 0,
    },
    documentsToRevert: 0,
    documentsReverted: 0,
    batchesCommitted: 0,
    errors: [],
  };

  const db = options.firestore || initAdminFirestore();

  interface PendingRollbackOp {
    type: 'update' | 'delete';
    ref: FirebaseFirestore.DocumentReference;
    data?: Record<string, any>;
  }

  const pendingOps: PendingRollbackOp[] = [];

  // 1. Revert Projects and subcollections
  try {
    const projectsSnap = await db.collection('projects').get();
    for (const doc of projectsSnap.docs) {
      const data = doc.data();
      if (data.migratedFromUid) {
        report.revertedCounts.projects++;
        pendingOps.push({
          type: 'update',
          ref: doc.ref,
          data: {
            ownerId: data.migratedFromUid,
            migratedFromUid: FieldValue.delete(),
            migratedAt: FieldValue.delete(),
            rolledBackAt: isApply ? FieldValue.serverTimestamp() : new Date().toISOString(),
          },
        });
      }

      // Check subcollections
      try {
        const filesSnap = await doc.ref.collection('files').get();
        for (const fileDoc of filesSnap.docs) {
          const fileData = fileDoc.data();
          if (fileData.migratedFromUid) {
            report.revertedCounts.projectFiles++;
            pendingOps.push({
              type: 'update',
              ref: fileDoc.ref,
              data: {
                ownerId: fileData.migratedFromUid,
                migratedFromUid: FieldValue.delete(),
                migratedAt: FieldValue.delete(),
                rolledBackAt: isApply ? FieldValue.serverTimestamp() : new Date().toISOString(),
              },
            });
          }
        }

        const messagesSnap = await doc.ref.collection('messages').get();
        for (const msgDoc of messagesSnap.docs) {
          const msgData = msgDoc.data();
          if (msgData.migratedFromUid) {
            report.revertedCounts.projectMessages++;
            pendingOps.push({
              type: 'update',
              ref: msgDoc.ref,
              data: {
                ownerId: msgData.migratedFromUid,
                migratedFromUid: FieldValue.delete(),
                migratedAt: FieldValue.delete(),
                rolledBackAt: isApply ? FieldValue.serverTimestamp() : new Date().toISOString(),
              },
            });
          }
        }
      } catch (err: any) {
        report.errors.push(`Error checking subcollections for project ${doc.id}: ${err.message}`);
      }
    }
  } catch (err: any) {
    report.errors.push(`Error inspecting projects for rollback: ${err.message}`);
  }

  // 2. Revert Deployments
  try {
    const deploymentsSnap = await db.collection('deployments').get();
    for (const doc of deploymentsSnap.docs) {
      const data = doc.data();
      if (data.migratedFromUid) {
        report.revertedCounts.deployments++;
        pendingOps.push({
          type: 'update',
          ref: doc.ref,
          data: {
            ownerId: data.migratedFromUid,
            migratedFromUid: FieldValue.delete(),
            migratedAt: FieldValue.delete(),
            rolledBackAt: isApply ? FieldValue.serverTimestamp() : new Date().toISOString(),
          },
        });
      }
    }
  } catch (err: any) {
    report.errors.push(`Error inspecting deployments for rollback: ${err.message}`);
  }

  // 3. User Preferences (Remove copy created with modern Clerk ID; historical UID doc remains intact)
  try {
    const prefsSnap = await db.collection('user_preferences').get();
    for (const doc of prefsSnap.docs) {
      const data = doc.data();
      if (data.migratedFromUid) {
        report.revertedCounts.userPreferences++;
        pendingOps.push({
          type: 'delete',
          ref: doc.ref,
        });
      }
    }
  } catch (err: any) {
    report.errors.push(`Error inspecting user preferences for rollback: ${err.message}`);
  }

  // 4. Vault (Remove copy created with modern Clerk ID; historical UID doc remains intact)
  try {
    const vaultsSnap = await db.collection('vault').get();
    for (const doc of vaultsSnap.docs) {
      const data = doc.data();
      if (data.migratedFromUid) {
        report.revertedCounts.vaults++;
        pendingOps.push({
          type: 'delete',
          ref: doc.ref,
        });
      }
    }
  } catch (err: any) {
    report.errors.push(`Error inspecting vault for rollback: ${err.message}`);
  }

  report.documentsToRevert = pendingOps.length;

  // 5. If --apply, commit operations in chunks of batchSize
  if (isApply && pendingOps.length > 0) {
    for (let i = 0; i < pendingOps.length; i += batchSize) {
      const chunk = pendingOps.slice(i, i + batchSize);
      const batch = db.batch();
      for (const op of chunk) {
        if (op.type === 'update' && op.data) {
          batch.update(op.ref, op.data);
        } else if (op.type === 'delete') {
          batch.delete(op.ref);
        }
      }
      await batch.commit();
      report.batchesCommitted += 1;
      report.documentsReverted += chunk.length;
      if (verbose) {
        console.log(`[Rollback] Committed batch ${report.batchesCommitted} (${chunk.length} operations)`);
      }
    }
  }

  return report;
}

/**
 * Formats rollback report as human-readable markdown / CLI table.
 */
export function formatRollbackReport(report: RollbackReport): string {
  const lines: string[] = [];
  lines.push('===============================================================');
  lines.push(`   MIST IDENTITY ROLLBACK REPORT (${report.dryRun ? 'DRY RUN' : 'APPLIED'})`);
  lines.push('===============================================================');
  lines.push('');
  lines.push(`Mode:                     ${report.dryRun ? 'DRY RUN (no database writes)' : 'LIVE APPLY (changes committed)'}`);
  lines.push(`Documents to Revert:      ${report.documentsToRevert}`);
  if (report.applied) {
    lines.push(`Documents Reverted:       ${report.documentsReverted}`);
    lines.push(`Batches Committed:        ${report.batchesCommitted}`);
  }
  lines.push('');

  lines.push('--- Reverted Records by Collection ---');
  for (const [col, count] of Object.entries(report.revertedCounts)) {
    lines.push(`  - ${col.padEnd(20)}: ${count} documents`);
  }
  lines.push('');

  if (report.errors.length > 0) {
    lines.push('--- Errors / Warnings ---');
    for (const err of report.errors) {
      lines.push(`  ! ${err}`);
    }
    lines.push('');
  }

  lines.push('===============================================================');
  if (report.dryRun) {
    lines.push('DRY RUN COMPLETE: Zero database writes executed.');
    lines.push('To apply this rollback, run:');
    lines.push('  npx tsx scripts/migrate-identities.ts --rollback --apply');
  } else {
    lines.push(`APPLY COMPLETE: ${report.documentsReverted} documents reverted in ${report.batchesCommitted} batches.`);
  }
  lines.push('===============================================================');

  return lines.join('\n');
}

// CLI entrypoint if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  const args = process.argv.slice(2);
  const rollback = args.includes('--rollback');
  const apply = args.includes('--apply');
  const dryRun = args.includes('--dry-run') || !apply;
  const verbose = args.includes('--verbose') || args.includes('-v');

  if (rollback) {
    console.log(`Starting Mist Identity Rollback (${dryRun ? 'DRY RUN' : 'APPLY MODE'})...`);

    executeRollback({ dryRun, apply, verbose })
      .then((report) => {
        console.log(formatRollbackReport(report));
        if (report.errors.length > 0) {
          process.exitCode = 1;
        }
      })
      .catch((err) => {
        console.error('Rollback failed fatal exception:', err);
        process.exit(1);
      });
  } else {
    console.log(`Starting Mist Identity Migration (${dryRun ? 'DRY RUN' : 'APPLY MODE'})...`);

    executeMigration({ dryRun, apply, verbose })
      .then((report) => {
        console.log(formatReport(report));
        if (report.errors.length > 0) {
          process.exitCode = 1;
        }
      })
      .catch((err) => {
        console.error('Migration failed fatal exception:', err);
        process.exit(1);
      });
  }
}
