import { describe, expect, it } from "vitest";
import {
  addressFromSaved,
  composeDeliveryAddress,
  isSameAddress,
  looseAddressFields,
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

describe("addressFromSaved", () => {
  const saved = {
    id: "a1",
    label: "HOME" as const,
    address_line_1: "1600 Pennsylvania Avenue NW",
    address_line_2: "Apt 4B",
    landmark: null,
    city: "Washington",
    state: "DC",
    postal_code: "20500",
    phone_number: "2025550143",
    is_default: true,
    formatted_address: "1600 Pennsylvania Avenue NW, Apt 4B, Washington, DC 20500",
  };

  it("fills every field the saved address has", () => {
    expect(addressFromSaved(saved)).toEqual({
      line1: "1600 Pennsylvania Avenue NW",
      line2: "Apt 4B",
      landmark: "",
      city: "Washington",
      state: "DC",
      zip: "20500",
    });
  });

  it("turns the nulls into empty strings the inputs can hold", () => {
    // A controlled input given null renders "null" and React warns about the
    // switch from uncontrolled; the form only ever holds strings.
    const bare = { ...saved, address_line_2: null, landmark: null };
    expect(addressFromSaved(bare).line2).toBe("");
    expect(addressFromSaved(bare).landmark).toBe("");
  });
});

describe("looseAddressFields", () => {
  /**
   * `users.default_address` is one free-text column, so this is a guess by
   * shape, not a parser. It fills the form only when the shape is
   * unmistakable, and every field stays editable either way.
   */
  it("reads the comma-separated shape the app has always written", () => {
    expect(looseAddressFields("100 Main St, Springfield, IL, 62704")).toEqual({
      line1: "100 Main St",
      line2: "",
      landmark: "",
      city: "Springfield",
      state: "IL",
      zip: "62704",
    });
  });

  it("keeps the extra parts as the second line", () => {
    expect(looseAddressFields("100 Main St, Apt 2, Springfield, IL, 62704")).toMatchObject({
      line1: "100 Main St",
      line2: "Apt 2",
      city: "Springfield",
      zip: "62704",
    });
  });

  it("puts an unrecognisable address on the first line and asks for the rest", () => {
    // Better than spreading a wrong guess across five fields the customer then
    // has to find and undo.
    expect(looseAddressFields("behind the blue gate near the temple")).toEqual({
      line1: "behind the blue gate near the temple",
      line2: "",
      landmark: "",
      city: "",
      state: "",
      zip: "",
    });
  });

  it("does not claim a postal code from a part that is not one", () => {
    expect(looseAddressFields("100 Main St, Springfield, Illinois")).toMatchObject({
      line1: "100 Main St, Springfield, Illinois",
      city: "",
      zip: "",
    });
  });

  it("has nothing to say about nothing", () => {
    expect(looseAddressFields(null)).toEqual({
      line1: "",
      line2: "",
      landmark: "",
      city: "",
      state: "",
      zip: "",
    });
  });
});

describe("isSameAddress", () => {
  const saved = {
    address_line_1: "1600 Pennsylvania Avenue NW",
    address_line_2: "Apt 4B",
    landmark: null,
    city: "Washington",
    state: "DC",
    postal_code: "20500",
  };
  const typed = {
    line1: "1600 Pennsylvania Avenue NW",
    line2: "Apt 4B",
    landmark: "",
    city: "Washington",
    state: "DC",
    zip: "20500",
  };

  it("knows an address it already has", () => {
    expect(isSameAddress(typed, saved)).toBe(true);
  });

  it("ignores case and stray spacing", () => {
    // "washington" and "Washington  " are the same place, and saving a second
    // copy of an address because of a capital letter is how a picker fills up
    // with the same street five times.
    expect(isSameAddress({ ...typed, city: "  washington " }, saved)).toBe(true);
  });

  it("treats a real change as a different address", () => {
    expect(isSameAddress({ ...typed, line2: "Apt 5C" }, saved)).toBe(false);
    expect(isSameAddress({ ...typed, zip: "20501" }, saved)).toBe(false);
  });
});
