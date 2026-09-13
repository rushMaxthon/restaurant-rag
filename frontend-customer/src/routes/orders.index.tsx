import { useEffect } from "react";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { ArrowRight, LogOut, ReceiptText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { OrderItemThumb } from "@/components/bangkok/order-item-thumb";
import { formatINR, orderCode } from "@/lib/bangkok-data";
import { useAuth } from "@/lib/auth";
import { useRequireAuth } from "@/lib/require-auth";
import { useOrders } from "@/lib/queries";

export const Route = createFileRoute("/orders/")({
  head: () => ({
    meta: [
      { title: "Your Orders — Bangkok Bowl" },
      { name: "description", content: "Track current Bangkok Bowl orders and view past orders." },
      { property: "og:title", content: "Your Orders — Bangkok Bowl" },
      { property: "og:description", content: "Track and review your Bangkok Bowl orders." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: Orders,
});

const STATUS_TONE: Record<string, string> = {
  DELIVERED: "bg-success/15 text-success",
  CANCELLED: "bg-danger/15 text-danger",
};

function Orders() {
  const { user, logout } = useAuth();
  const isAuthenticated = useRequireAuth();
  const navigate = useNavigate();
  const ordersQuery = useOrders(isAuthenticated);


  if (!isAuthenticated) return null;

  return (
    <div className="page-pad mx-auto max-w-5xl pb-24 pt-10">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-black sm:text-6xl">Your orders</h1>
          {user && <p className="mt-2 text-lg text-muted">Signed in as {user.full_name}</p>}
        </div>
        <Button
          variant="outline"
          onClick={() => {
            logout();
            navigate({ to: "/" });
          }}
        >
          <LogOut />
          Log out
        </Button>
      </div>

      {ordersQuery.isLoading && (
        <div className="mt-10 grid gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="dish-placeholder placeholder-a h-28 animate-pulse rounded-lg" />
          ))}
        </div>
      )}
      {ordersQuery.isError && <p className="mt-10 text-muted">We couldn't load your orders right now.</p>}
      {!ordersQuery.isLoading && !ordersQuery.isError && ordersQuery.data?.length === 0 && (
        <div className="surface-panel mt-10 py-24 text-center">
          <ReceiptText className="mx-auto size-14 text-primary" />
          <h2 className="mt-5 text-2xl font-bold">No orders yet</h2>
          <p className="mt-2 text-muted">Your order history will show up here once you place one.</p>
          <Button className="mt-6 h-12 px-6" asChild>
            <Link to="/menu">Browse the menu</Link>
          </Button>
        </div>
      )}

      <div className="mt-8 grid gap-4">
        {ordersQuery.data?.map((o) => {
          const tone = STATUS_TONE[o.status] ?? "bg-primary/15 text-primary";
          return (
            <Card key={o.id} className="border-border">
              <CardContent className="flex flex-wrap items-start justify-between gap-4 p-5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full px-3 py-1 text-xs font-black ${tone}`}>{o.status.replaceAll("_", " ")}</span>
                    {o.restaurant && <span className="text-sm font-semibold text-muted">{o.restaurant.name}</span>}
                  </div>
                  <h2 className="mt-2 text-2xl font-black">Order {orderCode(o)}</h2>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {o.items.slice(0, 4).map((item) => (
                      <OrderItemThumb key={item.id} menuItemId={item.menu_item_id} name={item.item_name_snapshot} className="size-12 rounded-md" />
                    ))}
                    {o.items.length > 4 && <span className="flex size-12 items-center justify-center rounded-md bg-surface-alt text-xs font-bold text-muted">+{o.items.length - 4}</span>}
                  </div>
                </div>
                <div className="text-right">
                  <b className="text-lg">{formatINR(o.total_amount)}</b>
                  <Button variant="ghost" asChild className="mt-2 block">
                    <Link to="/orders/$orderId" params={{ orderId: o.id }}>
                      View order <ArrowRight />
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
