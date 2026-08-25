import { useState } from "react";
import { AlertTriangle, ChevronDown, Info, Minus, TrendingDown, TrendingUp } from "lucide-react";

import { formatCurrency } from "../../services/api";
import { percentIsMisleading } from "../../services/insightFormat";
import type { DiagnosticsSnapshot, MetricDelta, OwnerBriefing } from "../../types/app";

/**
 * The nightly briefing, said rather than displayed.
 *
 * This screen is a conversation, so the analysis is not a panel above the
 * thread - it is the first thing the assistant tells you when you arrive. The
 * figures and the rules behind them are unchanged; only where they sit is.
 */
const MONEY_METRICS = new Set([
  "gross_revenue",
  "average_order_value",
  "item_revenue",
  "cancelled_value",
  "discount_total",
]);

const HEADLINE_METRICS: { metric: string; label: string }[] = [
  { metric: "gross_revenue", label: "Revenue" },
  { metric: "orders", label: "Orders" },
  { metric: "average_order_value", label: "Avg order" },
  { metric: "customers", label: "Customers" },
];

function formatMetric(metric: string, value: number): string {
  if (MONEY_METRICS.has(metric)) {
    return formatCurrency(value);
  }
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value);
}

function MetricTile({ label, delta }: { label: string; delta: MetricDelta }) {
  // A missing baseline is not growth. Showing a green arrow because the previous
  // period was zero invents a comparison that was never made.
  const hasBaseline = delta.percent_change !== null;
  const Icon =
    delta.direction === "up" ? TrendingUp : delta.direction === "down" ? TrendingDown : Minus;

  // A quiet previous period turns an ordinary week into "+2859.6%", which
  // dominates the tile and tells an owner nothing they can act on. The change
  // in money says the same thing truthfully. Same threshold as the backend, so
  // the tile and the briefing headline above it cannot disagree.
  const misleading = percentIsMisleading(delta.previous, delta.percent_change);
  const movement = misleading
    ? formatMetric(delta.metric, Math.abs(delta.absolute_change))
    : `${Math.abs(delta.percent_change ?? 0).toFixed(1)}%`;

  return (
    <article className="ai-tile">
      <span className="ai-tile__label">{label}</span>
      <strong className="ai-tile__value">{formatMetric(delta.metric, delta.current)}</strong>
      {hasBaseline ? (
        <span className={`ai-tile__delta ai-tile__delta--${delta.direction}`}>
          <Icon size={13} strokeWidth={2.4} />
          {movement}
          <em>vs {formatMetric(delta.metric, delta.previous)}</em>
        </span>
      ) : (
        <span className="ai-tile__delta ai-tile__delta--none">no prior period</span>
      )}
    </article>
  );
}

export function BriefingMessage({
  briefing,
  diagnostics,
}: {
  briefing: OwnerBriefing | null;
  diagnostics: DiagnosticsSnapshot | null;
}) {
  const [notesOpen, setNotesOpen] = useState(false);
  const deltas = new Map((diagnostics?.headline ?? []).map((row) => [row.metric, row]));
  const notes = diagnostics?.data_quality.notes ?? [];

  return (
    <div className="ai-said">
      {diagnostics ? (
        <p className="ai-said__period">
          {diagnostics.current_period.label}
          <span> vs {diagnostics.previous_period.label}</span>
        </p>
      ) : null}

      <h2 className="ai-said__headline">
        {briefing ? briefing.headline : "Nothing generated yet"}
      </h2>

      {briefing?.is_stale && briefing.stale_reason ? (
        // An owner reading "Orders are down 53.8%" beside an up week deserves to
        // know which one is describing now.
        <p className="ai-stale" role="status">
          <AlertTriangle size={13} strokeWidth={2.4} />
          {briefing.stale_reason} Pick a period above to see the current picture.
        </p>
      ) : null}

      <p className="ai-said__narrative">
        {briefing
          ? briefing.narrative
          : "Briefings come from the nightly analysis. An administrator can also run it on demand."}
      </p>

      {diagnostics ? (
        <div className="ai-tiles">
          {HEADLINE_METRICS.map(({ metric, label }) => {
            const delta = deltas.get(metric);
            return delta ? <MetricTile delta={delta} key={metric} label={label} /> : null;
          })}
        </div>
      ) : null}

      {diagnostics ? (
        <div className="ai-said__foot">
          <span className="ai-meta">{diagnostics.scope.timezone}</span>
          {notes.length > 0 ? (
            <button
              aria-expanded={notesOpen}
              className={`ai-notes-toggle${notesOpen ? " is-open" : ""}`}
              onClick={() => setNotesOpen((open) => !open)}
              type="button"
            >
              <Info size={12} strokeWidth={2.4} />
              {notes.length} data note{notes.length === 1 ? "" : "s"}
              <ChevronDown size={12} strokeWidth={2.4} />
            </button>
          ) : null}
        </div>
      ) : null}

      {notesOpen ? (
        <ul className="ai-notes">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
