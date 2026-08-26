import { AlertCircle, ArrowUpRight, Check, Loader2, Sparkles, Tag, Utensils } from "lucide-react";
import { useState } from "react";

import type { SuggestionCard } from "../../types/app";
import { discountLabel, needsDecimals, rupees } from "./suggestionFormat";

/**
 * Offers and combos the assistant suggested, as things you can act on.
 *
 * The answer text above these says what to do in a sentence. The card is where
 * the detail and the action live, so an owner never has to re-read a paragraph
 * to find the discount, then leave the conversation to apply it.
 *
 * State is resolved server-side into one of three: `creatable` (the offer does
 * not exist yet), `activatable` (it exists but is not running), `active`. The
 * client only tracks what happens after a click.
 */

export type CardOutcome = { state: "idle" } | { state: "busy" } | { state: "done"; label: string } | { state: "error"; message: string };

export interface SuggestionCardsProps {
  cards: SuggestionCard[];
  /** Resolves with the label to show once the action has succeeded. */
  onAct: (card: SuggestionCard) => Promise<string>;
  onView?: (card: SuggestionCard) => void;
}

/** What the card says about itself before anything has been clicked. */
const STATE_LABEL: Record<SuggestionCard["state"], string> = {
  creatable: "Not created yet",
  activatable: "Not running",
  active: "Live",
};

function Card({
  card,
  onAct,
  onView,
}: {
  card: SuggestionCard;
  onAct: SuggestionCardsProps["onAct"];
  onView?: SuggestionCardsProps["onView"];
}) {
  const [outcome, setOutcome] = useState<CardOutcome>({ state: "idle" });

  const discount = discountLabel(card.discount);
  const saving = card.pricing?.saving ?? null;
  const precise = needsDecimals(card.pricing);
  // Once the action has succeeded the card is live regardless of what the
  // server said when the answer was written, so the badge follows the outcome.
  const settled = outcome.state === "done" || card.state === "active";
  const busy = outcome.state === "busy";

  const act = async () => {
    if (busy || !card.action) {
      return;
    }
    setOutcome({ state: "busy" });
    try {
      setOutcome({ state: "done", label: await onAct(card) });
    } catch (error) {
      setOutcome({
        state: "error",
        message: error instanceof Error ? error.message : "That did not work. Try again.",
      });
    }
  };

  return (
    <article className={`ai-sug${settled ? " is-settled" : ""}`}>
      <header className="ai-sug__head">
        <span className={`ai-sug__icon ai-sug__icon--${card.kind}`}>
          {card.kind === "combo" ? <Utensils size={14} strokeWidth={2.2} /> : <Tag size={14} strokeWidth={2.2} />}
        </span>
        <div className="ai-sug__title">
          <strong>{card.title}</strong>
          <span className="ai-sug__kind">{card.kind === "combo" ? "Combo" : "Offer"}</span>
        </div>
        <span className={`ai-sug__state ai-sug__state--${settled ? "active" : card.state}`}>
          {settled ? "Live" : STATE_LABEL[card.state]}
        </span>
      </header>

      {/* The commercial terms, which is what an owner scans for first. */}
      {(discount || saving !== null || card.pricing) && (
        <div className="ai-sug__terms">
          {discount ? <span className="ai-sug__deal">{discount}</span> : null}
          {card.pricing && card.pricing.offered !== null ? (
            <span className="ai-sug__price">
              <s>
                {card.pricing.original !== null ? rupees(card.pricing.original, precise) : null}
              </s>
              <b>{rupees(card.pricing.offered, precise)}</b>
            </span>
          ) : null}
          {saving !== null && saving > 0 ? (
            <span className="ai-sug__save">Saves {rupees(saving, precise)}</span>
          ) : null}
          {card.minimum_order_amount ? (
            <span className="ai-sug__meta">Min order {rupees(card.minimum_order_amount)}</span>
          ) : null}
          {card.valid_for_days ? (
            <span className="ai-sug__meta">Runs {card.valid_for_days} days</span>
          ) : null}
        </div>
      )}

      {card.details.length > 0 ? (
        <ul className="ai-sug__items">
          {card.details.map((detail, index) => (
            <li key={`${detail.label}-${index}`}>
              <span>{detail.label}</span>
              {detail.value ? <b>{detail.value}</b> : null}
            </li>
          ))}
        </ul>
      ) : null}

      {card.reason ? <p className="ai-sug__why">{card.reason}</p> : null}

      {card.expected_impact ? (
        <p className="ai-sug__impact">
          <Sparkles size={12} strokeWidth={2.2} />
          Estimated recovery {rupees(card.expected_impact)}
        </p>
      ) : null}

      {card.evidence.length > 0 ? (
        <dl className="ai-sug__evidence">
          {card.evidence.map((row, index) => (
            <div key={`${row.label}-${index}`}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      <footer className="ai-sug__foot">
        {outcome.state === "done" ? (
          <span className="ai-sug__done">
            <Check size={14} strokeWidth={2.4} />
            {outcome.label}
          </span>
        ) : card.action ? (
          <button className="ai-sug__act" disabled={busy} onClick={act} type="button">
            {busy ? <Loader2 className="ai-sug__spin" size={14} strokeWidth={2.2} /> : null}
            {busy ? "Working…" : card.action_label}
          </button>
        ) : (
          <span className="ai-sug__done">
            <Check size={14} strokeWidth={2.4} />
            Already {card.kind === "combo" ? "live" : "running"}
          </span>
        )}

        {onView && (card.target_id || outcome.state === "done") ? (
          <button className="ai-sug__view" onClick={() => onView(card)} type="button">
            View
            <ArrowUpRight size={13} strokeWidth={2.2} />
          </button>
        ) : null}
      </footer>

      {outcome.state === "error" ? (
        <p className="ai-sug__error" role="alert">
          <AlertCircle size={13} strokeWidth={2.2} />
          {outcome.message}
        </p>
      ) : null}
    </article>
  );
}

export function SuggestionCards({ cards, onAct, onView }: SuggestionCardsProps) {
  if (cards.length === 0) {
    return null;
  }
  return (
    <div className="ai-sugs">
      {cards.map((card) => (
        <Card card={card} key={`${card.kind}-${card.id}`} onAct={onAct} onView={onView} />
      ))}
    </div>
  );
}
