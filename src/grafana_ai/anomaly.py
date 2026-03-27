from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SeriesPoint:
    t_ms: int
    value: float


@dataclass(frozen=True)
class Anomaly:
    t_ms: int
    value: float
    score: float


def robust_z_anomalies(points: Iterable[SeriesPoint], *, z_threshold: float = 6.0) -> list[Anomaly]:
    pts = list(points)
    if len(pts) < 8:
        return []

    values = [p.value for p in pts]
    values_sorted = sorted(values)
    mid = len(values_sorted) // 2
    median = values_sorted[mid] if len(values_sorted) % 2 else (values_sorted[mid - 1] + values_sorted[mid]) / 2.0

    abs_dev = [abs(v - median) for v in values]
    abs_dev_sorted = sorted(abs_dev)
    mid2 = len(abs_dev_sorted) // 2
    mad = abs_dev_sorted[mid2] if len(abs_dev_sorted) % 2 else (abs_dev_sorted[mid2 - 1] + abs_dev_sorted[mid2]) / 2.0

    # Consistent with stddev for normal distributions
    scale = 1.4826 * mad
    if scale <= 1e-12:
        return []

    out: list[Anomaly] = []
    for p in pts:
        z = (p.value - median) / scale
        if abs(z) >= z_threshold:
            out.append(Anomaly(t_ms=p.t_ms, value=p.value, score=float(z)))
    return out
