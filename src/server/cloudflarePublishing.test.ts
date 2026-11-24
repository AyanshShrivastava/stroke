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

async function startPublishingTestServer(deps?: {
  adminStore?: InMemoryAdminStore;
  r2Store?: InMemoryR2ArtifactStore;
  publishBaseUrl?: string;
}) {
  const users = createMockUsers();
  const adminStore = deps?.adminStore || new InMemoryAdminStore();
  const r2Store = deps?.r2Store || new InMemoryR2ArtifactStore();
  const deploymentStore = createFirestoreDeploymentStore({ adminStore, r2Store });

  const app = createMistApp({
    deploymentStore,
    adminStore,
    r2Store,
    publishBaseUrl: deps?.publishBaseUrl || 'https://*.mist-sites.com',
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
    r2Store,
    deploymentStore,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

test('1. Publishing stores HTML bundle in Cloudflare R2 and metadata only in Firestore', async () => {
  const srv = await startPublishingTestServer();
  try {
    const deployPayload = {
      slug: 'alice-shop',
      projectId: 'proj_alice_1',
      title: 'Alice Artisan Shop',
      files: [
        { path: 'index.html', content: '<!DOCTYPE html><html><body><div id="root">Alice Store</div></body></html>' },
        { path: 'src/App.tsx', content: 'export default function App() { return <h1>Alice Store</h1>; }' },
      ],
    };

    const resp = await fetch(`${srv.baseUrl}/api/deployments`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify(deployPayload),
    });

    assert.equal(resp.status, 200);
    const data = (await resp.json()) as { slug: string; publishedUrl: string };
    assert.equal(data.slug, 'alice-shop');
    assert.equal(data.publishedUrl, 'https://alice-shop.mist-sites.com');

    // Verify Cloudflare R2 storage has the compiled HTML bundle
    const r2Exists = await srv.r2Store.artifactExists('alice-shop');
    assert.equal(r2Exists, true, 'HTML bundle must exist in R2');
    const r2Html = await srv.r2Store.getPublishedHtml('alice-shop');
    assert.match(r2Html || '', /Alice Store/);

    // Verify Firestore document stores metadata but NOT the full HTML bundle
    const firestoreDoc = await srv.adminStore.getDeployment('alice-shop');
    assert.ok(firestoreDoc, 'Firestore metadata must exist');
    assert.equal(firestoreDoc.ownerUid, 'user_alice');
    assert.equal(firestoreDoc.title, 'Alice Artisan Shop');
    assert.equal(firestoreDoc.artifactPath, 'sites/alice-shop/index.html');
    assert.equal(firestoreDoc.htmlBundle, '', 'Firestore must NOT store the full HTML bundle when R2 is active');
  } finally {
    await srv.close();
  }
});

test('2. Ownership Enforcement: Another user cannot overwrite or hijack an existing website', async () => {
  const srv = await startPublishingTestServer();
  try {
    // 1. Alice creates her website
    await fetch(`${srv.baseUrl}/api/deployments`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({
        slug: 'secure-portal',
        projectId: 'proj_alice',
        title: 'Alice Secure Portal',
        files: [
          { path: 'index.html', content: '<!DOCTYPE html><html><body><div id="root"></div></body></html>' },
          { path: 'src/App.tsx', content: 'export default function App() { return <h1>Alice Original Content</h1>; }' },
        ],
      }),
    });

    const originalR2Html = await srv.r2Store.getPublishedHtml('secure-portal');
    assert.match(originalR2Html || '', /Alice Original Content/);

    // 2. Bob attempts to overwrite Alice's website
    const bobAttempt = await fetch(`${srv.baseUrl}/api/deployments`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-bob',
      },
      body: JSON.stringify({
        slug: 'secure-portal',
        projectId: 'proj_bob',
        title: 'Malicious Hijack',
        files: [
          { path: 'index.html', content: '<!DOCTYPE html><html><body><div id="root"></div></body></html>' },
          { path: 'src/App.tsx', content: 'export default function App() { return <h1>Hacked by Bob</h1>; }' },
        ],
      }),
    });

    assert.equal(bobAttempt.status, 403, 'Must reject unauthorized deployment overwrite with 403');
    const bobJson = (await bobAttempt.json()) as { error: string };
    assert.match(bobJson.error, /Deployment slug belongs to another user/i);

    // 3. CRITICAL: Verify Alice's HTML in Cloudflare R2 was NOT overwritten!
    const r2AfterBob = await srv.r2Store.getPublishedHtml('secure-portal');
    assert.match(r2AfterBob || '', /Alice Original Content/);
    assert.doesNotMatch(r2AfterBob || '', /Hacked by Bob/);
  } finally {
    await srv.close();
  }
});

test('3. Deployment Updates: Owner can update their website, preserving metadata and updating R2', async () => {
  const srv = await startPublishingTestServer();
  try {
    // 1. Initial publish
    const r1 = await fetch(`${srv.baseUrl}/api/deployments`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({
        slug: 'living-site',
        projectId: 'proj_living',
        title: 'Version 1',
        files: [
          { path: 'index.html', content: '<!DOCTYPE html><html><body><div id="root"></div></body></html>' },
          { path: 'src/App.tsx', content: 'export default function App() { return <h1>V1 Content</h1>; }' },
        ],
      }),
    });
    assert.equal(r1.status, 200);

    const docV1 = await srv.adminStore.getDeployment('living-site');
    const createdAtV1 = docV1?.createdAt;

    // 2. Owner publishes an update
    const r2 = await fetch(`${srv.baseUrl}/api/deployments`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({
        slug: 'living-site',
        projectId: 'proj_living',
        title: 'Version 2 (Updated)',
        files: [
          { path: 'index.html', content: '<!DOCTYPE html><html><body><div id="root"></div></body></html>' },
          { path: 'src/App.tsx', content: 'export default function App() { return <h1>V2 Updated Content</h1>; }' },
        ],
      }),
    });
    assert.equal(r2.status, 200);

    // 3. R2 holds the new updated content
    const updatedHtml = await srv.r2Store.getPublishedHtml('living-site');
    assert.match(updatedHtml || '', /V2 Updated Content/);

    // 4. Firestore preserves createdAt and updates title
    const docV2 = await srv.adminStore.getDeployment('living-site');
    assert.equal(docV2?.title, 'Version 2 (Updated)');
    assert.equal(docV2?.createdAt, createdAtV1, 'createdAt timestamp must be preserved on updates');
  } finally {
    await srv.close();
  }
});

test('4. Deployment Deletion: Only owner can delete; deletes both Firestore metadata and R2 artifact', async () => {
  const srv = await startPublishingTestServer();
  try {
    // 1. Alice creates site
    await fetch(`${srv.baseUrl}/api/deployments`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer token-alice',
      },
      body: JSON.stringify({
        slug: 'to-be-deleted',
        projectId: 'proj_del',
        title: 'Delete Me',
        files: [
          { path: 'index.html', content: '<!DOCTYPE html><html><body><div id="root"></div></body></html>' },
          { path: 'src/App.tsx', content: 'export default function App() { return <h1>Temporary Site</h1>; }' },
        ],
      }),
    });

    assert.equal(await srv.r2Store.artifactExists('to-be-deleted'), true);

    // 2. Bob attempts to delete Alice's site
    const bobDel = await fetch(`${srv.baseUrl}/api/deployments/to-be-deleted`, {
      method: 'DELETE',
      headers: { Authorization: 'Bearer token-bob' },
    });
    assert.equal(bobDel.status, 403, 'Unauthorized user cannot delete site');

    // Site still exists in both stores
    assert.equal(await srv.r2Store.artifactExists('to-be-deleted'), true);
    assert.ok(await srv.adminStore.getDeployment('to-be-deleted'));

    // 3. Alice deletes her site
    const aliceDel = await fetch(`${srv.baseUrl}/api/deployments/to-be-deleted`, {
      method: 'DELETE',
      headers: { Authorization: 'Bearer token-alice' },
    });
    assert.equal(aliceDel.status, 200);

    // Site is removed from both Firestore and R2
    assert.equal(await srv.r2Store.artifactExists('to-be-deleted'), false, 'R2 artifact must be deleted');
    const docAfter = await srv.adminStore.getDeployment('to-be-deleted');
    assert.equal(docAfter, null, 'Firestore record must be deleted');

    // 4. Missing deployment deletion returns 404 or clean false
    const delMissing = await fetch(`${srv.baseUrl}/api/deployments/non-existent-xyz`, {
      method: 'DELETE',
      headers: { Authorization: 'Bearer token-alice' },
    });
    assert.equal(delMissing.status, 200); // Idempotent delete
  } finally {
    await srv.close();
  }
});
