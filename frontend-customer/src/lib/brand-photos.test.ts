/**
 * The brand page's collage has to look like the whole kitchen.
 *
 * The first version took the first eight rows with a photograph. The API
 * returns a menu grouped by category, so on a bakery of 187 dishes across 19
 * sections that was eight photographs of cake under the words "from our
 * kitchen" — every one of them true, and together a claim about the range
 * that was wrong. The rule is the fix, and these are the cases that made it.
 */

import { describe, expect, it } from "vitest";

import { pickBrandPhotos, type PhotoSource } from "./brand-photos";

const dish = (name: string, category: string, extra: Partial<PhotoSource> = {}): PhotoSource => ({
  name,
  category,
  image_url: `https://img.example/${name}.jpg`,
  ...extra,
});

const names = (items: readonly PhotoSource[], limit: number) =>
  pickBrandPhotos(items, limit).map((photo) => photo.alt);

const categories = (items: readonly PhotoSource[], limit: number) =>
  pickBrandPhotos(items, limit).map((photo) => photo.category);

describe("pickBrandPhotos", () => {
  it("spreads across categories rather than taking the first rows", () => {
    const menu = [
      dish("Choco cake", "Cakes"),
      dish("Vanilla cake", "Cakes"),
      dish("Fruit cake", "Cakes"),
      dish("Khari", "Khari"),
      dish("Sev", "Namkeen"),
    ];
    // Three cakes sit at the front of the list; the collage takes one.
    expect(categories(menu, 3)).toEqual(["Cakes", "Khari", "Namkeen"]);
  });

  it("comes back for a second photograph once every category has had one", () => {
    const menu = [dish("A", "One"), dish("B", "One"), dish("C", "Two")];
    expect(categories(menu, 4)).toEqual(["One", "Two", "One"]);
  });

  it("leads with the biggest section, because that is what the kitchen majors in", () => {
    const menu = [dish("Solo", "Chocolates"), dish("A", "Breads"), dish("B", "Breads")];
    expect(categories(menu, 1)).toEqual(["Breads"]);
  });

  it("represents a section with its most popular photographed dish", () => {
    const menu = [
      dish("Quiet one", "Cakes", { popularity_score: 1 }),
      dish("The one people order", "Cakes", { popularity_score: 99 }),
    ];
    expect(names(menu, 1)).toEqual(["The one people order"]);
  });

  it("reads a score the API sent as a string", () => {
    // Decimal columns arrive as strings over JSON, and `"9" > "80"` as text.
    const menu = [
      dish("Eighty", "Cakes", { popularity_score: "80" }),
      dish("Nine", "Cakes", { popularity_score: "9" }),
    ];
    expect(names(menu, 1)).toEqual(["Eighty"]);
  });

  it("is stable for the same menu, so the page does not reshuffle on a render", () => {
    const menu = [dish("B", "Cakes"), dish("A", "Cakes"), dish("C", "Cakes")];
    expect(names(menu, 3)).toEqual(names(menu, 3));
    // Unscored dishes fall back to the name rather than to row order.
    expect(names(menu, 3)).toEqual(["A", "B", "C"]);
  });

  it("skips dishes with no photograph", () => {
    const menu = [dish("No photo", "Cakes", { image_url: null }), dish("Photographed", "Cakes")];
    expect(names(menu, 5)).toEqual(["Photographed"]);
  });

  it("returns nothing when the restaurant has uploaded no photographs", () => {
    // No gallery rather than a substitute: see the note on the rule itself.
    expect(pickBrandPhotos([dish("X", "Cakes", { image_url: null })], 6)).toEqual([]);
    expect(pickBrandPhotos([], 6)).toEqual([]);
  });

  it("returns fewer than asked rather than repeating a dish", () => {
    const menu = [dish("A", "One"), dish("B", "Two")];
    expect(names(menu, 8)).toEqual(["A", "B"]);
  });

  it("asked for nothing, gives nothing", () => {
    expect(pickBrandPhotos([dish("A", "One")], 0)).toEqual([]);
  });

  it("ranks a search thumbnail below a real photograph of the same section", () => {
    // A third of this bakery's menu points at Google's image thumbnails, which
    // are fine in a dish card and fall apart in a 570px tile.
    const menu = [
      dish("Thumbnail", "Cakes", {
        image_url: "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9Gc",
        popularity_score: 99,
      }),
      dish("Real photo", "Cakes", { image_url: "https://cdn.shop/real.jpg", popularity_score: 1 }),
    ];
    expect(names(menu, 2)).toEqual(["Real photo", "Thumbnail"]);
  });

  it("still uses thumbnails when that is all the kitchen has", () => {
    // No gallery at all is the worse outcome.
    const menu = [dish("Only one", "Cakes", { image_url: "https://lh3.gstatic.com/x.jpg" })];
    expect(names(menu, 2)).toEqual(["Only one"]);
  });

  it("demotes a watermarked stock preview", () => {
    const menu = [
      dish("Stock", "Cakes", { image_url: "https://as1.ftcdn.net/v2/jpg/06/76/x.jpg" }),
      dish("Ours", "Cakes", { image_url: "/uploads/ours.jpg" }),
    ];
    expect(names(menu, 2)).toEqual(["Ours", "Stock"]);
  });

  it("matches the host, not the dish name or the path", () => {
    // A dish called "Alamy special", or a path that happens to contain a
    // stock library's name, is not a thumbnail.
    const menu = [
      dish("Alamy special", "Cakes", { image_url: "https://cdn.shop/alamy.com/photo.jpg" }),
      dish("Other", "Cakes", { image_url: "https://cdn.shop/b.jpg" }),
    ];
    expect(names(menu, 2)).toEqual(["Alamy special", "Other"]);
  });

  it("carries the dish name as the alt text", () => {
    // "Food" tells a screen reader nothing; the dish's own name is a fact.
    expect(pickBrandPhotos([dish("Mawa Cake", "Cakes")], 1)[0]).toMatchObject({
      alt: "Mawa Cake",
      src: "https://img.example/Mawa Cake.jpg",
    });
  });
});
