# MIST Security Specification

## 1. Data Invariants
1. **User Isolation**: A `users/{userId}` document contains PII (`email`, `displayName`) and can only be read, created, or updated by the authenticated, email-verified user whose `request.auth.uid == userId`.
2. **Account-Bound Credential Vault**: `/users/{userId}/private/{vaultId}` (`vaultId == 'credentials'`) stores AES-256-GCM ciphertext sealed by the server and bound to both `ownerId == request.auth.uid` and `boundEmail == request.auth.token.email`. Plaintext API keys are never persisted in browser `localStorage` or unencrypted Firestore documents.
3. **Project Ownership**: Every `projects/{projectId}` document must have `ownerId == request.auth.uid` on create, `ownerId` is immutable on update, and list queries are strictly restricted to `resource.data.ownerId == request.auth.uid`.
4. **Subcollection Master Gate (Files & Messages)**: Every `projects/{projectId}/files/{fileId}` and `projects/{projectId}/messages/{messageId}` document requires parent `projects/{projectId}` to exist and belong to `request.auth.uid`. `projectId` and `ownerId` are immutable on update.
5. **Deployment Ownership & Public Get**: A `deployments/{slug}` document can be fetched individually (`get`) by anyone with a valid slug ID so published sites load publicly, while `list` is restricted to `resource.data.ownerId == request.auth.uid`, and writes require `ownerId == request.auth.uid` plus existence/ownership of the referenced `projectId`.
6. **Temporal Integrity**: All `createdAt` and `updatedAt` timestamps must equal `request.time`, and `createdAt` is immutable on update.
7. **Strict Schema Enforcement**: No shadow/ghost keys allowed (`keys().hasOnly(...)` on create, `affectedKeys().hasOnly(...)` on update), and every string/ID/array has strict length bounds.

## 2. Dirty Dozen Adversarial Payloads
1. **Shadow Field Injection on User Create**: `{ uid, email, displayName, createdAt, updatedAt, isAdmin: true }` -> MUST FAIL (`hasOnly`).
2. **Cross-User PII & Vault Read**: Authenticated User B attempting `get /users/userA` or `get /users/userA/private/credentials` -> MUST FAIL.
3. **Vault Bound Email Spoofing**: User A attempting to write `/users/userA/private/credentials` with `boundEmail: "victim@example.com"` (`!= request.auth.token.email`) -> MUST FAIL.
4. **Unverified Email Write**: Authenticated user with `email_verified: false` creating a project or credential vault -> MUST FAIL.
5. **Owner Spoofing on Project Create**: User A creating `/projects/p1` with `ownerId: "userB"` -> MUST FAIL.
6. **Owner Hijack on Project Update**: User A updating `/projects/p1` changing `ownerId` -> MUST FAIL.
7. **Project List Scraping**: User A querying `/projects` without `where('ownerId', '==', uid)` -> MUST FAIL (`resource.data.ownerId == request.auth.uid`).
8. **Orphaned File or Message Write**: Creating `/projects/nonexistent/files/f1` or `/projects/nonexistent/messages/m1` -> MUST FAIL (`exists` + `get` parent check).
9. **Cross-Tenant Subcollection Injection**: User B writing to `/projects/userAProject/files/f1` or `/projects/userAProject/messages/m1` -> MUST FAIL.
10. **Oversized ID Poisoning**: Creating `/projects/<150-char-id>` or `/projects/bad$id` -> MUST FAIL (`isValidId`).
11. **Client Timestamp Forgery**: Creating a project or vault with `createdAt: "2020-01-01T00:00:00Z"` instead of `request.time` -> MUST FAIL.
12. **Deployment Slug Hijack & List Scraping**: User B updating `/deployments/userA-site` or listing `/deployments` without owner filter -> MUST FAIL.
