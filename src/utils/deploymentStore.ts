import { SecurityValidationError } from './serverSecurity';
import { FirestoreAdminStore, type AdminDatabaseOperations } from '../server/firestoreAdmin';
import {
  CloudflareR2ArtifactStore,
  InMemoryR2ArtifactStore,
  type R2StorageOperations,
} from './r2ArtifactStore';

export interface StoredDeployment {
  slug: string;
  ownerUid: string;
  projectId: string;
  title: string;
  htmlBundle: string;
  createdAt?: string;
  updatedAt: string;
  r2Bucket?: string;
  artifactPath?: string;
}

export interface DeploymentSummary {
  slug: string;
  projectId: string;
  title: string;
  url: string;
  updatedAt: string;
}

export function formatDeploymentUrl(slug: string, publishBaseUrl?: string): string {
  const cleanSlug = (slug || '')
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  if (!cleanSlug) return '';

  const cleanBase = (publishBaseUrl || '').trim().replace(/\/+$/, '');
  if (!cleanBase) {
    // Strictly prevent same-origin publishing fallback
    return '';
  }

  if (cleanBase.includes('*')) {
    return cleanBase.replace('*', cleanSlug);
  }
  return `${cleanBase}/${cleanSlug}`;
}

export interface DeploymentStore {
  listByOwner(ownerUid: string, idToken?: string, publishBaseUrl?: string): Promise<DeploymentSummary[]>;
  getPublic(slug: string): Promise<StoredDeployment | null>;
  upsertOwned(
    input: {
      slug: string;
      ownerUid: string;
      projectId: string;
      title: string;
      htmlBundle: string;
    },
    idToken?: string,
  ): Promise<StoredDeployment>;
  deleteOwned(slug: string, ownerUid: string, idToken?: string): Promise<boolean>;
}

export const MAX_DEPLOYMENT_BUNDLE_BYTES = 900_000;

function resolveProductionStore<T>(name: string, initFn: () => T, fallback?: T): T | undefined {
  try {
    return initFn();
  } catch (err) {
    if (process.env.NODE_ENV === 'production') {
      throw new Error(
        `Failed to initialize production ${name}: ${
          err instanceof Error ? err.message : String(err)
        }`
      );
    }
    return fallback;
  }
}

export function createFirestoreDeploymentStore(options?: {
  adminStore?: AdminDatabaseOperations;
  r2Store?: R2StorageOperations;
}): DeploymentStore {
  let adminDb = options?.adminStore;
  let r2 = options?.r2Store;

  function getStores() {
    if (!adminDb) {
      adminDb = resolveProductionStore('FirestoreAdminStore', () => new FirestoreAdminStore());
    }
    if (!r2) {
      r2 = resolveProductionStore<R2StorageOperations>(
        'CloudflareR2ArtifactStore',
        () => new CloudflareR2ArtifactStore(),
        new InMemoryR2ArtifactStore(),
      )!;
    }
    return { adminDb, r2 };
  }

  return {
    async getPublic(slug: string): Promise<StoredDeployment | null> {
      const { adminDb, r2 } = getStores();
      if (adminDb) {
        const metadata = await adminDb.getDeployment(slug);
        if (metadata) {
          if (r2 && !metadata.htmlBundle) {
            const html = await r2.getPublishedHtml(slug);
            if (html) metadata.htmlBundle = html;
          }
          return metadata;
        }
      }
      if (r2) {
        const html = await r2.getPublishedHtml(slug);
        if (html) {
          return {
            slug,
            ownerUid: 'unknown',
            projectId: slug,
            title: slug,
            htmlBundle: html,
            updatedAt: new Date().toISOString(),
          };
        }
      }
      return null;
    },

    async listByOwner(ownerUid: string, _idToken?: string, publishBaseUrl?: string): Promise<DeploymentSummary[]> {
      const { adminDb } = getStores();
      if (!adminDb) return [];
      const list = await adminDb.listDeployments(ownerUid);
      const baseUrl = publishBaseUrl ?? process.env.PUBLISH_BASE_URL?.trim();
      return list.map((item) => ({
        ...item,
        url: formatDeploymentUrl(item.slug, baseUrl),
      }));
    },

    async upsertOwned(input): Promise<StoredDeployment> {
      const { adminDb, r2 } = getStores();
      const slug = input.slug;

      // 1. Enforce ownership check BEFORE any R2 write: prevent user A from overwriting user B's site
      if (adminDb) {
        const existing = await adminDb.getDeployment(slug);
        if (existing && existing.ownerUid !== input.ownerUid) {
          throw new SecurityValidationError(403, 'Deployment slug belongs to another user.');
        }
      }

      // 2. Upload HTML bundle to Cloudflare R2
      let artifactInfo: { key: string; bytes?: number; etag?: string } | undefined;
      if (r2) {
        artifactInfo = await r2.uploadPublishedSite(slug, input.htmlBundle);
        const exists = await r2.artifactExists(slug);
        if (!exists) {
          throw new SecurityValidationError(500, 'Artifact upload verification failed.');
        }
      }

      // 3. Store publishing metadata and ownership in Firestore (omitting full htmlBundle when R2 is active)
      if (adminDb) {
        await adminDb.saveDeployment(input.ownerUid, {
          slug,
          projectId: input.projectId,
          title: input.title,
          r2Bucket: process.env.R2_BUCKET_NAME || 'mist-published-sites',
          artifactPath: artifactInfo?.key || `sites/${slug}/index.html`,
          htmlBundle: r2 ? undefined : input.htmlBundle,
          bytes: artifactInfo?.bytes,
          etag: artifactInfo?.etag,
        });
      }

      const now = new Date().toISOString();
      return {
        slug: input.slug,
        ownerUid: input.ownerUid,
        projectId: input.projectId,
        title: input.title,
        htmlBundle: input.htmlBundle,
        createdAt: now,
        updatedAt: now,
        artifactPath: artifactInfo?.key,
      };
    },

    async deleteOwned(slug: string, ownerUid: string): Promise<boolean> {
      const { adminDb, r2 } = getStores();
      // Ownership check is strictly enforced in adminDb.deleteDeployment FIRST
      if (adminDb) {
        const deleted = await adminDb.deleteDeployment(ownerUid, slug);
        if (deleted && r2) {
          await r2.deletePublishedSite(slug).catch((err) => {
            console.warn(`[Mist Deployment] Failed to delete R2 artifact for ${slug}:`, err);
          });
        }
        return deleted;
      }
      if (r2) {
        return r2.deletePublishedSite(slug);
      }
      return true;
    },
  };
}

/**
 * In-memory DeploymentStore implementation matching the exact authorization semantics
 * for unit tests (without hitting live Firestore/R2).
 */
export function createMemoryDeploymentStore(): DeploymentStore {
  const map = new Map<string, StoredDeployment>();
  return {
    async getPublic(slug: string) {
      return map.get(slug) || null;
    },
    async listByOwner(ownerUid: string, _idToken?: string, publishBaseUrl?: string) {
      const list: DeploymentSummary[] = [];
      const baseUrl = publishBaseUrl ?? process.env.PUBLISH_BASE_URL?.trim();
      for (const dep of map.values()) {
        if (dep.ownerUid === ownerUid) {
          list.push({
            slug: dep.slug,
            projectId: dep.projectId,
            title: dep.title,
            url: formatDeploymentUrl(dep.slug, baseUrl),
            updatedAt: dep.updatedAt,
          });
        }
      }
      return list.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    },
    async upsertOwned(input) {
      const existing = map.get(input.slug);
      if (existing && existing.ownerUid !== input.ownerUid) {
        throw new SecurityValidationError(403, 'This deployment URL is owned by another user.');
      }
      const now = new Date().toISOString();
      const saved: StoredDeployment = {
        slug: input.slug,
        ownerUid: input.ownerUid,
        projectId: input.projectId,
        title: input.title,
        htmlBundle: input.htmlBundle,
        createdAt: existing?.createdAt || now,
        updatedAt: now,
      };
      map.set(input.slug, saved);
      return saved;
    },
    async deleteOwned(slug, ownerUid) {
      const existing = map.get(slug);
      if (!existing) return false;
      if (existing.ownerUid !== ownerUid) {
        throw new SecurityValidationError(403, 'Only the deployment owner can unpublish this site.');
      }
      map.delete(slug);
      return true;
    },
  };
}
