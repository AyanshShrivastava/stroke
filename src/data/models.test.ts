import test from 'node:test';
import assert from 'node:assert/strict';
import {
  clearClientModelCatalogCache,
  createManualModelEntry,
  CUSTOM_GATEWAY_PRESETS,
  DEFAULT_BYOK_CONFIG,
  detectGatewayFromBaseUrl,
  fetchLiveModelCatalog,
  findModelEntry,
  getDefaultModelForProvider,
  getModelDisplayLabel,
  normalizeProviderConfigToStudio,
  promptRequestsAi,
  PROVIDER_CATALOG,
  shouldEnableAppAi,
} from './models';

test('DEFAULT_BYOK_CONFIG configures OpenRouter free auto-router without hardcoded keys or outdated IDs', () => {
  assert.equal(DEFAULT_BYOK_CONFIG.provider, 'custom');
  assert.equal(DEFAULT_BYOK_CONFIG.name, 'OpenRouter');
  assert.equal(DEFAULT_BYOK_CONFIG.baseUrl, 'https://openrouter.ai/api/v1');
  assert.equal(DEFAULT_BYOK_CONFIG.apiKey, '');
  assert.equal(DEFAULT_BYOK_CONFIG.model, 'openrouter/free');
});

test('Gateway presets never fabricate hardcoded Groq/Gemini/NVIDIA free billing guesses or deprecated Gemini 2.5 Pro defaults', () => {
  const gatewayIds = CUSTOM_GATEWAY_PRESETS.map((g) => g.id);
  assert.ok(gatewayIds.includes('openrouter'));
  assert.ok(gatewayIds.includes('groq'));
  assert.ok(gatewayIds.includes('gemini_byok'));
  assert.ok(gatewayIds.includes('nvidia'));
  assert.ok(gatewayIds.includes('openai'));
  assert.ok(gatewayIds.includes('custom_url'));

  for (const gwId of ['groq', 'gemini_byok', 'nvidia', 'openai', 'custom_url'] as const) {
    const preset = CUSTOM_GATEWAY_PRESETS.find((g) => g.id === gwId)!;
    assert.equal(
      preset.models.length,
      0,
      `Expected ${gwId} preset to avoid stale hardcoded models and rely on live /models`,
    );
  }

  const orPreset = CUSTOM_GATEWAY_PRESETS.find((g) => g.id === 'openrouter')!;
  assert.deepEqual(
    orPreset.models.map((m) => m.id),
    ['openrouter/free'],
  );
  assert.equal(orPreset.models[0].billing, 'free');
});

test('normalizeProviderConfigToStudio preserves valid current Gemini IDs like gemini-4-hydrogen and never swaps to gemini-2.5-flash', () => {
  const preservedHydrogen = normalizeProviderConfigToStudio({
    provider: 'gemini',
    model: 'gemini-4-hydrogen',
    apiKey: 'AIza-test',
  });
  assert.equal(preservedHydrogen.provider, 'custom');
  assert.equal(preservedHydrogen.name, 'Gemini (BYOK)');
  assert.equal(preservedHydrogen.model, 'gemini-4-hydrogen');
  assert.equal(
    preservedHydrogen.baseUrl,
    'https://generativelanguage.googleapis.com/v1beta/openai',
  );
  assert.equal(detectGatewayFromBaseUrl(preservedHydrogen.baseUrl), 'gemini_byok');

  const preservedArgon = normalizeProviderConfigToStudio({
    provider: 'custom',
    name: 'Gemini (BYOK)',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    model: 'gemini-4-argon',
    apiKey: 'AIza-test',
  });
  assert.equal(preservedArgon.model, 'gemini-4-argon');

  const preservedCarbon = normalizeProviderConfigToStudio({
    provider: 'custom',
    name: 'Gemini (BYOK)',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    model: 'gemini-4-carbon',
    apiKey: 'AIza-test',
  });
  assert.equal(preservedCarbon.model, 'gemini-4-carbon');

  // Empty Gemini selection stays empty rather than silently selecting deprecated gemini-2.5-pro or 2.5-flash
  const emptyGemini = normalizeProviderConfigToStudio({
    provider: 'gemini',
    model: '',
    apiKey: 'AIza-test',
  });
  assert.equal(emptyGemini.model, '');

  const normalizedOr = normalizeProviderConfigToStudio({
    provider: 'openrouter',
    model: 'openai/gpt-4.1',
    apiKey: 'sk-or-test',
    sessionOnlyKey: true,
  });
  assert.equal(normalizedOr.provider, 'custom');
  assert.equal(normalizedOr.name, 'OpenRouter');
  assert.equal(normalizedOr.baseUrl, 'https://openrouter.ai/api/v1');
  assert.equal(normalizedOr.model, 'openai/gpt-4.1');
  assert.equal(normalizedOr.sessionOnlyKey, true);
  assert.equal(detectGatewayFromBaseUrl(normalizedOr.baseUrl), 'openrouter');

  const normalizedGroq = normalizeProviderConfigToStudio({
    provider: 'groq',
    model: 'llama-3.3-70b-versatile',
    apiKey: 'gsk-test',
  });
  assert.equal(normalizedGroq.provider, 'custom');
  assert.equal(normalizedGroq.name, 'Groq');
  assert.equal(normalizedGroq.baseUrl, 'https://api.groq.com/openai/v1');
  assert.equal(normalizedGroq.model, 'llama-3.3-70b-versatile');
  assert.equal(normalizedGroq.sessionOnlyKey, false);
});

test('createManualModelEntry marks custom manual models as Unverified with Unknown billing', () => {
  const manual = createManualModelEntry('gemini-4-hydrogen');
  assert.equal(manual.id, 'gemini-4-hydrogen');
  assert.equal(manual.status, 'unverified');
  assert.equal(manual.billing, 'unknown');
  assert.equal(manual.billingLabel, 'Unknown');
  assert.equal(manual.capabilities.textGeneration, true);
  assert.equal(manual.capabilities.jsonOutput, 'unknown');
  assert.equal(manual.capabilities.streaming, 'unknown');
});

test('getModelDisplayLabel, getDefaultModelForProvider & findModelEntry resolve accurately without inventing metadata', () => {
  assert.equal(getDefaultModelForProvider('custom'), 'openrouter/free');
  assert.equal(PROVIDER_CATALOG.custom.requiresUserKey, true);
  assert.equal(
    getModelDisplayLabel('custom', 'my-org/custom-coder-v1'),
    'my-org/custom-coder-v1',
  );
  assert.equal(
    findModelEntry('custom', 'openrouter/free', 'https://openrouter.ai/api/v1')?.billing,
    'free',
  );
  // Unknown un-fetched custom model returns undefined unless live catalog is supplied
  assert.equal(
    findModelEntry('custom', 'gemini-4-hydrogen', 'https://generativelanguage.googleapis.com/v1beta/openai'),
    undefined,
  );
});

test('fetchLiveModelCatalog caches live responses, sends auth headers via POST, and aborts cleanly on provider switch', async () => {
  clearClientModelCatalogCache();
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;

  try {
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      fetchCalls++;
      const url = typeof input === 'string' ? input : input.toString();
      assert.equal(url, '/api/ai/models');
      assert.equal(init?.method, 'POST');
      const headers = (init?.headers || {}) as Record<string, string>;
      assert.equal(headers.Authorization, 'Bearer firebase-id-token');

      if (init?.signal?.aborted) {
        const abortErr = new Error('Aborted');
        abortErr.name = 'AbortError';
        throw abortErr;
      }

      return new Response(
        JSON.stringify({
          gateway: 'gemini_byok',
          source: 'live',
          fetchedAt: '2026-11-15T12:00:00.000Z',
          models: [
            {
              id: 'gemini-4-hydrogen',
              label: 'Gemini 4 Hydrogen',
              summary: 'Provider billed',
              tier: 'Default',
              billing: 'provider_billed',
              billingLabel: 'Provider billed',
              status: 'active',
              capabilities: {
                textGeneration: true,
                jsonOutput: 'unknown',
                streaming: true,
                imageInput: 'unknown',
                toolCalling: 'unknown',
              },
              isLiveFetched: true,
            },
          ],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }) as typeof fetch;

    const liveRes = await fetchLiveModelCatalog({
      baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
      apiKey: 'AIza-mock',
      idToken: 'firebase-id-token',
    });
    assert.equal(liveRes.source, 'live');
    assert.equal(liveRes.models[0].id, 'gemini-4-hydrogen');
    assert.equal(fetchCalls, 1);

    // Second call hits client cache -> source === 'cached', zero extra network fetches
    const cachedRes = await fetchLiveModelCatalog({
      baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
      apiKey: 'AIza-mock',
      idToken: 'firebase-id-token',
    });
    assert.equal(cachedRes.source, 'cached');
    assert.equal(fetchCalls, 1);

    // Pre-aborted signal on provider switch never returns stale data
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(
      () =>
        fetchLiveModelCatalog({
          baseUrl: 'https://api.groq.com/openai/v1',
          apiKey: 'gsk-mock',
          idToken: 'firebase-id-token',
          signal: controller.signal,
        }),
      (err: unknown) => err instanceof Error && err.name === 'AbortError',
    );
  } finally {
    globalThis.fetch = originalFetch;
    clearClientModelCatalogCache();
  }
});

test('promptRequestsAi and shouldEnableAppAi enable App AI strictly when requested unless overridden', () => {
  assert.equal(promptRequestsAi('Subway Surfers 2D runner with trains and coins'), false);
  assert.equal(promptRequestsAi('Minimalist coffee roastery landing page with detail view'), false);
  assert.equal(promptRequestsAi('Interactive Three.js 3D product studio with OrbitControls'), false);

  assert.equal(promptRequestsAi('Build an AI writing workspace with an assistant'), true);
  assert.equal(promptRequestsAi('Create a customer portal with an embedded chatbot'), true);
  assert.equal(promptRequestsAi('Add live LLM summarization using /api/app-ai'), true);

  assert.equal(shouldEnableAppAi('Subway Surfers 2D game', 'on_request'), false);
  assert.equal(shouldEnableAppAi('Build a fitness app with an AI coach', 'on_request'), true);
  assert.equal(shouldEnableAppAi('Subway Surfers 2D game', 'always'), true);
  assert.equal(shouldEnableAppAi('Build a site with an AI chatbot', 'off'), false);
  assert.equal(shouldEnableAppAi('Change button color', 'on_request', true), true);
});
