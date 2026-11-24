export type FileLanguage = 'tsx' | 'ts' | 'css' | 'html' | 'json';

export interface ProjectFile {
  id: string;
  path: string;
  language: FileLanguage;
  content: string;
}

export type WebSearchProviderId = 'duckduckgo' | 'brave_llm_context' | 'brave_web' | 'custom_json';
export type WebSearchMode = 'auto' | 'on' | 'off';

export interface WebSearchConfig {
  provider: WebSearchProviderId;
  name?: string;
  baseUrl?: string;
  apiKey?: string;
  sessionOnlyKey?: boolean;
  maxResults?: number;
}

export interface WebSearchSource {
  id: string;
  title: string;
  url: string;
  publishedDate?: string;
  snippet: string;
  hostname?: string;
}

export interface WebSearchOutcome {
  status: 'performed' | 'skipped' | 'no_results' | 'failed' | 'cancelled';
  queries: string[];
  sources: WebSearchSource[];
  citedIds?: string[];
  warning?: string;
  error?: string;
  searchedAt?: string;
  providerName?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  changedFiles?: string[];
  searchOutcome?: WebSearchOutcome;
}

export interface MistProject {
  id: string;
  ownerId?: string;
  name: string;
  description: string;
  prompt: string;
  templateId?: string;
  appAiEnabled?: boolean;
  files: ProjectFile[];
  chatHistory: ChatMessage[];
  publishedSlug?: string;
  isPublished: boolean;
  createdAt: string;
  updatedAt: string;
}

export type AiProviderId = 'custom' | 'openrouter' | 'groq' | 'gemini';
export type PrimaryProviderId = 'custom';
export type ModelBilling = 'free' | 'paid' | 'unknown' | 'provider_billed';
export type ModelLifecycleStatus = 'active' | 'preview' | 'deprecated' | 'retired' | 'unverified';
export type CatalogSource = 'live' | 'cached' | 'preset';
export type AppAiMode = 'on_request' | 'always' | 'off';

export interface ModelCapabilities {
  textGeneration: boolean;
  jsonOutput: boolean | 'unknown';
  streaming: boolean | 'unknown';
  imageInput: boolean | 'unknown';
  toolCalling: boolean | 'unknown';
}

export interface ModelVerificationResult {
  gatewayBaseUrl: string;
  model: string;
  verified: boolean;
  testedAt: string;
  capabilities?: Partial<ModelCapabilities>;
}

export interface AiProviderConfig {
  provider: AiProviderId;
  name?: string;
  model: string;
  apiKey?: string;
  baseUrl?: string;
  sessionOnlyKey?: boolean;
}

export interface AiStreamProgress {
  phase: string;
  activeFile?: string;
  completedFiles: string[];
  charsReceived: number;
  startedAt: number;
  searchState?: 'idle' | 'searching' | 'done' | 'failed';
  searchQueries?: string[];
  searchSources?: WebSearchSource[];
  searchError?: string;
}

export interface ProjectSyncRecord {
  projectId: string;
  state: 'synced' | 'syncing' | 'local' | 'error';
  cloudFileCount?: number;
  lastSyncedAt?: string;
  error?: string;
}

export interface VisualElementStyles {
  color: string;
  backgroundColor: string;
  fontSize: string;
  fontWeight: string;
  paddingTop: string;
  paddingBottom: string;
  paddingLeft: string;
  paddingRight: string;
  borderRadius: string;
  textAlign: string;
}

export interface SelectedVisualElement {
  mistId: string;
  tagName: string;
  textContent: string;
  className: string;
  styles: VisualElementStyles;
  canEditText: boolean;
}

export interface VisualElementPatch {
  mistId: string;
  originalText?: string;
  newText?: string;
  styles?: Partial<VisualElementStyles>;
  deleted?: boolean;
}

export interface DeploymentRecord {
  slug: string;
  projectId: string;
  title: string;
  url: string;
  updatedAt: string;
}

export type WorkspaceViewMode = 'preview' | 'visual' | 'code' | 'split';
export type ViewportSize = 'desktop' | 'tablet' | 'mobile';

export interface StudioSettings {
  theme: 'dark' | 'light';
  defaultViewMode: WorkspaceViewMode;
  defaultViewport: ViewportSize;
  enableAppAi: boolean;
  appAiMode: AppAiMode;
  webSearchMode?: WebSearchMode;
  notifyOnAnswerDone?: boolean;
}

/**
 * Canonical Authenticated User in Mist.
 * Clerk is the sole authentication provider.
 * Firebase Auth is completely removed from the client and backend.
 */
export interface MistUser {
  /** Canonical Clerk User ID (e.g. 'user_2...') */
  id: string;
  /** Canonical Clerk User ID (alias for id) */
  uid: string;
  email: string | null;
  displayName: string | null;
  photoURL?: string | null;
  emailVerified: boolean;
  /** Resolves the active Clerk session JWT token for authenticating backend API requests */
  getIdToken: () => Promise<string | null>;
}

export type User = MistUser;

