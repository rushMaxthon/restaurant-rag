import { useMemo } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import { ArrowRight, BookOpen, MapPin, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrandFaqs, BrandStory } from "@/components/bangkok/brand-story";
import { HowToOrder } from "@/components/bangkok/how-to-order";
import { KitchenGallery } from "@/components/bangkok/kitchen-gallery";
import { StorefrontHero } from "@/components/bangkok/storefront-hero";
import { TrustStrip } from "@/components/bangkok/trust-strip";
import { VisitUs } from "@/components/bangkok/visit-us";
import { hasCapability, useBangkokStore } from "@/lib/bangkok-store";
import { availabilityNow } from "@/lib/branch-hours";
import { pickBrandPhotos } from "@/lib/brand-photos";
import { useMenuItems } from "@/lib/queries";
import { useStorefrontBrand, useStorefrontCopy, useStorefrontCover } from "@/lib/storefront";

export const Route = createFileRoute("/")({
  // The root route already resolves this restaurant's copy from the request
  // host; the home page renders the hero from the same nine strings, so the
  // words in the tab and the words on the page cannot disagree.
  component: Home,
});

/**
 * The restaurant's own front page.
 *
 * **This page sells the kitchen. The menu page sells the food.** It used to do
 * both: a hero, a rail of category chips, eight dish cards under "Crowd
 * favourites", then the owner's words at the bottom where nobody reached them.
 * That is a storefront for a marketplace listing, not a website for a
 * business — the dishes were a worse version of `/menu`, which does the same
 * job with search, sorting, filters and a section rail, and they pushed the
 * one thing this page can say that no other page can below the fold.
 *
 * So everything shoppable is gone from here. In reading order it now answers
 * the questions a first-time visitor actually asks, in the order they ask
 * them: who is this (hero) → can I trust them, and are they open (the strip
 * of facts) → who are they really (their own story, beside their own food) →
 * what does it look like (the gallery) → how does ordering work (three steps)
 * → what about X (their own answers) → where are they, and when (the closing
 * band). One route into the menu from each block, and a permanent one in the
 * header.
 *
 * **Every claim on it comes from this restaurant's own rows**, and a block
 * whose rows are empty is absent rather than filled in: no story, no gallery,
 * no questions, no hours — just a shorter page. The alternative is prose
 * written once by us and shown under every tenant's name, which is the bug
 * `restaurant_storefront.py` and `restaurant_brand.py` both exist to have
 * fixed.
 */
function Home() {
  // From the root route's loader, which read it off the request host — so the
  // hero is this restaurant's own words in the server-rendered HTML rather
  // than after a client fetch.
  const copy = useStorefrontCopy();
  const brand = useStorefrontBrand();
  const store = useBangkokStore();
  // Nothing invites a customer to a page this restaurant has switched off.
  const askAi = hasCapability(store.capabilities, "ask_ai");
  const { restaurantId, branchId, locations } = store;
  const menuQuery = useMenuItems(restaurantId, branchId || undefined);
  // Memoised, not `?? []` inline: the fallback is a new array on every render,
  // so both derivations below would recompute on every render — and
  // `pickBrandPhotos` returning a new array each time would hand the gallery
  // new `src` keys and remount every photograph.
  const items = useMemo(() => menuQuery.data ?? [], [menuQuery.data]);

  // Eight: three set beside the lead story, five for the mosaic below it.
  // The rule spreads them across the menu's sections — see `pickBrandPhotos`,
  // which exists because the first version showed six photographs of cake.
  const photos = useMemo(() => pickBrandPhotos(items, 8), [items]);

  // How much there is to eat, counted from the rows rather than asserted.
  const sectionCount = useMemo(() => new Set(items.map((item) => item.category)).size, [items]);

  // Everything the hero says about this restaurant comes from the branch row
  // the admin filled in. It used to assert "Open now" whether or not it was,
  // invent "3 branches" while the list loaded, name a city in a literal, and
  // promise 35 minutes regardless of the branch's own ETA. A customer cannot
  // tell an invented fact from a real one, which is what makes them expensive.
  const branch = store.orderLocation ?? store.currentLocation;
  const openNow = availabilityNow(branch, store.fulfillment, new Date(), store.timeZone);
  const city = branch?.city;
  const branchCount = locations.length;
  const hasStory = brand.about_sections.length > 0;

  // A restaurant with a photograph of its own food earns the tall hero: the
  // picture IS the content. Without one the hero is a brand wash that says
  // nothing about the food (deliberately — see `StorefrontHero`), and at
  // 72svh a phone opens on two thirds of a screen of flat orange before
  // anything is said. So the box follows what is in it.
  const hasCover = Boolean(useStorefrontCover());
  const heroHeight = hasCover ? "min-h-[72svh]" : "min-h-[48svh] sm:min-h-[58svh]";

  return (
    <div className="pb-20 lg:pb-0">
      <StorefrontHero className={heroHeight}>
        <div className="hero-overlay absolute inset-0" />
        {/* No ink utility here: `.hero-copy` is white, because it is on a
            photograph. See the note on that class in polish.css — this used to
            be `text-primary-foreground`, which is the ink for the BRAND colour
            and resolved to near-black in dark mode. */}
        <div
          className={`hero-copy page-pad relative flex ${heroHeight} max-w-3xl flex-col justify-end pb-16 pt-28 sm:pb-20`}
        >
          <div className="mb-5 flex flex-wrap gap-2">
            {/* Nothing is claimed until it is known: no branch count before the
                list arrives, and no city that is not this branch's. */}
            {branchCount > 0 && (
              <span className="hero-chip bg-surface text-foreground">
                <MapPin className="size-4 text-primary" />
                {branchCount} {branchCount === 1 ? "branch" : "branches"}
                {city ? ` in ${city}` : ""}
              </span>
            )}
            {branch && (
              <span
                // The chip sits on `--success` or `--muted`, neither of which
                // is the brand, so the brand's ink token was never right here.
                className={`hero-chip text-white ${openNow.available ? "bg-success" : "bg-muted"}`}
              >
                {openNow.available ? "Open now" : "Closed right now"}
              </span>
            )}
          </div>
          <h1 className="font-display text-5xl font-extrabold leading-[.98] sm:text-7xl">
            {copy.hero_headline}
          </h1>
          <p className="mt-5 max-w-xl text-lg font-medium sm:text-xl">{copy.hero_subcopy}</p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Button size="lg" asChild>
              <Link to="/menu">
                See the menu <ArrowRight />
              </Link>
            </Button>
            {/* An in-page anchor, not a route: the story is directly below, and
                sending somebody to /about to read what is on the screen they
                are already on is a page load for nothing. A plain `<a>` with
                `scroll-margin-top` on the target, so it works before
                hydration and lands clear of the sticky header. */}
            {hasStory ? (
              <Button size="lg" variant="secondary" asChild>
                <a href="#story">
                  <BookOpen />
                  Who we are
                </a>
              </Button>
            ) : askAi ? (
              <Button size="lg" variant="secondary" asChild>
                <Link to="/concierge">
                  <Sparkles />
                  Ask the food concierge
                </Link>
              </Button>
            ) : null}
          </div>
        </div>
      </StorefrontHero>

      {/* Open or closed, how long, how much there is, where — read off the
          branch row, with fewer cells for a branch that has published less. */}
      <TrustStrip
        branch={branch}
        fulfillment={store.fulfillment}
        timeZone={store.timeZone}
        dishCount={items.length}
        sectionCount={sectionCount}
      />

      {/* The owner's own words, in a shape that follows what they wrote. */}
      <BrandStory photos={photos} />

      {/* Their own food, as photography rather than as a shop. The lead story
          has taken the first three, so the mosaic starts after them and
          disappears when there are not enough left to fill it. */}
      <KitchenGallery photos={photos.slice(3)} />

      <HowToOrder branch={branch} />

      <BrandFaqs />

      {/* The closing band. The left half is entirely about the concierge, so a
          restaurant without it gets the right half full-width. The right half
          is where to find the kitchen — address, directions and today's hours
          — which is the last thing somebody needs before they decide. */}
      <section className={askAi ? "grid bg-surface-alt lg:grid-cols-2" : "grid bg-surface-alt"}>
        {askAi ? (
          <div className="page-pad section-pad">
            <Sparkles className="mb-5 size-10 text-primary" />
            <p className="eyebrow">Not sure what to order?</p>
            <h2 className="font-display text-4xl font-extrabold">
              Tell us the craving. We will find it on the menu.
            </h2>
            <p className="mt-4 max-w-xl text-muted">
              Describe what you are after — spicy, light, enough for four — and the food concierge
              points you straight at it.
            </p>
            <Button size="lg" className="mt-7" asChild>
              <Link to="/concierge">
                Ask the food concierge <ArrowRight />
              </Link>
            </Button>
          </div>
        ) : null}
        <div className="page-pad section-pad bg-primary text-primary-foreground">
          <VisitUs branch={branch} />
        </div>
      </section>
    </div>
  );
}
