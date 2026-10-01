/**
 * Light or dark, chosen by the person using the panel.
 *
 * The storefront has had this since it was built and the panel never did, so
 * an operator with a dark storefront open beside a permanently white admin was
 * looking at two products rather than one — the most visible thing keeping the
 * two from reading as the same system.
 *
 * `.dark` on `<html>`, which is exactly what the storefront toggles, so one
 * shared token file drives both. Nothing here knows a colour.
 *
 * A CLASS rather than `prefers-color-scheme`, deliberately and to match the
 * storefront: this is a choice somebody made about this product, not a setting
 * their laptop made about everything. An operator who keeps their machine dark
 * and wants the panel bright can have that.
 */

const STORAGE_KEY = "admin.theme";

export type Theme = "light" | "dark";

/**
 * What to show on first paint.
 *
 * Reads what was chosen last time, and falls back to the machine's preference
 * only when nobody has chosen — which is the one moment a laptop's setting is
 * better than a guess.
 *
 * Every access is wrapped: `localStorage` throws in a private window and in a
 * browser with site data blocked, and a panel that will not render because it
 * could not read a colour preference is worse than one in the wrong colour.
 */
export function storedTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // Unreadable storage is not an error worth surfacing.
  }
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** Put it on the document, and remember it for next time. */
export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  // `color-scheme` is what makes the browser's own furniture follow: scrollbars,
  // form controls and the flash between pages. Without it a dark panel keeps
  // white scrollbars and a white gap on every navigation.
  document.documentElement.style.colorScheme = theme;
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // The panel still works; it just forgets by the next visit.
  }
}
