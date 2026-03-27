export interface AiPanelOptions {
  dashboardUid?: string;
  aiServiceUrl: string;
  aiServiceApiKey?: string;
  aiServiceToken?: string;
  maxPanels: number;
  maxTargetsPerPanel: number;
  anomalyZ: number;
}

export const defaultOptions: AiPanelOptions = {
  aiServiceUrl: 'http://127.0.0.1:8088',
  maxPanels: 50,
  maxTargetsPerPanel: 6,
  anomalyZ: 6,
};
