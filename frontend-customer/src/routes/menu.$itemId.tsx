import { useMemo, useState } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import { Check, ChevronLeft, Minus, Plus, ShoppingBag, Star, Store } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DishImage } from "@/components/bangkok/dish-image";
import { VegMark } from "@/components/bangkok/veg-mark";
import { DishCard } from "@/components/bangkok/dish-card";
import { formatMoney } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useMenuItem, useMenuItems, useRestaurant } from "@/lib/queries";

export const Route = createFileRoute("/menu/$itemId")({
  head: () => ({
    meta: [
      { title: "Dish — Bangkok Bowl" },
      { name: "description", content: "Explore a Bangkok Bowl Thai dish." },
      { property: "og:title", content: "Dish — Bangkok Bowl" },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: DishPage,
});

function DishPage() {
  const { itemId } = Route.useParams();
  const store = useBangkokStore();
  const itemQuery = useMenuItem(itemId);
  const item = itemQuery.data;

  const [size, setSize] = useState<string>("");
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [quantity, setQuantity] = useState(1);
  const [added, setAdded] = useState(false);

  // Related dishes come from THIS dish's restaurant, not whichever one the app
  // is currently showing. A concierge suggestion can belong to another kitchen,
  // and pairing a Luigi's pasta with Bangkok Bowl sides was nonsense.
  const relatedQuery = useMenuItems(item?.restaurant_id, item?.restaurant_location_id);
  // Named so the cart can say "items from Luigi's Italian Trattoria" rather
  // than the vague "another restaurant" when the kitchens clash.
  const dishRestaurant = useRestaurant(item?.restaurant_id);
  const related = useMemo(
    () => (relatedQuery.data ?? []).filter((i) => i.id !== itemId).slice(0, 4),
    [relatedQuery.data, itemId],
  );

  const chosenSize = item?.sizes.find((s) => s.id === (size || item.sizes[0]?.id));
  const addons =
    item?.customization_groups.flatMap((g) =>
      g.options.filter((o) => selected[g.id]?.includes(o.id)),
    ) ?? [];
  const unitPrice = item
    ? Number(item.price) +
      Number(chosenSize?.price ?? 0) +
      addons.reduce((n, o) => n + Number(o.extra_price), 0)
    : 0;
  const total = unitPrice * quantity;
  const valid = item
    ? item.customization_groups.every(
        (g) => !g.is_required || (selected[g.id]?.length ?? 0) >= g.min_selection,
      )
    : false;

  const conflicts = item ? store.conflictsWithCart(item) : false;

  function toggle(gid: string, oid: string, single: boolean) {
    setSelected((s) => ({
      ...s,
      [gid]: single
        ? [oid]
        : s[gid]?.includes(oid)
          ? s[gid]?.filter((v) => v !== oid)
          : [...(s[gid] ?? []), oid],
    }));
  }

  function handleAdd(replace = false) {
    if (!item) return;
    const options = {
      unitPrice,
      restaurantName: dishRestaurant.data?.name,
      sizeId: chosenSize?.id,
      sizeName: chosenSize?.name,
      optionIds: addons.map((a) => a.id),
      addOnNames: addons.map((a) => a.name),
    };
    if (replace) store.replaceCartWith(item, options);
    else store.addItem(item, options);
    // The store keys lines by their option signature and increments on repeat,
    // so quantity is applied by adding the same configuration again.
    for (let i = 1; i < quantity; i += 1) store.addItem(item, options);
    setAdded(true);
  }

  if (itemQuery.isLoading) {
    return (
      <div className="page-pad mx-auto max-w-7xl py-10">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_420px]">
          <div className="dish-placeholder placeholder-a aspect-[16/10] animate-pulse rounded-2xl" />
          <div className="dish-placeholder placeholder-b h-64 animate-pulse rounded-2xl" />
        </div>
      </div>
    );
  }

  if (itemQuery.isError || !item) {
    return (
      <div className="page-pad mx-auto max-w-xl py-24 text-center">
        <h1 className="font-display text-3xl font-black">We couldn't find that dish</h1>
        <p className="mt-3 text-muted">It may have been taken off the menu.</p>
        <Button className="mt-7 h-12 px-6" asChild>
          <Link to="/menu">Back to menu</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="pb-24">
      <div className="page-pad mx-auto max-w-7xl pt-6">
        <Link
          to="/menu"
          className="inline-flex items-center gap-1.5 text-sm font-bold text-muted hover:text-foreground"
        >
          <ChevronLeft className="size-4" /> Back to menu
        </Link>

        <div className="mt-5 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_420px]">
          <div className="relative overflow-hidden rounded-2xl">
            <DishImage src={item.image_url} name={item.name} className="aspect-[16/10]" priority />
            {(item.is_bestseller || item.is_new) && (
              <div className="absolute left-3 top-3 flex gap-1.5">
                {item.is_bestseller && (
                  <span className="dish-badge dish-badge--hot">Bestseller</span>
                )}
                {item.is_new && <span className="dish-badge dish-badge--new">New</span>}
              </div>
            )}
            {!item.is_available && (
              <div className="absolute inset-0 grid place-items-center bg-overlay">
                <span className="rounded-full bg-surface px-4 py-2 font-black uppercase tracking-wide">
                  Unavailable
                </span>
              </div>
            )}
          </div>

          <aside className="elevated-panel p-5 sm:p-6 lg:sticky lg:top-24">
            <div className="flex flex-wrap items-center gap-3">
              <VegMark veg={item.is_veg} />
              {item.rating && (
                <span className="flex items-center gap-1 font-semibold">
                  <Star className="size-4 fill-primary text-primary" />
                  {item.rating}
                  {item.rating_count > 0 && (
                    <span className="text-sm text-muted">({item.rating_count})</span>
                  )}
                </span>
              )}
              <span className="rounded-full bg-surface-alt px-2.5 py-0.5 text-xs font-bold text-muted">
                {item.category}
              </span>
            </div>

            <h1 className="mt-3 font-display text-4xl font-black leading-[1.05]">{item.name}</h1>

            {(dishRestaurant.data?.name || item.cuisine_type) && (
              <p className="mt-2 flex items-center gap-1.5 text-sm font-semibold text-muted">
                <Store className="size-3.5 shrink-0 text-primary" />
                {dishRestaurant.data?.name ?? item.cuisine_type}
                {dishRestaurant.data?.name && item.cuisine_type && (
                  <span className="font-medium">· {item.cuisine_type}</span>
                )}
              </p>
            )}

            <p className="mt-4 text-muted">{item.description}</p>

            {item.has_sizes && (
              <div className="mt-6">
                <h2 className="text-sm font-black uppercase tracking-wide text-muted">
                  Choose a size
                </h2>
                <div className="mt-3 grid gap-2">
                  {item.sizes.map((s) => {
                    const active = (size || item.sizes[0]?.id) === s.id;
                    return (
                      <button
                        type="button"
                        className="option-row"
                        data-on={active}
                        onClick={() => setSize(s.id)}
                        key={s.id}
                      >
                        <span className="flex items-center gap-2 font-semibold">
                          <span className="option-dot" data-on={active} />
                          {s.name}
                        </span>
                        <span className="money text-sm font-bold">+{formatMoney(s.price)}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {item.customization_groups.map((g) => (
              <div className="mt-6" key={g.id}>
                <h2 className="flex items-center gap-2 text-sm font-black uppercase tracking-wide text-muted">
                  {g.title}
                  {g.is_required && (
                    <span className="rounded-full bg-primary-soft px-2 py-0.5 text-[0.6rem] text-primary">
                      Required
                    </span>
                  )}
                </h2>
                <div className="mt-3 grid gap-2">
                  {g.options.map((o) => {
                    const active = Boolean(selected[g.id]?.includes(o.id));
                    return (
                      <button
                        type="button"
                        onClick={() => toggle(g.id, o.id, g.selection_type === "SINGLE")}
                        className="option-row"
                        data-on={active}
                        key={o.id}
                      >
                        <span className="flex items-center gap-2 font-semibold">
                          <span className="option-dot" data-on={active}>
                            {active && <Check className="size-3" strokeWidth={3} />}
                          </span>
                          {o.name}
                        </span>
                        <span className="money text-sm font-bold">
                          +{formatMoney(o.extra_price)}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}

            <div className="mt-7 flex items-center justify-between gap-4 border-t border-border pt-5">
              <div className="qty-pill">
                <button
                  type="button"
                  className="qty-step"
                  aria-label="Reduce quantity"
                  disabled={quantity <= 1}
                  onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                >
                  <Minus className="size-4" />
                </button>
                <span className="qty-value">{quantity}</span>
                <button
                  type="button"
                  className="qty-step"
                  aria-label="Increase quantity"
                  onClick={() => setQuantity((q) => q + 1)}
                >
                  <Plus className="size-4" />
                </button>
              </div>
              <div className="text-right">
                <p className="text-xs font-bold uppercase tracking-wide text-muted">Total</p>
                <p className="money font-display text-3xl font-black leading-tight">
                  {formatMoney(total)}
                </p>
              </div>
            </div>

            {/* Cart scope is restaurant + location, so a dish from another
                kitchen cannot join this order. Offering to start a fresh cart
                beats refusing the dish, which is what made a concierge
                suggestion feel like a dead end. */}
            {conflicts ? (
              <div className="mt-5 rounded-xl border border-border bg-surface-alt p-4">
                <p className="text-sm font-semibold">
                  Your cart already has items from{" "}
                  {store.cartRestaurantName ?? "another restaurant"}. One order can only come from
                  one kitchen.
                </p>
                <Button
                  className="mt-3 h-12 w-full"
                  disabled={!valid || !item.is_available}
                  onClick={() => handleAdd(true)}
                >
                  Start a new cart with this
                </Button>
              </div>
            ) : added ? (
              <div className="mt-5 grid gap-2">
                <p className="flex items-center justify-center gap-2 text-sm font-bold text-success">
                  <Check className="size-4" strokeWidth={3} /> Added to your cart
                </p>
                <Button className="h-12 w-full" asChild>
                  <Link to="/cart">
                    <ShoppingBag className="size-4" /> Go to cart
                  </Link>
                </Button>
                <Button variant="outline" className="h-12 w-full" onClick={() => setAdded(false)}>
                  Add another
                </Button>
              </div>
            ) : (
              <Button
                className="mt-5 h-12 w-full text-base"
                disabled={!valid || !item.is_available}
                onClick={() => handleAdd(false)}
              >
                {item.is_available
                  ? `Add to cart · ${formatMoney(total)}`
                  : "Currently unavailable"}
              </Button>
            )}
          </aside>
        </div>
      </div>

      {related.length > 0 && (
        <section className="page-pad section-pad mx-auto max-w-7xl">
          <h2 className="mb-6 font-display text-3xl font-black">Goes well with this</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {related.map((i) => (
              <DishCard item={i} key={i.id} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
