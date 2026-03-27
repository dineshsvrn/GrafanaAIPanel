from __future__ import annotations

from typing import Any

from .ai_client import AIClient
from .dashboard_digest import build_dashboard_digest
from .grafana_client import GrafanaClient
from .prompt_compact import compact_digest_for_llm
from .report import AnalysisReport, build_report
from .time_range import resolve_time_range
from .timeseries_analysis import analyze_dashboard_timeseries


def analyze_dashboard(
    *,
    grafana_client: GrafanaClient,
    ai_client: AIClient,
    dashboard_uid: str,
    max_panels: int,
    max_targets_per_panel: int,
    enable_timeseries: bool,
    from_expr: str | int | None = None,
    to_expr: str | int | None = None,
    timeseries_max_panels: int = 12,
    anomaly_z_threshold: float = 6.0,
) -> tuple[AnalysisReport, dict[str, Any], dict[str, Any] | None]:
    payload = grafana_client.get_dashboard_by_uid(dashboard_uid)
    digest = build_dashboard_digest(
        payload,
        max_panels=max_panels,
        max_targets_per_panel=max_targets_per_panel,
    )

    timeseries_summary: dict[str, Any] | None = None
    if enable_timeseries:
        tr = resolve_time_range(from_expr=from_expr, to_expr=to_expr)
        timeseries_summary = analyze_dashboard_timeseries(
            grafana_client=grafana_client,
            dashboard_payload=payload,
            from_ms=tr.from_ms,
            to_ms=tr.to_ms,
            max_panels=timeseries_max_panels,
            z_threshold=anomaly_z_threshold,
        )

    markdown = ai_client.analyze_dashboard(
        dashboard_digest=compact_digest_for_llm(digest),
        timeseries_summary=timeseries_summary,
    )
    report = build_report(
        grafana_url=grafana_client.base_url,
        dashboard_uid=dashboard_uid,
        dashboard_payload=payload,
        markdown=markdown,
    )
    return report, digest, timeseries_summary
