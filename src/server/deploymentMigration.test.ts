import { test } from 'node:test';
import assert from 'node:assert/strict';
import { migrateDeploymentsToR2 } from './deploymentMigration';
import { InMemoryAdminStore } from './firestoreAdmin';
import { InMemoryR2ArtifactStore } from '../utils/r2ArtifactStore';

test('1. Dry run identifies eligible deployments without modifying Firestore or R2', async () => {
  const adminStore = new InMemoryAdminStore();
  const r2Store = new InMemoryR2ArtifactStore();

  // Seed legacy deployments in Firestore with raw htmlBundle
  await adminStore.saveDeployment('user_alice', {
    slug: 'legacy-site-1',
    projectId: 'proj_1',
    title: 'Legacy Site One',
    htmlBundle: '<!DOCTYPE html><html><body>Site One</body></html>',
  });
  await adminStore.saveDeployment('user_alice', {
    slug: 'legacy-site-2',
    projectId: 'proj_2',
    title: 'Legacy Site Two',
    htmlBundle: '<!DOCTYPE html><html><body>Site Two</body></html>',
  });

  const report = await migrateDeploymentsToR2({
    adminStore,
    r2Store,
    dryRun: true,
  });

  assert.equal(report.dryRun, true);
  assert.equal(report.applied, false);
  assert.equal(report.totalFound, 2);
  assert.equal(report.migratedCount, 2);
  assert.equal(report.alreadyMigratedCount, 0);
  assert.equal(report.failedCount, 0);

  // In dry run, files must NOT have been written to R2
  assert.equal(await r2Store.artifactExists('legacy-site-1'), false);
  assert.equal(await r2Store.artifactExists('legacy-site-2'), false);

  // In dry run, Firestore still holds the HTML bundle
  const d1 = await adminStore.getDeployment('legacy-site-1');
  assert.ok(d1?.htmlBundle.includes('Site One'));
});

test('2. Live apply migrates HTML bundles to R2 and cleans up Firestore htmlBundle', async () => {
  const adminStore = new InMemoryAdminStore();
  const r2Store = new InMemoryR2ArtifactStore();

  await adminStore.saveDeployment('user_bob', {
    slug: 'portfolio-bob',
    projectId: 'proj_bob',
    title: 'Bob Portfolio',
    htmlBundle: '<!DOCTYPE html><html><body>Bob Web Site</body></html>',
  });

  const report = await migrateDeploymentsToR2({
    adminStore,
    r2Store,
    apply: true,
  });

  assert.equal(report.applied, true);
  assert.equal(report.migratedCount, 1);
  assert.equal(report.failedCount, 0);

  // Artifact now exists in R2
  const existsInR2 = await r2Store.artifactExists('portfolio-bob');
  assert.equal(existsInR2, true);
  const r2Html = await r2Store.getPublishedHtml('portfolio-bob');
  assert.match(r2Html || '', /Bob Web Site/);

  // Deployment metadata is preserved and htmlBundle cleaned from Firestore store
  const doc = await adminStore.getDeployment('portfolio-bob');
  assert.equal(doc?.slug, 'portfolio-bob');
  assert.equal(doc?.ownerUid, 'user_bob');
  assert.equal(doc?.title, 'Bob Portfolio');
  assert.equal(doc?.htmlBundle, '');
  assert.equal(doc?.artifactPath, 'sites/portfolio-bob/index.html');
});

test('3. Already migrated deployments in R2 are skipped cleanly', async () => {
  const adminStore = new InMemoryAdminStore();
  const r2Store = new InMemoryR2ArtifactStore();

  // Already uploaded to R2
  await r2Store.uploadPublishedSite('modern-site', '<!DOCTYPE html><html><body>Modern</body></html>');

  await adminStore.saveDeployment('user_charlie', {
    slug: 'modern-site',
    projectId: 'proj_modern',
    title: 'Modern Site',
    artifactPath: 'sites/modern-site/index.html',
    // No htmlBundle in Firestore
  });

  const report = await migrateDeploymentsToR2({
    adminStore,
    r2Store,
    apply: true,
  });

  assert.equal(report.totalFound, 1);
  assert.equal(report.alreadyMigratedCount, 1);
  assert.equal(report.migratedCount, 0);
  assert.equal(report.failedCount, 0);
});

test('4. R2 upload failure preserves Firestore data safely', async () => {
  const adminStore = new InMemoryAdminStore();

  // Create an R2 store that fails on upload
  const failingR2Store = new InMemoryR2ArtifactStore();
  failingR2Store.uploadPublishedSite = async () => {
    throw new Error('Simulated R2 network timeout');
  };

  await adminStore.saveDeployment('user_dave', {
    slug: 'dave-site',
    projectId: 'proj_dave',
    title: 'Dave Site',
    htmlBundle: '<!DOCTYPE html><html><body>Dave Content</body></html>',
  });

  const report = await migrateDeploymentsToR2({
    adminStore,
    r2Store: failingR2Store,
    apply: true,
  });

  assert.equal(report.failedCount, 1);
  assert.equal(report.migratedCount, 0);

  // Firestore HTML bundle was NOT deleted
  const doc = await adminStore.getDeployment('dave-site');
  assert.ok(doc?.htmlBundle.includes('Dave Content'));
});
