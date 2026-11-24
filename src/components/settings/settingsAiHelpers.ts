import React, { useCallback, useEffect, useRef, useState } from 'react';
import type {
  AiProviderConfig,
  CatalogSource,
  MistUser as User,
  ModelCapabilities,
  ModelVerificationResult,
} from '../../types/mist';
import type { ModelHealthIncident } from '../../utils/aiErrors';
import {
  CUSTOM_GATEWAY_PRESETS,
  fetchLiveModelCatalog,
  type CustomGatewayId,
  type ModelCatalogItem,
} from '../../data/models';

export interface ProviderTestOutcome {
  ok: boolean;
  message: string;
  incident: ModelHealthIncident | null;
  verifiedModel: ModelVerificationResult | null;
}

function parseTestErrorMessage(data: { incident?: ModelHealthIncident; error?: string }): string {
  if (data.incident?.message) return data.incident.message;
  return data.error || 'Connection test failed.';
}

function buildVerifiedModel(
  draft: AiProviderConfig,
  data: { testedAt?: string; capabilities?: Partial<ModelCapabilities> }
): ModelVerificationResult {
  return {
    gatewayBaseUrl: draft.baseUrl ?? '',
    model: draft.model,
    verified: true,
    testedAt: data.testedAt ?? new Date().toISOString(),
    capabilities: data.capabilities,
  };
}

export async function executeProviderTest(
  draft: AiProviderConfig,
  user: User
): Promise<ProviderTestOutcome> {
  const idToken = await user.getIdToken();
  const resp = await fetch('/api/ai/test-provider', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${idToken}`,
    },
    body: JSON.stringify(draft),
  });
  const data = (await resp.json()) as {
    ok?: boolean;
    testedAt?: string;
    capabilities?: Partial<ModelCapabilities>;
    error?: string;
    incident?: ModelHealthIncident;
  };
  if (!resp.ok || !data.ok) {
    return {
      ok: false,
      message: parseTestErrorMessage(data),
      incident: data.incident ?? null,
      verifiedModel: null,
    };
  }
  return {
    ok: true,
    message: `${draft.name} (${draft.model}) responded cleanly and is verified.`,
    incident: null,
    verifiedModel: buildVerifiedModel(draft, data),
  };
}

export function resolveGatewayBaseUrl(nextGwId: CustomGatewayId, currentBaseUrl: string): string {
  const gw = CUSTOM_GATEWAY_PRESETS.find((g) => g.id === nextGwId);
  if (gw?.baseUrl) {
    return gw.baseUrl;
  }
  const isPresetBaseUrl = CUSTOM_GATEWAY_PRESETS.some((p) => p.baseUrl === currentBaseUrl);
  if (nextGwId === 'custom_url' && isPresetBaseUrl) {
    return '';
  }
  return currentBaseUrl;
}

export interface FetchCatalogParams {
  targetUrl: string;
  targetKey: string;
  forceRefresh?: boolean;
  user: User | null;
  signal: AbortSignal;
}

export interface SafeCatalogResult {
  models: ModelCatalogItem[] | null;
  source: CatalogSource;
  fetchedAt: string | null;
  isOutdatedFallback: boolean;
  error: string | null;
  note: string | null;
}

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return 'Unable to refresh model catalog.';
}

function getCatalogNote(cleaned: string): string | null {
  if (cleaned.length > 0) return 'Enter an https:// URL to fetch live models.';
  return null;
}

async function getUserAuthToken(user: User | null): Promise<string | undefined> {
  if (!user) return undefined;
  const token = await user.getIdToken().catch(() => undefined);
  return token ?? undefined;
}

export async function fetchModelCatalogSafe(
  params: FetchCatalogParams
): Promise<SafeCatalogResult> {
  const { targetUrl, targetKey, forceRefresh = false, user, signal } = params;
  const cleaned = targetUrl.trim();
  if (!cleaned.startsWith('https://')) {
    return {
      models: null,
      source: 'preset',
      fetchedAt: null,
      isOutdatedFallback: false,
      error: null,
      note: getCatalogNote(cleaned),
    };
  }

  try {
    const idToken = await getUserAuthToken(user);
    const res = await fetchLiveModelCatalog({
      baseUrl: cleaned,
      apiKey: targetKey,
      forceRefresh,
      idToken,
      signal,
    });
    return {
      models: res.models,
      source: res.source,
      fetchedAt: res.fetchedAt,
      isOutdatedFallback: Boolean(res.isOutdatedFallback),
      error: null,
      note: res.note ?? null,
    };
  } catch (err) {
    return {
      models: null,
      source: 'preset',
      fetchedAt: null,
      isOutdatedFallback: true,
      error: getErrorMessage(err),
      note: null,
    };
  }
}

function useCatalogTimer(
  baseUrl: string,
  apiKey: string,
  loadCatalog: (url: string, key: string, force?: boolean) => Promise<void>,
  abortRef: React.MutableRefObject<AbortController | null>
) {
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadCatalog(baseUrl, apiKey, false);
    }, 260);
    return () => {
      window.clearTimeout(timer);
      abortRef.current?.abort();
    };
  }, [baseUrl, apiKey, loadCatalog, abortRef]);
}

export function useModelCatalog(baseUrl: string, apiKey: string, user: User | null) {
  const [liveModels, setLiveModels] = useState<ModelCatalogItem[] | null>(null);
  const [catalogSource, setCatalogSource] = useState<CatalogSource>('preset');
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);
  const [isOutdatedFallback, setIsOutdatedFallback] = useState(false);
  const [isLoadingCatalog, setIsLoadingCatalog] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogNote, setCatalogNote] = useState<string | null>(null);

  const catalogAbortRef = useRef<AbortController | null>(null);
  const catalogSeqRef = useRef(0);

  const loadCatalog = useCallback(
    async (targetUrl: string, targetKey: string, forceRefresh = false) => {
      catalogAbortRef.current?.abort();
      const seq = ++catalogSeqRef.current;
      const controller = new AbortController();
      catalogAbortRef.current = controller;
      setIsLoadingCatalog(true);
      setCatalogError(null);

      try {
        const res = await fetchModelCatalogSafe({
          targetUrl,
          targetKey,
          forceRefresh,
          user,
          signal: controller.signal,
        });
        if (seq !== catalogSeqRef.current || controller.signal.aborted) return;
        if (res.models !== null) {
          setLiveModels(res.models);
        }
        setCatalogSource(res.source);
        setLastRefreshedAt(res.fetchedAt);
        setIsOutdatedFallback(res.isOutdatedFallback);
        setCatalogError(res.error);
        setCatalogNote(res.note);
      } finally {
        if (seq === catalogSeqRef.current) {
          setIsLoadingCatalog(false);
        }
      }
    },
    [user],
  );

  useCatalogTimer(baseUrl, apiKey, loadCatalog, catalogAbortRef);

  const resetCatalog = useCallback(() => {
    catalogAbortRef.current?.abort();
    catalogSeqRef.current += 1;
    setIsLoadingCatalog(false);
    setLiveModels(null);
    setCatalogSource('preset');
    setLastRefreshedAt(null);
    setIsOutdatedFallback(false);
    setCatalogError(null);
    setCatalogNote(null);
  }, []);

  return {
    liveModels,
    catalogSource,
    lastRefreshedAt,
    isOutdatedFallback,
    isLoadingCatalog,
    catalogError,
    catalogNote,
    loadCatalog,
    resetCatalog,
  };
}