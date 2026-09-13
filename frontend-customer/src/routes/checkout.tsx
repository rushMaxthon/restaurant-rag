import { useEffect, useState } from "react";
import { Link, createFileRoute, useNavigate, useRouterState } from "@tanstack/react-router";
import { AlertCircle, CheckCircle2, MapPin, Phone, ShieldCheck, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DishImage } from "@/components/bangkok/dish-image";
import { formatINR, orderCode } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useAuth } from "@/lib/auth";
import { useCreateOrder, useValidateOrder } from "@/lib/queries";
import { ApiError, type OrderCreateRequest } from "@/lib/api";

export const Route = createFileRoute("/checkout")({
  head: () => ({
    meta: [
      { title: "Checkout — Bangkok Bowl" },
      { name: "description", content: "Choose delivery or pickup and place your Bangkok Bowl order." },
      { property: "og:title", content: "Checkout — Bangkok Bowl" },
      { property: "og:description", content: "Complete your Bangkok Bowl order." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: Checkout,
});

function Checkout() {
  const s = useBangkokStore();
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (st) => st.location.href });
  const validateOrder = useValidateOrder();
  const createOrder = useCreateOrder();

  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [placedOrderId, setPlacedOrderId] = useState<string | null>(null);
  const [placedOrderNumber, setPlacedOrderNumber] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated) navigate({ to: "/login", search: { redirect: pathname } });
  }, [isAuthenticated, navigate, pathname]);

  if (!isAuthenticated) return null;

  const branch = s.currentLocation;
  const delivery = s.fulfillment === "DELIVERY" ? Number(branch?.delivery_fee ?? 45) : 0;
  const tax = s.subtotal * 0.05;
  const total = s.subtotal + delivery + tax;

  if (placedOrderId) {
    return (
      <div className="page-pad mx-auto max-w-xl py-24 text-center">
        <CheckCircle2 className="mx-auto size-20 text-success" />
        <h1 className="mt-6 font-display text-5xl font-black sm:text-6xl">Order placed!</h1>
        <p className="mt-4 text-lg text-muted">Your Thai feast is on its way. Track {placedOrderNumber ?? "your order"} for live updates.</p>
        <Button className="mt-8 h-12 px-8 text-base" asChild>
          <Link to="/orders/$orderId" params={{ orderId: placedOrderId }}>
            Track order
          </Link>
        </Button>
      </div>
    );
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    if (!s.restaurantId || !s.branchId) {
      setError("We couldn't determine your branch. Please pick a branch and try again.");
      return;
    }
    const deliveryAddress = s.fulfillment === "DELIVERY" ? address : branch?.address_line_1 || address || "Pickup order";
    if (s.fulfillment === "DELIVERY" && deliveryAddress.trim().length < 5) {
      setError("Please enter a delivery address.");
      return;
    }

    const payload: OrderCreateRequest = {
      restaurant_id: s.restaurantId,
      restaurant_location_id: s.branchId,
      fulfillment_type: s.fulfillment,
      delivery_address: deliveryAddress,
      items: s.cart.map((line) => ({
        menu_item_id: line.itemId,
        menu_item_size_id: line.sizeId ?? null,
        selected_options: line.optionIds.map((id) => ({ option_id: id, quantity: 1 })),
        quantity: line.quantity,
      })),
    };

    try {
      await validateOrder.mutateAsync(payload);
      const order = await createOrder.mutateAsync(payload);
      s.clearCart();
      setPlacedOrderId(order.id);
      setPlacedOrderNumber(orderCode(order));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't place your order. Please try again.");
    }
  }

  const submitting = validateOrder.isPending || createOrder.isPending;

  return (
    <form className="page-pad mx-auto max-w-6xl pb-32 pt-10" onSubmit={handleSubmit}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-full bg-primary px-3 py-1 text-xs font-black text-primary-foreground">STEP 2 OF 3</span>
        <p className="text-sm font-bold text-muted">Cart → Checkout → Confirmation</p>
      </div>
      <h1 className="mt-4 font-display text-4xl font-black sm:text-6xl">Checkout</h1>
      <p className="mt-3 text-lg text-muted">Almost there — just confirm where this is headed.</p>

      {error && (
        <div className="mt-6 flex items-start gap-2 rounded-md border border-danger bg-danger/10 p-4 text-sm font-semibold text-danger">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_420px]">
        <Card className="border-border">
          <CardHeader>
            <CardTitle className="text-xl">Contact &amp; {s.fulfillment === "DELIVERY" ? "delivery" : "pickup"}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="full_name" className="flex items-center gap-2">
                <User className="size-4 text-primary" /> Full name
              </Label>
              <Input id="full_name" required placeholder="Your name" value={fullName} onChange={(e) => setFullName(e.target.value)} className="h-12" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="phone" className="flex items-center gap-2">
                <Phone className="size-4 text-primary" /> Phone number
              </Label>
              <Input id="phone" required type="tel" placeholder="Phone number" value={phone} onChange={(e) => setPhone(e.target.value)} className="h-12" />
            </div>
            {s.fulfillment === "DELIVERY" && (
              <div className="space-y-1.5">
                <Label htmlFor="address" className="flex items-center gap-2">
                  <MapPin className="size-4 text-primary" /> Delivery address
                </Label>
                <Input id="address" required placeholder="Flat, street, area" value={address} onChange={(e) => setAddress(e.target.value)} className="h-12" />
              </div>
            )}
            {s.fulfillment === "PICKUP" && branch && (
              <div className="flex items-start gap-2 rounded-md bg-surface-alt p-3 text-sm">
                <MapPin className="mt-0.5 size-4 shrink-0 text-primary" />
                <span>
                  Pickup from <b>{branch.branch_name}</b>, {branch.address_line_1}
                </span>
              </div>
            )}
            <div className="flex items-start gap-2 pt-2 text-sm text-muted">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-success" />
              <span>Pay securely on delivery or pickup — no card details needed now.</span>
            </div>
          </CardContent>
        </Card>

        <Card className="h-fit border-border">
          <CardHeader>
            <CardTitle className="text-xl">Your order</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted">
              {s.fulfillment === "DELIVERY" ? "Delivery" : "Pickup"} from {branch?.branch_name ?? "your branch"}
            </p>
            <div className="mt-4 space-y-3 border-b border-border pb-4">
              {s.cart.map((line) => (
                <div className="flex items-center gap-3" key={line.lineId}>
                  <DishImage src={line.image_url} name={line.name} className="size-12 shrink-0 rounded-md" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold">
                      {line.quantity}× {line.name}
                    </p>
                  </div>
                  <span className="shrink-0 font-semibold">{formatINR(line.unitPrice * line.quantity)}</span>
                </div>
              ))}
            </div>
            <div className="mt-4 space-y-2 text-sm">
              <div className="flex justify-between text-muted">
                <span>Subtotal</span>
                <span>{formatINR(s.subtotal)}</span>
              </div>
              <div className="flex justify-between text-muted">
                <span>Delivery fee</span>
                <span>{formatINR(delivery)}</span>
              </div>
              <div className="flex justify-between text-muted">
                <span>Tax</span>
                <span>{formatINR(tax)}</span>
              </div>
            </div>
            <div className="mt-4 flex justify-between border-t border-border pt-4 text-2xl font-black">
              <span>Total</span>
              <span>{formatINR(total)}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="fixed inset-x-0 bottom-[58px] z-30 border-t border-border bg-surface p-3 lg:bottom-0">
        <Button className="mx-auto flex h-14 w-full max-w-2xl text-base" disabled={!s.cart.length || submitting} type="submit">
          {submitting ? "Placing order…" : `Place order · ${formatINR(total)}`}
        </Button>
      </div>
    </form>
  );
}
