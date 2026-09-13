import { useEffect } from "react";
import { Link, createFileRoute, useNavigate, useRouterState } from "@tanstack/react-router";
import { CheckCircle2, ChevronLeft, Circle, MapPin } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { OrderItemThumb } from "@/components/bangkok/order-item-thumb";
import { formatINR, orderCode } from "@/lib/bangkok-data";
import { useAuth } from "@/lib/auth";
import { useOrder } from "@/lib/queries";

const steps = ["PLACED", "ACCEPTED", "PREPARING", "OUT_FOR_DELIVERY", "DELIVERED"];

export const Route = createFileRoute("/orders/$orderId")({
  head: () => ({
    meta: [
      { title: "Track Order — Bangkok Bowl" },
      { name: "description", content: "Follow your Bangkok Bowl order from kitchen to doorstep." },
      { property: "og:title", content: "Track Order — Bangkok Bowl" },
      { property: "og:description", content: "Live Bangkok Bowl order status." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: OrderDetail,
});

function OrderDetail() {
  const { orderId } = Route.useParams();
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.href });
  const orderQuery = useOrder(orderId, isAuthenticated);

  useEffect(() => {
    if (!isAuthenticated) navigate({ to: "/login", search: { redirect: pathname } });
  }, [isAuthenticated, navigate, pathname]);

  if (!isAuthenticated) return null;
  if (orderQuery.isLoading) {
    return (
      <div className="page-pad mx-auto max-w-4xl py-24">
        <div className="dish-placeholder placeholder-a h-64 animate-pulse rounded-lg" />
      </div>
    );
  }
  if (orderQuery.isError || !orderQuery.data) {
    return (
      <div className="page-pad py-24 text-center">
        <h1 className="font-display text-3xl font-black">We couldn't find that order</h1>
        <Button className="mt-6" asChild>
          <Link to="/orders">All orders</Link>
        </Button>
      </div>
    );
  }

  const o = orderQuery.data;
  const cancelled = o.status === "CANCELLED";
  const active = Math.max(steps.indexOf(o.status), 0);

  return (
    <div className="page-pad mx-auto max-w-4xl pb-24 pt-8">
      <Button variant="ghost" asChild>
        <Link to="/orders">
          <ChevronLeft />
          All orders
        </Link>
      </Button>
      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <Card className="border-border">
          <CardHeader>
            <p className="font-bold text-primary">Order {orderCode(o)}</p>
            <CardTitle className="font-display text-3xl font-black sm:text-4xl">
              {cancelled ? "This order was cancelled" : `Your order is ${o.status.toLowerCase().replaceAll("_", " ")}`}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!cancelled && (
              <div className="space-y-7">
                {steps.map((s, i) => (
                  <div className="flex items-start gap-3" key={s}>
                    {i <= active ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" /> : <Circle className="mt-0.5 size-5 shrink-0 text-border" />}
                    <div>
                      <b className={i <= active ? "" : "text-muted"}>{s.replaceAll("_", " ")}</b>
                      <p className="text-sm text-muted">{i <= active ? "Completed" : "Waiting"}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {o.fulfillment_type === "DELIVERY" && o.delivery_address && (
              <div className="mt-6 flex items-start gap-2 rounded-md bg-surface-alt p-3 text-sm">
                <MapPin className="mt-0.5 size-4 shrink-0 text-primary" />
                <span>{o.delivery_address}</span>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="h-fit border-border">
          <CardHeader>
            <CardTitle className="text-xl">Order summary</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 border-b border-border pb-4">
              {o.items.map((i) => (
                <div className="flex items-center gap-3" key={i.id}>
                  <OrderItemThumb menuItemId={i.menu_item_id} name={i.item_name_snapshot} className="size-12 shrink-0 rounded-md" />
                  <span className="min-w-0 flex-1 truncate">
                    {i.quantity}× {i.item_name_snapshot}
                  </span>
                  <span className="shrink-0 font-semibold">{formatINR(i.total_price)}</span>
                </div>
              ))}
            </div>
            <div className="mt-4 flex justify-between text-2xl font-black">
              <span>Total</span>
              <span>{formatINR(o.total_amount)}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
