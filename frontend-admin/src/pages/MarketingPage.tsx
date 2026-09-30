import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  BarChart3,
  Bell,
  ChevronLeft,
  ChevronRight,
  Copy,
  FileText,
  History,
  Mail,
  Megaphone,
  MessageCircle,
  Pencil,
  Plug,
  Plus,
  Rocket,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  TicketPercent,
  Trash2,
  TrendingDown,
  TrendingUp,
  Trophy,
  Users,
  Wallet,
  XCircle,
} from 'lucide-react';
import { AreaTrendChart } from '../components/AnimatedCharts';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { DemoStateSelect } from '../components/marketing/DemoStateSelect';
import { FALLBACK_ICON, GOAL_ICONS, statusLabel } from '../components/marketing/meta';
import { RestaurantScopePicker } from '../components/marketing/RestaurantScopePicker';
import { useMarketingScope } from '../hooks/useMarketingScope';
import { formatCompactCurrency, formatCurrency, formatDate } from '../services/api';
import {
  cancelCampaign,
  deleteDraft,
  duplicateCampaign,
  getDashboard,
  getSegment,
  listCampaigns,
  marketingReference,
  subscribeToDemoMode,
} from '../services/marketing/marketingApi';
import type { Campaign, MarketingDashboard } from '../services/marketing/types';

interface MarketingPageProps {
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: 'success' | 'error' | 'info',
  ) => void;
}

/** Rows in the "recent" table before the owner asks for the full list. */
const RECENT_LIMIT = 5;

type TrendWindow = 7 | 14 | 30;

function whenLabel(campaign: Campaign): string {
  if (campaign.sent_at) {
    return formatDate(campaign.sent_at);
  }
  if (campaign.schedule.send_at) {
    return `Goes out ${formatDate(campaign.schedule.send_at)}`;
  }
  return `Edited ${formatDate(campaign.updated_at)}`;
}

/** Percentage change, or null when there is no meaningful base to compare to. */
function deltaPercent(current: number, previous: number): number | null {
  if (previous <= 0) {
    return null;
  }
  return Math.round(((current - previous) / previous) * 100);
}

function DeltaPill({ value }: { value: number }) {
  const tone = value > 0 ? 'up' : value < 0 ? 'down' : 'flat';
  return (
    <span className={`hub-pill hub-pill--${tone}`}>
      {value > 0 ? <TrendingUp size={11} strokeWidth={2.7} /> : null}
      {value < 0 ? <TrendingDown size={11} strokeWidth={2.7} /> : null}
      {value > 0 ? '+' : ''}
      {value}%
    </span>
  );
}

export function MarketingPage({ onNavigate, onToast }: MarketingPageProps) {
  // An owner is pinned to their own restaurant by the backend and must not name
  // one; an admin has no implicit restaurant, so every call they made arrived
  // unscoped and came back `restaurant_id is required for admin insights
  // requests`. That 400 was the whole of "The Marketing Hub didn't load".
  // The scope logic lives in `useMarketingScope` — extracted from here once
  // `ChannelsPage` was written without it and reintroduced the same 400.
  const scope = useMarketingScope();

  const [dashboard, setDashboard] = useState<MarketingDashboard | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [trendWindow, setTrendWindow] = useState<TrendWindow>(7);
  const [flagIndex, setFlagIndex] = useState(0);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Campaign | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Campaign | null>(null);

  // Everything the data layer sends is scoped through the hook's setter, so
  // the campaign editor and the report — neither of which has a picker of
  // its own — read the same restaurant the Hub is showing.
  const scopeReady = scope.ready;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dashboardResponse, campaignResponse] = await Promise.all([
        getDashboard(),
        listCampaigns(),
      ]);
      setDashboard(dashboardResponse);
      setCampaigns(campaignResponse);
      setFlagIndex(0);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'The marketing workspace did not load.',
      );
      setDashboard(null);
      setCampaigns([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Gated on the scope rather than guarded inside `load`: an admin who has not
  // picked a restaurant yet is not loading and not failing, and fetching anyway
  // is what turned "pick a restaurant" into "The Marketing Hub didn't load".
  useEffect(() => {
    if (!scopeReady) {
      return;
    }
    void load();
  }, [load, scopeReady]);

  // Re-fetch when the reviewer switches the demo state, so the loading, empty
  // and error screens are one click apart.
  useEffect(
    () => subscribeToDemoMode(() => {
      if (scopeReady) {
        void load();
      }
    }),
    [load, scopeReady],
  );

  const visible = showAll ? campaigns : campaigns.slice(0, RECENT_LIMIT);

  // The selector is real: the mock carries 30 days and the window slices it,
  // rather than relabelling the same line.
  const trendData = useMemo(() => {
    const trend = dashboard?.revenue_trend ?? [];
    return trend.slice(Math.max(trend.length - trendWindow, 0));
  }, [dashboard, trendWindow]);

  const runAction = async (
    campaign: Campaign,
    action: () => Promise<unknown>,
    successTitle: string,
    successDescription: string,
  ) => {
    setBusyId(campaign.id);
    try {
      await action();
      onToast(successTitle, successDescription, 'success');
      await load();
    } catch (caught) {
      onToast(
        'That did not work',
        caught instanceof Error ? caught.message : 'The action failed.',
        'error',
      );
    } finally {
      setBusyId(null);
    }
  };

  const revenueDelta = dashboard
    ? deltaPercent(
        dashboard.attributed_revenue_30d,
        dashboard.attributed_revenue_previous_30d,
      )
    : null;

  const flags = dashboard?.attention ?? [];
  const flag = flags[Math.min(flagIndex, Math.max(flags.length - 1, 0))];
  const isEmptyWorkspace = !loading && !error && campaigns.length === 0;

  /* Rendered wherever the admin can be looking when the answer matters: the
     working header, the error state a wrong scope produces, and the prompt. */
  const restaurantPicker = <RestaurantScopePicker scope={scope} />;

  /* ------------------------------------------------- nothing chosen yet -- */

  // An admin arrives with no restaurant in mind. Asking is the honest screen:
  // the Hub used to fetch anyway and render the backend's 400 as a failure,
  // which read as "the Marketing Hub is broken" rather than "pick a restaurant".
  if (!scopeReady) {
    return (
      <div className="mkt-hub">
        <section className="hub-card">
          <div className="hub-state">
            <span className="hub-state__icon">
              <Megaphone size={24} strokeWidth={2} />
            </span>
            <strong>Whose marketing?</strong>
            <p>
              {scope.restaurants.length > 0
                ? 'Campaigns, segments and offers all belong to one restaurant. Choose which.'
                : 'No restaurants are available on this account yet.'}
            </p>
            {restaurantPicker}
            <DemoStateSelect />
          </div>
        </section>
      </div>
    );
  }

  /* ------------------------------------------------------------- error -- */

  if (error) {
    return (
      <div className="mkt-hub">
        <section className="hub-card">
          <div className="hub-state">
            <span className="hub-state__icon">
              <XCircle size={24} strokeWidth={2} />
            </span>
            <strong>The Marketing Hub didn't load</strong>
            <p>{error}</p>
            <button
              className="hub-btn hub-btn--primary"
              disabled={loading}
              onClick={() => void load()}
              type="button"
            >
              {loading ? 'Retrying…' : 'Try again'}
            </button>
            {restaurantPicker}
            <DemoStateSelect />
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="mkt-hub">
      {/* ------------------------------------------------ banner + CTA -- */}
      <section className="hub-top">
        <div className="hub-banner">
          <div className="hub-banner__copy">
            <span className="hub-eyebrow">Marketing Hub</span>
            <h1 className="hub-banner__title">
              Reach your customers,
              <em>and see what it earned.</em>
            </h1>
            <p className="hub-banner__lead">
              Create and manage campaigns across multiple channels, and turn your
              customers into loyal regulars.
            </p>
          </div>

          {/* Drawn rather than shipped as an asset — the admin has no image
              pipeline, and a flat illustration would be one more file to keep. */}
          <div aria-hidden="true" className="hub-art">
            <span className="hub-art__disc" />
            <span className="hub-art__horn">
              <Megaphone size={54} strokeWidth={1.6} />
            </span>
            <span className="hub-art__badge hub-art__badge--a">
              <MessageCircle size={15} strokeWidth={2.4} />
            </span>
            <span className="hub-art__badge hub-art__badge--b">
              <Mail size={15} strokeWidth={2.4} />
            </span>
            <span className="hub-art__badge hub-art__badge--c">
              <BarChart3 size={15} strokeWidth={2.4} />
            </span>
          </div>
        </div>

        <div className="hub-launch">
          <button
            className="hub-btn hub-btn--primary hub-btn--block"
            onClick={() => onNavigate('/marketing/campaigns/new')}
            type="button"
          >
            <Plus size={17} strokeWidth={2.6} />
            Create Campaign
            <ArrowRight size={16} strokeWidth={2.4} />
          </button>

          <button
            className="hub-quickstart"
            onClick={() => onNavigate('/marketing/campaigns/new')}
            type="button"
          >
            <span className="hub-chip hub-chip--purple">
              <Sparkles size={17} strokeWidth={2.2} />
            </span>
            <span className="hub-quickstart__copy">
              <strong>Quick start</strong>
              <span>Use a ready-made template to launch your first campaign.</span>
            </span>
            <ChevronRight size={16} strokeWidth={2.3} />
          </button>
        </div>
      </section>

      {/* ------------------------------------------------------- stats -- */}
      <section className="hub-stats">
        <article className="hub-stat">
          <div className="hub-stat__top">
            <span className="hub-chip hub-chip--green">
              <Wallet size={17} strokeWidth={2.2} />
            </span>
            <span className="hub-stat__label">Total Revenue</span>
          </div>
          <span className="hub-stat__value">
            {loading || !dashboard
              ? '—'
              : formatCompactCurrency(dashboard.attributed_revenue_30d)}
            {revenueDelta !== null && !loading ? <DeltaPill value={revenueDelta} /> : null}
          </span>
          <span className="hub-stat__hint">
            {dashboard && !loading
              ? `Last 30 days · was ${formatCompactCurrency(dashboard.attributed_revenue_previous_30d)}`
              : 'Last 30 days'}
          </span>
        </article>

        <article className="hub-stat">
          <div className="hub-stat__top">
            <span className="hub-chip">
              <ShoppingBag size={17} strokeWidth={2.2} />
            </span>
            <span className="hub-stat__label">Orders Attributed</span>
          </div>
          <span className="hub-stat__value">
            {loading || !dashboard ? '—' : dashboard.attributed_orders_30d}
          </span>
          <span className="hub-stat__hint">
            Inside a {marketingReference.attributionWindowDays}-day window
          </span>
        </article>

        <article className="hub-stat">
          <div className="hub-stat__top">
            <span className="hub-chip hub-chip--purple">
              <Users size={17} strokeWidth={2.2} />
            </span>
            <span className="hub-stat__label">Campaigns Sent</span>
          </div>
          <span className="hub-stat__value">
            {loading || !dashboard ? '—' : dashboard.campaigns_sent_30d}
          </span>
          <span className="hub-stat__hint">Last 30 days</span>
        </article>

        <article className="hub-stat">
          <div className="hub-stat__top">
            <span className="hub-chip hub-chip--amber">
              <Trophy size={17} strokeWidth={2.2} />
            </span>
            <span className="hub-stat__label">Best Campaign</span>
          </div>
          <span className="hub-stat__value">
            {loading || !dashboard?.best_campaign
              ? '—'
              : formatCompactCurrency(dashboard.best_campaign.net_revenue)}
          </span>
          <span className="hub-stat__hint">
            {dashboard?.best_campaign?.name ?? 'Nothing sent yet'}
          </span>
        </article>
      </section>

      {/* --------------------------------------------------- attention -- */}
      {flag ? (
        <section className="hub-attention">
          <span className="hub-chip">
            <ShieldCheck size={17} strokeWidth={2.2} />
          </span>
          <div className="hub-attention__copy">
            <strong>What needs your attention</strong>
            <span>
              {flag.title}. {flag.description}
            </span>
          </div>

          {flag.campaign_id ? (
            <button
              className="hub-btn hub-btn--ghost"
              onClick={() => onNavigate(`/marketing/campaigns/${flag.campaign_id}`)}
              type="button"
            >
              View details
              <ArrowRight size={15} strokeWidth={2.3} />
            </button>
          ) : null}

          {flags.length > 1 ? (
            <div className="hub-pager">
              <button
                aria-label="Previous item"
                className="hub-pager__btn"
                disabled={flagIndex === 0}
                onClick={() => setFlagIndex((current) => Math.max(current - 1, 0))}
                type="button"
              >
                <ChevronLeft size={14} strokeWidth={2.4} />
              </button>
              <span>
                {flagIndex + 1}/{flags.length}
              </span>
              <button
                aria-label="Next item"
                className="hub-pager__btn"
                disabled={flagIndex >= flags.length - 1}
                onClick={() =>
                  setFlagIndex((current) => Math.min(current + 1, flags.length - 1))
                }
                type="button"
              >
                <ChevronRight size={14} strokeWidth={2.4} />
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      {/* ------------------------------------------------------- chart -- */}
      <section className="hub-card">
        <header className="hub-panel__head">
          <span className="hub-chip">
            <BarChart3 size={17} strokeWidth={2.2} />
          </span>
          <div className="hub-panel__head-copy">
            <h2 className="hub-title">Revenue from Marketing</h2>
            <p className="hub-sub">
              See how your campaigns are performing and the revenue they bring in.
            </p>
          </div>
          <select
            aria-label="Trend window"
            className="hub-select"
            onChange={(event) => setTrendWindow(Number(event.target.value) as TrendWindow)}
            value={trendWindow}
          >
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>
        </header>

        <div className="hub-chart">
          {loading ? (
            <span className="hub-skeleton" style={{ height: 190 }} />
          ) : trendData.length > 0 ? (
            <AreaTrendChart
              className="dashboard-admin-area-chart"
              data={trendData}
              height={190}
              seriesLabel="Attributed revenue"
              valueFormatter={(value) => formatCurrency(value)}
              yTickFormatter={(value) => formatCompactCurrency(value)}
            />
          ) : (
            <div className="hub-state">
              <span className="hub-state__icon">
                <BarChart3 size={24} strokeWidth={2} />
              </span>
              <strong>Nothing to chart yet</strong>
              <p>Send your first campaign and the revenue it drives appears here.</p>
            </div>
          )}
        </div>
      </section>

      {/* ----------------------------------------------- table + rail -- */}
      <div className="hub-split">
        <section className="hub-card">
          <header className="hub-panel__head">
            <span className="hub-chip">
              <Megaphone size={17} strokeWidth={2.2} />
            </span>
            <div className="hub-panel__head-copy">
              <h2 className="hub-title">
                {showAll ? 'All Campaigns' : 'Recent Campaigns'}
              </h2>
              <p className="hub-sub">Your latest campaigns and their performance.</p>
            </div>
            {!isEmptyWorkspace && !loading ? (
              <button
                className="hub-link"
                onClick={() => setShowAll((current) => !current)}
                type="button"
              >
                {showAll ? 'Show less' : 'View all campaigns'}
                <ArrowRight size={14} strokeWidth={2.4} />
              </button>
            ) : null}
          </header>

          {loading ? (
            <div className="hub-skeleton-stack">
              {[0, 1, 2, 3].map((index) => (
                <span className="hub-skeleton" key={index} style={{ height: 48 }} />
              ))}
            </div>
          ) : isEmptyWorkspace ? (
            <div className="hub-state">
              <span className="hub-state__icon">
                <Megaphone size={24} strokeWidth={2} />
              </span>
              <strong>No campaigns yet</strong>
              <p>
                Pick a goal and we build the audience from your own orders, draft the
                message, and report what it earned.
              </p>
              <button
                className="hub-btn hub-btn--primary"
                onClick={() => onNavigate('/marketing/campaigns/new')}
                type="button"
              >
                <Plus size={16} strokeWidth={2.5} />
                Create your first campaign
              </button>
            </div>
          ) : (
            <div className="hub-table-wrap">
              <table className="hub-table">
                <thead>
                  <tr>
                    <th>Campaign</th>
                    <th>Audience</th>
                    <th>Channel</th>
                    <th>Status</th>
                    <th>Sent</th>
                    <th>Orders</th>
                    <th>Revenue</th>
                    <th>{showAll ? 'Actions' : ''}</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((campaign) => {
                    const Icon = GOAL_ICONS[campaign.goal] ?? FALLBACK_ICON;
                    const segment = getSegment(campaign.segment_key);
                    const canEdit =
                      campaign.status === 'DRAFT' || campaign.status === 'SCHEDULED';

                    return (
                      <tr
                        key={campaign.id}
                        onClick={() => onNavigate(`/marketing/campaigns/${campaign.id}`)}
                      >
                        <td>
                          <span className="hub-cell">
                            <span className="hub-chip hub-chip--sm">
                              <Icon size={14} strokeWidth={2.2} />
                            </span>
                            <span className="hub-cell__copy">
                              <strong>{campaign.name}</strong>
                              <span>{whenLabel(campaign)}</span>
                            </span>
                          </span>
                        </td>

                        <td>
                          <span className="hub-cell__copy hub-cell--stack">
                            <strong>{campaign.audience_size}</strong>
                            <span>{segment.name}</span>
                          </span>
                        </td>

                        <td>
                          <span className="hub-channel">
                            <Bell size={13} strokeWidth={2.3} />
                            Push
                          </span>
                        </td>

                        <td>
                          <span
                            className={`hub-status hub-status--${campaign.status.toLowerCase()}`}
                          >
                            {statusLabel(campaign.status)}
                          </span>
                        </td>

                        <td>{campaign.delivery ? campaign.delivery.sent : '—'}</td>

                        <td>{campaign.attribution ? campaign.attribution.orders : '—'}</td>

                        <td className="hub-money">
                          {campaign.attribution
                            ? formatCurrency(campaign.attribution.net_revenue)
                            : '—'}
                        </td>

                        <td>
                          {showAll ? (
                            <span
                              className="hub-actions-cell"
                              onClick={(event) => event.stopPropagation()}
                              role="presentation"
                            >
                              {canEdit ? (
                                <button
                                  aria-label={`Continue editing ${campaign.name}`}
                                  className="hub-icon-btn"
                                  onClick={() =>
                                    onNavigate(`/marketing/campaigns/${campaign.id}/edit`)
                                  }
                                  title="Continue editing"
                                  type="button"
                                >
                                  <Pencil size={14} strokeWidth={2.2} />
                                </button>
                              ) : null}

                              <button
                                aria-label={`Duplicate ${campaign.name}`}
                                className="hub-icon-btn"
                                disabled={busyId === campaign.id}
                                onClick={() =>
                                  void runAction(
                                    campaign,
                                    () => duplicateCampaign(campaign.id),
                                    'Campaign duplicated',
                                    'The copy is a draft, with its audience rebuilt from today.',
                                  )
                                }
                                title="Duplicate"
                                type="button"
                              >
                                <Copy size={14} strokeWidth={2.2} />
                              </button>

                              {campaign.status === 'SCHEDULED' ? (
                                <button
                                  aria-label={`Cancel ${campaign.name}`}
                                  className="hub-icon-btn hub-icon-btn--danger"
                                  onClick={() => setCancelTarget(campaign)}
                                  title="Cancel send"
                                  type="button"
                                >
                                  <XCircle size={14} strokeWidth={2.2} />
                                </button>
                              ) : null}

                              {campaign.status === 'DRAFT' ? (
                                <button
                                  aria-label={`Delete ${campaign.name}`}
                                  className="hub-icon-btn hub-icon-btn--danger"
                                  onClick={() => setDeleteTarget(campaign)}
                                  title="Delete draft"
                                  type="button"
                                >
                                  <Trash2 size={14} strokeWidth={2.2} />
                                </button>
                              ) : null}
                            </span>
                          ) : (
                            <span aria-hidden="true" className="hub-chevron">
                              <ChevronRight size={16} strokeWidth={2.3} />
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <aside className="hub-side">
          <section className="hub-card">
            <header className="hub-panel__head">
              <span className="hub-chip hub-chip--purple">
                <Sparkles size={17} strokeWidth={2.2} />
              </span>
              <div className="hub-panel__head-copy">
                <h2 className="hub-title">Quick Actions</h2>
              </div>
            </header>

            <div className="hub-quick">
              <button
                className="hub-quick__item"
                onClick={() => onNavigate('/marketing/campaigns/new')}
                type="button"
              >
                <span className="hub-chip">
                  <Plus size={16} strokeWidth={2.4} />
                </span>
                <span className="hub-quick__copy">
                  <strong>Create Campaign</strong>
                  <span>Start a new marketing campaign</span>
                </span>
                <ChevronRight size={15} strokeWidth={2.3} />
              </button>

              {/* The only route to the connect screens. Second rather than
                  buried at the bottom: on a fresh restaurant, "which channels
                  can I even use" is the question that comes before the first
                  campaign, and the builder's Connect panel points here. */}
              <button
                className="hub-quick__item"
                onClick={() => onNavigate('/marketing/channels')}
                type="button"
              >
                <span className="hub-chip hub-chip--purple">
                  <Plug size={16} strokeWidth={2.4} />
                </span>
                <span className="hub-quick__copy">
                  <strong>Set Up Channels</strong>
                  <span>WhatsApp, SMS, email, Instagram, Facebook</span>
                </span>
                <ChevronRight size={15} strokeWidth={2.3} />
              </button>

              <button
                className="hub-quick__item"
                onClick={() => setShowAll(true)}
                type="button"
              >
                <span className="hub-chip hub-chip--purple">
                  <History size={16} strokeWidth={2.4} />
                </span>
                <span className="hub-quick__copy">
                  <strong>View Campaign History</strong>
                  <span>Check all past campaigns</span>
                </span>
                <ChevronRight size={15} strokeWidth={2.3} />
              </button>

              <button
                className="hub-quick__item"
                onClick={() => onNavigate('/offers')}
                type="button"
              >
                <span className="hub-chip hub-chip--amber">
                  <TicketPercent size={16} strokeWidth={2.4} />
                </span>
                <span className="hub-quick__copy">
                  <strong>Manage Offers</strong>
                  <span>Discounts to attach to a campaign</span>
                </span>
                <ChevronRight size={15} strokeWidth={2.3} />
              </button>

              <button
                className="hub-quick__item"
                onClick={() => onNavigate('/reports')}
                type="button"
              >
                <span className="hub-chip hub-chip--green">
                  <FileText size={16} strokeWidth={2.4} />
                </span>
                <span className="hub-quick__copy">
                  <strong>View Reports</strong>
                  <span>Track performance and revenue</span>
                </span>
                <ChevronRight size={15} strokeWidth={2.3} />
              </button>
            </div>
          </section>

          <section className="hub-promo">
            <span aria-hidden="true" className="hub-promo__art">
              <Rocket size={86} strokeWidth={1.2} />
            </span>
            <span className="hub-chip">
              <TrendingUp size={17} strokeWidth={2.2} />
            </span>
            <strong>Grow your restaurant</strong>
            <p>Simple campaigns. Real customers. More orders.</p>
            <button
              className="hub-btn hub-btn--primary"
              onClick={() => onNavigate('/marketing/campaigns/new')}
              type="button"
            >
              Explore Templates
              <ArrowRight size={15} strokeWidth={2.4} />
            </button>
          </section>

          {restaurantPicker}
          <DemoStateSelect />
        </aside>
      </div>

      <ConfirmDialog
        confirmLabel="Cancel this send"
        description={
          cancelTarget
            ? `"${cancelTarget.name}" is scheduled for ${
                cancelTarget.schedule.send_at
                  ? formatDate(cancelTarget.schedule.send_at)
                  : 'later'
              }. Cancelling stops it going out. Nothing has been sent yet.`
            : ''
        }
        eyebrow="Confirm cancellation"
        onCancel={() => setCancelTarget(null)}
        onConfirm={() => {
          const target = cancelTarget;
          setCancelTarget(null);
          if (target) {
            void runAction(
              target,
              () => cancelCampaign(target.id),
              'Campaign cancelled',
              'It will not go out. You can still duplicate it later.',
            );
          }
        }}
        open={Boolean(cancelTarget)}
        title="Cancel this scheduled campaign?"
        tone="danger"
      />

      <ConfirmDialog
        confirmLabel="Delete draft"
        description={
          deleteTarget
            ? `"${deleteTarget.name}" has never been sent. Deleting it cannot be undone.`
            : ''
        }
        eyebrow="Confirm deletion"
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          const target = deleteTarget;
          setDeleteTarget(null);
          if (target) {
            void runAction(
              target,
              () => deleteDraft(target.id),
              'Draft deleted',
              'It has been removed from your campaign list.',
            );
          }
        }}
        open={Boolean(deleteTarget)}
        title="Delete this draft?"
        tone="danger"
      />
    </div>
  );
}
