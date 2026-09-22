/**
 * The monogram in the round badge belongs to the restaurant wearing it.
 *
 * It was the literal "BB" in four places: the site header on every page, the
 * branch chooser a new visitor meets first, and twice on the concierge. Every
 * tenant on this platform wore Bangkok Bowl's initials — and the header told
 * screen readers "Bangkok Bowl home" while the name beside the badge fell
 * back to "Bangkok Bowl" as well.
 *
 * The rule being kept is narrow: the badge must never contradict the name
 * printed beside it, so both are derived from one string.
 */

import { describe, expect, it } from "vitest";

import { brandInitials } from "./brand-mark";

describe("brandInitials", () => {
  it("takes the first letter of the first two words", () => {
    expect(brandInitials("Radhe Dhokla")).toBe("RD");
    expect(brandInitials("Bangkok Bowl")).toBe("BB");
    expect(brandInitials("Spice Route Indian Kitchen")).toBe("SR");
  });

  it("skips the words a restaurant is not called", () => {
    expect(brandInitials("The Spice Route")).toBe("SR");
    expect(brandInitials("House of Dhokla")).toBe("HD");
  });

  it("gives a one-word name two of its own letters", () => {
    // A single letter in a round badge reads as an icon that failed to load.
    expect(brandInitials("Zomato")).toBe("ZO");
  });

  it("ignores punctuation rather than turning it into an initial", () => {
    expect(brandInitials("Luigi's Italian Trattoria")).toBe("LI");
    expect(brandInitials("Café—Bombay")).toBe("CB");
  });

  it("is always upper case, whatever the name is stored as", () => {
    expect(brandInitials("radhe dhokla")).toBe("RD");
  });

  it("returns nothing it would have to invent", () => {
    // The caller renders no badge at all rather than a placeholder — which is
    // how "BB" ended up on every tenant in the first place.
    expect(brandInitials("")).toBe("");
    expect(brandInitials(null)).toBe("");
    expect(brandInitials(undefined)).toBe("");
    expect(brandInitials("   ")).toBe("");
  });

  it("never answers with another restaurant's initials", () => {
    // The whole point, stated as a test: nothing about this function can
    // produce "BB" unless the name really does start with those letters.
    for (const name of ["Radhe Dhokla", "Momo Mountain", "Dragon Wok", "", "The Grill"]) {
      expect(brandInitials(name)).not.toBe("BB");
    }
  });
});
