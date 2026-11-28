import type {
  AiProviderConfig,
  AiProviderId,
  AppAiMode,
  CatalogSource,
  ModelBilling,
  ModelCapabilities,
  ModelLifecycleStatus,
} from '../types/mist';

export interface ModelCatalogItem {
  id: string;
  label: string;
  summary: string;
  tier: 'Default' | 'Fast' | 'Reasoning' | 'Pro' | 'Coding';
  billing: ModelBilling;
  billingLabel: string;
  status: ModelLifecycleStatus;
  capabilities: ModelCapabilities;
  contextLength?: number;
  pricingSummary?: string;
  isLiveFetched?: boolean;
  modality?: string;
  supportedMethods?: string[];
}

export type CustomGatewayId = 'openrouter' | 'groq' | 'gemini_byok' | 'nvidia' | 'openai' | 'custom_url';

export interface CustomGatewayPreset {
  id: CustomGatewayId;
  name: string;
  baseUrl: string;
  portalLabel?: string;
  portalUrl?: string;
  placeholder: string;
  steps?: string[];
  models: ModelCatalogItem[];
}

export const UNKNOWN_CAPABILITIES: ModelCapabilities = {
  textGeneration: true,
  jsonOutput: 'unknown',
  streaming: 'unknown',
  imageInput: 'unknown',
  toolCalling: 'unknown',
};

export function createManualModelEntry(modelId: string): ModelCatalogItem {
  return {
    id: modelId,
    label: modelId,
    summary: 'Manually entered model ID — unverified until tested against the provider endpoint.',
    tier: 'Default',
    billing: 'unknown',
    billingLabel: 'Unknown',
    status: 'unverified',
    capabilities: { ...UNKNOWN_CAPABILITIES },
    isLiveFetched: false,
  };
}

export const DEFAULT_BYOK_CONFIG: AiProviderConfig = {
  provider: 'custom',
  name: 'OpenRouter',
  baseUrl: 'https://openrouter.ai/api/v1',
  model: 'openrouter/free',
  apiKey: '',
  sessionOnlyKey: false,
};

export const CUSTOM_GATEWAY_PRESETS: CustomGatewayPreset[] = [
  {
    id: 'openrouter',
    name: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    portalLabel: 'openrouter.ai/keys',
    portalUrl: 'https://openrouter.ai/keys',
    placeholder: 'sk-or-v1-...',
    steps: [
      'Open openrouter.ai/keys and sign in to your OpenRouter account.',
      'Click Create Key and paste your sk-or-... BYOK key below.',
      'Select from the live OpenRouter /models catalog (automatically fetched with actual pricing and capabilities).',
    ],
    models: [
      {
        id: 'openrouter/free',
        label: 'OpenRouter Free Auto-Router',
        summary: 'Fallback auto-router — refresh live catalog to inspect current free & paid models.',
        tier: 'Default',
        billing: 'free',
        billingLabel: 'Free',
        status: 'active',
        capabilities: {
          textGeneration: true,
          jsonOutput: 'unknown',
          streaming: true,
          imageInput: 'unknown',
          toolCalling: 'unknown',
        },
        pricingSummary: '$0 / Free',
      },
    ],
  },
  {
    id: 'groq',
    name: 'Groq',
    baseUrl: 'https://api.groq.com/openai/v1',
    portalLabel: 'console.groq.com/keys',
    portalUrl: 'https://console.groq.com/keys',
    placeholder: 'gsk_...',
    steps: [
      'Sign in at console.groq.com/keys with your Groq account.',
      'Click Create API Key and paste the key starting with gsk_ below.',
      'Mist fetches your active models live from /openai/v1/models (billing follows your Groq plan).',
    ],
    models: [],
  },
  {
    id: 'gemini_byok',
    name: 'Gemini (BYOK)',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    portalLabel: 'aistudio.google.com/apikey',
    portalUrl: 'https://aistudio.google.com/apikey',
    placeholder: 'AIza...',
    steps: [
      'Open Google AI Studio (aistudio.google.com/apikey) and create your own Gemini API key.',
      'Paste your AIza... key below to load current Gemini models directly from Google /v1beta/models.',
      'You can also enter any valid Gemini model ID manually (e.g. gemini-4-hydrogen) and test it directly.',
    ],
    models: [],
  },
  {
    id: 'nvidia',
    name: 'NVIDIA NIM',
    baseUrl: 'https://integrate.api.nvidia.com/v1',
    portalLabel: 'build.nvidia.com',
    portalUrl: 'https://build.nvidia.com/explore/discover',
    placeholder: 'nvapi-...',
    steps: [
      'Visit build.nvidia.com and sign in to NVIDIA Developer.',
      'Click Get API Key and copy your nvapi- key.',
      'Mist queries the live NVIDIA /models catalog when your key is present (provider billed).',
    ],
    models: [],
  },
  {
    id: 'openai',
    name: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    portalLabel: 'platform.openai.com/api-keys',
    portalUrl: 'https://platform.openai.com/api-keys',
    placeholder: 'sk-proj-...',
    steps: [
      'Open platform.openai.com/api-keys and create a secret key.',
      'Paste your OpenAI key to load your live /v1/models list (paid API usage).',
    ],
    models: [],
  },
  {
    id: 'custom_url',
    name: 'Custom Endpoint',
    baseUrl: '',
    placeholder: 'sk-...',
    steps: [
      'Enter any HTTPS OpenAI-compatible Base URL and API key.',
      'Mist attempts to fetch <Base URL>/models if supported; manually entered model IDs stay Unverified until tested.',
    ],
    models: [],
  },
];

export const PROVIDER_CATALOG: Record<
  AiProviderId,
  {
    name: string;
    shortDesc: string;
    requiresUserKey: boolean;
    models: ModelCatalogItem[];
  }
> = {
  custom: {
    name: 'Custom BYOK',
    shortDesc: 'Connect any API Key, Base URL & Provider Name',
    requiresUserKey: true,
    models: CUSTOM_GATEWAY_PRESETS[0].models,
  },
  openrouter: {
    name: 'OpenRouter',
    shortDesc: 'Live OpenRouter catalog with verified pricing',
    requiresUserKey: true,
    models: CUSTOM_GATEWAY_PRESETS[0].models,
  },
  groq: {
    name: 'Groq',
    shortDesc: 'Live Groq /openai/v1/models endpoint',
    requiresUserKey: true,
    models: CUSTOM_GATEWAY_PRESETS[1].models,
  },
  gemini: {
    name: 'Gemini (BYOK)',
    shortDesc: 'Official Gemini /v1beta/models catalog',
    requiresUserKey: true,
    models: CUSTOM_GATEWAY_PRESETS[2].models,
  },
};

export function detectGatewayFromBaseUrl(baseUrl?: string): CustomGatewayId {
  const lower = (baseUrl || '').toLowerCase();
  if (lower.includes('openrouter.ai')) return 'openrouter';
  if (lower.includes('api.groq.com')) return 'groq';
  if (lower.includes('generativelanguage.googleapis.com')) return 'gemini_byok';
  if (lower.includes('nvidia.com')) return 'nvidia';
  if (lower.includes('api.openai.com')) return 'openai';
  return 'custom_url';
}

/**
 * Preserves legitimate user-selected model IDs (such as gemini-4-hydrogen) without silently
 * substituting them with legacy models. Only supplies a safe fallback when model is empty.
 */
export function normalizeProviderConfigToStudio(config?: AiProviderConfig): AiProviderConfig {
  const rawProvider = config?.provider;
  const sessionOnlyKey = Boolean(config?.sessionOnlyKey);
  const trimmedModel = typeof config?.model === 'string' ? config.model.trim() : '';

  if (rawProvider === 'openrouter' && config) {
    return {
      provider: 'custom',
      name: config.name?.trim() || 'OpenRouter',
      model: trimmedModel || 'openrouter/free',
      apiKey: config.apiKey || '',
      baseUrl: config.baseUrl || 'https://openrouter.ai/api/v1',
      sessionOnlyKey,
    };
  }
  if (rawProvider === 'groq' && config) {
    return {
      provider: 'custom',
      name: config.name?.trim() || 'Groq',
      model: trimmedModel,
      apiKey: config.apiKey || '',
      baseUrl: config.baseUrl || 'https://api.groq.com/openai/v1',
      sessionOnlyKey,
    };
  }
  if (rawProvider === 'gemini' && config) {
    return {
      provider: 'custom',
      name: config.name?.trim() || 'Gemini (BYOK)',
      model: trimmedModel,
      apiKey: config.apiKey || '',
      baseUrl: config.baseUrl || 'https://generativelanguage.googleapis.com/v1beta/openai',
      sessionOnlyKey,
    };
  }

  const baseUrl = config?.baseUrl ?? DEFAULT_BYOK_CONFIG.baseUrl;
  const detected = detectGatewayFromBaseUrl(baseUrl);
  const preset = CUSTOM_GATEWAY_PRESETS.find((g) => g.id === detected);
  const defaultModelForBase =
    detected === 'openrouter' ? 'openrouter/free' : preset?.models[0]?.id || '';

  return {
    provider: 'custom',
    name: config?.name?.trim() || (preset && preset.id !== 'custom_url' ? preset.name : 'Custom Provider'),
    model: trimmedModel || (baseUrl === DEFAULT_BYOK_CONFIG.baseUrl ? DEFAULT_BYOK_CONFIG.model : defaultModelForBase),
    apiKey: config?.apiKey || '',
    baseUrl,
    sessionOnlyKey,
  };
}

export function getDefaultModelForProvider(provider: AiProviderId): string {
  return PROVIDER_CATALOG[provider]?.models[0]?.id || '';
}

export function getModelDisplayLabel(
  provider: AiProviderId,
  modelId: string,
  liveModels?: ModelCatalogItem[],
): string {
  if (!modelId) return 'Select model';
  if (liveModels) {
    const inLive = liveModels.find((m) => m.id === modelId);
    if (inLive) return inLive.label;
  }
  const inPrimary = PROVIDER_CATALOG[provider]?.models.find((m) => m.id === modelId);
  if (inPrimary) return inPrimary.label;
  for (const preset of CUSTOM_GATEWAY_PRESETS) {
    const match = preset.models.find((m) => m.id === modelId);
    if (match) return match.label;
  }
  return modelId;
}

export function findModelEntry(
  provider: AiProviderId,
  modelId: string,
  baseUrl?: string,
  liveModels?: ModelCatalogItem[],
): ModelCatalogItem | undefined {
  if (!modelId) return undefined;
  if (liveModels) {
    const liveMatch = liveModels.find((item) => item.id === modelId);
    if (liveMatch) return liveMatch;
  }
  const gw = CUSTOM_GATEWAY_PRESETS.find((g) => g.id === detectGatewayFromBaseUrl(baseUrl));
  if (gw) {
    const m = gw.models.find((item) => item.id === modelId);
    if (m) return m;
  }
  for (const preset of CUSTOM_GATEWAY_PRESETS) {
    const m = preset.models.find((item) => item.id === modelId);
    if (m) return m;
  }
  return PROVIDER_CATALOG[provider]?.models.find((m) => m.id === modelId);
}

/**
 * Detects whether a user's website prompt explicitly asks for live AI functionality inside the generated app.
 */
export function promptRequestsAi(prompt: string): boolean {
  const cleaned = (prompt || '').trim();
  if (!cleaned) return false;
  return (
    /\b(?:ai|llm|chatbot|chat-bot|ai-powered|ai-enabled|copilot|co-pilot)\b/i.test(cleaned) ||
    /\/api\/app-ai|mistai/i.test(cleaned) ||
    /\b(?:with|add|include|using|powered by)\s+(?:an?\s+)?(?:smart\s+)?(?:assistant|summarizer|translator|tutor|coach|analyzer|writer|generator)\b/i.test(
      cleaned,
    ) ||
    /\b(?:ai\s+(?:chat|writer|assistant|editor|tutor|planner|search|quiz|analyzer|generator))\b/i.test(
      cleaned,
    )
  );
}

export function shouldEnableAppAi(
  prompt: string,
  mode: AppAiMode = 'on_request',
  explicitOverride?: boolean,
): boolean {
  if (typeof explicitOverride === 'boolean') return explicitOverride;
  if (mode === 'off') return false;
  if (mode === 'always') return true;
  return promptRequestsAi(prompt);
}

export interface LiveCatalogResponse {
  gateway: CustomGatewayId;
  source: CatalogSource;
  fetchedAt: string;
  models: ModelCatalogItem[];
  isOutdatedFallback?: boolean;
  note?: string;
}

const clientCatalogCache = new Map<string, { expiresAt: number; data: LiveCatalogResponse }>();

export function clearClientModelCatalogCache(): void {
  clientCatalogCache.clear();
}

export async function fetchLiveModelCatalog(params: {
  baseUrl: string;
  apiKey?: string;
  idToken?: string;
  forceRefresh?: boolean;
  signal?: AbortSignal;
}): Promise<LiveCatalogResponse> {
  const cleanUrl = (params.baseUrl || '').trim().replace(/\/+$/, '');
  const cleanKey = params.apiKey?.trim() || '';
  const hasKey = Boolean(cleanKey);
  const cacheKey = `${cleanUrl}|${hasKey ? 'auth' : 'anon'}`;

  if (!params.forceRefresh) {
    const hit = clientCatalogCache.get(cacheKey);
    if (hit && hit.expiresAt > Date.now()) {
      return {
        ...hit.data,
        source: 'cached',
      };
    }
  }

  if (params.signal?.aborted) {
    const abortErr = new Error('Aborted');
    abortErr.name = 'AbortError';
    throw abortErr;
  }

  const gatewayId = detectGatewayFromBaseUrl(cleanUrl);
  let resp: Response;
  if (params.idToken) {
    resp = await fetch('/api/ai/models', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${params.idToken}`,
      },
      body: JSON.stringify({
        baseUrl: cleanUrl,
        apiKey: cleanKey || undefined,
        forceRefresh: Boolean(params.forceRefresh),
      }),
      signal: params.signal,
    });
  } else {
    if (gatewayId !== 'openrouter') {
      throw new Error('Sign in to Mist to inspect live models on non-public gateways.');
    }
    const qs = new URLSearchParams({
      baseUrl: cleanUrl,
      forceRefresh: String(Boolean(params.forceRefresh)),
    });
    resp = await fetch(`/api/ai/models?${qs.toString()}`, {
      method: 'GET',
      signal: params.signal,
    });
  }

  if (!resp.ok) {
    const errPayload = (await resp.json().catch(() => ({}))) as { error?: string };
    throw new Error(errPayload.error || `Failed to load model catalog (${resp.status}).`);
  }

  const data = (await resp.json()) as LiveCatalogResponse;
  if (data.source === 'live' || data.source === 'cached') {
    clientCatalogCache.set(cacheKey, {
      expiresAt: Date.now() + 5 * 60 * 1000,
      data,
    });
  }
  return data;
}
