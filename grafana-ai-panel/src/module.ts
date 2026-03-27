import { PanelPlugin } from '@grafana/data';

import { AiPanel } from './panel/AiPanel';
import { AiPanelOptions, defaultOptions } from './types';

export const plugin = new PanelPlugin<AiPanelOptions>(AiPanel).setPanelOptions((builder) => {
  return builder
    .addTextInput({
      path: 'dashboardUid',
      name: 'Dashboard UID (optional)',
      description: 'Leave blank to auto-detect from the URL (/d/<uid>/...)',
      defaultValue: '',
    })
    .addTextInput({
      path: 'aiServiceUrl',
      name: 'AI service URL',
      defaultValue: defaultOptions.aiServiceUrl,
    })
    .addTextInput({
      path: 'aiServiceApiKey',
      name: 'AI service API key (X-API-Key)',
      defaultValue: '',
      settings: { placeholder: 'optional' },
    })
    .addTextInput({
      path: 'aiServiceToken',
      name: 'AI service token (?token=)',
      defaultValue: '',
      settings: { placeholder: 'optional' },
    })
    .addNumberInput({
      path: 'maxPanels',
      name: 'Max panels',
      defaultValue: defaultOptions.maxPanels,
      settings: { min: 1, max: 500, integer: true },
    })
    .addNumberInput({
      path: 'maxTargetsPerPanel',
      name: 'Max targets per panel',
      defaultValue: defaultOptions.maxTargetsPerPanel,
      settings: { min: 1, max: 50, integer: true },
    })
    .addNumberInput({
      path: 'anomalyZ',
      name: 'Anomaly z-threshold (optional)',
      description: 'Used only if time-series data can be queried; higher = fewer anomalies.',
      defaultValue: defaultOptions.anomalyZ,
      settings: { min: 2, max: 20 },
    });
});
