import { Check, EyeOff, Search } from "lucide-react";

import type { OwnerInsight, OwnerInsightStatus } from "../../types/app";

interface InsightFeedProps {
  insights: OwnerInsight[];
  /** Findings from runs whose window does not overlap the period on screen. */
  olderInsights?: OwnerInsight[];
  periodPhrase?: string;
  loading: boolean;
  busyId: string | null;
  onUpdateStatus: (insight: OwnerInsight, status: OwnerInsightStatus) => void;
}

const SEVERITY_LABEL: Record<string, string> = {
  HIGH: "High",
  MEDIUM: "Med",
  LOW: "Low",
  INFO: "Info",
};

function formatPeriod(insight: OwnerInsight): string {
  const formatter = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
  return `${formatter.format(new Date(insight.period_start))} – ${formatter.format(
    new Date(insight.period_end),
  )}`;
}

function InsightRow({
  insight,
  busyId,
  onUpdateStatus,
}: {
  insight: OwnerInsight;
  busyId: string | null;
  onUpdateStatus: (insight: OwnerInsight, status: OwnerInsightStatus) => void;
}) {
  return (
    <li
      className={`ai-row ai-row--${insight.severity.toLowerCase()}${
        insight.status === "DISMISSED" ? " is-dismissed" : ""
      }`}
    >
      <div className="ai-row__main">
        <div className="ai-row__head">
          <span className={`ai-sev ai-sev--${insight.severity.toLowerCase()}`}>
            {SEVERITY_LABEL[insight.severity] ?? insight.severity}
          </span>
          <strong>{insight.title}</strong>
          {insight.status !== "NEW" ? (
            <span className="ai-row__status">{insight.status}</span>
          ) : null}
          <span className="ai-row__period">{formatPeriod(insight)}</span>
        </div>

        <p className="ai-row__body">{insight.body}</p>

        {insight.root_cause ? (
          <p className="ai-cause">
            <Search size={12} strokeWidth={2.5} />
            {insight.root_cause}
          </p>
        ) : null}
      </div>

      {/* Hidden for a finding computed for the period on screen: there is no
          stored row behind it, so "mark seen" would have nothing to write to.
          Offering a control that cannot work is worse than not offering it. */}
      {insight.is_live ? null : (
      <div className="ai-row__actions">
        <button
          type="button"
          className="ai-icon-button"
          title="Mark seen"
          aria-label={`Mark "${insight.title}" seen`}
          disabled={busyId === insight.id || insight.status === "SEEN"}
          onClick={() => onUpdateStatus(insight, "SEEN")}
        >
          <Check size={14} strokeWidth={2.4} />
        </button>
        <button
          type="button"
          className="ai-icon-button"
          title="Dismiss"
          aria-label={`Dismiss "${insight.title}"`}
          disabled={busyId === insight.id || insight.status === "DISMISSED"}
          onClick={() => onUpdateStatus(insight, "DISMISSED")}
        >
          <EyeOff size={14} strokeWidth={2.4} />
        </button>
      </div>
      )}
    </li>
  );
}

export function InsightFeed({
  insights,
  olderInsights = [],
  periodPhrase,
  loading,
  busyId,
  onUpdateStatus,
}: InsightFeedProps) {
  if (loading) {
    return <section className="ai-card ai-card--loading">Loading insights…</section>;
  }

  return (
    <section className="ai-card">
      <header className="ai-card__head">
        <div className="ai-card__title">
          <span className="ai-eyebrow">Insight feed</span>
          <h2>
            {insights.length === 0
              ? "Nothing to flag"
              : `${insights.length} finding${insights.length === 1 ? "" : "s"}`}
          </h2>
        </div>
      </header>

      {insights.length === 0 ? (
        <p className="ai-empty">
          Nothing moved enough in {periodPhrase ?? "this period"} to be worth
          your attention. Quiet periods produce nothing, which is intentional —
          you can still ask the assistant anything about your data.
        </p>
      ) : (
        <ul className="ai-list">
          {insights.map((insight) => (
            <InsightRow
              key={insight.id}
              insight={insight}
              busyId={busyId}
              onUpdateStatus={onUpdateStatus}
            />
          ))}
        </ul>
      )}

      {olderInsights.length > 0 ? (
        // Kept, but visibly apart. These come from earlier runs covering other
        // windows; interleaving them made one list silently span two analyses.
        <details className="ai-older">
          <summary>
            {olderInsights.length} finding{olderInsights.length === 1 ? "" : "s"} from
            earlier periods
          </summary>
          <ul className="ai-list">
            {olderInsights.map((insight) => (
              <InsightRow
                key={insight.id}
                insight={insight}
                busyId={busyId}
                onUpdateStatus={onUpdateStatus}
              />
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
