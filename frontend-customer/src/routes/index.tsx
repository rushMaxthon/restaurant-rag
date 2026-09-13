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
import heroImage from "@/assets/bangkok-bowl-hero.jpg";
import { Button } from "@/components/ui/button";
import { DishCard } from "@/components/bangkok/dish-card";
import { DishSkeleton } from "@/components/bangkok/menu-grid";
import { OfferCard } from "@/components/bangkok/offer-card";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useAuth } from "@/lib/auth";
import { useMenuItems, usePersonalizedOffers } from "@/lib/queries";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Bangkok Bowl — Thai Food Delivery Ahmedabad" },
      {
        name: "description",
        content:
          "Order fresh Thai noodles, curries and bowls from three Bangkok Bowl branches in Ahmedabad.",
      },
      { property: "og:title", content: "Bangkok Bowl — Thai Food Delivery Ahmedabad" },
      {
        property: "og:description",
        content: "Big Thai flavour, cooked fresh and delivered across Ahmedabad.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Home,
});

const CRAVING_CHIPS = [
  { label: "Something spicy", query: "Something spicy", icon: Flame },
  { label: "Under $15", query: "Something good under $15", icon: DollarSign },
  { label: "Comfort food", query: "Comfort food", icon: Soup },
  { label: "Light and fresh", query: "Something light and fresh", icon: Leaf },
  { label: "Feed two people", query: "Something to feed two people", icon: Users },
];

function Home() {
  const { restaurantId, branchId, locations } = useBangkokStore();
  const { isAuthenticated } = useAuth();
  const menuQuery = useMenuItems(restaurantId, branchId || undefined);
  const offersQuery = usePersonalizedOffers(isAuthenticated);
  const items = menuQuery.data ?? [];
  const bestsellers = (
    items.filter((i) => i.is_bestseller).length ? items.filter((i) => i.is_bestseller) : items
  ).slice(0, 8);
  const offers = offersQuery.data ?? [];

  return (
    <div className="pb-20 lg:pb-0">
      <section className="relative min-h-[70svh] overflow-hidden">
        <img
          src={heroImage}
          alt="A colourful Bangkok Bowl Thai food spread"
          width={1600}
          height={912}
          className="absolute inset-0 size-full object-cover"
        />
        <div className="hero-overlay absolute inset-0" />
        <div className="hero-copy page-pad relative flex min-h-[70svh] max-w-3xl flex-col justify-end pb-12 pt-28 text-primary-foreground sm:pb-16">
          <div className="mb-5 flex flex-wrap gap-2">
            <span className="hero-chip bg-surface text-foreground">
              <MapPin className="size-4 text-primary" />
              {locations.length || 3} branches in Ahmedabad
            </span>
            <span className="hero-chip bg-success text-primary-foreground">Open now</span>
          </div>
          <h1 className="font-display text-5xl font-black leading-[.98] sm:text-7xl">
            Bangkok Bowl
          </h1>
          <p className="mt-5 max-w-xl text-lg font-medium sm:text-xl">
            Wok-fired noodles, velvety curries and bold Bangkok street flavours—made fresh for you.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Button size="lg" asChild>
              <Link to="/menu">
                Explore the menu <ArrowRight />
              </Link>
            </Button>
            <Button size="lg" variant="secondary" asChild>
              <Link to="/concierge">
                <Sparkles />
                Ask the food concierge
              </Link>
            </Button>
          </div>
        </div>
      </section>

      {isAuthenticated && offers.length > 0 && (
        <section className="page-pad section-pad !pb-0">
          <div className="mb-6">
            <p className="eyebrow">Picked for you</p>
            <h2 className="font-display text-3xl font-black sm:text-4xl">
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
            <p className="eyebrow">Most loved</p>
            <h2 className="font-display text-3xl font-black sm:text-4xl">Crowd favourites</h2>
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

      <section className="grid bg-surface-alt lg:grid-cols-2">
        <div className="page-pad section-pad">
          <Sparkles className="mb-5 size-10 text-primary" />
          <p className="eyebrow">Not sure what to order?</p>
          <h2 className="font-display text-4xl font-black">
            Not sure what to eat? Tell us your craving.
          </h2>
          <p className="mt-4 max-w-xl text-muted">
            Tap a craving and our AI food concierge points you straight to a dish on the menu.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            {CRAVING_CHIPS.map((chip) => (
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
        <div className="page-pad section-pad bg-primary text-primary-foreground">
          <Clock3 className="mb-5 size-10" />
          <p className="eyebrow eyebrow--inherit">Fast &amp; fresh</p>
          <h2 className="font-display text-4xl font-black">
            Dinner from wok to door in about 35 minutes.
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
