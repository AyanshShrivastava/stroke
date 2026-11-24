import type {
  ChatMessage,
  MistProject,
  ProjectFile,
  WebSearchConfig,
  AiProviderConfig,
} from '../types/mist';
import type { UserProfilePreferences, UserCredentialVaultDoc } from '../firebase/client';
import type { DeploymentSummary, StoredDeployment } from './deploymentStore';

export type TokenProvider = () => Promise<string | null>;

let globalTokenProvider: TokenProvider = async () => null;

export function setApiTokenProvider(provider: TokenProvider): void {
  globalTokenProvider = provider;
}

export async function getAuthHeaders(explicitToken?: string | null): Promise<HeadersInit> {
  const token = explicitToken ?? (await globalTokenProvider());
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

export class ApiError extends Error {
  status: number;
  data?: unknown;
  constructor(status: number, message: string, data?: unknown) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const authHeaders = await getAuthHeaders(token);
  const headers = {
    ...authHeaders,
    ...(options.headers || {}),
  };

  const response = await fetch(endpoint, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errMessage = `API request failed (${response.status})`;
    let errData: unknown;
    try {
      const body = await response.json();
      errData = body;
      if (body && typeof body.error === 'string') {
        errMessage = body.error;
      }
    } catch {
      // not JSON
    }
    throw new ApiError(response.status, errMessage, errData);
  }

  return response.json() as Promise<T>;
}

export const mistApi = {
  // User Preferences
  async getPreferences(token?: string | null): Promise<UserProfilePreferences | null> {
    const res = await apiFetch<{ preferences: UserProfilePreferences }>('/api/user/preferences', { method: 'GET' }, token);
    return res.preferences || null;
  },

  async updatePreferences(
    preferences: UserProfilePreferences,
    meta?: { email?: string; displayName?: string; photoURL?: string },
    token?: string | null,
  ): Promise<void> {
    await apiFetch<{ success: boolean }>(
      '/api/user/preferences',
      {
        method: 'PUT',
        body: JSON.stringify({ preferences, meta }),
      },
      token,
    );
  },

  // Credential Vault
  async getVault(token?: string | null): Promise<UserCredentialVaultDoc | null> {
    const res = await apiFetch<{ vault: UserCredentialVaultDoc | null }>('/api/user/vault', { method: 'GET' }, token);
    return res.vault;
  },

  async sealVault(
    payload: { ai?: AiProviderConfig; search?: WebSearchConfig },
    token?: string | null,
  ): Promise<{ ciphertext: string; aiKeyHint?: string; searchKeyHint?: string }> {
    return apiFetch<{ ciphertext: string; aiKeyHint?: string; searchKeyHint?: string }>(
      '/api/user/vault/seal',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
      token,
    );
  },

  async unsealVault(
    ciphertext: string,
    token?: string | null,
  ): Promise<{ ai?: AiProviderConfig; search?: WebSearchConfig }> {
    return apiFetch<{ ai?: AiProviderConfig; search?: WebSearchConfig }>(
      '/api/user/vault/unseal',
      {
        method: 'POST',
        body: JSON.stringify({ ciphertext }),
      },
      token,
    );
  },

  async clearVault(token?: string | null): Promise<void> {
    await apiFetch<{ success: boolean }>('/api/user/vault', { method: 'DELETE' }, token);
  },

  // Render Hosting Integration
  async getRenderStatus(token?: string | null): Promise<{
    connected: boolean;
    owner?: { id: string; name: string; email?: string; type: 'user' | 'team' };
    keyHint?: string;
    connectedAt?: string;
  }> {
    return apiFetch('/api/render/status', { method: 'GET' }, token);
  },

  async connectRender(
    apiKey: string,
    token?: string | null,
  ): Promise<{
    ok: boolean;
    connected: boolean;
    owner: { id: string; name: string; email?: string; type: 'user' | 'team' };
    workspaces: Array<{ id: string; name: string; email?: string; type: 'user' | 'team' }>;
    keyHint: string;
    connectedAt: string;
  }> {
    return apiFetch(
      '/api/render/connect',
      {
        method: 'POST',
        body: JSON.stringify({ apiKey }),
      },
      token,
    );
  },

  async disconnectRender(token?: string | null): Promise<{ ok: boolean; connected: boolean }> {
    return apiFetch('/api/render/disconnect', { method: 'POST' }, token);
  },

  async getRenderWorkspaces(token?: string | null): Promise<{
    primaryOwner: { id: string; name: string; email?: string; type: 'user' | 'team' };
    workspaces: Array<{ id: string; name: string; email?: string; type: 'user' | 'team' }>;
  }> {
    return apiFetch('/api/render/workspaces', { method: 'GET' }, token);
  },

  async deployToRender(
    params: {
      repoUrl: string;
      branch?: string;
      serviceName?: string;
      ownerId?: string;
      buildCommand?: string;
      publishPath?: string;
      autoDeploy?: 'commit' | 'checksPass' | 'off';
    },
    token?: string | null,
  ): Promise<{
    ok: boolean;
    service: {
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
    };
    deploy?: { id: string; status: string } | null;
  }> {
    return apiFetch(
      '/api/render/deploy',
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      token,
    );
  },

  async getRenderService(
    serviceId: string,
    token?: string | null,
  ): Promise<{
    service: {
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
    };
    latestDeploy?: {
      id: string;
      status: string;
      createdAt: string;
      finishedAt?: string;
      commit?: { id?: string; message?: string };
    } | null;
  }> {
    return apiFetch(`/api/render/services/${encodeURIComponent(serviceId)}`, { method: 'GET' }, token);
  },

  // Projects CRUD
  async listProjects(token?: string | null): Promise<MistProject[]> {
    const res = await apiFetch<{ projects: MistProject[] }>('/api/projects', { method: 'GET' }, token);
    return res.projects || [];
  },

  async getProject(projectId: string, token?: string | null): Promise<MistProject | null> {
    const res = await apiFetch<{ project: MistProject }>(`/api/projects/${encodeURIComponent(projectId)}`, { method: 'GET' }, token);
    return res.project;
  },

  async createProject(project: MistProject, token?: string | null): Promise<MistProject> {
    const res = await apiFetch<{ project: MistProject }>(
      '/api/projects',
      {
        method: 'POST',
        body: JSON.stringify({ project }),
      },
      token,
    );
    return res.project;
  },

  async updateProject(project: MistProject, token?: string | null): Promise<MistProject> {
    const res = await apiFetch<{ project: MistProject }>(
      `/api/projects/${encodeURIComponent(project.id)}`,
      {
        method: 'PUT',
        body: JSON.stringify({ project }),
      },
      token,
    );
    return res.project;
  },

  async deleteProject(projectId: string, token?: string | null): Promise<void> {
    await apiFetch<{ success: boolean }>(`/api/projects/${encodeURIComponent(projectId)}`, { method: 'DELETE' }, token);
  },

  async syncProjects(
    projects: MistProject[],
    token?: string | null,
  ): Promise<{
    synced: number;
    successfulProjectIds?: string[];
    failedProjects?: Array<{ id: string; error: string }>;
  }> {
    return apiFetch<{
      synced: number;
      successfulProjectIds?: string[];
      failedProjects?: Array<{ id: string; error: string }>;
    }>(
      '/api/projects/sync',
      {
        method: 'POST',
        body: JSON.stringify({ projects }),
      },
      token,
    );
  },

  // Deployments
  async listDeployments(token?: string | null): Promise<DeploymentSummary[]> {
    const res = await apiFetch<{ deployments: DeploymentSummary[] }>('/api/deployments', { method: 'GET' }, token);
    return res.deployments || [];
  },

  async deployWebsite(
    params: {
      slug: string;
      projectId: string;
      title: string;
      files: ProjectFile[];
      enableAppAi?: boolean;
    },
    token?: string | null,
  ): Promise<StoredDeployment & { url: string }> {
    return apiFetch<StoredDeployment & { url: string }>(
      '/api/deployments',
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      token,
    );
  },

  async deleteDeployment(slug: string, token?: string | null): Promise<void> {
    await apiFetch<{ ok: boolean }>(`/api/deployments/${encodeURIComponent(slug)}`, { method: 'DELETE' }, token);
  },
};
