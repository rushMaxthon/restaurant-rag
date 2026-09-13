import { useMemo, useState } from "react";
import { Link, createFileRoute, useNavigate, useRouterState } from "@tanstack/react-router";
import { Check, ChevronLeft, Clock3, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DishImage } from "@/components/bangkok/dish-image";
import { VegMark } from "@/components/bangkok/veg-mark";
import { DishCard } from "@/components/bangkok/dish-card";
import { formatMoney } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useMenuItem, useMenuItems } from "@/lib/queries";

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
  const { addItem, restaurantId, branchId } = useBangkokStore();
  const navigate = useNavigate();
  const itemQuery = useMenuItem(itemId);
  const relatedQuery = useMenuItems(restaurantId, branchId || undefined);
  const item = itemQuery.data;

  const [size, setSize] = useState<string>("");
  const [selected, setSelected] = useState<Record<string, string[]>>({});

  const chosenSize = item?.sizes.find((s) => s.id === (size || item.sizes[0]?.id));
  const addons = item?.customization_groups.flatMap((g) => g.options.filter((o) => selected[g.id]?.includes(o.id))) ?? [];
  const total = item ? Number(item.price) + Number(chosenSize?.price ?? 0) + addons.reduce((n, o) => n + Number(o.extra_price), 0) : 0;
  const valid = item ? item.customization_groups.every((g) => !g.is_required || (selected[g.id]?.length ?? 0) >= g.min_selection) : false;
  const related = useMemo(() => (relatedQuery.data ?? []).filter((i) => i.id !== itemId).slice(0, 3), [relatedQuery.data, itemId]);

  function toggle(gid: string, oid: string, single: boolean) {
    setSelected((s) => ({ ...s, [gid]: single ? [oid] : s[gid]?.includes(oid) ? s[gid]?.filter((v) => v !== oid) : [...(s[gid] ?? []), oid] }));
  }

  function handleAdd() {
    if (!item) return;
    addItem(item, {
      unitPrice: total,
      sizeId: chosenSize?.id,
      sizeName: chosenSize?.name,
      optionIds: addons.map((a) => a.id),
      addOnNames: addons.map((a) => a.name),
    });
  }

  if (itemQuery.isLoading) {
    return <div className="page-pad py-24 text-center text-muted">Loading dish…</div>;
  }
  if (itemQuery.isError || !item) {
    return (
      <div className="page-pad py-24 text-center">
        <h1 className="font-display text-3xl font-black">We couldn't find that dish</h1>
        <Button className="mt-6" asChild>
          <Link to="/menu">Back to menu</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="pb-28">
      <div className="page-pad grid gap-8 py-8 lg:grid-cols-2">
        <div>
          <Button variant="ghost" asChild>
            <Link to="/menu">
              <ChevronLeft />
              Back to menu
            </Link>
          </Button>
          <DishImage src={item.image_url} name={item.name} className="mt-3 rounded-lg" priority />
        </div>
        <div className="lg:pt-16">
          <div className="flex items-center gap-3">
            <VegMark veg={item.is_veg} />
            {item.rating && (
              <span className="flex items-center gap-1">
                <Star className="size-4 fill-primary text-primary" />
                {item.rating} ({item.rating_count})
              </span>
            )}
            <span className="flex items-center gap-1 text-muted">
              <Clock3 className="size-4" />
              20 min
            </span>
          </div>
          <h1 className="mt-4 font-display text-4xl font-black sm:text-6xl">{item.name}</h1>
          <p className="mt-3 text-2xl font-bold">{item.has_sizes ? `From ${formatMoney(item.price)}` : formatMoney(item.price)}</p>
          <p className="mt-5 text-lg text-muted">{item.description}</p>
          {item.has_sizes && (
            <div className="mt-8">
              <h2 className="text-lg font-bold">Choose a size</h2>
              <div className="mt-3 grid gap-2">
                {item.sizes.map((s) => (
                  <button className={(size || item.sizes[0]?.id) === s.id ? "category-pill active flex justify-between" : "category-pill flex justify-between"} onClick={() => setSize(s.id)} key={s.id}>
                    <span>{s.name}</span>
                    <span>+{formatMoney(s.price)}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {item.customization_groups.map((g) => (
            <div className="mt-8" key={g.id}>
              <h2 className="text-lg font-bold">
                {g.title} {g.is_required && <span className="text-primary">Required</span>}
              </h2>
              <div className="mt-3 grid gap-2">
                {g.options.map((o) => {
                  const active = selected[g.id]?.includes(o.id);
                  return (
                    <button onClick={() => toggle(g.id, o.id, g.selection_type === "SINGLE")} className="flex min-h-12 items-center justify-between rounded-md border border-border px-4 text-left" key={o.id}>
                      <span className="flex items-center gap-2">
                        {active && <Check className="size-4 text-success" />}
                        {o.name}
                      </span>
                      <span>+{formatMoney(o.extra_price)}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
      {related.length > 0 && (
        <section className="page-pad section-pad bg-surface-alt">
          <h2 className="mb-6 font-display text-3xl font-black">Goes well with this</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {related.map((i) => (
              <DishCard item={i} key={i.id} />
            ))}
          </div>
        </section>
      )}
      <div className="fixed inset-x-0 bottom-[58px] z-30 border-t border-border bg-surface p-3 lg:bottom-0">
        <Button disabled={!valid || !item.is_available} className="mx-auto flex w-full max-w-2xl" onClick={handleAdd}>
          Add to cart · {formatMoney(total)}
        </Button>
      </div>
    </div>
  );
}
