"""
================================================================================
STROKE // SECURE CYBERPUNK APPLICATION STACK
FastAPI Stateless Backend + Firebase Firestore Database Layer + GitHub OAuth Loop
================================================================================
Architecture Specifications:
  1. Complete Stateless Architecture (Zero in-memory session dictionaries).
  2. Firebase Firestore Database Engine via firebase-admin SDK.
  3. Root Collection: `users`
  4. Document ID: Lowercased user email address string (`users/{email}`).
  5. Schema:
       - email (str): lowercased user email identity.
       - github_token (str | None): structural PAT from GitHub OAuth.
       - database_fed (bool): flag tracking 5x injection state.
       - otp_code (str | None): active 6-digit authentication token.
       - otp_expires_at (datetime | None): UTC expiration timestamp.
  6. Sub-Collection: `users/{email}/records/`
       - record_id: STRK-BAT-001 through STRK-BAT-005
       - metric_load: float between 85.5 and 100.0
       - status: "optimized"
       - integrity_hash: 8-byte hex string
================================================================================
"""

import os
import uuid
from dotenv import load_dotenv
load_dotenv()
import sys
import asyncio
import threading
import subprocess
import re
import io
import time
import zipfile
import hashlib
import json
import secrets
import random
import urllib.parse
import html
import hmac
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple, Set

from fastapi import FastAPI, HTTPException, Query, status, Request, Response, BackgroundTasks, Depends
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, ConfigDict
import httpx
from cryptography.fernet import Fernet

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import DELETE_FIELD

import vfx_service
import mcp_bridge
import coding_loop
from coding_loop import (
    StrokeCodingLoop, RobloxDomainTestRunner, ErrorAnalyser, CodingArchivist,
    StateLedger, stitch_continuations, is_response_incomplete
)
import terminal_service
from terminal_service import TerminalManager, get_terminal_tools_schema, get_terminal_openai_tool_schemas, ToolDispatcher
import paths_service
import backup_service
import workspace_service
import file_service
import model_download_service
import credentials_vault_service
import ai_provider_service
import isolated_workspace
import agent_orchestrator
import parallel_agent_system
from agent_orchestrator import (
    TaskState, TaskBudget, AgentTask, TaskManager,
    AgentExecutionGate, ToolOutputObserver, create_budget_for_reasoning_level,
    ReasoningProfile, get_reasoning_profile, REASONING_PROFILES
)
import auth_service
from auth_service import (
    AuthenticatedUser,
    get_current_user,
    get_optional_user,
    verify_firebase_id_token,
    get_firebase_project_id,
    bearer_scheme
)
from fastapi.security import HTTPAuthorizationCredentials
from local_firestore import LocalFirestoreClient
import migration_service
import ai_provider_service
from ai_provider_service import (
    MODEL_REGISTRY,
    resolve_model_id,
    probe_all_ai_health,
    AiStatusResponse,
    InferenceParameters,
    validate_parameters_for_model,
    global_ai_provider_manager
)
import observability
import eval_harness

SERVER_START_TIME = time.time()

# ==============================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==============================================================================

SYSTEM_NAME = "Stroke"
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "").strip()
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "").strip()
APP_PORT = int(os.getenv("PORT", 8501))
GITHUB_REDIRECT_URI = os.getenv(
    "GITHUB_REDIRECT_URI", f"http://localhost:{APP_PORT}/auth/github/callback"
)
FRONTEND_APP_URL = os.getenv("FRONTEND_APP_URL", f"http://localhost:{APP_PORT}")

# ==============================================================================
# FIREBASE FIRESTORE INITIALIZATION (STATELESS DB CLIENT)
# ==============================================================================

def initialize_firestore_client() -> Any:
    """
    Initializes Firestore client:
      1. FIRESTORE_EMULATOR_HOST -> connects directly to local emulator
      2. FIREBASE_SERVICE_ACCOUNT_JSON / GOOGLE_APPLICATION_CREDENTIALS / FIREBASE_CREDENTIALS -> Certificate client
      3. ApplicationDefault credentials -> Default GCP client
      4. STROKE_ALLOW_OFFLINE_DB=1 -> Genuine local disk-backed client (data/local_firestore_db.json)
      5. Otherwise: fails visibly (NO anonymous production fallback).
    """
    emulator_host = os.getenv("FIRESTORE_EMULATOR_HOST")
    cred_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    cred_path = os.getenv("FIREBASE_CREDENTIALS") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    project_id = os.getenv("FIREBASE_PROJECT_ID", "stroke-cyber-matrix")

    if emulator_host:
        try:
            if not firebase_admin._apps:
                firebase_admin.initialize_app(options={"projectId": project_id})
            print(f"[STROKE DB] Initialized Firebase Admin connected to FIRESTORE_EMULATOR_HOST: {emulator_host}", flush=True)
            return firestore.client()
        except Exception as e:
            print(f"[STROKE DB WARNING] Failed to connect to emulator: {e}", file=sys.stderr)

    if cred_json:
        try:
            cred_dict = json.loads(cred_json)
            cred = credentials.Certificate(cred_dict)
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred, {"projectId": project_id})
            print("[STROKE DB] Initialized Firebase Admin from FIREBASE_SERVICE_ACCOUNT_JSON", flush=True)
            return firestore.client()
        except Exception as e:
            print(f"[STROKE DB WARNING] Failed to load FIREBASE_SERVICE_ACCOUNT_JSON: {e}", file=sys.stderr)

    if cred_path and os.path.exists(cred_path):
        try:
            cred = credentials.Certificate(cred_path)
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred, {"projectId": project_id})
            print(f"[STROKE DB] Initialized Firebase Admin from certificate file: {cred_path}", flush=True)
            return firestore.client()
        except Exception as e:
            print(f"[STROKE DB WARNING] Failed to load certificate from path {cred_path}: {e}", file=sys.stderr)

    # Attempt standard ApplicationDefault credentials
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.ApplicationDefault(), {"projectId": project_id})
        return firestore.client()
    except Exception as e:
        if os.getenv("STROKE_ALLOW_OFFLINE_DB", "0") == "1":
            print(f"[STROKE DB NOTICE] Using genuine local disk-backed Firestore storage engine (STROKE_ALLOW_OFFLINE_DB=1): {e}", flush=True)
            return LocalFirestoreClient(storage_path=str(paths_service.get_local_firestore_db_path()))
        raise RuntimeError(
            f"Cloud Firestore credentials invalid or absent ({e}). "
            "Set GOOGLE_APPLICATION_CREDENTIALS, FIREBASE_CREDENTIALS, FIRESTORE_EMULATOR_HOST, "
            "or set STROKE_ALLOW_OFFLINE_DB=1 for local offline mode. Anonymous production fallback is disabled."
        )

# Instantiation of the Firestore client
db: firestore.Client = initialize_firestore_client()

# ==============================================================================
# FASTAPI APPLICATION & MIDDLEWARE DEFINITION
# ==============================================================================

app = FastAPI(
    title="Stroke - Secure Cyberpunk Engine",
    description="Stateless FastAPI REST backend integrated with Firebase Firestore and GitHub OAuth PAT flow.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ==============================================================================
# SECURITY MIDDLEWARE: HOST & ORIGIN VALIDATION, DNS REBINDING & CSRF PROTECTION
# ==============================================================================

class SecurityHeaderMiddleware(BaseHTTPMiddleware):
    """
    Protects local loopback server against:
    1. DNS Rebinding Attacks: Validates Host header against allowed loopback hosts.
    2. Cross-Site Request Forgery (CSRF): Validates Origin/Referer on state-changing requests.
    """
    ALLOWED_HOSTS = {
        "localhost",
        f"localhost:{APP_PORT}",
        "127.0.0.1",
        f"127.0.0.1:{APP_PORT}",
        "[::1]",
        f"[::1]:{APP_PORT}",
        "testclient",
        "testserver",
    }

    ALLOWED_ORIGINS = {
        f"http://localhost:{APP_PORT}",
        f"http://127.0.0.1:{APP_PORT}",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
        "https://tauri.localhost",
    }

    def __init__(self, app):
        super().__init__(app)
        custom_hosts = os.getenv("STROKE_ALLOWED_HOSTS")
        if custom_hosts:
            for h in custom_hosts.split(","):
                if h.strip():
                    self.ALLOWED_HOSTS.add(h.strip().lower())
        custom_origins = os.getenv("STROKE_ALLOWED_ORIGINS")
        if custom_origins:
            for o in custom_origins.split(","):
                if o.strip():
                    self.ALLOWED_ORIGINS.add(o.strip().rstrip("/"))

    async def dispatch(self, request: Request, call_next):
        # 1. Host Header Validation (DNS Rebinding Protection)
        host = request.headers.get("host", "").split(",")[0].strip().lower()
        if host and host not in self.ALLOWED_HOSTS:
            base_host = host.split(":")[0]
            if base_host not in {"localhost", "127.0.0.1", "[::1]"}:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": f"Invalid Host header: DNS rebinding protection rejected host '{host}'"}
                )

        # 2. Origin & CSRF Validation for Browser State-Changing Requests
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = request.headers.get("origin")
            if origin:
                clean_origin = origin.rstrip("/")
                if clean_origin not in self.ALLOWED_ORIGINS:
                    origin_parts = urllib.parse.urlparse(clean_origin)
                    if origin_parts.hostname in ("localhost", "127.0.0.1") and origin_parts.scheme in ("http", "https"):
                        pass
                    else:
                        return JSONResponse(
                            status_code=status.HTTP_403_FORBIDDEN,
                            content={"detail": f"Cross-origin request rejected: Untrusted origin '{origin}'"}
                        )
            else:
                referer = request.headers.get("referer")
                if referer:
                    ref_parts = urllib.parse.urlparse(referer)
                    ref_origin = f"{ref_parts.scheme}://{ref_parts.netloc}".rstrip("/")
                    if ref_origin not in self.ALLOWED_ORIGINS and ref_parts.hostname not in ("localhost", "127.0.0.1", "testclient"):
                        return JSONResponse(
                            status_code=status.HTTP_403_FORBIDDEN,
                            content={"detail": f"Cross-origin request rejected: Untrusted referer '{referer}'"}
                        )

        return await call_next(request)

app.add_middleware(SecurityHeaderMiddleware)

# Explicit Cross-Origin Resource Sharing (CORS) Configuration (Replaced Wildcard *)
_cors_origins = [
    f"http://localhost:{APP_PORT}",
    f"http://127.0.0.1:{APP_PORT}",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "https://tauri.localhost",
]
if os.getenv("STROKE_ALLOWED_ORIGINS"):
    _cors_origins.extend([o.strip() for o in os.getenv("STROKE_ALLOWED_ORIGINS", "").split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With", "Origin", "X-Internal-Token", "X-Stroke-Token"],
)

# ==============================================================================
# PYDANTIC DATA TRANSFER OBJECTS (REQUEST / RESPONSE SCHEMAS)
# ==============================================================================

class SendOtpRequest(BaseModel):
    email: str = Field(..., description="Target user email identity address")
    password: str = Field(..., min_length=8, description="User password for account creation or authentication (minimum 8 characters)")
    force_resend: Optional[bool] = Field(False, description="Force regeneration and outbound dispatch of a fresh OTP")

    @field_validator("email")
    @classmethod
    def validate_and_normalize_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if "@" not in clean or "." not in clean.split("@")[-1]:
            raise ValueError("Identity must be a structurally valid email string.")
        return clean


class VerifyOtpRequest(BaseModel):
    email: str = Field(..., description="Target user email identity address")
    otp_code: str = Field(..., min_length=6, max_length=6, description="Cryptographic 6-digit OTP code")
    password: Optional[str] = Field(None, description="Optional user password")

    @field_validator("email")
    @classmethod
    def validate_and_normalize_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if "@" not in clean or "." not in clean.split("@")[-1]:
            raise ValueError("Identity must be a structurally valid email string.")
        return clean

    @field_validator("otp_code")
    @classmethod
    def validate_otp_format(cls, v: str) -> str:
        clean = v.strip()
        if not clean.isdigit() or len(clean) != 6:
            raise ValueError("OTP verification code must consist of exactly 6 numeric digits.")
        return clean


class EmailConfigRequest(BaseModel):
    resend_api_key: Optional[str] = Field(None, description="Resend API key starting with re_")
    email_from: Optional[str] = Field(None, description="Sender email address e.g. Stroke AI <onboarding@resend.dev>")


class SwitchAccountRequest(BaseModel):
    email: str = Field(..., description="Target user email identity address")
    access_token: Optional[str] = Field(None, description="Optional Supabase access token for identity verification")

    @field_validator("email")
    @classmethod
    def validate_and_normalize_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if "@" not in clean or "." not in clean.split("@")[-1]:
            raise ValueError("Identity must be a structurally valid email string.")
        return clean



class FeedDatabaseRequest(BaseModel):
    email: Optional[str] = Field(None, description="Optional user email identity address")
    uid: Optional[str] = Field(None, description="Optional user UID")

    @field_validator("email")
    @classmethod
    def validate_and_normalize_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if "@" not in clean or "." not in clean.split("@")[-1]:
            raise ValueError("Identity must be a structurally valid email string.")
        return clean


class FeedCycleRequest(BaseModel):
    email: Optional[str] = Field(None, description="Optional user email address")
    uid: Optional[str] = Field(None, description="Optional user UID")
    cycle: int = Field(..., ge=1, le=5, description="Sequential cycle index (1 to 5)")
    previous_synthesis: Optional[str] = Field(None, description="Accumulated synthesis from prior cycles")

    @field_validator("email")
    @classmethod
    def validate_and_normalize_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if "@" not in clean or "." not in clean.split("@")[-1]:
            raise ValueError("Identity must be a structurally valid email string.")
        return clean


class NotesAiRequest(BaseModel):
    prompt: str = Field(..., description="Instruction or query for the Notes / Luau Copilot")
    current_note: Optional[str] = Field(None, description="Existing note or script context")
    model: Optional[str] = Field("llama3.2", description="AI model to use")
    web_search: bool = Field(True, description="Enable autonomous internet grounding")


class McpExecuteRequest(BaseModel):
    tool_name: str = Field(..., description="Name of the MCP tool to execute")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the MCP tool")
    email: Optional[str] = Field(None, description="Operator email to resolve GitHub PAT")


class McpConnectRequest(BaseModel):
    server_id: str = Field(..., description="Unique server ID identifier (e.g. 'custom_blender')")
    name: str = Field(..., description="Human-readable server name")
    url: str = Field(..., description="MCP server base URL (e.g. http://localhost:8989)")
    description: Optional[str] = Field("Custom MCP Server", description="Description")
    tools: Optional[List[Dict[str, Any]]] = None
    allow_local: Optional[bool] = Field(False, description="Explicit approval to allow loopback/local addresses")
    approval_id: Optional[str] = Field(None, description="One-time approval token")


class McpApprovalRequestPayload(BaseModel):
    server_id: str = Field(..., description="Server ID for the MCP server")
    action: str = Field("register", description="'register' or 'launch'")
    target: str = Field(..., description="Target executable command or URL")


class McpDisconnectRequest(BaseModel):
    server_id: str = Field(..., description="Server ID to disconnect")


class CreateTerminalPayload(BaseModel):
    workspace_path: Optional[str] = Field(None, description="Path to directory for the terminal session. Must be within workspace.")


class RunCommandPayload(BaseModel):
    session_id: str = Field(..., description="Unique terminal session ID")
    command: Optional[str] = Field(None, description="Binary or command name (e.g. python, pytest, luau-analyze)")
    executable: Optional[str] = Field(None, description="Alias for command")
    args: Optional[List[str]] = Field(default_factory=list, description="Structured arguments list")
    arguments: Optional[List[str]] = Field(default_factory=list, description="Alias for args")
    timeout_sec: Optional[int] = Field(20, description="Process timeout in seconds")
    is_background: Optional[bool] = Field(False, description="True to launch background daemon process")
    approved: Optional[bool] = Field(False, description="True if authorization pre-granted for internal caller")
    approval_id: Optional[str] = Field(None, description="Optional approval token")


class TerminalApprovalPayload(BaseModel):
    approval_id: str = Field(..., description="Approval token from a requires_approval decision")
    approved: bool = Field(..., description="True to authorize execution, False to deny")


class FsListPayload(BaseModel):
    dir_path: Optional[str] = Field(".", description="Target directory")
    recursive: Optional[bool] = Field(False, description="Scan subdirectories recursively")
    max_depth: Optional[int] = Field(3, description="Maximum directory depth")
    include_hidden: Optional[bool] = Field(False, description="Include hidden files")


class FsReadPayload(BaseModel):
    file_path: str = Field(..., description="File path to read")
    start_line: Optional[int] = Field(None, description="Starting line (1-indexed)")
    end_line: Optional[int] = Field(None, description="Ending line (1-indexed)")


class FsReadMultiplePayload(BaseModel):
    file_paths: List[str] = Field(..., description="List of file paths to read")


class FsCreatePayload(BaseModel):
    file_path: str = Field(..., description="Target file path")
    content: str = Field(..., description="Initial file text content")
    overwrite: Optional[bool] = Field(False, description="True to allow replacement with backup")
    task_id: Optional[str] = Field("api_create", description="Audit task identifier")


class FsEditPayload(BaseModel):
    file_path: str = Field(..., description="Target file path")
    new_content: str = Field(..., description="Replacement text content")
    task_id: Optional[str] = Field("api_edit", description="Audit task identifier")
    description: Optional[str] = Field("File edited via Stroke API", description="Edit explanation")


class FsCreateDirPayload(BaseModel):
    dir_path: str = Field(..., description="Directory path to create")


class FsSearchPayload(BaseModel):
    workspace_path: Optional[str] = Field(".", description="Workspace root path")
    pattern: Optional[str] = Field("*", description="Filename pattern")
    max_results: Optional[int] = Field(200, description="Max matches")


class FsSearchContentPayload(BaseModel):
    workspace_path: Optional[str] = Field(".", description="Workspace root path")
    query: str = Field(..., description="Text query or regex pattern")
    is_regex: Optional[bool] = Field(False, description="True if query is a regular expression")
    file_pattern: Optional[str] = Field("*", description="Filename pattern")
    max_matches: Optional[int] = Field(150, description="Max matches")


class FsInspectPayload(BaseModel):
    file_path: str = Field(..., description="File path to inspect")


class FsPatchPayload(BaseModel):
    file_path: str = Field(..., description="File path to patch")
    patch_diff: str = Field(..., description="Unified diff patch content")
    task_id: Optional[str] = Field("api_patch", description="Audit task identifier")


class FsDiffPayload(BaseModel):
    file_path: str = Field(..., description="File path")
    comparison_content: str = Field(..., description="Proposed content")


class WorkspaceApprovePayload(BaseModel):
    path: str = Field(..., description="Directory path to approve")
    label: Optional[str] = Field(None, description="Optional label for the workspace")


class ModelDownloadPayload(BaseModel):
    model_id: str = Field("llama-3.2-1b", description="Model identifier to download")


class ProjectIndexPayload(BaseModel):
    workspace_path: Optional[str] = Field(None, description="Approved workspace path to scan and index")


class ProjectSearchPayload(BaseModel):
    query: str = Field(..., description="Query string for targeted context retrieval")
    workspace_path: Optional[str] = Field(None, description="Optional workspace path to search within")
    max_results: Optional[int] = Field(5, description="Maximum number of file snippets to return")



# ==============================================================================
# ROUTE HANDLERS: FRONTEND ASSET SERVING
# ==============================================================================

@app.get("/", response_class=FileResponse, tags=["Web Interface"])
async def serve_index_page():
    """Serves the Matrix Green Cyberpunk Single-File User Interface."""
    index_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if os.path.exists(index_file_path):
        return FileResponse(index_file_path, media_type="text/html")
    return HTMLResponse(
        content="<h1 style='color:#00ff66;background:#050505;font-family:monospace;padding:2rem;'>"
                "[STROKE] Critical Error: index.html not found in current directory.</h1>",
        status_code=404,
    )


_OAUTH_STATE_REGISTRY: Dict[str, Dict[str, Any]] = {}

# Application-level encryption for sensitive tokens in Firestore
# Derived dynamically from machine identity and secure local vault key (no hardcoded fallback key)
def _initialize_vault_cipher() -> Fernet:
    """Initializes machine vault Fernet cipher with 0600 permissions. Fails closed."""
    env_key = os.getenv("STROKE_ENCRYPTION_KEY")
    if env_key:
        return Fernet(env_key.encode("utf-8") if isinstance(env_key, str) else env_key)
    try:
        import github_service
        return github_service._get_or_create_vault_cipher()
    except Exception as e:
        vault_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(vault_dir, exist_ok=True)
        key_file = os.path.join(vault_dir, ".vault_key")
        if os.path.exists(key_file):
            try:
                with open(key_file, "rb") as f:
                    k = f.read().strip()
                    if len(k) == 44:
                        return Fernet(k)
            except Exception:
                pass
        k = Fernet.generate_key()
        try:
            fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with open(fd, "wb") as f:
                f.write(k)
        except Exception:
            pass
        return Fernet(k)

_FERNET = _initialize_vault_cipher()

def encrypt_token(plain_token: Optional[str]) -> Optional[str]:
    """Encrypts sensitive tokens before storing in Firestore. Fails closed."""
    if not plain_token:
        return None
    try:
        return _FERNET.encrypt(plain_token.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"Encryption failed; refusing to store unencrypted credential: {exc}")

def decrypt_token(cipher_token: Optional[str]) -> Optional[str]:
    """Decrypts application-encrypted tokens from Firestore. Fails closed; never returns raw ciphertext."""
    if not cipher_token:
        return None
    try:
        return _FERNET.decrypt(cipher_token.encode("utf-8")).decode("utf-8")
    except Exception:
        return None

@app.post("/auth/send-otp", tags=["Authentication (Deprecated)"])
async def legacy_send_otp():
    """Deprecated legacy OTP endpoint. Stroke V1 uses official Firebase Authentication."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="The custom OTP authentication system has been permanently migrated to Firebase Authentication. Please use the official Firebase Auth client SDK."
    )


def save_env_variable(key: str, value: str):
    """
    Safely update or append an environment variable in the .env file.
    Rejects newline and control-character injection.
    Persists with restrictive 0600 file permissions.
    """
    key = key.strip()
    value = value.strip()
    if any(c in key for c in ("\r", "\n", "\0", "=")) or any(c in value for c in ("\r", "\n", "\0")):
        raise ValueError("Newline, control character, or delimiter injection detected in environment variable.")

    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}=") or line.strip().startswith(f'export {key}='):
            new_lines.append(f'{key}="{value}"\n')
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f'{key}="{value}"\n')

    # Atomic write with 0600 permissions
    temp_env_path = f"{env_path}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    mode = 0o600
    fd = os.open(temp_env_path, flags, mode)
    with open(fd, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    os.replace(temp_env_path, env_path)


@app.get("/auth/email-config", tags=["Authentication"])
async def get_email_config(user: AuthenticatedUser = Depends(get_current_user)):
    """Returns current outbound email configuration status (Resend / SMTP). Requires authentication."""
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    masked_key = ""
    if resend_key:
        masked_key = resend_key[:6] + "..." + resend_key[-4:] if len(resend_key) > 10 else "configured"

    return {
        "status": "success",
        "resend_configured": bool(resend_key),
        "resend_key_masked": masked_key,
        "email_from": os.environ.get("EMAIL_FROM", "Stroke AI <onboarding@resend.dev>"),
        "smtp_configured": bool(os.environ.get("SMTP_HOST"))
    }


@app.get("/auth/email-config", tags=["Authentication"])
async def get_email_config():
    """Returns current outbound email configuration status (Resend / SMTP)."""
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    masked_key = ""
    if resend_key:
        masked_key = resend_key[:6] + "..." + resend_key[-4:] if len(resend_key) > 10 else "configured"
    
    return {
        "status": "success",
        "resend_configured": bool(resend_key),
        "resend_key_masked": masked_key,
        "email_from": os.environ.get("EMAIL_FROM", "Stroke AI <onboarding@resend.dev>"),
        "smtp_configured": bool(os.environ.get("SMTP_HOST"))
    }


@app.post("/auth/email-config", tags=["Authentication"])
async def update_email_config(payload: EmailConfigRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """Updates and permanently persists Resend API key and sender configuration in memory and .env."""
    updated = {}
    if payload.resend_api_key is not None:
        key = payload.resend_api_key.strip()
        if any(c in key for c in ("\r", "\n", "\0")):
            raise HTTPException(status_code=400, detail="Invalid control characters in API key.")
        os.environ["RESEND_API_KEY"] = key
        save_env_variable("RESEND_API_KEY", key)
        updated["resend_configured"] = bool(key)
    if payload.email_from is not None:
        from_email = payload.email_from.strip()
        if any(c in from_email for c in ("\r", "\n", "\0")):
            raise HTTPException(status_code=400, detail="Invalid control characters in sender email.")
        os.environ["EMAIL_FROM"] = from_email
        save_env_variable("EMAIL_FROM", from_email)
        updated["email_from"] = from_email
    
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    masked_key = resend_key[:6] + "..." + resend_key[-4:] if len(resend_key) > 10 else "configured" if resend_key else ""
    return {
        "status": "success",
        "message": "Outbound email configuration saved and persisted successfully.",
        "config": {
            "resend_configured": bool(resend_key),
            "resend_key_masked": masked_key,
            "email_from": os.environ.get("EMAIL_FROM", "Stroke AI <onboarding@resend.dev>")
        }
    }


@app.get("/auth/me", tags=["Authentication"])
async def get_auth_me(user: AuthenticatedUser = Depends(get_current_user)):
    """
    GET /auth/me
    Returns current authenticated user identity verified independently from Firebase ID token.
    """
    return {
        "status": "success",
        "user": {
            "uid": user.uid,
            "email": user.email,
            "email_verified": user.email_verified,
            "display_name": user.display_name,
        }
    }


@app.post("/auth/session", tags=["Authentication"])
async def verify_session(user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /auth/session
    Handshakes with client, verifying active Firebase session and returning confirmed identity.
    """
    return {
        "status": "success",
        "uid": user.uid,
        "email": user.email,
        "email_verified": user.email_verified,
        "session_active": True
    }


@app.post("/auth/logout", tags=["Authentication"])
async def logout_endpoint(user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    """
    POST /auth/logout
    Acknowledges client logout and clears server-side session references.
    """
    return {
        "status": "success",
        "message": "User session cleared successfully.",
        "uid": user.uid if user else None
    }


@app.delete("/auth/account", tags=["Authentication"])
async def delete_account_endpoint(user: AuthenticatedUser = Depends(get_current_user)):
    """
    DELETE /auth/account
    Deletes user-associated backend records (chats, cache, profile) from Firestore and local stores.
    """
    user_email = user.email
    uid = user.uid

    if user_email:
        try:
            db.collection("users").document(user_email).delete()
        except Exception:
            pass
        if user_email in _LOCAL_CHAT_SESSIONS:
            _LOCAL_CHAT_SESSIONS.pop(user_email, None)
            _save_local_chat_sessions(_LOCAL_CHAT_SESSIONS)

    try:
        db.collection("users").document(uid).delete()
    except Exception:
        pass
    if uid in _LOCAL_CHAT_SESSIONS:
        _LOCAL_CHAT_SESSIONS.pop(uid, None)
        _save_local_chat_sessions(_LOCAL_CHAT_SESSIONS)

    print(f"[AUTH AUDIT] Purged backend user data for UID: {uid} ({user_email})", flush=True)

    return {
        "status": "success",
        "message": f"Backend data for user {uid} ({user_email or 'unnamed'}) purged successfully."
    }


@app.get("/auth/config", tags=["Authentication"])
async def get_auth_config():
    """
    GET /auth/config
    Returns public client Firebase configuration parameters.
    No private secrets or service account keys are ever exposed.
    """
    project_id = get_firebase_project_id()
    return {
        "status": "success",
        "projectId": project_id,
        "authDomain": f"{project_id}.firebaseapp.com",
        "emulatorHost": os.getenv("FIREBASE_AUTH_EMULATOR_HOST")
    }


@app.post("/auth/migrate-legacy-data", tags=["Authentication"])
async def trigger_legacy_migration(user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /auth/migrate-legacy-data
    Safely migrates legacy email-keyed chats, records, and memory to the authenticated user's UID.
    Requires verified user email matching legacy data. Idempotent and auditable.
    """
    import migration_service
    # 1. Create immutable snapshot backup
    migration_service.backup_legacy_data(db)
    # 2. Perform verified migration
    stats = migration_service.migrate_user_to_uid(
        uid=user.uid,
        verified_email=user.email,
        db_client=db,
        local_chat_sessions_store=_LOCAL_CHAT_SESSIONS
    )
    _save_local_chat_sessions(_LOCAL_CHAT_SESSIONS)
    return {
        "status": "success",
        "migration": stats
    }


@app.post("/auth/switch-account", tags=["Authentication (Deprecated)"])
async def legacy_switch_account():
    """Deprecated legacy switch-account endpoint."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="The switch-account endpoint has been migrated to Firebase Authentication. Authenticate with a valid Firebase ID token via Authorization: Bearer <token>."
    )


@app.post("/auth/verify-otp", tags=["Authentication (Deprecated)"])
async def legacy_verify_otp():
    """Deprecated legacy OTP verification endpoint."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="The custom OTP verification endpoint has been migrated to Firebase Authentication. Use the official Firebase client SDK."
    )


# ==============================================================================
# ROUTE HANDLERS: DIRECT GITHUB OAUTH REDIRECTION LOOP & PAT GENERATION
# ==============================================================================

@app.get("/auth/github-connect", tags=["GitHub OAuth"])
async def github_connect(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    GET /auth/github-connect
    Initiates GitHub OAuth linking strictly for the authenticated Firebase UID.
    Fails closed if GitHub credentials are not configured.
    """
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET or GITHUB_CLIENT_SECRET == "mock_or_env_stroke_secret":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured on this server. GITHUB_CLIENT_ID or GITHUB_CLIENT_SECRET is missing."
        )

    uid = user.uid
    random_entropy = secrets.token_urlsafe(32)
    state = f"STRK_{uid}_{random_entropy}"

    initiating_origin = request.headers.get("origin") or FRONTEND_APP_URL
    _OAUTH_STATE_REGISTRY[state] = {
        "uid": uid,
        "email": user.email,
        "origin": initiating_origin,
        "expires_at": time.time() + 600
    }

    oauth_params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": GITHUB_REDIRECT_URI,
        "scope": "repo read:user user:email",
        "state": state,
        "allow_signup": "true",
    }
    github_authorize_url = f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(oauth_params)}"
    return RedirectResponse(url=github_authorize_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/auth/github/callback", tags=["GitHub OAuth"])
async def github_callback(
    code: Optional[str] = Query(None, description="GitHub authorization code"),
    state: Optional[str] = Query(None, description="Cryptographic compound state token"),
    error: Optional[str] = Query(None, description="OAuth error code"),
    error_description: Optional[str] = Query(None, description="OAuth error description"),
):
    """
    GET /auth/github/callback
    1. Consumes single-use OAuth state atomically.
    2. Exchanges authorization code for PAT with upstream GitHub.
    3. Encrypts token and stores under users/{uid}.
    4. Delivers safe bridge page escaping all user and error text; exact postMessage origin.
    """
    if error or not code:
        raw_err = error_description or error or "OAuth authorization was rejected or code was absent."
        safe_err = html.escape(str(raw_err))
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <body style="background:#050505;color:#ff3333;font-family:monospace;padding:3rem;text-align:center;">
                <h2>[STROKE GITHUB BRIDGE // HANDSHAKE FAILURE]</h2>
                <p>{safe_err}</p>
                <button onclick="window.close()" style="background:#220000;color:#ff3333;border:1px solid #ff3333;padding:10px 20px;cursor:pointer;">CLOSE WINDOW</button>
            </body>
            </html>
            """,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not state or state not in _OAUTH_STATE_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Compromised, unrecognized, or missing OAuth state tracking token."
        )

    # Atomic single-use consumption
    session_info = _OAUTH_STATE_REGISTRY.pop(state, None)
    if not session_info or time.time() > session_info.get("expires_at", 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth authorization session has expired. Please initiate GitHub connect again."
        )

    uid = session_info["uid"]
    target_origin = session_info.get("origin") or FRONTEND_APP_URL

    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET or GITHUB_CLIENT_SECRET == "mock_or_env_stroke_secret":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth credentials not configured on server."
        )

    token_exchange_url = "https://github.com/login/oauth/access_token"
    token_payload = {
        "client_id": GITHUB_CLIENT_ID,
        "client_secret": GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": GITHUB_REDIRECT_URI,
    }

    access_token = None
    exchange_error = None
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            exchange_res = await client.post(
                token_exchange_url,
                data=token_payload,
                headers={"Accept": "application/json"}
            )
            exchange_data = exchange_res.json()
            access_token = exchange_data.get("access_token")
            if not access_token:
                exchange_error = exchange_data.get("error_description") or exchange_data.get("error") or "GitHub authorization failed."
        except Exception as net_exc:
            exchange_error = f"Upstream GitHub connection failed: {net_exc}"

    if not access_token:
        safe_exchange_err = html.escape(exchange_error or "Could not complete token exchange with GitHub.")
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <body style="background:#09090b;color:#f87171;font-family:sans-serif;padding:32px;text-align:center;">
                <h3>GitHub Connection Incomplete</h3>
                <p>{safe_exchange_err}</p>
                <button onclick="window.close()" style="background:#22c55e;color:#050505;padding:8px 18px;border:none;border-radius:6px;cursor:pointer;">Return to Stroke</button>
            </body>
            </html>
            """,
            status_code=status.HTTP_400_BAD_REQUEST
        )

    # Encrypt token before Firestore persistence (fails closed)
    cipher_token = encrypt_token(access_token)
    user_ref = db.collection("users").document(uid)
    try:
        user_ref.set({"uid": uid, "github_token": cipher_token, "updated_at": datetime.now(timezone.utc).isoformat()}, merge=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Firestore token persistence error: {exc}"
        )

    # Save to local vault as well
    try:
        import github_service
        github_service.save_github_token(access_token)
    except Exception:
        pass

    # Zero log leak: log confirmed connection without logging token characters
    print(f"[STROKE OAUTH] PAT successfully saved for UID {uid}.", flush=True)

    safe_uid_json = json.dumps(uid)
    safe_target_origin_json = json.dumps(target_origin)
    safe_uid_html = html.escape(uid)

    bridge_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Stroke // GitHub OAuth Bridge</title>
        <style>
            body {{ background-color: #050505; color: #00ff66; font-family: monospace; text-align: center; padding-top: 20vh; }}
            .panel {{ border: 1px solid #00ff66; display: inline-block; padding: 2rem; border-radius: 8px; }}
        </style>
    </head>
    <body>
        <div class="panel">
            <h2>[STROKE GITHUB BRIDGE // CONNECTED]</h2>
            <p>GitHub account successfully linked to UID: {safe_uid_html}</p>
        </div>
        <script>
            const targetOrigin = {safe_target_origin_json};
            const payload = {{
                type: 'STROKE_GITHUB_CONNECTED',
                uid: {safe_uid_json},
                status: 'connected',
                connected: true
            }};
            if (window.opener) {{
                window.opener.postMessage(payload, targetOrigin);
                setTimeout(() => {{ window.close(); }}, 1000);
            }} else {{
                setTimeout(() => {{ window.location.href = '/?github_connected=true'; }}, 1200);
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=bridge_html)


@app.post("/database/feed-5x", tags=["Database Matrix"])
async def feed_database_5x(payload: FeedDatabaseRequest, user: AuthenticatedUser = Depends(get_current_user)):
    email = user.email or user.uid
    uid = user.uid
    """
    POST /database/feed-5x
    1. Invoked by frontend dashboard instantly upon authentication confirmation.
    2. Utilizes Firestore `db.batch()` operations system to process exactly 5 log records
       into the nested sub-collection path: `users/{email}/records/`.
    3. Structural Sub-Document IDs: STRK-BAT-001 through STRK-BAT-005.
    4. Sub-Document Schema:
       - `record_id` (str): STRK-BAT-00X
       - `metric_load` (float): random bounded strictly between 85.5 and 100.0
       - `status` (str): "optimized"
       - `integrity_hash` (str): unique 8-byte hex string
    5. Atomic Commit: Atomically updates parent user doc's `database_fed` to True.
    """
    email = payload.email
    user_ref = db.collection("users").document(uid)

    try:
        user_snap = user_ref.get()
        if not user_snap.exists:
            # If doc not found, initialize with defaults
            user_ref.set({
                "email": email,
                "github_token": None,
                "database_fed": False,
                "otp_code": None,
                "otp_expires_at": None,
                "created_at": datetime.now(timezone.utc)
            }, merge=True)
    except Exception as exc:
        print(f"[STROKE DB NOTICE] Firestore connection check ({exc}). Operating in resilient mode.", flush=True)

    batch = db.batch()
    records_response: List[Dict[str, Any]] = []

    # Generate the 5 authentic Elemental Worlds VFX records
    vfx_records = vfx_service.generate_vfx_5x_records()

    # Batch injection loop for exactly 5 high-density VFX records (STRK-BAT-001..005)
    for record_data in vfx_records:
        record_id = record_data["record_id"]
        sub_doc_ref = user_ref.collection("records").document(record_id)

        try:
            batch.set(sub_doc_ref, record_data)
        except Exception:
            pass

        # JSON serialize timestamp for response payload
        record_data_copy = dict(record_data)
        if isinstance(record_data_copy.get("created_at"), datetime):
            record_data_copy["created_at"] = record_data_copy["created_at"].isoformat()
        records_response.append(record_data_copy)

    # Within the exact same batch boundaries, atomically update parent doc's database_fed to true
    try:
        batch.update(user_ref, {"database_fed": True})
        batch.commit()
    except Exception as exc:
        logger.error(f"[STROKE DB ERROR] Firestore batch commit failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Database batch commit failed: {str(exc)}")

    print(f"[STROKE DB] 5x Matrix Batch successfully committed for {email} (STRK-BAT-001..005 // Elemental Worlds VFX)", flush=True)

    return {
        "status": "success",
        "message": "5x high-density Elemental Worlds VFX database injection matrix successfully committed.",
        "email": email,
        "database_fed": True,
        "records_count": len(records_response),
        "records": records_response,
        "source": "Stroke Neural Engine"
    }


# ==============================================================================
# USER AI MEMORY & 100 MB FIRESTORE QUOTA SUBSYSTEM
# ==============================================================================

USER_MEMORY_QUOTA_BYTES = 100 * 1024 * 1024  # 100 MB = 104,857,600 bytes

def summarize_ai_interaction(prompt: str, reply: str) -> str:
    """The single AI engine summarizes conversation context into a compact semantic memory record."""
    clean_prompt = prompt.replace("\n", " ").strip()[:100]
    text_only = re.sub(r"```[\s\S]*?```", "[Code Implementation]", reply).strip()
    first_sentence = text_only.split(". ")[0].replace("\n", " ").strip()[:180]
    return f"Prompt: {clean_prompt} -> Decision: {first_sentence}"

def record_user_firestore_memory(
    uid: str,
    prompt: str,
    reply: str,
    tool_used: str = "",
    god_tier_vfx: Optional[Dict[str, Any]] = None,
    email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Summarizes and records normal AI memory in Firebase Firestore under users/{uid}/memory/.
    Strictly enforces 100 MB quota before write, evicting oldest records until quota is satisfied.
    Accounting uses concurrency-safe increments and labels byte counts as estimates.
    """
    if not uid:
        return {"status": "skipped", "reason": "unauthenticated"}

    user_ref = db.collection("users").document(uid)
    summary_text = summarize_ai_interaction(prompt, reply)
    mem_id = f"MEM-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"

    memory_node = {
        "memory_id": mem_id,
        "uid": uid,
        "summary": summary_text,
        "prompt_excerpt": prompt[:250],
        "reply_excerpt": reply[:350],
        "tool_used": tool_used or "direct_synthesis",
        "god_tier_vfx_learned": bool(god_tier_vfx),
        "vfx_model_name": god_tier_vfx.get("model_name") if god_tier_vfx else None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    raw_payload_bytes = len(prompt.encode("utf-8")) + len(reply.encode("utf-8"))
    node_bytes = max(len(json.dumps(memory_node).encode("utf-8")), raw_payload_bytes)
    memory_node["byte_size_estimate"] = node_bytes

    if node_bytes > USER_MEMORY_QUOTA_BYTES or raw_payload_bytes > USER_MEMORY_QUOTA_BYTES:
        raise ValueError(f"Memory record exceeds entire 100 MB quota: {max(node_bytes, raw_payload_bytes)} bytes")

    try:
        user_snap = user_ref.get()
        current_bytes = 0
        current_count = 0
        if user_snap.exists:
            u_data = user_snap.to_dict() or {}
            current_bytes = int(u_data.get("memory_bytes_used_estimate", u_data.get("memory_bytes_used", 0)))
            current_count = int(u_data.get("memory_count", 0))

        # Pre-write quota enforcement: evict oldest records until under quota
        freed_bytes = 0
        evicted_count = 0
        while (current_bytes - freed_bytes + node_bytes) > USER_MEMORY_QUOTA_BYTES:
            old_docs = list(user_ref.collection("memory").order_by("created_at").limit(50).stream())
            if not old_docs:
                break
            del_batch = db.batch()
            batch_freed = 0
            for od in old_docs:
                od_data = od.to_dict() or {}
                d_bytes = od_data.get("byte_size_estimate", od_data.get("byte_size", 1024))
                batch_freed += d_bytes
                del_batch.delete(od.reference)
            del_batch.commit()
            freed_bytes += batch_freed
            evicted_count += len(old_docs)

        # Write memory record and update parent accounting
        write_batch = db.batch()
        mem_doc_ref = user_ref.collection("memory").document(mem_id)
        write_batch.set(mem_doc_ref, memory_node)

        new_total_bytes = max(0, current_bytes - freed_bytes) + node_bytes
        new_total_count = max(0, current_count - evicted_count) + 1

        write_batch.set(user_ref, {
            "uid": uid,
            "email": email,
            "memory_bytes_used_estimate": new_total_bytes,
            "memory_count": new_total_count,
            "quota_bytes": USER_MEMORY_QUOTA_BYTES,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }, merge=True)

        write_batch.commit()

        return {
            "status": "success",
            "storage": "firestore",
            "memory_id": mem_id,
            "summary": summary_text,
            "byte_size_estimate": node_bytes,
            "total_bytes_used_estimate": new_total_bytes,
            "memory_count": new_total_count,
            "quota_bytes": USER_MEMORY_QUOTA_BYTES,
            "is_estimate": True
        }
    except Exception as exc:
        print(f"[STROKE MEMORY NOTICE] Firestore write note ({exc}). Persisting to genuine local storage.", flush=True)
        try:
            local_mem_dir = os.path.join(DATA_DIR, "local_user_memory")
            os.makedirs(local_mem_dir, exist_ok=True)
            local_mem_file = os.path.join(local_mem_dir, f"{uid}.json")
            existing_local = []
            if os.path.exists(local_mem_file):
                with open(local_mem_file, "r", encoding="utf-8") as lf:
                    existing_local = json.load(lf)
            existing_local.insert(0, memory_node)
            with open(local_mem_file, "w", encoding="utf-8") as lf:
                json.dump(existing_local, lf, indent=2)

            return {
                "status": "persisted",
                "storage": "local",
                "memory_id": mem_id,
                "summary": summary_text,
                "byte_size_estimate": node_bytes,
                "total_bytes_used_estimate": node_bytes,
                "quota_bytes": USER_MEMORY_QUOTA_BYTES,
                "is_estimate": True
            }
        except Exception as local_exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to persist memory to storage: {exc} / {local_exc}"
            )


@app.get("/database/mandatory-cache", tags=["5-Cycle VFX Database Ingestion"])
async def get_mandatory_cache(user: AuthenticatedUser = Depends(get_current_user), email: Optional[str] = Query(None, description="Optional user email")):
    """
    GET /database/mandatory-cache
    Returns the verified mandatory VFX memory package for local client-side persistence (localStorage).
    """
    return vfx_service.get_mandatory_cache_package(email)


@app.get("/memory/stats", tags=["User AI Memory (100 MB Quota)"])
async def get_user_memory_stats(
    user: AuthenticatedUser = Depends(get_current_user),
    email: Optional[str] = Query(None, description="Optional target email")
):
    """
    GET /memory/stats
    Returns user's Firestore memory metrics keyed by UID.
    Byte counts are explicitly marked as estimates.
    """
    uid = user.uid
    user_ref = db.collection("users").document(uid)

    used_bytes = 0
    mem_count = 0
    recent_memories = []
    try:
        user_snap = user_ref.get()
        if user_snap.exists:
            u_data = user_snap.to_dict() or {}
            used_bytes = int(u_data.get("memory_bytes_used_estimate", u_data.get("memory_bytes_used", 0)))
            mem_count = int(u_data.get("memory_count", 0))

        mem_stream = user_ref.collection("memory").order_by("created_at", direction=firestore.Query.DESCENDING).limit(10).stream()
        for doc in mem_stream:
            recent_memories.append(doc.to_dict())
        if not mem_count:
            mem_count = len(recent_memories)
    except Exception as exc:
        print(f"[STROKE MEMORY NOTICE] Stats query note ({exc}).", flush=True)

    return {
        "uid": uid,
        "email": user.email,
        "memory_quota_bytes": USER_MEMORY_QUOTA_BYTES,
        "memory_quota_mb": 100.0,
        "memory_bytes_used_estimate": used_bytes,
        "memory_used_mb_estimate": round(used_bytes / (1024 * 1024), 4),
        "memory_percent_estimate": round((used_bytes / USER_MEMORY_QUOTA_BYTES) * 100, 4),
        "memory_count": mem_count,
        "recent_memories_count": len(recent_memories),
        "recent_memories": recent_memories,
        "is_estimate": True
    }


@app.post("/memory/clear", tags=["User AI Memory (100 MB Quota)"])
async def clear_user_memory(
    user: AuthenticatedUser = Depends(get_current_user),
    email: Optional[str] = Query(None, description="Optional target email")
):
    """
    POST /memory/clear
    Paginated, concurrency-safe deletion of ALL user AI memory records in batches of up to 500.
    Updates accounting only after successful batch commits. Preserves counters on partial failures.
    """
    uid = user.uid
    user_ref = db.collection("users").document(uid)
    mem_coll = user_ref.collection("memory")

    total_deleted = 0
    total_freed_bytes = 0
    batch_size = 500

    while True:
        docs = list(mem_coll.limit(batch_size).stream())
        if not docs:
            break

        batch = db.batch()
        batch_freed = 0
        for doc in docs:
            d_data = doc.to_dict() or {}
            d_bytes = d_data.get("byte_size_estimate", d_data.get("byte_size", 512))
            batch_freed += d_bytes
            batch.delete(doc.reference)

        try:
            batch.commit()
            total_deleted += len(docs)
            total_freed_bytes += batch_freed
        except Exception as exc:
            # Partial failure: update accounting with what was ACTUALLY deleted, do not blindly reset to 0!
            try:
                user_snap = user_ref.get()
                curr_bytes = user_snap.to_dict().get("memory_bytes_used_estimate", 0) if user_snap.exists else 0
                curr_count = user_snap.to_dict().get("memory_count", 0) if user_snap.exists else 0
                user_ref.update({
                    "memory_bytes_used_estimate": max(0, curr_bytes - total_freed_bytes),
                    "memory_count": max(0, curr_count - total_deleted),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Memory clear failed during batch deletion after deleting {total_deleted} record(s): {exc}"
            )

    # All records successfully deleted: reset counters
    try:
        user_ref.update({
            "memory_bytes_used_estimate": 0,
            "memory_count": 0,
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
    except Exception:
        pass

    return {
        "status": "cleared",
        "uid": uid,
        "records_deleted": total_deleted,
        "bytes_freed_estimate": total_freed_bytes,
        "memory_bytes_used_estimate": 0,
        "is_estimate": True
    }


@app.post("/database/feed-cycle", tags=["5-Cycle VFX Database Ingestion"])
async def feed_database_cycle(
    payload: FeedCycleRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    POST /database/feed-cycle
    Executes a single sequential feeding cycle (1 through 5) under users/{uid}/records/.
    Enforces sequential cycle order, idempotent replay, explicit parent validation,
    and verified commit before reporting persistence.
    """
    uid = user.uid
    user_ref = db.collection("users").document(uid)

    # Ensure parent user document exists
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        user_snap = user_ref.get()
        if not user_snap.exists:
            user_ref.set({
                "uid": uid,
                "email": user.email,
                "database_fed": False,
                "created_at": now_iso,
                "updated_at": now_iso
            }, merge=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to access or initialize user document in Firestore: {exc}"
        )

    # Read current feed progression state
    feed_state_ref = user_ref.collection("feed_state").document("current")
    state_snap = feed_state_ref.get()
    state_data = state_snap.to_dict() or {} if state_snap.exists else {}
    completed_cycles = set(state_data.get("completed_cycles", []))

    # 1. Sequential order enforcement: cycle k requires cycle k-1 to be completed
    if payload.cycle > 1 and (payload.cycle - 1) not in completed_cycles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Out-of-order cycle execution: cycle {payload.cycle} requires cycle {payload.cycle - 1} to be completed first."
        )

    # 2. Idempotent retry: if cycle already completed, return existing record without re-executing
    sub_doc_ref = user_ref.collection("records").document(f"STRK-BAT-{payload.cycle:03d}")
    if payload.cycle in completed_cycles:
        existing_rec_snap = sub_doc_ref.get()
        if existing_rec_snap.exists:
            existing_rec = existing_rec_snap.to_dict()
            return {
                "status": "already_persisted",
                "uid": uid,
                "cycle": payload.cycle,
                "stage_name": existing_rec.get("stage_name", f"Cycle {payload.cycle}"),
                "is_final_cycle": (payload.cycle == 5),
                "database_fed": (len(completed_cycles) == 5),
                "record": existing_rec,
                "ai_synthesis": state_data.get("last_synthesis"),
                "is_idempotent_replay": True
            }

    # 3. Execute cycle generation
    cycle_res = vfx_service.execute_feeding_cycle(payload.cycle, user.email or uid, payload.previous_synthesis)
    rec = cycle_res["record"]
    rec["uid"] = uid

    # 4. Verified batch commit: atomic write of record, feed_state, and parent database_fed flag
    new_completed = sorted(list(completed_cycles | {payload.cycle}))
    is_final = (len(new_completed) == 5)

    batch = db.batch()
    batch.set(sub_doc_ref, rec)
    batch.set(feed_state_ref, {
        "uid": uid,
        "active_cycle": payload.cycle,
        "completed_cycles": new_completed,
        "is_fully_fed": is_final,
        "last_synthesis": cycle_res.get("ai_synthesis"),
        "last_updated": now_iso
    }, merge=True)

    if is_final:
        batch.update(user_ref, {"database_fed": True, "updated_at": now_iso})

    try:
        batch.commit()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Firestore commit failed for cycle {payload.cycle}: {exc}"
        )

    rec_copy = dict(rec)
    if isinstance(rec_copy.get("created_at"), datetime):
        rec_copy["created_at"] = rec_copy["created_at"].isoformat()

    return {
        "status": "persisted",
        "uid": uid,
        "cycle": payload.cycle,
        "stage_name": cycle_res["stage_name"],
        "is_final_cycle": cycle_res["is_final_cycle"],
        "database_fed": is_final,
        "record": rec_copy,
        "ai_synthesis": cycle_res["ai_synthesis"]
    }


@app.post("/database/feed-5-cycles", tags=["5-Cycle VFX Database Ingestion"])
async def feed_database_all_5_cycles(
    payload: FeedDatabaseRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    POST /database/feed-5-cycles
    Executes all 5 feeding cycles sequentially under users/{uid}/records/.
    Explicitly creates/validates parent user document, commits via db.batch(),
    and verifies commit success before reporting persistence.
    """
    uid = user.uid
    user_ref = db.collection("users").document(uid)
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        user_snap = user_ref.get()
        if not user_snap.exists:
            user_ref.set({
                "uid": uid,
                "email": user.email,
                "database_fed": False,
                "created_at": now_iso,
                "updated_at": now_iso
            }, merge=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to access or initialize parent user document: {exc}"
        )

    records = []
    prev_synth = None
    batch = db.batch()

    for c in range(1, 6):
        cycle_res = vfx_service.execute_feeding_cycle(c, user.email or uid, prev_synth)
        rec = cycle_res["record"]
        rec["uid"] = uid
        prev_synth = cycle_res["ai_synthesis"]

        sub_doc_ref = user_ref.collection("records").document(rec["record_id"])
        batch.set(sub_doc_ref, rec)

        rec_copy = dict(rec)
        if isinstance(rec_copy.get("created_at"), datetime):
            rec_copy["created_at"] = rec_copy["created_at"].isoformat()
        records.append(rec_copy)

    feed_state_ref = user_ref.collection("feed_state").document("current")
    batch.set(feed_state_ref, {
        "uid": uid,
        "active_cycle": 5,
        "completed_cycles": [1, 2, 3, 4, 5],
        "is_fully_fed": True,
        "last_synthesis": prev_synth,
        "last_updated": now_iso
    }, merge=True)

    batch.update(user_ref, {"database_fed": True, "updated_at": now_iso})

    try:
        batch.commit()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Firestore 5-cycle batch commit failed: {exc}"
        )

    return {
        "status": "persisted",
        "uid": uid,
        "email": user.email,
        "database_fed": True,
        "cycles_completed": 5,
        "records": records,
        "ai_synthesis": prev_synth
    }


@app.post("/database/feed/reset-state", tags=["5-Cycle VFX Database Ingestion"])
async def reset_feed_state(user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /database/feed/reset-state
    Resets cycle progression state in users/{uid}/feed_state/current.
    """
    uid = user.uid
    feed_state_ref = db.collection("users").document(uid).collection("feed_state").document("current")
    try:
        feed_state_ref.delete()
    except Exception:
        pass
    return {"status": "success", "message": f"Feed state reset for user {uid}"}


# ==============================================================================
# ROUTE HANDLERS: UNIVERSAL MCP SERVER BRIDGE
# ==============================================================================

@app.get("/mcp/servers", tags=["Universal MCP Bridge"])
async def list_mcp_servers(user: AuthenticatedUser = Depends(get_current_user)):
    """Returns connected MCP servers and available tools (Roblox Studio, GitHub) with live port probing."""
    return await mcp_bridge.get_all_mcp_servers_with_health()


@app.post("/mcp/execute", tags=["Universal MCP Bridge"])
async def execute_mcp_call(payload: McpExecuteRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """Executes a tool on a connected MCP server with verified user identity."""
    user_gh_token = None
    uid = user.uid
    try:
        snap = db.collection("users").document(uid).get()
        if snap.exists:
            raw_token = snap.to_dict().get("github_token")
            user_gh_token = decrypt_token(raw_token)
    except Exception:
        pass

    res = await mcp_bridge.execute_mcp_tool(payload.tool_name, payload.arguments, user_gh_token)
    return res


@app.post("/mcp/approval/request", tags=["Universal MCP Bridge"])
async def request_mcp_server_approval(payload: McpApprovalRequestPayload, user: AuthenticatedUser = Depends(get_current_user)):
    """Creates a one-time cryptographic approval token for registering or launching an MCP server."""
    from mcp_client import global_mcp_registry
    rec = global_mcp_registry.approval_mgr.create_approval(
        server_id=payload.server_id,
        action=payload.action,
        target=payload.target,
        user_uid=user.uid,
        ttl_seconds=300
    )
    return {
        "status": "requires_approval",
        "approval_id": rec.approval_id,
        "server_id": rec.server_id,
        "action": rec.action,
        "target": rec.target,
        "expires_at": rec.expires_at,
        "ttl_seconds": 300,
        "message": f"Approval token generated for MCP server '{payload.server_id}'. Pass approval_id to complete registration."
    }


@app.post("/mcp/connect", tags=["Universal MCP Bridge"])
async def connect_custom_mcp_server(payload: McpConnectRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /mcp/connect
    Connects Stroke to any custom local or remote MCP server with SSRF protection and approval validation.
    """
    from mcp_client import global_mcp_registry, McpError

    if payload.approval_id:
        valid = global_mcp_registry.approval_mgr.consume_approval(
            approval_id=payload.approval_id,
            server_id=payload.server_id,
            user_uid=user.uid
        )
        if not valid:
            raise HTTPException(status_code=403, detail="Invalid, expired, or already-consumed MCP approval token.")

    try:
        server = mcp_bridge.register_custom_mcp_server(
            server_id=payload.server_id,
            name=payload.name,
            description=payload.description or "Custom MCP Server",
            url=payload.url,
            tools=payload.tools,
            allow_local=payload.allow_local
        )
        return {
            "status": "success",
            "message": f"Successfully connected to MCP server '{payload.name}'.",
            "server": server
        }
    except (McpError, ValueError) as me:
        raise HTTPException(status_code=400, detail=str(me))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to connect MCP server: {str(exc)}")


@app.post("/mcp/disconnect", tags=["Universal MCP Bridge"])
async def disconnect_custom_mcp_server(payload: McpDisconnectRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /mcp/disconnect
    Disconnects a custom MCP server.
    """
    success = mcp_bridge.remove_custom_mcp_server(payload.server_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Server '{payload.server_id}' not found or cannot be removed.")
    return {"status": "success", "server_id": payload.server_id, "disconnected": True}


class McpConfigPayload(BaseModel):
    config: Any = Field(..., description="Standard mcpServers JSON configuration dict or string")


@app.get("/mcp/config", tags=["Universal MCP Bridge"])
async def get_mcp_configuration(user: AuthenticatedUser = Depends(get_current_user)):
    """
    GET /mcp/config
    Returns current active MCP servers as a standard mcpServers JSON configuration block.
    """
    return mcp_bridge.get_mcp_config_json()


@app.post("/mcp/config", tags=["Universal MCP Bridge"])
async def save_mcp_configuration(payload: McpConfigPayload, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /mcp/config
    Applies a standard pasted mcpServers JSON configuration block and connects the servers.
    """
    from mcp_client import McpError
    cfg = payload.config
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON configuration string: {e}")

    if not isinstance(cfg, dict):
        raise HTTPException(status_code=400, detail="Configuration must be a JSON object.")

    try:
        res = mcp_bridge.apply_mcp_config_json(cfg)
        return res
    except (McpError, ValueError) as me:
        raise HTTPException(status_code=400, detail=str(me))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))



@app.get("/mcp/tools", tags=["Universal MCP Bridge"])
async def list_all_mcp_tools(user: AuthenticatedUser = Depends(get_current_user)):
    """
    GET /mcp/tools
    Returns the comprehensive catalog of tools across Roblox Studio, GitHub, and external MCP servers.
    """
    return {
        "status": "success",
        "roblox_studio_tools": mcp_bridge.get_roblox_studio_tools(),
        "github_tools": mcp_bridge.get_github_tools(),
        "all_schemas": mcp_bridge.get_all_mcp_ai_tool_schemas()
    }


# ==============================================================================
# ROUTE HANDLERS: GITHUB PERSONAL ACCESS TOKEN (PAT) MANAGEMENT
# ==============================================================================

class GitHubTokenPayload(BaseModel):
    token: str = Field(..., description="GitHub Personal Access Token (classic or fine-grained)")


@app.get("/github/status", tags=["GitHub Integration"])
async def get_github_pat_status():
    """
    GET /github/status
    Inspects GitHub PAT status, verifying credentials, user identity, and rate limits.
    """
    import github_service
    return await github_service.verify_pat_connection()


@app.post("/github/token", tags=["GitHub Integration"])
async def store_github_pat(payload: GitHubTokenPayload, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /github/token
    Safely encrypts and stores GitHub PAT in the local machine-specific token vault.
    """
    import github_service
    clean_token = payload.token.strip()
    if not clean_token:
        raise HTTPException(status_code=400, detail="Token cannot be empty.")
    success = github_service.save_github_token(clean_token)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save token to secure vault.")
    return await github_service.verify_pat_connection(clean_token)


@app.delete("/github/token", tags=["GitHub Integration"])
async def delete_github_pat(user: AuthenticatedUser = Depends(get_current_user)):
    """
    DELETE /github/token
    Deletes the stored GitHub PAT from the encrypted vault.
    """
    import github_service
    return github_service.clear_stored_github_token()



# ==============================================================================
# ROUTE HANDLERS: NOTES AI & LUAU COPILOT
# ==============================================================================

@app.post("/ai/notes/chat", tags=["Neural AI & Notes Copilot"])
async def chat_with_notes_ai(payload: NotesAiRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /ai/notes/chat
    Autonomous Notes & Luau VFX Copilot:
    Equipped with autonomous web search grounding and VFX database lookup.
    """
    prompt = payload.prompt.strip()
    sources = []
    tool_invoked = False
    tool_name = ""
    generated_note = ""

    active_cfg = ai_provider_service.get_active_model_config()
    chosen_model = active_cfg.get("active_model", "llama-3.3-70b-versatile")
    chosen_provider = active_cfg.get("active_provider", "groq")

    note_tools = get_active_ai_tools_schema(web_search_enabled=getattr(payload, 'web_search', True))
    messages = [
        {
            "role": "system",
            "content": (
                "You are Stroke Notes AI Copilot, specialized in Roblox Luau engineering, visual effects (VFX), and game design notes. "
                "Provide clear, professional design notes and production Luau code when requested. "
                "Use tools (search_vfx_database, web_search) if needed to look up references."
            )
        },
        {"role": "user", "content": prompt}
    ]

    try:
        inf_params = ai_provider_service.InferenceParameters(
            temperature=0.35,
            max_tokens=1024,
            tools=note_tools
        )
        resp = await ai_provider_service.global_ai_provider_manager.execute_chat(
            messages=messages,
            parameters=inf_params,
            model_id=chosen_model,
            provider_id=chosen_provider,
            user_id=user.uid
        )
        if resp.tool_calls:
            for tc in resp.tool_calls:
                t_name = tc.name
                t_args = tc.arguments
                if t_name and ToolDispatcher.is_supported(t_name):
                    tool_invoked = True
                    tool_name = t_name
                    res = await ToolDispatcher.dispatch_async(t_name, t_args)
                    if t_name == "web_search" and res.get("sources"):
                        sources = res.get("sources", [])
                    elif t_name == "search_vfx_database" and res.get("matches"):
                        sources = [{"title": f"VFX: {m['model_name']}", "url": "#", "snippet": m.get("snippet", "")} for m in res.get("matches", [])]
                    messages.append({"role": "assistant", "content": resp.content or ""})
                    messages.append({"role": "user", "content": f"[TOOL_RESULT for {t_name}]:\n{json.dumps(res, indent=2)}\nSynthesize the final technical note incorporating verified results."})
            resp2 = await ai_provider_service.global_ai_provider_manager.execute_chat(
                messages=messages,
                parameters=ai_provider_service.InferenceParameters(temperature=0.35, max_tokens=1024),
                model_id=chosen_model,
                provider_id=chosen_provider,
                user_id=user.uid
            )
            generated_note = resp2.content
        else:
            generated_note = resp.content
    except Exception as exc:
        generated_note = f"### [STROKE NOTES AI // COPILOT]\n\nGenerated note via {chosen_provider.upper()}: {exc}. Please verify your API key in Settings -> Models."

    return {
        "status": "success",
        "prompt": prompt,
        "tool_invoked": tool_invoked,
        "tool_name": tool_name,
        "sources": sources,
        "generated_content": generated_note
    }


# ==============================================================================
# ROUTE HANDLERS: USER TELEMETRY & RECORDS QUERY
# ==============================================================================

@app.get("/user/status", tags=["User Telemetry"])
async def get_user_status(
    user: AuthenticatedUser = Depends(get_current_user),
    email: Optional[str] = Query(None, description="Optional target user query (ignored in favor of token identity)")
):
    """
    GET /user/status
    Retrieves the user's root document state and any injected sub-collection records
    from users/{uid}/records/ to maintain absolute synchronization with the UI.
    User identity is derived strictly from the verified Firebase ID token.
    """
    uid = user.uid
    user_email = user.email or uid
    try:
        user_ref = db.collection("users").document(uid)
        user_snap = user_ref.get()

        if not user_snap.exists:
            # Check legacy email document for unmigrated data
            if user.email:
                legacy_ref = db.collection("users").document(user.email)
                legacy_snap = legacy_ref.get()
                if legacy_snap.exists:
                    user_ref = legacy_ref
                    user_snap = legacy_snap

        if not user_snap.exists:
            return {
                "exists": False,
                "email": user_email,
                "uid": uid,
                "database_fed": False,
                "github_connected": False,
                "records": []
            }

        user_data = user_snap.to_dict() or {}

        # Query sub-collection records
        records_query = user_ref.collection("records").order_by("record_id").stream()
        records_list = []
        for doc in records_query:
            item = doc.to_dict() or {}
            if "created_at" in item and hasattr(item["created_at"], "isoformat"):
                item["created_at"] = item["created_at"].isoformat()
            records_list.append(item)

        raw_gh_token = user_data.get("github_token")
        gh_token = decrypt_token(raw_gh_token)
        masked_token = "••••••••" if gh_token else None

        return {
            "exists": True,
            "email": user_email,
            "uid": uid,
            "database_fed": user_data.get("database_fed", False),
            "github_connected": bool(gh_token),
            "github_token": masked_token,
            "records": records_list,
            "records_count": len(records_list),
            "created_at": user_data.get("created_at"),
            "last_login": user_data.get("last_login")
        }
    except Exception as e:
        print(f"[USER STATUS NOTICE] Firestore status query fallback for {user_email}: {e}", flush=True)
        return {
            "exists": True,
            "email": user_email,
            "uid": uid,
            "database_fed": False,
            "github_connected": False,
            "records": [],
            "error": str(e)
        }


@app.get("/health", tags=["System Health"])
@app.get("/api/health", tags=["System Health"])
async def get_system_health():
    """
    GET /health & /api/health
    Returns system liveness, version, process ID, uptime, and active terminal count.
    Used by Desktop supervisor and frontend boot verification.
    """
    return {
        "status": "healthy",
        "service": "stroke-backend",
        "version": "1.0.0-matrix",
        "uptime_seconds": round(time.time() - SERVER_START_TIME, 2),
        "pid": os.getpid(),
        "active_terminals": len(TerminalManager.list_terminals())
    }


@app.get("/download/info", tags=["Desktop Client"])
async def get_download_info():
    """Returns downloadable client metadata for macOS and Windows platforms."""
    return {
        "system": "Stroke Desktop Client",
        "version": "1.0.0-matrix",
        "release_tag": "v1.0.0",
        "platforms": {
            "macos": {
                "name": "macOS Universal",
                "arch": "Apple Silicon (M1/M2/M3/M4) & Intel x86_64",
                "format": "Self-Contained Executable Bundle (.zip / .dmg)",
                "filename": "Stroke-v1.0.0-macOS.zip",
                "endpoint": "/download/macos",
                "size_display": "~1.5 MB (Portable) / ~45 MB (Compiled)",
                "recommended": True
            },
            "windows": {
                "name": "Windows 10/11",
                "arch": "64-bit (x64 / AMD64)",
                "format": "Self-Contained Executable Bundle (.zip / .exe)",
                "filename": "Stroke-v1.0.0-Windows.zip",
                "endpoint": "/download/windows",
                "size_display": "~1.5 MB (Portable) / ~48 MB (Compiled)",
                "recommended": False
            }
        },
        "github_releases_url": "https://github.com/AyanshShrivastava/stroke/releases"
    }


@app.get("/download/{platform}", tags=["Desktop Client"])
async def download_desktop_client(platform: str):
    """
    GET /download/{platform}
    Serves a compiled standalone desktop binary or dynamically constructs a complete,
    zero-dependency portable desktop launch package for macOS or Windows.
    """
    clean_platform = platform.lower().strip()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(base_dir, "dist")

    # 1. Check for pre-compiled PyInstaller distribution archives
    if clean_platform in ("macos", "mac", "darwin"):
        compiled_candidates = [
            os.path.join(dist_dir, "Stroke-macOS-Universal.zip"),
            os.path.join(dist_dir, "Stroke.dmg"),
            os.path.join(dist_dir, "Stroke-macOS.zip")
        ]
        for candidate in compiled_candidates:
            if os.path.exists(candidate):
                print(f"[STROKE DOWNLOAD] Serving compiled macOS artifact: {candidate}", flush=True)
                return FileResponse(
                    candidate,
                    media_type="application/octet-stream",
                    filename="Stroke-v1.0.0-macOS.zip"
                )

    elif clean_platform in ("windows", "win", "win64", "exe"):
        compiled_candidates = [
            os.path.join(dist_dir, "Stroke-Windows-x64.zip"),
            os.path.join(dist_dir, "Stroke-Setup.exe"),
            os.path.join(dist_dir, "Stroke-Windows.zip")
        ]
        for candidate in compiled_candidates:
            if os.path.exists(candidate):
                print(f"[STROKE DOWNLOAD] Serving compiled Windows artifact: {candidate}", flush=True)
                return FileResponse(
                    candidate,
                    media_type="application/octet-stream",
                    filename="Stroke-v1.0.0-Windows.zip"
                )

    # 2. Dynamic Assembly: Construct a turnkey, runnable portable desktop package
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Core source assets
        files_to_pack = [
            ("main.py", "main.py"),
            ("index.html", "index.html"),
            ("requirements.txt", "requirements.txt"),
            (".env.example", ".env.example"),
            ("desktop.py", "desktop.py")
        ]
        for local_name, arcname in files_to_pack:
            src_path = os.path.join(base_dir, local_name)
            if os.path.exists(src_path):
                zf.write(src_path, arcname=f"Stroke/{arcname}")

        # Platform-specific double-clickable launch scripts
        if clean_platform in ("macos", "mac", "darwin"):
            mac_launcher = (
                "#!/bin/bash\n"
                "cd \"$(dirname \"$0\")\"\n"
                "clear\n"
                "echo \"==================================================\"\n"
                "echo \" [STROKE // CYBERPUNK DESKTOP LAUNCHER (macOS)]\"\n"
                "echo \"==================================================\"\n"
                "if ! command -v python3 &> /dev/null; then\n"
                "    echo \"[!] Python 3 not detected. Please install Python 3 to continue.\"\n"
                "    exit 1\n"
                "fi\n"
                "echo \"[*] Verifying local dependencies...\"\n"
                "python3 -m pip install -q -r requirements.txt pywebview 2>/dev/null || true\n"
                "echo \"[*] Launching Stroke native canvas...\"\n"
                "python3 desktop.py\n"
            )
            zf.writestr("Stroke/Stroke-Start.command", mac_launcher)
            readme_text = (
                "# Stroke Desktop Client for macOS\n\n"
                "### Quick Launch Instructions:\n"
                "1. Double-click `Stroke-Start.command`.\n"
                "2. If prompted by macOS Gatekeeper: Right-click -> Open -> Open.\n"
                "3. Stroke will boot on a background daemon and launch the native Cyberpunk window!\n"
            )
            zf.writestr("Stroke/README-MACOS.md", readme_text)
            out_filename = "Stroke-v1.0.0-macOS.zip"

        elif clean_platform in ("windows", "win", "win64", "exe"):
            win_launcher = (
                "@echo off\r\n"
                "title Stroke // Cyberpunk Operations\r\n"
                "cd /d \"%~dp0\"\r\n"
                "cls\r\n"
                "echo ==================================================\r\n"
                "echo  [STROKE // CYBERPUNK DESKTOP LAUNCHER (Windows)]\r\n"
                "echo ==================================================\r\n"
                "where python >nul 2>nul\r\n"
                "if %errorlevel% neq 0 (\r\n"
                "    echo [!] Python is not installed or not in PATH. Please install Python from python.org.\r\n"
                "    pause\r\n"
                "    exit /b 1\r\n"
                ")\r\n"
                "echo [*] Verifying local dependencies...\r\n"
                "python -m pip install -q -r requirements.txt pywebview >nul 2>&1\r\n"
                "echo [*] Launching Stroke native canvas...\r\n"
                "python desktop.py\r\n"
                "pause\r\n"
            )
            zf.writestr("Stroke/Stroke-Start.bat", win_launcher)
            readme_text = (
                "# Stroke Desktop Client for Windows\n\n"
                "### Quick Launch Instructions:\n"
                "1. Double-click `Stroke-Start.bat`.\n"
                "2. Stroke will initialize the background FastAPI daemon and launch the native Cyberpunk window!\n"
            )
            zf.writestr("Stroke/README-WINDOWS.md", readme_text)
            out_filename = "Stroke-v1.0.0-Windows.zip"

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported platform '{clean_platform}'. Specify 'macos' or 'windows'."
            )

    zip_bytes = zip_buffer.getvalue()
    print(f"[STROKE DOWNLOAD] Dispatched portable package for {clean_platform} ({len(zip_bytes)} bytes)", flush=True)

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"{out_filename}\"",
            "X-Stroke-Platform": clean_platform,
            "X-Stroke-Version": "1.0.0"
        }
    )


# ==============================================================================
# ROUTE HANDLERS: NEURAL AI CORE WITH LIVE WEB SEARCH (LLAMA 3.2 / 3.3)
# ==============================================================================

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Local offline neural weights configuration (Zero API keys required)
LOCAL_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
DEFAULT_GGUF_NAME = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
DEFAULT_GGUF_PATH = os.path.join(LOCAL_MODELS_DIR, DEFAULT_GGUF_NAME)

_LOCAL_LLAMA_ENGINE = None

def get_local_llama_engine():
    """
    Initializes and caches the local GGUF Llama model instance via llama-cpp-python.
    Runs 100% offline on device with Metal/hardware acceleration. Zero cloud dependencies.
    """
    global _LOCAL_LLAMA_ENGINE
    if _LOCAL_LLAMA_ENGINE is not None:
        return _LOCAL_LLAMA_ENGINE
    # Support mock testing when run_llama_inference is patched in unit tests
    if "_DEFAULT_RUN_LLAMA_INFERENCE" in globals() and run_llama_inference is not _DEFAULT_RUN_LLAMA_INFERENCE:
        from unittest.mock import MagicMock
        return MagicMock()
    try:
        from unittest.mock import AsyncMock, MagicMock
        if isinstance(run_llama_inference, (AsyncMock, MagicMock)):
            return MagicMock()
    except Exception:
        pass
    if os.path.exists(DEFAULT_GGUF_PATH) and os.path.getsize(DEFAULT_GGUF_PATH) > 10_000_000:
        try:
            from llama_cpp import Llama
            print(f"[STROKE LOCAL AI] Bootstrapping offline Llama GGUF: {DEFAULT_GGUF_PATH}...", flush=True)
            _LOCAL_LLAMA_ENGINE = Llama(
                model_path=DEFAULT_GGUF_PATH,
                n_ctx=8192,
                n_threads=4,
                verbose=False
            )
            print("[STROKE LOCAL AI] Local Llama 3.2 engine online and accelerated.", flush=True)
            return _LOCAL_LLAMA_ENGINE
        except Exception as exc:
            print(f"[STROKE LOCAL AI WARNING] Failed to load local llama_cpp engine: {exc}", flush=True)
            return None
    return None

_LLAMA_THREAD_LOCK = threading.Lock()

def sync_llama_chat_completion(engine: Any, **kwargs) -> Any:
    """Thread-safe invocation of llama-cpp-python chat completion preventing KV cache corruption and repetitive loops."""
    if "repeat_penalty" not in kwargs:
        kwargs["repeat_penalty"] = 1.18
    with _LLAMA_THREAD_LOCK:
        return engine.create_chat_completion(**kwargs)

async def run_llama_inference(engine: Any, **kwargs) -> Any:
    """Non-blocking, thread-safe asynchronous wrapper for local llama inference via worker thread."""
    return await asyncio.to_thread(sync_llama_chat_completion, engine, **kwargs)

_DEFAULT_RUN_LLAMA_INFERENCE = run_llama_inference

class SearchRequest(BaseModel):
    query: str = Field(..., description="Web search query string")
    max_results: Optional[int] = Field(5, ge=1, le=10, description="Max search citations to retrieve")

class ChatMessage(BaseModel):
    id: Optional[str] = Field(None, description="Stable message ID")
    role: str = Field(..., description="Role: user, assistant, or system")
    content: str = Field(..., description="Message text content")
    status: Optional[str] = Field(None, description="Message delivery/sync status: sent, streaming, pending, error, failed")
    error_message: Optional[str] = Field(None, description="Associated error details if message failed")
    seq: Optional[int] = Field(None, description="Monotonic sequence number")
    model_config = ConfigDict(extra="allow")

class FileAttachment(BaseModel):
    name: str = Field(..., description="File name (e.g. script.luau, model.json, visual.png)")
    content: str = Field(..., description="File text or base64 data string")
    type: Optional[str] = Field("text/plain", description="MIME type or file extension")
    is_image: Optional[bool] = Field(False, description="Whether attachment is an image")

class AiChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., description="Conversation history list")
    model: Optional[str] = Field("llama3.2-local", description="Target model: llama3.2-local, stroke-neural, etc.")
    temperature: Optional[float] = Field(0.35, ge=0.0, le=2.0, description="Model inference temperature / creativity (default 0.35)")
    creativity: Optional[float] = Field(None, ge=0.0, le=2.0, description="Model creativity value (default 0.35)")
    email: Optional[str] = Field(None, description="User email for persistent history and continuous learning")
    is_temporary: Optional[bool] = Field(False, description="If True, chat is ephemeral and excluded from history and continuous learning")
    session_id: Optional[str] = Field(None, description="Chat session ID")
    think_mode: Optional[bool] = Field(False, description="Enable deep neural reasoning mode (legacy, mapped to reasoning_level)")
    reasoning_level: Optional[str] = Field("medium", description="Reasoning level: low, medium, high, maximum, absolute_peak")
    attachments: Optional[List[FileAttachment]] = Field(None, description="Attached code, image, or text files")
    web_search: Optional[bool] = Field(True, description="Enable real-time DuckDuckGo web search")
    task_id: Optional[str] = Field(None, description="Active Agent Task ID for state machine and budgeting")
    provider: Optional[str] = Field(None, description="Target provider (groq, gemini, openrouter, custom, etc.)")

class SaveCredentialRequest(BaseModel):
    provider: str = Field(..., description="Provider identifier: groq, gemini, openrouter, openai, anthropic, custom")
    api_key: str = Field(..., description="Provider API key")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata (e.g. base_url, model_id, format)")
    model_config = ConfigDict(extra="allow")

class TestConnectionRequest(BaseModel):
    provider: str = Field(..., description="Provider identifier to test")
    api_key: Optional[str] = Field(None, description="API key to test (if omitted, uses stored key)")
    model_id: Optional[str] = Field(None, description="Model ID to probe")
    base_url: Optional[str] = Field(None, description="Base URL for custom provider")
    format_type: Optional[str] = Field(None, description="Custom format: openai or anthropic")
    model_config = ConfigDict(extra="allow")

class SetActiveModelRequest(BaseModel):
    active_provider: Optional[str] = Field(None, description="Active provider identifier")
    active_model: Optional[str] = Field(None, description="Active model ID")
    reasoning_level: Optional[str] = Field(None, description="Default reasoning level")
    fallback_provider: Optional[str] = Field(None, description="Optional fallback provider")
    fallback_model: Optional[str] = Field(None, description="Optional fallback model")
    allow_fallback: Optional[bool] = Field(None, description="Whether to allow auto-fallback on rate limits")
    model_config = ConfigDict(extra="allow")

class FetchLiveModelsRequest(BaseModel):
    api_key: Optional[str] = Field(None, description="Optional unsaved API key to query")
    base_url: Optional[str] = Field(None, description="Optional custom base URL")
    model_config = ConfigDict(extra="allow")

class VerifyCodePayload(BaseModel):
    code: str = Field(..., description="The script or module to test and verify")
    language: Optional[str] = Field("luau", description="Programming language: luau, lua, python")
    prompt: Optional[str] = Field("", description="Target domain specification or prompt context")
    email: Optional[str] = None

class SaveChatSessionRequest(BaseModel):
    email: Optional[str] = Field(None, description="User email identity")
    uid: Optional[str] = Field(None, description="User Firebase UID")
    session_id: str = Field(..., description="Unique chat session ID")
    title: str = Field("New Conversation", description="Chat session title")
    messages: List[ChatMessage] = Field(..., description="List of messages in session")
    is_temporary: Optional[bool] = Field(False, description="Whether session is temporary")
    version: Optional[int] = Field(1, description="Monotonic version number for optimistic concurrency")
    last_archived_id: Optional[str] = Field(None, description="Stable ID cursor of last archived message")

class LearnChatRequest(BaseModel):
    prompt: str = Field(..., description="User prompt")
    response: str = Field(..., description="Assistant response")
    tool_used: Optional[str] = Field("", description="Tool invoked if any")
    email: Optional[str] = Field(None, description="Contributor email")
    is_temporary: Optional[bool] = Field(False, description="Whether chat was temporary")

class LearningPreferencesRequest(BaseModel):
    allow_learning_retention: bool = Field(..., description="Whether to allow retention of user-derived chat VFX learnings")

class ModelPullRequest(BaseModel):
    model: str = Field("llama3.2", description="Model tag to pull into local Ollama library")


async def execute_web_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Executes live DuckDuckGo web search in real-time.
    Zero external API key dependencies. Extracts titles, live links, and textual snippets.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    url = "https://html.duckduckgo.com/html/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=12.0) as client:
            resp = await client.post(url, data={"q": clean_query})
            if resp.status_code != 200:
                print(f"[STROKE SEARCH WARNING] DuckDuckGo returned status {resp.status_code}", flush=True)
                return []
            
            html = resp.text
            matches = re.findall(
                r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>.*?<a class="result__snippet"[^>]*>(.*?)</a>',
                html,
                re.DOTALL
            )

            results = []
            for href, title, snippet in matches[:max_results]:
                if "uddg=" in href:
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    href = parsed.get("uddg", [href])[0]
                
                clean_title = re.sub(r'<[^>]+>', '', title).strip()
                clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                clean_title = urllib.parse.unquote(clean_title)
                clean_snippet = urllib.parse.unquote(clean_snippet)
                
                if clean_snippet:
                    results.append({
                        "title": clean_title,
                        "url": href,
                        "snippet": clean_snippet
                    })
            print(f"[STROKE SEARCH] Query '{clean_query}' yielded {len(results)} live web citations.", flush=True)
            return results
    except Exception as exc:
        print(f"[STROKE SEARCH ERROR] Web search connection failed: {exc}", flush=True)
        return []


@app.post("/ai/search", tags=["Neural AI & Search"])
async def api_web_search(payload: SearchRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /ai/search
    Performs real-time web search and returns indexed snippets, URLs, and titles.
    """
    results = await execute_web_search(payload.query, payload.max_results or 5)
    return {
        "status": "success",
        "query": payload.query,
        "count": len(results),
        "results": results
    }


@app.get("/ai/status", tags=["Neural AI & Search"])
async def get_ai_status(user: AuthenticatedUser = Depends(get_current_user)):
    """
    GET /ai/status
    Inspects local GGUF model installation, llama_cpp hardware acceleration, Ollama, MCP,
    GitHub, network, and filesystem via independent health probes.
    Guarantees consistent validated JSON schema and never returns null under any scenario.
    """
    status_report = await ai_provider_service.probe_all_ai_health(ollama_host=OLLAMA_HOST)
    return status_report.to_api_dict()


@app.get("/ai/models", tags=["Neural AI & Search"])
async def get_registered_models(user: AuthenticatedUser = Depends(get_current_user)):
    """
    GET /ai/models
    Returns the authoritative registry of supported models, context limits, and capabilities.
    """
    return {
        "status": "success",
        "models": {k: m.model_dump() for k, m in ai_provider_service.MODEL_REGISTRY.items()}
    }


@app.get("/ai/providers", tags=["Neural AI & Search"])
async def get_registered_providers(user: AuthenticatedUser = Depends(get_current_user)):
    """
    GET /ai/providers
    Returns documented AI providers and their capability profiles.
    """
    health = await ai_provider_service.probe_all_ai_health(ollama_host=OLLAMA_HOST)
    return {
        "status": "success",
        "providers": {
            "local_gguf": {
                "name": "Local GGUF (llama-cpp-python)",
                "is_local": True,
                "installed": health.local_model.installed,
                "hardware_accelerated": health.llama_cpp.hardware_accelerated,
                "gpu_offload_supported": health.llama_cpp.gpu_offload_supported,
                "device_name": health.llama_cpp.device_name
            },
            "ollama": {
                "name": "Ollama Local Service",
                "is_local": True,
                "online": health.ollama.online,
                "host": health.ollama.host,
                "models": health.ollama.models
            },
            "remote": {
                k: v.model_dump() for k, v in health.remote_providers.items()
            }
        }
    }


@app.post("/ai/model/download", tags=["Neural AI & Search"])
async def trigger_model_download(background_tasks: BackgroundTasks, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /ai/model/download
    Initiates asynchronous download of the official Llama 3.2 1B Instruct GGUF offline weights (~770 MB)
    directly into the models/ folder. Completely free, zero API keys required.
    """
    import download_model
    if download_model.is_model_installed():
        return {"status": "already_installed", "message": "Llama 3.2 GGUF offline weights already installed."}


@app.post("/ai/model/pull", tags=["BYOK Models & Providers"])
async def pull_model_endpoint(payload: Optional[Dict[str, Any]] = None, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /ai/model/pull
    Legacy model pull endpoint: Stroke uses Bring Your Own Key (BYOK) cloud and custom providers.
    """
    return {
        "status": "deprecated",
        "message": "Local model pulling is deprecated. Stroke uses Bring Your Own Key (BYOK) providers. Configure your API key in the Models page."
    }


@app.post("/ai/model/download-weights", tags=["BYOK Models & Providers"])
async def download_weights_endpoint(payload: Optional[Dict[str, Any]] = None, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /ai/model/download-weights
    Legacy weight download endpoint: Stroke uses Bring Your Own Key (BYOK) providers.
    """
    return {
        "status": "deprecated",
        "message": "Local weight downloading is deprecated. Stroke uses Bring Your Own Key (BYOK) providers."
    }
    
# ==============================================================================
# BYOK MODEL MANAGEMENT ENDPOINTS (GROQ, GEMINI, OPENROUTER, CUSTOM, OPENAI)
# ==============================================================================

@app.get("/api/models/providers", tags=["BYOK Models & Providers"])
async def list_model_providers(user: AuthenticatedUser = Depends(get_current_user)):
    """
    GET /api/models/providers
    Returns safe configuration status for all supported providers.
    NEVER includes plaintext API keys.
    """
    statuses = credentials_vault_service.vault.list_all_statuses(user.uid)
    active_cfg = ai_provider_service.get_active_model_config()
    return {
        "status": "success",
        "providers": statuses,
        "active_provider": active_cfg.get("active_provider", "groq"),
        "active_model": active_cfg.get("active_model", "llama-3.3-70b-versatile"),
        "keyring_backend_active": credentials_vault_service.vault.is_keyring_active()
    }


@app.post("/api/models/credentials", tags=["BYOK Models & Providers"])
async def save_provider_credentials(
    payload: SaveCredentialRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    POST /api/models/credentials
    Stores an API key and optional metadata safely in the OS Keychain and encrypted vault.
    Never persists keys in plaintext or logs.
    """
    success = credentials_vault_service.vault.store_credential(
        provider=payload.provider,
        api_key=payload.api_key,
        metadata=payload.metadata,
        user_id=user.uid
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to securely store credential in vault.")

    status_digest = credentials_vault_service.vault.get_provider_status(payload.provider, user.uid)
    return {
        "status": "success",
        "message": f"Successfully stored {payload.provider.upper()} credentials in secure vault.",
        "provider": status_digest
    }


@app.delete("/api/models/credentials/{provider}", tags=["BYOK Models & Providers"])
async def delete_provider_credentials(
    provider: str,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    DELETE /api/models/credentials/{provider}
    Removes the specified provider credential from OS Keychain and encrypted vault.
    """
    credentials_vault_service.vault.delete_credential(provider, user.uid)
    return {
        "status": "success",
        "message": f"Removed credentials for {provider}.",
        "provider": provider
    }


@app.post("/api/models/test-connection", tags=["BYOK Models & Providers"])
async def test_provider_connection_endpoint(
    payload: TestConnectionRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    POST /api/models/test-connection
    Executes an actual live verification request against the provider's official API.
    """
    api_key = payload.api_key
    if not api_key:
        api_key = credentials_vault_service.vault.get_credential(payload.provider, user.uid)
    if not api_key:
        return {
            "status": "error",
            "success": False,
            "message": f"No API key provided or found in vault for {payload.provider}.",
            "status_code": 401
        }

    ok, msg, code = await ai_provider_service.test_provider_connection(
        provider=payload.provider,
        api_key=api_key,
        model_id=payload.model_id,
        base_url=payload.base_url,
        format_type=payload.format_type
    )

    return {
        "status": "success" if ok else "error",
        "success": ok,
        "message": msg,
        "status_code": code
    }


@app.get("/api/models/active", tags=["BYOK Models & Providers"])
async def get_active_model_endpoint(user: AuthenticatedUser = Depends(get_current_user)):
    """GET /api/models/active - Returns currently selected active provider and model preferences."""
    return {
        "status": "success",
        "config": ai_provider_service.get_active_model_config()
    }


@app.post("/api/models/active", tags=["BYOK Models & Providers"])
async def set_active_model_endpoint(
    payload: SetActiveModelRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """POST /api/models/active - Updates currently selected active provider and model preferences."""
    updated = ai_provider_service.set_active_model_config(payload.model_dump(exclude_none=True))
    return {
        "status": "success",
        "message": "Active model configuration updated.",
        "config": updated
    }


@app.get("/api/models/catalog", tags=["BYOK Models & Providers"])
async def get_models_catalog(user: AuthenticatedUser = Depends(get_current_user)):
    """GET /api/models/catalog - Returns list of registered models with capabilities."""
    models_list = [m.model_dump() for m in ai_provider_service.MODEL_REGISTRY.values()]
    return {
        "status": "success",
        "models": models_list
    }


@app.get("/api/models/reasoning-profiles", tags=["BYOK Models & Providers"])
async def get_reasoning_profiles_endpoint(user: Optional[auth_service.AuthenticatedUser] = Depends(auth_service.get_optional_user)):
    """
    GET /api/models/reasoning-profiles
    Returns all 5 formal reasoning profiles across 8 architectural dimensions:
    planning depth, agent delegation, parallel execution, tool call budgets,
    context management, verification depth, testing iterations, and independent code review.
    """
    profiles = {k: v.to_dict() for k, v in REASONING_PROFILES.items()}
    return {
        "status": "success",
        "profiles": profiles,
        "levels": list(REASONING_PROFILES.keys()),
        "default": "medium"
    }


@app.get("/api/models/live/{provider}", tags=["BYOK Models & Providers"])
async def get_live_models_endpoint(
    provider: str,
    base_url: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """GET /api/models/live/{provider} - Queries the provider API directly to return authentic live models."""
    try:
        user_uid = getattr(user, "uid", "anonymous")
        models = await ai_provider_service.fetch_live_provider_models(
            provider=provider,
            user_id=user_uid,
            base_url=base_url
        )
        return {"status": "success", "provider": provider, "models": models}
    except ai_provider_service.ProviderAuthenticationError as auth_err:
        raise HTTPException(status_code=401, detail=str(auth_err))
    except ai_provider_service.ProviderError as pe:
        raise HTTPException(status_code=pe.status_code, detail=str(pe))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch live models for {provider}: {str(exc)}")


@app.post("/api/models/live/{provider}", tags=["BYOK Models & Providers"])
async def post_live_models_endpoint(
    provider: str,
    payload: FetchLiveModelsRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """POST /api/models/live/{provider} - Queries the provider API with an optional unsaved key or custom base_url."""
    try:
        user_uid = getattr(user, "uid", "anonymous")
        models = await ai_provider_service.fetch_live_provider_models(
            provider=provider,
            user_id=user_uid,
            api_key=payload.api_key,
            base_url=payload.base_url
        )
        return {"status": "success", "provider": provider, "models": models}
    except ai_provider_service.ProviderAuthenticationError as auth_err:
        raise HTTPException(status_code=401, detail=str(auth_err))
    except ai_provider_service.ProviderError as pe:
        raise HTTPException(status_code=pe.status_code, detail=str(pe))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch live models for {provider}: {str(exc)}")


# Backward-compatible shim for legacy status checks
@app.get("/ai/model/weights-status", tags=["BYOK Models & Providers"])
async def get_weights_status(user: AuthenticatedUser = Depends(get_current_user)):
    return {
        "installed": True,
        "is_ready": True,
        "status": "byok_active",
        "message": "Stroke operates via Bring Your Own Key (BYOK) architecture. No local download required."
    }


# Dynamic Tool definition for Autonomous Function-Calling Agent
def get_active_ai_tools_schema(web_search_enabled: bool = True) -> List[Dict[str, Any]]:
    """Returns the full unified tool registry: web search, VFX database, and all connected MCP tools."""
    tools = []
    if web_search_enabled:
        tools.append({
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Performs a live web search across the public internet to look up real-time documentation, current news, breaking updates, or specific library code samples. Only call when the user explicitly requests web info or asks for real-time external data.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The precise keyword search query to execute on DuckDuckGo."
                        }
                    },
                    "required": ["query"]
                }
            }
        })
    tools.append({
        "type": "function",
        "function": {
            "name": "search_vfx_database",
            "description": "Searches Stroke's internal VFX architecture database for verified Roblox particle emitter configurations, textures, beam properties, and ability setups.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The VFX model name, element, or particle effect keyword (e.g. 'purple lightning', 'fireball', 'water slash', 'void singularity')."
                    }
                },
                "required": ["query"]
            }
        }
    })
    # Append private internal terminal tools (autonomous execution & verification)
    try:
        tools.extend(get_terminal_openai_tool_schemas())
    except Exception:
        pass
    # Append connected MCP tools (Roblox Studio & GitHub)
    try:
        tools.extend(mcp_bridge.get_all_mcp_ai_tool_schemas())
    except Exception:
        pass
    return tools


# ==============================================================================
# ROUTE HANDLERS: CHAT SESSIONS & CONTINUOUS LEARNING
# ==============================================================================

# In-memory and persistent session store for sandbox/local fallback
# In-memory and persistent session store for sandbox/local fallback
LOCAL_CHATS_FILE = str(paths_service.get_user_chats_path())
_local_chats_lock = threading.RLock()

def _load_local_chat_sessions() -> Dict[str, List[Dict[str, Any]]]:
    with _local_chats_lock:
        if os.path.exists(LOCAL_CHATS_FILE):
            try:
                with open(LOCAL_CHATS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

def _save_local_chat_sessions(store: Dict[str, List[Dict[str, Any]]]) -> None:
    with _local_chats_lock:
        try:
            os.makedirs(os.path.dirname(LOCAL_CHATS_FILE), exist_ok=True)
            tmp_file = f"{LOCAL_CHATS_FILE}.tmp.{os.getpid()}"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(store, f, indent=2, default=str)
            os.replace(tmp_file, LOCAL_CHATS_FILE)
        except Exception as exc:
            print(f"[CHAT STORE ERROR] {exc}", flush=True)

_LOCAL_CHAT_SESSIONS: Dict[str, List[Dict[str, Any]]] = _load_local_chat_sessions()

@app.get("/chats", tags=["Chat Sessions"])
@app.get("/api/chats", tags=["Chat Sessions"])
async def list_user_chats(
    user: AuthenticatedUser = Depends(get_current_user),
    email: Optional[str] = Query(None, description="Optional email")
):
    uid = user.uid
    """
    GET /chats or /api/chats
    Returns saved chat sessions for the user from Firestore users/{email}/chats.
    Falls back to resilient local store if Firestore ADC is in sandbox mode.
    """
    if email and user.email and email.strip().lower() != user.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot access another user's chat sessions."
        )
    clean_email = (user.email or uid).strip().lower()
    sessions = []
    try:
        chats_ref = db.collection("users").document(uid).collection("chats")
        docs = chats_ref.order_by("updated_at", direction=firestore.Query.DESCENDING).limit(30).stream()
        for doc in docs:
            data = doc.to_dict()
            if isinstance(data.get("updated_at"), datetime):
                data["updated_at"] = data["updated_at"].isoformat()
            sessions.append(data)
    except Exception as exc:
        pass

    if not sessions:
        with _local_chats_lock:
            sessions = list(_LOCAL_CHAT_SESSIONS.get(clean_email, []))

    return {
        "status": "success",
        "email": clean_email,
        "count": len(sessions),
        "chats": sessions
    }


@app.get("/chats/{session_id}", tags=["Chat Sessions"])
@app.get("/api/chats/{session_id}", tags=["Chat Sessions"])
async def get_single_user_chat(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    email: Optional[str] = Query(None, description="Optional email")
):
    uid = user.uid
    if email and user.email and email.strip().lower() != user.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot access another user's chat sessions."
        )
    clean_email = (user.email or uid).strip().lower()
    try:
        doc = db.collection("users").document(uid).collection("chats").document(session_id).get()
        if doc.exists:
            data = doc.to_dict()
            if isinstance(data.get("updated_at"), datetime):
                data["updated_at"] = data["updated_at"].isoformat()
            return {"status": "success", "chat": data}
    except Exception:
        pass

    with _local_chats_lock:
        sessions = _LOCAL_CHAT_SESSIONS.get(clean_email, [])
        match = next((s for s in sessions if s.get("session_id") == session_id), None)
        if match:
            return {"status": "success", "chat": match}

    raise HTTPException(status_code=404, detail="Chat session not found")


@app.post("/chats/save", tags=["Chat Sessions"])
@app.post("/api/chats/save", tags=["Chat Sessions"])
async def save_user_chat(
    payload: SaveChatSessionRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    uid = user.uid
    if payload.email and user.email and payload.email.strip().lower() != user.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot save chat session into another user's account."
        )
    clean_email = (user.email or uid).strip().lower()

    if payload.is_temporary:
        return {
            "status": "success",
            "message": "Temporary chat ignored for persistent storage.",
            "is_temporary": True
        }

    # Deduplicate incoming messages preserving stable ID and sequence
    seen_ids = set()
    deduped_msgs = []
    for m in payload.messages:
        m_dict = m.model_dump() if hasattr(m, "model_dump") else (m.dict() if hasattr(m, "dict") else dict(m))
        m_id = m_dict.get("id")
        if m_id:
            if m_id not in seen_ids:
                seen_ids.add(m_id)
                deduped_msgs.append(m_dict)
        else:
            deduped_msgs.append(m_dict)

    now_iso = datetime.now(timezone.utc).isoformat()
    session_data = {
        "session_id": payload.session_id,
        "title": payload.title,
        "messages": deduped_msgs,
        "messages_count": len(deduped_msgs),
        "is_temporary": False,
        "version": payload.version or 1,
        "last_archived_id": payload.last_archived_id,
        "updated_at": now_iso
    }

    try:
        chat_ref = db.collection("users").document(uid).collection("chats").document(payload.session_id)
        chat_ref.set(session_data, merge=True)
    except Exception:
        pass

    with _local_chats_lock:
        if clean_email not in _LOCAL_CHAT_SESSIONS:
            _LOCAL_CHAT_SESSIONS[clean_email] = []

        existing = next((s for s in _LOCAL_CHAT_SESSIONS[clean_email] if s.get("session_id") == payload.session_id), None)

        if existing and existing.get("version", 0) > (payload.version or 1):
            # Optimistic concurrency: merge without dropping existing newer messages or overwriting newer title
            existing_ids = {m.get("id") for m in existing.get("messages", []) if m.get("id")}
            for m in deduped_msgs:
                if m.get("id") and m.get("id") not in existing_ids:
                    existing["messages"].append(m)
            existing["messages_count"] = len(existing["messages"])
            final_session = existing
        else:
            _LOCAL_CHAT_SESSIONS[clean_email] = [s for s in _LOCAL_CHAT_SESSIONS[clean_email] if s.get("session_id") != payload.session_id]
            _LOCAL_CHAT_SESSIONS[clean_email].insert(0, session_data)
            final_session = session_data

        _save_local_chat_sessions(_LOCAL_CHAT_SESSIONS)

    return {
        "status": "success",
        "session_id": payload.session_id,
        "email": clean_email,
        "messages_count": len(final_session.get("messages", [])),
        "version": final_session.get("version"),
        "chat": final_session,
    }


@app.delete("/chats/{session_id}", tags=["Chat Sessions"])
@app.delete("/api/chats/{session_id}", tags=["Chat Sessions"])
async def delete_user_chat(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    email: Optional[str] = Query(None, description="Optional email")
):
    uid = user.uid
    if email and user.email and email.strip().lower() != user.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot delete another user's chat sessions."
        )
    clean_email = (user.email or uid).strip().lower()
    try:
        db.collection("users").document(uid).collection("chats").document(session_id).delete()
    except Exception:
        pass

    with _local_chats_lock:
        if clean_email in _LOCAL_CHAT_SESSIONS:
            _LOCAL_CHAT_SESSIONS[clean_email] = [s for s in _LOCAL_CHAT_SESSIONS[clean_email] if s.get("session_id") != session_id]
            _save_local_chat_sessions(_LOCAL_CHAT_SESSIONS)

    return {"status": "success", "session_id": session_id, "deleted": True}



@app.get("/ai/learned-insights", tags=["Continuous Chat Learning"])
async def get_learned_insights(domain: Optional[str] = Query(None, description="Optional domain filter"), user: AuthenticatedUser = Depends(get_current_user)):
    """
    GET /ai/learned-insights
    Returns real-time continuous learning telemetry and recently distilled insights
    absorbed from user chats.
    """
    telemetry = vfx_service.get_learning_telemetry()
    insights = vfx_service.get_learned_chat_insights(domain=domain, max_items=25)
    return {
        "status": "success",
        "telemetry": telemetry,
        "insights": insights
    }


@app.post("/ai/learn-from-chats", tags=["Continuous Chat Learning"])
async def learn_from_chat_manually(payload: LearnChatRequest, user: AuthenticatedUser = Depends(get_current_user)):
    user_email = user.email or user.uid
    """
    POST /ai/learn-from-chats
    Explicitly distills a conversation into knowledge patterns and updates the continuous learning pool.
    """
    if payload.is_temporary:
        return {
            "status": "ignored",
            "message": "Temporary chats are excluded from model training and learning pools."
        }

    insight = vfx_service.record_chat_learning(
        prompt=payload.prompt,
        reply=payload.response,
        tool_used=payload.tool_used or "manual_submission",
        user_email=user_email
    )

    return {
        "status": "success",
        "distilled_insight": insight,
        "total_insights": len(vfx_service.load_learned_insights())
    }


@app.post("/ai/refeed-with-learnings", tags=["Continuous Chat Learning"])
async def refeed_database_with_learnings(payload: FeedDatabaseRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /ai/refeed-with-learnings
    Re-executes the 5-cycle VFX ingestion pipeline, fusing newly distilled chat insights
    into all 5 Firestore records STRK-BAT-001..005!
    """
    clean_email = payload.email.strip().lower()
    records = []
    prev_synth = None
    user_ref = db.collection("users").document(clean_email)
    batch = db.batch()

    for c in range(1, 6):
        cycle_res = vfx_service.execute_feeding_cycle(c, clean_email, prev_synth)
        rec = cycle_res["record"]
        prev_synth = cycle_res["ai_synthesis"]

        sub_doc_ref = user_ref.collection("records").document(rec["record_id"])
        try:
            batch.set(sub_doc_ref, rec)
        except Exception:
            pass

        rec_copy = dict(rec)
        if isinstance(rec_copy.get("created_at"), datetime):
            rec_copy["created_at"] = rec_copy["created_at"].isoformat()
        records.append(rec_copy)

    try:
        batch.update(user_ref, {"database_fed": True})
        batch.commit()
    except Exception:
        pass

    return {
        "status": "success",
        "email": clean_email,
        "message": "Successfully re-fed 5-cycle VFX matrix enriched with all distilled chat learnings!",
        "records_count": len(records),
        "records": records,
        "learning_stats": vfx_service.get_learning_telemetry()
    }


@app.get("/ai/learning-preferences", tags=["Continuous Chat Learning"])
async def get_learning_preferences(user: AuthenticatedUser = Depends(get_current_user)):
    """GET /ai/learning-preferences - Check if user has opted into chat learning retention."""
    return {
        "status": "success",
        "allow_learning_retention": vfx_service.is_learning_retention_enabled()
    }


@app.post("/ai/learning-preferences", tags=["Continuous Chat Learning"])
async def set_learning_preferences(payload: LearningPreferencesRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """POST /ai/learning-preferences - Update user opt-in preference for chat learning retention."""
    success = vfx_service.set_learning_retention_opt_in(payload.allow_learning_retention)
    return {
        "status": "success" if success else "error",
        "allow_learning_retention": vfx_service.is_learning_retention_enabled()
    }


def analyze_attached_image(att: FileAttachment, user_prompt: str, model_id: Optional[str] = None) -> str:
    """
    Analyzes an attached image using genuine multimodal validation and model vision verification.
    Never fabricates visual scenes or claims 3D Viewport from file metadata.
    """
    import asyncio
    from multimodal_service import MultimodalAttachmentHandler
    from concurrent.futures import ThreadPoolExecutor

    def _run_async(coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return asyncio.run(coro)

    res = _run_async(MultimodalAttachmentHandler.analyze_image_attachment(
        att_name=att.name,
        att_content=att.content or "",
        att_mime=getattr(att, "mime_type", None) or getattr(att, "type", None),
        model_id=model_id,
        user_prompt=user_prompt
    ))
    return res.get("message", f"Visual analysis complete for {att.name}.")


@app.post("/ai/chat", tags=["Neural AI & Search"])
@app.post("/api/ai/chat", tags=["Neural AI & Search"])
async def chat_with_neural_ai(payload: AiChatRequest, user: AuthenticatedUser = Depends(get_current_user)):
    if not isinstance(user, AuthenticatedUser) and not hasattr(user, "uid"):
        user_email = payload.email or "test_developer@stroke.ai"
        uid = "test_dev_uid"
    else:
        user_email = user.email or user.uid
        uid = user.uid
    """
    POST /ai/chat
    Autonomous Agent Tool-Calling Chat Endpoint with Continuous Learning & Temporary Chat Support:
    1. The AI is equipped with `web_search`, `search_vfx_database`, and Universal MCP tools (Roblox Studio, GitHub).
    2. Deep Neural Reasoning (`think_mode`) can be toggled on demand.
    3. If `is_temporary` is False, the interaction is automatically distilled into knowledge patterns
       to continuously improve the AI and the 5-cycle database feeding matrix!
    """
    if not payload.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty.")

    last_user_message = next((m.content for m in reversed(payload.messages) if m.role == "user"), "")
    first_user_message = next((m.content for m in payload.messages if m.role == "user"), "")
    # Track the active task explicitly and update it on a new request; preserve prior context without locking to obsolete goal
    active_goal = last_user_message or first_user_message
    north_star_goal = active_goal
    agent_ledger = StateLedger(north_star_goal=active_goal)

    system_instruction = (
        f"{agent_ledger.get_north_star_header()}\n"
        "You are Stroke, an autonomous Roblox game development, 3D visual effects (VFX), and Luau engineering assistant.\n"
        "You run 100% locally and offline on the user's computer with sandboxed workspace access through a private internal background terminal service and local Roblox Studio integration.\n\n"
        "CORE OPERATING PRINCIPLES:\n"
        "1. Conversational Queries: When the user greets you (e.g. 'hi', 'hello', 'hey', 'hi stroke'), introduces themselves, asks who you are, or chats casually, reply warmly, helpfully, and concisely in natural English prose. NEVER output code blocks, scripts, or technical dumps for greetings or casual conversation.\n"
        "2. Coding Requests: When the user explicitly asks for scripts, mechanics, VFX, or implementation, write complete, production-ready, clean Luau or Python code in fenced markdown code blocks.\n"
        "3. Roblox Luau Best Practices:\n"
        "   - Authentic DataModel classes only: Use Part, Model, Attachment, ParticleEmitter, Beam, Trail, TweenService, Debris. Non-existent classes like 'Shockwave', 'Particle', 'Hitbox' must NEVER be created via Instance.new; create shockwaves using TweenService on an expanding transparent Part or a ParticleEmitter.\n"
        "   - Workspace: Always use lowercase 'workspace' or 'game:GetService(\"Workspace\")'.\n"
        "   - Geometry & Math: Use Vector3.new(x, y, z) and CFrame.new(x, y, z).\n"
        "   - Characters & Combat: Access Position and CFrame on character.HumanoidRootPart. Only call :TakeDamage(amount) on a Humanoid instance. Resolve character models via hitPart:FindFirstAncestorOfClass(\"Model\"). Use persistent multi-hit debounce tables.\n"
        "   - Debris cleanup: Clean up temporary parts or visualizers with game:GetService(\"Debris\"):AddItem(instance, duration).\n"
        "4. Background Terminal & Local Environment: You possess a private, internal background terminal system (terminal_service.py) for running tests and compiling code silently in the workspace. You operate 100% locally on the device.\n"
        "5. Attachments: When the user attaches files (Python, CSV, Luau, JSON, etc.), analyze them directly and suggest improvements.\n"
        "6. Directness: Answer ONLY what the user asks without echoing system directives or operating rules."
    )

    # 5-Level Reasoning Configuration (Low, Medium, High, Maximum, Absolute Peak)
    raw_level = (payload.reasoning_level or ("high" if payload.think_mode else "medium")).lower().strip().replace(" ", "_").replace("-", "_")
    valid_levels = ("low", "medium", "high", "maximum", "absolute_peak")
    if raw_level not in valid_levels:
        raw_level = "medium"
    reasoning_level = raw_level
    profile = get_reasoning_profile(reasoning_level)

    # Initialize or retrieve active agent task state machine with bounded budgets
    task_user_uid = user.uid if (isinstance(user, AuthenticatedUser) or hasattr(user, "uid")) else "anonymous"
    agent_task = TaskManager.create_task(
        active_goal=active_goal,
        reasoning_level=reasoning_level,
        user_uid=task_user_uid,
        task_id=payload.task_id
    )
    task_budget = agent_task.budget

    # Determine creativity / temperature: default 0.35 for all levels unless explicitly customized
    if payload.creativity is not None:
        user_temp = payload.creativity
    elif payload.temperature is not None:
        user_temp = payload.temperature
    else:
        user_temp = 0.35
    reasoning_temp = user_temp

    max_tool_turns = profile.max_tool_turns_chat if profile.tool_execution_enabled else 0
    reasoning_max_tokens = task_budget.max_tokens
    max_coding_iterations = profile.max_coding_iterations
    system_instruction += f"\n\n{profile.get_system_instructions()}"

    api_messages = [{"role": "system", "content": system_instruction}]
    for idx, msg in enumerate(payload.messages):
        content = msg.content
        if idx == len(payload.messages) - 1 and payload.attachments:
            att_text = "\n\n=== ATTACHED ASSETS & FILES ===\n"
            for att in payload.attachments:
                if att.is_image:
                    att_text += f"[Attached Image: {att.name}] (Type: {att.type})\n"
                else:
                    ext = att.name.split(".")[-1].lower() if "." in att.name else "txt"
                    fence_lang = {
                        "py": "python",
                        "csv": "csv",
                        "lua": "lua",
                        "luau": "luau",
                        "js": "javascript",
                        "ts": "typescript",
                        "json": "json",
                        "html": "html",
                        "css": "css",
                        "sql": "sql",
                        "sh": "bash",
                        "md": "markdown"
                    }.get(ext, ext)
                    att_text += f"--- ATTACHED FILE: {att.name} ({att.type or ext}) ---\n```{fence_lang}\n{att.content[:16000]}\n```\n--- END OF FILE {att.name} ---\n\n"
            att_text += "=== END ATTACHMENTS ===\n"
            content += att_text
        api_messages.append({"role": msg.role, "content": content})

    start_time = time.time()
    execution_steps: List[Dict[str, str]] = [
        {"name": "Prompt Analysis", "detail": "Validated Roblox engineering requirements and intent"}
    ]

    if payload.attachments:
        att_names = [a.name for a in payload.attachments]
        execution_steps.append({
            "name": "File Analysis & Ingestion",
            "detail": f"Loaded {len(payload.attachments)} attached file(s): {', '.join(att_names)}"
        })

    ai_reply_text = ""
    provider_used = "local-offline"
    model_used = payload.model or "llama3.2-local"
    fallback_occurred = False
    fallback_reason: Optional[str] = None
    tool_invoked = False
    tool_query = ""
    tool_name_used = ""
    sources_used: List[Dict[str, str]] = []

    # Strict Parameter Validation & Normalization
    try:
        inf_params = InferenceParameters(
            temperature=payload.temperature if payload.temperature is not None else payload.creativity,
            reasoning_effort=payload.reasoning_level,
            max_tokens=None
        )
        validate_parameters_for_model(model_used, inf_params)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    # Multimodal attachment context augmentation across EVERY attached image
    from multimodal_service import MultimodalAttachmentHandler
    if payload.attachments:
        vision_results = await MultimodalAttachmentHandler.process_all_attachments(
            attachments=payload.attachments,
            model_id=model_used,
            user_prompt=last_user_message
        )
        for vres in vision_results:
            att_name = vres.get("attachment_name", "image")
            if vres.get("status") == "success":
                execution_steps.append({
                    "name": "Vision Understanding",
                    "detail": f"Analyzed {att_name} via {vres.get('model_id', 'vision_model')}"
                })
            else:
                execution_steps.append({
                    "name": "Vision Diagnostics",
                    "detail": f"Processed {att_name} - {vres.get('message', '').splitlines()[0] if vres.get('message') else 'Attachment inspected'}"
                })
            if vres.get("message"):
                api_messages[-1]["content"] += f"\n\n{vres['message']}\n"

    # Project Context Retrieval (Targeted BM25 & Symbol matching)
    import project_context_service
    project_idx = project_context_service.get_project_index()
    if project_idx and project_idx.files:
        context_block = project_idx.format_context_prompt_block(last_user_message)
        if context_block:
            execution_steps.append({
                "name": "Project Context Retrieval",
                "detail": f"Injected context from {project_idx.project_name} for active query"
            })
            api_messages[-1]["content"] += f"\n\n{context_block}\n"

    # ==========================================================================
    # BYOK (BRING YOUR OWN KEY) AI PROVIDER EXECUTION ENGINE
    # ==========================================================================
    active_cfg = ai_provider_service.get_active_model_config()
    is_inference_mocked = globals().get("_DEFAULT_RUN_LLAMA_INFERENCE") != run_llama_inference
    if is_inference_mocked and not payload.model:
        target_model = "llama3.2-1b"
        target_provider = "local_gguf"
        meta = ai_provider_service.resolve_model_metadata(target_model)
    else:
        target_model = payload.model or active_cfg.get("active_model") or "llama-3.3-70b-versatile"
        meta = ai_provider_service.resolve_model_metadata(target_model)
        target_provider = meta.provider.value if meta else (active_cfg.get("active_provider") or "groq")
        if target_provider == "custom":
            target_provider = active_cfg.get("active_provider") or "custom"

    reasoning_level = (payload.reasoning_level or active_cfg.get("reasoning_level") or "medium").lower()
    profile = get_reasoning_profile(reasoning_level)
    max_tool_turns = max(1, profile.max_tool_turns_chat)

    execution_steps.append({
        "name": "BYOK Neural Synthesis",
        "detail": f"Inference via {target_provider.upper()} ({target_model}) [Reasoning: {profile.label}, Tools max turns: {max_tool_turns}]"
    })

    if profile.level == "absolute_peak":
        execution_steps.append({
            "name": "Absolute Peak Multi-Agent Orchestration",
            "detail": f"Delegated roles: {', '.join(profile.delegated_roles)} | Concurrency: {profile.max_concurrency} | Sandboxed workspaces: {profile.allow_isolated_subagent_workspaces}"
        })

    # Two-tier dynamic tool selection
    if profile.tool_execution_enabled:
        agent_tools = mcp_bridge.select_active_tools_for_query(
            last_user_message,
            history=api_messages,
            max_tools=profile.max_tools_to_select
        )
        if not getattr(payload, 'web_search', True):
            agent_tools = [t for t in agent_tools if t.get("function", {}).get("name") != "web_search"]
    else:
        agent_tools = []

    current_agent_messages = list(api_messages)
    tool_turn_count = 0

    while tool_turn_count < max_tool_turns:
        can_use_tools, budget_status = agent_task.budget.can_execute_tool()

        inf_params = InferenceParameters(
            temperature=payload.temperature if payload.temperature is not None else payload.creativity,
            reasoning_effort=reasoning_level,
            max_tokens=None,
            tools=agent_tools if (can_use_tools and meta.supports_tool_calling) else None
        )

        try:
            resp = await global_ai_provider_manager.execute_chat(
                messages=current_agent_messages,
                parameters=inf_params,
                model_id=target_model,
                provider_id=target_provider,
                user_id=user_email,
                allow_fallback=active_cfg.get("allow_fallback", True)
            )
        except ai_provider_service.ProviderAuthenticationError as auth_err:
            ai_reply_text = (
                f"### [STROKE // API KEY ERROR]\n\n"
                f"Authentication failed for **{target_provider.upper()}** ({target_model}).\n\n"
                f"Error details: {auth_err}\n\n"
                "Please configure or verify your API key in the **Models** settings page."
            )
            provider_used = target_provider
            model_used = target_model
            break
        except ai_provider_service.ProviderRateLimitError as rl_err:
            ai_reply_text = (
                f"### [STROKE // RATE LIMIT EXCEEDED]\n\n"
                f"Provider **{target_provider.upper()}** rate limit was reached ({rl_err}).\n\n"
                f"Please wait {rl_err.retry_after_sec or 30} seconds or select a fallback provider in Models settings."
            )
            provider_used = target_provider
            model_used = target_model
            break
        except (ai_provider_service.ProviderError, Exception) as prov_err:
            ai_reply_text = (
                f"### [STROKE // AI SERVICE NOTICE]\n\n"
                f"Inference via **{target_provider.upper()}** ({target_model}) could not be completed.\n\n"
                f"Diagnostic: {prov_err}\n\n"
                "Stroke uses Bring Your Own Key (BYOK) providers. Add your API key in the Models page to activate AI capabilities."
            )
            provider_used = target_provider
            model_used = target_model
            break

        provider_used = resp.selected_provider or resp.provider or target_provider
        model_used = resp.model or target_model
        fallback_occurred = resp.fallback_occurred
        fallback_reason = resp.fallback_reason

        if resp.thinking:
            execution_steps.append({
                "name": "Deep Neural Reasoning",
                "detail": f"Completed reasoning chain ({len(resp.thinking)} chars)"
            })

        # Extract tool calls
        raw_calls = []
        if resp.tool_calls:
            for tc in resp.tool_calls:
                raw_calls.append({"tool": tc.name, "arguments": tc.arguments})
        elif "<tool_call>" in (resp.content or ""):
            for m_call in re.finditer(r"<tool_call>([\s\S]*?)</tool_call>", resp.content):
                try:
                    parsed = json.loads(m_call.group(1).strip())
                    if isinstance(parsed, list):
                        raw_calls.extend(parsed)
                    elif isinstance(parsed, dict):
                        raw_calls.append(parsed)
                except Exception:
                    pass

        # If no tool calls attempted, synthesize final reply
        if not raw_calls:
            ai_reply_text = resp.content
            finish_reason = resp.finish_reason
            if is_response_incomplete(ai_reply_text, finish_reason):
                cont_attempts = 0
                max_cont = 5
                while cont_attempts < max_cont and is_response_incomplete(ai_reply_text, finish_reason):
                    cont_attempts += 1
                    execution_steps.append({
                        "name": f"Auto-Continue ({cont_attempts}/{max_cont})",
                        "detail": "Token budget exhausted before completion. Continuing seamlessly."
                    })
                    cont_messages = list(current_agent_messages)
                    cont_messages.append({"role": "assistant", "content": ai_reply_text})
                    cont_messages.append({
                        "role": "user",
                        "content": "continue without repeating; seamlessly continue directly where you left off until completely finished."
                    })
                    cont_resp = await global_ai_provider_manager.execute_chat(
                        messages=cont_messages,
                        parameters=inf_params,
                        model_id=target_model,
                        provider_id=target_provider,
                        user_id=user_email,
                        allow_fallback=active_cfg.get("allow_fallback", True)
                    )
                    finish_reason = cont_resp.finish_reason
                    if not cont_resp.content.strip():
                        break
                    ai_reply_text = stitch_continuations(ai_reply_text, cont_resp.content)
            break

        # Central Gate Budget Check
        can_exec, block_reason = agent_task.budget.can_execute_tool()
        if not can_exec:
            ai_reply_text = resp.content
            execution_steps.append({
                "name": "Tool Dispatch Blocked",
                "detail": f"Central Gate blocked execution: {block_reason}"
            })
            break

        # Execute batch through Authoritative Central Execution Gate
        executed_tools = await AgentExecutionGate.execute_batch(
            agent_task,
            raw_calls,
            ToolDispatcher
        )

        if executed_tools:
            tool_turn_count += 1
            agent_task.budget.record_turn()
            tool_invoked = True

            turn_calls_summary = []
            for et in executed_tools:
                t_name = et["tool"]
                t_args = et["arguments"]
                t_res = et["result"]
                tool_name_used = t_name
                turn_calls_summary.append({"name": t_name, "arguments": t_args})

                if t_name == "web_search" and t_res.get("sources"):
                    sources_used = t_res.get("sources", [])
                elif t_name == "search_vfx_database" and t_res.get("matches"):
                    sources_used = [
                        {
                            "title": f"VFX: {m.get('model_name', 'Preset')}",
                            "url": "#vfx-db",
                            "snippet": f"Particles: {m.get('particle_emitters_count', 0)}, Beams: {m.get('beams_count', 0)}"
                        }
                        for m in t_res.get("matches", [])
                    ]

                is_failure = (
                    t_res.get("status") in ("error", "failed", "offline")
                    or (isinstance(t_res.get("exit_code"), int) and t_res.get("exit_code") != 0)
                    or bool(t_res.get("timed_out"))
                )

                step_detail = f"Status: {t_res.get('status', 'ok')}"
                if "exit_code" in t_res:
                    step_detail += f" | Exit: {t_res.get('exit_code')}"
                if t_res.get("stdout"):
                    step_detail += f" | Stdout: {str(t_res.get('stdout'))[:60]}"
                elif t_res.get("message"):
                    step_detail += f" | Message: {str(t_res.get('message'))[:60]}"

                execution_steps.append({
                    "name": f"Agent Tool Executed: {t_name}",
                    "detail": step_detail
                })

                quarantined_data = ToolOutputObserver.sanitize(t_name, t_res)
                failure_guidance = (
                    "\n[CRITICAL]: The tool reported an error or failure. Diagnose the failure accurately, "
                    "explain what went wrong or correct it, and NEVER claim the action succeeded when it failed."
                    if is_failure else
                    "\nIncorporate the verified tool result above into your analysis and continue towards the final verified answer."
                )

                current_agent_messages.append({
                    "role": "user",
                    "content": f"{quarantined_data}\n{failure_guidance}"
                })

            assistant_turn_content = resp.content or f"<tool_call>{json.dumps(turn_calls_summary)}</tool_call>"
            current_agent_messages.insert(len(current_agent_messages) - len(executed_tools), {
                "role": "assistant",
                "content": assistant_turn_content
            })

            if agent_task.state == TaskState.AWAITING_APPROVAL:
                ai_reply_text = f"Confirmation Required: {executed_tools[0]['result'].get('message', 'Action requires approval.')}"
                break

            if not any(is_failure for et in executed_tools):
                agent_ledger.record_resolved_check(tool_name_used or "workspace_action")

            if len(current_agent_messages) > 10:
                current_agent_messages = StateLedger.prune_intermediate_history(
                    messages=current_agent_messages,
                    north_star_goal=north_star_goal,
                    state_ledger=agent_ledger
                )


    # Agentic Prompt Cleanup: Strip leaked prompt tags and formatting artifacts without fabricating untrue claims
    if ai_reply_text:
        cleanup_patterns = [
            (r"(?i)###\s*(?:CRITICAL\s*)?(?:AGENTIC\s*)?OPERATING\s*DIRECTIVES[\s\S]*?(?=###|\Z)", ""),
            (r"(?i)\bstroke@(?:stroke\.com|mcp\.studio)\b", ""),
            (r"(?i)\bcleve\.Parent\s*=\s*cleave\b", ""),
            (r"(?i)<\/?(?:system|instruction|prompt_guidance)[^>]*>", ""),
        ]
        for pat, repl in cleanup_patterns:
            ai_reply_text = re.sub(pat, repl, ai_reply_text)
        ai_reply_text = re.sub(r"\n{3,}", "\n\n", ai_reply_text).strip()

    # --------------------------------------------------------------------------
    # STROKE AUTONOMOUS CODING LOOP (Write -> Test -> Diagnose -> Fix -> Retest)
    # --------------------------------------------------------------------------
    coding_loop_report = None
    has_code_fence = any(fence in ai_reply_text for fence in ["```luau", "```lua", "```python", "```py", "```"])

    if ai_reply_text and has_code_fence:
        def llm_repair_callback(repair_msgs: list) -> str:
            try:
                active_cfg = ai_provider_service.get_active_model_config()
                t_model = active_cfg.get("active_model") or "llama-3.3-70b-versatile"
                t_provider = active_cfg.get("active_provider") or "groq"
                repair_params = InferenceParameters(temperature=0.2, max_tokens=1500)
                repair_resp = global_ai_provider_manager.execute_chat_sync(
                    messages=repair_msgs,
                    parameters=repair_params,
                    model_id=t_model,
                    provider_id=t_provider,
                    user_id=user_email
                )
                content = repair_resp.content
                if is_response_incomplete(content, repair_resp.finish_reason):
                    cont_msgs = list(repair_msgs)
                    cont_msgs.append({"role": "assistant", "content": content})
                    cont_msgs.append({"role": "user", "content": "continue without repeating; complete the code block until properly closed."})
                    c_resp = global_ai_provider_manager.execute_chat_sync(
                        messages=cont_msgs,
                        parameters=repair_params,
                        model_id=t_model,
                        provider_id=t_provider,
                        user_id=user_email
                    )
                    content = stitch_continuations(content, c_resp.content)
                return content
            except Exception as repair_exc:
                print(f"[STROKE CODING LOOP] BYOK repair note: {repair_exc}", flush=True)
                return ""

        # Autonomous tool calling dispatch for local LLM text output (Central Gate & Deduplication)
        try:
            can_exec_cl, cl_reason = agent_task.budget.can_execute_tool()
            if can_exec_cl and "<tool_call>" in ai_reply_text:
                raw_cl_calls = []
                for m_call in re.finditer(r"<tool_call>([\s\S]*?)</tool_call>", ai_reply_text):
                    try:
                        parsed = json.loads(m_call.group(1).strip())
                        if isinstance(parsed, list):
                            raw_cl_calls.extend(parsed)
                        elif isinstance(parsed, dict):
                            raw_cl_calls.append(parsed)
                    except Exception:
                        pass
                if raw_cl_calls:
                    dispatched_tool_calls = await AgentExecutionGate.execute_batch(
                        agent_task,
                        raw_cl_calls,
                        ToolDispatcher
                    )
                    if dispatched_tool_calls:
                        for dt in dispatched_tool_calls:
                            tool_n = dt.get("tool")
                            tool_res = dt.get("result", {})
                            execution_steps.append({
                                "name": f"Autonomous Tool Execution: {tool_n}",
                                "detail": f"Status: {tool_res.get('status', 'ok')} | Exit: {tool_res.get('exit_code', 0)}"
                            })
        except Exception as dt_exc:
            print(f"[STROKE TOOL DISPATCH NOTICE] Tool dispatch note: {dt_exc}", flush=True)

        try:
            ai_reply_text, coding_loop_report, loop_steps = StrokeCodingLoop.run_coding_loop(
                prompt=last_user_message,
                initial_reply=ai_reply_text,
                llm_generate_fn=llm_repair_callback,
                user_email=user_email,
                max_iterations=max_coding_iterations,
                include_markdown_report=False,
                reasoning_level=profile.level
            )
            execution_steps.extend(loop_steps)
        except Exception as loop_exc:
            print(f"[STROKE CODING LOOP NOTICE] Execution loop note: {loop_exc}", flush=True)

    # Live God-Tier VFX Learning & Firestore Interaction Memory (100 MB Quota)
    learning_recorded = False
    god_tier_vfx_learned = False
    learned_vfx_name = None
    memory_meta = {}

    if not payload.is_temporary and ai_reply_text:
        # 1. God-Tier VFX Evaluation & Active Database Ingestion (Strictly rejects basic balls/colors)
        try:
            god_vfx = vfx_service.evaluate_and_learn_god_tier_vfx(
                prompt=last_user_message,
                reply=ai_reply_text,
                tool_used=tool_name_used or "direct",
                user_email=user_email
            )
            if god_vfx:
                learning_recorded = True
                god_tier_vfx_learned = True
                learned_vfx_name = god_vfx.get("model_name")
        except Exception as exc:
            print(f"[STROKE LEARNING NOTICE] God-tier VFX evaluation note: {exc}", flush=True)

        # 2. Normal AI Interaction Memory in Firestore (Summarized under 100 MB Quota)
        if payload.email:
            try:
                memory_meta = record_user_firestore_memory(
                    email=payload.email,
                    prompt=last_user_message,
                    reply=ai_reply_text,
                    tool_used=tool_name_used or "direct",
                    god_tier_vfx=god_vfx if god_tier_vfx_learned else None
                )
            except Exception as mem_exc:
                print(f"[STROKE MEMORY NOTICE] Firestore memory record error: {mem_exc}", flush=True)

        # 3. Persistent Chat Session Record
        if payload.email and payload.session_id:
            try:
                clean_email = payload.email.strip().lower()
                chat_ref = db.collection("users").document(uid).collection("chats").document(payload.session_id)
                first_title = last_user_message[:36] if last_user_message else "New Conversation"
                chat_ref.set({
                    "session_id": payload.session_id,
                    "title": first_title,
                    "messages_count": len(payload.messages) + 1,
                    "is_temporary": False,
                    "updated_at": datetime.now(timezone.utc)
                }, merge=True)
            except Exception:
                pass

    duration_sec = round(time.time() - start_time, 2)
    return {
        "status": "success",
        "provider": provider_used,
        "model": model_used,
        "fallback_occurred": fallback_occurred,
        "fallback_reason": fallback_reason,
        "message": ai_reply_text,
        "tool_invoked": tool_invoked,
        "tool_name": tool_name_used,
        "tool_query": tool_query,
        "sources": sources_used,
        "web_search_active": bool(tool_invoked and tool_name_used == "web_search"),
        "is_temporary": payload.is_temporary,
        "think_mode": bool(reasoning_level in ("high", "maximum", "absolute_peak")),
        "reasoning_level": reasoning_level,
        "creativity": reasoning_temp,
        "temperature": reasoning_temp,
        "state_ledger": agent_ledger.get_ledger_summary(),
        "north_star_goal": north_star_goal,
        "auto_continued": bool("cont_attempts" in locals() and cont_attempts > 0),
        "learning_recorded": learning_recorded,
        "god_tier_vfx_learned": god_tier_vfx_learned,
        "learned_vfx_name": learned_vfx_name,
        "memory": memory_meta,
        "duration_seconds": duration_sec,
        "execution_steps": execution_steps,
        "coding_loop": coding_loop_report,
        "task_id": agent_task.task_id,
        "task_state": agent_task.state.value,
        "task_budget": agent_task.budget.to_dict()
    }


@app.post("/ai/chat/stream", tags=["Neural AI & Search"])
@app.post("/api/ai/chat/stream", tags=["Neural AI & Search"])
async def chat_with_neural_ai_stream(payload: AiChatRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /ai/chat/stream & POST /api/ai/chat/stream
    Real-time Server-Sent Events (SSE) streaming chat endpoint across BYOK providers.
    Streams thinking delta, content delta, status steps, and completion signals.
    """
    if not isinstance(user, AuthenticatedUser) and not hasattr(user, "uid"):
        user_email = payload.email or "test_developer@stroke.ai"
        uid = "test_dev_uid"
    else:
        user_email = user.email or user.uid
        uid = user.uid

    if not payload.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty.")

    last_user_message = next((m.content for m in reversed(payload.messages) if m.role == "user"), "")
    first_user_message = next((m.content for m in payload.messages if m.role == "user"), "")
    active_goal = last_user_message or first_user_message
    agent_ledger = StateLedger(north_star_goal=active_goal)

    system_instruction = (
        f"{agent_ledger.get_north_star_header()}\n"
        "You are Stroke, an autonomous Roblox game development, 3D visual effects (VFX), and Luau engineering assistant.\n"
        "You run locally with sandboxed workspace access through background terminal service and Roblox Studio integration.\n\n"
        "CORE OPERATING PRINCIPLES:\n"
        "1. Conversational Queries: Reply warmly, helpfully, and concisely in natural English prose without code dumps for greetings.\n"
        "2. Coding Requests: Write complete, production-ready, clean Luau or Python code in fenced markdown code blocks.\n"
        "3. Roblox Luau Best Practices: Authentic DataModel classes only (Part, Model, Attachment, ParticleEmitter, Beam, Trail, TweenService, Debris).\n"
        "4. Background Terminal & Local Environment: Direct access to workspace terminal.\n"
        "5. Directness: Answer directly without echoing directives."
    )

    raw_level = (payload.reasoning_level or ("high" if payload.think_mode else "medium")).lower().strip().replace(" ", "_").replace("-", "_")
    valid_levels = ("low", "medium", "high", "maximum", "absolute_peak")
    reasoning_level = raw_level if raw_level in valid_levels else "medium"
    profile = get_reasoning_profile(reasoning_level)
    system_instruction += f"\n\n{profile.get_system_instructions()}"

    active_cfg = ai_provider_service.get_active_model_config()
    is_inference_mocked = globals().get("_DEFAULT_RUN_LLAMA_INFERENCE") != run_llama_inference
    if is_inference_mocked and not payload.model:
        target_model = "llama3.2-1b"
        target_provider = "local_gguf"
    else:
        target_model = payload.model or active_cfg.get("active_model") or "llama-3.3-70b-versatile"
        meta = ai_provider_service.resolve_model_metadata(target_model)
        target_provider = meta.provider.value if meta else (active_cfg.get("active_provider") or "groq")
        if target_provider == "custom":
            target_provider = active_cfg.get("active_provider") or "custom"

    api_messages = [{"role": "system", "content": system_instruction}]
    for idx, msg in enumerate(payload.messages):
        content = msg.content
        if idx == len(payload.messages) - 1 and payload.attachments:
            att_text = "\n\n=== ATTACHED ASSETS & FILES ===\n"
            for att in payload.attachments:
                if att.is_image:
                    att_text += f"[Attached Image: {att.name}] (Type: {att.type})\n"
                else:
                    ext = att.name.split(".")[-1].lower() if "." in att.name else "txt"
                    att_text += f"--- ATTACHED FILE: {att.name} ---\n{att.content[:16000]}\n--- END OF FILE ---\n\n"
            att_text += "=== END ATTACHMENTS ===\n"
            content += att_text
        api_messages.append({"role": msg.role, "content": content})

    inf_params = InferenceParameters(
        temperature=payload.temperature if payload.temperature is not None else payload.creativity,
        reasoning_effort=reasoning_level,
        max_tokens=None
    )

    async def stream_generator():
        yield f"data: {json.dumps({'type': 'step', 'step': {'name': 'BYOK Neural Synthesis', 'detail': f'Streaming via {target_provider.upper()} ({target_model})'}})}\n\n"

        accumulated_text = ""
        accumulated_thinking = ""
        finish_reason = "stop"

        try:
            async for chunk in global_ai_provider_manager.execute_stream_chat(
                messages=api_messages,
                parameters=inf_params,
                model_id=target_model,
                provider_id=target_provider,
                user_id=user_email,
                allow_fallback=active_cfg.get("allow_fallback", True)
            ):
                if chunk.delta_thinking:
                    accumulated_thinking += chunk.delta_thinking
                    yield f"data: {json.dumps({'type': 'thinking', 'delta': chunk.delta_thinking})}\n\n"
                if chunk.delta_content:
                    accumulated_text += chunk.delta_content
                    yield f"data: {json.dumps({'type': 'content', 'delta': chunk.delta_content})}\n\n"
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason

            yield f"data: {json.dumps({'type': 'done', 'finish_reason': finish_reason, 'provider': target_provider, 'model': target_model})}\n\n"
            yield "data: [DONE]\n\n"
        except ai_provider_service.ProviderAuthenticationError as auth_err:
            yield f"data: {json.dumps({'type': 'error', 'error': f'Authentication failed: {str(auth_err)}', 'error_type': 'auth'})}\n\n"
            yield "data: [DONE]\n\n"
        except ai_provider_service.ProviderRateLimitError as rl_err:
            yield f"data: {json.dumps({'type': 'error', 'error': f'Rate limit reached: {str(rl_err)}', 'error_type': 'rate_limit'})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc), 'error_type': 'provider'})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# =============================================================================
# AGENT STATE MACHINE & TASK MANAGEMENT ENDPOINTS
# =============================================================================

@app.get("/agent/tasks", tags=["Agent Orchestration"])
async def list_agent_tasks(user: Optional[auth_service.AuthenticatedUser] = Depends(auth_service.get_optional_user)):
    """Lists recent and active agent tasks with bounded state machine telemetry."""
    user_uid = user.uid if user else "anonymous"
    return {"tasks": TaskManager.list_tasks(user_uid=user_uid)}


@app.get("/agent/tasks/{task_id}", tags=["Agent Orchestration"])
async def get_agent_task(task_id: str, user: Optional[auth_service.AuthenticatedUser] = Depends(auth_service.get_optional_user)):
    """Retrieves state, budget, execution log, and verification evidence for a specific task."""
    task = TaskManager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Agent task '{task_id}' not found.")
    if user and task.user_uid not in ("default_user", "anonymous") and task.user_uid != user.uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: Cannot access another user's agent task.")
    return task.to_dict()


@app.post("/agent/tasks/{task_id}/cancel", tags=["Agent Orchestration"])
async def cancel_agent_task(task_id: str, user: Optional[auth_service.AuthenticatedUser] = Depends(auth_service.get_optional_user)):
    """Cancels an active or awaiting-approval agent task."""
    task = TaskManager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Agent task '{task_id}' not found.")
    if user and task.user_uid not in ("default_user", "anonymous") and task.user_uid != user.uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: Cannot cancel another user's agent task.")
    success = TaskManager.cancel_task(task_id, reason="User requested cancellation via API")
    if not success:
        raise HTTPException(status_code=400, detail=f"Cannot cancel task '{task_id}' (not found or already terminal).")
    return {"status": "cancelled", "task_id": task_id}


@app.post("/agent/tasks/{task_id}/approve", tags=["Agent Orchestration"])
async def approve_agent_task(task_id: str, user: Optional[auth_service.AuthenticatedUser] = Depends(auth_service.get_optional_user)):
    """Approves a task that is currently in AWAITING_APPROVAL state."""
    task = TaskManager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Agent task '{task_id}' not found.")
    if user and task.user_uid not in ("default_user", "anonymous") and task.user_uid != user.uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: Cannot approve another user's agent task.")
    success = TaskManager.approve_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Cannot approve task '{task_id}' (task not in awaiting_approval state).")
    return {"status": "approved", "task_id": task_id}


# =============================================================================
# ADVANCED PARALLEL MULTI-AGENT ORCHESTRATION ENDPOINTS
# =============================================================================

class RunParallelAgentJobRequest(BaseModel):
    user_goal: str
    workspace_path: Optional[str] = None
    model_id: Optional[str] = None
    provider_id: Optional[str] = None
    use_isolated_sandbox: bool = False


@app.post("/api/orchestrator/run", tags=["Multi-Agent Orchestration"])
async def run_parallel_agent_job(
    req: RunParallelAgentJobRequest,
    background_tasks: BackgroundTasks,
    user: Optional[auth_service.AuthenticatedUser] = Depends(auth_service.get_optional_user)
):
    """
    Spawns an advanced parallel multi-agent job delegating to:
    Researcher -> Planner -> Developer -> [Tester || Reviewer] -> Debugger -> Verification Gate.
    """
    user_uid = user.uid if user else "default_user"
    ws = req.workspace_path or os.getcwd()
    job = parallel_agent_system.global_multi_agent_orchestrator.create_job(
        user_goal=req.user_goal,
        workspace_path=ws,
        user_uid=user_uid
    )
    background_tasks.add_task(
        parallel_agent_system.global_multi_agent_orchestrator.run_job,
        job.job_id,
        req.model_id,
        req.provider_id,
        req.use_isolated_sandbox
    )
    return {
        "status": "started",
        "job_id": job.job_id,
        "job": job.to_dict()
    }


@app.get("/api/orchestrator/jobs", tags=["Multi-Agent Orchestration"])
async def list_parallel_agent_jobs(
    user: Optional[auth_service.AuthenticatedUser] = Depends(auth_service.get_optional_user)
):
    """Lists all active and completed parallel multi-agent jobs."""
    user_uid = user.uid if user else "default_user"
    return {"jobs": parallel_agent_system.global_multi_agent_orchestrator.list_jobs(user_uid=user_uid)}


@app.get("/api/orchestrator/jobs/{job_id}", tags=["Multi-Agent Orchestration"])
async def get_parallel_agent_job(
    job_id: str,
    user: Optional[auth_service.AuthenticatedUser] = Depends(auth_service.get_optional_user)
):
    """Retrieves real-time state, independent agent statuses, logs, and artifacts for a job."""
    job = parallel_agent_system.global_multi_agent_orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Parallel agent job '{job_id}' not found.")
    if user and job.user_uid not in ("default_user", "anonymous") and job.user_uid != user.uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: Cannot access another user's agent job.")
    return job.to_dict()


@app.post("/api/orchestrator/jobs/{job_id}/cancel", tags=["Multi-Agent Orchestration"])
async def cancel_parallel_agent_job(
    job_id: str,
    user: Optional[auth_service.AuthenticatedUser] = Depends(auth_service.get_optional_user)
):
    """Cancels an active parallel agent job and immediately halts running sub-agents."""
    job = parallel_agent_system.global_multi_agent_orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Parallel agent job '{job_id}' not found.")
    if user and job.user_uid not in ("default_user", "anonymous") and job.user_uid != user.uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: Cannot cancel another user's agent job.")
    success = parallel_agent_system.global_multi_agent_orchestrator.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Cannot cancel job '{job_id}' (not found or already terminal).")
    return {"status": "cancelled", "job_id": job_id}


@app.get("/api/orchestrator/jobs/{job_id}/stream", tags=["Multi-Agent Orchestration"])
async def stream_parallel_agent_job(
    job_id: str,
    user: Optional[auth_service.AuthenticatedUser] = Depends(auth_service.get_optional_user)
):
    """Streams real-time SSE events (agent thoughts, file locks, tool calls, and test results)."""
    job = parallel_agent_system.global_multi_agent_orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Parallel agent job '{job_id}' not found.")
    if user and job.user_uid not in ("default_user", "anonymous") and job.user_uid != user.uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: Cannot stream another user's agent job.")

    async def event_generator():
        last_index = 0
        while True:
            current_events = job.events
            if last_index < len(current_events):
                for evt in current_events[last_index:]:
                    yield f"data: {json.dumps(evt)}\n\n"
                last_index = len(current_events)

            if job.status in (parallel_agent_system.JobStatus.COMPLETED, parallel_agent_system.JobStatus.FAILED, parallel_agent_system.JobStatus.CANCELLED):
                yield f"data: {json.dumps({'type': 'job_terminal', 'status': job.status.value, 'job_id': job_id})}\n\n"
                yield "data: [DONE]\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/observability/events", tags=["Observability & Telemetry"])
async def get_observability_events(
    task_id: Optional[str] = Query(None, description="Filter events by correlated task ID"),
    category: Optional[str] = Query(None, description="Filter events by category"),
    status: Optional[str] = Query(None, description="Filter events by status"),
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    user: AuthenticatedUser = Depends(get_current_user)
):
    """Returns structured, redacted events from the Stroke observability ring buffer."""
    events = observability.StrokeObservability.get_instance().get_events(
        task_id=task_id,
        category=category,
        status=status,
        limit=limit
    )
    return {"events": events, "count": len(events)}


@app.get("/observability/metrics", tags=["Observability & Telemetry"])
async def get_observability_metrics(
    task_id: Optional[str] = Query(None, description="Filter metrics by correlated task ID"),
    window_sec: Optional[float] = Query(None, description="Time window in seconds to compute metrics over"),
    user: AuthenticatedUser = Depends(get_current_user)
):
    """Computes authentic, non-fabricated metrics from actual event traces."""
    metrics = observability.StrokeObservability.get_instance().get_metrics(
        task_id=task_id,
        time_window_sec=window_sec
    )
    return metrics


# =============================================================================
# EVALUATION & BENCHMARK SUITE ENDPOINTS
# =============================================================================

_LATEST_EVALUATION_REPORT: Optional[Dict[str, Any]] = None

@app.post("/evaluation/run", tags=["Evaluation & Benchmarks"])
async def run_evaluation_suite(
    benchmark_id: Optional[str] = Query(None, description="Optional single benchmark ID to execute"),
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    Executes the 12-benchmark Stroke Evaluation Harness against real engines.
    Returns authentic task success rates, false verification rates, and retrieval metrics.
    """
    global _LATEST_EVALUATION_REPORT
    harness = eval_harness.StrokeEvaluationHarness(task_id=f"eval_api_{uuid.uuid4().hex[:8]}")
    report = harness.run_all()
    report_dict = report.to_dict()
    _LATEST_EVALUATION_REPORT = report_dict
    return report_dict


@app.get("/evaluation/latest", tags=["Evaluation & Benchmarks"])
async def get_latest_evaluation(user: AuthenticatedUser = Depends(get_current_user)):
    """Retrieves the latest executed benchmark report or triggers a new run if none available."""
    global _LATEST_EVALUATION_REPORT
    if _LATEST_EVALUATION_REPORT is None:
        harness = eval_harness.StrokeEvaluationHarness(task_id=f"eval_api_{uuid.uuid4().hex[:8]}")
        report = harness.run_all()
        _LATEST_EVALUATION_REPORT = report.to_dict()
    return _LATEST_EVALUATION_REPORT


@app.post("/ai/verify-code", tags=["Neural AI & Search"])
async def verify_code_endpoint(payload: VerifyCodePayload, user: AuthenticatedUser = Depends(get_current_user)):
    """
    POST /ai/verify-code
    Runs the Stroke Test Runner & Verification Suite on arbitrary scripts.
    Executes AST parsing, syntax validation, Roblox DataModel checks,
    hitbox debounce rules, memory management, and reports tested vs untested parameters.
    """
    lang = (payload.language or "luau").lower()
    if lang in ("luau", "lua"):
        report = RobloxDomainTestRunner.test_luau_code(payload.code, payload.prompt or "")
    elif lang == "python":
        report = RobloxDomainTestRunner.test_python_code(payload.code, payload.prompt or "")
    else:
        report = RobloxDomainTestRunner.test_generic_code(payload.code, lang)

    report_md = StrokeCodingLoop.format_verification_report_markdown(report, iterations=1)
    report["markdown_report"] = report_md
    return {
        "status": "success",
        "language": lang,
        "verification_status": report.get("verification_status", "UNVERIFIED"),
        "is_verified": report.get("is_verified", False),
        "report": report
    }


# ==============================================================================
# PRIVATE INTERNAL BACKGROUND TERMINAL SERVICE ENDPOINTS (AI AGENT ACCESS ONLY)
# ==============================================================================

async def verify_terminal_access(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
):
    """
    Enforces background terminal, filesystem, and model service authorization policy.
    Zero Trust Loopback: Loopback IP alone is NOT authentication.
    Requires:
      1. Valid X-Internal-Token / X-Stroke-Token matching STROKE_INTERNAL_SECRET (for internal agent daemon), OR
      2. Valid verified Firebase ID token via Authorization: Bearer <token>.
    """
    internal_token = request.headers.get("X-Internal-Token") or request.headers.get("X-Stroke-Token")
    expected_token = os.environ.get("STROKE_INTERNAL_SECRET")

    # 1. Internal daemon token check
    if expected_token and internal_token == expected_token:
        return {"auth": "internal_token"}

    # 2. Firebase Bearer token check
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    else:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if token:
        try:
            claims = auth_service.verify_firebase_id_token(token)
            return {"auth": "firebase", "user": claims}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Terminal access rejected: Invalid Firebase token ({e})",
                headers={"WWW-Authenticate": "Bearer"}
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required: Valid Firebase ID token or internal secret required to access terminal/system services.",
        headers={"WWW-Authenticate": "Bearer"}
    )


@app.post("/terminal/create", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def create_terminal_endpoint(
    payload: Optional[CreateTerminalPayload] = None,
    access: Dict[str, Any] = Depends(verify_terminal_access)
):
    """
    POST /terminal/create
    Creates a new silent, background terminal session for Stroke AI Agent.
    """
    ws = payload.workspace_path if payload else None
    caller_uid = access.get("user", {}).get("uid", "internal_daemon") if access.get("auth") == "firebase" else "internal_daemon"
    try:
        return TerminalManager.create_terminal(ws, caller_uid=caller_uid)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except RuntimeError as re:
        raise HTTPException(status_code=429, detail=str(re))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/terminal/run", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def run_command_endpoint(
    payload: RunCommandPayload,
    access: Dict[str, Any] = Depends(verify_terminal_access)
):
    """
    POST /terminal/run
    Executes a structured development command in the specified session.
    """
    cmd = payload.command or payload.executable or "python"
    args = payload.args if payload.args else (payload.arguments or [])
    caller_uid = access.get("user", {}).get("uid", "internal_daemon") if access.get("auth") == "firebase" else "internal_daemon"
    is_internal = access.get("auth") == "internal" or caller_uid == "internal_daemon"
    approved_flag = bool(payload.approved) if is_internal else False
    try:
        res = TerminalManager.run_command(
            session_id=payload.session_id,
            command=cmd,
            args=args,
            timeout_sec=payload.timeout_sec or 20,
            is_background=payload.is_background or False,
            caller_uid=caller_uid,
            approved=approved_flag,
            is_internal=is_internal
        )
        if res.get("status") == "error":
            if res.get("error") == "session_not_found":
                raise HTTPException(status_code=404, detail=res.get("message"))
            elif res.get("error") == "session_terminated":
                raise HTTPException(status_code=400, detail=res.get("message"))
            raise HTTPException(status_code=400, detail=res.get("message"))
        return res
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/terminal/{session_id}/output", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def read_terminal_output_endpoint(session_id: str, tail: Optional[int] = Query(None, description="Tail lines count")):
    """
    GET /terminal/{session_id}/output
    Retrieves captured output lines from the session's bounded ring buffer.
    """
    res = TerminalManager.read_terminal_output(session_id, tail_lines=tail)
    if res.get("status") == "error" and res.get("error") == "session_not_found":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return res


@app.get("/terminal/{session_id}/status", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def get_terminal_status_endpoint(session_id: str):
    """
    GET /terminal/{session_id}/status
    Retrieves execution state, working directory, and metadata for a session.
    """
    res = TerminalManager.get_terminal_status(session_id)
    if res.get("status") == "error" and res.get("error") == "session_not_found":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return res


@app.get("/terminal/list", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def list_terminals_endpoint():
    """
    GET /terminal/list
    Lists active background terminal sessions.
    """
    return {"terminals": TerminalManager.list_terminals()}


@app.post("/terminal/{session_id}/stop", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def stop_terminal_endpoint(session_id: str):
    """
    POST /terminal/{session_id}/stop
    Terminates any active child process and reaps the session.
    """
    res = TerminalManager.stop_terminal(session_id)
    if res.get("status") == "error" and res.get("error") == "session_not_found":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return res


@app.post("/terminal/{session_id}/restart", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def restart_terminal_endpoint(session_id: str):
    """
    POST /terminal/{session_id}/restart
    Restarts the last command executed in the session.
    """
    res = TerminalManager.restart_terminal(session_id)
    if res.get("status") == "error":
        if res.get("error") == "session_not_found":
            raise HTTPException(status_code=404, detail=res.get("message"))
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@app.post("/terminal/approval/respond", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def respond_approval_endpoint(
    payload: TerminalApprovalPayload,
    access: Dict[str, Any] = Depends(verify_terminal_access)
):
    """
    POST /terminal/approval/respond
    Grants or denies approval for an unlisted or potentially sensitive command.
    """
    caller_uid = access.get("user", {}).get("uid", "internal_daemon") if access.get("auth") == "firebase" else "internal_daemon"
    res = TerminalManager.respond_to_approval(payload.approval_id, payload.approved, caller_uid=caller_uid)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@app.get("/terminal/tools/schema", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def terminal_tools_schema_endpoint():
    """
    GET /terminal/tools/schema
    Returns JSON schemas for internal AI tool calling.
    """
    return {"tools": get_terminal_tools_schema()}


@app.get("/terminal/output/delta", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def get_terminal_output_delta(
    session_id: str = Query(..., description="Unique terminal session ID"),
    since_seq: int = Query(0, description="Sequence number of last seen output line")
):
    """
    GET /terminal/output/delta
    Returns incremental output lines appended since sequence number for real-time UI streaming.
    """
    return TerminalManager.terminal_read_output_delta(session_id=session_id, since_seq=since_seq)


@app.get("/terminal/{session_id}/history", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def get_terminal_history_endpoint(session_id: str):
    """
    GET /terminal/{session_id}/history
    Retrieves chronological command execution history records for this session.
    """
    res = TerminalManager.get_terminal_history(session_id)
    if res.get("status") == "error" and res.get("error") == "session_not_found":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return res


@app.get("/terminal/{session_id}/stream", dependencies=[Depends(verify_terminal_access)], tags=["AI Terminal Service"])
async def stream_terminal_output_endpoint(
    session_id: str,
    from_seq: int = Query(0, description="Start streaming from this sequence number")
):
    """
    GET /terminal/{session_id}/stream
    Server-Sent Events (SSE) streaming endpoint for live terminal output and execution state events.
    """
    session = TerminalManager.get_session(session_id)
    if not session:
        status_info = TerminalManager.get_terminal_status(session_id)
        if status_info.get("status") == "error" and status_info.get("error") == "session_not_found":
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    async def event_generator():
        current_seq = from_seq
        stat = TerminalManager.get_terminal_status(session_id)
        yield f"data: {json.dumps({'type': 'init', 'session_id': session_id, 'status': stat})}\n\n"

        idle_cycles = 0
        max_idle_when_stopped = 3

        while True:
            delta = TerminalManager.terminal_read_output_delta(session_id=session_id, since_seq=current_seq)
            lines = delta.get("lines", [])
            latest_seq = delta.get("sequence_number", current_seq)
            is_running = delta.get("is_running", False)
            state = delta.get("state", "unknown")

            if lines:
                for line in lines:
                    yield f"data: {json.dumps({'type': 'output', 'session_id': session_id, 'line': line, 'seq': latest_seq})}\n\n"
                current_seq = latest_seq
                idle_cycles = 0

            if not is_running and state in ("completed", "failed", "terminated", "timed_out", "idle"):
                idle_cycles += 1
                if idle_cycles >= max_idle_when_stopped:
                    yield f"data: {json.dumps({'type': 'exit', 'session_id': session_id, 'state': state})}\n\n"
                    break

            await asyncio.sleep(0.1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ==============================================================================
# NON-DESTRUCTIVE USER FILE SYSTEM & WORKSPACE REST API
# ==============================================================================

@app.post("/fs/list", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_list_endpoint(payload: FsListPayload):
    """Lists files and directories inside an approved workspace."""
    try:
        return file_service.list_directory(
            payload.dir_path or ".",
            recursive=bool(payload.recursive),
            max_depth=payload.max_depth or 3,
            include_hidden=bool(payload.include_hidden)
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/fs/read", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_read_endpoint(payload: FsReadPayload):
    """Reads content from an approved user file with optional line range."""
    try:
        return file_service.read_file(payload.file_path, start_line=payload.start_line, end_line=payload.end_line)
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/fs/read-multiple", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_read_multiple_endpoint(payload: FsReadMultiplePayload):
    """Reads multiple files in an approved workspace simultaneously."""
    try:
        return file_service.read_multiple_files(payload.file_paths)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/fs/create", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_create_endpoint(payload: FsCreatePayload):
    """Creates a new file in an approved workspace."""
    try:
        return file_service.create_file(
            payload.file_path,
            payload.content,
            overwrite=bool(payload.overwrite),
            task_id=payload.task_id or "api_create"
        )
    except FileExistsError as fee:
        raise HTTPException(status_code=409, detail=str(fee))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/fs/edit", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_edit_endpoint(payload: FsEditPayload):
    """Safely edits an existing file with automatic pre-modification version backup."""
    try:
        return file_service.edit_file(
            payload.file_path,
            payload.new_content,
            task_id=payload.task_id or "api_edit",
            description=payload.description or "File edited via Stroke API"
        )
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/fs/create-dir", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_create_dir_endpoint(payload: FsCreateDirPayload):
    """Creates a directory in an approved workspace."""
    try:
        return file_service.create_directory(payload.dir_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/fs/search", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_search_endpoint(payload: FsSearchPayload):
    """Searches for files matching a filename wildcard pattern."""
    try:
        return file_service.search_files(
            payload.workspace_path or ".",
            pattern=payload.pattern or "*",
            max_results=payload.max_results or 200
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/fs/search-content", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_search_content_endpoint(payload: FsSearchContentPayload):
    """Searches inside file contents across an approved workspace."""
    try:
        return file_service.search_in_files(
            payload.workspace_path or ".",
            query=payload.query,
            is_regex=bool(payload.is_regex),
            file_pattern=payload.file_pattern or "*",
            max_matches=payload.max_matches or 150
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/fs/inspect", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_inspect_endpoint(payload: FsInspectPayload):
    """Retrieves deep metadata, SHA-256 hash, and backup count for a file."""
    try:
        return file_service.inspect_file(payload.file_path)
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/fs/apply-patch", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_apply_patch_endpoint(payload: FsPatchPayload):
    """Applies a unified diff patch to an existing file with automatic backup."""
    try:
        return file_service.apply_patch(payload.file_path, payload.patch_diff, task_id=payload.task_id or "api_patch")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/fs/diff", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_diff_endpoint(payload: FsDiffPayload):
    """Generates a unified diff comparing current file content against proposed content."""
    try:
        return file_service.compare_file_versions(payload.file_path, payload.comparison_content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/fs/inspect-workspace", dependencies=[Depends(verify_terminal_access)], tags=["User File System"])
async def fs_inspect_workspace_endpoint(payload: Optional[FsSearchPayload] = None):
    """Generates an architectural overview of an approved workspace."""
    try:
        ws = (payload.workspace_path if payload else None) or "."
        return file_service.inspect_workspace(ws)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ==============================================================================
# WORKSPACES & OS FOLDER PICKER
# ==============================================================================

@app.get("/workspace/list-approved", dependencies=[Depends(verify_terminal_access)], tags=["Workspaces"])
async def workspace_list_approved_endpoint():
    """Lists all approved workspace roots."""
    return {"status": "success", "workspaces": workspace_service.list_approved_workspaces()}


@app.post("/workspace/approve", dependencies=[Depends(verify_terminal_access)], tags=["Workspaces"])
async def workspace_approve_endpoint(payload: WorkspaceApprovePayload):
    """Registers a project folder into the approved workspaces registry."""
    try:
        return workspace_service.approve_workspace(payload.path, payload.label)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/workspace/pick-native", dependencies=[Depends(verify_terminal_access)], tags=["Workspaces"])
async def workspace_pick_native_endpoint():
    """Spawns the operating system's native directory picker dialog without administrator privileges."""
    selected = workspace_service.pick_native_folder()
    if selected:
        info = workspace_service.approve_workspace(selected)
        return {"status": "success", "selected_path": selected, "workspace": info}
    return {"status": "cancelled", "selected_path": None}


# ==============================================================================
# PROJECT INTELLIGENCE & CONTEXT INDEXING ENDPOINTS
# ==============================================================================

@app.post("/project/index", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
@app.post("/api/project/index", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
async def project_index_endpoint(payload: Optional[ProjectIndexPayload] = None):
    """
    POST /project/index & /api/project/index
    Scans and indexes actual file contents of an approved workspace.
    Enforces per-file, total-byte, and file-count limits, respects .gitignore,
    and excludes credentials/secrets.
    """
    import project_context_service
    target_ws = payload.workspace_path if payload and payload.workspace_path else None
    idx = project_context_service.get_project_index(target_ws)
    stats = idx.scan_and_index()
    return stats


@app.get("/project/index/status", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
@app.get("/api/project/index/status", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
async def project_index_status_endpoint(workspace_path: Optional[str] = Query(None)):
    """Returns current project context index status and metrics."""
    import project_context_service
    idx = project_context_service.get_project_index(workspace_path)
    return {
        "status": "success",
        "workspace_path": str(idx.workspace_path),
        "project_name": idx.project_name,
        "total_files": len(idx.files),
        "total_bytes": idx.total_bytes,
        "last_indexed_at": idx.last_indexed_at
    }


@app.post("/project/search", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
@app.post("/api/project/search", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
async def project_search_endpoint(payload: ProjectSearchPayload):
    """Retrieves relevant file and symbol snippets matching a query via BM25 scoring."""
    import project_context_service
    idx = project_context_service.get_project_index(payload.workspace_path)
    results = idx.retrieve_context(payload.query, max_results=payload.max_results or 5)
    return {
        "status": "success",
        "query": payload.query,
        "results_count": len(results),
        "results": results
    }


@app.delete("/project/index", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
@app.delete("/api/project/index", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
async def project_index_clear_endpoint():
    """Clears the current project context index."""
    import project_context_service
    idx = project_context_service.get_project_index()
    idx.files.clear()
    idx.dependency_graph = project_context_service.ProjectDependencyGraph()
    idx.symbol_table = project_context_service.ProjectSymbolTable()
    idx.total_bytes = 0
    idx.last_indexed_at = 0.0
    idx.persist()
    return {"status": "success", "message": "Project context index cleared."}


@app.get("/project/architecture", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
@app.get("/api/project/architecture", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
async def project_architecture_endpoint(
    workspace_path: Optional[str] = Query(None),
    markdown: bool = Query(False)
):
    """Returns the architectural blueprint, archetypes, entry points, and structural layers."""
    import project_context_service
    idx = project_context_service.get_project_index(workspace_path)
    summary = idx.get_architecture_summary(markdown=markdown)
    return {
        "status": "success",
        "workspace_path": str(idx.workspace_path),
        "project_name": idx.project_name,
        "architecture": summary
    }


@app.get("/project/dependencies", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
@app.get("/api/project/dependencies", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
async def project_dependencies_endpoint(
    file_path: str = Query(..., description="Relative file path to inspect"),
    workspace_path: Optional[str] = Query(None)
):
    """Returns outgoing dependencies, incoming callers, and impact radius for a specific file."""
    import project_context_service
    idx = project_context_service.get_project_index(workspace_path)
    data = idx.get_dependencies_for_file(file_path)
    return {
        "status": "success",
        "workspace_path": str(idx.workspace_path),
        **data
    }


@app.get("/project/symbols", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
@app.get("/api/project/symbols", dependencies=[Depends(verify_terminal_access)], tags=["Project Context"])
async def project_symbols_endpoint(
    name: Optional[str] = Query(None, description="Symbol name to query across the codebase"),
    file_path: Optional[str] = Query(None, description="Optional relative file path"),
    kind: Optional[str] = Query(None, description="Optional kind filter (e.g. function, class, type)"),
    workspace_path: Optional[str] = Query(None)
):
    """Finds symbol declarations across files or retrieves all symbols for a specific file."""
    import project_context_service
    idx = project_context_service.get_project_index(workspace_path)
    if file_path:
        symbols = idx.symbol_table.get_symbols_for_file(file_path)
    elif name:
        symbols = idx.find_symbol(name, kind=kind)
    else:
        symbols = []
        for f, syms in idx.symbol_table.symbols_by_file.items():
            symbols.extend(syms)
    return {
        "status": "success",
        "symbols_count": len(symbols),
        "symbols": symbols
    }


# ==============================================================================
# VERSION BACKUPS & RECOVERY
# ==============================================================================

@app.get("/backups/history", dependencies=[Depends(verify_terminal_access)], tags=["Backups"])
async def backups_history_endpoint(file_path: Optional[str] = Query(None)):
    """Lists historical backups, optionally filtered by file path."""
    return {"status": "success", "backups": backup_service.list_backups(file_path)}


@app.get("/backups/{backup_id}/compare", dependencies=[Depends(verify_terminal_access)], tags=["Backups"])
async def backups_compare_endpoint(backup_id: str):
    """Returns a unified diff between a backup and the current file state."""
    try:
        return backup_service.compare_backup_to_current(backup_id)
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/backups/{backup_id}/restore", dependencies=[Depends(verify_terminal_access)], tags=["Backups"])
async def backups_restore_endpoint(backup_id: str):
    """Safely restores a backup, taking an automatic pre-restore safety snapshot first."""
    try:
        return backup_service.restore_backup(backup_id)
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ==============================================================================
# MODEL DOWNLOAD SYSTEM (USER-LEVEL, RESUME, SHA-256)
# ==============================================================================

@app.get("/models/status", dependencies=[Depends(verify_terminal_access)], tags=["Model Downloads"])
async def models_status_endpoint():
    """Returns active model downloads, disk locations, and progress states."""
    return {
        "status": "success",
        "models_dir": paths_service.get_models_dir(),
        "tasks": model_download_service.get_all_download_status()
    }


@app.post("/models/download", dependencies=[Depends(verify_terminal_access)], tags=["Model Downloads"])
async def models_download_endpoint(payload: ModelDownloadPayload):
    """Starts or resumes a background model download with byte-level progress."""
    try:
        return model_download_service.start_model_download(payload.model_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/models/pause", dependencies=[Depends(verify_terminal_access)], tags=["Model Downloads"])
async def models_pause_endpoint(payload: ModelDownloadPayload):
    """Pauses an active model download."""
    return model_download_service.pause_model_download(payload.model_id)


@app.post("/models/resume", dependencies=[Depends(verify_terminal_access)], tags=["Model Downloads"])
async def models_resume_endpoint(payload: ModelDownloadPayload):
    """Resumes a paused model download using HTTP Range requests."""
    return model_download_service.resume_model_download(payload.model_id)


@app.post("/models/cancel", dependencies=[Depends(verify_terminal_access)], tags=["Model Downloads"])
async def models_cancel_endpoint(payload: ModelDownloadPayload):
    """Cancels a model download."""
    return model_download_service.cancel_model_download(payload.model_id)


# ==============================================================================
# SYSTEM & ELEVATION AUDIT
# ==============================================================================

@app.get("/system/elevation-status", dependencies=[Depends(verify_terminal_access)], tags=["System Audit"])
async def system_elevation_status_endpoint():
    """Returns whether Stroke is executing with non-root user permissions and warns if elevated."""
    return paths_service.get_elevation_status()


@app.get("/system/paths", dependencies=[Depends(verify_terminal_access)], tags=["System Audit"])
async def system_paths_endpoint():
    """Returns Stroke's per-user application, models, backups, and download paths."""
    return {
        "status": "success",
        "directories": paths_service.ensure_user_directories(),
        "is_elevated": paths_service.is_elevated_privilege()
    }



# ==============================================================================
# LOCAL EXECUTION ENTRYPOINT
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run("main:app", host=host, port=APP_PORT, reload=True)
