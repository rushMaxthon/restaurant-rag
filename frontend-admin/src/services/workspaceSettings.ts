export type WorkspaceSettings = {
  /** Platform-wide notice. Admin only - owners cannot post one. */
  maintenanceBanner: boolean;
  compactDashboard: boolean;
  /** Period the AI Manager opens on, in days. */
  defaultPeriodDays: number;
  /** Rows every paginated table starts with. */
  defaultPageSize: number;
};

/** The only values the pickers offer, and the only ones honoured on read. */
export const PERIOD_CHOICES = [7, 30, 90] as const;
export const PAGE_SIZE_CHOICES = [10, 25, 50] as const;

export const WORKSPACE_SETTINGS_KEY = 'restaurant-rag-admin-settings';
export const WORKSPACE_SETTINGS_EVENT = 'restaurant-rag-admin-settings-changed';

/**
 * Only preferences this workspace can actually honour.
 *
 * `strictModeration` and `aiFallbacks` used to live here too. Both described
 * backend behaviour - review flagging and RAG fallback policy - that nothing on
 * the client could change, so the switches wrote to localStorage and nothing
 * ever read them. They belong on a real settings API, not in a browser store.
 */
export const DEFAULT_WORKSPACE_SETTINGS: WorkspaceSettings = {
  maintenanceBanner: false,
  compactDashboard: false,
  defaultPeriodDays: 90,
  defaultPageSize: 10,
};

export function readWorkspaceSettings(): WorkspaceSettings {
  const raw = window.localStorage.getItem(WORKSPACE_SETTINGS_KEY);
  if (!raw) {
    return DEFAULT_WORKSPACE_SETTINGS;
  }
  try {
    const stored = JSON.parse(raw) as Partial<WorkspaceSettings>;
    const merged = { ...DEFAULT_WORKSPACE_SETTINGS, ...stored };
    // A hand-edited or stale store must not put a table on 7 rows or the AI
    // Manager on a period the picker cannot show.
    return {
      ...merged,
      defaultPeriodDays: PERIOD_CHOICES.includes(
        merged.defaultPeriodDays as (typeof PERIOD_CHOICES)[number],
      )
        ? merged.defaultPeriodDays
        : DEFAULT_WORKSPACE_SETTINGS.defaultPeriodDays,
      defaultPageSize: PAGE_SIZE_CHOICES.includes(
        merged.defaultPageSize as (typeof PAGE_SIZE_CHOICES)[number],
      )
        ? merged.defaultPageSize
        : DEFAULT_WORKSPACE_SETTINGS.defaultPageSize,
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
