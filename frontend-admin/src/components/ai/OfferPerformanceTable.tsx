import { formatCurrency } from "../../services/api";
import type { OfferPerformanceRow, OfferPerformanceSnapshot } from "../../types/app";
import { ResponsiveTable, type TableColumn } from "../ResponsiveTable";

interface OfferPerformanceTableProps {
  snapshot: OfferPerformanceSnapshot | null;
  loading: boolean;
}

const COLUMNS: Array<TableColumn<OfferPerformanceRow>> = [
  {
    id: "offer",
    header: "Offer",
    render: (row) => (
      <div className="ai-offer-cell">
        <strong>{row.offer_name}</strong>
        <span className="ai-chip">{row.offer_kind}</span>
      </div>
    ),
  },
  {
    id: "orders",
    header: "Orders",
    align: "right",
    render: (row) => row.orders,
  },
  {
    id: "revenue",
    header: "Revenue",
    align: "right",
    render: (row) => formatCurrency(row.gross_revenue),
  },
  {
    id: "discount",
    header: "Discount cost",
    align: "right",
    render: (row) => formatCurrency(row.discount_cost),
    hideOnMobile: true,
  },
  {
    id: "net",
    header: "Net revenue",
    align: "right",
    render: (row) => formatCurrency(row.net_revenue),
  },
  {
    id: "ratio",
    header: "Return per unit discount",
    align: "right",
    hideOnMobile: true,
    // No ratio is shown when nothing was discounted, rather than an invented one.
    render: (row) =>
      row.return_per_unit_discount === null
        ? "—"
        : `${row.return_per_unit_discount.toFixed(1)}×`,
  },
];

export function OfferPerformanceTable({ snapshot, loading }: OfferPerformanceTableProps) {
  const offers = snapshot?.offers ?? [];

  return (
    <section className="ai-card">
      <header className="ai-card__head">
        <div className="ai-card__title">
          <span className="ai-eyebrow">Offer performance</span>
          <h2>
            {offers.length === 0
              ? "No offers used yet"
              : `${offers.length} offer${offers.length === 1 ? "" : "s"} with orders`}
          </h2>
        </div>
        {snapshot ? <span className="ai-meta">{snapshot.period.label}</span> : null}
      </header>

      <ResponsiveTable
        rows={offers}
        columns={COLUMNS}
        keyExtractor={(row) => row.offer_id}
        loading={loading}
        emptyTitle="Nothing to measure"
        emptyDescription="No orders in this period were placed with an offer. Once customers order using one, its revenue and discount cost appear here."
        mobileTitle={(row) => row.offer_name}
        mobileSubtitle={(row) => `${row.orders} orders · ${formatCurrency(row.gross_revenue)}`}
      />

      {offers.length > 0 ? (
        <p className="ai-footnote">
          Net revenue is revenue after the discount, not profit: food and delivery costs are not
          recorded anywhere in the platform.
        </p>
      ) : null}
    </section>
  );
}
