import { useState } from "react";

import { DishMotif } from "@/components/bangkok/dish-motif";
import { groundFor, motifFor } from "@/lib/dish-motif";
import { cn } from "@/lib/utils";

/**
 * A dish's picture, or something worth looking at instead.
 *
 * Two things were wrong with the old stand-in. It was two initials on a flat
 * pastel — "AM" for Aloo Mater — which reads as a failed image rather than a
 * chosen one; and 82 of the 136 dishes at a Radhe Dhokla branch have no
 * photograph, so that was most of the menu. A photograph cannot be invented
 * and must not be borrowed (see `StorefrontHero` for what borrowing one
 * costs), so the honest move is a drawing that is plainly a drawing, picked
 * from the dish's own category so a scroll down the menu has some variety in
 * it.
 *
 * The real photograph, when there is one, fades up as it decodes instead of
 * snapping in under the text — and it fades up from the same motif, so the
 * tile is never empty and never changes size.
 */
export function DishImage({
  src,
  name,
  category,
  className,
  priority = false,
}: {
  src: string | null;
  name: string;
  /** The kitchen's own grouping, which picks the drawing. */
  category?: string | null;
  className?: string;
  priority?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const motif = motifFor(category, name);
  const ground = groundFor(name);

  return (
    <div
      // The ratio and width stay Tailwind classes rather than moving into
      // `.dish-motif`, because callers override them through tailwind-merge:
      // the waiter prompt asks for `aspect-square h-14 w-14`, and a plain CSS
      // rule would not be dropped by that merge.
      className={cn("dish-motif aspect-[4/3] w-full", className)}
      data-ground={ground}
      role="img"
      aria-label={src && !failed ? name : `${name} — no photograph yet`}
    >
      <DishMotif motif={motif} seed={ground} />
      {src && !failed && (
        <img
          alt=""
          className="dish-motif__photo"
          data-loaded={loaded}
          // Below the fold on a 136-dish menu, this is most of the page's
          // weight; `lazy` keeps it off the wire until it is nearly in view.
          decoding="async"
          loading={priority ? "eager" : "lazy"}
          height={700}
          onError={() => setFailed(true)}
          onLoad={() => setLoaded(true)}
          src={src}
          width={900}
        />
      )}
    </div>
  );
}
