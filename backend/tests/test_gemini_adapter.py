"""Tests for the Gemini tool adapter and response parser.

Uses mocks and synthetic objects only. No real Gemini API calls are made.
No ERP files are modified.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import types

from backend.ai_providers.gemini.response_parser import (
    ParsedGeminiResponse,
    extract_function_call_arguments,
    extract_function_call_name,
    parse_generate_content_response,
)
from backend.ai_providers.gemini.tool_adapter import (
    ToolArgumentIssue,
    adapt_all_erp_tools,
    to_function_declaration,
    to_function_declarations,
    to_function_response,
    to_gemini_tools,
    to_tool_execution_request,
    validate_function_call,
)
from backend.agent.erp.definitions import (
    ERP_TOOL_DEFINITIONS,
    ERP_TOOL_DEFINITIONS_BY_NAME,
    ERP_TOOL_NAMES,
)
from backend.agent.tools.contracts import (
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
)
from backend.agent.tools.validation import validate_arguments


def _make_function_call(name: str, args: dict | None = None, call_id: str = "call-1"):
    """Build a synthetic Gemini FunctionCall-like object."""
    return SimpleNamespace(
        id=call_id,
        name=name,
        args=args if args is not None else {},
        partial_args=None,
        will_continue=False,
    )


def _make_tool_result(
    tool_name: str,
    status: ToolExecutionStatus = ToolExecutionStatus.SUCCEEDED,
    output: dict | None = None,
    error_message: str | None = None,
) -> ToolExecutionResult:
    """Build a synthetic ToolExecutionResult."""
    from backend.agent.models import ErrorCategory, utc_now
    from backend.agent.tools.contracts import ToolExecutionError

    now = utc_now()
    if status is ToolExecutionStatus.SUCCEEDED:
        return ToolExecutionResult(
            execution_id="exec-1",
            tool_name=tool_name,
            status=status,
            output=output or {"ok": True},
            started_at=now,
            finished_at=now,
            duration_ms=10.0,
        )
    # CANCELLED results cannot contain an error or output per ToolExecutionResult rules.
    if status is ToolExecutionStatus.CANCELLED:
        return ToolExecutionResult(
            execution_id="exec-1",
            tool_name=tool_name,
            status=status,
            output=None,
            error=None,
            started_at=now,
            finished_at=now,
            duration_ms=10.0,
        )
    error = ToolExecutionError(
        code="test_error",
        message=error_message or "Something went wrong",
        category=ErrorCategory.TOOL,
        recoverable=False,
        retryable=False,
        details={},
    )
    return ToolExecutionResult(
        execution_id="exec-1",
        tool_name=tool_name,
        status=status,
        output=None,
        error=error,
        started_at=now,
        finished_at=now,
        duration_ms=10.0,
    )


class TestToolAdapterFunctionDeclaration(unittest.TestCase):
    """Tests for converting ToolDefinition to Gemini FunctionDeclaration."""

    def test_adapt_all_erp_tools_returns_nine_tools(self):
        """All nine ERP tool definitions produce Gemini tools."""
        tools = adapt_all_erp_tools()
        self.assertEqual(len(tools), 1)  # wrapped in a single Tool
        declarations = tools[0].function_declarations
        self.assertEqual(len(declarations), len(ERP_TOOL_NAMES))

    def test_adapt_all_erp_tools_preserves_names(self):
        """Generated declarations preserve ERP tool names."""
        tools = adapt_all_erp_tools()
        declarations = tools[0].function_declarations
        names = {d.name for d in declarations}
        self.assertEqual(names, set(ERP_TOOL_NAMES))

    def test_to_function_declaration_product_search(self):
        """erp.products.search converts to a declaration with correct schema."""
        defn = ERP_TOOL_DEFINITIONS_BY_NAME["erp.products.search"]
        decl = to_function_declaration(defn)
        self.assertEqual(decl.name, "erp.products.search")
        self.assertIsInstance(decl.description, str)
        self.assertGreater(len(decl.description), 0)
        params = decl.parameters.model_dump(mode="json")
        self.assertEqual(str(params.get("type")).lower(), "object")
        props = params.get("properties", {})
        self.assertIn("query", props)
        self.assertIn("limit", props)
        self.assertEqual(str(props["query"].get("type")).lower(), "string")
        self.assertEqual(str(props["limit"].get("type")).lower(), "integer")
        self.assertFalse(params.get("additional_properties", True))

    def test_to_function_declaration_required_fields(self):
        """Required fields are preserved in the declaration schema."""
        defn = ERP_TOOL_DEFINITIONS_BY_NAME["erp.products.get"]
        decl = to_function_declaration(defn)
        params = decl.parameters.model_dump(mode="json")
        self.assertIn("product_id", params.get("required", []))

    def test_to_function_declaration_no_required(self):
        """Tools with no required fields have empty required list."""
        defn = ERP_TOOL_DEFINITIONS_BY_NAME["erp.products.count"]
        decl = to_function_declaration(defn)
        params = decl.parameters.model_dump(mode="json")
        self.assertEqual(params.get("required") or [], [])

    def test_to_function_declarations_list(self):
        """to_function_declarations returns a list matching input length."""
        defns = list(ERP_TOOL_DEFINITIONS[:3])
        decls = to_function_declarations(defns)
        self.assertEqual(len(decls), 3)
        for decl, defn in zip(decls, defns):
            self.assertEqual(decl.name, defn.name)

    def test_to_gemini_tools_wraps_in_single_tool(self):
        """to_gemini_tools returns a list with one Tool wrapping all declarations."""
        defns = list(ERP_TOOL_DEFINITIONS[:2])
        tools = to_gemini_tools(defns)
        self.assertEqual(len(tools), 1)
        self.assertEqual(len(tools[0].function_declarations), 2)


class TestToolAdapterValidation(unittest.TestCase):
    """Tests for validating function calls against the ERP tool catalog."""

    def test_validate_valid_call_returns_empty(self):
        """A valid call with known tool and valid args returns no issues."""
        issues = validate_function_call(
            "erp.products.get",
            {"product_id": "PRD001"},
            ERP_TOOL_DEFINITIONS_BY_NAME,
        )
        self.assertEqual(issues, [])

    def test_validate_unknown_tool_returns_issue(self):
        """An unknown tool name returns a validation issue."""
        issues = validate_function_call(
            "erp.nonexistent.tool",
            {},
            ERP_TOOL_DEFINITIONS_BY_NAME,
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].keyword, "unknown_tool")
        self.assertIn("erp.nonexistent.tool", issues[0].message)

    def test_validate_missing_required_arg_returns_issue(self):
        """Missing a required argument returns a validation issue."""
        issues = validate_function_call(
            "erp.products.get",
            {},  # product_id is required
            ERP_TOOL_DEFINITIONS_BY_NAME,
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].path, "product_id")

    def test_validate_unknown_argument_rejected(self):
        """An undeclared argument is rejected (additionalProperties: false)."""
        issues = validate_function_call(
            "erp.products.get",
            {"product_id": "PRD001", "bogus_field": "value"},
            ERP_TOOL_DEFINITIONS_BY_NAME,
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].path, "bogus_field")

    def test_validate_wrong_type_rejected(self):
        """A wrong argument type returns a validation issue."""
        issues = validate_function_call(
            "erp.products.search",
            {"limit": "not-an-integer"},
            ERP_TOOL_DEFINITIONS_BY_NAME,
        )
        self.assertEqual(len(issues), 1)

    def test_validate_against_real_validation_module(self):
        """validate_function_call results match validate_arguments directly."""
        defn = ERP_TOOL_DEFINITIONS_BY_NAME["erp.inventory.get"]
        direct_issues = validate_arguments(
            {"product_id": "PRD001"}, defn.input_schema
        )
        adapter_issues = validate_function_call(
            "erp.inventory.get",
            {"product_id": "PRD001"},
            ERP_TOOL_DEFINITIONS_BY_NAME,
        )
        self.assertEqual(len(direct_issues), len(adapter_issues))


class TestToolAdapterToRequest(unittest.TestCase):
    """Tests for converting FunctionCall to ToolExecutionRequest."""

    def test_to_tool_execution_request_valid(self):
        """A valid function call produces a ToolExecutionRequest."""
        fc = _make_function_call(
            "erp.products.get", {"product_id": "PRD001"}, "call-abc"
        )
        request = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
        self.assertIsInstance(request, ToolExecutionRequest)
        self.assertEqual(request.tool_name, "erp.products.get")
        self.assertEqual(request.arguments, {"product_id": "PRD001"})

    def test_to_tool_execution_request_unknown_tool_returns_none(self):
        """An unknown tool name returns None."""
        fc = _make_function_call("erp.bogus.tool", {}, "call-x")
        result = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
        self.assertIsNone(result)

    def test_to_tool_execution_request_invalid_args_returns_none(self):
        """Invalid arguments return None (missing required field)."""
        fc = _make_function_call(
            "erp.products.get", {}, "call-x"  # product_id missing
        )
        result = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
        self.assertIsNone(result)

    def test_to_tool_execution_request_non_dict_args(self):
        """Non-dict args are rejected explicitly, not silently coerced."""
        fc = SimpleNamespace(
            id="call-x", name="erp.products.get", args="not-a-dict"
        )
        result = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
        # Non-dict arguments must be rejected, not silently converted to {}.
        self.assertIsNone(result)

    def test_to_tool_execution_request_args_none(self):
        """Args of None are rejected explicitly."""
        fc = SimpleNamespace(
            id="call-x", name="erp.products.get", args=None
        )
        result = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
        self.assertIsNone(result)

    def test_to_tool_execution_request_empty_function_name(self):
        """An empty function name returns None (no executable request)."""
        fc = SimpleNamespace(id="call-x", name="   ", args={})
        result = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
        self.assertIsNone(result)

    def test_to_tool_execution_request_missing_function_name(self):
        """A missing function name returns None (no executable request)."""
        fc = SimpleNamespace(id="call-x", args={"product_id": "PRD001"})
        result = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
        self.assertIsNone(result)

    def test_to_tool_execution_request_non_string_function_name(self):
        """A non-string function name returns None (no executable request)."""
        fc = SimpleNamespace(id="call-x", name=123, args={})
        result = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
        self.assertIsNone(result)

    def test_to_tool_execution_request_tool_with_no_required_args(self):
        """A tool with no required arguments produces a valid request with {}."""
        fc = _make_function_call("erp.warehouses.list", {}, "call-valid")
        request = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
        self.assertIsNotNone(request)
        self.assertEqual(request.tool_name, "erp.warehouses.list")
        self.assertEqual(request.arguments, {})

    def test_to_tool_execution_request_all_erp_tools(self):
        """Every ERP tool name can produce a valid request with proper args."""
        for tool_name in ERP_TOOL_NAMES:
            defn = ERP_TOOL_DEFINITIONS_BY_NAME[tool_name]
            # Build minimal valid args based on required fields
            args = {}
            for prop in defn.input_schema.get("required", []):
                args[prop] = "dummy-value"
            fc = _make_function_call(tool_name, args, "call-valid")
            request = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
            self.assertIsNotNone(request, f"Tool {tool_name} should be valid")
            self.assertEqual(request.tool_name, tool_name)


class TestToolAdapterToFunctionResponse(unittest.TestCase):
    """Tests for converting ToolExecutionResult to Gemini FunctionResponse."""

    def test_to_function_response_success(self):
        """A successful result converts to a FunctionResponse with output."""
        result = _make_tool_result(
            "erp.products.get",
            ToolExecutionStatus.SUCCEEDED,
            output={"product_id": "PRD001", "product_name": "Hex Bolt"},
        )
        resp = to_function_response("call-1", "erp.products.get", result)
        self.assertEqual(resp.id, "call-1")
        self.assertEqual(resp.name, "erp.products.get")
        self.assertIn("output", resp.response)
        self.assertEqual(resp.response.get("output", {}).get("product_id"), "PRD001")

    def test_to_function_response_failure(self):
        """A failed result converts to a FunctionResponse with error."""
        result = _make_tool_result(
            "erp.products.get",
            ToolExecutionStatus.FAILED,
            error_message="Product not found",
        )
        resp = to_function_response("call-2", "erp.products.get", result)
        self.assertEqual(resp.id, "call-2")
        self.assertEqual(resp.name, "erp.products.get")
        self.assertIn("error", resp.response)
        error = resp.response.get("error", {})
        self.assertEqual(error.get("code"), "test_error")
        self.assertEqual(error.get("message"), "Product not found")
        self.assertEqual(error.get("category"), "tool")

    def test_to_function_response_cancelled(self):
        """A cancelled result converts to a FunctionResponse with error."""
        result = _make_tool_result(
            "erp.products.get",
            ToolExecutionStatus.CANCELLED,
        )
        resp = to_function_response("call-3", "erp.products.get", result)
        self.assertIn("error", resp.response)

    def test_to_function_response_preserves_details(self):
        """Error details are preserved in the function response."""
        from backend.agent.models import ErrorCategory, utc_now
        from backend.agent.tools.contracts import ToolExecutionError

        now = utc_now()
        result = ToolExecutionResult(
            execution_id="exec-detail",
            tool_name="erp.products.get",
            status=ToolExecutionStatus.FAILED,
            output=None,
            error=ToolExecutionError(
                code="erp_not_found",
                message="Product not found",
                category=ErrorCategory.NOT_FOUND,
                recoverable=True,
                retryable=False,
                details={"resource": "product"},
            ),
            started_at=now,
            finished_at=now,
            duration_ms=5.0,
        )
        resp = to_function_response("call-detail", "erp.products.get", result)
        error = resp.response.get("error", {})
        self.assertEqual(error.get("details", {}).get("resource"), "product")


class TestResponseParser(unittest.TestCase):
    """Tests for parsing Gemini GenerateContentResponse objects."""

    def _make_candidate(self, parts, finish_reason="STOP"):
        """Build a synthetic Candidate-like object."""
        content = SimpleNamespace(parts=parts, role="model")
        return SimpleNamespace(
            content=content,
            finish_reason=finish_reason,
        )

    def _make_part_text(self, text: str):
        """Build a synthetic text part."""
        return SimpleNamespace(text=text, function_call=None)

    def _make_part_function_call(self, name: str, args: dict, call_id: str = "fc-1"):
        """Build a synthetic function-call part."""
        return SimpleNamespace(
            text=None,
            function_call=SimpleNamespace(
                id=call_id, name=name, args=args, partial_args=None
            ),
        )

    def _make_response(self, candidates):
        """Build a synthetic GenerateContentResponse-like object."""
        return SimpleNamespace(candidates=candidates)

    def test_parse_text_only_response(self):
        """A text-only response produces text with no function calls."""
        part = self._make_part_text("Hello, how can I help?")
        candidate = self._make_candidate([part])
        response = self._make_response([candidate])
        parsed = parse_generate_content_response(response)
        self.assertEqual(parsed.text, "Hello, how can I help?")
        self.assertEqual(parsed.function_calls, [])
        self.assertEqual(parsed.finish_reason, "STOP")
        self.assertFalse(parsed.truncated)

    def test_parse_function_call_response(self):
        """A response with a function call extracts the call."""
        part = self._make_part_function_call(
            "erp.products.get", {"product_id": "PRD001"}, "fc-abc"
        )
        candidate = self._make_candidate([part])
        response = self._make_response([candidate])
        parsed = parse_generate_content_response(response)
        self.assertEqual(parsed.text, "")
        self.assertEqual(len(parsed.function_calls), 1)
        fc = parsed.function_calls[0]
        self.assertEqual(fc.id, "fc-abc")
        self.assertEqual(fc.name, "erp.products.get")
        self.assertEqual(fc.args, {"product_id": "PRD001"})

    def test_parse_mixed_text_and_function_call(self):
        """A response with both text and function calls captures both."""
        text_part = self._make_part_text("Let me look that up.")
        fc_part = self._make_part_function_call(
            "erp.warehouses.list", {}, "fc-xyz"
        )
        candidate = self._make_candidate([text_part, fc_part])
        response = self._make_response([candidate])
        parsed = parse_generate_content_response(response)
        self.assertEqual(parsed.text, "Let me look that up.")
        self.assertEqual(len(parsed.function_calls), 1)
        self.assertEqual(parsed.function_calls[0].name, "erp.warehouses.list")

    def test_parse_empty_candidates(self):
        """An empty candidates list produces an empty response."""
        response = self._make_response([])
        parsed = parse_generate_content_response(response)
        self.assertEqual(parsed.text, "")
        self.assertEqual(parsed.function_calls, [])
        self.assertIsNone(parsed.finish_reason)
        self.assertFalse(parsed.truncated)

    def test_parse_truncated_response(self):
        """A truncated response sets truncated=True."""
        part = self._make_part_text("Partial answer...")
        candidate = self._make_candidate([part], finish_reason="length")
        response = self._make_response([candidate])
        parsed = parse_generate_content_response(response)
        self.assertTrue(parsed.truncated)
        self.assertEqual(parsed.finish_reason, "length")

    def test_parse_no_candidates_attribute(self):
        """A response without candidates attribute is handled gracefully."""
        response = SimpleNamespace()
        parsed = parse_generate_content_response(response)
        self.assertEqual(parsed.text, "")
        self.assertEqual(parsed.function_calls, [])

    def test_parse_part_without_text_or_function_call(self):
        """Parts with neither text nor function_call are skipped."""
        part = SimpleNamespace()  # no text, no function_call
        candidate = self._make_candidate([part])
        response = self._make_response([candidate])
        parsed = parse_generate_content_response(response)
        self.assertEqual(parsed.text, "")
        self.assertEqual(parsed.function_calls, [])

    def test_parse_function_call_without_name(self):
        """A function call with no name is skipped."""
        fc = SimpleNamespace(id="fc-1", name="", args={})
        part = SimpleNamespace(text=None, function_call=fc)
        candidate = self._make_candidate([part])
        response = self._make_response([candidate])
        parsed = parse_generate_content_response(response)
        self.assertEqual(parsed.text, "")
        self.assertEqual(parsed.function_calls, [])

    def test_extract_function_call_arguments(self):
        """extract_function_call_arguments returns the args dict."""
        fc = _make_function_call("erp.products.get", {"product_id": "PRD001"})
        args = extract_function_call_arguments(fc)
        self.assertEqual(args, {"product_id": "PRD001"})

    def test_extract_function_call_arguments_none(self):
        """extract_function_call_arguments returns {} for None args."""
        fc = SimpleNamespace(id="fc-1", name="test", args=None)
        args = extract_function_call_arguments(fc)
        self.assertEqual(args, {})

    def test_extract_function_call_arguments_non_dict(self):
        """extract_function_call_arguments returns {} for non-dict args."""
        fc = SimpleNamespace(id="fc-1", name="test", args="not-a-dict")
        args = extract_function_call_arguments(fc)
        self.assertEqual(args, {})

    def test_extract_function_call_name(self):
        """extract_function_call_name returns the name."""
        fc = _make_function_call("erp.products.get", {"product_id": "PRD001"})
        name = extract_function_call_name(fc)
        self.assertEqual(name, "erp.products.get")

    def test_extract_function_call_name_empty(self):
        """extract_function_call_name returns None for empty name."""
        fc = SimpleNamespace(id="fc-1", name="   ", args={})
        name = extract_function_call_name(fc)
        self.assertIsNone(name)

    def test_parsed_response_is_dataclass(self):
        """ParsedGeminiResponse is a proper dataclass with defaults."""
        r = ParsedGeminiResponse()
        self.assertEqual(r.text, "")
        self.assertEqual(r.function_calls, [])
        self.assertIsNone(r.finish_reason)
        self.assertFalse(r.truncated)


class TestAdapterWithRealSDKTypes(unittest.TestCase):
    """Integration-style tests using real google-genai SDK types."""

    def test_real_function_declaration_construction(self):
        """A real types.FunctionDeclaration can be constructed from our adapter."""
        defn = ERP_TOOL_DEFINITIONS_BY_NAME["erp.warehouses.list"]
        decl = to_function_declaration(defn)
        self.assertIsInstance(decl, types.FunctionDeclaration)
        self.assertEqual(decl.name, "erp.warehouses.list")

    def test_real_gemini_tool_construction(self):
        """Real types.Tool objects can be constructed from our adapter."""
        defns = [ERP_TOOL_DEFINITIONS_BY_NAME["erp.products.get"]]
        tools = to_gemini_tools(defns)
        self.assertEqual(len(tools), 1)
        self.assertIsInstance(tools[0], types.Tool)
        self.assertEqual(len(tools[0].function_declarations), 1)

    def test_real_parse_generate_content_response(self):
        """A real SDK response can be parsed."""
        fc = types.FunctionCall(
            id="real-call-1",
            name="erp.products.search",
            args={"query": "bolt", "limit": 5},
        )
        part = types.Part(
            text=None,
            function_call=fc,
        )
        content = types.Content(parts=[part], role="model")
        candidate = types.Candidate(
            content=content,
            finish_reason="STOP",
        )
        response = types.GenerateContentResponse(candidates=[candidate])
        parsed = parse_generate_content_response(response)
        self.assertEqual(len(parsed.function_calls), 1)
        self.assertEqual(parsed.function_calls[0].name, "erp.products.search")
        self.assertEqual(parsed.function_calls[0].args, {"query": "bolt", "limit": 5})

    def test_real_function_response_construction(self):
        """A real types.FunctionResponse can be constructed from our adapter."""
        result = _make_tool_result(
            "erp.products.get",
            ToolExecutionStatus.SUCCEEDED,
            output={"product_id": "PRD001"},
        )
        resp = to_function_response("real-call", "erp.products.get", result)
        self.assertIsInstance(resp, types.FunctionResponse)
        self.assertEqual(resp.id, "real-call")
        self.assertEqual(resp.name, "erp.products.get")
        self.assertIn("output", resp.response)

    def test_real_parse_truncated_finish_reason_enum(self):
        """A real SDK finish_reason enum value (e.g. MAX_TOKENS) is detected
        as truncation."""
        part = types.Part(
            text="Partial answer...",
        )
        content = types.Content(parts=[part], role="model")
        # types.FinishReason.MAX_TOKENS is the real SDK enum for truncation.
        candidate = types.Candidate(
            content=content,
            finish_reason=types.FinishReason.MAX_TOKENS,
        )
        response = types.GenerateContentResponse(candidates=[candidate])
        parsed = parse_generate_content_response(response)
        self.assertTrue(parsed.truncated)
        self.assertEqual(parsed.finish_reason, types.FinishReason.MAX_TOKENS)
        self.assertEqual(parsed.text, "Partial answer...")


class TestAdapterImportSafety(unittest.TestCase):
    """Verifies that tool_adapter and response_parser can be imported when
    google-genai is not installed (Ollama-only installations)."""

    def _block_google_imports(self):
        """Block google and google.genai imports via sys.meta_path."""
        import sys

        # Remove any already-imported google modules.
        for name in list(sys.modules):
            if name == "google" or name.startswith("google."):
                del sys.modules[name]

        class BlockFinder:
            def find_module(self, name, path=None):
                if name == "google" or name.startswith("google."):
                    return self
                return None

            def load_module(self, name):
                raise ImportError(f"Blocked: {name}")

        sys.meta_path.insert(0, BlockFinder())
        return BlockFinder

    def test_tool_adapter_importable_without_genai(self):
        """tool_adapter can be imported when google-genai is not installed."""
        import subprocess
        import sys
        import os

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        code = (
            "import sys\n"
            "for name in list(sys.modules):\n"
            "    if name == 'google' or name.startswith('google.'):\n"
            "        del sys.modules[name]\n"
            "class BlockFinder:\n"
            "    def find_module(self, name, path=None):\n"
            "        if name == 'google' or name.startswith('google.'):\n"
            "            return self\n"
            "        return None\n"
            "    def load_module(self, name):\n"
            "        raise ImportError(f'Blocked: {name}')\n"
            "sys.meta_path.insert(0, BlockFinder())\n"
            "from backend.ai_providers.gemini.tool_adapter import (\n"
            "    to_function_declaration,\n"
            "    to_gemini_tools,\n"
            "    to_tool_execution_request,\n"
            "    validate_function_call,\n"
            ")\n"
            "print('OK')\n"
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = project_root + (os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else project_root
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)

    def test_response_parser_importable_without_genai(self):
        """response_parser can be imported when google-genai is not installed."""
        import subprocess
        import sys
        import os

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        code = (
            "import sys\n"
            "for name in list(sys.modules):\n"
            "    if name == 'google' or name.startswith('google.'):\n"
            "        del sys.modules[name]\n"
            "class BlockFinder:\n"
            "    def find_module(self, name, path=None):\n"
            "        if name == 'google' or name.startswith('google.'):\n"
            "            return self\n"
            "        return None\n"
            "    def load_module(self, name):\n"
            "        raise ImportError(f'Blocked: {name}')\n"
            "sys.meta_path.insert(0, BlockFinder())\n"
            "from backend.ai_providers.gemini.response_parser import (\n"
            "    parse_generate_content_response,\n"
            "    ParsedGeminiResponse,\n"
            ")\n"
            "print('OK')\n"
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = project_root + (os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else project_root
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
