import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createMistApp } from '../../src/utils/mistServerApp';
import { InMemoryAdminStore } from '../../src/server/firestoreAdmin';
import { InMemoryR2ArtifactStore } from '../../src/utils/r2ArtifactStore';
import worker, {
  isValidSlug,
  extractSubdomain,
  getContentType,
  render404Page,
  handlePublishedSite,
  proxyToHeroku,
  RESERVED_SUBDOMAINS,
  type Env,
} from './index';

test('isValidSlug validates correct DNS slugs and rejects invalid formats', () => {
  // Valid
  assert.equal(isValidSlug('my-portfolio'), true);
  assert.equal(isValidSlug('alpha123'), true);
  assert.equal(isValidSlug('site-v2-test'), true);
  assert.equal(isValidSlug('abc'), true);

  // Invalid: length bounds
  assert.equal(isValidSlug(''), false);
  assert.equal(isValidSlug('ab'), false); // min 3 chars
  assert.equal(isValidSlug('a'.repeat(64)), false); // max 63 chars

  // Invalid: characters
  assert.equal(isValidSlug('My-Site'), false); // uppercase
  assert.equal(isValidSlug('site_test'), false); // underscores
  assert.equal(isValidSlug('site.test'), false); // dots
  assert.equal(isValidSlug('site test'), false); // spaces

  // Invalid: leading/trailing/consecutive hyphens
  assert.equal(isValidSlug('-site'), false);
  assert.equal(isValidSlug('site-'), false);
  assert.equal(isValidSlug('site--test'), false);
});

test('extractSubdomain distinguishes apex domain from subdomains correctly', () => {
  // Apex cases
  assert.deepEqual(extractSubdomain('mist.me', 'mist.me'), { isApex: true, subdomain: null });
  assert.deepEqual(extractSubdomain('MIST.ME', 'mist.me'), { isApex: true, subdomain: null });
  assert.deepEqual(extractSubdomain('localhost', 'mist.me'), { isApex: true, subdomain: null });
  assert.deepEqual(extractSubdomain('127.0.0.1', 'mist.me'), { isApex: true, subdomain: null });

  // Subdomain cases
  assert.deepEqual(extractSubdomain('my-app.mist.me', 'mist.me'), { isApex: false, subdomain: 'my-app' });
  assert.deepEqual(extractSubdomain('www.mist.me', 'mist.me'), { isApex: false, subdomain: 'www' });
  assert.deepEqual(extractSubdomain('api.mist.me', 'mist.me'), { isApex: false, subdomain: 'api' });
  assert.deepEqual(extractSubdomain('test-site.localhost', 'mist.me'), { isApex: false, subdomain: 'test-site' });
});

test('getContentType maps file extensions to correct MIME types', () => {
  assert.equal(getContentType('index.html'), 'text/html; charset=utf-8');
  assert.equal(getContentType('style.css'), 'text/css; charset=utf-8');
  assert.equal(getContentType('bundle.js'), 'application/javascript; charset=utf-8');
  assert.equal(getContentType('data.json'), 'application/json; charset=utf-8');
  assert.equal(getContentType('logo.svg'), 'image/svg+xml');
  assert.equal(getContentType('photo.png'), 'image/png');
  assert.equal(getContentType('binary.wasm'), 'application/octet-stream');
});

test('render404Page returns branded HTML 404 response', async () => {
  const res = render404Page('missing-project', 'mist.me');
  assert.equal(res.status, 404);
  assert.equal(res.headers.get('content-type'), 'text/html; charset=utf-8');
  const text = await res.text();
  assert.match(text, /404 NOT FOUND/);
  assert.match(text, /missing-project\.mist\.me/);
  assert.match(text, /Create on Mist/);
});

test('handlePublishedSite enforces reserved subdomains and format validation', async () => {
  const env: Env = {
    APEX_DOMAIN: 'mist.me',
    PUBLISHED_BUCKET: {
      get: async () => null,
    },
  };

  // 1. Reserved subdomain: www -> redirects to apex
  const wwwReq = new Request('https://www.mist.me/some/path');
  const wwwRes = await handlePublishedSite('www', wwwReq, new URL(wwwReq.url), env);
  assert.equal(wwwRes.status, 301);
  assert.equal(wwwRes.headers.get('location'), 'https://mist.me/some/path');

  // 2. Reserved subdomains: auth, admin, dashboard, assets, status, mail -> 403 Forbidden
  for (const reserved of ['auth', 'admin', 'dashboard', 'assets', 'status', 'mail']) {
    const req = new Request(`https://${reserved}.mist.me/`);
    const res = await handlePublishedSite(reserved, req, new URL(req.url), env);
    assert.equal(res.status, 403, `Subdomain ${reserved} should return 403`);
    const text = await res.text();
    assert.match(text, /reserved subdomain/i);
  }

  // 3. Invalid slug: too short or bad chars -> 400 Bad Request
  const badReq = new Request('https://bad--slug.mist.me/');
  const badRes = await handlePublishedSite('bad--slug', badReq, new URL(badReq.url), env);
  assert.equal(badRes.status, 400);

  // 4. Disallow non-GET/HEAD methods
  const postReq = new Request('https://valid-slug.mist.me/', { method: 'POST' });
  const postRes = await handlePublishedSite('valid-slug', postReq, new URL(postReq.url), env);
  assert.equal(postRes.status, 405);
});

test('handlePublishedSite serves R2 artifact and supports SPA fallback', async () => {
  const r2Storage = new Map<string, string>();
  r2Storage.set('sites/my-site/index.html', '<!DOCTYPE html><html><body>Published HTML</body></html>');
  r2Storage.set('sites/my-site/styles.css', 'body { color: blue; }');

  const env: Env = {
    APEX_DOMAIN: 'mist.me',
    PUBLISHED_BUCKET: {
      get: async (key: string) => {
        const content = r2Storage.get(key);
        if (!content) return null;
        return {
          body: new Response(content).body!,
          httpEtag: '"mock-etag-123"',
          httpMetadata: { contentType: getContentType(key) },
        };
      },
    },
  };

  // 1. Root index.html request
  const rootReq = new Request('https://my-site.mist.me/');
  const rootRes = await handlePublishedSite('my-site', rootReq, new URL(rootReq.url), env);
  assert.equal(rootRes.status, 200);
  assert.equal(rootRes.headers.get('content-type'), 'text/html; charset=utf-8');
  assert.equal(rootRes.headers.get('etag'), '"mock-etag-123"');
  assert.equal(rootRes.headers.get('x-frame-options'), 'DENY');
  assert.ok((rootRes.headers.get('content-security-policy') || '').includes('sandbox allow-scripts'));
  assert.ok((rootRes.headers.get('content-security-policy') || '').includes("frame-ancestors 'none'"));
  assert.match(rootRes.headers.get('cache-control') || '', /public/);
  const rootBody = await rootRes.text();
  assert.match(rootBody, /Published HTML/);

  // 2. Specific sub-resource request (styles.css)
  const cssReq = new Request('https://my-site.mist.me/styles.css');
  const cssRes = await handlePublishedSite('my-site', cssReq, new URL(cssReq.url), env);
  assert.equal(cssRes.status, 200);
  assert.equal(cssRes.headers.get('content-type'), 'text/css; charset=utf-8');
  const cssBody = await cssRes.text();
  assert.equal(cssBody, 'body { color: blue; }');

  // 3. SPA Route fallback (e.g. /dashboard/profile -> falls back to index.html)
  const spaReq = new Request('https://my-site.mist.me/dashboard/profile');
  const spaRes = await handlePublishedSite('my-site', spaReq, new URL(spaReq.url), env);
  assert.equal(spaRes.status, 200);
  assert.equal(spaRes.headers.get('content-type'), 'text/html; charset=utf-8');
  const spaBody = await spaRes.text();
  assert.match(spaBody, /Published HTML/);

  // 4. Missing project -> returns 404 page
  const missingReq = new Request('https://non-existent-site.mist.me/');
  const missingRes = await handlePublishedSite('non-existent-site', missingReq, new URL(missingReq.url), env);
  assert.equal(missingRes.status, 404);
  const missingBody = await missingRes.text();
  assert.match(missingBody, /Project Unavailable/);
});

test('proxyToHeroku sanitizes client headers, attaches edge origin secret, and preserves SSE streaming', async () => {
  let capturedTargetUrl = '';
  let capturedHeaders: Headers | null = null;
  let capturedMethod = '';

  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedTargetUrl = input.toString();
      capturedHeaders = new Headers(init?.headers);
      capturedMethod = init?.method || 'GET';

      // Simulate Heroku SSE response
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('data: {"status":"generating"}\n\n'));
          controller.close();
        },
      });

      return new Response(stream, {
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
        },
      });
    }) as any;

    const env: Env = {
      HEROKU_API_ORIGIN: 'https://mist-heroku-api.internal',
      MIST_EDGE_ORIGIN_SECRET: 'super-edge-secret-456',
      APEX_DOMAIN: 'mist.me',
    };

    const clientReq = new Request('https://mist.me/api/ai/generate/stream?model=auto', {
      method: 'POST',
      headers: {
        'x-mist-edge-secret': 'attacker-spoofed-secret', // Must be stripped and replaced!
        'cf-connecting-ip': '203.0.113.195',
        'authorization': 'Bearer clerk_test_token',
        'content-type': 'application/json',
      },
      body: JSON.stringify({ prompt: 'Build a store' }),
    });

    const res = await proxyToHeroku(clientReq, new URL(clientReq.url), env);

    assert.equal(capturedTargetUrl, 'https://mist-heroku-api.internal/api/ai/generate/stream?model=auto');
    assert.equal(capturedMethod, 'POST');
    assert.equal(capturedHeaders!.get('x-mist-edge-secret'), 'super-edge-secret-456');
    assert.equal(capturedHeaders!.get('authorization'), 'Bearer clerk_test_token');
    assert.equal(capturedHeaders!.get('cf-connecting-ip'), '203.0.113.195');
    assert.equal(capturedHeaders!.get('x-forwarded-host'), 'mist.me');

    // Verify response preserved SSE streaming headers
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('content-type'), 'text/event-stream');
    assert.equal(res.headers.get('x-accel-buffering'), 'no');
    assert.match(res.headers.get('cache-control') || '', /no-cache/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Worker fetch handler routes /cdn-health, apex static assets, and subdomains', async () => {
  let assetFetchCalled = false;
  const env: Env = {
    APEX_DOMAIN: 'mist.me',
    ASSETS: {
      fetch: async (req: Request) => {
        assetFetchCalled = true;
        return new Response('<html>Mist Vite App</html>', {
          headers: { 'Content-Type': 'text/html; charset=utf-8' },
        });
      },
    },
    PUBLISHED_BUCKET: {
      get: async () => null,
    },
  };

  // 1. Edge health check
  const healthRes = await worker.fetch(new Request('https://mist.me/cdn-health'), env);
  assert.equal(healthRes.status, 200);
  const healthJson = await healthRes.json();
  assert.equal(healthJson.status, 'healthy');

  // 2. Static asset request on apex
  const assetRes = await worker.fetch(new Request('https://mist.me/assets/index-D7P4gJS7.js'), env);
  assert.equal(assetRes.status, 200);
  assert.equal(assetFetchCalled, true);
  assert.match(assetRes.headers.get('cache-control') || '', /immutable/);

  // 3. Subdomain request routed to published site handler
  const subRes = await worker.fetch(new Request('https://unknown-subdomain.mist.me/'), env);
  assert.equal(subRes.status, 404);
  const subBody = await subRes.text();
  assert.match(subBody, /Project Unavailable/);

  // 4. Legacy /p/:slug on apex domain redirects to isolated subdomain
  const apexLegacyRes = await worker.fetch(new Request('https://mist.me/p/my-site'), env);
  assert.equal(apexLegacyRes.status, 301);
  assert.equal(apexLegacyRes.headers.get('location'), 'https://my-site.mist.me/');
});

test('Dedicated wildcard publishing domain and HEAD request routing', async () => {
  const r2Storage = new Map<string, string>();
  r2Storage.set('sites/portfolio-2026/index.html', '<!DOCTYPE html><html><body>Alice 2026 Portfolio</body></html>');

  const env: Env = {
    APEX_DOMAIN: 'mist.me',
    PUBLISH_DOMAIN: 'mist-sites.com',
    PUBLISHED_BUCKET: {
      get: async (key: string) => {
        const content = r2Storage.get(key);
        if (!content) return null;
        return {
          body: new Response(content).body!,
          httpEtag: '"mock-etag-portfolio"',
          httpMetadata: { contentType: 'text/html; charset=utf-8' },
        };
      },
    },
  };

  // 1. Dedicated publishing domain wildcard routing
  const pubReq = new Request('https://portfolio-2026.mist-sites.com/');
  const pubRes = await worker.fetch(pubReq, env);
  assert.equal(pubRes.status, 200);
  assert.equal(pubRes.headers.get('content-type'), 'text/html; charset=utf-8');
  assert.equal(pubRes.headers.get('etag'), '"mock-etag-portfolio"');
  const pubHtml = await pubRes.text();
  assert.match(pubHtml, /Alice 2026 Portfolio/);

  // 2. HEAD request on published site returns 200 with headers but empty body
  const headReq = new Request('https://portfolio-2026.mist-sites.com/', { method: 'HEAD' });
  const headRes = await worker.fetch(headReq, env);
  assert.equal(headRes.status, 200);
  assert.equal(headRes.headers.get('content-type'), 'text/html; charset=utf-8');
  assert.equal(headRes.headers.get('x-frame-options'), 'DENY');
  const headBody = await headRes.text();
  assert.equal(headBody, '');

  // 3. Request hitting the bare publishing domain redirects to the builder application
  const barePubReq = new Request('https://mist-sites.com/');
  const barePubRes = await worker.fetch(barePubReq, env);
  assert.equal(barePubRes.status, 302);
  assert.equal(barePubRes.headers.get('location'), 'https://mist.me/');

  // 4. Legacy redirect respects dedicated publishing domain
  const legacyReq = new Request('https://mist.me/p/portfolio-2026');
  const legacyRes = await worker.fetch(legacyReq, env);
  assert.equal(legacyRes.status, 301);
  assert.equal(legacyRes.headers.get('location'), 'https://portfolio-2026.mist-sites.com/');
});

test('Worker proxy forwards mutations to Express backend with edge origin verification and same-origin defense', async () => {
  const edgeSecret = 'test-edge-origin-secret-xyz123';
  const app = createMistApp({
    edgeOriginSecret: edgeSecret,
    adminStore: new InMemoryAdminStore(),
    r2Store: new InMemoryR2ArtifactStore(),
  });

  // Mutating endpoint on Express
  app.post('/api/test-mutation', (req, res) => {
    res.json({ ok: true, received: req.body });
  });

  // Start real local HTTP server for the Express backend
  const server = http.createServer(app);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', () => resolve()));
  const address = server.address() as { port: number };
  const backendOrigin = `http://127.0.0.1:${address.port}`;

  const env: Env = {
    APEX_DOMAIN: 'mist.me',
    HEROKU_API_ORIGIN: backendOrigin,
    MIST_EDGE_ORIGIN_SECRET: edgeSecret,
  };

  try {
    // 1. Valid mutation routed via Worker proxy: Browser Origin is mist.me, Host forwarded
    const clientReq = new Request('https://mist.me/api/test-mutation', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: 'https://mist.me',
      },
      body: JSON.stringify({ message: 'create-project' }),
    });

    const proxyRes = await proxyToHeroku(clientReq, new URL(clientReq.url), env);
    assert.equal(proxyRes.status, 200);
    const data = (await proxyRes.json()) as { ok: boolean; received: { message: string } };
    assert.equal(data.ok, true);
    assert.equal(data.received.message, 'create-project');

    // 2. Direct mutation to backend WITHOUT edge secret -> 403 Forbidden
    const directReqNoSecret = await fetch(`${backendOrigin}/api/test-mutation`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: 'https://mist.me',
      },
      body: JSON.stringify({ message: 'bypass-attempt' }),
    });
    assert.equal(directReqNoSecret.status, 403);

    // 3. Direct mutation to backend with invalid edge secret -> 403 Forbidden
    const directReqBadSecret = await fetch(`${backendOrigin}/api/test-mutation`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: 'https://mist.me',
        'x-mist-edge-secret': 'wrong-secret',
      },
      body: JSON.stringify({ message: 'bypass-attempt-2' }),
    });
    assert.equal(directReqBadSecret.status, 403);

    // 4. Cross-site mutation via Worker with untrusted origin -> 403 Forbidden
    const crossSiteReq = new Request('https://mist.me/api/test-mutation', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: 'https://evil-attacker.com',
      },
      body: JSON.stringify({ message: 'csrf-attack' }),
    });
    const crossSiteRes = await proxyToHeroku(crossSiteReq, new URL(crossSiteReq.url), env);
    assert.equal(crossSiteRes.status, 403);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
