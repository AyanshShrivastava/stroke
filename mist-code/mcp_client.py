"""
================================================================================
STROKE // GENERAL-PURPOSE MODEL CONTEXT PROTOCOL (MCP) CLIENT & REGISTRY
Full JSON-RPC 2.0 / MCP spec compliance over STDIO and Streamable HTTP transports.
Multi-server management, dynamic tool discovery, namespacing, and schema validation.
Hardened with SSRF protection, secret vaulting, process cleanup, and lifecycle states.
================================================================================
"""

import os
import sys
import json
import asyncio
import logging
import uuid
import ipaddress
import socket
import signal
import re
import time
import shutil
import urllib.parse
import atexit
import subprocess
import threading
from enum import Enum
from typing import Dict, List, Any, Optional, Callable, Awaitable, Set, Tuple
from dataclasses import dataclass, field
import httpx
from cryptography.fernet import Fernet
import paths_service

logger = logging.getLogger("stroke.mcp_client")

# Track active subprocess PIDs across the process lifecycle for leak-free termination
_ACTIVE_STDIO_PIDS: Set[int] = set()
_ACTIVE_STDIO_PIDS_LOCK = threading.Lock()


def _cleanup_all_mcp_processes():
    """Safety cleanup handler: kills any remaining MCP child processes on application exit."""
    with _ACTIVE_STDIO_PIDS_LOCK:
        pids = list(_ACTIVE_STDIO_PIDS)
    for pid in pids:
        try:
            if sys.platform != "win32":
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except Exception:
                    os.kill(pid, signal.SIGTERM)
            else:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        except Exception:
            pass


atexit.register(_cleanup_all_mcp_processes)

# ------------------------------------------------------------------------------
# PROTOCOL CONSTANTS & LIFECYCLE STATES
# ------------------------------------------------------------------------------
MCP_PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {
    "name": "Stroke",
    "version": "2.0.0"
}


class McpServerState(str, Enum):
    """5-Tier Connection Lifecycle States for MCP Servers."""
    CONFIGURED = "configured"              # Tier 1: Config saved in registry
    EXECUTABLE_FOUND = "executable_found"  # Tier 2: Binary found on disk or HTTP URL syntactically valid
    PROCESS_RUNNING = "process_running"    # Tier 3: Subprocess spawned or HTTP port reachable
    PROTOCOL_CONNECTED = "protocol_connected"  # Tier 4: JSON-RPC initialize handshake complete
    TOOLS_READY = "tools_ready"            # Tier 5: Tools discovered, schema validated, ready for AI dispatch
    OFFLINE = "offline"                    # Disconnected or unreachable
    FAILED = "failed"                      # Process crash, handshake failure, or fatal error
    DISABLED = "disabled"                  # Explicitly disabled by user


class McpError(Exception):
    """Raised when an MCP protocol, transport, or tool call error occurs."""
    def __init__(self, message: str, code: int = -32000, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


# ------------------------------------------------------------------------------
# SSRF PROTECTION ENGINE
# ------------------------------------------------------------------------------
class SsrfProtector:
    """
    Prevents Server-Side Request Forgery (SSRF), DNS rebinding, redirect bypasses,
    and access to private networks, loopback, and cloud metadata services.
    """

    BLOCKED_NETWORKS = [
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("100.64.0.0/10"),        # Carrier-grade NAT (RFC 6598)
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),       # Link-local & cloud metadata
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.0.0.0/24"),         # IETF Protocol Assignments
        ipaddress.ip_network("192.0.2.0/24"),         # TEST-NET-1 (RFC 5737)
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("198.18.0.0/15"),        # Network benchmark tests (RFC 2544)
        ipaddress.ip_network("198.51.100.0/24"),      # TEST-NET-2 (RFC 5737)
        ipaddress.ip_network("203.0.113.0/24"),       # TEST-NET-3 (RFC 5737)
        ipaddress.ip_network("224.0.0.0/4"),          # Multicast
        ipaddress.ip_network("240.0.0.0/4"),          # Reserved
        ipaddress.ip_network("::/128"),
        ipaddress.ip_network("::1/128"),              # IPv6 loopback
        ipaddress.ip_network("::ffff:0:0/96"),        # IPv4-mapped IPv6
        ipaddress.ip_network("64:ff9b::/96"),         # IPv4/IPv6 translation (RFC 6052)
        ipaddress.ip_network("2001:db8::/32"),        # Documentation IPv6
        ipaddress.ip_network("fc00::/7"),             # IPv6 Unique Local
        ipaddress.ip_network("fe80::/10"),            # IPv6 Link-Local
    ]

    BLOCKED_HOSTNAMES = {
        "metadata.google.internal",
        "instance-data",
        "169.254.169.254",
        "metadata",
        "localhost.localdomain"
    }

    REBINDING_DOMAINS = (
        ".nip.io",
        ".sslip.io",
        ".localtest.me",
        ".vcap.me",
        ".lvh.me",
        ".traefik.me",
        ".127.0.0.1.nip.io"
    )

    @classmethod
    def validate_url(cls, url: str, allow_local: bool = False) -> str:
        """
        Validates URL scheme, resolves hostname to IP addresses, and ensures
        target is not on a private/metadata network unless allow_local is set.
        """
        if not url or not isinstance(url, str):
            raise McpError("Invalid or empty MCP server URL.", code=-32602)

        url_str = url.strip()
        parsed = urllib.parse.urlparse(url_str)

        # 1. Strict protocol validation
        if parsed.scheme not in ("http", "https"):
            raise McpError(f"Unsupported MCP protocol scheme '{parsed.scheme}'. Only http and https are allowed.", code=-32602)

        hostname = parsed.hostname
        if not hostname:
            raise McpError(f"URL '{url_str}' has no valid hostname.", code=-32602)

        hostname_lower = hostname.lower()

        # 2. Block known cloud metadata hostnames
        if hostname_lower in cls.BLOCKED_HOSTNAMES:
            raise McpError(f"Access to cloud metadata hostname '{hostname}' is strictly prohibited.", code=-32602)

        # 3. Block known DNS rebinding domains
        for rebinding in cls.REBINDING_DOMAINS:
            if hostname_lower == rebinding.lstrip(".") or hostname_lower.endswith(rebinding):
                raise McpError(f"DNS rebinding domain '{hostname}' is strictly prohibited.", code=-32602)

        # 4. Detect numeric / decimal / octal / hex IP obfuscation in host
        if re.match(r"^(0x[0-9a-f]+|\d+)$", hostname_lower):
            raise McpError("Obfuscated or integer IP addresses are prohibited.", code=-32602)
        if re.match(r"^0\d+", hostname_lower):
            raise McpError("Octal IP addresses are prohibited.", code=-32602)

        # 5. Check for direct localhost naming
        is_named_localhost = hostname_lower in ("localhost", "127.0.0.1", "::1")
        if is_named_localhost:
            if not allow_local:
                raise McpError(
                    f"Access to local host '{hostname}' is restricted. Enable 'allow_local' in server config to connect.",
                    code=-32602
                )
            return url_str

        # 6. DNS Resolution & IP Range Check
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as e:
            raise McpError(f"Could not resolve host '{hostname}': {e}", code=-32602)

        if not addr_info:
            raise McpError(f"No IP addresses resolved for host '{hostname}'.", code=-32602)

        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                # Unwrap IPv4-mapped IPv6 (::ffff:127.0.0.1)
                if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
                    ip_obj = ip_obj.ipv4_mapped

                is_blocked = any(ip_obj in net for net in cls.BLOCKED_NETWORKS)

                if is_blocked:
                    # Cloud metadata and link-local (169.254.0.0/16, fe80::/10) must NEVER be permitted
                    is_cloud_metadata = (
                        (isinstance(ip_obj, ipaddress.IPv4Address) and ip_obj in ipaddress.ip_network("169.254.0.0/16"))
                        or (isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj in ipaddress.ip_network("fe80::/10"))
                    )
                    if is_cloud_metadata:
                        raise McpError(
                            f"SSRF Protection: Access to link-local/cloud metadata IP '{ip_str}' is strictly prohibited.",
                            code=-32602
                        )

                    # Only genuine loopback (127.0.0.0/8 or ::1) is permitted when allow_local is True
                    if (ip_obj.is_loopback or ip_str == "127.0.0.1" or ip_str == "::1") and allow_local:
                        continue
                    raise McpError(
                        f"SSRF Protection: Connection to IP '{ip_str}' ({hostname}) blocked. Private/cloud/metadata access prohibited.",
                        code=-32602
                    )
            except ValueError:
                raise McpError(f"Invalid resolved IP '{ip_str}' for host '{hostname}'.", code=-32602)

        return url_str


# ------------------------------------------------------------------------------
# SECRET VAULT & ENVIRONMENT HYGIENE
# ------------------------------------------------------------------------------
class McpSecretVault:
    """
    Encrypts sensitive environment variables and HTTP headers using a local
    machine AES-256 key with 0600 permissions. Prevents secrets from being saved
    in plaintext JSON configuration files.
    """

    VAULT_DIR = str(paths_service.get_app_data_dir() / "credentials")
    KEY_DIR = str(paths_service.get_app_data_dir() / ".keys")
    KEY_FILE = os.path.join(KEY_DIR, ".mcp_vault_key")
    _BAK_KEY_FILE = os.path.join(KEY_DIR, ".mcp_vault_key.bak")
    _KEYRING_SERVICE = "stroke_vault_master"
    _KEYRING_ACCOUNT = "mcp_vault_key"
    _cipher: Optional[Fernet] = None

    @classmethod
    def _is_keyring_usable(cls) -> bool:
        try:
            import keyring
            kr = keyring.get_keyring()
            return bool(kr and "fail" not in kr.__class__.__name__.lower())
        except Exception:
            return False

    @classmethod
    def _get_cipher(cls) -> Fernet:
        if cls._cipher is not None:
            return cls._cipher

        os.makedirs(cls.VAULT_DIR, exist_ok=True)
        os.makedirs(cls.KEY_DIR, exist_ok=True)
        try:
            os.chmod(cls.VAULT_DIR, 0o700)
            os.chmod(cls.KEY_DIR, 0o700)
        except Exception:
            pass

        # 1. Prefer OS keyring for master key storage (never stored beside ciphertext)
        if cls._is_keyring_usable():
            try:
                import keyring
                kr_key = keyring.get_password(cls._KEYRING_SERVICE, cls._KEYRING_ACCOUNT)
                if kr_key and len(kr_key.strip()) >= 32:
                    cipher = Fernet(kr_key.strip().encode("utf-8"))
                    cipher.encrypt(b"probe")
                    cls._cipher = cipher
                    return cls._cipher
            except Exception as e:
                logger.debug(f"[McpSecretVault] Keyring lookup skipped: {e}")

        # 2. Separate .keys/ fallback location
        if os.path.exists(cls.KEY_FILE):
            try:
                with open(cls.KEY_FILE, "rb") as f:
                    key = f.read().strip()
                if key and len(key) >= 32:
                    cipher = Fernet(key)
                    cipher.encrypt(b"probe")
                    cls._cipher = cipher
                    return cls._cipher
            except Exception as e:
                logger.error(f"[McpSecretVault] Primary key file corrupted at {cls.KEY_FILE}: {e}")
                if os.path.exists(cls._BAK_KEY_FILE):
                    try:
                        with open(cls._BAK_KEY_FILE, "rb") as bf:
                            bkey = bf.read().strip()
                        if bkey and len(bkey) >= 32:
                            cipher = Fernet(bkey)
                            cipher.encrypt(b"probe")
                            cls._cipher = cipher
                            fd = os.open(cls.KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                            with open(fd, "wb") as f:
                                f.write(bkey)
                            logger.info("[McpSecretVault] Restored MCP vault key from backup file.")
                            return cls._cipher
                    except Exception as be:
                        logger.error(f"[McpSecretVault] Backup key also unreadable: {be}")
                raise RuntimeError(f"MCP Secret Vault key corrupted at {cls.KEY_FILE}. Refusing to overwrite and lose existing secrets: {e}")

        # 3. Check backup key if primary is absent
        if os.path.exists(cls._BAK_KEY_FILE):
            try:
                with open(cls._BAK_KEY_FILE, "rb") as bf:
                    bkey = bf.read().strip()
                if bkey and len(bkey) >= 32:
                    cls._cipher = Fernet(bkey)
                    fd = os.open(cls.KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with open(fd, "wb") as f:
                        f.write(bkey)
                    return cls._cipher
            except Exception:
                pass

        # 4. Check whether existing encrypted data exists before generating new key
        config_path = paths_service.get_app_data_dir() / "mcp_servers.json"
        if config_path.exists():
            try:
                raw_cfg = config_path.read_text(encoding="utf-8")
                if "enc:fernet:" in raw_cfg:
                    raise RuntimeError(
                        f"Cannot generate new MCP Vault key: Existing encrypted MCP configurations found at {config_path} "
                        "but the encryption key is missing. Refusing to regenerate key to prevent permanent credential loss."
                    )
            except RuntimeError:
                raise
            except Exception:
                pass

        # 5. Generate new CSPRNG key; store in OS keyring first, else 0600 in .keys/
        new_key = Fernet.generate_key()
        if cls._is_keyring_usable():
            try:
                import keyring
                keyring.set_password(cls._KEYRING_SERVICE, cls._KEYRING_ACCOUNT, new_key.decode("utf-8"))
                cls._cipher = Fernet(new_key)
                return cls._cipher
            except Exception as e:
                logger.info(f"[McpSecretVault] Keyring store failed, falling back to 0600 key file: {e}")

        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(cls.KEY_FILE, flags, 0o600)
        with open(fd, "wb") as f:
            f.write(new_key)
        try:
            bfd = os.open(cls._BAK_KEY_FILE, flags, 0o600)
            with open(bfd, "wb") as bf:
                bf.write(new_key)
        except Exception:
            pass
        cls._cipher = Fernet(new_key)
        return cls._cipher

    @classmethod
    def encrypt(cls, secret: str) -> str:
        if not secret:
            return ""
        if secret.startswith("enc:fernet:"):
            return secret
        cipher = cls._get_cipher()
        encrypted = cipher.encrypt(secret.encode("utf-8")).decode("utf-8")
        return f"enc:fernet:{encrypted}"

    @classmethod
    def decrypt(cls, val: str) -> str:
        if not val or not isinstance(val, str):
            return val
        if not val.startswith("enc:fernet:"):
            return val
        try:
            cipher = cls._get_cipher()
            enc_part = val[len("enc:fernet:"):]
            return cipher.decrypt(enc_part.encode("utf-8")).decode("utf-8")
        except Exception as e:
            logger.warning(f"[McpSecretVault] Decryption failed: {e}")
            return ""

    @classmethod
    def encrypt_dict(cls, d: Dict[str, str]) -> Dict[str, str]:
        """Encrypts known sensitive keys or values in a dictionary."""
        out = {}
        sensitive_pattern = re.compile(r"(?i)(TOKEN|KEY|SECRET|PASSWORD|AUTH|CREDENTIAL|PAT)")
        for k, v in d.items():
            if sensitive_pattern.search(k) and v and not v.startswith("enc:fernet:"):
                out[k] = cls.encrypt(v)
            else:
                out[k] = v
        return out

    @classmethod
    def decrypt_dict(cls, d: Dict[str, str]) -> Dict[str, str]:
        """Decrypts all encrypted values in a dictionary."""
        out = {}
        for k, v in d.items():
            out[k] = cls.decrypt(v)
        return out

    @classmethod
    def redact_dict(cls, d: Dict[str, Any]) -> Dict[str, Any]:
        """Redacts sensitive values for diagnostic export or UI display."""
        out = {}
        sensitive_pattern = re.compile(r"(?i)(TOKEN|KEY|SECRET|PASSWORD|AUTH|CREDENTIAL|PAT)")
        for k, v in d.items():
            if sensitive_pattern.search(k):
                out[k] = "***REDACTED***"
            elif isinstance(v, str) and v.startswith("enc:fernet:"):
                out[k] = "***ENCRYPTED***"
            else:
                out[k] = v
        return out


def build_minimal_mcp_env(custom_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Constructs a minimal child process environment, scrubbing sensitive backend secrets
    (Firebase, GitHub, Session, Stroke internal keys) and injecting decrypted user env.
    """
    SAFE_SYSTEM_KEYS = {
        "PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "TEMP", "TMP",
        "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "NODE_PATH", "TERM",
        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"
    }

    env: Dict[str, str] = {}
    backend_secret_pattern = re.compile(
        r"(?i)(KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH|FERNET|SESSION|FIREBASE|GITHUB|STROKE)"
    )

    for k, v in os.environ.items():
        if k in SAFE_SYSTEM_KEYS:
            # Ensure safe system var itself doesn't contain secrets
            if not backend_secret_pattern.search(k):
                env[k] = v

    # Extend standard paths safely
    current_path = env.get("PATH", "")
    local_node_bin = os.path.expanduser("~/.local/node/bin")
    if os.path.exists(local_node_bin) and local_node_bin not in current_path:
        env["PATH"] = f"{local_node_bin}{os.pathsep}{current_path}"

    # Merge decrypted custom env safely (blocking process injection & secret override)
    DANGEROUS_INJECTION_KEYS = {
        "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "PYTHONPATH",
        "PYTHONHOME", "NODE_OPTIONS", "STROKE_INTERNAL_SECRET",
        "STROKE_ENCRYPTION_KEY", "STROKE_VAULT_KEY", "SHELL", "HOME"
    }

    if custom_env:
        decrypted = McpSecretVault.decrypt_dict(custom_env)
        for k, v in decrypted.items():
            clean_k = str(k).strip()
            if not clean_k or any(c in clean_k for c in ("\r", "\n", "\0", "=")):
                continue
            if clean_k.upper() in DANGEROUS_INJECTION_KEYS:
                logger.warning(f"[McpEnv] Blocked dangerous process injection variable: '{clean_k}'")
                continue
            if any(c in str(v) for c in ("\r", "\n", "\0")):
                logger.warning(f"[McpEnv] Stripped control characters from env var '{clean_k}'")
                v = str(v).replace("\r", "").replace("\n", "").replace("\0", "")
            env[clean_k] = str(v)

    return env


# ------------------------------------------------------------------------------
# JSON SCHEMA VALIDATOR
# ------------------------------------------------------------------------------
class McpJsonSchemaValidator:
    """
    Validates tool call arguments and discovered tool definitions against
    JSON Schema specifications (required fields, types, enums, min/max,
    additionalProperties policy).
    """

    TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None)
    }

    @classmethod
    def validate(cls, schema: Dict[str, Any], data: Any, path: str = "arguments") -> None:
        if not schema or not isinstance(schema, dict):
            return

        expected_type = schema.get("type")
        if expected_type and expected_type in cls.TYPE_MAP:
            target_types = cls.TYPE_MAP[expected_type]
            # Handle float/int distinction: bool is a subclass of int in Python
            if expected_type in ("integer", "number") and isinstance(data, bool):
                raise McpError(f"Field '{path}' expected {expected_type}, got boolean.", code=-32602)
            if expected_type == "integer" and isinstance(data, float) and not data.is_integer():
                raise McpError(f"Field '{path}' expected integer, got float {data}.", code=-32602)
            if not isinstance(data, target_types):
                raise McpError(f"Field '{path}' expected type '{expected_type}', got {type(data).__name__}.", code=-32602)

        # Enums
        if "enum" in schema and isinstance(schema["enum"], list):
            if data not in schema["enum"]:
                raise McpError(f"Field '{path}' value {json.dumps(data)} is not one of allowed values: {schema['enum']}", code=-32602)

        # Numeric limits
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            if "minimum" in schema and data < schema["minimum"]:
                raise McpError(f"Field '{path}' value {data} is less than minimum {schema['minimum']}.", code=-32602)
            if "maximum" in schema and data > schema["maximum"]:
                raise McpError(f"Field '{path}' value {data} is greater than maximum {schema['maximum']}.", code=-32602)

        # String limits
        if isinstance(data, str):
            if "minLength" in schema and len(data) < schema["minLength"]:
                raise McpError(f"Field '{path}' length {len(data)} is shorter than minLength {schema['minLength']}.", code=-32602)
            if "maxLength" in schema and len(data) > schema["maxLength"]:
                raise McpError(f"Field '{path}' length {len(data)} is longer than maxLength {schema['maxLength']}.", code=-32602)
            if "pattern" in schema:
                pattern = schema["pattern"]
                if not re.search(pattern, data):
                    raise McpError(f"Field '{path}' does not match pattern '{pattern}'.", code=-32602)

        # Object validation
        if isinstance(data, dict):
            # Required fields
            required = schema.get("required", [])
            for req in required:
                if req not in data:
                    raise McpError(f"Missing required parameter '{path}.{req}'.", code=-32602)

            # Additional properties policy
            allow_additional = schema.get("additionalProperties", True)
            props = schema.get("properties", {})
            if allow_additional is False:
                for k in data.keys():
                    if k not in props:
                        raise McpError(f"Unrecognized property '{path}.{k}' not allowed by tool schema.", code=-32602)

            # Recursive property validation
            for k, val in data.items():
                if k in props and isinstance(props[k], dict):
                    cls.validate(props[k], val, path=f"{path}.{k}")

        # Array validation
        if isinstance(data, list) and "items" in schema and isinstance(schema["items"], dict):
            item_schema = schema["items"]
            for idx, item in enumerate(data):
                cls.validate(item_schema, item, path=f"{path}[{idx}]")

    @classmethod
    def validate_tool_shape(cls, tool: Dict[str, Any]) -> None:
        """Validates that a tool definition returned from tools/list conforms to standard shape."""
        if not isinstance(tool, dict):
            raise McpError("Discovered tool is not a JSON object.", code=-32600)
        name = tool.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            raise McpError("Discovered tool missing valid non-empty 'name'.", code=-32600)
        schema = tool.get("inputSchema") or tool.get("parameters")
        if schema is not None and not isinstance(schema, dict):
            raise McpError(f"Tool '{name}' inputSchema must be a JSON object.", code=-32600)


# ------------------------------------------------------------------------------
# TRANSPORT INTERFACES
# ------------------------------------------------------------------------------
class McpTransport:
    """Abstract Base Class for MCP transports."""
    async def connect(self):
        raise NotImplementedError

    async def send(self, message: Dict[str, Any]):
        raise NotImplementedError

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Any:
        raise NotImplementedError

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None):
        raise NotImplementedError

    async def close(self):
        raise NotImplementedError

    def is_connected(self) -> bool:
        raise NotImplementedError


class StdioTransport(McpTransport):
    """
    Standard IO transport communicating with a child process via JSON-RPC over stdin/stdout.
    Hardened with minimal environment sanitization, process group isolation, and robust cleanup.
    """
    def __init__(
        self,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None
    ):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self.process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._pending_requests: Dict[Any, asyncio.Future] = {}
        self._notification_handlers: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []
        self._stderr_buffer: List[str] = []
        self._closed = False
        self._pid: Optional[int] = None

    def is_connected(self) -> bool:
        return self.process is not None and self.process.returncode is None and not self._closed

    def register_notification_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]):
        self._notification_handlers.append(handler)

    def check_executable(self) -> str:
        """Verifies executable existence on disk or in PATH."""
        cmd_expanded = os.path.expanduser(self.command)
        if os.path.exists(cmd_expanded) and os.access(cmd_expanded, os.X_OK):
            return cmd_expanded
        resolved = shutil.which(self.command)
        if resolved:
            return resolved
        raise McpError(f"MCP executable '{self.command}' not found on disk or in PATH.", code=-32602)

    async def connect(self):
        exec_path = self.check_executable()
        minimal_env = build_minimal_mcp_env(self.env)

        # Process group management kwargs
        kwargs: Dict[str, Any] = {
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "env": minimal_env,
            "cwd": self.cwd,
            "limit": 16 * 1024 * 1024  # 16 MB buffer limit for large MCP tool manifests
        }
        if sys.platform != "win32":
            kwargs["start_new_session"] = True

        try:
            self.process = await asyncio.create_subprocess_exec(
                exec_path,
                *self.args,
                **kwargs
            )
            self._pid = self.process.pid
            with _ACTIVE_STDIO_PIDS_LOCK:
                _ACTIVE_STDIO_PIDS.add(self._pid)
            self._closed = False
            self._reader_task = asyncio.create_task(self._read_stdout_loop())
            self._stderr_task = asyncio.create_task(self._read_stderr_loop())
        except Exception as e:
            logger.error(f"[McpStdio] Failed to launch '{self.command}': {e}")
            raise McpError(f"Failed to spawn MCP process '{self.command}': {str(e)}")

    async def send(self, message: Dict[str, Any]):
        if not self.is_connected() or not self.process or not self.process.stdin:
            raise McpError("Stdio transport is disconnected.")

        raw_line = json.dumps(message) + "\n"
        self.process.stdin.write(raw_line.encode("utf-8"))
        await self.process.stdin.drain()

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Any:
        req_id = str(uuid.uuid4())
        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }
        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = fut

        try:
            await self.send(msg)
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending_requests.pop(req_id, None)

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None):
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }
        await self.send(msg)

    async def _read_stdout_loop(self):
        while self.is_connected() and self.process and self.process.stdout:
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break
                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    logger.debug(f"[McpStdio non-JSON stdout]: {raw[:150]}")
                    continue

                req_id = payload.get("id")
                if req_id is not None and req_id in self._pending_requests:
                    fut = self._pending_requests[req_id]
                    if not fut.done():
                        if "error" in payload:
                            err = payload["error"]
                            fut.set_exception(McpError(
                                message=err.get("message", "Unknown MCP RPC error"),
                                code=err.get("code", -32000),
                                data=err.get("data")
                            ))
                        else:
                            fut.set_result(payload.get("result"))
                else:
                    # Server notification or asynchronous response
                    for handler in self._notification_handlers:
                        try:
                            res = handler(payload)
                            if asyncio.iscoroutine(res):
                                asyncio.create_task(res)
                        except Exception as ne:
                            logger.error(f"[McpStdio notification handler error]: {ne}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[McpStdio read loop error]: {e}")
                break

    async def _read_stderr_loop(self):
        while self.process and self.process.stderr:
            try:
                line = await self.process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    self._stderr_buffer.append(text)
                    if len(self._stderr_buffer) > 200:
                        self._stderr_buffer.pop(0)
            except Exception:
                break

    def get_recent_stderr(self) -> str:
        return "\n".join(self._stderr_buffer)

    async def close(self):
        self._closed = True
        if self._reader_task:
            self._reader_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()

        for req_id, fut in list(self._pending_requests.items()):
            if not fut.done():
                fut.set_exception(McpError("Transport closed"))
        self._pending_requests.clear()

        # Robust process tree teardown to prevent zombies
        if self.process:
            pid = self.process.pid
            with _ACTIVE_STDIO_PIDS_LOCK:
                _ACTIVE_STDIO_PIDS.discard(pid)
            try:
                if self.process.stdin and not self.process.stdin.is_closing():
                    self.process.stdin.close()
            except Exception:
                pass

            try:
                if sys.platform != "win32":
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    self.process.terminate()

                await asyncio.wait_for(self.process.wait(), timeout=1.5)
            except (asyncio.TimeoutError, Exception):
                try:
                    if sys.platform != "win32":
                        try:
                            os.killpg(os.getpgid(pid), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        self.process.kill()
                    await self.process.wait()
                except Exception:
                    pass

            self.process = None


class StreamableHttpTransport(McpTransport):
    """
    Streamable HTTP & SSE transport for MCP servers communicating over HTTP.
    Enforces SSRF protection, redirect verification, Accept content negotiation,
    and SSE stream buffer decoding.
    """
    def __init__(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
        allow_local: bool = False
    ):
        self.raw_url = url
        self.allow_local = allow_local
        self.validated_url = SsrfProtector.validate_url(url, allow_local=allow_local).rstrip("/")
        self.custom_headers = headers or {}
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self.client: Optional[httpx.AsyncClient] = None
        self._connected = False
        self._notification_handlers: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []

    def is_connected(self) -> bool:
        return self._connected and self.client is not None

    def register_notification_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]):
        self._notification_handlers.append(handler)

    async def connect(self):
        # Re-verify destination URL against SSRF
        self.validated_url = SsrfProtector.validate_url(self.raw_url, allow_local=self.allow_local).rstrip("/")

        decrypted_headers = McpSecretVault.decrypt_dict(self.custom_headers)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        headers.update(decrypted_headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        # Custom transport to intercept redirects and validate destination against SSRF
        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout,
            follow_redirects=False  # Handled manually to inspect Location header
        )
        self._connected = True

    async def _safe_post(self, endpoint: str, payload: Dict[str, Any], timeout: float) -> httpx.Response:
        """Sends POST request with manual redirect validation against SSRF and credential stripping."""
        if not self.client:
            raise McpError("HTTP transport not connected.")

        current_url = endpoint
        max_redirects = 5
        cross_origin_redirected = False
        initial_netloc = urllib.parse.urlparse(endpoint).netloc.lower()
        sensitive_header_names = {"authorization", "cookie", "proxy-authorization", "x-api-key"}

        for _ in range(max_redirects):
            # Validate URL before dispatch (re-validates DNS resolution)
            SsrfProtector.validate_url(current_url, allow_local=self.allow_local)

            req_headers = {}
            if self.session_id and not cross_origin_redirected:
                req_headers["Mcp-Session-Id"] = self.session_id

            if cross_origin_redirected:
                # Strip sensitive headers on cross-origin redirect to prevent credential leakage
                sanitized_client_headers = {
                    k: v for k, v in self.client.headers.items()
                    if k.lower() not in sensitive_header_names
                }
                async with httpx.AsyncClient(
                    headers=sanitized_client_headers,
                    timeout=timeout,
                    follow_redirects=False
                ) as redirect_client:
                    resp = await redirect_client.post(current_url, json=payload, headers=req_headers, timeout=timeout)
            else:
                resp = await self.client.post(current_url, json=payload, headers=req_headers, timeout=timeout)

            # Capture session header if provided
            if "Mcp-Session-Id" in resp.headers and not cross_origin_redirected:
                self.session_id = resp.headers["Mcp-Session-Id"]

            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if not location:
                    raise McpError(f"HTTP redirect {resp.status_code} received without Location header.")
                next_url = urllib.parse.urljoin(current_url, location)
                # Ensure redirect target passes SSRF check
                SsrfProtector.validate_url(next_url, allow_local=self.allow_local)
                next_netloc = urllib.parse.urlparse(next_url).netloc.lower()
                if next_netloc != initial_netloc:
                    cross_origin_redirected = True
                current_url = next_url
                continue

            return resp

        raise McpError("Exceeded maximum redirects (5) during MCP HTTP request.")

    def _parse_response_body(self, response: httpx.Response) -> Dict[str, Any]:
        """Parses response as either standard JSON or Server-Sent Events (SSE) data stream."""
        content_type = response.headers.get("Content-Type", "")
        text = response.text.strip()

        # 1. Standard application/json
        if "application/json" in content_type or (text.startswith("{") and text.endswith("}")):
            try:
                return response.json()
            except Exception as e:
                raise McpError(f"Failed to parse JSON response: {e}")

        # 2. Server-Sent Events (text/event-stream)
        if "text/event-stream" in content_type or "data:" in text:
            # Parse lines looking for data: {...}
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    data_str = line[len("data:"):].strip()
                    if data_str:
                        try:
                            return json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

        raise McpError(f"Unrecognized response format from MCP server: {text[:200]}")

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Any:
        req_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }

        try:
            response = await self._safe_post(self.validated_url, payload, timeout=timeout)
            if response.status_code >= 400:
                raise McpError(f"HTTP {response.status_code}: {response.text[:200]}", code=response.status_code)

            res_json = self._parse_response_body(response)
            if "error" in res_json:
                err = res_json["error"]
                raise McpError(
                    message=err.get("message", "Unknown HTTP MCP error"),
                    code=err.get("code", -32000),
                    data=err.get("data")
                )
            return res_json.get("result")
        except httpx.RequestError as re:
            raise McpError(f"HTTP network failure connecting to {self.validated_url}: {str(re)}")

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None):
        if not self.client:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }
        try:
            await self._safe_post(self.validated_url, payload, timeout=5.0)
        except Exception as e:
            logger.debug(f"[McpHttp notify non-fatal]: {e}")

    async def close(self):
        self._connected = False
        if self.client:
            await self.client.aclose()
            self.client = None


# ------------------------------------------------------------------------------
# MCP CLIENT IMPLEMENTATION
# ------------------------------------------------------------------------------
class McpClient:
    """
    Standard MCP Client managing the protocol handshake, dynamic tool discovery,
    namespacing, argument validation, and lifecycle state transitions.
    """
    def __init__(self, server_id: str, transport: McpTransport, server_name: str = ""):
        self.server_id = server_id
        self.server_name = server_name or server_id
        self.transport = transport
        self.server_info: Dict[str, Any] = {}
        self.capabilities: Dict[str, Any] = {}
        self.discovered_tools: List[Dict[str, Any]] = []
        self.state: McpServerState = McpServerState.CONFIGURED
        self.error_message: str = ""
        self._initialized = False

    def is_active(self) -> bool:
        return self._initialized and self.transport.is_connected() and self.state == McpServerState.TOOLS_READY

    async def start(self) -> Dict[str, Any]:
        """Performs connection, initialize handshake, capability negotiation, and tool discovery."""
        try:
            self.state = McpServerState.EXECUTABLE_FOUND
            await self.transport.connect()
            self.state = McpServerState.PROCESS_RUNNING

            init_params = {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "roots": {"listChanged": True},
                    "sampling": {}
                },
                "clientInfo": CLIENT_INFO
            }

            result = await self.transport.request("initialize", init_params, timeout=15.0)
            self.server_info = result.get("serverInfo", {})
            self.capabilities = result.get("capabilities", {})
            self.state = McpServerState.PROTOCOL_CONNECTED

            # Complete handshake notification
            await self.transport.notify("notifications/initialized", {})
            self._initialized = True

            # Register dynamic tools change listener
            if hasattr(self.transport, "register_notification_handler"):
                self.transport.register_notification_handler(self._on_server_notification)

            # Discover available tools
            await self.refresh_tools()
            self.state = McpServerState.TOOLS_READY
            return result
        except Exception as exc:
            self.state = McpServerState.FAILED
            self.error_message = str(exc)
            await self.close()
            raise

    async def _on_server_notification(self, notification: Dict[str, Any]):
        method = notification.get("method")
        if method == "notifications/tools/list_changed":
            logger.info(f"[MCP] Tools list changed on server '{self.server_id}'. Refreshing tools...")
            try:
                await self.refresh_tools()
            except Exception as e:
                logger.error(f"[MCP] Failed to refresh tools after notification: {e}")

    async def refresh_tools(self) -> List[Dict[str, Any]]:
        """
        Queries tools/list with resilient pagination, cycle detection, max page limits,
        shape validation, and tool deduplication.
        """
        tools: List[Dict[str, Any]] = []
        seen_cursors: Set[str] = set()
        seen_tool_names: Set[str] = set()
        cursor = None
        max_pages = 25
        page_count = 0

        while page_count < max_pages:
            page_count += 1
            params: Dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor

            result = await self.transport.request("tools/list", params, timeout=12.0)
            if not result or not isinstance(result, dict):
                break

            fetched = result.get("tools", [])
            for t in fetched:
                try:
                    McpJsonSchemaValidator.validate_tool_shape(t)
                    t_name = t.get("name")
                    if t_name and t_name not in seen_tool_names:
                        seen_tool_names.add(t_name)
                        tools.append(t)
                except McpError as ve:
                    logger.warning(f"[MCP] Server '{self.server_id}' returned invalid tool shape: {ve}")

            next_cursor = result.get("nextCursor")
            if not next_cursor or next_cursor in seen_cursors:
                # Cycle detected or pagination complete
                break

            seen_cursors.add(next_cursor)
            cursor = next_cursor

        self.discovered_tools = tools
        return self.discovered_tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout: float = 45.0) -> Dict[str, Any]:
        """
        Executes tools/call on the remote MCP server with strict argument schema validation.
        Properly honors MCP isError and JSON-RPC errors — never reports failure as success!
        """
        if not self.transport.is_connected():
            return {
                "status": "error",
                "server_id": self.server_id,
                "tool": tool_name,
                "message": f"Server '{self.server_id}' is disconnected."
            }

        # Local schema validation before dispatch
        tool_def = next((t for t in self.discovered_tools if t.get("name") == tool_name), None)
        if tool_def:
            schema = tool_def.get("inputSchema") or tool_def.get("parameters")
            if schema and isinstance(schema, dict):
                try:
                    McpJsonSchemaValidator.validate(schema, arguments, path=tool_name)
                except McpError as ve:
                    return {
                        "status": "error",
                        "server_id": self.server_id,
                        "tool": tool_name,
                        "error_code": ve.code,
                        "message": str(ve)
                    }

        params = {
            "name": tool_name,
            "arguments": arguments
        }

        try:
            result = await self.transport.request("tools/call", params, timeout=timeout)
            if not result or not isinstance(result, dict):
                return {
                    "status": "success",
                    "server_id": self.server_id,
                    "tool": tool_name,
                    "result": result
                }

            # Spec compliance: MCP tools indicate errors via isError: true
            is_error = result.get("isError", False)
            content = result.get("content", [])
            output_text = ""
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict):
                    output_text = first.get("text", "")
            elif isinstance(result.get("output"), str):
                output_text = result["output"]

            if is_error:
                return {
                    "status": "error",
                    "server_id": self.server_id,
                    "tool": tool_name,
                    "is_error": True,
                    "message": output_text or "Tool execution failed on remote MCP server.",
                    "result": result
                }

            return {
                "status": "success",
                "server_id": self.server_id,
                "tool": tool_name,
                "result": result,
                "output": output_text
            }

        except McpError as me:
            return {
                "status": "error",
                "server_id": self.server_id,
                "tool": tool_name,
                "error_code": me.code,
                "message": str(me)
            }
        except Exception as e:
            return {
                "status": "error",
                "server_id": self.server_id,
                "tool": tool_name,
                "message": f"Tool execution failed: {str(e)}"
            }

    async def close(self):
        self._initialized = False
        self.state = McpServerState.OFFLINE
        await self.transport.close()


# ------------------------------------------------------------------------------
# ONE-TIME APPROVAL MANAGER
# ------------------------------------------------------------------------------
@dataclass
class McpApprovalRecord:
    approval_id: str
    server_id: str
    action: str  # "register" or "launch"
    target: str  # executable command or URL
    user_uid: str
    created_at: float
    expires_at: float
    consumed: bool = False


class McpApprovalManager:
    """
    Manages one-time, cryptographically random, durably persisted approvals
    for registering, connecting, or launching MCP servers across restarts/instances.
    """
    def __init__(self, store_path: Optional[str] = None):
        self._lock = threading.RLock()
        self._store_path = store_path
        self._approvals: Dict[str, McpApprovalRecord] = {}
        self._load_store()

    def _get_store_path(self) -> str:
        if self._store_path:
            return self._store_path
        return str(paths_service.get_app_data_dir() / "mcp_approvals.json")

    def _load_store(self) -> None:
        path = self._get_store_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                now = time.time()
                for appr_id, rec in raw.items():
                    if not isinstance(rec, dict):
                        continue
                    expires_at = float(rec.get("expires_at", 0))
                    if now > expires_at + 3600:
                        continue
                    self._approvals[appr_id] = McpApprovalRecord(
                        approval_id=str(rec.get("approval_id", appr_id)),
                        server_id=str(rec.get("server_id", "")),
                        action=str(rec.get("action", "")),
                        target=str(rec.get("target", "")),
                        user_uid=str(rec.get("user_uid", "")),
                        created_at=float(rec.get("created_at", 0)),
                        expires_at=expires_at,
                        consumed=bool(rec.get("consumed", False)),
                    )
        except Exception as exc:
            logger.debug(f"[McpApprovalManager] Failed reading approval store: {exc}")

    def _save_store(self) -> None:
        path = self._get_store_path()
        now = time.time()
        payload = {}
        for appr_id, rec in self._approvals.items():
            if now > rec.expires_at + 3600:
                continue
            payload[appr_id] = {
                "approval_id": rec.approval_id,
                "server_id": rec.server_id,
                "action": rec.action,
                "target": rec.target,
                "user_uid": rec.user_uid,
                "created_at": rec.created_at,
                "expires_at": rec.expires_at,
                "consumed": rec.consumed,
            }
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception as exc:
            logger.warning(f"[McpApprovalManager] Failed saving approval store: {exc}")

    def create_approval(
        self,
        server_id: str,
        action: str,
        target: str,
        user_uid: str,
        ttl_seconds: int = 300
    ) -> McpApprovalRecord:
        with self._lock:
            self._load_store()
            appr_id = f"mcp_appr_{uuid.uuid4().hex}"
            now = time.time()
            record = McpApprovalRecord(
                approval_id=appr_id,
                server_id=server_id,
                action=action,
                target=target,
                user_uid=user_uid,
                created_at=now,
                expires_at=now + ttl_seconds,
                consumed=False
            )
            self._approvals[appr_id] = record
            self._save_store()
            return record

    def get_approval(self, approval_id: str) -> Optional[McpApprovalRecord]:
        with self._lock:
            self._load_store()
            return self._approvals.get(approval_id)

    def reject_approval(self, approval_id: str, user_uid: str) -> bool:
        with self._lock:
            self._load_store()
            rec = self._approvals.get(approval_id)
            if not rec or rec.user_uid != user_uid or rec.consumed:
                return False
            rec.consumed = True
            self._save_store()
            return True

    def consume_approval(
        self,
        approval_id: str,
        server_id: str,
        user_uid: str,
        action: Optional[str] = None,
        target: Optional[str] = None,
    ) -> bool:
        with self._lock:
            self._load_store()
            if not approval_id or approval_id not in self._approvals:
                return False
            rec = self._approvals[approval_id]
            if rec.consumed:
                return False
            if rec.server_id != server_id:
                return False
            if rec.user_uid != user_uid:
                return False
            if action is not None and rec.action != action:
                return False
            if target is not None and rec.target != target:
                return False
            if time.time() > rec.expires_at:
                return False

            rec.consumed = True
            self._save_store()
            return True


# ------------------------------------------------------------------------------
# MULTI-SERVER REGISTRY & MANAGER
# ------------------------------------------------------------------------------
@dataclass
class ServerConfig:
    id: str
    name: str
    transport_type: str = "stdio"  # "stdio" or "http"
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    allow_local: bool = False
    description: str = ""

McpServerConfig = ServerConfig


class McpServerRegistry:
    """
    Authoritative single-source-of-truth registry for all MCP servers.
    Provides encrypted configuration storage, 5-tier connection lifecycle management,
    persistent StudioMCP sessions, namespacing, and dispatch.
    """
    _instance: Optional['McpServerRegistry'] = None

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or str(paths_service.get_mcp_config_path())
        self.configs: Dict[str, ServerConfig] = {}
        self.clients: Dict[str, McpClient] = {}
        self.approval_mgr = McpApprovalManager()
        self._lock: Optional[asyncio.Lock] = None
        self.load_configurations()

    @classmethod
    def get_instance(cls) -> 'McpServerRegistry':
        if cls._instance is None:
            cls._instance = McpServerRegistry()
        return cls._instance

    def _ensure_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def load_configurations(self):
        """Loads and decrypts server configurations from disk."""
        if not os.path.exists(self.config_path):
            legacy = str(paths_service.get_legacy_mcp_config_path())
            if not os.path.exists(legacy):
                legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mcp_config.json")
            if os.path.exists(legacy):
                self._import_legacy_config(legacy)
                return
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            self.save_configurations()
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            servers = data.get("mcpServers", {})
            self.configs.clear()
            for s_id, s_data in servers.items():
                self.configs[s_id] = ServerConfig(
                    id=s_id,
                    name=s_data.get("name", s_id.replace("_", " ").title()),
                    transport_type=s_data.get("transport", "stdio" if "command" in s_data else "http"),
                    command=s_data.get("command"),
                    args=s_data.get("args", []),
                    env=s_data.get("env", {}),
                    url=s_data.get("url") or s_data.get("endpoint"),
                    headers=s_data.get("headers", {}),
                    enabled=s_data.get("enabled", True),
                    allow_local=s_data.get("allow_local", False),
                    description=s_data.get("description", "")
                )
        except Exception as e:
            logger.error(f"[McpRegistry] Failed to load config from {self.config_path}: {e}")

    def _import_legacy_config(self, legacy_path: str):
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            servers = data.get("mcpServers", {})
            for s_id, s_data in servers.items():
                self.configs[s_id] = ServerConfig(
                    id=s_id,
                    name=s_id.replace("_", " ").title(),
                    transport_type="stdio" if "command" in s_data else "http",
                    command=s_data.get("command"),
                    args=s_data.get("args", []),
                    env=s_data.get("env", {}),
                    url=s_data.get("url"),
                    enabled=True,
                    allow_local=True if "studio" in s_id.lower() or "roblox" in s_id.lower() else False,
                    description=s_data.get("description", f"Imported MCP server {s_id}")
                )
            self.save_configurations()
        except Exception as e:
            logger.error(f"[McpRegistry] Error migrating legacy config: {e}")

    def save_configurations(self):
        """Saves configurations to disk with encrypted secrets."""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        out = {"mcpServers": {}}
        for s_id, cfg in self.configs.items():
            entry: Dict[str, Any] = {
                "name": cfg.name,
                "transport": cfg.transport_type,
                "enabled": cfg.enabled,
                "allow_local": cfg.allow_local,
                "description": cfg.description
            }
            if cfg.command:
                entry["command"] = cfg.command
                entry["args"] = cfg.args
                # Vault encryption for env
                entry["env"] = McpSecretVault.encrypt_dict(cfg.env)
            if cfg.url:
                entry["url"] = cfg.url
                # Vault encryption for headers
                entry["headers"] = McpSecretVault.encrypt_dict(cfg.headers)
            out["mcpServers"][s_id] = entry

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
        except Exception as e:
            logger.error(f"[McpRegistry] Could not save config: {e}")

    async def connect_server(self, server_id: str, allow_local_override: Optional[bool] = None) -> McpClient:
        """Connects or reconnects a configured server with lifecycle state tracking."""
        async with self._ensure_lock():
            if server_id not in self.configs:
                raise McpError(f"Server '{server_id}' is not configured.")

            cfg = self.configs[server_id]
            if not cfg.enabled:
                raise McpError(f"Server '{server_id}' is currently disabled.")

            # Close existing client cleanly if present
            if server_id in self.clients:
                await self.clients[server_id].close()

            allow_local = allow_local_override if allow_local_override is not None else cfg.allow_local

            transport: McpTransport
            if cfg.transport_type == "stdio":
                if not cfg.command:
                    raise McpError(f"Stdio server '{server_id}' has no command configured.")
                transport = StdioTransport(command=cfg.command, args=cfg.args, env=cfg.env)
            elif cfg.transport_type == "http":
                if not cfg.url:
                    raise McpError(f"HTTP server '{server_id}' has no URL configured.")
                transport = StreamableHttpTransport(url=cfg.url, headers=cfg.headers, allow_local=allow_local)
            else:
                raise McpError(f"Unknown transport type '{cfg.transport_type}'")

            client = McpClient(server_id=server_id, transport=transport, server_name=cfg.name)
            await client.start()
            self.clients[server_id] = client
            return client

    async def disconnect_server(self, server_id: str):
        """Disconnects an active server."""
        async with self._ensure_lock():
            if server_id in self.clients:
                await self.clients[server_id].close()
                del self.clients[server_id]

    async def start_all_enabled(self):
        """Attempts connection for all enabled servers concurrently."""
        tasks = []
        for s_id, cfg in self.configs.items():
            if cfg.enabled:
                tasks.append(self._safe_connect(s_id))
        if tasks:
            await asyncio.gather(*tasks)

    async def _safe_connect(self, server_id: str):
        try:
            await self.connect_server(server_id)
        except Exception as e:
            logger.warning(f"[McpRegistry] Startup connection to '{server_id}' deferred: {e}")

    def list_all_tools(self) -> List[Dict[str, Any]]:
        """Gathers tools across all servers with server namespaces."""
        all_tools = []
        for s_id, client in self.clients.items():
            for tool in client.discovered_tools:
                orig_name = tool.get("name", "")
                namespaced_name = f"{s_id}__{orig_name}"
                schema = tool.get("inputSchema") or tool.get("parameters") or {"type": "object", "properties": {}}
                all_tools.append({
                    "name": namespaced_name,
                    "original_name": orig_name,
                    "server_id": s_id,
                    "server_name": client.server_name,
                    "description": f"[{client.server_name}] {tool.get('description', '')}",
                    "parameters": schema
                })
        return all_tools

    def get_all_tool_schemas(self) -> List[Dict[str, Any]]:
        """Returns OpenAI function-formatted tool schemas for active MCP tools."""
        tools = self.list_all_tools()
        return [{"type": "function", "function": t} for t in tools]

    def register_server(self, cfg: ServerConfig) -> McpClient:
        """Registers a server config and instantiates an McpClient."""
        self.configs[cfg.id] = cfg
        self.save_configurations()

        if cfg.transport_type == "stdio":
            transport = StdioTransport(command=cfg.command or "python", args=cfg.args, env=cfg.env)
        else:
            transport = StreamableHttpTransport(url=cfg.url or "http://localhost", headers=cfg.headers, allow_local=cfg.allow_local)

        client = McpClient(server_id=cfg.id, transport=transport, server_name=cfg.name)
        self.clients[cfg.id] = client
        return client

    async def dispatch_tool(self, full_tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches namespaced tool '{server_id}__{tool_name}' or resolves tool directly."""
        server_id: Optional[str] = None
        target_tool = full_tool_name

        if "__" in full_tool_name:
            server_id, target_tool = full_tool_name.split("__", 1)
        else:
            for s_id, client in self.clients.items():
                if any(t.get("name") == full_tool_name for t in client.discovered_tools):
                    server_id = s_id
                    target_tool = full_tool_name
                    break

        if not server_id or server_id not in self.clients:
            return {
                "status": "error",
                "message": f"No active MCP server found for tool '{full_tool_name}'. Available servers: {list(self.clients.keys())}"
            }

        client = self.clients[server_id]
        return await client.call_tool(target_tool, arguments)

    def get_server_statuses(self) -> List[Dict[str, Any]]:
        """Returns 5-tier diagnostic status for all configured servers."""
        res = []
        for s_id, cfg in self.configs.items():
            client = self.clients.get(s_id)
            state = client.state if client else (McpServerState.CONFIGURED if cfg.enabled else McpServerState.DISABLED)
            connected = client.is_active() if client else False
            tool_count = len(client.discovered_tools) if client and connected else 0

            res.append({
                "id": s_id,
                "name": cfg.name,
                "transport": cfg.transport_type,
                "enabled": cfg.enabled,
                "state": state.value,
                "lifecycle_state": state.value,
                "connected": connected,
                "tools_count": tool_count,
                "endpoint": cfg.command if cfg.transport_type == "stdio" else cfg.url,
                "allow_local": cfg.allow_local,
                "description": cfg.description,
                "error": client.error_message if client else ""
            })
        return res


# Authoritative Global Singleton Instance
global_mcp_registry = McpServerRegistry.get_instance()
