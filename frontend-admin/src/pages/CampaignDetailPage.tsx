import { useCallback, useEffect, useState } from 'react';
import {
  BadgeDollarSign,
  Bell,
  Calendar,
  ChevronLeft,
  Copy,
  MapPin,
  MousePointerClick,
  Pencil,
  RotateCcw,
  ShoppingBag,
  TicketPercent,
  TriangleAlert,
  UserMinus,
  Users,
  XCircle,
} from 'lucide-react';
import { VerticalBarsChart } from '../components/AnimatedCharts';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { CampaignFunnel } from '../components/marketing/CampaignFunnel';
import { CampaignNotices } from '../components/marketing/CampaignNotices';
import { ChannelPreview } from '../components/marketing/ChannelPreview';
import { SocialReport } from '../components/marketing/SocialReport';
import { getChannel, primaryChannel } from '../components/marketing/channels';
import {
  FALLBACK_ICON,
  GOAL_ICONS,
  statusClass,
  statusLabel,
} from '../components/marketing/meta';
import { formatCompactCurrency, formatCurrency, formatDate } from '../services/api';
import { pluralize } from '../services/format';
import {
  cancelCampaign,
  duplicateCampaign,
  getCampaign,
  sendNow,
  getGoal,
  getOffer,
  getSegment,
  marketingReference,
  subscribeToDemoMode,
} from '../services/marketing/marketingApi';
import type { Campaign } from '../services/marketing/types';

interface CampaignDetailPageProps {
  campaignId: string;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: 'success' | 'error' | 'info',
  ) => void;
}

function branchLabel(branchIds: string[]): string {
  const names = branchIds
    .map((id) => marketingReference.branches.find((branch) => branch.id === id)?.branch_name)
    .filter((name): name is string => Boolean(name));
  return names.length > 0 ? names.join(', ') : 'No branch';
}

interface MetricProps {
  label: string;
  value: string | number;
  hint: string;
  icon: typeof BadgeDollarSign;
}

function Metric({ label, value, hint, icon: Icon }: MetricProps) {
  return (
    <article className="mkt-metric">
      <div className="mkt-metric__top">
        <span aria-hidden="true" className="mkt-metric__icon">
          <Icon size={17} strokeWidth={2.2} />
        </span>
      </div>
      <div>
        <span className="mkt-metric__label">{label}</span>
        <strong className="mkt-metric__value">{value}</strong>
      </div>
      <span className="mkt-metric__hint">{hint}</span>
    </article>
  );
}

export function CampaignDetailPage({
  campaignId,
  onNavigate,
  onToast,
}: CampaignDetailPageProps) {
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [retryOpen, setRetryOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCampaign(await getCampaign(campaignId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'That campaign did not load.');
      setCampaign(null);
    } finally {
      setLoading(false);
    }
  }, [campaignId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => subscribeToDemoMode(() => void load()), [load]);

  const handleDuplicate = async () => {
    if (!campaign) {
      return;
    }
    setBusy(true);
    try {
      const copy = await duplicateCampaign(campaign.id);
      onToast(
        'Campaign duplicated',
        'The copy is a draft, with its audience rebuilt from today.',
        'success',
      );
      onNavigate(`/marketing/campaigns/${copy.id}/edit`);
    } catch (caught) {
      onToast(
        'Duplicate failed',
        caught instanceof Error ? caught.message : 'The copy could not be made.',
        'error',
      );
    } finally {
      setBusy(false);
    }
  };

  /**
   * Send a failed campaign again.
   *
   * The backend has always allowed FAILED -> SENDING and recipient rows make
   * it safe — dispatch skips anyone already reached, so a send that died
   * halfway resumes rather than messaging the first half twice. There was
   * simply no way to ask for it: `canEdit` excludes FAILED, so a campaign
   * that failed offered neither an edit nor a retry and the owner's only
   * route was to duplicate it and lose the report.
   */
  const handleRetry = async () => {
    if (!campaign) {
      return;
    }
    setRetryOpen(false);
    setBusy(true);
    try {
      await sendNow(campaign.id);
      onToast(
        'Sending again',
        'Anyone who already received it is skipped, so nobody gets it twice.',
        'success',
      );
      await load();
    } catch (caught) {
      onToast(
        'Still not sending',
        caught instanceof Error ? caught.message : 'It could not be sent.',
        'error',
      );
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = async () => {
    if (!campaign) {
      return;
    }
    setCancelOpen(false);
    setBusy(true);
    try {
      await cancelCampaign(campaign.id);
      onToast('Campaign cancelled', 'It will not go out.', 'success');
      await load();
    } catch (caught) {
      onToast(
        'Cancel failed',
        caught instanceof Error ? caught.message : 'The campaign could not be cancelled.',
        'error',
      );
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="mkt">
        <div className="mkt-card">
          <span className="mkt-skeleton mkt-skeleton--title" />
          <span className="mkt-skeleton mkt-skeleton--line" />
          <span className="mkt-skeleton mkt-skeleton--block" />
        </div>
      </div>
    );
  }

  if (error || !campaign) {
    return (
      <div className="mkt">
        <button className="mkt-back" onClick={() => onNavigate('/marketing')} type="button">
          <ChevronLeft size={14} strokeWidth={2.5} />
          Marketing
        </button>
        <div className="mkt-empty">
          <span className="mkt-empty__icon">
            <XCircle size={26} strokeWidth={2} />
          </span>
          <strong>This campaign didn't load</strong>
          <p>{error ?? 'That campaign could not be found.'}</p>
          <button
            className="mkt-btn mkt-btn--ghost"
            disabled={loading}
            onClick={() => void load()}
            type="button"
          >
            {loading ? 'Retrying…' : 'Try again'}
          </button>
        </div>
      </div>
    );
  }

  const goal = getGoal(campaign.goal);
  const segment = getSegment(campaign.segment_key);
  const offer = getOffer(campaign.offer_id);
  const attribution = campaign.attribution;
  const delivery = campaign.delivery;
  const GoalIcon = GOAL_ICONS[campaign.goal] ?? FALLBACK_ICON;

  const channel = primaryChannel(campaign.channels);
  // A post and a send are reported differently because they are measured
  // differently. See `SocialReport` — the two numbers are not comparable and
  // presenting them in one funnel would imply they are.
  const social = campaign.social;
  const isSocial = getChannel(channel).family === 'SOCIAL';

  const canCancel = campaign.status === 'SCHEDULED' || campaign.status === 'SENDING';
  const canEdit = campaign.status === 'DRAFT' || campaign.status === 'SCHEDULED';

  return (
    <div className="mkt">
      <button className="mkt-back" onClick={() => onNavigate('/marketing')} type="button">
        <ChevronLeft size={14} strokeWidth={2.5} />
        Marketing
      </button>

      <header className="mkt-hero">
        <div className="mkt-hero__copy">
          <span className="mkt-eyebrow">
            <GoalIcon size={12} strokeWidth={2.6} />
            {goal.label}
          </span>
          <h1 className="mkt-hero__title">{campaign.name}</h1>
          <p className="mkt-hero__lead">
            {segment.name} · {branchLabel(campaign.branch_ids)} ·{' '}
            {getChannel(primaryChannel(campaign.channels)).label}
          </p>
        </div>

        <div className="mkt-hero__actions">
          {canEdit ? (
            <button
              className="mkt-btn mkt-btn--ghost"
              onClick={() => onNavigate(`/marketing/campaigns/${campaign.id}/edit`)}
              type="button"
            >
              <Pencil size={15} strokeWidth={2.3} />
              Edit
            </button>
          ) : null}
          {canCancel ? (
            <button
              className="mkt-btn mkt-btn--ghost"
              disabled={busy}
              onClick={() => setCancelOpen(true)}
              type="button"
            >
              <XCircle size={15} strokeWidth={2.3} />
              Cancel send
            </button>
          ) : null}
          {campaign.status === 'FAILED' ? (
            <button
              className="mkt-btn mkt-btn--primary"
              disabled={busy}
              onClick={() => setRetryOpen(true)}
              type="button"
            >
              <RotateCcw size={15} strokeWidth={2.3} />
              Try again
            </button>
          ) : null}
          <button
            className="mkt-btn mkt-btn--primary"
            disabled={busy}
            onClick={() => void handleDuplicate()}
            type="button"
          >
            <Copy size={15} strokeWidth={2.3} />
            Duplicate
          </button>
        </div>
      </header>

      <section className="mkt-summary">
        <span className={statusClass(campaign.status)}>{statusLabel(campaign.status)}</span>
        <span>
          <Calendar size={13} strokeWidth={2.3} />
          {campaign.sent_at
            ? `Sent ${formatDate(campaign.sent_at)}`
            : campaign.schedule.send_at
              ? `Scheduled for ${formatDate(campaign.schedule.send_at)}`
              : `Last edited ${formatDate(campaign.updated_at)}`}
        </span>
        <span>
          <Users size={13} strokeWidth={2.3} />
          {isSocial
            ? 'Public post — no targeting'
            : `${pluralize(campaign.audience_size, 'person', 'people')} targeted`}
        </span>
        <span>
          <MapPin size={13} strokeWidth={2.3} />
          {branchLabel(campaign.branch_ids)}
        </span>
        <span>
          <TicketPercent size={13} strokeWidth={2.3} />
          {offer ? offer.discount_label : 'No offer'}
        </span>
      </section>

      {campaign.status === 'FAILED' && campaign.last_error ? (
        <CampaignNotices
          notices={[
            {
              id: 'campaign-failed',
              tone: 'block',
              title: 'This campaign did not send',
              description: `${campaign.last_error} You can fix the problem and try again — anyone who already received it will be skipped.`,
            },
          ]}
        />
      ) : null}

      {attribution?.window_open ? (
        <CampaignNotices
          notices={[
            {
              id: 'window-open',
              tone: 'info',
              title: 'Results are still coming in',
              description: `Orders count for ${attribution.window_days} days after sending, so these figures will keep rising. Do not judge it yet.`,
            },
          ]}
        />
      ) : null}

      <section className="mkt-metrics">
        <Metric
          hint={
            attribution
              ? `After ${formatCurrency(attribution.discount_given)} discount`
              : 'No orders attributed yet'
          }
          icon={BadgeDollarSign}
          label="Net revenue"
          value={attribution ? formatCompactCurrency(attribution.net_revenue) : '—'}
        />
        <Metric
          hint={
            !attribution
              ? `${marketingReference.attributionWindowDays}-day window`
              : isSocial
                ? // A post has no "these same customers before the send", so
                  // there is no baseline to compare against and none is shown.
                  'People who typed the code'
                : `vs ${attribution.baseline_orders} in a typical week`
          }
          icon={ShoppingBag}
          label="Orders"
          value={attribution ? attribution.orders : '—'}
        />
        {isSocial ? (
          <>
            <Metric
              hint="Counted by the platform, not by us"
              icon={MousePointerClick}
              label="Times shown"
              value={
                social?.insights?.impressions ??
                social?.insights?.post_impressions ??
                '—'
              }
            />
            <Metric
              hint={
                social?.promo_code
                  ? `Only orders that typed ${social.promo_code}`
                  : 'No code on this post'
              }
              icon={TicketPercent}
              label="Traced by code"
              value={attribution ? attribution.orders : '—'}
            />
          </>
        ) : (
          <>
            <Metric
              hint={
                delivery && delivery.delivered > 0
                  ? `${Math.round((delivery.clicked / delivery.delivered) * 100)}% of delivered`
                  : 'Nothing delivered yet'
              }
              icon={MousePointerClick}
              label="Clicks"
              value={delivery ? delivery.clicked : '—'}
            />
            <Metric
              hint="The cost side of the ledger"
              icon={UserMinus}
              label="Unsubscribed"
              value={delivery ? delivery.unsubscribed : '—'}
            />
          </>
        )}
      </section>

      <div className="mkt-detail">
        <div className="mkt-detail__main">
          <section className="mkt-card">
            <div className="mkt-card__head">
              <span className="mkt-eyebrow">What happened</span>
              <h2 className="mkt-h2">{isSocial ? 'The post' : 'From sent to ordered'}</h2>
              <p className="mkt-sub">
                {isSocial
                  ? 'Where it went up, and what the platform says about it.'
                  : 'Each step is measured against the one above it.'}
              </p>
            </div>

            {isSocial && social ? (
              <SocialReport channel={channel} post={social} />
            ) : delivery ? (
              <CampaignFunnel
                attribution={attribution}
                audienceSize={campaign.audience_size}
                delivery={delivery}
              />
            ) : (
              <div className="mkt-empty">
                <span className="mkt-empty__icon">
                  <Bell size={26} strokeWidth={2} />
                </span>
                <strong>No delivery yet</strong>
                <p>
                  {campaign.status === 'SCHEDULED'
                    ? 'This campaign has not gone out yet. Delivery appears here the moment it starts.'
                    : 'Nothing has been sent from this campaign yet.'}
                </p>
              </div>
            )}
          </section>

          <section className="mkt-card">
            <div className="mkt-card__head">
              <span className="mkt-eyebrow">Revenue</span>
              <h2 className="mkt-h2">Attributed revenue by day</h2>
              <p className="mkt-sub">
                {isSocial
                  ? `Orders that used this post's code, within ${marketingReference.attributionWindowDays} days of it going up. Cancelled orders are excluded, and anyone who ordered without the code is not counted.`
                  : `Orders from people who tapped this campaign, within ${marketingReference.attributionWindowDays} days of it being sent. Cancelled orders are excluded.`}
              </p>
            </div>

            {attribution && attribution.daily.length > 0 ? (
              <>
                <div className="mkt-chart">
                  <VerticalBarsChart
                    className="dashboard-admin-bars"
                    data={attribution.daily.map((day) => ({
                      label: day.label,
                      value: day.revenue,
                      meta: `${day.label} · ${pluralize(day.orders, 'order')}`,
                    }))}
                    valueFormatter={(value) => formatCurrency(value)}
                  />
                </div>

                <dl className="mkt-money">
                  <div>
                    <dt>Revenue</dt>
                    <dd>{formatCurrency(attribution.revenue)}</dd>
                  </div>
                  <div>
                    <dt>Discount given</dt>
                    <dd>−{formatCurrency(attribution.discount_given)}</dd>
                  </div>
                  <div className="mkt-money__total">
                    <dt>Net revenue</dt>
                    <dd>{formatCurrency(attribution.net_revenue)}</dd>
                  </div>
                  <div>
                    <dt>Average order</dt>
                    <dd>{formatCurrency(attribution.average_order_value)}</dd>
                  </div>
                  <div>
                    <dt>Returning</dt>
                    <dd>{attribution.returning_customers}</dd>
                  </div>
                  <div>
                    <dt>New</dt>
                    <dd>{attribution.new_customers}</dd>
                  </div>
                </dl>

                <p className="mkt-field__hint">
                  Attribution shows influence, not proof — some of these customers would
                  have ordered anyway. The comparison against a typical week is the
                  honest read.
                </p>
              </>
            ) : (
              <div className="mkt-empty">
                <span className="mkt-empty__icon">
                  <BadgeDollarSign size={26} strokeWidth={2} />
                </span>
                <strong>No revenue attributed yet</strong>
                <p>
                  {attribution?.window_open
                    ? 'The attribution window has just opened. Orders will appear here as they come in.'
                    : 'Revenue appears here once this campaign has been sent and customers start ordering.'}
                </p>
              </div>
            )}
          </section>

          {campaign.failure_reasons.length > 0 ? (
            <section className="mkt-card">
              <div className="mkt-card__head">
                <span className="mkt-eyebrow">Delivery problems</span>
                <h2 className="mkt-h2">Who did not receive it, and why</h2>
              </div>
              <ul className="mkt-failures">
                {campaign.failure_reasons.map((failure) => (
                  <li key={failure.reason}>
                    <span aria-hidden="true" className="mkt-failures__icon">
                      <TriangleAlert size={15} strokeWidth={2.3} />
                    </span>
                    <span>{failure.reason}</span>
                    <strong>{failure.count}</strong>
                  </li>
                ))}
              </ul>
              <p className="mkt-field__hint">
                Devices that no longer exist are removed from future campaigns
                automatically.
              </p>
            </section>
          ) : null}
        </div>

        <aside className="mkt-detail__rail">
          <section className="mkt-card mkt-card--tight">
            <div className="mkt-card__head">
              <span className="mkt-eyebrow">Message</span>
              <h2 className="mkt-h2">Exactly what went out</h2>
            </div>
            {/* Drawn as whatever it actually was. A campaign that went out on
                Instagram shown as a lock-screen notification would make the
                report describe a send that never happened. */}
            <ChannelPreview
              appName="Spice Route"
              branchName={
                marketingReference.branches.find(
                  (branch) => branch.id === campaign.branch_ids[0],
                )?.branch_name ?? null
              }
              channel={primaryChannel(campaign.channels)}
              content={campaign.content}
              showRecipientSwitcher={false}
            />
            <p className="mkt-field__hint">
              Kept as it was sent, so you can answer a customer asking about it weeks
              later.
            </p>
          </section>

          <section className="mkt-card mkt-card--tight">
            <div className="mkt-card__head">
              <span className="mkt-eyebrow">Setup</span>
              <h2 className="mkt-h2">How it was built</h2>
            </div>
            <dl className="mkt-setup">
              <div>
                <dt>Goal</dt>
                <dd>{goal.label}</dd>
              </div>
              <div>
                <dt>Audience</dt>
                <dd>{segment.name}</dd>
              </div>
              <div>
                <dt>Definition</dt>
                <dd>{segment.definition}</dd>
              </div>
              <div>
                <dt>Branches</dt>
                <dd>{branchLabel(campaign.branch_ids)}</dd>
              </div>
              <div>
                <dt>Where it ran</dt>
                <dd>{getChannel(primaryChannel(campaign.channels)).label}</dd>
              </div>
              <div>
                <dt>Offer</dt>
                <dd>{offer ? `${offer.name} (${offer.discount_label})` : 'None'}</dd>
              </div>
              <div>
                <dt>Measured by</dt>
                <dd>{goal.success_metric}</dd>
              </div>
              <div>
                <dt>Created by</dt>
                <dd>{campaign.created_by}</dd>
              </div>
            </dl>
          </section>
        </aside>
      </div>

      <ConfirmDialog
        busy={busy}
        confirmLabel="Send it again"
        description="Anyone this already reached is skipped, so nobody receives it twice. Whatever stopped it last time will stop it again if it has not been fixed."
        eyebrow="Try again"
        onCancel={() => setRetryOpen(false)}
        onConfirm={() => void handleRetry()}
        open={retryOpen}
        title="Send this campaign again?"
      />

      <ConfirmDialog
        busy={busy}
        confirmLabel="Cancel this send"
        description={`"${campaign.name}" is scheduled for ${
          campaign.schedule.send_at ? formatDate(campaign.schedule.send_at) : 'later'
        }. Cancelling stops it going out. Nothing has been sent yet.`}
        eyebrow="Confirm cancellation"
        onCancel={() => setCancelOpen(false)}
        onConfirm={() => void handleCancel()}
        open={cancelOpen}
        title="Cancel this scheduled campaign?"
        tone="danger"
      />
    </div>
  );
}
