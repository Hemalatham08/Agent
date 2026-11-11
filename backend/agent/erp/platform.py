from __future__ import annotations

from threading import RLock

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.registration import (
    ErpToolRegistration,
    register_erp_tools,
)
from backend.agent.erp.runner import ErpToolRunner
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry


class ErpToolPlatform:
    """Application-scoped ERP service, tool registry, executor, and runner."""

    def __init__(
        self,
        *,
        config: ErpDatabaseConfig,
        adapter: SqliteErpReadAdapter,
        service: ErpReadService,
        registry: ToolRegistry,
        executor: ToolExecutor,
        registration: ErpToolRegistration,
        runner: ErpToolRunner,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.service = service
        self.registry = registry
        self.executor = executor
        self.registration = registration
        self.runner = runner
        self._lock = RLock()
        self._closed = False

    @classmethod
    def from_config(cls, config: ErpDatabaseConfig) -> ErpToolPlatform:
        if not isinstance(config, ErpDatabaseConfig):
            raise TypeError("config must be an ErpDatabaseConfig")

        adapter = SqliteErpReadAdapter(config)
        service = ErpReadService(adapter)
        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        registration: ErpToolRegistration | None = None
        try:
            registration = register_erp_tools(registry, executor, service)
            runner = ErpToolRunner(executor)
            return cls(
                config=config,
                adapter=adapter,
                service=service,
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
    def from_env(cls) -> ErpToolPlatform:
        return cls.from_config(ErpDatabaseConfig.from_env())

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

    def __enter__(self) -> ErpToolPlatform:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


__all__ = ["ErpToolPlatform"]
