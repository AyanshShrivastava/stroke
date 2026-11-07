# Stroke // Secure Cyberpunk Application Stack

> Stateless FastAPI REST backend integrated with Firebase Firestore database layer, GitHub OAuth Personal Access Token (PAT) flow, and a high-contrast Matrix Green Cyberpunk Web UI with reactive terminal telemetry.

---

## ⚡ System Architecture

1. **Application Identity**:
   - System Name: **Stroke**
   - Core Architecture: Stateless FastAPI REST backend integrated with Firebase Firestore via `firebase-admin` SDK.
   - User Interface: Single-file Cyberpunk web interface embedding responsive layouts, vanilla JavaScript asynchronous network controllers, and a reactive terminal telemetry monitor.

2. **Firestore Data Architecture & Persistence**:
   - Completely stateless: No local dictionaries or in-memory session caches.
   - Root Collection Path: `users`
   - Document ID: Lowercased user email address string (`users/{email}`).
   - Root Document Schema:
     - `email` (string): Lowercase email identity.
     - `github_token` (string | null): Personal Access Token from OAuth redirection loop.
     - `database_fed` (boolean): Flag tracking if 5x database matrix has been injected.
     - `otp_code` (string | null): Active 6-digit authentication session string.
     - `otp_expires_at` (timestamp | null): UTC expiry date-time marker.
   - Sub-Collection Path: Injected records nested at `users/{email}/records/`.

3. **Secure Email OTP Verification**:
   - `POST /auth/send-otp`: Generates cryptographically secure 6-digit token, performs atomic write transaction to `users/{email}` with 5-minute expiry, and logs token to server stdout.
   - `POST /auth/verify-otp`: Atomic lookup, validation against current server time, and clean state purge (clearing `otp_code` and `otp_expires_at` to `null`).

4. **GitHub OAuth Redirection Loop & PAT Generation**:
   - `GET /auth/github-connect`: Computes cryptographic compound state hex and routes client to GitHub OAuth Gateway with scopes: `repo`, `read:user`, `user:email`.
   - `GET /auth/github/callback`: Exchanges authorization code for access token via background async HTTP POST, and atomically updates `users/{email}.github_token`.

5. **5X High-Density Database Injection Matrix**:
   - `POST /database/feed-5x`: Uses `db.batch()` to process exactly 5 independent structural log documents into `users/{email}/records/` (`STRK-BAT-001` through `STRK-BAT-005`) with bounded metric load (85.5 to 100.0) and 8-byte hex integrity hash, atomically flipping `database_fed = true`.

---

## 🚀 Quickstart

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your Firebase and GitHub credentials
```

### 3. Launch Backend & Web Interface
```bash
uvicorn main:app --reload --port 8000
```
Open [http://localhost:8000](http://localhost:8000) to access the Cyberpunk Matrix Operations Console.
