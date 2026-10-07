/**
 * The admin's Delivery pricing page: the distance slabs every restaurant
 * charges, how far the platform delivers, and the GST on delivery.
 *
 * The server holds the real rules (`backend/app/services/delivery/slabs.py`,
 * `validate_update`) and refuses a bad list with a 422. These repeat them only
 * so the Save button can say what is wrong before anything is sent. Kept out
 * of the page so they can be tested without rendering a form.
 */

import type { DeliveryPricing, DeliveryPricingInput } from "../types/app";

export interface SlabDraft {
  /** Ignored on the last slab, which prices everything further. */
  upToKm: string;
  fee: string;
}

export interface PricingDraft {
  slabs: SlabDraft[];
  maxDistanceKm: string;
  gstPercent: string;
}

const MAX_GST_PERCENT = 28;

const isLast = (draft: PricingDraft, index: number) => index === draft.slabs.length - 1;

function num(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function draftFrom(pricing: DeliveryPricing): PricingDraft {
  return {
    slabs: pricing.slabs.map((slab) => ({
      upToKm: slab.up_to_km === null ? "" : String(slab.up_to_km),
      fee: String(slab.fee),
    })),
    maxDistanceKm: String(pricing.max_distance_km),
    gstPercent: String(pricing.gst_percent),
  };
}

/** The fee plus GST, to the paisa, or null while either is not a number. */
export function withGst(fee: string, gstPercent: string): number | null {
  const base = num(fee);
  const rate = num(gstPercent);
  if (base === null || rate === null) return null;
  return Math.round(base * (100 + rate)) / 100;
}

/** "Up to 2 km", "2 – 5 km", and the last slab ending at the delivery limit. */
export function slabRangeLabel(draft: PricingDraft, index: number): string {
  const from = index === 0 ? null : draft.slabs[index - 1].upToKm || "?";
  const to = isLast(draft, index) ? draft.maxDistanceKm || "?" : draft.slabs[index].upToKm || "?";
  return from === null ? `Up to ${to} km` : `${from} – ${to} km`;
}

/** What stops this draft being saved, in the admin's words, or null. */
export function pricingFormError(draft: PricingDraft): string | null {
  const limit = num(draft.maxDistanceKm);
  if (limit === null || limit <= 0) return "Say how far the platform delivers, in km.";
  if (draft.slabs.length === 0) return "Add at least one delivery slab.";

  let previous = 0;
  for (const [index, slab] of draft.slabs.entries()) {
    const fee = num(slab.fee);
    if (fee === null) return `Enter a fee for ${slabRangeLabel(draft, index)}.`;
    if (fee < 0) return "A delivery fee cannot be negative.";
    if (isLast(draft, index)) continue;
    const upTo = num(slab.upToKm);
    if (upTo === null || upTo <= 0) return `Enter the distance slab ${index + 1} goes up to.`;
    if (upTo <= previous) return "Each slab must go further than the one before it.";
    if (upTo >= limit) {
      return `A slab up to ${upTo} km is past the ${limit} km delivery limit, so nobody could be charged it.`;
    }
    previous = upTo;
  }

  const gst = num(draft.gstPercent);
  if (gst === null || gst < 0 || gst > MAX_GST_PERCENT) {
    return `GST on delivery must be between 0% and ${MAX_GST_PERCENT}%.`;
  }
  return null;
}

export function toPayload(draft: PricingDraft): DeliveryPricingInput {
  return {
    slabs: draft.slabs.map((slab, index) => ({
      up_to_km: isLast(draft, index) ? null : Number(slab.upToKm),
      fee: Number(slab.fee).toFixed(2),
    })),
    max_distance_km: Number(draft.maxDistanceKm),
    gst_percent: Number(draft.gstPercent).toFixed(2),
  };
}

/** A new slab just before the open-ended last one, a kilometre further. */
export function addSlab(draft: PricingDraft): PricingDraft {
  const slabs = [...draft.slabs];
  const beforeLast = slabs.length >= 2 ? num(slabs[slabs.length - 2].upToKm) ?? 0 : 0;
  const last = slabs[slabs.length - 1];
  slabs.splice(slabs.length - 1, 0, { upToKm: String(beforeLast + 1), fee: last?.fee ?? "" });
  return { ...draft, slabs };
}

/** Removes a slab. The only one left stays: there must always be a price. */
export function removeSlab(draft: PricingDraft, index: number): PricingDraft {
  if (draft.slabs.length <= 1) return draft;
  const slabs = draft.slabs.filter((_, at) => at !== index);
  // The new last slab is open-ended; its old upper distance means nothing now.
  slabs[slabs.length - 1] = { ...slabs[slabs.length - 1], upToKm: "" };
  return { ...draft, slabs };
}
