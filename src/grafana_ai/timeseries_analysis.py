from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .anomaly import SeriesPoint, robust_z_anomalies
from .dataframe import TimeSeries, parse_grafana_query_response
from .datasource_query import build_panel_queries
from .grafana_client import GrafanaClient
from .series_stats import SeriesStats, compute_stats


@dataclass(frozen=True)
class SeriesAnomalySummary:
    series_name: str
    points: int
    stats: SeriesStats
    anomalies: int
    last_anomaly_t_ms: int | None
    strongest_score: float | None
    sample_last_points: list[tuple[int, float]]


@dataclass(frozen=True)
class PanelAnomalySummary:
    panel_id: int | None
    panel_title: str | None
    panel_type: str | None
    datasource_type: str | None
    datasource_uid: str | None
    series: list[SeriesAnomalySummary]
    series_total: int
    series_with_anomalies: int
    error: str | None = None


def _summarize_series(ts: TimeSeries, *, z_threshold: float, sample_points: int) -> SeriesAnomalySummary:
    pts = [SeriesPoint(t_ms=t, value=v) for t, v in ts.points]
    anomalies = robust_z_anomalies(pts, z_threshold=z_threshold)

    last_t = max((a.t_ms for a in anomalies), default=None)
    strongest = max((abs(a.score) for a in anomalies), default=None) if anomalies else None

    stats = compute_stats(ts.points)
    sample_last = sorted(ts.points, key=lambda x: x[0])[-sample_points:] if sample_points > 0 else []

    return SeriesAnomalySummary(
        series_name=ts.name,
        points=len(ts.points),
        stats=stats,
        anomalies=len(anomalies),
        last_anomaly_t_ms=last_t,
        strongest_score=float(strongest) if strongest is not None else None,
        sample_last_points=sample_last,
    )


def analyze_dashboard_timeseries(
    *,
    grafana_client: GrafanaClient,
    dashboard_payload: dict[str, Any],
    from_ms: int,
    to_ms: int,
    max_panels: int = 0,
    z_threshold: float = 6.0,
    max_series_per_panel: int = 12,
    sample_last_points: int = 6,
) -> dict[str, Any]:
    dashboard = dashboard_payload.get("dashboard") if isinstance(dashboard_payload, dict) else None
    panels = (dashboard or {}).get("panels") if isinstance(dashboard, dict) else None
    if not isinstance(panels, list):
        return {"enabled": True, "panels": [], "error": "No panels found in dashboard payload."}

    panels_to_analyze = panels if max_panels <= 0 else panels[:max_panels]
    summaries: list[PanelAnomalySummary] = []

    for panel in panels_to_analyze:
        if not isinstance(panel, dict):
            continue

        panel_id = panel.get("id") if isinstance(panel.get("id"), int) else None
        title = panel.get("title") if isinstance(panel.get("title"), str) else None
        ptype = panel.get("type") if isinstance(panel.get("type"), str) else None

        ds = panel.get("datasource") if isinstance(panel.get("datasource"), dict) else {}
        ds_type = ds.get("type") if isinstance(ds.get("type"), str) else None
        ds_uid = ds.get("uid") if isinstance(ds.get("uid"), str) else None

        try:
            panel_queries = build_panel_queries(panel)
            if not panel_queries:
                continue

            resp = grafana_client.query_datasource(
                queries=[q.model for q in panel_queries],
                from_ms=from_ms,
                to_ms=to_ms,
            )
            series = parse_grafana_query_response(resp)

            series_summaries_all = [
                _summarize_series(s, z_threshold=z_threshold, sample_points=sample_last_points) for s in series
            ]
            series_total = len(series_summaries_all)
            series_with_anom = sum(1 for s in series_summaries_all if s.anomalies > 0)

            # Prefer returning anomalous series to keep prompt size small.
            series_summaries = [s for s in series_summaries_all if s.anomalies > 0]
            if not series_summaries:
                # Return a tiny sample so user can tell it ran.
                series_summaries = series_summaries_all[: min(3, len(series_summaries_all))]

            series_summaries = sorted(
                series_summaries,
                key=lambda s: (s.anomalies, s.strongest_score or 0.0),
                reverse=True,
            )
            series_summaries = series_summaries[:max_series_per_panel]

            summaries.append(
                PanelAnomalySummary(
                    panel_id=panel_id,
                    panel_title=title,
                    panel_type=ptype,
                    datasource_type=ds_type,
                    datasource_uid=ds_uid,
                    series=series_summaries,
                    series_total=series_total,
                    series_with_anomalies=series_with_anom,
                )
            )
        except Exception as exc:
            summaries.append(
                PanelAnomalySummary(
                    panel_id=panel_id,
                    panel_title=title,
                    panel_type=ptype,
                    datasource_type=ds_type,
                    datasource_uid=ds_uid,
                    series=[],
                    series_total=0,
                    series_with_anomalies=0,
                    error=str(exc),
                )
            )

    return {
        "enabled": True,
        "from_ms": from_ms,
        "to_ms": to_ms,
        "z_threshold": z_threshold,
        "panels_analyzed": len(summaries),
        "panels": [asdict(s) for s in summaries],
    }

