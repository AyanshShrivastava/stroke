# Mist Security Policy & Technical Architecture

This document outlines the security controls, cryptographic implementations, network boundaries, and threat model enforced across **Mist**.

---

## 1. Authentication & Identity Management

### Sole Identity Provider: Clerk
* **Clerk Exclusivity**: Mist relies solely on Clerk for identity, sign-in, MFA, and session lifecycle.
* **Complete Removal of Firebase Auth**: Direct client-side Firebase Auth SDK, custom token bridges, and client-side database rules have been completely removed.
* **Canonical User Identity**: The canonical account owner ID is strictly the Clerk User ID (`user_...`).
* **Session Verification**: The Express backend uses `@clerk/express` (`verifyAuthHeader` / `requireVerifiedAuth`) to verify cryptographically signed JWT session tokens on every protected endpoint.
* **Email Verification**: Sensitive operations (e.g. credential vault sealing and cloud project synchronization) require `emailVerified: true` from Clerk claims.

---

## 2. Credential Vault & Cryptographic Protections

Mist includes a server-side authenticated credential vault for storing user-supplied third-party credentials (e.g. Render API keys, BYOK AI keys, search keys).

### Cryptographic Specification
* **Cipher**: `AES-256-GCM` (Galois/Counter Mode) authenticated encryption.
* **Key Derivation**: `HKDF-SHA256` (RFC 5869).
  * Master secret: `MIST_VAULT_SECRET` (strictly enforced to be at least 32 high-entropy characters in production).
  * Salt: User's normalized canonical email address (`email.trim().toLowerCase()`).
  * Info parameter: Account UID (`uid:mist-credential-vault-v1`).
  * Derived Key: 32 bytes (256 bits).
* **Authenticated Additional Data (AAD)**: The envelope binds `user.userId` and normalized email as AAD. Decryption fails if ciphertext is substituted or transferred across accounts.
* **Envelope Format**: Base64-encoded JSON envelope with schema `{ v: 1, iv: "...", tag: "...", ct: "..." }`.
  * `iv`: 12-byte cryptographically secure random initialization vector (`crypto.randomBytes(12)`).
  * `tag`: 16-byte GCM authentication tag (`cipher.getAuthTag()`).
  * `ct`: Ciphertext encrypted data.

### Storage Isolation Rules
1. **Zero Browser LocalStorage**: Raw API keys are never stored in browser `localStorage`, IndexedDB, or cookies.
2. **Zero Firestore Plaintext Fields**: Raw keys are never written to unencrypted Firestore fields. Firestore stores only the ciphertext envelope and a masked key hint (`rnd_••••••••` or `sk-o••••cdef`).
3. **Session-Only Keys**: Users can flag credentials as "session-only". Session-only keys remain in server memory for the duration of the active request and are discarded immediately.
4. **Zero-Downtime Key Rotation**: Supports `MIST_VAULT_PREVIOUS_SECRETS`. The vault unseals records encrypted with older keys and automatically re-encrypts them under the active `MIST_VAULT_SECRET` just-in-time.
5. **Legacy Migration Safeguard**: Dev-fallback decryption is disabled by default in production and only active when `ALLOW_LEGACY_VAULT_MIGRATION="true"`.

---

## 3. Multi-Tenant Project & Data Isolation

* **Owner-Checked Operations**: Every project read, update, list, and delete operation verifies that `project.ownerId === authUser.userId`.
* **Cross-Account Overwrite Rejection**: If User B attempts to write or update a project ID owned by User A, the backend immediately rejects the request with `403 Forbidden`.
* **Guest Draft Separation**: Anonymous/guest local storage keys (`mist_projects_anonymous`) are strictly isolated from account-scoped keys (`mist_projects_user_...`). Signing out does not wipe local projects, and switching accounts never transfers or merges projects across accounts.
* **Batched Synchronization Queue**: The dirty synchronization queue is account-scoped (`mist_dirty_projects_<userId>`). Requests to sync projects with mismatched owner IDs are dropped and logged.

---

## 4. Public Website Origin Isolation & Sandboxing

Serving user-generated HTML/JavaScript on the same origin as the web builder creates a critical stored-XSS vulnerability. Mist implements complete physical origin separation:

```
[ Application Builder ]                          [ Published Websites ]
Origin: https://mist.me                          Origin: https://<slug>.mist-sites.com
- Clerk Auth Cookies                             - NO Clerk Auth Cookies
- LocalStorage Access                            - NO LocalStorage Access
- API Control Plane                              - Strict Sandboxed Iframe/CSP
```

### Origin Isolation Controls
1. **Dedicated Hostname**: Published sites are served from `PUBLISH_BASE_URL` (e.g. `https://*.mist-sites.com`), never on the builder origin `https://mist.me`.
2. **Old Public Routes Disabled**: Route `/p/:slug` on the builder origin permanently redirects (`301 Moved Permanently`) to the dedicated domain. If `PUBLISH_BASE_URL` is omitted, public execution is safely disabled (`404 Not Found`).
3. **Cookie Partitioning**: Authentication cookies are scoped strictly to the application domain (`Domain=mist.me`) and never use parent-domain wildcard cookies (`Domain=.mist.me`), preventing token leakage to published subdomains.
4. **Sandboxed Content Security Policy (CSP)**:
   * Edge Worker injects: `Content-Security-Policy: sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' https:; style-src 'unsafe-inline' https:; img-src data: https: blob:; font-src https: data:; connect-src https:; frame-ancestors *;`
   * Notice `allow-same-origin` is omitted, ensuring published code cannot access the origin's cookies, storage, or permissions.
5. **Preview Iframes**: In-app previews use `sandbox="allow-scripts"` without `allow-same-origin` and communicate only via structured `postMessage`.

---

## 5. Express Backend & API Hardening

### Request Validation & Route-Specific Body Limits
* Route-specific JSON body parsers prevent resource exhaustion and denial-of-service:
  * Authentication, vault, notifications: `100KB` max limit.
  * Project sync & publish bundles: `5MB` max limit.
* Validates file paths to reject path traversal attempts (e.g. `../etc/passwd`).
* Prohibits prototype pollution properties (`__proto__`, `constructor.prototype`).

### Server-Side Request Forgery (SSRF) Protection
All outbound requests from the backend (Web Search, BYOK endpoints, push notification endpoints) pass through `safeFetchExternal` and `isPrivateIpAddress`:
* **Blocked IP Ranges**:
  * Loopback: `127.0.0.0/8`, `::1`
  * Private RFC 1918: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
  * Link-Local & Cloud Metadata: `169.254.169.254`, `169.254.0.0/16`, `fe80::/10`
* **DNS Rebinding & Redirect Protection**: Re-verifies resolved IP addresses before establishing TCP sockets and re-evaluates all HTTP redirect target locations.

### Rate Limiting & Abuse Prevention
* **Route-Specific Limits**: Configured across AI generation, project sync, search, and credential vault operations.
* **Distributed Adapter Architecture**: Includes `MistRateLimitAdapter` interface for production multi-instance clusters (e.g. Redis), backed by a safe in-memory fallback for standalone nodes.

### Global Secret Redaction
* Automatically scrubs API keys (`sk-or-v1-...`, `AIzaSy...`, `rnd_...`, `BSA...`), Bearer tokens, passwords, database URIs, JWTs, and private keys from all console logs and API error responses via `redactSecrets` and `sanitizeErrorMessage`.

---

## 6. Vulnerability Reporting

If you discover a security vulnerability in Mist:
1. Please email **security@mist.me** (or project maintainers directly).
2. Do not open public GitHub issues for security vulnerabilities.
3. Include detailed steps to reproduce, affected endpoints, and impact assessment.
4. We aim to acknowledge reports within 24 hours and provide resolution timelines.
