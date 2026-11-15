"""
Stroke AI — Firebase Authentication Service & Identity Engine
Authoritative verification of Firebase ID tokens for local desktop, emulator, and hosted server.

Trust Boundary Architecture:
1. No Firebase Admin private service-account key is bundled with the desktop distribution.
2. In production desktop & server mode, ID tokens are verified cryptographically via Google's
   public x509 certificates (RS256) using `google.oauth2.id_token.verify_firebase_token`.
3. In local emulator development mode (when FIREBASE_AUTH_EMULATOR_HOST is set), tokens are
   verified via `firebase_admin.auth.verify_id_token`.
4. Every protected endpoint independently verifies token signature, audience (FIREBASE_PROJECT_ID),
   issuer (https://securetoken.google.com/<FIREBASE_PROJECT_ID>), and expiration.
5. Passwords, password hashes, and OTP codes are strictly owned by Firebase Auth and are NEVER
   stored in local memory stores, files, logs, or Firestore documents.
"""

import os
import time
import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import google.oauth2.id_token
from google.auth.transport.requests import Request as GoogleAuthRequest

logger = logging.getLogger("stroke.auth")

# Canonical Firebase Project Configuration
DEFAULT_FIREBASE_PROJECT_ID = "stroke-cyber-matrix"
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", DEFAULT_FIREBASE_PROJECT_ID).strip()
FIREBASE_AUTH_EMULATOR_HOST = os.getenv("FIREBASE_AUTH_EMULATOR_HOST")

# HTTP Bearer scheme for token extraction
bearer_scheme = HTTPBearer(auto_error=False)

# Cached google auth HTTP transport request object
_google_auth_request = GoogleAuthRequest()


class AuthenticatedUser(BaseModel):
    """Represents an independently verified Firebase user identity."""
    uid: str = Field(..., description="Firebase Unique Identifier (sub/user_id)")
    email: Optional[str] = Field(None, description="Verified primary email address")
    email_verified: bool = Field(False, description="Whether user email has been verified")
    display_name: Optional[str] = Field(None, description="User display name")
    token: str = Field("", description="Raw verified ID token", repr=False)
    claims: Dict[str, Any] = Field(default_factory=dict, description="Decoded JWT claims", repr=False)


def get_firebase_project_id() -> str:
    """Returns the active Firebase Project ID."""
    return os.getenv("FIREBASE_PROJECT_ID", FIREBASE_PROJECT_ID) or DEFAULT_FIREBASE_PROJECT_ID


def verify_firebase_id_token(token: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Cryptographically verifies a Firebase Authentication ID token.
    
    Checks:
    - Signature validity against Google's public x509 certs or local emulator
    - Audience matching the active Firebase Project ID
    - Issuer matching https://securetoken.google.com/<project_id>
    - Expiration time (exp > now)
    - Non-empty subject (uid)
    
    Returns decoded JWT claims dictionary or raises ValueError.
    """
    if not token or not isinstance(token, str) or not token.strip():
        raise ValueError("ID token must be a non-empty string.")

    token = token.strip()
    target_project_id = (project_id or get_firebase_project_id()).strip()

    # Case A: Local Firebase Auth Emulator is configured
    emulator_host = os.getenv("FIREBASE_AUTH_EMULATOR_HOST") or FIREBASE_AUTH_EMULATOR_HOST
    if emulator_host:
        try:
            import firebase_admin
            from firebase_admin import auth as admin_auth
            if not firebase_admin._apps:
                firebase_admin.initialize_app(options={"projectId": target_project_id})
            decoded = admin_auth.verify_id_token(token, check_revoked=False)
            return decoded
        except Exception as exc:
            raise ValueError(f"Firebase Emulator token verification failed: {exc}")

    # Case B: Standard Desktop / Server Token Verification via Google's Public Certificates
    try:
        claims = google.oauth2.id_token.verify_firebase_token(
            token,
            _google_auth_request,
            audience=target_project_id,
            clock_skew_in_seconds=10
        )
    except Exception as primary_exc:
        # Fallback check: if firebase-admin has ADC or credentials initialized, attempt admin verification
        try:
            import firebase_admin
            from firebase_admin import auth as admin_auth
            if firebase_admin._apps:
                claims = admin_auth.verify_id_token(token, check_revoked=False)
            else:
                raise primary_exc
        except Exception:
            raise ValueError(f"Token verification failed: {primary_exc}")

    if not isinstance(claims, dict):
        raise ValueError("Decoded token claims must be a dictionary.")

    # Validate essential claims
    uid = claims.get("user_id") or claims.get("sub") or claims.get("uid")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise ValueError("Token missing valid subject (UID).")

    # Validate audience
    aud = claims.get("aud")
    if aud != target_project_id:
        raise ValueError(f"Token audience mismatch: got '{aud}', expected '{target_project_id}'.")

    # Validate issuer
    expected_iss = f"https://securetoken.google.com/{target_project_id}"
    iss = claims.get("iss")
    if iss != expected_iss:
        raise ValueError(f"Token issuer mismatch: got '{iss}', expected '{expected_iss}'.")

    # Validate expiration
    exp = claims.get("exp")
    if exp and time.time() > float(exp):
        raise ValueError("Firebase ID token has expired.")

    return claims


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> AuthenticatedUser:
    """
    FastAPI dependency that enforces authenticated Firebase user identity.
    Extracts Bearer token from the Authorization header and verifies it.
    Raises HTTP 401 Unauthorized if missing, expired, or invalid.
    """
    token: Optional[str] = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif request:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: Missing Bearer ID token in Authorization header.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    try:
        claims = verify_firebase_id_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unauthorized: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Failed to verify authentication token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    uid = claims.get("user_id") or claims.get("sub") or claims.get("uid")
    email = claims.get("email")
    if email:
        email = str(email).strip().lower()
    email_verified = bool(claims.get("email_verified", False))
    display_name = claims.get("name")

    return AuthenticatedUser(
        uid=uid,
        email=email,
        email_verified=email_verified,
        display_name=display_name,
        token=token,
        claims=claims
    )


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> Optional[AuthenticatedUser]:
    """
    FastAPI dependency for endpoints where user identity is optional.
    If Authorization header is provided, it must be valid (raises 401 if invalid).
    If omitted, returns None without error.
    """
    token: Optional[str] = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif request:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if not token:
        return None

    try:
        claims = verify_firebase_id_token(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unauthorized: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"}
        )

    uid = claims.get("user_id") or claims.get("sub") or claims.get("uid")
    email = claims.get("email")
    if email:
        email = str(email).strip().lower()
    email_verified = bool(claims.get("email_verified", False))
    display_name = claims.get("name")

    return AuthenticatedUser(
        uid=uid,
        email=email,
        email_verified=email_verified,
        display_name=display_name,
        token=token,
        claims=claims
    )
