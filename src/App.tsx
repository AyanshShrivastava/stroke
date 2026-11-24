import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  useAuth as useClerkAuth,
  useClerk,
  useUser,
  AuthenticateWithRedirectCallback,
} from '@clerk/react';
import JSZip from 'jszip';
import type {
  AiProviderConfig,
  AiStreamProgress,
  DeploymentRecord,
  MistProject,
  MistUser,
  ProjectFile,
  SelectedVisualElement,
  StudioSettings,
  WebSearchConfig,
  WebSearchOutcome,
  WebSearchSource,
} from './types/mist';
import type { ModelHealthIncident } from './utils/aiErrors';
import {
  DEFAULT_BYOK_CONFIG,
  normalizeProviderConfigToStudio,
  shouldEnableAppAi,
} from './data/models';
import {
  DEFAULT_WEB_SEARCH_CONFIG,
  normalizeWebSearchConfig,
  webSearchConfigReady,
} from './data/webSearch';
import {
  applyVisualPatchToFiles,
  buildExportManifest,
  createSafeId,
  duplicateProjectData,
  inferLanguageFromPath,
  mergeProjectFiles,
  normalizeProjectFilePath,
  sanitizeSlug,
  suggestShortSlug,
} from './utils/projectOps';
import { canUseDirectClient, executeDirectGenerate } from './utils/directClientAi';
import { notifyAnswerDone } from './utils/pushNotifications';
import {
  fetchUserEncryptedVault,
  fetchUserProfilePreferences,
  saveUserEncryptedVault,
  syncUserProfile,
} from './firebase/client';
import {
  clearKnownCloudProjects,
  deleteProjectFromFirestore,
  listUserProjectsFromFirestore,
  saveProjectToFirestore,
  syncLocalProjectsToFirestore,
} from './firebase/store';
import { mistApi, setApiTokenProvider } from './utils/apiClient';
import HomeView from './components/HomeView';
import WorkspaceView from './components/WorkspaceView';
import SettingsView from './components/SettingsView';
import VoiceChatModal from './components/VoiceChatModal';
import {
  AccountModal,
  DeploymentsModal,
  DeployModal,
  ProvidersModal,
} from './components/Modals';
import MistCodeModal from './components/MistCodeModal';
import { mistClerkAppearance } from './utils/clerkTheme';
import {
  clearPendingDirtyQueue,
  dequeueProjectFromBatchedSync,
  flushBatchedSyncNow,
  flushBatchedSyncOnAppExit,
  getProjectsStorageKey,
  initLocalCacheQueue,
  queueProjectForBatchedSync,
  setBatchedSyncUserProvider,
} from './firebase/batchedProjectSync';

export { getProjectsStorageKey };

const LEGACY_STORAGE_PROVIDER_KEY = 'mist_provider_v1';
const LEGACY_STORAGE_SEARCH_KEY = 'mist_search_v1';
const STORAGE_SETTINGS_KEY = 'mist_settings_v1';
const STORAGE_THEME_KEY = 'mist_theme_v1';

const DEFAULT_STUDIO_SETTINGS: StudioSettings = {
  theme: 'dark',
  defaultViewMode: 'preview',
  defaultViewport: 'desktop',
  enableAppAi: false,
  appAiMode: 'on_request',
  webSearchMode: 'auto',
  notifyOnAnswerDone: true,
};

function loadLocalProjects(userId?: string | null): MistProject[] {
  try {
    const key = getProjectsStorageKey(userId);
    let raw = localStorage.getItem(key);
    // Only fall back to legacy shared keys if userId is explicitly anonymous (null/undefined)
    if (!raw && !userId) {
      raw = localStorage.getItem('mist_projects_v1') || localStorage.getItem('mist_projects');
      if (raw) {
        try {
          localStorage.setItem('mist_projects_anonymous', raw);
          localStorage.removeItem('mist_projects_v1');
          localStorage.removeItem('mist_projects');
        } catch {
          // ignore
        }
      }
    }
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as MistProject[]) : [];
  } catch {
    return [];
  }
}

function scrubLegacyCredentialStorage(): void {
  try {
    localStorage.removeItem(LEGACY_STORAGE_PROVIDER_KEY);
    localStorage.removeItem(LEGACY_STORAGE_SEARCH_KEY);
  } catch {
    // ignore storage access issues
  }
}

function loadStudioSettings(): StudioSettings {
  try {
    const raw = localStorage.getItem(STORAGE_SETTINGS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<StudioSettings>;
      const resolvedMode =
        parsed.appAiMode === 'on_request' ||
        parsed.appAiMode === 'always' ||
        parsed.appAiMode === 'off'
          ? parsed.appAiMode
          : parsed.enableAppAi === false
            ? 'off'
            : 'on_request';
      const resolvedSearchMode =
        parsed.webSearchMode === 'auto' ||
        parsed.webSearchMode === 'on' ||
        parsed.webSearchMode === 'off'
          ? parsed.webSearchMode
          : 'auto';
      return {
        ...DEFAULT_STUDIO_SETTINGS,
        ...parsed,
        appAiMode: resolvedMode,
        enableAppAi: resolvedMode === 'always',
        webSearchMode: resolvedSearchMode,
      };
    }
    const legacyTheme = localStorage.getItem(STORAGE_THEME_KEY);
    if (legacyTheme === 'light' || legacyTheme === 'dark') {
      return { ...DEFAULT_STUDIO_SETTINGS, theme: legacyTheme };
    }
  } catch {
    // ignore
  }
  return DEFAULT_STUDIO_SETTINGS;
}

interface SseStreamPayload {
  type:
    | 'phase'
    | 'search_start'
    | 'search_results'
    | 'search_error'
    | 'file_start'
    | 'file_done'
    | 'progress'
    | 'complete'
    | 'error';
  phase?: string;
  path?: string;
  activeFile?: string;
  completedFiles?: string[];
  chars?: number;
  queries?: string[];
  sources?: WebSearchSource[];
  result?: Record<string, unknown>;
  error?: string;
  incident?: ModelHealthIncident;
}

async function consumeAiSseStream(
  resp: Response,
  onEvent: (ev: SseStreamPayload) => void,
): Promise<Record<string, unknown>> {
  if (!resp.body) {
    throw new Error('Streaming response body unavailable.');
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let completedResult: Record<string, unknown> | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let nlIndex: number;
    while ((nlIndex = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, nlIndex).trim();
      buffer = buffer.slice(nlIndex + 1);
      if (!line.startsWith('data:')) continue;
      const rawJson = line.slice(5).trim();
      if (!rawJson) continue;
      const ev = JSON.parse(rawJson) as SseStreamPayload;
      onEvent(ev);
      if (ev.type === 'error') {
        const err = new Error(ev.incident?.message || ev.error || 'AI request failed.') as Error & {
          incident?: ModelHealthIncident;
        };
        err.incident = ev.incident;
        throw err;
      }
      if (ev.type === 'complete' && ev.result) {
        completedResult = ev.result;
      }
    }
  }

  if (!completedResult) {
    throw new Error('AI stream ended before returning generated files.');
  }
  return completedResult;
}

export default function App() {
  const clerk = useClerk();
  const clerkAuth = useClerkAuth();
  const { user: clerkUser, isLoaded: clerkUserLoaded, isSignedIn: clerkSignedIn } = useUser();

  // If returning from Google/GitHub OAuth redirect
  if (typeof window !== 'undefined' && window.location.pathname === '/sso-callback') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#090b10] text-white">
        <AuthenticateWithRedirectCallback
          signInForceRedirectUrl="/"
          signUpForceRedirectUrl="/"
        />
      </div>
    );
  }

  const [user, setUser] = useState<MistUser | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authPromptReason, setAuthPromptReason] = useState<string | null>(null);
  const pendingGeneratePromptRef = useRef<string | null>(null);

  const [projects, setProjects] = useState<MistProject[]>(() => loadLocalProjects(clerkUser?.id || null));
  const projectsRef = useRef(projects);
  projectsRef.current = projects;
  const activeAccountUidRef = useRef<string | null>(clerkUser?.id || null);

  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [activePage, setActivePage] = useState<'home' | 'settings'>('home');
  const [deployments, setDeployments] = useState<DeploymentRecord[]>([]);
  const [providerConfig, setProviderConfig] = useState<AiProviderConfig>(() => ({
    ...DEFAULT_BYOK_CONFIG,
  }));
  const providerConfigRef = useRef(providerConfig);
  providerConfigRef.current = providerConfig;

  const [webSearchConfig, setWebSearchConfig] = useState<WebSearchConfig>(() => ({
    ...DEFAULT_WEB_SEARCH_CONFIG,
  }));
  const webSearchConfigRef = useRef(webSearchConfig);
  webSearchConfigRef.current = webSearchConfig;

  const [studioSettings, setStudioSettings] = useState<StudioSettings>(() => loadStudioSettings());
  const studioSettingsRef = useRef(studioSettings);
  studioSettingsRef.current = studioSettings;

  const [modelIncident, setModelIncident] = useState<ModelHealthIncident | null>(null);

  // Live preview bundling state
  const [bundledHtml, setBundledHtml] = useState<string>('');
  const [bundleError, setBundleError] = useState<string | null>(null);
  const [isBundling, setIsBundling] = useState(false);

  // AI generation & refinement streaming state
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [isRefining, setIsRefining] = useState(false);
  const [refineError, setRefineError] = useState<string | null>(null);
  const [aiStreamProgress, setAiStreamProgress] = useState<AiStreamProgress | null>(null);

  // Deploy / Publish Export state
  const [isDeploying, setIsDeploying] = useState(false);
  const [deployError, setDeployError] = useState<string | null>(null);
  const [downloadedFileName, setDownloadedFileName] = useState<string | null>(null);
  const [deployProjectId, setDeployProjectId] = useState<string | null>(null);

  const [providersOpen, setProvidersOpen] = useState(false);
  const [deployOpen, setDeployOpen] = useState(false);
  const [deploymentsListOpen, setDeploymentsListOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [voiceChatOpen, setVoiceChatOpen] = useState(false);
  const [mistCodeOpen, setMistCodeOpen] = useState(false);

  const activeProject = projects.find((p) => p.id === activeProjectId) || null;
  const deployProject =
    (deployProjectId ? projects.find((p) => p.id === deployProjectId) : null) || activeProject;
  const darkMode = studioSettings.theme === 'dark';
  const bundleTimerRef = useRef<number | null>(null);
  const cloudSaveTimerRef = useRef<number | null>(null);
  const generateAbortRef = useRef<AbortController | null>(null);
  const refineAbortRef = useRef<AbortController | null>(null);
  const ignorePopRef = useRef(false);

  // Never store API keys in browser localStorage: purge any legacy plaintext keys on startup
  useEffect(() => {
    scrubLegacyCredentialStorage();
  }, []);

  // Browser Back / Forward navigation helper between Home, Workspace, and Settings
  const navigateToHome = useCallback(() => {
    setActivePage('home');
    setActiveProjectId(null);
    setDownloadedFileName(null);
    if (typeof window !== 'undefined' && window.history.state?.mistView) {
      window.history.pushState({ mistView: 'home' }, '');
    }
  }, []);

  const navigateToProject = useCallback((projectId: string) => {
    setActivePage('home');
    setActiveProjectId(projectId);
    setDownloadedFileName(null);
    if (typeof window !== 'undefined') {
      window.history.pushState({ mistView: 'project', projectId }, '');
    }
  }, []);

  const navigateToSettings = useCallback(() => {
    setActivePage('settings');
    if (typeof window !== 'undefined') {
      window.history.pushState({ mistView: 'settings', projectId: activeProjectId }, '');
    }
  }, [activeProjectId]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!window.history.state?.mistView) {
      window.history.replaceState({ mistView: 'home' }, '');
    }
    const handlePopState = () => {
      ignorePopRef.current = true;
      const st = window.history.state as { mistView?: string; projectId?: string | null } | null;
      if (st?.mistView === 'settings') {
        setActivePage('settings');
      } else if (st?.mistView === 'project' && st.projectId) {
        setActivePage('home');
        setActiveProjectId(st.projectId);
      } else {
        setActivePage('home');
        setActiveProjectId(null);
        setDownloadedFileName(null);
      }
      queueMicrotask(() => {
        ignorePopRef.current = false;
      });
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  // Encrypt & persist BYOK AI + Search credentials to Firestore bound to the verified Clerk account
  const syncCredentialsToAccountVault = useCallback(
    async (currentUser: MistUser, nextAi: AiProviderConfig, nextSearch: WebSearchConfig) => {
      try {
        const idToken = await currentUser.getIdToken();
        const resp = await fetch('/api/user/vault/seal', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${idToken}`,
          },
          body: JSON.stringify({ aiConfig: nextAi, searchConfig: nextSearch }),
        });
        if (!resp.ok) return;
        const sealed = (await resp.json()) as {
          encryptedPayload?: string;
          aiKeyHint?: string;
          searchKeyHint?: string;
        };
        if (sealed.encryptedPayload) {
          await saveUserEncryptedVault(currentUser, {
            ciphertext: sealed.encryptedPayload,
            aiKeyHint: sealed.aiKeyHint,
            searchKeyHint: sealed.searchKeyHint,
          });
        }
      } catch {
        // Non-blocking account vault sync
      }
    },
    [],
  );

  // Sync dark mode class on <html> + persist studioSettings
  useEffect(() => {
    const root = document.documentElement;
    if (darkMode) {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    try {
      localStorage.setItem(STORAGE_THEME_KEY, studioSettings.theme);
      localStorage.setItem(STORAGE_SETTINGS_KEY, JSON.stringify(studioSettings));
    } catch {
      // ignore
    }
  }, [darkMode, studioSettings]);

  // Persist local projects cache scoped to active account
  useEffect(() => {
    try {
      const key = getProjectsStorageKey(activeAccountUidRef.current);
      localStorage.setItem(key, JSON.stringify(projects));
    } catch {
      // ignore quota errors
    }
  }, [projects]);

  // Local-First Batched Sync: NO 10-second interval!
  // Syncs strictly when user closes or exits the app (tab close, reload, or backgrounding)
  useEffect(() => {
    initLocalCacheQueue(user?.uid);

    const handleFlushOnExit = () => {
      void flushBatchedSyncOnAppExit(user).catch(() => {});
    };

    window.addEventListener('beforeunload', handleFlushOnExit);
    window.addEventListener('pagehide', handleFlushOnExit);
    const handleVisibility = () => {
      if (document.visibilityState === 'hidden') {
        handleFlushOnExit();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      window.removeEventListener('beforeunload', handleFlushOnExit);
      window.removeEventListener('pagehide', handleFlushOnExit);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [user]);

  // Fetch deployments (authenticated per-user) & AI status
  const refreshDeployments = useCallback(async (currentUser: MistUser | null) => {
    if (!currentUser) {
      setDeployments([]);
      return;
    }
    try {
      const idToken = await currentUser.getIdToken();
      const resp = await fetch('/api/deployments', {
        headers: {
          Authorization: `Bearer ${idToken}`,
        },
      });
      if (resp.ok) {
        const data = (await resp.json()) as { deployments?: DeploymentRecord[] };
        if (Array.isArray(data.deployments)) {
          setDeployments(data.deployments);
        }
      } else {
        setDeployments([]);
      }
    } catch {
      // ignore offline
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const resp = await fetch('/api/ai/status');
        if (resp.ok) {
          const data = (await resp.json()) as { incidents?: ModelHealthIncident[] };
          if (Array.isArray(data.incidents) && data.incidents.length > 0) {
            setModelIncident(data.incidents[0]);
          }
        }
      } catch {
        // ignore
      }
    })();
  }, []);

  // Bundle active project for live preview
  const runBundle = useCallback(async (project: MistProject) => {
    setIsBundling(true);
    const hasAppAi = Boolean(
      project.appAiEnabled ||
        project.files.some((f) => /\/api\/app-ai|window\.mistAI/.test(f.content)),
    );
    try {
      const resp = await fetch('/api/bundle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: project.files,
          title: project.name,
          includeInspector: true,
          enableAppAi: hasAppAi,
        }),
      });
      const data = (await resp.json()) as { html?: string; bundleError?: string; error?: string };
      if (!resp.ok) {
        setBundleError(data.error || 'Preview build failed.');
      } else {
        setBundledHtml(data.html || '');
        setBundleError(data.bundleError || null);
      }
    } catch (err) {
      setBundleError(err instanceof Error ? err.message : 'Preview request failed.');
    } finally {
      setIsBundling(false);
    }
  }, []);

  useEffect(() => {
    if (!activeProject || activePage === 'settings') return;
    if (bundleTimerRef.current) window.clearTimeout(bundleTimerRef.current);
    bundleTimerRef.current = window.setTimeout(() => {
      void runBundle(activeProject);
    }, 180);
    return () => {
      if (bundleTimerRef.current) window.clearTimeout(bundleTimerRef.current);
    };
  }, [activeProject, activePage, runBundle]);

  // Persist project updates to state + background Firestore sync
  const updateActiveProject = useCallback(
    (updater: (prev: MistProject) => MistProject) => {
      if (!activeProjectId) return;
      let updatedProject: MistProject | null = null;
      setProjects((prev) =>
        prev.map((p) => {
          if (p.id !== activeProjectId) return p;
          updatedProject = { ...updater(p), updatedAt: new Date().toISOString() };
          if (user?.uid) {
            updatedProject.ownerId = user.uid;
          }
          return updatedProject;
        }),
      );

      if (updatedProject) {
        queueProjectForBatchedSync(updatedProject, user?.uid);
      }
    },
    [activeProjectId, user?.uid],
  );

  const handleCancelGeneration = useCallback(() => {
    generateAbortRef.current?.abort();
  }, []);

  const handleCancelRefine = useCallback(() => {
    refineAbortRef.current?.abort();
  }, []);

  // Core SSE streaming generation executor
  const executeGenerateWebsite = useCallback(
    async (prompt: string, currentUser: MistUser) => {
      const cfg = providerConfigRef.current;
      if (!cfg.apiKey?.trim()) {
        setGenerationError(
          `Add your BYOK API key for ${cfg.name || 'your provider'} before generating.`,
        );
        setProvidersOpen(true);
        return;
      }

      const enableAppAiForBuild = shouldEnableAppAi(
        prompt,
        studioSettingsRef.current.appAiMode,
      );

      generateAbortRef.current?.abort();
      const abortController = new AbortController();
      generateAbortRef.current = abortController;

      setIsGenerating(true);
      setGenerationError(null);
      const startedAt = Date.now();
      setAiStreamProgress({
        phase: `Connecting to ${cfg.name || 'BYOK Provider'} (${cfg.model})...`,
        completedFiles: [],
        charsReceived: 0,
        startedAt,
        searchState: 'idle',
      });

      try {
        let data: {
          projectName?: string;
          description?: string;
          summary?: string;
          searchOutcome?: WebSearchOutcome;
          files?: Array<{ path: string; language?: ProjectFile['language']; content: string }>;
        } | null = null;

        // Try direct browser-to-Gemini connection first to eliminate server load
        if (canUseDirectClient(cfg)) {
          try {
            data = await executeDirectGenerate({
              prompt,
              config: cfg,
              signal: abortController.signal,
              onProgress: (ev) => {
                setAiStreamProgress((prev) => {
                  const base = prev || {
                    phase: 'Generating...',
                    completedFiles: [],
                    charsReceived: 0,
                    startedAt,
                  };
                  return {
                    ...base,
                    phase: ev.phase || base.phase,
                    activeFile: ev.activeFile ?? base.activeFile,
                    completedFiles: ev.completedFiles ?? base.completedFiles,
                    charsReceived: ev.chars ?? base.charsReceived,
                  };
                });
              },
            });
          } catch (directErr) {
            console.warn('[Direct Client AI] Direct connection failed, falling back to server stream:', directErr);
          }
        }

        if (!data) {
          const idToken = await currentUser.getIdToken();
          const resp = await fetch('/api/ai/generate/stream', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${idToken}`,
            },
            signal: abortController.signal,
            body: JSON.stringify({
              prompt,
              providerConfig: cfg,
              enableAppAi: enableAppAiForBuild,
              searchConfig: webSearchConfigRef.current,
              searchMode: studioSettingsRef.current.webSearchMode || 'auto',
            }),
          });

          if (!resp.ok) {
            const errPayload = (await resp.json().catch(() => ({}))) as {
              error?: string;
              incident?: ModelHealthIncident;
            };
            const err = new Error(
              errPayload.incident?.message ||
                errPayload.error ||
                `Generation failed (${resp.status}).`,
            ) as Error & { incident?: ModelHealthIncident };
            err.incident = errPayload.incident;
            throw err;
          }

          data = (await consumeAiSseStream(resp, (ev) => {
            setAiStreamProgress((prev) => {
              const base = prev || {
                phase: 'Generating...',
                completedFiles: [],
                charsReceived: 0,
                startedAt,
              };
              if (ev.type === 'search_start') {
                return {
                  ...base,
                  phase: ev.phase || 'Searching live web sources...',
                  searchState: 'searching',
                  searchQueries: ev.queries ?? base.searchQueries,
                  searchError: undefined,
                };
              }
              if (ev.type === 'search_results') {
                return {
                  ...base,
                  searchState: 'done',
                  searchQueries: ev.queries ?? base.searchQueries,
                  searchSources: ev.sources ?? base.searchSources,
                  searchError: undefined,
                };
              }
              if (ev.type === 'search_error') {
                return {
                  ...base,
                  searchState: 'failed',
                  searchQueries: ev.queries ?? base.searchQueries,
                  searchError: ev.error || 'Web search failed.',
                };
              }
              if (ev.type === 'phase') {
                return {
                  ...base,
                  phase: ev.phase || base.phase,
                  completedFiles: ev.completedFiles ?? base.completedFiles,
                  charsReceived: ev.chars ? Math.max(base.charsReceived, ev.chars) : base.charsReceived,
                };
              }
              if (ev.type === 'file_start') {
                return {
                  ...base,
                  phase: `Writing ${ev.path || 'file'}...`,
                  activeFile: ev.path,
                  completedFiles: ev.completedFiles ?? base.completedFiles,
                  charsReceived: ev.chars ?? base.charsReceived,
                };
              }
              if (ev.type === 'file_done' && ev.path) {
                const nextCompleted = base.completedFiles.includes(ev.path)
                  ? base.completedFiles
                  : [...base.completedFiles, ev.path];
                return {
                  ...base,
                  completedFiles: nextCompleted,
                };
              }
              if (ev.type === 'progress') {
                return {
                  ...base,
                  activeFile: ev.activeFile ?? base.activeFile,
                  completedFiles: ev.completedFiles ?? base.completedFiles,
                  charsReceived: ev.chars ?? base.charsReceived,
                };
              }
              return base;
            });
          })) as {
            projectName?: string;
            description?: string;
            summary?: string;
            searchOutcome?: WebSearchOutcome;
            files?: Array<{ path: string; language?: ProjectFile['language']; content: string }>;
          };
        }

        if (!data || !Array.isArray(data.files) || data.files.length === 0) {
          throw new Error('AI did not return project files.');
        }

        setModelIncident(null);
        const now = new Date().toISOString();
        const newProject: MistProject = {
          id: createSafeId('proj'),
          name: (data.projectName || 'Generated Website').slice(0, 120),
          description: (data.description || prompt).slice(0, 500),
          prompt,
          appAiEnabled: enableAppAiForBuild,
          isPublished: false,
          createdAt: now,
          updatedAt: now,
          files: data.files.map((f) => {
            const cleanPath = normalizeProjectFilePath(f.path);
            return {
              id: createSafeId('file'),
              path: cleanPath,
              language: f.language || inferLanguageFromPath(cleanPath),
              content: f.content,
            };
          }),
          chatHistory: [
            {
              id: createSafeId('msg'),
              role: 'user',
              content: prompt,
              timestamp: now,
            },
            {
              id: createSafeId('msg'),
              role: 'assistant',
              content:
                data.summary ||
                `Generated ${data.files.length} files for ${data.projectName || 'your site'}.`,
              timestamp: now,
              changedFiles: data.files.map((f) => f.path),
              searchOutcome: data.searchOutcome,
            },
          ],
        };

        setProjects((prev) => [newProject, ...prev]);
        navigateToProject(newProject.id);

        if (studioSettingsRef.current.notifyOnAnswerDone !== false) {
          notifyAnswerDone(newProject.name).catch(() => {});
        }

        if (currentUser) {
          queueProjectForBatchedSync(newProject);
        }
      } catch (err) {
        if (
          abortController.signal.aborted ||
          (err instanceof Error && err.name === 'AbortError')
        ) {
          setGenerationError('Generation cancelled.');
        } else {
          const withIncident = err as Error & { incident?: ModelHealthIncident };
          if (withIncident.incident) setModelIncident(withIncident.incident);
          setGenerationError(err instanceof Error ? err.message : 'Failed to generate website.');
        }
      } finally {
        if (generateAbortRef.current === abortController) {
          generateAbortRef.current = null;
        }
        setIsGenerating(false);
        setAiStreamProgress(null);
      }
    },
    [],
  );

  // Pure Clerk Authentication State & User Hydration
  useEffect(() => {
    if (!clerkUserLoaded) return;

    if (!clerkSignedIn || !clerkUser) {
      const prevUid = activeAccountUidRef.current;
      if (prevUid) {
        try {
          localStorage.setItem(getProjectsStorageKey(prevUid), JSON.stringify(projectsRef.current));
        } catch {
          // ignore
        }
      }

      setUser(null);
      activeAccountUidRef.current = null;
      setBatchedSyncUserProvider(() => null);
      setDeployments([]);
      clearKnownCloudProjects();
      scrubLegacyCredentialStorage();

      // Cleanly switch to anonymous guest drafts
      const anonProjects = loadLocalProjects(null);
      setProjects(anonProjects);
      projectsRef.current = anonProjects;
      initLocalCacheQueue(null);

      if (activeProjectId && !anonProjects.some((p) => p.id === activeProjectId)) {
        setActiveProjectId(null);
      }
      return;
    }

    setAuthError(null);
    setAuthPromptReason(null);

    const newUid = clerkUser.id;
    const prevUid = activeAccountUidRef.current;

    if (prevUid !== newUid) {
      // Preserve previous account's projects before switching
      try {
        localStorage.setItem(getProjectsStorageKey(prevUid), JSON.stringify(projectsRef.current));
      } catch {
        // ignore
      }

      activeAccountUidRef.current = newUid;

      // Load new user's local projects (NEVER transfer previous account's or anonymous projects!)
      const newLocalProjects = loadLocalProjects(newUid);
      setProjects(newLocalProjects);
      projectsRef.current = newLocalProjects;
      initLocalCacheQueue(newUid);

      if (activeProjectId && !newLocalProjects.some((p) => p.id === activeProjectId)) {
        setActiveProjectId(null);
      }
    }

    const mistUser: MistUser = {
      id: clerkUser.id,
      uid: clerkUser.id,
      email: clerkUser.primaryEmailAddress?.emailAddress ?? null,
      displayName: clerkUser.fullName || clerkUser.firstName || clerkUser.username || null,
      photoURL: clerkUser.imageUrl || null,
      emailVerified: clerkUser.primaryEmailAddress?.verification?.status === 'verified',
      getIdToken: async () => clerkAuth.getToken(),
    };

    setUser(mistUser);
    setApiTokenProvider(clerkAuth.getToken);
    setBatchedSyncUserProvider(() => mistUser);

    void (async () => {
      try {
        const token = await clerkAuth.getToken();
        const [cloudPrefs, encryptedVault] = await Promise.all([
          fetchUserProfilePreferences(mistUser),
          fetchUserEncryptedVault(mistUser),
        ]);

        let hydratedAiConfig = providerConfigRef.current;
        let hydratedSearchConfig = webSearchConfigRef.current;

        if (cloudPrefs) {
          if (cloudPrefs.preferredProvider || cloudPrefs.preferredModel) {
            hydratedAiConfig = normalizeProviderConfigToStudio({
              ...hydratedAiConfig,
              provider: cloudPrefs.preferredProvider || hydratedAiConfig.provider,
              model: cloudPrefs.preferredModel || hydratedAiConfig.model,
            });
          }
          setStudioSettings((prev) => {
            const nextMode =
              cloudPrefs.appAiMode ||
              (typeof cloudPrefs.enableAppAi === 'boolean'
                ? cloudPrefs.enableAppAi
                  ? 'always'
                  : prev.appAiMode
                : prev.appAiMode);
            return {
              theme: cloudPrefs.theme || prev.theme,
              defaultViewMode: cloudPrefs.defaultViewMode || prev.defaultViewMode,
              defaultViewport: cloudPrefs.defaultViewport || prev.defaultViewport,
              appAiMode: nextMode,
              enableAppAi: nextMode === 'always',
              webSearchMode: cloudPrefs.webSearchMode || prev.webSearchMode || 'auto',
            };
          });
        }

        if (encryptedVault?.ciphertext) {
          try {
            const unsealResp = await fetch('/api/user/vault/unseal', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
              },
              body: JSON.stringify({ encryptedPayload: encryptedVault.ciphertext }),
            });
            if (unsealResp.ok) {
              const unsealed = (await unsealResp.json()) as {
                aiConfig?: AiProviderConfig;
                searchConfig?: WebSearchConfig;
              };
              if (unsealed.aiConfig) {
                hydratedAiConfig = normalizeProviderConfigToStudio({
                  ...hydratedAiConfig,
                  ...unsealed.aiConfig,
                  apiKey: unsealed.aiConfig.apiKey || hydratedAiConfig.apiKey || '',
                });
              }
              if (unsealed.searchConfig) {
                hydratedSearchConfig = normalizeWebSearchConfig({
                  ...hydratedSearchConfig,
                  ...unsealed.searchConfig,
                  apiKey: unsealed.searchConfig.apiKey || hydratedSearchConfig.apiKey || '',
                });
              }
            }
          } catch {
            // Non-blocking decrypt failure
          }
        } else if (
          hydratedAiConfig.apiKey?.trim() ||
          hydratedSearchConfig.apiKey?.trim()
        ) {
          void syncCredentialsToAccountVault(
            mistUser,
            hydratedAiConfig,
            hydratedSearchConfig,
          );
        }

        setProviderConfig(hydratedAiConfig);
        setWebSearchConfig(hydratedSearchConfig);

        await syncUserProfile(mistUser, {
          preferredProvider: hydratedAiConfig.provider || cloudPrefs?.preferredProvider,
          preferredModel: hydratedAiConfig.model || cloudPrefs?.preferredModel,
          theme: cloudPrefs?.theme || studioSettingsRef.current.theme,
          defaultViewMode: cloudPrefs?.defaultViewMode || studioSettingsRef.current.defaultViewMode,
          defaultViewport: cloudPrefs?.defaultViewport || studioSettingsRef.current.defaultViewport,
          enableAppAi:
            typeof cloudPrefs?.enableAppAi === 'boolean'
              ? cloudPrefs.enableAppAi
              : studioSettingsRef.current.enableAppAi,
          appAiMode: cloudPrefs?.appAiMode || studioSettingsRef.current.appAiMode,
          webSearchMode: cloudPrefs?.webSearchMode || studioSettingsRef.current.webSearchMode,
        });

        const cloudProjects = await listUserProjectsFromFirestore(mistUser.uid, token);
        const cloudIds = new Set(cloudProjects.map((p) => p.id));

        // Load mistUser's own local projects (NEVER anonymous or other accounts!)
        const userLocal = loadLocalProjects(mistUser.uid);
        const userLocalOnly = userLocal.filter((p) => !cloudIds.has(p.id));

        const merged = new Map<string, MistProject>();
        for (const p of userLocal) merged.set(p.id, p);
        for (const cp of cloudProjects) merged.set(cp.id, cp);
        const mergedList = Array.from(merged.values()).sort((a, b) =>
          b.updatedAt.localeCompare(a.updatedAt),
        );

        setProjects(mergedList);
        projectsRef.current = mergedList;
        try {
          localStorage.setItem(getProjectsStorageKey(mistUser.uid), JSON.stringify(mergedList));
        } catch {
          // ignore
        }

        if (userLocalOnly.length > 0) {
          await syncLocalProjectsToFirestore(userLocalOnly, cloudIds, token, mistUser.uid);
        }

        await refreshDeployments(mistUser);
      } catch (err) {
        console.warn('[Mist App] User hydration failed:', err);
      }

      if (pendingGeneratePromptRef.current) {
        const queued = pendingGeneratePromptRef.current;
        pendingGeneratePromptRef.current = null;
        void executeGenerateWebsite(queued, mistUser);
      }
    })();
  }, [
    clerkUserLoaded,
    clerkSignedIn,
    clerkUser,
    clerkAuth.getToken,
    executeGenerateWebsite,
    refreshDeployments,
    syncCredentialsToAccountVault,
  ]);


  // Require sign-in when clicking Generate Website on the front page
  const handleGenerateWebsite = (prompt: string) => {
    if (!user) {
      pendingGeneratePromptRef.current = prompt;
      setAuthError(null);
      setAuthPromptReason('Sign in to generate and save your website with Mist.');
      setGenerationError('Please sign in to generate a website.');
      setAccountOpen(true);
      return;
    }
    void executeGenerateWebsite(prompt, user);
  };

  const handleDuplicateProject = (target: MistProject) => {
    const copy = duplicateProjectData(target);
    if (user?.uid) {
      copy.ownerId = user.uid;
    }
    setProjects((prev) => [copy, ...prev]);
    navigateToProject(copy.id);
    queueProjectForBatchedSync(copy, user?.uid);
  };

  const handleDeleteProject = (projectId: string) => {
    setProjects((prev) => prev.filter((p) => p.id !== projectId));
    if (activeProjectId === projectId) {
      setActiveProjectId(null);
    }
    dequeueProjectFromBatchedSync(projectId, user?.uid);
    if (user?.uid) {
      void deleteProjectFromFirestore(projectId).catch(() => {});
    }
  };

  const handleRefineWithAi = async (
    instruction: string,
    selectedElement?: SelectedVisualElement | null,
  ) => {
    if (!activeProject) return;
    if (!user) {
      setRefineError('Sign in with Google before using AI refinement.');
      setAuthPromptReason('Sign in with Google to use Mist AI refinement.');
      setAccountOpen(true);
      return;
    }
    if (!providerConfig.apiKey?.trim()) {
      setRefineError(
        `Add your BYOK API key for ${providerConfig.name || 'your provider'} first.`,
      );
      setProvidersOpen(true);
      return;
    }

    const enableAppAiForRefine = shouldEnableAppAi(
      instruction,
      studioSettingsRef.current.appAiMode,
      activeProject.appAiEnabled ? true : undefined,
    );

    refineAbortRef.current?.abort();
    const abortController = new AbortController();
    refineAbortRef.current = abortController;

    setIsRefining(true);
    setRefineError(null);
    const startedAt = Date.now();
    setAiStreamProgress({
      phase: `Analyzing codebase with ${providerConfig.name || 'BYOK'} (${providerConfig.model})...`,
      completedFiles: [],
      charsReceived: 0,
      startedAt,
      searchState: 'idle',
    });

    try {
      const idToken = await user.getIdToken();
      const resp = await fetch('/api/ai/refine/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${idToken}`,
        },
        signal: abortController.signal,
        body: JSON.stringify({
          instruction,
          files: activeProject.files,
          enableAppAi: enableAppAiForRefine,
          selectedElement: selectedElement
            ? {
                tagName: selectedElement.tagName,
                textContent: selectedElement.textContent,
                className: selectedElement.className,
              }
            : undefined,
          providerConfig,
          searchConfig: webSearchConfigRef.current,
          searchMode: studioSettingsRef.current.webSearchMode || 'auto',
        }),
      });
      if (!resp.ok) {
        const errPayload = (await resp.json().catch(() => ({}))) as {
          error?: string;
          incident?: ModelHealthIncident;
        };
        const err = new Error(
          errPayload.incident?.message ||
            errPayload.error ||
            `Refinement failed (${resp.status}).`,
        ) as Error & { incident?: ModelHealthIncident };
        err.incident = errPayload.incident;
        throw err;
      }

      const data = (await consumeAiSseStream(resp, (ev) => {
        setAiStreamProgress((prev) => {
          const base = prev || {
            phase: 'Refining...',
            completedFiles: [],
            charsReceived: 0,
            startedAt,
          };
          if (ev.type === 'search_start') {
            return {
              ...base,
              phase: ev.phase || 'Searching live web sources...',
              searchState: 'searching',
              searchQueries: ev.queries ?? base.searchQueries,
              searchError: undefined,
            };
          }
          if (ev.type === 'search_results') {
            return {
              ...base,
              searchState: 'done',
              searchQueries: ev.queries ?? base.searchQueries,
              searchSources: ev.sources ?? base.searchSources,
              searchError: undefined,
            };
          }
          if (ev.type === 'search_error') {
            return {
              ...base,
              searchState: 'failed',
              searchQueries: ev.queries ?? base.searchQueries,
              searchError: ev.error || 'Web search failed.',
            };
          }
          if (ev.type === 'phase') {
            return {
              ...base,
              phase: ev.phase || base.phase,
              completedFiles: ev.completedFiles ?? base.completedFiles,
              charsReceived: ev.chars ? Math.max(base.charsReceived, ev.chars) : base.charsReceived,
            };
          }
          if (ev.type === 'file_start') {
            return {
              ...base,
              phase: `Editing ${ev.path || 'file'}...`,
              activeFile: ev.path,
              completedFiles: ev.completedFiles ?? base.completedFiles,
              charsReceived: ev.chars ?? base.charsReceived,
            };
          }
          if (ev.type === 'file_done' && ev.path) {
            const nextCompleted = base.completedFiles.includes(ev.path)
              ? base.completedFiles
              : [...base.completedFiles, ev.path];
            return {
              ...base,
              completedFiles: nextCompleted,
            };
          }
          if (ev.type === 'progress') {
            return {
              ...base,
              activeFile: ev.activeFile ?? base.activeFile,
              completedFiles: ev.completedFiles ?? base.completedFiles,
              charsReceived: ev.chars ?? base.charsReceived,
            };
          }
          return base;
        });
      })) as {
        summary?: string;
        searchOutcome?: WebSearchOutcome;
        files?: Array<{ path: string; language?: ProjectFile['language']; content: string }>;
      };

      if (!Array.isArray(data.files)) {
        throw new Error('Refinement did not return updated files.');
      }

      setModelIncident(null);
      const now = new Date().toISOString();
      const changedPaths = data.files.map((f) => f.path.replace(/^\/+/, ''));

      updateActiveProject((prev) => ({
        ...prev,
        appAiEnabled: Boolean(prev.appAiEnabled || enableAppAiForRefine),
        files: mergeProjectFiles(prev.files, data.files!),
        chatHistory: [
          ...prev.chatHistory,
          { id: createSafeId('msg'), role: 'user', content: instruction, timestamp: now },
          {
            id: createSafeId('msg'),
            role: 'assistant',
            content: data.summary || 'Applied your refinement.',
            timestamp: now,
            changedFiles: changedPaths,
            searchOutcome: data.searchOutcome,
          },
        ],
      }));

      if (studioSettingsRef.current.notifyOnAnswerDone !== false) {
        notifyAnswerDone(activeProject.name).catch(() => {});
      }
    } catch (err) {
      if (
        abortController.signal.aborted ||
        (err instanceof Error && err.name === 'AbortError')
      ) {
        setRefineError('Refinement cancelled.');
      } else {
        const withIncident = err as Error & { incident?: ModelHealthIncident };
        if (withIncident.incident) setModelIncident(withIncident.incident);
        setRefineError(err instanceof Error ? err.message : 'Failed to apply refinement.');
      }
    } finally {
      if (refineAbortRef.current === abortController) {
        refineAbortRef.current = null;
      }
      setIsRefining(false);
      setAiStreamProgress(null);
    }
  };

  const triggerBrowserFileDownload = (blob: Blob, fileName: string) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const fetchStandaloneHtmlBundle = async (target: MistProject): Promise<string | undefined> => {
    try {
      const resp = await fetch('/api/bundle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: target.files,
          title: target.name,
          includeInspector: false,
          enableAppAi: false,
          standaloneExport: true,
        }),
      });
      if (!resp.ok) return undefined;
      const data = (await resp.json()) as { html?: string };
      return typeof data.html === 'string' && data.html.trim() ? data.html : undefined;
    } catch {
      return undefined;
    }
  };

  const handleExportZip = async (
    targetProject?: MistProject | null,
    customSlug?: string,
  ): Promise<string | null> => {
    const target = targetProject || activeProject;
    if (!target) return null;
    const cleanSlug = customSlug ? sanitizeSlug(customSlug) : target.publishedSlug || suggestShortSlug(target.name);
    const standaloneHtml = await fetchStandaloneHtmlBundle(target);
    const manifest = buildExportManifest(target, { standaloneHtml, slug: cleanSlug });
    const zip = new JSZip();
    for (const [filePath, content] of Object.entries(manifest)) {
      zip.file(filePath, content);
    }
    const blob = await zip.generateAsync({ type: 'blob' });
    const fileName = `${cleanSlug}.zip`;
    triggerBrowserFileDownload(blob, fileName);
    return fileName;
  };

  const handleDownloadStandaloneHtml = async (
    targetProject?: MistProject | null,
    customSlug?: string,
  ) => {
    const target = targetProject || deployProject || activeProject;
    if (!target) return;
    setIsDeploying(true);
    setDeployError(null);
    try {
      const cleanSlug = customSlug ? sanitizeSlug(customSlug) : suggestShortSlug(target.name);
      const html = await fetchStandaloneHtmlBundle(target);
      if (!html) {
        throw new Error('Could not build standalone HTML right now. Use Download Publish ZIP instead.');
      }
      const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
      const fileName = `${cleanSlug}-index.html`;
      triggerBrowserFileDownload(blob, fileName);
      setDownloadedFileName(fileName);
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : 'Failed to export standalone HTML.');
    } finally {
      setIsDeploying(false);
    }
  };

  const handleDownloadPublishZip = async (
    slug: string,
    targetProject?: MistProject | null,
  ) => {
    const target = targetProject || deployProject || activeProject;
    if (!target) return;
    setIsDeploying(true);
    setDeployError(null);
    try {
      const cleanSlug = sanitizeSlug(slug || suggestShortSlug(target.name));
      const fileName = await handleExportZip(target, cleanSlug);
      if (fileName) {
        setDownloadedFileName(fileName);
      }
      const updatedProject: MistProject = {
        ...target,
        isPublished: true,
        publishedSlug: cleanSlug,
        updatedAt: new Date().toISOString(),
      };
      setProjects((prev) => prev.map((p) => (p.id === target.id ? updatedProject : p)));
      if (user) {
        queueProjectForBatchedSync(updatedProject);
      }
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : 'Failed to prepare publish ZIP.');
    } finally {
      setIsDeploying(false);
    }
  };

  const handleOpenPublish = (targetProject?: MistProject) => {
    const target = targetProject || activeProject;
    if (!target) return;
    setDeployProjectId(target.id);
    setDeployError(null);
    setDownloadedFileName(null);
    setDeployOpen(true);
    const defaultSlug = target.publishedSlug || suggestShortSlug(target.name);
    void handleDownloadPublishZip(defaultSlug, target);
  };

  const handleDeleteDeployment = async (slug: string) => {
    if (!user) {
      setAuthPromptReason('Sign in with Google to unpublish your website.');
      setAccountOpen(true);
      return;
    }
    try {
      const idToken = await user.getIdToken();
      await fetch(`/api/deployments/${encodeURIComponent(slug)}`, {
        method: 'DELETE',
        headers: {
          Authorization: `Bearer ${idToken}`,
        },
      });
      await refreshDeployments(user);
    } catch {
      // ignore
    }
  };

  const handleSaveProvider = (rawNext: AiProviderConfig) => {
    const next = normalizeProviderConfigToStudio(rawNext);
    setProviderConfig(next);
    setGenerationError(null);
    setRefineError(null);
    setModelIncident((prev) =>
      prev && (prev.provider !== next.provider || prev.model !== next.model) ? null : prev,
    );
    scrubLegacyCredentialStorage();
    if (user) {
      void syncUserProfile(user, {
        preferredProvider: next.provider,
        preferredModel: next.model,
      }).catch(() => {});
      void syncCredentialsToAccountVault(user, next, webSearchConfigRef.current);
    }
  };

  const handleSaveWebSearch = (rawNext: WebSearchConfig) => {
    const next = normalizeWebSearchConfig(rawNext);
    setWebSearchConfig(next);
    setGenerationError(null);
    setRefineError(null);
    scrubLegacyCredentialStorage();
    if (user) {
      void syncCredentialsToAccountVault(user, providerConfigRef.current, next);
    }
  };

  const handleUpdateSettings = (partial: Partial<StudioSettings>) => {
    setStudioSettings((prev) => {
      const next: StudioSettings = {
        ...prev,
        ...partial,
        enableAppAi:
          partial.appAiMode !== undefined
            ? partial.appAiMode === 'always'
            : typeof partial.enableAppAi === 'boolean'
              ? partial.enableAppAi
              : prev.appAiMode === 'always',
      };
      if (user) {
        void syncUserProfile(user, {
          theme: next.theme,
          defaultViewMode: next.defaultViewMode,
          defaultViewport: next.defaultViewport,
          enableAppAi: next.enableAppAi,
          appAiMode: next.appAiMode,
          webSearchMode: next.webSearchMode,
        }).catch(() => {});
      }
      return next;
    });
  };

  const handleOAuthSignIn = async (strategy: 'oauth_google' | 'oauth_github') => {
    setAuthError(null);
    try {
      const redirectUrl = `${window.location.origin}/sso-callback`;
      const redirectUrlComplete = `${window.location.origin}/`;

      if (clerk.client?.signIn) {
        await clerk.client.signIn.authenticateWithRedirect({
          strategy,
          redirectUrl,
          redirectUrlComplete,
          continueSignUp: true,
          oidcPrompt: 'consent',
        });
        return;
      }
      if (clerk.client?.signUp) {
        await clerk.client.signUp.authenticateWithRedirect({
          strategy,
          redirectUrl,
          redirectUrlComplete,
          continueSignUp: true,
          oidcPrompt: 'consent',
        });
        return;
      }
      clerk.openSignIn({ appearance: mistClerkAppearance });
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'OAuth sign-in failed.');
    }
  };

  const handleEmailSignIn = () => {
    setAuthError(null);
    try {
      clerk.openSignIn({ appearance: mistClerkAppearance });
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'Sign-in failed.');
    }
  };

  const handleSignOut = async () => {
    setAuthError(null);
    try {
      if (user) {
        try {
          const idToken = await user.getIdToken();
          await fetch('/api/ai/session/revoke-all', {
            method: 'POST',
            headers: { Authorization: `Bearer ${idToken}` },
          });
        } catch {
          // Best-effort session revocation before sign-out
        }
      }
      await clerkAuth.signOut();
      clearKnownCloudProjects();
      scrubLegacyCredentialStorage();
      setProjects([]);
      setProviderConfig({ ...DEFAULT_BYOK_CONFIG });
      setWebSearchConfig({ ...DEFAULT_WEB_SEARCH_CONFIG });
      setActiveProjectId(null);
      setActivePage('home');
      clearPendingDirtyQueue();
      try {
        localStorage.removeItem(getProjectsStorageKey(user?.uid));
      } catch {
        // ignore
      }
      setAccountOpen(false);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'Sign-out failed.');
    }
  };

  return (
    <>
      {activePage === 'settings' ? (
        <SettingsView
          user={user}
          projects={projects}
          deployments={deployments}
          providerConfig={providerConfig}
          webSearchConfig={webSearchConfig}
          studioSettings={studioSettings}
          modelIncident={modelIncident}
          onBack={() => setActivePage('home')}
          onSaveProvider={handleSaveProvider}
          onSaveWebSearch={handleSaveWebSearch}
          onUpdateSettings={handleUpdateSettings}
          onIncident={setModelIncident}
          onSignIn={() => void handleOAuthSignIn('oauth_google')}
          onSignOut={() => void handleSignOut()}
        />
      ) : activeProject ? (
        <WorkspaceView
          key={activeProject.id}
          user={user}
          project={activeProject}
          providerConfig={providerConfig}
          defaultViewMode={studioSettings.defaultViewMode}
          defaultViewport={studioSettings.defaultViewport}
          webSearchMode={studioSettings.webSearchMode || 'auto'}
          hasWebSearchKey={webSearchConfigReady(webSearchConfig)}
          modelIncident={modelIncident}
          bundledHtml={bundledHtml}
          bundleError={bundleError}
          isBundling={isBundling}
          isRefining={isRefining}
          streamProgress={aiStreamProgress}
          refineError={refineError}
          onBackHome={navigateToHome}
          onUpdateProjectName={(name) =>
            updateActiveProject((prev) => ({ ...prev, name: name.slice(0, 120) }))
          }
          onChangeFileContent={(filePath, content) =>
            updateActiveProject((prev) => ({
              ...prev,
              files: prev.files.map((f) => (f.path === filePath ? { ...f, content } : f)),
            }))
          }
          onCreateFile={(filePath) =>
            updateActiveProject((prev) => ({
              ...prev,
              files: [
                ...prev.files,
                {
                  id: createSafeId('file'),
                  path: filePath,
                  language: inferLanguageFromPath(filePath),
                  content: `import React from 'react';\n\nexport default function Component() {\n  return <div>New component</div>;\n}\n`,
                },
              ],
            }))
          }
          onDeleteFile={(filePath) =>
            updateActiveProject((prev) => ({
              ...prev,
              files: prev.files.filter((f) => f.path !== filePath),
            }))
          }
          onCommitVisualPatch={(patch) =>
            updateActiveProject((prev) => ({
              ...prev,
              files: applyVisualPatchToFiles(prev.files, patch),
            }))
          }
          onRefineWithAi={handleRefineWithAi}
          onCancelRefine={handleCancelRefine}
          onChangeWebSearchMode={(mode) => handleUpdateSettings({ webSearchMode: mode })}
          onOpenVoiceChat={() => setVoiceChatOpen(true)}
          onRebundle={() => void runBundle(activeProject)}
          onDuplicateProject={() => handleDuplicateProject(activeProject)}
          onExportZip={() => void handleExportZip(activeProject)}
          onOpenDeploy={() => handleOpenPublish(activeProject)}
          onOpenProviders={() => setProvidersOpen(true)}
          onOpenSettings={navigateToSettings}
          onOpenAccount={() => {
            setAuthPromptReason(null);
            setAccountOpen(true);
          }}
          onOpenMistCode={() => setMistCodeOpen(true)}
        />
      ) : (
        <HomeView
          user={user}
          projects={projects}
          deployments={deployments}
          providerConfig={providerConfig}
          modelIncident={modelIncident}
          isGenerating={isGenerating}
          streamProgress={aiStreamProgress}
          generationError={generationError}
          darkMode={darkMode}
          appAiMode={studioSettings.appAiMode}
          webSearchMode={studioSettings.webSearchMode || 'auto'}
          hasWebSearchKey={webSearchConfigReady(webSearchConfig)}
          onChangeAppAiMode={(mode) =>
            handleUpdateSettings({ appAiMode: mode, enableAppAi: mode === 'always' })
          }
          onChangeWebSearchMode={(mode) => handleUpdateSettings({ webSearchMode: mode })}
          onToggleDarkMode={() =>
            handleUpdateSettings({ theme: darkMode ? 'light' : 'dark' })
          }
          onSaveProvider={handleSaveProvider}
          onGenerate={handleGenerateWebsite}
          onCancelGeneration={handleCancelGeneration}
          onOpenVoiceChat={() => setVoiceChatOpen(true)}
          onOpenProject={(project) => navigateToProject(project.id)}
          onPublishProject={(project) => handleOpenPublish(project)}
          onDuplicateProject={handleDuplicateProject}
          onDeleteProject={handleDeleteProject}
          onOpenProviders={() => setProvidersOpen(true)}
          onOpenSettings={navigateToSettings}
          onOpenDeployments={() => {
            void refreshDeployments(user);
            setDeploymentsListOpen(true);
          }}
          onOpenAccount={() => {
            setAuthPromptReason(null);
            setAccountOpen(true);
          }}
          onOpenMistCode={() => setMistCodeOpen(true)}
        />
      )}

      <ProvidersModal
        isOpen={providersOpen}
        user={user}
        config={providerConfig}
        modelIncident={modelIncident}
        onClose={() => setProvidersOpen(false)}
        onSave={handleSaveProvider}
        onIncident={setModelIncident}
      />

      <DeployModal
        isOpen={deployOpen}
        project={deployProject}
        user={user}
        isDeploying={isDeploying}
        deployError={deployError}
        downloadedFileName={downloadedFileName}
        onClose={() => setDeployOpen(false)}
        onDownloadPublishZip={(slug) => void handleDownloadPublishZip(slug)}
        onDownloadStandaloneHtml={(slug) => void handleDownloadStandaloneHtml(undefined, slug)}
      />

      <DeploymentsModal
        isOpen={deploymentsListOpen}
        deployments={deployments}
        onClose={() => setDeploymentsListOpen(false)}
        onDeleteDeployment={(slug) => void handleDeleteDeployment(slug)}
      />

      <AccountModal
        isOpen={accountOpen}
        user={user}
        authError={authError}
        promptReason={authPromptReason}
        onClose={() => {
          setAccountOpen(false);
          setAuthPromptReason(null);
        }}
        onSignIn={() => void handleOAuthSignIn('oauth_google')}
        onSignInGoogle={() => void handleOAuthSignIn('oauth_google')}
        onSignInGithub={() => void handleOAuthSignIn('oauth_github')}
        onSignInEmail={() => void handleEmailSignIn()}
        onSignOut={() => void handleSignOut()}
        onManageProfile={() => {
          try {
            clerk.openUserProfile({ appearance: mistClerkAppearance });
          } catch (err) {
            console.error('Failed to open user profile:', err);
          }
        }}
      />

      <VoiceChatModal
        isOpen={voiceChatOpen}
        user={user}
        mode={activeProject ? 'refine' : 'create'}
        projectName={activeProject?.name}
        providerConfig={providerConfig}
        onClose={() => setVoiceChatOpen(false)}
        onOpenProviders={() => setProvidersOpen(true)}
        onIncident={(incident) => setModelIncident(incident)}
        onApplyPrompt={(synthesized) => {
          if (activeProject) {
            void handleRefineWithAi(synthesized);
          } else {
            handleGenerateWebsite(synthesized);
          }
        }}
      />

      <MistCodeModal
        isOpen={mistCodeOpen}
        onClose={() => setMistCodeOpen(false)}
      />
    </>
  );
}
