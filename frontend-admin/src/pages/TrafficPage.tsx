import { Eye, MonitorSmartphone, Radio, ShoppingBag, UserPlus, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { AreaTrendChart, VerticalBarsChart } from "../components/AnimatedCharts";
import { EmptyPanel } from "../components/EmptyPanel";
import { PageIntro } from "../components/PageIntro";
import { ResponsiveTable, type TableColumn } from "../components/ResponsiveTable";
import { StatTiles, type StatTileItem } from "../components/StatTiles";
import { useAdminStore } from "../hooks/useAdminStore";
import { ApiError, api } from "../services/api";
import { busiestHours, dailyChart, hourChart, percentText, versusYesterday } from "../services/traffic";
import type { TrafficOverview, TrafficOverviewRow, TrafficSummary } from "../types/app";

interface TrafficPageProps {
  token: string;
}

/** Online now changes by the minute; the page follows it without a reload. */
const REFRESH_MS = 30_000;

/** Calls `load` now and every REFRESH_MS while the tab is visible. */
function useRefreshing(load: () => void, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return undefined;
    load();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [enabled, load]);
}

/**
 * Who is on each restaurant's website right now, and how many came.
 *
 * Counted by the server from the storefront's heartbeat
 * (`backend/app/services/traffic.py`): one visitor per browser per day,
 * robots and local testing left out. The platform admin sees every
 * restaurant and can open any one; an owner sees their own, and the server
 * refuses them anything else.
 */
export function TrafficPage({ token }: TrafficPageProps) {
  const { role, activeRestaurantId } = useAdminStore();
  const isAdmin = role === "ADMIN";
  const [overview, setOverview] = useState<TrafficOverview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  // What this page's table last opened, and which sidebar restaurant was
  // chosen when it did. The sidebar switcher scopes the whole panel, so
  // choosing a different restaurant there wins over an older click here.
  const [picked, setPicked] = useState<{ id: string; under: string | null } | null>(null);
  const selected = isAdmin
    ? picked && picked.under === activeRestaurantId
      ? picked.id
      : activeRestaurantId
    : null;
  const setSelected = (id: string) => setPicked({ id, under: activeRestaurantId });

  const loadOverview = useCallback(() => {
    api
      .getTrafficOverview(token)
      .then((next) => {
        setOverview(next);
        setOverviewError(null);
      })
      .catch((error: unknown) => setOverviewError(error instanceof ApiError ? error.message : "Please try again."));
  }, [token]);
  useRefreshing(loadOverview, isAdmin);

  const selectedName = overview?.restaurants.find((row) => row.restaurant_id === selected)?.restaurant_name;

  const columns: Array<TableColumn<TrafficOverviewRow>> = [
    { id: "restaurant", header: "Restaurant", render: (row) => <strong>{row.restaurant_name}</strong> },
    {
      id: "online",
      header: "Online now",
      align: "right",
      mobileLabel: "Online now",
      render: (row) => (
        <span className={row.online_now > 0 ? "traffic-online traffic-online--live" : "traffic-online"}>
          {row.online_now}
        </span>
      ),
    },
    {
      id: "today",
      header: "Visitors today",
      align: "right",
      mobileLabel: "Visitors today",
      render: (row) => <strong>{row.visitors_today}</strong>,
    },
    {
      id: "trend",
      header: "Compared",
      mobileLabel: "Compared",
      hideOnMobile: true,
      render: (row) => versusYesterday(row.visitors_today, row.visitors_yesterday) ?? "—",
    },
    { id: "ordered", header: "Ordered", align: "right", mobileLabel: "Ordered", render: (row) => row.ordered_today },
    {
      id: "conversion",
      header: "Conversion",
      align: "right",
      mobileLabel: "Conversion",
      render: (row) => percentText(row.conversion_percent),
    },
  ];

  return (
    <div className="page-stack">
      <PageIntro
        description={
          isAdmin
            ? "Who is on each restaurant's website right now, and how many people visited today. Refreshes every 30 seconds."
            : "Who is on your website right now, and how many people visited today. Refreshes every 30 seconds."
        }
        eyebrow={isAdmin ? "Platform" : "Insights"}
        title="Traffic"
      />

      {isAdmin ? (
        <section className="admin-surface">
          <div className="admin-surface__header">
            <div>
              <span className="eyebrow">All restaurants</span>
              <h2>Today, by restaurant</h2>
            </div>
          </div>
          {overviewError && !overview ? (
            <EmptyPanel
              action={
                <button className="primary-button" onClick={loadOverview} type="button">
                  Try again
                </button>
              }
              description={overviewError}
              title="Traffic didn't load"
            />
          ) : (
            <ResponsiveTable
              actions={[{ id: "open", label: "See details", icon: Eye, onClick: (row) => setSelected(row.restaurant_id) }]}
              columns={columns}
              emptyDescription="Restaurants appear here as soon as they exist; visitors are counted from their websites."
              emptyTitle="No restaurants yet"
              keyExtractor={(row) => row.restaurant_id}
              loading={!overview}
              mobileTitle={(row) => row.restaurant_name}
              rows={overview?.restaurants ?? []}
            />
          )}
        </section>
      ) : null}

      {isAdmin && !selected ? null : (
        <RestaurantTraffic
          // Remounted per restaurant, so one restaurant's numbers never sit
          // under another's name while its own are on the way.
          key={selected ?? "own"}
          heading={isAdmin ? (selectedName ?? "Restaurant") : "Your website"}
          restaurantId={isAdmin ? selected : null}
          token={token}
        />
      )}

      <small className="hint-text">
        Counted from the restaurant&rsquo;s own website. One browser is one visitor a day, however many times it
        reloads or how many tabs it opens; robots, link previews and test traffic are left out. &ldquo;Ordered&rdquo;
        is a visitor signed in to the website whose account placed an order that day.
      </small>
    </div>
  );
}

function RestaurantTraffic({
  token,
  restaurantId,
  heading,
}: {
  token: string;
  restaurantId: string | null;
  heading: string;
}) {
  const [summary, setSummary] = useState<TrafficSummary | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .getTrafficSummary(token, restaurantId)
      .then((next) => {
        setSummary(next);
        setFailed(null);
      })
      .catch((error: unknown) => setFailed(error instanceof ApiError ? error.message : "Please try again."));
  }, [restaurantId, token]);

  useRefreshing(load, true);

  if (failed && !summary) {
    return (
      <section className="admin-surface">
        <EmptyPanel
          action={
            <button className="primary-button" onClick={load} type="button">
              Try again
            </button>
          }
          description={failed}
          title="Traffic didn't load"
        />
      </section>
    );
  }

  const today = summary?.today;
  const yesterday = summary?.daily.at(-2)?.visitors ?? 0;
  const tiles: StatTileItem[] = [
    {
      key: "online",
      label: "Online now",
      icon: Radio,
      value: summary?.online_now ?? 0,
      hint: "On the website in the last 2 minutes",
      isStatic: true,
    },
    {
      key: "visitors",
      label: "Visitors today",
      icon: Users,
      value: today?.visitors ?? 0,
      hint: versusYesterday(today?.visitors ?? 0, yesterday) ?? "Unique people, not page views",
      isStatic: true,
    },
    {
      key: "ordered",
      label: "Visitors who ordered",
      icon: ShoppingBag,
      value: today?.ordered ?? 0,
      hint: `${percentText(today?.conversion_percent ?? null)} conversion · ${today?.orders ?? 0} orders today in all`,
      isStatic: true,
    },
    {
      key: "new",
      label: "New visitors",
      icon: UserPlus,
      value: today?.new ?? 0,
      hint: `${today?.returning ?? 0} came back from an earlier day`,
      isStatic: true,
    },
    {
      key: "devices",
      label: "On a phone",
      icon: MonitorSmartphone,
      value: today?.devices.phone ?? 0,
      hint: `${today?.devices.desktop ?? 0} on a computer · ${today?.devices.tablet ?? 0} on a tablet`,
      isStatic: true,
    },
  ];
  const peak = summary ? busiestHours(summary.hours) : null;

  return (
    <>
      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Today</span>
            <h2>{heading}</h2>
          </div>
        </div>
        <StatTiles ariaLabel={`Traffic today for ${heading}`} loading={!summary} tiles={tiles} />
      </section>

      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Last 30 days</span>
            <h2>Daily visitors</h2>
          </div>
        </div>
        {summary ? (
          <AreaTrendChart className="dashboard-admin-area-chart" data={dailyChart(summary.daily)} seriesLabel="Visitors" />
        ) : (
          <p className="hint-text">Loading…</p>
        )}
      </section>

      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Last 7 days</span>
            <h2>Busiest hours</h2>
            <p className="hint-text">{peak ? `Most visitors: ${peak}.` : "No visitors in the last 7 days yet."}</p>
          </div>
        </div>
        {summary ? <VerticalBarsChart className="dashboard-admin-bars" data={hourChart(summary.hours)} /> : null}
      </section>
    </>
  );
}
