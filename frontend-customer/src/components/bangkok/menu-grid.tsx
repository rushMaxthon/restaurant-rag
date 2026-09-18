import { useMemo, useState } from "react";
import { Leaf, Search, SlidersHorizontal, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { deriveCategories, type MenuItem } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useMenuItems } from "@/lib/queries";
import { DishCard } from "./dish-card";

type Sort = "recommended" | "price-asc" | "price-desc" | "rating";

const SORTS: { value: Sort; label: string }[] = [
  { value: "recommended", label: "Recommended" },
  { value: "price-asc", label: "Price: low to high" },
  { value: "price-desc", label: "Price: high to low" },
  { value: "rating", label: "Top rated" },
];

/** Bestsellers first, then rating — the order the menu arrives in is arbitrary. */
function compare(sort: Sort, a: MenuItem, b: MenuItem): number {
  if (sort === "price-asc") return Number(a.price) - Number(b.price);
  if (sort === "price-desc") return Number(b.price) - Number(a.price);
  if (sort === "rating") return Number(b.rating ?? 0) - Number(a.rating ?? 0);
  if (a.is_bestseller !== b.is_bestseller) return a.is_bestseller ? -1 : 1;
  return Number(b.rating ?? 0) - Number(a.rating ?? 0);
}

/**
 * Placeholder shaped like a DishCard — image, meta line, title, two lines of
 * description, price and button — so the swap to real content is a crossfade
 * rather than a jump from a tinted rectangle to a card twice its height.
 */
export function DishSkeleton() {
  return (
    <div className="skeleton-card" aria-hidden="true">
      <div className="skeleton skeleton-img" />
      <div className="skeleton-body">
        <div className="skeleton skeleton-line skeleton-line--meta" />
        <div className="skeleton skeleton-line skeleton-line--title" />
        <div className="skeleton skeleton-line" />
        <div className="skeleton skeleton-line skeleton-line--short" />
        <div className="skeleton-row">
          <div className="skeleton skeleton-price" />
          <div className="skeleton skeleton-btn" />
        </div>
      </div>
    </div>
  );
}

export function MenuGrid({ limit }: { limit?: number }) {
  const [category, setCategory] = useState("All");
  const [query, setQuery] = useState("");
  const [vegOnly, setVegOnly] = useState(false);
  const [sort, setSort] = useState<Sort>("recommended");

  const { restaurantId, branchId, isRestaurantLoading, isRestaurantError } = useBangkokStore();
  const menuQuery = useMenuItems(restaurantId, branchId || undefined);
  // `?? []` alone builds a fresh array on every render, so both memos below
  // would recompute every time and the memoisation would buy nothing.
  const items = useMemo(() => menuQuery.data ?? [], [menuQuery.data]);
  const categories = useMemo(() => deriveCategories(items), [items]);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items
      .filter((item) => category === "All" || item.category === category)
      .filter((item) => !vegOnly || item.is_veg)
      .filter(
        (item) =>
          !needle ||
          // Searching only the name missed "something with peanuts", which is
          // the kind of thing people actually type into a food search.
          item.name.toLowerCase().includes(needle) ||
          item.description.toLowerCase().includes(needle) ||
          item.category.toLowerCase().includes(needle),
      )
      .sort((a, b) => compare(sort, a, b))
      .slice(0, limit);
  }, [items, category, query, vegOnly, sort, limit]);

  const loading = isRestaurantLoading || menuQuery.isLoading;
  // A request that never happened is not an empty menu. When /app-config fails
  // the menu query is disabled, so it reports neither loading nor error and the
  // screen used to say "Nothing matches that" — telling the customer something
  // false about the restaurant instead of that we could not reach it.
  const failed = isRestaurantError || menuQuery.isError;
  const filtered = category !== "All" || vegOnly || query.trim().length > 0;

  function reset() {
    setCategory("All");
    setVegOnly(false);
    setQuery("");
  }

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search a dish, an ingredient, a category…"
            className="h-12 bg-surface pl-10"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-full text-muted transition-colors hover:bg-surface-alt hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => setVegOnly((v) => !v)}
            aria-pressed={vegOnly}
            className="filter-toggle"
            data-on={vegOnly}
          >
            <Leaf className="size-4" />
            Veg only
          </button>
          {/* A styled listbox rather than a bare <select>.
              The native control opens the operating system's own menu, which on
              Windows is a grey list in a different typeface, different radius
              and different colours to everything around it — the one place the
              app stopped looking like itself. Radix renders the list in the
              page, so it inherits the design, and it keeps the keyboard and
              screen-reader behaviour a hand-rolled menu would lose. */}
          <Select value={sort} onValueChange={(value) => setSort(value as Sort)}>
            <SelectTrigger className="sort-select" aria-label="Sort dishes">
              <SlidersHorizontal className="size-4 shrink-0 text-muted" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
              {SORTS.map((s) => (
                <SelectItem value={s.value} key={s.value}>
                  {s.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="category-rail mt-4 flex gap-2 overflow-x-auto pb-2">
        {categories.map((c) => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={c === category ? "category-pill active" : "category-pill"}
          >
            {c}
          </button>
        ))}
      </div>

      {!loading && !failed && (
        <div className="mb-5 mt-3 flex flex-wrap items-center gap-3">
          <p className="result-count text-sm font-semibold text-muted" key={shown.length}>
            {shown.length} {shown.length === 1 ? "dish" : "dishes"}
            {category !== "All" && ` in ${category}`}
          </p>
          {filtered && (
            <button type="button" onClick={reset} className="clear-filters text-sm">
              Clear filters
            </button>
          )}
        </div>
      )}

      {loading && (
        <div className="menu-grid mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {Array.from({ length: limit ?? 8 }).map((_, i) => (
            <DishSkeleton key={i} />
          ))}
        </div>
      )}

      {!loading && failed && (
        <div className="state-panel elevated-panel px-6 py-16 text-center">
          <h3 className="font-display text-xl font-extrabold">The menu didn't load</h3>
          <p className="mx-auto mt-2 max-w-sm text-muted">
            We couldn't load the menu right now. Please try again shortly.
          </p>
        </div>
      )}

      {!loading && !failed && shown.length > 0 && (
        <div className="menu-grid grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {shown.map((item, i) => (
            <div
              className="rise-in"
              style={{ "--i": Math.min(i, 11) } as React.CSSProperties}
              key={item.id}
            >
              <DishCard item={item} />
            </div>
          ))}
        </div>
      )}

      {!loading && !failed && shown.length === 0 && (
        <div className="state-panel elevated-panel px-6 py-20 text-center">
          <h3 className="font-display text-2xl font-extrabold">Nothing matches that</h3>
          <p className="mx-auto mt-2 max-w-sm text-muted">
            Try a different word, or clear the filters to see the whole menu.
          </p>
          {filtered && (
            <button type="button" onClick={reset} className="clear-filters mt-5">
              Clear filters
            </button>
          )}
        </div>
      )}
    </div>
  );
}
