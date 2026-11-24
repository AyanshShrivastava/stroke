# Stroke V1 — Bring Your Own Key (BYOK) AI Provider Architecture Migration Report

## 1. Executive Summary

Stroke has completed a comprehensive architectural migration away from mandatory local language model downloads (e.g., Llama 3.2 1B Instruct GGUF or local Ollama instances) to an enterprise-grade **Bring Your Own Key (BYOK)** multi-provider ecosystem. 

Users are no longer blocked by hardware constraints, gigabyte-sized weight downloads, or local C++ inference compiler crashes. Instead, users securely connect their own API keys for world-class hosted AI providers and open routers, select their preferred model and reasoning effort tier, and execute autonomous coding workflows seamlessly.

---

## 2. Supported AI Providers & Model Catalog

| Provider | Supported Models | Adapter Implementation | Tool Calling Support |
| :--- | :--- | :--- | :--- |
| **Groq** | `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `mixtral-8x7b-32768` | `GroqProvider` (Fast HTTPX client, ultra-low latency LPU) | Native OpenAI-compatible tool calling |
| **Google Gemini** | `gemini-1.5-pro`, `gemini-1.5-flash`, `gemini-2.0-flash-exp` | `GeminiProvider` (REST API with contents/parts translation) | Structured function declarations |
| **OpenRouter** | `anthropic/claude-3.5-sonnet`, `deepseek/deepseek-chat`, `meta-llama/llama-3.3-70b-instruct` | `OpenRouterProvider` (Multi-model routing, provider fallbacks) | Unified OpenAI format with tool transforms |
| **OpenAI** | `gpt-4o`, `gpt-4o-mini`, `o1`, `o3-mini` | `RemoteOpenAiCompatibleProvider` | Native function calling & structured outputs |
| **Anthropic** | `claude-3-5-sonnet-20241022`, `claude-3-5-haiku-20241022` | `AnthropicProvider` (Messages API format, tool blocks) | Native `input_schema` tools |
| **Custom Providers** | User-defined model ID, base URL, optional auth key | `CustomProvider` (OpenAI & Anthropic compatibility modes) | Configurable per base endpoint |
| *Backward-Compat* | `llama3.2-local` (optional fallback for offline dev/tests) | `LlamaCppProvider`, `OllamaProvider` | Local fallback parser |

---

## 3. Security Architecture & Credential Vault

Stroke enforces strict, defense-in-depth credential protection governed by `credentials_vault_service.py`:

```
   ┌────────────────────────────────────────────────────────┐
   │                  Inference Request                     │
   └──────────────────────────┬─────────────────────────────┘
                              │
               Retrieve API Key (Memory Only)
                              │
             ┌────────────────┴────────────────┐
             ▼                                 ▼
   ┌───────────────────┐             ┌───────────────────┐
   │    OS Keychain    │             │  Encrypted Vault  │
   │ (macOS / Win / X) │ (fallback)  │ (AES-256 Fernet)  │
   └───────────────────┘             └───────────────────┘
```

1. **Zero Plaintext Secrets**:
   - API keys are never stored in browser `localStorage`, `sessionStorage`, or IndexedDB.
   - API keys are never written to unencrypted files, git commits, terminal logs, or crash telemetry.
   - HTTP response bodies never return unmasked keys (`mask_key()` preserves only a 4-char prefix and 4-char suffix with `••••••••••••`).

2. **OS Keychain First**:
   - Uses the platform's native keyring via Python's `keyring` library (Apple Keychain on macOS, Windows Credential Manager on Windows, SecretService/KWallet on Linux).

3. **Machine-Bound Encrypted Vault Fallback**:
   - When running in environments where OS Keyring is headless or locked, keys are saved in `~/.stroke/credentials/byok_credentials.vault`.
   - Encrypted using Fernet (AES-128-CBC with HMAC-SHA256) keyed by a locally generated 256-bit secret stored in `byok_vault.key` with strict `0600` POSIX file permissions and `0700` directory permissions.

4. **Environment Variable Fallback**:
   - Supports CI/CD and developer workflows via standard environment variables (`GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `CUSTOM_AI_API_KEY`).

---

## 4. Reasoning Effort & Parameter Normalization

All 5 reasoning effort levels configured in Stroke's UI are dynamically mapped to model-appropriate inference parameters:

| Reasoning Effort | Max Tokens | Temperature | Provider-Specific Adaptations |
| :--- | :--- | :--- | :--- |
| **Low** | 1,024 | 0.2 | Focused, deterministic, minimal thinking tokens |
| **Medium** | 4,096 | 0.5 | Balanced coding & explanation |
| **High** | 8,192 | 0.7 | Deep code analysis and architectural planning |
| **Maximum** | 16,384 | 0.8 | Extensive multi-file refactoring and exploration |
| **Absolute Peak** | 32,768 | 0.9 | Extended reasoning budget (o1/o3-mini reasoning tokens, Anthropic 64k tokens) |

---

## 5. Model Management UI (`/integrations` — Models & Engine)

The Models page within `/integrations` offers a minimalist, intuitive configuration experience:
1. **Active Engine Summary Banner**: Displays the currently active provider, model name, context window size, latency badge, and reasoning level.
2. **Provider Sub-Navigation**: Quick tabs for Groq, Gemini, OpenRouter, Anthropic, OpenAI, and Custom endpoints.
3. **Secure Credential Input**: Password-masked input field with visibility toggle and status indicator (OS Keychain vs Local Encrypted).
4. **Live Connection Testing**: Real HTTP test probe sending a minimal diagnostic completion to verify authentication, quota, and latency before saving.
5. **Model Catalog & Default Selection**: Radio selection of available models with context window metadata and "Set as Default" button.
6. **Reasoning Effort Selector**: Interactive 5-tier pill toggle (`Low`, `Medium`, `High`, `Maximum`, `Absolute Peak`).

---

## 6. Backend API Endpoints

- `GET /api/models/providers`: Lists all supported providers, their active configured status, and masked keys.
- `POST /api/models/credentials`: Stores or updates API keys in OS Keychain / encrypted vault.
- `DELETE /api/models/credentials/{provider}`: Purges credentials from both OS Keychain and encrypted vault.
- `POST /api/models/test-connection`: Executes an end-to-end diagnostic ping with user-supplied or saved credentials.
- `GET /api/models/active`: Retrieves the currently active provider, model ID, and inference settings.
- `POST /api/models/active`: Updates active provider and default model settings.
- `GET /api/models/catalog`: Returns the complete registry of supported models, context limits, and capabilities.

---

## 7. Verification & Test Matrix

All test suites were executed and verified locally:

```bash
# Backend Test Suites (79 tests passed)
STROKE_ALLOW_OFFLINE_DB=1 ./venv/bin/pytest \
  test_byok_provider_architecture.py \
  test_ai_providers_and_runtime_health.py \
  test_filesystem_and_backup_safety.py \
  test_autonomous_coding_system.py \
  test_agent_loop.py

# Frontend Vitest Suite (17 tests passed)
npx vitest run

# Production Build (Nitro SSR bundle generated in 143ms)
npm run build
```

---

## 8. Migration Checklist Completion

- [x] Removed startup local GGUF download blocking in `desktop.py`.
- [x] Implemented BYOK providers (`Groq`, `Gemini`, `OpenRouter`, `Anthropic`, `OpenAI`, `Custom`).
- [x] Built secure OS Keychain and Fernet encrypted vault with 0600 permissions.
- [x] Zero plaintext keys in logs, HTTP payloads, or browser storage.
- [x] Replaced `ai_chat` inference pipeline in `main.py` with multi-provider BYOK dispatcher.
- [x] Added `llm_repair_callback` sync execution support for autonomous coding loop.
- [x] Updated frontend store `keyboard-store.ts` with BYOK API client helpers and 5 reasoning tiers.
- [x] Designed and integrated Model Management UI tab in `src/routes/_authenticated/integrations.tsx`.
- [x] Preserved backward-compatible model definitions for existing regression tests.
- [x] Author comprehensive migration report and push changes to `product-v1-overhaul`.
