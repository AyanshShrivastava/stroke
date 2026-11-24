"""
test_code_engineering_and_verification.py
================================================================================
STROKE V1 — CODE ENGINEERING & VERIFICATION PIPELINE TEST SUITE
================================================================================
Tests:
1. Lexer & Comment/String Masking:
   - Operators (!=, &&, ||) inside comments and string literals are never flagged.
   - Luau keywords inside strings/comments never distort block matching.
   - Escaped single and double quotes (\', \", \\) parse correctly.
   - Arbitrary long bracket strings and comments ([===[ ... ]===]) handle nested brackets.
2. Block Structure & Delimiter Balancing:
   - Valid while..do, for..do, if..then..elseif..else, repeat..until, do..end structures.
   - Catch unclosed delimiters, unexpected 'end', mismatched 'until'.
3. Real Luau API Validation:
   - Rejects fake APIs (Instance.new("Hitbox"), capitalized Workspace, OverlapParams = {}).
   - Allows genuine APIs in code, strings, and comments.
4. Code Preservation & Extraction:
   - Proves _clean_code_artifacts never deletes legitimate identical rows (e.g. matrices).
   - Proves extract_all_code_blocks preserves indentation, whitespace, and comments.
5. Explicit Verification States (PASS, FAIL, UNVERIFIED):
   - Unsupported languages (JS, TS, C++, Rust, Unknown) strictly return UNVERIFIED.
   - Missing compilers never return PASS.
   - Failed test assertions strictly invalidate verified status (FAIL).
   - Real Python compilation returns PASS for valid code.
6. API Endpoint /ai/verify-code:
   - Enforces correct verification states over HTTP.
================================================================================
"""

import os
import unittest
from fastapi.testclient import TestClient

# Set offline DB mode for testing
os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

from luau_analyzer import (
    LuauLexer,
    LuauToken,
    LuauTokenType,
    mask_comments_and_strings,
    AuthenticLuauValidator,
    find_system_luau_tool
)
from coding_loop import (
    StrokeCodingLoop,
    LuauSyntaxValidator,
    RobloxDomainTestRunner
)
from main import app, get_current_user
from auth_service import AuthenticatedUser


# ==============================================================================
# 1. LEXER & COMMENT/STRING MASKING TESTS
# ==============================================================================

class TestLuauLexerAndMasking(unittest.TestCase):

    def test_operators_inside_comments_and_strings_ignored(self):
        """Operators !=, &&, || inside comments and strings must never be flagged."""
        code = '''
        -- Note: in Luau, != and && and || are illegal operators
        local comment_sample = "Testing != and && and || inside double quotes"
        local single_sample = 'Testing != and && and || inside single quotes'
        local valid_op = (a ~= b) and (c or d)
        '''
        issues = AuthenticLuauValidator.validate_code(code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertEqual(len(errors), 0, f"Expected 0 errors, got: {errors}")

    def test_escaped_quotes_in_string_literals(self):
        """Escaped quotes (\', \", \\) must not terminate string literals early."""
        code = r'''
        local s1 = 'It\'s a string with escaped single quote and != and &&'
        local s2 = "String with \"escaped double quotes\" and != and ||"
        local s3 = "String with \\ escaped backslash and != "
        local clean = true
        '''
        issues = AuthenticLuauValidator.validate_code(code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertEqual(len(errors), 0, f"Expected 0 errors, got: {errors}")

    def test_arbitrary_long_brackets(self):
        """Arbitrary long-bracket strings [===[ ... ]===] must allow arbitrary delimiters and nested brackets."""
        code = '''
        --[===[
            Multiline comment with != and && and ||
            [==[ nested long bracket ]==]
            Instance.new("Hitbox")
        ]===]
        local raw = [====[
            This raw string contains [=[ nested ]=] and [[ simple ]]
            and operators: !=, &&, ||, and Workspace.Part = true
            Instance.new("Hitbox")
        ]====]
        local x = 42
        '''
        issues = AuthenticLuauValidator.validate_code(code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertEqual(len(errors), 0, f"Expected 0 errors, got: {errors}")

    def test_mask_comments_and_strings_preserves_exact_lines_and_columns(self):
        """Masking must preserve exact line count and column layout."""
        code = "local a = 1\n-- comment with != and &&\nlocal b = 'str with ||'\nlocal c = 3"
        masked, tokens = mask_comments_and_strings(code)
        self.assertEqual(len(masked), len(code))
        self.assertEqual(masked.count("\n"), code.count("\n"))
        self.assertIn("local a = 1", masked)
        self.assertIn("local c = 3", masked)
        self.assertNotIn("!=", masked)
        self.assertNotIn("&&", masked)
        self.assertNotIn("||", masked)


# ==============================================================================
# 2. SYNTAX & BLOCK STRUCTURE BALANCING TESTS
# ==============================================================================

class TestLuauStructureBalancing(unittest.TestCase):

    def test_valid_nested_blocks_pass(self):
        """Balanced function, while..do, for..do, if..then..else, repeat..until pass."""
        code = '''
        local function processData(items)
            local total = 0
            for i = 1, #items do
                if items[i] > 10 then
                    total = total + items[i]
                elseif items[i] > 5 then
                    total = total + 1
                else
                    total = total - 1
                end
            end

            local count = 0
            while count < 5 do
                count = count + 1
            end

            repeat
                count = count - 1
            until count == 0

            do
                local isolated = true
            end

            return total
        end
        '''
        issues = AuthenticLuauValidator.validate_code(code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertEqual(len(errors), 0, f"Expected 0 errors, got: {errors}")

    def test_unclosed_block_fails(self):
        """Missing 'end' for function must produce an error."""
        code = '''
        local function test()
            local x = 10
        '''
        issues = AuthenticLuauValidator.validate_code(code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("Unclosed block 'function'" in e["message"] for e in errors))

    def test_unexpected_end_fails(self):
        """Extra 'end' must produce an error."""
        code = '''
        local x = 10
        end
        '''
        issues = AuthenticLuauValidator.validate_code(code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("Unexpected 'end'" in e["message"] for e in errors))

    def test_mismatched_repeat_until_fails(self):
        """Closing a repeat block with 'end' instead of 'until' must produce an error."""
        code = '''
        repeat
            task.wait()
        end
        '''
        issues = AuthenticLuauValidator.validate_code(code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("until" in e["message"].lower() for e in errors))

    def test_delimiter_imbalance_fails(self):
        """Mismatched and unclosed parentheses or brackets must produce errors."""
        code1 = "local t = { 1, 2, 3 )"
        issues1 = AuthenticLuauValidator.validate_code(code1)
        errors1 = [i for i in issues1 if i["type"] == "error"]
        self.assertTrue(len(errors1) > 0)
        self.assertTrue(any("Mismatched delimiter" in e["message"] for e in errors1))

        code2 = "local x = ((1 + 2) * 3"
        issues2 = AuthenticLuauValidator.validate_code(code2)
        errors2 = [i for i in issues2 if i["type"] == "error"]
        self.assertTrue(len(errors2) > 0)
        self.assertTrue(any("Unclosed opening delimiter" in e["message"] for e in errors2))


# ==============================================================================
# 3. REAL ROBLOX API & OPERATOR TESTS
# ==============================================================================

class TestLuauApiAndOperators(unittest.TestCase):

    def test_illegal_operators_in_code_detected(self):
        """Illegal operators !=, &&, || in actual code must produce errors."""
        code = '''
        if a != b and c && d or e || f then
            print("illegal")
        end
        '''
        issues = AuthenticLuauValidator.validate_code(code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertGreaterEqual(len(errors), 3)
        messages = [e["message"] for e in errors]
        self.assertTrue(any("!=" in m for m in messages))
        self.assertTrue(any("&&" in m for m in messages))
        self.assertTrue(any("||" in m for m in messages))

    def test_invalid_instance_new_class_detected(self):
        """Instance.new with non-existent class must be flagged."""
        code = 'local h = Instance.new("Hitbox")'
        issues = AuthenticLuauValidator.validate_code(code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("Invalid Roblox class 'Hitbox'" in e["message"] for e in errors))

    def test_capitalized_workspace_global_detected(self):
        """Capitalized 'Workspace.' without declaration must be flagged."""
        code = 'Workspace.Part.Transparency = 0.5'
        issues = AuthenticLuauValidator.validate_code(code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("Unresolved Global: 'Workspace'" in e["message"] for e in errors))

    def test_fake_api_mocking_detected(self):
        """Mock tables for built-in Roblox datatypes must be flagged."""
        code = 'local OverlapParams = {}'
        issues = AuthenticLuauValidator.validate_code(code)
        errors = [i for i in issues if i["type"] == "error"]
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("Fake API Implementation" in e["message"] for e in errors))


# ==============================================================================
# 4. CODE PRESERVATION & EXTRACTION TESTS
# ==============================================================================

class TestCodePreservation(unittest.TestCase):

    def test_clean_code_artifacts_never_deletes_identical_lines(self):
        """Prove that matrices and repeated statements are 100% preserved."""
        code = "\n".join([
            "local matrix = {",
            "    {0, 0, 0, 0},",
            "    {0, 0, 0, 0},",
            "    {0, 0, 0, 0},",
            "    {0, 0, 0, 0},",
            "    {0, 0, 0, 0},",
            "    {0, 0, 0, 0},",
            "}",
            "print('step')",
            "print('step')",
            "print('step')",
            "print('step')",
            "print('step')",
        ])
        result = StrokeCodingLoop._clean_code_artifacts(code)
        self.assertEqual(result, code, "Code was modified or truncated by _clean_code_artifacts!")
        self.assertEqual(result.count("{0, 0, 0, 0}"), 6, "Identical matrix rows were deleted!")
        self.assertEqual(result.count("print('step')"), 5, "Repeated statements were deleted!")

    def test_extract_all_code_blocks_preserves_indentation(self):
        """Extraction must not strip leading spaces off first or internal lines."""
        text = (
            "Here is the script:\n\n"
            "```python\n"
            "    def indented_func():\n"
            "        x = 10\n"
            "        return x\n"
            "```\n"
        )
        blocks = StrokeCodingLoop.extract_all_code_blocks(text, default_lang="python")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["language"], "python")
        extracted = blocks[0]["code"]
        self.assertTrue(extracted.startswith("    def indented_func():"), f"Indentation lost: {extracted!r}")
        self.assertIn("        x = 10", extracted)


# ==============================================================================
# 5. MULTI-LANGUAGE VERIFICATION STATES (PASS, FAIL, UNVERIFIED)
# ==============================================================================

class TestMultiLanguageVerificationStates(unittest.TestCase):

    def test_unsupported_languages_strictly_unverified(self):
        """JS, TS, C++, Rust, Unknown must NEVER return PASS or is_verified=True."""
        unsupported = ["javascript", "typescript", "js", "ts", "cpp", "c++", "rust", "go", "brainfuck"]
        for lang in unsupported:
            report = RobloxDomainTestRunner.test_generic_code("console.log('hi')", lang)
            self.assertFalse(report["is_verified"], f"Language '{lang}' returned is_verified=True!")
            self.assertEqual(report["verification_status"], "UNVERIFIED", f"Language '{lang}' status was not UNVERIFIED!")
            self.assertIn("UNVERIFIED", report["syntax_status"])

    def test_python_valid_code_passes(self):
        """Valid Python code compiles and returns PASS."""
        code = '''
def add(a: int, b: int) -> int:
    """Adds two integers."""
    return a + b

result = add(5, 7)
assert result == 12
'''
        report = RobloxDomainTestRunner.test_python_code(code, prompt="run test assertions")
        self.assertTrue(report["is_verified"])
        self.assertEqual(report["verification_status"], "PASS")
        self.assertEqual(report["syntax_status"], "PASS")
        self.assertEqual(report["test_status"], "PASS")

    def test_python_syntax_error_fails(self):
        """Syntax error in Python code must return FAIL."""
        code = "def bad_syntax(:\n    pass"
        report = RobloxDomainTestRunner.test_python_code(code)
        self.assertFalse(report["is_verified"])
        self.assertEqual(report["verification_status"], "FAIL")
        self.assertEqual(report["syntax_status"], "FAIL")

    def test_python_failed_assertion_invalidates_verified_status(self):
        """Failed test assertion must strictly set is_verified=False and verification_status=FAIL."""
        code = '''
def calculate():
    return 42

assert calculate() == 999  # Intentional failure
'''
        report = RobloxDomainTestRunner.test_python_code(code, prompt="run tests")
        self.assertFalse(report["is_verified"])
        self.assertEqual(report["verification_status"], "FAIL")
        self.assertEqual(report["test_status"], "FAIL")

    def test_luau_missing_compiler_strictly_unverified(self):
        """If native luau binary is absent, valid AST must return UNVERIFIED (never false PASS)."""
        code = '''
        local function test()
            local x = 10
            return x
        end
        '''
        report = RobloxDomainTestRunner.test_luau_code(code, prompt="")
        has_luau = bool(find_system_luau_tool())
        if has_luau:
            self.assertEqual(report["verification_status"], "PASS")
            self.assertTrue(report["is_verified"])
        else:
            self.assertEqual(report["verification_status"], "UNVERIFIED")
            self.assertFalse(report["is_verified"])
            self.assertIn("UNVERIFIED", report["syntax_status"])

    def test_luau_syntax_error_fails(self):
        """Luau code with syntax errors must return FAIL."""
        code = "if a != b then"
        report = RobloxDomainTestRunner.test_luau_code(code, prompt="")
        self.assertFalse(report["is_verified"])
        self.assertEqual(report["verification_status"], "FAIL")
        self.assertEqual(report["syntax_status"], "FAIL")


# ==============================================================================
# 6. FASTAPI /ai/verify-code ENDPOINT TESTS
# ==============================================================================

class TestVerifyCodeEndpoint(unittest.TestCase):

    def setUp(self):
        async def override_user():
            return AuthenticatedUser(uid="test-verifier-uid", email="verifier@stroke.test")

        app.dependency_overrides[get_current_user] = override_user
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_endpoint_unsupported_language_returns_unverified(self):
        """POST /ai/verify-code with javascript must return is_verified=False and UNVERIFIED."""
        resp = self.client.post("/ai/verify-code", json={
            "code": "console.log('hello')",
            "language": "javascript",
            "prompt": "Test JS"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["language"], "javascript")
        self.assertFalse(data["is_verified"])
        self.assertEqual(data["verification_status"], "UNVERIFIED")
        self.assertFalse(data["report"]["is_verified"])
        self.assertEqual(data["report"]["verification_status"], "UNVERIFIED")

    def test_endpoint_python_clean_code_passes(self):
        """POST /ai/verify-code with valid python returns PASS."""
        resp = self.client.post("/ai/verify-code", json={
            "code": "x = 10\ny = 20\nassert x + y == 30\n",
            "language": "python",
            "prompt": "run tests"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_verified"])
        self.assertEqual(data["verification_status"], "PASS")

    def test_endpoint_python_error_fails(self):
        """POST /ai/verify-code with invalid python returns FAIL."""
        resp = self.client.post("/ai/verify-code", json={
            "code": "def broken(\n",
            "language": "python",
            "prompt": "run tests"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["is_verified"])
        self.assertEqual(data["verification_status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
