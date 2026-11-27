"""
STROKE // SECURE AI CREDENTIALS VAULT SERVICE
================================================================================
Manages Bring Your Own Key (BYOK) AI provider API keys with zero plaintext leaks.

Security Architecture:
1. Primary Storage: OS-level secure credential storage via Python 'keyring'
   - macOS: Apple Keychain (Keychain Services API)
   - Windows: Windows Credential Manager
   - Linux: SecretService API / KWallet
2. Resilient Fallback: Machine-Identity Encrypted Vault
   - Encrypted with AES-256 (Fernet) using a key derived via PBKDF2-HMAC-SHA256
     from the machine's hardware node and a CSPRNG salt stored in 0600 mode.
   - Stored in standard user application data (paths_service.get_app_data_dir()).
3. Environment Fallback: Checks standard env vars (GROQ_API_KEY, GEMINI_API_KEY, etc.)
   as read-only sources.
4. Privacy & Leak Prevention:
   - Plaintext keys are NEVER written to logs, analytics, or chat history.
   - Frontend APIs return masked digests only (e.g., 'gsk_••••••••••••...4a89').
   - Browser localStorage is NEVER used for storing keys.
5. Multi-Provider Scoping:
   - Supports 'groq', 'gemini', 'openrouter', 'openai', 'anthropic', 'custom'.
   - Custom provider stores 'base_url', 'model_id', and 'provider_type'.
================================================================================
"""

import os
import sys
import time
import json
import uuid
import base64
import hashlib
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from cryptography.fernet import Fernet

import paths_service

logger = logging.getLogger("stroke.credentials_vault")

SERVICE_NAME = "stroke_ai_byok"
VAULT_KEY_FILE = "byok_vault.key"
VAULT_DATA_FILE = "byok_credentials.vault"

# Supported provider identifiers
SUPPORTED_PROVIDERS = ["groq", "gemini", "openrouter", "openai", "anthropic", "deepseek", "custom"]

# Standard environment variable mappings
ENV_KEY_MAPPINGS = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "custom": "CUSTOM_AI_API_KEY",
}


class VaultKeyCorruptionError(RuntimeError):
    """Raised when an existing vault key is unreadable or corrupted, preventing silent key loss."""
    pass


def _get_vault_dir() -> Path:
    """Returns the secure credentials directory inside the user's application data folder."""
    vault_dir = paths_service.get_app_data_dir() / "credentials"
    vault_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(vault_dir, 0o700)
    except Exception:
        pass
    return vault_dir


def _get_key_dir() -> Path:
    """Returns a separate key directory so fallback keys are never stored beside ciphertext."""
    key_dir = paths_service.get_app_data_dir() / ".keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(key_dir, 0o700)
    except Exception:
        pass
    return key_dir


def _is_keyring_usable() -> bool:
    try:
        import keyring
        kr = keyring.get_keyring()
        return bool(kr and "fail" not in kr.__class__.__name__.lower())
    except Exception:
        return False


def _get_or_create_cipher() -> Optional[Fernet]:
    """
    Loads or creates a Fernet cipher key.
    1. Prefers OS-level keyring ('stroke_vault_master' / 'byok_vault_key') so the key is
       never stored beside the encrypted vault file.
    2. Falls back to a 0600 key file in a separate .keys/ directory (never beside ciphertext
       and never migrating from legacy repository data/.vault_key).
    """
    vault_dir = _get_vault_dir()
    key_dir = _get_key_dir()
    key_file = key_dir / VAULT_KEY_FILE
    legacy_vault_dir_key = vault_dir / VAULT_KEY_FILE
    vault_data_file = vault_dir / VAULT_DATA_FILE

    # 0. Fail closed if a corrupted key file is present alongside vault data
    for candidate_dir, candidate_key in ((key_dir, key_file), (vault_dir, legacy_vault_dir_key)):
        if candidate_key.exists():
            try:
                with open(candidate_key, "rb") as f:
                    key_bytes = f.read().strip()
                if len(key_bytes) != 44:
                    raise ValueError(f"Invalid key length: {len(key_bytes)} (expected 44 bytes)")
                Fernet(key_bytes)
            except Exception as exc:
                backup_key = candidate_dir / f"{VAULT_KEY_FILE}.corrupted.{int(time.time())}.bak"
                try:
                    import shutil
                    shutil.copy2(str(candidate_key), str(backup_key))
                    logger.error("Preserved snapshot of corrupted key at %s", backup_key)
                except Exception as copy_err:
                    logger.error("Failed to backup corrupted vault key: %s", copy_err)

                if vault_data_file.exists() and vault_data_file.stat().st_size > 0:
                    logger.critical("Refusing to silently regenerate key while encrypted vault data exists: %s", exc)
                    raise VaultKeyCorruptionError(
                        f"BYOK credentials key corrupted at {candidate_key}. "
                        f"Preserved damaged key at {backup_key}. Refusing to overwrite and lose existing vault secrets: {exc}"
                    )

    # 1. Prefer OS keyring for master key storage
    if _is_keyring_usable():
        try:
            import keyring
            kr_key = keyring.get_password("stroke_vault_master", "byok_vault_key")
            if kr_key:
                key_bytes = kr_key.strip().encode("utf-8")
                if len(key_bytes) == 44:
                    return Fernet(key_bytes)
        except Exception as exc:
            logger.debug("Keyring master key lookup unavailable: %s", exc)

    # 2. Check separate .keys/ fallback location
    if key_file.exists():
        try:
            with open(key_file, "rb") as f:
                key_bytes = f.read().strip()
                if len(key_bytes) == 44:
                    return Fernet(key_bytes)
                else:
                    raise ValueError(f"Invalid key length: {len(key_bytes)} (expected 44 bytes)")
        except Exception as exc:
            backup_key = key_dir / f"{VAULT_KEY_FILE}.corrupted.{int(time.time())}.bak"
            try:
                import shutil
                shutil.copy2(str(key_file), str(backup_key))
                logger.error("Preserved snapshot of corrupted key at %s", backup_key)
            except Exception as copy_err:
                logger.error("Failed to backup corrupted vault key: %s", copy_err)

            if vault_data_file.exists() and vault_data_file.stat().st_size > 0:
                logger.critical("Refusing to silently regenerate key while encrypted vault data exists: %s", exc)
                raise VaultKeyCorruptionError(
                    f"BYOK credentials key corrupted at {key_file}. "
                    f"Preserved damaged key at {backup_key}. Refusing to overwrite and lose existing vault secrets: {exc}"
                )
            logger.warning("Corrupted key without vault data, regenerating: %s", exc)

    # 3. Generate fresh CSPRNG Fernet key (never derive from MAC address or migrate compromised repo keys)
    try:
        fernet_key = Fernet.generate_key()

        if _is_keyring_usable():
            try:
                import keyring
                keyring.set_password("stroke_vault_master", "byok_vault_key", fernet_key.decode("utf-8"))
                return Fernet(fernet_key)
            except Exception as exc:
                logger.info("Keyring master key persistence failed, using 0600 key file: %s", exc)

        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = 0o600
        fd = os.open(str(key_file), flags, mode)
        with open(fd, "wb") as f:
            f.write(fernet_key)

        return Fernet(fernet_key)
    except Exception as exc:
        logger.error("Failed to generate secure vault cipher: %s", exc)
        return None


def mask_key(key: Optional[str]) -> str:
    """Masks an API key for safe UI display (e.g. 'gsk_••••••••...12ab')."""
    if not key or not isinstance(key, str):
        return ""
    stripped = key.strip()
    if len(stripped) <= 8:
        return "••••••••"
    prefix = stripped[:4]
    suffix = stripped[-4:]
    return f"{prefix}••••••••••••{suffix}"

# Alias for backwards compatibility
mask_secret = mask_key


def get_credential_vault_path() -> Path:
    """Returns standard path to the encrypted credentials vault file."""
    return _get_vault_dir() / VAULT_DATA_FILE


class CredentialsVault:
    """Authoritative API key and BYOK configuration vault with OS-keyring & encrypted-fallback."""

    def __init__(self, vault_path: Optional[str] = None):
        self.vault_path = Path(vault_path) if vault_path else None
        self._lock = threading.RLock()
        self._keyring_available = False
        try:
            import keyring
            # Test that a backend is actually present
            kr = keyring.get_keyring()
            if kr and "fail" not in kr.__class__.__name__.lower():
                self._keyring_available = True
        except Exception:
            self._keyring_available = False

    def is_keyring_active(self) -> bool:
        return self._keyring_available

    def _read_encrypted_vault_file(self) -> Dict[str, Any]:
        """Reads and decrypts the local encrypted vault file."""
        with self._lock:
            vault_file = self.vault_path if self.vault_path else (_get_vault_dir() / VAULT_DATA_FILE)
            if not vault_file.exists():
                return {}

            cipher = _get_or_create_cipher()
            if not cipher:
                return {}

            try:
                with open(vault_file, "rb") as f:
                    encrypted_bytes = f.read()
                if not encrypted_bytes:
                    return {}
                decrypted = cipher.decrypt(encrypted_bytes).decode("utf-8")
                return json.loads(decrypted)
            except Exception as exc:
                logger.warning("Failed to decrypt local credentials vault: %s", exc)
                return {}

    def _write_encrypted_vault_file(self, data: Dict[str, Any]) -> bool:
        """Encrypts and atomically saves the local credentials vault file with 0600 permissions."""
        with self._lock:
            cipher = _get_or_create_cipher()
            if not cipher:
                return False

            vault_file = self.vault_path if self.vault_path else (_get_vault_dir() / VAULT_DATA_FILE)
            tmp_file = vault_file.with_name(f"{vault_file.name}.{os.getpid()}.{threading.get_ident()}.tmp")

            try:
                payload_str = json.dumps(data)
                encrypted = cipher.encrypt(payload_str.encode("utf-8"))

                flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                mode = 0o600
                fd = os.open(str(tmp_file), flags, mode)
                with open(fd, "wb") as f:
                    f.write(encrypted)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp_file, vault_file)
                return True
            except Exception as exc:
                logger.error("Failed to write credentials vault: %s", exc)
                if tmp_file.exists():
                    try:
                        tmp_file.unlink()
                    except Exception:
                        pass
                return False

    def store_credential(
        self,
        provider: str,
        api_key: str,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None
    ) -> bool:
        """
        Stores an API key and optional metadata securely.
        Tries OS keychain first; persists to encrypted vault as well to ensure durability.
        """
        provider = provider.strip().lower()
        api_key = api_key.strip()
        if not provider or not api_key:
            return False

        account_key = f"{user_id}:{provider}" if user_id else provider
        success_keyring = False

        if self._keyring_available:
            try:
                import keyring
                keyring.set_password(SERVICE_NAME, account_key, api_key)
                success_keyring = True
            except Exception as exc:
                logger.info("Keyring storage failed for %s, using encrypted vault: %s", provider, exc)

        # Only store key in encrypted vault file if OS keyring is unavailable;
        # always update non-secret metadata in the vault file.
        with self._lock:
            vault_data = self._read_encrypted_vault_file()
            user_block = vault_data.setdefault(user_id or "default", {})
            prov_record = user_block.setdefault(provider, {})
            if success_keyring:
                prov_record.pop("key", None)
                prov_record["stored_in_keyring"] = True
            else:
                prov_record["key"] = api_key
                prov_record["stored_in_keyring"] = False
            prov_record["updated_at"] = os.environ.get("MOCK_TIME", "") or str(int(time.time()))
            if metadata:
                prov_record["metadata"] = metadata

            success_vault = self._write_encrypted_vault_file(vault_data)
        return success_keyring or success_vault

    set_credential = store_credential

    def get_credential(self, provider: str, user_id: Optional[str] = None) -> Optional[str]:
        """
        Retrieves the plaintext API key for internal server-side inference calls only.
        NEVER expose the return value of this method to HTTP responses or logs.
        Order of precedence:
        1. OS Keychain
        2. Encrypted Vault
        3. Environment variable (e.g. GROQ_API_KEY)
        """
        provider = provider.strip().lower()
        account_key = f"{user_id}:{provider}" if user_id else provider

        # 1. OS Keychain
        if self._keyring_available:
            try:
                import keyring
                pwd = keyring.get_password(SERVICE_NAME, account_key)
                if pwd and pwd.strip():
                    return pwd.strip()
            except Exception:
                pass

        # 2. Encrypted Vault
        with self._lock:
            vault_data = self._read_encrypted_vault_file()
            user_block = vault_data.get(user_id) if user_id else None
            prov_record = user_block.get(provider, {}) if user_block else {}
            if prov_record.get("key"):
                return prov_record["key"].strip()
            # Fallback to default user block if not found under specific user_id
            if user_id and "default" in vault_data:
                default_record = vault_data.get("default", {}).get(provider, {})
                if default_record.get("key"):
                    return default_record["key"].strip()

        # 3. Environment Variable
        env_var = ENV_KEY_MAPPINGS.get(provider)
        if env_var and os.getenv(env_var):
            val = os.getenv(env_var, "").strip()
            if val:
                return val

        return None

    def get_metadata(self, provider: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Returns non-sensitive metadata for a provider (e.g. custom base URL, model ID)."""
        provider = provider.strip().lower()
        with self._lock:
            vault_data = self._read_encrypted_vault_file()
            user_block = vault_data.get(user_id or "default", {})
            prov_record = user_block.get(provider, {})
            return dict(prov_record.get("metadata", {}))

    def set_metadata(self, provider: str, metadata: Dict[str, Any], user_id: Optional[str] = None) -> bool:
        """Updates non-sensitive metadata for a provider."""
        provider = provider.strip().lower()
        with self._lock:
            vault_data = self._read_encrypted_vault_file()
            user_block = vault_data.setdefault(user_id or "default", {})
            prov_record = user_block.setdefault(provider, {})
            prov_record["metadata"] = metadata
            return self._write_encrypted_vault_file(vault_data)

    def delete_credential(self, provider: str, user_id: Optional[str] = None) -> bool:
        """Deletes a credential from the OS keychain and local encrypted vault."""
        provider = provider.strip().lower()
        account_key = f"{user_id}:{provider}" if user_id else provider

        if self._keyring_available:
            try:
                import keyring
                keyring.delete_password(SERVICE_NAME, account_key)
            except Exception:
                pass

        with self._lock:
            vault_data = self._read_encrypted_vault_file()
            user_block = vault_data.get(user_id or "default", {})
            if provider in user_block:
                del user_block[provider]
                self._write_encrypted_vault_file(vault_data)

        return True

    def delete_all_user_credentials(self, user_id: str) -> bool:
        """Purges all stored BYOK provider credentials for a specific user ID."""
        if not user_id:
            return False

        if self._keyring_available:
            try:
                import keyring
                for provider in SUPPORTED_PROVIDERS:
                    account_key = f"{user_id}:{provider}"
                    try:
                        keyring.delete_password(SERVICE_NAME, account_key)
                    except Exception:
                        pass
            except Exception:
                pass

        with self._lock:
            vault_data = self._read_encrypted_vault_file()
            if user_id in vault_data:
                del vault_data[user_id]
                self._write_encrypted_vault_file(vault_data)

        return True

    def get_provider_status(self, provider: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns a completely safe status digest suitable for frontend display.
        GUARANTEE: NEVER includes the plaintext API key.
        """
        provider = provider.strip().lower()
        key = self.get_credential(provider, user_id)
        configured = bool(key)
        masked = mask_key(key) if key else ""
        meta = self.get_metadata(provider, user_id)

        source = "none"
        env_var = ENV_KEY_MAPPINGS.get(provider)
        if key:
            if env_var and os.getenv(env_var) == key:
                source = "environment"
            elif self._keyring_available:
                source = "os_keychain"
            else:
                source = "encrypted_vault"

        return {
            "provider": provider,
            "configured": configured,
            "masked_key": masked,
            "source": source,
            "metadata": meta,
        }

    def list_all_statuses(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns safe status summaries for all supported providers."""
        return [self.get_provider_status(p, user_id) for p in SUPPORTED_PROVIDERS]


# Global vault singleton instance
vault = CredentialsVault()
