# Mist Production Setup Guide

This document provides complete, production-verified instructions for provisioning and configuring the external services and infrastructure required to run **Mist**.

---

## 1. System Architecture Overview

Mist is designed around a zero-trust, multi-tenant cloud architecture:

```
                                  [ User Browser ]
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
       [ Cloudflare Edge Worker ]                  [ Cloudflare Edge Worker ]
       Hostname: mist.me                           Hostname: *.mist-sites.com
                   │                                           │
         ┌─────────┴─────────┐                                 ▼
         ▼                   ▼                      [ Cloudflare R2 Bucket ]
    Static SPA          API Requests               (Published HTML Bundles)
    (Vite Assets)      (X-Edge-Secret)             [Strict Sandboxed CSP]
                             │
                             ▼
               [ Heroku Node.js / Express API ]
               - Clerk Session Verification
               - AES-256-GCM HKDF Vault
               - SSRF & Rate Limiting
                             │
                             ▼
                 [ Google Cloud Firestore ]
                 (Database ONLY - Admin SDK)
```

### Core Architecture Principles
1. **Clerk is the SOLE Authentication Provider**: Client browsers authenticate with Clerk. Firebase Auth is completely removed. The canonical user ID is the Clerk User ID (`user_...`).
2. **Firebase Firestore is DATABASE ONLY**: All database queries are executed server-side via the Firebase Admin SDK. Client browsers never access Firestore directly.
3. **AES-256-GCM Credential Vault**: User API keys (Render, OpenRouter, custom providers) are encrypted server-side with AES-256-GCM authenticated encryption and HKDF-derived per-user keys. Keys are never saved to browser `localStorage`.
4. **Cloudflare R2 & Origin Isolation**: Published website bundles are stored in Cloudflare R2 and served on a separate wildcard domain (`*.mist-sites.com`) with sandboxed CSP to eliminate cross-tenant XSS against the builder origin.
5. **Connect to Render**: Users can connect personal Render accounts via their official Render API key (`rnd_...`) to deploy static sites directly to their own Render infrastructure.

---

## 2. External Services Setup

### A. Clerk Authentication
1. Go to the [Clerk Dashboard](https://dashboard.clerk.com) and create a production application.
2. In **User & Authentication > Social Connections**, enable **Google** (or other desired identity providers).
3. In **API Keys**, retrieve:
   * **Publishable Key**: `pk_live_...` (or `pk_test_...` for staging).
   * **Secret Key**: `sk_live_...` (or `sk_test_...` for staging).
4. In **Paths**, configure:
   * Home URL: `https://mist.me`
   * Sign-in URL: `https://mist.me`
   * Sign-up URL: `https://mist.me`

---

### B. Google Cloud / Firebase Firestore (Database Only)
1. Go to the [Firebase Console](https://console.firebase.google.com) or [Google Cloud Console](https://console.cloud.google.com).
2. Select your project (e.g. `your-firebase-project-id`).
3. In **Build > Firestore Database**, ensure a Firestore database is created in **Native Mode**.
4. Deploy the production Firestore security rules:
   ```bash
   firebase deploy --only firestore:rules
   ```
   *(Note: Client access is locked down because client-side direct writes are disabled; the backend accesses Firestore via Admin credentials).*
5. Go to **Project Settings > Service Accounts > Firebase Admin SDK**.
6. Click **Generate New Private Key**. Download the resulting JSON credentials file.
7. Prepare the service account for environment configuration:
   * Minify the JSON file into a single line string.
   * Format: `{"type":"service_account","project_id":"...","private_key":"...","client_email":"..."}`.

---

### C. Cloudflare R2 & Edge Worker
1. Go to the [Cloudflare Dashboard](https://dash.cloudflare.com).
2. **Create R2 Bucket**:
   * Navigate to **R2 > Create Bucket**.
   * Bucket Name: `mist-published-sites` (or your configured `CLOUDFLARE_R2_BUCKET`).
   * Location: Auto (or nearest region).
3. **Generate R2 S3 API Credentials**:
   * Navigate to **R2 > Manage R2 API Tokens > Create API Token**.
   * Permissions: **Object Read & Write**.
   * Bucket: `mist-published-sites`.
   * Save the generated **Access Key ID** and **Secret Access Key**.
4. **Deploy Edge Worker**:
   * Navigate to the `cloudflare/` directory in this repository.
   * Follow the steps in [cloudflare/README.md](file:///Users/ayansh/.gemini/antigravity/scratch/mist/cloudflare/README.md).
   * Configure `wrangler.jsonc` with your Account ID, Zone ID, and Bucket name.
   * Set Worker secrets:
     ```bash
     npx wrangler secret put MIST_EDGE_ORIGIN_SECRET
     ```
   * Deploy via `npx wrangler deploy`.
5. **DNS & Custom Domains**:
   * Add a DNS CNAME record for your apex/control domain (e.g. `mist.me`).
   * Add a wildcard DNS record for the publishing domain (e.g. `*.mist-sites.com` pointing to the Worker).

---

### D. Render Account Connection (Optional for Users)
* Users can generate their own personal API key in their Render dashboard:
  * **Render Dashboard > Account Settings > API Keys > Create API Key**.
* For private GitHub repository deployments, ensure users have installed the [Render GitHub App](https://github.com/apps/render/installations/new).

---

### E. Web Push Notifications (VAPID)
Generate standard VAPID credentials for Web Push delivery:
```bash
npx web-push generate-vapid-keys
```
Save the public and private keys as `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY`.

---

## 3. Environment Variables Reference

| Variable | Required | Description | Example / Source |
| :--- | :---: | :--- | :--- |
| `NODE_ENV` | Yes | Runtime environment | `production` |
| `PORT` | Yes | HTTP port (set automatically by Heroku) | `3000` |
| `VITE_CLERK_PUBLISHABLE_KEY` | Yes | Client-side Clerk publishable key | `pk_live_...` |
| `CLERK_SECRET_KEY` | Yes | Server-side Clerk secret key | `sk_live_...` |
| `FIREBASE_PROJECT_ID` | Yes | Google Cloud / Firebase project ID | `mist-app-prod` |
| `FIREBASE_DATABASE_ID` | No | Firestore database ID (defaults to `(default)`) | `(default)` |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Yes | Single-line JSON service account string | `{"type":"service_account",...}` |
| `MIST_VAULT_SECRET` | Yes | 32+ character high-entropy key for AES-256-GCM vault | `openssl rand -hex 32` |
| `MIST_VAULT_PREVIOUS_SECRETS` | No | Comma-separated older keys for rotation | `secret1,secret2` |
| `ALLOW_LEGACY_VAULT_MIGRATION`| No | Decrypt old dev-fallback vault records JIT | `false` |
| `CLOUDFLARE_R2_ACCOUNT_ID` | Yes | Cloudflare account ID | `a1b2c3d4e5f6...` |
| `CLOUDFLARE_R2_ACCESS_KEY_ID` | Yes | R2 S3-compatible Access Key ID | `24-character hex` |
| `CLOUDFLARE_R2_SECRET_ACCESS_KEY`| Yes | R2 S3-compatible Secret Access Key | `64-character hex` |
| `CLOUDFLARE_R2_BUCKET` | Yes | R2 Bucket name | `mist-published-sites` |
| `MIST_EDGE_ORIGIN_SECRET` | Yes | Shared edge secret between Worker and Heroku | `openssl rand -hex 32` |
| `PUBLIC_APP_URL` | Yes | Public URL of Mist application builder | `https://mist.me` |
| `PUBLISH_BASE_URL` | Yes | Dedicated publishing origin pattern | `https://*.mist-sites.com` |
| `VAPID_PUBLIC_KEY` | Yes | Web Push VAPID public key | Generated via `web-push` |
| `VAPID_PRIVATE_KEY` | Yes | Web Push VAPID private key | Generated via `web-push` |
| `VAPID_SUBJECT` | Yes | Contact email for Web Push notifications | `mailto:ops@mist.me` |
| `VITE_SENTRY_DSN` | No | Frontend Sentry error tracking DSN | `https://...@sentry.io/...` |
| `GEMINI_API_KEY` | No | Fallback server AI key (users supply BYOK) | `AIzaSy...` |
| `BRAVE_SEARCH_API_KEY` | No | Fallback server web search key | `BSA...` |

---

## 4. Production Provisioning Step-by-Step

### Step 1: Generate Cryptographic Secrets
Run in your terminal to generate high-entropy secrets:
```bash
# 1. Credential Vault Master Secret
openssl rand -hex 32

# 2. Edge Origin Shared Secret
openssl rand -hex 32

# 3. Web Push VAPID Keys
npx web-push generate-vapid-keys
```

### Step 2: Configure Environment on Heroku
```bash
heroku config:set \
  NODE_ENV=production \
  VITE_CLERK_PUBLISHABLE_KEY="pk_live_..." \
  CLERK_SECRET_KEY="sk_live_..." \
  FIREBASE_PROJECT_ID="your-project-id" \
  FIREBASE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}' \
  MIST_VAULT_SECRET="<generated-vault-secret>" \
  CLOUDFLARE_R2_ACCOUNT_ID="<your-cloudflare-account-id>" \
  CLOUDFLARE_R2_ACCESS_KEY_ID="<your-r2-access-key>" \
  CLOUDFLARE_R2_SECRET_ACCESS_KEY="<your-r2-secret-key>" \
  CLOUDFLARE_R2_BUCKET="mist-published-sites" \
  MIST_EDGE_ORIGIN_SECRET="<generated-edge-secret>" \
  PUBLIC_APP_URL="https://mist.me" \
  PUBLISH_BASE_URL="https://*.mist-sites.com" \
  VAPID_PUBLIC_KEY="<generated-vapid-public>" \
  VAPID_PRIVATE_KEY="<generated-vapid-private>" \
  VAPID_SUBJECT="mailto:ops@mist.me" \
  -a your-heroku-app-name
```

### Step 3: Run Database Migrations
If migrating existing data from older versions:
```bash
# 1. Identity migration (resolving Clerk IDs)
npm run migrate:identities

# 2. Deployment bundle migration (moving HTML bundles from Firestore to Cloudflare R2)
npm run migrate:deployments
```

### Step 4: Verify Deployment Health
Check health endpoints:
* **Control Plane API**: `GET /api/health` returns `200 OK`.
* **Edge Worker CDN**: `GET /cdn-health` returns `200 OK` (`{"status":"ok","time":"..."}`).
* **Wildcard Subdomains**: Verify `GET https://test-slug.mist-sites.com` properly routes to Cloudflare R2 artifacts with sandboxed CSP headers.
