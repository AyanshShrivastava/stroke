# Mist Production Deployment Guide

This guide details the step-by-step production deployment process for the Mist application, including the Heroku control plane, Cloudflare edge worker, and Cloudflare R2 storage.

---

## 1. Deployment Topology

Mist consists of two coordinated services:

```
                    ┌───────────────────────────────────┐
                    │      Cloudflare Edge Worker       │
                    │      (cloudflare/src/index.ts)    │
                    └─────────────────┬─────────────────┘
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                   ▼
 [ Cloudflare R2 Storage ]                           [ Heroku Control Plane ]
 - Bucket: mist-published-sites                      - Node.js 22 LTS / Express
 - Stores HTML website bundles                       - Proxied at /api/*
 - Edge-cached via Worker                            - Authenticated via Clerk
```

---

## 2. Prerequisites

* **Node.js**: `v20.19.0` or `v22.x` (recommended: Node 22 LTS).
* **Package Manager**: npm 10+ (using `package-lock.json`).
* **CLIs**:
  * [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli): `heroku --version`
  * [Wrangler CLI](https://developers.cloudflare.com/workers/wrangler/): `npx wrangler --version`
  * [Firebase CLI](https://firebase.google.com/docs/cli): `firebase --version`

---

## 3. Production Build & Packaging Verification

Mist compiles its frontend single-page application into `dist/` using Vite. The Express server serves static assets in production from `dist/` and runs runtime bundling through esbuild and Tailwind.

### Clean Dependency Architecture
* **Runtime Dependencies**: `express`, `@clerk/express`, `firebase-admin`, `@aws-sdk/client-s3`, `esbuild`, `tailwindcss`, `web-push`, `jszip`, `dotenv`.
* **Zero Platform-Specific Direct Binaries**: All platform-dependent native bindings (such as darwin-arm64 rolldown) are resolved dynamically or managed via optional dependencies, ensuring reproducible Linux builds on Heroku and Docker.
* **Pre-deployment Verification**:
  ```bash
  # 1. Typecheck
  npm run typecheck

  # 2. Automated Test Suite (120 tests)
  npm test

  # 3. Production Build
  npm run build
  ```

---

## 4. Deploying the Heroku Control Plane

### Step 1: Create Heroku Application
```bash
heroku create mist-control-plane-api --region us
```

### Step 2: Configure Buildpacks
Set Node.js buildpack:
```bash
heroku buildpacks:set heroku/nodejs -a mist-control-plane-api
```

### Step 3: Configure Environment Variables
Set the mandatory production environment variables:
```bash
heroku config:set \
  NODE_ENV=production \
  VITE_CLERK_PUBLISHABLE_KEY="pk_live_..." \
  CLERK_SECRET_KEY="sk_live_..." \
  FIREBASE_PROJECT_ID="your-firebase-project-id" \
  FIREBASE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}' \
  MIST_VAULT_SECRET="$(openssl rand -hex 32)" \
  CLOUDFLARE_R2_ACCOUNT_ID="your_account_id" \
  CLOUDFLARE_R2_ACCESS_KEY_ID="your_r2_access_key" \
  CLOUDFLARE_R2_SECRET_ACCESS_KEY="your_r2_secret_key" \
  CLOUDFLARE_R2_BUCKET="mist-published-sites" \
  MIST_EDGE_ORIGIN_SECRET="$(openssl rand -hex 32)" \
  PUBLIC_APP_URL="https://mist.me" \
  PUBLISH_BASE_URL="https://*.mist-sites.com" \
  VAPID_PUBLIC_KEY="your_vapid_public_key" \
  VAPID_PRIVATE_KEY="your_vapid_private_key" \
  VAPID_SUBJECT="mailto:ops@mist.me" \
  -a mist-control-plane-api
```

### Step 4: Deploy Control Plane
```bash
git push heroku main
```
*Heroku uses the `Procfile` (`web: npm start`), which executes `NODE_ENV=production tsx server.ts`.*

---

## 5. Deploying the Cloudflare Edge Worker

The edge worker routes incoming traffic between the Heroku control plane, published R2 website bundles, and CDN caching.

### Step 1: Configure `cloudflare/wrangler.jsonc`
Verify the configuration in [cloudflare/wrangler.jsonc](file:///Users/ayansh/.gemini/antigravity/scratch/mist/cloudflare/wrangler.jsonc):
* Set your `account_id`.
* Set your `zone_id`.
* Verify the R2 bucket binding name: `MIST_PUBLISHED_SITES`.

### Step 2: Configure Worker Secrets
Navigate to the `cloudflare/` directory and configure secrets:
```bash
cd cloudflare

# Edge secret (MUST match MIST_EDGE_ORIGIN_SECRET set on Heroku)
npx wrangler secret put MIST_EDGE_ORIGIN_SECRET

# Heroku origin URL
npx wrangler secret put HEROKU_API_ORIGIN
```

### Step 3: Deploy Worker
```bash
npx wrangler deploy
```

---

## 6. Database Migrations

Mist provides zero-downtime, idempotent migration scripts with dry-run and rollback capabilities.

### 1. Identity Migration (Clerk Migration)
Migrates legacy Firebase Auth user IDs to Clerk User IDs in Firestore:
```bash
# Step 1: Preview changes without writing to database (Dry Run)
npm run migrate:identities -- --dry-run

# Step 2: Apply migration
npm run migrate:identities -- --apply

# (Optional) Revert migration if needed
npm run migrate:identities -- --rollback
```

### 2. Deployment Artifact Migration (R2 Migration)
Extracts legacy HTML bundles stored directly in Firestore and uploads them into Cloudflare R2:
```bash
# Step 1: Preview eligible deployments (Dry Run)
npm run migrate:deployments -- --dry-run

# Step 2: Apply migration to R2 and clean up Firestore htmlBundle
npm run migrate:deployments -- --apply
```

---

## 7. Post-Deployment Verification

1. **Edge Worker Health Check**:
   ```bash
   curl -i https://mist.me/cdn-health
   # Expected: HTTP 200 OK {"status":"ok","time":"..."}
   ```

2. **Control Plane API Health Check**:
   ```bash
   curl -i https://mist.me/api/health
   # Expected: HTTP 200 OK {"status":"ok","version":"..."}
   ```

3. **Origin Isolation Verification**:
   ```bash
   curl -i https://mist.me/p/test-site
   # Expected: HTTP 301 Moved Permanently with Location: https://test-site.mist-sites.com
   ```

4. **Wildcard Published Site Verification**:
   ```bash
   curl -i https://test-site.mist-sites.com
   # Expected: Content-Security-Policy contains 'sandbox allow-scripts' and omits 'allow-same-origin'
   ```
