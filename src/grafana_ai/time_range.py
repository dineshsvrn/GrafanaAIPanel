from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal


TimeExpr = str | int | float | None


@dataclass(frozen=True)
class TimeRange:
    from_ms: int
    to_ms: int


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _parse_now_offset(expr: str, now_ms: int) -> int | None:
    expr = expr.strip().lower()
    if expr == "now":
        return now_ms

    sign: Literal["+", "-"]
    if expr.startswith("now-"):
        sign = "-"
        offset = expr[4:]
    elif expr.startswith("now+"):
        sign = "+"
        offset = expr[4:]
    else:
        return None

    # offset: <int><unit>, unit in s,m,h,d,w
    num = ""
    unit = ""
    for ch in offset:
        if ch.isdigit():
            num += ch
        else:
            unit += ch
    if not num or not unit:
        return None

    n = int(num)
    unit = unit.strip()
    mult_s = {
        "s": 1,
        "sec": 1,
        "secs": 1,
        "m": 60,
        "min": 60,
        "mins": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800,
    }.get(unit)
    if mult_s is None:
        return None

    delta_ms = int(n * mult_s * 1000)
    return now_ms - delta_ms if sign == "-" else now_ms + delta_ms


def parse_time_ms(expr: TimeExpr, *, now_ms: int | None = None) -> int:
    if now_ms is None:
        now_ms = _now_ms()

    if expr is None:
        return now_ms

    if isinstance(expr, (int, float)):
        # assume ms
        return int(expr)

    s = str(expr).strip()
    if not s:
        return now_ms

    # epoch ms
    if s.isdigit():
        return int(s)

    # ISO
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        pass

    # Grafana-ish now offsets
    v = _parse_now_offset(s, now_ms)
    if v is not None:
        return v

    raise ValueError(f"Unsupported time expression: {expr!r}")


def resolve_time_range(
    *,
    from_expr: TimeExpr,
    to_expr: TimeExpr,
    default_from_expr: TimeExpr = "now-12h",
    default_to_expr: TimeExpr = "now",
    now_ms: int | None = None,
) -> TimeRange:
    if now_ms is None:
        now_ms = _now_ms()

    from_ms = parse_time_ms(from_expr or default_from_expr, now_ms=now_ms)
    to_ms = parse_time_ms(to_expr or default_to_expr, now_ms=now_ms)

    if to_ms < from_ms:
        # Swap to avoid Grafana API errors; better than failing hard.
        from_ms, to_ms = to_ms, from_ms

    # Clamp ranges that are too tiny/negative due to parsing quirks.
    if to_ms == from_ms:
        to_ms = from_ms + int(timedelta(minutes=5).total_seconds() * 1000)

    return TimeRange(from_ms=from_ms, to_ms=to_ms)
