from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable


@dataclass(frozen=True)
class SeriesStats:
    points: int
    first_t_ms: int | None
    last_t_ms: int | None
    first: float | None
    last: float | None
    min: float | None
    max: float | None
    mean: float | None
    stdev: float | None
    delta: float | None


def compute_stats(points: Iterable[tuple[int, float]]) -> SeriesStats:
    pts = list(points)
    if not pts:
        return SeriesStats(
            points=0,
            first_t_ms=None,
            last_t_ms=None,
            first=None,
            last=None,
            min=None,
            max=None,
            mean=None,
            stdev=None,
            delta=None,
        )

    pts_sorted = sorted(pts, key=lambda x: x[0])
    values = [v for _, v in pts_sorted]

    n = len(values)
    vmin = min(values)
    vmax = max(values)
    mean = sum(values) / n

    if n >= 2:
        var = sum((v - mean) ** 2 for v in values) / (n - 1)
        stdev = sqrt(var)
    else:
        stdev = 0.0

    first_t, first_v = pts_sorted[0]
    last_t, last_v = pts_sorted[-1]

    return SeriesStats(
        points=n,
        first_t_ms=int(first_t),
        last_t_ms=int(last_t),
        first=float(first_v),
        last=float(last_v),
        min=float(vmin),
        max=float(vmax),
        mean=float(mean),
        stdev=float(stdev),
        delta=float(last_v - first_v),
    )
