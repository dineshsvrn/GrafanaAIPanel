export function detectDashboardUid(pathname: string): string | undefined {
  // Typical: /d/<uid>/<slug>
  const m = pathname.match(/\/d\/([^/]+)\//);
  return m?.[1];
}

function nowMs(): number {
  return Date.now();
}

export function parseTimeMs(expr: string): number {
  const s = (expr || '').trim();
  if (!s) {
    return nowMs();
  }
  if (/^\d+$/.test(s)) {
    return parseInt(s, 10);
  }
  if (s === 'now') {
    return nowMs();
  }
  const m = s.match(/^now([+-])(\d+)(s|m|h|d|w)$/);
  if (m) {
    const sign = m[1];
    const n = parseInt(m[2], 10);
    const unit = m[3];
    const mult: Record<string, number> = { s: 1000, m: 60_000, h: 3_600_000, d: 86_400_000, w: 604_800_000 };
    const delta = n * (mult[unit] ?? 0);
    return sign === '-' ? nowMs() - delta : nowMs() + delta;
  }
  const dt = Date.parse(s);
  if (!Number.isNaN(dt)) {
    return dt;
  }
  throw new Error(`Unsupported time expression: ${expr}`);
}
