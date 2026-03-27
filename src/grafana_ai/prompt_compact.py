from __future__ import annotations

from typing import Any


def _clip(s: Any, max_len: int) -> str | None:
    if s is None:
        return None
    if not isinstance(s, str):
        s = str(s)
    s = s.strip()
    if not s:
        return None
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def compact_digest_for_llm(digest: dict[str, Any], *, max_query_len: int = 180) -> dict[str, Any]:
    """Reduce payload size so local LLMs don't stall on huge dashboard JSON."""

    dash = digest.get("dashboard") if isinstance(digest, dict) else {}
    panels = digest.get("panels") if isinstance(digest, dict) else []

    out: dict[str, Any] = {
        "dashboard": {
            "uid": (dash or {}).get("uid"),
            "title": (dash or {}).get("title"),
            "timezone": (dash or {}).get("timezone"),
            "time": (dash or {}).get("time"),
            "refresh": (dash or {}).get("refresh"),
            "tags": (dash or {}).get("tags"),
        },
        "counts": digest.get("counts"),
        "templating": digest.get("templating"),
        "panels": [],
    }

    if not isinstance(panels, list):
        return out

    compact_panels: list[dict[str, Any]] = []
    for p in panels:
        if not isinstance(p, dict):
            continue
        ds = p.get("datasource") if isinstance(p.get("datasource"), dict) else {}
        targets = p.get("targets") if isinstance(p.get("targets"), list) else []

        compact_targets: list[dict[str, Any]] = []
        for t in targets:
            if not isinstance(t, dict):
                continue
            compact_targets.append(
                {
                    "refId": t.get("refId"),
                    "type": t.get("type"),
                    "seriesType": t.get("seriesType"),
                    "queryType": t.get("queryType"),
                    "metricGroup": t.get("metricGroup"),
                    "metric": t.get("metric"),
                    "target": t.get("target"),
                    "targetType": t.get("targetType"),
                    "expr": _clip(t.get("expr"), max_query_len),
                }
            )

        compact_panels.append(
            {
                "id": p.get("id"),
                "title": p.get("title"),
                "type": p.get("type"),
                "description": _clip(p.get("description"), 220),
                "datasource": {"type": ds.get("type"), "uid": ds.get("uid")},
                "fieldConfig": p.get("fieldConfig"),
                "targets": compact_targets,
            }
        )

    out["panels"] = compact_panels
    return out


def _compact_non_timeseries(nt: Any) -> Any:
    """Trim potentially-large non-timeseries summaries coming from the panel plugin."""

    if not isinstance(nt, dict):
        return None

    derived = nt.get("derived") if isinstance(nt.get("derived"), dict) else {}

    scalars = nt.get("scalars")
    if not isinstance(scalars, list):
        scalars = []
    compact_scalars: list[dict[str, Any]] = []
    for s in scalars[:12]:
        if not isinstance(s, dict):
            continue
        compact_scalars.append(
            {
                "field": _clip(s.get("field"), 120),
                "value": s.get("value"),
                "unit": _clip(s.get("unit"), 32),
            }
        )

    categories = nt.get("categories")
    if not isinstance(categories, list):
        categories = []
    compact_categories: list[dict[str, Any]] = []
    for c in categories[:10]:
        if not isinstance(c, dict):
            continue
        top = c.get("top")
        if not isinstance(top, list):
            top = []
        compact_top: list[dict[str, Any]] = []
        for t in top[:6]:
            if not isinstance(t, dict):
                continue
            compact_top.append({"value": _clip(t.get("value"), 120), "count": t.get("count")})
        if compact_top:
            compact_categories.append({"field": _clip(c.get("field"), 120), "top": compact_top})

    tables = nt.get("tables")
    if not isinstance(tables, list):
        tables = []
    compact_tables: list[dict[str, Any]] = []
    for t in tables[:3]:
        if not isinstance(t, dict):
            continue
        cols = t.get("columns")
        if not isinstance(cols, list):
            cols = []
        sample = t.get("sample_rows")
        if not isinstance(sample, list):
            sample = []
        compact_rows: list[dict[str, Any]] = []
        for r in sample[:6]:
            if not isinstance(r, dict):
                continue
            row_out: dict[str, Any] = {}
            for k, v in r.items():
                key = _clip(k, 80)
                if key is None:
                    continue
                if isinstance(v, str):
                    row_out[key] = _clip(v, 220)
                else:
                    row_out[key] = v
            if row_out:
                compact_rows.append(row_out)
        compact_tables.append(
            {
                "columns": [str(x)[:80] for x in cols[:20]],
                "row_count": t.get("row_count"),
                "sample_rows": compact_rows,
            }
        )

    return {
        "derived": {
            "up_down": derived.get("up_down"),
            "blocking_rows": derived.get("blocking_rows"),
            "row_lock_contention_rows": derived.get("row_lock_contention_rows"),
        },
        "scalars": compact_scalars,
        "categories": compact_categories,
        "tables": compact_tables,
    }


def compact_timeseries_summary_for_llm(summary: dict[str, Any] | None, *, max_panels: int = 20) -> dict[str, Any] | None:
    """Trim time-series summaries to keep prompts small and focused."""

    if summary is None or not isinstance(summary, dict):
        return None

    panels = summary.get("panels")
    if not isinstance(panels, list):
        panels = []

    compact_panels: list[dict[str, Any]] = []
    for p in panels[:max_panels]:
        if not isinstance(p, dict):
            continue

        series = p.get("series")
        if not isinstance(series, list):
            series = []

        compact_series: list[dict[str, Any]] = []
        for s in series[:12]:
            if not isinstance(s, dict):
                continue
            compact_series.append(
                {
                    "series_name": _clip(s.get("series_name"), 120),
                    "points": s.get("points"),
                    "stats": s.get("stats"),
                    "anomalies": s.get("anomalies"),
                    "strongest_score": s.get("strongest_score"),
                    "last_time_ms": s.get("last_time_ms"),
                    "last_value": s.get("last_value"),
                    "peak_time_ms": s.get("peak_time_ms"),
                    "peak_value": s.get("peak_value"),
                    "pct_change": s.get("pct_change"),
                    "sample_last_points": (s.get("sample_last_points") or [])[:6],
                }
            )

        compact_panels.append(
            {
                "panel_id": p.get("panel_id"),
                "panel_title": _clip(p.get("panel_title"), 140),
                "panel_type": p.get("panel_type"),
                "datasource_type": p.get("datasource_type"),
                "datasource_uid": p.get("datasource_uid"),
                "series_total": p.get("series_total"),
                "series_with_anomalies": p.get("series_with_anomalies"),
                "skipped_reason": _clip(p.get("skipped_reason"), 220),
                "error": _clip(p.get("error"), 220),
                "series": compact_series,
                "non_timeseries": _compact_non_timeseries(p.get("non_timeseries")),
            }
        )

    return {
        "enabled": summary.get("enabled"),
        "from_ms": summary.get("from_ms"),
        "to_ms": summary.get("to_ms"),
        "z_threshold": summary.get("z_threshold"),
        "panels_analyzed": summary.get("panels_analyzed"),
        "panels": compact_panels,
    }
