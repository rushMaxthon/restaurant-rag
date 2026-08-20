import { AlertCircle, Check, Info, TrendingUp, X } from "lucide-react";

import { formatCurrency } from "../../services/api";
import type { ActionOutcome, OwnerActionProposal } from "../../types/app";

interface RecommendationListProps {
  proposals: OwnerActionProposal[];
  loading: boolean;
  busyId: string | null;
  onApprove: (proposal: OwnerActionProposal) => void;
  onReject: (proposal: OwnerActionProposal) => void;
}

/** Pulls the headline terms out of the stored offer payload for display. */
function offerTerms(proposal: OwnerActionProposal): string | null {
  const payload = proposal.action_payload ?? {};
  const discountType = payload.discount_type;
  const discountValue = payload.discount_value;
  const minimumOrder = payload.minimum_order_amount;

  if (typeof discountType !== "string" || discountValue === undefined) {
    return null;
  }

  const value = Number(discountValue);
  const amount =
    discountType === "PERCENTAGE" ? `${value}% off` : `${formatCurrency(value)} off`;
  const minimum =
    minimumOrder === undefined
      ? ""
      : ` on orders over ${formatCurrency(Number(minimumOrder))}`;
  return `${amount}${minimum}`;
}


const VERDICT_LABEL: Record<string, string> = {
  NO_UPTAKE: "No uptake",
  BELOW_ESTIMATE: "Below estimate",
  MET_ESTIMATE: "Met estimate",
  ABOVE_ESTIMATE: "Above estimate",
  NOT_MEASURABLE: "Measured",
};

/**
 * What happened after an action ran.
 *
 * Worded as observation, matching the backend: these are orders that *used* the
 * offer, not orders it can be shown to have caused. There is no holdout group,
 * so an owner reading a causal claim here would be misled.
 */
function OutcomeBadge({ outcome }: { outcome: ActionOutcome }) {
  return (
    <div className={`ai-outcome ai-outcome--${outcome.verdict.toLowerCase()}`}>
      <div className="ai-outcome__head">
        <TrendingUp size={13} strokeWidth={2.3} />
        <strong>{VERDICT_LABEL[outcome.verdict] ?? "Measured"}</strong>
        <span>
          {outcome.attributed_orders} order{outcome.attributed_orders === 1 ? "" : "s"} ·{" "}
          {formatCurrency(outcome.attributed_revenue)} used this offer
        </span>
      </div>
      <p>{outcome.summary}</p>
    </div>
  );
}

export function RecommendationList({
  proposals,
  loading,
  busyId,
  onApprove,
  onReject,
}: RecommendationListProps) {
  if (loading) {
    return <div className="ai-card ai-card--loading">Loading recommendations…</div>;
  }

  if (proposals.length === 0) {
    return (
      <section className="ai-card">
        <header className="ai-card__head">
          <div className="ai-card__title">
            <span className="ai-eyebrow">Recommendations</span>
            <h2>Nothing to act on</h2>
          </div>
        </header>
        <p className="ai-empty">
          These come from the nightly analysis. New ones appear when a finding
          suggests something you can actually do.
        </p>
      </section>
    );
  }

  return (
    <section className="ai-card">
      <header className="ai-card__head">
        <div className="ai-card__title">
          <span className="ai-eyebrow">Recommendations</span>
          <h2>{proposals.length} suggested action{proposals.length === 1 ? "" : "s"}</h2>
        </div>
      </header>

      <ul className="ai-list">
        {proposals.map((proposal) => {
          const terms = offerTerms(proposal);
          return (
            <li className="ai-row ai-row--action" key={proposal.id}>
              {/* Everything stacks inside one column. Without this wrapper the
                  row's own flex layout turned each block below into a side-by-side
                  column, which is what made the title wrap to three lines while
                  the buttons stacked. */}
              <div className="ai-row__main">
                <div className="ai-row__head">
                  <strong>{proposal.title}</strong>
                  {proposal.is_executable ? (
                    <span className="ai-chip ai-chip--action">Creates an offer</span>
                  ) : (
                    <span className="ai-chip ai-chip--advisory">
                      <Info size={12} strokeWidth={2.3} />
                      Advisory only
                    </span>
                  )}
                </div>

                <p className="ai-row__body">{proposal.rationale}</p>

                {/* Labelled pairs in a fixed grid, so terms and impact line up
                    from one recommendation to the next instead of landing
                    wherever the prose above them happens to end. */}
                {terms || proposal.expected_impact_amount !== null ? (
                  <dl className="ai-facts-grid">
                    {terms ? (
                      <div className="ai-facts-grid__item">
                        <dt>Offer terms</dt>
                        <dd>{terms}</dd>
                      </div>
                    ) : null}
                    {proposal.expected_impact_amount !== null ? (
                      <div className="ai-facts-grid__item">
                        <dt>Estimated recovery</dt>
                        <dd>
                          <strong>
                            {formatCurrency(proposal.expected_impact_amount)}
                          </strong>
                          {proposal.expected_impact_basis ? (
                            <span className="ai-row__basis">
                              {proposal.expected_impact_basis}
                            </span>
                          ) : null}
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                ) : null}

                {proposal.outcome ? <OutcomeBadge outcome={proposal.outcome} /> : null}

                {proposal.status === "FAILED" && proposal.failure_reason ? (
                  <p className="ai-row__error">
                    <AlertCircle size={14} strokeWidth={2.2} />
                    {proposal.failure_reason}
                  </p>
                ) : null}

                <div className="ai-row__foot">
                  <span className="ai-row__status">{proposal.status}</span>
                  <div className="ai-row__buttons">
                    <button
                      type="button"
                      className="primary-button ai-btn"
                      disabled={busyId === proposal.id}
                      onClick={() => onApprove(proposal)}
                    >
                      <Check size={14} strokeWidth={2.2} />
                      {proposal.is_executable ? "Approve & create" : "Acknowledge"}
                    </button>
                    <button
                      type="button"
                      className="secondary-button ai-btn"
                      disabled={busyId === proposal.id}
                      onClick={() => onReject(proposal)}
                    >
                      <X size={14} strokeWidth={2.2} />
                      Reject
                    </button>
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <p className="ai-footnote">
        Impact figures are estimates, not forecasts. Nothing is created until you approve it.
      </p>
    </section>
  );
}
