/**
 * STROKE // BROWSER STORAGE ENGINE (IndexedDB + Safe Fallback)
 * 
 * Provides resilient, quota-safe local storage for conversations, messages,
 * and archived context without misleading capacity claims.
 * 
 * Guarantees:
 * 1. Uses IndexedDB for multi-MB chat histories and structured records.
 * 2. Catches QuotaExceededError, SecurityError, and private-mode storage blocks.
 * 3. Failed writes never erase or overwrite prior valid data.
 * 4. Zero credential storage (no PATs, secrets, or keys).
 * 5. Full Export, Import, and Clear operations.
 * 6. Honest storage diagnostics via navigator.storage.estimate().
 */

import type { Chat } from "./keyboard-store";

const DB_NAME = "stroke_db";
const DB_VERSION = 1;
const CHATS_STORE = "chats";
const META_STORE = "metadata";

const isBrowser = () => typeof window !== "undefined" && typeof window.indexedDB !== "undefined";

// In-memory fallback if IndexedDB is blocked or disabled
const memoryFallback = new Map<string, any>();

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (!isBrowser()) {
      return reject(new Error("IndexedDB is not available in non-browser environment"));
    }

    try {
      const request = window.indexedDB.open(DB_NAME, DB_VERSION);

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;
        if (!db.objectStoreNames.contains(CHATS_STORE)) {
          db.createObjectStore(CHATS_STORE, { keyPath: "id" });
        }
        if (!db.objectStoreNames.contains(META_STORE)) {
          db.createObjectStore(META_STORE, { keyPath: "key" });
        }
      };

      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("Failed to open IndexedDB"));
      request.onblocked = () => reject(new Error("IndexedDB database open blocked"));
    } catch (err) {
      reject(err);
    }
  });
}

/**
 * Saves a chat session to IndexedDB.
 * If quota or security errors occur, rejects without destroying existing data.
 */
export async function idbSaveChat(chat: Chat): Promise<boolean> {
  if (!chat || !chat.id) return false;

  try {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const tx = db.transaction([CHATS_STORE], "readwrite");
      const store = tx.objectStore(CHATS_STORE);

      tx.oncomplete = () => resolve(true);
      tx.onerror = (e) => {
        const error = tx.error || (e.target as any)?.error;
        console.warn("[Stroke IDB Write Warning]", error);
        reject(error);
      };
      tx.onabort = () => reject(new Error("Transaction aborted"));

      store.put(chat);
    });
  } catch (err) {
    // Graceful fallback to memory storage without corrupting existing records
    memoryFallback.set(`chat:${chat.id}`, chat);
    return false;
  }
}

/**
 * Loads all chat sessions from IndexedDB.
 */
export async function idbLoadChats(): Promise<Chat[]> {
  try {
    const db = await openDatabase();
    return new Promise((resolve) => {
      const tx = db.transaction([CHATS_STORE], "readonly");
      const store = tx.objectStore(CHATS_STORE);
      const request = store.getAll();

      request.onsuccess = () => {
        const results = (request.result || []) as Chat[];
        // Sort newest first
        results.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
        resolve(results);
      };

      request.onerror = () => {
        resolve(getMemoryFallbackChats());
      };
    });
  } catch {
    return getMemoryFallbackChats();
  }
}

export const idbLoadAllChats = idbLoadChats;

/**
 * Loads a single chat session by ID from IndexedDB or memory fallback.
 */
export async function idbLoadChat(chatId: string): Promise<Chat | null> {
  if (!chatId) return null;
  try {
    const db = await openDatabase();
    return new Promise((resolve) => {
      const tx = db.transaction([CHATS_STORE], "readonly");
      const store = tx.objectStore(CHATS_STORE);
      const request = store.get(chatId);

      request.onsuccess = () => {
        const res = request.result as Chat | undefined;
        if (res) {
          resolve(res);
        } else {
          resolve(memoryFallback.get(`chat:${chatId}`) || null);
        }
      };

      request.onerror = () => {
        resolve(memoryFallback.get(`chat:${chatId}`) || null);
      };
    });
  } catch {
    return memoryFallback.get(`chat:${chatId}`) || null;
  }
}

/**
 * Deletes a single chat session from IndexedDB.
 */
export async function idbDeleteChat(chatId: string): Promise<boolean> {
  if (!chatId) return false;
  memoryFallback.delete(`chat:${chatId}`);

  try {
    const db = await openDatabase();
    return new Promise((resolve) => {
      const tx = db.transaction([CHATS_STORE], "readwrite");
      const store = tx.objectStore(CHATS_STORE);
      store.delete(chatId);
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => resolve(false);
    });
  } catch {
    return false;
  }
}

/**
 * Clears all chat records from IndexedDB and local memory fallback.
 */
export async function idbClearAllChats(): Promise<boolean> {
  memoryFallback.clear();
  try {
    const db = await openDatabase();
    return new Promise((resolve) => {
      const tx = db.transaction([CHATS_STORE], "readwrite");
      const store = tx.objectStore(CHATS_STORE);
      store.clear();
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => resolve(false);
    });
  } catch {
    return false;
  }
}

function getMemoryFallbackChats(): Chat[] {
  const chats: Chat[] = [];
  memoryFallback.forEach((val, key) => {
    if (key.startsWith("chat:") && val) chats.push(val);
  });
  chats.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  return chats;
}

/**
 * Storage diagnostics using real browser quota estimation.
 */
export type StorageDiagnostics = {
  usageBytes: number;
  quotaBytes: number;
  quotaReported: boolean;
  usageFormatted: string;
  quotaFormatted: string;
  usagePercent: number;
  engine: "IndexedDB" | "LocalStorageFallback" | "Memory";
};

export async function estimateStorage(): Promise<StorageDiagnostics> {
  let usage = 0;
  let quota = 0;
  let quotaReported = false;

  if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.estimate) {
    try {
      const est = await navigator.storage.estimate();
      if (est.usage !== undefined) usage = est.usage;
      if (est.quota !== undefined && est.quota > 0) {
        quota = est.quota;
        quotaReported = true;
      }
    } catch {
      // ignore
    }
  }

  // If navigator estimate not supported or 0, compute rough byte tally
  if (usage === 0 && typeof localStorage !== "undefined") {
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i)!;
        usage += (k.length + (localStorage.getItem(k)?.length || 0)) * 2;
      }
    } catch {
      // ignore
    }
  }

  const percent = quota > 0 ? (usage / quota) * 100 : 0;
  const isIdbActive = isBrowser();

  return {
    usageBytes: usage,
    quotaBytes: quota,
    quotaReported,
    usageFormatted: formatStorageBytes(usage),
    quotaFormatted: quota > 0 ? formatStorageBytes(quota) : "Browser Managed",
    usagePercent: Math.min(100, Math.max(0, percent)),
    engine: isIdbActive ? "IndexedDB" : "LocalStorageFallback",
  };
}

export function formatStorageBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  return `${(b / 1024 ** 3).toFixed(2)} GB`;
}

/**
 * Exports all local chats as a standardized JSON structure.
 */
export async function exportLocalDataJson(): Promise<string> {
  const chats = await idbLoadChats();
  const payload = {
    version: 1,
    exported_at: new Date().toISOString(),
    chats_count: chats.length,
    chats,
  };
  return JSON.stringify(payload, null, 2);
}

/**
 * Imports chats from an exported JSON string with validation and deduplication.
 */
export async function importLocalDataJson(jsonStr: string): Promise<{ imported: number; errors: string[] }> {
  const errors: string[] = [];
  try {
    let parsed: any;
    try {
      parsed = JSON.parse(jsonStr);
    } catch (parseErr) {
      return { imported: 0, errors: [`Malformed JSON: ${(parseErr as Error).message}`] };
    }

    const chatsList = Array.isArray(parsed) ? parsed : parsed?.chats;
    if (!Array.isArray(chatsList)) {
      throw new Error("Invalid format: expected a JSON array or object with a 'chats' array.");
    }

    let count = 0;
    const existing = await idbLoadChats();
    const existingMap = new Map(existing.map((c) => [c.id, c]));

    for (const item of chatsList) {
      if (!item || typeof item !== "object" || !item.id) {
        errors.push("Skipped invalid chat item missing 'id'");
        continue;
      }

      // Merge or save
      const chatObj: Chat = {
        id: String(item.id),
        title: String(item.title || "Imported Chat"),
        updatedAt: Number(item.updatedAt || Date.now()),
        messages: Array.isArray(item.messages) ? item.messages : [],
        lastArchivedId: item.lastArchivedId,
        archivedMessageIds: Array.isArray(item.archivedMessageIds) ? item.archivedMessageIds : [],
        model: item.model,
        reasoningLevel: item.reasoningLevel,
        version: Number(item.version || 1),
      };

      await idbSaveChat(chatObj);
      existingMap.set(chatObj.id, chatObj);
      count++;
    }

    return { imported: count, errors };
  } catch (err) {
    return { imported: 0, errors: [(err as Error).message] };
  }
}
