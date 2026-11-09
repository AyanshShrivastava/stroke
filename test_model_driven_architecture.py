"""
test_model_driven_architecture.py
=============================================================================
Comprehensive Regression Test Suite for Stroke Model-Driven Architecture:
1. Greetings receive natural model-generated text, not canned strings.
2. "Explain how to build a house in Roblox" does NOT invoke studio_execute_luau.
3. "Build a house in Studio" invokes studio_execute_luau with model-generated code.
4. "What is a hitbox?" does NOT execute code.
5. "Create a purple lightning VFX" produces adapted code, not a canned template.
6. Asking how GitHub commits work does NOT call github_commit_file.
7. Direct request to commit requires confirmation (status: 'requires_confirmation').
8. Semantic VFX query retrieves relevant records even with unfamiliar wording ("crackling violet sparks").
9. Ineffective debounce (local debounce = true without guard or mutation) fails verification with 'Ineffective Debounce Logic'.
10. All reasoning levels (low, medium, high, maximum, absolute_peak) function properly.
=============================================================================
"""

import unittest
import asyncio
import json
from unittest.mock import patch, AsyncMock

import main
import vfx_service
from coding_loop import RobloxDomainTestRunner
from terminal_service import ToolDispatcher


class TestModelDrivenArchitecture(unittest.IsolatedAsyncioTestCase):

    def test_01_greetings_not_canned(self):
        """Verify casual greetings receive model-generated text, NOT canned strings."""
        canned_greeting_substring = "I am Stroke, your local Roblox game development, 3D visual effects, and Luau engineering AI."
        canned_identity_substring = "I am Stroke, an autonomous Roblox game development, 3D visual effects (VFX)"

        self.assertFalse(hasattr(main, "is_casual_greeting"), "is_casual_greeting must not exist")
        self.assertFalse(hasattr(main, "is_identity_query"), "is_identity_query must not exist")

        mock_completion = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Hey! How can I assist you with your Roblox project today?"
                }
            }]
        }

        with patch("main.run_llama_inference", new=AsyncMock(return_value=mock_completion)):
            payload = main.AiChatRequest(
                messages=[main.ChatMessage(role="user", content="hello!")]
            )
            response = asyncio.run(main.chat_with_neural_ai(payload))
            reply = response.get("message", "") if isinstance(response, dict) else getattr(response, "message", "")
            self.assertEqual(reply, "Hey! How can I assist you with your Roblox project today?")
            self.assertNotIn(canned_greeting_substring, reply)
            self.assertNotIn(canned_identity_substring, reply)

    async def test_02_explain_how_to_build_house_does_not_execute_studio(self):
        """Verify 'Explain how to build a house in Roblox' does NOT invoke studio_execute_luau."""
        mock_completion = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "To build a house in Roblox, start by creating a foundation Part in Workspace, anchoring it, and adding walls..."
                }
            }]
        }

        dispatched_tools = []

        async def fake_dispatch(tool_name, args=None):
            dispatched_tools.append(tool_name)
            return {"status": "success"}

        with patch("main.run_llama_inference", new=AsyncMock(return_value=mock_completion)), \
             patch.object(ToolDispatcher, "dispatch_async", side_effect=fake_dispatch):
            payload = main.AiChatRequest(
                messages=[main.ChatMessage(role="user", content="Explain how to build a house in Roblox")]
            )
            response = await main.chat_with_neural_ai(payload)
            tool_invoked = response.get("tool_invoked") if isinstance(response, dict) else response.tool_invoked
            reply = response.get("message", "") if isinstance(response, dict) else getattr(response, "message", "")
            self.assertNotIn("studio_execute_luau", dispatched_tools)
            self.assertFalse(tool_invoked)
            self.assertIn("To build a house in Roblox", reply)

    async def test_03_build_house_in_studio_calls_studio_execute_with_model_code(self):
        """Verify 'Build a house in Studio' invokes studio_execute_luau with custom model-generated code."""
        custom_model_code = (
            "local houseModel = Instance.new('Model')\n"
            "houseModel.Name = 'CustomPlayerHouse'\n"
            "houseModel.Parent = workspace\n"
            "return 'House built'"
        )

        # Turn 1: Model calls studio_execute_luau with custom code
        completion_turn_1 = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "studio_execute_luau",
                            "arguments": json.dumps({"code": custom_model_code, "target_parent": "workspace"})
                        }
                    }]
                }
            }]
        }
        # Turn 2: Model synthesizes final response incorporating tool output
        completion_turn_2 = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "I have deployed your CustomPlayerHouse model directly into Workspace."
                }
            }]
        }

        mock_inference = AsyncMock(side_effect=[completion_turn_1, completion_turn_2])
        dispatched_calls = []

        async def fake_dispatch(tool_name, args=None):
            dispatched_calls.append({"tool": tool_name, "args": args})
            return {"status": "success", "message": "Successfully executed script in Roblox Studio."}

        with patch("main.run_llama_inference", new=mock_inference), \
             patch.object(ToolDispatcher, "dispatch_async", side_effect=fake_dispatch):
            payload = main.AiChatRequest(
                messages=[main.ChatMessage(role="user", content="Build a house in Studio")]
            )
            response = await main.chat_with_neural_ai(payload)
            reply = response.get("message", "") if isinstance(response, dict) else getattr(response, "message", "")
            self.assertEqual(len(dispatched_calls), 1)
            self.assertEqual(dispatched_calls[0]["tool"], "studio_execute_luau")
            self.assertEqual(dispatched_calls[0]["args"]["code"], custom_model_code)
            self.assertIn("CustomPlayerHouse", reply)

    async def test_04_what_is_a_hitbox_does_not_execute_code(self):
        """Verify 'What is a hitbox?' is treated conversationally and does not execute tools or code."""
        mock_completion = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "A hitbox is an invisible geometric volume (like a Part or bounding box) used in game development to detect collisions and damage."
                }
            }]
        }

        dispatched_tools = []

        async def fake_dispatch(tool_name, args=None):
            dispatched_tools.append(tool_name)
            return {"status": "success"}

        with patch("main.run_llama_inference", new=AsyncMock(return_value=mock_completion)), \
             patch.object(ToolDispatcher, "dispatch_async", side_effect=fake_dispatch):
            payload = main.AiChatRequest(
                messages=[main.ChatMessage(role="user", content="What is a hitbox?")]
            )
            response = await main.chat_with_neural_ai(payload)
            tool_invoked = response.get("tool_invoked") if isinstance(response, dict) else response.tool_invoked
            reply = response.get("message", "") if isinstance(response, dict) else getattr(response, "message", "")
            self.assertEqual(len(dispatched_tools), 0)
            self.assertFalse(tool_invoked)
            self.assertIn("invisible geometric volume", reply)

    async def test_05_create_purple_lightning_vfx_custom_code(self):
        """Verify 'Create a purple lightning VFX' generates custom adapted code, not a canned template."""
        custom_vfx_luau = (
            "```luau\n"
            "-- Purple Lightning Custom Emitter\n"
            "local host = Instance.new('Part')\n"
            "host.Name = 'PurpleLightningHost'\n"
            "host.Anchored = true\n"
            "host.Parent = workspace\n\n"
            "local emitter = Instance.new('ParticleEmitter')\n"
            "emitter.Rate = 45\n"
            "emitter.Color = ColorSequence.new(Color3.fromRGB(180, 0, 255))\n"
            "emitter.Lifetime = NumberRange.new(0.2, 0.5)\n"
            "emitter.Speed = NumberRange.new(10, 20)\n"
            "emitter.SpreadAngle = Vector2.new(180, 180)\n"
            "emitter.Parent = host\n"
            "```"
        )
        mock_completion = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": f"Here is the custom purple lightning VFX:\n\n{custom_vfx_luau}"
                }
            }]
        }

        with patch("main.run_llama_inference", new=AsyncMock(return_value=mock_completion)):
            payload = main.AiChatRequest(
                messages=[main.ChatMessage(role="user", content="Create a purple lightning VFX")]
            )
            response = await main.chat_with_neural_ai(payload)
            reply = response.get("message", "") if isinstance(response, dict) else getattr(response, "message", "")
            self.assertIn("PurpleLightningHost", reply)
            self.assertIn("Color3.fromRGB(180, 0, 255)", reply)
            # Ensure it is not the old canned ModularHouse
            self.assertNotIn("ModularHouse", reply)

    async def test_06_explain_github_commits_does_not_commit(self):
        """Verify asking how GitHub commits work does NOT call github_commit_file."""
        mock_completion = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "A GitHub commit is a cryptographic snapshot of changes staged in a Git repository."
                }
            }]
        }

        dispatched_tools = []

        async def fake_dispatch(tool_name, args=None):
            dispatched_tools.append(tool_name)
            return {"status": "success"}

        with patch("main.run_llama_inference", new=AsyncMock(return_value=mock_completion)), \
             patch.object(ToolDispatcher, "dispatch_async", side_effect=fake_dispatch):
            payload = main.AiChatRequest(
                messages=[main.ChatMessage(role="user", content="How do GitHub commits work?")]
            )
            response = await main.chat_with_neural_ai(payload)
            reply = response.get("message", "") if isinstance(response, dict) else getattr(response, "message", "")
            self.assertNotIn("github_commit_file", dispatched_tools)
            self.assertIn("snapshot of changes", reply)

    async def test_07_github_commit_requires_confirmation(self):
        """Verify direct request to commit without explicit confirmation returns requires_confirmation."""
        res_unconfirmed = await ToolDispatcher.dispatch_async("github_commit_file", {
            "repo": "AyanshShrivastava/stroke",
            "path": "src/test.luau",
            "content": "-- test content",
            "commit_message": "test commit"
        })
        self.assertEqual(res_unconfirmed.get("status"), "requires_confirmation")
        self.assertTrue(res_unconfirmed.get("requires_confirmation"))
        self.assertIn("Confirmation Required", res_unconfirmed.get("message", ""))

    def test_08_semantic_vfx_retrieval_unfamiliar_wording(self):
        """Verify semantic VFX query retrieves relevant records even with unfamiliar wording ('crackling violet sparks')."""
        matches = vfx_service.search_vfx_database("crackling violet sparks", max_results=3)
        self.assertIsInstance(matches, list)
        self.assertGreater(len(matches), 0, "Semantic retrieval must find matching presets for violet/sparks concepts")
        matched_names = [m.get("model_name", "") for m in matches]
        has_relevant = any("Purple" in n or "Electro" in n or "Slash" in n or "Spark" in n for n in matched_names)
        self.assertTrue(has_relevant, f"Matches {matched_names} should contain semantic matches for violet sparks")

    def test_09_ineffective_debounce_fails_verification(self):
        """Verify ineffective debounce (local debounce = true without guard or mutation) fails verification."""
        broken_debounce_code = """
        local function executeHitbox(character)
            local root = character:FindFirstChild("HumanoidRootPart")
            if not root then return end

            local debounce = true -- Table/flag declared but NEVER checked in an if condition and never mutated!

            local parts = workspace:GetPartBoundsInBox(root.CFrame, Vector3.new(4, 4, 4))
            for _, part in ipairs(parts) do
                local model = part:FindFirstAncestorOfClass("Model")
                if model then
                    local hum = model:FindFirstChildOfClass("Humanoid")
                    if hum then
                        hum:TakeDamage(15)
                    end
                end
            end
        end
        """
        report = RobloxDomainTestRunner.test_luau_code(broken_debounce_code, prompt="create hitbox")
        self.assertFalse(report.get("is_verified", False), "Ineffective debounce must fail spatial hitbox verification")
        has_ineffective_debounce_error = any(
            "Ineffective Debounce Logic" in (f.get("message", "") if isinstance(f, dict) else str(f))
            for f in report.get("failed_checks", [])
        )
        self.assertTrue(has_ineffective_debounce_error, f"Expected Ineffective Debounce error in {report.get('failed_checks')}")

    async def test_10_all_reasoning_levels_configure_properly(self):
        """Verify low, medium, high, maximum, and absolute_peak reasoning levels function properly."""
        levels = ["low", "medium", "high", "maximum", "absolute_peak"]

        for lvl in levels:
            captured_system = []

            async def capture_inference(engine, **kwargs):
                messages = kwargs.get("messages", [])
                if messages and messages[0].get("role") == "system":
                    captured_system.append(messages[0].get("content", ""))
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": f"Reasoning level {lvl} verified."
                        }
                    }]
                }

            with patch("main.run_llama_inference", new=capture_inference):
                payload = main.AiChatRequest(
                    messages=[main.ChatMessage(role="user", content="Test reasoning")],
                    reasoning_level=lvl
                )
                response = await main.chat_with_neural_ai(payload)
                reply = response.get("message", "") if isinstance(response, dict) else getattr(response, "message", "")
                self.assertIn(f"Reasoning level {lvl} verified.", reply)
                self.assertTrue(len(captured_system) > 0)
                sys_content = captured_system[0]
                self.assertIn(lvl.upper().replace("_", " "), sys_content.upper())


if __name__ == "__main__":
    unittest.main()
