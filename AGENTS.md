<!-- LOVABLE:BEGIN -->

> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.

## What Lovable manages

Rules outside this block are the project's own. Change the pieces below in
Lovable, not by hand. With the [Lovable MCP](https://mcp.lovable.dev)
connected, `send_message` asks Lovable to do it; otherwise ask the user to
use the editor.

- **Database.** Do not add or edit `supabase/migrations/` or `drizzle/`.
  Ask Lovable to change the schema.
- **Generated files.** Do not edit a file whose header says it is automatically
  generated.
- **AI gateway.** Keep model calls on Lovable's gateway, and keep
  `LOVABLE_API_KEY` out of browser code.
- **Connectors.** Lovable provides native connectors. `list_connectors` shows
  which are enabled; `add_connector` only returns the dashboard link. When a
  connector is enabled, calls go through the connector gateway and need
  `LOVABLE_API_KEY`. When Lovable does not provide one, users can bring their
  own key and store it in Secrets.
- **Secrets.** Lovable manages them. Do not put secret values in the repo.

<!-- LOVABLE:END -->

## Authoritative Architecture & Production Rules

- **Authoritative Backend:** Python FastAPI (`main.py`) running natively on `127.0.0.1:8501`.
- **Authoritative Production Frontend:** Single-page application served directly by FastAPI at `/` backed by `index.html`.
- **Authoritative Desktop Supervisor:** `desktop.py` with PyWebView / system default browser fallback.
- **Database Engine:** Google Cloud Firestore in production; genuine disk-backed offline Firestore engine (`local_firestore.py` via `data/local_firestore_db.json`) when `STROKE_ALLOW_OFFLINE_DB=1`.
- **Identity & Authorization:** Strictly keyed by Firebase Auth UID. Email query parameters or headers are never trusted for document or session ownership.
- **Terminal Execution:** Sandboxed Python backend terminal engine (`terminal_service.py`) enforcing UID session ownership, single-use cryptographic approvals, output buffer bounds, and secret redaction.
- **Reference Web Client:** The React/TanStack Start client under `src/` is retained for headless developer routing and Vitest test coverage (`npm test`). It does not replace `index.html` as the primary production interface.
- **Git History Safety:** Never force-push or rewrite published Git history. Preserve all user repositories, workspaces, and local user data.
