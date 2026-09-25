/**
 * Applies a tenant's brand colour to the document as CSS custom properties.
 * Never hardcode a colour in components — this is the single place that
 * turns the `/app-config` branding response into the `--primary` family of
 * variables consumed across styles.css.
 */
export function applyBrandColor(primaryColor: string | undefined | null) {
  if (typeof document === "undefined" || !primaryColor) return;
  const root = document.documentElement;
  root.style.setProperty("--primary", primaryColor);
  root.style.setProperty(
    "--primary-soft",
    `color-mix(in srgb, ${primaryColor} 15%, var(--surface))`,
  );
  root.style.setProperty(
    "--placeholder-a",
    `color-mix(in srgb, ${primaryColor} 15%, var(--surface))`,
  );
  root.style.setProperty(
    "--placeholder-b",
    `color-mix(in srgb, ${primaryColor} 25%, var(--surface))`,
  );
  root.style.setProperty("--on-primary", pickReadableForeground(primaryColor));
}

/** Picks black or white text depending on the relative luminance of `hex`. */
function pickReadableForeground(hex: string): string {
  const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex.trim());
  if (!match) return "#ffffff";
  const r = parseInt(match[1] ?? "ff", 16) / 255;
  const g = parseInt(match[2] ?? "ff", 16) / 255;
  const b = parseInt(match[3] ?? "ff", 16) / 255;
  const linear = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
  return luminance > 0.6 ? "#14171F" : "#ffffff";
}
