"""
================================================================================
STROKE // SECURE GITHUB PERSONAL ACCESS TOKEN (PAT) INTEGRATION
Provides secure token vault storage (machine-keyed AES/Fernet encryption, no hardcoded keys)
with strict credential state separation (environment vs vault), zero token leakage in logs,
one-time cryptographically bound write approvals, robust pagination, rate-limit defense,
and comprehensive GitHub API operations: Repos, Files, Commits, Branches, Issues, PRs.
================================================================================
"""

import os
import sys
import re
import json
import base64
import hashlib
import uuid
import time
import threading
import logging
from typing import Dict, List, Any, Optional, Tuple
import httpx
from cryptography.fernet import Fernet

import paths_service

logger = logging.getLogger("stroke.github_service")

# Base API domain with HTTPS enforcement
GITHUB_API_BASE = os.getenv("GITHUB_API_BASE", "https://api.github.com").rstrip("/")
if not GITHUB_API_BASE.startswith("https://"):
    GITHUB_API_BASE = "https://api.github.com"

VAULT_DIR = str(paths_service.get_app_data_dir() / "credentials")
KEY_FILE = os.path.join(VAULT_DIR, ".vault_key")
TOKEN_VAULT_FILE = os.path.join(VAULT_DIR, ".github_token.enc")
_LEGACY_VAULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_LEGACY_KEY_FILE = os.path.join(_LEGACY_VAULT_DIR, ".vault_key")
_LEGACY_TOKEN_FILE = os.path.join(_LEGACY_VAULT_DIR, ".github_token.enc")

# Validation regex patterns
REPO_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")
BRANCH_PATTERN = re.compile(r"^[a-zA-Z0-9_./-]+$")
LINK_PATTERN = re.compile(r'<([^>]+)>;\s*rel="([^"]+)"')


# ------------------------------------------------------------------------------
# INPUT SANITIZATION & VALIDATION
# ------------------------------------------------------------------------------
def validate_repo_name(repo: str) -> bool:
    """Validates GitHub repository format 'owner/repo' preventing path traversal."""
    if not repo or not isinstance(repo, str):
        return False
    repo = repo.strip()
    if len(repo) > 200 or ".." in repo:
        return False
    return bool(REPO_PATTERN.match(repo))


def validate_file_path(path: str) -> bool:
    """Validates file path within repository, disallowing path traversal and control chars."""
    if not path or not isinstance(path, str):
        return False
    path = path.strip()
    if path.startswith("/") or ".." in path or "\x00" in path or "\\" in path:
        return False
    return True


def validate_ref_name(ref: Optional[str]) -> bool:
    """Validates git ref or branch name."""
    if not ref:
        return True
    ref = ref.strip()
    if ".." in ref or "\x00" in ref or "\n" in ref or "\r" in ref:
        return False
    return bool(BRANCH_PATTERN.match(ref))


# ------------------------------------------------------------------------------
# SECURE LOCAL TOKEN VAULT (MACHINE IDENTITY ENCRYPTION, 0600 PERMISSIONS)
# ------------------------------------------------------------------------------
def _get_or_create_vault_cipher() -> Fernet:
    """
    Derives or loads an authentic Fernet encryption key stored in stable user application data
    with 0600 file permissions and 0700 directory permissions.
    Refuses to silently overwrite existing damaged keys when encrypted token data exists.
    """
    os.makedirs(VAULT_DIR, exist_ok=True)
    try:
        os.chmod(VAULT_DIR, 0o700)
    except Exception:
        pass

    # 1. Primary stable location
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "rb") as f:
                key = f.read().strip()
                if len(key) == 44:
                    return Fernet(key)
                else:
                    raise ValueError(f"Invalid key length: {len(key)} (expected 44 bytes)")
        except Exception as e:
            backup_key = f"{KEY_FILE}.corrupted.{int(time.time())}.bak"
            try:
                import shutil
                shutil.copy2(KEY_FILE, backup_key)
                logger.error("Preserved snapshot of corrupted GitHub key at %s", backup_key)
            except Exception as copy_err:
                logger.error("Failed to backup corrupted GitHub key: %s", copy_err)

            if os.path.exists(TOKEN_VAULT_FILE) and os.path.getsize(TOKEN_VAULT_FILE) > 0:
                logger.critical("Refusing to silently regenerate key while encrypted token exists: %s", e)
                raise RuntimeError(
                    f"GitHub vault key corrupted at {KEY_FILE}. Preserved snapshot at {backup_key}. "
                    f"Refusing to overwrite key and destroy existing encrypted token: {e}"
                )
            logger.warning("Corrupted key without token file, regenerating: %s", e)

    # 2. Seamless migration from legacy source-directory key and token file
    if not os.path.exists(KEY_FILE) and os.path.exists(_LEGACY_KEY_FILE):
        try:
            with open(_LEGACY_KEY_FILE, "rb") as f:
                legacy_key = f.read().strip()
            if len(legacy_key) == 44:
                fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with open(fd, "wb") as f:
                    f.write(legacy_key)
                logger.info("Migrated legacy GitHub vault key to %s", KEY_FILE)
                if not os.path.exists(TOKEN_VAULT_FILE) and os.path.exists(_LEGACY_TOKEN_FILE):
                    import shutil
                    shutil.copy2(_LEGACY_TOKEN_FILE, TOKEN_VAULT_FILE)
                    os.chmod(TOKEN_VAULT_FILE, 0o600)
                    logger.info("Migrated legacy GitHub encrypted token to %s", TOKEN_VAULT_FILE)
                return Fernet(legacy_key)
        except Exception as mig_err:
            logger.warning("Legacy GitHub vault migration failed: %s", mig_err)

    # 3. Derive key from machine node + local CSPRNG bytes
    machine_id = str(uuid.getnode()).encode("utf-8")
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", machine_id, salt, 100_000)
    key = base64.urlsafe_b64encode(derived[:32])

    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = 0o600  # Read/write for owner only
        fd = os.open(KEY_FILE, flags, mode)
        with open(fd, "wb") as f:
            f.write(key)
    except Exception as e:
        logger.error("Failed to persist secure vault key: %s", e)

    return Fernet(key)


def save_github_token(token: str) -> bool:
    """Encrypts and safely stores GitHub PAT in the local machine vault with 0600 permissions."""
    token = token.strip()
    if not token:
        return False

    try:
        cipher = _get_or_create_vault_cipher()
        encrypted = cipher.encrypt(token.encode("utf-8"))
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = 0o600
        fd = os.open(TOKEN_VAULT_FILE, flags, mode)
        with open(fd, "wb") as f:
            f.write(encrypted)
        logger.info("GitHub PAT encrypted and stored in local machine vault.")
        return True
    except Exception as e:
        logger.error("Failed to save GitHub PAT to secure vault.")
        return False


store_github_token = save_github_token


def _read_vault_token() -> Optional[str]:
    """Reads and decrypts stored PAT from machine vault."""
    if not os.path.exists(TOKEN_VAULT_FILE):
        return None
    try:
        cipher = _get_or_create_vault_cipher()
        with open(TOKEN_VAULT_FILE, "rb") as f:
            encrypted = f.read().strip()
        decrypted = cipher.decrypt(encrypted).decode("utf-8")
        clean = decrypted.strip()
        return clean if clean else None
    except Exception as e:
        logger.warning("Failed to decrypt stored GitHub PAT from vault.")
        return None


def get_stored_github_token(preferred_source: Optional[str] = None) -> Optional[str]:
    """
    Retrieves the GitHub PAT from vault or environment.
    Distinguishes user-managed vault vs environment credentials.
    Never exposes or logs token substrings.
    """
    if preferred_source == "vault":
        return _read_vault_token()
    elif preferred_source == "environment":
        env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT")
        return env_token.strip() if env_token and env_token.strip() else None

    # Priority: environment first if present, otherwise vault
    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT")
    if env_token and env_token.strip():
        return env_token.strip()

    return _read_vault_token()


def get_github_credential_state() -> Dict[str, Any]:
    """
    Returns the distinct credential status indicating whether credentials come from
    process environment (read-only/system managed) or user-managed encrypted vault.
    """
    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT")
    has_env = bool(env_token and env_token.strip())

    vault_token = _read_vault_token()
    has_vault = bool(vault_token and vault_token.strip())

    active_source = "environment" if has_env else ("vault" if has_vault else "none")

    return {
        "has_token": has_env or has_vault,
        "source": active_source,
        "active_source": active_source,
        "is_environment_managed": has_env,
        "is_vault_managed": has_vault
    }


def clear_stored_github_token() -> Dict[str, Any]:
    """
    Removes user-managed stored token from disk vault.
    Accurately reports whether an environment-managed token remains active.
    Never mutates the user's host or process environment.
    """
    vault_cleared = False
    if os.path.exists(TOKEN_VAULT_FILE):
        try:
            os.remove(TOKEN_VAULT_FILE)
            vault_cleared = True
        except Exception as e:
            logger.error("Failed to remove token vault file.")

    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT")
    env_present = bool(env_token and env_token.strip())

    if env_present:
        return {
            "status": "vault_cleared_env_remains",
            "vault_cleared": vault_cleared,
            "environment_token_present": True,
            "active_source": "environment",
            "message": "Vault credential removed, but GITHUB_TOKEN or GITHUB_PAT environment variable remains active in host environment."
        }
    else:
        return {
            "status": "success",
            "vault_cleared": vault_cleared or not os.path.exists(TOKEN_VAULT_FILE),
            "environment_token_present": False,
            "active_source": "none",
            "message": "GitHub Personal Access Token cleared from secure vault."
        }


def get_auth_headers(token: Optional[str] = None) -> Dict[str, str]:
    """Generates GitHub standard headers without exposing secret in logs."""
    t = token or get_stored_github_token()
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Stroke-AI-Assistant/2.0"
    }
    if t:
        headers["Authorization"] = f"Bearer {t}"
    return headers


# ------------------------------------------------------------------------------
# RATE LIMITS, PAGINATION & ERROR HANDLING HELPERS
# ------------------------------------------------------------------------------
def _extract_rate_limit(headers: httpx.Headers) -> Dict[str, Any]:
    """Extracts rate limit metadata from GitHub response headers."""
    remaining = headers.get("x-ratelimit-remaining")
    limit = headers.get("x-ratelimit-limit")
    reset_ts = headers.get("x-ratelimit-reset")
    retry_after = headers.get("retry-after")

    return {
        "remaining": int(remaining) if remaining and remaining.isdigit() else None,
        "limit": int(limit) if limit and limit.isdigit() else None,
        "reset_timestamp": int(reset_ts) if reset_ts and reset_ts.isdigit() else None,
        "retry_after": int(retry_after) if retry_after and retry_after.isdigit() else None
    }


def _parse_link_header(link_header: Optional[str]) -> Dict[str, str]:
    """Parses standard RFC 5988 Link header into relation -> URL mapping."""
    if not link_header:
        return {}
    links: Dict[str, str] = {}
    for part in link_header.split(","):
        match = LINK_PATTERN.search(part.strip())
        if match:
            url, rel = match.groups()
            links[rel] = url
    return links


def _extract_page_number_from_url(url: str) -> Optional[int]:
    """Extracts the page query param from a GitHub pagination URL."""
    match = re.search(r'[?&]page=(\d+)', url)
    return int(match.group(1)) if match else None


def _handle_github_response_error(res: httpx.Response, action_desc: str) -> Dict[str, Any]:
    """Normalizes HTTP errors including 401, 403, 404, 429, and secondary rate limits."""
    rate_info = _extract_rate_limit(res.headers)
    status_code = res.status_code
    body_text = res.text[:250]

    # Secondary or standard rate limit
    is_rate_limited = (
        status_code == 429 or
        (status_code == 403 and (
            rate_info.get("remaining") == 0 or
            "rate limit" in body_text.lower() or
            "secondary rate" in body_text.lower()
        ))
    )
    if is_rate_limited:
        retry_secs = rate_info.get("retry_after") or 60
        return {
            "status": "error",
            "error_type": "rate_limited",
            "status_code": status_code,
            "retry_after": retry_secs,
            "rate_limit_reset": rate_info.get("reset_timestamp"),
            "message": f"GitHub API rate limit exceeded during {action_desc}. Retry after {retry_secs}s."
        }

    if status_code == 401:
        return {
            "status": "error",
            "error_type": "bad_credentials",
            "status_code": 401,
            "message": f"GitHub rejected token during {action_desc}: 401 Bad credentials. Verify token validity and scopes."
        }

    if status_code == 403:
        return {
            "status": "error",
            "error_type": "forbidden",
            "status_code": 403,
            "message": f"GitHub permission denied (HTTP 403) during {action_desc}. Ensure your PAT has required scopes."
        }

    if status_code == 404:
        return {
            "status": "error",
            "error_type": "not_found",
            "status_code": 404,
            "message": f"Resource not found on GitHub (HTTP 404) during {action_desc}."
        }

    return {
        "status": "error",
        "error_type": f"http_{status_code}",
        "status_code": status_code,
        "message": f"GitHub API error (HTTP {status_code}) during {action_desc}: {body_text}"
    }


# ------------------------------------------------------------------------------
# ONE-TIME CRYPTOGRAPHIC APPROVAL MANAGER FOR EXTERNAL WRITE OPERATIONS
# ------------------------------------------------------------------------------
class GitHubApprovalRecord:
    """Stores one-time authorization bound to exact repo, branch, path, and diff hash."""
    def __init__(
        self,
        approval_id: str,
        action: str,
        repo: str,
        operation_hash: str,
        details: Dict[str, Any],
        user_id: Optional[str] = None,
        ttl_seconds: int = 300,
    ):
        self.approval_id = approval_id
        self.action = action
        self.repo = repo
        self.operation_hash = operation_hash
        self.details = details
        self.user_id = user_id
        self.created_at = time.time()
        self.expires_at = self.created_at + ttl_seconds
        self.consumed = False


class GitHubApprovalManager:
    """
    Central approval registry for GitHub external side-effects (writes, commits, PRs, issues, branches).
    Rejects replays, tampered payloads, expired tokens, and cross-user execution.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._records: Dict[str, GitHubApprovalRecord] = {}

    def _cleanup_expired(self):
        now = time.time()
        expired = [aid for aid, r in self._records.items() if now > r.expires_at]
        for aid in expired:
            self._records.pop(aid, None)

    def compute_hash(self, action: str, repo: str, details: Dict[str, Any]) -> str:
        """Computes deterministic canonical SHA-256 bound to action parameters."""
        canonical_str = f"{action}:{repo.lower()}"
        if action == "commit_file":
            canonical_str += f":{details.get('branch', '')}:{details.get('path', '')}:{details.get('commit_message', '')}:{details.get('content_sha256', '')}"
        elif action == "create_branch":
            canonical_str += f":{details.get('new_branch', '')}:{details.get('from_branch', '')}"
        elif action == "create_issue":
            labels_str = ",".join(sorted(details.get("labels") or []))
            canonical_str += f":{details.get('title', '')}:{details.get('body_sha256', '')}:{labels_str}"
        elif action == "create_pull_request":
            canonical_str += f":{details.get('title', '')}:{details.get('head', '')}:{details.get('base', '')}:{details.get('body_sha256', '')}"
        else:
            canonical_str += f":{json.dumps(details, sort_keys=True)}"

        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def create_approval(
        self,
        action: str,
        repo: str,
        details: Dict[str, Any],
        user_id: Optional[str] = None,
        ttl_seconds: int = 300
    ) -> Dict[str, Any]:
        with self._lock:
            self._cleanup_expired()
            approval_id = f"gh_appr_{uuid.uuid4().hex}"
            op_hash = self.compute_hash(action, repo, details)
            record = GitHubApprovalRecord(
                approval_id=approval_id,
                action=action,
                repo=repo,
                operation_hash=op_hash,
                details=details,
                user_id=user_id,
                ttl_seconds=ttl_seconds
            )
            self._records[approval_id] = record
            return {
                "approval_id": approval_id,
                "operation_hash": op_hash,
                "expires_at": record.expires_at,
                "ttl_seconds": ttl_seconds,
                "action": action,
                "repo": repo,
                "details": details
            }

    def validate_and_consume(
        self,
        approval_id: str,
        action: str,
        repo: str,
        details: Dict[str, Any],
        user_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        with self._lock:
            self._cleanup_expired()
            record = self._records.get(approval_id)
            if not record:
                return False, "Approval record not found or expired."
            if record.consumed:
                return False, "Approval record has already been consumed (replay rejected)."
            if time.time() > record.expires_at:
                return False, "Approval record has expired."
            if record.action != action:
                return False, f"Approval action mismatch: expected '{record.action}', got '{action}'."
            if record.repo.lower() != repo.lower():
                return False, f"Approval repository mismatch: expected '{record.repo}', got '{repo}'."
            if record.user_id and user_id and record.user_id != user_id:
                return False, "Approval record belongs to a different authenticated user."

            current_hash = self.compute_hash(action, repo, details)
            if current_hash != record.operation_hash:
                return False, "Operation parameters (diff/content, branch, or message) do not match approved record (hash mismatch)."

            # Atomically consume
            record.consumed = True
            return True, "Approval verified and consumed."


approval_manager = GitHubApprovalManager()


def create_github_approval_record(
    action: str,
    repo: str,
    details: Dict[str, Any],
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Helper to issue a one-time write approval record."""
    return approval_manager.create_approval(action, repo, details, user_id=user_id)


def validate_and_consume_github_approval(
    approval_id: str,
    action: str,
    repo: str,
    details: Dict[str, Any],
    user_id: Optional[str] = None
) -> Tuple[bool, str]:
    """Helper to validate and atomically consume a write approval record."""
    return approval_manager.validate_and_consume(approval_id, action, repo, details, user_id=user_id)


# ------------------------------------------------------------------------------
# GITHUB OPERATIONS: VERIFICATION, REPOSITORIES, CONTENTS, COMMITS, BRANCHES, PRs
# ------------------------------------------------------------------------------
async def verify_pat_connection(token: Optional[str] = None) -> Dict[str, Any]:
    """
    Tests connection to GitHub API and retrieves authenticated user identity,
    rate limits, OAuth scopes, and source information without logging secrets.
    """
    state = get_github_credential_state()
    t = token or get_stored_github_token()
    if not t:
        return {
            "status": "error",
            "connected": False,
            "credential_state": state,
            "message": "No GitHub Personal Access Token configured. Add your token in Stroke settings or set GITHUB_TOKEN."
        }

    headers = get_auth_headers(t)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            user_res = await client.get(f"{GITHUB_API_BASE}/user", headers=headers)
            rate_info = _extract_rate_limit(user_res.headers)
            if user_res.status_code == 200:
                data = user_res.json()
                raw_scopes = user_res.headers.get("x-oauth-scopes", "")
                scopes = [s.strip() for s in raw_scopes.split(",") if s.strip()]
                return {
                    "status": "success",
                    "connected": True,
                    "user": data.get("login"),
                    "name": data.get("name"),
                    "avatar_url": data.get("avatar_url"),
                    "scopes": scopes,
                    "rate_limit": rate_info,
                    "rate_limit_remaining": rate_info.get("remaining"),
                    "credential_state": state,
                    "source": state["active_source"],
                    "is_environment_managed": state["is_environment_managed"],
                    "is_vault_managed": state["is_vault_managed"],
                    "message": f"Successfully connected as @{data.get('login')}"
                }
            elif user_res.status_code == 401:
                return {
                    "status": "error",
                    "connected": False,
                    "error_type": "bad_credentials",
                    "credential_state": state,
                    "message": "GitHub rejected token: 401 Bad credentials. Verify token validity and scopes."
                }
            else:
                err = _handle_github_response_error(user_res, "verify connection")
                err["connected"] = False
                err["credential_state"] = state
                return err
    except Exception as e:
        return {
            "status": "error",
            "connected": False,
            "credential_state": state,
            "message": f"Connection to GitHub failed: {str(e)}"
        }


async def list_repositories(
    visibility: str = "all",
    per_page: int = 30,
    page: int = 1,
    auto_paginate: bool = False,
    max_pages: int = 5
) -> Dict[str, Any]:
    """
    Lists repositories accessible to the configured token with RFC 5988 pagination.
    Supports auto-pagination up to max_pages.
    """
    token = get_stored_github_token()
    if not token:
        return {"status": "error", "error_type": "missing_token", "message": "GITHUB_TOKEN not configured."}

    headers = get_auth_headers(token)
    all_repos: List[Dict[str, Any]] = []
    current_page = max(1, page)
    pages_fetched = 0
    has_next = False
    next_page_num = None
    rate_info: Dict[str, Any] = {}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                params = {"visibility": visibility, "sort": "updated", "per_page": per_page, "page": current_page}
                res = await client.get(f"{GITHUB_API_BASE}/user/repos", headers=headers, params=params)
                rate_info = _extract_rate_limit(res.headers)

                if res.status_code != 200:
                    if pages_fetched > 0:
                        return {
                            "status": "partial_success",
                            "count": len(all_repos),
                            "repos": all_repos,
                            "page": current_page,
                            "warning": f"Pagination interrupted at page {current_page}: HTTP {res.status_code}"
                        }
                    return _handle_github_response_error(res, "list repositories")

                data = res.json()
                if not isinstance(data, list):
                    return {"status": "error", "error_type": "invalid_response", "message": "Unexpected response format from GitHub API."}

                for r in data:
                    all_repos.append({
                        "full_name": r.get("full_name"),
                        "name": r.get("name"),
                        "private": r.get("private"),
                        "description": r.get("description"),
                        "default_branch": r.get("default_branch"),
                        "html_url": r.get("html_url")
                    })

                pages_fetched += 1
                links = _parse_link_header(res.headers.get("link"))
                has_next = "next" in links
                next_page_num = _extract_page_number_from_url(links["next"]) if has_next else None

                if not auto_paginate or not has_next or pages_fetched >= max_pages:
                    break

                current_page = next_page_num if next_page_num else current_page + 1

        return {
            "status": "success",
            "count": len(all_repos),
            "page": page,
            "per_page": per_page,
            "pages_fetched": pages_fetched,
            "has_next": has_next,
            "next_page": next_page_num,
            "rate_limit": rate_info,
            "repos": all_repos
        }
    except Exception as e:
        return {"status": "error", "error_type": "request_failed", "message": f"Failed to list repositories: {str(e)}"}


async def get_file_contents(repo: str, path: str, ref: Optional[str] = None) -> Dict[str, Any]:
    """
    Reads file contents directly from GitHub repository.
    Accurately handles and distinguishes:
    - Directories (returns structured entry list with error_type: 'is_directory')
    - Empty files (size == 0, returns content: '')
    - Text files (UTF-8 decoded content)
    - Binary files (returns is_binary: True, raw_base64, content: None)
    - Large files > 1MB (fetches blob via Git Data Blobs API up to 10MB limit)
    - Files > 10MB (rejected safely with error_type: 'file_too_large')
    - Malformed Base64 decoding errors
    """
    if not validate_repo_name(repo):
        return {"status": "error", "error_type": "invalid_repo", "message": f"Invalid repo format: '{repo}'. Expected 'owner/repo'."}
    if not validate_file_path(path):
        return {"status": "error", "error_type": "invalid_path", "message": f"Invalid file path: '{path}'."}
    if ref and not validate_ref_name(ref):
        return {"status": "error", "error_type": "invalid_ref", "message": f"Invalid git ref: '{ref}'."}

    token = get_stored_github_token()
    if not token:
        return {"status": "error", "error_type": "missing_token", "message": "GITHUB_TOKEN not configured."}

    headers = get_auth_headers(token)
    params = {}
    if ref:
        params["ref"] = ref

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}", headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()

                # 1. Directory response check
                if isinstance(data, list):
                    entries = [{
                        "name": item.get("name"),
                        "path": item.get("path"),
                        "type": item.get("type"),
                        "size": item.get("size"),
                        "sha": item.get("sha")
                    } for item in data if isinstance(item, dict)]
                    return {
                        "status": "error",
                        "error_type": "is_directory",
                        "repo": repo,
                        "path": path,
                        "entries_count": len(entries),
                        "entries": entries,
                        "message": f"Path '{path}' in repository '{repo}' is a directory, not a file."
                    }

                size = data.get("size", 0)
                sha = data.get("sha")

                # 2. Empty file check
                if size == 0:
                    return {
                        "status": "success",
                        "repo": repo,
                        "path": path,
                        "sha": sha,
                        "size": 0,
                        "content": "",
                        "encoding": "utf-8",
                        "is_empty": True,
                        "is_binary": False
                    }

                content_b64 = data.get("content")

                # 3. Large file handling (>1MB where Contents API omits content)
                if size > 1_000_000 or (size > 0 and not content_b64):
                    if size > 10_000_000:
                        return {
                            "status": "error",
                            "error_type": "file_too_large",
                            "repo": repo,
                            "path": path,
                            "sha": sha,
                            "size": size,
                            "message": f"File '{path}' ({size} bytes) exceeds the 10 MB maximum buffer size. Clone repo or download directly."
                        }

                    if sha:
                        blob_res = await client.get(f"{GITHUB_API_BASE}/repos/{repo}/git/blobs/{sha}", headers=headers)
                        if blob_res.status_code == 200:
                            blob_data = blob_res.json()
                            content_b64 = blob_data.get("content")
                        else:
                            return {
                                "status": "error",
                                "error_type": "file_too_large_blob_fetch_failed",
                                "repo": repo,
                                "path": path,
                                "sha": sha,
                                "size": size,
                                "message": f"File '{path}' is too large for inline Contents API and Git Blob fetch returned HTTP {blob_res.status_code}."
                            }
                    else:
                        return {
                            "status": "error",
                            "error_type": "file_too_large",
                            "repo": repo,
                            "path": path,
                            "sha": sha,
                            "size": size,
                            "message": f"File '{path}' is too large for inline Contents API and no Git SHA was provided."
                        }

                # 4. Decode base64 payload
                if not content_b64:
                    return {
                        "status": "error",
                        "error_type": "empty_content_payload",
                        "repo": repo,
                        "path": path,
                        "sha": sha,
                        "size": size,
                        "message": f"GitHub returned no content payload for non-empty file '{path}' ({size} bytes)."
                    }

                try:
                    clean_b64 = content_b64.replace("\n", "").replace("\r", "").strip()
                    raw_bytes = base64.b64decode(clean_b64)
                except Exception as decode_err:
                    return {
                        "status": "error",
                        "error_type": "decoding_error",
                        "repo": repo,
                        "path": path,
                        "sha": sha,
                        "size": size,
                        "message": f"Failed to decode base64 content for '{path}': {decode_err}"
                    }

                # 5. Distinguish text vs binary file
                is_binary = b"\x00" in raw_bytes
                decoded_text = None
                if not is_binary:
                    try:
                        decoded_text = raw_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        is_binary = True

                if is_binary:
                    return {
                        "status": "success",
                        "repo": repo,
                        "path": path,
                        "sha": sha,
                        "size": size,
                        "is_binary": True,
                        "is_empty": False,
                        "content": None,
                        "raw_base64": clean_b64,
                        "message": f"File '{path}' is a binary file ({size} bytes)."
                    }

                return {
                    "status": "success",
                    "repo": repo,
                    "path": path,
                    "sha": sha,
                    "size": size,
                    "content": decoded_text,
                    "encoding": "utf-8",
                    "is_binary": False,
                    "is_empty": False
                }

            return _handle_github_response_error(res, f"read file '{path}' in '{repo}'")
    except Exception as e:
        return {"status": "error", "error_type": "request_failed", "message": f"Failed to read file '{path}': {str(e)}"}


async def commit_file(
    repo: str,
    path: str,
    content: str,
    commit_message: str,
    branch: Optional[str] = None,
    confirmed: bool = False,
    approval_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates or updates a file in a GitHub repository with safety confirmation.
    Binds execution to a one-time cryptographic approval token matching the exact
    repository, branch, path, content SHA-256 hash, and commit message.
    """
    if not validate_repo_name(repo):
        return {"status": "error", "error_type": "invalid_repo", "message": f"Invalid repo format: '{repo}'. Expected 'owner/repo'."}
    if not validate_file_path(path):
        return {"status": "error", "error_type": "invalid_path", "message": f"Invalid file path: '{path}'."}
    if branch and not validate_ref_name(branch):
        return {"status": "error", "error_type": "invalid_branch", "message": f"Invalid target branch: '{branch}'."}

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    details = {
        "path": path,
        "branch": branch or "default",
        "commit_message": commit_message,
        "content_sha256": content_hash
    }

    # Step 1: Confirmation gate
    if not confirmed:
        appr = approval_manager.create_approval("commit_file", repo, details, user_id=user_id)
        prompt_msg = (
            f"Confirmation Required: External GitHub write requested to repository '{repo}' for path '{path}'. "
            f"Please confirm execution before proceeding."
        )
        return {
            "status": "requires_confirmation",
            "tool": "github_commit_file",
            "repo": repo,
            "path": path,
            "branch": branch,
            "commit_message": commit_message,
            "content_sha256": content_hash,
            "approval_id": appr["approval_id"],
            "operation_hash": appr["operation_hash"],
            "expires_at": appr["expires_at"],
            "message": prompt_msg,
            "confirmation_prompt": prompt_msg,
            "requires_confirmation": True
        }

    # Step 2: Token verification
    token = get_stored_github_token()
    if not token:
        return {
            "status": "error",
            "error_type": "missing_token",
            "message": "GITHUB_TOKEN is not configured. Please supply a valid GitHub Personal Access Token in environment or profile."
        }

    # Step 3: Approval record validation & consumption
    if not approval_id:
        return {
            "status": "error",
            "error_type": "approval_required",
            "message": "Direct external writes require a valid server-issued one-time approval ID bound to content/diff hash. 'confirmed=true' alone is not sufficient."
        }

    valid, reason = approval_manager.validate_and_consume(approval_id, "commit_file", repo, details, user_id=user_id)
    if not valid:
        return {
            "status": "error",
            "error_type": "approval_rejected",
            "message": f"Commit authorization failed: {reason}"
        }

    headers = get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Check existing file to obtain SHA if updating
            sha = None
            check_params = {"ref": branch} if branch else {}
            check_res = await client.get(f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}", headers=headers, params=check_params)
            if check_res.status_code == 200:
                data = check_res.json()
                if isinstance(data, dict):
                    sha = data.get("sha")

            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            body: Dict[str, Any] = {
                "message": commit_message,
                "content": encoded
            }
            if sha:
                body["sha"] = sha
            if branch:
                body["branch"] = branch

            put_res = await client.put(f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}", headers=headers, json=body)
            if put_res.status_code in (200, 201):
                data = put_res.json()
                return {
                    "status": "success",
                    "source": "github_mcp",
                    "repo": repo,
                    "path": path,
                    "commit_sha": data.get("commit", {}).get("sha"),
                    "message": f"Successfully committed '{path}' to GitHub repository '{repo}'."
                }
            return _handle_github_response_error(put_res, f"commit '{path}' to '{repo}'")
    except Exception as e:
        return {"status": "error", "error_type": "request_failed", "message": f"GitHub commit failed: {str(e)}"}


async def list_branches(
    repo: str,
    per_page: int = 30,
    page: int = 1,
    auto_paginate: bool = False,
    max_pages: int = 5
) -> Dict[str, Any]:
    """Lists branches in a GitHub repository with pagination."""
    if not validate_repo_name(repo):
        return {"status": "error", "error_type": "invalid_repo", "message": f"Invalid repo format: '{repo}'."}

    token = get_stored_github_token()
    if not token:
        return {"status": "error", "error_type": "missing_token", "message": "GITHUB_TOKEN not configured."}

    headers = get_auth_headers(token)
    all_branches: List[str] = []
    current_page = max(1, page)
    pages_fetched = 0
    has_next = False
    next_page_num = None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                res = await client.get(
                    f"{GITHUB_API_BASE}/repos/{repo}/branches",
                    headers=headers,
                    params={"per_page": per_page, "page": current_page}
                )
                if res.status_code != 200:
                    if pages_fetched > 0:
                        return {
                            "status": "partial_success",
                            "repo": repo,
                            "branches": all_branches,
                            "count": len(all_branches),
                            "warning": f"Pagination stopped at page {current_page}: HTTP {res.status_code}"
                        }
                    return _handle_github_response_error(res, f"list branches for '{repo}'")

                data = res.json()
                if not isinstance(data, list):
                    return {"status": "error", "error_type": "invalid_response", "message": "Unexpected response format."}

                for b in data:
                    name = b.get("name")
                    if name:
                        all_branches.append(name)

                pages_fetched += 1
                links = _parse_link_header(res.headers.get("link"))
                has_next = "next" in links
                next_page_num = _extract_page_number_from_url(links["next"]) if has_next else None

                if not auto_paginate or not has_next or pages_fetched >= max_pages:
                    break

                current_page = next_page_num if next_page_num else current_page + 1

        return {
            "status": "success",
            "repo": repo,
            "count": len(all_branches),
            "page": page,
            "per_page": per_page,
            "has_next": has_next,
            "next_page": next_page_num,
            "branches": all_branches
        }
    except Exception as e:
        return {"status": "error", "error_type": "request_failed", "message": f"Failed to list branches: {str(e)}"}


async def create_branch(
    repo: str,
    new_branch: str,
    from_branch: str = "main",
    confirmed: bool = False,
    approval_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Creates a new git branch in a repository with safety approval record."""
    if not validate_repo_name(repo):
        return {"status": "error", "error_type": "invalid_repo", "message": f"Invalid repo format: '{repo}'."}
    if not validate_ref_name(new_branch):
        return {"status": "error", "error_type": "invalid_branch", "message": f"Invalid new branch name: '{new_branch}'."}
    if not validate_ref_name(from_branch):
        return {"status": "error", "error_type": "invalid_branch", "message": f"Invalid source branch name: '{from_branch}'."}

    details = {"new_branch": new_branch, "from_branch": from_branch}

    if not confirmed:
        appr = approval_manager.create_approval("create_branch", repo, details, user_id=user_id)
        prompt_msg = f"Confirmation Required: Create new git branch '{new_branch}' from '{from_branch}' in '{repo}'?"
        return {
            "status": "requires_confirmation",
            "tool": "github_create_branch",
            "repo": repo,
            "new_branch": new_branch,
            "from_branch": from_branch,
            "approval_id": appr["approval_id"],
            "operation_hash": appr["operation_hash"],
            "expires_at": appr["expires_at"],
            "message": prompt_msg,
            "confirmation_prompt": prompt_msg,
            "requires_confirmation": True
        }

    token = get_stored_github_token()
    if not token:
        return {"status": "error", "error_type": "missing_token", "message": "GITHUB_TOKEN not configured."}

    if not approval_id:
        return {
            "status": "error",
            "error_type": "approval_required",
            "message": "Creating branch requires a valid server-issued one-time approval ID."
        }

    valid, reason = approval_manager.validate_and_consume(approval_id, "create_branch", repo, details, user_id=user_id)
    if not valid:
        return {"status": "error", "error_type": "approval_rejected", "message": f"Branch creation rejected: {reason}"}

    headers = get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            ref_res = await client.get(f"{GITHUB_API_BASE}/repos/{repo}/git/ref/heads/{from_branch}", headers=headers)
            if ref_res.status_code != 200:
                return {"status": "error", "error_type": "source_branch_not_found", "message": f"Source branch '{from_branch}' not found in '{repo}'."}

            sha = ref_res.json().get("object", {}).get("sha")
            create_res = await client.post(
                f"{GITHUB_API_BASE}/repos/{repo}/git/refs",
                headers=headers,
                json={"ref": f"refs/heads/{new_branch}", "sha": sha}
            )
            if create_res.status_code == 201:
                return {
                    "status": "success",
                    "repo": repo,
                    "branch": new_branch,
                    "sha": sha,
                    "message": f"Successfully created branch '{new_branch}' in '{repo}'."
                }
            return _handle_github_response_error(create_res, f"create branch '{new_branch}' in '{repo}'")
    except Exception as e:
        return {"status": "error", "error_type": "request_failed", "message": f"Branch creation error: {str(e)}"}


async def list_issues(
    repo: str,
    state: str = "open",
    per_page: int = 30,
    page: int = 1,
    auto_paginate: bool = False,
    max_pages: int = 5
) -> Dict[str, Any]:
    """Lists issues in a GitHub repository with pagination."""
    if not validate_repo_name(repo):
        return {"status": "error", "error_type": "invalid_repo", "message": f"Invalid repo format: '{repo}'."}

    token = get_stored_github_token()
    if not token:
        return {"status": "error", "error_type": "missing_token", "message": "GITHUB_TOKEN not configured."}

    headers = get_auth_headers(token)
    all_issues: List[Dict[str, Any]] = []
    current_page = max(1, page)
    pages_fetched = 0
    has_next = False
    next_page_num = None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                res = await client.get(
                    f"{GITHUB_API_BASE}/repos/{repo}/issues",
                    headers=headers,
                    params={"state": state, "per_page": per_page, "page": current_page}
                )
                if res.status_code != 200:
                    if pages_fetched > 0:
                        return {
                            "status": "partial_success",
                            "repo": repo,
                            "issues": all_issues,
                            "count": len(all_issues),
                            "warning": f"Pagination stopped at page {current_page}: HTTP {res.status_code}"
                        }
                    return _handle_github_response_error(res, f"list issues for '{repo}'")

                data = res.json()
                if not isinstance(data, list):
                    return {"status": "error", "error_type": "invalid_response", "message": "Unexpected response format."}

                for i in data:
                    if "pull_request" not in i:
                        all_issues.append({
                            "number": i.get("number"),
                            "title": i.get("title"),
                            "state": i.get("state"),
                            "user": i.get("user", {}).get("login"),
                            "html_url": i.get("html_url")
                        })

                pages_fetched += 1
                links = _parse_link_header(res.headers.get("link"))
                has_next = "next" in links
                next_page_num = _extract_page_number_from_url(links["next"]) if has_next else None

                if not auto_paginate or not has_next or pages_fetched >= max_pages:
                    break

                current_page = next_page_num if next_page_num else current_page + 1

        return {
            "status": "success",
            "repo": repo,
            "count": len(all_issues),
            "page": page,
            "per_page": per_page,
            "has_next": has_next,
            "next_page": next_page_num,
            "issues": all_issues
        }
    except Exception as e:
        return {"status": "error", "error_type": "request_failed", "message": f"Failed to list issues: {str(e)}"}


async def create_issue(
    repo: str,
    title: str,
    body: str = "",
    labels: Optional[List[str]] = None,
    confirmed: bool = False,
    approval_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Creates a new issue in a GitHub repository with safety approval record."""
    if not validate_repo_name(repo):
        return {"status": "error", "error_type": "invalid_repo", "message": f"Invalid repo format: '{repo}'."}
    title = title.strip()
    if not title:
        return {"status": "error", "error_type": "invalid_title", "message": "Issue title cannot be empty."}

    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    details = {
        "title": title,
        "body_sha256": body_hash,
        "labels": sorted(labels or [])
    }

    if not confirmed:
        appr = approval_manager.create_approval("create_issue", repo, details, user_id=user_id)
        prompt_msg = f"Confirmation Required: File new GitHub issue '{title}' in '{repo}'?"
        return {
            "status": "requires_confirmation",
            "tool": "github_create_issue",
            "repo": repo,
            "title": title,
            "approval_id": appr["approval_id"],
            "operation_hash": appr["operation_hash"],
            "expires_at": appr["expires_at"],
            "message": prompt_msg,
            "confirmation_prompt": prompt_msg,
            "requires_confirmation": True
        }

    token = get_stored_github_token()
    if not token:
        return {"status": "error", "error_type": "missing_token", "message": "GITHUB_TOKEN not configured."}

    if not approval_id:
        return {
            "status": "error",
            "error_type": "approval_required",
            "message": "Filing an issue requires a valid server-issued one-time approval ID."
        }

    valid, reason = approval_manager.validate_and_consume(approval_id, "create_issue", repo, details, user_id=user_id)
    if not valid:
        return {"status": "error", "error_type": "approval_rejected", "message": f"Issue creation rejected: {reason}"}

    headers = get_auth_headers(token)
    payload: Dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(f"{GITHUB_API_BASE}/repos/{repo}/issues", headers=headers, json=payload)
            if res.status_code == 201:
                data = res.json()
                return {
                    "status": "success",
                    "repo": repo,
                    "issue_number": data.get("number"),
                    "url": data.get("html_url"),
                    "message": f"Created Issue #{data.get('number')} in '{repo}'."
                }
            return _handle_github_response_error(res, f"create issue in '{repo}'")
    except Exception as e:
        return {"status": "error", "error_type": "request_failed", "message": f"Issue creation error: {str(e)}"}


async def list_pull_requests(
    repo: str,
    state: str = "open",
    per_page: int = 30,
    page: int = 1,
    auto_paginate: bool = False,
    max_pages: int = 5
) -> Dict[str, Any]:
    """Lists pull requests in a GitHub repository with pagination."""
    if not validate_repo_name(repo):
        return {"status": "error", "error_type": "invalid_repo", "message": f"Invalid repo format: '{repo}'."}

    token = get_stored_github_token()
    if not token:
        return {"status": "error", "error_type": "missing_token", "message": "GITHUB_TOKEN not configured."}

    headers = get_auth_headers(token)
    all_prs: List[Dict[str, Any]] = []
    current_page = max(1, page)
    pages_fetched = 0
    has_next = False
    next_page_num = None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                res = await client.get(
                    f"{GITHUB_API_BASE}/repos/{repo}/pulls",
                    headers=headers,
                    params={"state": state, "per_page": per_page, "page": current_page}
                )
                if res.status_code != 200:
                    if pages_fetched > 0:
                        return {
                            "status": "partial_success",
                            "repo": repo,
                            "pull_requests": all_prs,
                            "count": len(all_prs),
                            "warning": f"Pagination stopped at page {current_page}: HTTP {res.status_code}"
                        }
                    return _handle_github_response_error(res, f"list pull requests for '{repo}'")

                data = res.json()
                if not isinstance(data, list):
                    return {"status": "error", "error_type": "invalid_response", "message": "Unexpected response format."}

                for p in data:
                    all_prs.append({
                        "number": p.get("number"),
                        "title": p.get("title"),
                        "state": p.get("state"),
                        "user": p.get("user", {}).get("login"),
                        "html_url": p.get("html_url")
                    })

                pages_fetched += 1
                links = _parse_link_header(res.headers.get("link"))
                has_next = "next" in links
                next_page_num = _extract_page_number_from_url(links["next"]) if has_next else None

                if not auto_paginate or not has_next or pages_fetched >= max_pages:
                    break

                current_page = next_page_num if next_page_num else current_page + 1

        return {
            "status": "success",
            "repo": repo,
            "count": len(all_prs),
            "page": page,
            "per_page": per_page,
            "has_next": has_next,
            "next_page": next_page_num,
            "pull_requests": all_prs
        }
    except Exception as e:
        return {"status": "error", "error_type": "request_failed", "message": f"Failed to list PRs: {str(e)}"}


async def create_pull_request(
    repo: str,
    title: str,
    head: str,
    base: str = "main",
    body: str = "",
    confirmed: bool = False,
    approval_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Creates a pull request on GitHub with safety approval record."""
    if not validate_repo_name(repo):
        return {"status": "error", "error_type": "invalid_repo", "message": f"Invalid repo format: '{repo}'."}
    title = title.strip()
    if not title:
        return {"status": "error", "error_type": "invalid_title", "message": "Pull request title cannot be empty."}
    if not validate_ref_name(head):
        return {"status": "error", "error_type": "invalid_branch", "message": f"Invalid head branch: '{head}'."}
    if not validate_ref_name(base):
        return {"status": "error", "error_type": "invalid_branch", "message": f"Invalid base branch: '{base}'."}

    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    details = {
        "title": title,
        "head": head,
        "base": base,
        "body_sha256": body_hash
    }

    if not confirmed:
        appr = approval_manager.create_approval("create_pull_request", repo, details, user_id=user_id)
        prompt_msg = f"Confirmation Required: Open Pull Request '{title}' ({head} -> {base}) in repository '{repo}'?"
        return {
            "status": "requires_confirmation",
            "tool": "github_create_pull_request",
            "repo": repo,
            "title": title,
            "head": head,
            "base": base,
            "approval_id": appr["approval_id"],
            "operation_hash": appr["operation_hash"],
            "expires_at": appr["expires_at"],
            "message": prompt_msg,
            "confirmation_prompt": prompt_msg,
            "requires_confirmation": True
        }

    token = get_stored_github_token()
    if not token:
        return {"status": "error", "error_type": "missing_token", "message": "GITHUB_TOKEN not configured."}

    if not approval_id:
        return {
            "status": "error",
            "error_type": "approval_required",
            "message": "Opening a pull request requires a valid server-issued one-time approval ID."
        }

    valid, reason = approval_manager.validate_and_consume(approval_id, "create_pull_request", repo, details, user_id=user_id)
    if not valid:
        return {"status": "error", "error_type": "approval_rejected", "message": f"Pull request creation rejected: {reason}"}

    headers = get_auth_headers(token)
    payload = {"title": title, "head": head, "base": base, "body": body}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(f"{GITHUB_API_BASE}/repos/{repo}/pulls", headers=headers, json=payload)
            if res.status_code == 201:
                data = res.json()
                return {
                    "status": "success",
                    "repo": repo,
                    "pr_number": data.get("number"),
                    "url": data.get("html_url"),
                    "message": f"Successfully opened Pull Request #{data.get('number')} in '{repo}'."
                }
            return _handle_github_response_error(res, f"create PR in '{repo}'")
    except Exception as e:
        return {"status": "error", "error_type": "request_failed", "message": f"Failed to open PR: {str(e)}"}
