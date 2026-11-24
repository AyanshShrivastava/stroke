import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { initializeApp, getApps, type App } from 'firebase-admin/app';
import { getFirestore, FieldValue, Timestamp, type Firestore } from 'firebase-admin/firestore';
import admin from 'firebase-admin';
import type {
  ChatMessage,
  MistProject,
  ProjectFile,
  WebSearchOutcome,
  WebSearchSource,
} from '../types/mist';
import type { UserProfilePreferences, UserCredentialVaultDoc } from '../firebase/client';
import type { DeploymentSummary, StoredDeployment } from '../utils/deploymentStore';
import type { WebPushSubscription } from '../utils/notificationService';
import { SecurityValidationError } from '../utils/serverSecurity';
import { createSafeId } from '../utils/projectOps';

let cachedApp: App | null = null;
let cachedFirestore: Firestore | null = null;

export function initAdminFirestore(): Firestore {
  if (cachedFirestore) return cachedFirestore;

  const projectId =
    process.env.FIREBASE_PROJECT_ID ||
    readConfigProjectId() ||
    'mist-dev-project';
  const databaseId =
    process.env.FIREBASE_DATABASE_ID ||
    readConfigDatabaseId() ||
    '(default)';

  if (getApps().length === 0) {
    const rawServiceAccount = process.env.FIREBASE_SERVICE_ACCOUNT_JSON;
    if (rawServiceAccount) {
      let certObj: admin.ServiceAccount;
      try {
        certObj = JSON.parse(rawServiceAccount);
      } catch {
        const resolvedPath = path.resolve(rawServiceAccount);
        certObj = JSON.parse(fs.readFileSync(resolvedPath, 'utf8'));
      }
      cachedApp = initializeApp({
        credential: admin.credential.cert(certObj),
        projectId,
      });
    } else {
      cachedApp = initializeApp({ projectId });
    }
  } else {
    cachedApp = getApps()[0]!;
  }

  cachedFirestore =
    databaseId && databaseId !== '(default)'
      ? getFirestore(cachedApp, databaseId)
      : getFirestore(cachedApp);

  return cachedFirestore;
}

function readConfigProjectId(): string | undefined {
  try {
    const p = path.resolve(process.cwd(), 'firebase-applet-config.json');
    if (fs.existsSync(p)) {
      const data = JSON.parse(fs.readFileSync(p, 'utf8'));
      return data.projectId;
    }
  } catch {
    // ignore
  }
  return undefined;
}

function readConfigDatabaseId(): string | undefined {
  try {
    const p = path.resolve(process.cwd(), 'firebase-applet-config.json');
    if (fs.existsSync(p)) {
      const data = JSON.parse(fs.readFileSync(p, 'utf8'));
      return data.firestoreDatabaseId;
    }
  } catch {
    // ignore
  }
  return undefined;
}

export function resetAdminFirestoreForTesting(customDb?: Firestore): void {
  cachedFirestore = customDb || null;
}

export interface AdminDatabaseOperations {
  getUserPreferences(userId: string): Promise<UserProfilePreferences | null>;
  saveUserPreferences(
    userId: string,
    prefs: UserProfilePreferences,
    meta?: { email?: string; displayName?: string; photoURL?: string },
  ): Promise<void>;

  getUserVault(userId: string): Promise<UserCredentialVaultDoc | null>;
  saveUserVault(
    userId: string,
    email: string,
    vault: { ciphertext: string; aiKeyHint?: string; searchKeyHint?: string; renderKeyHint?: string },
  ): Promise<void>;
  deleteUserVault(userId: string): Promise<void>;

  listUserProjects(userId: string): Promise<MistProject[]>;
  getProject(userId: string, projectId: string): Promise<MistProject | null>;
  saveProject(userId: string, project: MistProject, options?: { isNew?: boolean }): Promise<void>;
  deleteProject(userId: string, projectId: string): Promise<void>;
  syncProjects(
    userId: string,
    projects: MistProject[],
  ): Promise<{
    synced: number;
    successfulProjectIds: string[];
    failedProjects: Array<{ id: string; error: string }>;
  }>;

  listDeployments(userId: string): Promise<DeploymentSummary[]>;
  getDeployment(slug: string): Promise<StoredDeployment | null>;
  saveDeployment(
    userId: string,
    params: {
      slug: string;
      projectId: string;
      title: string;
      r2Bucket?: string;
      artifactPath?: string;
      htmlBundle?: string;
      bytes?: number;
      etag?: string;
    },
  ): Promise<void>;
  deleteDeployment(userId: string, slug: string): Promise<boolean>;

  savePushSubscription(userId: string, subscription: WebPushSubscription): Promise<void>;
  deletePushSubscription(userId: string, endpoint: string): Promise<boolean>;
  listPushSubscriptions(userId?: string): Promise<WebPushSubscription[]>;
  deletePushSubscriptionsByEndpoints(endpoints: string[]): Promise<number>;
}

function hashEndpoint(endpoint: string): string {
  return crypto.createHash('sha256').update(endpoint.trim()).digest('hex');
}

function toIsoString(val: unknown): string {
  if (val && typeof val === 'object' && 'toDate' in val && typeof (val as Timestamp).toDate === 'function') {
    return (val as Timestamp).toDate().toISOString();
  }
  if (typeof val === 'string') return val;
  return new Date().toISOString();
}

function sanitizeSearchOutcome(outcome?: WebSearchOutcome): Record<string, unknown> | undefined {
  if (!outcome || typeof outcome !== 'object') return undefined;
  const cleanSources: WebSearchSource[] = Array.isArray(outcome.sources)
    ? outcome.sources.slice(0, 12).map((s, idx) => ({
        id: String(s.id || `S${idx + 1}`).slice(0, 16),
        title: String(s.title || 'Source').slice(0, 240),
        url: String(s.url || '').slice(0, 1024),
        snippet: String(s.snippet || '').slice(0, 1200),
        publishedDate: s.publishedDate ? String(s.publishedDate).slice(0, 64) : undefined,
        hostname: s.hostname ? String(s.hostname).slice(0, 128) : undefined,
      }))
    : [];

  return {
    status: outcome.status || 'skipped',
    queries: Array.isArray(outcome.queries)
      ? outcome.queries.slice(0, 6).map((q) => String(q).slice(0, 240))
      : [],
    sources: cleanSources,
    citedIds: Array.isArray(outcome.citedIds)
      ? outcome.citedIds.slice(0, 16).map((id) => String(id).slice(0, 16))
      : undefined,
    warning: outcome.warning ? String(outcome.warning).slice(0, 500) : undefined,
    error: outcome.error ? String(outcome.error).slice(0, 500) : undefined,
    searchedAt: outcome.searchedAt ? String(outcome.searchedAt).slice(0, 64) : undefined,
    providerName: outcome.providerName ? String(outcome.providerName).slice(0, 120) : undefined,
  };
}

export class FirestoreAdminStore implements AdminDatabaseOperations {
  private db: Firestore;

  constructor(customDb?: Firestore) {
    this.db = customDb || initAdminFirestore();
  }

  async getUserPreferences(userId: string): Promise<UserProfilePreferences | null> {
    const docRef = this.db.collection('users').doc(userId);
    const snap = await docRef.get();
    if (!snap.exists) return null;
    const d = snap.data() || {};
    return {
      preferredProvider: d.preferredProvider,
      preferredModel: d.preferredModel,
      theme: d.theme,
      defaultViewMode: d.defaultViewMode,
      defaultViewport: d.defaultViewport,
      enableAppAi: d.enableAppAi,
      appAiMode: d.appAiMode,
      webSearchMode: d.webSearchMode,
    };
  }

  async saveUserPreferences(
    userId: string,
    prefs: UserProfilePreferences,
    meta?: { email?: string; displayName?: string; photoURL?: string },
  ): Promise<void> {
    const docRef = this.db.collection('users').doc(userId);
    const snap = await docRef.get();
    const now = FieldValue.serverTimestamp();

    const cleanPrefs: Record<string, unknown> = {
      updatedAt: now,
    };
    if (prefs.preferredProvider !== undefined) cleanPrefs.preferredProvider = prefs.preferredProvider;
    if (prefs.preferredModel !== undefined) cleanPrefs.preferredModel = prefs.preferredModel.slice(0, 120);
    if (prefs.theme !== undefined) cleanPrefs.theme = prefs.theme;
    if (prefs.defaultViewMode !== undefined) cleanPrefs.defaultViewMode = prefs.defaultViewMode;
    if (prefs.defaultViewport !== undefined) cleanPrefs.defaultViewport = prefs.defaultViewport;
    if (typeof prefs.enableAppAi === 'boolean') cleanPrefs.enableAppAi = prefs.enableAppAi;
    if (prefs.appAiMode !== undefined) cleanPrefs.appAiMode = prefs.appAiMode;
    if (prefs.webSearchMode !== undefined) cleanPrefs.webSearchMode = prefs.webSearchMode;

    if (!snap.exists) {
      await docRef.set({
        uid: userId,
        email: meta?.email?.slice(0, 254) || '',
        displayName: meta?.displayName?.slice(0, 120) || 'Mist Builder',
        photoURL: meta?.photoURL?.slice(0, 512),
        createdAt: now,
        ...cleanPrefs,
      });
    } else {
      if (meta?.email) cleanPrefs.email = meta.email.slice(0, 254);
      if (meta?.displayName) cleanPrefs.displayName = meta.displayName.slice(0, 120);
      if (meta?.photoURL) cleanPrefs.photoURL = meta.photoURL.slice(0, 512);
      await docRef.update(cleanPrefs);
    }
  }

  async getUserVault(userId: string): Promise<UserCredentialVaultDoc | null> {
    const vaultRef = this.db.collection('users').doc(userId).collection('private').doc('credentials');
    const snap = await vaultRef.get();
    if (!snap.exists) return null;
    const d = snap.data() || {};
    if (typeof d.ciphertext !== 'string' || !d.ciphertext) return null;

    return {
      ownerId: String(d.ownerId || userId),
      boundEmail: String(d.boundEmail || ''),
      algorithm: 'AES-256-GCM',
      ciphertext: d.ciphertext,
      aiKeyHint: typeof d.aiKeyHint === 'string' ? d.aiKeyHint : undefined,
      searchKeyHint: typeof d.searchKeyHint === 'string' ? d.searchKeyHint : undefined,
      renderKeyHint: typeof d.renderKeyHint === 'string' ? d.renderKeyHint : undefined,
    };
  }

  async saveUserVault(
    userId: string,
    email: string,
    vault: { ciphertext: string; aiKeyHint?: string; searchKeyHint?: string; renderKeyHint?: string },
  ): Promise<void> {
    const vaultRef = this.db.collection('users').doc(userId).collection('private').doc('credentials');
    const now = FieldValue.serverTimestamp();
    const snap = await vaultRef.get();

    const data: Record<string, unknown> = {
      ownerId: userId,
      boundEmail: email.trim().slice(0, 254),
      algorithm: 'AES-256-GCM',
      ciphertext: vault.ciphertext.slice(0, 16384),
      aiKeyHint: (vault.aiKeyHint || '').slice(0, 32),
      searchKeyHint: (vault.searchKeyHint || '').slice(0, 32),
      renderKeyHint: (vault.renderKeyHint || '').slice(0, 32),
      updatedAt: now,
    };

    if (!snap.exists) {
      data.createdAt = now;
      await vaultRef.set(data);
    } else {
      await vaultRef.update(data);
    }
  }

  async deleteUserVault(userId: string): Promise<void> {
    const vaultRef = this.db.collection('users').doc(userId).collection('private').doc('credentials');
    await vaultRef.delete();
  }

  async listUserProjects(userId: string): Promise<MistProject[]> {
    const projectsSnap = await this.db.collection('projects').where('ownerId', '==', userId).get();
    const projects: MistProject[] = [];

    for (const pDoc of projectsSnap.docs) {
      const pData = pDoc.data();
      const projectId = pDoc.id;

      // Subcollection files
      const filesSnap = await this.db
        .collection('projects')
        .doc(projectId)
        .collection('files')
        .where('ownerId', '==', userId)
        .get();

      const files: ProjectFile[] = filesSnap.docs.map((fDoc) => {
        const fd = fDoc.data();
        return {
          id: fDoc.id,
          path: String(fd.path || 'src/App.tsx'),
          language: (fd.language || 'tsx') as ProjectFile['language'],
          content: String(fd.content || ''),
        };
      });

      // Subcollection messages
      const msgsSnap = await this.db
        .collection('projects')
        .doc(projectId)
        .collection('messages')
        .where('ownerId', '==', userId)
        .get();

      const chatHistory: ChatMessage[] = msgsSnap.docs
        .map((mDoc) => {
          const md = mDoc.data();
          return {
            seq: typeof md.seq === 'number' ? md.seq : 0,
            msg: {
              id: mDoc.id,
              role: (md.role === 'assistant' ? 'assistant' : 'user') as ChatMessage['role'],
              content: String(md.content || ''),
              timestamp: String(md.timestamp || toIsoString(pData.createdAt)),
              changedFiles: Array.isArray(md.changedFiles) ? md.changedFiles.map(String) : undefined,
              searchOutcome: md.searchOutcome as WebSearchOutcome | undefined,
            },
          };
        })
        .sort((a, b) => a.seq - b.seq)
        .map((entry) => entry.msg);

      projects.push({
        id: projectId,
        name: String(pData.name || 'Untitled Website'),
        description: String(pData.description || ''),
        prompt: String(pData.prompt || ''),
        templateId: pData.templateId ? String(pData.templateId) : undefined,
        appAiEnabled: typeof pData.appAiEnabled === 'boolean' ? pData.appAiEnabled : undefined,
        publishedSlug: pData.publishedSlug ? String(pData.publishedSlug) : undefined,
        isPublished: Boolean(pData.isPublished),
        createdAt: toIsoString(pData.createdAt),
        updatedAt: toIsoString(pData.updatedAt),
        files,
        chatHistory:
          chatHistory.length > 0
            ? chatHistory
            : [
                {
                  id: createSafeId('msg'),
                  role: 'user',
                  content: String(pData.prompt || ''),
                  timestamp: toIsoString(pData.createdAt),
                },
              ],
      });
    }

    return projects.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }

  async getProject(userId: string, projectId: string): Promise<MistProject | null> {
    const projectRef = this.db.collection('projects').doc(projectId);
    const snap = await projectRef.get();
    if (!snap.exists) return null;
    const data = snap.data() || {};
    if (data.ownerId !== userId) {
      throw new SecurityValidationError(403, 'Access denied: You do not own this project.');
    }

    const [filesSnap, msgsSnap] = await Promise.all([
      projectRef.collection('files').where('ownerId', '==', userId).get(),
      projectRef.collection('messages').where('ownerId', '==', userId).get(),
    ]);

    const files: ProjectFile[] = filesSnap.docs.map((fDoc) => {
      const fd = fDoc.data();
      return {
        id: fDoc.id,
        path: String(fd.path || 'src/App.tsx'),
        language: (fd.language || 'tsx') as ProjectFile['language'],
        content: String(fd.content || ''),
      };
    });

    const chatHistory: ChatMessage[] = msgsSnap.docs
      .map((mDoc) => {
        const md = mDoc.data();
        return {
          seq: typeof md.seq === 'number' ? md.seq : 0,
          msg: {
            id: mDoc.id,
            role: (md.role === 'assistant' ? 'assistant' : 'user') as ChatMessage['role'],
            content: String(md.content || ''),
            timestamp: String(md.timestamp || toIsoString(data.createdAt)),
            changedFiles: Array.isArray(md.changedFiles) ? md.changedFiles.map(String) : undefined,
            searchOutcome: md.searchOutcome as WebSearchOutcome | undefined,
          },
        };
      })
      .sort((a, b) => a.seq - b.seq)
      .map((entry) => entry.msg);

    return {
      id: projectId,
      name: String(data.name || 'Untitled Website'),
      description: String(data.description || ''),
      prompt: String(data.prompt || ''),
      templateId: data.templateId ? String(data.templateId) : undefined,
      appAiEnabled: typeof data.appAiEnabled === 'boolean' ? data.appAiEnabled : undefined,
      publishedSlug: data.publishedSlug ? String(data.publishedSlug) : undefined,
      isPublished: Boolean(data.isPublished),
      createdAt: toIsoString(data.createdAt),
      updatedAt: toIsoString(data.updatedAt),
      files,
      chatHistory,
    };
  }

  async saveProject(
    userId: string,
    project: MistProject,
    options?: { isNew?: boolean },
  ): Promise<void> {
    const projectRef = this.db.collection('projects').doc(project.id);
    const snap = await projectRef.get();
    const now = FieldValue.serverTimestamp();

    if (snap.exists && snap.data()?.ownerId !== userId) {
      throw new SecurityValidationError(403, 'Access denied: You cannot overwrite another user project.');
    }
    if (project.ownerId && project.ownerId !== userId) {
      throw new SecurityValidationError(403, 'Access denied: Project ownership mismatch.');
    }

    const safeName = (project.name || 'Untitled Website').slice(0, 120);
    const safeDesc = (project.description || '').slice(0, 500);
    const safePrompt = (project.prompt || '').slice(0, 4000);

    const projectPayload: Record<string, unknown> = {
      id: project.id,
      ownerId: userId,
      name: safeName,
      description: safeDesc,
      prompt: safePrompt,
      appAiEnabled: Boolean(project.appAiEnabled),
      isPublished: Boolean(project.isPublished),
      updatedAt: now,
    };
    if (project.templateId) projectPayload.templateId = project.templateId.slice(0, 64);
    if (project.publishedSlug) projectPayload.publishedSlug = project.publishedSlug.slice(0, 80);

    const batch = this.db.batch();

    if (!snap.exists) {
      let createdTimestamp: any = now;
      if (project.createdAt) {
        const parsed = new Date(project.createdAt);
        if (!isNaN(parsed.getTime())) {
          createdTimestamp = Timestamp.fromDate(parsed);
        }
      }
      projectPayload.createdAt = createdTimestamp;
      batch.set(projectRef, projectPayload);
    } else {
      // Update mask: update only modified project metadata, never overwrite createdAt or ownerId!
      batch.update(projectRef, projectPayload);
    }

    // Existing files & messages clean diff
    const [existingFiles, existingMsgs] = snap.exists
      ? await Promise.all([
          projectRef.collection('files').where('ownerId', '==', userId).get(),
          projectRef.collection('messages').where('ownerId', '==', userId).get(),
        ])
      : [{ docs: [] }, { docs: [] }];

    const currentFileIds = new Set(project.files.map((f) => f.id));
    for (const fDoc of existingFiles.docs) {
      if (!currentFileIds.has(fDoc.id)) {
        batch.delete(fDoc.ref);
      }
    }

    for (const file of project.files) {
      const fileRef = projectRef.collection('files').doc(file.id);
      batch.set(fileRef, {
        id: file.id,
        projectId: project.id,
        ownerId: userId,
        path: file.path.slice(0, 256),
        language: file.language,
        content: file.content.slice(0, 200000),
        updatedAt: now,
      });
    }

    const currentMsgIds = new Set((project.chatHistory || []).map((m) => m.id));
    for (const mDoc of existingMsgs.docs) {
      if (!currentMsgIds.has(mDoc.id)) {
        batch.delete(mDoc.ref);
      }
    }

    (project.chatHistory || []).slice(-100).forEach((msg, idx) => {
      const msgRef = projectRef.collection('messages').doc(msg.id);
      const msgData: Record<string, unknown> = {
        id: msg.id,
        projectId: project.id,
        ownerId: userId,
        role: msg.role === 'assistant' ? 'assistant' : 'user',
        content: String(msg.content || '').slice(0, 24000),
        seq: idx,
        timestamp: msg.timestamp || new Date().toISOString(),
        updatedAt: now,
      };
      if (Array.isArray(msg.changedFiles)) {
        msgData.changedFiles = msg.changedFiles.map((f) => String(f).slice(0, 256)).slice(0, 120);
      }
      const outcome = sanitizeSearchOutcome(msg.searchOutcome);
      if (outcome) {
        msgData.searchOutcome = outcome;
      }
      batch.set(msgRef, msgData);
    });

    await batch.commit();
  }

  async deleteProject(userId: string, projectId: string): Promise<void> {
    const projectRef = this.db.collection('projects').doc(projectId);
    const snap = await projectRef.get();
    if (!snap.exists) return;
    if (snap.data()?.ownerId !== userId) {
      throw new SecurityValidationError(403, 'Access denied: You do not own this project.');
    }

    const [filesSnap, msgsSnap] = await Promise.all([
      projectRef.collection('files').where('ownerId', '==', userId).get(),
      projectRef.collection('messages').where('ownerId', '==', userId).get(),
    ]);

    const batch = this.db.batch();
    filesSnap.docs.forEach((d) => batch.delete(d.ref));
    msgsSnap.docs.forEach((d) => batch.delete(d.ref));
    batch.delete(projectRef);

    await batch.commit();
  }

  async syncProjects(
    userId: string,
    projects: MistProject[],
  ): Promise<{
    synced: number;
    successfulProjectIds: string[];
    failedProjects: Array<{ id: string; error: string }>;
  }> {
    const successfulProjectIds: string[] = [];
    const failedProjects: Array<{ id: string; error: string }> = [];

    for (const project of projects) {
      try {
        await this.saveProject(userId, project);
        successfulProjectIds.push(project.id);
      } catch (err) {
        console.warn(`[FirestoreAdmin] Sync failure for project ${project.id}:`, err);
        failedProjects.push({
          id: project.id,
          error: err instanceof Error ? err.message : 'Save failed',
        });
      }
    }
    return {
      synced: successfulProjectIds.length,
      successfulProjectIds,
      failedProjects,
    };
  }

  async listDeployments(userId: string): Promise<DeploymentSummary[]> {
    const snap = await this.db.collection('deployments').where('ownerId', '==', userId).get();
    return snap.docs.map((doc) => {
      const d = doc.data();
      return {
        slug: d.slug || doc.id,
        projectId: d.projectId || doc.id,
        title: d.title || 'Untitled Site',
        url: `https://${d.slug || doc.id}.mist.me`,
        updatedAt: toIsoString(d.updatedAt || d.createdAt),
      };
    });
  }

  async getDeployment(slug: string): Promise<StoredDeployment | null> {
    const docRef = this.db.collection('deployments').doc(slug);
    const snap = await docRef.get();
    if (!snap.exists) return null;
    const d = snap.data() || {};
    return {
      slug: d.slug || slug,
      ownerUid: d.ownerId,
      projectId: d.projectId || slug,
      title: d.title || 'Published Site',
      htmlBundle: d.htmlBundle || '',
      r2Bucket: d.r2Bucket,
      artifactPath: d.artifactPath,
      createdAt: toIsoString(d.createdAt),
      updatedAt: toIsoString(d.updatedAt || d.createdAt),
    };
  }

  async saveDeployment(
    userId: string,
    params: {
      slug: string;
      projectId: string;
      title: string;
      r2Bucket?: string;
      artifactPath?: string;
      htmlBundle?: string;
      bytes?: number;
      etag?: string;
    },
  ): Promise<void> {
    const docRef = this.db.collection('deployments').doc(params.slug);
    const snap = await docRef.get();
    const now = FieldValue.serverTimestamp();

    if (snap.exists && snap.data()?.ownerId !== userId) {
      throw new SecurityValidationError(403, 'Deployment slug belongs to another user.');
    }

    const payload: Record<string, unknown> = {
      slug: params.slug,
      ownerId: userId,
      projectId: params.projectId,
      title: params.title.slice(0, 120),
      r2Bucket: params.r2Bucket || 'mist-published-sites',
      artifactPath: params.artifactPath || `sites/${params.slug}/index.html`,
      updatedAt: now,
    };
    if (params.htmlBundle) {
      // Legacy fallback storage if provided
      payload.htmlBundle = params.htmlBundle.slice(0, 900000);
    } else if (snap.exists && snap.data()?.htmlBundle) {
      // Clean up legacy full HTML bundle from Firestore once stored in R2
      payload.htmlBundle = FieldValue.delete();
    }
    if (typeof params.bytes === 'number') {
      payload.bytes = params.bytes;
    }
    if (params.etag) {
      payload.etag = params.etag;
    }

    if (!snap.exists) {
      payload.createdAt = now;
      await docRef.set(payload);
    } else {
      await docRef.update(payload);
    }
  }

  async deleteDeployment(userId: string, slug: string): Promise<boolean> {
    const docRef = this.db.collection('deployments').doc(slug);
    const snap = await docRef.get();
    if (!snap.exists) return false;
    if (snap.data()?.ownerId !== userId) {
      throw new SecurityValidationError(403, 'Deployment slug belongs to another user.');
    }
    await docRef.delete();
    return true;
  }

  async savePushSubscription(userId: string, subscription: WebPushSubscription): Promise<void> {
    const docId = hashEndpoint(subscription.endpoint);
    const ref = this.db.collection('push_subscriptions').doc(docId);
    const snap = await ref.get();
    if (snap.exists && snap.data()?.userId !== userId) {
      throw new SecurityValidationError(403, 'Push subscription is registered to another account.');
    }
    const now = FieldValue.serverTimestamp();
    await ref.set(
      {
        id: docId,
        endpoint: subscription.endpoint,
        userId,
        keys: {
          p256dh: subscription.keys.p256dh,
          auth: subscription.keys.auth,
        },
        expirationTime: subscription.expirationTime ?? null,
        updatedAt: now,
        ...(snap.exists ? {} : { createdAt: now }),
      },
      { merge: true },
    );
  }

  async deletePushSubscription(userId: string, endpoint: string): Promise<boolean> {
    const docId = hashEndpoint(endpoint);
    const ref = this.db.collection('push_subscriptions').doc(docId);
    const snap = await ref.get();
    if (!snap.exists) return false;
    if (snap.data()?.userId !== userId) {
      throw new SecurityValidationError(403, 'Access denied: Subscription belongs to another account.');
    }
    await ref.delete();
    return true;
  }

  async listPushSubscriptions(userId?: string): Promise<WebPushSubscription[]> {
    let query: FirebaseFirestore.Query = this.db.collection('push_subscriptions');
    if (userId) {
      query = query.where('userId', '==', userId);
    }
    const snap = await query.get();
    return snap.docs.map((doc) => {
      const d = doc.data();
      return {
        endpoint: d.endpoint,
        userId: d.userId,
        expirationTime: typeof d.expirationTime === 'number' ? d.expirationTime : null,
        keys: {
          p256dh: d.keys?.p256dh || '',
          auth: d.keys?.auth || '',
        },
        createdAt: toIsoString(d.createdAt),
      };
    });
  }

  async deletePushSubscriptionsByEndpoints(endpoints: string[]): Promise<number> {
    if (!endpoints.length) return 0;
    let deleted = 0;
    const batch = this.db.batch();
    for (const ep of endpoints) {
      const docId = hashEndpoint(ep);
      batch.delete(this.db.collection('push_subscriptions').doc(docId));
      deleted++;
    }
    await batch.commit();
    return deleted;
  }
}

/**
 * In-memory database store for testing and offline local development
 */
export class InMemoryAdminStore implements AdminDatabaseOperations {
  public users = new Map<string, Record<string, unknown>>();
  public vaults = new Map<string, UserCredentialVaultDoc>();
  public projects = new Map<string, MistProject & { ownerId: string }>();
  public deployments = new Map<string, StoredDeployment & { r2Bucket?: string; artifactPath?: string }>();

  async getUserPreferences(userId: string): Promise<UserProfilePreferences | null> {
    const u = this.users.get(userId);
    if (!u) return null;
    return {
      preferredProvider: u.preferredProvider as any,
      preferredModel: u.preferredModel as string,
      theme: u.theme as any,
      defaultViewMode: u.defaultViewMode as any,
      defaultViewport: u.defaultViewport as any,
      enableAppAi: u.enableAppAi as boolean,
      appAiMode: u.appAiMode as any,
      webSearchMode: u.webSearchMode as any,
    };
  }

  async saveUserPreferences(
    userId: string,
    prefs: UserProfilePreferences,
    meta?: { email?: string; displayName?: string; photoURL?: string },
  ): Promise<void> {
    const existing = this.users.get(userId) || { uid: userId, createdAt: new Date().toISOString() };
    this.users.set(userId, {
      ...existing,
      ...meta,
      ...prefs,
      updatedAt: new Date().toISOString(),
    });
  }

  async getUserVault(userId: string): Promise<UserCredentialVaultDoc | null> {
    return this.vaults.get(userId) || null;
  }

  async saveUserVault(
    userId: string,
    email: string,
    vault: { ciphertext: string; aiKeyHint?: string; searchKeyHint?: string; renderKeyHint?: string },
  ): Promise<void> {
    this.vaults.set(userId, {
      ownerId: userId,
      boundEmail: email,
      algorithm: 'AES-256-GCM',
      ciphertext: vault.ciphertext,
      aiKeyHint: vault.aiKeyHint,
      searchKeyHint: vault.searchKeyHint,
      renderKeyHint: vault.renderKeyHint,
    });
  }

  async deleteUserVault(userId: string): Promise<void> {
    this.vaults.delete(userId);
  }

  async listUserProjects(userId: string): Promise<MistProject[]> {
    const list: MistProject[] = [];
    for (const p of this.projects.values()) {
      if (p.ownerId === userId) {
        list.push({ ...p });
      }
    }
    return list.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }

  async getProject(userId: string, projectId: string): Promise<MistProject | null> {
    const p = this.projects.get(projectId);
    if (!p) return null;
    if (p.ownerId !== userId) {
      throw new SecurityValidationError(403, 'Access denied: You do not own this project.');
    }
    return { ...p };
  }

  async saveProject(userId: string, project: MistProject): Promise<void> {
    const existing = this.projects.get(project.id);
    if (existing && existing.ownerId !== userId) {
      throw new SecurityValidationError(403, 'Access denied: You cannot overwrite another user project.');
    }
    if (project.ownerId && project.ownerId !== userId) {
      throw new SecurityValidationError(403, 'Access denied: Project ownership mismatch.');
    }
    const now = new Date().toISOString();
    let createdAt = existing?.createdAt;
    if (!createdAt) {
      if (project.createdAt && !isNaN(new Date(project.createdAt).getTime())) {
        createdAt = new Date(project.createdAt).toISOString();
      } else {
        createdAt = now;
      }
    }
    this.projects.set(project.id, {
      ...project,
      ownerId: userId,
      createdAt,
      updatedAt: now,
    });
  }

  async deleteProject(userId: string, projectId: string): Promise<void> {
    const p = this.projects.get(projectId);
    if (!p) return;
    if (p.ownerId !== userId) {
      throw new SecurityValidationError(403, 'Access denied: You do not own this project.');
    }
    this.projects.delete(projectId);
  }

  async syncProjects(
    userId: string,
    projects: MistProject[],
  ): Promise<{
    synced: number;
    successfulProjectIds: string[];
    failedProjects: Array<{ id: string; error: string }>;
  }> {
    const successfulProjectIds: string[] = [];
    const failedProjects: Array<{ id: string; error: string }> = [];

    for (const p of projects) {
      try {
        await this.saveProject(userId, p);
        successfulProjectIds.push(p.id);
      } catch (err) {
        failedProjects.push({
          id: p.id,
          error: err instanceof Error ? err.message : 'Save failed',
        });
      }
    }
    return {
      synced: successfulProjectIds.length,
      successfulProjectIds,
      failedProjects,
    };
  }

  async listDeployments(userId: string): Promise<DeploymentSummary[]> {
    const list: DeploymentSummary[] = [];
    for (const d of this.deployments.values()) {
      if (d.ownerUid === userId) {
        list.push({
          slug: d.slug,
          projectId: d.projectId,
          title: d.title,
          url: `https://${d.slug}.mist.me`,
          updatedAt: d.updatedAt,
        });
      }
    }
    return list;
  }

  async getDeployment(slug: string): Promise<StoredDeployment | null> {
    return this.deployments.get(slug) || null;
  }

  async saveDeployment(
    userId: string,
    params: {
      slug: string;
      projectId: string;
      title: string;
      r2Bucket?: string;
      artifactPath?: string;
      htmlBundle?: string;
      bytes?: number;
      etag?: string;
    },
  ): Promise<void> {
    const existing = this.deployments.get(params.slug);
    if (existing && existing.ownerUid !== userId) {
      throw new SecurityValidationError(403, 'Deployment slug belongs to another user.');
    }
    const now = new Date().toISOString();
    this.deployments.set(params.slug, {
      slug: params.slug,
      ownerUid: userId,
      projectId: params.projectId,
      title: params.title,
      htmlBundle: params.htmlBundle || '',
      r2Bucket: params.r2Bucket || 'mist-published-sites',
      artifactPath: params.artifactPath || `sites/${params.slug}/index.html`,
      createdAt: existing?.createdAt || now,
      updatedAt: now,
    });
  }

  async deleteDeployment(userId: string, slug: string): Promise<boolean> {
    const d = this.deployments.get(slug);
    if (!d) return false;
    if (d.ownerUid !== userId) {
      throw new SecurityValidationError(403, 'Deployment slug belongs to another user.');
    }
    this.deployments.delete(slug);
    return true;
  }

  public pushSubscriptions = new Map<string, WebPushSubscription>();

  async savePushSubscription(userId: string, subscription: WebPushSubscription): Promise<void> {
    const existing = this.pushSubscriptions.get(subscription.endpoint);
    if (existing && existing.userId && existing.userId !== userId) {
      throw new SecurityValidationError(403, 'Push subscription is registered to another account.');
    }
    this.pushSubscriptions.set(subscription.endpoint, {
      ...subscription,
      userId,
      createdAt: existing?.createdAt || new Date().toISOString(),
    });
  }

  async deletePushSubscription(userId: string, endpoint: string): Promise<boolean> {
    const existing = this.pushSubscriptions.get(endpoint);
    if (!existing) return false;
    if (existing.userId && existing.userId !== userId) {
      throw new SecurityValidationError(403, 'Access denied: Subscription belongs to another account.');
    }
    return this.pushSubscriptions.delete(endpoint);
  }

  async listPushSubscriptions(userId?: string): Promise<WebPushSubscription[]> {
    const all = Array.from(this.pushSubscriptions.values());
    if (!userId) return all;
    return all.filter((s) => s.userId === userId);
  }

  async deletePushSubscriptionsByEndpoints(endpoints: string[]): Promise<number> {
    let count = 0;
    for (const ep of endpoints) {
      if (this.pushSubscriptions.delete(ep)) count++;
    }
    return count;
  }
}
