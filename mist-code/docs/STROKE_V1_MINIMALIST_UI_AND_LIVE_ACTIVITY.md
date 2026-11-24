# Stroke V1 — Minimalist UI Redesign, Light/Dark Mode & Live Activity Architecture

## Executive Summary
This document outlines the complete architectural overhaul of Stroke's user interface under **Prompt 20**, introducing an ultra-minimalist, distraction-free visual identity, a comprehensive Light/Dark/System theme engine, and attached **Live Thinking & Activity Feeds** displaying verified agent actions in real time.

---

## 1. Visual Identity & Design Principles
- **Minimalist Aesthetics**: Removed clutter, extraneous borders, heavy glows, and decorative cards. Maximize usable canvas area for active coding conversations and code previews.
- **Stroke Signature Color System**: Built using OKLCH perceptual lightness tokens to prevent eye strain in both light and dark environments:
  - **Light Mode (`:root`)**: Soft porcelain background (`oklch(0.985 0.003 250)`), deep graphite typography (`oklch(0.18 0.015 250)`), subtle hairline borders (`oklch(0.89 0.006 250)`), and deep sapphire/indigo primary accent (`oklch(0.42 0.16 260)`).
  - **Dark Mode (`.dark`)**: Deep obsidian graphite (`oklch(0.125 0.01 250)`), crisp readable off-white (`oklch(0.94 0.005 250)`), subtle slate borders (`oklch(0.22 0.012 250)`), and electric violet-indigo primary accent (`oklch(0.72 0.16 255)`).
  - **System Mode**: Dynamically synchronizes with OS preference (`prefers-color-scheme`) with zero page reloads.

---

## 2. Core Frontend Components

### 2.1 Theme Management (`src/lib/theme.ts` & `ThemeToggle.tsx`)
- Supports `"light" | "dark" | "system"`.
- Persists user selection in `localStorage` (`stroke_theme`).
- Anti-flash script in `src/routes/__root.tsx` executes before initial paint to guarantee zero light/dark flickering on hydration.
- Dispatches reactive `stroke:theme-changed` custom events so header buttons, settings tabs, and cards update immediately.

### 2.2 Live Thinking & Activity Feed (`src/components/chat/ActivityFeed.tsx`)
Attached directly to each assistant response inside the conversation stream:
- **Thinking / Active State**:
  - Displays pulsating status with live timer (e.g. `1.8s`) and active agent loop indicator.
- **Completed / Verified State**:
  - Collapsed header bar summarizing actions:
    - Elapsed duration (e.g. `1.8s`).
    - Task state badge (`completed`, `failed`).
    - Action pills: e.g. `3 files inspected`, `2 actions`, `Self-healed (2 iters)`, `Tests passed`.
    - Single-click expand/collapse chevron.
  - Expanded step-by-step audit:
    - **Luau Syntax & Domain Test Report**: Syntax check status, domain tests passed, healing iterations.
    - **Chronological Action Steps**: File analysis, terminal executions, Roblox Studio tool calls, symbol searches, autonomous patches.
    - **Privacy Safe**: Strips tokens, credentials, and raw private thoughts; surfaces only clean operational logs.

### 2.3 Minimalist Floating Composer (`src/components/chat/Composer.tsx`)
- Auto-expanding multiline textarea.
- **Model Selector Pill**: Displays active engine with offline local indicator (e.g., `Llama 3.2 1B [Local GGUF]`, `DeepSeek R1 [Reasoning]`, `Claude 3.7 Sonnet [Hybrid]`, `Gemini 2.5 Pro [Multimodal]`).
- **Reasoning Effort Pill**: Fast switching between `Low`, `Medium`, `High`, and `Maximum`.
- **File Attachments**: File picker and drag-and-drop preview pills with one-click removal.
- **Action Control**: Transforms between Send (ArrowUp) and Stop (Square) during generation.
- **Keyboard Ergonomics**: `Enter` to submit, `Shift+Enter` for newlines.

### 2.4 Navigation & AppShell (`src/components/keyboard/AppShell.tsx`)
- Compact 256px sidebar with sleek `+ New Chat` button (and `⌘K` shortcut badge).
- Recent conversations list with hover actions for deletion.
- Minimalist Storage Meter tracking the 1 GB local session cache limit.
- Quick-access theme toggle button and direct navigation to Settings & Integrations.

### 2.5 Settings & Integrations (`src/routes/_authenticated/integrations.tsx`)
Clean horizontal tab interface dividing system intelligence into:
1. **Appearance**: Instant theme switching cards.
2. **Models & AI Engine**: Default model presets and reasoning effort configurations.
3. **Workspaces & Ingestion**: Real workspace scanning, symbol extraction, and Rojo/Wally config indexing.
4. **GitHub Vault**: AES-encrypted local token storage with environment fallback.
5. **Roblox Studio MCP**: MCP bridge status and available Studio tool count.
6. **Storage & Memory**: Context quota usage and cache maintenance.

---

## 3. Verification & Test Coverage
- **Frontend Unit Tests** (`src/test/theme-and-activity.test.tsx`):
  - Theme mode storage and OS preference resolution.
  - Activity feed live thinking state rendering.
  - Collapsed and expanded activity summary verification.
  - Composer model selection, reasoning toggle, and enter-key submission.
  - **Result: 7/7 tests passed**.
- **Production Build** (`npm run build`):
  - Cloudflare Nitro worker and client bundles compiled with 0 errors.
- **Backend Safety & Pipeline Suites**:
  - Filesystem safety (`test_filesystem_and_backup_safety.py`): 16/16 OK.
  - User file system (`test_user_file_system.py`): 13/13 OK.
  - VFX knowledge registry (`test_vfx_knowledge_registry_and_telemetry.py`): 16/16 OK.
  - Code engineering pipeline (`test_code_engineering_and_verification.py`): 29/29 OK.
  - Evaluation & Observability (`test_evaluation_and_observability.py`): 13/13 OK.
  - MCP Security (`test_mcp_security_and_protocol.py`): 11/11 OK.
  - **Result: 98/98 backend tests passing**.
