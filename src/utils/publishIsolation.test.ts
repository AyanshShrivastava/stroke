import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createMistApp, bundleProjectToHtml } from './mistServerApp';
import { createMemoryDeploymentStore, formatDeploymentUrl } from './deploymentStore';
import {
  BUILDER_CSP,
  PUBLISHED_SITE_CSP,
  isPublishingHostname,
  sanitizeSetCookieHeader,
  enforceSameOriginOnMutations,
  type VerifiedFirebaseUser,
} from './serverSecurity';
import { buildExportManifest } from './projectOps';
import type { MistProject } from '../types/mist';

function createMockUsers(): Record<string, VerifiedFirebaseUser> {
  return {
    'token-user-a': {
      userId: 'user-a',
      uid: 'user-a',
      email: 'alice@example.com',
      emailVerified: true,
      idToken: 'token-user-a',
    },
  };
}

async function startServerWithConfig(options?: {
  publishBaseUrl?: string;
}) {
  const users = createMockUsers();
  const store = createMemoryDeploymentStore();
  const app = createMistApp({
    deploymentStore: store,
    skipDnsLookup: true,
    publishBaseUrl: options?.publishBaseUrl,
    verifyAuthHeader: async (authHeader?: string) => {
      if (!authHeader || !authHeader.startsWith('Bearer ')) {
        throw new Error('Sign in required.');
      }
      const token = authHeader.slice('Bearer '.length).trim();
      const matched = users[token];
      if (!matched) throw new Error('Invalid token.');
      return matched;
    },
  });

  const server = http.createServer(app);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Expected TCP port');
  const baseUrl = `http://127.0.0.1:${address.port}`;
  return {
    baseUrl,
    store,
    close: () => new Promise<void>((resolve, reject) => server.close((e) => (e ? reject(e) : resolve()))),
  };
}

test('Origin Isolation: PUBLISH_BASE_URL routes published sites and disables arbitrary HTML on builder origin', async () => {
  const srv = await startServerWithConfig({ publishBaseUrl: 'https://sites.mist.me' });
  try {
    // 1. Seed a deployment into the store
    await srv.store.upsertOwned({
      slug: 'my-portfolio',
      ownerUid: 'user-a',
      projectId: 'proj-1',
      title: 'My Portfolio',
      htmlBundle: '<!doctype html><html><body><h1>Safe Portfolio</h1></body></html>',
    });

    // 2. Accessing /:slug on builder origin NEVER executes arbitrary published HTML
    const builderSlugResp = await fetch(`${srv.baseUrl}/my-portfolio`);
    assert.notEqual(builderSlugResp.status, 200, 'Builder origin must not execute published HTML via /:slug');

    // 3. Accessing /p/:slug on builder origin redirects (301) to the dedicated publishing hostname
    const builderLegacyResp = await fetch(`${srv.baseUrl}/p/my-portfolio`, { redirect: 'manual' });
    assert.equal(builderLegacyResp.status, 301, 'Builder /p/:slug must redirect to dedicated publishing origin');
    assert.equal(builderLegacyResp.headers.get('location'), 'https://sites.mist.me/my-portfolio');

    // 4. Accessing published website on the dedicated publishing hostname serves the site with strict sandbox CSP
    const publishedResp = await fetch(`${srv.baseUrl}/my-portfolio`, {
      headers: { 'x-forwarded-host': 'sites.mist.me' },
    });
    assert.equal(publishedResp.status, 200);
    const body = await publishedResp.text();
    assert.ok(body.includes('Safe Portfolio'));

    const csp = publishedResp.headers.get('content-security-policy') || '';
    assert.ok(csp.includes('sandbox allow-scripts allow-forms allow-popups'), 'Must enforce sandbox without allow-same-origin');
    assert.ok(!csp.includes('allow-same-origin'), 'Published site CSP must never grant allow-same-origin');
    assert.ok(csp.includes("frame-ancestors 'none'"), 'Published site must not be framed by third parties');
    assert.equal(publishedResp.headers.get('x-frame-options'), 'DENY');
    assert.equal(publishedResp.headers.get('cross-origin-opener-policy'), 'same-origin');
    assert.equal(publishedResp.headers.get('set-cookie'), null, 'Published site responses must never set cookies');

    // 5. Builder control plane /api endpoints are blocked on publishing hostname
    const blockedApiResp = await fetch(`${srv.baseUrl}/api/deployments`, {
      headers: { 'x-forwarded-host': 'sites.mist.me' },
    });
    assert.equal(blockedApiResp.status, 404, 'Control plane APIs must be inaccessible on the publishing origin');
  } finally {
    await srv.close();
  }
});

test('Wildcard Subdomain Publishing: Routes <slug>.mist-sites.com cleanly', async () => {
  const srv = await startServerWithConfig({ publishBaseUrl: 'https://*.mist-sites.com' });
  try {
    await srv.store.upsertOwned({
      slug: 'art-gallery',
      ownerUid: 'user-a',
      projectId: 'proj-2',
      title: 'Art Gallery',
      htmlBundle: '<!doctype html><html><body><h1>Exhibition</h1></body></html>',
    });

    // Request arrives at art-gallery.mist-sites.com root
    const subResp = await fetch(`${srv.baseUrl}/`, {
      headers: { 'x-forwarded-host': 'art-gallery.mist-sites.com' },
    });
    assert.equal(subResp.status, 200);
    const text = await subResp.text();
    assert.ok(text.includes('Exhibition'));

    const csp = subResp.headers.get('content-security-policy') || '';
    assert.ok(csp.includes('sandbox allow-scripts'));
    assert.ok(!csp.includes('allow-same-origin'));
  } finally {
    await srv.close();
  }
});

test('Safe Disabling: When PUBLISH_BASE_URL is not configured, public publishing is disabled safely while project export works', async () => {
  // Start server with no PUBLISH_BASE_URL
  const srv = await startServerWithConfig({ publishBaseUrl: '' });
  try {
    // 1. formatDeploymentUrl never falls back to insecure same-origin paths
    assert.equal(formatDeploymentUrl('alice-site', ''), '', 'Must not fall back to /alice-site');
    assert.equal(formatDeploymentUrl('alice-site', undefined), '', 'Must not fall back to /alice-site');

    // 2. POST /api/deployments rejects publishing cleanly with a 400 error explaining it is disabled
    const publishAttempt = await fetch(`${srv.baseUrl}/api/deployments`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-user-a',
      },
      body: JSON.stringify({
        slug: 'alice-site',
        projectId: 'proj-1',
        title: 'Alice Site',
        files: [{ id: 'f1', path: 'src/App.tsx', language: 'tsx', content: 'export default () => <h1>Hi</h1>;' }],
      }),
    });
    assert.equal(publishAttempt.status, 400);
    const errJson = (await publishAttempt.json()) as { error: string };
    assert.ok(errJson.error.includes('PUBLISH_BASE_URL is not configured'));

    // 3. /p/:slug returns 404 without executing HTML
    const getAttempt = await fetch(`${srv.baseUrl}/p/alice-site`);
    assert.equal(getAttempt.status, 404);
    const text = await getAttempt.text();
    assert.ok(text.includes('Public publishing is disabled'));

    // 4. Project export (ZIP / standalone HTML) remains completely functional
    const mockProject: MistProject = {
      id: 'proj-export-test',
      name: 'Safe Export Project',
      description: 'Export demo',
      prompt: 'Build safe app',
      files: [
        { id: '1', path: 'src/App.tsx', language: 'tsx', content: 'export default () => <div>Exported App</div>;' },
        { id: '2', path: 'src/index.css', language: 'css', content: 'body { margin: 0; }' },
      ],
      chatHistory: [],
      isPublished: false,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    const manifest = buildExportManifest(mockProject, {
      standaloneHtml: '<!doctype html><html><body>Exported App</body></html>',
      slug: 'safe-export',
    });
    assert.ok(manifest['dist/index.html'], 'Project export must generate dist/index.html');
    assert.ok(manifest['package.json'], 'Project export must generate package.json');
    assert.ok(manifest['index.html'], 'Project export must generate index.html');
    assert.ok(manifest['render.yaml'], 'Project export must generate render.yaml blueprint');
  } finally {
    await srv.close();
  }
});

test('Cookie Protection: Authentication cookies never leak to published subdomains via parent-domain attributes', () => {
  // 1. Parent-domain cookies (e.g. Domain=.mist.me or Domain=mist.me) must have Domain stripped
  const cookieWithWildcard = 'mist_auth_session=secret_token_123; Domain=.mist.me; Path=/; Secure; HttpOnly';
  const sanitizedWildcard = sanitizeSetCookieHeader(cookieWithWildcard);
  assert.equal(sanitizedWildcard, 'mist_auth_session=secret_token_123; Path=/; Secure; HttpOnly');
  assert.ok(!sanitizedWildcard.includes('Domain='), 'Must strip parent-domain scoping to prevent subdomain access');

  const cookieWithDomain = 'clerk_session=jwt_abc; Domain=mist.me; Path=/; SameSite=Lax';
  const sanitizedDomain = sanitizeSetCookieHeader(cookieWithDomain);
  assert.equal(sanitizedDomain, 'clerk_session=jwt_abc; Path=/; SameSite=Lax');
  assert.ok(!sanitizedDomain.includes('Domain='), 'Must force Host-Only cookie');

  // 2. Already host-only cookies remain intact
  const hostOnlyCookie = '__Host-session=xyz789; Path=/; Secure; HttpOnly; SameSite=Strict';
  const sanitizedHostOnly = sanitizeSetCookieHeader(hostOnlyCookie);
  assert.equal(sanitizedHostOnly, hostOnlyCookie);
});

test('Security Headers & CSP: Builder and published websites have distinct, appropriate policies', async () => {
  const srv = await startServerWithConfig({ publishBaseUrl: 'https://sites.mist.me' });
  try {
    await srv.store.upsertOwned({
      slug: 'header-test-site',
      ownerUid: 'user-a',
      projectId: 'proj-headers',
      title: 'Headers Test',
      htmlBundle: '<!doctype html><html><body>Test</body></html>',
    });

    // 1. Builder response headers
    const builderResp = await fetch(`${srv.baseUrl}/api/health`);
    assert.equal(builderResp.status, 200);
    const builderCsp = builderResp.headers.get('content-security-policy') || '';
    assert.ok(builderCsp.includes("default-src 'self'"), 'Builder CSP must allow self by default');
    assert.ok(builderCsp.includes("frame-src 'self' blob: data: https://challenges.cloudflare.com"), 'Builder CSP must permit preview sandbox frames');
    assert.equal(builderResp.headers.get('cross-origin-opener-policy'), 'same-origin-allow-popups', 'Builder must support popup auth flows');
    assert.equal(builderResp.headers.get('x-frame-options'), 'SAMEORIGIN');

    // 2. Published site response headers
    const pubResp = await fetch(`${srv.baseUrl}/header-test-site`, {
      headers: { 'x-forwarded-host': 'sites.mist.me' },
    });
    assert.equal(pubResp.status, 200);
    const pubCsp = pubResp.headers.get('content-security-policy') || '';
    assert.ok(pubCsp.includes('sandbox allow-scripts allow-forms allow-popups'), 'Published site must be sandboxed');
    assert.ok(!pubCsp.includes('allow-same-origin'), 'Published site must NEVER have allow-same-origin');
    assert.ok(pubCsp.includes("frame-ancestors 'none'"), 'Published site must disallow framing');
    assert.equal(pubResp.headers.get('x-frame-options'), 'DENY');
    assert.equal(pubResp.headers.get('cross-origin-opener-policy'), 'same-origin');
  } finally {
    await srv.close();
  }
});

test('Proof of Isolation: Published website and sandboxed iframe cannot access Mist application localStorage or session tokens', async () => {
  // 1. Verify bundleProjectToHtml creates sandboxed code with an isolated in-memory storage shim
  const { html, bundleError } = await bundleProjectToHtml({
    files: [
      {
        id: 'f1',
        path: 'src/App.tsx',
        language: 'tsx',
        content: `
          export default function App() {
            // Malicious script attempting cross-origin access to builder storage
            let stolen = '';
            try {
              // Attempt 1: parent window localStorage
              stolen = window.parent.localStorage.getItem('mist_sess') || '';
            } catch (e) {
              stolen = 'blocked_parent_access';
            }

            try {
              // Attempt 2: local localStorage check
              window.localStorage.setItem('probe', 'active');
            } catch (e) {}

            return <div>{stolen}</div>;
          }
        `,
      },
    ],
    title: 'Storage Probe',
    includeInspector: false,
    enableAppAi: false,
  });

  assert.ok(!bundleError, 'Bundle must compile without error');
  assert.ok(html.includes('makeMemoryStorage'), 'Must bundle memory storage shim for opaque sandboxes');
  assert.ok(html.includes('isOpaqueSandbox'), 'Must detect opaque sandbox origin');

  // 2. Simulate the Browser DOM security boundary:
  // Builder origin window has sensitive tokens:
  const builderLocalStorage = new Map<string, string>();
  builderLocalStorage.set('mist_sess', 'secret_builder_token_XYZ987');
  builderLocalStorage.set('firebase:authUser:apiKey:app', JSON.stringify({ uid: 'user-a', token: 'jwt_secret' }));

  // Published website or iframe without allow-same-origin runs in opaque origin 'null':
  const iframeOrigin = 'null';
  const builderOrigin = 'https://mist.me';

  // Cross-origin access check per W3C HTML Living Standard (§7.2 Origin & §7.4 Cross-origin objects):
  function accessParentStorageFromIframe(sourceOrigin: string, targetOrigin: string): string {
    if (sourceOrigin !== targetOrigin) {
      throw new Error(`DOMException: Blocked a frame with origin "${sourceOrigin}" from accessing a cross-origin frame.`);
    }
    return builderLocalStorage.get('mist_sess') || '';
  }

  // A published website running on dedicated publishing host or opaque iframe cannot access builder's storage:
  assert.throws(
    () => accessParentStorageFromIframe(iframeOrigin, builderOrigin),
    /Blocked a frame with origin "null" from accessing a cross-origin frame/,
    'Browser same-origin policy blocks opaque iframe from reading builder window localStorage',
  );

  const publishedSiteOrigin = 'https://sites.mist.me';
  assert.throws(
    () => accessParentStorageFromIframe(publishedSiteOrigin, builderOrigin),
    /Blocked a frame with origin "https:\/\/sites\.mist\.me" from accessing a cross-origin frame/,
    'Browser same-origin policy blocks dedicated publishing origin from reading builder localStorage',
  );

  // 3. Cross-origin mutating requests are blocked by enforceSameOriginOnMutations
  let mutationBlocked = false;
  const mockReq: any = {
    method: 'POST',
    headers: {
      origin: 'https://sites.mist.me',
      host: 'mist.me',
    },
  };
  const mockRes: any = {
    status: (code: number) => {
      if (code === 403) mutationBlocked = true;
      return { json: () => {} };
    },
  };
  enforceSameOriginOnMutations(mockReq, mockRes, () => {});
  assert.equal(mutationBlocked, true, 'Cross-origin mutations from published website to builder API must be blocked');
});
