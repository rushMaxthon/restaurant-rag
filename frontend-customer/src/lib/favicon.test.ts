/**
 * Every tenant wore the generator's favicon.
 *
 * `/favicon.ico` was hardcoded in the root route, so the icon in the tab, in
 * a bookmark and on a phone's home screen was Lovable's — on a Surat bakery's
 * site and on every other restaurant on the platform. The same class of bug
 * as the shared hero photograph and the shared page title, in the places a
 * brand is most visible and least often checked.
 */

import { describe, expect, it } from "vitest";

import { faviconHref, generatedMark } from "./favicon";

const decode = (href: string) => decodeURIComponent(href.replace("data:image/svg+xml,", ""));

describe("faviconHref", () => {
  it("prefers the icon the operator chose", () => {
    expect(
      faviconHref({
        favicon_url: "https://cdn.test/icon.png",
        logo_url: "https://cdn.test/logo.png",
        name: "Bhagwati Bakery",
      }),
    ).toBe("https://cdn.test/icon.png");
  });

  it("falls back to the logo, which is what nearly every restaurant has", () => {
    expect(
      faviconHref({ favicon_url: "  ", logo_url: "https://cdn.test/logo.png", name: "X" }),
    ).toBe("https://cdn.test/logo.png");
  });

  it("draws a mark when the restaurant has uploaded nothing", () => {
    const href = faviconHref({ name: "Bhagwati Bakery", primary_color: "#ff5200" });
    expect(href.startsWith("data:image/svg+xml,")).toBe(true);
    expect(decode(href)).toContain(">BB<");
    expect(decode(href)).toContain("#ff5200");
  });

  it("never returns the empty string, so the tab cannot fall back to a 404", () => {
    for (const config of [{}, { name: "" }, { name: null, logo_url: null }]) {
      expect(faviconHref(config).length).toBeGreaterThan(0);
    }
  });
});

describe("generatedMark", () => {
  it("uses the restaurant's own colour", () => {
    expect(decode(generatedMark("Teal Kitchen", "#0d9488"))).toContain("#0d9488");
  });

  it("refuses anything that is not a hex colour", () => {
    // This string is interpolated into markup the browser parses, so a value
    // that is not plainly a colour does not go in it.
    for (const bad of ["var(--primary)", "red; }</text><script>", "rgb(1,2,3)", "", null]) {
      expect(decode(generatedMark("Teal Kitchen", bad))).toContain("#ff5200");
    }
  });

  it("cannot have markup pushed into it through the name", () => {
    // Belt and braces: `brandInitials` already strips everything that is not
    // a letter or a digit, so "<script> & Co" arrives as "SC" and the escape
    // below never fires. Asserted anyway, because the day that function is
    // relaxed this is the string being written into a parsed document.
    const svg = decode(generatedMark("<script> & Co", "#ff5200"));
    expect(svg).not.toContain("<script");
    expect(svg).toContain(">SC<");
  });

  it("still draws something for a restaurant with no usable name", () => {
    // `brandInitials` returns "" rather than another restaurant's letters.
    expect(decode(generatedMark("", "#ff5200"))).toContain(">•<");
  });

  it("sets one letter larger than two, so neither looks lost in the box", () => {
    // A one-WORD name still gets two letters ("Zaika" -> "ZA"); only a name
    // with a single letter in it produces one.
    expect(decode(generatedMark("Z", "#ff5200"))).toContain('font-size="56"');
    expect(decode(generatedMark("Bhagwati Bakery", "#ff5200"))).toContain('font-size="44"');
  });
});
