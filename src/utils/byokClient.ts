import type { AiProviderConfig, ModelCapabilities } from '../types/mist';
import { DEFAULT_BYOK_CONFIG, normalizeProviderConfigToStudio } from '../data/models';
import { redactSecrets } from './aiErrors';
import {
  assertSafeExternalUrl,
  safeFetchExternal,
  SecurityValidationError,
  validateAiProviderConfig,
  type LookupFn,
} from './serverSecurity';

export class ProviderHttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function extractNumericStatus(err: unknown): number | null {
  if (err instanceof SecurityValidationError || err instanceof ProviderHttpError) {
    return err.status;
  }
  if (err && typeof err === 'object' && 'status' in err) {
    const status = (err as { status: unknown }).status;
    if (typeof status === 'number') return status;
  }
  return null;
}

const STATUS_PATTERNS: Array<[RegExp, number]> = [
  [/429|resource_exhausted/i, 429],
  [/503|unavailable/i, 503],
  [/502/i, 502],
  [/504|timed out/i, 504],
  [/401|403|api_key_invalid/i, 401],
  [/404|not_found/i, 404],
];

export function getHttpStatusFromError(err: unknown): number {
  const explicit = extractNumericStatus(err);
  if (explicit !== null) return explicit;
  const msg = err instanceof Error ? err.message : String(err);
  for (const [pattern, status] of STATUS_PATTERNS) {
    if (pattern.test(msg)) return status;
  }
  return 500;
}

export async function resolveByokRequestParams(
  rawConfig?: AiProviderConfig,
  options?: { skipDnsLookup?: boolean; lookupFn?: LookupFn },
): Promise<{
  config: AiProviderConfig;
  providerLabel: string;
  endpoint: string;
  headers: Record<string, string>;
}> {
  const validated = rawConfig ? validateAiProviderConfig(rawConfig) : DEFAULT_BYOK_CONFIG;
  const config = normalizeProviderConfigToStudio(validated);
  const providerLabel = config.name?.trim() || 'Custom BYOK';
  const apiKey = config.apiKey?.trim();
  if (!apiKey) {
    throw new ProviderHttpError(
      401,
      `Enter your BYOK API key for ${providerLabel} in Models & API Keys or Settings.`,
    );
  }
  if (!config.model?.trim()) {
    throw new ProviderHttpError(
      400,
      `Select or enter a valid model ID for ${providerLabel} before sending a request.`,
    );
  }
  const base = (config.baseUrl || '').trim().replace(/\/+$/, '');
  if (!base) {
    throw new ProviderHttpError(
      400,
      `${providerLabel} requires an HTTPS OpenAI-compatible Base URL (e.g. https://openrouter.ai/api/v1).`,
    );
  }

  await assertSafeExternalUrl(base, options);

  const endpoint = base.endsWith('/chat/completions') ? base : `${base}/chat/completions`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${apiKey}`,
  };
  if (endpoint.includes('openrouter.ai')) {
    headers['HTTP-Referer'] = process.env.APP_URL || 'http://localhost:3000';
    headers['X-Title'] = 'Mist Website Builder';
  }
  return { config, providerLabel, endpoint, headers };
}

export interface ByokCompletionOptions {
  config?: AiProviderConfig;
  messages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }>;
  jsonMode?: boolean;
  temperature?: number;
  maxTokens?: number;
  timeoutMs?: number;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
  skipDnsLookup?: boolean;
}

function extractPartText(part: unknown): string {
  if (typeof part === 'string') return part;
  if (!part || typeof part !== 'object') return '';
  const obj = part as { text?: unknown; content?: unknown };
  if (typeof obj.text === 'string') return obj.text;
  if (typeof obj.content === 'string') return obj.content;
  return '';
}

export function extractChoiceText(content: unknown): string {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content.map(extractPartText).join('');
  }
  return '';
}

async function retryOnFormatError(
  resp: Response,
  runRequest: (tokens: number, json: boolean) => Promise<Response>,
  maxTokens: number,
  providerLabel: string,
): Promise<Response> {
  const errPreview = redactSecrets(await resp.text());
  if (/response_format|json_object/i.test(errPreview)) {
    return runRequest(maxTokens, false);
  }
  throw new ProviderHttpError(400, `${providerLabel} error (400): ${errPreview.slice(0, 350)}`);
}

async function retryOnAffordabilityError(
  resp: Response,
  runRequest: (tokens: number, json: boolean) => Promise<Response>,
  params: { maxTokens: number; jsonMode: boolean; providerLabel: string },
): Promise<Response> {
  const errText = redactSecrets(await resp.text());
  const affordMatch = errText.match(/can only afford\s+(\d+)/i);
  const affordable = affordMatch ? Number(affordMatch[1]) : 0;
  if (affordable >= 1024 && params.maxTokens > affordable - 128) {
    return runRequest(Math.max(1024, affordable - 128), params.jsonMode);
  }
  throw new ProviderHttpError(402, `${params.providerLabel} error (402): ${errText.slice(0, 350)}`);
}

async function handleFormatOrAffordabilityRetry(
  initialResp: Response,
  runRequest: (tokens: number, json: boolean) => Promise<Response>,
  params: { maxTokens: number; jsonMode: boolean; providerLabel: string },
): Promise<Response> {
  if (initialResp.ok) return initialResp;
  if (initialResp.status === 400 && params.jsonMode) {
    return retryOnFormatError(initialResp, runRequest, params.maxTokens, params.providerLabel);
  }
  if (initialResp.status === 402) {
    return retryOnAffordabilityError(initialResp, runRequest, params);
  }
  return initialResp;
}

export async function callByokCompletionRaw(params: ByokCompletionOptions): Promise<string> {
  const {
    messages,
    jsonMode = true,
    temperature = 0.3,
    maxTokens = 10240,
    timeoutMs = 90_000,
    signal,
    fetchImpl,
    skipDnsLookup,
  } = params;

  if (signal?.aborted) {
    throw new ProviderHttpError(499, 'Client disconnected before upstream request started.');
  }

  const { config, providerLabel, endpoint, headers } = await resolveByokRequestParams(
    params.config,
    { skipDnsLookup },
  );

  const runRequest = async (limitTokens: number, useJsonFormat: boolean) => {
    const body: Record<string, unknown> = {
      model: config.model,
      messages,
      temperature,
      max_tokens: limitTokens,
    };
    if (useJsonFormat) {
      body.response_format = { type: 'json_object' };
    }
    return safeFetchExternal(endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      timeoutMs,
      parentSignal: signal,
      fetchImpl,
      skipDnsLookup,
    });
  };

  let resp = await runRequest(maxTokens, jsonMode);
  resp = await handleFormatOrAffordabilityRetry(resp, runRequest, { maxTokens, jsonMode, providerLabel });

  if (!resp.ok) {
    const errText = redactSecrets(await resp.text());
    throw new ProviderHttpError(
      resp.status,
      `${providerLabel} error (${resp.status}): ${errText.slice(0, 350)}`,
    );
  }

  const data = (await resp.json()) as {
    choices?: Array<{ message?: { content?: unknown } }>;
  };
  const content = extractChoiceText(data.choices?.[0]?.message?.content);
  if (!content) {
    throw new ProviderHttpError(502, `${providerLabel} returned an empty response.`);
  }
  return content;
}

export interface StreamByokOptions extends ByokCompletionOptions {
  connectTimeoutMs?: number;
  idleTimeoutMs?: number;
  totalTimeoutMs?: number;
  onDelta: (accumulatedText: string) => void;
}

/**
 * Streams a chat completion over SSE with:
 * - SSRF/redirect protection
 * - Client disconnect cancellation (cancels upstream fetch & stream reader immediately)
 * - Connect, chunk-inactivity (idle), and total timeout watchdogs
 * - Proper flushing of trailing incomplete SSE lines at EOF
 */
export async function streamByokCompletion(params: StreamByokOptions): Promise<string> {
  const {
    messages,
    jsonMode = true,
    temperature = 0.3,
    maxTokens = 12288,
    connectTimeoutMs = 25_000,
    idleTimeoutMs = 45_000,
    totalTimeoutMs = 180_000,
    signal,
    fetchImpl,
    skipDnsLookup,
    onDelta,
  } = params;

  const { config, providerLabel, endpoint, headers } = await resolveByokRequestParams(
    params.config,
    { skipDnsLookup },
  );

  const streamAbort = new AbortController();
  let abortedReason: 'disconnect' | 'idle_timeout' | 'total_timeout' | null = null;

  const onCallerAbort = () => {
    abortedReason = 'disconnect';
    streamAbort.abort();
  };
  if (signal) {
    if (signal.aborted) {
      throw new ProviderHttpError(499, 'Client disconnected before upstream request started.');
    }
    signal.addEventListener('abort', onCallerAbort, { once: true });
  }

  const totalTimer = setTimeout(() => {
    abortedReason = 'total_timeout';
    streamAbort.abort();
  }, totalTimeoutMs);

  let idleTimer: ReturnType<typeof setTimeout> | null = null;
  const resetIdleTimer = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      abortedReason = 'idle_timeout';
      streamAbort.abort();
    }, idleTimeoutMs);
  };

  try {
    const runStreamRequest = async (limitTokens: number, useJsonFormat: boolean) => {
      const body: Record<string, unknown> = {
        model: config.model,
        messages,
        temperature,
        max_tokens: limitTokens,
        stream: true,
      };
      if (useJsonFormat) {
        body.response_format = { type: 'json_object' };
      }
      return safeFetchExternal(endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        timeoutMs: connectTimeoutMs,
        parentSignal: streamAbort.signal,
        fetchImpl,
        skipDnsLookup,
      });
    };

    let resp = await runStreamRequest(maxTokens, jsonMode);
    if (!resp.ok && resp.status === 400 && jsonMode) {
      const errPreview = redactSecrets(await resp.text());
      if (
        errPreview.toLowerCase().includes('response_format') ||
        errPreview.toLowerCase().includes('json_object')
      ) {
        resp = await runStreamRequest(maxTokens, false);
      } else {
        throw new ProviderHttpError(400, `${providerLabel} error (400): ${errPreview.slice(0, 350)}`);
      }
    }

    if (!resp.ok && resp.status === 402) {
      const errText = redactSecrets(await resp.text());
      const affordMatch = errText.match(/can only afford\s+(\d+)/i);
      const affordable = affordMatch ? Number(affordMatch[1]) : 0;
      if (affordable >= 1024 && maxTokens > affordable - 128) {
        resp = await runStreamRequest(Math.max(1024, affordable - 128), jsonMode);
      } else {
        throw new ProviderHttpError(402, `${providerLabel} error (402): ${errText.slice(0, 350)}`);
      }
    }

    if (!resp.ok) {
      const errText = redactSecrets(await resp.text());
      throw new ProviderHttpError(
        resp.status,
        `${providerLabel} error (${resp.status}): ${errText.slice(0, 350)}`,
      );
    }

    if (!resp.body) {
      const text = await callByokCompletionRaw({
        config,
        messages,
        jsonMode,
        temperature,
        maxTokens,
        timeoutMs: totalTimeoutMs,
        signal: streamAbort.signal,
        fetchImpl,
        skipDnsLookup,
      });
      onDelta(text);
      return text;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let sseBuffer = '';
    let fullContent = '';

    const processLine = (rawLine: string) => {
      const line = rawLine.trim();
      if (!line.startsWith('data:')) return;
      const payload = line.slice(5).trim();
      if (!payload || payload === '[DONE]') return;
      try {
        const parsed = JSON.parse(payload) as {
          choices?: Array<{ delta?: { content?: unknown }; message?: { content?: unknown } }>;
          error?: { message?: string };
        };
        if (parsed.error?.message) {
          throw new ProviderHttpError(502, redactSecrets(parsed.error.message));
        }
        const delta = extractChoiceText(
          parsed.choices?.[0]?.delta?.content ?? parsed.choices?.[0]?.message?.content,
        );
        if (delta) {
          fullContent += delta;
          onDelta(fullContent);
        }
      } catch (parseErr) {
        if (parseErr instanceof ProviderHttpError) throw parseErr;
        // Ignore partial non-JSON keepalive comments
      }
    };

    try {
      resetIdleTimer();
      while (true) {
        if (streamAbort.signal.aborted) {
          await reader.cancel().catch(() => {});
          break;
        }

        const readResult = await Promise.race([
          reader.read(),
          new Promise<never>((_, reject) => {
            const onAbort = () => reject(new Error('__STREAM_ABORTED__'));
            streamAbort.signal.addEventListener('abort', onAbort, { once: true });
          }),
        ]);

        resetIdleTimer();
        const { done, value } = readResult;
        if (done) break;
        sseBuffer += decoder.decode(value, { stream: true });

        let nlIndex: number;
        while ((nlIndex = sseBuffer.indexOf('\n')) !== -1) {
          const line = sseBuffer.slice(0, nlIndex);
          sseBuffer = sseBuffer.slice(nlIndex + 1);
          processLine(line);
        }
      }

      // Flush remaining decoder bytes + trailing incomplete line without trailing newline
      sseBuffer += decoder.decode();
      if (sseBuffer.trim()) {
        processLine(sseBuffer);
        sseBuffer = '';
      }
    } catch (err) {
      await reader.cancel().catch(() => {});
      if (abortedReason === 'disconnect') {
        throw new ProviderHttpError(499, 'Request cancelled by client disconnect.');
      }
      if (abortedReason === 'idle_timeout') {
        throw new ProviderHttpError(
          504,
          `${providerLabel} stream stalled with no data for ${Math.round(idleTimeoutMs / 1000)}s.`,
        );
      }
      if (abortedReason === 'total_timeout') {
        throw new ProviderHttpError(
          504,
          `${providerLabel} stream exceeded the ${Math.round(totalTimeoutMs / 1000)}s total timeout.`,
        );
      }
      throw err;
    }

    if (abortedReason === 'disconnect') {
      throw new ProviderHttpError(499, 'Request cancelled by client disconnect.');
    }
    if (abortedReason === 'idle_timeout') {
      throw new ProviderHttpError(
        504,
        `${providerLabel} stream stalled with no data for ${Math.round(idleTimeoutMs / 1000)}s.`,
      );
    }
    if (abortedReason === 'total_timeout') {
      throw new ProviderHttpError(
        504,
        `${providerLabel} stream exceeded the ${Math.round(totalTimeoutMs / 1000)}s total timeout.`,
      );
    }

    if (!fullContent.trim()) {
      throw new ProviderHttpError(502, `${providerLabel} returned an empty stream.`);
    }
    return fullContent;
  } finally {
    if (idleTimer) clearTimeout(idleTimer);
    clearTimeout(totalTimer);
    if (signal) signal.removeEventListener('abort', onCallerAbort);
  }
}

async function handleProbeFailure(
  resp: Response,
  norm: AiProviderConfig,
  options?: { fetchImpl?: typeof fetch; skipDnsLookup?: boolean; signal?: AbortSignal },
): Promise<boolean> {
  const errText = redactSecrets(await resp.text());
  if (resp.status === 400 && /response_format|json_object/i.test(errText)) {
    await callByokCompletionRaw({
      config: norm,
      messages: [{ role: 'user', content: 'Reply with OK' }],
      jsonMode: false,
      maxTokens: 24,
      timeoutMs: 25_000,
      signal: options?.signal,
      fetchImpl: options?.fetchImpl,
      skipDnsLookup: options?.skipDnsLookup,
    });
    return false;
  }
  throw new ProviderHttpError(resp.status, `${norm.name || 'Provider'} error (${resp.status}): ${errText.slice(0, 300)}`);
}

async function probeJsonOrTextGeneration(
  norm: AiProviderConfig,
  endpoint: string,
  headers: Record<string, string>,
  options?: { fetchImpl?: typeof fetch; skipDnsLookup?: boolean; signal?: AbortSignal },
): Promise<boolean | 'unknown'> {
  const resp = await safeFetchExternal(endpoint, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      model: norm.model,
      messages: [
        { role: 'system', content: 'Respond strictly with valid JSON.' },
        { role: 'user', content: 'Return {"ok":true}' },
      ],
      response_format: { type: 'json_object' },
      max_tokens: 48,
      temperature: 0,
    }),
    timeoutMs: 25_000,
    parentSignal: options?.signal,
    fetchImpl: options?.fetchImpl,
    skipDnsLookup: options?.skipDnsLookup,
  });

  if (resp.ok) {
    const data = (await resp.json()) as { choices?: Array<{ message?: { content?: string } }> };
    const text = data.choices?.[0]?.message?.content || '';
    if (!text.trim()) {
      throw new ProviderHttpError(502, `${norm.name || 'Provider'} returned an empty test response.`);
    }
    return true;
  }

  return handleProbeFailure(resp, norm, options);
}

export async function probeProviderCapabilities(
  config: AiProviderConfig,
  options?: { fetchImpl?: typeof fetch; skipDnsLookup?: boolean; signal?: AbortSignal },
): Promise<Partial<ModelCapabilities>> {
  const { config: norm, endpoint, headers } = await resolveByokRequestParams(config, {
    skipDnsLookup: options?.skipDnsLookup,
  });

  let jsonSupported: boolean | 'unknown' = 'unknown';
  try {
    jsonSupported = await probeJsonOrTextGeneration(norm, endpoint, headers, options);
  } catch (err) {
    if (err instanceof ProviderHttpError || err instanceof SecurityValidationError) throw err;
    throw new ProviderHttpError(502, err instanceof Error ? err.message : String(err));
  }

  return {
    textGeneration: true,
    jsonOutput: jsonSupported,
  };
}
