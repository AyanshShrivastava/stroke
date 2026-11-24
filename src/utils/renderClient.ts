/**
 * Official Render REST API Client for Mist
 *
 * Implements real "Connect to Render" static-site service provisioning,
 * deployment status tracking, credential verification, and workspace discovery.
 *
 * API Reference: https://api.render.com/v1
 * Authentication: Authorization: Bearer rnd_...
 */

import { SecurityValidationError, sanitizeErrorMessage } from './serverSecurity';

export interface RenderOwner {
  id: string;
  name: string;
  email?: string;
  type: 'user' | 'team';
}

export interface RenderVerificationResult {
  primaryOwner: RenderOwner;
  owners: RenderOwner[];
}

export interface RenderCreateStaticSiteParams {
  name: string;
  ownerId: string;
  repo: string;
  branch?: string;
  buildCommand?: string;
  publishPath?: string;
  autoDeploy?: 'commit' | 'checksPass' | 'off';
}

export interface RenderServiceSummary {
  id: string;
  name: string;
  ownerId: string;
  repo: string;
  branch: string;
  url: string;
  dashboardUrl: string;
  status: string;
  createdAt: string;
  updatedAt: string;
  serviceDetails?: {
    buildCommand?: string;
    publishPath?: string;
    url?: string;
  };
}

export interface RenderDeploySummary {
  id: string;
  status: 'created' | 'build_in_progress' | 'live' | 'build_failed' | 'canceled' | 'deactivated';
  finishedAt?: string;
  createdAt: string;
  commit?: { id?: string; message?: string };
}

const RENDER_API_BASE = 'https://api.render.com/v1';

/**
 * Validates a user-supplied Render API key.
 * Render API keys start with rnd_ and are 32-128 alphanumeric characters.
 */
export function validateRenderApiKey(rawKey: unknown): string {
  if (typeof rawKey !== 'string') {
    throw new SecurityValidationError(400, 'Render API key must be a string.', 'INVALID_RENDER_KEY');
  }
  const trimmed = rawKey.trim();
  if (!trimmed) {
    throw new SecurityValidationError(400, 'Render API key cannot be empty.', 'INVALID_RENDER_KEY');
  }
  if (trimmed.length < 20 || trimmed.length > 128) {
    throw new SecurityValidationError(
      400,
      'Invalid Render API key length (expected 20-128 characters).',
      'INVALID_RENDER_KEY',
    );
  }
  if (!/^rnd_[A-Za-z0-9_-]+$/.test(trimmed)) {
    throw new SecurityValidationError(
      400,
      "Invalid Render API key format. Render API keys start with 'rnd_' followed by alphanumeric characters.",
      'INVALID_RENDER_KEY',
    );
  }
  return trimmed;
}

/**
 * Validates a GitHub repository URL.
 * Accepts: https://github.com/owner/repo or https://github.com/owner/repo.git
 */
export function validateGitHubRepoUrl(rawRepo: unknown): { url: string; owner: string; repo: string } {
  if (typeof rawRepo !== 'string') {
    throw new SecurityValidationError(400, 'GitHub repository URL must be a string.', 'INVALID_REPO_URL');
  }
  const trimmed = rawRepo.trim();
  if (!trimmed) {
    throw new SecurityValidationError(400, 'GitHub repository URL cannot be empty.', 'INVALID_REPO_URL');
  }

  // Must match standard GitHub HTTPS repo URL pattern
  const match = trimmed.match(/^https:\/\/github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git|\/)?$/);
  if (!match) {
    throw new SecurityValidationError(
      400,
      'Invalid GitHub repository URL. Must be in the format: https://github.com/username/repository',
      'INVALID_REPO_URL',
    );
  }

  const owner = match[1]!;
  const repo = match[2]!;
  const canonicalUrl = `https://github.com/${owner}/${repo}`;

  return { url: canonicalUrl, owner, repo };
}

/**
 * Normalizes and validates a Render service name.
 * Render requires service names to be 3-63 lowercase alphanumeric characters or hyphens.
 */
export function validateRenderServiceName(rawName: unknown): string {
  if (typeof rawName !== 'string') {
    throw new SecurityValidationError(400, 'Service name must be a string.', 'INVALID_SERVICE_NAME');
  }
  const cleaned = rawName
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/^-+|-+$/g, '');

  if (cleaned.length < 3 || cleaned.length > 63) {
    throw new SecurityValidationError(
      400,
      'Service name must be between 3 and 63 alphanumeric characters or hyphens.',
      'INVALID_SERVICE_NAME',
    );
  }
  if (cleaned.includes('--')) {
    throw new SecurityValidationError(400, 'Service name cannot contain consecutive hyphens.', 'INVALID_SERVICE_NAME');
  }
  return cleaned;
}

const REPO_ACCESS_ERROR_RE = /repository not found|access denied|not have permission|unable to access|repo/i;
const CONFLICT_ERROR_RE = /already exists|taken/i;

function validateServiceId(serviceId: unknown): string {
  if (typeof serviceId !== 'string' || !serviceId.trim()) {
    throw new SecurityValidationError(400, 'Service ID is required.');
  }
  return serviceId.trim();
}

/**
 * Helper to normalize a single owner entry from Render API responses.
 */
function normalizeOwnerItem(item: unknown): RenderOwner | null {
  if (!item || typeof item !== 'object') return null;
  const o = (item as any).owner || item;
  if (!o || typeof o !== 'object') return null;
  const id = typeof o.id === 'string' ? o.id.trim() : '';
  const name = typeof o.name === 'string' ? o.name.trim() : '';
  if (!id || !name) return null;
  return {
    id,
    name,
    email: typeof o.email === 'string' ? o.email.trim() : undefined,
    type: o.type === 'team' ? 'team' : 'user',
  };
}

/**
 * Helper to normalize owners from Render API responses.
 * Render /v1/owners returns an array of items where each item is either
 * `{ owner: { id, name, email, type } }` or directly `{ id, name, email, type }`.
 */
function parseOwnersResponse(raw: unknown): RenderOwner[] {
  if (!Array.isArray(raw)) return [];
  const list: RenderOwner[] = [];
  for (const item of raw) {
    const owner = normalizeOwnerItem(item);
    if (owner) list.push(owner);
  }
  return list;
}

/**
 * Handles fetch network or abort errors for Render API calls.
 */
function handleRenderFetchError(err: any, actionLabel: string): never {
  if (err?.name === 'AbortError') {
    throw new SecurityValidationError(499, `Render ${actionLabel} request was canceled.`, 'REQUEST_CANCELED');
  }
  throw new SecurityValidationError(
    502,
    `Unable to reach Render API: ${sanitizeErrorMessage(err)}`,
    'RENDER_NETWORK_ERROR',
  );
}

/**
 * Extracts error text from a Render API response safely.
 */
async function extractRenderErrorMessage(response: Response): Promise<string> {
  try {
    const errJson = await response.json();
    return (errJson as any)?.message || JSON.stringify(errJson);
  } catch {
    return response.statusText;
  }
}

/**
 * Checks for known Render error patterns like repo access or service name collisions.
 */
function checkSpecificRenderErrors(
  errorDetail: string,
  context?: { repoUrl?: string; serviceName?: string },
): void {
  if (context?.repoUrl && REPO_ACCESS_ERROR_RE.test(errorDetail)) {
    throw new SecurityValidationError(
      400,
      `Render could not access the GitHub repository "${context.repoUrl}". If the repository is private, please ensure the Render GitHub App (https://github.com/apps/render/installations/new) is installed and granted access to this repository in your Render account.`,
      'GITHUB_REPO_UNAVAILABLE',
    );
  }

  if (context?.serviceName && CONFLICT_ERROR_RE.test(errorDetail)) {
    throw new SecurityValidationError(
      400,
      `A Render service named "${context.serviceName}" already exists in your workspace. Please choose a different service name.`,
      'SERVICE_NAME_CONFLICT',
    );
  }
}

/**
 * Handles non-OK HTTP responses from the Render API.
 */
async function handleRenderHttpError(
  response: Response,
  actionLabel: string,
  context?: { repoUrl?: string; serviceName?: string },
): Promise<never> {
  const status = response.status;
  if (status === 401 || status === 403) {
    throw new SecurityValidationError(
      401,
      'Invalid, expired, or unauthorized Render API key. Please generate a new API key from your Render account settings.',
      'RENDER_AUTH_FAILED',
    );
  }

  if (status === 429) {
    const retryAfter = response.headers.get('retry-after') || '60';
    throw new SecurityValidationError(
      429,
      `Render API rate limit exceeded. Please wait ${retryAfter}s and try again.`,
      'RENDER_RATE_LIMITED',
    );
  }

  const errorDetail = await extractRenderErrorMessage(response);
  checkSpecificRenderErrors(errorDetail, context);

  const code = actionLabel === 'service creation' ? 'RENDER_SERVICE_CREATION_FAILED' : 'RENDER_API_ERROR';
  throw new SecurityValidationError(
    status,
    `Render API ${actionLabel} error (${status}): ${errorDetail}`,
    code,
  );
}

function resolveServiceUrl(service: any, defaultName: string): string {
  const detailsUrl = service.serviceDetails && service.serviceDetails.url;
  if (detailsUrl) return detailsUrl;
  if (service.url) return service.url;
  return `https://${defaultName}.onrender.com`;
}

/**
 * Maps raw Render API service payload to RenderServiceSummary.
 */
function parseRenderServiceSummary(
  data: any,
  fallback: { name: string; ownerId: string; repo: string; branch?: string },
): RenderServiceSummary {
  const service = data?.service || data || {};
  const serviceId = service.id || 'unknown';
  const name = service.name || fallback.name;
  const serviceUrl = resolveServiceUrl(service, name);

  return {
    id: serviceId,
    name,
    ownerId: service.ownerId || fallback.ownerId,
    repo: service.repo || fallback.repo,
    branch: service.branch || fallback.branch || 'main',
    url: serviceUrl,
    dashboardUrl: `https://dashboard.render.com/static/${serviceId}`,
    status: service.status || 'created',
    createdAt: service.createdAt || new Date().toISOString(),
    updatedAt: service.updatedAt || new Date().toISOString(),
    serviceDetails: service.serviceDetails,
  };
}

/**
 * Builds static site service creation payload.
 */
function buildRenderStaticSitePayload(
  params: RenderCreateStaticSiteParams,
  validatedName: string,
  repoUrl: string,
) {
  return {
    type: 'static_site',
    name: validatedName,
    ownerId: params.ownerId.trim(),
    repo: repoUrl,
    branch: (params.branch || 'main').trim(),
    autoDeployTrigger: params.autoDeploy || 'commit',
    serviceDetails: {
      buildCommand: (params.buildCommand || 'npm run build').trim(),
      publishPath: (params.publishPath || 'dist').trim(),
    },
  };
}

/**
 * Verifies a Render API key against the official Render API (GET /v1/owners).
 */
export async function verifyRenderApiKey(
  apiKey: string,
  options?: { fetchImpl?: typeof fetch; signal?: AbortSignal },
): Promise<RenderVerificationResult> {
  const fetchFn = options?.fetchImpl || globalThis.fetch;
  const validatedKey = validateRenderApiKey(apiKey);

  let response: Response;
  try {
    response = await fetchFn(`${RENDER_API_BASE}/owners?limit=20`, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${validatedKey}`,
      },
      signal: options?.signal,
    });
  } catch (err: any) {
    handleRenderFetchError(err, 'verification');
  }

  if (!response.ok) {
    await handleRenderHttpError(response, 'verification');
  }

  const rawJson = await response.json();
  const owners = parseOwnersResponse(rawJson);

  if (owners.length === 0) {
    throw new SecurityValidationError(
      400,
      'Render API key is valid, but no workspaces or owners were found for this account.',
      'NO_WORKSPACES_FOUND',
    );
  }

  return {
    primaryOwner: owners[0]!,
    owners,
  };
}

/**
 * Creates a static site service on Render using the official Render REST API.
 */
export async function createRenderStaticSite(
  apiKey: string,
  params: RenderCreateStaticSiteParams,
  options?: { fetchImpl?: typeof fetch; signal?: AbortSignal },
): Promise<RenderServiceSummary> {
  const fetchFn = options?.fetchImpl || globalThis.fetch;
  const validatedKey = validateRenderApiKey(apiKey);
  const validatedRepo = validateGitHubRepoUrl(params.repo);
  const validatedName = validateRenderServiceName(params.name);

  if (!params.ownerId || typeof params.ownerId !== 'string') {
    throw new SecurityValidationError(400, 'Render ownerId / workspace ID is required.', 'INVALID_OWNER_ID');
  }

  const requestBody = buildRenderStaticSitePayload(params, validatedName, validatedRepo.url);

  let response: Response;
  try {
    response = await fetchFn(`${RENDER_API_BASE}/services`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        Authorization: `Bearer ${validatedKey}`,
      },
      body: JSON.stringify(requestBody),
      signal: options?.signal,
    });
  } catch (err: any) {
    handleRenderFetchError(err, 'deploy');
  }

  if (!response.ok) {
    await handleRenderHttpError(response, 'service creation', {
      repoUrl: validatedRepo.url,
      serviceName: validatedName,
    });
  }

  const rawData = await response.json();
  return parseRenderServiceSummary(rawData, {
    name: validatedName,
    ownerId: params.ownerId,
    repo: validatedRepo.url,
    branch: params.branch,
  });
}

/**
 * Retrieves details for a specific Render service.
 */
export async function getRenderService(
  apiKey: string,
  serviceId: string,
  options?: { fetchImpl?: typeof fetch; signal?: AbortSignal },
): Promise<RenderServiceSummary> {
  const fetchFn = options?.fetchImpl || globalThis.fetch;
  const validatedKey = validateRenderApiKey(apiKey);
  const cleanId = validateServiceId(serviceId);

  const response = await fetchFn(`${RENDER_API_BASE}/services/${cleanId}`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${validatedKey}`,
    },
    signal: options?.signal,
  });

  if (response.status === 404) {
    throw new SecurityValidationError(404, `Render service '${cleanId}' was not found.`, 'SERVICE_NOT_FOUND');
  }

  if (!response.ok) {
    throw new SecurityValidationError(response.status, `Failed to load Render service: ${response.statusText}`);
  }

  const s = (await response.json()) as any;
  return parseRenderServiceSummary(s, {
    name: 'unknown',
    ownerId: '',
    repo: '',
  });
}

/**
 * Retrieves the latest deployment status for a Render service.
 */
export async function getRenderLatestDeploy(
  apiKey: string,
  serviceId: string,
  options?: { fetchImpl?: typeof fetch; signal?: AbortSignal },
): Promise<RenderDeploySummary | null> {
  const fetchFn = options?.fetchImpl || globalThis.fetch;
  const validatedKey = validateRenderApiKey(apiKey);
  const cleanId = validateServiceId(serviceId);

  const response = await fetchFn(`${RENDER_API_BASE}/services/${cleanId}/deploys?limit=1`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${validatedKey}`,
    },
    signal: options?.signal,
  });

  if (!response.ok) return null;

  const data = (await response.json()) as any;
  const deploys = Array.isArray(data) ? data : data.deploys || [];
  if (deploys.length === 0) return null;

  const raw = deploys[0].deploy || deploys[0];
  return {
    id: raw.id,
    status: raw.status || 'created',
    createdAt: raw.createdAt,
    finishedAt: raw.finishedAt,
    commit: raw.commit,
  };
}

/**
 * Triggers a manual deployment for an existing Render service.
 */
export async function triggerRenderDeploy(
  apiKey: string,
  serviceId: string,
  options?: { clearCache?: boolean; fetchImpl?: typeof fetch; signal?: AbortSignal },
): Promise<{ id: string; status: string }> {
  const fetchFn = options?.fetchImpl || globalThis.fetch;
  const validatedKey = validateRenderApiKey(apiKey);
  const cleanId = validateServiceId(serviceId);

  const response = await fetchFn(`${RENDER_API_BASE}/services/${cleanId}/deploys`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      Authorization: `Bearer ${validatedKey}`,
    },
    body: JSON.stringify({
      clearCache: options?.clearCache ? 'clear' : 'do_not_clear',
    }),
    signal: options?.signal,
  });

  if (!response.ok) {
    throw new SecurityValidationError(response.status, `Failed to trigger Render deploy: ${response.statusText}`);
  }

  const d = (await response.json()) as any;
  const dep = d.deploy || d;
  return {
    id: dep.id,
    status: dep.status || 'created',
  };
}

function parseRenderServiceItem(item: any): RenderServiceSummary {
  return parseRenderServiceSummary(item, {
    name: 'unknown',
    ownerId: '',
    repo: '',
    branch: 'main',
  });
}

/**
 * Lists static site services in the user's Render workspace.
 */
export async function listRenderStaticSites(
  apiKey: string,
  options?: { ownerId?: string; limit?: number; fetchImpl?: typeof fetch; signal?: AbortSignal },
): Promise<RenderServiceSummary[]> {
  const fetchFn = options?.fetchImpl || globalThis.fetch;
  const validatedKey = validateRenderApiKey(apiKey);
  const limit = options?.limit || 20;

  let url = `${RENDER_API_BASE}/services?type=static_site&limit=${limit}`;
  if (options?.ownerId) {
    url += `&ownerId=${encodeURIComponent(options.ownerId)}`;
  }

  const response = await fetchFn(url, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${validatedKey}`,
    },
    signal: options?.signal,
  });

  if (!response.ok) {
    throw new SecurityValidationError(response.status, `Failed to list Render services: ${response.statusText}`);
  }

  const data = (await response.json()) as any;
  const services = Array.isArray(data) ? data : data.services || [];
  return services.map(parseRenderServiceItem);
}
