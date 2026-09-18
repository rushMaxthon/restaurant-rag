import { useMemo, useState } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  Heart,
  Minus,
  Plus,
  ShoppingBag,
  Star,
  Store,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { DishImage } from "@/components/bangkok/dish-image";
import { VegMark } from "@/components/bangkok/veg-mark";
import { DishCard } from "@/components/bangkok/dish-card";
import { formatMoney } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import type { OptionPortion } from "@/lib/bangkok-store";
import { useAuth } from "@/lib/auth";
import { useFavoriteIds, useToggleFavorite } from "@/lib/queries";
import type { CustomizationGroup } from "@/lib/bangkok-data";
import {
  activeOptions,
  canPickMore,
  nextSideFor,
  regroupForMode,
  roomOnSide,
  selectionHint,
  sideCounts,
  activeSizes,
  requiresChoosing,
  splitSummary,
  selectionProblem,
  unitPriceFor,
  visibleGroups,
} from "@/lib/customization";
import { useMenuItem, useMenuItems, useRestaurant } from "@/lib/queries";
import { pageMeta } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

export const Route = createFileRoute("/menu/$itemId")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Dish", "Explore a dish from the menu."),
  }),
  component: DishPage,
});

function DishPage() {
  const { itemId } = Route.useParams();
  const store = useBangkokStore();
  const itemQuery = useMenuItem(itemId);
  const item = itemQuery.data;
  const { isAuthenticated } = useAuth();
  const favorites = useFavoriteIds(isAuthenticated);
  const toggleFavorite = useToggleFavorite();
  const isFavorite = Boolean(item && favorites.data?.has(item.id));

  const [size, setSize] = useState<string>("");
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  // Which half each chosen topping goes on, keyed by option id. Only groups the
  // owner marked splittable ever put anything here.
  const [portions, setPortions] = useState<Record<string, OptionPortion>>({});
  // Groups the customer has folded away. Everything starts open — nothing is
  // hidden from someone who has not asked for it - but a pizza with a sauce,
  // seven toppings and a crust is a long scroll, and folding what is already
  // answered brings the Add button back into reach.
  const [folded, setFolded] = useState<Record<string, boolean>>({});
  // Which splittable groups the customer has chosen to split. A group is one
  // thing or the other — the whole item, or two halves — and this is where
  // that is decided, once, rather than inferred from each topping's portion.
  const [split, setSplit] = useState<Record<string, boolean>>({});
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

  // Sizes and options the owner switched off are not offered, and a group that
  // belongs to another size is not shown. All of it mirrors the server; see
  // lib/customization.ts for what went wrong when it did not.
  const sizes = activeSizes(item);
  const chosenSize = sizes.find((s) => s.id === (size || sizes[0]?.id));
  const groups = visibleGroups(item, chosenSize);
  const chosenOptionIds = groups.flatMap((g) => selected[g.id] ?? []);
  const unitPrice = unitPriceFor(item, chosenSize, chosenOptionIds, portions);
  const halves = splitSummary(item, chosenSize, chosenOptionIds, portions);
  const total = unitPrice * quantity;
  const problem = selectionProblem(item, chosenSize, selected, portions);
  const valid = problem === null;
  // The options the customer can actually see and has actually chosen. Derived
  // from the same visible set as the price, so what is charged, what is shown
  // and what is stored on the line can never drift apart.
  const addons = groups
    .flatMap((g) => activeOptions(g))
    .filter((o) => chosenOptionIds.includes(o.id));

  const conflicts = item ? store.conflictsWithCart(item) : false;

  function toggle(group: CustomizationGroup, oid: string, single: boolean, groupIsSplit = false) {
    const gid = group.id;
    const current = selected[gid] ?? [];

    // Set alongside the other updater rather than inside it: a state setter
    // called from within an updater runs again every time React replays that
    // updater, and React replays them.
    if (!current.includes(oid) && !single) {
      // Decided from what is already in the group, before this one joins it.
      setPortions((p) => ({
        ...p,
        [oid]: groupIsSplit ? nextSideFor(group, current, p) : "WHOLE",
      }));
    }
    setSelected((s) => {
      const latest = s[gid] ?? [];
      return {
        ...s,
        [gid]: single
          ? [oid]
          : latest.includes(oid)
            ? latest.filter((v) => v !== oid)
            : [...latest, oid],
      };
    });
  }

  /**
   * Switch a group between "all over it" and "split across halves".
   *
   * The choices are re-rationed for the mode being entered rather than carried
   * across unchanged: two toppings picked for opposite halves are not two
   * toppings on the whole pizza, and treating them as such put a group over
   * its own limit the moment the customer switched back.
   */
  function setGroupSplit(group: CustomizationGroup, wantSplit: boolean, optionIds: string[]) {
    const next = regroupForMode(group, optionIds, wantSplit);
    setSplit((current) => ({ ...current, [group.id]: wantSplit }));
    setSelected((current) => ({ ...current, [group.id]: next.chosen }));
    setPortions((current) => ({ ...current, ...next.portions }));
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
      optionPortions: portions,
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
      <div className="page-pad mx-auto max-w-7xl py-10" aria-busy="true">
        <div className="grid gap-8 grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,1fr)_440px]">
          <div className="skeleton aspect-[16/10] !rounded-2xl" />
          <div className="elevated-panel skeleton-panel p-5 sm:p-6">
            <div className="skeleton skeleton-line skeleton-line--meta" />
            <div className="skeleton h-9 w-4/5" />
            <div className="skeleton skeleton-line" />
            <div className="skeleton skeleton-line skeleton-line--short" />
            <div className="skeleton mt-4 h-12" />
            <div className="skeleton h-12" />
            <div className="skeleton mt-4 h-12" />
          </div>
        </div>
      </div>
    );
  }

  if (itemQuery.isError || !item) {
    return (
      <div className="state-panel page-pad mx-auto max-w-xl py-24 text-center">
        <h1 className="font-display text-3xl font-extrabold">We couldn't find that dish</h1>
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
        <Link to="/menu" className="back-link">
          <ChevronLeft className="size-4" /> Back to menu
        </Link>

        <div className="mt-5 grid items-start gap-8 grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,1fr)_440px]">
          {/* The picture and what the dish IS travel together, and stay put
              while the choices scroll beside them. Before this the left column
              held only the image while the right one ran to three screens, so
              anyone past the first group was choosing toppings alongside a
              screen and a half of empty background. */}
          <div className="dish-lede lg:sticky lg:top-24">
            <div className="dish-hero relative overflow-hidden rounded-2xl">
              {/* The same gesture in the same place as on the menu card, so it
                  is one thing to learn wherever you meet the dish. */}
              {isAuthenticated && (
                <button
                  type="button"
                  className="heart"
                  data-on={isFavorite}
                  aria-pressed={isFavorite}
                  aria-label={
                    isFavorite ? `Remove ${item.name} from your usuals` : `Save ${item.name}`
                  }
                  onClick={() => toggleFavorite.mutate({ menuItemId: item.id, next: !isFavorite })}
                >
                  <Heart className="size-4" fill={isFavorite ? "currentColor" : "none"} />
                </button>
              )}
              <DishImage
                src={item.image_url}
                name={item.name}
                className="aspect-[16/10]"
                priority
              />
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
                  <span className="rounded-full bg-surface px-4 py-2 font-extrabold uppercase tracking-wide">
                    Unavailable
                  </span>
                </div>
              )}
            </div>

            <div className="dish-lede__body">
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

              <h1 className="mt-3 font-display text-4xl font-extrabold leading-[1.05]">{item.name}</h1>

              {(dishRestaurant.data?.name || item.cuisine_type) && (
                <p className="mt-2 flex items-center gap-1.5 text-sm font-semibold text-muted">
                  <Store className="size-3.5 shrink-0 text-primary" />
                  {dishRestaurant.data?.name ?? item.cuisine_type}
                  {dishRestaurant.data?.name && item.cuisine_type && (
                    <span className="font-medium">· {item.cuisine_type}</span>
                  )}
                </p>
              )}

              <p className="mt-3 leading-relaxed text-muted">{item.description}</p>

              {/* "From $12" until a size is picked, because that is the only
                  honest single number then. Once one IS picked the guess is
                  replaced by what that size actually costs — leaving "From"
                  up there asks the customer to keep discounting the headline. */}
              {sizes.length > 0 && (
                <div className="dish-lede__price">
                  <p className="money font-display text-3xl font-extrabold">
                    {chosenSize ? (
                      formatMoney(chosenSize.price)
                    ) : (
                      <>
                        From{" "}
                        {formatMoney(
                          sizes.reduce(
                            (low, s) => (Number(s.price) < Number(low.price) ? s : low),
                            sizes[0]!,
                          ).price,
                        )}
                      </>
                    )}
                  </p>
                  <p className="text-sm text-muted">
                    {chosenSize
                      ? `${chosenSize.name} · extras are charged on top`
                      : "Final price depends on the size you pick"}
                  </p>
                </div>
              )}
            </div>
          </div>

          <aside className="elevated-panel dish-choices">
            {sizes.length > 0 && (
              <section className="choice-card mt-6">
                <header className="choice-card__head">
                  <h2 className="choice-card__title">
                    Choose a size
                    <span className="choice-badge choice-badge--required">Required</span>
                  </h2>
                  <p className="choice-card__hint">Base price varies with size</p>
                </header>
                {/* Tiles, not a list. A size is the price of the pizza rather
                    than an addition to it, so the three sit side by side to be
                    compared — which is also how the mobile app shows them. */}
                <div className="size-tiles">
                  {sizes.map((s) => {
                    const active = chosenSize?.id === s.id;
                    return (
                      <button
                        type="button"
                        className="size-tile"
                        data-on={active}
                        onClick={() => setSize(s.id)}
                        key={s.id}
                      >
                        <span className="size-tile__name">{s.name}</span>
                        {/* The absolute price, not "+". A size REPLACES the
                            base price, so a plus sign said the opposite of what
                            the customer would be charged. */}
                        <span className="money size-tile__price">{formatMoney(s.price)}</span>
                      </button>
                    );
                  })}
                </div>
              </section>
            )}

            {groups.map((g) => {
              const chosenHere = activeOptions(g).filter((o) =>
                (selected[g.id] ?? []).includes(o.id),
              );
              const isFolded = Boolean(folded[g.id]);
              const chosenIds = selected[g.id] ?? [];
              const canSplit = g.supports_halves && g.selection_type === "MULTI";
              const isSplit = canSplit && Boolean(split[g.id]);
              // The owner's maximum counts on each half once the item is
              // split, so what is already on each side decides what can still
              // go on it.
              const counts = sideCounts(chosenIds, portions);
              return (
                <section className="choice-card mt-6" key={g.id} data-folded={isFolded}>
                  <button
                    type="button"
                    className="choice-card__head choice-card__toggle"
                    aria-expanded={!isFolded}
                    onClick={() => setFolded((f) => ({ ...f, [g.id]: !f[g.id] }))}
                  >
                    <h2 className="choice-card__title">
                      {g.title}
                      {/* Labelled from the same rule the server enforces: a group
                        marked "not required" with a minimum of one IS required,
                        and showing it as optional only defers the surprise. */}
                      {requiresChoosing(g) ? (
                        <span className="choice-badge choice-badge--required">Required</span>
                      ) : (
                        <span className="choice-badge">Optional</span>
                      )}
                      <ChevronDown className="choice-card__chevron size-4" />
                    </h2>
                    {/* What kind of choice this is, said once at the top rather
                      than left for the customer to infer from how the controls
                      behave when they tap a second one. */}
                    {/* Folded, the card says what was chosen rather than what
                        kind of choice it was — the question is answered, and the
                        answer is the useful thing to show. */}
                    <p className="choice-card__hint">
                      {isFolded && chosenHere.length > 0
                        ? chosenHere.map((o) => o.name).join(", ")
                        : isSplit
                          ? `${selectionHint(g)} on each half · ${counts.LEFT} left, ${counts.RIGHT} right`
                          : `${selectionHint(g)}${
                              chosenHere.length > 0 ? ` · ${chosenHere.length} chosen` : ""
                            }`}
                    </p>
                  </button>

                  {/* The owner's flag turned into one question, asked once:
                      the same on all of it, or different on each half. Asking
                      it per topping produced dead ends - two toppings on the
                      whole item and neither could move to a half, because each
                      read the other as whole. */}
                  {canSplit && !isFolded && (
                    <div
                      className="split-switch"
                      role="group"
                      aria-label={`How to put on ${g.title}`}
                    >
                      <button
                        type="button"
                        className="split-switch__option"
                        data-on={!isSplit}
                        onClick={() => setGroupSplit(g, false, chosenIds)}
                      >
                        <span className="portion-glyph portion-glyph--whole" aria-hidden="true" />
                        Same all over
                      </button>
                      <button
                        type="button"
                        className="split-switch__option"
                        data-on={isSplit}
                        onClick={() => setGroupSplit(g, true, chosenIds)}
                      >
                        <span className="portion-glyph portion-glyph--left" aria-hidden="true" />
                        Half &amp; half
                      </button>
                    </div>
                  )}

                  {!isFolded && (
                    <div className="option-grid">
                      {activeOptions(g).map((o) => {
                        const active = Boolean(selected[g.id]?.includes(o.id));
                        const portion = portions[o.id] ?? "WHOLE";
                        const half = isSplit && portion !== "WHOLE";
                        // At the ceiling, the ones already chosen stay tappable
                        // so they can be taken off again; the rest go quiet.
                        // The cap used to be checked only at the Add button,
                        // which let someone build a seven-topping pizza and
                        // told them it was too many at the end.
                        // The side the toggle would actually put it on, so
                        // the button and the click cannot disagree.
                        const landsOn = isSplit ? nextSideFor(g, chosenIds, portions) : "WHOLE";
                        const atCeiling =
                          !active &&
                          (isSplit
                            ? !roomOnSide(g, counts, landsOn)
                            : !canPickMore(g, chosenHere.length));
                        return (
                          <div key={o.id}>
                            <button
                              type="button"
                              disabled={atCeiling}
                              title={
                                atCeiling
                                  ? isSplit
                                    ? `Each half takes up to ${g.max_selection} from "${g.title}".`
                                    : `You can choose up to ${g.max_selection} from "${g.title}".`
                                  : undefined
                              }
                              onClick={() =>
                                toggle(g, o.id, g.selection_type === "SINGLE", isSplit)
                              }
                              className="option-row w-full"
                              data-on={active}
                            >
                              <span className="flex items-center gap-2 font-semibold">
                                <span className="option-dot" data-on={active}>
                                  {active && <Check className="size-3" strokeWidth={3} />}
                                </span>
                                {o.name}
                              </span>
                              <span className="money text-sm font-bold">
                                {/* Half the topping, half the price — shown here so
                                the number moves when the customer splits it,
                                rather than only in the total. */}
                                {Number(o.extra_price) > 0
                                  ? `+${formatMoney(half ? Number(o.extra_price) / 2 : o.extra_price)}`
                                  : "Free"}
                              </span>
                            </button>

                            {/* Which half, once the group is being split.
                            "Whole" is not offered here: that is the other
                            answer to the question asked above, not a third
                            option beside the two halves. */}
                            {active && isSplit && (
                              <div
                                className="portion-picker"
                                role="group"
                                aria-label={`Which half for ${o.name}`}
                              >
                                {(["LEFT", "RIGHT"] as OptionPortion[]).map((value) => {
                                  // Room on the side it would move TO, not
                                  // counting where it sits now.
                                  const full = portion !== value && !roomOnSide(g, counts, value);
                                  return (
                                    <button
                                      type="button"
                                      key={value}
                                      className="portion-option"
                                      data-on={portion === value}
                                      disabled={full}
                                      title={
                                        full
                                          ? `That half already has ${g.max_selection} from "${g.title}".`
                                          : undefined
                                      }
                                      onClick={() =>
                                        setPortions((current) => ({ ...current, [o.id]: value }))
                                      }
                                    >
                                      <span
                                        className={`portion-glyph portion-glyph--${value.toLowerCase()}`}
                                        aria-hidden="true"
                                      />
                                      {value === "LEFT" ? "Left" : "Right"}
                                    </button>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </section>
              );
            })}

            {/* The pizza read back, so it can be checked before paying
                rather than discovered at the door. */}
            {(halves.left.length > 0 || halves.right.length > 0) && (
              <div className="half-summary mt-6">
                {/* The item's own name, not "Your pizza": a splittable group is a
                    flag on a group, and nothing says the item is a pizza. */}
                <p className="half-summary__title">How it is split</p>
                <div className="half-summary__rows">
                  <p>
                    <span className="portion-glyph portion-glyph--left" aria-hidden="true" />
                    <b>Left half</b>
                    <span>{halves.left.length ? halves.left.join(", ") : "Nothing extra"}</span>
                  </p>
                  <p>
                    <span className="portion-glyph portion-glyph--right" aria-hidden="true" />
                    <b>Right half</b>
                    <span>{halves.right.length ? halves.right.join(", ") : "Nothing extra"}</span>
                  </p>
                  {halves.whole.length > 0 && (
                    <p>
                      <span className="portion-glyph portion-glyph--whole" aria-hidden="true" />
                      <b>Whole</b>
                      <span>{halves.whole.join(", ")}</span>
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Quantity, total and Add stay on screen while the choices
                scroll under them. A dish with a size, a glaze and four topping
                groups is taller than any phone and taller than most desktops,
                and the button that ends the task sat below all of it. */}
            <div className="dish-actions">
              <div className="flex items-center justify-between gap-4">
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
                  <p className="money total-figure font-display text-3xl font-extrabold leading-tight">
                    {formatMoney(total)}
                  </p>
                </div>
              </div>

              {/* Cart scope is restaurant + location, so a dish from another
                kitchen cannot join this order. Offering to start a fresh cart
                beats refusing the dish, which is what made a concierge
                suggestion feel like a dead end. */}
              {conflicts ? (
                <div className="added-note mt-5 rounded-xl border border-border bg-surface-alt p-4">
                  <p className="text-sm font-semibold leading-relaxed">
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
                <div className="added-note mt-5 grid gap-2">
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
                <>
                  <Button
                    className="mt-5 h-12 w-full text-base"
                    disabled={!valid || !item.is_available}
                    onClick={() => handleAdd(false)}
                  >
                    {item.is_available
                      ? `Add to cart · ${formatMoney(total)}`
                      : "Currently unavailable"}
                  </Button>
                  {/* Say what is missing. A greyed-out button with no reason is
                    the dead end this app keeps producing; the customer has to
                    hunt the page for whichever group is unanswered. */}
                  {item.is_available && problem && (
                    <p className="mt-2 text-center text-sm font-semibold text-muted">{problem}</p>
                  )}
                </>
              )}
            </div>
          </aside>
        </div>
      </div>

      {related.length > 0 && (
        <section className="page-pad section-pad mx-auto max-w-7xl">
          <h2 className="mb-6 font-display text-3xl font-extrabold">Goes well with this</h2>
          <div className="menu-grid grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {related.map((dish, i) => (
              <div className="rise-in" style={{ "--i": i } as React.CSSProperties} key={dish.id}>
                <DishCard item={dish} />
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
