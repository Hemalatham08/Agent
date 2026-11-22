"""Service that builds deterministic chart specs from ERP tool output."""

from __future__ import annotations

from typing import Any

from backend.agent.charts.builders import build_chart
from backend.agent.charts.specs import ChartSpec

MAX_CHARTS = 2


class ChartService:
    """Translate successful ERP tool results into chart specifications.

    At most :attr:`MAX_CHARTS` specs are emitted, in the order the tools were
    executed. Charts are derived exclusively from verified read-only tool
    output and are provider-independent.
    """

    def build_charts(
        self, successful_outputs: list[tuple[str, Any]]
    ) -> list[ChartSpec]:
        charts: list[ChartSpec] = []
        for tool_name, output in successful_outputs:
            if len(charts) >= MAX_CHARTS:
                break
            spec = build_chart(tool_name, output)
            if spec is not None:
                charts.append(spec)
        return charts


__all__ = ["ChartService", "MAX_CHARTS"]
