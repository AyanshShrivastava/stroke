import crypto from 'node:crypto';
import dns from 'node:dns/promises';
import net from 'node:net';
import fs from 'node:fs';
import path from 'node:path';
import type {
  Request as ExpressRequest,
  Response as ExpressResponse,
  NextFunction,
} from 'express';
import type {
  AiProviderConfig,
  ChatMessage,
  MistProject,
  ProjectFile,
  WebSearchConfig,
} from '../types/mist';
import { redactSecrets } from './aiErrors';
import { maskApiKey, normalizeProjectFilePath } from './projectOps';

// --- 1. SSRF Protection, Safe Redirect-Blocked Fetch & URL Validation ---

const BLOCKED_HOSTNAMES = new Set([
  'localhost',
  'localhost.localdomain',
  'ip6-localhost',
  'ip6-loopback',
  'metadata.google.internal',
  'metadata',
  'instance-data',
  '0.0.0.0',
  '169.254.169.254',
  '169.254.169.253',
  '100.100.100.200',
]);

export function isPrivateOrReservedIp(ip: string): boolean {
  let clean = (ip || '').trim().toLowerCase();
  // Strip IPv4-mapped IPv6 prefix (e.g., ::ffff:127.0.0.1 or ::ffff:7f00:1)
  if (clean.startsWith('::ffff:')) {
    clean = clean.slice('::ffff:'.length);
    if (clean.includes(':')) {
      const hexParts = clean.split(':');
      if (hexParts.length === 2) {
        const num1 = parseInt(hexParts[0], 16);
        const num2 = parseInt(hexParts[1], 16);
        if (!isNaN(num1) && !isNaN(num2)) {
          clean = `${(num1 >> 8) & 0xff}.${num1 & 0xff}.${(num2 >> 8) & 0xff}.${num2 & 0xff}`;
        }
      }
    }
  }

  if (net.isIPv4(clean)) {
    const parts = clean.split('.').map(Number);
    if (parts.length !== 4 || parts.some((n) => Number.isNaN(n) || n < 0 || n > 255)) return true;
    const [a, b, c, d] = parts;
    if (a === 0) return true; // 0.0.0.0/8
    if (a === 10) return true; // 10.0.0.0/8
    if (a === 100 && b >= 64 && b <= 127) return true; // CGNAT 100.64.0.0/10
    if (a === 100 && b === 100 && c === 100 && d === 200) return true; // Alibaba Cloud metadata 100.100.100.200
    if (a === 127) return true; // Loopback 127.0.0.0/8
    if (a === 169 && b === 254) return true; // Link-local & cloud metadata 169.254.0.0/16
    if (a === 172 && b >= 16 && b <= 31) return true; // 172.16.0.0/12
    if (a === 192 && b === 168) return true; // 192.168.0.0/16
    if (a === 192 && b === 0 && c === 0) return true; // 192.0.0.0/24 (IETF protocol assignments)
    if (a === 192 && b === 0 && c === 2) return true; // TEST-NET-1 (192.0.2.0/24)
    if (a === 198 && (b === 18 || b === 19)) return true; // Benchmarking (198.18.0.0/15)
    if (a === 198 && b === 51 && c === 100) return true; // TEST-NET-2 (198.51.100.0/24)
    if (a === 203 && b === 0 && c === 113) return true; // TEST-NET-3 (203.0.113.0/24)
    if (a >= 224) return true; // Multicast (224.0.0.0/4), Reserved Class E (240.0.0.0/4), Broadcast (255.255.255.255)
    return false;
  }

  if (net.isIPv6(clean)) {
    const lower = clean.toLowerCase();
    if (lower === '::' || lower === '::1') return true;
    if (lower.startsWith('fc') || lower.startsWith('fd')) return true; // Unique local fc00::/7
    if (lower.startsWith('fe8') || lower.startsWith('fe9') || lower.startsWith('fea') || lower.startsWith('feb')) {
      return true; // Link-local fe80::/10
    }
    if (lower.startsWith('ff')) return true; // Multicast
    if (lower.startsWith('2001:db8:') || lower.startsWith('2001:0db8:')) return true; // Documentation
    if (lower.startsWith('64:ff9b::')) return true; // IPv4/IPv6 translation
    return false;
  }

  return true;
}

export class SecurityValidationError extends Error {
  status: number;
  code: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code =
      code ||
      (status === 400
        ? 'VALIDATION_ERROR'
        : status === 401
          ? 'UNAUTHORIZED'
          : status === 403
            ? 'FORBIDDEN'
            : status === 404
              ? 'NOT_FOUND'
              : status === 413
                ? 'PAYLOAD_TOO_LARGE'
                : status === 429
                  ? 'RATE_LIMIT_EXCEEDED'
                  : 'SECURITY_ERROR');
  }
}

export function validateExternalUrlSyntax(rawUrl: string): URL {
  let parsed: URL;
  try {
    parsed = new URL((rawUrl || '').trim());
  } catch {
    throw new SecurityValidationError(400, 'Enter a valid HTTPS Base URL (e.g. https://openrouter.ai/api/v1).');
  }

  if (parsed.protocol !== 'https:') {
    throw new SecurityValidationError(400, 'For security, external AI endpoints must use HTTPS (https://).');
  }

  if (parsed.username || parsed.password) {
    throw new SecurityValidationError(400, 'Embedded credentials in URLs are not allowed.');
  }

  const host = parsed.hostname.toLowerCase();
  if (
    !host ||
    BLOCKED_HOSTNAMES.has(host) ||
    host.endsWith('.local') ||
    host.endsWith('.internal') ||
    host.endsWith('.localhost') ||
    host.endsWith('.arpa')
  ) {
    throw new SecurityValidationError(400, 'Blocked internal or loopback host.');
  }

  if (net.isIP(host) && isPrivateOrReservedIp(host)) {
    throw new SecurityValidationError(400, 'Private, link-local, and metadata IP addresses are blocked.');
  }

  return parsed;
}

export type LookupFn = (
  hostname: string,
  options: { all: true; verbatim: true },
) => Promise<Array<{ address: string; family: number }>>;

export async function assertSafeExternalUrl(
  rawUrl: string,
  options?: { skipDnsLookup?: boolean; lookupFn?: LookupFn },
): Promise<URL> {
  const parsed = validateExternalUrlSyntax(rawUrl);
  const host = parsed.hostname.toLowerCase();
  const lookup = options?.lookupFn || dns.lookup;

  if (!options?.skipDnsLookup && !net.isIP(host)) {
    try {
      const resolved = (await lookup(host, {
        all: true,
        verbatim: true,
      })) as Array<{ address: string; family: number }>;
      if (resolved.length === 0) {
        throw new SecurityValidationError(400, `Unable to resolve host "${host}".`);
      }
      for (const entry of resolved) {
        if (isPrivateOrReservedIp(entry.address)) {
          throw new SecurityValidationError(
            400,
            `Host "${host}" resolved to a restricted private IP address.`,
          );
        }
      }
    } catch (err) {
      if (err instanceof SecurityValidationError) throw err;
      throw new SecurityValidationError(400, `DNS resolution failed for "${host}".`);
    }
  }

  return parsed;
}

export interface SafeFetchOptions extends Omit<RequestInit, 'redirect' | 'signal'> {
  timeoutMs?: number;
  parentSignal?: AbortSignal;
  skipDnsLookup?: boolean;
  lookupFn?: LookupFn;
  fetchImpl?: typeof fetch;
}

/**
 * Performs an SSRF-hardened external fetch:
 * - Validates HTTPS syntax & resolves DNS immediately before connecting (blocks private/loopback/metadata IPs)
 * - Disables HTTP redirects (`redirect: 'error'`) so 301/302 responses cannot redirect into internal networks
 * - Attaches bounded timeouts & propagates caller AbortSignal cancellation
 */
export async function safeFetchExternal(
  rawUrl: string,
  options: SafeFetchOptions = {},
): Promise<Response> {
  const {
    timeoutMs = 15000,
    parentSignal,
    skipDnsLookup,
    lookupFn,
    fetchImpl = globalThis.fetch,
    ...requestInit
  } = options;

  const parsed = await assertSafeExternalUrl(rawUrl, { skipDnsLookup, lookupFn });

  const controller = new AbortController();
  let timedOut = false;

  const onParentAbort = () => controller.abort();
  if (parentSignal) {
    if (parentSignal.aborted) {
      controller.abort();
    } else {
      parentSignal.addEventListener('abort', onParentAbort, { once: true });
    }
  }

  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    return await fetchImpl(parsed.toString(), {
      ...requestInit,
      redirect: 'error',
      signal: controller.signal,
    });
  } catch (err) {
    if (timedOut) {
      throw new SecurityValidationError(504, `Upstream endpoint timed out after ${Math.round(timeoutMs / 1000)}s.`);
    }
    const msg = err instanceof Error ? err.message.toLowerCase() : '';
    const causeMsg =
      err instanceof Error && err.cause instanceof Error ? err.cause.message.toLowerCase() : '';
    if (msg.includes('redirect') || causeMsg.includes('redirect')) {
      throw new SecurityValidationError(400, 'Blocked HTTP redirect from external endpoint.');
    }
    throw err;
  } finally {
    clearTimeout(timer);
    if (parentSignal) {
      parentSignal.removeEventListener('abort', onParentAbort);
    }
  }
}

export function sanitizeErrorMessage(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err || '');
  return redactSecrets(raw);
}

// --- 2. Generated File & Path Validation Limits ---

export const MAX_PROJECT_FILES = 120;
export const MAX_FILE_BYTES = 250_000;
export const MAX_TOTAL_PROJECT_BYTES = 3_500_000;

export function validateProjectFilesPayload(
  files: unknown,
  options?: { requireNonEmpty?: boolean },
): ProjectFile[] {
  if (!Array.isArray(files)) {
    throw new SecurityValidationError(400, 'Invalid files payload: expected an array.');
  }
  if (options?.requireNonEmpty && files.length === 0) {
    throw new SecurityValidationError(400, 'Project must contain at least one file.');
  }
  if (files.length > MAX_PROJECT_FILES) {
    throw new SecurityValidationError(
      400,
      `Project exceeds the maximum limit of ${MAX_PROJECT_FILES} files.`,
    );
  }

  let totalBytes = 0;
  const validated: ProjectFile[] = [];
  const seenPaths = new Set<string>();

  for (let i = 0; i < files.length; i++) {
    const raw = files[i] as Partial<ProjectFile> | null;
    if (!raw || typeof raw !== 'object') {
      throw new SecurityValidationError(400, `Invalid file entry at index ${i}.`);
    }
    const rawPath = String(raw.path || '');
    if (rawPath.includes('\0') || rawPath.includes('..')) {
      throw new SecurityValidationError(400, `Unsafe file path rejected: "${rawPath}".`);
    }
    const cleanPath = normalizeProjectFilePath(rawPath);
    if (!cleanPath || cleanPath.length > 256 || !/^[a-zA-Z0-9._/\-]+$/.test(cleanPath)) {
      throw new SecurityValidationError(400, `Invalid file path: "${cleanPath || '(empty)'}".`);
    }
    if (cleanPath.split('/').some((seg) => seg === '..' || seg === '.')) {
      throw new SecurityValidationError(400, `Path traversal segment not permitted in "${cleanPath}".`);
    }
    if (seenPaths.has(cleanPath.toLowerCase())) continue;
    seenPaths.add(cleanPath.toLowerCase());

    const content = typeof raw.content === 'string' ? raw.content : '';
    const bytes = Buffer.byteLength(content, 'utf8');
    if (bytes > MAX_FILE_BYTES) {
      throw new SecurityValidationError(
        400,
        `File "${cleanPath}" exceeds maximum allowed size (${Math.round(MAX_FILE_BYTES / 1000)}KB).`,
      );
    }
    totalBytes += bytes;
    if (totalBytes > MAX_TOTAL_PROJECT_BYTES) {
      throw new SecurityValidationError(400, 'Total project source size exceeds 3.5MB limit.');
    }

    const lang = raw.language;
    const validLang: ProjectFile['language'] =
      lang === 'tsx' || lang === 'ts' || lang === 'css' || lang === 'html' || lang === 'json'
        ? lang
        : cleanPath.endsWith('.css')
          ? 'css'
          : cleanPath.endsWith('.ts')
            ? 'ts'
            : cleanPath.endsWith('.html')
              ? 'html'
              : cleanPath.endsWith('.json')
                ? 'json'
                : 'tsx';

    validated.push({
      id: typeof raw.id === 'string' && raw.id.trim() ? raw.id.slice(0, 128) : `file_${i}`,
      path: cleanPath,
      language: validLang,
      content,
    });
  }

  return validated;
}

export function validateProjectPayload(raw: unknown): MistProject {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new SecurityValidationError(400, 'Invalid project payload: expected an object.');
  }

  // Block prototype pollution
  if (
    Object.prototype.hasOwnProperty.call(raw, '__proto__') ||
    Object.prototype.hasOwnProperty.call(raw, 'constructor') ||
    Object.prototype.hasOwnProperty.call(raw, 'prototype')
  ) {
    throw new SecurityValidationError(400, 'Invalid project payload: prototype properties are forbidden.');
  }

  const p = raw as Record<string, unknown>;

  const id = typeof p.id === 'string' ? p.id.trim() : '';
  if (!id) {
    throw new SecurityValidationError(400, 'Project ID is required.');
  }
  if (id.length > 64 || !/^[a-zA-Z0-9_-]+$/.test(id)) {
    throw new SecurityValidationError(400, 'Project ID contains invalid characters or exceeds 64 characters.');
  }

  const name = typeof p.name === 'string' ? p.name.trim().slice(0, 120) : 'Untitled Website';
  const description = typeof p.description === 'string' ? p.description.trim().slice(0, 500) : '';
  const prompt = typeof p.prompt === 'string' ? p.prompt.trim().slice(0, 4000) : '';
  const templateId =
    typeof p.templateId === 'string' && p.templateId.trim() ? p.templateId.trim().slice(0, 64) : undefined;
  const publishedSlug =
    typeof p.publishedSlug === 'string' && p.publishedSlug.trim() ? p.publishedSlug.trim().slice(0, 80) : undefined;
  const isPublished = Boolean(p.isPublished);
  const appAiEnabled = Boolean(p.appAiEnabled);
  const ownerId = typeof p.ownerId === 'string' && p.ownerId.trim() ? p.ownerId.trim().slice(0, 128) : undefined;

  // Validate files
  const files = validateProjectFilesPayload(p.files || []);

  // Validate createdAt/updatedAt
  let createdAt = typeof p.createdAt === 'string' ? p.createdAt.trim() : '';
  if (createdAt && isNaN(new Date(createdAt).getTime())) {
    createdAt = new Date().toISOString();
  }
  let updatedAt = typeof p.updatedAt === 'string' ? p.updatedAt.trim() : '';
  if (updatedAt && isNaN(new Date(updatedAt).getTime())) {
    updatedAt = new Date().toISOString();
  }

  // Validate chatHistory if present
  const chatHistory: ChatMessage[] = [];
  if (Array.isArray(p.chatHistory)) {
    for (let idx = 0; idx < Math.min(p.chatHistory.length, 100); idx++) {
      const m = p.chatHistory[idx];
      if (m && typeof m === 'object') {
        chatHistory.push({
          id: typeof m.id === 'string' ? m.id.slice(0, 64) : `msg_${idx}`,
          role: m.role === 'assistant' ? 'assistant' : 'user',
          content: typeof m.content === 'string' ? m.content.slice(0, 24000) : '',
          timestamp: typeof m.timestamp === 'string' ? m.timestamp.slice(0, 64) : new Date().toISOString(),
          changedFiles: Array.isArray(m.changedFiles) ? m.changedFiles.map(String).slice(0, 120) : undefined,
          searchOutcome: typeof m.searchOutcome === 'object' ? m.searchOutcome : undefined,
        });
      }
    }
  }

  return {
    id,
    ownerId,
    name,
    description,
    prompt,
    templateId,
    publishedSlug,
    isPublished,
    appAiEnabled,
    files,
    chatHistory,
    createdAt: createdAt || new Date().toISOString(),
    updatedAt: updatedAt || new Date().toISOString(),
  };
}

// --- 3. Sliding-Window Rate Limiter (Trusted req.ip + Authenticated User UID) ---

export interface RateLimitCheckResult {
  allowed: boolean;
  remaining: number;
  retryAfterSeconds?: number;
  limit: number;
  resetSeconds: number;
  totalRequests: number;
}

export interface SharedRateLimitAdapter {
  checkAndRecord: (
    key: string,
    limit: number,
    windowMs: number,
  ) => Promise<RateLimitCheckResult> | RateLimitCheckResult;
  recordViolation?: (key: string, windowMs?: number) => Promise<number> | number;
  reset?: (key: string) => Promise<void> | void;
}

interface MemoryRateBucket {
  timestamps: number[];
  violations: number[];
}

export class MemoryRateLimitAdapter implements SharedRateLimitAdapter {
  private buckets = new Map<string, MemoryRateBucket>();
  private readonly maxBuckets = 5000;

  checkAndRecord(key: string, limit: number, windowMs: number): RateLimitCheckResult {
    const now = Date.now();
    const cutoff = now - windowMs;
    let bucket = this.buckets.get(key);
    if (!bucket) {
      bucket = { timestamps: [], violations: [] };
      this.buckets.set(key, bucket);
    }

    bucket.timestamps = bucket.timestamps.filter((t) => t > cutoff);
    bucket.violations = bucket.violations.filter((t) => t > now - 10 * 60 * 1000); // 10 min window for violations

    const totalRequests = bucket.timestamps.length;
    const remaining = Math.max(0, limit - totalRequests);
    const resetSeconds =
      totalRequests > 0
        ? Math.max(1, Math.ceil((bucket.timestamps[0] + windowMs - now) / 1000))
        : Math.ceil(windowMs / 1000);

    if (totalRequests >= limit) {
      // Abuse penalty: multiple violations within 10 minutes increase cool-off
      bucket.violations.push(now);
      const violationCount = bucket.violations.length;
      const penaltyMultiplier = violationCount >= 5 ? Math.min(5, 1 + (violationCount - 4) * 0.5) : 1;
      const retryAfterSeconds = Math.max(1, Math.ceil(resetSeconds * penaltyMultiplier));

      return {
        allowed: false,
        remaining: 0,
        retryAfterSeconds,
        limit,
        resetSeconds,
        totalRequests,
      };
    }

    bucket.timestamps.push(now);
    this.evictStale(cutoff);

    return {
      allowed: true,
      remaining: Math.max(0, limit - (totalRequests + 1)),
      limit,
      resetSeconds,
      totalRequests: totalRequests + 1,
    };
  }

  recordViolation(key: string): number {
    const now = Date.now();
    let bucket = this.buckets.get(key);
    if (!bucket) {
      bucket = { timestamps: [], violations: [] };
      this.buckets.set(key, bucket);
    }
    bucket.violations.push(now);
    return bucket.violations.length;
  }

  reset(key: string): void {
    this.buckets.delete(key);
  }

  private evictStale(cutoff: number): void {
    if (this.buckets.size > this.maxBuckets) {
      for (const [k, b] of this.buckets.entries()) {
        if (b.timestamps.every((t) => t <= cutoff) && b.violations.length === 0) {
          this.buckets.delete(k);
        }
      }
    }
  }
}

export function createRateLimiter(options: {
  windowMs: number;
  maxRequests: number;
  label: string;
  userMaxRequests?: number;
  getUserKey?: (req: ExpressRequest) => string | undefined;
  adapter?: SharedRateLimitAdapter;
}) {
  const localAdapter = new MemoryRateLimitAdapter();
  const adapter = options.adapter || localAdapter;

  return async (req: ExpressRequest, res: ExpressResponse, next: NextFunction) => {
    // Strictly rely on Express's resolved `req.ip` (governed by app.set('trust proxy', ...)),
    // never blindly trusting raw spoofable X-Forwarded-For headers.
    const clientIp = req.ip || req.socket?.remoteAddress || 'unknown';
    const userKey = options.getUserKey?.(req) || (req as AuthenticatedRequest).authUser?.uid;
    const userLimit = options.userMaxRequests ?? options.maxRequests;

    try {
      // 1. Check IP rate limit
      let ipResult: RateLimitCheckResult;
      try {
        ipResult = await adapter.checkAndRecord(`ip:${clientIp}`, options.maxRequests, options.windowMs);
      } catch (adapterErr) {
        console.warn(`[Mist RateLimiter] Shared adapter failed for IP ${clientIp}, falling back to local memory:`, adapterErr);
        ipResult = localAdapter.checkAndRecord(`ip:${clientIp}`, options.maxRequests, options.windowMs);
      }

      // Set standard RFC rate limit headers for client inspection
      res.setHeader('X-RateLimit-Limit', String(options.maxRequests));
      res.setHeader('X-RateLimit-Remaining', String(ipResult.remaining));
      res.setHeader('X-RateLimit-Reset', String(ipResult.resetSeconds));

      if (!ipResult.allowed) {
        const retry = ipResult.retryAfterSeconds || 1;
        res.setHeader('Retry-After', String(retry));
        res.status(429).json({
          error: `Too many ${options.label} requests from this network. Please wait ${retry}s and try again.`,
          code: 'RATE_LIMIT_EXCEEDED',
          status: 429,
          retryAfter: retry,
          limit: options.maxRequests,
          windowMs: options.windowMs,
        });
        return;
      }

      // 2. Check authenticated user rate limit if applicable
      if (userKey) {
        let userResult: RateLimitCheckResult;
        try {
          userResult = await adapter.checkAndRecord(`uid:${userKey}`, userLimit, options.windowMs);
        } catch (adapterErr) {
          console.warn(`[Mist RateLimiter] Shared adapter failed for User ${userKey}, falling back to local memory:`, adapterErr);
          userResult = localAdapter.checkAndRecord(`uid:${userKey}`, userLimit, options.windowMs);
        }

        res.setHeader('X-RateLimit-Remaining', String(Math.min(ipResult.remaining, userResult.remaining)));

        if (!userResult.allowed) {
          const retry = userResult.retryAfterSeconds || 1;
          res.setHeader('Retry-After', String(retry));
          res.status(429).json({
            error: `Too many ${options.label} requests for this account. Please wait ${retry}s and try again.`,
            code: 'RATE_LIMIT_EXCEEDED',
            status: 429,
            retryAfter: retry,
            limit: userLimit,
            windowMs: options.windowMs,
          });
          return;
        }
      }

      next();
    } catch (err) {
      // In unexpected failure cases, fail open with warning so system doesn't crash
      console.error('[Mist RateLimiter] Rate limiting error:', err);
      next();
    }
  };
}

// --- 4. Ephemeral Scoped Preview AI Session Vault (Owner-Bound) ---

interface PreviewSessionRecord {
  config: AiProviderConfig;
  ownerUid?: string;
  expiresAt: number;
  createdAt: number;
}

const SESSION_TTL_MS = 2 * 60 * 60 * 1000;
const MAX_SESSIONS = 500;
const previewSessions = new Map<string, PreviewSessionRecord>();

export function createPreviewAiSession(
  config: AiProviderConfig,
  ownerUid?: string,
): {
  token: string;
  expiresAt: string;
} {
  const now = Date.now();
  for (const [key, rec] of previewSessions.entries()) {
    if (rec.expiresAt <= now) previewSessions.delete(key);
  }
  while (previewSessions.size >= MAX_SESSIONS) {
    const oldestKey = previewSessions.keys().next().value;
    if (!oldestKey) break;
    previewSessions.delete(oldestKey);
  }

  const token = `mist_sess_${crypto.randomBytes(24).toString('hex')}`;
  const expiresAt = now + SESSION_TTL_MS;
  previewSessions.set(token, {
    config: { ...config },
    ownerUid,
    expiresAt,
    createdAt: now,
  });

  return {
    token,
    expiresAt: new Date(expiresAt).toISOString(),
  };
}

export function resolvePreviewAiSession(token?: string): AiProviderConfig | null {
  if (!token || typeof token !== 'string' || !token.startsWith('mist_sess_')) {
    return null;
  }
  const rec = previewSessions.get(token);
  if (!rec) return null;
  if (rec.expiresAt <= Date.now()) {
    previewSessions.delete(token);
    return null;
  }
  return rec.config;
}

export function revokePreviewAiSession(token?: string, requesterUid?: string): boolean {
  if (!token) return false;
  const rec = previewSessions.get(token);
  if (!rec) return false;
  if (rec.ownerUid && requesterUid && rec.ownerUid !== requesterUid) {
    throw new SecurityValidationError(403, 'You do not have permission to revoke this session token.');
  }
  if (rec.ownerUid && !requesterUid) {
    throw new SecurityValidationError(401, 'Authentication required to revoke this session.');
  }
  return previewSessions.delete(token);
}

export function revokeAllUserPreviewSessions(uid?: string): number {
  if (!uid) return 0;
  let removed = 0;
  for (const [token, rec] of previewSessions.entries()) {
    if (rec.ownerUid === uid) {
      previewSessions.delete(token);
      removed += 1;
    }
  }
  return removed;
}

// --- 4B. Account-Bound AES-256-GCM Encrypted Credential Vault ---

// --- 4B. Account-Bound AES-256-GCM Encrypted Credential Vault & Secret Management ---

export const MIN_VAULT_SECRET_ENTROPY_CHARS = 32;

const FORBIDDEN_SECRET_PATTERNS = [
  'generate_random',
  'your-secret',
  'your-vault-secret',
  'mist-vault-secret',
  '12345678901234567890123456789012',
  'password',
  'secret',
  'change_me',
  'placeholder',
];

export function assertValidVaultSecret(
  secret: string | undefined,
  isProduction: boolean,
): string {
  const trimmed = secret?.trim() || '';

  if (isProduction) {
    if (!trimmed) {
      throw new SecurityValidationError(
        500,
        'Server configuration error: MIST_VAULT_SECRET must be configured in production.',
      );
    }
    if (trimmed.length < MIN_VAULT_SECRET_ENTROPY_CHARS) {
      throw new SecurityValidationError(
        500,
        `Server configuration error: MIST_VAULT_SECRET must be at least ${MIN_VAULT_SECRET_ENTROPY_CHARS} high-entropy characters in production.`,
      );
    }
    const lower = trimmed.toLowerCase();
    if (
      FORBIDDEN_SECRET_PATTERNS.some((p) => lower.includes(p)) ||
      /^([a-z0-9])\1{31,}$/i.test(trimmed) ||
      new Set(trimmed).size < 10
    ) {
      throw new SecurityValidationError(
        500,
        'Server configuration error: MIST_VAULT_SECRET is too weak or uses a known placeholder.',
      );
    }
    return trimmed;
  }

  // Non-production (dev/test): use provided secret if valid, otherwise safe dev-only secret
  if (trimmed) {
    return trimmed;
  }
  return 'mist-dev-vault-secret-do-not-use-in-production-entropy-32c';
}

export interface RenderCredentialConfig {
  apiKey: string;
  ownerId: string;
  ownerName: string;
  ownerEmail?: string;
  workspaceType?: 'user' | 'team';
  connectedAt?: string;
}

export interface VaultPlainPayload {
  aiConfig?: AiProviderConfig;
  searchConfig?: WebSearchConfig;
  renderConfig?: RenderCredentialConfig;
  needsReencryption?: boolean;
}

export function validateVaultPayload(payload: unknown): VaultPlainPayload {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new SecurityValidationError(400, 'Invalid credential vault payload: must be an object.');
  }

  const obj = payload as Record<string, unknown>;

  // Block prototype pollution attempts
  if (
    Object.prototype.hasOwnProperty.call(obj, '__proto__') ||
    Object.prototype.hasOwnProperty.call(obj, 'constructor') ||
    Object.prototype.hasOwnProperty.call(obj, 'prototype')
  ) {
    throw new SecurityValidationError(400, 'Invalid credential vault payload: forbidden properties detected.');
  }

  let rawJson = '';
  try {
    rawJson = JSON.stringify(obj);
  } catch {
    throw new SecurityValidationError(400, 'Credential vault payload cannot be serialized.');
  }

  if (rawJson.length > 65536) {
    throw new SecurityValidationError(400, 'Credential vault payload exceeds maximum allowed size (64KB).');
  }

  const result: VaultPlainPayload = {};

  if (obj.aiConfig !== undefined) {
    if (!obj.aiConfig || typeof obj.aiConfig !== 'object' || Array.isArray(obj.aiConfig)) {
      throw new SecurityValidationError(400, 'Invalid aiConfig in credential vault payload.');
    }
    const ai = obj.aiConfig as Record<string, unknown>;
    const provider = String(ai.provider || '').trim().toLowerCase();
    const VALID_AI_PROVIDERS = new Set(['custom', 'openrouter', 'groq', 'gemini', 'openai', 'nvidia']);
    if (provider && !VALID_AI_PROVIDERS.has(provider)) {
      throw new SecurityValidationError(400, `Invalid AI provider '${provider}' in credential vault.`);
    }

    const apiKey = typeof ai.apiKey === 'string' ? ai.apiKey.trim() : '';
    if (apiKey.length > 512) {
      throw new SecurityValidationError(400, 'AI API key exceeds maximum length (512 characters).');
    }

    const model = typeof ai.model === 'string' ? ai.model.trim().slice(0, 128) : '';
    const name = typeof ai.name === 'string' ? ai.name.trim().slice(0, 128) : undefined;
    let baseUrl: string | undefined = undefined;
    if (typeof ai.baseUrl === 'string' && ai.baseUrl.trim()) {
      const bUrl = ai.baseUrl.trim();
      if (bUrl.length > 2048) {
        throw new SecurityValidationError(400, 'AI baseUrl exceeds maximum length (2048 characters).');
      }
      try {
        const u = new URL(bUrl);
        if (u.protocol !== 'https:' && u.protocol !== 'http:') {
          throw new SecurityValidationError(400, 'AI baseUrl must use http or https protocol.');
        }
      } catch {
        throw new SecurityValidationError(400, 'AI baseUrl is not a valid URL.');
      }
      baseUrl = bUrl;
    }

    let customEndpoint: string | undefined = undefined;
    if (typeof ai.customEndpoint === 'string' && ai.customEndpoint.trim()) {
      const endpoint = ai.customEndpoint.trim();
      if (endpoint.length > 2048) {
        throw new SecurityValidationError(400, 'AI custom endpoint exceeds maximum length (2048 characters).');
      }
      try {
        const u = new URL(endpoint);
        if (u.protocol !== 'https:' && u.protocol !== 'http:') {
          throw new SecurityValidationError(400, 'AI custom endpoint must use http or https protocol.');
        }
      } catch {
        throw new SecurityValidationError(400, 'AI custom endpoint is not a valid URL.');
      }
      customEndpoint = endpoint;
    }

    result.aiConfig = {
      ...(ai as any),
      provider: (provider || 'custom') as any,
      apiKey,
      model,
      name,
      baseUrl,
      customEndpoint,
      sessionOnlyKey: Boolean(ai.sessionOnlyKey),
    };
  }

  if (obj.searchConfig !== undefined) {
    if (!obj.searchConfig || typeof obj.searchConfig !== 'object' || Array.isArray(obj.searchConfig)) {
      throw new SecurityValidationError(400, 'Invalid searchConfig in credential vault payload.');
    }
    const search = obj.searchConfig as Record<string, unknown>;
    const provider = String(search.provider || '').trim().toLowerCase();
    const VALID_SEARCH_PROVIDERS = new Set(['duckduckgo', 'brave', 'brave_llm_context', 'custom']);
    if (provider && !VALID_SEARCH_PROVIDERS.has(provider)) {
      throw new SecurityValidationError(400, `Invalid search provider '${provider}' in credential vault.`);
    }

    const apiKey = typeof search.apiKey === 'string' ? search.apiKey.trim() : '';
    if (apiKey.length > 512) {
      throw new SecurityValidationError(400, 'Search API key exceeds maximum length (512 characters).');
    }

    const mode = (search.mode === 'on' || search.mode === 'off' ? search.mode : 'auto') as any;

    result.searchConfig = {
      ...(search as any),
      provider: (provider || 'duckduckgo') as any,
      apiKey,
      mode,
      sessionOnlyKey: Boolean(search.sessionOnlyKey),
    };
  }

  if (obj.renderConfig !== undefined) {
    if (!obj.renderConfig || typeof obj.renderConfig !== 'object' || Array.isArray(obj.renderConfig)) {
      throw new SecurityValidationError(400, 'Invalid renderConfig in credential vault payload.');
    }
    const render = obj.renderConfig as Record<string, unknown>;
    const apiKey = typeof render.apiKey === 'string' ? render.apiKey.trim() : '';
    if (apiKey.length > 256) {
      throw new SecurityValidationError(400, 'Render API key exceeds maximum length (256 characters).');
    }
    const ownerId = typeof render.ownerId === 'string' ? render.ownerId.trim().slice(0, 128) : '';
    const ownerName = typeof render.ownerName === 'string' ? render.ownerName.trim().slice(0, 128) : '';
    const ownerEmail = typeof render.ownerEmail === 'string' ? render.ownerEmail.trim().slice(0, 256) : undefined;
    const workspaceType = render.workspaceType === 'team' ? 'team' : 'user';
    const connectedAt = typeof render.connectedAt === 'string' ? render.connectedAt : new Date().toISOString();

    result.renderConfig = {
      apiKey,
      ownerId,
      ownerName,
      ownerEmail,
      workspaceType,
      connectedAt,
    };
  }

  return result;
}

export function deriveUserVaultKey(params: {
  uid: string;
  email: string;
  secretOverride?: string;
  secret?: string;
  isProduction?: boolean;
  runtimeProject?: string;
}): Buffer {
  const uid = (params.uid || '').trim();
  const normalizedEmail = (params.email || '').trim().toLowerCase();
  if (!uid || !normalizedEmail) {
    throw new SecurityValidationError(400, 'Verified account UID and email are required for credential vault operations.');
  }

  const isProd = params.isProduction !== undefined ? params.isProduction : (process.env.NODE_ENV === 'production');
  const rawSecret = params.secretOverride?.trim() || params.secret?.trim() || process.env.MIST_VAULT_SECRET?.trim();
  const effectiveSecret = assertValidVaultSecret(rawSecret, isProd);

  let runtimeProject = params.runtimeProject?.trim() || 'mist';
  if (!params.runtimeProject) {
    try {
      runtimeProject = getFirebaseProjectId();
    } catch {
      // Fallback for isolated test environments
    }
  }

  const derived = crypto.hkdfSync(
    'sha256',
    Buffer.from(effectiveSecret, 'utf8'),
    Buffer.from(`mist:${runtimeProject}:${uid}`, 'utf8'),
    Buffer.from(`mist-vault:${normalizedEmail}`, 'utf8'),
    32,
  );
  return Buffer.from(derived);
}

function makeVaultAad(uid: string, email: string): Buffer {
  return Buffer.from(`${uid.trim()}:${email.trim().toLowerCase()}:mist-vault-v1`, 'utf8');
}

export function sealUserVaultPayload(params: {
  uid: string;
  email: string;
  aiConfig?: AiProviderConfig;
  searchConfig?: WebSearchConfig;
  renderConfig?: RenderCredentialConfig;
  secretOverride?: string;
  isProduction?: boolean;
  runtimeProject?: string;
}): {
  encryptedPayload: string;
  aiKeyHint: string;
  searchKeyHint: string;
  renderKeyHint: string;
} {
  const validated = validateVaultPayload({
    aiConfig: params.aiConfig,
    searchConfig: params.searchConfig,
    renderConfig: params.renderConfig,
  });

  const key = deriveUserVaultKey({
    uid: params.uid,
    email: params.email,
    secretOverride: params.secretOverride,
    isProduction: params.isProduction,
    runtimeProject: params.runtimeProject,
  });

  // Session-only keys remain in memory only and are never saved to the account vault
  const cleanAi: AiProviderConfig | undefined = validated.aiConfig
    ? {
        ...validated.aiConfig,
        apiKey: validated.aiConfig.sessionOnlyKey ? '' : validated.aiConfig.apiKey || '',
      }
    : undefined;

  const cleanSearch: WebSearchConfig | undefined = validated.searchConfig
    ? {
        ...validated.searchConfig,
        apiKey: validated.searchConfig.sessionOnlyKey ? '' : validated.searchConfig.apiKey || '',
      }
    : undefined;

  const cleanRender: RenderCredentialConfig | undefined = validated.renderConfig
    ? {
        ...validated.renderConfig,
        apiKey: validated.renderConfig.apiKey || '',
      }
    : undefined;

  const plaintext = JSON.stringify({
    v: 1,
    email: params.email.trim().toLowerCase(),
    aiConfig: cleanAi,
    searchConfig: cleanSearch,
    renderConfig: cleanRender,
  });

  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  cipher.setAAD(makeVaultAad(params.uid, params.email));
  const encrypted = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
  const authTag = cipher.getAuthTag();

  const envelope = JSON.stringify({
    v: 1,
    iv: iv.toString('base64'),
    tag: authTag.toString('base64'),
    ct: encrypted.toString('base64'),
  });

  return {
    encryptedPayload: Buffer.from(envelope, 'utf8').toString('base64'),
    aiKeyHint: cleanAi?.apiKey ? maskApiKey(cleanAi.apiKey) : '',
    searchKeyHint: cleanSearch?.apiKey ? maskApiKey(cleanSearch.apiKey) : '',
    renderKeyHint: cleanRender?.apiKey ? maskApiKey(cleanRender.apiKey) : '',
  };
}

export interface UnsealVaultParams {
  uid: string;
  email: string;
  encryptedPayload: string;
  secretOverride?: string;
  previousSecrets?: string[];
  allowLegacyFallback?: boolean;
  isProduction?: boolean;
  runtimeProject?: string;
}

export function unsealUserVaultPayload(params: UnsealVaultParams): VaultPlainPayload {
  const uid = (params.uid || '').trim();
  const normalizedEmail = (params.email || '').trim().toLowerCase();
  if (!uid || !normalizedEmail) {
    throw new SecurityValidationError(400, 'Verified account UID and email are required for credential vault operations.');
  }

  if (!params.encryptedPayload || typeof params.encryptedPayload !== 'string') {
    throw new SecurityValidationError(400, 'Missing encrypted vault payload.');
  }

  const payloadStr = params.encryptedPayload.trim();
  if (payloadStr.length < 20 || payloadStr.length > 262144) {
    throw new SecurityValidationError(400, 'Malformed encrypted credential vault: payload length out of bounds.');
  }

  let parsedEnvelope: { v?: number; iv?: string; tag?: string; ct?: string };
  try {
    const rawJson = Buffer.from(payloadStr, 'base64').toString('utf8');
    parsedEnvelope = JSON.parse(rawJson) as { v?: number; iv?: string; tag?: string; ct?: string };
  } catch {
    throw new SecurityValidationError(400, 'Malformed encrypted credential vault.');
  }

  if (
    parsedEnvelope.v !== 1 ||
    typeof parsedEnvelope.iv !== 'string' ||
    typeof parsedEnvelope.tag !== 'string' ||
    typeof parsedEnvelope.ct !== 'string'
  ) {
    throw new SecurityValidationError(400, 'Unsupported credential vault format.');
  }

  const iv = Buffer.from(parsedEnvelope.iv, 'base64');
  const tag = Buffer.from(parsedEnvelope.tag, 'base64');
  const ct = Buffer.from(parsedEnvelope.ct, 'base64');

  if (iv.length !== 12) {
    throw new SecurityValidationError(400, 'Unsupported credential vault format: invalid IV length.');
  }
  if (tag.length !== 16) {
    throw new SecurityValidationError(400, 'Unsupported credential vault format: invalid authentication tag length.');
  }
  if (ct.length === 0) {
    throw new SecurityValidationError(400, 'Unsupported credential vault format: empty ciphertext.');
  }

  const isProd = params.isProduction !== undefined ? params.isProduction : (process.env.NODE_ENV === 'production');
  let runtimeProject = params.runtimeProject?.trim() || 'mist';
  if (!params.runtimeProject) {
    try {
      runtimeProject = getFirebaseProjectId();
    } catch {
      // fallback
    }
  }

  // Build candidate secrets:
  // 1. Primary current secret
  const primarySecret = assertValidVaultSecret(
    params.secretOverride?.trim() || process.env.MIST_VAULT_SECRET?.trim(),
    isProd,
  );

  const candidateSecrets: string[] = [primarySecret];

  // 2. Previous rotation secrets (support zero-downtime key rotation)
  if (params.previousSecrets && Array.isArray(params.previousSecrets)) {
    for (const s of params.previousSecrets) {
      if (typeof s === 'string' && s.trim()) candidateSecrets.push(s.trim());
    }
  } else if (process.env.MIST_VAULT_PREVIOUS_SECRETS) {
    const prevList = process.env.MIST_VAULT_PREVIOUS_SECRETS.split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    candidateSecrets.push(...prevList);
  }

  // 3. Legacy project ID fallback secret (enabled in dev or during explicit migration window)
  const allowLegacy =
    params.allowLegacyFallback === true ||
    (params.allowLegacyFallback !== false &&
      (!isProd || process.env.ALLOW_LEGACY_VAULT_MIGRATION === 'true'));
  if (allowLegacy) {
    const legacySecret = `${runtimeProject}:mist-account-vault-dev-only`;
    if (!candidateSecrets.includes(legacySecret)) {
      candidateSecrets.push(legacySecret);
    }
  }

  const aad = makeVaultAad(uid, normalizedEmail);

  for (let i = 0; i < candidateSecrets.length; i++) {
    const secret = candidateSecrets[i];
    try {
      const key = Buffer.from(
        crypto.hkdfSync(
          'sha256',
          Buffer.from(secret, 'utf8'),
          Buffer.from(`mist:${runtimeProject}:${uid}`, 'utf8'),
          Buffer.from(`mist-vault:${normalizedEmail}`, 'utf8'),
          32,
        ),
      );

      const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv);
      decipher.setAAD(aad);
      decipher.setAuthTag(tag);
      const plaintext = Buffer.concat([decipher.update(ct), decipher.final()]).toString('utf8');

      const data = JSON.parse(plaintext) as {
        email?: string;
        aiConfig?: AiProviderConfig;
        searchConfig?: WebSearchConfig;
        renderConfig?: RenderCredentialConfig;
      };

      if (data.email && data.email !== normalizedEmail) {
        throw new SecurityValidationError(403, 'Credential vault email does not match your signed-in Google account.');
      }

      const validated = validateVaultPayload({
        aiConfig: data.aiConfig,
        searchConfig: data.searchConfig,
        renderConfig: data.renderConfig,
      });

      return {
        aiConfig: validated.aiConfig,
        searchConfig: validated.searchConfig,
        renderConfig: validated.renderConfig,
        needsReencryption: i > 0, // Mark true if decrypted using an older rotation key or legacy fallback
      };
    } catch (err) {
      if (err instanceof SecurityValidationError) {
        throw err;
      }
      // GCM authentication failure -> try next candidate secret
      continue;
    }
  }

  throw new SecurityValidationError(403, 'Unable to decrypt credential vault for this Google account.');
}

export function migrateUserVaultCiphertext(params: {
  uid: string;
  email: string;
  ciphertext: string;
  newSecret?: string;
  previousSecrets?: string[];
  allowLegacyFallback?: boolean;
  isProduction?: boolean;
  runtimeProject?: string;
}): {
  newCiphertext: string;
  aiKeyHint: string;
  searchKeyHint: string;
  migrated: boolean;
} {
  const unsealed = unsealUserVaultPayload({
    uid: params.uid,
    email: params.email,
    encryptedPayload: params.ciphertext,
    secretOverride: params.newSecret,
    previousSecrets: params.previousSecrets,
    allowLegacyFallback: params.allowLegacyFallback,
    isProduction: params.isProduction,
    runtimeProject: params.runtimeProject,
  });

  if (unsealed.needsReencryption) {
    const resealed = sealUserVaultPayload({
      uid: params.uid,
      email: params.email,
      aiConfig: unsealed.aiConfig,
      searchConfig: unsealed.searchConfig,
      secretOverride: params.newSecret,
      isProduction: params.isProduction,
      runtimeProject: params.runtimeProject,
    });
    return {
      newCiphertext: resealed.encryptedPayload,
      aiKeyHint: resealed.aiKeyHint,
      searchKeyHint: resealed.searchKeyHint,
      migrated: true,
    };
  }

  return {
    newCiphertext: params.ciphertext,
    aiKeyHint: unsealed.aiConfig?.apiKey ? maskApiKey(unsealed.aiConfig.apiKey) : '',
    searchKeyHint: unsealed.searchConfig?.apiKey ? maskApiKey(unsealed.searchConfig.apiKey) : '',
    migrated: false,
  };
}

import { verifyToken as clerkVerifyToken } from '@clerk/express';

// --- 5. Clerk Auth Token Verification & Edge Origin Protection ---

let cachedProjectId: string | null = null;
export function getFirebaseProjectId(): string {
  if (cachedProjectId) return cachedProjectId;
  const configPath = path.resolve(process.cwd(), 'firebase-applet-config.json');
  if (fs.existsSync(configPath)) {
    const parsed = JSON.parse(fs.readFileSync(configPath, 'utf8')) as { projectId?: string };
    if (parsed.projectId) {
      cachedProjectId = parsed.projectId;
      return cachedProjectId;
    }
  }
  cachedProjectId = process.env.FIREBASE_PROJECT_ID || 'lithe-sensor-2v0ns';
  return cachedProjectId;
}

export function getFirebaseAppletConfig(): { projectId: string; firestoreDatabaseId: string } {
  const configPath = path.resolve(process.cwd(), 'firebase-applet-config.json');
  if (fs.existsSync(configPath)) {
    const parsed = JSON.parse(fs.readFileSync(configPath, 'utf8')) as {
      projectId?: string;
      firestoreDatabaseId?: string;
    };
    if (parsed.projectId) {
      return {
        projectId: parsed.projectId,
        firestoreDatabaseId: parsed.firestoreDatabaseId || '(default)',
      };
    }
  }
  return {
    projectId: process.env.FIREBASE_PROJECT_ID || 'lithe-sensor-2v0ns',
    firestoreDatabaseId: process.env.FIREBASE_DATABASE_ID || '(default)',
  };
}

export interface VerifiedClerkUser {
  userId: string;
  uid: string;
  email?: string;
  emailVerified: boolean;
  claims?: Record<string, unknown>;
  idToken?: string;
}

export type VerifiedFirebaseUser = VerifiedClerkUser;

export interface AuthenticatedRequest extends ExpressRequest {
  authUser?: VerifiedClerkUser;
}

export async function verifyClerkToken(
  token: string,
  options?: {
    secretKey?: string;
    jwtKey?: string;
    authorizedParties?: string[];
  },
): Promise<VerifiedClerkUser> {
  const secretKey = options?.secretKey || process.env.CLERK_SECRET_KEY;
  const authorizedParties =
    options?.authorizedParties ||
    (process.env.CLERK_AUTHORIZED_PARTIES
      ? process.env.CLERK_AUTHORIZED_PARTIES.split(',').map((s) => s.trim()).filter(Boolean)
      : undefined);

  if (!token) {
    throw new SecurityValidationError(401, 'Missing authentication token.');
  }

  try {
    const verified = await clerkVerifyToken(token, {
      secretKey,
      jwtKey: options?.jwtKey || process.env.CLERK_JWT_KEY,
      authorizedParties,
    });

    const sub = verified.sub;
    if (!sub || typeof sub !== 'string') {
      throw new SecurityValidationError(401, 'Authentication token missing subject.');
    }

    const claims = verified as Record<string, unknown>;
    const email =
      (typeof claims.email === 'string' && claims.email) ||
      (typeof claims.primary_email === 'string' && claims.primary_email) ||
      undefined;

    const emailVerified =
      claims.email_verified === true ||
      claims.email_verified === undefined;

    return {
      userId: sub,
      uid: sub,
      email,
      emailVerified,
      claims,
      idToken: token,
    };
  } catch (err) {
    if (err instanceof SecurityValidationError) throw err;
    const msg = err instanceof Error ? err.message : String(err);
    throw new SecurityValidationError(401, `Authentication failed: ${msg}`);
  }
}

export async function verifyClerkAuthHeader(
  authHeader?: string,
  options?: {
    secretKey?: string;
    jwtKey?: string;
    authorizedParties?: string[];
  },
): Promise<VerifiedClerkUser> {
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    throw new SecurityValidationError(401, 'Clerk authentication is required for this action.');
  }
  const token = authHeader.slice('Bearer '.length).trim();
  if (!token) {
    throw new SecurityValidationError(401, 'Missing authentication token.');
  }
  return verifyClerkToken(token, options);
}

export const verifyFirebaseAuthHeader = verifyClerkAuthHeader;

export function createClerkAuthMiddleware(options?: {
  requireVerifiedEmail?: boolean;
  verifyHeaderFn?: (header?: string) => Promise<VerifiedClerkUser>;
  authorizedParties?: string[];
  secretKey?: string;
}) {
  const verifyFn = options?.verifyHeaderFn || ((h) => verifyClerkAuthHeader(h, options));
  const requireEmailVerified = options?.requireVerifiedEmail !== false;

  return async (req: AuthenticatedRequest, res: ExpressResponse, next: NextFunction) => {
    try {
      const authUser = await verifyFn(req.headers.authorization);
      if (!authUser.userId) {
        authUser.userId = authUser.uid;
      }
      if (requireEmailVerified && authUser.emailVerified === false) {
        res.status(403).json({
          error: 'A verified account email is required for this action.',
        });
        return;
      }

      // Check server-side allowlists if configured in environment
      const allowedUserIds = (process.env.MIST_ALLOWED_USER_IDS || '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const allowedEmails = (process.env.MIST_ALLOWED_EMAILS || '')
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);

      if (allowedUserIds.length > 0 && !allowedUserIds.includes(authUser.userId)) {
        res.status(403).json({ error: 'Access denied: user ID is not authorized.' });
        return;
      }

      if (
        allowedEmails.length > 0 &&
        (!authUser.email || !allowedEmails.includes(authUser.email.toLowerCase()))
      ) {
        res.status(403).json({ error: 'Access denied: account email is not authorized.' });
        return;
      }

      req.authUser = authUser;
      next();
    } catch (err) {
      const status = err instanceof SecurityValidationError ? err.status : 401;
      res.status(status).json({ error: sanitizeErrorMessage(err) || 'Authentication required.' });
    }
  };
}

export const createFirebaseAuthMiddleware = createClerkAuthMiddleware;

export function createOptionalAuthMiddleware(options?: {
  verifyHeaderFn?: (header?: string) => Promise<VerifiedClerkUser>;
  authorizedParties?: string[];
  secretKey?: string;
}) {
  const verifyFn = options?.verifyHeaderFn || ((h) => verifyClerkAuthHeader(h, options));

  return async (req: AuthenticatedRequest, res: ExpressResponse, next: NextFunction) => {
    const authHeader = req.headers.authorization;
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return next();
    }
    try {
      const authUser = await verifyFn(authHeader);
      req.authUser = authUser;
      next();
    } catch (err) {
      const status = err instanceof SecurityValidationError ? err.status : 401;
      res.status(status).json({
        error: sanitizeErrorMessage(err) || 'Invalid authentication token.',
        code: 'UNAUTHORIZED',
        status,
      });
    }
  };
}

// --- 5B. Route-Specific Request Body Limits & JSON Body Error Handler ---

export const BODY_LIMITS = {
  SEARCH: 64 * 1024, // 64 KB
  NOTIFICATIONS: 32 * 1024, // 32 KB
  VAULT: 256 * 1024, // 256 KB
  AI_CONFIG: 64 * 1024, // 64 KB
  AI_SESSION: 64 * 1024, // 64 KB
  AI_PROMPT: 1.5 * 1024 * 1024, // 1.5 MB
  BUNDLE: 4 * 1024 * 1024, // 4 MB
  DEPLOYMENT: 4 * 1024 * 1024, // 4 MB
  PROJECT_SYNC: 6 * 1024 * 1024, // 6 MB
  DEFAULT: 256 * 1024, // 256 KB
};

export function createBodySizeLimitMiddleware(maxBytes: number, label = 'Request body') {
  return (req: ExpressRequest, res: ExpressResponse, next: NextFunction) => {
    const contentLength = req.headers['content-length'];
    if (contentLength) {
      const length = parseInt(contentLength, 10);
      if (!isNaN(length) && length > maxBytes) {
        res.status(413).json({
          error: `${label} exceeds maximum allowed size of ${Math.round(maxBytes / 1024)}KB.`,
          code: 'PAYLOAD_TOO_LARGE',
          status: 413,
        });
        return;
      }
    }
    if (req.body && typeof req.body === 'object') {
      try {
        const bodyStr = JSON.stringify(req.body);
        if (Buffer.byteLength(bodyStr, 'utf8') > maxBytes) {
          res.status(413).json({
            error: `${label} exceeds maximum allowed size of ${Math.round(maxBytes / 1024)}KB.`,
            code: 'PAYLOAD_TOO_LARGE',
            status: 413,
          });
          return;
        }
      } catch {
        // serialization ignored
      }
    }
    next();
  };
}

export function handleBodyParserErrors(
  err: unknown,
  _req: ExpressRequest,
  res: ExpressResponse,
  next: NextFunction,
) {
  if (err instanceof SyntaxError && (err as any).status === 400 && 'body' in err) {
    res.status(400).json({
      error: 'Malformed JSON payload in request body.',
      code: 'INVALID_JSON',
      status: 400,
    });
    return;
  }
  if ((err as any)?.type === 'entity.too.large' || (err as any)?.status === 413) {
    res.status(413).json({
      error: 'Request body exceeds maximum allowed size limit.',
      code: 'PAYLOAD_TOO_LARGE',
      status: 413,
    });
    return;
  }
  next(err);
}

// --- 5C. Deep Request Validation for AI & Search Configurations ---

export function validateAiProviderConfig(raw: unknown): AiProviderConfig {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new SecurityValidationError(400, 'Invalid providerConfig: expected an object.', 'INVALID_PAYLOAD');
  }

  const proto = Object.getPrototypeOf(raw);
  if (
    (proto !== Object.prototype && proto !== null) ||
    Object.prototype.hasOwnProperty.call(raw, '__proto__') ||
    Object.prototype.hasOwnProperty.call(raw, 'constructor') ||
    Object.prototype.hasOwnProperty.call(raw, 'prototype')
  ) {
    throw new SecurityValidationError(400, 'Invalid providerConfig: prototype properties are forbidden.', 'PROTOTYPE_POLLUTION');
  }

  const c = raw as Record<string, unknown>;
  const provider = typeof c.provider === 'string' ? c.provider.trim().toLowerCase() : '';
  const ALLOWED_PROVIDERS = new Set(['custom', 'openrouter', 'groq', 'gemini', 'openai', 'nvidia']);
  if (provider && !ALLOWED_PROVIDERS.has(provider)) {
    throw new SecurityValidationError(400, `Unsupported AI provider "${provider}".`, 'INVALID_PROVIDER');
  }

  if (typeof c.name === 'string' && c.name.length > 128) {
    throw new SecurityValidationError(400, 'Provider name exceeds maximum allowed length of 128 characters.', 'PAYLOAD_TOO_LARGE');
  }
  if (typeof c.model === 'string' && c.model.length > 128) {
    throw new SecurityValidationError(400, 'Model identifier exceeds maximum allowed length of 128 characters.', 'PAYLOAD_TOO_LARGE');
  }
  if (typeof c.apiKey === 'string' && c.apiKey.length > 512) {
    throw new SecurityValidationError(400, 'API key exceeds maximum allowed length of 512 characters.', 'PAYLOAD_TOO_LARGE');
  }
  if (typeof c.baseUrl === 'string' && c.baseUrl.length > 2048) {
    throw new SecurityValidationError(400, 'Base URL exceeds maximum allowed length of 2048 characters.', 'PAYLOAD_TOO_LARGE');
  }

  const name = typeof c.name === 'string' ? c.name.trim() : undefined;
  const model = typeof c.model === 'string' ? c.model.trim() : '';
  const apiKey = typeof c.apiKey === 'string' ? c.apiKey.trim() : '';
  const sessionOnlyKey = Boolean(c.sessionOnlyKey);

  let baseUrl = typeof c.baseUrl === 'string' && c.baseUrl.trim() ? c.baseUrl.trim() : undefined;
  if (baseUrl) {
    validateExternalUrlSyntax(baseUrl);
  }

  return {
    provider: (provider || 'custom') as any,
    name,
    model,
    apiKey,
    baseUrl,
    sessionOnlyKey,
  };
}

export function validateWebSearchConfig(raw: unknown): WebSearchConfig {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new SecurityValidationError(400, 'Invalid searchConfig: expected an object.', 'INVALID_PAYLOAD');
  }

  const proto = Object.getPrototypeOf(raw);
  if (
    (proto !== Object.prototype && proto !== null) ||
    Object.prototype.hasOwnProperty.call(raw, '__proto__') ||
    Object.prototype.hasOwnProperty.call(raw, 'constructor') ||
    Object.prototype.hasOwnProperty.call(raw, 'prototype')
  ) {
    throw new SecurityValidationError(400, 'Invalid searchConfig: prototype properties are forbidden.', 'PROTOTYPE_POLLUTION');
  }

  const c = raw as Record<string, unknown>;
  const provider = typeof c.provider === 'string' ? c.provider.trim().toLowerCase() : 'duckduckgo';
  const ALLOWED_SEARCH = new Set(['duckduckgo', 'brave_llm_context', 'brave_web', 'custom_json', 'brave', 'custom']);
  if (!ALLOWED_SEARCH.has(provider)) {
    throw new SecurityValidationError(400, `Unsupported web search provider "${provider}".`, 'INVALID_PROVIDER');
  }

  if (typeof c.name === 'string' && c.name.length > 128) {
    throw new SecurityValidationError(400, 'Search provider name exceeds maximum allowed length of 128 characters.', 'PAYLOAD_TOO_LARGE');
  }
  if (typeof c.apiKey === 'string' && c.apiKey.length > 512) {
    throw new SecurityValidationError(400, 'Search API key exceeds maximum allowed length of 512 characters.', 'PAYLOAD_TOO_LARGE');
  }
  if (typeof c.baseUrl === 'string' && c.baseUrl.length > 2048) {
    throw new SecurityValidationError(400, 'Search base URL exceeds maximum allowed length of 2048 characters.', 'PAYLOAD_TOO_LARGE');
  }

  const name = typeof c.name === 'string' ? c.name.trim() : undefined;
  const apiKey = typeof c.apiKey === 'string' ? c.apiKey.trim() : '';
  let baseUrl = typeof c.baseUrl === 'string' && c.baseUrl.trim() ? c.baseUrl.trim() : undefined;
  if (baseUrl) {
    validateExternalUrlSyntax(baseUrl);
  }

  return {
    provider: provider as any,
    name,
    apiKey,
    baseUrl,
    sessionOnlyKey: Boolean(c.sessionOnlyKey),
  };
}

export function sendSecurityErrorResponse(
  res: ExpressResponse,
  err: unknown,
  defaultStatus = 500,
): void {
  const status =
    err instanceof SecurityValidationError
      ? err.status
      : typeof (err as any)?.status === 'number'
        ? (err as any).status
        : defaultStatus;

  const code =
    err instanceof SecurityValidationError
      ? err.code
      : typeof (err as any)?.code === 'string'
        ? (err as any).code
        : status === 400
          ? 'BAD_REQUEST'
          : status === 401
            ? 'UNAUTHORIZED'
            : status === 403
              ? 'FORBIDDEN'
              : status === 404
                ? 'NOT_FOUND'
                : status === 413
                  ? 'PAYLOAD_TOO_LARGE'
                  : status === 429
                    ? 'RATE_LIMIT_EXCEEDED'
                    : 'INTERNAL_SERVER_ERROR';

  const message = sanitizeErrorMessage(err) || 'A security or server error occurred.';
  res.status(status).json({
    error: message,
    code,
    status,
  });
}

function isValidEdgeSecret(header: unknown, expected: string): boolean {
  if (typeof header !== 'string' || !header) return false;
  const bufHeader = Buffer.from(header, 'utf8');
  const bufExpected = Buffer.from(expected, 'utf8');
  if (bufHeader.length !== bufExpected.length) return false;
  return crypto.timingSafeEqual(bufHeader, bufExpected);
}

export function createEdgeOriginSecretMiddleware(options?: {
  expectedSecret?: string;
  isProduction?: boolean;
}) {
  const isProd = options?.isProduction ?? process.env.NODE_ENV === 'production';
  const expected = options?.expectedSecret ?? process.env.MIST_EDGE_ORIGIN_SECRET;
  if (isProd && !expected) {
    throw new Error('MIST_EDGE_ORIGIN_SECRET is mandatory in production to prevent direct origin bypass.');
  }

  return (req: ExpressRequest, res: ExpressResponse, next: NextFunction) => {
    if (!expected) {
      return next();
    }

    if (!isValidEdgeSecret(req.headers['x-mist-edge-secret'], expected)) {
      res.status(403).json({ error: 'Direct access to origin is prohibited. Requests must route via Cloudflare edge.' });
      return;
    }

    (req as any).isEdgeOriginVerified = true;
    next();
  };
}


// --- 6. Same-Origin / Cross-Site Mutation Defense ---

export interface OriginCheckContext {
  originHost: string;
  hostHeader: string;
  forwardedHost: string;
  isEdgeVerified: boolean;
}

export function isOriginAuthorized(ctx: OriginCheckContext): boolean {
  if (ctx.hostHeader && ctx.originHost === ctx.hostHeader) {
    return true;
  }
  if (ctx.isEdgeVerified) {
    if (ctx.forwardedHost && ctx.originHost === ctx.forwardedHost) {
      return true;
    }
  }
  return false;
}

function getForwardedHostHeader(req: ExpressRequest): string {
  const forwarded = req.headers['x-forwarded-host'];
  if (typeof forwarded === 'string' && forwarded) {
    return forwarded.split(',')[0].trim().toLowerCase();
  }
  return '';
}

export function enforceSameOriginOnMutations(
  req: ExpressRequest,
  res: ExpressResponse,
  next: NextFunction,
): void {
  const method = req.method.toUpperCase();
  if (method === 'GET' || method === 'HEAD' || method === 'OPTIONS') {
    return next();
  }

  const secFetchSite = String(req.headers['sec-fetch-site'] || '').toLowerCase();
  if (secFetchSite === 'cross-site') {
    res.status(403).json({ error: 'Cross-site mutating requests are blocked for security.' });
    return;
  }

  const originHeader = typeof req.headers.origin === 'string' ? req.headers.origin.trim() : '';
  if (!originHeader) {
    return next();
  }

  let originHost = '';
  try {
    originHost = new URL(originHeader).host.toLowerCase();
  } catch {
    res.status(403).json({ error: 'Invalid request Origin header.' });
    return;
  }

  const hostHeader = typeof req.headers.host === 'string' ? req.headers.host.trim().toLowerCase() : '';
  const forwardedHost = getForwardedHostHeader(req);
  const isEdgeVerified = Boolean((req as any).isEdgeOriginVerified);

  const isAllowed = isOriginAuthorized({
    originHost,
    hostHeader,
    forwardedHost,
    isEdgeVerified,
  });

  if (!isAllowed) {
    res.status(403).json({ error: 'Cross-origin mutating requests are blocked for security.' });
    return;
  }

  next();
}

// --- 7. Publishing Architecture & Origin Isolation Defense ---

export const BUILDER_CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://*.clerk.accounts.dev https://*.clerk.com https://challenges.cloudflare.com",
  "worker-src 'self' blob:",
  "style-src 'self' 'unsafe-inline' https:",
  "font-src 'self' data: https:",
  "img-src 'self' data: blob: https:",
  "connect-src 'self' https: wss:",
  "frame-src 'self' blob: data: https://challenges.cloudflare.com",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join('; ');

export const PUBLISHED_SITE_CSP = [
  "sandbox allow-scripts allow-forms allow-popups",
  "default-src 'unsafe-inline' 'unsafe-eval' data: blob: https:",
  "img-src * data: blob: https:",
  "media-src * data: blob: https:",
  "style-src * 'unsafe-inline'",
  "font-src * data: https:",
  "connect-src *",
  "object-src 'none'",
  "base-uri 'none'",
  "frame-ancestors 'none'",
].join('; ');

export function getEffectiveHost(req: ExpressRequest): string {
  const forwarded = req.headers['x-forwarded-host'];
  if (typeof forwarded === 'string' && forwarded.trim()) {
    return forwarded.split(',')[0].trim().toLowerCase();
  }
  return (req.headers.host || '').toLowerCase().trim();
}

export function isPublishingHostname(
  reqHost: string,
  publishBaseUrl?: string,
): { isPublishing: boolean; slug?: string } {
  if (!publishBaseUrl || !publishBaseUrl.trim() || !reqHost) {
    return { isPublishing: false };
  }
  const rawHost = reqHost.toLowerCase().trim();
  const cleanPublishBase = publishBaseUrl.trim();

  // 1. Wildcard subdomain pattern: e.g. https://*.mist-sites.com or https://*.mist.me
  if (cleanPublishBase.includes('*')) {
    try {
      const dummyUrl = new URL(cleanPublishBase.replace('*', 'dummy-slug'));
      const dummyHost = dummyUrl.host.toLowerCase();
      const suffix = dummyHost.replace(/^dummy-slug\./, '');
      const [rawHostWithoutPort, rawPort] = rawHost.split(':');
      const [suffixWithoutPort, suffixPort] = suffix.split(':');

      if (rawHostWithoutPort.endsWith(`.${suffixWithoutPort}`)) {
        if (!suffixPort || suffixPort === rawPort) {
          const slug = rawHostWithoutPort.slice(0, -(suffixWithoutPort.length + 1));
          if (slug && /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(slug)) {
            return { isPublishing: true, slug };
          }
        }
      }
    } catch {
      // fallback
    }
  } else {
    // 2. Dedicated single domain or port, e.g. https://sites.mist.me or http://localhost:3001 or http://published.localhost:3000
    try {
      const parsed = new URL(cleanPublishBase);
      const targetHost = parsed.host.toLowerCase();
      if (rawHost === targetHost) {
        return { isPublishing: true };
      }
      // Also match without port if testing or custom host
      if (
        rawHost.split(':')[0] === targetHost.split(':')[0] &&
        targetHost.split(':')[0] !== 'localhost' &&
        targetHost.split(':')[0] !== '127.0.0.1'
      ) {
        return { isPublishing: true };
      }
    } catch {
      if (rawHost === cleanPublishBase.toLowerCase()) {
        return { isPublishing: true };
      }
    }
  }

  return { isPublishing: false };
}

export function sanitizeSetCookieHeader(cookieStr: string): string {
  // Strips any parent-domain "Domain=..." attribute to force the cookie to be Host-Only.
  // RFC 6265 defines that cookies lacking a Domain attribute are strictly host-only and
  // are never shared with subdomains (e.g. *.mist.me).
  return cookieStr.replace(/;\s*Domain=[^;]+/gi, '');
}

export function enforceHostOnlyCookies(
  publishBaseUrl?: string,
): (req: ExpressRequest, res: ExpressResponse, next: NextFunction) => void {
  return (req: ExpressRequest, res: ExpressResponse, next: NextFunction) => {
    const hostHeader = getEffectiveHost(req);
    const { isPublishing } = isPublishingHostname(hostHeader, publishBaseUrl);

    const originalSetHeader = res.setHeader.bind(res);
    res.setHeader = function (name: string, value: any): ExpressResponse {
      if (typeof name === 'string' && name.toLowerCase() === 'set-cookie') {
        // If this request is served on the published website hostname, NEVER set cookies!
        if (isPublishing) {
          return res;
        }
        if (typeof value === 'string') {
          return originalSetHeader(name, sanitizeSetCookieHeader(value));
        }
        if (Array.isArray(value)) {
          const sanitized = value.map((c) =>
            typeof c === 'string' ? sanitizeSetCookieHeader(c) : c,
          );
          return originalSetHeader(name, sanitized);
        }
      }
      return originalSetHeader(name, value);
    };

    next();
  };
}

export function sendPublishedSiteHtml(res: ExpressResponse, htmlBundle: string): void {
  res.setHeader('Content-Security-Policy', PUBLISHED_SITE_CSP);
  res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  res.setHeader('Cache-Control', 'public, max-age=60, s-maxage=300');
  res.removeHeader('Set-Cookie');
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.send(htmlBundle);
}

