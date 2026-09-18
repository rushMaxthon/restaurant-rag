import { createFileRoute } from "@tanstack/react-router";
import { MenuGrid } from "@/components/bangkok/menu-grid";
import { UsualsAndPairs } from "@/components/bangkok/usuals-and-pairs";
import { pageMeta, useStorefrontCopy } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";
export const Route = createFileRoute("/menu/")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Menu", "Browse the full menu and order online."),
  }),
  component: MenuPage,
});
function MenuPage() {
  // This restaurant's own name, resolved from the address in the root route.
  const copy = useStorefrontCopy();
  return (
    <div className="page-pad pb-24 pt-10">
      <p className="eyebrow">Cooked to order</p>
      <h1 className="font-display text-4xl font-extrabold sm:text-6xl">
        The {copy.name} menu
      </h1>
      <p className="mt-3 max-w-2xl text-muted">
        Made fresh to order. Pick a favourite or discover something new.
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
