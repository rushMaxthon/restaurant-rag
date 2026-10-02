/**
 * Just the columns this rule reads, so it can be stated — and tested —
 * without building a whole `MenuItem`. The same shape `menu-sorts.ts` takes,
 * for the same reason.
 */
export type PhotoSource = {
  name: string;
  category: string;
  image_url: string | null;
  popularity_score?: number | string | null;
};

export type BrandPhoto = {
  src: string;
  /** The dish's own name, so the alt text is a fact rather than "food". */
  alt: string;
  /** Carried so a caption can name the part of the kitchen it came from. */
  category: string;
};

/**
 * A handful of this restaurant's own food photographs, for the brand page.
 *
 * This is imagery, not a menu: no price, no add button, nothing to buy. The
 * menu has its own page and its own grid. What a brand page needs is evidence
 * that a real kitchen stands behind the words — and for an Indian storefront
 * especially, photographs of the actual food are the single strongest reason
 * somebody stays on the page long enough to read any of it.
 *
 * **Round-robin across categories, not the first N rows.** A bakery's rows
 * arrive grouped, so taking the first eight gave eight photographs of cake
 * under the words "from our kitchen" — a true statement illustrated so
 * narrowly that it reads as the whole range. One pass takes the best-ranked
 * item from each category in turn, then a second pass fills from the same
 * order, so a six-photo collage spans six parts of the menu and a kitchen with
 * two categories still fills the grid.
 *
 * Ordered within a category by picture QUALITY first and the platform's own
 * popularity score second, so the photograph that represents a section is a
 * real photograph of the dish people actually order from it.
 *
 * Quality is judged by where the file is served from, which is the only
 * signal available before the image loads. A third of this bakery's menu
 * points at `encrypted-tbn0.gstatic.com` — Google's search THUMBNAILS, a few
 * hundred pixels wide and hotlinked — and one at a stock library's
 * watermarked preview. Both are passable in a 200px dish card and neither
 * survives being blown up to a 570px tile on the page that is supposed to
 * show this kitchen at its best. So they rank last rather than being
 * excluded: a restaurant whose every photograph is a thumbnail still gets a
 * gallery, because no gallery at all would be the worse outcome.
 *
 * Returns fewer than asked, or nothing at all, when the menu carries fewer
 * photographs — a restaurant that has uploaded none gets no gallery, and the
 * page closes up around it. Nothing is ever substituted: a stock photograph of
 * someone else's food is a claim about this kitchen, which is the bug the
 * whole storefront layer exists to have fixed.
 */
export function pickBrandPhotos(items: readonly PhotoSource[], limit: number): BrandPhoto[] {
  if (limit <= 0) return [];

  const byCategory = new Map<string, PhotoSource[]>();
  for (const item of items) {
    // `is_available` is deliberately NOT a filter. A dish that has sold out
    // today is still something this kitchen makes, and a gallery that empties
    // itself at 9pm tells a customer the restaurant has nothing to offer.
    if (!item.image_url) continue;
    const bucket = byCategory.get(item.category);
    if (bucket) bucket.push(item);
    else byCategory.set(item.category, [item]);
  }
  if (byCategory.size === 0) return [];

  // Biggest sections first, so the lead photograph comes from the part of the
  // menu this kitchen actually majors in.
  const categories = [...byCategory.entries()].sort((a, b) => b[1].length - a[1].length);
  for (const [, bucket] of categories) {
    bucket.sort((a, b) => {
      const byQuality = rankOf(a.image_url) - rankOf(b.image_url);
      if (byQuality !== 0) return byQuality;
      const byScore = Number(b.popularity_score ?? 0) - Number(a.popularity_score ?? 0);
      // Then by name, so the same menu always produces the same collage. A
      // gallery that reshuffles on every render is a page that looks broken.
      return byScore !== 0 ? byScore : a.name.localeCompare(b.name);
    });
  }

  const photos: BrandPhoto[] = [];
  const taken = new Map<string, number>();
  // Keeps going while any category still has an unused photograph, so the
  // limit is only missed when the menu genuinely cannot fill it.
  let progressed = true;
  while (photos.length < limit && progressed) {
    progressed = false;
    for (const [category, bucket] of categories) {
      if (photos.length >= limit) break;
      const at = taken.get(category) ?? 0;
      const item = bucket[at];
      if (!item) continue;
      taken.set(category, at + 1);
      photos.push({ src: item.image_url!, alt: item.name, category });
      progressed = true;
    }
  }
  return photos;
}

/**
 * Hosts that serve search thumbnails or watermarked stock previews.
 *
 * Matched on the host rather than the whole URL, so a dish merely NAMED
 * "alamy special" is not demoted. `ftcdn.net` is on the list because it is
 * where Adobe serves its previews from — the first version named only
 * `adobestock.com` and the lead photograph on this bakery's page stayed a
 * watermarked packet of bhujia. Lower is better; everything unrecognised is
 * treated as a real photograph, because the common case is a restaurant
 * hosting its own.
 */
const THUMBNAIL_HOSTS =
  /(^|\.)(gstatic\.com|ftcdn\.net|adobestock\.com|shutterstock\.com|istockphoto\.com|dreamstime\.com|alamy\.com|123rf\.com)$/i;

function rankOf(url: string | null): number {
  if (!url) return 2;
  try {
    return THUMBNAIL_HOSTS.test(new URL(url).hostname) ? 1 : 0;
  } catch {
    // A relative path is this app's own upload, which is the good case.
    return 0;
  }
}
