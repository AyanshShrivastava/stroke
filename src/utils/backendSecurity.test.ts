import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createMistApp } from './mistServerApp';
import {
  isPrivateOrReservedIp,
  validateExternalUrlSyntax,
  assertSafeExternalUrl,
  safeFetchExternal,
  SecurityValidationError,
  validateAiProviderConfig,
  validateWebSearchConfig,
  BODY_LIMITS,
  type SharedRateLimitAdapter,
  type RateLimitCheckResult,
} from './serverSecurity';
import { redactSecrets } from './aiErrors';
import { createMemoryDeploymentStore } from './deploymentStore';
import type { VerifiedClerkUser } from './serverSecurity';

function createMockUsers(): Record<string, VerifiedClerkUser> {
  return {
    'token-alice': {
      userId: 'user_alice_123',
      uid: 'user_alice_123',
      email: 'alice@example.com',
      emailVerified: true,
      claims: { email: 'alice@example.com', email_verified: true },
      idToken: 'token-alice',
    },
    'token-unverified': {
      userId: 'user_unverified_456',
      uid: 'user_unverified_456',
      email: 'unverified@example.com',
      emailVerified: false,
      claims: { email: 'unverified@example.com', email_verified: false },
      idToken: 'token-unverified',
    },
  };
}

async function startSecurityTestServer(deps?: {
  rateLimitAdapter?: SharedRateLimitAdapter;
  aiRateLimitMax?: number;
  searchRateLimitMax?: number;
  bundleRateLimitMax?: number;
  aiFetchImpl?: typeof fetch;
}) {
  const users = createMockUsers();
  const store = createMemoryDeploymentStore();
  const app = createMistApp({
    deploymentStore: store,
    publishBaseUrl: 'https://sites.mist.me',
    skipDnsLookup: true,
    aiRateLimitMax: deps?.aiRateLimitMax ?? 10,
    searchRateLimitMax: deps?.searchRateLimitMax ?? 10,
    bundleRateLimitMax: deps?.bundleRateLimitMax ?? 10,
    rateLimitAdapter: deps?.rateLimitAdapter,
    aiFetchImpl:
      deps?.aiFetchImpl ||
      (async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url.includes('/models') || url.includes('/chat/completions')) {
          return new Response(
            JSON.stringify({
              id: 'mock-test',
              choices: [{ message: { content: 'OK' } }],
              data: [{ id: 'mock-model' }],
            }),
            { status: 200, headers: { 'content-type': 'application/json' } },
          );
        }
        return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
      }),
    verifyAuthHeader: async (authHeader?: string) => {
      if (!authHeader || !authHeader.startsWith('Bearer ')) {
        throw new SecurityValidationError(401, 'Clerk authentication is required.', 'UNAUTHORIZED');
      }
      const token = authHeader.slice('Bearer '.length).trim();
      const user = users[token];
      if (!user) {
        throw new SecurityValidationError(401, 'Invalid authentication token.', 'UNAUTHORIZED');
      }
      return user;
    },
  });

  const server = http.createServer(app);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', () => resolve()));
  const port = (server.address() as any).port;
  const baseUrl = `http://127.0.0.1:${port}`;

  return {
    baseUrl,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

test('1. Adversarial Request Validation: Malformed JSON and route-specific body size limits', async () => {
  const srv = await startSecurityTestServer();
  try {
    // A. Malformed JSON syntax returns clean 400 with code INVALID_JSON (not HTML error)
    const malformedResp = await fetch(`${srv.baseUrl}/api/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: '{"query": "broken json payload, missing closing brace',
    });
    assert.equal(malformedResp.status, 400);
    const malformedJson = (await malformedResp.json()) as { error: string; code: string };
    assert.equal(malformedJson.code, 'INVALID_JSON');
    assert.ok(malformedJson.error.includes('Malformed JSON'));

    // B. Oversized payload on route with strict limit (Search limit: 64KB)
    const oversizedSearchPayload = {
      query: 'test query',
      searchConfig: {
        provider: 'duckduckgo',
        extraPadding: 'x'.repeat(BODY_LIMITS.SEARCH + 1024),
      },
    };
    const searchTooLargeResp = await fetch(`${srv.baseUrl}/api/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify(oversizedSearchPayload),
    });
    assert.equal(searchTooLargeResp.status, 413);
    const searchTooLargeJson = (await searchTooLargeResp.json()) as { code: string };
    assert.equal(searchTooLargeJson.code, 'PAYLOAD_TOO_LARGE');

    // C. Oversized payload on notifications endpoint (limit: 32KB)
    const oversizedSubPayload = {
      subscription: {
        endpoint: 'https://fcm.googleapis.com/fcm/send/foo',
        keys: { p256dh: 'p256', auth: 'auth' },
        padding: 'y'.repeat(BODY_LIMITS.NOTIFICATIONS + 1024),
      },
    };
    const subTooLargeResp = await fetch(`${srv.baseUrl}/api/notifications/subscribe`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify(oversizedSubPayload),
    });
    assert.equal(subTooLargeResp.status, 413);
    const subTooLargeJson = (await subTooLargeResp.json()) as { code: string };
    assert.equal(subTooLargeJson.code, 'PAYLOAD_TOO_LARGE');
  } finally {
    await srv.close();
  }
});

test('2. Adversarial Authentication: Missing, invalid, unverified, and optional tokens', async () => {
  const srv = await startSecurityTestServer();
  try {
    // A. Unauthenticated request to protected endpoints rejected with 401
    const endpoints = [
      { url: '/api/projects/sync', method: 'POST', body: { projects: [] } },
      { url: '/api/deployments', method: 'POST', body: { slug: 'test' } },
      { url: '/api/search', method: 'POST', body: { query: 'test' } },
      { url: '/api/ai/test-provider', method: 'POST', body: { provider: 'custom', model: 'm', apiKey: 'k' } },
      { url: '/api/user/vault/seal', method: 'POST', body: {} },
    ];

    for (const ep of endpoints) {
      const resp = await fetch(`${srv.baseUrl}${ep.url}`, {
        method: ep.method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(ep.body),
      });
      assert.equal(resp.status, 401, `Expected 401 for ${ep.url}`);
      const data = (await resp.json()) as { error: string };
      assert.ok(data.error);
    }

    // B. Invalid Bearer token
    const invalidTokenResp = await fetch(`${srv.baseUrl}/api/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-invalid-spoof',
      },
      body: JSON.stringify({ query: 'test' }),
    });
    assert.equal(invalidTokenResp.status, 401);

    // C. Account with unverified email rejected with 403
    const unverifiedResp = await fetch(`${srv.baseUrl}/api/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-unverified',
      },
      body: JSON.stringify({ query: 'test' }),
    });
    assert.equal(unverifiedResp.status, 403);
    const unverifiedJson = (await unverifiedResp.json()) as { error: string };
    assert.ok(unverifiedJson.error.includes('verified account email'));

    // D. /api/bundle allows anonymous guest preview, but rejects corrupted Bearer tokens
    const guestBundle = await fetch(`${srv.baseUrl}/api/bundle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        files: [{ path: 'src/App.tsx', content: 'export default function App() { return <div>Hi</div>; }' }],
      }),
    });
    assert.equal(guestBundle.status, 200, 'Guest preview must succeed');

    const corruptedAuthBundle = await fetch(`${srv.baseUrl}/api/bundle`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-invalid-tampered',
      },
      body: JSON.stringify({ files: [] }),
    });
    assert.equal(corruptedAuthBundle.status, 401, 'Corrupted auth header on bundle must be rejected');
  } finally {
    await srv.close();
  }
});

test('3. Adversarial SSRF, DNS Rebinding & Malicious URL Protections', async () => {
  // A. Blocked IP verification
  const privateIps = [
    '127.0.0.1',
    '127.0.1.1',
    '10.0.0.1',
    '10.254.254.254',
    '169.254.169.254', // AWS/GCP metadata
    '169.254.0.1',
    '172.16.0.1',
    '172.31.255.255',
    '192.168.0.1',
    '192.168.100.50',
    '100.64.0.1', // CGNAT
    '100.100.100.200', // Alibaba Cloud metadata
    '198.51.100.5', // RFC 5737 TEST-NET-2
    '203.0.113.10', // RFC 5737 TEST-NET-3
    '224.0.0.1', // Multicast
    '240.0.0.1', // Reserved Class E
    '255.255.255.255', // Broadcast
    '::1',
    'fc00::1',
    'fe80::1',
    '2001:db8::1', // IPv6 Documentation
    '::ffff:127.0.0.1', // IPv4-mapped IPv6 loopback
    '::ffff:169.254.169.254', // IPv4-mapped IPv6 metadata
  ];

  for (const ip of privateIps) {
    assert.equal(isPrivateOrReservedIp(ip), true, `Expected ${ip} to be classified as private/reserved`);
  }

  // Public IPs must not be blocked
  assert.equal(isPrivateOrReservedIp('8.8.8.8'), false);
  assert.equal(isPrivateOrReservedIp('1.1.1.1'), false);
  assert.equal(isPrivateOrReservedIp('93.184.216.34'), false);

  // B. Dangerous URL syntax rejections
  const maliciousUrls = [
    'http://openrouter.ai/api/v1', // Insecure HTTP
    'ftp://attacker.com/v1',
    'file:///etc/passwd',
    'gopher://attacker.com/v1',
    'https://localhost:3000/v1',
    'https://127.0.0.1:8080/v1',
    'https://169.254.169.254/latest/meta-data',
    'https://metadata.google.internal/computeMetadata/v1',
    'https://instance-data/v1',
    'https://user:pass@openrouter.ai/api/v1', // Embedded credentials
    'https://attacker.internal/api',
    'https://attacker.local/api',
  ];

  for (const url of maliciousUrls) {
    assert.throws(
      () => validateExternalUrlSyntax(url),
      SecurityValidationError,
      `Expected ${url} to be rejected by validateExternalUrlSyntax`,
    );
  }

  // C. DNS Rebinding: resolution resolving to internal IP
  await assert.rejects(
    () =>
      assertSafeExternalUrl('https://rebind.attacker.com/v1', {
        lookupFn: async () => [{ address: '127.0.0.1', family: 4 }],
      }),
    SecurityValidationError,
  );

  // D. HTTP Redirect blocking
  await assert.rejects(
    () =>
      safeFetchExternal('https://openrouter.ai/api/v1/models', {
        skipDnsLookup: true,
        fetchImpl: (async () => {
          throw new TypeError('redirect mode is set to error');
        }) as typeof fetch,
      }),
    (err: unknown) =>
      err instanceof SecurityValidationError && err.message.includes('Blocked HTTP redirect'),
  );
});

test('4. Rate Limit Abuse & Configurable Shared Adapter Fallback', async () => {
  // A. In-memory rate limiting enforcement and RFC headers
  const srv = await startSecurityTestServer({ aiRateLimitMax: 3 });
  try {
    const callTest = () =>
      fetch(`${srv.baseUrl}/api/ai/test-provider`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer token-alice',
        },
        body: JSON.stringify({
          provider: 'custom',
          name: 'OpenRouter',
          baseUrl: 'https://openrouter.ai/api/v1',
          model: 'openrouter/free',
          apiKey: 'sk-or-mock-key',
        }),
      });

    const r1 = await callTest();
    assert.equal(r1.status, 200);
    assert.equal(r1.headers.get('X-RateLimit-Limit'), '3');

    const r2 = await callTest();
    assert.equal(r2.status, 200);

    const r3 = await callTest();
    assert.equal(r3.status, 200);

    // 4th request exceeds limit of 3
    const r4 = await callTest();
    assert.equal(r4.status, 429);
    assert.ok(r4.headers.has('Retry-After'));
    const r4Json = (await r4.json()) as { code: string; retryAfter: number };
    assert.equal(r4Json.code, 'RATE_LIMIT_EXCEEDED');
    assert.ok(r4Json.retryAfter >= 1);
  } finally {
    await srv.close();
  }

  // B. Configurable shared adapter injection and graceful fallback
  let customAdapterCalled = false;
  const failingSharedAdapter: SharedRateLimitAdapter = {
    checkAndRecord: async () => {
      customAdapterCalled = true;
      throw new Error('Simulated Redis network partition error');
    },
  };

  const srvWithAdapter = await startSecurityTestServer({
    rateLimitAdapter: failingSharedAdapter,
    aiRateLimitMax: 5,
  });

  try {
    const resp = await fetch(`${srvWithAdapter.baseUrl}/api/ai/test-provider`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({
        provider: 'custom',
        name: 'OpenRouter',
        baseUrl: 'https://openrouter.ai/api/v1',
        model: 'openrouter/free',
        apiKey: 'sk-or-mock-key',
      }),
    });
    // Server must gracefully fall back to in-memory rate limiter instead of failing
    assert.equal(customAdapterCalled, true);
    assert.equal(resp.status, 200);
  } finally {
    await srvWithAdapter.close();
  }
});

test('5. Timeout and Cancellation Handling in App AI & Bundling', async () => {
  // A. Client disconnect aborts upstream request cleanly
  let upstreamAborted = false;
  const srv = await startSecurityTestServer({
    aiFetchImpl: (async (_input, init) => {
      // Monitor upstream cancellation signal
      init?.signal?.addEventListener('abort', () => {
        upstreamAborted = true;
      });
      // Simulate slow upstream response
      await new Promise((r) => setTimeout(r, 500));
      return new Response(JSON.stringify({ choices: [{ message: { content: 'hello' } }] }));
    }) as typeof fetch,
  });

  try {
    const controller = new AbortController();
    const fetchPromise = fetch(`${srv.baseUrl}/api/app-ai`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({
        prompt: 'say hi',
        providerConfig: {
          provider: 'custom',
          name: 'OpenRouter',
          baseUrl: 'https://openrouter.ai/api/v1',
          model: 'openrouter/free',
          apiKey: 'sk-or-mock-key',
        },
      }),
      signal: controller.signal,
    });

    // Abort client request after 50ms
    setTimeout(() => controller.abort(), 50);

    await assert.rejects(fetchPromise);
    // Allow abort event to propagate
    await new Promise((r) => setTimeout(r, 100));
    assert.equal(upstreamAborted, true, 'Upstream fetch must be aborted when client disconnects');
  } finally {
    await srv.close();
  }
});

test('6. Secret Redaction: Private keys, tokens, database URIs, and JWTs are scrubbed', () => {
  const sensitiveOutput = `
    Error connecting with Bearer sk-or-v1-abcdef1234567890abcdef1234567890
    Also leaked BSA_01234567890abcdef and gsk_01234567890abcdef
    VAPID_PRIVATE_KEY: abcdef1234567890abcdef1234567890
    CLERK_SECRET_KEY=sk_test_abcdef1234567890abcdef1234567890
    Clerk session sess_abcdef1234567890abcdef1234567890
    Database postgres://admin:supersecretpw@db.example.com:5432/mist
    JWT eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsK88
    Raw RSA -----BEGIN RSA PRIVATE KEY-----
    MIIEowIBAAKCAQEA0...
    -----END RSA PRIVATE KEY-----
  `;

  const redacted = redactSecrets(sensitiveOutput);

  assert.equal(redacted.includes('sk-or-v1-abcdef1234567890abcdef1234567890'), false);
  assert.equal(redacted.includes('supersecretpw'), false);
  assert.equal(redacted.includes('sk_test_abcdef1234567890abcdef1234567890'), false);
  assert.equal(redacted.includes('sess_abcdef1234567890abcdef1234567890'), false);
  assert.equal(redacted.includes('MIIEowIBAAKCAQEA0...'), false);
  assert.ok(redacted.includes('Bearer [REDACTED]'));
  assert.ok(redacted.includes('[REDACTED PRIVATE KEY]'));
  assert.ok(redacted.includes('postgres://[REDACTED]:[REDACTED]@db.example.com'));
  assert.ok(redacted.includes('eyJ[REDACTED]'));
});

test('7. Prototype Pollution & Config Sanitization', () => {
  // A. Provider config with prototype pollution rejected
  const pollutedAi = JSON.parse('{"__proto__":{"polluted":true},"provider":"custom","model":"test","apiKey":"k"}');
  assert.throws(
    () => validateAiProviderConfig(pollutedAi),
    (err: unknown) => err instanceof SecurityValidationError && err.code === 'PROTOTYPE_POLLUTION',
  );

  // B. Search config with prototype pollution rejected
  const pollutedSearch = JSON.parse('{"constructor":{"prototype":{"polluted":true}},"provider":"duckduckgo"}');
  assert.throws(
    () => validateWebSearchConfig(pollutedSearch),
    (err: unknown) => err instanceof SecurityValidationError && err.code === 'PROTOTYPE_POLLUTION',
  );

  // C. Provider config with excessive string lengths rejected
  const oversizedApiKey = {
    provider: 'custom',
    model: 'test',
    apiKey: 'k'.repeat(600), // Max allowed 512
  };
  assert.throws(
    () => validateAiProviderConfig(oversizedApiKey),
    (err: unknown) => err instanceof SecurityValidationError,
  );
});
