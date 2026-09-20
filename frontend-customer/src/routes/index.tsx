import { Link, createFileRoute } from "@tanstack/react-router";
import {
  ArrowRight,
  Clock3,
  Flame,
  DollarSign,
  Leaf,
  MapPin,
  Soup,
  Sparkles,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { DishCard } from "@/components/bangkok/dish-card";
import { DishSkeleton } from "@/components/bangkok/menu-grid";
import { OfferCard } from "@/components/bangkok/offer-card";
import { WaiterPrompt } from "@/components/bangkok/waiter-prompt";
import { StorefrontHero } from "@/components/bangkok/storefront-hero";
import { hasCapability, useBangkokStore } from "@/lib/bangkok-store";
import { availabilityNow } from "@/lib/branch-hours";
import { useAuth } from "@/lib/auth";
import { useMenuItems, usePersonalizedOffers } from "@/lib/queries";
import { budgetChipAmount } from "@/lib/budget";
import { useMoney, useStorefrontCopy, useStorefrontCover } from "@/lib/storefront";

export const Route = createFileRoute("/")({
  // The root route already resolves this restaurant's copy from the request
  // host; the home page renders the hero from the same nine strings, so the
  // words in the tab and the words on the page cannot disagree.
  component: Home,
});

const CRAVING_CHIPS = [
  { label: "Something spicy", query: "Something spicy", icon: Flame },
  { label: "Comfort food", query: "Comfort food", icon: Soup },
  { label: "Light and fresh", query: "Something light and fresh", icon: Leaf },
  { label: "Feed two people", query: "Something to feed two people", icon: Users },
];

function Home() {
  // From the root route's loader, which read it off the request host — so the
  // hero is this restaurant's own words in the server-rendered HTML rather
  // than after a client fetch.
  const copy = useStorefrontCopy();
  const money = useMoney();
  const store = useBangkokStore();
  // Nothing invites a customer to a page this restaurant has switched off.
  const askAi = hasCapability(store.capabilities, "ask_ai");
  const { restaurantId, branchId, locations } = store;
  const { isAuthenticated } = useAuth();
  const menuQuery = useMenuItems(restaurantId, branchId || undefined);
  const offersQuery = usePersonalizedOffers(isAuthenticated);
  const items = menuQuery.data ?? [];
  // Two different sections wearing one heading. A restaurant that has marked
  // its bestsellers gets "Crowd favourites", which is then a fact. One that
  // has not gets the first eight rows the API returned, in no order anybody
  // chose — for a Surat dhokla shop that was four Chinese rice dishes under
  // the words "Most loved", which is not a small thing to be wrong about on
  // the first screen a customer sees. So the label follows the data: the same
  // eight dishes, honestly introduced, until somebody ticks Best seller in the
  // admin.
  const flagged = items.filter((i) => i.is_bestseller);
  const hasBestsellers = flagged.length > 0;
  const bestsellers = (hasBestsellers ? flagged : items).slice(0, 8);
  const offers = offersQuery.data ?? [];

  // Everything the hero says about this restaurant comes from the branch row
  // the admin filled in. It used to assert "Open now" whether or not it was,
  // invent "3 branches" while the list loaded, name a city in a literal, and
  // promise 35 minutes regardless of the branch's own ETA. A customer cannot
  // tell an invented fact from a real one, which is what makes them expensive.
  const branch = store.orderLocation ?? store.currentLocation;
  const openNow = availabilityNow(branch, store.fulfillment, new Date(), store.timeZone);
  const city = branch?.city;
  const heroEta = Number(branch?.estimated_delivery_time);
  const branchCount = locations.length;

  // A restaurant with a photograph of its own food earns the tall hero: the
  // picture IS the content. Without one the hero is a brand wash that says
  // nothing about the food (deliberately — see `StorefrontHero`), and at
  // 70svh a phone opens on two thirds of a screen of flat orange before any
  // dish appears. So the box follows what is in it. Radhe Dhokla gets the
  // tall one back the moment a cover image is uploaded in the admin.
  const heroHeight = useStorefrontCover() ? "min-h-[70svh]" : "min-h-[46svh] sm:min-h-[56svh]";

  const budget = budgetChipAmount(items.map((i) => Number(i.price)));
  const cravingChips = budget
    ? [
        ...CRAVING_CHIPS.slice(0, 1),
        {
          label: `Under ${money(budget)}`,
          query: `Something good under ${money(budget)}`,
          icon: DollarSign,
        },
        ...CRAVING_CHIPS.slice(1),
      ]
    : CRAVING_CHIPS;

  return (
    <div className="pb-20 lg:pb-0">
      <StorefrontHero className={heroHeight}>
        <div className="hero-overlay absolute inset-0" />
        <div
          className={`hero-copy page-pad relative flex ${heroHeight} max-w-3xl flex-col justify-end pb-12 pt-28 text-primary-foreground sm:pb-16`}
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
                className={`hero-chip text-primary-foreground ${
                  openNow.available ? "bg-success" : "bg-muted"
                }`}
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
                Explore the menu <ArrowRight />
              </Link>
            </Button>
            {askAi ? (
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

      <WaiterPrompt placement="home" />

      {isAuthenticated && offers.length > 0 && (
        <section className="page-pad section-pad !pb-0">
          <div className="mb-6">
            <p className="eyebrow">Picked for you</p>
            <h2 className="font-display text-3xl font-extrabold sm:text-4xl">
              Your personalised picks
            </h2>
          </div>
          <div className="offer-rail">
            {offers.map((offer, i) => (
              <div
                className="rise-in flex shrink-0"
                style={{ "--i": Math.min(i, 8) } as React.CSSProperties}
                key={offer.id}
              >
                <OfferCard offer={offer} />
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="page-pad section-pad">
        <div className="mb-7 flex items-end justify-between gap-4">
          <div>
            <p className="eyebrow">{hasBestsellers ? "Most loved" : "Straight from the kitchen"}</p>
            <h2 className="font-display text-3xl font-extrabold sm:text-4xl">
              {hasBestsellers ? "Crowd favourites" : "On the menu today"}
            </h2>
          </div>
          <Button variant="outline" asChild>
            <Link to="/menu">See all</Link>
          </Button>
        </div>
        {menuQuery.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <DishSkeleton key={i} />
            ))}
          </div>
        ) : (
          <div className="menu-grid grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {bestsellers.map((item, i) => (
              <div
                className="rise-in"
                style={{ "--i": Math.min(i, 8) } as React.CSSProperties}
                key={item.id}
              >
                <DishCard item={item} />
              </div>
            ))}
            {bestsellers.length === 0 && (
              <p className="text-muted">Bestsellers will appear here once the menu loads.</p>
            )}
          </div>
        )}
      </section>

      {/* The left half of this band is entirely about the concierge, so a
          restaurant without it gets the right half full-width rather than an
          invitation to a page that is not there. */}
      <section className={askAi ? "grid bg-surface-alt lg:grid-cols-2" : "grid bg-surface-alt"}>
        {askAi ? (
        <div className="page-pad section-pad">
          <Sparkles className="mb-5 size-10 text-primary" />
          <p className="eyebrow">Not sure what to order?</p>
          <h2 className="font-display text-4xl font-extrabold">
            Not sure what to eat? Tell us your craving.
          </h2>
          <p className="mt-4 max-w-xl text-muted">
            Tap a craving and our AI food concierge points you straight to a dish on the menu.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            {cravingChips.map((chip) => (
              <Link
                key={chip.label}
                to="/concierge"
                search={{ q: chip.query }}
                className="craving-chip"
              >
                <chip.icon className="size-4" />
                {chip.label}
              </Link>
            ))}
          </div>
          <Button variant="outline" className="mt-6" asChild>
            <Link to="/concierge">
              Or describe your own craving <ArrowRight />
            </Link>
          </Button>
        </div>
        ) : null}
        <div className="page-pad section-pad bg-primary text-primary-foreground">
          <Clock3 className="mb-5 size-10" />
          <p className="eyebrow eyebrow--inherit">Fast &amp; fresh</p>
          <h2 className="font-display text-4xl font-extrabold">
            {Number.isFinite(heroEta) && heroEta > 0
              ? `Cooked to order and at your door in about ${heroEta} minutes.`
              : "Cooked fresh to order, and on its way the moment it is ready."}
          </h2>
          <div className="mt-7 flex flex-wrap gap-3">
            {locations.map((l) => (
              <span key={l.id} className="rounded-full border border-primary-foreground px-4 py-2">
                {l.branch_name}
              </span>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
