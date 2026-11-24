import crypto from 'node:crypto';
import {
  CUSTOM_GATEWAY_PRESETS,
  detectGatewayFromBaseUrl,
  UNKNOWN_CAPABILITIES,
  type CustomGatewayId,
  type ModelCatalogItem,
} from '../data/models';
import type { CatalogSource, ModelCapabilities, ModelLifecycleStatus } from '../types/mist';
import { safeFetchExternal, sanitizeErrorMessage, SecurityValidationError } from './serverSecurity';

export interface ServerCatalogResult {
  gateway: CustomGatewayId;
  source: CatalogSource;
  fetchedAt: string;
  models: ModelCatalogItem[];
  isOutdatedFallback?: boolean;
  note?: string;
}

const CATALOG_TTL_MS = 10 * 60 * 1000;
const MAX_CATALOG_CACHE_ENTRIES = 100;
const serverCatalogCache = new Map<string, { expiresAt: number; result: ServerCatalogResult }>();

function setCatalogCache(key: string, result: ServerCatalogResult): void {
  const now = Date.now();
  if (serverCatalogCache.size >= MAX_CATALOG_CACHE_ENTRIES) {
    for (const [k, v] of serverCatalogCache.entries()) {
      if (v.expiresAt <= now || serverCatalogCache.size >= MAX_CATALOG_CACHE_ENTRIES) {
        serverCatalogCache.delete(k);
      }
    }
  }
  serverCatalogCache.set(key, { expiresAt: now + CATALOG_TTL_MS, result });
}

export function clearServerCatalogCache(): void {
  serverCatalogCache.clear();
}

function formatPerMillionUsd(perTokenRaw?: string | number): string | null {
  if (perTokenRaw === undefined || perTokenRaw === null || perTokenRaw === '') return null;
  const num = Number(perTokenRaw);
  if (!Number.isFinite(num) || num < 0) return null;
  if (num === 0) return '$0';
  const perMillion = num * 1_000_000;
  if (perMillion < 0.01) return `$${perMillion.toFixed(4)}/1M`;
  if (perMillion < 1) return `$${perMillion.toFixed(3)}/1M`;
  return `$${perMillion.toFixed(2)}/1M`;
}

function inferTierFromId(id: string): ModelCatalogItem['tier'] {
  const lower = id.toLowerCase();
  if (lower.includes('coder') || lower.includes('codestral') || lower.includes('devstral')) {
    return 'Coding';
  }
  if (
    lower.includes('r1') ||
    lower.includes('thinking') ||
    lower.includes('reason') ||
    lower.includes('o3') ||
    lower.includes('o4') ||
    lower.includes('qwq')
  ) {
    return 'Reasoning';
  }
  if (
    lower.includes('nano') ||
    lower.includes('mini') ||
    lower.includes('instant') ||
    lower.includes('lite') ||
    lower.includes('8b') ||
    lower.includes('flash') ||
    lower.includes('scout')
  ) {
    return 'Fast';
  }
  if (
    lower.includes('pro') ||
    lower.includes('sonnet') ||
    lower.includes('opus') ||
    lower.includes('235b') ||
    lower.includes('405b') ||
    lower.includes('maverick') ||
    lower.includes('ultra')
  ) {
    return 'Pro';
  }
  return 'Default';
}

export interface OpenRouterRawModel {
  id: string;
  name?: string;
  description?: string;
  context_length?: number;
  expiration_date?: string | null;
  architecture?: {
    modality?: string;
    input_modalities?: string[];
    output_modalities?: string[];
  };
  pricing?: {
    prompt?: string | number;
    completion?: string | number;
  };
  supported_parameters?: string[];
}

export function mapOpenRouterModels(rawList: OpenRouterRawModel[]): ModelCatalogItem[] {
  const mapped: ModelCatalogItem[] = [];
  const seen = new Set<string>();
  const nowMs = Date.now();

  for (const item of rawList) {
    if (!item || typeof item.id !== 'string' || !item.id.trim()) continue;
    const id = item.id.trim();
    if (seen.has(id)) continue;

    // Only keep chat/code text-output models for Mist builder UI
    const outputs = item.architecture?.output_modalities;
    const modality = item.architecture?.modality || '';
    if (Array.isArray(outputs) && outputs.length > 0 && !outputs.includes('text')) {
      continue;
    }
    if (modality && modality.includes('->') && !modality.includes('->text')) {
      continue;
    }

    seen.add(id);

    const hasPromptPrice = item.pricing?.prompt !== undefined && item.pricing?.prompt !== null && item.pricing?.prompt !== '';
    const hasCompletionPrice =
      item.pricing?.completion !== undefined && item.pricing?.completion !== null && item.pricing?.completion !== '';
    const promptCost = hasPromptPrice ? Number(item.pricing?.prompt) : NaN;
    const completionCost = hasCompletionPrice ? Number(item.pricing?.completion) : NaN;
    const hasNumericPricing = Number.isFinite(promptCost) && Number.isFinite(completionCost);

    const isFree =
      id === 'openrouter/free' ||
      id.endsWith(':free') ||
      (hasNumericPricing && promptCost === 0 && completionCost === 0);

    const billing: ModelCatalogItem['billing'] = isFree
      ? 'free'
      : hasNumericPricing
        ? 'paid'
        : 'unknown';

    const billingLabel =
      billing === 'free' ? 'Free' : billing === 'paid' ? 'Paid' : 'Unknown';

    const inStr = formatPerMillionUsd(item.pricing?.prompt);
    const outStr = formatPerMillionUsd(item.pricing?.completion);
    const pricingSummary =
      billing === 'free'
        ? '$0 / Free'
        : inStr && outStr
          ? `${inStr} in · ${outStr} out`
          : billing === 'paid'
            ? 'Paid per token'
            : 'Pricing not reported';

    const ctxLabel = item.context_length
      ? `${Math.round(item.context_length / 1000)}k ctx`
      : '';

    const cleanLabel = (item.name || id)
      .replace(/\s*\(free\)\s*$/i, '')
      .trim();

    const params = Array.isArray(item.supported_parameters)
      ? new Set(item.supported_parameters.map((p) => String(p).toLowerCase()))
      : null;
    const inputs = item.architecture?.input_modalities;

    const capabilities: ModelCapabilities = {
      textGeneration: true,
      jsonOutput: params
        ? params.has('response_format') || params.has('structured_outputs')
        : 'unknown',
      streaming: true,
      imageInput: Array.isArray(inputs)
        ? inputs.includes('image')
        : modality.includes('image')
          ? true
          : 'unknown',
      toolCalling: params ? params.has('tools') || params.has('tool_choice') : 'unknown',
    };

    const descLower = (item.description || '').toLowerCase();
    const expMs = item.expiration_date ? Date.parse(item.expiration_date) : NaN;
    let status: ModelLifecycleStatus = 'active';
    if ((Number.isFinite(expMs) && expMs <= nowMs) || /\b(?:retired|discontinued|shut\s?down)\b/.test(descLower)) {
      status = 'retired';
    } else if (/\bdeprecated\b/.test(descLower) || id.toLowerCase().includes(':deprecated')) {
      status = 'deprecated';
    } else if (/\bpreview\b/.test(id.toLowerCase()) || /\bpreview\b/.test(cleanLabel.toLowerCase())) {
      status = 'preview';
    }

    mapped.push({
      id,
      label:
        isFree && id.endsWith(':free') && !cleanLabel.includes(':free')
          ? `${cleanLabel} (:free)`
          : cleanLabel,
      summary: [billingLabel, pricingSummary !== '$0 / Free' ? pricingSummary : '', ctxLabel]
        .filter(Boolean)
        .join(' · '),
      tier: inferTierFromId(id),
      billing,
      billingLabel,
      status,
      capabilities,
      contextLength: item.context_length,
      pricingSummary,
      isLiveFetched: true,
      modality: modality || undefined,
    });
  }

  // Ensure openrouter/free router exists if API omitted it
  if (!seen.has('openrouter/free')) {
    const presetAuto = CUSTOM_GATEWAY_PRESETS[0].models.find((m) => m.id === 'openrouter/free');
    if (presetAuto) {
      mapped.unshift({ ...presetAuto, isLiveFetched: true });
    }
  }

  const priorityVendors = [
    'openrouter/free',
    'nvidia/',
    'deepseek/',
    'qwen/',
    'meta-llama/',
    'google/',
    'anthropic/',
    'openai/',
  ];
  const billingRank = (b: ModelCatalogItem['billing']) =>
    b === 'free' ? 0 : b === 'paid' ? 1 : 2;
  const statusRank = (s: ModelLifecycleStatus) =>
    s === 'deprecated' || s === 'retired' ? 1 : 0;

  mapped.sort((a, b) => {
    if (a.id === 'openrouter/free') return -1;
    if (b.id === 'openrouter/free') return 1;
    if (statusRank(a.status) !== statusRank(b.status)) return statusRank(a.status) - statusRank(b.status);
    if (billingRank(a.billing) !== billingRank(b.billing)) return billingRank(a.billing) - billingRank(b.billing);
    const aPri = priorityVendors.findIndex((p) => a.id.startsWith(p));
    const bPri = priorityVendors.findIndex((p) => b.id.startsWith(p));
    const aScore = aPri === -1 ? 99 : aPri;
    const bScore = bPri === -1 ? 99 : bPri;
    if (aScore !== bScore) return aScore - bScore;
    return a.label.localeCompare(b.label);
  });

  return mapped;
}

export interface OpenAiCompatRawModel {
  id: string;
  active?: boolean;
  owned_by?: string;
  context_window?: number;
  deprecated?: boolean;
  status?: string;
}

const GROQ_NON_CHAT_PATTERNS = [
  /whisper/i,
  /tts/i,
  /orpheus/i,
  /prompt-guard/i,
  /llama-guard/i,
  /safeguard/i,
];

/**
 * Maps live models returned from Groq /openai/v1/models without fabricating free-tier guesses.
 * Groq's /models endpoint does not include billing metadata, so models are honestly marked
 * "Provider billed" according to the user's Groq plan.
 */
export function mapGroqModels(rawList: OpenAiCompatRawModel[]): ModelCatalogItem[] {
  const mapped: ModelCatalogItem[] = [];
  const seen = new Set<string>();

  for (const item of rawList) {
    if (!item || typeof item.id !== 'string' || !item.id.trim()) continue;
    const id = item.id.trim();
    if (seen.has(id)) continue;
    if (GROQ_NON_CHAT_PATTERNS.some((rx) => rx.test(id))) continue;

    seen.add(id);
    const ctx = typeof item.context_window === 'number' && item.context_window > 0 ? item.context_window : undefined;
    const isRetired = item.active === false || item.status === 'retired';
    const isDeprecated = Boolean(item.deprecated) || item.status === 'deprecated';
    const isPreview = /\bpreview\b/i.test(id);
    const status: ModelLifecycleStatus = isRetired
      ? 'retired'
      : isDeprecated
        ? 'deprecated'
        : isPreview
          ? 'preview'
          : 'active';

    mapped.push({
      id,
      label: id,
      summary: [
        isRetired ? 'Unavailable (inactive on Groq)' : 'Provider billed (Groq plan limits apply)',
        item.owned_by ? `by ${item.owned_by}` : '',
        ctx ? `${Math.round(ctx / 1000)}k ctx` : '',
      ]
        .filter(Boolean)
        .join(' · '),
      tier: inferTierFromId(id),
      billing: 'provider_billed',
      billingLabel: 'Provider billed',
      status,
      capabilities: { ...UNKNOWN_CAPABILITIES },
      contextLength: ctx,
      isLiveFetched: true,
    });
  }

  mapped.sort((a, b) => {
    const rank = (s: ModelLifecycleStatus) => (s === 'active' || s === 'preview' ? 0 : 1);
    if (rank(a.status) !== rank(b.status)) return rank(a.status) - rank(b.status);
    return a.id.localeCompare(b.id);
  });

  return mapped;
}

export interface GeminiRawModel {
  id?: string;
  name?: string;
  displayName?: string;
  description?: string;
  version?: string;
  inputTokenLimit?: number;
  outputTokenLimit?: number;
  supportedGenerationMethods?: string[];
}

const KNOWN_DEPRECATED_GEMINI_PATTERNS = [
  /^gemini-1\.0-/i,
  /^gemini-1\.5-/i,
  /^gemini-2\.0-flash-exp$/i,
  /^gemini-2\.5-pro$/i,
];

/**
 * Maps official Gemini /v1beta/models metadata without name-based billing guesses or replacing valid new IDs
 * such as gemini-4-hydrogen. Checks supportedGenerationMethods and official description metadata.
 */
export function mapGeminiModels(rawList: GeminiRawModel[]): ModelCatalogItem[] {
  const mapped: ModelCatalogItem[] = [];
  const seen = new Set<string>();

  for (const item of rawList) {
    const rawId = item.id || item.name || '';
    const id = rawId.replace(/^models\//, '').trim();
    if (!id || seen.has(id)) continue;
    const lower = id.toLowerCase();
    if (!lower.includes('gemini')) continue;
    if (
      lower.includes('embedding') ||
      lower.includes('imagen') ||
      lower.includes('veo') ||
      lower.includes('aqa') ||
      lower.includes('tts') ||
      lower.includes('native-audio') ||
      lower.includes('robotics') ||
      lower.includes('computer-use')
    ) {
      continue;
    }

    const methods = Array.isArray(item.supportedGenerationMethods)
      ? item.supportedGenerationMethods
      : [];
    if (methods.length > 0 && !methods.includes('generateContent')) {
      continue;
    }

    seen.add(id);

    const descLower = (item.description || '').toLowerCase();
    const isRetired = /\b(?:retired|discontinued|turned down|shut down|no longer supported)\b/.test(descLower);
    const isDeprecated =
      /\b(?:deprecated|legacy)\b/.test(descLower) ||
      KNOWN_DEPRECATED_GEMINI_PATTERNS.some((rx) => rx.test(id));
    const isPreview =
      /\b(?:preview|experimental)\b/.test(lower) || /\b(?:preview|experimental)\b/.test(descLower);

    const status: ModelLifecycleStatus = isRetired
      ? 'retired'
      : isDeprecated
        ? 'deprecated'
        : isPreview
          ? 'preview'
          : 'active';

    const capabilities: ModelCapabilities = {
      textGeneration: methods.length === 0 ? true : methods.includes('generateContent'),
      streaming: methods.length > 0 ? methods.includes('streamGenerateContent') : 'unknown',
      jsonOutput: 'unknown',
      imageInput: 'unknown',
      toolCalling: 'unknown',
    };

    const ctx =
      typeof item.inputTokenLimit === 'number' && item.inputTokenLimit > 0
        ? item.inputTokenLimit
        : undefined;

    mapped.push({
      id,
      label: item.displayName || id,
      summary: [
        status === 'deprecated'
          ? 'Deprecated / legacy Gemini model'
          : status === 'retired'
            ? 'Retired model'
            : 'Provider billed (depends on AI Studio / Cloud project tier)',
        ctx ? `${Math.round(ctx / 1000)}k in ctx` : '',
      ]
        .filter(Boolean)
        .join(' · '),
      tier: inferTierFromId(id),
      billing: 'provider_billed',
      billingLabel: 'Provider billed',
      status,
      capabilities,
      contextLength: ctx,
      supportedMethods: methods.length > 0 ? methods : undefined,
      isLiveFetched: true,
    });
  }

  mapped.sort((a, b) => {
    const statusWeight = (s: ModelLifecycleStatus) =>
      s === 'active' ? 0 : s === 'preview' ? 1 : s === 'deprecated' ? 2 : 3;
    if (statusWeight(a.status) !== statusWeight(b.status)) {
      return statusWeight(a.status) - statusWeight(b.status);
    }
    return a.id.localeCompare(b.id);
  });

  return mapped;
}

export function mapGenericOpenAiCompatModels(
  rawList: OpenAiCompatRawModel[],
  gateway: CustomGatewayId,
  providerDisplayName: string,
): ModelCatalogItem[] {
  const mapped: ModelCatalogItem[] = [];
  const seen = new Set<string>();

  for (const item of rawList) {
    if (!item || typeof item.id !== 'string' || !item.id.trim()) continue;
    const id = item.id.trim();
    if (seen.has(id)) continue;
    if (gateway === 'openai' && !/^(gpt-|o1|o3|o4|chatgpt-)/i.test(id)) continue;
    seen.add(id);

    const isRetired = item.active === false || item.status === 'retired';
    const isDeprecated = Boolean(item.deprecated) || item.status === 'deprecated';
    const isPreview = /\bpreview\b/i.test(id);
    const status: ModelLifecycleStatus = isRetired
      ? 'retired'
      : isDeprecated
        ? 'deprecated'
        : isPreview
          ? 'preview'
          : 'active';

    const billing: ModelCatalogItem['billing'] =
      gateway === 'openai' ? 'paid' : gateway === 'nvidia' ? 'provider_billed' : 'unknown';
    const billingLabel =
      billing === 'paid' ? 'Paid' : billing === 'provider_billed' ? 'Provider billed' : 'Unknown';

    const ctx =
      typeof item.context_window === 'number' && item.context_window > 0 ? item.context_window : undefined;

    mapped.push({
      id,
      label: id,
      summary: [
        `Live model from ${providerDisplayName}`,
        billingLabel,
        ctx ? `${Math.round(ctx / 1000)}k ctx` : '',
      ]
        .filter(Boolean)
        .join(' · '),
      tier: inferTierFromId(id),
      billing,
      billingLabel,
      status,
      capabilities: { ...UNKNOWN_CAPABILITIES },
      contextLength: ctx,
      isLiveFetched: true,
    });
  }

  mapped.sort((a, b) => a.id.localeCompare(b.id));
  return mapped;
}

export async function fetchGatewayModelsCatalog(params: {
  baseUrl: string;
  apiKey?: string;
  forceRefresh?: boolean;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
  skipDnsLookup?: boolean;
}): Promise<ServerCatalogResult> {
  const cleanBase = (params.baseUrl || '').trim().replace(/\/+$/, '');
  const cleanKey = (params.apiKey || '').trim();
  const gateway = detectGatewayFromBaseUrl(cleanBase);
  const preset = CUSTOM_GATEWAY_PRESETS.find((g) => g.id === gateway) || CUSTOM_GATEWAY_PRESETS[5];

  const keyHash = cleanKey
    ? crypto.createHash('sha256').update(cleanKey).digest('hex').slice(0, 12)
    : 'anon';
  const cacheKey = `${cleanBase}|${keyHash}`;

  if (!params.forceRefresh) {
    const cached = serverCatalogCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) {
      return {
        ...cached.result,
        source: 'cached',
      };
    }
  }

  const fetchedAt = new Date().toISOString();

  if (gateway === 'openrouter') {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (cleanKey) headers.Authorization = `Bearer ${cleanKey}`;
    try {
      const resp = await safeFetchExternal('https://openrouter.ai/api/v1/models', {
        headers,
        timeoutMs: 12000,
        parentSignal: params.signal,
        fetchImpl: params.fetchImpl,
        skipDnsLookup: params.skipDnsLookup,
      });
      if (!resp.ok) {
        throw new Error(`OpenRouter /models returned HTTP ${resp.status}.`);
      }
      const json = (await resp.json()) as { data?: OpenRouterRawModel[] };
      const mapped = Array.isArray(json.data) ? mapOpenRouterModels(json.data) : [];
      if (mapped.length === 0) {
        return {
          gateway,
          source: 'preset',
          fetchedAt,
          isOutdatedFallback: true,
          models: preset.models,
          note: 'OpenRouter returned an empty catalog; showing fallback preset (may be outdated).',
        };
      }
      const result: ServerCatalogResult = {
        gateway,
        source: 'live',
        fetchedAt,
        models: mapped,
      };
      setCatalogCache(cacheKey, result);
      return result;
    } catch (err) {
      if (err instanceof SecurityValidationError) throw err;
      throw new SecurityValidationError(
        502,
        `OpenRouter catalog unreachable (${sanitizeErrorMessage(err)}). Retry or use the fallback openrouter/free preset.`,
      );
    }
  }

  if (gateway === 'groq') {
    if (!cleanKey) {
      return {
        gateway,
        source: 'preset',
        fetchedAt,
        models: [],
        note: 'Add your Groq API key (gsk_...) and refresh to load live models from /openai/v1/models.',
      };
    }
    const resp = await safeFetchExternal('https://api.groq.com/openai/v1/models', {
      headers: {
        Authorization: `Bearer ${cleanKey}`,
        Accept: 'application/json',
      },
      timeoutMs: 10000,
      parentSignal: params.signal,
      fetchImpl: params.fetchImpl,
      skipDnsLookup: params.skipDnsLookup,
    });
    if (!resp.ok) {
      throw new SecurityValidationError(resp.status >= 400 ? resp.status : 502, `Groq /openai/v1/models returned HTTP ${resp.status}.`);
    }
    const json = (await resp.json()) as { data?: OpenAiCompatRawModel[] };
    const mapped = Array.isArray(json.data) ? mapGroqModels(json.data) : [];
    const result: ServerCatalogResult = {
      gateway,
      source: 'live',
      fetchedAt,
      models: mapped,
      note: mapped.length === 0 ? 'Groq returned 0 eligible chat models for this key.' : undefined,
    };
    setCatalogCache(cacheKey, result);
    return result;
  }

  if (gateway === 'gemini_byok') {
    if (!cleanKey) {
      return {
        gateway,
        source: 'preset',
        fetchedAt,
        models: [],
        note: 'Add your Gemini API key (AIza...) to load live models from /v1beta/models, or type a custom model ID.',
      };
    }
    const resp = await safeFetchExternal('https://generativelanguage.googleapis.com/v1beta/models?pageSize=100', {
      headers: {
        'x-goog-api-key': cleanKey,
        Accept: 'application/json',
      },
      timeoutMs: 10000,
      parentSignal: params.signal,
      fetchImpl: params.fetchImpl,
      skipDnsLookup: params.skipDnsLookup,
    });
    if (!resp.ok) {
      throw new SecurityValidationError(
        resp.status >= 400 ? resp.status : 502,
        `Gemini /v1beta/models returned HTTP ${resp.status}.`,
      );
    }
    const json = (await resp.json()) as { models?: GeminiRawModel[] };
    const mapped = Array.isArray(json.models) ? mapGeminiModels(json.models) : [];
    const result: ServerCatalogResult = {
      gateway,
      source: 'live',
      fetchedAt,
      models: mapped,
      note: mapped.length === 0 ? 'Gemini API returned 0 generateContent models for this key.' : undefined,
    };
    setCatalogCache(cacheKey, result);
    return result;
  }

  // Generic OpenAI-compatible gateway (NVIDIA, OpenAI, Custom URL)
  if (!cleanBase) {
    return {
      gateway,
      source: 'preset',
      fetchedAt,
      models: [],
      note: 'Enter an HTTPS Base URL to inspect available models.',
    };
  }

  if (!cleanKey) {
    return {
      gateway,
      source: 'preset',
      fetchedAt,
      models: [],
      note: `Add your ${preset.name} API key to query /models live, or type a custom model ID manually (marked Unverified until tested).`,
    };
  }

  const modelsEndpoint = cleanBase.endsWith('/chat/completions')
    ? cleanBase.replace(/\/chat\/completions$/, '/models')
    : `${cleanBase}/models`;

  const resp = await safeFetchExternal(modelsEndpoint, {
    headers: {
      Authorization: `Bearer ${cleanKey}`,
      Accept: 'application/json',
    },
    timeoutMs: 10000,
    parentSignal: params.signal,
    fetchImpl: params.fetchImpl,
    skipDnsLookup: params.skipDnsLookup,
  });
  if (!resp.ok) {
    throw new SecurityValidationError(
      resp.status >= 400 ? resp.status : 502,
      `${preset.name} /models returned HTTP ${resp.status}. Enter a model ID manually and run Test Connection.`,
    );
  }

  const json = (await resp.json()) as { data?: OpenAiCompatRawModel[] };
  const liveList = Array.isArray(json.data)
    ? mapGenericOpenAiCompatModels(json.data, gateway, preset.name)
    : [];

  const result: ServerCatalogResult = {
    gateway,
    source: 'live',
    fetchedAt,
    models: liveList,
    note:
      liveList.length === 0
        ? `${preset.name} /models returned an empty list. Enter a custom model ID below and test it.`
        : undefined,
  };
  setCatalogCache(cacheKey, result);
  return result;
}
