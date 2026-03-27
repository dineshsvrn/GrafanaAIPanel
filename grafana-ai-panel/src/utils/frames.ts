export type GrafanaFrame = {
  schema?: { fields?: Array<{ name?: string; type?: any }> };
  data?: { values?: any[][] };
  fields?: Array<{ name?: string; type?: any; values?: any }>;
};

export type GrafanaQueryResponse = {
  results?: Record<string, { frames?: GrafanaFrame[]; dataframes?: GrafanaFrame[]; error?: string }>;
};

function stripOradbPrefix(name: string): string {
  const p = 'ORADB_ORADB';
  return name.startsWith(p) ? name.slice(p.length) : name;
}

function fieldType(field: any): string | undefined {
  const t = field?.type;
  if (typeof t === 'string') {
    return t;
  }
  if (t && typeof t.type === 'string') {
    return t.type;
  }
  return undefined;
}

function coerceVector(v: any): any[] | undefined {
  if (Array.isArray(v)) return v;
  // Grafana sometimes serializes "values" as { buffer: [...] }
  if (v && Array.isArray((v as any).buffer)) return (v as any).buffer;
  // Some plugins return { values: [...] }
  if (v && Array.isArray((v as any).values)) return (v as any).values;
  return undefined;
}

function frameFields(frame: any): any[] {
  const f1 = frame?.schema?.fields;
  if (Array.isArray(f1)) return f1;
  const f2 = frame?.fields;
  if (Array.isArray(f2)) return f2;
  return [];
}

function frameValues(frame: any, fieldIdx: number): any[] | undefined {
  const dv = frame?.data?.values;
  if (Array.isArray(dv) && Array.isArray(dv[fieldIdx])) {
    return dv[fieldIdx];
  }
  const f = frame?.fields?.[fieldIdx];
  if (f) {
    return coerceVector(f.values);
  }
  return undefined;
}

function coerceTimeMs(v: any): number | undefined {
  if (v == null) return undefined;
  if (typeof v === 'number') return Math.trunc(v);
  if (typeof v === 'string') {
    const s = v.trim();
    if (!s) return undefined;
    if (/^\d+$/.test(s)) return parseInt(s, 10);
    const dt = Date.parse(s);
    if (!Number.isNaN(dt)) return dt;
  }
  return undefined;
}

function isNumber(v: any): boolean {
  return typeof v === 'number' && Number.isFinite(v);
}

export type TimeSeries = { name: string; points: Array<[number, number]> };

export function parseGrafanaQueryResponse(resp: GrafanaQueryResponse): TimeSeries[] {
  const results = resp?.results;
  if (!results) return [];

  const out: TimeSeries[] = [];

  for (const [refId, r] of Object.entries(results)) {
    const frames = (r.frames ?? r.dataframes ?? []).filter(Boolean);
    for (const frame of frames) {
      const fields = frameFields(frame);
      if (!fields.length) continue;

      // Find time field index
      let timeIdx: number | undefined;
      for (let i = 0; i < fields.length; i++) {
        const f = fields[i];
        const name = String(f?.name ?? '').toLowerCase();
        const t = fieldType(f);
        if (t === 'time' || name === 'time' || name === 'time_sec' || name === 'timestamp') {
          timeIdx = i;
          break;
        }
      }
      if (timeIdx == null) continue;

      const timeValuesRaw = frameValues(frame, timeIdx);
      if (!timeValuesRaw || timeValuesRaw.length === 0) continue;

      // For each other numeric field, build points.
      for (let j = 0; j < fields.length; j++) {
        if (j === timeIdx) continue;

        const colRaw = frameValues(frame, j);
        if (!colRaw || colRaw.length === 0) continue;
        if (!colRaw.some(isNumber)) continue;

        const seriesNameRaw = String(fields[j]?.name ?? refId);
        const seriesName = stripOradbPrefix(seriesNameRaw);

        const pts: Array<[number, number]> = [];
        for (let k = 0; k < Math.min(timeValuesRaw.length, colRaw.length); k++) {
          const tMs = coerceTimeMs(timeValuesRaw[k]);
          const v = colRaw[k];
          if (tMs == null || v == null) continue;
          if (isNumber(v)) pts.push([tMs, v]);
        }
        if (pts.length) out.push({ name: seriesName, points: pts });
      }
    }
  }

  return out;
}
