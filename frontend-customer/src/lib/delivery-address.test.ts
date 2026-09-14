import { describe, expect, it } from "vitest";
import {
  composeDeliveryAddress,
  formatPhoneAsTyped,
  validateAddress,
  validatePhone,
  type AddressFields,
} from "./delivery-address";

/**
 * The checkout address, validated where the customer can still fix it.
 *
 * Before this the form asked for one free-text line and a phone, marked both
 * required, and sent neither the phone nor a structured address anywhere. A
 * rider got a single string and no number.
 *
 * The rules are deliberately not "every field must be filled": address line 2
 * and a landmark are genuinely optional, and demanding them is how a checkout
 * loses an order. What must be there is enough to find the door.
 */

function fields(over: Partial<AddressFields> = {}): AddressFields {
  return {
    line1: over.line1 ?? "1600 Pennsylvania Avenue NW",
    line2: over.line2 ?? "",
    landmark: over.landmark ?? "",
    city: over.city ?? "Washington",
    state: over.state ?? "DC",
    zip: over.zip ?? "20500",
  };
}

describe("validatePhone", () => {
  it("accepts a ten-digit number however it is punctuated", () => {
    for (const raw of ["(415) 555-0132", "415-555-0132", "415 555 0132", "4155550132"]) {
      expect(validatePhone(raw)).toBeNull();
    }
  });

  it("accepts a number that carries its own country code", () => {
    expect(validatePhone("+44 20 7183 8750")).toBeNull();
  });

  it("rejects too few digits, and says how many are wanted", () => {
    const problem = validatePhone("415555");
    expect(problem).not.toBeNull();
    expect(problem).toMatch(/10/);
  });

  it("rejects letters", () => {
    expect(validatePhone("call me")).not.toBeNull();
  });

  it("asks for a number when the field is empty", () => {
    expect(validatePhone("")).toMatch(/phone/i);
    expect(validatePhone("   ")).toMatch(/phone/i);
  });
});

describe("formatPhoneAsTyped", () => {
  /**
   * Grouping as the customer types, so a wrong digit is visible before they
   * submit. Never rearranges or drops anything they typed — a formatter that
   * eats characters is worse than none.
   */
  it("groups a US number", () => {
    expect(formatPhoneAsTyped("4155550132")).toBe("(415) 555-0132");
  });

  it("formats partial input without jumping ahead", () => {
    expect(formatPhoneAsTyped("415")).toBe("(415)");
    expect(formatPhoneAsTyped("41555")).toBe("(415) 55");
  });

  it("leaves an international number alone", () => {
    // Only the default country has a known grouping; guessing at others
    // produces confident nonsense.
    expect(formatPhoneAsTyped("+442071838750")).toBe("+442071838750");
  });

  it("never invents digits", () => {
    const digits = (value: string) => value.replace(/\D/g, "");
    for (const raw of ["4", "41", "415555013", "4155550132"]) {
      expect(digits(formatPhoneAsTyped(raw))).toBe(digits(raw));
    }
  });
});

describe("validateAddress", () => {
  it("is happy with the required parts", () => {
    expect(validateAddress(fields())).toEqual({});
  });

  it("does not demand line 2 or a landmark", () => {
    expect(validateAddress(fields({ line2: "", landmark: "" }))).toEqual({});
  });

  it("names each missing required field", () => {
    const problems = validateAddress(fields({ line1: "", city: "", state: "", zip: "" }));
    expect(Object.keys(problems).sort()).toEqual(["city", "line1", "state", "zip"]);
  });

  it("wants a street address with something in it, not a single character", () => {
    expect(validateAddress(fields({ line1: "x" })).line1).toBeTruthy();
  });

  it("checks the shape of a ZIP code", () => {
    expect(validateAddress(fields({ zip: "20500" }))).toEqual({});
    expect(validateAddress(fields({ zip: "20500-0003" }))).toEqual({});
    expect(validateAddress(fields({ zip: "2050" })).zip).toBeTruthy();
    expect(validateAddress(fields({ zip: "ABCDE" })).zip).toBeTruthy();
  });

  it("treats whitespace as empty", () => {
    expect(validateAddress(fields({ city: "   " })).city).toBeTruthy();
  });
});

describe("composeDeliveryAddress", () => {
  /**
   * The server stores one string, so the parts are joined into something a
   * rider can read at the door rather than a JSON blob.
   */
  it("joins the parts in the order they are read", () => {
    expect(composeDeliveryAddress(fields({ line2: "Apt 4B", landmark: "Opposite the park" }))).toBe(
      "1600 Pennsylvania Avenue NW, Apt 4B, Opposite the park, Washington, DC 20500",
    );
  });

  it("leaves out the parts that were not given", () => {
    expect(composeDeliveryAddress(fields())).toBe(
      "1600 Pennsylvania Avenue NW, Washington, DC 20500",
    );
  });

  it("trims what the customer typed", () => {
    expect(composeDeliveryAddress(fields({ line1: "  1 Main St  ", city: " Springfield " }))).toBe(
      "1 Main St, Springfield, DC 20500",
    );
  });
});
