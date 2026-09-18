import { createFileRoute } from "@tanstack/react-router";
import { MenuGrid } from "@/components/bangkok/menu-grid";
import { UsualsAndPairs } from "@/components/bangkok/usuals-and-pairs";
export const Route = createFileRoute("/menu/")({
  head: () => ({
    meta: [
      { title: "Thai Menu — Bangkok Bowl" },
      {
        name: "description",
        content: "Browse Thai curries, noodles, rice bowls, starters, desserts and drinks.",
      },
      { property: "og:title", content: "Thai Menu — Bangkok Bowl" },
      {
        property: "og:description",
        content: "Explore the complete Bangkok Bowl menu in Ahmedabad.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: MenuPage,
});
function MenuPage() {
  return (
    <div className="page-pad pb-24 pt-10">
      <p className="eyebrow">Cooked to order</p>
      <h1 className="font-display text-4xl font-extrabold sm:text-6xl">The Bangkok menu</h1>
      <p className="mt-3 max-w-2xl text-muted">
        Fragrant, punchy and made fresh. Pick a favourite or discover something new.
      </p>
      {/* Above the menu because this is where someone lands when they are
          hungry: the thing they always order, and what other people pair. Both
          disappear when there is nothing to show. */}
      <UsualsAndPairs />
      <div className="mt-8">
        <MenuGrid />
      </div>
    </div>
  );
}
