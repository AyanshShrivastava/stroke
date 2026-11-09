"""
================================================================================
STROKE // GENERAL-PURPOSE MODEL CONTEXT PROTOCOL (MCP) CLIENT & REGISTRY
Full JSON-RPC 2.0 / MCP spec compliance over STDIO and Streamable HTTP transports.
Multi-server management, dynamic tool discovery, namespacing, and schema validation.
================================================================================
"""

import os
import sys
import json
import asyncio
import logging
import uuid
from typing import Dict, List, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field
import httpx

logger = logging.getLogger("stroke.mcp_client")

# ------------------------------------------------------------------------------
# EXCEPTIONS & PROTOCOL CONSTANTS
# ------------------------------------------------------------------------------
MCP_PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {
    "name": "Stroke",
    "version": "2.0.0"
}

class McpError(Exception):
    """Raised when an MCP protocol, transport, or tool call error occurs."""
    def __init__(self, message: str, code: int = -32000, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


# ------------------------------------------------------------------------------
# TRANSPORT INTERFACES
# ------------------------------------------------------------------------------
class McpTransport:
    """Abstract Base Class for MCP transports."""
    async def connect(self):
        raise NotImplementedError

    async def send(self, message: Dict[str, Any]):
        raise NotImplementedError

    async def close(self):
        raise NotImplementedError

    def is_connected(self) -> bool:
        raise NotImplementedError


class StdioTransport(McpTransport):
    """Standard IO transport communicating with a child process via JSON-RPC over stdin/stdout."""
    def __init__(
        self,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None
    ):
        self.command = command
        self.args = args or []
        self.env = env
        self.cwd = cwd
        self.process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._pending_requests: Dict[Any, asyncio.Future] = {}
        self._notification_handlers: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []
        self._stderr_buffer: List[str] = []
        self._closed = False

    def is_connected(self) -> bool:
        return self.process is not None and self.process.returncode is None and not self._closed

    def register_notification_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]):
        self._notification_handlers.append(handler)

    async def connect(self):
        full_env = os.environ.copy()
        if self.env:
            full_env.update(self.env)

        try:
            self.process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=full_env,
                cwd=self.cwd
            )
            self._reader_task = asyncio.create_task(self._read_stdout_loop())
            self._stderr_task = asyncio.create_task(self._read_stderr_loop())
            self._closed = False
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
                    logger.debug(f"[McpStdio raw stdout non-JSON]: {raw}")
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
                    # Handle notification
                    for handler in self._notification_handlers:
                        try:
                            res = handler(payload)
                            if asyncio.iscoroutine(res):
                                asyncio.create_task(res)
                        except Exception as ne:
                            logger.error(f"[McpStdio notification error]: {ne}")

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

        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None


class StreamableHttpTransport(McpTransport):
    """Streamable HTTP / SSE transport for MCP servers communicating over HTTP."""
    def __init__(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0
    ):
        self.url = url.rstrip("/")
        self.custom_headers = headers or {}
        self.timeout = timeout
        self.client: Optional[httpx.AsyncClient] = None
        self._connected = False
        self._notification_handlers: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []

    def is_connected(self) -> bool:
        return self._connected and self.client is not None

    def register_notification_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]):
        self._notification_handlers.append(handler)

    async def connect(self):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        headers.update(self.custom_headers)
        self.client = httpx.AsyncClient(headers=headers, timeout=self.timeout)
        self._connected = True

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Any:
        if not self.client:
            raise McpError("HTTP transport not connected.")

        req_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }

        # Most MCP HTTP endpoints expose /mcp or direct URL
        endpoint = self.url
        try:
            response = await self.client.post(endpoint, json=payload, timeout=timeout)
            if response.status_code >= 400:
                raise McpError(f"HTTP error {response.status_code}: {response.text[:200]}", code=response.status_code)

            res_json = response.json()
            if "error" in res_json:
                err = res_json["error"]
                raise McpError(
                    message=err.get("message", "Unknown HTTP MCP error"),
                    code=err.get("code", -32000),
                    data=err.get("data")
                )
            return res_json.get("result")
        except httpx.RequestError as re:
            raise McpError(f"HTTP network failure connecting to {self.url}: {str(re)}")

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None):
        if not self.client:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }
        try:
            await self.client.post(self.url, json=payload, timeout=5.0)
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
    and structured tool calls.
    """
    def __init__(self, server_id: str, transport: McpTransport, server_name: str = ""):
        self.server_id = server_id
        self.server_name = server_name or server_id
        self.transport = transport
        self.server_info: Dict[str, Any] = {}
        self.capabilities: Dict[str, Any] = {}
        self.discovered_tools: List[Dict[str, Any]] = []
        self._initialized = False

    def is_active(self) -> bool:
        return self._initialized and self.transport.is_connected()

    async def start(self) -> Dict[str, Any]:
        """Performs connection, initialize handshake, and tool discovery."""
        await self.transport.connect()

        # Handshake: initialize
        init_params = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "roots": {"listChanged": True},
                "sampling": {}
            },
            "clientInfo": CLIENT_INFO
        }

        if hasattr(self.transport, "request"):
            result = await self.transport.request("initialize", init_params, timeout=15.0)
            self.server_info = result.get("serverInfo", {})
            self.capabilities = result.get("capabilities", {})

            # Handshake notification: notifications/initialized
            await self.transport.notify("notifications/initialized", {})
            self._initialized = True

            # Register dynamic tools change listener
            if hasattr(self.transport, "register_notification_handler"):
                self.transport.register_notification_handler(self._on_server_notification)

            # Discover available tools
            await self.refresh_tools()
            return result
        else:
            self._initialized = True
            return {}

    async def _on_server_notification(self, notification: Dict[str, Any]):
        method = notification.get("method")
        if method == "notifications/tools/list_changed":
            logger.info(f"[MCP] Tools list changed on server '{self.server_id}'. Refreshing...")
            await self.refresh_tools()

    async def refresh_tools(self) -> List[Dict[str, Any]]:
        """Queries tools/list with pagination support and caches discovered tools."""
        tools: List[Dict[str, Any]] = []
        cursor = None

        while True:
            params = {}
            if cursor:
                params["cursor"] = cursor

            if not hasattr(self.transport, "request"):
                break

            result = await self.transport.request("tools/list", params, timeout=10.0)
            if not result or not isinstance(result, dict):
                break

            fetched = result.get("tools", [])
            tools.extend(fetched)

            cursor = result.get("nextCursor")
            if not cursor:
                break

        self.discovered_tools = tools
        return self.discovered_tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout: float = 45.0) -> Dict[str, Any]:
        """Calls tools/call with the specified arguments."""
        if not self.is_active():
            raise McpError(f"Server '{self.server_id}' is offline or disconnected.")

        # Local schema validation if tool schema exists
        self.validate_arguments(tool_name, arguments)

        params = {
            "name": tool_name,
            "arguments": arguments
        }

        try:
            result = await self.transport.request("tools/call", params, timeout=timeout)
            return {
                "status": "success",
                "server_id": self.server_id,
                "tool": tool_name,
                "result": result
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

    def validate_arguments(self, tool_name: str, arguments: Dict[str, Any]):
        """Validates arguments against inputSchema required fields."""
        schema = None
        for t in self.discovered_tools:
            if t.get("name") == tool_name:
                schema = t.get("inputSchema") or t.get("parameters")
                break

        if not schema or not isinstance(schema, dict):
            return

        required = schema.get("required", [])
        missing = [r for r in required if r not in arguments]
        if missing:
            raise McpError(f"Missing required parameter(s) for tool '{tool_name}': {', '.join(missing)}", code=-32602)

    async def close(self):
        self._initialized = False
        await self.transport.close()


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
    description: str = ""

McpServerConfig = ServerConfig


class McpServerRegistry:
    """
    Central manager for multiple MCP servers.
    Handles configuration persistence, connection pooling, namespacing, and dispatch.
    """
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "mcp_servers.json"
        )
        self.configs: Dict[str, ServerConfig] = {}
        self.clients: Dict[str, McpClient] = {}
        self._lock: Optional[asyncio.Lock] = None
        self.load_configurations()

    def _ensure_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def load_configurations(self):
        """Loads server configurations from disk."""
        if not os.path.exists(self.config_path):
            # Check legacy mcp_config.json
            legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mcp_config.json")
            if os.path.exists(legacy):
                self._import_legacy_config(legacy)
                return

            # Default initial empty configuration
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
                    description=f"Imported MCP server {s_id}"
                )
            self.save_configurations()
        except Exception as e:
            logger.error(f"[McpRegistry] Error migrating legacy config: {e}")

    def save_configurations(self):
        """Saves active configurations to disk."""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        out = {"mcpServers": {}}
        for s_id, cfg in self.configs.items():
            entry = {
                "name": cfg.name,
                "transport": cfg.transport_type,
                "enabled": cfg.enabled,
                "description": cfg.description
            }
            if cfg.command:
                entry["command"] = cfg.command
                entry["args"] = cfg.args
                entry["env"] = cfg.env
            if cfg.url:
                entry["url"] = cfg.url
                entry["headers"] = cfg.headers
            out["mcpServers"][s_id] = entry

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
        except Exception as e:
            logger.error(f"[McpRegistry] Could not save config: {e}")

    async def connect_server(self, server_id: str) -> McpClient:
        """Connects or reconnects a configured server."""
        async with self._ensure_lock():
            if server_id not in self.configs:
                raise McpError(f"Server '{server_id}' is not configured.")

            cfg = self.configs[server_id]
            if not cfg.enabled:
                raise McpError(f"Server '{server_id}' is currently disabled.")

            # Close existing if active
            if server_id in self.clients:
                await self.clients[server_id].close()

            transport: McpTransport
            if cfg.transport_type == "stdio":
                if not cfg.command:
                    raise McpError(f"Stdio server '{server_id}' has no command configured.")
                transport = StdioTransport(command=cfg.command, args=cfg.args, env=cfg.env)
            elif cfg.transport_type == "http":
                if not cfg.url:
                    raise McpError(f"HTTP server '{server_id}' has no URL configured.")
                transport = StreamableHttpTransport(url=cfg.url, headers=cfg.headers)
            else:
                raise McpError(f"Unknown transport type '{cfg.transport_type}'")

            client = McpClient(server_id=server_id, transport=transport, server_name=cfg.name)
            await client.start()
            self.clients[server_id] = client
            return client

    async def disconnect_server(self, server_id: str):
        """Disconnects a server if connected."""
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
        """
        Gathers tools across all connected servers with namespacing.
        Returns OpenAI-compatible / MCP tool definitions with server tags.
        """
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
        if cfg.transport_type == "stdio":
            transport = StdioTransport(command=cfg.command or "python", args=cfg.args, env=cfg.env)
        else:
            transport = StreamableHttpTransport(url=cfg.url or "http://localhost", headers=cfg.headers)
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
            # Attempt to find which server hosts this tool
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
        """Returns comprehensive diagnostic status for all configured servers."""
        res = []
        for s_id, cfg in self.configs.items():
            client = self.clients.get(s_id)
            connected = client.is_active() if client else False
            tool_count = len(client.discovered_tools) if client and connected else 0
            res.append({
                "id": s_id,
                "name": cfg.name,
                "transport": cfg.transport_type,
                "enabled": cfg.enabled,
                "connected": connected,
                "tools_count": tool_count,
                "endpoint": cfg.command if cfg.transport_type == "stdio" else cfg.url,
                "description": cfg.description
            })
        return res


# Global singleton instance
global_mcp_registry = McpServerRegistry()
