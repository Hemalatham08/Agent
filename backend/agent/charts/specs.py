"""Deterministic chart specifications for ERP analytics tool results.

Chart specs are pure, provider-independent descriptions derived from actual
read-only ERP tool output. They contain no LLM-generated values and are
intended to be rendered by the frontend with Recharts.

The supported chart types are ``bar``, ``line``, ``pie`` and ``grouped_bar``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChartSpec(BaseModel):
    """A single chart to render in the assistant bubble.

    ``data`` holds the chart rows already produced by an ERP tool, so chart
    values always trace back to verified read-only tool output.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    chart_type: str = Field(
        description="One of 'bar', 'line', 'pie', 'grouped_bar'."
    )
    title: str = Field(description="Human-readable chart title.")
    data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Chart rows, each keyed by the x field and y field(s).",
    )
    x_field: str = Field(description="Data key used for the category axis.")
    y_fields: list[str] = Field(
        default_factory=list,
        description="Data key(s) used for the value axis.",
    )
    x_label: str = Field(default="", description="Category axis label.")
    y_label: str = Field(default="", description="Value axis label.")
    color_scheme: str = Field(default="default", description="Palette hint.")

    @property
    def is_series(self) -> bool:
        return self.chart_type == "grouped_bar" and len(self.y_fields) > 1


__all__ = ["ChartSpec"]
