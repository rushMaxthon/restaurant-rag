import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";

import type { BrandPhoto } from "@/lib/brand-photos";
import { useStorefrontCopy } from "@/lib/storefront";

/**
 * A look at what comes out of this kitchen.
 *
 * **This is photography, not a menu.** No price, no quantity, no add button,
 * nothing that can be put in a cart — the menu has its own page, and a brand
 * home page that reprints eight dish cards is a shop window pretending to be a
 * shop. What this answers is the question a photograph answers better than any
 * sentence can: does the food look like something I want.
 *
 * It matters more here than it would on an English-language storefront. For
 * the customers this platform is being sold into, an unfamiliar bakery's site
 * is judged on its pictures in about a second, and a page of type with one
 * hero image reads as a listing rather than as a business.
 *
 * Every photograph is the restaurant's own, uploaded against its own dishes,
 * and chosen by `pickBrandPhotos` so the collage spans the kitchen rather than
 * showing six photographs of cake. The dish's name is the caption AND the alt
 * text, so what is being shown is never implied — a scrim-and-label on a
 * photograph nobody can identify is decoration dressed as information.
 *
 * Renders nothing below three photographs. One or two in a mosaic built for
 * six is a layout with holes in it, and the lead story above has already used
 * the best of them.
 */
export function KitchenGallery({
  photos,
  loading = false,
}: {
  photos: readonly BrandPhoto[];
  loading?: boolean;
}) {
  const copy = useStorefrontCopy();

  // The menu is fetched on the client, so this block has nothing to show for
  // the first second or so of a cold visit. Rendering nothing and then
  // appearing shoves everything below it down the page while somebody is
  // reading it; the mosaic holds its own shape until the photographs arrive.
  if (loading && photos.length === 0) {
    return (
      <section className="gallery" aria-hidden="true">
        <div className="page-pad section-pad gallery__inner">
          <div className="gallery__head">
            <div>
              <p className="eyebrow">From our kitchen</p>
              <h2 className="font-display gallery__title reveal-wipe">
                <span>{copy.kitchen_headline}</span>
              </h2>
            </div>
          </div>
          <ul className="gallery__grid">
            {Array.from({ length: 5 }).map((_, index) => (
              <li className="gallery__tile" data-lead={index === 0 ? true : undefined} key={index}>
                <span className="gallery__placeholder skeleton" />
              </li>
            ))}
          </ul>
        </div>
      </section>
    );
  }

  if (photos.length < 3) return null;

  // Five fills the mosaic exactly: the lead tile two wide and two tall, four
  // singles filling the rest of a four-column, two-row grid. Six leaves a
  // single tile alone on a third row, which reads as a photograph that failed
  // to load. Fewer than five still tiles, because every cell after the lead
  // is the same size.
  const shown = photos.slice(0, 5);

  return (
    <section className="gallery">
      <div className="page-pad section-pad gallery__inner">
        <div className="gallery__head reveal">
          <div>
            <p className="eyebrow">From our kitchen</p>
            <h2 className="font-display gallery__title reveal-wipe">
              <span>{copy.kitchen_headline}</span>
            </h2>
          </div>
          {/* The one way out of this block, and it goes to the menu — where
              the prices, the sizes and the add buttons are. */}
          <Link className="gallery__cta" to="/menu">
            Browse everything <ArrowRight aria-hidden="true" />
          </Link>
        </div>

        <ul className="gallery__grid reveal-group--settle parallax-img">
          {shown.map((photo, index) => (
            <li
              className="gallery__tile"
              data-lead={index === 0 ? true : undefined}
              key={photo.src}
            >
              <img
                alt={`${photo.alt} from ${copy.name}`}
                /* Not lazy for the lead tile on a phone, where it is often the
                   first photograph after the hero; lazy for the rest, which
                   are reliably below the fold at every width. */
                loading={index === 0 ? "eager" : "lazy"}
                src={photo.src}
              />
              <span className="gallery__label">
                <strong>{photo.alt}</strong>
                <small>{photo.category}</small>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
