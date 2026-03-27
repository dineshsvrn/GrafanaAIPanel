from __future__ import annotations

from typing import Any


def _take_str(value: Any, max_len: int = 600) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return None
    if len(value) > max_len:
        return value[: max_len - 3] + "..."
    return value


def _summarize_targets(targets: Any, max_targets: int) -> list[dict[str, Any]]:
    if not isinstance(targets, list):
        return []
    summarized: list[dict[str, Any]] = []
    for t in targets[:max_targets]:
        if not isinstance(t, dict):
            continue
        summarized.append(
            {
                "refId": t.get("refId"),
                "queryType": t.get("queryType"),
                "seriesType": t.get("seriesType"),
                "type": t.get("type"),
                "target": t.get("target") or t.get("targetName"),
                "targetType": t.get("targetType"),
                "metricGroup": t.get("metricGroup"),
                "metric": t.get("metric"),
                "expr": _take_str(t.get("expr") or t.get("expression") or t.get("query") or t.get("rawSql") or t.get("rawQuery")),
                "legendFormat": _take_str(t.get("legendFormat") or t.get("alias")),
                "format": t.get("format"),
                "datasource": t.get("datasource"),
            }
        )
    return summarized


def _summarize_field_config(field_config: Any) -> dict[str, Any]:
    if not isinstance(field_config, dict):
        return {}
    defaults = field_config.get("defaults")
    overrides = field_config.get("overrides")
    out: dict[str, Any] = {}
    if isinstance(defaults, dict):
        thresholds = defaults.get("thresholds")
        out["defaults"] = {
            "unit": defaults.get("unit"),
            "decimals": defaults.get("decimals"),
            "min": defaults.get("min"),
            "max": defaults.get("max"),
            "thresholds": thresholds.get("steps") if isinstance(thresholds, dict) else None,
            "noValue": defaults.get("noValue"),
            "mappings": defaults.get("mappings"),
        }
    if isinstance(overrides, list):
        out["overrides_count"] = len(overrides)
    return out


def build_dashboard_digest(
    dashboard_payload: dict[str, Any],
    *,
    max_panels: int = 60,
    max_targets_per_panel: int = 6,
) -> dict[str, Any]:
    dashboard = dashboard_payload.get("dashboard") if isinstance(dashboard_payload, dict) else None
    meta = dashboard_payload.get("meta") if isinstance(dashboard_payload, dict) else None
    if not isinstance(dashboard, dict):
        raise ValueError("dashboard_payload must include a 'dashboard' object.")

    panels_raw = dashboard.get("panels") or []
    if not isinstance(panels_raw, list):
        panels_raw = []

    templating = (dashboard.get("templating") or {}).get("list") if isinstance(dashboard.get("templating"), dict) else []
    if not isinstance(templating, list):
        templating = []

    digest: dict[str, Any] = {
        "dashboard": {
            "uid": dashboard.get("uid"),
            "id": dashboard.get("id"),
            "title": dashboard.get("title"),
            "tags": dashboard.get("tags"),
            "timezone": dashboard.get("timezone"),
            "refresh": dashboard.get("refresh"),
            "time": dashboard.get("time"),
            "timepicker": dashboard.get("timepicker"),
            "schemaVersion": dashboard.get("schemaVersion"),
            "version": dashboard.get("version"),
        },
        "meta": {
            "slug": meta.get("slug") if isinstance(meta, dict) else None,
            "folderTitle": meta.get("folderTitle") if isinstance(meta, dict) else None,
            "created": meta.get("created") if isinstance(meta, dict) else None,
            "updated": meta.get("updated") if isinstance(meta, dict) else None,
        },
        "templating": [
            {
                "name": v.get("name"),
                "type": v.get("type"),
                "label": v.get("label"),
                "query": _take_str(v.get("query")),
                "current": v.get("current"),
                "hide": v.get("hide"),
            }
            for v in templating
            if isinstance(v, dict)
        ],
        "panels": [],
        "counts": {
            "panels_total": len(panels_raw),
            "templating_vars": len(templating),
        },
    }

    panels_out: list[dict[str, Any]] = []
    for p in panels_raw[:max_panels]:
        if not isinstance(p, dict):
            continue
        panels_out.append(
            {
                "id": p.get("id"),
                "type": p.get("type"),
                "title": p.get("title"),
                "description": _take_str(p.get("description")),
                "datasource": p.get("datasource"),
                "gridPos": p.get("gridPos"),
                "fieldConfig": _summarize_field_config(p.get("fieldConfig")),
                "targets": _summarize_targets(p.get("targets"), max_targets_per_panel),
            }
        )

    digest["panels"] = panels_out
    digest["counts"]["panels_included"] = len(panels_out)
    digest["counts"]["panels_truncated"] = max(0, len(panels_raw) - len(panels_out))
    return digest
