import { useEffect, useState } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type SavedAddress } from "@/lib/api";
import { formatMoney, orderCode, type Order } from "@/lib/bangkok-data";
import { useAuth } from "@/lib/auth";
import { formatPhoneAsTyped, validatePhone } from "@/lib/delivery-address";
import { useFavorites, useProfile, useToggleFavorite } from "@/lib/queries";
import { useRequireAuth } from "@/lib/require-auth";
import { pageMeta } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

export const Route = createFileRoute("/profile")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Your tab", "Your account, addresses and saved details."),
  }),
  component: ProfilePage,
});

const PLACE_NAMES: Record<SavedAddress["label"], string> = {
  HOME: "Home",
  WORK: "Work",
  OTHER: "Another place",
};

/** Orders that have not finished yet, so they can be said differently. */
const SETTLED = new Set(["DELIVERED", "CANCELLED"]);

function whenPlaced(order: Order): string {
  const at = order.scheduled_at || order.placed_at;
  const date = at ? new Date(at) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * How this customer is doing here, as a sentence.
 *
 * This was four stat tiles — orders, delivered, saved places, favourites — set
 * in big numerals over small capitals. Legible, and the single most templated
 * treatment there is. A customer checking their account wants to know where
 * they stand, and that is a sentence, not a scoreboard.
 */
function standing(orders: number, onTheirWay: number, name: string): string {
  if (orders === 0) return `Nothing on your tab yet, ${name.split(" ")[0]}.`;
  const total = orders === 1 ? "One order" : `${orders} orders`;
  if (onTheirWay > 0) {
    return `${total} so far, and ${onTheirWay === 1 ? "one is" : `${onTheirWay} are`} on the way.`;
  }
  return `${total} so far. Nothing in the kitchen right now.`;
}

function ProfilePage() {
  const isAuthenticated = useRequireAuth();
  const { user } = useAuth();
  const profile = useProfile(isAuthenticated);
  const favorites = useFavorites(isAuthenticated);
  const toggleFavorite = useToggleFavorite();

  const [editing, setEditing] = useState(false);
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyPlace, setBusyPlace] = useState<string | null>(null);

  const account = profile.data?.user ?? user ?? null;

  useEffect(() => {
    if (!account || editing) return;
    setFullName(account.full_name ?? "");
    setPhone(account.phone_number ? formatPhoneAsTyped(account.phone_number) : "");
  }, [account, editing]);

  if (!isAuthenticated) return null;

  const stats = profile.data?.stats;
  const places = profile.data?.saved_addresses ?? [];
  const saved = favorites.data ?? [];
  const orders = profile.data?.recent_orders ?? [];
  const phoneProblem = phone.trim() ? validatePhone(phone) : null;
  const live = orders.filter((order) => !SETTLED.has(order.status)).length;

  async function saveDetails() {
    if (phoneProblem) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateProfile({ full_name: fullName.trim(), phone_number: phone.trim() || null });
      await profile.refetch();
      setEditing(false);
    } catch {
      setError("That did not save. Check your connection and try again.");
    } finally {
      setSaving(false);
    }
  }

  async function onPlace(id: string, action: () => Promise<unknown>) {
    setBusyPlace(id);
    setError(null);
    try {
      await action();
      await profile.refetch();
    } catch {
      setError("That address did not change. Try again in a moment.");
    } finally {
      setBusyPlace(null);
    }
  }

  return (
    <div className="page-pad mx-auto max-w-5xl py-6 pb-32 sm:py-8">
      {/* Reached from the header on any screen, so there is no one page to go
          back TO — it goes back to wherever you were. On a phone this is the
          only way out that is not the browser chrome. */}
      <button type="button" className="back-link" onClick={() => window.history.back()}>
        <ArrowLeft className="size-4" /> Back
      </button>

      <h1 className="tab__name mt-5">{account?.full_name || "Your tab"}</h1>
      <p className="tab__standing">
        {profile.isLoading
          ? "Fetching your tab…"
          : standing(stats?.total_orders ?? 0, live, account?.full_name || "there")}
      </p>

      {error && (
        <p className="tab__error mt-5" role="alert">
          {error}
        </p>
      )}

      <div className="tab mt-9">
        {/* The rail: quiet by design. It answers "is my number right", which is
            a question people ask once and then stop looking at. */}
        <aside className="rail">
          {editing ? (
            <div className="grid gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="tab_name">Name</Label>
                <Input
                  id="tab_name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="h-11"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tab_phone">Phone</Label>
                <Input
                  id="tab_phone"
                  type="tel"
                  inputMode="tel"
                  value={phone}
                  onChange={(e) => setPhone(formatPhoneAsTyped(e.target.value))}
                  className="h-11"
                  aria-invalid={Boolean(phoneProblem)}
                />
                {phoneProblem && <p className="field-error">{phoneProblem}</p>}
              </div>
              <div className="flex gap-2">
                <Button
                  onClick={saveDetails}
                  disabled={saving || !fullName.trim()}
                  className="h-10"
                >
                  {saving && <Loader2 className="size-4 animate-spin" />}
                  Save changes
                </Button>
                <Button variant="ghost" className="h-10" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <>
              <dl className="rail__row">
                <dt>Email</dt>
                <dd>{account?.email || "—"}</dd>
              </dl>
              <dl className="rail__row">
                <dt>Phone</dt>
                <dd>
                  {account?.phone_number
                    ? formatPhoneAsTyped(account.phone_number)
                    : "Not added yet"}
                </dd>
              </dl>
              <button type="button" className="rail__action" onClick={() => setEditing(true)}>
                Change these
              </button>
              <Link to="/preferences" className="rail__action">
                What you like to eat
              </Link>
            </>
          )}
        </aside>

        {/* The receipt: one surface, torn into sections. */}
        <section className="receipt">
          <div className="receipt__block">
            <h2 className="receipt__heading">Delivering to</h2>
            {places.length === 0 ? (
              <p className="receipt__note">
                No address saved. Tick <em>save this address</em> when you order and it will be
                waiting here.
              </p>
            ) : (
              <div className="mt-2">
                {places.map((place) => (
                  <div className="place" key={place.id} data-default={place.is_default}>
                    <span className="place__mark" aria-hidden="true" />
                    <span className="place__text">
                      <span className="place__name">{PLACE_NAMES[place.label]}</span>{" "}
                      {place.formatted_address}
                    </span>
                    <span className="place__actions">
                      {!place.is_default && (
                        <button
                          type="button"
                          className="rail__action"
                          disabled={busyPlace === place.id}
                          onClick={() =>
                            onPlace(place.id, () => api.makeSavedAddressDefault(place.id))
                          }
                        >
                          Use by default
                        </button>
                      )}
                      <button
                        type="button"
                        className="rail__action rail__danger"
                        disabled={busyPlace === place.id}
                        onClick={() => onPlace(place.id, () => api.deleteSavedAddress(place.id))}
                        aria-label={`Remove ${PLACE_NAMES[place.label]}`}
                      >
                        {busyPlace === place.id ? "Removing" : "Remove"}
                      </button>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="receipt__tear" />

          <div className="receipt__block">
            <h2 className="receipt__heading">What you keep coming back to</h2>
            {saved.length === 0 ? (
              <p className="receipt__note">
                Nothing saved. Tap the heart on a dish and it will be here, and at the top of{" "}
                <Link to="/menu" className="underline">
                  the menu
                </Link>
                .
              </p>
            ) : (
              <div className="mt-2">
                {saved.map((dish) => (
                  <div className="line line--saved" key={dish.id}>
                    <Link
                      to="/menu/$itemId"
                      params={{ itemId: dish.id }}
                      className="line__code line__dish"
                    >
                      {dish.name}
                    </Link>
                    <span className="money line__total">{formatMoney(dish.price)}</span>
                    <button
                      type="button"
                      className="rail__action rail__danger line__drop"
                      onClick={() => toggleFavorite.mutate({ menuItemId: dish.id, next: false })}
                      aria-label={`Remove ${dish.name} from your usuals`}
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="receipt__tear" />

          <div className="receipt__block">
            <h2 className="receipt__heading">What you have ordered</h2>
            {orders.length === 0 ? (
              <p className="receipt__note">
                Nothing yet.{" "}
                <Link to="/menu" className="underline">
                  Start with the menu
                </Link>
                .
              </p>
            ) : (
              <div className="mt-2">
                {orders.slice(0, 6).map((order) => (
                  <Link
                    to="/orders/$orderId"
                    params={{ orderId: order.id }}
                    className={`line ${SETTLED.has(order.status) ? "" : "line--live"}`}
                    key={order.id}
                  >
                    <span className="line__code">{orderCode(order)}</span>
                    <span className="money line__total">{formatMoney(order.total_amount)}</span>
                    <span className="line__when">
                      {whenPlaced(order)}
                      {!SETTLED.has(order.status) && (
                        <>
                          {" · "}
                          <span className="line__state">
                            {order.status.replaceAll("_", " ").toLowerCase()}
                          </span>
                        </>
                      )}
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </div>

          {orders.length > 0 && (
            <>
              <div className="receipt__tear" />
              <div className="receipt__block receipt__foot">
                <Link to="/orders" className="rail__action">
                  Every order
                </Link>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
