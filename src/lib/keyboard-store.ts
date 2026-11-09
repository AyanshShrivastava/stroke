// Browser-side simulation of Keyboard's desktop features (cache gate, local chats, storage cap).
export type ChatMsg = { id: string; role: "user" | "builder"; text: string; at: number };
export type Chat = { id: string; title: string; updatedAt: number; messages: ChatMsg[]; archivedUpTo: number };
export type Ingested = { name: string; files: number; bytes: number; map: string; at: number } | null;

export const CACHE_KEY = ".stroke_cache";
const CHATS_KEY = "keyboard.chats";
const INGEST_KEY = "keyboard.ingest";
const GH_KEY = "keyboard.github";
export const STORAGE_CAP_BYTES = 1024 * 1024 * 1024; // 1 GB hard ceiling
export const STORAGE_WARN_RATIO = 0.85;

const isBrowser = () => typeof window !== "undefined";
const uid = () => Math.random().toString(36).slice(2, 10);

export function hasCache() { return isBrowser() && !!localStorage.getItem(CACHE_KEY); }
export function writeCache() {
  localStorage.setItem(CACHE_KEY, JSON.stringify({ v: 1, at: Date.now() }));
}
export function wipeCache() { if (isBrowser()) localStorage.removeItem(CACHE_KEY); }

export function loadChats(): Chat[] {
  if (!isBrowser()) return [];
  try { return JSON.parse(localStorage.getItem(CHATS_KEY) || "[]"); } catch { return []; }
}
export function saveChats(chats: Chat[]) {
  localStorage.setItem(CHATS_KEY, JSON.stringify(chats));
  window.dispatchEvent(new Event("keyboard:chats"));
}
export function getChat(id: string) { return loadChats().find((c) => c.id === id); }
export function createChat(): Chat {
  const chat: Chat = { id: uid(), title: "New chat", updatedAt: Date.now(), messages: [], archivedUpTo: 0 };
  saveChats([chat, ...loadChats()]);
  return chat;
}
export function upsertChat(chat: Chat) {
  const rest = loadChats().filter((c) => c.id !== chat.id);
  saveChats([chat, ...rest]);
}
export function deleteChat(id: string) { saveChats(loadChats().filter((c) => c.id !== id)); }
export const newMsg = (role: ChatMsg["role"], text: string): ChatMsg => ({ id: uid(), role, text, at: Date.now() });

export function loadIngest(): Ingested {
  if (!isBrowser()) return null;
  try { return JSON.parse(localStorage.getItem(INGEST_KEY) || "null"); } catch { return null; }
}
export function saveIngest(i: Ingested) { localStorage.setItem(INGEST_KEY, JSON.stringify(i)); }

export function loadGithub(): { pat: string; repo: string } {
  if (!isBrowser()) return { pat: "", repo: "" };
  try { return JSON.parse(localStorage.getItem(GH_KEY) || '{"pat":"","repo":""}'); } catch { return { pat: "", repo: "" }; }
}
export function saveGithub(v: { pat: string; repo: string }) { localStorage.setItem(GH_KEY, JSON.stringify(v)); }

export function localBytes(): number {
  if (!isBrowser()) return 0;
  let n = 0;
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i)!;
    n += (k.length + (localStorage.getItem(k)?.length ?? 0)) * 2;
  }
  return n;
}
export function storageStatus(bytes: number) {
  const ratio = bytes / STORAGE_CAP_BYTES;
  return { ratio, warn: ratio >= STORAGE_WARN_RATIO, full: ratio >= 1 };
}
export function formatBytes(b: number) {
  if (b < 1024) return `${b} B`;
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  return `${(b / 1024 ** 3).toFixed(2)} GB`;
}

// Archivist: extract rules / decisions / changes from new messages.
const RULE_RX = /\b(always|never|must|don't|do not|should|rule|prefer|use)\b/i;
export function compactMessages(msgs: ChatMsg[]): string | null {
  const userLines = msgs.filter((m) => m.role === "user").flatMap((m) => m.text.split(/[\n.!?]+/)).map((l) => l.trim()).filter(Boolean);
  if (!userLines.length) return null;
  const rules = userLines.filter((l) => RULE_RX.test(l));
  const rest = userLines.filter((l) => !RULE_RX.test(l));
  const parts: string[] = [];
  if (rules.length) parts.push("RULES:\n" + rules.map((r) => `- ${r.slice(0, 160)}`).join("\n"));
  if (rest.length) parts.push("CHANGES:\n" + rest.slice(0, 6).map((r) => `- ${r.slice(0, 120)}`).join("\n"));
  return parts.join("\n\n");
}

// Authentic Stroke AI communication to Python FastAPI backend
export async function fetchAiReply(prompt: string, history: ChatMsg[] = []): Promise<string> {
  try {
    const res = await fetch("/api/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        messages: history.map((m) => ({ role: m.role === "builder" ? "assistant" : "user", content: m.text }))
      })
    });
    if (!res.ok) {
      return `[Stroke AI Error: HTTP ${res.status}] Failed to obtain inference from local neural model.`;
    }
    const data = await res.json();
    return data.message || data.reply || (typeof data === "string" ? data : JSON.stringify(data));
  } catch (err) {
    return `[Stroke AI Offline] Could not reach backend engine (${(err as Error).message}). Ensure the Python FastAPI server is running.`;
  }
}

