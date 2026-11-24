import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {
  assertSafeExternalUrl,
  assertValidVaultSecret,
  createPreviewAiSession,
  deriveUserVaultKey,
  isPrivateOrReservedIp,
  migrateUserVaultCiphertext,
  resolvePreviewAiSession,
  revokeAllUserPreviewSessions,
  revokePreviewAiSession,
  safeFetchExternal,
  sanitizeErrorMessage,
  sealUserVaultPayload,
  SecurityValidationError,
  unsealUserVaultPayload,
  validateExternalUrlSyntax,
  validateProjectFilesPayload,
  validateVaultPayload,
  verifyClerkAuthHeader,
  createClerkAuthMiddleware,
  createEdgeOriginSecretMiddleware,
} from './serverSecurity';
import {
  clearServerCatalogCache,
  fetchGatewayModelsCatalog,
  mapGeminiModels,
  mapGenericOpenAiCompatModels,
  mapGroqModels,
  mapOpenRouterModels,
} from './modelCatalogServer';
import { extractChoiceText, ProviderHttpError, streamByokCompletion } from './byokClient';
import { redactSecrets } from './aiErrors';
import { chunkOperations } from '../firebase/batchOps';
import { buildExportManifest, maskApiKey, suggestShortSlug } from './projectOps';

test('SSRF protection blocks private/loopback IPs, DNS rebinding resolutions, and HTTP redirects', async () => {
  assert.equal(isPrivateOrReservedIp('127.0.0.1'), true);
  assert.equal(isPrivateOrReservedIp('10.20.30.40'), true);
  assert.equal(isPrivateOrReservedIp('169.254.169.254'), true);
  assert.equal(isPrivateOrReservedIp('172.16.5.4'), true);
  assert.equal(isPrivateOrReservedIp('192.168.1.1'), true);
  assert.equal(isPrivateOrReservedIp('::1'), true);
  assert.equal(isPrivateOrReservedIp('8.8.8.8'), false);

  const blockedUrls = [
    'http://openrouter.ai/api/v1',
    'https://localhost:3000/v1',
    'https://127.0.0.1/v1',
    'https://169.254.169.254/latest/meta-data',
    'https://10.0.0.5/v1',
    'https://metadata.google.internal/computeMetadata/v1',
    'https://user:pass@openrouter.ai/api/v1',
    'file:///etc/passwd',
  ];

  for (const url of blockedUrls) {
    assert.throws(
      () => validateExternalUrlSyntax(url),
      SecurityValidationError,
      `Expected SSRF rejection for ${url}`,
    );
  }

  // Simulated DNS rebinding: public hostname resolving to internal IP
  await assert.rejects(
    () =>
      assertSafeExternalUrl('https://rebind.attacker.example/v1', {
        lookupFn: async () => [{ address: '169.254.169.254', family: 4 }],
      }),
    SecurityValidationError,
  );

  // Redirect blocking: safeFetchExternal uses redirect: 'error'
  await assert.rejects(
    () =>
      safeFetchExternal('https://openrouter.ai/api/v1/models', {
        skipDnsLookup: true,
        fetchImpl: (async (_url, init) => {
          assert.equal(init?.redirect, 'error');
          throw new TypeError('unexpected redirect');
        }) as typeof fetch,
      }),
    (err: unknown) =>
      err instanceof SecurityValidationError && err.message.includes('Blocked HTTP redirect'),
  );
});

test('Preview AI session vault binds sessions to owner UID and enforces ownership on revoke', () => {
  const { token, expiresAt } = createPreviewAiSession(
    {
      provider: 'custom',
      name: 'OpenRouter',
      baseUrl: 'https://openrouter.ai/api/v1',
      model: 'openrouter/free',
      apiKey: 'sk-or-v1-supersecret-preview-key',
    },
    'uid-owner-1',
  );

  assert.ok(token.startsWith('mist_sess_'));
  assert.ok(Date.parse(expiresAt) > Date.now());

  const resolved = resolvePreviewAiSession(token);
  assert.equal(resolved?.apiKey, 'sk-or-v1-supersecret-preview-key');

  assert.throws(
    () => revokePreviewAiSession(token, 'uid-other-user'),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 403,
  );
  assert.throws(
    () => revokePreviewAiSession(token, undefined),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 401,
  );

  assert.equal(revokePreviewAiSession(token, 'uid-owner-1'), true);
  assert.equal(resolvePreviewAiSession(token), null);
});

function toBase64Url(input: Buffer | string): string {
  return Buffer.from(input)
    .toString('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
}

function signTestJwt(params: {
  privateKey: crypto.KeyObject;
  kid: string;
  payload: Record<string, unknown>;
}): string {
  const header = toBase64Url(JSON.stringify({ alg: 'RS256', kid: params.kid, typ: 'JWT' }));
  const body = toBase64Url(JSON.stringify(params.payload));
  const signer = crypto.createSign('RSA-SHA256');
  signer.update(`${header}.${body}`);
  signer.end();
  const sig = toBase64Url(signer.sign(params.privateKey));
  return `${header}.${body}.${sig}`;
}

test('Clerk Auth & Edge Origin Secret enforce strict verification and rejection', async () => {
  // 1. Missing header
  await assert.rejects(
    () => verifyClerkAuthHeader(undefined),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 401,
  );

  // 2. Malformed token form
  await assert.rejects(
    () => verifyClerkAuthHeader('Bearer invalid-not-jwt'),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 401,
  );

  // 3. Edge Origin Secret middleware tests
  const edgeMiddleware = createEdgeOriginSecretMiddleware({ expectedSecret: 'super-secret-edge-key-123' });

  // Missing secret -> 403
  let statusMissing = 0;
  let jsonMissing: any = null;
  const reqMissing = { headers: {} } as any;
  const resMissing = {
    status: (s: number) => {
      statusMissing = s;
      return { json: (j: any) => { jsonMissing = j; } };
    },
  } as any;
  edgeMiddleware(reqMissing, resMissing, () => {});
  assert.equal(statusMissing, 403);
  assert.ok(jsonMissing.error.includes('Direct access to origin is prohibited'));

  // Tampered / wrong secret -> 403
  let statusWrong = 0;
  const reqWrong = { headers: { 'x-mist-edge-secret': 'wrong-secret' } } as any;
  const resWrong = {
    status: (s: number) => {
      statusWrong = s;
      return { json: () => {} };
    },
  } as any;
  edgeMiddleware(reqWrong, resWrong, () => {});
  assert.equal(statusWrong, 403);

  // Valid secret -> passes
  let nextCalled = false;
  const reqValid = { headers: { 'x-mist-edge-secret': 'super-secret-edge-key-123' } } as any;
  const resValid = {} as any;
  edgeMiddleware(reqValid, resValid, () => {
    nextCalled = true;
  });
  assert.equal(nextCalled, true);
});

test('Model mappers avoid name-based billing guesses, preserve new Gemini models, track capabilities, and flag deprecated models', () => {
  const orModels = mapOpenRouterModels([
    {
      id: 'nvidia/llama-3.3-nemotron-super-49b-v1:free',
      name: 'NVIDIA: Llama 3.3 Nemotron Super 49B v1 (free)',
      context_length: 131072,
      pricing: { prompt: '0', completion: '0' },
      architecture: { input_modalities: ['text'], output_modalities: ['text'] },
      supported_parameters: ['response_format', 'tools'],
    },
    {
      id: 'openai/gpt-4.1',
      name: 'OpenAI: GPT-4.1',
      context_length: 1047576,
      pricing: { prompt: '0.000002', completion: '0.000008' },
      architecture: { input_modalities: ['text', 'image'], output_modalities: ['text'] },
      supported_parameters: ['structured_outputs', 'tools'],
    },
    {
      id: 'vendor/unknown-price-preview',
      name: 'Vendor Preview',
      architecture: { output_modalities: ['text'] },
    },
    {
      id: 'black-forest-labs/flux.1-schnell',
      name: 'FLUX.1 Schnell',
      architecture: { output_modalities: ['image'] },
    },
  ]);

  assert.equal(orModels[0].id, 'openrouter/free');
  const nemotron = orModels.find((m) => m.id.includes('nemotron'))!;
  assert.equal(nemotron.billing, 'free');
  assert.equal(nemotron.capabilities.jsonOutput, true);
  assert.equal(nemotron.capabilities.imageInput, false);
  assert.equal(nemotron.capabilities.toolCalling, true);

  const gpt41 = orModels.find((m) => m.id === 'openai/gpt-4.1')!;
  assert.equal(gpt41.billing, 'paid');
  assert.equal(gpt41.capabilities.imageInput, true);
  assert.ok(gpt41.pricingSummary?.includes('$2.00/1M'));

  const unknownPriced = orModels.find((m) => m.id === 'vendor/unknown-price-preview')!;
  assert.equal(unknownPriced.billing, 'unknown');
  assert.equal(unknownPriced.billingLabel, 'Unknown');
  assert.equal(unknownPriced.status, 'preview');
  assert.equal(orModels.some((m) => m.id.includes('flux')), false);

  // Groq never fabricates "Free" guesses from model IDs
  const groqModels = mapGroqModels([
    { id: 'llama-3.3-70b-versatile', active: true, context_window: 131072 },
    { id: 'whisper-large-v3', active: true },
    { id: 'legacy-model', active: false, deprecated: true },
  ]);
  assert.equal(groqModels.some((m) => m.id.includes('whisper')), false);
  assert.equal(groqModels.find((m) => m.id === 'llama-3.3-70b-versatile')?.billing, 'provider_billed');
  assert.equal(groqModels.find((m) => m.id === 'legacy-model')?.status, 'retired');

  // NVIDIA & custom generic gateways never label non-OpenAI models as "free"
  const nvidiaModels = mapGenericOpenAiCompatModels(
    [{ id: 'nvidia/llama-3.1-nemotron-ultra-253b-v1', active: true }],
    'nvidia',
    'NVIDIA NIM',
  );
  assert.equal(nvidiaModels[0].billing, 'provider_billed');
  assert.equal(nvidiaModels[0].billingLabel, 'Provider billed');

  const customModels = mapGenericOpenAiCompatModels(
    [{ id: 'my-local-model' }],
    'custom_url',
    'My Proxy',
  );
  assert.equal(customModels[0].billing, 'unknown');
  assert.equal(customModels[0].billingLabel, 'Unknown');

  // Gemini checks supportedGenerationMethods, preserves gemini-4-hydrogen/argon/carbon without claiming they are free,
  // and marks gemini-2.5-pro as deprecated
  const geminiModels = mapGeminiModels([
    {
      name: 'models/gemini-4-hydrogen',
      displayName: 'Gemini 4 Hydrogen',
      inputTokenLimit: 1048576,
      supportedGenerationMethods: ['generateContent', 'streamGenerateContent'],
    },
    {
      name: 'models/gemini-4-argon',
      displayName: 'Gemini 4 Argon',
      supportedGenerationMethods: ['generateContent'],
    },
    {
      name: 'models/gemini-4-carbon',
      displayName: 'Gemini 4 Carbon',
      supportedGenerationMethods: ['generateContent'],
    },
    {
      name: 'models/gemini-2.5-pro',
      displayName: 'Gemini 2.5 Pro',
      supportedGenerationMethods: ['generateContent'],
    },
    {
      name: 'models/text-embedding-004',
      supportedGenerationMethods: ['embedContent'],
    },
  ]);
  assert.equal(geminiModels.length, 4);
  const hydrogen = geminiModels.find((m) => m.id === 'gemini-4-hydrogen')!;
  assert.equal(hydrogen.status, 'active');
  assert.equal(hydrogen.billing, 'provider_billed');
  assert.equal(hydrogen.capabilities.streaming, true);
  assert.equal(geminiModels.find((m) => m.id === 'gemini-4-argon')?.billing, 'provider_billed');
  assert.equal(geminiModels.find((m) => m.id === 'gemini-4-carbon')?.billing, 'provider_billed');
  assert.equal(geminiModels.find((m) => m.id === 'gemini-2.5-pro')?.status, 'deprecated');
});

test('fetchGatewayModelsCatalog hits live mocked APIs, caches results, and does not leak stale state', async () => {
  clearServerCatalogCache();
  let calls = 0;
  const mockGeminiFetch = (async () => {
    calls++;
    return new Response(
      JSON.stringify({
        models: [
          {
            name: 'models/gemini-4-hydrogen',
            displayName: 'Gemini 4 Hydrogen',
            supportedGenerationMethods: ['generateContent', 'streamGenerateContent'],
          },
        ],
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    );
  }) as typeof fetch;

  const live = await fetchGatewayModelsCatalog({
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    apiKey: 'AIza-test-key',
    fetchImpl: mockGeminiFetch,
    skipDnsLookup: true,
  });
  assert.equal(live.source, 'live');
  assert.equal(live.models[0].id, 'gemini-4-hydrogen');
  assert.equal(calls, 1);

  const cached = await fetchGatewayModelsCatalog({
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    apiKey: 'AIza-test-key',
    fetchImpl: mockGeminiFetch,
    skipDnsLookup: true,
  });
  assert.equal(cached.source, 'cached');
  assert.equal(calls, 1);
  clearServerCatalogCache();
});

test('chunkOperations splits large Firestore project writes cleanly within the 400-op safe limit', () => {
  const ops = Array.from({ length: 850 }, (_, i) => ({ id: i }));
  const batches = chunkOperations(ops);
  assert.equal(batches.length, 3);
  assert.equal(batches[0].length, 400);
  assert.equal(batches[1].length, 400);
  assert.equal(batches[2].length, 50);
  assert.deepEqual(chunkOperations([]), []);
});

test('validateProjectFilesPayload enforces path safety and count/size limits', () => {
  assert.throws(
    () => validateProjectFilesPayload([{ path: '../secret.ts', content: 'x' }]),
    SecurityValidationError,
  );
  assert.throws(
    () =>
      validateProjectFilesPayload([
        { path: 'src/big.ts', content: 'x'.repeat(260_000) },
      ]),
    SecurityValidationError,
  );
  const ok = validateProjectFilesPayload([{ path: '/src/App.tsx', content: 'export default function App(){}' }]);
  assert.equal(ok[0].path, 'src/App.tsx');
});

test('streamByokCompletion handles incomplete trailing SSE chunks, caller cancellation, and idle timeouts', async () => {
  const config = {
    provider: 'custom' as const,
    name: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    model: 'openrouter/free',
    apiKey: 'sk-or-v1-secret-test-key',
  };

  // 1. Trailing incomplete SSE line without trailing \n
  const encoder = new TextEncoder();
  const incompleteBody = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"Hello "}}]}\n'));
      controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"World"}}]}'));
      controller.close();
    },
  });
  const streamed = await streamByokCompletion({
    config,
    messages: [{ role: 'user', content: 'hi' }],
    skipDnsLookup: true,
    onDelta: () => {},
    fetchImpl: (async () => new Response(incompleteBody, { status: 200 })) as typeof fetch,
  });
  assert.equal(streamed, 'Hello World');

  // 2. Client disconnect cancellation
  const abortController = new AbortController();
  const stalledBody = new ReadableStream<Uint8Array>({
    start() {
      setTimeout(() => abortController.abort(), 30);
    },
  });
  await assert.rejects(
    () =>
      streamByokCompletion({
        config,
        messages: [{ role: 'user', content: 'hi' }],
        signal: abortController.signal,
        skipDnsLookup: true,
        idleTimeoutMs: 5000,
        onDelta: () => {},
        fetchImpl: (async () => new Response(stalledBody, { status: 200 })) as typeof fetch,
      }),
    (err: unknown) => err instanceof ProviderHttpError && err.status === 499,
  );

  // 3. Idle timeout when upstream hangs mid-stream
  const hangBody = new ReadableStream<Uint8Array>({
    start() {
      // Never enqueues or closes
    },
  });
  await assert.rejects(
    () =>
      streamByokCompletion({
        config,
        messages: [{ role: 'user', content: 'hi' }],
        idleTimeoutMs: 60,
        totalTimeoutMs: 5000,
        skipDnsLookup: true,
        onDelta: () => {},
        fetchImpl: (async () => new Response(hangBody, { status: 200 })) as typeof fetch,
      }),
    (err: unknown) => err instanceof ProviderHttpError && err.status === 504,
  );

  // 4. Secret redaction never leaks keys
  const redacted = redactSecrets('Failed calling key sk-or-v1-abcdef1234567890 and AIzaSyA1234567890abcdef');
  assert.equal(redacted.includes('sk-or-v1-abcdef'), false);
  assert.equal(redacted.includes('AIzaSyA123456'), false);
  assert.ok(redacted.includes('[REDACTED]'));
});

test('Secret redaction and error sanitization strip private keys, secrets, passwords, and sensitive system errors', () => {
  // 1. Private keys redaction
  const rsaKey = '-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----';
  assert.equal(redactSecrets(rsaKey), '[REDACTED PRIVATE KEY]');

  // 2. Vault secret and passwords in queries or logs
  const logWithVaultSecret = 'Error during sealing: MIST_VAULT_SECRET=supersecret12345678901234567890 and password="my-secret-password"';
  const redactedLog = redactSecrets(logWithVaultSecret);
  assert.ok(!redactedLog.includes('supersecret12345678901234567890'));
  assert.ok(!redactedLog.includes('my-secret-password'));

  // 3. Clerk secret key & Firebase service account JSON
  const clerkLog = 'Config CLERK_SECRET_KEY=sk_test_51Abcdef12345678901234567890';
  assert.ok(!redactSecrets(clerkLog).includes('sk_test_51Abcdef'));

  // 4. sanitizeErrorMessage masks stack traces and file paths while keeping error message clean
  const errWithSecret = new Error('Database connection failed at /app/src/db.ts:42 with secret=supersecret12345678901234567890');
  const sanitized = sanitizeErrorMessage(errWithSecret);
  assert.ok(!sanitized.includes('supersecret12345678901234567890'));
  assert.ok(sanitized.includes('Database connection failed'));
});

test('Vault secret validation enforces high entropy and rejects weak, short, or missing secrets in production', () => {
  // In production (isProduction: true):
  // 1. Missing or empty secret throws 500
  assert.throws(
    () => assertValidVaultSecret('', true),
    (err: unknown) =>
      err instanceof SecurityValidationError &&
      err.status === 500 &&
      err.message.includes('must be configured in production'),
  );

  assert.throws(
    () => assertValidVaultSecret(undefined, true),
    (err: unknown) =>
      err instanceof SecurityValidationError &&
      err.status === 500 &&
      err.message.includes('must be configured in production'),
  );

  // 2. Secret too short (< 32 chars) throws 500
  assert.throws(
    () => assertValidVaultSecret('short_secret_under_32_chars', true),
    (err: unknown) =>
      err instanceof SecurityValidationError &&
      err.status === 500 &&
      err.message.includes('at least 32'),
  );

  // 3. Low entropy (repeated characters) throws 500
  assert.throws(
    () => assertValidVaultSecret('a'.repeat(40), true),
    (err: unknown) =>
      err instanceof SecurityValidationError &&
      err.status === 500 &&
      err.message.includes('too weak'),
  );

  // 4. Predictable / placeholder secrets throw 500
  const weakPlaceholders = [
    'generate_random_32_byte_hex_secret_placeholder',
    'your-vault-secret-key-goes-here-1234567890',
    'change_me_before_production_deployment_123',
    '1234567890123456789012345678901234567890',
  ];
  for (const weak of weakPlaceholders) {
    assert.throws(
      () => assertValidVaultSecret(weak, true),
      (err: unknown) =>
        err instanceof SecurityValidationError &&
        err.status === 500 &&
        err.message.includes('too weak'),
      `Expected weak placeholder ${weak} to be rejected in production`,
    );
  }

  // 5. High-entropy 32+ char secret succeeds
  const highEntropy = crypto.randomBytes(32).toString('hex'); // 64 chars
  const valid = assertValidVaultSecret(highEntropy, true);
  assert.equal(valid, highEntropy);

  // In non-production (development/test):
  // When empty, returns the safe dev fallback
  const devDefault = assertValidVaultSecret('', false);
  assert.ok(devDefault.length >= 32);

  // deriveUserVaultKey rejects invalid secret in production
  assert.throws(
    () =>
      deriveUserVaultKey({
        uid: 'user-prod-1',
        email: 'prod@example.com',
        secret: 'too-short',
        isProduction: true,
      }),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 500,
  );
});

test('Vault payload validation rejects prototype pollution, malformed objects, oversized fields, and invalid providers', () => {
  // 1. Non-objects / arrays rejected
  assert.throws(
    () => validateVaultPayload('not-an-object'),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 400,
  );
  assert.throws(
    () => validateVaultPayload(['array-payload']),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 400,
  );
  assert.throws(
    () => validateVaultPayload(null),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 400,
  );

  // 2. Prototype pollution attempts rejected
  assert.throws(
    () => JSON.parse('{"__proto__":{"polluted":true},"aiConfig":{"provider":"custom"}}', (k, v) => {
      if (k === '__proto__') {
        const payload: Record<string, unknown> = {};
        Object.defineProperty(payload, '__proto__', { value: { polluted: true }, enumerable: true });
        validateVaultPayload(payload);
      }
      return v;
    }),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 400,
  );

  const pollutedPayload = Object.create(null);
  pollutedPayload.constructor = { polluted: true };
  assert.throws(
    () => validateVaultPayload(pollutedPayload),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 400,
  );

  // 3. Oversized payload rejected (>64KB)
  const hugePayload = {
    aiConfig: {
      provider: 'custom' as const,
      model: 'large',
      apiKey: 'a'.repeat(65000),
    },
  };
  assert.throws(
    () => validateVaultPayload(hugePayload),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 400,
  );

  // 4. Invalid AI provider rejected
  assert.throws(
    () =>
      validateVaultPayload({
        aiConfig: {
          provider: 'unsupported_ai' as any,
          model: 'm1',
          apiKey: 'key',
        },
      }),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 400,
  );

  // 5. Insecure / invalid baseUrl rejected
  assert.throws(
    () =>
      validateVaultPayload({
        aiConfig: {
          provider: 'custom',
          model: 'm1',
          apiKey: 'key',
          baseUrl: 'javascript:alert(1)',
        },
      }),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 400,
  );

  // 6. Valid payload is cleaned and trimmed
  const cleaned = validateVaultPayload({
    aiConfig: {
      provider: 'custom',
      name: '  Trimmed Model  ',
      model: ' openrouter/free ',
      apiKey: '  sk-or-valid-key  ',
      baseUrl: 'https://openrouter.ai/api/v1',
    },
    searchConfig: {
      provider: 'brave_llm_context',
      apiKey: '  BSA_valid_search_key  ',
    },
  });
  assert.equal(cleaned.aiConfig?.name, 'Trimmed Model');
  assert.equal(cleaned.aiConfig?.apiKey, 'sk-or-valid-key');
  assert.equal(cleaned.searchConfig?.apiKey, 'BSA_valid_search_key');
});

test('AES-256-GCM vault security: tampering detection on IV, ciphertext, and auth tag, and malformed envelopes', () => {
  const secret = crypto.randomBytes(32).toString('hex');
  const sealed = sealUserVaultPayload({
    uid: 'tamper-user-1',
    email: 'tamper@example.com',
    secretOverride: secret,
    aiConfig: {
      provider: 'custom',
      model: 'openrouter/free',
      apiKey: 'sk-or-super-secret-12345678',
    },
  });

  const rawJson = Buffer.from(sealed.encryptedPayload, 'base64').toString('utf8');
  const parsedEnvelope = JSON.parse(rawJson);
  assert.equal(parsedEnvelope.v, 1);
  assert.ok(parsedEnvelope.iv);
  assert.ok(parsedEnvelope.tag);
  assert.ok(parsedEnvelope.ct);

  // 1. Tampered IV (flip first char of base64 iv)
  const tamperedIvEnvelope = Buffer.from(
    JSON.stringify({
      ...parsedEnvelope,
      iv: parsedEnvelope.iv[0] === 'A' ? 'B' + parsedEnvelope.iv.slice(1) : 'A' + parsedEnvelope.iv.slice(1),
    }),
    'utf8',
  ).toString('base64');
  assert.throws(
    () =>
      unsealUserVaultPayload({
        uid: 'tamper-user-1',
        email: 'tamper@example.com',
        encryptedPayload: tamperedIvEnvelope,
        secretOverride: secret,
      }),
    (err: unknown) => err instanceof SecurityValidationError && (err.status === 403 || err.status === 400),
  );

  // 2. Tampered Ciphertext (flip first char of base64 ct)
  const tamperedCtEnvelope = Buffer.from(
    JSON.stringify({
      ...parsedEnvelope,
      ct: parsedEnvelope.ct[0] === 'A' ? 'B' + parsedEnvelope.ct.slice(1) : 'A' + parsedEnvelope.ct.slice(1),
    }),
    'utf8',
  ).toString('base64');
  assert.throws(
    () =>
      unsealUserVaultPayload({
        uid: 'tamper-user-1',
        email: 'tamper@example.com',
        encryptedPayload: tamperedCtEnvelope,
        secretOverride: secret,
      }),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 403,
  );

  // 3. Tampered Auth Tag (flip first char of base64 tag)
  const tamperedTagEnvelope = Buffer.from(
    JSON.stringify({
      ...parsedEnvelope,
      tag: parsedEnvelope.tag[0] === 'A' ? 'B' + parsedEnvelope.tag.slice(1) : 'A' + parsedEnvelope.tag.slice(1),
    }),
    'utf8',
  ).toString('base64');
  assert.throws(
    () =>
      unsealUserVaultPayload({
        uid: 'tamper-user-1',
        email: 'tamper@example.com',
        encryptedPayload: tamperedTagEnvelope,
        secretOverride: secret,
      }),
    (err: unknown) => err instanceof SecurityValidationError && (err.status === 403 || err.status === 400),
  );

  // 4. Malformed envelopes (missing fields, wrong version)
  const wrongVersionEnvelope = Buffer.from(
    JSON.stringify({ v: 2, iv: 'aaa', tag: 'bbb', ct: 'ccc' }),
    'utf8',
  ).toString('base64');
  assert.throws(
    () =>
      unsealUserVaultPayload({
        uid: 'tamper-user-1',
        email: 'tamper@example.com',
        encryptedPayload: wrongVersionEnvelope,
        secretOverride: secret,
      }),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 400,
  );

  assert.throws(
    () =>
      unsealUserVaultPayload({
        uid: 'tamper-user-1',
        email: 'tamper@example.com',
        encryptedPayload: 'not-valid-base64-json-payload-at-least-20-chars',
        secretOverride: secret,
      }),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 400,
  );
});

test('AES-256-GCM vault user isolation, account-bound AAD verification, email normalization, and sessionOnlyKey', () => {
  const secret = crypto.randomBytes(32).toString('hex');
  const sealed = sealUserVaultPayload({
    uid: 'user-vault-alice',
    email: 'Alice.Smith@Example.COM',
    secretOverride: secret,
    aiConfig: {
      provider: 'custom',
      name: 'Gemini (BYOK)',
      baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
      model: 'gemini-3.1-flash-lite',
      apiKey: 'AIzaSySecretKeyValue9911',
      sessionOnlyKey: false,
    },
    searchConfig: {
      provider: 'brave_llm_context',
      apiKey: 'BSA_search_secret_4455',
      sessionOnlyKey: false,
    },
  });

  assert.equal(sealed.aiKeyHint, 'AIza••••9911');
  assert.equal(sealed.searchKeyHint, 'BSA_••••4455');
  assert.equal(sealed.encryptedPayload.includes('AIzaSySecretKeyValue9911'), false);

  // 1. Successful unseal with matching UID and case-insensitive email
  const unsealed = unsealUserVaultPayload({
    uid: 'user-vault-alice',
    email: '  alice.smith@example.com  ',
    encryptedPayload: sealed.encryptedPayload,
    secretOverride: secret,
  });
  assert.equal(unsealed.aiConfig?.apiKey, 'AIzaSySecretKeyValue9911');
  assert.equal(unsealed.aiConfig?.model, 'gemini-3.1-flash-lite');
  assert.equal(unsealed.searchConfig?.apiKey, 'BSA_search_secret_4455');
  assert.equal(unsealed.needsReencryption, false);

  // 2. Cross-account attempt with wrong UID rejected with 403
  assert.throws(
    () =>
      unsealUserVaultPayload({
        uid: 'attacker-bob',
        email: 'alice.smith@example.com',
        encryptedPayload: sealed.encryptedPayload,
        secretOverride: secret,
      }),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 403,
  );

  // 3. Attempt with different email rejected with 403
  assert.throws(
    () =>
      unsealUserVaultPayload({
        uid: 'user-vault-alice',
        email: 'eve@example.com',
        encryptedPayload: sealed.encryptedPayload,
        secretOverride: secret,
      }),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 403,
  );

  // 4. sessionOnlyKey strips API key before encryption
  const sessionOnlySealed = sealUserVaultPayload({
    uid: 'user-vault-alice',
    email: 'alice.smith@example.com',
    secretOverride: secret,
    aiConfig: {
      provider: 'custom',
      model: 'openrouter/free',
      apiKey: 'sk-or-never-persist',
      sessionOnlyKey: true,
    },
  });
  assert.equal(sessionOnlySealed.aiKeyHint, '');
  const sessionOnlyUnsealed = unsealUserVaultPayload({
    uid: 'user-vault-alice',
    email: 'alice.smith@example.com',
    encryptedPayload: sessionOnlySealed.encryptedPayload,
    secretOverride: secret,
  });
  assert.equal(sessionOnlyUnsealed.aiConfig?.apiKey, '');
});

test('Vault key rotation and legacy migration with automatic re-encryption', () => {
  const oldSecret = crypto.randomBytes(32).toString('hex');
  const newSecret = crypto.randomBytes(32).toString('hex');
  const newestSecret = crypto.randomBytes(32).toString('hex');

  // 1. Seal record with oldSecret
  const sealedOld = sealUserVaultPayload({
    uid: 'rotate-user-1',
    email: 'rotate@example.com',
    secretOverride: oldSecret,
    aiConfig: {
      provider: 'custom',
      model: 'gemini-3.1-flash-lite',
      apiKey: 'AIzaSySecretRotateOldKey',
    },
  });

  // 2. Unseal with only newSecret -> fails with 403
  assert.throws(
    () =>
      unsealUserVaultPayload({
        uid: 'rotate-user-1',
        email: 'rotate@example.com',
        encryptedPayload: sealedOld.encryptedPayload,
        secretOverride: newSecret,
        previousSecrets: [],
      }),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 403,
  );

  // 3. Unseal with newSecret as primary and oldSecret in previousSecrets -> succeeds with needsReencryption: true
  const unsealedRotated = unsealUserVaultPayload({
    uid: 'rotate-user-1',
    email: 'rotate@example.com',
    encryptedPayload: sealedOld.encryptedPayload,
    secretOverride: newSecret,
    previousSecrets: [oldSecret],
  });
  assert.equal(unsealedRotated.aiConfig?.apiKey, 'AIzaSySecretRotateOldKey');
  assert.equal(unsealedRotated.needsReencryption, true);

  // 4. migrateUserVaultCiphertext re-encrypts old ciphertext with new secret
  const migrationResult = migrateUserVaultCiphertext({
    uid: 'rotate-user-1',
    email: 'rotate@example.com',
    ciphertext: sealedOld.encryptedPayload,
    newSecret: newestSecret,
    previousSecrets: [oldSecret],
  });
  assert.equal(migrationResult.migrated, true);
  assert.ok(migrationResult.newCiphertext !== sealedOld.encryptedPayload);

  // Decrypting the migrated ciphertext with newestSecret alone succeeds with needsReencryption: false
  const unsealedNewest = unsealUserVaultPayload({
    uid: 'rotate-user-1',
    email: 'rotate@example.com',
    encryptedPayload: migrationResult.newCiphertext,
    secretOverride: newestSecret,
    previousSecrets: [],
  });
  assert.equal(unsealedNewest.aiConfig?.apiKey, 'AIzaSySecretRotateOldKey');
  assert.equal(unsealedNewest.needsReencryption, false);

  // 5. Legacy migration from old predictable fallback
  const testProjectId = 'test-mist-legacy-proj';
  const legacySecret = `${testProjectId}:mist-account-vault-dev-only`;
  const sealedLegacy = sealUserVaultPayload({
    uid: 'legacy-user-1',
    email: 'legacy@example.com',
    secretOverride: legacySecret,
    runtimeProject: testProjectId,
    aiConfig: {
      provider: 'custom',
      model: 'legacy-model',
      apiKey: 'sk-legacy-test-api-key',
    },
  });

  // In production mode with allowLegacyFallback: false, unsealing legacy ciphertext fails
  assert.throws(
    () =>
      unsealUserVaultPayload({
        uid: 'legacy-user-1',
        email: 'legacy@example.com',
        encryptedPayload: sealedLegacy.encryptedPayload,
        secretOverride: newSecret,
        previousSecrets: [],
        allowLegacyFallback: false,
        isProduction: true,
        runtimeProject: testProjectId,
      }),
    (err: unknown) => err instanceof SecurityValidationError && err.status === 403,
  );

  // When allowLegacyFallback: true, unsealing legacy ciphertext succeeds and sets needsReencryption: true
  const unsealedLegacy = unsealUserVaultPayload({
    uid: 'legacy-user-1',
    email: 'legacy@example.com',
    encryptedPayload: sealedLegacy.encryptedPayload,
    secretOverride: newSecret,
    previousSecrets: [],
    allowLegacyFallback: true,
    runtimeProject: testProjectId,
  });
  assert.equal(unsealedLegacy.aiConfig?.apiKey, 'sk-legacy-test-api-key');
  assert.equal(unsealedLegacy.needsReencryption, true);

  // Migrate legacy record
  const legacyMigrated = migrateUserVaultCiphertext({
    uid: 'legacy-user-1',
    email: 'legacy@example.com',
    ciphertext: sealedLegacy.encryptedPayload,
    newSecret,
    allowLegacyFallback: true,
    runtimeProject: testProjectId,
  });
  assert.equal(legacyMigrated.migrated, true);

  // Migrated record now unseals cleanly with newSecret without legacy fallback
  const unsealedPostMigration = unsealUserVaultPayload({
    uid: 'legacy-user-1',
    email: 'legacy@example.com',
    encryptedPayload: legacyMigrated.newCiphertext,
    secretOverride: newSecret,
    allowLegacyFallback: false,
    isProduction: true,
    runtimeProject: testProjectId,
  });
  assert.equal(unsealedPostMigration.aiConfig?.apiKey, 'sk-legacy-test-api-key');
  assert.equal(unsealedPostMigration.needsReencryption, false);
});

test('revokeAllUserPreviewSessions revokes all tokens for target user only', () => {
  const s1 = createPreviewAiSession({ provider: 'custom', model: 'm1', apiKey: 'k1' }, 'uid-bulk-a');
  const s2 = createPreviewAiSession({ provider: 'custom', model: 'm2', apiKey: 'k2' }, 'uid-bulk-a');
  const sOther = createPreviewAiSession({ provider: 'custom', model: 'm3', apiKey: 'k3' }, 'uid-bulk-b');

  assert.equal(revokeAllUserPreviewSessions('uid-bulk-a'), 2);
  assert.equal(resolvePreviewAiSession(s1.token), null);
  assert.equal(resolvePreviewAiSession(s2.token), null);
  assert.equal(resolvePreviewAiSession(sOther.token)?.apiKey, 'k3');
  revokePreviewAiSession(sOther.token, 'uid-bulk-b');
});

test('extractChoiceText, maskApiKey, and suggestShortSlug normalize outputs cleanly', () => {
  assert.equal(extractChoiceText('plain text'), 'plain text');
  assert.equal(
    extractChoiceText([{ type: 'text', text: '{"ok":' }, { text: 'true}' }]),
    '{"ok":true}',
  );
  assert.equal(maskApiKey('AIzaSyABCDEF1234'), 'AIza••••1234');
  assert.equal(maskApiKey(''), '');
  assert.equal(suggestShortSlug('My Awesome Coffee Roastery Website App Builder', 20), 'my-awesome-coffee');
});

test('buildExportManifest includes standalone dist/index.html, Render Static blueprint, and free no-credit-card guide', () => {
  const manifest = buildExportManifest(
    {
      id: 'proj_test',
      name: 'Tokyo Coffee Roastery',
      description: 'Specialty pour-over cafe',
      prompt: 'Build a Tokyo specialty coffee roastery website',
      isPublished: false,
      createdAt: '2026-11-16T00:00:00Z',
      updatedAt: '2026-11-16T00:00:00Z',
      files: [
        {
          id: 'f1',
          path: 'src/App.tsx',
          language: 'tsx',
          content: 'export default function App() { return <main>Tokyo Coffee</main>; }',
        },
        {
          id: 'f2',
          path: 'src/index.css',
          language: 'css',
          content: '@import "tailwindcss";\n',
        },
      ],
      chatHistory: [],
    },
    {
      slug: 'tokyo-coffee',
      standaloneHtml: '<!doctype html><html><body>Tokyo Coffee Standalone</body></html>',
    },
  );

  assert.equal(manifest['dist/index.html'], '<!doctype html><html><body>Tokyo Coffee Standalone</body></html>');
  assert.ok(manifest['render.yaml'].includes('name: tokyo-coffee'));
  assert.ok(manifest['render.yaml'].includes('runtime: static'));
  assert.ok(manifest['render.yaml'].includes('staticPublishPath: ./dist'));
  assert.ok(manifest['DEPLOY_FREE.md'].includes('no credit card billing required'));
  assert.ok(manifest['DEPLOY_FREE.md'].includes('https://app.netlify.com/drop'));
  assert.ok(manifest['DEPLOY_FREE.md'].includes('https://dashboard.render.com/select-repo?type=static'));
  assert.equal(Object.values(manifest).some((v) => v.includes('/api/app-ai')), false);
});

