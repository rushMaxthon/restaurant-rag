/**
 * Which drawing stands in for a dish that has no photograph.
 *
 * 82 of the 136 dishes at a Radhe Dhokla branch have no picture, and what
 * filled the gap was two initials on a flat pastel square — which reads as a
 * missing image rather than a considered one, 82 times down a menu.
 *
 * A photograph cannot be invented here and must not be borrowed: a picture of
 * someone else's dhokla is a claim about this kitchen, which is exactly the
 * bug that put Bangkok Bowl's pad thai on every tenant's home page. So the
 * gap is filled with something that is obviously a drawing — a motif chosen
 * from the dish's own category, so a wall of them reads as a menu rather than
 * as a wall of the same tile.
 *
 * Categories are a restaurant's own free text, so this matches on words
 * rather than on an exact list: "Corn Dhokla", "Khaman" and "Idada" are all
 * steamed-and-cut, and a restaurant that adds "Masala Dhokla" tomorrow gets
 * the right drawing without anybody editing this file. Anything unrecognised
 * gets the plate, which is true of every dish ever served.
 */

export type Motif =
  | "squares"
  | "grains"
  | "flatbread"
  | "noodles"
  | "bowl"
  | "cubes"
  | "thali"
  | "leaf"
  | "plate";

/**
 * Word → motif, in priority order: the FIRST match wins, so the specific
 * entries have to sit above the general ones. "Tandoori Roti & Paratha"
 * contains both "tandoori" and "roti", and it is bread.
 */
const BY_WORD: ReadonlyArray<readonly [string, Motif]> = [
  ["dhokla", "squares"],
  ["khaman", "squares"],
  ["idada", "squares"],
  ["roti", "flatbread"],
  ["paratha", "flatbread"],
  ["chapati", "flatbread"],
  ["naan", "flatbread"],
  ["puri", "flatbread"],
  ["noodle", "noodles"],
  ["hakka", "noodles"],
  ["chowmein", "noodles"],
  ["soup", "bowl"],
  ["dal", "bowl"],
  ["curry", "bowl"],
  ["gravy", "bowl"],
  ["pavbhaji", "bowl"],
  ["biryani", "grains"],
  ["pulao", "grains"],
  ["rice", "grains"],
  ["fried rice", "grains"],
  ["thali", "thali"],
  ["paneer", "cubes"],
  ["kofta", "cubes"],
  ["kaju", "cubes"],
  ["tikka", "cubes"],
  ["starter", "cubes"],
  ["farsan", "cubes"],
  ["vegetable", "leaf"],
  ["salad", "leaf"],
  ["veg", "leaf"],
];

/**
 * The motif for a dish, from its category and then its name.
 *
 * The category is asked first because it is the kitchen's own grouping and
 * describes the dish more reliably than a name can — "Tripple Rice" is in
 * "Chinese Rice", but "Manchurian Rice" could be anything. The name is the
 * fallback for a menu whose categories are thin, and the plate is the
 * fallback for both.
 */
export function motifFor(category: string | null | undefined, name: string): Motif {
  for (const source of [category ?? "", name]) {
    const text = source.toLowerCase();
    for (const [word, motif] of BY_WORD) {
      if (text.includes(word)) {
        return motif;
      }
    }
  }
  return "plate";
}

/** How many grounds the palette below offers. */
export const GROUND_COUNT = 5;

/**
 * Which of the grounds this dish sits on.
 *
 * Deterministic, so a dish keeps its colour between visits and between the
 * card and the page it opens — a tile that changes colour on reload reads as
 * a bug. Hashed from the name rather than taken from the list position, so
 * neighbours in a category do not come out striped.
 */
export function groundFor(name: string): number {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    // The classic djb2 step, kept in 32-bit range: `|0` after each round
    // stops a long dish name from drifting into float territory, where
    // different engines could round differently and the same dish could get
    // two colours on two devices.
    hash = (hash * 33 + name.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % GROUND_COUNT;
}
