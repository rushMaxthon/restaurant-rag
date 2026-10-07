import { describe, expect, it } from "vitest";

import { jsonLd } from "./json-ld";

const LS = String.fromCharCode(0x2028);
const PS = String.fromCharCode(0x2029);

/**
 * Structured data is written into a <script> tag on every storefront page,
 * built from text an owner typed (FAQ answers, the meta description, the
 * address). `JSON.stringify` leaves `</script>` intact, so an answer containing
 * it closed the tag and ran whatever followed for every visitor. Found in the
 * 2026-10-07 security review.
 */
describe("jsonLd", () => {
  it("cannot be closed from inside", () => {
    const out = jsonLd({ text: "</script><script>alert(1)</script>" });
    expect(out).not.toContain("</script");
    expect(out).not.toContain("<");
  });

  it("escapes every character that can change how HTML reads the script", () => {
    const out = jsonLd({ text: `<!-- & > ${LS} ${PS}` });
    for (const raw of ["<", ">", "&", LS, PS]) expect(out).not.toContain(raw);
  });

  it("is still the same data to a JSON reader", () => {
    const value = { name: "Bhagwati <Bakery> & Co", faq: ["a</script>b", `x${LS}y`], n: 1 };
    expect(JSON.parse(jsonLd(value))).toEqual(value);
  });
});
