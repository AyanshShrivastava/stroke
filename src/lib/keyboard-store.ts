/**
 * STROKE // KEYBOARD CHAT & LOCAL DATA STORE
 * Robust, quota-safe local data management, optimistic concurrency,
 * durable message ID cursors, and bidirectional Archivist rule extraction.
 */

import {
  idbSaveChat,
  idbLoadChats,
  idbDeleteChat,
  idbClearAllChats,
  estimateStorage,
  formatStorageBytes,
  type StorageDiagnostics,
} from "./idb-storage";

export type ExecutionStep = {
  name: string;
  detail: string;
  status?: "pending" | "running" | "success" | "error" | "warning";
  timestamp?: string;
  type?: "tool" | "file" | "test" | "agent" | "reasoning" | "studio" | "general";
};

export type CodingLoopReport = {
  iterations: number;
  initial_passed: boolean;
  final_passed: boolean;
  healed: boolean;
  syntax_valid: boolean;
  domain_tests_passed: boolean;
  history?: Array<{
    iteration: number;
    passed: boolean;
    fixes?: string[];
  }>;
};

export type Attachment = {
  name: string;
  size?: number;
  type?: string;
  preview?: string;
};

export type MessageStatus = "sent" | "streaming" | "pending" | "error" | "failed";

export type ChatMsg = {
  id: string;
  role: "user" | "builder";
  text: string;
  at: number;
  seq?: number;
  status?: MessageStatus;
  errorMessage?: string;
  executionSteps?: ExecutionStep[];
  codingLoop?: CodingLoopReport;
  taskId?: string;
  taskState?: string;
  taskBudget?: Record<string, unknown>;
  durationSeconds?: number;
  model?: string;
  provider?: string;
  reasoningLevel?: string;
  sources?: Array<{ title?: string; url?: string; snippet?: string }>;
  attachments?: Attachment[];
  godTierVfxLearned?: boolean;
  learnedVfxName?: string;
};

export type Note = {
  id: string;
  content: string;
  created_at: string;
  messageId?: string;
};

export type Chat = {
  id: string;
  title: string;
  updatedAt: number;
  version: number;
  messages: ChatMsg[];
  lastArchivedId?: string;
  archivedMessageIds?: string[];
  notes?: Note[];
  isSyncing?: boolean;
  syncStatus?: "synced" | "syncing" | "failed";
  archivedUpTo?: number; // Deprecated legacy index
  model?: string;
  reasoningLevel?: string;
};

export type Ingested = {
  name: string;
  files: number;
  bytes: number;
  map: string;
  at: number;
} | null;

export const CACHE_KEY = ".stroke_cache";
const CHATS_KEY = "keyboard.chats";
const INGEST_KEY = "keyboard.ingest";
const GH_KEY = "keyboard.github";
const PREFS_KEY = "stroke.user_preferences";

export const AVAILABLE_MODELS = [
  {
    id: "llama-3.3-70b-versatile",
    name: "Llama 3.3 70B",
    badge: "Groq LPU",
    provider: "groq",
    isLocal: false,
    description: "Ultra-fast 70B open model running on Groq LPUs with full tool support",
  },
  {
    id: "llama-3.1-8b-instant",
    name: "Llama 3.1 8B Instant",
    badge: "Groq LPU",
    provider: "groq",
    isLocal: false,
    description: "Instantaneous feedback on Groq LPUs for rapid edits and queries",
  },
  {
    id: "gemini-2.0-flash",
    name: "Gemini 2.0 Flash",
    badge: "Google Flash",
    provider: "gemini",
    isLocal: false,
    description: "Frontier multimodal model with 1M context, high speed, and robust tool calling",
  },
  {
    id: "gemini-1.5-pro",
    name: "Gemini 1.5 Pro",
    badge: "Google Pro",
    provider: "gemini",
    isLocal: false,
    description: "2M token context window for massive project analysis and deep reasoning",
  },
  {
    id: "claude-3-5-sonnet-20241022",
    name: "Claude 3.5 Sonnet",
    badge: "Anthropic",
    provider: "anthropic",
    isLocal: false,
    description: "Industry-leading coding, architectural reasoning, and Luau generation",
  },
  {
    id: "deepseek/deepseek-r1",
    name: "DeepSeek R1",
    badge: "OpenRouter",
    provider: "openrouter",
    isLocal: false,
    description: "Deep open reasoning engine with explicit thought traces via OpenRouter",
  },
  {
    id: "gpt-4o",
    name: "GPT-4o",
    badge: "OpenAI",
    provider: "openai",
    isLocal: false,
    description: "High-intelligence multimodal flagship from OpenAI",
  },
  {
    id: "custom",
    name: "Custom Provider",
    badge: "BYOK",
    provider: "custom",
    isLocal: false,
    description: "Custom OpenAI-compatible or Anthropic-compatible API endpoint",
  },
  {
    id: "llama3.2-local",
    name: "Llama 3.2 1B",
    badge: "Legacy",
    provider: "local",
    isLocal: true,
    description: "Offline local model option",
  },
] as const;

export const REASONING_LEVELS = [
  { id: "low", label: "Low", desc: "Fast synthesis, minimal verification" },
  { id: "medium", label: "Medium", desc: "Standard analysis and syntax checks" },
  { id: "high", label: "High", desc: "Deep reasoning with multi-file verification" },
  { id: "maximum", label: "Max", desc: "Exhaustive self-healing & domain tests" },
  { id: "absolute_peak", label: "Peak", desc: "Ultimate agentic VFX & procedural orchestration" },
] as const;

const isBrowser = () => typeof window !== "undefined";
const uid = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

// In-memory cache for fast synchronous reads
let memoryChatsCache: Chat[] = [];
let cacheLoaded = false;
const activeSyncs = new Set<string>();

export function hasCache() {
  return isBrowser() && !!localStorage.getItem(CACHE_KEY);
}
export function writeCache() {
  if (isBrowser()) {
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify({ v: 1, at: Date.now() }));
    } catch {
      // ignore
    }
  }
}
export function wipeCache() {
  if (isBrowser()) {
    try {
      localStorage.removeItem(CACHE_KEY);
    } catch {
      // ignore
    }
  }
}

export function loadUserPreferences(): { model: string; reasoningLevel: string } {
  if (!isBrowser()) return { model: "llama-3.3-70b-versatile", reasoningLevel: "medium" };
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    // fallback
  }
  return { model: "llama-3.3-70b-versatile", reasoningLevel: "medium" };
}

export function saveUserPreferences(updates: Partial<{ model: string; reasoningLevel: string }>) {
  if (!isBrowser()) return;
  try {
    const current = loadUserPreferences();
    const merged = { ...current, ...updates };
    localStorage.setItem(PREFS_KEY, JSON.stringify(merged));
  } catch {
    // quota or security error
  }
}

/**
 * Loads chats synchronously from memory / localStorage, with background async IDB hydration.
 */
export function loadChats(): Chat[] {
  if (!isBrowser()) return [];
  if (cacheLoaded && memoryChatsCache.length > 0) {
    return memoryChatsCache;
  }

  let chats: Chat[] = [];
  try {
    const raw = localStorage.getItem(CHATS_KEY);
    if (raw) {
      chats = JSON.parse(raw);
    }
  } catch {
    chats = [];
  }

  // Normalize legacy chats
  chats = chats.map((c) => normalizeChat(c));
  memoryChatsCache = chats;
  cacheLoaded = true;

  // Background hydration from IndexedDB for comprehensive history
  idbLoadChats()
    .then((idbChats) => {
      if (idbChats && idbChats.length > 0) {
        const mergedMap = new Map<string, Chat>();
        idbChats.forEach((c) => mergedMap.set(c.id, normalizeChat(c)));
        memoryChatsCache.forEach((c) => {
          if (!mergedMap.has(c.id) || (c.version || 0) >= (mergedMap.get(c.id)?.version || 0)) {
            mergedMap.set(c.id, c);
          }
        });
        const merged = Array.from(mergedMap.values());
        merged.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
        memoryChatsCache = merged;
        window.dispatchEvent(new Event("keyboard:chats"));
      }
    })
    .catch(() => {});

  return memoryChatsCache;
}

function normalizeChat(c: Partial<Chat> & Record<string, unknown>): Chat {
  const messages: ChatMsg[] = Array.isArray(c.messages) ? c.messages : [];
  let lastArchivedId = c.lastArchivedId;
  const archivedMessageIds: string[] = Array.isArray(c.archivedMessageIds)
    ? c.archivedMessageIds
    : [];

  // Migration from legacy archivedUpTo index
  if (
    !lastArchivedId &&
    typeof c.archivedUpTo === "number" &&
    c.archivedUpTo > 0 &&
    messages.length > 0
  ) {
    const idx = Math.min(c.archivedUpTo - 1, messages.length - 1);
    if (idx >= 0 && messages[idx]) {
      lastArchivedId = messages[idx].id;
    }
  }

  return {
    id: c.id || uid(),
    title: c.title || "Untitled Chat",
    updatedAt: c.updatedAt || Date.now(),
    version: c.version || 1,
    messages,
    lastArchivedId,
    archivedMessageIds,
    notes: Array.isArray(c.notes) ? c.notes : [],
    syncStatus: c.syncStatus || "synced",
    model: c.model || "llama-3.3-70b-versatile",
    reasoningLevel: c.reasoningLevel || "medium",
  };
}

export function saveChats(chats: Chat[]) {
  const normalized = chats.map((c) => normalizeChat(c));
  memoryChatsCache = normalized;

  if (isBrowser()) {
    // 1. Write to IndexedDB (asynchronously, handles large payloads)
    normalized.forEach((chat) => {
      idbSaveChat(chat).catch((err) => {
        console.warn("[Stroke Store] Failed to save chat to IDB:", err);
      });
    });

    // 2. Write lightweight index to localStorage with Quota protection
    try {
      // Strip large execution step payloads in localStorage copy to prevent QuotaExceededError
      const lightChats = normalized.map((c) => ({
        ...c,
        messages: c.messages.slice(-50).map((m) => ({
          id: m.id,
          role: m.role,
          text: m.text,
          at: m.at,
          status: m.status,
          errorMessage: m.errorMessage,
        })),
      }));
      localStorage.setItem(CHATS_KEY, JSON.stringify(lightChats));
    } catch (err) {
      console.warn("[Stroke Store] localStorage quota reached; relying on IndexedDB:", err);
    }
  }

  window.dispatchEvent(new Event("keyboard:chats"));
}

export function getChat(id: string): Chat | undefined {
  return loadChats().find((c) => c.id === id);
}

export function createChat(): Chat {
  const prefs = loadUserPreferences();
  const chat: Chat = {
    id: uid(),
    title: "New chat",
    updatedAt: Date.now(),
    version: 1,
    messages: [],
    archivedMessageIds: [],
    notes: [],
    syncStatus: "synced",
    model: prefs.model,
    reasoningLevel: prefs.reasoningLevel,
  };
  saveChats([chat, ...loadChats()]);
  return chat;
}

export function upsertChat(chat: Chat) {
  const existing = getChat(chat.id);
  const nextVersion = (chat.version || existing?.version || 0) + 1;
  const updatedChat: Chat = {
    ...chat,
    version: nextVersion,
    updatedAt: Date.now(),
  };

  const currentChats = loadChats();
  const rest = currentChats.filter((c) => c.id !== chat.id);
  saveChats([updatedChat, ...rest]);

  // Trigger background cloud sync if available
  triggerCloudSync(updatedChat).catch(() => {});
}

export function deleteChat(id: string) {
  if (isBrowser()) {
    idbDeleteChat(id).catch(() => {});
  }
  saveChats(loadChats().filter((c) => c.id !== id));

  // Propagate deletion to backend
  fetch(`/api/chats/${id}`, { method: "DELETE" }).catch(() => {});
}

export const newMsg = (
  role: ChatMsg["role"],
  text: string,
  extra?: Partial<Omit<ChatMsg, "id" | "role" | "text" | "at">>,
): ChatMsg => ({
  id: uid(),
  role,
  text,
  at: Date.now(),
  status: "sent",
  ...extra,
});

export function loadIngest(): Ingested {
  if (!isBrowser()) return null;
  try {
    return JSON.parse(localStorage.getItem(INGEST_KEY) || "null");
  } catch {
    return null;
  }
}
export function saveIngest(i: Ingested) {
  if (!isBrowser()) return;
  try {
    localStorage.setItem(INGEST_KEY, JSON.stringify(i));
  } catch {
    // quota guard
  }
}

export function loadGithub(): { pat: string; repo: string } {
  if (!isBrowser()) return { pat: "", repo: "" };
  try {
    const raw = localStorage.getItem(GH_KEY);
    if (!raw) return { pat: "", repo: "" };
    const parsed = JSON.parse(raw);
    // Security: purge any PAT from browser storage
    if (parsed.pat) {
      localStorage.setItem(GH_KEY, JSON.stringify({ repo: parsed.repo || "" }));
    }
    return { pat: "", repo: parsed.repo || "" };
  } catch {
    return { pat: "", repo: "" };
  }
}
export function saveGithub(v: { pat?: string; repo: string }) {
  if (isBrowser()) {
    try {
      // Security: never save PAT in localStorage
      localStorage.setItem(GH_KEY, JSON.stringify({ repo: v.repo || "" }));
    } catch {
      // ignore
    }
  }
}

export async function getStorageDiagnostics(): Promise<StorageDiagnostics> {
  return estimateStorage();
}

export function localBytes(): number {
  if (!isBrowser()) return 0;
  let n = 0;
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)!;
      n += (k.length + (localStorage.getItem(k)?.length ?? 0)) * 2;
    }
  } catch {
    // ignore
  }
  return n;
}

export function formatBytes(b: number) {
  return formatStorageBytes(b);
}

// -----------------------------------------------------------------------------
// ARCHIVIST: IDEMPOTENT MULTI-ROLE RULE & CONTEXT EXTRACTION
// -----------------------------------------------------------------------------
const RULE_RX =
  /\b(always|never|must|don't|do not|should|rule|prefer|use|require|enforce|standard)\b/i;
const DECISION_RX =
  /\b(decided|architect|pattern|implemented|structured|refactored|verified|passed|created|configured)\b/i;

export type ArchivistResult = {
  content: string;
  archivedIds: string[];
};

export function compactMessages(
  msgs: ChatMsg[],
  existingNotes: Note[] = [],
): ArchivistResult | null {
  if (!msgs || msgs.length === 0) return null;

  const existingContents = new Set(existingNotes.map((n) => n.content.trim()));
  const userRules: string[] = [];
  const systemDecisions: string[] = [];
  const processedIds: string[] = [];

  for (const m of msgs) {
    if (!m.text) continue;
    processedIds.push(m.id);

    const lines = m.text
      .split(/[\n.!?]+/)
      .map((l) => l.trim())
      .filter(Boolean);

    if (m.role === "user") {
      for (const line of lines) {
        if (RULE_RX.test(line) && line.length > 5) {
          const rule = `- ${line.slice(0, 160)}`;
          if (!userRules.includes(rule)) {
            userRules.push(rule);
          }
        }
      }
    } else if (m.role === "builder") {
      for (const line of lines) {
        if ((DECISION_RX.test(line) || RULE_RX.test(line)) && line.length > 8) {
          const dec = `- ${line.slice(0, 160)}`;
          if (!systemDecisions.includes(dec)) {
            systemDecisions.push(dec);
          }
        }
      }
    }
  }

  const parts: string[] = [];
  if (userRules.length > 0) {
    parts.push("RULES & REQUIREMENTS:\n" + userRules.slice(0, 8).join("\n"));
  }
  if (systemDecisions.length > 0) {
    parts.push("ARCHITECTURE & DECISIONS:\n" + systemDecisions.slice(0, 8).join("\n"));
  }

  if (parts.length === 0) return null;

  const summary = parts.join("\n\n");
  if (existingContents.has(summary.trim())) {
    return null; // Idempotent: already archived
  }

  return {
    content: summary,
    archivedIds: processedIds,
  };
}

// -----------------------------------------------------------------------------
// CLOUD / BACKEND PERSISTENCE WITH CONCURRENCY MUTEX
// -----------------------------------------------------------------------------
async function triggerCloudSync(chat: Chat): Promise<boolean> {
  if (!chat || !chat.id || activeSyncs.has(chat.id)) {
    return false;
  }

  activeSyncs.add(chat.id);
  try {
    const res = await fetch("/api/chats/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: chat.id,
        title: chat.title,
        version: chat.version,
        last_archived_id: chat.lastArchivedId,
        messages: chat.messages.map((m) => ({
          id: m.id,
          role: m.role === "builder" ? "assistant" : "user",
          content: m.text,
          status: m.status || "sent",
          error_message: m.errorMessage,
        })),
      }),
    });

    return res.ok;
  } catch {
    return false;
  } finally {
    activeSyncs.delete(chat.id);
  }
}

// -----------------------------------------------------------------------------
// AUTHENTIC INFERENCE ENGINE INTERACTION
// -----------------------------------------------------------------------------
export type AiChatResponse = {
  message: string;
  provider?: string;
  model?: string;
  duration_seconds?: number;
  execution_steps?: ExecutionStep[];
  coding_loop?: CodingLoopReport;
  task_id?: string;
  task_state?: string;
  task_budget?: Record<string, unknown>;
  sources?: Array<{ title?: string; url?: string; snippet?: string }>;
  god_tier_vfx_learned?: boolean;
  learned_vfx_name?: string;
  status: "success" | "error";
  errorMessage?: string;
};

export type FetchAiOptions = {
  prompt: string;
  history?: ChatMsg[];
  model?: string;
  reasoningLevel?: string;
  attachments?: Attachment[];
  sessionId?: string;
  isTemporary?: boolean;
};

export async function fetchAiFull(options: FetchAiOptions): Promise<AiChatResponse> {
  const {
    prompt,
    history = [],
    model = "llama3.2-local",
    reasoningLevel = "medium",
    attachments = [],
    sessionId,
    isTemporary = false,
  } = options;

  try {
    const res = await fetch("/api/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        model,
        reasoning_level: reasoningLevel,
        session_id: sessionId,
        is_temporary: isTemporary,
        attachments: attachments.map((a) => ({
          name: a.name,
          type: a.type || "file",
        })),
        messages: history
          .filter((m) => m.status !== "error") // Do not pass previous error messages into inference history
          .map((m) => ({
            role: m.role === "builder" ? "assistant" : "user",
            content: m.text,
          })),
      }),
    });

    if (!res.ok) {
      const errText = await res.text().catch(() => "");
      const errorMsg = `Server error HTTP ${res.status}: ${errText || res.statusText}`;
      return {
        message: "",
        status: "error",
        errorMessage: errorMsg,
        execution_steps: [
          {
            name: "Backend Communication",
            detail: errorMsg,
            status: "error",
            type: "general",
          },
        ],
        task_state: "failed",
      };
    }

    const data = await res.json();
    return {
      message:
        data.message || data.reply || (typeof data === "string" ? data : JSON.stringify(data)),
      provider: data.provider,
      model: data.model,
      duration_seconds: data.duration_seconds,
      execution_steps: data.execution_steps || [],
      coding_loop: data.coding_loop,
      task_id: data.task_id,
      task_state: data.task_state || "completed",
      task_budget: data.task_budget,
      sources: data.sources || [],
      god_tier_vfx_learned: data.god_tier_vfx_learned,
      learned_vfx_name: data.learned_vfx_name,
      status: "success",
    };
  } catch (err) {
    const errorMsg = `Connection failure: ${(err as Error).message}. Ensure Stroke FastAPI is running.`;
    return {
      message: "",
      status: "error",
      errorMessage: errorMsg,
      execution_steps: [
        {
          name: "Connection Failure",
          detail: errorMsg,
          status: "error",
          type: "general",
        },
      ],
      task_state: "failed",
    };
  }
}

export async function fetchAiReply(prompt: string, history: ChatMsg[] = []): Promise<string> {
  const res = await fetchAiFull({ prompt, history });
  if (res.status === "error") {
    throw new Error(res.errorMessage || "Inference failed");
  }
  return res.message;
}

// =============================================================================
// BYOK AI PROVIDER CLIENT APIS
// =============================================================================

export interface ProviderStatusInfo {
  provider: string;
  name: string;
  configured: boolean;
  masked_key: string | null;
  base_url: string | null;
  custom_model: string | null;
  format_type: string | null;
  is_local: boolean;
  status_message: string;
  supported_models: string[];
}

export interface ActiveModelConfig {
  active_provider: string;
  active_model: string;
  reasoning_level: string;
  fallback_provider: string | null;
  fallback_model: string | null;
  allow_fallback: boolean;
}

export async function fetchModelProviders(): Promise<ProviderStatusInfo[]> {
  try {
    const res = await fetch("/api/models/providers", { credentials: "omit" });
    if (!res.ok) return [];
    const data = await res.json();
    return data.providers || [];
  } catch {
    return [];
  }
}

export async function saveProviderCredential(payload: {
  provider: string;
  api_key: string;
  base_url?: string;
  model_id?: string;
  format_type?: string;
}): Promise<{ status: string; message: string }> {
  const res = await fetch("/api/models/credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to save API key" }));
    throw new Error(err.detail || "Failed to save API key");
  }
  return await res.json();
}

export async function deleteProviderCredential(provider: string): Promise<void> {
  const res = await fetch(`/api/models/credentials/${encodeURIComponent(provider)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to delete API key" }));
    throw new Error(err.detail || "Failed to delete API key");
  }
}

export async function testProviderConnection(payload: {
  provider: string;
  api_key?: string;
  base_url?: string;
  model_id?: string;
  format_type?: string;
}): Promise<{ success: boolean; message: string; status_code?: number }> {
  const res = await fetch("/api/models/test-connection", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res
    .json()
    .catch(() => ({ success: false, message: "Network error testing connection" }));
  return data;
}

export async function fetchActiveModelConfig(): Promise<ActiveModelConfig | null> {
  try {
    const res = await fetch("/api/models/active", { credentials: "omit" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function saveActiveModelConfig(
  updates: Partial<ActiveModelConfig>,
): Promise<ActiveModelConfig> {
  const res = await fetch("/api/models/active", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to update active model" }));
    throw new Error(err.detail || "Failed to update active model");
  }
  return await res.json();
}

export interface LiveModelInfo {
  id: string;
  name: string;
  provider: string;
  context_length?: number;
  description?: string;
  owned_by?: string;
}

export async function fetchLiveProviderModels(
  provider: string,
  apiKey?: string,
  baseUrl?: string,
): Promise<LiveModelInfo[]> {
  try {
    let res: Response;
    if (apiKey || baseUrl) {
      res = await fetch(`/api/models/live/${encodeURIComponent(provider)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey, base_url: baseUrl }),
      });
    } else {
      res = await fetch(`/api/models/live/${encodeURIComponent(provider)}`, {
        credentials: "omit",
      });
    }
    if (!res.ok) return [];
    const data = await res.json();
    return data.models || [];
  } catch {
    return [];
  }
}

export interface StreamChatCallbacks {
  onStep?: (step: { name: string; detail: string }) => void;
  onThinking?: (delta: string) => void;
  onContent?: (delta: string) => void;
  onError?: (error: string) => void;
  onDone?: (info: { finish_reason: string; provider: string; model: string }) => void;
}

export async function streamAiChat(
  payload: {
    messages: { role: string; content: string }[];
    model?: string;
    reasoning_level?: string;
    temperature?: number;
    attachments?: unknown[];
    task_id?: string;
  },
  callbacks: StreamChatCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/ai/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    callbacks.onError?.(err.detail || "Stream request failed");
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    callbacks.onError?.("No response stream available");
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith(":")) continue;
      if (trimmed.startsWith("data: ")) {
        const raw = trimmed.slice(6).trim();
        if (raw === "[DONE]") {
          return;
        }
        try {
          const parsed = JSON.parse(raw);
          if (parsed.type === "step" && callbacks.onStep) {
            callbacks.onStep(parsed.step);
          } else if (parsed.type === "thinking" && callbacks.onThinking) {
            callbacks.onThinking(parsed.delta);
          } else if (parsed.type === "content" && callbacks.onContent) {
            callbacks.onContent(parsed.delta);
          } else if (parsed.type === "error" && callbacks.onError) {
            callbacks.onError(parsed.error);
          } else if (parsed.type === "done" && callbacks.onDone) {
            callbacks.onDone(parsed);
          }
        } catch {
          // ignore malformed SSE line
        }
      }
    }
  }
}

export type ParallelAgentRole =
  "researcher" | "planner" | "developer" | "tester" | "reviewer" | "debugger" | "orchestrator";
export type ParallelAgentStatus =
  | "idle"
  | "queued"
  | "running"
  | "awaiting_dependency"
  | "completed"
  | "failed"
  | "cancelled"
  | "retrying";

export interface ParallelAgentLogEntry {
  timestamp: number;
  level: string;
  message: string;
  metadata?: Record<string, unknown>;
}

export interface ParallelAgentContextInfo {
  agent_id: string;
  role: ParallelAgentRole;
  name: string;
  status: ParallelAgentStatus;
  status_message: string;
  created_at: number;
  started_at?: number;
  finished_at?: number;
  logs_count: number;
  recent_logs: ParallelAgentLogEntry[];
  owned_files: string[];
  retry_count: number;
  max_retries: number;
  error?: string;
  output_artifacts?: Record<string, unknown>;
}

export interface ParallelAgentJob {
  job_id: string;
  user_goal: string;
  workspace_path: string;
  user_uid: string;
  status: "planned" | "running" | "verifying" | "completed" | "failed" | "cancelled";
  created_at: number;
  updated_at: number;
  completed_at?: number;
  error?: string;
  agents: Record<string, ParallelAgentContextInfo>;
  final_verification?: Record<string, unknown>;
  events_count: number;
  recent_events: Array<{
    job_id: string;
    type: string;
    timestamp: number;
    data: Record<string, unknown>;
  }>;
}

export async function runParallelAgentJob(payload: {
  user_goal: string;
  workspace_path?: string;
  model_id?: string;
  provider_id?: string;
  use_isolated_sandbox?: boolean;
}): Promise<{ status: string; job_id: string; job: ParallelAgentJob }> {
  const res = await fetch("/api/orchestrator/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || "Failed to start parallel agent job");
  }
  return await res.json();
}

export async function listParallelAgentJobs(): Promise<ParallelAgentJob[]> {
  try {
    const res = await fetch("/api/orchestrator/jobs");
    if (!res.ok) return [];
    const data = await res.json();
    return data.jobs || [];
  } catch {
    return [];
  }
}

export async function getParallelAgentJob(jobId: string): Promise<ParallelAgentJob | null> {
  try {
    const res = await fetch(`/api/orchestrator/jobs/${encodeURIComponent(jobId)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function cancelParallelAgentJob(jobId: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/orchestrator/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function streamParallelAgentJob(
  jobId: string,
  onEvent: (event: Record<string, unknown>) => void,
  onDone?: () => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const res = await fetch(`/api/orchestrator/jobs/${encodeURIComponent(jobId)}/stream`, {
      signal,
    });
    if (!res.ok) return;
    const reader = res.body?.getReader();
    if (!reader) return;

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(":")) continue;
        if (trimmed.startsWith("data: ")) {
          const raw = trimmed.slice(6).trim();
          if (raw === "[DONE]") {
            onDone?.();
            return;
          }
          try {
            const parsed = JSON.parse(raw);
            onEvent(parsed);
          } catch {
            // ignore
          }
        }
      }
    }
    onDone?.();
  } catch {
    // network or abort
  }
}
