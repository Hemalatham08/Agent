from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.agent.models import ErrorCategory
from backend.agent.rag.config import DEFAULT_KNOWLEDGE_DIR, RagConfig
from backend.agent.rag.errors import (
    RagConfigurationError,
    RagInternalError,
    RagInvalidArgumentsError,
    RagNotFoundError,
)
from backend.agent.rag.platform import RagToolPlatform
from backend.agent.rag.registration import register_rag_tools
from backend.agent.rag.runner import RagToolRunner
from backend.agent.tools.contracts import (
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
)
from backend.agent.tools.errors import ToolNotFoundError
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry
from backend.tests.rag_tool_support import (
    make_platform,
    make_rag_config,
    write_long_document,
    write_tool_corpus,
)

_NO_TIMEOUT = object()


def make_result(
    output: object = None,
    *,
    status: ToolExecutionStatus = ToolExecutionStatus.SUCCEEDED,
    error: ToolExecutionError | None = None,
    execution_id: str = "exec-1",
    tool_name: str = "rag.knowledge.search",
) -> ToolExecutionResult:
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    finished_at = datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
    return ToolExecutionResult(
        execution_id=execution_id,
        tool_name=tool_name,
        status=status,
        output=output,
        error=error,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=1000.0,
    )


class _StaticExecutor:
    def __init__(self, result: ToolExecutionResult) -> None:
        self.result = result
        self.timeouts: list[object] = []

    def execute(
        self,
        request: ToolExecutionRequest,
        timeout: object = _NO_TIMEOUT,
    ) -> ToolExecutionResult:
        self.timeouts.append(timeout)
        return self.result


class _PlatformTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.root = Path(self._temp_dir.name)
        write_tool_corpus(self.root)
        self.platform = make_platform(self.root)
        self.addCleanup(self.platform.close)


class RagToolRunnerSuccessTests(_PlatformTestCase):
    def test_all_three_tools_execute_successfully(self) -> None:
        cases = (
            ("rag.knowledge.search", {"query": "What is free stock?"}),
            ("rag.knowledge.get", {"doc_id": "free-stock"}),
            ("rag.knowledge.topics", {}),
        )
        for tool_name, arguments in cases:
            with self.subTest(tool=tool_name):
                request = ToolExecutionRequest(
                    execution_id=f"exec-{tool_name}",
                    tool_name=tool_name,
                    arguments=arguments,
                )
                result = self.platform.runner.execute(request)

                self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
                self.assertIsNone(result.error)
                self.assertEqual(result.execution_id, request.execution_id)
                self.assertEqual(result.tool_name, tool_name)
                self.assertIsInstance(result.output, dict)
                self.assertNotIn("ok", result.output)
                self.assertNotIn("data", result.output)
                self.assertIsNotNone(result.started_at)
                self.assertIsNotNone(result.finished_at)
                self.assertGreaterEqual(result.duration_ms or 0, 0)

    def test_search_data_contract_is_bounded_and_documentation_only(self) -> None:
        result = self.platform.runner.execute(
            ToolExecutionRequest(
                tool_name="rag.knowledge.search",
                arguments={"query": "What is free stock?", "top_k": 1},
            )
        )

        output = result.output
        self.assertEqual(
            set(output),
            {
                "query",
                "status",
                "blocked_reason",
                "guidance",
                "hits",
                "total_chars",
                "index_version",
                "live_data",
                "disclaimer",
            },
        )
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["index_version"], self.platform.bundle.index_version)
        self.assertIs(output["live_data"], False)
        self.assertLessEqual(len(output["hits"]), 1)
        self.assertEqual(
            output["total_chars"],
            sum(len(hit["snippet"]) for hit in output["hits"]),
        )
        for hit in output["hits"]:
            self.assertLessEqual(len(hit["snippet"]), 700)
            self.assertEqual(hit["category"], "business_definitions")

    def test_blocked_live_query_is_a_successful_blocked_result(self) -> None:
        result = self.platform.runner.execute(
            ToolExecutionRequest(
                tool_name="rag.knowledge.search",
                arguments={"query": "How many products do we have?"},
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertIsNone(result.error)
        output = result.output
        self.assertEqual(output["status"], "blocked")
        self.assertEqual(output["blocked_reason"], "count")
        self.assertEqual(output["hits"], [])
        self.assertEqual(output["total_chars"], 0)
        self.assertTrue(output["guidance"])
        self.assertIs(output["live_data"], False)

    def test_guard_runs_before_bm25_through_the_runner(self) -> None:
        with patch.object(
            self.platform.index,
            "search",
            side_effect=AssertionError("BM25 must not run"),
        ):
            result = self.platform.runner.execute(
                ToolExecutionRequest(
                    tool_name="rag.knowledge.search",
                    arguments={"query": "How many products do we have?"},
                )
            )

        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(result.output["status"], "blocked")

    def test_executor_exposes_the_internal_envelope(self) -> None:
        result = self.platform.executor.execute(
            ToolExecutionRequest(
                tool_name="rag.knowledge.topics",
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(set(result.output), {"ok", "data"})
        self.assertIs(result.output["ok"], True)
        self.assertIn("items", result.output["data"])

    def test_get_and_topics_data_are_metadata_only(self) -> None:
        get_result = self.platform.runner.execute(
            ToolExecutionRequest(
                tool_name="rag.knowledge.get",
                arguments={"doc_id": "free-stock"},
            )
        )
        topics_result = self.platform.runner.execute(
            ToolExecutionRequest(tool_name="rag.knowledge.topics")
        )

        self.assertIn("body", get_result.output)
        self.assertNotIn("items", get_result.output)
        self.assertIn("items", topics_result.output)
        self.assertNotIn("body", topics_result.output)
        for item in topics_result.output["items"]:
            self.assertNotIn("body", item)
            self.assertNotIn("source_path", item)


class RagToolRunnerErrorTests(_PlatformTestCase):
    def test_semantic_invalid_arguments_become_failed_results(self) -> None:
        result = self.platform.runner.execute(
            ToolExecutionRequest(
                tool_name="rag.knowledge.search",
                arguments={"query": "What is free stock?", "top_k": 0},
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertIsNone(result.output)
        self.assertEqual(result.error.code, "rag_invalid_arguments")
        self.assertEqual(result.error.category, ErrorCategory.VALIDATION)
        self.assertEqual(result.error.details, {"field": "top_k"})
        self.assertTrue(result.error.recoverable)
        self.assertFalse(result.error.retryable)

    def test_category_enum_is_rejected_by_executor_preflight(self) -> None:
        result = self.platform.runner.execute(
            ToolExecutionRequest(
                tool_name="rag.knowledge.search",
                arguments={
                    "query": "What is free stock?",
                    "category": "reports",
                },
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "invalid_arguments")
        self.assertEqual(result.error.category, ErrorCategory.VALIDATION)
        self.assertEqual(
            result.error.details["issues"][0]["path"],
            "category",
        )
        self.assertEqual(
            result.error.details["issues"][0]["keyword"],
            "enum",
        )

    def test_unexpected_argument_is_rejected_by_executor_preflight(self) -> None:
        result = self.platform.runner.execute(
            ToolExecutionRequest(
                tool_name="rag.knowledge.search",
                arguments={"query": "What is free stock?", "sql": "SELECT 1"},
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "invalid_arguments")
        self.assertEqual(
            result.error.details["issues"][0]["path"],
            "sql",
        )
        self.assertEqual(
            result.error.details["issues"][0]["keyword"],
            "additionalProperties",
        )

    def test_missing_required_argument_is_rejected_by_executor_preflight(
        self,
    ) -> None:
        for tool_name in ("rag.knowledge.search", "rag.knowledge.get"):
            with self.subTest(tool=tool_name):
                result = self.platform.runner.execute(
                    ToolExecutionRequest(tool_name=tool_name)
                )
                self.assertEqual(result.status, ToolExecutionStatus.FAILED)
                self.assertEqual(result.error.code, "invalid_arguments")
                self.assertEqual(
                    result.error.details["issues"][0]["keyword"],
                    "required",
                )

    def test_unknown_doc_id_is_translated_to_not_found(self) -> None:
        result = self.platform.runner.execute(
            ToolExecutionRequest(
                tool_name="rag.knowledge.get",
                arguments={"doc_id": "missing-doc"},
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "rag_not_found")
        self.assertEqual(result.error.category, ErrorCategory.NOT_FOUND)
        self.assertEqual(result.error.details, {"resource": "document"})
        self.assertTrue(result.error.recoverable)

    def test_path_like_doc_id_is_a_validation_failure(self) -> None:
        result = self.platform.runner.execute(
            ToolExecutionRequest(
                tool_name="rag.knowledge.get",
                arguments={"doc_id": "../secret"},
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "rag_invalid_arguments")
        self.assertEqual(result.error.details, {"field": "doc_id"})

    def test_unknown_tool_is_returned_unchanged(self) -> None:
        result = self.platform.runner.execute(
            ToolExecutionRequest(tool_name="rag.knowledge.unknown")
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "tool_not_found")
        self.assertEqual(result.error.category, ErrorCategory.NOT_FOUND)

    def test_malformed_handler_envelopes_fail_closed(self) -> None:
        malformed_outputs = (
            None,
            [],
            {},
            {"ok": True},
            {"ok": "yes", "data": {}},
            {"ok": 1, "data": {}},
            {"ok": True, "data": {"value": float("nan")}},
            {"ok": True, "data": {}, "extra": True},
            {"ok": False},
            {"ok": False, "error": {}},
            {
                "ok": False,
                "error": {
                    "code": " ",
                    "message": "bad",
                    "category": "internal",
                    "recoverable": False,
                    "retryable": False,
                    "details": {},
                },
            },
            {
                "ok": False,
                "error": {
                    "code": "secret",
                    "message": "bad",
                    "category": "not-a-category",
                    "recoverable": False,
                    "retryable": False,
                    "details": {},
                },
            },
            {
                "ok": False,
                "error": {
                    "code": "rag_internal_error",
                    "message": "bad",
                    "category": "internal",
                    "recoverable": 0,
                    "retryable": False,
                    "details": {},
                },
            },
            {
                "ok": False,
                "error": {
                    "code": "rag_internal_error",
                    "message": "bad",
                    "category": "internal",
                    "recoverable": False,
                    "retryable": False,
                    "details": {"value": float("nan")},
                },
            },
            {
                "ok": False,
                "error": {
                    "code": "rag_internal_error",
                    "message": "bad",
                    "category": "internal",
                    "recoverable": False,
                    "retryable": False,
                    "details": {},
                    "extra": True,
                },
            },
        )
        for output in malformed_outputs:
            with self.subTest(output=repr(output)):
                runner = RagToolRunner(  # type: ignore[arg-type]
                    _StaticExecutor(make_result(output))
                )
                result = runner.execute(
                    ToolExecutionRequest(tool_name="rag.knowledge.search")
                )

                self.assertEqual(result.status, ToolExecutionStatus.FAILED)
                self.assertIsNone(result.output)
                self.assertEqual(result.error.code, "rag_internal_error")
                self.assertEqual(result.error.category, ErrorCategory.INTERNAL)
                self.assertFalse(result.error.recoverable)
                self.assertFalse(result.error.retryable)
                self.assertEqual(result.error.details, {})
                self.assertNotIn("secret", result.error.message)


class RagToolRunnerEnvelopeTests(unittest.TestCase):
    def _run_with_output(self, output: object) -> ToolExecutionResult:
        runner = RagToolRunner(  # type: ignore[arg-type]
            _StaticExecutor(make_result(output))
        )
        return runner.execute(
            ToolExecutionRequest(tool_name="rag.knowledge.search")
        )

    def test_rag_error_envelopes_are_translated(self) -> None:
        errors = (
            RagInvalidArgumentsError("query"),
            RagNotFoundError("document"),
            RagInternalError(),
        )
        for error in errors:
            with self.subTest(code=error.code):
                result = self._run_with_output(error.to_envelope())

                self.assertEqual(result.status, ToolExecutionStatus.FAILED)
                self.assertIsNone(result.output)
                self.assertEqual(result.error.code, error.code)
                self.assertEqual(result.error.category, error.category)
                self.assertEqual(
                    result.error.recoverable,
                    error.recoverable,
                )
                self.assertEqual(result.error.retryable, error.retryable)
                self.assertEqual(result.error.details, error.details)

    def test_success_translation_preserves_timing(self) -> None:
        source = make_result({"ok": True, "data": {"status": "ok"}})
        runner = RagToolRunner(_StaticExecutor(source))  # type: ignore[arg-type]
        result = runner.execute(
            ToolExecutionRequest(
                execution_id="exec-1",
                tool_name="rag.knowledge.search",
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(result.output, {"status": "ok"})
        self.assertEqual(result.execution_id, source.execution_id)
        self.assertEqual(result.tool_name, source.tool_name)
        self.assertEqual(result.started_at, source.started_at)
        self.assertEqual(result.finished_at, source.finished_at)
        self.assertEqual(result.duration_ms, source.duration_ms)

    def test_error_translation_preserves_timing(self) -> None:
        source = make_result(
            RagNotFoundError("document").to_envelope()
        )
        runner = RagToolRunner(_StaticExecutor(source))  # type: ignore[arg-type]
        result = runner.execute(
            ToolExecutionRequest(
                execution_id="exec-1",
                tool_name="rag.knowledge.search",
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.execution_id, source.execution_id)
        self.assertEqual(result.tool_name, source.tool_name)
        self.assertEqual(result.started_at, source.started_at)
        self.assertEqual(result.finished_at, source.finished_at)
        self.assertEqual(result.duration_ms, source.duration_ms)

    def test_failed_and_cancelled_results_are_returned_unchanged(self) -> None:
        failed = make_result(
            status=ToolExecutionStatus.FAILED,
            error=ToolExecutionError(
                code="handler_error",
                message="failed",
                category=ErrorCategory.TOOL,
            ),
        )
        cancelled = make_result(status=ToolExecutionStatus.CANCELLED)

        for source in (failed, cancelled):
            with self.subTest(status=source.status):
                runner = RagToolRunner(  # type: ignore[arg-type]
                    _StaticExecutor(source)
                )
                result = runner.execute(
                    ToolExecutionRequest(tool_name="rag.knowledge.search")
                )
                self.assertIs(result, source)

    def test_timeout_forwarding(self) -> None:
        executor = _StaticExecutor(
            make_result({"ok": True, "data": {}})
        )
        runner = RagToolRunner(executor)  # type: ignore[arg-type]
        request = ToolExecutionRequest(tool_name="rag.knowledge.search")

        runner.execute(request, timeout=1.25)
        runner.execute(request, timeout=None)
        runner.execute(request)

        self.assertEqual(executor.timeouts[0], 1.25)
        self.assertIsNone(executor.timeouts[1])
        self.assertIs(executor.timeouts[2], _NO_TIMEOUT)


class RagToolPlatformTests(_PlatformTestCase):
    def test_from_config_builds_all_components(self) -> None:
        platform = self.platform

        self.assertIsInstance(platform, RagToolPlatform)
        self.assertIsInstance(platform.config, RagConfig)
        self.assertEqual(platform.bundle.index_version, platform.index.index_version)
        self.assertEqual(platform.bundle.index_version, platform.retriever.index.index_version)
        self.assertEqual(len(platform.bundle.documents), 5)
        self.assertEqual(platform.index.chunk_count, len(platform.bundle.chunks))
        self.assertEqual(
            {definition.name for definition in platform.registry.list_tools()},
            {
                "rag.knowledge.search",
                "rag.knowledge.get",
                "rag.knowledge.topics",
            },
        )
        for name in (
            "rag.knowledge.search",
            "rag.knowledge.get",
            "rag.knowledge.topics",
        ):
            self.assertTrue(platform.executor.has_handler(name))
        self.assertIsInstance(platform.runner, RagToolRunner)
        self.assertFalse(platform.closed)

    def test_registry_is_isolated_to_the_rag_namespace(self) -> None:
        names = {
            definition.name for definition in self.platform.registry.list_tools()
        }

        self.assertTrue(names)
        for name in names:
            self.assertTrue(name.startswith("rag.knowledge."))
        with self.assertRaises(ToolNotFoundError):
            self.platform.registry.get("erp.products.search")

    def test_from_directory(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tool_corpus(root)
            with RagToolPlatform.from_directory(root) as platform:
                self.assertEqual(platform.config.knowledge_dir, root.resolve())
                result = platform.runner.execute(
                    ToolExecutionRequest(tool_name="rag.knowledge.topics")
                )
                self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
                self.assertEqual(result.output["count"], 5)
            self.assertTrue(platform.closed)

    def test_from_env(self) -> None:
        environment = {
            "RAG_KNOWLEDGE_DIR": str(self.root),
            "RAG_ENABLED": "true",
            "RAG_DEFAULT_TOP_K": "2",
            "RAG_MIN_SCORE": "0.2",
        }
        with patch.dict(os.environ, environment, clear=True):
            platform = RagToolPlatform.from_env()
        self.addCleanup(platform.close)

        self.assertTrue(platform.config.enabled)
        self.assertEqual(platform.config.default_top_k, 2)
        self.assertEqual(platform.config.min_score, 0.2)
        self.assertEqual(platform.config.knowledge_dir, self.root.resolve())

    def test_from_env_defaults_to_the_shipped_corpus(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            platform = RagToolPlatform.from_env()
        self.addCleanup(platform.close)

        self.assertEqual(
            platform.config.knowledge_dir,
            DEFAULT_KNOWLEDGE_DIR.resolve(),
        )
        self.assertFalse(platform.config.enabled)
        self.assertTrue(platform.bundle.documents)
        self.assertEqual(
            {document.category for document in platform.bundle.documents},
            {
                "erp_docs",
                "business_definitions",
                "workflows",
                "policies_faqs",
                "schema",
            },
        )
        result = platform.runner.execute(
            ToolExecutionRequest(tool_name="rag.knowledge.topics")
        )
        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(
            result.output["count"],
            len(platform.bundle.documents),
        )

    def test_disabled_flag_does_not_block_initialization(self) -> None:
        config = make_rag_config(self.root, enabled=False)
        with RagToolPlatform.from_config(config) as platform:
            self.assertFalse(platform.config.enabled)
            result = platform.runner.execute(
                ToolExecutionRequest(tool_name="rag.knowledge.topics")
            )
            self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)

    def test_from_config_rejects_a_non_config(self) -> None:
        with self.assertRaises(TypeError):
            RagToolPlatform.from_config("not a config")  # type: ignore[arg-type]

    def test_from_directory_rejects_invalid_configuration(self) -> None:
        with self.assertRaises(RagConfigurationError):
            RagToolPlatform.from_directory(
                self.root,
                max_document_chars=1,
            )

    def test_close_unregisters_and_shuts_down(self) -> None:
        platform = self.platform
        self.assertFalse(platform.closed)

        platform.close()

        self.assertTrue(platform.closed)
        self.assertEqual(platform.registry.list_tools(), [])
        for name in (
            "rag.knowledge.search",
            "rag.knowledge.get",
            "rag.knowledge.topics",
        ):
            self.assertFalse(platform.executor.has_handler(name))
        platform.close()
        with self.assertRaises(RuntimeError):
            platform.executor.execute(
                ToolExecutionRequest(tool_name="rag.knowledge.topics")
            )

    def test_context_manager_closes(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tool_corpus(root)
            with make_platform(root) as platform:
                self.assertFalse(platform.closed)
            self.assertTrue(platform.closed)

    def test_empty_corpus_initializes_and_returns_empty_results(self) -> None:
        with TemporaryDirectory() as temporary:
            empty_root = Path(temporary)
            with make_platform(empty_root) as platform:
                self.assertEqual(platform.bundle.documents, ())
                self.assertEqual(platform.bundle.chunks, ())
                self.assertEqual(len(platform.bundle.index_version), 12)

                topics = platform.runner.execute(
                    ToolExecutionRequest(tool_name="rag.knowledge.topics")
                )
                self.assertEqual(topics.status, ToolExecutionStatus.SUCCEEDED)
                self.assertEqual(topics.output["count"], 0)
                self.assertEqual(topics.output["items"], [])

                search = platform.runner.execute(
                    ToolExecutionRequest(
                        tool_name="rag.knowledge.search",
                        arguments={"query": "What is free stock?"},
                    )
                )
                self.assertEqual(search.status, ToolExecutionStatus.SUCCEEDED)
                self.assertEqual(search.output["status"], "no_match")
                self.assertEqual(search.output["hits"], [])

                blocked = platform.runner.execute(
                    ToolExecutionRequest(
                        tool_name="rag.knowledge.search",
                        arguments={"query": "How many products do we have?"},
                    )
                )
                self.assertEqual(blocked.status, ToolExecutionStatus.SUCCEEDED)
                self.assertEqual(blocked.output["status"], "blocked")

                missing = platform.runner.execute(
                    ToolExecutionRequest(
                        tool_name="rag.knowledge.get",
                        arguments={"doc_id": "missing-doc"},
                    )
                )
                self.assertEqual(missing.status, ToolExecutionStatus.FAILED)
                self.assertEqual(missing.error.code, "rag_not_found")

    def test_output_bounds_are_enforced_by_the_platform(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tool_corpus(root)
            write_long_document(root)
            with make_platform(
                root,
                default_top_k=5,
                max_snippet_chars=100,
                max_total_chars=500,
                max_document_chars=100,
            ) as platform:
                search = platform.runner.execute(
                    ToolExecutionRequest(
                        tool_name="rag.knowledge.search",
                        arguments={
                            "query": "Explain the long reference page",
                            "top_k": 5,
                        },
                    )
                )
                self.assertEqual(search.status, ToolExecutionStatus.SUCCEEDED)
                self.assertEqual(search.output["status"], "ok")
                self.assertLessEqual(search.output["total_chars"], 500)
                for hit in search.output["hits"]:
                    self.assertLessEqual(len(hit["snippet"]), 100)

                document = platform.runner.execute(
                    ToolExecutionRequest(
                        tool_name="rag.knowledge.get",
                        arguments={"doc_id": "long-reference"},
                    )
                )
                self.assertEqual(
                    document.status,
                    ToolExecutionStatus.SUCCEEDED,
                )
                self.assertLessEqual(len(document.output["body"]), 100)
                self.assertIs(document.output["truncated"], True)

    def test_default_top_k_comes_from_configuration(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tool_corpus(root)
            with make_platform(root, default_top_k=1) as platform:
                search = platform.runner.execute(
                    ToolExecutionRequest(
                        tool_name="rag.knowledge.search",
                        arguments={"query": "What is stock or order?"},
                    )
                )
                self.assertEqual(search.status, ToolExecutionStatus.SUCCEEDED)
                self.assertLessEqual(len(search.output["hits"]), 1)

    def test_outputs_are_deterministic_across_platforms(self) -> None:
        other = make_platform(self.root)
        self.addCleanup(other.close)

        cases = (
            ToolExecutionRequest(
                tool_name="rag.knowledge.search",
                arguments={"query": "What is free stock?", "top_k": 3},
            ),
            ToolExecutionRequest(
                tool_name="rag.knowledge.get",
                arguments={"doc_id": "free-stock"},
            ),
            ToolExecutionRequest(tool_name="rag.knowledge.topics"),
        )
        for request in cases:
            with self.subTest(tool=request.tool_name):
                first = self.platform.runner.execute(request)
                second = self.platform.runner.execute(request)
                third = other.runner.execute(request)
                self.assertEqual(first.output, second.output)
                self.assertEqual(first.output, third.output)
                self.assertEqual(first.status, third.status)

    def test_registration_helper_is_reusable_on_a_fresh_registry(self) -> None:
        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        self.addCleanup(executor.shutdown)

        registration = register_rag_tools(
            registry,
            executor,
            self.platform.handlers,
        )
        self.addCleanup(registration.unregister)

        result = executor.execute(
            ToolExecutionRequest(tool_name="rag.knowledge.topics")
        )
        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertIs(result.output["ok"], True)


if __name__ == "__main__":
    unittest.main()
