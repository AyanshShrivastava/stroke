# Mist Production Release Checklist

Complete each verification step in this checklist before tagging a production release or directing user traffic to the deployment.

---

## 1. Automated Code Verification Gates

- [ ] **TypeScript Typecheck**:
  ```bash
  npm run typecheck
  ```
  *Must exit with code 0 and 0 errors.*

- [ ] **Automated Test Suite**:
  ```bash
  npm test
  ```
  *Must pass all 120 tests across 16 test files with 0 failures.*

- [ ] **Frontend Production Build**:
  ```bash
  npm run build
  ```
  *Must compile the Vite SPA bundle into `dist/` cleanly.*

- [ ] **GitHub Actions CI**:
  *GitHub Actions workflow `.github/workflows/ci.yml` passes cleanly on target release branch.*

---

## 2. External Provider & Dashboard Configurations

### Clerk Dashboard
- [ ] Application is switched to a **Production Instance** (not development sandbox).
- [ ] Social Connection (**Google**) is configured with valid production OAuth client ID and secret.
- [ ] Authorized Redirect URLs include:
  - `https://mist.me`
  - `https://mist.me/`
- [ ] Session Token expiration and refresh settings are reviewed and configured.
- [ ] `VITE_CLERK_PUBLISHABLE_KEY` (`pk_live_...`) and `CLERK_SECRET_KEY` (`sk_live_...`) match the production instance.

### Google Cloud / Firebase Console
- [ ] Cloud Firestore is active in **Native Mode**.
- [ ] Service Account `FIREBASE_SERVICE_ACCOUNT_JSON` is created with role `Firebase Admin SDK Administrator Service Agent` and `Cloud Datastore User`.
- [ ] Firestore Composite Indexes are deployed if custom queries are configured.
- [ ] Firestore Security Rules are deployed via `firebase deploy --only firestore:rules`.

### Cloudflare Dashboard
- [ ] R2 Bucket `mist-published-sites` exists and has Object Read & Write permissions.
- [ ] R2 API Token credentials (`CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`) are active.
- [ ] Cloudflare Edge Worker is deployed with secrets `MIST_EDGE_ORIGIN_SECRET` and `HEROKU_API_ORIGIN`.
- [ ] Wildcard DNS record (`*.mist-sites.com` or configured `PUBLISH_BASE_URL`) points to the Cloudflare Worker.
- [ ] Apex DNS record (`mist.me`) points to Cloudflare proxy.

### Sentry Telemetry
- [ ] `VITE_SENTRY_DSN` is populated in environment and connected to the production project.
- [ ] Error boundary captures unhandled exceptions in the frontend.

### Web Push Notifications
- [ ] VAPID keys generated and configured (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`).
- [ ] `public/sw.js` is accessible at `https://mist.me/sw.js`.

---

## 3. Environment Variables Verification

Verify every required variable is set in the hosting environment (Heroku, Cloudflare):

| Variable | Configured? | Notes |
| :--- | :---: | :--- |
| `NODE_ENV=production` | [ ] | Enforces production security checks |
| `VITE_CLERK_PUBLISHABLE_KEY` | [ ] | Matches Clerk production instance |
| `CLERK_SECRET_KEY` | [ ] | High-entropy server secret |
| `FIREBASE_PROJECT_ID` | [ ] | Production project ID |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | [ ] | Valid minified JSON |
| `MIST_VAULT_SECRET` | [ ] | 32+ char high-entropy hex string |
| `CLOUDFLARE_R2_ACCOUNT_ID` | [ ] | Cloudflare Account ID |
| `CLOUDFLARE_R2_ACCESS_KEY_ID` | [ ] | R2 S3 Access Key |
| `CLOUDFLARE_R2_SECRET_ACCESS_KEY` | [ ] | R2 S3 Secret Key |
| `CLOUDFLARE_R2_BUCKET` | [ ] | Bucket name |
| `MIST_EDGE_ORIGIN_SECRET` | [ ] | Identical on Heroku and Worker |
| `PUBLIC_APP_URL` | [ ] | `https://mist.me` |
| `PUBLISH_BASE_URL` | [ ] | `https://*.mist-sites.com` |
| `VAPID_PUBLIC_KEY` | [ ] | Public VAPID key |
| `VAPID_PRIVATE_KEY` | [ ] | Private VAPID key |
| `VAPID_SUBJECT` | [ ] | `mailto:...` |

---

## 4. Post-Deployment Verification & Smoke Tests

- [ ] **Edge Health**: `curl -s https://mist.me/cdn-health` returns `200 OK`.
- [ ] **API Health**: `curl -s https://mist.me/api/health` returns `200 OK`.
- [ ] **Sign In Flow**: Test signing in with Google via Clerk; verify avatar and email load in header and settings.
- [ ] **Project Creation & Sync**: Create a new project, edit a file, and verify offline dirty tracking and cloud sync.
- [ ] **Credential Vault**: Test connecting an API key (e.g. Render personal API key); verify it seals in vault without leaking plaintext.
- [ ] **Website Publishing**: Publish a test website; verify it is served from the dedicated wildcard origin (`https://<slug>.mist-sites.com`) with sandboxed CSP (`sandbox allow-scripts`).
- [ ] **Connect to Render**: Test deploying a static site to Render; verify live status polling and `.onrender.com` URL generation.

---

## 5. Rollback & Disaster Recovery Procedures

1. **Immediate Traffic Rollback (Cloudflare)**:
   * In Cloudflare Dashboard > Workers & Pages > Mist Worker > Deployments, rollback to the previous deployment version in 1 click.
2. **Heroku Control Plane Rollback**:
   ```bash
   heroku releases -a mist-control-plane-api
   heroku rollback vXX -a mist-control-plane-api
   ```
3. **Database Identity Rollback**:
   ```bash
   npm run migrate:identities -- --rollback
   ```
4. **Key Rotation Revert**:
   * If rotating `MIST_VAULT_SECRET`, ensure the previous secret is retained in `MIST_VAULT_PREVIOUS_SECRETS` until all active accounts have unsealed and re-encrypted their credentials.
