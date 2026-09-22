/**
 * Which drawing a dish with no photograph gets.
 *
 * 492 of Radhe Dhokla's 816 menu rows have no picture, and the stand-in was
 * two initials on a flat tint — a failed image, not a chosen one, most of the
 * way down the menu. A photograph cannot be invented and must not be
 * borrowed, so the gap is filled with a drawing taken from the dish's own
 * category.
 *
 * The rules that matter are about not being wrong: the motif has to be
 * recognisable as the food, the order of matching has to survive categories
 * that contain two words at once ("Tandoori Roti & Paratha" is bread, not a
 * kebab), and a dish must keep the same tile between visits — a card that
 * changes colour on reload reads as a bug.
 */

import { describe, expect, it } from "vitest";

import { GROUND_COUNT, groundFor, motifFor } from "./dish-motif";

describe("motifFor", () => {
  it("knows the things this restaurant is actually named after", () => {
    expect(motifFor("Corn Dhokla", "Jeera Corn Dhokla")).toBe("squares");
    expect(motifFor("Khaman", "Khaman")).toBe("squares");
    expect(motifFor("Idada", "Idada")).toBe("squares");
  });

  it("reads a two-word category by what the dish actually is", () => {
    // Contains both "tandoori" and "roti". It is bread.
    expect(motifFor("Tandoori Roti & Paratha", "Butter Roti")).toBe("flatbread");
  });

  it("puts rice under grains however the category is spelled", () => {
    expect(motifFor("Chinese Rice", "American Corn Fried Rice")).toBe("grains");
    expect(motifFor("Biryani", "Nawabi Pudina Ghee Biryani")).toBe("grains");
    expect(motifFor("Pulao", "Veg Pulao")).toBe("grains");
  });

  it("gives the wet dishes a bowl", () => {
    expect(motifFor("Rice & Dal", "Dal Fry")).toBe("bowl");
    expect(motifFor("Soup", "Hot and Sour Soup")).toBe("bowl");
    expect(motifFor("Pavbhaji", "Cheese Pavbhaji")).toBe("bowl");
  });

  it("falls back to the dish's name when the category says nothing", () => {
    // Some menus file everything under one heading.
    expect(motifFor("Specials", "Paneer Tikka")).toBe("cubes");
    expect(motifFor(null, "Hakka Noodles")).toBe("noodles");
  });

  it("gives anything unrecognised a plate, which is true of every dish", () => {
    expect(motifFor("Chef's Corner", "House Special")).toBe("plate");
    expect(motifFor("", "")).toBe("plate");
  });

  it("does not care about case", () => {
    expect(motifFor("KHAMAN", "KHAMAN")).toBe(motifFor("khaman", "khaman"));
  });

  it("matches a word this restaurant has not invented yet", () => {
    // The point of matching on words rather than an exact list: a new dhokla
    // on the menu tomorrow gets the right drawing with no edit here.
    expect(motifFor("Masala Dhokla", "Masala Dhokla")).toBe("squares");
  });
});

describe("groundFor", () => {
  it("gives the same dish the same ground every time", () => {
    // A tile that changes colour between the menu and the page it opens, or
    // between one visit and the next, reads as a bug.
    expect(groundFor("Paneer Afghani (Creamy Red)")).toBe(groundFor("Paneer Afghani (Creamy Red)"));
  });

  it("stays inside the palette", () => {
    for (const name of ["a", "Dal Fry", "Nawabi Pudina Ghee Biryani (Green)", "x".repeat(200)]) {
      const ground = groundFor(name);
      expect(ground).toBeGreaterThanOrEqual(0);
      expect(ground).toBeLessThan(GROUND_COUNT);
      expect(Number.isInteger(ground)).toBe(true);
    }
  });

  it("does not hand one colour to a whole category", () => {
    // Four paneer dishes sitting in a row should not come out as four
    // identical tiles.
    const names = [
      "Cheese Angoori (Brown)",
      "Cheese Butter Masala (Brown)",
      "Palak Paneer (Green)",
      "Paneer Afghani (Creamy Red)",
      "Paneer Tikka Masala",
      "Shahi Paneer",
    ];
    expect(new Set(names.map(groundFor)).size).toBeGreaterThan(1);
  });

  it("survives an empty name without throwing", () => {
    expect(groundFor("")).toBe(0);
  });
});
