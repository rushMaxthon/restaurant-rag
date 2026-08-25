import { useState } from "react";
import { Check, EyeOff, Search } from "lucide-react";

import { formatImpact, rankInsights, type InsightImpact } from "./insightImpact";
import type { OwnerInsight, OwnerInsightStatus } from "../../types/app";

/**
 * The ranked findings, said rather than displayed.
 *
 * Second message in the thread, after the briefing. Ordering comes from the
 * `score` the API already sends, and the bar is that score against the largest
 * finding on screen - so which two of nine matter is answerable before reading.
 */
const OPEN_COUNT = 5;

/** Only shown when it says something. Nine identical "Low" chips said nothing. */
const NOTABLE_SEVERITY: Record<string, string> = {
  HIGH: "High",
  MEDIUM: "Medium",
};

function Finding({
  insight,
  impact,
  busyId,
  onUpdateStatus,
}: {
  insight: OwnerInsight;
  impact: InsightImpact;
  busyId: string | null;
  onUpdateStatus: (insight: OwnerInsight, status: OwnerInsightStatus) => void;
}) {
  const amount = formatImpact(impact.amount);
  const severity = NOTABLE_SEVERITY[insight.severity];

  return (
    <li
      className={`ai-find${insight.status === "DISMISSED" ? " is-dismissed" : ""}${
        insight.status === "SEEN" ? " is-seen" : ""
      }`}
    >
      <div className="ai-find__impact">
        <div className={`ai-find__bar ai-find__bar--${impact.direction}`}>
          <i style={{ width: `${Math.max(impact.share * 100, 4)}%` }} />
        </div>
        {amount ? <span className="ai-find__amount">{amount}</span> : null}
      </div>

      <div className="ai-find__main">
        <div className="ai-find__head">
          <strong>{insight.title}</strong>
          {severity ? (
            <span className={`ai-sev ai-sev--${insight.severity.toLowerCase()}`}>{severity}</span>
          ) : null}
          {impact.stoppedTrading ? (
            <span className="ai-sev ai-sev--stopped">Stopped trading</span>
          ) : null}
        </div>

        <p className="ai-find__body">{insight.body}</p>

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
        <div className="ai-find__actions">
          <button
            aria-label={`Mark "${insight.title}" seen`}
            className="ai-find__action"
            disabled={busyId === insight.id || insight.status === "SEEN"}
            onClick={() => onUpdateStatus(insight, "SEEN")}
            type="button"
          >
            <Check size={13} strokeWidth={2.4} />
            Acknowledge
          </button>
          <button
            aria-label={`Dismiss "${insight.title}"`}
            className="ai-find__action"
            disabled={busyId === insight.id || insight.status === "DISMISSED"}
            onClick={() => onUpdateStatus(insight, "DISMISSED")}
            type="button"
          >
            <EyeOff size={13} strokeWidth={2.4} />
            Dismiss
          </button>
        </div>
      )}
    </li>
  );
}

export function FindingsMessage({
  insights,
  periodPhrase,
  busyId,
  onUpdateStatus,
}: {
  insights: OwnerInsight[];
  periodPhrase: string;
  busyId: string | null;
  onUpdateStatus: (insight: OwnerInsight, status: OwnerInsightStatus) => void;
}) {
  const [showAll, setShowAll] = useState(false);

  if (insights.length === 0) {
    // A quiet period is one sentence, not a panel apologising for itself.
    return (
      <div className="ai-said">
        <p className="ai-said__narrative">
          Nothing else moved enough in {periodPhrase} to be worth flagging. You can
          still ask me anything about your data.
        </p>
      </div>
    );
  }

  const ranked = rankInsights(insights);
  const visible = showAll ? ranked : ranked.slice(0, OPEN_COUNT);
  const hidden = ranked.length - visible.length;

  return (
    <div className="ai-said">
      <p className="ai-said__lead">
        {insights.length} finding{insights.length === 1 ? "" : "s"}, largest first.
      </p>
      <ul className="ai-finds">
        {visible.map(({ insight, impact }) => (
          <Finding
            busyId={busyId}
            impact={impact}
            insight={insight}
            key={insight.id}
            onUpdateStatus={onUpdateStatus}
          />
        ))}
      </ul>
      {hidden > 0 ? (
        <button className="ai-fold" onClick={() => setShowAll(true)} type="button">
          Show {hidden} smaller finding{hidden === 1 ? "" : "s"}
        </button>
      ) : null}
    </div>
  );
}
