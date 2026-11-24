import {
  S3Client,
  PutObjectCommand,
  GetObjectCommand,
  DeleteObjectCommand,
  DeleteObjectsCommand,
  HeadObjectCommand,
  ListObjectsV2Command,
} from '@aws-sdk/client-s3';
import { SecurityValidationError } from './serverSecurity';

export interface PublishedArtifactInfo {
  key: string;
  bytes: number;
  contentType: string;
  etag?: string;
  uploadedAt: string;
}

export interface R2StorageOperations {
  uploadPublishedSite(
    slug: string,
    htmlBundle: string,
    options?: { customPath?: string },
  ): Promise<PublishedArtifactInfo>;
  deletePublishedSite(slug: string): Promise<boolean>;
  artifactExists(slug: string, relativePath?: string): Promise<boolean>;
  getPublishedHtml(slug: string): Promise<string | null>;
}

export function validateSiteSlug(slug: string): string {
  const cleaned = (slug || '').trim().toLowerCase();
  if (!cleaned) {
    throw new SecurityValidationError(400, 'Deployment slug cannot be empty.');
  }
  if (cleaned.length < 2 || cleaned.length > 63) {
    throw new SecurityValidationError(400, 'Deployment slug must be between 2 and 63 characters.');
  }
  if (!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(cleaned)) {
    throw new SecurityValidationError(
      400,
      'Deployment slug may only contain lowercase letters, numbers, and hyphens (cannot start or end with hyphen).',
    );
  }
  if (cleaned.includes('--')) {
    throw new SecurityValidationError(400, 'Deployment slug cannot contain consecutive hyphens.');
  }
  const reserved = new Set(['www', 'api', 'auth', 'admin', 'dashboard', 'assets', 'status', 'mail', 'app']);
  if (reserved.has(cleaned)) {
    throw new SecurityValidationError(400, `Slug "${cleaned}" is a reserved system name.`);
  }
  return cleaned;
}

export function validateArtifactPath(slug: string, subpath: string = 'index.html'): string {
  const safeSlug = validateSiteSlug(slug);
  const normalized = subpath.replace(/\\/g, '/').replace(/^\/+/, '');
  if (!normalized || normalized.includes('..') || normalized.includes('\0') || normalized.includes('//')) {
    throw new SecurityValidationError(400, 'Invalid or unsafe artifact path.');
  }
  return `sites/${safeSlug}/${normalized}`;
}

export class CloudflareR2ArtifactStore implements R2StorageOperations {
  private s3: S3Client;
  private bucket: string;

  constructor(options?: {
    accountId?: string;
    accessKeyId?: string;
    secretAccessKey?: string;
    bucketName?: string;
  }) {
    const accountId =
      options?.accountId || process.env.CLOUDFLARE_ACCOUNT_ID || process.env.CLOUDFLARE_R2_ACCOUNT_ID;
    const accessKeyId =
      options?.accessKeyId || process.env.R2_ACCESS_KEY_ID || process.env.CLOUDFLARE_R2_ACCESS_KEY_ID;
    const secretAccessKey =
      options?.secretAccessKey || process.env.R2_SECRET_ACCESS_KEY || process.env.CLOUDFLARE_R2_SECRET_ACCESS_KEY;
    this.bucket =
      options?.bucketName || process.env.R2_BUCKET_NAME || process.env.CLOUDFLARE_R2_BUCKET || 'mist-published-sites';

    if (!accountId || !accessKeyId || !secretAccessKey) {
      throw new Error(
        'Cloudflare R2 is not fully configured. Missing CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID, or R2_SECRET_ACCESS_KEY.',
      );
    }

    this.s3 = new S3Client({
      region: 'auto',
      endpoint: `https://${accountId}.r2.cloudflarestorage.com`,
      credentials: {
        accessKeyId,
        secretAccessKey,
      },
    });
  }

  async uploadPublishedSite(
    slug: string,
    htmlBundle: string,
    options?: { customPath?: string },
  ): Promise<PublishedArtifactInfo> {
    const key = validateArtifactPath(slug, options?.customPath || 'index.html');
    const bodyBuffer = Buffer.from(htmlBundle, 'utf8');

    const cmd = new PutObjectCommand({
      Bucket: this.bucket,
      Key: key,
      Body: bodyBuffer,
      ContentType: 'text/html; charset=utf-8',
      CacheControl: 'public, max-age=300, stale-while-revalidate=86400',
      Metadata: {
        'x-mist-slug': slug,
        'x-mist-bundled-at': new Date().toISOString(),
      },
    });

    const response = await this.s3.send(cmd);
    return {
      key,
      bytes: bodyBuffer.byteLength,
      contentType: 'text/html; charset=utf-8',
      etag: response.ETag,
      uploadedAt: new Date().toISOString(),
    };
  }

  async deletePublishedSite(slug: string): Promise<boolean> {
    const safeSlug = validateSiteSlug(slug);
    const prefix = `sites/${safeSlug}/`;
    try {
      const listed = await this.s3.send(
        new ListObjectsV2Command({
          Bucket: this.bucket,
          Prefix: prefix,
        }),
      );
      if (listed.Contents && listed.Contents.length > 0) {
        await this.s3.send(
          new DeleteObjectsCommand({
            Bucket: this.bucket,
            Delete: {
              Objects: listed.Contents.map((obj) => ({ Key: obj.Key! })),
            },
          }),
        );
      } else {
        await this.s3.send(
          new DeleteObjectCommand({
            Bucket: this.bucket,
            Key: `sites/${safeSlug}/index.html`,
          }),
        );
      }
      return true;
    } catch {
      return false;
    }
  }

  async artifactExists(slug: string, relativePath: string = 'index.html'): Promise<boolean> {
    const key = validateArtifactPath(slug, relativePath);
    try {
      await this.s3.send(
        new HeadObjectCommand({
          Bucket: this.bucket,
          Key: key,
        }),
      );
      return true;
    } catch {
      return false;
    }
  }

  async getPublishedHtml(slug: string): Promise<string | null> {
    const key = validateArtifactPath(slug, 'index.html');
    try {
      const resp = await this.s3.send(
        new GetObjectCommand({
          Bucket: this.bucket,
          Key: key,
        }),
      );
      if (!resp.Body) return null;
      return await resp.Body.transformToString('utf8');
    } catch {
      return null;
    }
  }
}

export class InMemoryR2ArtifactStore implements R2StorageOperations {
  public files = new Map<string, { content: string; contentType: string; updatedAt: string }>();

  async uploadPublishedSite(
    slug: string,
    htmlBundle: string,
    options?: { customPath?: string },
  ): Promise<PublishedArtifactInfo> {
    const key = validateArtifactPath(slug, options?.customPath || 'index.html');
    const bytes = Buffer.byteLength(htmlBundle, 'utf8');
    const now = new Date().toISOString();
    this.files.set(key, {
      content: htmlBundle,
      contentType: 'text/html; charset=utf-8',
      updatedAt: now,
    });
    return {
      key,
      bytes,
      contentType: 'text/html; charset=utf-8',
      etag: `"etag-${slug}-${Date.now()}"`,
      uploadedAt: now,
    };
  }

  async deletePublishedSite(slug: string): Promise<boolean> {
    const safeSlug = validateSiteSlug(slug);
    const prefix = `sites/${safeSlug}/`;
    let anyDeleted = false;
    for (const key of Array.from(this.files.keys())) {
      if (key.startsWith(prefix) || key === `sites/${safeSlug}/index.html`) {
        this.files.delete(key);
        anyDeleted = true;
      }
    }
    return anyDeleted;
  }

  async artifactExists(slug: string, relativePath: string = 'index.html'): Promise<boolean> {
    const key = validateArtifactPath(slug, relativePath);
    return this.files.has(key);
  }

  async getPublishedHtml(slug: string): Promise<string | null> {
    const key = validateArtifactPath(slug, 'index.html');
    const f = this.files.get(key);
    return f ? f.content : null;
  }
}
