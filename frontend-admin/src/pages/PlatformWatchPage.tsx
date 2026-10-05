import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  CircleX,
  Info,
  RefreshCw,
  Store,
} from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyPanel } from "../components/EmptyPanel";
import { PageIntro } from "../components/PageIntro";
import { ResponsiveTable, type TableColumn } from "../components/ResponsiveTable";
import { useMoney } from "../hooks/useMoney";
import { ApiError, api } from "../services/api";
import {
  SEVERITY_LABEL,
  issuesBySeverity,
  overallVerdict,
  verdictHeadline,
} from "../services/platformWatch";
import type {
  PlatformCheck,
  PlatformIssue,
  PlatformRestaurantToday,
  PlatformWatch,
} from "../types/app";

interface PlatformWatchPageProps {
  token: string;
  onNavigate: (path: string) => void;
}

/** Every minute: fast enough to see a stuck order, slow enough to be cheap. */
const REFRESH_MS = 60_000;

const CHECK_ICON = { ok: CheckCircle2, warn: CircleAlert, down: CircleX } as const;
const SEVERITY_ICON = { high: CircleX, medium: AlertTriangle, low: Info } as const;

/**
 * Is anything wrong, anywhere on the platform?
 *
 * The admin could already see every restaurant, order and user, one screen
 * at a time, and still not answer that. This page asks every question at
 * once - is the machinery up, what needs a person, how is each restaurant
 * doing today - and links each answer to the screen where it is fixed. The
 * rules live in `backend/app/services/platform_watch.py`.
 */
export function PlatformWatchPage({ token, onNavigate }: PlatformWatchPageProps) {
  const money = useMoney();
  const [watch, setWatch] = useState<PlatformWatch | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let current = true;
    const load = () =>
      api
        .getPlatformWatch(token)
        .then((next) => {
          if (!current) return;
          setWatch(next);
          setFailed(null);
        })
        .catch((error: unknown) => {
          if (!current) return;
          setFailed(error instanceof ApiError ? error.message : "Please try again.");
        })
        .finally(() => {
          if (current) setRefreshing(false);
        });
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [attempt, token]);

  const refresh = () => {
    setRefreshing(true);
    setAttempt((count) => count + 1);
  };

  const verdict = overallVerdict(watch);
  const VerdictIcon = CHECK_ICON[verdict];
  const groups = issuesBySeverity(watch?.issues ?? []);
  const updated = watch
    ? new Date(watch.generated_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : null;

  const columns: Array<TableColumn<PlatformRestaurantToday>> = [
    {
      id: "restaurant",
      header: "Restaurant",
      render: (row) => (
        <>
          <strong>{row.name}</strong>
          <span>
            {row.city}
            {!row.approved ? " · awaiting approval" : ""}
            {row.storefront && row.storefront !== "ACTIVE" ? ` · storefront ${row.storefront.toLowerCase()}` : ""}
          </span>
        </>
      ),
    },
    {
      id: "branches",
      header: "Open now",
      render: (row) => `${row.branches_open} of ${row.branches}`,
      mobileLabel: "Branches open",
      align: "right",
    },
    {
      id: "orders",
      header: "Orders today",
      render: (row) => row.orders_today,
      mobileLabel: "Orders today",
      align: "right",
    },
    {
      id: "sales",
      header: "Sales today",
      render: (row) => money.format(Number(row.sales_today), row.restaurant_id),
      mobileLabel: "Sales today",
      align: "right",
    },
    {
      id: "waiting",
      header: "To accept",
      render: (row) =>
        row.awaiting_accept > 0 ? (
          <span className="pw-badge pw-badge--warn">{row.awaiting_accept} waiting</span>
        ) : (
          "—"
        ),
      mobileLabel: "Waiting to be accepted",
      align: "right",
    },
    {
      id: "stock",
      header: "Out of stock",
      render: (row) => (row.out_of_stock > 0 ? row.out_of_stock : "—"),
      mobileLabel: "Dishes out of stock",
      align: "right",
    },
    {
      id: "issues",
      header: "Problems",
      render: (row) =>
        row.issues > 0 ? (
          <span className="pw-badge pw-badge--down">
            {row.issues} problem{row.issues === 1 ? "" : "s"}
          </span>
        ) : (
          <span className="pw-badge pw-badge--ok">OK</span>
        ),
      mobileLabel: "Problems",
      align: "right",
    },
  ];

  return (
    <div className="page-stack">
      <PageIntro
        actions={
          <button className="secondary-button" disabled={refreshing} onClick={refresh} type="button">
            <RefreshCw aria-hidden="true" size={15} />
            {refreshing ? "Checking…" : "Check now"}
          </button>
        }
        description="Is the platform running, and does any restaurant need you? Checked every minute."
        eyebrow="Platform"
        help="platform-watch"
        title="Platform watch"
      />

      {failed && !watch ? (
        <section className="admin-surface">
          <EmptyPanel
            action={
              <button className="primary-button" onClick={refresh} type="button">
                Try again
              </button>
            }
            description={failed}
            title="Platform watch didn't load"
          />
        </section>
      ) : (
        <>
          <section aria-live="polite" className={`pw-verdict pw-verdict--${verdict}`}>
            <VerdictIcon aria-hidden="true" size={22} />
            <div>
              <strong>{verdictHeadline(watch)}</strong>
              <span>
                {updated ? `Last checked at ${updated}.` : "Running the checks."}
                {failed ? ` The latest check failed: ${failed}` : ""}
              </span>
            </div>
          </section>

          <section aria-label="System health" className="pw-checks">
            {(watch?.checks ?? []).map((check: PlatformCheck) => {
              const Icon = CHECK_ICON[check.status];
              return (
                <article className={`pw-check pw-check--${check.status}`} key={check.key}>
                  <header>
                    <Icon aria-hidden="true" size={16} />
                    <strong>{check.label}</strong>
                  </header>
                  <p>{check.detail}</p>
                  {check.hint ? <p className="pw-check__hint">{check.hint}</p> : null}
                </article>
              );
            })}
          </section>

          <section aria-label="Needs attention" className="admin-surface pw-issues">
            <header className="pw-section-head">
              <h2>Needs attention</h2>
              <span>{watch ? `${watch.issues.length} across all restaurants` : ""}</span>
            </header>
            {watch && watch.issues.length === 0 ? (
              <p className="pw-empty">
                <CheckCircle2 aria-hidden="true" size={16} />
                Nothing needs you right now.
              </p>
            ) : null}
            {(["high", "medium", "low"] as const).map((severity) =>
              groups[severity].length > 0 ? (
                <div className={`pw-group pw-group--${severity}`} key={severity}>
                  <h3>{SEVERITY_LABEL[severity]}</h3>
                  <ul>
                    {groups[severity].map((issue: PlatformIssue, index) => {
                      const Icon = SEVERITY_ICON[issue.severity];
                      return (
                        <li className="pw-issue" key={`${issue.key}-${issue.restaurant_id}-${issue.location_id}-${index}`}>
                          <Icon aria-hidden="true" className="pw-issue__icon" size={16} />
                          <div className="pw-issue__copy">
                            <strong>
                              {issue.restaurant_name ? <em>{issue.restaurant_name}</em> : null}
                              {issue.title}
                            </strong>
                            <span>{issue.detail}</span>
                          </div>
                          {issue.link ? (
                            <button
                              className="secondary-button secondary-button--ghost pw-issue__go"
                              onClick={() => onNavigate(issue.link as string)}
                              type="button"
                            >
                              Open
                              <ArrowRight aria-hidden="true" size={14} />
                            </button>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ) : null,
            )}
          </section>

          <section className="admin-surface">
            <header className="pw-section-head">
              <h2>Restaurants today</h2>
              <span>Problems first, then the busiest</span>
            </header>
            <ResponsiveTable
              actions={[
                {
                  id: "open",
                  label: "Open restaurant",
                  icon: Store,
                  onClick: (row) => onNavigate(`/admin/restaurants/${row.restaurant_id}`),
                },
              ]}
              columns={columns}
              emptyDescription="Restaurants appear here once they are onboarded."
              emptyTitle="No restaurants yet"
              keyExtractor={(row) => row.restaurant_id}
              loading={!watch}
              mobileTitle={(row) => row.name}
              rows={watch?.restaurants ?? []}
            />
          </section>
        </>
      )}
    </div>
  );
}
