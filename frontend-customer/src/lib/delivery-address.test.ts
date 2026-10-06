import { describe, expect, it } from "vitest";
import {
  addressFromSaved,
  composeDeliveryAddress,
  isSameAddress,
  looseAddressFields,
  pointFromSaved,
  postalCodeLabel,
  formatPhoneAsTyped,
  phoneWithoutCountryCode,
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
    house: over.house ?? "",
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

  /**
   * This block used to assert the US rule — five digits, or five and four —
   * and that assertion was the bug. Every restaurant on this platform that
   * charges in rupees was unreachable by its own customers: a Surat PIN code
   * is six digits, so the form answered "Enter a 5-digit ZIP code" to a
   * correctly typed address and the order could not be placed.
   *
   * What replaced it is a shape check, not a format check, and these are the
   * postal codes of the currencies this platform actually supports.
   */
  it("takes a real postal code from any of the countries this platform serves", () => {
    expect(validateAddress(fields({ zip: "395002" }))).toEqual({}); // Surat
    expect(validateAddress(fields({ zip: "110001" }))).toEqual({}); // New Delhi
    expect(validateAddress(fields({ zip: "20500" }))).toEqual({}); // Washington
    expect(validateAddress(fields({ zip: "20500-0003" }))).toEqual({}); // ZIP+4
    expect(validateAddress(fields({ zip: "M5V 2T6" }))).toEqual({}); // Toronto
    expect(validateAddress(fields({ zip: "SW1A 1AA" }))).toEqual({}); // London
    expect(validateAddress(fields({ zip: "75008" }))).toEqual({}); // Paris
  });

  it("still asks for one, and says what this storefront calls it", () => {
    expect(validateAddress(fields({ zip: "" }), "PIN code").zip).toBe("Enter your PIN code.");
    expect(validateAddress(fields({ zip: "" }), "ZIP code").zip).toBe("Enter your ZIP code.");
  });

  it("still refuses something that is plainly not a postal code", () => {
    // The check that remains is worth keeping: a sentence in this box means
    // the address was pasted into the wrong field.
    expect(validateAddress(fields({ zip: "near the big temple" })).zip).toBeTruthy();
    expect(validateAddress(fields({ zip: "!!" })).zip).toBeTruthy();
  });

  it("names the box after the money the storefront charges in", () => {
    expect(postalCodeLabel("INR")).toBe("PIN code");
    expect(postalCodeLabel("USD")).toBe("ZIP code");
    expect(postalCodeLabel("GBP")).toBe("Postcode");
    // Anything else gets the name that is true everywhere rather than a guess.
    expect(postalCodeLabel("AED")).toBe("Postal code");
    expect(postalCodeLabel(undefined)).toBe("Postal code");
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

  it("puts the house number first, where the rider reads it", () => {
    // The flat number is the first thing somebody standing at the gate needs
    // and the last thing a geocoder wants, which is why it is a field of its
    // own and why it leads here.
    expect(
      composeDeliveryAddress(
        fields({ house: "A-31, 3rd floor", line1: "Rang Darshan Society", city: "Surat" }),
      ),
    ).toBe("A-31, 3rd floor, Rang Darshan Society, Surat, DC 20500");
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
      house: "",
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

describe("pointFromSaved", () => {
  /**
   * The bug this exists for: the checkout filled its form from a saved
   * address and left the picked point null, so a delivery order carried no
   * coordinates and the server refused it with "Please choose your address
   * from the suggestions" — shown to a customer whose address was already on
   * the screen, prefilled, unedited. Reported 2026-10-03.
   */
  it("hands back the point a saved address carries", () => {
    expect(pointFromSaved({ latitude: 21.3026097, longitude: 72.9159345 })).toEqual({
      latitude: 21.3026097,
      longitude: 72.9159345,
    });
  });

  it("is null for an address saved before coordinates were captured", () => {
    expect(pointFromSaved({ latitude: null, longitude: null })).toBeNull();
    expect(pointFromSaved({})).toBeNull();
  });

  it("refuses half a coordinate", () => {
    // Half a point is worse than none: it would price and drive to the
    // meridian. The server falls back to the row's own stored point instead.
    expect(pointFromSaved({ latitude: 21.3026097, longitude: null })).toBeNull();
    expect(pointFromSaved({ latitude: null, longitude: 72.9159345 })).toBeNull();
  });

  it("keeps a coordinate of zero", () => {
    // 0,0 is in the Atlantic and no restaurant delivers there, but a falsy
    // check here would also discard a real longitude of 0 — Greenwich, Accra,
    // and everywhere else on the meridian.
    expect(pointFromSaved({ latitude: 5.6037, longitude: 0 })).toEqual({
      latitude: 5.6037,
      longitude: 0,
    });
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
      house: "",
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
      house: "",
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
      house: "",
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
    house: "",
    line1: "1600 Pennsylvania Avenue NW",
    line2: "Apt 4B",
    landmark: "",
    city: "Washington",
    state: "DC",
    zip: "20500",
  };

  it("matches an address saved with its house number in the line", () => {
    // A saved address is ONE line, so the flat number was written into it when
    // it was stored. Comparing only `line1` would miss the match and the picker
    // would fill up with a second copy of the same home every time somebody
    // ordered to it.
    expect(
      isSameAddress(
        { ...typed, house: "Apt 4B", line1: "1600 Pennsylvania Avenue NW", line2: "" },
        { ...saved, address_line_1: "Apt 4B, 1600 Pennsylvania Avenue NW", address_line_2: "" },
      ),
    ).toBe(true);
  });

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

/**
 * Checkout showed a returning customer "+91 +916353100362": the chip beside
 * the field carries the storefront's country code, and the profile stores the
 * number in full. Their own phone number, shown back to them wrong, in the
 * field they are least willing to see a mistake in.
 */
describe("phoneWithoutCountryCode", () => {
  it("drops the code the chip already shows", () => {
    expect(phoneWithoutCountryCode("+916353100362", "+91")).toBe("6353100362");
  });

  it("copes with the number stored spaced out", () => {
    expect(phoneWithoutCountryCode("+91 63531 00362", "+91")).toBe("6353100362");
  });

  it("leaves another country's number in full", () => {
    // Here the "+" is the point: the chip is wrong about this number, and the
    // digits are the only thing saying so.
    expect(phoneWithoutCountryCode("+14155550132", "+91")).toBe("+14155550132");
  });

  it("leaves a national number alone", () => {
    expect(phoneWithoutCountryCode("6353100362", "+91")).toBe("6353100362");
    expect(phoneWithoutCountryCode("(635) 310-0362", "+91")).toBe("(635) 310-0362");
  });

  it("does nothing when the storefront publishes no code", () => {
    expect(phoneWithoutCountryCode("+916353100362", undefined)).toBe("+916353100362");
    expect(phoneWithoutCountryCode("+916353100362", "")).toBe("+916353100362");
  });

  it("formats to a grouped national number once stripped", () => {
    // The pair, which is what checkout actually does.
    expect(formatPhoneAsTyped(phoneWithoutCountryCode("+916353100362", "+91"))).toBe(
      "(635) 310-0362",
    );
  });
});

describe("editKeepsPickedPoint", () => {
  it("keeps the point when only the flat or the landmark changes", async () => {
    const { editKeepsPickedPoint } = await import("./delivery-address");
    // Picked "Sheri Limda Chowk", then typed "Second floor" into the flat box:
    // the building did not move, so the point must not be thrown away.
    expect(editKeepsPickedPoint("house")).toBe(true);
    expect(editKeepsPickedPoint("landmark")).toBe(true);
  });

  it("drops the point when the street, area, city or PIN changes", async () => {
    const { editKeepsPickedPoint } = await import("./delivery-address");
    for (const part of ["line1", "line2", "city", "state", "zip"] as const) {
      expect(editKeepsPickedPoint(part)).toBe(false);
    }
  });
});
