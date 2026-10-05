/**
 * Whether the sidebar is a full column or an icon rail.
 *
 * The panel's tables are wide and the sidebar took 256px of every screen
 * whether or not anybody was navigating. Collapsed, it is a 72px rail of
 * icons and the page gets the rest.
 *
 * Remembered per browser, like the theme and for the same reason: it is a
 * choice about how this person works, not about the page they are on.
 *
 * Every access is wrapped. `localStorage` throws in a private window and with
 * site data blocked, and a panel that will not render because it could not
 * read how wide its sidebar should be is worse than one with a wide sidebar.
 */

const STORAGE_KEY = "admin.sidebar";

/** Expanded unless this browser explicitly chose otherwise. */
export function storedSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "collapsed";
  } catch {
    return false;
  }
}

export function storeSidebarCollapsed(collapsed: boolean): void {
  try {
    if (collapsed) {
      localStorage.setItem(STORAGE_KEY, "collapsed");
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // An unwritable preference lasts until the next reload. Not worth an error.
  }
}
