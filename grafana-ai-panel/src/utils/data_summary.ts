function fieldType(field: any): string | undefined {
  const t = field?.type;
  if (typeof t === 'string') return t;
  if (t && typeof t.type === 'string') return t.type;
  return undefined;
}

function coerceVector(v: any): any[] | undefined {
  if (Array.isArray(v)) return v;
  if (v && Array.isArray(v.buffer)) return v.buffer;
  if (v && Array.isArray(v.values)) return v.values;
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
  if (Array.isArray(dv) && Array.isArray(dv[fieldIdx])) return dv[fieldIdx];
  const f = frame?.fields?.[fieldIdx];
  if (f) return coerceVector(f.values);
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

function isString(v: any): boolean {
  return typeof v === 'string' && v.trim().length > 0;
}

function findTimeFieldIndex(fields: any[]): number | undefined {
  for (let i = 0; i < fields.length; i++) {
    const f = fields[i];
    const name = String(f?.name ?? '').toLowerCase();
    const t = fieldType(f);
    if (t === 'time' || name === 'time' || name === 'time_sec' || name === 'timestamp') return i;
  }
  return undefined;
}

function topCounts(values: any[], max: number): Array<{ value: string; count: number }> {
  const m = new Map<string, number>();
  for (const v of values) {
    if (!isString(v)) continue;
    const s = String(v);
    m.set(s, (m.get(s) ?? 0) + 1);
  }
  const arr = [...m.entries()].map(([value, count]) => ({ value, count }));
  arr.sort((a, b) => b.count - a.count);
  return arr.slice(0, max);
}

function rowHasSubstring(row: Record<string, any>, needles: string[]): boolean {
  const hay = Object.values(row)
    .filter((v) => v != null)
    .map((v) => String(v).toLowerCase())
    .join(' | ');
  return needles.some((n) => hay.includes(n));
}

function looksLikeBlockingTable(columns: string[]): boolean {
  const cols = columns.map((c) => c.toLowerCase());
  const hasBlocker = cols.some((c) => c.includes('blocker') || c.includes('blocking'));
  const hasSid = cols.some((c) => c === 'sid' || c.includes('sid'));
  const hasSql = cols.some((c) => c.includes('sql_id') || c.includes('sqlid'));
  return hasBlocker && (hasSid || hasSql);
}

export type FrameShape = { name?: string; type?: string; len?: number };

export type NonTimeseriesSummary = {
  scalars: Array<{ field: string; value: number; unit?: string }>;
  categories: Array<{ field: string; top: Array<{ value: string; count: number }> }>;
  tables: Array<{ columns: string[]; row_count: number; sample_rows: Array<Record<string, any>> }>;
  derived: {
    up_down: Array<{ field: string; value: string }>;
    blocking_rows: number;
    row_lock_contention_rows: number;
  };
  shapes: FrameShape[];
};

export function summarizeNonTimeseries(
  frames: any[],
  opts?: { maxRows?: number; maxCategory?: number; maxShapes?: number; fullTableRowLimit?: number }
): NonTimeseriesSummary {
  const maxRows = opts?.maxRows ?? 6;
  const maxCategory = opts?.maxCategory ?? 6;
  const maxShapes = opts?.maxShapes ?? 60;
  const fullTableRowLimit = opts?.fullTableRowLimit ?? 50;

  const scalars: NonTimeseriesSummary['scalars'] = [];
  const categories: NonTimeseriesSummary['categories'] = [];
  const tables: NonTimeseriesSummary['tables'] = [];
  const shapes: NonTimeseriesSummary['shapes'] = [];

  const derived = {
    up_down: [] as Array<{ field: string; value: string }>,
    blocking_rows: 0,
    row_lock_contention_rows: 0,
  };

  for (const frame of frames ?? []) {
    const fields = frameFields(frame);
    if (!fields.length) continue;

    const timeIdx = findTimeFieldIndex(fields);

    // Shape info
    for (let i = 0; i < fields.length; i++) {
      const f = fields[i];
      const col = frameValues(frame, i);
      shapes.push({
        name: String(f?.name ?? ''),
        type: fieldType(f),
        len: Array.isArray(col) ? col.length : undefined,
      });
    }

    const cols: Array<{ name: string; values: any[]; unit?: string }> = [];
    let rowCount = 0;
    for (let i = 0; i < fields.length; i++) {
      const name = String(fields[i]?.name ?? `field_${i}`);
      const unit = (frame as any)?.fields?.[i]?.config?.unit;
      const col = frameValues(frame, i) ?? [];
      const values = Array.isArray(col) ? col : [];
      cols.push({ name, values, unit });
      rowCount = Math.max(rowCount, values.length);
    }

    if (rowCount === 0) continue;

    // If there is a time field, create a "latest snapshot" from the last timestamp.
    if (timeIdx != null) {
      const tvals = cols[timeIdx]?.values ?? [];
      let lastIdx: number | undefined;
      let bestT = -Infinity;
      for (let i = 0; i < tvals.length; i++) {
        const tms = coerceTimeMs(tvals[i]);
        if (tms != null && tms >= bestT) {
          bestT = tms;
          lastIdx = i;
        }
      }
      if (lastIdx == null) lastIdx = Math.max(0, rowCount - 1);

      for (let c = 0; c < cols.length; c++) {
        if (c === timeIdx) continue;
        const col = cols[c];
        const v = col.values[lastIdx];
        if (isNumber(v)) {
          scalars.push({ field: col.name, value: v, unit: col.unit });
        } else if (isString(v)) {
          categories.push({ field: col.name, top: [{ value: String(v), count: 1 }] });
          const s = String(v).trim();
          if (s === 'Up' || s === 'UP' || s === 'Down' || s === 'DOWN') {
            derived.up_down.push({ field: col.name, value: s });
          }
        }
      }

      // For time+string frames, add top counts.
      for (let c = 0; c < cols.length; c++) {
        if (c === timeIdx) continue;
        const col = cols[c];
        if (col.values.some(isString)) {
          const top = topCounts(col.values, maxCategory);
          if (top.length) categories.push({ field: col.name, top });
        }
      }

      continue;
    }

    // No time field.
    if (rowCount === 1) {
      for (const col of cols) {
        const v = col.values[0];
        if (isNumber(v)) {
          scalars.push({ field: col.name, value: v, unit: col.unit });
        } else if (isString(v)) {
          const s = String(v).trim();
          categories.push({ field: col.name, top: [{ value: s, count: 1 }] });
          if (s === 'Up' || s === 'UP' || s === 'Down' || s === 'DOWN') {
            derived.up_down.push({ field: col.name, value: s });
          }
        }
      }
      continue;
    }

    // Multi-row -> table + categories.
    const columns = cols.map((c) => c.name);
    const sampleLimit = rowCount <= fullTableRowLimit ? rowCount : maxRows;

    const sample_rows: Array<Record<string, any>> = [];
    for (let r = 0; r < Math.min(rowCount, sampleLimit); r++) {
      const row: Record<string, any> = {};
      for (const col of cols) {
        row[col.name] = col.values[r];
      }
      sample_rows.push(row);
    }
    tables.push({ columns, row_count: rowCount, sample_rows });
    // Derived counts for common OEM problems
    if (looksLikeBlockingTable(columns)) {
      derived.blocking_rows += rowCount;
    }
    for (const row of sample_rows) {
      if (rowHasSubstring(row, ['row lock contention', 'enq: tx', 'tx - row lock'])) {
        derived.row_lock_contention_rows++;
      }
    }

    for (const col of cols) {
      if (col.values.some(isString)) {
        const top = topCounts(col.values, maxCategory);
        if (top.length) categories.push({ field: col.name, top });
      }
    }
  }

  return { scalars, categories, tables, derived, shapes: shapes.slice(0, maxShapes) };
}
