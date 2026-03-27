export function robustZAnomalies(points: Array<[number, number]>, zThreshold: number): { count: number; strongest?: number } {
  if (points.length < 8) return { count: 0 };
  const values = points.map((p) => p[1]);
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;

  const absDev = values.map((v) => Math.abs(v - median));
  const absSorted = [...absDev].sort((a, b) => a - b);
  const mid2 = Math.floor(absSorted.length / 2);
  const mad = absSorted.length % 2 ? absSorted[mid2] : (absSorted[mid2 - 1] + absSorted[mid2]) / 2;
  const scale = 1.4826 * mad;
  if (scale <= 1e-12) return { count: 0 };

  let count = 0;
  let strongest = 0;
  for (const [, v] of points) {
    const z = (v - median) / scale;
    if (Math.abs(z) >= zThreshold) {
      count++;
      strongest = Math.max(strongest, Math.abs(z));
    }
  }
  return count ? { count, strongest } : { count: 0 };
}

export function basicStats(points: Array<[number, number]>): { points: number; first?: number; last?: number; min?: number; max?: number; mean?: number; delta?: number } {
  if (!points.length) return { points: 0 };
  const pts = [...points].sort((a, b) => a[0] - b[0]);
  const values = pts.map((p) => p[1]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const first = pts[0][1];
  const last = pts[pts.length - 1][1];
  return { points: pts.length, first, last, min, max, mean, delta: last - first };
}
