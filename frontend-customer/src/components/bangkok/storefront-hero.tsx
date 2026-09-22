import { useStorefrontCopy, useStorefrontCover } from "@/lib/storefront";

/**
 * The backdrop behind a hero, for whichever restaurant this site belongs to.
 *
 * Three pages — home, sign in, sign up — each imported a bundled photograph
 * from `src/assets`: Bangkok Bowl's hero, its pad thai and its green curry.
 * Every tenant got them. A Surat dhokla shop's home page opened on a bowl of
 * Thai noodle salad and a tom yum, its sign-in page on pad thai.
 *
 * **A photograph of someone else's food is a claim, not decoration.** It tells
 * a customer what this kitchen makes, in the most prominent place on the site,
 * and it is wrong. So when a restaurant has no cover image of its own this
 * renders none: a wash built from that restaurant's brand colour, which says
 * nothing about the food and is the right colour for every tenant because
 * `--primary` is set from their branding at startup.
 *
 * The image is not lazy and carries no fade-in. It is the largest element
 * above the fold, so it is what the page is waiting on either way, and a hero
 * that fades in is a hero that is briefly absent.
 */
interface StorefrontHeroProps {
  /**
   * What sits over it. The overlay and the copy are the caller's, because the
   * three pages place them differently.
   */
  children: React.ReactNode;
  /** Hero sizes differ per page; the caller owns the box. */
  className?: string;
}

export function StorefrontHero({ children, className }: StorefrontHeroProps) {
  const cover = useStorefrontCover();
  const copy = useStorefrontCopy();

  return (
    <section className={`relative overflow-hidden ${className ?? ""}`}>
      {cover ? (
        <img
          alt={`Food from ${copy.name}`}
          className="absolute inset-0 size-full object-cover"
          src={cover}
        />
      ) : (
        // Not an empty div: a flat brand block behind white type reads as an
        // unloaded image. The gradient and the grain give it a deliberate
        // surface without saying anything about the food.
        <div aria-hidden className="storefront-hero-wash absolute inset-0" />
      )}
      {children}
    </section>
  );
}
