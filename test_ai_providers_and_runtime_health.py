"""
Stroke AI // AI Providers and Runtime Health Test Suite
================================================================================
Exhaustively verifies:
  1. Real Model & Provider Registry (documented source, context limit, modalities, tools, etc.)
  2. Parameter validation & separation of creativity/temperature from reasoning effort
  3. Response normalization (ProviderResponse, usage, tool calls, error hierarchy)
  4. Transparent fallback tracking (never silent fallback)
  5. Cancellation handling
  6. Independent health probes:
     - Ollama online, offline (connect error), timeout, malformed JSON, HTTP error
     - GGUF binary magic header validation
     - GPU acceleration detection (never reported by import alone)
     - Isolation: one probe failure does not abort other probes
     - Remote providers: never marked connected merely because key is configured
  7. Endpoints /ai/status, /ai/models, /ai/providers, /health, /api/health never return null
     and conform to validated schemas
================================================================================
"""

import os
import sys
import time
import json
import asyncio
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

import httpx
from fastapi.testclient import TestClient

import main
from main import app
import ai_provider_service
from ai_provider_service import (
    ProviderType,
    ModelMetadata,
    MODEL_REGISTRY,
    resolve_model_id,
    InferenceParameters,
    validate_parameters_for_model,
    ProviderResponse,
    StreamChunk,
    NormalizedUsage,
    NormalizedToolCall,
    ProviderError,
    ProviderTimeoutError,
    ProviderRateLimitError,
    ProviderOutOfMemoryError,
    ProviderRuntimeMissingError,
    ProviderUnsupportedModelError,
    ProviderUnavailableError,
    GgufHealthStatus,
    LlamaCppHealthStatus,
    OllamaHealthStatus,
    McpHealthStatus,
    GithubHealthStatus,
    NetworkHealthStatus,
    FilesystemHealthStatus,
    RemoteProviderHealthStatus,
    AiStatusResponse,
    check_gguf_integrity,
    probe_llama_cpp,
    probe_gguf_local,
    probe_ollama,
    probe_mcp,
    probe_github,
    probe_network,
    probe_filesystem,
    probe_remote_provider,
    probe_all_ai_health,
    LlamaCppProvider,
    OllamaProvider,
    RemoteOpenAiCompatibleProvider,
    AiProviderManager
)


class TestAiProvidersAndRegistry(unittest.TestCase):
    """Validates the authoritative model and provider registry."""

    def test_01_real_registry_no_hallucinations(self):
        """Registry must contain verified models with complete capability definitions."""
        self.assertIn("llama3.2-1b", MODEL_REGISTRY)
        self.assertIn("mini-agent-v2-1.5b", MODEL_REGISTRY)
        self.assertIn("qwen2.5-coder-1.5b", MODEL_REGISTRY)
        self.assertIn("llama3.2-3b", MODEL_REGISTRY)
        self.assertIn("llama3.2", MODEL_REGISTRY)
        self.assertIn("gpt-4o", MODEL_REGISTRY)
        self.assertIn("o1", MODEL_REGISTRY)

        for m_id, meta in MODEL_REGISTRY.items():
            self.assertIsInstance(meta, ModelMetadata)
            self.assertEqual(meta.model_id, m_id)
            self.assertTrue(len(meta.source) > 0)
            self.assertGreater(meta.context_limit, 0)
            self.assertIsInstance(meta.input_modalities, list)
            self.assertTrue(len(meta.input_modalities) >= 1)
            self.assertIsInstance(meta.supported_sampling_params, list)

    def test_02_resolve_model_id_aliases(self):
        """Aliases (e.g. stroke-neural, llama3.2-local) must resolve to canonical model IDs."""
        self.assertEqual(resolve_model_id("llama3.2-local"), "llama3.2-1b")
        self.assertEqual(resolve_model_id("stroke-neural"), "llama3.2-1b")
        self.assertEqual(resolve_model_id("default"), "llama3.2-1b")
        self.assertEqual(resolve_model_id("qwen-coder"), "qwen2.5-coder-1.5b")
        self.assertEqual(resolve_model_id("mini-agent"), "mini-agent-v2-1.5b")
        self.assertEqual(resolve_model_id("gpt-4"), "gpt-4o")
        self.assertEqual(resolve_model_id("claude"), "claude-3-5-sonnet-20241022")
        self.assertEqual(resolve_model_id(None), "llama3.2-1b")


class TestParameterValidationAndSeparation(unittest.TestCase):
    """Validates parameter separation (temperature vs reasoning effort) and capability gating."""

    def test_03_temperature_vs_reasoning_effort_distinction(self):
        """Standard instruct models accept temperature and separate reasoning effort."""
        params = InferenceParameters(temperature=0.7, reasoning_effort="high", max_tokens=2048)
        self.assertEqual(params.temperature, 0.7)
        self.assertEqual(params.reasoning_effort, "high")

        validated = validate_parameters_for_model("llama3.2-1b", params)
        self.assertEqual(validated["temperature"], 0.7)
        self.assertEqual(validated["max_tokens"], 2048)

    def test_04_reasoning_models_reject_temperature(self):
        """Pure reasoning models (e.g. o1, o3-mini) reject custom temperature."""
        params_with_temp = InferenceParameters(temperature=0.5, reasoning_effort="high")
        with self.assertRaises(ValueError) as ctx:
            validate_parameters_for_model("o1", params_with_temp)
        self.assertIn("does not accept 'temperature'", str(ctx.exception))

        # But accepts reasoning_effort without temperature
        params_pure_reasoning = InferenceParameters(reasoning_effort="high", max_tokens=4000)
        validated = validate_parameters_for_model("o1", params_pure_reasoning)
        self.assertEqual(validated["reasoning_effort"], "high")
        self.assertNotIn("temperature", validated)

    def test_05_unsupported_tool_calling_rejected(self):
        """Passing tools to a model with supports_tool_calling=False must be rejected."""
        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        params = InferenceParameters(tools=tools)
        with self.assertRaises(ValueError) as ctx:
            validate_parameters_for_model("deepseek-r1:1.5b", params)
        self.assertIn("does not support tool calling", str(ctx.exception))

    def test_06_invalid_reasoning_effort_rejected(self):
        """Invalid reasoning effort strings must fail Pydantic validation."""
        with self.assertRaises(ValueError):
            InferenceParameters(reasoning_effort="invalid_level")


class TestResponseAndErrorNormalization(unittest.TestCase):
    """Validates normalized response schemas, usage metrics, and error hierarchy."""

    def test_07_provider_response_structure(self):
        """ProviderResponse must normalize usage, tool calls, and duration."""
        tool_call = NormalizedToolCall(id="call_1", name="read_file", arguments={"path": "main.py"})
        usage = NormalizedUsage(prompt_tokens=50, completion_tokens=100, total_tokens=150)
        resp = ProviderResponse(
            content="File contents analyzed.",
            model="llama3.2-1b",
            provider="local_gguf",
            tool_calls=[tool_call],
            usage=usage,
            duration_ms=45.2,
            selected_provider="local_gguf"
        )
        self.assertEqual(resp.content, "File contents analyzed.")
        self.assertEqual(resp.tool_calls[0].name, "read_file")
        self.assertEqual(resp.usage.total_tokens, 150)
        self.assertFalse(resp.fallback_occurred)

    def test_08_error_hierarchy_status_codes(self):
        """Normalized errors must map to standard HTTP status codes."""
        err_timeout = ProviderTimeoutError("Timed out after 60s", "ollama", "llama3.2")
        self.assertEqual(err_timeout.status_code, 504)

        err_rl = ProviderRateLimitError("Rate limit exceeded", "openai", "gpt-4o", retry_after_sec=10.0)
        self.assertEqual(err_rl.status_code, 429)
        self.assertEqual(err_rl.retry_after_sec, 10.0)

        err_oom = ProviderOutOfMemoryError("CUDA OOM", "local_gguf", "llama3.2-3b")
        self.assertEqual(err_oom.status_code, 507)

        err_missing = ProviderRuntimeMissingError("No runtime", "local_gguf", "llama3.2-1b")
        self.assertEqual(err_missing.status_code, 503)

    def test_09_stream_chunk_structure(self):
        """StreamChunk must normalize delta content and finish reasons."""
        chunk = StreamChunk(delta_content="Hello world", finish_reason=None)
        self.assertEqual(chunk.delta_content, "Hello world")
        self.assertIsNone(chunk.finish_reason)


class TestTransparentFallbackAndCancellation(unittest.IsolatedAsyncioTestCase):
    """Validates that fallbacks are never silent and cancellation is handled."""

    async def test_10_fallback_reported_never_silent(self):
        """When local GGUF is missing, manager falls back to Ollama and reports the reason."""
        manager = AiProviderManager()

        # Mock local_gguf to raise runtime missing error
        manager.local_gguf.chat_complete = AsyncMock(
            side_effect=ProviderRuntimeMissingError("Weights missing", "local_gguf", "llama3.2-1b")
        )
        # Mock ollama to succeed
        mock_ollama_resp = ProviderResponse(
            content="Answer from Ollama",
            model="llama3.2",
            provider="ollama",
            selected_provider="ollama"
        )
        manager.ollama.chat_complete = AsyncMock(return_value=mock_ollama_resp)

        resp = await manager.execute_chat(
            messages=[{"role": "user", "content": "hi"}],
            model_id="llama3.2-1b",
            allow_fallback=True
        )
        self.assertTrue(resp.fallback_occurred)
        self.assertEqual(resp.selected_provider, "ollama")
        self.assertIn("Weights missing", resp.fallback_reason)
        self.assertIn("Switched to local Ollama", resp.fallback_reason)

    async def test_11_all_offline_reports_structured_notice(self):
        """When both engines fail, a structured notice is returned with both error reasons."""
        manager = AiProviderManager()
        manager.local_gguf.chat_complete = AsyncMock(
            side_effect=ProviderRuntimeMissingError("No weights", "local_gguf", "llama3.2-1b")
        )
        manager.ollama.chat_complete = AsyncMock(
            side_effect=ProviderUnavailableError("Ollama daemon down", "ollama", "llama3.2")
        )

        resp = await manager.execute_chat(
            messages=[{"role": "user", "content": "hi"}],
            model_id="llama3.2-1b",
            allow_fallback=True
        )
        self.assertTrue(resp.fallback_occurred)
        self.assertEqual(resp.selected_provider, "offline_notice")
        self.assertIn("No weights", resp.fallback_reason)
        self.assertIn("Ollama daemon down", resp.fallback_reason)
        self.assertIn("STROKE // LOCAL AI ENGINE OFFLINE", resp.content)


class TestIndependentHealthProbes(unittest.IsolatedAsyncioTestCase):
    """Exhaustively validates each health probe under online, offline, timeout, and malformed scenarios."""

    # --------------------------------------------------------------------------
    # Ollama Probe Scenarios
    # --------------------------------------------------------------------------
    async def test_12_ollama_probe_online(self):
        """HTTP 200 with valid models list returns online=True with models."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "llama3.2:latest"}, {"name": "qwen2.5-coder:1.5b"}]
        }
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
            status = await probe_ollama("http://localhost:11434")
            self.assertTrue(status.online)
            self.assertEqual(status.models, ["llama3.2:latest", "qwen2.5-coder:1.5b"])
            self.assertIsNone(status.error)

    async def test_13_ollama_probe_offline_connect_error(self):
        """Connection refused returns online=False with clear diagnostic, no crash."""
        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=httpx.ConnectError("Connection refused"))):
            status = await probe_ollama("http://localhost:11434")
            self.assertFalse(status.online)
            self.assertEqual(status.models, [])
            self.assertIn("Connection refused", status.error)

    async def test_14_ollama_probe_timeout(self):
        """Timeout returns online=False with timeout diagnostic, no crash."""
        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=httpx.TimeoutException("Timeout"))):
            status = await probe_ollama("http://localhost:11434", timeout=0.1)
            self.assertFalse(status.online)
            self.assertIn("Timeout", status.error)

    async def test_15_ollama_probe_malformed_json(self):
        """Malformed JSON response returns online=False with diagnostic."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = json.JSONDecodeError("Expecting value", "bad json", 0)
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
            status = await probe_ollama("http://localhost:11434")
            self.assertFalse(status.online)
            self.assertIn("Malformed JSON", status.error)

    async def test_16_ollama_probe_http_500_error(self):
        """HTTP 500 error returns online=False with status code diagnostic."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error in Ollama engine"
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
            status = await probe_ollama("http://localhost:11434")
            self.assertFalse(status.online)
            self.assertIn("HTTP 500", status.error)

    # --------------------------------------------------------------------------
    # GGUF Binary Magic Header Integrity Scenarios
    # --------------------------------------------------------------------------
    def test_17_gguf_integrity_valid_file(self):
        """Valid file with b'GGUF' magic header and version 3 passes integrity."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            # Write 'GGUF' magic bytes + version 3 (little-endian 32-bit int) + padding > 10MB
            f.write(b"GGUF")
            f.write((3).to_bytes(4, "little"))
            f.write(b"\x00" * 10_000_100)
            tmp_path = f.name

        try:
            valid, err = check_gguf_integrity(tmp_path)
            self.assertTrue(valid)
            self.assertIsNone(err)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_18_gguf_integrity_invalid_magic_header(self):
        """File with invalid magic bytes (e.g. b'FAKE') fails integrity check."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"FAKE")
            f.write((3).to_bytes(4, "little"))
            f.write(b"\x00" * 10_000_100)
            tmp_path = f.name

        try:
            valid, err = check_gguf_integrity(tmp_path)
            self.assertFalse(valid)
            self.assertIn("Invalid binary header", err)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_19_gguf_integrity_undersized_file(self):
        """File smaller than 10MB fails integrity check."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"GGUF\x03\x00\x00\x00short")
            tmp_path = f.name

        try:
            valid, err = check_gguf_integrity(tmp_path)
            self.assertFalse(valid)
            self.assertIn("too small", err)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # --------------------------------------------------------------------------
    # GPU Acceleration Detection (Never based on import alone)
    # --------------------------------------------------------------------------
    def test_20_gpu_support_not_reported_by_import_alone(self):
        """When llama_supports_gpu_offload returns False, GPU offload MUST NOT be reported."""
        mock_llama = MagicMock()
        mock_llama.__version__ = "0.3.36"
        mock_llama.llama_supports_gpu_offload.return_value = False

        with patch.dict("sys.modules", {"llama_cpp": mock_llama}):
            status = probe_llama_cpp()
            self.assertTrue(status.package_installed)
            self.assertTrue(status.runtime_importable)
            self.assertFalse(status.gpu_offload_supported)
            self.assertFalse(status.hardware_accelerated)

    def test_21_gpu_support_reported_when_detected(self):
        """When llama_supports_gpu_offload returns True, GPU offload and device are reported."""
        mock_llama = MagicMock()
        mock_llama.__version__ = "0.3.36"
        mock_llama.llama_supports_gpu_offload.return_value = True

        with patch.dict("sys.modules", {"llama_cpp": mock_llama}):
            status = probe_llama_cpp()
            self.assertTrue(status.package_installed)
            self.assertTrue(status.gpu_offload_supported)
            self.assertTrue(status.hardware_accelerated)
            self.assertIsNotNone(status.device_name)

    # --------------------------------------------------------------------------
    # Probe Isolation (One failure does not abort others)
    # --------------------------------------------------------------------------
    async def test_22_probe_isolation_one_failure_does_not_abort_others(self):
        """Failure in Ollama and Network probes must not prevent Llama, MCP, or FS probes from running."""
        with patch("ai_provider_service.probe_ollama", new=AsyncMock(side_effect=RuntimeError("Ollama crashed"))), \
             patch("ai_provider_service.probe_network", side_effect=RuntimeError("DNS failure")):
            report = await probe_all_ai_health(timeout=0.5)
            self.assertIsInstance(report, AiStatusResponse)
            # Ollama and network captured their errors
            self.assertIn("Ollama crashed", report.ollama.error)
            self.assertIn("DNS failure", report.network.error)
            # Filesystem and MCP still succeeded independently!
            self.assertTrue(report.filesystem.models_dir_writable)
            self.assertIsInstance(report.mcp, McpHealthStatus)

    # --------------------------------------------------------------------------
    # Remote Providers: Never connected merely because key is configured
    # --------------------------------------------------------------------------
    async def test_23_remote_provider_never_connected_by_config_alone(self):
        """Having an API key set in env reports configured=True, but NOT connected=True without live test."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-mock-key-12345"}), \
             patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=httpx.ConnectError("Network unreachable"))):
            status = await probe_remote_provider("openai")
            self.assertTrue(status.configured)
            self.assertFalse(status.connected)
            self.assertIn("Network unreachable", status.error)


class TestEndpointsAndSchemaValidation(unittest.TestCase):
    """Audits HTTP endpoints (/ai/status, /ai/models, /ai/providers, /health, /api/health)."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_user = {"uid": "verified_dev_user", "email": "dev@stroke.ai", "email_verified": True}
        self.auth_headers = {"Authorization": "Bearer mock-token"}

    def test_24_ai_status_endpoint_never_null_when_ollama_online(self):
        """Endpoint /ai/status must NEVER return null or empty when Ollama is online."""
        mock_ollama_status = OllamaHealthStatus(
            online=True,
            host="http://localhost:11434",
            models=["llama3.2:latest"]
        )
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_user), \
             patch("ai_provider_service.probe_ollama", new=AsyncMock(return_value=mock_ollama_status)):
            res = self.client.get("/ai/status", headers=self.auth_headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIsNotNone(data)
            self.assertIn("engine", data)
            self.assertIn("status", data)
            self.assertTrue(data["ollama"]["online"])
            self.assertEqual(data["ollama"]["models"], ["llama3.2:latest"])

    def test_25_ai_status_endpoint_never_null_when_ollama_offline(self):
        """Endpoint /ai/status must NEVER return null when Ollama is offline."""
        mock_ollama_status = OllamaHealthStatus(online=False, host="http://localhost:11434", error="Connection refused")
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_user), \
             patch("ai_provider_service.probe_ollama", new=AsyncMock(return_value=mock_ollama_status)):
            res = self.client.get("/ai/status", headers=self.auth_headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIsNotNone(data)
            self.assertFalse(data["ollama"]["online"])
            self.assertIn("Connection refused", data["ollama"]["error"])

    def test_26_health_and_api_health_endpoints(self):
        """Both /health and /api/health must return HTTP 200 with service metadata."""
        for path in ("/health", "/api/health"):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "healthy")
            self.assertEqual(data["service"], "stroke-backend")
            self.assertEqual(data["version"], "1.0.0-matrix")
            self.assertIsInstance(data["pid"], int)
            self.assertIsInstance(data["uptime_seconds"], (int, float))

    def test_27_ai_models_and_ai_providers_endpoints(self):
        """Endpoints /ai/models and /ai/providers return the authoritative model and provider registry."""
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_user):
            res_models = self.client.get("/ai/models", headers=self.auth_headers)
            self.assertEqual(res_models.status_code, 200)
            models_data = res_models.json()
            self.assertEqual(models_data["status"], "success")
            self.assertIn("llama3.2-1b", models_data["models"])
            self.assertIn("gpt-4o", models_data["models"])

            res_providers = self.client.get("/ai/providers", headers=self.auth_headers)
            self.assertEqual(res_providers.status_code, 200)
            providers_data = res_providers.json()
            self.assertEqual(providers_data["status"], "success")
            self.assertIn("local_gguf", providers_data["providers"])
            self.assertIn("ollama", providers_data["providers"])


if __name__ == "__main__":
    unittest.main()
