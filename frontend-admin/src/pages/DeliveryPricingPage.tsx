import { Plus, Save, Trash2, Undo2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EmptyPanel } from "../components/EmptyPanel";
import { PageIntro } from "../components/PageIntro";
import { useMoney } from "../hooks/useMoney";
import { ApiError, api } from "../services/api";
import {
  addSlab,
  draftFrom,
  pricingFormError,
  removeSlab,
  slabRangeLabel,
  toPayload,
  withGst,
  type PricingDraft,
} from "../services/deliveryPricing";
import type { DeliveryPricing, ToastMessage } from "../types/app";

interface DeliveryPricingPageProps {
  token: string;
  onToast: (title: string, description: string, tone?: ToastMessage["tone"]) => void;
}

/**
 * What every restaurant charges for delivery, by distance.
 *
 * Since 2026-10-07 the platform prices delivery itself rather than printing
 * the courier's estimate; this is where the slabs, the furthest the platform
 * delivers and the GST on delivery are set. One answer for every restaurant,
 * applied to the next checkout after Save.
 *
 * Admin only, like the endpoint: beside what a courier charges, this is the
 * platform's delivery margin, and an owner is not shown it.
 */
export function DeliveryPricingPage({ token, onToast }: DeliveryPricingPageProps) {
  const money = useMoney();
  const [saved, setSaved] = useState<DeliveryPricing | null>(null);
  const [draft, setDraft] = useState<PricingDraft | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    api
      .getDeliveryPricing(token)
      .then((pricing) => {
        if (!current) return;
        setSaved(pricing);
        setDraft(draftFrom(pricing));
        setFailed(null);
      })
      .catch((error: unknown) => {
        if (!current) return;
        setFailed(error instanceof ApiError ? error.message : "Please try again.");
      });
    return () => {
      current = false;
    };
  }, [attempt, token]);

  const formError = draft ? pricingFormError(draft) : null;
  const dirty = useMemo(
    () => Boolean(saved && draft && JSON.stringify(draftFrom(saved)) !== JSON.stringify(draft)),
    [saved, draft],
  );

  const edit = (next: PricingDraft) => {
    setDraft(next);
    setServerError(null);
  };
  const editSlab = (index: number, field: "upToKm" | "fee", value: string) => {
    if (!draft) return;
    edit({
      ...draft,
      slabs: draft.slabs.map((slab, at) => (at === index ? { ...slab, [field]: value } : slab)),
    });
  };

  async function save() {
    if (!draft || formError) return;
    setBusy(true);
    setServerError(null);
    try {
      const next = await api.saveDeliveryPricing(token, toPayload(draft));
      setSaved(next);
      setDraft(draftFrom(next));
      onToast("Delivery pricing saved", "Every restaurant's checkout uses it from the next order.", "success");
    } catch (error) {
      setServerError(error instanceof ApiError ? error.message : "Could not save. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const intro = (
    <PageIntro
      description="What every restaurant charges for delivery, by road distance from the restaurant to the customer. Saved changes apply to the next checkout at every restaurant."
      eyebrow="Platform"
      title="Delivery pricing"
    />
  );

  if (failed) {
    return (
      <div className="page-stack">
        {intro}
        <section className="admin-surface">
          <EmptyPanel
            action={
              <button className="primary-button" onClick={() => setAttempt((count) => count + 1)} type="button">
                Try again
              </button>
            }
            description={failed}
            title="Delivery pricing didn't load"
          />
        </section>
      </div>
    );
  }

  if (!draft || !saved) {
    return (
      <div className="page-stack">
        {intro}
        <section className="admin-surface">
          <p className="hint-text">Loading delivery pricing…</p>
        </section>
      </div>
    );
  }

  const lastSaved = saved.saved
    ? `Last changed${saved.updated_by_name ? ` by ${saved.updated_by_name}` : ""}${
        saved.updated_at
          ? ` on ${new Date(saved.updated_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`
          : ""
      }.`
    : "Using the built-in prices — nothing has been saved here yet.";

  return (
    <div className="page-stack">
      {intro}

      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Distance slabs</span>
            <h2>Delivery fee by distance</h2>
            <p className="hint-text">
              Fees are before GST. The last slab covers everything further, up to the delivery limit below.
            </p>
          </div>
        </div>

        <div className="delivery-slabs">
          {draft.slabs.map((slab, index) => {
            const last = index === draft.slabs.length - 1;
            const paid = withGst(slab.fee, draft.gstPercent);
            return (
              <div className="delivery-slab" key={index}>
                <strong className="delivery-slab__range">{slabRangeLabel(draft, index)}</strong>
                <label className="field">
                  <span>Up to (km)</span>
                  {last ? (
                    <input aria-label="Up to (km)" disabled readOnly value={`${draft.maxDistanceKm || "?"} (limit)`} />
                  ) : (
                    <input
                      disabled={busy}
                      inputMode="decimal"
                      min={0}
                      onChange={(event) => editSlab(index, "upToKm", event.target.value)}
                      step="0.1"
                      type="number"
                      value={slab.upToKm}
                    />
                  )}
                </label>
                <label className="field">
                  <span>Fee before GST (₹)</span>
                  <input
                    disabled={busy}
                    inputMode="decimal"
                    min={0}
                    onChange={(event) => editSlab(index, "fee", event.target.value)}
                    step="1"
                    type="number"
                    value={slab.fee}
                  />
                </label>
                <div className="delivery-slab__paid">
                  <span>Customer pays</span>
                  <strong className="money">{paid === null ? "—" : money.format(paid)}</strong>
                </div>
                <button
                  aria-label={`Remove ${slabRangeLabel(draft, index)}`}
                  className="secondary-button delivery-slab__remove"
                  disabled={busy || draft.slabs.length <= 1}
                  onClick={() => edit(removeSlab(draft, index))}
                  title={draft.slabs.length <= 1 ? "There must always be one slab." : "Remove this slab"}
                  type="button"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            );
          })}
        </div>

        <button className="secondary-button" disabled={busy} onClick={() => edit(addSlab(draft))} type="button">
          <Plus size={15} /> Add a slab
        </button>
      </section>

      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Limits</span>
            <h2>How far, and the tax</h2>
          </div>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>Furthest delivery (km)</span>
            <input
              disabled={busy}
              inputMode="decimal"
              min={0}
              onChange={(event) => edit({ ...draft, maxDistanceKm: event.target.value })}
              step="0.5"
              type="number"
              value={draft.maxDistanceKm}
            />
            <small>
              Further than this, checkout says the address is too far and the order is refused. A branch&rsquo;s own
              service radius wins where one is set.
            </small>
          </label>
          <label className="field">
            <span>GST on delivery (%)</span>
            <input
              disabled={busy}
              inputMode="decimal"
              max={28}
              min={0}
              onChange={(event) => edit({ ...draft, gstPercent: event.target.value })}
              step="0.5"
              type="number"
              value={draft.gstPercent}
            />
            <small>Added on top of the fee, for every restaurant.</small>
          </label>
        </div>
      </section>

      <section className="admin-surface delivery-pricing__save">
        {formError ? <p role="alert">{formError}</p> : null}
        {serverError ? <p role="alert">{serverError}</p> : null}
        <div className="modal-actions">
          <button
            className="secondary-button"
            disabled={busy || !dirty}
            onClick={() => edit(draftFrom(saved))}
            type="button"
          >
            <Undo2 size={15} /> Discard changes
          </button>
          <button
            className="primary-button"
            disabled={busy || !dirty || Boolean(formError)}
            onClick={() => void save()}
            title={formError ?? (dirty ? "Save for every restaurant" : "Nothing has changed")}
            type="button"
          >
            <Save size={15} /> {busy ? "Saving…" : "Save for all restaurants"}
          </button>
        </div>
        <small className="hint-text">{dirty ? "You have unsaved changes." : lastSaved}</small>
      </section>
    </div>
  );
}
