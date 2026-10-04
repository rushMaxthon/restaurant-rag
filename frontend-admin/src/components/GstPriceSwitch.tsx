import { useState } from "react";

import { ApiError, api } from "../services/api";
import type { RestaurantLocation } from "../types/app";
import { ConfirmDialog } from "./ConfirmDialog";

interface GstPriceSwitchProps {
  token: string;
  restaurantId: string;
  location: RestaurantLocation;
  /** Name the branch in the heading. For a screen that lists several. */
  showBranchName?: boolean;
  /** The saved branch. Every price it sells at has just changed. */
  onChanged: (updated: RestaurantLocation) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

/**
 * "18% GST in menu prices" for one branch: what it is doing now, and the one
 * button that changes it.
 *
 * It sits wherever a menu's prices are shown — the branch's Menu Items tab and
 * the Menu Items page — because that is where somebody looks for a setting
 * that changes prices. It first shipped only as a checkbox in the Fulfilment &
 * fees form, below the payment methods, and nobody could find it.
 *
 * Saves on its own rather than through that form, and sends the one field:
 * the endpoint is a PATCH. It asks first, because the change is the whole
 * menu, for customers, at once.
 */
export function GstPriceSwitch({
  token,
  restaurantId,
  location,
  showBranchName = false,
  onChanged,
  onToast,
}: GstPriceSwitchProps) {
  // `null` is closed; a boolean is the value being asked about.
  const [prompt, setPrompt] = useState<boolean | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const isOn = Boolean(location.gst_in_menu_prices);

  const confirm = async () => {
    if (prompt === null || isSaving) {
      return;
    }
    const next = prompt;
    setIsSaving(true);
    try {
      const updated = await api.updateRestaurantLocationGeneralSettings(
        token,
        restaurantId,
        location.id,
        { gst_in_menu_prices: next },
      );
      onChanged(updated);
      onToast(
        next ? "18% GST added to menu prices" : "18% GST removed from menu prices",
        next
          ? `Customers of ${updated.branch_name} now see every price 18% higher.`
          : `Customers of ${updated.branch_name} now see the prices you typed.`,
        "success",
      );
      setPrompt(null);
    } catch (error: unknown) {
      const message =
        error instanceof ApiError ? error.message : "Unable to change the GST setting.";
      onToast("GST setting failed", message, "error");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <>
      <div className="gst-switch-card">
        <div className="gst-switch-card__text">
          <div className="gst-switch-card__title">
            <strong>
              18% GST in menu prices
              {showBranchName ? ` · ${location.branch_name}` : ""}
            </strong>
            <span className={isOn ? "toggle-pill toggle-pill--on" : "toggle-pill"}>
              {isOn ? "On" : "Off"}
            </span>
          </div>
          <p className="hint-text">
            {isOn
              ? "Customers see and pay every price on this branch with 18% GST already added, and no separate tax on food is charged at checkout. The editor still shows the price you typed."
              : "Customers see the prices you typed, and tax on food is added on the bill. Turn this on to add 18% GST to every price on this branch at once."}
          </p>
        </div>
        <button
          className={isOn ? "secondary-button" : "primary-button"}
          disabled={isSaving}
          onClick={() => setPrompt(!isOn)}
          type="button"
        >
          {isOn ? "Remove 18% GST" : "Add 18% GST to prices"}
        </button>
      </div>
      <ConfirmDialog
        busy={isSaving}
        confirmLabel={prompt ? "Add 18% GST" : "Remove 18% GST"}
        description={
          prompt
            ? `Every dish, size and extra at ${location.branch_name} will be listed and charged 18% higher, starting now. A dish priced at 100 becomes 118. Tax on food will no longer be added at checkout.`
            : `Every price at ${location.branch_name} will go back to exactly what you typed, starting now. Tax on food (${location.tax_percent ?? 5}%) will be added at checkout again.`
        }
        eyebrow="Menu prices"
        onCancel={() => setPrompt(null)}
        onConfirm={() => void confirm()}
        open={prompt !== null}
        title={prompt ? "Add 18% GST to every menu price?" : "Remove 18% GST from menu prices?"}
      />
    </>
  );
}
