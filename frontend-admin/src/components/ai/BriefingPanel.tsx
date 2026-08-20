import { useState } from "react";
import { AlertTriangle, ChevronDown, Info, Minus, TrendingDown, TrendingUp } from "lucide-react";

import { formatCurrency } from "../../services/api";
import { percentIsMisleading } from "../../services/insightFormat";
import type { DiagnosticsSnapshot, MetricDelta, OwnerBriefing } from "../../types/app";

interface BriefingPanelProps {
  briefing: OwnerBriefing | null;
  diagnostics: DiagnosticsSnapshot | null;
  loading: boolean;
}

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

export function BriefingPanel({ briefing, diagnostics, loading }: BriefingPanelProps) {
  const [notesOpen, setNotesOpen] = useState(false);

  if (loading) {
    return <section className="ai-card ai-card--loading">Loading briefing…</section>;
  }

  const deltas = new Map((diagnostics?.headline ?? []).map((row) => [row.metric, row]));
  const notes = diagnostics?.data_quality.notes ?? [];

  return (
    <section className="ai-card ai-card--briefing">
      <header className="ai-card__head">
        <div className="ai-card__title">
          <span className="ai-eyebrow">Today's briefing</span>
          <h2>{briefing ? briefing.headline : "Nothing generated yet"}</h2>
        </div>
{/* The provenance badge ("AI wording" / "From data") is gone for the
            same reason it went from the chat: it describes how the sentence was
            produced, which is ours to care about, not the owner's. The figures
            themselves are still on the card. */}
      </header>

      {/* Narrative and figures side by side. Stacked, the prose stops at a
          readable measure and leaves half the card empty beside it; paired, the
          width earns its place and the numbers sit level with the sentences
          that describe them. */}
      {briefing?.is_stale && briefing.stale_reason ? (
        // The card is the loudest thing on the screen, and it had no way to say
        // its headline described a window that ended days ago. An owner reading
        // "Orders are down 53.8%" beside an up week deserves to know which is
        // describing now.
        <p className="ai-stale" role="status">
          <AlertTriangle size={13} strokeWidth={2.4} />
          {briefing.stale_reason} Pick a period above to see the current picture.
        </p>
      ) : null}

      <div className="ai-briefing__body">
        <p className="ai-lede">
          {briefing
            ? briefing.narrative
            : "Briefings come from the nightly analysis. An administrator can also run it on demand."}
        </p>

        {diagnostics ? (
          <div className="ai-tiles">
            {HEADLINE_METRICS.map(({ metric, label }) => {
              const delta = deltas.get(metric);
              return delta ? <MetricTile key={metric} label={label} delta={delta} /> : null;
            })}
          </div>
        ) : null}
      </div>

      {diagnostics ? (
        <>
          <footer className="ai-card__foot">
            <span className="ai-meta">
              {diagnostics.current_period.label} vs {diagnostics.previous_period.label}
              <em> · {diagnostics.scope.timezone}</em>
            </span>

            {notes.length > 0 ? (
              <button
                type="button"
                className={`ai-notes-toggle${notesOpen ? " is-open" : ""}`}
                onClick={() => setNotesOpen((open) => !open)}
                aria-expanded={notesOpen}
              >
                <Info size={12} strokeWidth={2.4} />
                {notes.length} data note{notes.length === 1 ? "" : "s"}
                <ChevronDown size={12} strokeWidth={2.4} />
              </button>
            ) : null}
          </footer>

          {notesOpen ? (
            <ul className="ai-notes">
              {notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
