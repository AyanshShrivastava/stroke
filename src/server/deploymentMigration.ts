/**
 * Deployment Migration Tool: Firestore to Cloudflare R2
 *
 * Migrates historical deployment HTML bundles stored directly in Firestore
 * into Cloudflare R2 storage, preserving document metadata and ownership.
 *
 * Guarantees:
 * 1. Safe default: Defaults to --dry-run. Writes only happen when --apply is passed.
 * 2. Preserves existing metadata: slug, ownerId, projectId, title, createdAt, updatedAt.
 * 3. Verifies R2 persistence: Only cleans up Firestore htmlBundle after R2 upload is verified.
 * 4. Safe rollback: Never deletes documents.
 */

import { FieldValue, type Firestore } from 'firebase-admin/firestore';
import { FirestoreAdminStore, type AdminDatabaseOperations, initAdminFirestore } from './firestoreAdmin';
import {
  CloudflareR2ArtifactStore,
  type R2StorageOperations,
} from '../utils/r2ArtifactStore';

export interface DeploymentMigrationItem {
  slug: string;
  ownerId: string;
  title: string;
  hasHtmlBundle: boolean;
  alreadyInR2: boolean;
  status: 'migrated' | 'already_migrated' | 'skipped' | 'failed';
  bytes?: number;
  error?: string;
}

export interface DeploymentMigrationReport {
  dryRun: boolean;
  applied: boolean;
  totalFound: number;
  migratedCount: number;
  alreadyMigratedCount: number;
  failedCount: number;
  items: DeploymentMigrationItem[];
  startedAt: string;
  completedAt: string;
}

export interface DeploymentMigrationOptions {
  dryRun?: boolean;
  apply?: boolean;
  adminStore?: AdminDatabaseOperations;
  r2Store?: R2StorageOperations;
  firestore?: Firestore;
  batchSize?: number;
  verbose?: boolean;
}

export async function migrateDeploymentsToR2(
  options: DeploymentMigrationOptions = {},
): Promise<DeploymentMigrationReport> {
  const startedAt = new Date().toISOString();
  const apply = Boolean(options.apply && !options.dryRun);
  const dryRun = !apply;
  const verbose = Boolean(options.verbose);

  // 1. Resolve R2 store
  let r2: R2StorageOperations;
  if (options.r2Store) {
    r2 = options.r2Store;
  } else {
    r2 = new CloudflareR2ArtifactStore();
  }

  const items: DeploymentMigrationItem[] = [];
  let migratedCount = 0;
  let alreadyMigratedCount = 0;
  let failedCount = 0;

  // 2. Discover deployments
  interface RawDeploymentDoc {
    id: string;
    ownerId: string;
    title?: string;
    projectId?: string;
    htmlBundle?: string;
    r2Bucket?: string;
    artifactPath?: string;
  }

  let deploymentDocs: RawDeploymentDoc[] = [];

  if (options.firestore) {
    const snap = await options.firestore.collection('deployments').get();
    deploymentDocs = snap.docs.map((d) => {
      const data = d.data();
      return {
        id: d.id,
        ownerId: data.ownerId || 'unknown',
        title: data.title || d.id,
        projectId: data.projectId || d.id,
        htmlBundle: data.htmlBundle,
        r2Bucket: data.r2Bucket,
        artifactPath: data.artifactPath,
      };
    });
  } else if (options.adminStore) {
    // If AdminDatabaseOperations provides list/in-memory records
    if ('deployments' in (options.adminStore as any)) {
      const memStore = options.adminStore as any;
      for (const [slug, dep] of memStore.deployments.entries()) {
        deploymentDocs.push({
          id: slug,
          ownerId: dep.ownerUid || 'unknown',
          title: dep.title || slug,
          projectId: dep.projectId || slug,
          htmlBundle: dep.htmlBundle,
          r2Bucket: dep.r2Bucket,
          artifactPath: dep.artifactPath,
        });
      }
    }
  } else {
    // Attempt connecting to Firestore
    try {
      const db = initAdminFirestore();
      if (db) {
        const snap = await db.collection('deployments').get();
        deploymentDocs = snap.docs.map((d) => {
          const data = d.data();
          return {
            id: d.id,
            ownerId: data.ownerId || 'unknown',
            title: data.title || d.id,
            projectId: data.projectId || d.id,
            htmlBundle: data.htmlBundle,
            r2Bucket: data.r2Bucket,
            artifactPath: data.artifactPath,
          };
        });
      }
    } catch (err) {
      throw new Error(`Unable to connect to Firestore for deployment migration: ${(err as Error).message}`);
    }
  }

  if (verbose) {
    console.log(`[DeploymentMigration] Found ${deploymentDocs.length} deployment records.`);
  }

  // 3. Process each deployment
  for (const doc of deploymentDocs) {
    const slug = doc.id;
    const hasHtmlBundle = Boolean(doc.htmlBundle && doc.htmlBundle.trim().length > 0);
    let alreadyInR2 = false;

    try {
      alreadyInR2 = await r2.artifactExists(slug);
    } catch {
      alreadyInR2 = false;
    }

    // Case A: Document already migrated (no HTML in Firestore and artifact exists in R2)
    if (!hasHtmlBundle && (alreadyInR2 || doc.artifactPath)) {
      alreadyMigratedCount++;
      items.push({
        slug,
        ownerId: doc.ownerId,
        title: doc.title || slug,
        hasHtmlBundle: false,
        alreadyInR2,
        status: 'already_migrated',
      });
      if (verbose) console.log(`[DeploymentMigration] ${slug}: already migrated.`);
      continue;
    }

    // Case B: Document has HTML bundle in Firestore -> needs migration
    if (hasHtmlBundle) {
      try {
        const html = doc.htmlBundle!;
        const byteLength = Buffer.byteLength(html, 'utf8');

        if (!dryRun) {
          // Upload to R2
          const uploadInfo = await r2.uploadPublishedSite(slug, html);
          const verified = await r2.artifactExists(slug);
          if (!verified) {
            throw new Error('R2 upload verification failed: artifact not found after write.');
          }

          // Update Firestore record: remove htmlBundle, set R2 metadata
          if (options.firestore) {
            await options.firestore.collection('deployments').doc(slug).update({
              artifactPath: uploadInfo.key,
              r2Bucket: process.env.R2_BUCKET_NAME || 'mist-published-sites',
              bytes: byteLength,
              etag: uploadInfo.etag || null,
              migratedToR2At: FieldValue.serverTimestamp(),
              htmlBundle: FieldValue.delete(),
            });
          } else if (options.adminStore && 'deployments' in (options.adminStore as any)) {
            const memStore = options.adminStore as any;
            const existing = memStore.deployments.get(slug);
            if (existing) {
              existing.htmlBundle = '';
              existing.artifactPath = uploadInfo.key;
              existing.r2Bucket = process.env.R2_BUCKET_NAME || 'mist-published-sites';
            }
          }
        }

        migratedCount++;
        items.push({
          slug,
          ownerId: doc.ownerId,
          title: doc.title || slug,
          hasHtmlBundle: true,
          alreadyInR2,
          status: 'migrated',
          bytes: byteLength,
        });

        if (verbose) {
          console.log(`[DeploymentMigration] ${dryRun ? '[DRY RUN] Would migrate' : 'Migrated'} ${slug} (${byteLength} bytes) to R2.`);
        }
      } catch (err: any) {
        failedCount++;
        items.push({
          slug,
          ownerId: doc.ownerId,
          title: doc.title || slug,
          hasHtmlBundle: true,
          alreadyInR2,
          status: 'failed',
          error: err?.message || 'Unknown error during migration',
        });
        console.error(`[DeploymentMigration] Failed to migrate ${slug}:`, err);
      }
      continue;
    }

    // Case C: Neither has HTML in Firestore nor exists in R2
    items.push({
      slug,
      ownerId: doc.ownerId,
      title: doc.title || slug,
      hasHtmlBundle: false,
      alreadyInR2: false,
      status: 'skipped',
      error: 'Missing both Firestore HTML bundle and R2 artifact.',
    });
  }

  const completedAt = new Date().toISOString();

  return {
    dryRun,
    applied: apply,
    totalFound: deploymentDocs.length,
    migratedCount,
    alreadyMigratedCount,
    failedCount,
    items,
    startedAt,
    completedAt,
  };
}
