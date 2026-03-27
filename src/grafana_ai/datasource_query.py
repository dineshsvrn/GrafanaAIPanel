from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _parse_interval_to_ms(interval: Any) -> int | None:
    if interval is None:
        return None
    if isinstance(interval, (int, float)):
        return int(interval)
    s = str(interval).strip().lower()
    if not s:
        return None

    num = ""
    unit = ""
    for ch in s:
        if ch.isdigit():
            num += ch
        else:
            unit += ch
    if not num:
        return None

    n = int(num)
    unit = unit.strip()
    mult = {
        "ms": 1,
        "s": 1000,
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
    }.get(unit)
    if mult is None:
        return None
    return n * mult


@dataclass(frozen=True)
class PanelQuery:
    ref_id: str
    model: dict[str, Any]


def build_panel_queries(panel: dict[str, Any]) -> list[PanelQuery]:
    datasource = panel.get("datasource") if isinstance(panel, dict) else None
    if not isinstance(datasource, dict):
        datasource = None

    targets = panel.get("targets") if isinstance(panel, dict) else None
    if not isinstance(targets, list):
        return []

    interval_ms = _parse_interval_to_ms(panel.get("interval"))
    max_data_points = panel.get("maxDataPoints")
    if not isinstance(max_data_points, int) or max_data_points <= 0:
        max_data_points = 1000

    out: list[PanelQuery] = []
    for t in targets:
        if not isinstance(t, dict):
            continue

        ref_id = t.get("refId") or "A"
        if not isinstance(ref_id, str):
            ref_id = str(ref_id)

        model = dict(t)
        model["refId"] = ref_id

        # Force panel datasource, because dashboards often override target.datasource with variables.
        if datasource is not None:
            model["datasource"] = datasource

        if interval_ms is not None:
            model.setdefault("intervalMs", interval_ms)
        model.setdefault("maxDataPoints", max_data_points)

        out.append(PanelQuery(ref_id=ref_id, model=model))

    return out
