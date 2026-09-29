import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { MenuGrid } from "@/components/bangkok/menu-grid";
import { UsualsAndPairs } from "@/components/bangkok/usuals-and-pairs";
import { pageMeta, useStorefrontCopy } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";
export const Route = createFileRoute("/menu/")({
  /**
   * The section lives in the address.
   *
   * It was state inside the grid, so a menu of 21 sections could not be
   * linked to, shared, or returned to with the back button, and the home page
   * had no way to send anybody into one. "All" is the default and is left out
   * of the URL rather than written into it, so the plain /menu link stays
   * plain.
   */
  validateSearch: (search: Record<string, unknown>): { category?: string } => {
    const category = typeof search["category"] === "string" ? search["category"].trim() : "";
    return category && category !== "All" ? { category } : {};
  },
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Menu", "Browse the full menu and order online."),
  }),
  component: MenuPage,
});
function MenuPage() {
  // This restaurant's own name, resolved from the address in the root route.
  const copy = useStorefrontCopy();
  const { category = "All" } = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  // `replace` so browsing sections does not fill the back button with them:
  // back should leave the menu, not walk every section they tried.
  const chooseCategory = (next: string) =>
    navigate({
      search: next && next !== "All" ? { category: next } : {},
      replace: true,
    });
  // The header is tighter on a phone, on purpose. This heading, its eyebrow
  // and its subtitle took about 170px above the search box, and the category
  // chips and the result count take more below it — so a customer opening a
  // menu of 136 dishes on a phone could see one of them. The words are worth
  // keeping where there is room; the subtitle is the line that tells a hungry
  // person nothing they cannot see for themselves, so it is the one that goes.
  return (
    <div className="page-pad pb-24 pt-6 sm:pt-10">
      <p className="eyebrow">Cooked to order</p>
      <h1 className="font-display text-3xl font-extrabold sm:text-6xl">The {copy.name} menu</h1>
      <p className="mt-3 hidden max-w-2xl text-muted sm:block">
        Made fresh to order. Pick a favourite or discover something new.
      </p>
      {/* Above the menu because this is where someone lands when they are
          hungry: the thing they always order, and what other people pair. Both
          disappear when there is nothing to show. */}
      <UsualsAndPairs />
      <div className="mt-8">
        <MenuGrid category={category} onCategoryChange={chooseCategory} />
      </div>
    </div>
  );
}
