import { Bike, ChefHat, ShoppingBag, UtensilsCrossed } from "lucide-react";

import type { RestaurantLocation } from "@/lib/bangkok-data";

/**
 * What happens between tapping a dish and eating it.
 *
 * Three sentences, and the reason they belong on a brand page rather than in a
 * help article is that a first-time visitor to an unfamiliar kitchen's site is
 * weighing exactly this: do I have to phone anyone, is the food sitting under
 * a lamp already, and how does it reach me.
 *
 * **These are facts about the platform and about this branch — never about the
 * food.** "Cooked after you order" is true of every restaurant here because
 * the kitchen board only receives an order once it is placed; the preparation
 * time is the branch's own `estimated_*` column, written by its owner; and the
 * last step names only the fulfilment methods the branch has actually switched
 * on. A branch that does no delivery is not told it delivers, and a branch
 * that has published no time gets a step with no number in it rather than an
 * invented thirty minutes.
 */
export function HowToOrder({ branch }: { branch: RestaurantLocation | undefined }) {
  if (!branch) return null;

  const delivery = branch.delivery_enabled;
  const pickup = branch.pickup_enabled;
  // Whichever is on; delivery's number when both are, because that is the one
  // being quoted on the rest of the page.
  const minutes = Number(delivery ? branch.estimated_delivery_time : branch.estimated_pickup_time);
  const hasMinutes = Number.isFinite(minutes) && minutes > 0;

  const last = delivery && pickup ? "both" : delivery ? "delivery" : pickup ? "pickup" : "neither";
  if (last === "neither") return null;

  return (
    <section className="how">
      <div className="page-pad section-pad how__inner">
        <p className="eyebrow reveal">How it works</p>
        <h2 className="font-display how__title reveal-wipe">
          <span>Three steps, no phone call</span>
        </h2>

        <ol className="how__steps reveal-group--sides">
          <li className="how__step">
            <span className="how__n" aria-hidden="true">
              1
            </span>
            <UtensilsCrossed className="how__icon" aria-hidden="true" />
            <h3>Pick what you want</h3>
            <p>
              The whole menu is online with the price you will actually be charged. Choose a size or
              an option where the kitchen offers one.
            </p>
          </li>

          <li className="how__step">
            <span className="how__n" aria-hidden="true">
              2
            </span>
            <ChefHat className="how__icon" aria-hidden="true" />
            <h3>Straight to the counter</h3>
            <p>
              {/* "Nothing is sitting waiting" was here and is not ours to
                  say: it is true of a bakery that bakes to order and false of
                  a counter that holds food ready, and this page cannot tell
                  which restaurant it is on. What is left is true by
                  construction — the kitchen board receives the order when it
                  is placed, because that is how the software works. */}
              Your order reaches the kitchen the moment it is placed.
              {hasMinutes ? ` ${branch.branch_name} works to about ${minutes} minutes.` : ""} Want
              it later? Pick a time at checkout.
            </p>
          </li>

          <li className="how__step">
            <span className="how__n" aria-hidden="true">
              3
            </span>
            {last === "pickup" ? (
              <ShoppingBag className="how__icon" aria-hidden="true" />
            ) : (
              <Bike className="how__icon" aria-hidden="true" />
            )}
            <h3>
              {last === "both"
                ? "Delivered, or collect it"
                : last === "delivery"
                  ? "Delivered to your door"
                  : "Collect when it is ready"}
            </h3>
            <p>
              {last === "both"
                ? "Have it brought to your address, or come to the counter — whichever suits. You are told when it is on its way."
                : last === "delivery"
                  ? "It leaves as soon as it is ready, and you are told when it does."
                  : "We let you know the moment it is ready, so it is still warm when you arrive."}
            </p>
          </li>
        </ol>
      </div>
    </section>
  );
}
