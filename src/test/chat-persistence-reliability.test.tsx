import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  compactMessages,
  fetchAiFull,
  type ChatMsg,
  type Chat,
  type Note,
} from "@/lib/keyboard-store";
import {
  idbSaveChat,
  idbLoadChat,
  idbLoadAllChats,
  idbDeleteChat,
  idbClearAllChats,
  exportLocalDataJson,
  importLocalDataJson,
  estimateStorage,
} from "@/lib/idb-storage";

describe("Chat Persistence & Local Data Reliability", () => {
  beforeEach(async () => {
    localStorage.clear();
    await idbClearAllChats();
    vi.restoreAllMocks();
  });

  describe("Archivist & compactMessages", () => {
    it("extracts constraints from user messages and architecture decisions from builder messages", () => {
      const messages: ChatMsg[] = [
        {
          id: "msg-1",
          role: "user",
          text: "Always use strict Luau type annotations and require server validation for spells.",
          at: Date.now(),
          seq: 1,
        },
        {
          id: "msg-2",
          role: "builder",
          text: "Architecture pattern: spells are configured via ModuleScript and validated on server before execution.",
          at: Date.now(),
          seq: 2,
        },
        {
          id: "msg-3",
          role: "user",
          text: "Do not use deprecated SpawnLocation or wait() builtins.",
          at: Date.now(),
          seq: 3,
        },
      ];

      const res = compactMessages(messages);
      expect(res).not.toBeNull();
      expect(res?.archivedIds).toEqual(["msg-1", "msg-2", "msg-3"]);

      // Verify user rule extraction
      expect(res?.content).toContain("RULES & REQUIREMENTS");
      expect(res?.content.toLowerCase()).toContain("strict luau");

      // Verify builder architecture pattern extraction
      expect(res?.content).toContain("ARCHITECTURE & DECISIONS");
      expect(res?.content.toLowerCase()).toContain("spells are configured");
    });

    it("is idempotent and avoids duplicate notes when re-processing previously archived messages", () => {
      const messages: ChatMsg[] = [
        {
          id: "msg-1",
          role: "user",
          text: "Always use ReplicatedStorage for shared client-server contracts.",
          at: Date.now(),
          seq: 1,
        },
      ];

      const run1 = compactMessages(messages);
      expect(run1).not.toBeNull();
      const existingNote: Note = { id: "n1", content: run1!.content, at: Date.now() };

      // Running again with existing note content should return null (idempotent duplicate prevention)
      const run2 = compactMessages(messages, [existingNote]);
      expect(run2).toBeNull();
    });

    it("handles empty or irrelevant messages without creating false notes", () => {
      const messages: ChatMsg[] = [
        {
          id: "msg-hello",
          role: "user",
          text: "hi",
          at: Date.now(),
        },
      ];

      const result = compactMessages(messages);
      expect(result).toBeNull();
    });
  });

  describe("API Error Handling in fetchAiFull", () => {
    it("returns status: 'error' without converting HTTP 500 into normal assistant content", async () => {
      const fakeFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: async () => JSON.stringify({ detail: "AI provider quota exceeded or model offline" }),
      });
      globalThis.fetch = fakeFetch as unknown as typeof fetch;

      const result = await fetchAiFull({
        prompt: "Create a fireball effect",
        sessionId: "test-chat-1",
      });

      expect(result.status).toBe("error");
      expect(result.errorMessage).toContain("quota exceeded");
      // Must not generate an ordinary fake builder response
      expect(result.message).toBe("");
    });

    it("returns status: 'error' on network throw or connection drop", async () => {
      const fakeFetch = vi.fn().mockRejectedValue(new Error("Network connection refused"));
      globalThis.fetch = fakeFetch as unknown as typeof fetch;

      const result = await fetchAiFull({
        prompt: "Ping",
        sessionId: "test-chat-2",
      });

      expect(result.status).toBe("error");
      expect(result.errorMessage).toContain("Network connection refused");
    });
  });

  describe("Local Persistence & Portability (IDB / Export / Import)", () => {
    it("saves and retrieves full chat sessions with version and durable cursor", async () => {
      const sampleChat: Chat = {
        id: "chat-101",
        title: "Combat VFX System",
        createdAt: Date.now(),
        updatedAt: Date.now(),
        version: 1,
        lastArchivedId: "msg-1",
        archivedMessageIds: ["msg-1"],
        notes: [{ id: "n1", content: "Client-side prediction only for movement", at: Date.now() }],
        messages: [
          {
            id: "msg-1",
            role: "user",
            text: "How do we handle replication?",
            at: Date.now(),
            status: "sent",
            seq: 1,
          },
          {
            id: "msg-2",
            role: "builder",
            text: "Use RemoteEvents with rate limiting.",
            at: Date.now(),
            status: "sent",
            seq: 2,
          },
        ],
      };

      await idbSaveChat(sampleChat);
      const retrieved = await idbLoadChat("chat-101");

      expect(retrieved).not.toBeNull();
      expect(retrieved?.id).toBe("chat-101");
      expect(retrieved?.version).toBe(1);
      expect(retrieved?.lastArchivedId).toBe("msg-1");
      expect(retrieved?.messages.length).toBe(2);
      expect(retrieved?.notes?.length).toBe(1);
    });

    it("exports all stored sessions and imports them back safely", async () => {
      const chatA: Chat = {
        id: "chat-a",
        title: "Session A",
        createdAt: 1000,
        updatedAt: 1000,
        version: 1,
        messages: [{ id: "m-a", role: "user", text: "Prompt A", at: 1000, status: "sent" }],
      };
      const chatB: Chat = {
        id: "chat-b",
        title: "Session B",
        createdAt: 2000,
        updatedAt: 2000,
        version: 1,
        messages: [{ id: "m-b", role: "user", text: "Prompt B", at: 2000, status: "sent" }],
      };

      await idbSaveChat(chatA);
      await idbSaveChat(chatB);

      const exportedJson = await exportLocalDataJson();
      expect(exportedJson).toContain('"version": 1');
      expect(exportedJson).toContain('"chat-a"');
      expect(exportedJson).toContain('"chat-b"');

      // Clear local database
      await idbClearAllChats();
      const emptyChats = await idbLoadAllChats();
      expect(emptyChats.length).toBe(0);

      // Re-import
      const importRes = await importLocalDataJson(exportedJson);
      expect(importRes.imported).toBe(2);
      expect(importRes.errors.length).toBe(0);

      const restoredChats = await idbLoadAllChats();
      expect(restoredChats.length).toBe(2);
      expect(restoredChats.map((c) => c.id).sort()).toEqual(["chat-a", "chat-b"]);
    });

    it("rejects malformed or unverified JSON payloads on import", async () => {
      const invalidJson = '{"version": 1, "chats": "not an array"}';
      const res = await importLocalDataJson(invalidJson);
      expect(res.imported).toBe(0);
      expect(res.errors.length).toBeGreaterThan(0);
      expect(res.errors[0].toLowerCase()).toContain("chats");

      const brokenJson = "{not-json}";
      const brokenRes = await importLocalDataJson(brokenJson);
      expect(brokenRes.imported).toBe(0);
      expect(brokenRes.errors[0]).toContain("Malformed JSON");
    });

    it("deletes individual chats and clears all data cleanly", async () => {
      const c1: Chat = { id: "c1", title: "C1", createdAt: 1, updatedAt: 1, messages: [] };
      const c2: Chat = { id: "c2", title: "C2", createdAt: 2, updatedAt: 2, messages: [] };

      await idbSaveChat(c1);
      await idbSaveChat(c2);

      await idbDeleteChat("c1");
      const loadedC1 = await idbLoadChat("c1");
      expect(loadedC1).toBeNull();

      const remaining = await idbLoadAllChats();
      expect(remaining.length).toBe(1);
      expect(remaining[0].id).toBe("c2");

      await idbClearAllChats();
      const allCleared = await idbLoadAllChats();
      expect(allCleared.length).toBe(0);
    });

    it("provides storage diagnostics without asserting a fake 1 GB ceiling", async () => {
      const diag = await estimateStorage();
      expect(diag.engine).toBeDefined();
      expect(diag.usageFormatted).toBeDefined();
      expect(diag.quotaFormatted).toBeDefined();
      expect(typeof diag.usageBytes).toBe("number");
      expect(typeof diag.quotaBytes).toBe("number");
    });
  });
});
