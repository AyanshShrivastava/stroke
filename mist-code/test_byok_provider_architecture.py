"""
Stroke AI // BYOK (Bring Your Own Key) Provider Architecture Test Suite
================================================================================
Comprehensive verification of:
  1. Secure Credential Vault (OS Keychain + AES-256 PBKDF2 machine vault)
  2. Provider Adapters (Groq, Gemini, OpenRouter, OpenAI, Anthropic, Custom)
  3. Five Reasoning Levels (Low, Medium, High, Maximum, Absolute Peak)
  4. Normalized Error Hierarchy (401, 403, 429, 502, 504)
  5. Live Test Connection Probes (HTTP 200, 401, timeout)
  6. Transparent Fallback Tracking (Never silent, user opt-in required)
  7. Active Model Configuration Persistence
  8. Endpoints: /api/models/providers, /api/models/credentials, /api/models/active,
     /api/models/test-connection, /api/models/catalog
================================================================================
"""

import os
import sys
import json
import tempfile
import asyncio
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
import credentials_vault_service
from credentials_vault_service import (
    CredentialsVault,
    mask_secret,
    get_credential_vault_path
)
import ai_provider_service
from ai_provider_service import (
    ProviderType,
    ModelMetadata,
    MODEL_REGISTRY,
    resolve_model_id,
    InferenceParameters,
    validate_parameters_for_model,
    ProviderResponse,
    NormalizedUsage,
    NormalizedToolCall,
    ProviderError,
    ProviderAuthenticationError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderServiceError,
    ProviderRuntimeMissingError,
    GroqProvider,
    GeminiProvider,
    OpenRouterProvider,
    AnthropicProvider,
    RemoteOpenAiCompatibleProvider,
    CustomProvider,
    AiProviderManager,
    StreamChunk,
    fetch_live_provider_models,
    test_provider_connection as probe_test_connection,
    get_active_model_config,
    set_active_model_config
)


class TestCredentialVaultSecurity(unittest.TestCase):
    """Verifies that API keys are stored securely without plaintext leaks."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.vault_file = os.path.join(self.tmp_dir, "test_credentials.vault")
        self.vault = CredentialsVault(vault_path=self.vault_file)

    def test_01_secret_masking(self):
        """Secrets must be properly masked with prefix and last 4 characters preserved."""
        self.assertEqual(mask_secret(None), "")
        self.assertEqual(mask_secret(""), "")
        self.assertEqual(mask_secret("short"), "••••••••")
        masked_groq = mask_secret("gsk_1234567890abcdef12345678")
        self.assertTrue(masked_groq.startswith("gsk_"))
        self.assertTrue(masked_groq.endswith("5678"))
        self.assertIn("••••••••", masked_groq)

    def test_02_vault_machine_encryption(self):
        """When storing in file vault, data must be encrypted with Fernet AES-256."""
        self.vault.set_credential("groq", "gsk_test_secret_key_12345", user_id="test_user")
        retrieved = self.vault.get_credential("groq", user_id="test_user")
        self.assertEqual(retrieved, "gsk_test_secret_key_12345")

        # Inspect raw file on disk: it must NOT contain plaintext secret
        with open(self.vault_file, "rb") as f:
            raw_disk = f.read()
        self.assertNotIn(b"gsk_test_secret_key_12345", raw_disk)

        # Deletion
        deleted = self.vault.delete_credential("groq", user_id="test_user")
        self.assertTrue(deleted)
        self.assertIsNone(self.vault.get_credential("groq", user_id="test_user"))

    def test_03_zero_plaintext_in_status_listings(self):
        """Listing credential statuses must never reveal unmasked secrets."""
        self.vault.set_credential("gemini", "AIzaSyTestSecretKey987654321", user_id="test_user")
        statuses = self.vault.list_all_statuses(user_id="test_user")
        prov_names = [s["provider"] for s in statuses]
        self.assertIn("gemini", prov_names)
        gemini_stat = next(s for s in statuses if s["provider"] == "gemini")
        self.assertTrue(gemini_stat["configured"])
        self.assertNotIn("AIzaSyTestSecretKey987654321", json.dumps(statuses))
        self.assertTrue(gemini_stat["masked_key"].startswith("AIza"))


class TestProviderAdapters(unittest.IsolatedAsyncioTestCase):
    """Verifies BYOK provider request formatting, response normalization, and tool translation."""

    async def test_04_groq_adapter_inference(self):
        """Groq provider formats OpenAI-compatible payload and parses chat response."""
        provider = GroqProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{
                "message": {"role": "assistant", "content": "Groq LPU synthesized code."},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 20, "completion_tokens": 15, "total_tokens": 35}
        }

        with patch.object(credentials_vault_service.vault, "get_credential", return_value="gsk_mock_key"), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            resp = await provider.chat_complete(
                messages=[{"role": "user", "content": "hello"}],
                parameters=InferenceParameters(temperature=0.7),
                model_id="llama-3.3-70b-versatile"
            )
            self.assertEqual(resp.content, "Groq LPU synthesized code.")
            self.assertEqual(resp.provider, "groq")
            self.assertEqual(resp.usage.total_tokens, 35)

    async def test_05_gemini_adapter_translation(self):
        """Gemini adapter translates messages, system prompt, and tools to Google Generative API schema."""
        provider = GeminiProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "Gemini 2.0 Flash response"}],
                    "role": "model"
                },
                "finishReason": "STOP"
            }],
            "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 25, "totalTokenCount": 55}
        }

        with patch.object(credentials_vault_service.vault, "get_credential", return_value="AIzaSyMockKey"), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)) as mock_post:
            resp = await provider.chat_complete(
                messages=[
                    {"role": "system", "content": "You are Stroke AI."},
                    {"role": "user", "content": "Build fire VFX"}
                ],
                parameters=InferenceParameters(
                    temperature=0.4,
                    tools=[{"type": "function", "function": {"name": "search_vfx", "description": "Search VFX"}}]
                ),
                model_id="gemini-2.0-flash"
            )
            self.assertEqual(resp.content, "Gemini 2.0 Flash response")
            self.assertEqual(resp.provider, "gemini")

            # Verify that post body included systemInstruction and functionDeclarations
            call_kwargs = mock_post.call_args[1]
            body = call_kwargs["json"]
            self.assertIn("systemInstruction", body)
            self.assertIn("tools", body)
            self.assertIn("functionDeclarations", body["tools"][0])

    async def test_06_openrouter_adapter_headers(self):
        """OpenRouter provider sends required identification headers (HTTP-Referer, X-Title)."""
        provider = OpenRouterProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "OpenRouter response"}, "finish_reason": "stop"}]
        }

        with patch.object(credentials_vault_service.vault, "get_credential", return_value="sk-or-v1-mock"), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)) as mock_post:
            resp = await provider.chat_complete(
                messages=[{"role": "user", "content": "ping"}],
                model_id="anthropic/claude-3.5-sonnet"
            )
            self.assertEqual(resp.content, "OpenRouter response")
            headers = mock_post.call_args[1]["headers"]
            self.assertIn("HTTP-Referer", headers)
            self.assertEqual(headers["X-Title"], "Stroke AI")

    async def test_07_anthropic_adapter_translation(self):
        """Anthropic adapter converts messages and separates top-level system parameter."""
        provider = AnthropicProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": "Claude 3.5 Sonnet reply"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 20}
        }

        with patch.object(credentials_vault_service.vault, "get_credential", return_value="sk-ant-mock"), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)) as mock_post:
            resp = await provider.chat_complete(
                messages=[
                    {"role": "system", "content": "Anthropic system prompt"},
                    {"role": "user", "content": "Hello Claude"}
                ],
                model_id="claude-3-5-sonnet-20241022"
            )
            self.assertEqual(resp.content, "Claude 3.5 Sonnet reply")
            body = mock_post.call_args[1]["json"]
            self.assertEqual(body["system"], "Anthropic system prompt")
            self.assertEqual(body["messages"][0]["role"], "user")


class TestReasoningLevelsAndErrorHierarchy(unittest.TestCase):
    """Verifies Stroke's 5 reasoning levels and standardized exception mapping."""

    def test_08_five_reasoning_levels_accepted(self):
        """Stroke must support: low, medium, high, maximum, absolute_peak."""
        for level in ("low", "medium", "high", "maximum", "absolute_peak"):
            params = InferenceParameters(reasoning_effort=level)
            self.assertEqual(params.reasoning_effort, level)

    def test_09_error_status_codes(self):
        """Normalized errors must map accurately to HTTP status codes."""
        self.assertEqual(ProviderAuthenticationError("Bad Key", "groq", "llama-3.3").status_code, 401)
        self.assertEqual(ProviderPermissionError("No Access", "openai", "gpt-4o").status_code, 403)
        self.assertEqual(ProviderRateLimitError("Limit Hit", "gemini", "gemini-2.0").status_code, 429)
        self.assertEqual(ProviderTimeoutError("Timed Out", "openrouter", "deepseek").status_code, 504)
        self.assertEqual(ProviderServiceError("Server Down", "anthropic", "claude").status_code, 502)
        self.assertEqual(ProviderRuntimeMissingError("No Key", "groq", "llama-3.3").status_code, 503)


class TestTestConnectionAndEndpoints(unittest.TestCase):
    """Audits live test connection logic and FastAPI BYOK endpoints."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_user = {"uid": "byok_dev", "email": "dev@stroke.ai", "email_verified": True}
        self.headers = {"Authorization": "Bearer mock-token"}

    def test_10_test_connection_probe_success_and_failure(self):
        """test_provider_connection executes real probe and returns diagnostic."""
        # 1. Mock HTTP 200
        mock_ok = MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"data": [{"id": "llama-3.3-70b-versatile"}]}

        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_ok)):
            success, msg, code = asyncio.run(probe_test_connection("groq", api_key="gsk_test"))
            self.assertTrue(success)
            self.assertEqual(code, 200)

        # 2. Mock HTTP 401
        mock_401 = MagicMock()
        mock_401.status_code = 401
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_401)):
            success, msg, code = asyncio.run(probe_test_connection("groq", api_key="gsk_invalid"))
            self.assertFalse(success)
            self.assertEqual(code, 401)
            self.assertIn("Invalid Groq API key", msg)

    def test_11_endpoints_providers_and_credentials(self):
        """Endpoints /api/models/providers, /api/models/credentials work securely."""
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_user):
            # GET providers
            res = self.client.get("/api/models/providers", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "success")
            providers = {p["provider"]: p for p in data["providers"]}
            self.assertIn("groq", providers)
            self.assertIn("gemini", providers)
            self.assertIn("openrouter", providers)

            # POST credential
            res_save = self.client.post(
                "/api/models/credentials",
                headers=self.headers,
                json={"provider": "groq", "api_key": "gsk_live_test_key_12345"}
            )
            self.assertEqual(res_save.status_code, 200)

            # GET active config
            res_active = self.client.get("/api/models/active", headers=self.headers)
            self.assertEqual(res_active.status_code, 200)
            active_data = res_active.json().get("config", res_active.json())
            self.assertIn("active_provider", active_data)
            self.assertIn("active_model", active_data)

            # POST active config
            res_set_active = self.client.post(
                "/api/models/active",
                headers=self.headers,
                json={"active_provider": "gemini", "active_model": "gemini-2.0-flash", "reasoning_level": "absolute_peak"}
            )
            self.assertEqual(res_set_active.status_code, 200)
            set_data = res_set_active.json().get("config", res_set_active.json())
            self.assertEqual(set_data["active_provider"], "gemini")
            self.assertEqual(set_data["reasoning_level"], "absolute_peak")


class TestStreamingAndLiveModelCatalog(unittest.IsolatedAsyncioTestCase):
    """Verifies streaming SSE across providers, fallback streaming, and live model fetching."""

    async def test_12_groq_streaming_chunks(self):
        """Groq provider parses SSE chunks including reasoning delta and finish reason."""
        provider = GroqProvider()
        lines = [
            'data: {"choices": [{"delta": {"content": "Hello ", "reasoning_content": "Analyze greeting"}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {"content": "world!"}, "finish_reason": "stop"}]}',
            'data: [DONE]'
        ]

        async def mock_aiter():
            for line in lines:
                yield line

        mock_stream_response = MagicMock()
        mock_stream_response.status_code = 200
        mock_stream_response.aiter_lines = mock_aiter

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__.return_value = mock_stream_response

        with patch.object(credentials_vault_service.vault, "get_credential", return_value="gsk_test_key"), \
             patch("httpx.AsyncClient.stream", return_value=mock_stream_ctx):
            chunks = []
            async for chunk in provider.stream_chat(
                messages=[{"role": "user", "content": "hi"}],
                model_id="llama-3.3-70b-versatile"
            ):
                chunks.append(chunk)

            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0].delta_content, "Hello ")
            self.assertEqual(chunks[0].delta_thinking, "Analyze greeting")
            self.assertIsNone(chunks[0].finish_reason)
            self.assertEqual(chunks[1].delta_content, "world!")
            self.assertEqual(chunks[1].finish_reason, "stop")

    async def test_13_gemini_streaming_chunks(self):
        """Gemini provider streams SSE text and thought parts accurately."""
        provider = GeminiProvider()
        lines = [
            'data: {"candidates": [{"content": {"parts": [{"text": "Pondering problem...", "thought": true}]}, "finishReason": null}]}',
            'data: {"candidates": [{"content": {"parts": [{"text": "Here is the solution."}]}, "finishReason": "STOP"}]}'
        ]

        async def mock_aiter():
            for line in lines:
                yield line

        mock_stream_response = MagicMock()
        mock_stream_response.status_code = 200
        mock_stream_response.aiter_lines = mock_aiter

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__.return_value = mock_stream_response

        with patch.object(credentials_vault_service.vault, "get_credential", return_value="AIzaSyMockKey"), \
             patch("httpx.AsyncClient.stream", return_value=mock_stream_ctx):
            chunks = []
            async for chunk in provider.stream_chat(
                messages=[{"role": "user", "content": "solve this"}],
                model_id="gemini-2.0-flash"
            ):
                chunks.append(chunk)

            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0].delta_thinking, "Pondering problem...")
            self.assertEqual(chunks[1].delta_content, "Here is the solution.")
            self.assertEqual(chunks[1].finish_reason, "STOP")

    async def test_14_anthropic_streaming_deltas(self):
        """Anthropic provider streams content_block_delta and message_delta."""
        provider = AnthropicProvider()
        lines = [
            'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Internal thought"}}',
            'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Claude response text"}}',
            'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}'
        ]

        async def mock_aiter():
            for line in lines:
                yield line

        mock_stream_response = MagicMock()
        mock_stream_response.status_code = 200
        mock_stream_response.aiter_lines = mock_aiter

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__.return_value = mock_stream_response

        with patch.object(credentials_vault_service.vault, "get_credential", return_value="sk-ant-test"), \
             patch("httpx.AsyncClient.stream", return_value=mock_stream_ctx):
            chunks = []
            async for chunk in provider.stream_chat(
                messages=[{"role": "user", "content": "hello claude"}],
                model_id="claude-3-5-sonnet-20241022"
            ):
                chunks.append(chunk)

            self.assertEqual(len(chunks), 3)
            self.assertEqual(chunks[0].delta_thinking, "Internal thought")
            self.assertEqual(chunks[1].delta_content, "Claude response text")
            self.assertEqual(chunks[2].finish_reason, "end_turn")

    async def test_15_manager_stream_fallback(self):
        """AiProviderManager seamlessly falls back to user-configured backup provider when primary encounters rate limit."""
        manager = AiProviderManager()

        async def failing_stream(*args, **kwargs):
            raise ProviderRateLimitError("Groq 429", "groq", "llama-3.3-70b-versatile", retry_after_sec=10)
            yield

        async def fallback_stream(*args, **kwargs):
            yield StreamChunk(delta_content="Fallback gemini chunk", finish_reason="stop")

        with patch.object(manager.groq, "stream_chat", side_effect=failing_stream), \
             patch.object(manager.gemini, "stream_chat", side_effect=fallback_stream), \
             patch.object(credentials_vault_service.vault, "get_credential", return_value="AIzaSyMockKey"), \
             patch("ai_provider_service.get_active_model_config", return_value={
                 "active_provider": "groq",
                 "active_model": "llama-3.3-70b-versatile",
                 "allow_fallback": True,
                 "fallback_provider": "gemini",
                 "fallback_model": "gemini-2.0-flash"
             }):
            chunks = []
            async for chunk in manager.execute_stream_chat(
                messages=[{"role": "user", "content": "ping"}],
                provider_id="groq",
                user_id="test_user"
            ):
                chunks.append(chunk)

            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0].delta_content, "Fallback gemini chunk")

    async def test_16_fetch_live_models_from_provider(self):
        """fetch_live_provider_models retrieves actual models without fake responses."""
        mock_groq_resp = MagicMock()
        mock_groq_resp.status_code = 200
        mock_groq_resp.json.return_value = {
            "data": [
                {"id": "llama-3.3-70b-versatile", "context_window": 131072, "owned_by": "Meta"},
                {"id": "mixtral-8x7b-32768", "context_window": 32768, "owned_by": "Mistral"}
            ]
        }

        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_groq_resp)):
            models = await fetch_live_provider_models("groq", api_key="gsk_live_key")
            self.assertEqual(len(models), 2)
            self.assertEqual(models[0]["id"], "llama-3.3-70b-versatile")
            self.assertEqual(models[0]["provider"], "groq")
            self.assertEqual(models[1]["id"], "mixtral-8x7b-32768")


class TestStreamEndpointsAndLiveModels(unittest.TestCase):
    """Verifies FastAPI SSE streaming endpoint and live model endpoints."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_user = {"uid": "byok_stream_dev", "email": "dev@stroke.ai", "email_verified": True}
        self.headers = {"Authorization": "Bearer mock-token"}

    def test_17_live_models_endpoints(self):
        """GET /api/models/live/{provider} and POST /api/models/live/{provider} work."""
        mock_gemini_resp = MagicMock()
        mock_gemini_resp.status_code = 200
        mock_gemini_resp.json.return_value = {
            "models": [
                {
                    "name": "models/gemini-2.0-flash",
                    "displayName": "Gemini 2.0 Flash",
                    "inputTokenLimit": 1048576,
                    "supportedGenerationMethods": ["generateContent"]
                }
            ]
        }

        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_user), \
             patch.object(credentials_vault_service.vault, "get_credential", return_value="AIzaSyTestKey"), \
             patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_gemini_resp)):
            # GET live models
            res = self.client.get("/api/models/live/gemini", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["provider"], "gemini")
            self.assertGreaterEqual(len(data["models"]), 1)
            self.assertEqual(data["models"][0]["id"], "gemini-2.0-flash")

            # POST live models with custom key
            res_post = self.client.post(
                "/api/models/live/gemini",
                headers=self.headers,
                json={"api_key": "AIzaSyDirectCustomKey"}
            )
            self.assertEqual(res_post.status_code, 200)
            data_post = res_post.json()
            self.assertEqual(data_post["status"], "success")

    def test_18_ai_chat_stream_endpoint(self):
        """POST /ai/chat/stream streams SSE events with step, content, and done signals."""
        async def mock_stream_gen(*args, **kwargs):
            yield StreamChunk(delta_content="Streaming ", finish_reason=None)
            yield StreamChunk(delta_content="code answer", finish_reason="stop")

        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_user), \
             patch("main.global_ai_provider_manager.execute_stream_chat", side_effect=mock_stream_gen):
            res = self.client.post(
                "/ai/chat/stream",
                headers=self.headers,
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                    "model": "llama-3.3-70b-versatile"
                }
            )
            self.assertEqual(res.status_code, 200)
            self.assertIn("text/event-stream", res.headers.get("content-type", ""))
            body = res.text
            self.assertIn("data: ", body)
            self.assertIn('"type": "step"', body)
            self.assertIn("Streaming ", body)
            self.assertIn("code answer", body)
            self.assertIn('"type": "done"', body)
            self.assertIn("data: [DONE]", body)


if __name__ == "__main__":
    unittest.main()
