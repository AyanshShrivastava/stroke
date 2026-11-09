"""
================================================================================
STROKE // SECURE GITHUB PERSONAL ACCESS TOKEN (PAT) INTEGRATION
Provides secure token vault storage (machine-keyed AES/Fernet encryption, no hardcoded keys)
and comprehensive GitHub API operations: Repos, Files, Commits, Branches, Issues, PRs, Actions.
================================================================================
"""

import os
import sys
import json
import base64
import hashlib
import uuid
import logging
from typing import Dict, List, Any, Optional
import httpx
from cryptography.fernet import Fernet

logger = logging.getLogger("stroke.github_service")

GITHUB_API_BASE = "https://api.github.com"
VAULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
KEY_FILE = os.path.join(VAULT_DIR, ".vault_key")
TOKEN_VAULT_FILE = os.path.join(VAULT_DIR, ".github_token.enc")


# ------------------------------------------------------------------------------
# SECURE LOCAL TOKEN VAULT (NO HARDCODED KEYS)
# ------------------------------------------------------------------------------
def _get_or_create_vault_cipher() -> Fernet:
    """
    Derives an authentic Fernet encryption key based on machine identity and a locally
    generated secure random salt with 0600 file permissions. Never uses hardcoded keys.
    """
    os.makedirs(VAULT_DIR, exist_ok=True)
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "rb") as f:
                key = f.read().strip()
                if len(key) == 44:
                    return Fernet(key)
        except Exception as e:
            logger.warning(f"Failed to read vault key: {e}")

    # Derive key from machine node + local CSPRNG bytes
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
        logger.error(f"Failed to persist vault key: {e}")

    return Fernet(key)


def save_github_token(token: str) -> bool:
    """Encrypts and safely stores GitHub PAT in the local machine vault."""
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
        return True
    except Exception as e:
        logger.error(f"Failed to save GitHub PAT: {e}")
        return False


def get_stored_github_token() -> Optional[str]:
    """Retrieves and decrypts the GitHub PAT from the vault or environment."""
    # Environment variable has priority
    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT")
    if env_token and env_token.strip():
        return env_token.strip()

    if not os.path.exists(TOKEN_VAULT_FILE):
        return None

    try:
        cipher = _get_or_create_vault_cipher()
        with open(TOKEN_VAULT_FILE, "rb") as f:
            encrypted = f.read().strip()
        decrypted = cipher.decrypt(encrypted).decode("utf-8")
        return decrypted.strip()
    except Exception as e:
        logger.warning(f"Failed to decrypt stored GitHub PAT: {e}")
        return None


def clear_stored_github_token() -> bool:
    """Removes stored token from disk."""
    if os.path.exists(TOKEN_VAULT_FILE):
        try:
            os.remove(TOKEN_VAULT_FILE)
            return True
        except Exception:
            return False
    return True


def get_auth_headers(token: Optional[str] = None) -> Dict[str, str]:
    t = token or get_stored_github_token()
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Stroke-AI-Assistant/2.0"
    }
    if t:
        headers["Authorization"] = f"Bearer {t}"
    return headers


# ------------------------------------------------------------------------------
# GITHUB OPERATIONS WITH SAFETY APPROVAL GUARDS
# ------------------------------------------------------------------------------
async def verify_pat_connection(token: Optional[str] = None) -> Dict[str, Any]:
    """Tests connection to GitHub API and retrieves user info, rate limits, and scopes."""
    t = token or get_stored_github_token()
    if not t:
        return {
            "status": "error",
            "connected": False,
            "message": "No GitHub Personal Access Token configured. Add your token in Stroke settings."
        }

    headers = get_auth_headers(t)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            user_res = await client.get(f"{GITHUB_API_BASE}/user", headers=headers)
            if user_res.status_code == 200:
                data = user_res.json()
                scopes = user_res.headers.get("x-oauth-scopes", "").split(", ")
                rate_limit = user_res.headers.get("x-ratelimit-remaining", "?")
                return {
                    "status": "success",
                    "connected": True,
                    "user": data.get("login"),
                    "name": data.get("name"),
                    "avatar_url": data.get("avatar_url"),
                    "scopes": [s.strip() for s in scopes if s.strip()],
                    "rate_limit_remaining": rate_limit,
                    "message": f"Successfully connected as @{data.get('login')}"
                }
            elif user_res.status_code == 401:
                return {
                    "status": "error",
                    "connected": False,
                    "message": "GitHub rejected token: 401 Bad credentials. Verify token validity and scopes."
                }
            else:
                return {
                    "status": "error",
                    "connected": False,
                    "message": f"GitHub API returned HTTP {user_res.status_code}: {user_res.text[:150]}"
                }
    except Exception as e:
        return {
            "status": "error",
            "connected": False,
            "message": f"Connection to GitHub failed: {str(e)}"
        }


async def list_repositories(visibility: str = "all", per_page: int = 30) -> Dict[str, Any]:
    token = get_stored_github_token()
    if not token:
        return {"status": "error", "message": "GITHUB_TOKEN not configured."}

    headers = get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(
                f"{GITHUB_API_BASE}/user/repos",
                headers=headers,
                params={"visibility": visibility, "sort": "updated", "per_page": per_page}
            )
            if res.status_code == 200:
                repos = [{
                    "full_name": r.get("full_name"),
                    "private": r.get("private"),
                    "description": r.get("description"),
                    "default_branch": r.get("default_branch"),
                    "html_url": r.get("html_url")
                } for r in res.json()]
                return {"status": "success", "count": len(repos), "repos": repos}
            return {"status": "error", "message": f"GitHub HTTP {res.status_code}: {res.text[:150]}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to list repositories: {str(e)}"}


async def get_file_contents(repo: str, path: str, ref: Optional[str] = None) -> Dict[str, Any]:
    token = get_stored_github_token()
    if not token:
        return {"status": "error", "message": "GITHUB_TOKEN not configured."}

    headers = get_auth_headers(token)
    params = {}
    if ref:
        params["ref"] = ref

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}", headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                content_b64 = data.get("content", "")
                decoded = base64.b64decode(content_b64).decode("utf-8", errors="replace") if content_b64 else ""
                return {
                    "status": "success",
                    "repo": repo,
                    "path": path,
                    "sha": data.get("sha"),
                    "size": data.get("size"),
                    "content": decoded
                }
            return {"status": "error", "message": f"File '{path}' not found or HTTP {res.status_code} in '{repo}'."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to read file '{path}': {str(e)}"}


async def commit_file(
    repo: str,
    path: str,
    content: str,
    commit_message: str,
    branch: Optional[str] = None,
    confirmed: bool = False
) -> Dict[str, Any]:
    """Creates or updates a file in a GitHub repository with safety confirmation."""
    if not confirmed:
        return {
            "status": "requires_confirmation",
            "tool": "github_commit_file",
            "repo": repo,
            "path": path,
            "commit_message": commit_message,
            "message": f"Confirmation Required: External GitHub write requested to repository '{repo}' for path '{path}'. Please confirm execution before proceeding.",
            "requires_confirmation": True
        }

    token = get_stored_github_token()
    if not token:
        return {
            "status": "error",
            "message": "GITHUB_TOKEN is not configured. Please supply a valid GitHub Personal Access Token in environment or profile."
        }

    headers = get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Check existing file to obtain SHA if updating
            sha = None
            check_params = {"ref": branch} if branch else {}
            check_res = await client.get(f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}", headers=headers, params=check_params)
            if check_res.status_code == 200:
                sha = check_res.json().get("sha")

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
            return {
                "status": "error",
                "message": f"GitHub API rejected commit (HTTP {put_res.status_code}): {put_res.text[:200]}"
            }
    except Exception as e:
        return {"status": "error", "message": f"GitHub commit failed: {str(e)}"}


async def list_branches(repo: str) -> Dict[str, Any]:
    token = get_stored_github_token()
    if not token:
        return {"status": "error", "message": "GITHUB_TOKEN not configured."}

    headers = get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(f"{GITHUB_API_BASE}/repos/{repo}/branches", headers=headers)
            if res.status_code == 200:
                branches = [b.get("name") for b in res.json()]
                return {"status": "success", "repo": repo, "branches": branches}
            return {"status": "error", "message": f"GitHub HTTP {res.status_code}: {res.text[:150]}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to list branches: {str(e)}"}


async def create_branch(repo: str, new_branch: str, from_branch: str = "main", confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        return {
            "status": "requires_confirmation",
            "tool": "github_create_branch",
            "repo": repo,
            "new_branch": new_branch,
            "from_branch": from_branch,
            "message": f"Confirmation Required: Create new git branch '{new_branch}' from '{from_branch}' in '{repo}'?",
            "requires_confirmation": True
        }

    token = get_stored_github_token()
    if not token:
        return {"status": "error", "message": "GITHUB_TOKEN not configured."}

    headers = get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            ref_res = await client.get(f"{GITHUB_API_BASE}/repos/{repo}/git/ref/heads/{from_branch}", headers=headers)
            if ref_res.status_code != 200:
                return {"status": "error", "message": f"Source branch '{from_branch}' not found."}

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
                    "message": f"Successfully created branch '{new_branch}' in '{repo}'."
                }
            return {"status": "error", "message": f"GitHub rejected branch creation: {create_res.text[:150]}"}
    except Exception as e:
        return {"status": "error", "message": f"Branch creation error: {str(e)}"}


async def list_issues(repo: str, state: str = "open") -> Dict[str, Any]:
    token = get_stored_github_token()
    if not token:
        return {"status": "error", "message": "GITHUB_TOKEN not configured."}

    headers = get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(f"{GITHUB_API_BASE}/repos/{repo}/issues", headers=headers, params={"state": state})
            if res.status_code == 200:
                issues = [{
                    "number": i.get("number"),
                    "title": i.get("title"),
                    "state": i.get("state"),
                    "user": i.get("user", {}).get("login"),
                    "html_url": i.get("html_url")
                } for i in res.json() if "pull_request" not in i]
                return {"status": "success", "repo": repo, "issues": issues}
            return {"status": "error", "message": f"GitHub HTTP {res.status_code}: {res.text[:150]}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to list issues: {str(e)}"}


async def create_issue(repo: str, title: str, body: str = "", labels: Optional[List[str]] = None, confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        return {
            "status": "requires_confirmation",
            "tool": "github_create_issue",
            "repo": repo,
            "title": title,
            "message": f"Confirmation Required: File new GitHub issue '{title}' in '{repo}'?",
            "requires_confirmation": True
        }

    token = get_stored_github_token()
    if not token:
        return {"status": "error", "message": "GITHUB_TOKEN not configured."}

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
            return {"status": "error", "message": f"GitHub rejected issue creation: {res.text[:150]}"}
    except Exception as e:
        return {"status": "error", "message": f"Issue creation error: {str(e)}"}


async def create_pull_request(repo: str, title: str, head: str, base: str = "main", body: str = "", confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        return {
            "status": "requires_confirmation",
            "tool": "github_create_pull_request",
            "repo": repo,
            "title": title,
            "head": head,
            "base": base,
            "message": f"Confirmation Required: Open Pull Request '{title}' ({head} -> {base}) in repository '{repo}'?",
            "requires_confirmation": True
        }

    token = get_stored_github_token()
    if not token:
        return {"status": "error", "message": "GITHUB_TOKEN not configured."}

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
            return {"status": "error", "message": f"GitHub rejected PR: {res.text[:200]}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to open PR: {str(e)}"}


async def list_pull_requests(repo: str, state: str = "open") -> Dict[str, Any]:
    token = get_stored_github_token()
    if not token:
        return {"status": "error", "message": "GITHUB_TOKEN not configured."}

    headers = get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(f"{GITHUB_API_BASE}/repos/{repo}/pulls", headers=headers, params={"state": state})
            if res.status_code == 200:
                prs = [{
                    "number": p.get("number"),
                    "title": p.get("title"),
                    "state": p.get("state"),
                    "user": p.get("user", {}).get("login"),
                    "html_url": p.get("html_url")
                } for p in res.json()]
                return {"status": "success", "repo": repo, "pull_requests": prs}
            return {"status": "error", "message": f"GitHub HTTP {res.status_code}: {res.text[:150]}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to list PRs: {str(e)}"}
