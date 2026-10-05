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
  /** The saved branch. */
  onChanged: (updated: RestaurantLocation) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

/**
 * "Menu prices already include GST" for one branch: what it is doing now, and
 * the one button that changes it.
 *
 * The switch is a statement about the prices the owner typed, and it never
 * changes one. On: they are GST-inclusive, so the customer pays the menu
 * price and no tax on food is added at checkout. Off: they are before tax,
 * and the branch's own rate is added on the bill. It first shipped the other
 * way round — on ADDED 18% to the menu — which is why every sentence here
 * says out loud that prices stay as typed.
 *
 * It sits wherever a menu's prices are shown — the branch's Menu Items tab and
 * the Menu Items page — because that is where somebody looks for a setting
 * about prices. As a checkbox in the Fulfilment & fees form alone, below the
 * payment methods, nobody could find it.
 *
 * Saves on its own rather than through that form, and sends the one field:
 * the endpoint is a PATCH. It asks first, because it changes what every
 * customer of the branch is billed from the next order on.
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
  const taxPercent = Number(location.tax_percent ?? 5);

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
        next ? "Menu prices now include GST" : "Tax is now added at checkout",
        next
          ? `Customers of ${updated.branch_name} pay the menu price, with no tax on food added at checkout.`
          : `Customers of ${updated.branch_name} pay the menu price plus ${Number(updated.tax_percent ?? 5)}% tax on food at checkout.`,
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
              Menu prices already include GST
              {showBranchName ? ` · ${location.branch_name}` : ""}
            </strong>
            <span className={isOn ? "toggle-pill toggle-pill--on" : "toggle-pill"}>
              {isOn ? "On" : "Off"}
            </span>
          </div>
          <p className="hint-text">
            {isOn
              ? "The prices you typed already have GST in them. Customers pay exactly the menu price, and no tax on food is added at checkout."
              : `The prices you typed are before tax. Tax on food (${taxPercent}%) is added to the bill at checkout. Turn this on if your prices already include GST.`}
          </p>
        </div>
        <button
          className={isOn ? "secondary-button" : "primary-button"}
          disabled={isSaving}
          onClick={() => setPrompt(!isOn)}
          type="button"
        >
          {isOn ? "Add tax at checkout instead" : "My prices include GST"}
        </button>
      </div>
      <ConfirmDialog
        busy={isSaving}
        confirmLabel={prompt ? "Yes, prices include GST" : "Add tax at checkout"}
        description={
          prompt
            ? `Customers of ${location.branch_name} will pay exactly the menu price, starting with the next order. Tax on food (${taxPercent}%) will no longer be added at checkout. Your menu prices do not change.`
            : `Tax on food (${taxPercent}%) will be added to every bill at ${location.branch_name}, on top of the menu price, starting with the next order. Your menu prices do not change.`
        }
        eyebrow="Tax on food"
        onCancel={() => setPrompt(null)}
        onConfirm={() => void confirm()}
        open={prompt !== null}
        title={prompt ? "Do your menu prices already include GST?" : "Add tax on food at checkout?"}
      />
    </>
  );
}
