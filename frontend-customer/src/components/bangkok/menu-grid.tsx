import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { deriveCategories } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useMenuItems } from "@/lib/queries";
import { DishCard } from "./dish-card";

export function MenuGrid({ limit }: { limit?: number }) {
  const [category, setCategory] = useState("All");
  const [query, setQuery] = useState("");
  const { restaurantId, branchId, isRestaurantLoading } = useBangkokStore();
  const menuQuery = useMenuItems(restaurantId, branchId || undefined);
  const items = menuQuery.data ?? [];
  const categories = useMemo(() => deriveCategories(items), [items]);
  const shown = useMemo(
    () => items.filter((item) => (category === "All" || item.category === category) && item.name.toLowerCase().includes(query.toLowerCase())).slice(0, limit),
    [items, category, query, limit],
  );

  const loading = isRestaurantLoading || menuQuery.isLoading;

  return (
    <div>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search Pad Thai, curry, tea…" className="h-12 bg-surface pl-10" />
        </div>
      </div>
      <div className="category-rail mb-6 flex gap-2 overflow-x-auto pb-2">
        {categories.map((c) => (
          <button key={c} onClick={() => setCategory(c)} className={c === category ? "category-pill active" : "category-pill"}>
            {c}
          </button>
        ))}
      </div>
      {loading && (
        <div className="menu-grid grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {Array.from({ length: limit ?? 8 }).map((_, i) => (
            <div key={i} className="dish-placeholder placeholder-a aspect-[4/3] animate-pulse rounded-lg" />
          ))}
        </div>
      )}
      {!loading && menuQuery.isError && <p className="py-16 text-center text-muted">We couldn't load the menu right now. Please try again shortly.</p>}
      {!loading && !menuQuery.isError && (
        <div className="menu-grid grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {shown.map((item) => (
            <DishCard key={item.id} item={item} />
          ))}
        </div>
      )}
      {!loading && !menuQuery.isError && shown.length === 0 && <p className="py-16 text-center text-muted">No dishes match your search.</p>}
    </div>
  );
}
