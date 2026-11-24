import type {
  WebSearchConfig,
  WebSearchMode,
  WebSearchProviderId,
  WebSearchSource,
} from '../types/mist';

export interface WebSearchPreset {
  id: WebSearchProviderId;
  name: string;
  baseUrl: string;
  placeholder: string;
  description: string;
  requiresApiKey?: boolean;
  portalUrl?: string;
  portalLabel?: string;
  steps?: string[];
}

export const WEB_SEARCH_PRESETS: WebSearchPreset[] = [
  {
    id: 'duckduckgo',
    name: 'DuckDuckGo (Free · No Key)',
    baseUrl: 'https://html.duckduckgo.com/html/',
    placeholder: 'No API key required',
    requiresApiKey: false,
    description:
      'Free web search powered by DuckDuckGo — works out of the box with no API key or account. Queries DuckDuckGo HTML search with automatic Instant Answer fallback.',
    portalUrl: 'https://duckduckgo.com',
    portalLabel: 'duckduckgo.com',
    steps: [
      'Select DuckDuckGo (Free · No Key) — no API key or signup is required.',
      'Set Search Web to Auto or On on the prompt bar or editor refinement bar.',
      'Optional: switch to Brave Search if you prefer an authenticated API key quota.',
    ],
  },
  {
    id: 'brave_llm_context',
    name: 'Brave Search (LLM Context)',
    baseUrl: 'https://api.search.brave.com/res/v1/llm/context',
    placeholder: 'BSA...',
    requiresApiKey: true,
    description:
      'Optional BYOK API key — returns ranked web sources and pre-extracted page chunks with real URLs and dates.',
    portalUrl: 'https://api-dashboard.search.brave.com',
    portalLabel: 'api-dashboard.search.brave.com',
    steps: [
      'Create or sign in to a Brave Search API account at api-dashboard.search.brave.com.',
      'Generate an API key with access to the LLM Context or Data for AI plan.',
      'Paste your BSA... subscription token here. It works with every AI model connected to Mist.',
    ],
  },
  {
    id: 'brave_web',
    name: 'Brave Web Search',
    baseUrl: 'https://api.search.brave.com/res/v1/web/search',
    placeholder: 'BSA...',
    requiresApiKey: true,
    description:
      'Optional BYOK Brave Web Search REST endpoint returning web results, descriptions, extra snippets, and page dates.',
    portalUrl: 'https://api-dashboard.search.brave.com',
    portalLabel: 'api-dashboard.search.brave.com',
    steps: [
      'Open api-dashboard.search.brave.com and copy your Brave Search API subscription token.',
      'Select Brave Web Search if your key is subscribed to the standard Web Search API.',
    ],
  },
  {
    id: 'custom_json',
    name: 'Custom Search Endpoint',
    baseUrl: '',
    placeholder: 'Bearer token or API key...',
    requiresApiKey: true,
    description:
      'Any HTTPS JSON search proxy accepting POST { query, count } and returning { results: [{ title, url, snippet, publishedDate }] }.',
  },
];

export const DEFAULT_WEB_SEARCH_CONFIG: WebSearchConfig = {
  provider: 'duckduckgo',
  name: 'DuckDuckGo (Free · No Key)',
  baseUrl: 'https://html.duckduckgo.com/html/',
  apiKey: '',
  sessionOnlyKey: false,
  maxResults: 5,
};

export function normalizeWebSearchConfig(
  raw?: Partial<WebSearchConfig> | null,
): WebSearchConfig {
  const provider: WebSearchProviderId =
    raw?.provider === 'brave_llm_context' ||
    raw?.provider === 'brave_web' ||
    raw?.provider === 'custom_json' ||
    raw?.provider === 'duckduckgo'
      ? raw.provider
      : 'duckduckgo';
  const preset =
    WEB_SEARCH_PRESETS.find((p) => p.id === provider) || WEB_SEARCH_PRESETS[0];

  const maxResultsRaw = typeof raw?.maxResults === 'number' ? raw.maxResults : 5;
  const maxResults = Math.min(8, Math.max(1, Math.round(maxResultsRaw)));

  const baseUrl =
    typeof raw?.baseUrl === 'string' && raw.baseUrl.trim()
      ? raw.baseUrl.trim().replace(/\/+$/, '')
      : preset.baseUrl;

  return {
    provider,
    name:
      typeof raw?.name === 'string' && raw.name.trim()
        ? raw.name.trim().slice(0, 80)
        : preset.name,
    baseUrl,
    apiKey: typeof raw?.apiKey === 'string' ? raw.apiKey.trim() : '',
    sessionOnlyKey: Boolean(raw?.sessionOnlyKey),
    maxResults,
  };
}

export function webSearchConfigReady(raw?: Partial<WebSearchConfig> | null): boolean {
  const normalized = normalizeWebSearchConfig(raw);
  const preset = WEB_SEARCH_PRESETS.find((p) => p.id === normalized.provider);
  if (preset && preset.requiresApiKey === false) {
    return Boolean(normalized.baseUrl?.trim());
  }
  return Boolean(normalized.apiKey?.trim());
}

/**
 * Determines whether a prompt requires live web search based on mode ('auto' | 'on' | 'off')
 * and freshness/current-information cues in the user's request.
 */
export function needsWebSearch(
  prompt: string,
  mode: WebSearchMode = 'auto',
): { shouldSearch: boolean; reason: string } {
  if (mode === 'off') {
    return { shouldSearch: false, reason: 'Search Web is turned Off.' };
  }
  if (mode === 'on') {
    return { shouldSearch: true, reason: 'Search Web is turned On.' };
  }

  const text = (prompt || '').trim();
  if (!text) {
    return { shouldSearch: false, reason: 'Empty prompt.' };
  }

  const explicitSearchPattern =
    /\b(search the web|web search|look up online|research online|find online|verify online|check online|use live data|up[- ]to[- ]date|latest news|breaking news)\b/i;
  const temporalFreshnessPattern =
    /\b(202[5-9]|203\d|latest|current|recent|newest|today|this week|this month|this year|right now|live score|standings|leaderboard|release date|changelog|pricing|price of|weather|forecast|stock price|schedule|lineup|winner|who won|what happened|version \d)\b/i;
  const liveDocsOrBrandPattern =
    /\b(current docs|official documentation|api reference|release notes|model list|benchmark|compare .+ 202\d)\b/i;

  if (explicitSearchPattern.test(text)) {
    return { shouldSearch: true, reason: 'User requested live web lookup.' };
  }
  if (temporalFreshnessPattern.test(text) || liveDocsOrBrandPattern.test(text)) {
    return {
      shouldSearch: true,
      reason: 'Prompt references current events, live info, or recent releases.',
    };
  }

  return { shouldSearch: false, reason: 'No current web lookup needed.' };
}

/**
 * Strips any HTML tags, script/style blocks, and control characters from untrusted
 * web snippets or titles before display or LLM grounding.
 */
export function sanitizeSearchText(raw: unknown, maxLen = 700): string {
  if (typeof raw !== 'string') return '';
  const withoutScripts = raw
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (withoutScripts.length <= maxLen) return withoutScripts;
  return `${withoutScripts.slice(0, Math.max(0, maxLen - 1)).trimEnd()}…`;
}

/**
 * Validates and normalizes an external source URL.
 * Rejects javascript:, data:, file:, relative paths, and embedded credentials.
 */
export function sanitizeSearchUrl(rawUrl: unknown): string | null {
  if (typeof rawUrl !== 'string') return null;
  const trimmed = rawUrl.trim();
  if (!trimmed || trimmed.length > 2048) return null;
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
      return null;
    }
    if (parsed.username || parsed.password) {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

/**
 * Canonicalizes a URL for deduplication (strips hash fragments, utm_* tracking params,
 * and trailing slash differences while preserving meaningful query params).
 */
export function normalizeUrlForDedupe(validUrl: string): string {
  try {
    const u = new URL(validUrl);
    u.hash = '';
    const keys = Array.from(u.searchParams.keys());
    for (const k of keys) {
      if (k.toLowerCase().startsWith('utm_') || k === 'fbclid' || k === 'gclid') {
        u.searchParams.delete(k);
      }
    }
    const qs = u.searchParams.toString();
    const cleanPath = u.pathname.replace(/\/+$/, '') || '/';
    return `${u.protocol}//${u.hostname.toLowerCase()}${cleanPath}${qs ? `?${qs}` : ''}`;
  } catch {
    return validUrl.toLowerCase();
  }
}

/**
 * Validates citation markers like [S1], [S2] inside a model's output against the
 * actual retrieved sources. Strips fabricated/unknown [S#] IDs and returns only
 * valid cited IDs.
 */
export function validateAndExtractCitations(
  text: string,
  sources: WebSearchSource[],
): {
  cleanedText: string;
  citedIds: string[];
  invalidCitedIds: string[];
} {
  const validSet = new Set(sources.map((s) => s.id.toUpperCase()));
  const citedSet = new Set<string>();
  const invalidSet = new Set<string>();

  const cleanedText = (text || '').replace(/\[(S\d+)\]/gi, (full, rawId: string) => {
    const id = rawId.toUpperCase();
    if (validSet.has(id)) {
      citedSet.add(id);
      return `[${id}]`;
    }
    invalidSet.add(id);
    return '';
  });

  // Preserve numeric source ordering ([S1], [S2], ...)
  const citedIds = sources
    .map((s) => s.id.toUpperCase())
    .filter((id) => citedSet.has(id));

  return {
    cleanedText: cleanedText.replace(/\s{2,}/g, ' ').trim(),
    citedIds,
    invalidCitedIds: Array.from(invalidSet),
  };
}
