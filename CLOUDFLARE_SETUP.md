# Cloudflare Production Infrastructure Setup Guide for Mist (`mist.me`)

This document provides exact, step-by-step instructions for provisioning, configuring, and verifying Cloudflare infrastructure for **Mist**.

---

## Architecture Overview

```
                      Internet Visitor
                             │
            ┌────────────────┴────────────────┐
            │                                 │
     (mist.me / assets)              (*.mist.me)
            ▼                                 ▼
   Cloudflare Edge (WAF/DDoS)        Cloudflare Edge (WAF/DDoS)
            │                                 │
   Cloudflare Worker (mist-edge)     Cloudflare Worker (mist-edge)
     ├── Static Assets (/assets/*)     └── Cloudflare R2 Bucket
     │   served from dist/                 (mist-published-sites)
     │                                     sites/<slug>/index.html
     └── Reverse Proxy (/api/*)
         with x-mist-edge-secret
            │
            ▼
    Private Heroku API
 (mist-control-plane-api)
```

---

## Step 1: Add `mist.me` Zone and Delegate Nameservers

1. Log in to the [Cloudflare Dashboard](https://dash.cloudflare.com/).
2. Click **Add a domain** (or **Add site**).
3. Enter `mist.me` and choose your plan (Free, Pro, or Business).
4. Cloudflare will scan existing DNS records. Click **Continue**.
5. Cloudflare assigns two authoritative nameservers (e.g., `ada.ns.cloudflare.com` and `bob.ns.cloudflare.com`).
6. In your domain registrar (e.g. Namecheap, Porkbun, Google Domains), replace existing nameservers with Cloudflare's assigned nameservers.
7. Return to Cloudflare Dashboard and click **Check nameservers**. Once delegation propagates, the zone status changes to **Active**.

---

## Step 2: Configure Proxied DNS Records

> [!IMPORTANT]
> All DNS records for `mist.me` must have the **Proxy status set to Proxied (Orange Cloud)**.
> Unproxied (Grey Cloud) records bypass Cloudflare's WAF, DDoS protection, CDN caching, and Workers Routes.

In **DNS > Records**, configure the following:

| Type | Name | Content | Proxy Status | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `AAAA` | `@` | `100::` | **Proxied** (Orange) | Apex placeholder for Workers route / Static Assets |
| `AAAA` | `*` | `100::` | **Proxied** (Orange) | Wildcard placeholder for published project subdomains (`*.mist.me`) |
| `CNAME` | `www` | `mist.me` | **Proxied** (Orange) | Redirected to apex by edge worker |

*(Note: `100::` is the official IETF reserved discard IPv6 prefix used by Cloudflare for Worker-only routes).*

### Wildcard Subdomain DNS Explanation
Cloudflare supports wildcard DNS records (`*`) on all plan levels. By proxying `*.mist.me`, any subdomain requested (e.g. `cool-store.mist.me`, `alice-app.mist.me`) is routed through Cloudflare's edge network, where our Workers Route intercepts the request.

---

## Step 3: Create the Cloudflare R2 Bucket

1. In the sidebar, navigate to **R2**.
2. Click **Create bucket**.
3. Bucket name: `mist-published-sites`.
4. Location: Select **Automatic** (or specific preferred region).
5. Click **Create Bucket**.
6. Note: Keep the bucket **Private** (do NOT enable public bucket access). Artifacts are retrieved strictly by the edge Worker via the `PUBLISHED_BUCKET` binding, preventing unauthorized reads or data leaks.

### Generate R2 API Tokens (for Backend Heroku Uploads)
1. In R2 Overview, click **Manage R2 API Tokens**.
2. Click **Create API Token**.
3. Name: `mist-heroku-r2-writer`.
4. Permissions: **Object Read & Write**.
5. Specify bucket: `mist-published-sites`.
6. Click **Create API Token**.
7. Securely record:
   - `Access Key ID` -> `CLOUDFLARE_R2_ACCESS_KEY_ID`
   - `Secret Access Key` -> `CLOUDFLARE_R2_SECRET_ACCESS_KEY`
   - `Endpoint` Account ID -> `CLOUDFLARE_R2_ACCOUNT_ID`

---

## Step 4: Configure Cloudflare Worker Routes & Static Assets

Cloudflare Workers Custom Domains do not support wildcard subdomains (`*.mist.me`) on standard plans. Therefore, the supported Cloudflare architecture utilizes **Workers Routes** bound to the proxied wildcard DNS.

In `cloudflare/wrangler.jsonc`, the routes and bindings are defined:
```jsonc
{
  "name": "mist-edge",
  "main": "src/index.ts",
  "compatibility_date": "2024-11-01",
  "compatibility_flags": ["nodejs_compat"],
  "assets": {
    "directory": "../dist",
    "binding": "ASSETS",
    "html_handling": "auto-trailing-slash",
    "not_found_handling": "single-page-application"
  },
  "r2_buckets": [
    {
      "binding": "PUBLISHED_BUCKET",
      "bucket_name": "mist-published-sites"
    }
  ],
  "routes": [
    { "pattern": "mist.me/*", "zone_name": "mist.me" },
    { "pattern": "*.mist.me/*", "zone_name": "mist.me" }
  ],
  "vars": {
    "APEX_DOMAIN": "mist.me",
    "HEROKU_API_ORIGIN": "https://mist-control-plane-api.herokuapp.com"
  }
}
```

### Deploying the Edge Worker:
1. Build the frontend:
   ```bash
   npm run build
   ```
2. Set the edge origin secret:
   ```bash
   cd cloudflare
   wrangler secret put MIST_EDGE_ORIGIN_SECRET
   # Enter the same 32-byte hex secret configured on Heroku
   ```
3. Deploy:
   ```bash
   wrangler deploy
   ```

---

## Step 5: Enable Bot Protection & DDoS Mitigation

> [!WARNING]
> Adding code to a Worker does **NOT** automatically turn on Bot Fight Mode.
> You must toggle Bot Fight Mode in the Cloudflare Dashboard.

### 1. Enable Bot Fight Mode
1. In Cloudflare Dashboard, select the `mist.me` zone.
2. In the left navigation, go to **Security > Bots**.
3. Under **Bot Fight Mode**, toggle the switch to **On**.
   - *On Pro/Business/Enterprise plans*: Enable **Super Bot Fight Mode** with:
     - Definitely automated: **Block**
     - Likely automated: **Managed Challenge**
     - Static resource protection: **Enabled**

### 2. Verify DDoS Protection
Cloudflare provides automatic Layer 3, 4, and 7 DDoS protection for all proxied traffic.
1. Navigate to **Security > Events**.
2. Verify that **Managed Rulesets** and **HTTP DDoS Attack Protection** are active.
3. Sensitivity can be adjusted under **Security > DDoS** if aggressive attacks are detected.

### 3. Configure WAF Rate Limiting
Protect the Mist control plane API against brute-force and credential stuffing:
1. Navigate to **Security > WAF > Rate limiting rules**.
2. Click **Create rule**.
3. Name: `Protect Mist API Rate Limit`.
4. If incoming request matches:
   - `Hostname equals mist.me` AND `URI Path starts with /api/`
5. Characteristics: `IP`.
6. Requests: `120 requests per 1 minute`.
7. Action: `Managed Challenge` or `Block (Period: 60 seconds)`.
8. Save and deploy.

---

## Step 6: Verify Edge Delivery & Hostname Isolation

Once deployed, verify the endpoints from the terminal:

1. **Verify Edge Health**:
   ```bash
   curl -I https://mist.me/cdn-health
   # Expected: HTTP/2 200, Content-Type: application/json
   ```

2. **Verify Static Asset Immutable Caching**:
   ```bash
   curl -I https://mist.me/assets/index-xxx.js
   # Expected: Cache-Control: public, max-age=31536000, immutable
   # cf-cache-status: HIT
   ```

3. **Verify Reserved Subdomain Rejection**:
   ```bash
   curl -I https://admin.mist.me
   # Expected: HTTP/2 403 Forbidden
   ```

4. **Verify Published Site Delivery from R2**:
   ```bash
   curl -I https://my-portfolio.mist.me
   # Expected: HTTP/2 200, Content-Type: text/html; charset=utf-8
   ```

5. **Verify Edge Origin Secret Injection**:
   ```bash
   curl -I https://mist.me/api/health
   # Worker injects x-mist-edge-secret -> Heroku validates and returns 200
   ```
