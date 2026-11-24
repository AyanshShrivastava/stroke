# Mist Cloudflare Publishing Architecture & Edge Router

Edge Worker and Cloudflare R2 configuration for **Mist** website publishing and static asset delivery.

---

## 1. Target Architecture Overview

```
Mist Application (React 19 Frontend)
         ↓  (POST /api/deployments with Clerk JWT)
Authenticated Express Publishing API
         ↓
    ┌────┴─────────────────────────────┐
    ↓                                  ↓
Cloudflare R2 Bucket          Firebase Firestore
(HTML bundles & static files)  (Metadata & ownership only)
    ↓
Cloudflare Worker (Edge Router)
    ↓
Published Website Hostname (e.g. https://<slug>.mist-sites.com)
```

### Architecture Highlights
- **Cloudflare R2 Storage**: Website HTML bundles are saved in Cloudflare R2 at `sites/<slug>/index.html` using official server-side S3 credentials (`@aws-sdk/client-s3`). No storage credentials ever reach the client.
- **Firestore Metadata Storage**: Only publishing metadata (`slug`, `ownerId`, `projectId`, `title`, `createdAt`, `updatedAt`, `artifactPath`, `r2Bucket`) is stored in Firestore. Large HTML bundles are excluded from Firestore once stored in R2.
- **Cloudflare Worker Edge Router**: Serves published websites directly from Cloudflare R2 using the `PUBLISHED_BUCKET` binding. The Express backend is completely offloaded from public website traffic.
- **Configurable Wildcard Publishing Domain**: Supports either apex subdomains (`*.mist.me`) or dedicated wildcard publishing domains (e.g. `*.mist-sites.com`).
- **Origin Isolation & Strict Security**: Published websites are served with strict sandbox Content Security Policy headers (`sandbox allow-scripts allow-forms allow-popups`, no `allow-same-origin`), `X-Frame-Options: DENY`, `Set-Cookie` stripping, and isolated storage boundaries.
- **Ownership Enforcement**: Users cannot hijack or overwrite other users' website slugs in Firestore or in Cloudflare R2. Only the verified owner can update or unpublish/delete a website.

---

## 2. Cloudflare & Environment Configuration

### A. Backend Control Plane (Express Server)
Configure the following server-side environment variables in your control plane (e.g. Heroku, Railway, or VPS):

```bash
# Cloudflare R2 Credentials (Server-side only)
CLOUDFLARE_ACCOUNT_ID="your-cloudflare-account-id"
R2_ACCESS_KEY_ID="your-r2-api-token-access-key-id"
R2_SECRET_ACCESS_KEY="your-r2-api-token-secret-access-key"
R2_BUCKET_NAME="mist-published-sites"

# Dedicated Publishing Domain Base URL
# Use wildcard syntax for subdomains:
PUBLISH_BASE_URL="https://*.mist-sites.com"
# Or a subdomain path base:
# PUBLISH_BASE_URL="https://sites.mist.me"

# Edge Origin Security
MIST_EDGE_ORIGIN_SECRET="your-high-entropy-edge-secret"
```

> [!IMPORTANT]
> Never hardcode credentials in code or repository configuration. Always use environment variables for R2 credentials and edge origin secrets.

### B. Cloudflare Edge Worker (`cloudflare/wrangler.jsonc`)
The Cloudflare Worker configuration connects the edge router to Cloudflare R2 and Workers Static Assets:

```jsonc
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "mist-edge",
  "main": "src/index.ts",
  "compatibility_date": "2024-11-01",
  "compatibility_flags": ["nodejs_compat"],

  // Workers Static Assets: serves the compiled Vite frontend from dist/
  "assets": {
    "directory": "../dist",
    "binding": "ASSETS",
    "html_handling": "auto-trailing-slash",
    "not_found_handling": "single-page-application"
  },

  // Cloudflare R2 bucket binding for published website artifacts
  "r2_buckets": [
    {
      "binding": "PUBLISHED_BUCKET",
      "bucket_name": "mist-published-sites"
    }
  ],

  // Workers Routes: handles apex mist.me and all wildcard subdomains (*.mist.me)
  "routes": [
    {
      "pattern": "mist.me/*",
      "zone_name": "mist.me"
    },
    {
      "pattern": "*.mist.me/*",
      "zone_name": "mist.me"
    }
  ],

  // Environment variables
  "vars": {
    "APEX_DOMAIN": "mist.me",
    // Configurable wildcard publishing domain:
    "PUBLISH_DOMAIN": "mist.me",
    "HEROKU_API_ORIGIN": "https://mist-control-plane-api.herokuapp.com"
  }
}
```

---

## 3. Step-by-Step Provisioning Guide

### Step 1: Create the Cloudflare R2 Bucket
Run using the Cloudflare Wrangler CLI:
```bash
npx wrangler r2 bucket create mist-published-sites
```

### Step 2: Create R2 API Tokens for the Express Backend
1. Go to the Cloudflare Dashboard -> **R2** -> **Manage R2 API Tokens**.
2. Click **Create API Token**.
3. Choose **Object Read & Write** permissions scoped to your `mist-published-sites` bucket.
4. Copy `Access Key ID` and `Secret Access Key` to your backend environment (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`).
5. Copy your Cloudflare Account ID from the dashboard sidebar (`CLOUDFLARE_ACCOUNT_ID`).

### Step 3: Configure Wildcard DNS in Cloudflare
In your Cloudflare DNS dashboard for your publishing zone (e.g. `mist.me` or `mist-sites.com`):
1. Add a **CNAME** record:
   - **Name**: `*`
   - **Target**: `@` (or your worker fallback domain)
   - **Proxy status**: **Proxied** (Orange Cloud)
2. Add an **A** or **CNAME** record for the root domain (`@`), set to **Proxied**.

### Step 4: Configure Edge Secret & Deploy Worker
1. Set the edge origin secret in Cloudflare:
   ```bash
   cd cloudflare
   npx wrangler secret put MIST_EDGE_ORIGIN_SECRET
   ```
2. Build the production client bundle:
   ```bash
   npm run build
   ```
3. Deploy the Worker:
   ```bash
   cd cloudflare
   npx wrangler deploy
   ```

---

## 4. Migration Strategy for Historical Firestore Deployments

To migrate historical deployments that have full HTML bundles stored directly in Firestore into Cloudflare R2, run the migration tool:

### 1. Dry Run (Preview & Verification)
Inspect all deployments without making any writes:
```bash
npm run migrate:deployments
# or:
npx tsx scripts/migrate-deployments-to-r2.ts
```

### 2. Live Apply
Upload eligible HTML bundles to Cloudflare R2 and strip the heavy `htmlBundle` field from Firestore:
```bash
npm run migrate:deployments -- --apply
```

### Migration Safety Guarantees
- **Safe Rollback**: If R2 upload fails for any document, Firestore is **never modified** and the HTML bundle remains safely in Firestore.
- **Idempotency**: Already migrated deployments are recognized and skipped.
- **Audit Metadata**: Sets `migratedToR2At`, `artifactPath`, and `r2Bucket` on migrated Firestore documents.

---

## 5. Automated Tests

Run the full Cloudflare edge and publishing test suite:
```bash
# Cloudflare Worker Edge tests (routing, wildcard subdomains, SPA fallback, caching, CSP)
npx tsx --test cloudflare/src/index.test.ts

# End-to-end publishing, ownership enforcement, updates, and deletion tests
npx tsx --test src/server/cloudflarePublishing.test.ts

# Deployment migration tests
npx tsx --test src/server/deploymentMigration.test.ts
```

> [!NOTE]
> Do not claim DDoS, WAF, bot protection, or custom SSL has been enabled unless specifically configured in your Cloudflare account dashboard.
