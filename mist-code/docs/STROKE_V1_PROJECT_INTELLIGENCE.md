# STROKE V1 — PROJECT INTELLIGENCE & MULTIMODAL UNDERSTANDING

## 1. Architectural Overview

Stroke V1 introduces a resilient project intelligence pipeline that ingests actual approved workspace contents and retrieves targeted, symbol-aware context without prompt flooding. Concurrently, the multimodal vision pipeline replaces legacy synthetic scene fallbacks with truthful capability gating and genuine vision model inference.

```
                                      +------------------------------------+
                                      |        User Request / Prompt       |
                                      +-----------------+------------------+
                                                        |
                                                        v
+-------------------------------------------------------+-------------------------------------------------------+
|                                              Stroke Backend (FastAPI)                                         |
|                                                                                                               |
|  +-------------------------------------------------+     +-------------------------------------------------+  |
|  |     Project Context Index (project_context)     |     |       Multimodal Handler (multimodal_service)   |  |
|  |                                                 |     |                                                 |  |
|  |  - Ingests actual file bytes (not metadata)     |     |  - Multi-image iteration (processes all assets) |  |
|  |  - Luau function, type, and service extractor   |     |  - Strict MIME (PNG, JPEG, WEBP, GIF)           |  |
|  |  - Roblox XML (.rbxmx/.rbxlx) instance parser   |     |  - Decompression bomb guard (MAX_IMAGE_PIXELS)  |  |
|  |  - Incremental SHA-256 hash tracking            |     |  - Capability Gating: Checks 'image' modality   |  |
|  |  - Strict secret & .gitignore exclusion filter  |     |  - Honest unsupported status (No canned house!) |  |
|  |  - Targeted BM25 & symbol retrieval scoring     |     |  - Genuine vision inference dispatch            |  |
|  +------------------------+------------------------+     +------------------------+------------------------+  |
|                           |                                                       |                           |
+---------------------------+-------------------------------------------------------+---------------------------+
                            |                                                       |
                            v                                                       v
            Targeted Context Snippets Injected                      Truthful Multi-Image Analysis Injected
                            |                                                       |
                            +---------------------------+---------------------------+
                                                        |
                                                        v
                                          +---------------------------+
                                          |   Sliding Window Prompt   |
                                          |     (No Starvation)       |
                                          +---------------------------+
```

---

## 2. Project Ingestion & Context Indexing Pipeline

### 2.1 File Ingestion vs. Metadata Counting
- **Actual Content Ingestion**: The index reads real file contents and computes cryptographic SHA-256 hashes. Stroke never counts file paths or byte sizes alone as context ingestion.
- **Hierarchy Preservation**: All files retain their canonical workspace-relative paths (e.g. `src/server/CombatService.server.luau`, `ReplicatedStorage/Modules/Hitbox.luau`, `default.project.json`).

### 2.2 Supported Languages & Formats
1. **Luau / Lua (`.luau`, `.lua`)**:
   - Classifies script roles automatically: `ServerScript` (`.server.luau`), `LocalScript` (`.client.luau`), and `ModuleScript` (`.luau`).
   - Extracts structured symbol signatures: functions (`function Class.method(...)`), exported/local types (`type DamagePacket = ...`), Roblox services (`game:GetService('Players')`), and module exports.
2. **Roblox XML Formats (`.rbxmx`, `.rbxlx`)**:
   - Parses XML trees using `xml.etree.ElementTree`.
   - Extracts instance hierarchies: `Model`, `Part`, `Folder`, `Script`, `LocalScript`, and `ModuleScript`.
   - Decodes embedded `<ProtectedString name="Source">` blocks and extracts symbols from embedded scripts.
3. **Project Metadata & Configurations**:
   - `default.project.json`, `rojo.json`: Rojo DataModel tree mappings.
   - `wally.toml`: Wally package dependencies and registries.
   - `aftman.toml`, `selene.toml`, `stylua.toml`: Tool configurations.
   - `package.json`, `tsconfig.json`: Web and tooling manifests.
4. **Documentation**:
   - `.md`, `.txt`, `.json`, `.toml`, `.yaml`, `.yml`.

### 2.3 Limits & Safety Defenses
- **Per-File Limit**: Maximum 1,048,576 bytes (1 MB) per file. Oversized files are skipped individually with reason `oversized_file`.
- **Total Index Capacity**: Capped at 25 MB total index bytes to avoid memory exhaustion.
- **File Count Limit**: Maximum 1,000 files per workspace index.
- **Job Timeout**: 30.0-second execution ceiling to avoid thread hanging.
- **Resilient Fault Isolation**: Corrupt binary files, malformed XML, unreadable files, and oversized files are logged and skipped individually without aborting the broader indexing job.

### 2.4 Secret Exclusion & Gitignore Respect
- **`.gitignore` Rules**: Parsed from the workspace root and respected across all nested directories.
- **Default Excluded Directories**: `.git`, `.svn`, `node_modules`, `venv`, `.venv`, `__pycache__`, `.output`, `.nitro`, `dist`, `build`.
- **Secret Filename Patterns**: Rejects `.env`, `.env.*`, `*token*`, `*secret*`, `*credential*`, `*id_rsa*`, `*id_ed25519*`, `*.pem`, `*.key`, `*.pfx`, `*.p12`, `.vault_key`.
- **Sensitive Content Scanning**: Scans initial bytes of every file for private keys (`-----BEGIN RSA PRIVATE KEY-----`), GitHub PATs (`ghp_`), API keys (`sk-`), and JWTs (`eyJhbGciOi`). Flagged files are excluded with reason `secret_or_credential`.

### 2.5 Incremental Indexing Engine
- Each indexed file record stores: `relative_path`, `content_hash`, `size_bytes`, `modified_at`, `file_type`, `symbols`, `summary`, and `content`.
- **Unchanged Files**: Content hash match skips re-reading and re-parsing.
- **Modified Files**: Re-scanned and symbols updated.
- **Deleted Files**: Automatically pruned from the index.
- **Persistence**: Persisted to `paths_service.get_app_data_dir() / "project_context_index.json"` and synchronized to `data/verified_project_context.json`.

### 2.6 Targeted BM25 & Symbol Retrieval
- Rather than dumping entire repositories into every prompt (which starves small context windows like Llama 3.2 1B), queries are tokenized and scored using BM25 frequency with heavy symbol and path boosts:
  - Exact symbol match (`function`, `type`, `class`): +8.0 boost
  - Path / filename match: +5.0 boost
  - Term frequency: Logarithmic term frequency scoring
- Extracts the top 3–5 most relevant sections (capped at 12,000 characters) and injects them into the prompt with file and symbol attribution.
- Lexical search remains the reliable fallback; embedding similarity is only reported when an actual embedding model is queried.

---

## 3. Multimodal & Vision Understanding Pipeline

### 3.1 Hardened Image Decompression & Validation
- **Pillow Decompression Bomb Defense**: Enforces `Image.MAX_IMAGE_PIXELS = 25_000_000` to prevent memory exhaustion from malicious high-dimension images.
- **File Size Limits**: Maximum 10 MB per image, 25 MB total across all attachments.
- **MIME Enforcement**: Strictly validates `image/png`, `image/jpeg`, `image/webp`, and `image/gif`.
- **Safe Base64 Decoding**: Handles raw Base64 and data URLs (`data:image/png;base64,...`) safely.

### 3.2 Capability Gating & Truthful Reporting
- Ingesting models are verified against `MODEL_REGISTRY[model_id].input_modalities`.
- **Text-Only Models (e.g. Llama 3.2 1B)**:
  - Returns honest `status: "unsupported"`.
  - Reports truthful technical file metadata (dimensions, format, byte size).
  - Explains model limitations and lists supported modalities (`['text']`).
  - **Zero Canned Hallucinations**: Stroke completely removes the legacy hardcoded Roblox-house description ("Modular House... crimson slate roof... 3D Viewport").
- **Vision-Capable Models (e.g. GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Flash)**:
  - Formats image URLs and prompts for real multimodal inference.
  - Returns model-generated visual reasoning.

### 3.3 Multi-Image Attachment Processing
- Iterates through **every** attached image, analyzing each individually rather than only the first attachment.

### 3.4 Static Screenshot Disclaimer
- Vision responses explicitly disclaim:
  > *"Visual screenshot analysis represents static 2D pixels and does not reflect live Roblox Studio runtime DataModel inspection."*

---

## 4. API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/project/index` / `/api/project/index` | `POST` | Triggers incremental scan and indexing of approved workspace directory. |
| `/project/index/status` / `/api/project/index/status` | `GET` | Returns file count, total bytes, workspace path, and last index timestamp. |
| `/project/search` / `/api/project/search` | `POST` | Queries index via BM25 and symbol ranking; returns relevant snippets. |
| `/project/index` / `/api/project/index` | `DELETE`| Clears the current project context index. |
| `/ai/chat` / `/api/ai/chat` | `POST` | Enriched with multi-image vision analysis and targeted project context injection. |

---

## 5. Verification Gate Results

- **`test_project_context_and_multimodal.py`**: **10/10 PASS** (100%):
  1. `test_01_nested_roblox_project_indexing_and_symbols`: Rojo config, ServerScript, ModuleScript, and .rbxmx XML model indexing.
  2. `test_02_incremental_indexing_modifications_and_deletions`: Hash-based tracking of added, modified, unchanged, and deleted files.
  3. `test_03_secrets_and_gitignore_strict_exclusion`: .env, tokens, RSA keys, and gitignore directories excluded.
  4. `test_04_binary_malformed_and_oversized_file_resilience`: Binary files, malformed XML, and oversized files skipped individually with exact skip reasons.
  5. `test_05_targeted_retrieval_and_chat_prompt_injection`: BM25 and symbol-boosted retrieval of relevant code snippets.
  6. `test_06_text_only_model_returns_honest_unsupported_not_canned_house`: Text-only models return honest unsupported notice without canned house claims.
  7. `test_07_decompression_bomb_rejection`: Rejection of excessive pixel dimensions.
  8. `test_08_multi_image_attachments_all_analyzed`: Multi-image attachments all analyzed individually.
  9. `test_09_vision_capable_model_dispatches_genuine_inference`: Genuine vision inference dispatch on vision-capable models.
  10. `test_10_project_intelligence_api_endpoints`: Authenticated FastAPI endpoints for index, status, search, and clear.
- **Frontend Build**: `npm run build` compiled cleanly in 142ms.
- **Regression Suites**: All 105+ existing tests pass with zero regressions.
