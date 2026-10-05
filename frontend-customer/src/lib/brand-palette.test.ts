/**
 * The brand palette has to read for EVERY restaurant, not just the orange one.
 *
 * A tenant picks one colour from twelve presets or types a hex
 * (`backend/app/services/restaurant_theme.py`). The storefront then derives a
 * button fill and a text tier from it. Before this existed it derived neither:
 * `--primary-text` stayed `#cf4300` — a darkened platform orange — no matter
 * what the restaurant chose, so a Teal or Forest storefront had orange
 * eyebrows, orange active tabs and orange prices.
 *
 * The test that matters is the loop at the bottom: every shipped preset must
 * come out readable. A derivation that works for orange and fails for Slate is
 * worse than no derivation, because it fails silently and only for the tenants
 * nobody is looking at.
 */

import { describe, expect, it } from "vitest";

import {
  brandPalette,
  contrast,
  fromHsl,
  liftForDark,
  luminance,
  parseHex,
  readableInk,
  toHex,
  toHsl,
  walkToContrast,
} from "./brand-palette";

/** Every preset in THEME_PRESETS, plus the storefront's own default. */
const PRESETS: ReadonlyArray<readonly [string, string]> = [
  ["sunset", "#FF5200"],
  ["amber", "#B45309"],
  ["crimson", "#C0392B"],
  ["cherry", "#C2185B"],
  ["grape", "#7B3FA0"],
  ["indigo", "#4338CA"],
  ["ocean", "#2D7FF9"],
  ["teal", "#0F766E"],
  ["forest", "#2E7D32"],
  ["olive", "#4D7C0F"],
  ["slate", "#334155"],
  ["mocha", "#78350F"],
];

const WHITE = { r: 255, g: 255, b: 255 };
const PAGE = { r: 250, g: 250, b: 250 };

describe("reading a hex", () => {
  it("takes both lengths, with or without the hash", () => {
    expect(parseHex("#ff5200")).toEqual({ r: 255, g: 82, b: 0 });
    expect(parseHex("ff5200")).toEqual({ r: 255, g: 82, b: 0 });
    expect(parseHex("#f50")).toEqual({ r: 255, g: 85, b: 0 });
    expect(parseHex("  #FF5200  ")).toEqual({ r: 255, g: 82, b: 0 });
  });

  it("returns null rather than a guess", () => {
    // A tenant's colour arrives over the wire. Guessing here would put an
    // arbitrary colour on a restaurant's storefront.
    for (const bad of ["", "   ", "red", "#12345", "#gggggg", null, undefined]) {
      expect(parseHex(bad as string)).toBeNull();
    }
  });

  it("round-trips through toHex", () => {
    for (const [, hex] of PRESETS) {
      expect(toHex(parseHex(hex)!)).toBe(hex.toLowerCase());
    }
  });
});

describe("the contrast maths", () => {
  it("puts white and black at the known extreme", () => {
    expect(contrast(WHITE, { r: 0, g: 0, b: 0 })).toBeCloseTo(21, 1);
  });

  it("does not care which way round the pair is given", () => {
    const a = parseHex("#ff5200")!;
    expect(contrast(a, WHITE)).toBeCloseTo(contrast(WHITE, a), 10);
  });

  it("linearises, so mid-tones are not flattered", () => {
    // The step everyone drops. Without it #808080 reads as luminance 0.5 and
    // every mid-tone appears to pass when it does not.
    expect(luminance({ r: 128, g: 128, b: 128 })).toBeLessThan(0.3);
  });

  it("agrees with the measured value the shared token was chosen for", () => {
    // #cf4300 is in frontend-shared/tokens.css because white on it clears
    // 4.5:1 where white on #ff5200 does not. Both halves of that claim.
    expect(contrast(parseHex("#cf4300")!, WHITE)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(parseHex("#ff5200")!, WHITE)).toBeLessThan(4.5);
  });
});

describe("HSL round-trip", () => {
  it("survives the trip for every preset", () => {
    for (const [name, hex] of PRESETS) {
      const rgb = parseHex(hex)!;
      const back = fromHsl(toHsl(rgb));
      // Within one step per channel: HSL is lossy at 8 bits and the point is
      // that hue is preserved, not that the bytes are identical.
      expect(Math.abs(back.r - rgb.r), name).toBeLessThanOrEqual(1);
      expect(Math.abs(back.g - rgb.g), name).toBeLessThanOrEqual(1);
      expect(Math.abs(back.b - rgb.b), name).toBeLessThanOrEqual(1);
    }
  });

  it("keeps a grey grey", () => {
    const grey = { r: 128, g: 128, b: 128 };
    expect(toHsl(grey).s).toBe(0);
    expect(fromHsl(toHsl(grey))).toEqual(grey);
  });
});

describe("walking to a contrast target", () => {
  it("leaves a colour alone when it already passes", () => {
    const already = parseHex("#78350F")!; // mocha, dark enough for white ink
    expect(walkToContrast(already, WHITE, 4.5, -1)).toEqual(already);
  });

  it("holds the hue while it moves the lightness", () => {
    // The whole reason this is not "pick a darker colour from a palette".
    const teal = parseHex("#0F766E")!;
    const walked = walkToContrast(teal, WHITE, 7, -1);
    expect(Math.abs(toHsl(walked).h - toHsl(teal).h)).toBeLessThan(2);
    expect(toHsl(walked).l).toBeLessThan(toHsl(teal).l);
  });

  it("gives up at the end of the ramp rather than looping", () => {
    // No shade of any hue reaches 21:1 against white except black.
    expect(walkToContrast(parseHex("#ff5200")!, WHITE, 21, -1)).toEqual({
      r: 0,
      g: 0,
      b: 0,
    });
  });
});

describe("the lift for dark mode", () => {
  it("lands inside the band for every preset", () => {
    // Bright enough to carry dark ink, not so bright it glares. The same band
    // the mobile app uses, so one product does not have two answers.
    for (const [name, hex] of PRESETS) {
      const l = toHsl(liftForDark(parseHex(hex)!)).l;
      expect(l, name).toBeGreaterThanOrEqual(0.42 - 0.001);
      expect(l, name).toBeLessThanOrEqual(0.72 + 0.001);
    }
  });

  it("keeps the hue", () => {
    for (const [name, hex] of PRESETS) {
      const rgb = parseHex(hex)!;
      expect(Math.abs(toHsl(liftForDark(rgb)).h - toHsl(rgb).h), name).toBeLessThan(2);
    }
  });
});

describe("readableInk", () => {
  it("keeps white wherever white is legible", () => {
    // Ten of the twelve presets. White on these is 4.99:1 or better, so the
    // design — white on a brand fill — stands.
    for (const hex of ["#B45309", "#C0392B", "#C2185B", "#7B3FA0", "#4338CA",
                       "#0F766E", "#2E7D32", "#4D7C0F", "#334155", "#78350F"]) {
      expect(readableInk(parseHex(hex)!)).toBe("#ffffff");
    }
  });

  it("goes dark where white fails AA, including on the platform's own orange", () => {
    // This is the change. White on #ff5200 is 3.25:1 — fine for large text and
    // not for a 12px Add button, which is where it was being used.
    expect(readableInk(parseHex("#ff5200")!)).toBe("#14171f");
    expect(readableInk(parseHex("#2D7FF9")!)).toBe("#14171f");
    // And the pale brands the old luminance threshold existed to catch still
    // land on dark ink, by a different route.
    expect(readableInk(parseHex("#ffd166")!)).toBe("#14171f");
  });

  it("whatever it picks, the label clears AA", () => {
    // The guard that matters: it is not asserted to be white or dark, only to
    // be readable. A future change to the rule is free as long as this holds.
    for (const [name, hex] of PRESETS) {
      const fill = parseHex(hex)!;
      const ink = parseHex(readableInk(fill))!;
      expect(contrast(ink, fill), `${name} (${hex}) button label`).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe("every preset a restaurant can choose", () => {
  it("produces a button whose white label clears AA", () => {
    for (const [name, hex] of PRESETS) {
      const palette = brandPalette(hex)!;
      const ratio = contrast(parseHex(palette.primaryStrong)!, WHITE);
      expect(ratio, `${name} button`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("produces a text tier that reads as small copy on the page", () => {
    // This is the bug that prompted the whole module: `--primary-text` was a
    // literal orange for every tenant.
    for (const [name, hex] of PRESETS) {
      const palette = brandPalette(hex)!;
      const ratio = contrast(parseHex(palette.primaryText)!, PAGE);
      expect(ratio, `${name} text`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps every derived value recognisably the restaurant's colour", () => {
    for (const [name, hex] of PRESETS) {
      const palette = brandPalette(hex)!;
      const brandHue = toHsl(parseHex(hex)!).h;
      for (const derived of [palette.primaryStrong, palette.primaryText, palette.darkPrimary]) {
        const hue = toHsl(parseHex(derived)!).h;
        // Hue is circular; compare the short way round.
        const delta = Math.min(Math.abs(hue - brandHue), 360 - Math.abs(hue - brandHue));
        expect(delta, `${name} → ${derived}`).toBeLessThan(3);
      }
    }
  });

  it("gives the dark button an ink that reads on it", () => {
    for (const [name, hex] of PRESETS) {
      const palette = brandPalette(hex)!;
      const ratio = contrast(parseHex(palette.darkPrimary)!, parseHex(palette.darkOnPrimary)!);
      expect(ratio, `${name} dark ink`).toBeGreaterThanOrEqual(3);
    }
  });

  it("refuses a colour it cannot read", () => {
    expect(brandPalette("not a colour")).toBeNull();
  });
});

describe("the platform default specifically", () => {
  it("lands on the values the shared token file already carries", () => {
    // Not a coincidence worth preserving by hand: if the derivation drifts away
    // from the measured literals in frontend-shared/tokens.css, the default
    // tenant would render differently from every static mock and screenshot.
    const palette = brandPalette("#FF5200")!;
    expect(palette.primary).toBe("#ff5200");
    // Dark, not white, and that is the one value in this block that moved:
    // white on this orange is 3.25:1. See `readableInk`.
    expect(palette.onPrimary).toBe("#14171f");
    // Within a shade of the hand-measured #cf4300 — the walk is in 1% steps so
    // it is allowed to land a step either side, not anywhere.
    const strong = parseHex(palette.primaryStrong)!;
    const measured = parseHex("#cf4300")!;
    expect(Math.abs(toHsl(strong).l - toHsl(measured).l)).toBeLessThan(0.05);
  });
});
