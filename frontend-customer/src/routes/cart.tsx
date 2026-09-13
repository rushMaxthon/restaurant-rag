import { Link, createFileRoute } from "@tanstack/react-router";
import { Minus, Plus, ShoppingBag } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DishImage } from "@/components/bangkok/dish-image";
import { formatINR } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/cart")({
  head: () => ({
    meta: [
      { title: "Your Cart — Bangkok Bowl" },
      { name: "description", content: "Review your Bangkok Bowl order and continue to checkout." },
      { property: "og:title", content: "Your Cart — Bangkok Bowl" },
      { property: "og:description", content: "Review your Thai food order." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: CartPage,
});

function CartPage() {
  const s = useBangkokStore();
  // The cart itself is guest-visible; it lives in localStorage and belongs to
  // the browser, not the account. The account is only needed to place the order.
  const { isAuthenticated } = useAuth();

  const delivery = s.fulfillment === "DELIVERY" ? Number(s.currentLocation?.delivery_fee ?? 45) : 0;
  const tax = s.subtotal * 0.05;
  const total = s.subtotal + delivery + tax;
  return (
    <div className="page-pad mx-auto max-w-6xl pb-28 pt-10">
      <h1 className="font-display text-4xl font-black sm:text-6xl">Your cart</h1>
      {!s.cart.length ? (
        <div className="surface-panel mt-8 py-24 text-center">
          <ShoppingBag className="mx-auto size-14 text-primary" />
          <h2 className="mt-5 text-2xl font-bold">Your bowl is empty</h2>
          <p className="mt-2 text-muted">Add a curry, a bowl of noodles or a snack to get started.</p>
          <Button className="mt-6 h-12 px-6" asChild>
            <Link to="/menu">Browse the menu</Link>
          </Button>
        </div>
      ) : (
        <div className="mt-8 grid gap-7 lg:grid-cols-[1fr_380px]">
          <div className="space-y-3">
            {s.cart.map((line) => (
              <article className="surface-panel grid grid-cols-[100px_1fr] gap-4 p-3 sm:grid-cols-[130px_1fr]" key={line.lineId}>
                <DishImage src={line.image_url} name={line.name} className="rounded-md" />
                <div>
                  <div className="flex justify-between gap-3">
                    <div>
                      <h2 className="font-bold">{line.name}</h2>
                      {line.sizeName && <p className="text-sm text-muted">{line.sizeName}</p>}
                      <p className="text-sm text-muted">{line.addOnNames.join(", ")}</p>
                    </div>
                    <b>{formatINR(line.unitPrice * line.quantity)}</b>
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <Button variant="outline" size="icon-sm" aria-label={`Reduce ${line.name}`} onClick={() => s.changeQuantity(line.lineId, -1)}>
                      <Minus />
                    </Button>
                    <span className="w-7 text-center font-bold">{line.quantity}</span>
                    <Button variant="outline" size="icon-sm" aria-label={`Add another ${line.name}`} onClick={() => s.changeQuantity(line.lineId, 1)}>
                      <Plus />
                    </Button>
                  </div>
                </div>
              </article>
            ))}
          </div>
          <aside className="surface-panel h-fit p-5">
            <div className="mb-5 grid grid-cols-2 rounded-md bg-surface-alt p-1">
              <Button variant={s.fulfillment === "DELIVERY" ? "default" : "ghost"} onClick={() => s.setFulfillment("DELIVERY")}>
                Delivery
              </Button>
              <Button variant={s.fulfillment === "PICKUP" ? "default" : "ghost"} onClick={() => s.setFulfillment("PICKUP")}>
                Pickup
              </Button>
            </div>
            {[["Subtotal", s.subtotal], ["Delivery fee", delivery], ["Tax", tax]].map(([l, v]) => (
              <div className="mb-3 flex justify-between" key={String(l)}>
                <span className="text-muted">{l}</span>
                <span>{formatINR(Number(v))}</span>
              </div>
            ))}
            <div className="mt-4 flex justify-between border-t border-border pt-4 text-xl font-black">
              <span>Total</span>
              <span>{formatINR(total)}</span>
            </div>
            <Button className="mt-6 w-full" asChild>
              {isAuthenticated ? (
                <Link to="/checkout">Continue to checkout</Link>
              ) : (
                <Link to="/login" search={{ redirect: "/checkout" }}>
                  Sign in to checkout
                </Link>
              )}
            </Button>
            {!isAuthenticated && (
              <p className="mt-3 text-center text-sm text-muted">Your cart is saved — signing in takes a moment.</p>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
