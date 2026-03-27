from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TimeSeries:
    name: str
    points: list[tuple[int, float]]


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _extract_frames(result_obj: Any) -> list[dict[str, Any]]:
    if not isinstance(result_obj, dict):
        return []

    for key in ("frames", "dataframes"):
        frames = result_obj.get(key)
        if isinstance(frames, list):
            return [f for f in frames if isinstance(f, dict)]

    return []


def _field_type(field: dict[str, Any]) -> str | None:
    t = field.get("type")
    if isinstance(t, str):
        return t
    if isinstance(t, dict) and isinstance(t.get("type"), str):
        return t.get("type")
    return None


def _coerce_time_ms(t: Any) -> int | None:
    if t is None:
        return None
    if isinstance(t, str):
        s = t.strip()
        if not s:
            return None
        if s.isdigit():
            return int(s)
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            return None
    if _is_number(t):
        return int(t)
    return None


def parse_grafana_query_response(resp_json: dict[str, Any]) -> list[TimeSeries]:
    results = resp_json.get("results") if isinstance(resp_json, dict) else None
    if not isinstance(results, dict):
        return []

    series: list[TimeSeries] = []

    for ref_id, result_obj in results.items():
        frames = _extract_frames(result_obj)
        for frame in frames:
            schema = frame.get("schema")
            data = frame.get("data")
            if not isinstance(schema, dict) or not isinstance(data, dict):
                continue

            fields = schema.get("fields")
            values = data.get("values")
            if not isinstance(fields, list) or not isinstance(values, list):
                continue
            if len(fields) != len(values) or len(fields) == 0:
                continue

            time_idx = None
            for i, f in enumerate(fields):
                if not isinstance(f, dict):
                    continue
                name = str(f.get("name") or "").lower()
                ftype = _field_type(f)
                if ftype == "time" or name in {"time", "time_sec", "ts", "timestamp"}:
                    time_idx = i
                    break

            if time_idx is None:
                continue

            time_values = values[time_idx]
            if not isinstance(time_values, list) or not time_values:
                continue

            for j, f in enumerate(fields):
                if j == time_idx:
                    continue
                if not isinstance(values[j], list):
                    continue
                if not any(_is_number(v) for v in values[j]):
                    continue

                field_name = f.get("name") if isinstance(f, dict) else None
                series_name = str(field_name or ref_id)

                pts: list[tuple[int, float]] = []
                for t, v in zip(time_values, values[j]):
                    t_ms = _coerce_time_ms(t)
                    if t_ms is None or v is None:
                        continue
                    if _is_number(v):
                        pts.append((t_ms, float(v)))

                if pts:
                    series.append(TimeSeries(name=series_name, points=pts))

    return series
