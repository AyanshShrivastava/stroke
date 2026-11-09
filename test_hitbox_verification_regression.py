"""
Regression test suite for Roblox Luau spatial hitbox verification.
Validates that Stroke accurately detects all 8 fatal runtime/API errors,
refuses to award false passes (debounce, caster filter, spatial query, memory profile),
and verifies clean production Luau scripts truthfully.
"""

import unittest
from coding_loop import LuauSyntaxValidator, RobloxDomainTestRunner, StrokeCodingLoop


class TestHitboxVerificationRegression(unittest.TestCase):
    def setUp(self):
        # The user's exact broken script with 8 fatal runtime defects and fake mock tables
        self.broken_hitbox_code = """
local function executeSpatialHitbox(casterCharacter, size, damage)
    local rootPart = casterCharacter:FindFirstChildOfClass("Humanoid"):WaitForChild("CFrame")
    local params = OverlapParams.new()
    params.FilterDescendantsInstances = {casterCharacter}
    params.FilterType = Enum.RaycastFilterType.Exclude

    local detectedParts = Workspace:GetPartBoundsInBox(rootPart.CFrame, size, params)
    local hitCharacters = {}

    for _, part in ipairs(detectedParts) do
        local targetChar = part.Parent
        local humanoid = targetChar:FindFirstChildOfClass("Humanoid")
        if humanoid and not hitCharacters[targetChar] then
            hitCharacters[targetChar] = true
            HumanoidRootPart:WaitForChild("Hitbox", function(hitbox)
                hitbox:TakeDamage(damage)
            end)
        end
    end
end

executeSpatialHitbox(HumanoidRootPart, Vector3.new(1, 1, 1), 10)
local task = task.wait
local OverlapParams = {}
local GetPartBoundsInBox = {}
local FilterDescendantsInstances = {}
"""

        # Fully corrected, production-ready Luau spatial hitbox implementation
        self.clean_hitbox_code = """
local Workspace = game:GetService("Workspace")

local hitDebounce = {}
local HIT_COOLDOWN = 0.5

local function executeSpatialHitbox(casterCharacter, size, damage)
    local casterRoot = casterCharacter:FindFirstChild("HumanoidRootPart")
    if not casterRoot then
        return
    end

    local overlapParams = OverlapParams.new()
    overlapParams.FilterDescendantsInstances = {casterCharacter}
    overlapParams.FilterType = Enum.RaycastFilterType.Exclude

    local detectedParts = Workspace:GetPartBoundsInBox(casterRoot.CFrame, size, overlapParams)
    local currentTime = os.clock()

    for _, part in ipairs(detectedParts) do
        local targetChar = part:FindFirstAncestorOfClass("Model")
        if targetChar and targetChar ~= casterCharacter then
            local humanoid = targetChar:FindFirstChildOfClass("Humanoid")
            local lastHit = hitDebounce[targetChar] or 0
            if humanoid and humanoid.Health > 0 and (currentTime - lastHit) >= HIT_COOLDOWN then
                hitDebounce[targetChar] = currentTime
                humanoid:TakeDamage(damage)
            end
        end
    end
end
"""

    def test_broken_hitbox_detects_all_8_defects(self):
        """Verify that AST & semantic validation catches all 8 errors + fake API mocks."""
        issues = LuauSyntaxValidator.check_syntax(self.broken_hitbox_code)
        messages = [i["message"] for i in issues]
        joined_msgs = "\n".join(messages)

        # 1. Caller argument type mismatch (executeSpatialHitbox called with HumanoidRootPart BasePart instead of Model)
        self.assertTrue(
            any("Type Mismatch in Call" in m and "executeSpatialHitbox" in m for m in messages),
            f"Failed to detect caller type mismatch. Messages:\n{joined_msgs}"
        )

        # 2. Humanoid CFrame access (Humanoid is a Controller without CFrame)
        self.assertTrue(
            any("Roblox Type Error" in m and "Humanoid" in m and "CFrame" in m for m in messages),
            f"Failed to detect Humanoid CFrame error. Messages:\n{joined_msgs}"
        )

        # 3. WaitForChild callback misuse
        self.assertTrue(
            any("Instance:WaitForChild" in m and "timeout" in m for m in messages),
            f"Failed to detect WaitForChild callback misuse. Messages:\n{joined_msgs}"
        )

        # 4. TakeDamage on non-Humanoid (hitbox BasePart)
        self.assertTrue(
            any(":TakeDamage()" in m and "Humanoid" in m for m in messages),
            f"Failed to detect invalid TakeDamage call on hitbox part. Messages:\n{joined_msgs}"
        )

        # 5. Library shadowing (local task = task.wait)
        self.assertTrue(
            any("Fatal Library Shadowing" in m and "task.wait" in m for m in messages),
            f"Failed to detect task library shadowing. Messages:\n{joined_msgs}"
        )

        # 6. Unresolved capitalized Workspace global
        self.assertTrue(
            any("Unresolved Global: 'Workspace'" in m for m in messages),
            f"Failed to detect capitalized Workspace global. Messages:\n{joined_msgs}"
        )

        # 7. Function-level single-invocation debounce table
        self.assertTrue(
            any("Single-Invocation Debounce Only" in m for m in messages),
            f"Failed to detect single-invocation debounce warning. Messages:\n{joined_msgs}"
        )

        # 8. Incomplete target character resolution (part.Parent)
        self.assertTrue(
            any("Incomplete Target Character Resolution" in m for m in messages),
            f"Failed to detect incomplete part.Parent character resolution. Messages:\n{joined_msgs}"
        )

        # Fake API mock tables at bottom (OverlapParams, GetPartBoundsInBox, FilterDescendantsInstances)
        self.assertTrue(
            any("Fake API Implementation" in m and "OverlapParams" in m for m in messages),
            f"Failed to detect OverlapParams mock table. Messages:\n{joined_msgs}"
        )
        self.assertTrue(
            any("Fake API Implementation" in m and "GetPartBoundsInBox" in m for m in messages),
            f"Failed to detect GetPartBoundsInBox mock table. Messages:\n{joined_msgs}"
        )
        self.assertTrue(
            any("Fake API Implementation" in m and "FilterDescendantsInstances" in m for m in messages),
            f"Failed to detect FilterDescendantsInstances mock table. Messages:\n{joined_msgs}"
        )

    def test_broken_hitbox_eliminates_false_green_passes(self):
        """Verify that RobloxDomainTestRunner rejects false passes for corrupted hitbox code."""
        result = RobloxDomainTestRunner.test_luau_code(self.broken_hitbox_code, "spatial hitbox melee attack")

        # Must report FAIL for API Validation and Static Validation
        self.assertEqual(result["api_status"], "FAIL", "api_status should be FAIL for broken hitbox code")
        self.assertEqual(result["static_status"], "FAIL", "static_status should be FAIL for broken hitbox code")
        self.assertFalse(result["is_verified"], "is_verified must be False for broken hitbox code")

        passed = result["passed_checks"]

        # MUST NOT claim cross-frame Multi-Hit Debounce Protection
        self.assertNotIn(
            "Multi-Hit Debounce Protection (Persistent debounce table or cooldown prevents damage spam across frames)",
            passed,
            "False pass: Broken hitbox claimed cross-frame Multi-Hit Debounce Protection"
        )
        # Should instead report Single-Query Limb Deduplication
        self.assertIn(
            "Single-Query Limb Deduplication (Filters multiple character limbs during a single spatial query)",
            passed,
            "Failed to classify single-invocation debounce accurately"
        )

        # MUST NOT claim Spatial Query Architecture PASS when corrupted by fake tables / unresolved globals
        self.assertNotIn(
            "Spatial Query Architecture (Modern OverlapParams / WorldRoot spatial query detected)",
            passed,
            "False pass: Broken hitbox claimed clean Spatial Query Architecture"
        )

        # MUST NOT claim Entity Humanoid Resolution PASS when Humanoid has fatal type errors
        self.assertNotIn(
            "Entity Humanoid Resolution (Validates target character model has Humanoid)",
            passed,
            "False pass: Broken hitbox claimed clean Entity Humanoid Resolution"
        )

        # MUST NOT claim Caster Immunity Filter PASS when caller passes BasePart and mock tables shadow Filter
        self.assertNotIn(
            "Caster Immunity Filter (Prevents attacker from damaging themselves)",
            passed,
            "False pass: Broken hitbox claimed Caster Immunity Filter PASS"
        )

        # MUST NOT claim Zero-Allocation Memory Profile
        self.assertNotIn(
            "Zero-Allocation Memory Profile (Pure spatial query without temporary Part allocations)",
            passed,
            "False pass: Broken hitbox claimed Zero-Allocation Memory Profile"
        )

    def test_broken_hitbox_report_badge_and_matrix(self):
        """Verify that the generated markdown report badge indicates API/Type failures."""
        result = RobloxDomainTestRunner.test_luau_code(self.broken_hitbox_code, "spatial hitbox melee attack")
        report_md = StrokeCodingLoop.format_verification_report_markdown(result, iterations=1)

        self.assertIn("FAILED (ROBLOX API OR TYPE ERRORS DETECTED)", report_md)
        self.assertIn("- Static Validation: FAIL", report_md)
        self.assertIn("- API Validation: FAIL", report_md)
        self.assertIn("- Verification Incomplete: YES", report_md)

    def test_clean_hitbox_passes_verification_cleanly(self):
        """Verify that the production-ready Luau spatial hitbox implementation passes all checks."""
        issues = LuauSyntaxValidator.check_syntax(self.clean_hitbox_code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertEqual(errors, [], f"Clean hitbox code produced unexpected errors: {errors}")

        result = RobloxDomainTestRunner.test_luau_code(self.clean_hitbox_code, "spatial hitbox melee attack")
        blocking = [f for f in result["failed_checks"] if f.get("type") == "error"]
        self.assertEqual(blocking, [], f"Clean hitbox produced blocking errors: {blocking}")

        self.assertEqual(result["api_status"], "PASS")
        self.assertEqual(result["static_status"], "PASS")

        passed = result["passed_checks"]
        self.assertTrue(any("Spatial Query Architecture" in p for p in passed))
        self.assertTrue(any("Multi-Hit Debounce Protection" in p for p in passed))
        self.assertTrue(any("Entity Humanoid Resolution" in p for p in passed))
        self.assertTrue(any("Living Entity Guard" in p for p in passed))
        self.assertTrue(any("Caster Immunity Filter" in p for p in passed))
        self.assertTrue(any("Partless Spatial Query Architecture" in p for p in passed))

        report_md = StrokeCodingLoop.format_verification_report_markdown(result, iterations=1)
        self.assertIn("STATIC CHECKS PASSED (COMPILER UNVERIFIED)", report_md)
        self.assertIn("- Static Validation: PASS", report_md)
        self.assertIn("- API Validation: PASS", report_md)


if __name__ == "__main__":
    unittest.main()
