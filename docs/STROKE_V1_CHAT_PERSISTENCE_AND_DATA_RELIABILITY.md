# STROKE V1 — CHAT PERSISTENCE AND LOCAL DATA RELIABILITY SPECIFICATION

## Overview
This document outlines the architectural changes, data contracts, and verification gates implemented for **Stroke V1 Chat Persistence and Local Data Reliability**.

---

## 1. Chat & Archivist Lifecycle Reliability

### 1.1 Dual-Role Continuous Context Archival
- **Previous limitation**: The system only extracted rules from a narrow subset of messages and missed builder decisions.
- **V1 Implementation**:
  - `compactMessages(msgs, existingNotes)` extracts constraints, user preferences, and negative rules from `user` messages (matching `RULE_RX`), and architectural patterns, framework decisions, and verified schemas from `builder` messages (matching `DECISION_RX` and `RULE_RX`).
  - Summaries are grouped under `RULES & REQUIREMENTS` and `ARCHITECTURE & DECISIONS`.

### 1.2 Stable Message ID Cursor & Idempotent Sync
- **Previous limitation**: An index-based `archivedUpTo: number` failed if messages were inserted, re-ordered, or streamed concurrently.
- **V1 Implementation**:
  - Replaced index slicing with stable message IDs: `lastArchivedId?: string` and `archivedMessageIds?: string[]`.
  - Idempotent deduplication: Previously processed message IDs and identical note hashes are skipped during archival cycles.
  - Concurrency lock: `syncInProgressRef` (frontend) and `_local_chats_lock` (backend) prevent overlapping concurrent syncs from clobbering state.
  - Monotonic versioning: Every chat mutation increments `version: number`. Optimistic concurrency on the backend merges new messages rather than letting stale responses overwrite newer messages.

### 1.3 Honest Message Status & Dedicated Error Flow
- **Previous limitation**: `fetchAiReply()` caught HTTP 500 errors and wrapped them as ordinary builder responses (`[Stroke AI Error: ...]`). This polluted the chat history and poisoned continuous learning.
- **V1 Implementation**:
  - `fetchAiFull()` returns `{ status: "error", errorMessage: string }`.
  - The chat interface records a dedicated message with `status: "error"`.
  - The UI renders an error card with details, retry button, and links, without ever creating fake assistant responses.
  - Local history is never trimmed before durability is confirmed.

---

## 2. Browser Storage & IndexedDB Engine

### 2.1 Removed Fake 1 GB Ceiling
- **Previous limitation**: The application hardcoded a claim of a guaranteed 1 GB `localStorage` ceiling (`STORAGE_CAP_BYTES = 1024 * 1024 * 1024`). Most browsers limit `localStorage` to 5–10 MB, causing sudden `QuotaExceededError` write crashes.
- **V1 Implementation**:
  - Created `src/lib/idb-storage.ts` using native IndexedDB (`stroke_db`) for chat sessions and metadata.
  - Added real quota reporting via `navigator.storage.estimate()`.
  - UI displays honest metrics: engine type (`IndexedDB`), used bytes, browser quota, and percent utilized.

### 2.2 Quota Safety & Non-Destructive Fallbacks
- All read and write operations wrap transactions with error handling.
- If storage quota is exceeded or storage is disabled (e.g., restrictive private windows), writes fall back gracefully to safe in-memory storage without corrupting or deleting existing valid records.
- Zero credentials: GitHub PATs, Firebase credentials, and API keys are strictly excluded from browser storage.

### 2.3 Portability: Export, Import & Clear
- **Export**: Generates structured, versioned JSON (`exportLocalDataJson()`) containing full sessions, timestamps, versions, and durable cursors.
- **Import**: Validates JSON schema (`importLocalDataJson()`), sanitizes incoming sessions, and merges them safely without data loss.
- **Clear**: User-controlled, confirmed complete deletion (`idbClearAllChats()` and `/api/chats/{id}`).

---

## 3. Runtime Data Locations & Packaged Bundle Safety

### 3.1 Single Path Authority (`paths_service.py`)
- Runtime state is strictly routed to user-level application data:
  - **macOS**: `~/Library/Application Support/Stroke/`
  - **Windows**: `%LOCALAPPDATA%\Stroke\`
  - **Linux**: `~/.local/share/Stroke/`
  - **Override**: Honors `STROKE_APP_DATA` / `STROKE_DATA_DIR`.
- All runtime data files are routed here:
  - User chats: `paths_service.get_user_chats_path()` (`local_chat_sessions.json`)
  - MCP configuration: `paths_service.get_mcp_config_path()` (`mcp_servers.json`)
  - Legacy MCP: `paths_service.get_legacy_mcp_config_path()` (`mcp_config.json`)
  - Verified project context: `paths_service.get_verified_project_context_path()` (`verified_project_context.json`)
  - Local Firestore DB: `paths_service.get_local_firestore_db_path()` (`local_firestore_db.json`)
  - VFX dataset: `paths_service.get_vfx_dir()` (`vfx/`)

### 3.2 Read-Only Application Bundle Safety
- When packaged as an installer or desktop bundle (e.g. `/Applications/Stroke.app` or `C:\Program Files\Stroke`), the application bundle is read-only.
- All write operations use `paths_service.atomic_write_json()` directed exclusively to user application-data paths, ensuring zero `PermissionError` failures during packaged runtime execution.
- Source directories and repository data folders are never written to at runtime.
- Legacy files from previous versions are seamlessly migrated to user application data via `paths_service.migrate_legacy_data()` on startup.

---

## 4. Verification & Test Coverage

| Test Module | Coverage | Status |
| :--- | :--- | :--- |
| `src/test/chat-persistence-reliability.test.tsx` | Archivist rule extraction (user & builder), idempotent deduplication, HTTP 500 error status, IndexedDB save/load, export/import roundtrip, storage diagnostics. | **PASS (10/10)** |
| `src/test/theme-and-activity.test.tsx` | UI theme switching, activity indicator, and minimalist layout components. | **PASS (6/6)** |
| `src/test/app-routing.test.tsx` | App routes and TanStack start setup. | **PASS (1/1) |
| `test_chat_persistence_and_runtime_data.py` | `paths_service` env overrides, legacy data migration, read-only bundle simulation, multithreaded concurrent atomic chat saves, optimistic concurrency version merge, chat deletion. | **PASS (8/8)** |
| Full backend regression suite (`test_*.py`) | Filesystem safety, MCP security, project context, terminal lifecycle, AI providers, VFX registry, OAuth/GitHub vault, and coding loop. | **PASS (199/199)** |
