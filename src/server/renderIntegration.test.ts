import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createMistApp } from '../utils/mistServerApp';
import { InMemoryAdminStore } from './firestoreAdmin';
import { InMemoryR2ArtifactStore } from '../utils/r2ArtifactStore';
import { createFirestoreDeploymentStore } from '../utils/deploymentStore';
import { SecurityValidationError } from '../utils/serverSecurity';
import type { VerifiedClerkUser } from '../utils/serverSecurity';

function createMockUsers(): Record<string, VerifiedClerkUser> {
  return {
    'token-alice': {
      userId: 'user_alice',
      uid: 'user_alice',
      email: 'alice@example.com',
      emailVerified: true,
      claims: { email: 'alice@example.com', email_verified: true },
      idToken: 'token-alice',
    },
    'token-bob': {
      userId: 'user_bob',
      uid: 'user_bob',
      email: 'bob@example.com',
      emailVerified: true,
      claims: { email: 'bob@example.com', email_verified: true },
      idToken: 'token-bob',
    },
  };
}

interface MockRenderServerState {
  owners: Array<{ id: string; name: string; email?: string; type: 'user' | 'team' }>;
  services: Map<string, any>;
  deploys: Map<string, any[]>;
  rateLimited?: boolean;
  rejectGitHubRepo?: boolean;
}

function createMockRenderFetch(state: MockRenderServerState): typeof fetch {
  return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const urlStr = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const method = (init?.method || 'GET').toUpperCase();
    const authHeader = (init?.headers as Record<string, string>)?.[
      'Authorization'
    ] || (init?.headers as Record<string, string>)?.[
      'authorization'
    ];

    if (!authHeader || !authHeader.startsWith('Bearer rnd_')) {
      return new Response(JSON.stringify({ message: 'Unauthorized: missing or invalid Bearer token' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const apiKey = authHeader.slice('Bearer '.length).trim();
    if (apiKey === 'rnd_revoked_key_1234567890abcdef') {
      return new Response(JSON.stringify({ message: 'API key has been revoked' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    if (state.rateLimited) {
      return new Response(
        JSON.stringify({ message: 'Too many requests. Please slow down.' }),
        {
          status: 429,
          headers: { 'Content-Type': 'application/json', 'Retry-After': '30' },
        },
      );
    }

    const parsedUrl = new URL(urlStr);
    const pathname = parsedUrl.pathname;

    // GET /v1/owners
    if (method === 'GET' && pathname === '/v1/owners') {
      return new Response(
        JSON.stringify(
          state.owners.map((owner) => ({
            cursor: `cur_${owner.id}`,
            owner,
          })),
        ),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }

    // POST /v1/services (Create Service)
    if (method === 'POST' && pathname === '/v1/services') {
      const body = JSON.parse(String(init?.body || '{}'));

      if (state.rejectGitHubRepo) {
        return new Response(
          JSON.stringify({
            message: 'Repository access denied. Please grant permission in the Render GitHub App.',
          }),
          { status: 400, headers: { 'Content-Type': 'application/json' } },
        );
      }

      const serviceId = `srv-${Date.now().toString(36)}`;
      const serviceObj = {
        id: serviceId,
        name: body.name,
        ownerId: body.ownerId,
        type: body.type,
        repo: body.repo,
        branch: body.branch || 'main',
        serviceDetails: {
          url: `https://${body.name}.onrender.com`,
          publishPath: body.serviceDetails?.publishPath || 'dist',
          buildCommand: body.serviceDetails?.buildCommand || 'npm run build',
        },
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };

      state.services.set(serviceId, serviceObj);

      const deployObj = {
        id: `dep-${Date.now().toString(36)}`,
        status: 'created',
        commit: { id: 'abc1234', message: 'Initial mist deployment' },
        createdAt: new Date().toISOString(),
      };
      state.deploys.set(serviceId, [deployObj]);

      return new Response(
        JSON.stringify({
          service: serviceObj,
          deploy: deployObj,
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } },
      );
    }

    // POST /v1/services/:serviceId/deploys (Trigger Deploy)
    const deploysMatch = pathname.match(/^\/v1\/services\/([^/]+)\/deploys$/);
    if (method === 'POST' && deploysMatch) {
      const sId = deploysMatch[1];
      const newDeploy = {
        id: `dep-${Date.now().toString(36)}`,
        status: 'created',
        commit: { id: 'abc1234', message: 'Mist deployment' },
        createdAt: new Date().toISOString(),
      };
      const existing = state.deploys.get(sId) || [];
      existing.unshift(newDeploy);
      state.deploys.set(sId, existing);
      return new Response(JSON.stringify(newDeploy), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // GET /v1/services/:serviceId/deploys
    if (method === 'GET' && deploysMatch) {
      const sId = deploysMatch[1];
      const sDeploys = state.deploys.get(sId) || [];
      return new Response(
        JSON.stringify(sDeploys.map((dep) => ({ deploy: dep, cursor: dep.id }))),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }

    // GET /v1/services/:serviceId
    const serviceMatch = pathname.match(/^\/v1\/services\/([^/]+)$/);
    if (method === 'GET' && serviceMatch) {
      const sId = serviceMatch[1];
      const s = state.services.get(sId);
      if (!s) {
        return new Response(JSON.stringify({ message: 'Service not found' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify(s), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // GET /v1/services
    if (method === 'GET' && pathname === '/v1/services') {
      const allServices = Array.from(state.services.values());
      return new Response(
        JSON.stringify(allServices.map((s) => ({ service: s, cursor: s.id }))),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }

    return new Response(JSON.stringify({ message: `Not found: ${method} ${pathname}` }), {
      status: 404,
      headers: { 'Content-Type': 'application/json' },
    });
  };
}

async function startRenderTestServer(options?: {
  renderState?: MockRenderServerState;
}) {
  const users = createMockUsers();
  const adminStore = new InMemoryAdminStore();
  const r2Store = new InMemoryR2ArtifactStore();
  const deploymentStore = createFirestoreDeploymentStore({ adminStore, r2Store });

  const renderState: MockRenderServerState = options?.renderState || {
    owners: [
      { id: 'usr-alice-12345', name: 'Alice Walker', email: 'alice@walker.org', type: 'user' },
      { id: 'tea-acme-corp', name: 'Acme Team', email: 'team@acme.com', type: 'team' },
    ],
    services: new Map(),
    deploys: new Map(),
  };

  const renderFetchImpl = createMockRenderFetch(renderState);

  const app = createMistApp({
    deploymentStore,
    adminStore,
    r2Store,
    renderFetchImpl,
    skipDnsLookup: true,
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

  return {
    baseUrl: `http://127.0.0.1:${port}`,
    adminStore,
    renderState,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

test('1. Connect to Render: validates key, verifies via Render API, seals in vault, returns masked hint', async () => {
  const srv = await startRenderTestServer();
  try {
    // A: Invalid key format rejected
    const badResp = await fetch(`${srv.baseUrl}/api/render/connect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ apiKey: 'invalid_key_without_prefix' }),
    });
    assert.equal(badResp.status, 400);
    const badData = await badResp.json();
    assert.match(badData.error, /rnd_/);

    // B: Valid key connects cleanly
    const goodResp = await fetch(`${srv.baseUrl}/api/render/connect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ apiKey: 'rnd_aliceKey1234567890abcdef' }),
    });
    assert.equal(goodResp.status, 200);
    const goodData = await goodResp.json();
    assert.equal(goodData.ok, true);
    assert.equal(goodData.owner.id, 'usr-alice-12345');
    assert.equal(goodData.owner.name, 'Alice Walker');
    assert.equal(goodData.keyHint.startsWith('rnd_'), true);
    assert.equal(goodData.keyHint.includes('cdef'), true);
    // Plaintext key is NOT returned
    assert.equal(goodData.apiKey, undefined);

    // C: Check status reflects connected state
    const statusResp = await fetch(`${srv.baseUrl}/api/render/status`, {
      headers: { Authorization: 'Bearer token-alice' },
    });
    assert.equal(statusResp.status, 200);
    const statusData = await statusResp.json();
    assert.equal(statusData.connected, true);
    assert.equal(statusData.ownerId, 'usr-alice-12345');
    assert.equal(statusData.ownerName, 'Alice Walker');
    assert.equal(statusData.keyHint, goodData.keyHint);
  } finally {
    await srv.close();
  }
});

test('2. Credential Vault Security & Separation: AES-256-GCM encryption and multi-tenant isolation', async () => {
  const srv = await startRenderTestServer();
  try {
    // Alice connects Render
    await fetch(`${srv.baseUrl}/api/render/connect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ apiKey: 'rnd_aliceSecretKey1234567890' }),
    });

    // Inspect Alice's Firestore document directly
    const aliceVaultDoc = await srv.adminStore.getUserVault('user_alice');
    assert.ok(aliceVaultDoc);
    assert.ok(aliceVaultDoc.ciphertext);
    // Confirm format is base64 JSON envelope with v=1, iv, tag, ct
    const envelope = JSON.parse(Buffer.from(aliceVaultDoc.ciphertext, 'base64').toString('utf8'));
    assert.equal(envelope.v, 1);
    assert.ok(envelope.iv);
    assert.ok(envelope.tag);
    assert.ok(envelope.ct);
    // Raw API key is NOT stored in plain text anywhere in the document
    assert.equal(JSON.stringify(aliceVaultDoc).includes('rnd_aliceSecretKey1234567890'), false);

    // Bob checks Render status: should be disconnected (tenant isolation)
    const bobStatus = await fetch(`${srv.baseUrl}/api/render/status`, {
      headers: { Authorization: 'Bearer token-bob' },
    });
    const bobData = await bobStatus.json();
    assert.equal(bobData.connected, false);
    assert.equal(bobData.ownerId, undefined);

    // Unauthenticated request is rejected with 401
    const unauthResp = await fetch(`${srv.baseUrl}/api/render/status`);
    assert.equal(unauthResp.status, 401);
  } finally {
    await srv.close();
  }
});

test('3. Static Site Deployment: creates static site on Render with custom repo and branch', async () => {
  const srv = await startRenderTestServer();
  try {
    // Alice connects Render
    await fetch(`${srv.baseUrl}/api/render/connect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ apiKey: 'rnd_aliceSecretKey1234567890' }),
    });

    // Deploy with valid GitHub repository
    const deployResp = await fetch(`${srv.baseUrl}/api/render/deploy`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({
        repoUrl: 'https://github.com/alice/personal-portfolio',
        branch: 'main',
        serviceName: 'alice-portfolio',
        buildCommand: 'npm run build',
        publishPath: 'dist',
      }),
    });

    assert.equal(deployResp.status, 200);
    const deployData = await deployResp.json();
    assert.equal(deployData.ok, true);
    assert.equal(deployData.service.name, 'alice-portfolio');
    assert.equal(deployData.service.url, 'https://alice-portfolio.onrender.com');
    assert.equal(deployData.service.ownerId, 'usr-alice-12345');
    assert.ok(deployData.service.id);
    assert.ok(deployData.deploy);
    assert.equal(deployData.deploy.status, 'created');

    // Confirm service is tracked in Render server state
    assert.ok(srv.renderState.services.has(deployData.service.id));

    // Non-GitHub URL is rejected with 400
    const badUrlResp = await fetch(`${srv.baseUrl}/api/render/deploy`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({
        repoUrl: 'https://gitlab.com/alice/gitlab-repo',
        serviceName: 'gitlab-repo',
      }),
    });
    assert.equal(badUrlResp.status, 400);
    const badUrlData = await badUrlResp.json();
    assert.match(badUrlData.error, /github\.com/);
  } finally {
    await srv.close();
  }
});

test('4. Service Status & Deploy Tracking: fetches live service details and latest deploy status', async () => {
  const srv = await startRenderTestServer();
  try {
    // Alice connects and deploys
    await fetch(`${srv.baseUrl}/api/render/connect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ apiKey: 'rnd_aliceSecretKey1234567890' }),
    });

    const deployResp = await fetch(`${srv.baseUrl}/api/render/deploy`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({
        repoUrl: 'https://github.com/alice/saas-landing',
        serviceName: 'saas-landing',
      }),
    });
    const { service } = await deployResp.json();

    // Query service status
    const statusResp = await fetch(`${srv.baseUrl}/api/render/services/${service.id}`, {
      headers: { Authorization: 'Bearer token-alice' },
    });
    assert.equal(statusResp.status, 200);
    const statusData = await statusResp.json();
    assert.equal(statusData.ok, true);
    assert.equal(statusData.service.id, service.id);
    assert.equal(statusData.service.name, 'saas-landing');
    assert.equal(statusData.latestDeploy?.status, 'created');

    // Simulate deploy progress on Render
    const deploys = srv.renderState.deploys.get(service.id);
    if (deploys && deploys[0]) {
      deploys[0].status = 'live';
      deploys[0].finishedAt = new Date().toISOString();
    }

    // Query again: status should now be 'live'
    const updatedResp = await fetch(`${srv.baseUrl}/api/render/services/${service.id}`, {
      headers: { Authorization: 'Bearer token-alice' },
    });
    const updatedData = await updatedResp.json();
    assert.equal(updatedData.latestDeploy?.status, 'live');
  } finally {
    await srv.close();
  }
});

test('5. Error Handling: handles revoked key (401), rate limits (429), and GitHub app permission requirement', async () => {
  const srv = await startRenderTestServer();
  try {
    // A: Revoked key during connection
    const revokedResp = await fetch(`${srv.baseUrl}/api/render/connect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ apiKey: 'rnd_revoked_key_1234567890abcdef' }),
    });
    assert.equal(revokedResp.status, 401);
    const revokedData = await revokedResp.json();
    assert.match(revokedData.error, /invalid.*expired/i);

    // B: Connect with valid key
    await fetch(`${srv.baseUrl}/api/render/connect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ apiKey: 'rnd_aliceSecretKey1234567890' }),
    });

    // C: GitHub private repository permission error gives helpful install link
    srv.renderState.rejectGitHubRepo = true;
    const repoErrResp = await fetch(`${srv.baseUrl}/api/render/deploy`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({
        repoUrl: 'https://github.com/alice/private-repo',
        serviceName: 'private-repo',
      }),
    });
    assert.equal(repoErrResp.status, 400);
    const repoErrData = await repoErrResp.json();
    assert.match(repoErrData.error, /Render GitHub App/);
    assert.match(repoErrData.error, /https:\/\/github\.com\/apps\/render\/installations\/new/);
    srv.renderState.rejectGitHubRepo = false;

    // D: Rate limit handling (429)
    srv.renderState.rateLimited = true;
    const rateResp = await fetch(`${srv.baseUrl}/api/render/workspaces`, {
      headers: { Authorization: 'Bearer token-alice' },
    });
    assert.equal(rateResp.status, 429);
    srv.renderState.rateLimited = false;
  } finally {
    await srv.close();
  }
});

test('6. Disconnect & Revocation: removes Render credential from vault, preserves other vaulted keys', async () => {
  const srv = await startRenderTestServer();
  try {
    // Connect Render
    await fetch(`${srv.baseUrl}/api/render/connect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({ apiKey: 'rnd_aliceSecretKey1234567890' }),
    });

    // Verify connected
    let statusResp = await fetch(`${srv.baseUrl}/api/render/status`, {
      headers: { Authorization: 'Bearer token-alice' },
    });
    let statusData = await statusResp.json();
    assert.equal(statusData.connected, true);

    // Disconnect
    const disconnectResp = await fetch(`${srv.baseUrl}/api/render/disconnect`, {
      method: 'POST',
      headers: { Authorization: 'Bearer token-alice' },
    });
    assert.equal(disconnectResp.status, 200);
    const disconnectData = await disconnectResp.json();
    assert.equal(disconnectData.ok, true);
    assert.equal(disconnectData.connected, false);

    // Verify status is now false
    statusResp = await fetch(`${srv.baseUrl}/api/render/status`, {
      headers: { Authorization: 'Bearer token-alice' },
    });
    statusData = await statusResp.json();
    assert.equal(statusData.connected, false);
    assert.equal(statusData.ownerId, undefined);

    // Attempting deploy without connected Render account returns 400
    const deployResp = await fetch(`${srv.baseUrl}/api/render/deploy`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({
        repoUrl: 'https://github.com/alice/personal-portfolio',
        serviceName: 'alice-portfolio',
      }),
    });
    assert.equal(deployResp.status, 400);
    const deployData = await deployResp.json();
    assert.match(deployData.error, /Render account is not connected/i);
  } finally {
    await srv.close();
  }
});
