import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { dateTime, PanelProps } from '@grafana/data';
import { getBackendSrv, getDataSourceSrv, getTemplateSrv } from '@grafana/runtime';
import { lastValueFrom } from 'rxjs';

import { AiPanelOptions } from '../types';
import { buildCompactDigest } from '../utils/digest';
import { summarizeNonTimeseries } from '../utils/data_summary';
import { parseGrafanaQueryResponse } from '../utils/frames';
import { basicStats, robustZAnomalies } from '../utils/stats';
import { detectDashboardUid } from '../utils/time';

type Props = PanelProps<AiPanelOptions>;

type PanelSummary = {
  panel_id?: number;
  panel_title?: string;
  panel_type?: string;
  datasource_type?: string;
  datasource_uid?: string;
  series_total?: number;
  series_with_anomalies?: number;
  series?: any[];
  error?: string;
  error_details?: string;
  non_timeseries?: any;
};

type RunStats = {
  panels_queried: number;
  panels_with_data: number;
  panels_with_errors: number;
  series_total: number;
};

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function clip(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s;
  return s.slice(0, Math.max(0, maxLen - 3)) + '...';
}

function formatError(err: unknown): { summary: string; details: string } {
  if (typeof err === 'string') {
    return { summary: err, details: err };
  }

  const anyErr: any = err as any;
  const status = anyErr?.status ?? anyErr?.response?.status;
  const statusText = anyErr?.statusText ?? anyErr?.response?.statusText;

  const data = anyErr?.data ?? anyErr?.response?.data;
  const dataMessage = data?.message ?? data?.error ?? data?.detail;

  const message =
    anyErr?.message ??
    (typeof dataMessage === 'string' ? dataMessage : undefined) ??
    (status ? `${status}${statusText ? ` ${statusText}` : ''}` : undefined) ??
    'Unknown error';

  const detailsObj = {
    message: anyErr?.message,
    status,
    statusText,
    data,
    stack: anyErr?.stack,
  };

  return { summary: message, details: safeJson(detailsObj) };
}

function inferSeriesType(t: any): string | undefined {
  const raw = t?.seriesType ?? t?.series_type ?? t?.series;
  if (typeof raw === 'string' && raw.trim()) {
    return raw.trim();
  }

  // OEM/EMCC plugin typically needs one of these.
  if (t?.metricGroup || t?.metric) {
    return 'EM Metrics(Raw)';
  }
  if (t?.rawQuery || t?.rawSql) {
    return 'General Query(Repository)';
  }

  return undefined;
}

function isHiddenTarget(t: any): boolean {
  return t?.hide === true || t?.hidden === true;
}

function isUsableTarget(t: any): boolean {
  if (isHiddenTarget(t)) return false;
  const st = inferSeriesType(t);
  if (st) return true;
  const rq = t?.rawQuery ?? t?.rawSql;
  return typeof rq === 'string' && rq.trim().length > 0;
}

function deepInterpolate(templateSrv: any, v: any, depth = 0): any {
  if (depth > 6) return v;
  if (typeof v === 'string') {
    return v.includes('$') ? templateSrv.replace(v) : v;
  }
  if (Array.isArray(v)) {
    return v.map((x) => deepInterpolate(templateSrv, x, depth + 1));
  }
  if (v && typeof v === 'object') {
    const out: any = {};
    for (const [k, val] of Object.entries(v)) {
      out[k] = deepInterpolate(templateSrv, val, depth + 1);
    }
    return out;
  }
  return v;
}

function isValidEMMetricsQuery(q: any): boolean {
  const metricGroup = typeof q?.metricGroup === 'string' ? q.metricGroup.trim() : '';
  const metric = typeof q?.metric === 'string' ? q.metric.trim() : '';
  if (!metricGroup) {
    return false;
  }
  // Some OEM queries may omit metric but still be meaningful (tables/details).
  // If the datasource rejects it, we will capture and surface the error.
  void metric;
  return true;
}

function dsKeyOf(ref: any): string {
  if (!ref) return '';
  if (typeof ref === 'string') return ref;
  const uid = typeof ref.uid === 'string' ? ref.uid : '';
  const type = typeof ref.type === 'string' ? ref.type : '';
  if (uid && type) return `${type}:${uid}`;
  if (uid) return uid;
  if (type) return type;
  try {
    return JSON.stringify(ref);
  } catch {
    return String(ref);
  }
}

function stripDatasource(target: any): any {
  if (!target || typeof target !== 'object') return target;
  const { datasource, ...rest } = target;
  return rest;
}

function toGrafanaQueryResponseFromDataFrames(data: any[]): any {
  const results: any = {};
  for (const frame of data ?? []) {
    const refId = (frame as any)?.refId ?? (frame as any)?.meta?.refId ?? 'A';
    if (!results[refId]) {
      results[refId] = { frames: [] };
    }
    results[refId].frames.push(frame);
  }
  return { results };
}

function variablesFingerprint(): string {
  try {
    const templateSrv = getTemplateSrv();
    const vars = (templateSrv as any)?.getVariables?.() ?? [];
    if (!Array.isArray(vars)) return '';
    const parts = vars
      .map((v: any) => {
        const name = v?.name ?? '';
        const cur = v?.current;
        const val = cur?.value ?? cur?.text ?? '';
        const valStr = Array.isArray(val) ? val.join(',') : String(val);
        return `${name}=${valStr}`;
      })
      .sort();
    return parts.join('|');
  } catch {
    return '';
  }
}


function hasPanelData(p: any): boolean {
  if ((p?.series_total ?? 0) > 0) return true;
  const nt = p?.non_timeseries;
  if (!nt || typeof nt !== 'object') return false;
  const scalars = Array.isArray(nt.scalars) ? nt.scalars.length : 0;
  const cats = Array.isArray(nt.categories) ? nt.categories.length : 0;
  const tables = Array.isArray(nt.tables) ? nt.tables.length : 0;
  return scalars + cats + tables > 0;
}
async function mapLimit<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;

  const workers = new Array(Math.max(1, limit)).fill(0).map(async () => {
    for (;;) {
      const idx = next++;
      if (idx >= items.length) return;
      out[idx] = await fn(items[idx]);
    }
  });

  await Promise.all(workers);
  return out;
}

export const AiPanel: React.FC<Props> = ({ options, width, height, timeRange }) => {
  const [loading, setLoading] = useState(false);
  const [errorSummary, setErrorSummary] = useState<string | undefined>();
  const [errorDetails, setErrorDetails] = useState<string | undefined>();
  const [report, setReport] = useState<string>('');
  const [lastRunAt, setLastRunAt] = useState<number | undefined>();
  const [stats, setStats] = useState<RunStats | undefined>();
  const [progress, setProgress] = useState<{ done: number; total: number } | undefined>();

  const inferredUid = useMemo(() => detectDashboardUid(window.location.pathname), []);
  const dashboardUid = options.dashboardUid?.trim() || inferredUid;

  const runKey = useMemo(() => {
    const fromMs = Math.trunc(timeRange.from.valueOf());
    const toMs = Math.trunc(timeRange.to.valueOf());
    const vfp = variablesFingerprint();
    const opt = [
      options.aiServiceUrl,
      options.aiServiceToken ?? '',
      options.aiServiceApiKey ?? '',
      String(options.maxPanels),
      String(options.maxTargetsPerPanel),
      String(options.anomalyZ),
    ].join('|');
    return [dashboardUid ?? '', String(fromMs), String(toMs), vfp, opt].join('||');
  }, [dashboardUid, timeRange, options]);

  const inFlightRef = useRef(false);
  const lastRunKeyRef = useRef<string | undefined>();

  const run = useCallback(async () => {
    if (!dashboardUid) {
      setErrorSummary('Unable to detect dashboard UID. Set Dashboard UID in panel options.');
      setErrorDetails(undefined);
      return;
    }

    if (inFlightRef.current) {
      return;
    }

    inFlightRef.current = true;
    setLoading(true);
    setProgress(undefined);
    setErrorSummary(undefined);
    setErrorDetails(undefined);

    try {
      const templateSrv = getTemplateSrv();

      const fromMs = Math.trunc(timeRange.from.valueOf());
      const toMs = Math.trunc(timeRange.to.valueOf());

      const dash = await getBackendSrv().get(`/api/dashboards/uid/${dashboardUid}`);
      const digest = buildCompactDigest(dash, options.maxPanels, options.maxTargetsPerPanel);

      const panels: any[] = Array.isArray(dash?.dashboard?.panels)
        ? dash.dashboard.panels.slice(0, options.maxPanels)
        : [];

      const spanMs = Math.max(1, toMs - fromMs);
      const defaultIntervalMs = Math.max(2000, Math.floor(spanMs / 600));

      const candidates = panels.filter((p: any) => {
        const ds = p?.datasource;
        const targetsRaw: any[] = Array.isArray(p?.targets) ? p.targets.slice(0, options.maxTargetsPerPanel) : [];
        const targets = targetsRaw.filter(isUsableTarget);
        return Boolean(ds) && targets.length > 0;
      });

      setProgress({ done: 0, total: candidates.length });

      let done = 0;

      const panelResults = await mapLimit<any, PanelSummary | null>(candidates, 3, async (p) => {
        const panelDs = p?.datasource;
        const targetsRaw: any[] = Array.isArray(p?.targets) ? p.targets.slice(0, options.maxTargetsPerPanel) : [];

        const panelType = typeof p?.type === 'string' ? p.type : undefined;
        const targets = targetsRaw.filter(isUsableTarget);

        const grouped = new Map<string, { dsRef: any; targets: any[] }>();

        for (const t of targets) {
          const seriesType = inferSeriesType(t);
          if (!seriesType) continue;

          const t2 = deepInterpolate(templateSrv, t);
          if (seriesType === 'EM Metrics(Raw)' && !isValidEMMetricsQuery(t2)) {
            continue;
          }

          const dsRef = t2?.datasource ?? panelDs;
          const key = dsKeyOf(dsRef);
          if (!key) continue;

          const enriched = {
            ...t2,
            seriesType,
            refId: t2?.refId ?? 'A',
            intervalMs: typeof t2?.intervalMs === 'number' ? t2.intervalMs : defaultIntervalMs,
            maxDataPoints: 240,
            datasource: dsRef,
          };

          const g = grouped.get(key) ?? { dsRef, targets: [] };
          g.targets.push(enriched);
          grouped.set(key, g);
        }

        try {
          const allFrames: any[] = [];
          let firstError: any | undefined;

          for (const g of grouped.values()) {
            const dsApi: any = await getDataSourceSrv().get(g.dsRef);

            const req: any = {
              requestId: `dragonsage-ai-${dashboardUid}-${p?.id}-${Date.now()}`,
              timezone: Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'browser',
              app: 'dashboard',
              dashboardUID: dashboardUid,
              panelId: p?.id,
              range: timeRange,
              rangeRaw: (timeRange as any)?.raw ?? { from: dateTime(fromMs), to: dateTime(toMs) },
              intervalMs: defaultIntervalMs,
              maxDataPoints: 240,
              scopedVars: {},
              targets: g.targets.map((t) => stripDatasource(t)),
            };

            const resp: any = await lastValueFrom(dsApi.query(req));
            if (resp?.error) {
              firstError = resp.error;
              break;
            }
            if (Array.isArray(resp?.data)) {
              allFrames.push(...resp.data);
            }
          }

          if (firstError) {
            const fe = formatError(firstError);
            return {
              panel_id: p?.id,
              panel_title: p?.title,
              panel_type: panelType,
              datasource_type: panelDs?.type,
              datasource_uid: panelDs?.uid,
              error: fe.summary,
              error_details: clip(fe.details, 1200),
            };
          }

          const wrapped = toGrafanaQueryResponseFromDataFrames(allFrames);
          const series = parseGrafanaQueryResponse(wrapped);
          const nonTs = summarizeNonTimeseries(allFrames, { fullTableRowLimit: 50 });

          const seriesSummaries = series.slice(0, 12).map((s) => {
            const stats = basicStats(s.points);
            const an = robustZAnomalies(s.points, options.anomalyZ);
            const ptsSorted = [...s.points].sort((a, b) => a[0] - b[0]);
            const lastPts = ptsSorted.slice(-6);
            const last = lastPts.length ? lastPts[lastPts.length - 1] : undefined;
            let peak: [number, number] | undefined;
            for (const p of ptsSorted) {
              if (!peak || (typeof p[1] === 'number' && p[1] > peak[1])) {
                peak = p;
              }
            }
            const first = ptsSorted.length ? ptsSorted[0] : undefined;
            const lastValue = last ? last[1] : undefined;
            const firstValue = first ? first[1] : undefined;
            const pctChange =
              typeof lastValue === 'number' && typeof firstValue === 'number' && Math.abs(firstValue) > 1e-9
                ? (lastValue - firstValue) / firstValue
                : undefined;

            return {
              series_name: s.name,
              points: stats.points,
              stats,
              anomalies: an.count,
              strongest_score: an.strongest,
              last_time_ms: last ? last[0] : undefined,
              last_value: last ? last[1] : undefined,
              peak_time_ms: peak ? peak[0] : undefined,
              peak_value: peak ? peak[1] : undefined,
              pct_change: pctChange,
              sample_last_points: lastPts,
            };
          });

          return {
            panel_id: p?.id,
            panel_title: p?.title,
            panel_type: panelType,
            datasource_type: panelDs?.type,
            datasource_uid: panelDs?.uid,
            series_total: series.length,
            series_with_anomalies: seriesSummaries.filter((x) => x.anomalies > 0).length,
            series: seriesSummaries,
            non_timeseries: nonTs,
          };
        } catch (e: unknown) {
          const fe = formatError(e);
          return {
            panel_id: p?.id,
            panel_title: p?.title,
            panel_type: panelType,
            datasource_type: panelDs?.type,
            datasource_uid: panelDs?.uid,
            error: fe.summary,
            error_details: clip(fe.details, 1200),
          };
        } finally {
          done++;
          setProgress((prev) => ({ done, total: prev?.total ?? candidates.length }));
        }
      });

      const panelsSummary: PanelSummary[] = panelResults.filter(Boolean) as PanelSummary[];

      const computedStats: RunStats = {
        panels_queried: panelsSummary.length,
        panels_with_data: panelsSummary.filter((p) => hasPanelData(p)).length,
        panels_with_errors: panelsSummary.filter((p) => Boolean(p.error)).length,
        series_total: panelsSummary.reduce((acc, p) => acc + (p.series_total ?? 0), 0),
      };

      const timeseriesSummary = {
        enabled: true,
        from_ms: fromMs,
        to_ms: toMs,
        z_threshold: options.anomalyZ,
        panels_analyzed: panelsSummary.length,
        panels: panelsSummary,
      };

      const urlBase = options.aiServiceUrl.replace(/\/$/, '');
      const url = options.aiServiceToken
        ? `${urlBase}/analyze_payload?token=${encodeURIComponent(options.aiServiceToken)}`
        : `${urlBase}/analyze_payload`;

      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (options.aiServiceApiKey) {
        headers['X-API-Key'] = options.aiServiceApiKey;
      }

      const aiResp = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify({ dashboard_digest: digest, timeseries_summary: timeseriesSummary }),
      });

      if (!aiResp.ok) {
        const txt = await aiResp.text();
        throw new Error(`AI service error HTTP ${aiResp.status}: ${txt}`);
      }

      const json = await aiResp.json();
      setReport(String(json.report_markdown ?? ''));
      setLastRunAt(Date.now());
      setStats(computedStats);
    } catch (e: unknown) {
      const fe = formatError(e);
      setErrorSummary(fe.summary);
      setErrorDetails(fe.details);
    } finally {
      setLoading(false);
      setProgress(undefined);
      inFlightRef.current = false;
    }
  }, [dashboardUid, options, timeRange]);

  useEffect(() => {
    if (!dashboardUid) return;

    if (lastRunKeyRef.current === runKey) {
      return;
    }

    lastRunKeyRef.current = runKey;

    const handle = window.setTimeout(() => {
      run();
    }, 1200);

    return () => window.clearTimeout(handle);
  }, [dashboardUid, runKey, run]);

  const rangeLabel = `${String((timeRange as any)?.raw?.from ?? timeRange.from.toISOString())} → ${String(
    (timeRange as any)?.raw?.to ?? timeRange.to.toISOString()
  )}`;

  const lastRunLabel = lastRunAt ? new Date(lastRunAt).toLocaleString() : '—';

  return (
    <div
      style={{
        width,
        height,
        overflow: 'hidden',
        padding: 10,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.2 }}>AI Recommendations</div>
          <div style={{ fontSize: 12, opacity: 0.8, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            Range: {rangeLabel}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
          <div style={{ fontSize: 12, opacity: 0.9 }}>{loading ? 'Analyzing…' : 'Up to date'}</div>
          <div style={{ fontSize: 11, opacity: 0.7 }}>Last run: {lastRunLabel}</div>
        </div>
      </div>

      {progress && (
        <div style={{ display: 'flex', gap: 12, fontSize: 11, opacity: 0.85, flexWrap: 'wrap' }}>
          <div>
            Fetching metrics: {progress.done}/{progress.total}
          </div>
        </div>
      )}

      {stats && !progress && (
        <div style={{ display: 'flex', gap: 12, fontSize: 11, opacity: 0.85, flexWrap: 'wrap' }}>
          <div>Panels queried: {stats.panels_queried}</div>
          <div>Panels with data: {stats.panels_with_data}</div>
          <div>Series: {stats.series_total}</div>
          {stats.panels_with_errors > 0 && <div style={{ color: '#d44' }}>Errors: {stats.panels_with_errors}</div>}
        </div>
      )}

      {errorSummary && (
        <div style={{ border: '1px solid rgba(220, 60, 60, 0.35)', borderRadius: 6, padding: 10, overflow: 'auto' }}>
          <div style={{ color: '#d44', fontWeight: 600, marginBottom: 6, fontSize: 12 }}>Error: {errorSummary}</div>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 11, margin: 0, opacity: 0.9 }}>
            {errorDetails ?? errorSummary}
          </pre>
        </div>
      )}

      <div
        style={{
          flex: 1,
          overflow: 'auto',
          border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: 6,
          padding: 10,
          background: 'rgba(0,0,0,0.12)',
        }}
      >
        {report ? (
          <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 13, lineHeight: 1.45 }}>{report}</div>
        ) : (
          <div style={{ opacity: 0.75, fontSize: 12 }}>{loading ? 'Analyzing dashboard…' : 'Waiting for analysis…'}</div>
        )}
      </div>
    </div>
  );
};










