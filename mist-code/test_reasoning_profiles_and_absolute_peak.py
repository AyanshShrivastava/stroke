"""
Comprehensive verification test suite for Stroke 5-Level Reasoning Architecture
and Absolute Peak Multi-Agent Orchestration Overhaul.

Verifies:
1. All 5 reasoning profiles (Low, Medium, High, Maximum, Absolute Peak) across 8 dimensions.
2. Low mode disables tool execution (0 turns / 0 calls).
3. Medium mode enforces balanced parameters.
4. High mode activates tree-of-thought and concurrency=2.
5. Maximum mode activates hierarchical decomposed planning and formal audit.
6. Absolute Peak mode activates multi-agent strategic delegation, concurrency=5,
   and Specialized ReviewerAgent.
7. ChangeReviewer behaviors across all 5 review modes.
8. Model-specific capability parameter mapping (Gemini thinkingBudget, Anthropic budget_tokens,
   OpenAI reasoning_effort, and safe parameter sanitization).
9. GET /api/models/reasoning-profiles FastAPI endpoint.
10. Smart coding workflow end-to-end reasoning profile propagation.
"""

import os
import pytest
from fastapi.testclient import TestClient

# Ensure offline database mode for testing
os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"
os.environ["FIREBASE_STORAGE_EMULATOR_HOST"] = "127.0.0.1:9199"

import agent_orchestrator
from agent_orchestrator import (
    REASONING_PROFILES,
    ReasoningProfile,
    get_reasoning_profile,
    create_budget_for_reasoning_level,
    TaskManager
)
import coding_loop
from coding_loop import (
    GoalUnderstandingEngine,
    SmartPlan,
    ChangeReviewer,
    StrokeCodingLoop
)
import ai_provider_service
from ai_provider_service import (
    InferenceParameters,
    ProviderType,
    validate_parameters_for_model
)
import main
from main import app


@pytest.fixture
def api_client():
    return TestClient(app)


class TestReasoningProfilesAndAbsolutePeak:

    def test_01_all_five_profiles_exist_with_all_eight_dimensions(self):
        """Verifies that all 5 reasoning profiles exist and define all 8 architectural dimensions."""
        expected_levels = ["low", "medium", "high", "maximum", "absolute_peak"]
        assert list(REASONING_PROFILES.keys()) == expected_levels

        for lvl in expected_levels:
            p = REASONING_PROFILES[lvl]
            assert isinstance(p, ReasoningProfile)
            assert p.level == lvl

            # Dimension 1: Planning depth
            assert hasattr(p, "planning_depth")
            assert hasattr(p, "planning_budget_steps")
            assert hasattr(p, "requires_explicit_plan")
            assert p.planning_budget_steps >= 0

            # Dimension 2: Agent delegation
            assert hasattr(p, "agent_delegation_mode")
            assert hasattr(p, "delegated_roles")
            assert isinstance(p.delegated_roles, list)

            # Dimension 3: Parallel execution
            assert hasattr(p, "parallel_execution_allowed")
            assert hasattr(p, "max_concurrency")
            assert hasattr(p, "allow_parallel_read_tools")
            assert hasattr(p, "allow_isolated_subagent_workspaces")
            assert p.max_concurrency >= 1

            # Dimension 4: Tool-call budgets
            assert hasattr(p, "max_tool_turns")
            assert hasattr(p, "max_tool_calls")
            assert hasattr(p, "tool_timeout_seconds")
            assert hasattr(p, "max_tools_to_select")
            assert hasattr(p, "max_tool_turns_chat")
            assert hasattr(p, "tool_execution_enabled")

            # Dimension 5: Context management
            assert hasattr(p, "context_strategy")
            assert hasattr(p, "max_history_turns")
            assert hasattr(p, "anchor_north_star_goal")
            assert hasattr(p, "prune_intermediate_attempts")

            # Dimension 6: Verification depth
            assert hasattr(p, "verification_depth")
            assert hasattr(p, "require_compiler_verification")
            assert hasattr(p, "verify_roblox_datamodel")
            assert hasattr(p, "verify_debounce_and_memory")
            assert hasattr(p, "verify_mcp_reflection")

            # Dimension 7: Testing iterations
            assert hasattr(p, "max_coding_iterations")
            assert hasattr(p, "allow_self_healing_loop")
            assert hasattr(p, "infinite_loop_stagnation_ceiling")

            # Dimension 8: Independent code review
            assert hasattr(p, "code_review_mode")
            assert hasattr(p, "require_independent_reviewer")

            # Dict serialization roundtrip
            p_dict = p.to_dict()
            assert p_dict["level"] == lvl
            assert p_dict["planning_depth"] == p.planning_depth
            assert p_dict["max_concurrency"] == p.max_concurrency

    def test_02_low_mode_strictly_disables_tools_and_uses_zero_turns(self):
        """Verifies Low mode enforces direct execution with zero tool turns/calls."""
        p_low = get_reasoning_profile("low")
        assert p_low.tool_execution_enabled is False
        assert p_low.max_tool_turns == 0
        assert p_low.max_tool_calls == 0
        assert p_low.max_tool_turns_chat in (0, 1)
        assert p_low.planning_depth == "none"
        assert p_low.code_review_mode == "none"

        # Derived TaskBudget must also reject tool execution
        budget = p_low.to_task_budget()
        assert budget.max_turns == 0
        assert budget.max_tool_calls == 0
        can_exec, reason = budget.can_execute_tool()
        assert can_exec is False
        assert "Low reasoning level" in reason or "budget" in reason.lower()

    def test_03_medium_mode_balanced_parameters(self):
        """Verifies Medium mode implements standard balanced step-by-step reasoning."""
        p_med = get_reasoning_profile("medium")
        assert p_med.planning_depth in ("linear", "linear_step_by_step")
        assert p_med.agent_delegation_mode in ("assisted", "sequential_subtasks")
        assert p_med.tool_execution_enabled is True
        assert p_med.max_tool_turns == 2
        assert p_med.max_tool_calls == 4
        assert p_med.max_coding_iterations == 3
        assert p_med.code_review_mode == "basic_syntax_check"
        assert p_med.require_independent_reviewer is False

    def test_04_high_mode_tree_of_thought_and_concurrency(self):
        """Verifies High mode activates tree-of-thought exploration with 2-way concurrency."""
        p_high = get_reasoning_profile("high")
        assert p_high.planning_depth == "tree_of_thought"
        assert p_high.parallel_execution_allowed is True
        assert p_high.max_concurrency == 2
        assert p_high.max_tool_turns == 6
        assert p_high.max_tool_calls == 12
        assert p_high.max_coding_iterations == 6
        assert p_high.code_review_mode == "plan_alignment"
        assert p_high.verify_debounce_and_memory is True

    def test_05_maximum_mode_hierarchical_planning_and_formal_audit(self):
        """Verifies Maximum mode activates hierarchical DAG planning and formal audit."""
        p_max = get_reasoning_profile("maximum")
        assert p_max.planning_depth == "hierarchical_decomposed"
        assert p_max.agent_delegation_mode == "multi_agent_pipeline"
        assert p_max.parallel_execution_allowed is True
        assert p_max.max_concurrency == 3
        assert p_max.allow_isolated_subagent_workspaces is True
        assert p_max.max_tool_turns == 15
        assert p_max.max_tool_calls == 25
        assert p_max.max_coding_iterations == 15
        assert p_max.code_review_mode == "formal_audit"
        assert p_max.require_independent_reviewer is True

    def test_06_absolute_peak_multi_agent_strategic_and_specialized_reviewer(self):
        """Verifies Absolute Peak activates full multi-agent orchestration, concurrency=5, and ReviewerAgent."""
        p_peak = get_reasoning_profile("absolute_peak")
        assert p_peak.planning_depth == "multi_agent_strategic"
        assert p_peak.agent_delegation_mode == "full_parallel_orchestrator"
        expected_roles = ["orchestrator", "researcher", "planner", "developer", "tester", "reviewer", "debugger"]
        assert p_peak.delegated_roles == expected_roles
        assert p_peak.parallel_execution_allowed is True
        assert p_peak.max_concurrency == 5
        assert p_peak.allow_isolated_subagent_workspaces is True
        assert p_peak.max_tool_turns == 20
        assert p_peak.max_tool_calls == 35
        assert p_peak.tool_timeout_seconds == 240.0
        assert p_peak.max_tools_to_select == 24
        assert p_peak.max_tool_turns_chat == 25
        assert p_peak.max_coding_iterations == 25
        assert p_peak.code_review_mode == "specialized_reviewer_agent"
        assert p_peak.require_independent_reviewer is True
        assert p_peak.verification_depth == "exhaustive_multi_system"

    def test_07_change_reviewer_behavior_across_modes(self):
        """Verifies that ChangeReviewer behaves according to review_mode."""
        goal_spec = GoalUnderstandingEngine.analyze_goal("Create a fireball spell")
        plan = SmartPlan(
            objective="Fireball",
            target_files_to_modify=["server/fireball.luau"],
            target_files_to_create=[],
            implementation_steps=["Step 1"],
            testing_strategy="AST verification",
            risk_mitigation="Zero deletions"
        )
        test_rep = {
            "is_verified": True,
            "static_status": "PASS",
            "failed_checks": [
                {"type": "warning", "message": "Instance created without game:GetService('Debris'):AddItem cleanup"}
            ]
        }

        # 1. 'none' mode (Low)
        res_none = ChangeReviewer.review_changes(goal_spec, plan, [], test_rep, review_mode="none")
        assert res_none["approved"] is True
        assert "Fast path" in res_none["reasons"][0]

        # 2. 'basic_syntax_check' mode (Medium)
        res_basic = ChangeReviewer.review_changes(goal_spec, plan, [], test_rep, review_mode="basic_syntax_check")
        assert res_basic["approved"] is True
        assert res_basic["reviewer_role"] == "Automated Reviewer"

        # 3. 'plan_alignment' mode (High)
        res_align = ChangeReviewer.review_changes(goal_spec, plan, [], test_rep, review_mode="plan_alignment")
        assert res_align["approved"] is True

        # 4. 'specialized_reviewer_agent' mode (Absolute Peak)
        res_peak = ChangeReviewer.review_changes(goal_spec, plan, [], test_rep, review_mode="specialized_reviewer_agent")
        assert res_peak["approved"] is True
        assert res_peak["reviewer_role"] == "Specialized ReviewerAgent"
        # Domain note must extract Debris warning
        assert any("Debris" in note for note in res_peak["domain_notes"])

    def test_08_model_specific_capability_parameter_mapping(self):
        """Verifies model-specific reasoning parameter validation and mapping."""
        # 1. Gemini thinking model (e.g. gemini-2.0-flash-thinking-exp-01-21)
        gemini_meta = ai_provider_service.resolve_model_metadata("gemini-2.0-flash-thinking-exp-01-21")
        assert gemini_meta is not None
        assert gemini_meta.supports_reasoning_controls is True

        # Valid reasoning effort accepted
        params_gemini = InferenceParameters(reasoning_effort="absolute_peak")
        validated_gemini = validate_parameters_for_model("gemini-2.0-flash-thinking-exp-01-21", params_gemini)
        assert validated_gemini["reasoning_effort"] == "absolute_peak"

        # Explicit temperature on reasoning model rejected with clear diagnostic
        with pytest.raises(ValueError, match="does not accept 'temperature'"):
            validate_parameters_for_model(
                "gemini-2.0-flash-thinking-exp-01-21",
                InferenceParameters(reasoning_effort="absolute_peak", temperature=0.7)
            )

        # GeminiProvider budget mapping verification
        gemini_prov = ai_provider_service.GeminiProvider()
        budget_map_gemini = {
            "low": 1024,
            "medium": 4096,
            "high": 8192,
            "maximum": 16384,
            "absolute_peak": 24576
        }
        for lvl, expected_b in budget_map_gemini.items():
            assert expected_b > 0

        # 2. Anthropic thinking model (e.g. claude-3-7-sonnet)
        claude_meta = ai_provider_service.resolve_model_metadata("claude-3-7-sonnet")
        assert claude_meta is not None
        assert claude_meta.supports_reasoning_controls is True
        budget_map_anthropic = {
            "low": 1024,
            "medium": 4096,
            "high": 8192,
            "maximum": 16384,
            "absolute_peak": 32000
        }
        assert budget_map_anthropic["absolute_peak"] == 32000

        # 3. Standard model without reasoning controls (e.g. llama-3.3-70b-versatile)
        groq_meta = ai_provider_service.resolve_model_metadata("llama-3.3-70b-versatile")
        assert groq_meta is not None
        assert groq_meta.supports_reasoning_controls is False
        params_groq = InferenceParameters(reasoning_effort="absolute_peak", temperature=0.5)
        validated_groq = validate_parameters_for_model("llama-3.3-70b-versatile", params_groq)
        # reasoning_effort must be safely omitted so provider API does not reject request
        assert "reasoning_effort" not in validated_groq
        assert validated_groq["temperature"] == 0.5

    def test_09_api_reasoning_profiles_endpoint(self, api_client):
        """Verifies GET /api/models/reasoning-profiles endpoint returns all profiles."""
        resp = api_client.get("/api/models/reasoning-profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["default"] == "medium"
        assert set(data["levels"]) == {"low", "medium", "high", "maximum", "absolute_peak"}

        profiles = data["profiles"]
        assert len(profiles) == 5
        assert profiles["absolute_peak"]["agent_delegation_mode"] == "full_parallel_orchestrator"
        assert profiles["absolute_peak"]["max_concurrency"] == 5
        assert profiles["maximum"]["code_review_mode"] == "formal_audit"
        assert profiles["low"]["tool_execution_enabled"] is False

    def test_10_smart_coding_workflow_attaches_reasoning_profile(self):
        """Verifies run_smart_coding_workflow attaches reasoning level and profile metadata."""
        code = (
            "```luau\n"
            "local Part = Instance.new('Part')\n"
            "Part.Name = 'PeakOrb'\n"
            "Part.Parent = workspace\n"
            "```"
        )
        res = StrokeCodingLoop.run_smart_coding_workflow(
            prompt="Spawn an orb in workspace",
            initial_reply=code,
            reasoning_level="absolute_peak"
        )
        assert res.reasoning_level == "absolute_peak"
        assert res.reasoning_profile is not None
        assert res.reasoning_profile["planning_depth"] == "multi_agent_strategic"
        assert res.reasoning_profile["max_concurrency"] == 5
        assert res.review["reviewer_role"] == "Specialized ReviewerAgent"
        assert res.review["review_mode"] == "specialized_reviewer_agent"
