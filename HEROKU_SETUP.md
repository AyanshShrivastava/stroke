# Heroku Control-Plane API Setup Guide for Mist

This guide covers setting up, securing, and deploying the private **Mist Control-Plane API** on Heroku.

---

## 1. Prerequisites

- [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli) installed and logged in (`heroku login`).
- A Clerk project configured with an active production instance.
- A Google Cloud / Firebase project with Cloud Firestore enabled.
- A Cloudflare R2 bucket with an S3-compatible API token.

---

## 2. Create the Heroku Application

Create an app in your preferred Heroku region:

```bash
heroku create mist-control-plane-api --region us
```

Ensure the official Node.js buildpack is attached:

```bash
heroku buildpacks:set heroku/nodejs -a mist-control-plane-api
```

---

## 3. Configure Production Environment Variables

Execute the following commands to configure all required secrets. Replace placeholder values with your production credentials:

```bash
# General Node environment
heroku config:set NODE_ENV=production -a mist-control-plane-api

# Clerk Authentication (Backend secret key & Frontend publishable key)
heroku config:set CLERK_SECRET_KEY="sk_live_..." -a mist-control-plane-api
heroku config:set VITE_CLERK_PUBLISHABLE_KEY="pk_live_..." -a mist-control-plane-api

# Firebase Firestore (Private Service Account - JSON formatted as single-line string)
heroku config:set FIREBASE_PROJECT_ID="your-firebase-project-id" -a mist-control-plane-api
heroku config:set FIREBASE_SERVICE_ACCOUNT_JSON="$(cat service-account.json | tr -d '\n')" -a mist-control-plane-api

# Cloudflare R2 Artifact Storage
heroku config:set CLOUDFLARE_R2_ACCOUNT_ID="your_cloudflare_account_id" -a mist-control-plane-api
heroku config:set CLOUDFLARE_R2_ACCESS_KEY_ID="your_r2_access_key_id" -a mist-control-plane-api
heroku config:set CLOUDFLARE_R2_SECRET_ACCESS_KEY="your_r2_secret_access_key" -a mist-control-plane-api
heroku config:set CLOUDFLARE_R2_BUCKET="mist-published-sites" -a mist-control-plane-api

# Edge-Origin Security Secret (Must match MIST_EDGE_ORIGIN_SECRET in Cloudflare Worker)
heroku config:set MIST_EDGE_ORIGIN_SECRET="$(openssl rand -hex 32)" -a mist-control-plane-api

# Encrypted User BYOK Vault Secret (AES-256-GCM HKDF master key)
heroku config:set MIST_VAULT_SECRET="$(openssl rand -hex 32)" -a mist-control-plane-api

# Mist Domain URL
heroku config:set PUBLIC_APP_URL="https://mist.me" -a mist-control-plane-api
```

> [!CAUTION]
> Never commit `service-account.json` to Git. Keep private keys strictly in Heroku Config Vars.

---

## 4. Process Model & Procfile

Heroku uses the committed `Procfile` in the repository root:

```text
web: npm run start
```

This runs `NODE_ENV=production tsx server.ts`, which starts Express listening on `0.0.0.0:$PORT` provided dynamically by the Heroku dyno runtime.

Ensure at least 1 web dyno is running:

```bash
heroku ps:scale web=1 -a mist-control-plane-api
```

---

## 5. Deployment

Deploy the codebase directly via Git:

```bash
# Add Heroku remote if not already added
heroku git:remote -a mist-control-plane-api

# Push to deploy
git push heroku main
```

Or connect the repository via **Heroku Dashboard > Deploy > GitHub** for continuous deployment on push.

---

## 6. Security & Health Verification

Once deployed, verify the private control plane endpoints:

1. **Verify Health Endpoint**:
   ```bash
   curl -i https://mist-control-plane-api.herokuapp.com/api/health
   # Expected: HTTP/1.1 200 OK
   # { "status": "ok", "service": "mist-server" }
   ```

2. **Verify Edge Origin Secret Rejection**:
   If `MIST_EDGE_ORIGIN_SECRET` is configured, direct calls from unauthorized clients should be rejected with 403:
   ```bash
   curl -i https://mist-control-plane-api.herokuapp.com/api/projects
   # Expected: HTTP/1.1 403 Forbidden ("Missing or invalid edge origin secret")
   ```

3. **Verify Edge Origin Secret Acceptance**:
   ```bash
   curl -i -H "x-mist-edge-secret: <your_secret>" https://mist-control-plane-api.herokuapp.com/api/projects
   # Expected: HTTP/1.1 401 Unauthorized ("Authentication required")
   # (Reaches Clerk authentication layer!)
   ```

4. **Verify Clerk Session Enforcement**:
   ```bash
   curl -i -H "x-mist-edge-secret: <your_secret>" \
           -H "Authorization: Bearer <clerk_jwt>" \
           https://mist-control-plane-api.herokuapp.com/api/projects
   # Expected: HTTP/1.1 200 OK
   # { "projects": [...] }
   ```
