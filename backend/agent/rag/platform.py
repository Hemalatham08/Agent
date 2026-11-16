"""Application-scoped, offline RAG tool platform.

``RagToolPlatform`` owns a corpus bundle, BM25 index, guard-first retriever,
tool handlers, registry, executor, registration, and runner. Construction is
fully offline: it loads the shipped Markdown corpus (or a caller-supplied
directory) and never opens the ERP database, network, LLM, or orchestrator.

The platform is intentionally not wired into ``backend/main.py``. It exists so
the RAG tool layer can be initialized, exercised, and torn down independently.
``RAG_ENABLED`` is an integration flag; constructing a platform does not depend
on it, so tests and diagnostics can run while the production flag stays false.
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from backend.agent.rag.bm25 import Bm25Index
from backend.agent.rag.config import RagConfig
from backend.agent.rag.corpus import load_corpus
from backend.agent.rag.handlers import RagToolHandlers
from backend.agent.rag.models import CorpusBundle
from backend.agent.rag.registration import (
    RagToolRegistration,
    register_rag_tools,
)
from backend.agent.rag.retriever import DocumentationRetriever
from backend.agent.rag.runner import RagToolRunner
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry


class RagToolPlatform:
    """Application-scoped RAG corpus, tool registry, executor, and runner."""

    def __init__(
        self,
        *,
        config: RagConfig,
        bundle: CorpusBundle,
        index: Bm25Index,
        retriever: DocumentationRetriever,
        handlers: RagToolHandlers,
        registry: ToolRegistry,
        executor: ToolExecutor,
        registration: RagToolRegistration,
        runner: RagToolRunner,
    ) -> None:
        self.config = config
        self.bundle = bundle
        self.index = index
        self.retriever = retriever
        self.handlers = handlers
        self.registry = registry
        self.executor = executor
        self.registration = registration
        self.runner = runner
        self._lock = RLock()
        self._closed = False

    @classmethod
    def from_config(cls, config: RagConfig) -> RagToolPlatform:
        if not isinstance(config, RagConfig):
            raise TypeError("config must be a RagConfig")

        bundle = load_corpus(config)
        index = Bm25Index(bundle, k1=config.bm25_k1, b=config.bm25_b)
        retriever = DocumentationRetriever(
            index,
            min_score=config.min_score,
            max_hits_per_doc=config.max_hits_per_doc,
            max_snippet_chars=config.max_snippet_chars,
            max_total_chars=config.max_total_chars,
        )
        handlers = RagToolHandlers(
            retriever,
            bundle,
            default_top_k=config.default_top_k,
            max_document_chars=config.max_document_chars,
        )

        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        registration: RagToolRegistration | None = None
        try:
            registration = register_rag_tools(registry, executor, handlers)
            runner = RagToolRunner(executor)
            return cls(
                config=config,
                bundle=bundle,
                index=index,
                retriever=retriever,
                handlers=handlers,
                registry=registry,
                executor=executor,
                registration=registration,
                runner=runner,
            )
        except BaseException:
            if registration is not None:
                try:
                    registration.unregister()
                except Exception:
                    pass
            try:
                executor.shutdown()
            except Exception:
                pass
            raise

    @classmethod
    def from_directory(
        cls,
        knowledge_dir: str | Path,
        **config_overrides: object,
    ) -> RagToolPlatform:
        """Build a platform from a corpus directory using offline defaults."""

        return cls.from_config(
            RagConfig(knowledge_dir=knowledge_dir, **config_overrides)
        )

    @classmethod
    def from_env(cls) -> RagToolPlatform:
        return cls.from_config(RagConfig.from_env())

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self.registration.unregister()
            finally:
                self.executor.shutdown()

    def __enter__(self) -> RagToolPlatform:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


__all__ = ["RagToolPlatform"]
