export type CompactDigest = {
  dashboard: { uid?: string; title?: string; timezone?: string; time?: any; refresh?: any; tags?: any };
  counts: { panels_total: number; panels_included: number; panels_truncated: number };
  panels: Array<any>;
};

function clip(s: any, maxLen: number): string | undefined {
  if (s == null) return undefined;
  const t = String(s).trim();
  if (!t) return undefined;
  return t.length > maxLen ? t.slice(0, maxLen - 3) + '...' : t;
}

function stripOradbPrefix(v: any): any {
  const p = 'ORADB_ORADB';
  return typeof v === 'string' && v.startsWith(p) ? v.slice(p.length) : v;
}

function compactFieldConfig(fc: any): any {
  if (!fc || typeof fc !== 'object') return undefined;

  const defaults = fc.defaults && typeof fc.defaults === 'object' ? fc.defaults : {};
  const thresholds = defaults.thresholds && typeof defaults.thresholds === 'object' ? defaults.thresholds : undefined;
  const mappings = Array.isArray(defaults.mappings) ? defaults.mappings : undefined;

  const compactDefaults: any = {};
  for (const k of ['unit', 'min', 'max', 'decimals', 'displayName', 'noValue']) {
    if (defaults[k] != null) compactDefaults[k] = defaults[k];
  }

  if (thresholds) {
    compactDefaults.thresholds = {
      mode: thresholds.mode,
      steps: Array.isArray(thresholds.steps) ? thresholds.steps.slice(0, 8) : thresholds.steps,
    };
  }

  if (mappings) {
    compactDefaults.mappings = mappings.slice(0, 8);
  }

  const overrides = Array.isArray(fc.overrides)
    ? fc.overrides.slice(0, 12).map((o: any) => {
        const matcher = o?.matcher;
        const properties = Array.isArray(o?.properties) ? o.properties.slice(0, 12) : [];
        const compactProps = properties
          .map((p: any) => {
            const id = p?.id;
            if (!id) return undefined;
            if (
              id === 'unit' ||
              id === 'decimals' ||
              id === 'min' ||
              id === 'max' ||
              id === 'thresholds' ||
              id === 'displayName'
            ) {
              return { id, value: stripOradbPrefix(p?.value) };
            }
            return undefined;
          })
          .filter(Boolean);

        return {
          matcher: matcher ? { id: matcher.id, options: stripOradbPrefix(matcher.options) } : undefined,
          properties: compactProps,
        };
      })
    : undefined;

  return {
    defaults: compactDefaults,
    overrides,
  };
}

export function buildCompactDigest(dashboardPayload: any, maxPanels: number, maxTargetsPerPanel: number): CompactDigest {
  const dashboard = dashboardPayload?.dashboard ?? dashboardPayload;
  const panelsRaw: any[] = Array.isArray(dashboard?.panels) ? dashboard.panels : [];
  const panels = panelsRaw.slice(0, maxPanels).map((p) => {
    const ds = p?.datasource ?? {};
    const targets = Array.isArray(p?.targets) ? p.targets.slice(0, maxTargetsPerPanel) : [];
    return {
      id: p?.id,
      type: p?.type,
      title: p?.title,
      description: clip(p?.description, 220),
      datasource: { type: ds?.type, uid: ds?.uid },
      fieldConfig: compactFieldConfig(p?.fieldConfig),
      targets: targets.map((t: any) => ({
        refId: t?.refId,
        type: t?.type,
        seriesType: t?.seriesType,
        queryType: t?.queryType,
        metricGroup: t?.metricGroup,
        metric: t?.metric,
        target: stripOradbPrefix(t?.target),
        targetType: t?.targetType,
        expr: clip(t?.rawQuery ?? t?.rawSql ?? t?.expr ?? t?.query, 180),
      })),
    };
  });

  return {
    dashboard: {
      uid: dashboard?.uid,
      title: dashboard?.title,
      timezone: dashboard?.timezone,
      time: dashboard?.time,
      refresh: dashboard?.refresh,
      tags: dashboard?.tags,
    },
    counts: {
      panels_total: panelsRaw.length,
      panels_included: panels.length,
      panels_truncated: Math.max(0, panelsRaw.length - panels.length),
    },
    panels,
  };
}
