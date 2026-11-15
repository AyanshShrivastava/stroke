# STROKE V1 — VFX Knowledge Registry & Telemetry Specification

## 1. Overview
The **Stroke V1 VFX Knowledge Registry** ingests domain knowledge from the Elemental Worlds dataset (`vfx_data.json` & `vfx_dump.txt`) and synthesizes top-tier VFX engineering parameters across five sequential feeding cycles. It also continuously distills user-approved chat interactions into knowledge patterns to improve prompt context through genuine **Retrieval-Augmented Generation (RAG)**.

---

## 2. Strict Data Correctness & Integrity Architecture

### 2.1 Seeded Reference Patterns vs. User-Derived Learnings
- **Seeded Insights**: Static domain references in `DEFAULT_SEEDED_INSIGHTS` are explicitly flagged with `source_type="seeded"`.
- **User-Derived Insights**: Insights distilled from user prompts and model responses are flagged with `source_type="user_derived"`.
- **Honest Metrics**: Seeded insights **never** increment or count toward `total_chats_learned` or `total_chats_distilled`. Initial counters start strictly at `0`.

### 2.2 Truthful Telemetry (Zero Synthetic Numbers)
- **No Random Fallbacks**: Removed all synthetic multipliers and fallback model/particle/beam counts (such as `total_emitters or 15` or `total_beams or 6`). True zeros are reported when records are absent.
- **Derived Metrics**: All counts, quality scores, domain breakdowns, and cycle summaries are computed strictly from raw in-memory records.
- **Deterministic Content Hashes**: Integrity verification in `execute_feeding_cycle` computes an authentic SHA-256 hash of the canonical JSON payload (`cycle`, `stage_name`, `element`, `models`, `total_emitters`, `total_beams`, `primary_asset`).
- **Honest Operational Status**: Reporting uses `status="ingested"`, avoiding unverified claims of "optimized" or "trained".

### 2.3 Honest RAG Semantics
- **Lexicon-Expanded Keyword Search**: Search across models and snippets uses token matching and concept synonym expansions (`CONCEPT_SYNONYMS`). The service explicitly reports `retrieval_method="lexicon_expanded_keyword_search"` and does **not** masquerade as neural vector embeddings.
- **Prompt Context Retrieval**: The registry provides parameter context for prompt construction. The service explicitly reports `model_training="none_prompt_context_retrieval_only"` to distinguish context retrieval from neural model fine-tuning.

---

## 3. Storage & Concurrency Model

### 3.1 Shipped Dataset Immutability
- Shipped repository assets (`data/vfx_data.json` and `data/vfx_dump.txt`) remain strictly **read-only** at runtime.

### 3.2 Application Data Directory Redirection
- All mutable user learnings, dynamically learned VFX models, and user preferences are persisted to `paths_service.get_app_data_dir() / "vfx"`:
  - `learned_chat_insights.json` (distilled chat insights)
  - `vfx_learned_models.json` (dynamically learned VFX models)
  - `vfx_learning_prefs.json` (user privacy opt-in/opt-out settings)

### 3.3 Atomic Writes, Backups, and Concurrency
- **Atomic File Writing**: `_atomic_write_json` writes to a temporary file (`.tmp`), flushes and calls `os.fsync()`, creates a `.bak` backup of the existing file, and atomically renames via `os.replace()`.
- **Thread Safety**: All pool mutations, cache lookups, and disk persistence are guarded by `_VFX_LOCK` (`threading.RLock`).
- **Schema Versioning**: All persisted payloads include `schema_version: 2`.

---

## 4. Privacy & User Opt-Out Controls

Users retain full control over whether their chat interactions are distilled and retained:
- **`is_learning_retention_enabled() -> bool`**: Checks user opt-in status.
- **`set_learning_retention_opt_in(enabled: bool) -> bool`**: Persists preference in `vfx_learning_prefs.json`.
- **Opt-Out Enforcement**: When opted out, `evaluate_and_learn_god_tier_vfx()` returns `{"status": "opted_out", ...}` and does not persist insights or increment counters.

---

## 5. API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/database/mandatory-cache` | `GET` | Compiles VFX database metadata package with authentic counts and checksum. |
| `/ai/learned-insights` | `GET` | Returns real-time continuous learning telemetry and distilled insights. |
| `/ai/learning-preferences` | `GET` | Returns current privacy opt-in preference. |
| `/ai/learning-preferences` | `POST` | Updates user opt-in preference (`allow_learning_retention`). |
| `/ai/learn-from-chats` | `POST` | Manually distills a chat interaction into knowledge patterns. |
| `/ai/refeed-with-learnings` | `POST` | Re-executes the 5-cycle VFX ingestion pipeline, fusing distilled insights. |

---

## 6. Verification & Test Suite

The test suite in [`test_vfx_knowledge_registry_and_telemetry.py`](file:///Users/ayansh/Desktop/stroke/test_vfx_knowledge_registry_and_telemetry.py) validates:
1. **Seeded vs. User-Derived Separation**: Seeded patterns do not increment `total_chats_learned` (starts at 0).
2. **Missing/Malformed Datasets**: Missing or corrupted JSON files handle errors gracefully without crashing or fabricating numbers.
3. **Shipped Dataset Immutability**: Shipped repo `data/` files are never overwritten; state is saved in `paths_service`.
4. **Atomic Writes & Backups**: `.bak` creation and thread-safe concurrent writes across multiple worker threads.
5. **Privacy Controls**: Opt-out blocks retention; opt-in resumes distillation.
6. **Feeding Cycle Content Hash**: 64-char SHA-256 hash derived from canonical payload, zero fallback emitter/beam counts.
7. **God-Tier Evaluator**: Filters conversational, refusal, fake API, and trivial primitive requests; accepts valid Luau VFX systems.
8. **Honest Telemetry Semantics**: Confirms keyword search and prompt-only retrieval declarations.
9. **Lexicon-Expanded Search**: Multi-token and synonym retrieval matches relevant models without hallucination.
10. **REST API Endpoints**: All VFX and learning endpoints return HTTP 200 with accurate schemas.
11. **Legacy Migration**: Gracefully migrates legacy records into user app data storage.
