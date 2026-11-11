from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class ErpReadAdapter(Protocol):
    """Internal read-only query adapter.

    Implementations execute only fixed, internal SELECT statements supplied by
    :class:`~backend.agent.erp.service.ErpReadService`. SQL text must never
    come from tool arguments, users, or an LLM.
    """

    @property
    def query_timeout_seconds(self) -> float:
        ...

    def fetch_all(
        self,
        sql: str,
        parameters: Sequence[object] = (),
        *,
        deadline: float | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def fetch_one(
        self,
        sql: str,
        parameters: Sequence[object] = (),
        *,
        deadline: float | None = None,
    ) -> dict[str, Any] | None:
        ...


__all__ = ["ErpReadAdapter"]
