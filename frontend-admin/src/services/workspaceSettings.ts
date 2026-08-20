export type WorkspaceSettings = {
  maintenanceBanner: boolean;
  strictModeration: boolean;
  aiFallbacks: boolean;
  compactDashboard: boolean;
};

export const WORKSPACE_SETTINGS_KEY = 'restaurant-rag-admin-settings';
export const WORKSPACE_SETTINGS_EVENT = 'restaurant-rag-admin-settings-changed';

export const DEFAULT_WORKSPACE_SETTINGS: WorkspaceSettings = {
  maintenanceBanner: false,
  strictModeration: true,
  aiFallbacks: true,
  compactDashboard: false,
};

export function readWorkspaceSettings(): WorkspaceSettings {
  const raw = window.localStorage.getItem(WORKSPACE_SETTINGS_KEY);
  if (!raw) {
    return DEFAULT_WORKSPACE_SETTINGS;
  }
  try {
    return {
      ...DEFAULT_WORKSPACE_SETTINGS,
      ...(JSON.parse(raw) as Partial<WorkspaceSettings>),
    };
  } catch {
    window.localStorage.removeItem(WORKSPACE_SETTINGS_KEY);
    return DEFAULT_WORKSPACE_SETTINGS;
  }
}

export function writeWorkspaceSettings(settings: WorkspaceSettings): void {
  window.localStorage.setItem(WORKSPACE_SETTINGS_KEY, JSON.stringify(settings));
  window.dispatchEvent(new CustomEvent(WORKSPACE_SETTINGS_EVENT));
}

export function clearWorkspaceSettings(): void {
  window.localStorage.removeItem(WORKSPACE_SETTINGS_KEY);
  window.dispatchEvent(new CustomEvent(WORKSPACE_SETTINGS_EVENT));
}
