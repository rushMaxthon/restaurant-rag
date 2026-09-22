import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Ban,
  Check,
  ChevronLeft,
  Clock,
  MapPin,
  Save,
  Send,
  Smartphone,
  Sparkles,
} from 'lucide-react';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { CampaignNotices } from '../components/marketing/CampaignNotices';
import { ChannelPicker } from '../components/marketing/ChannelPicker';
import { ChannelPreview } from '../components/marketing/ChannelPreview';
import { ContentStep } from '../components/marketing/ContentStep';
import { contentBlocker } from '../components/marketing/contentRules';
import { useAdminStore } from '../hooks/useAdminStore';
import { ReachSummary } from '../components/marketing/ReachSummary';
import { ReviewStep } from '../components/marketing/ReviewStep';
import { SocialAudienceStep } from '../components/marketing/SocialAudienceStep';
import { WizardSteps, type WizardStep } from '../components/marketing/WizardSteps';
import { hasBlockingNotice } from '../components/marketing/noticeUtils';
import {
  estimateSpend,
  getChannel,
  goalFitsChannel,
  primaryChannel,
} from '../components/marketing/channels';
import { FALLBACK_ICON, GOAL_ICONS, SEGMENT_ICONS } from '../components/marketing/meta';
import { formatCurrency, formatDate } from '../services/api';
import { pluralize } from '../services/format';
import {
  createDraftId,
  ensureReference,
  estimateReach,
  listChannels,
  getCampaign,
  getGoal,
  getOffer,
  getSegment,
  marketingReference,
  saveDraft,
  scheduleCampaign,
  sendNow,
  sendTest,
  templatesForGoal,
} from '../services/marketing/marketingApi';
import type {
  Campaign,
  CampaignContentExtra,
  CampaignDraft,
  CampaignGoalKey,
  ChannelConnection,
  MarketingChannel,
  ReachEstimate,
  SegmentKey,
} from '../services/marketing/types';

interface CampaignEditorPageProps {
  /** Null when creating. Otherwise the draft or scheduled campaign to resume. */
  campaignId: string | null;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: 'success' | 'error' | 'info',
  ) => void;
}

/**
 * Six questions, in the order an owner would ask them of themselves.
 *
 * "Where" is first because it decides the other five: the goals on offer, the
 * shape of the audience question, which content fields exist, what the preview
 * looks like and whether the button says Send or Post. The old flow asked it
 * fourth, after three steps of work that assumed push.
 *
 * The labels are the questions, not the nouns. "Audience" and "Content" are
 * what we call these things; "Who" and "Words" is what they are.
 */
const STEPS: WizardStep[] = [
  { id: 1, label: 'Where' },
  { id: 2, label: 'Why' },
  { id: 3, label: 'Who' },
  { id: 4, label: 'Words' },
  { id: 5, label: 'When' },
  { id: 6, label: 'Ready' },
];

const STEP_CHANNEL = 1;
const STEP_GOAL = 2;
const STEP_AUDIENCE = 3;
const STEP_CONTENT = 4;
const STEP_SCHEDULE = 5;
const STEP_REVIEW = 6;

/**
 * A blank campaign, built without touching reference data.
 *
 * This runs synchronously at mount, before `/reference` has answered, so
 * anything it reads from `marketingReference` is whatever the module happens
 * to hold at that instant. It used to seed `branch_ids` from there and picked
 * up the mock branches, which the backend rejects as invalid UUIDs — a new
 * campaign could not be saved at all. Branches, the name and the timezone are
 * filled in by the hydrate effect once the real data lands.
 *
 * `channel` starts as PUSH rather than null even though the first screen asks
 * for it: a null channel would mean every reader below needs a null branch,
 * and the screen is a choice between six values, not a choice about whether to
 * choose. Nothing is saved until the owner leaves that screen anyway.
 */
function emptyDraft(): CampaignDraft {
  const goal = getGoal('WINBACK');
  return {
    id: createDraftId(),
    name: '',
    channel: 'PUSH',
    goal: goal.key,
    segment_key: goal.default_segment,
    branch_ids: [],
    offer_id: null,
    content: {
      title: '',
      body: '',
      deep_link: 'RESTAURANT_HOME',
      template_id: null,
      extra: {},
    },
    schedule: { mode: 'NOW', send_at: null, timezone: marketingReference.timezone },
    last_step: STEP_CHANNEL,
  };
}

/**
 * The draft as it goes to the server.
 *
 * `persist` runs on every step change, so a fast click can beat the reference
 * load and send a draft nothing has filled in yet. Three fields would fail
 * validation for that reason — the backend requires a name, a title and a body
 * of at least one character each, because a campaign has to be findable and a
 * push has to say something. Defaulting them here rather than blocking the
 * save is what lets an owner step away from step 2 without losing the draft;
 * before this the very first Continue answered "Draft not saved".
 *
 * The placeholders are deliberately the goal's own words, so a draft resumed
 * from the campaign list reads as what it was going to be rather than as
 * "Untitled".
 */
function forSaving(draft: CampaignDraft): CampaignDraft {
  const goal = getGoal(draft.goal);
  const name = draft.name.trim() || goal.label;
  // The same template step 4 would have offered, so a draft resumed later
  // reads as a starting point rather than as something already written.
  const starter = templatesForGoal(draft.goal).find(
    (entry) => entry.channel === draft.channel,
  );
  return {
    ...draft,
    name,
    content: {
      ...draft.content,
      title: draft.content.title.trim() || starter?.title || name,
      body: draft.content.body.trim() || starter?.body || goal.description,
    },
  };
}

function campaignToDraft(campaign: Campaign): CampaignDraft {
  return {
    id: campaign.id,
    name: campaign.name,
    channel: primaryChannel(campaign.channels),
    goal: campaign.goal,
    segment_key: campaign.segment_key,
    branch_ids: [...campaign.branch_ids],
    offer_id: campaign.offer_id,
    content: { ...campaign.content, extra: { ...(campaign.content.extra ?? {}) } },
    schedule: { ...campaign.schedule },
    // `Campaign` does not carry the saved step — the response schema has never
    // returned it — so a resumed draft opens at the start with every step
    // already unlocked, which is what `setFurthest(STEP_REVIEW)` does below.
    last_step: STEP_CHANNEL,
  };
}

/** `datetime-local` wants local wall-clock text, not an ISO instant. */
function toLocalInput(iso: string | null): string {
  if (!iso) {
    return '';
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

function fromLocalInput(value: string): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function CampaignEditorPage({
  campaignId,
  onNavigate,
  onToast,
}: CampaignEditorPageProps) {
  // The signed-in staff member, because a test send goes to *their* address
  // rather than to the one the channel sends from.
  const { user: currentUser } = useAdminStore();
  const [draft, setDraft] = useState<CampaignDraft>(() => emptyDraft());
  const [step, setStep] = useState(STEP_CHANNEL);
  const [furthest, setFurthest] = useState(STEP_CHANNEL);
  const [loading, setLoading] = useState(Boolean(campaignId));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reach, setReach] = useState<ReachEstimate | null>(null);
  const [reachLoading, setReachLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);
  const [testing, setTesting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  /** The channel a switch would throw away work on, or null. */
  const [channelSwitch, setChannelSwitch] = useState<MarketingChannel | null>(null);
  /**
   * What this restaurant has actually connected.
   *
   * Null while it loads. Availability used to be a constant in the channel
   * registry that could only ever say "not connected yet" — so a channel the
   * owner HAD connected still rendered as unavailable and still refused to
   * send. It is a fact about the restaurant, so it comes from the server.
   */
  const [connections, setConnections] = useState<Map<MarketingChannel, ChannelConnection> | null>(
    null,
  );
  /**
   * Why we could not read the channel list, if we could not.
   *
   * Kept rather than swallowed. The catch used to set an empty map, which
   * renders every channel — including push, which is always on — as "needs
   * setup". That is the same mistake as rendering a 400 as "the Hub is
   * broken": it tells the owner six things are wrong with their account when
   * the truth is that we failed to ask.
   */
  const [connectionsError, setConnectionsError] = useState<string | null>(null);

  const channel = getChannel(draft.channel);
  const isSocial = channel.family === 'SOCIAL';
  const goal = getGoal(draft.goal);
  const segment = getSegment(draft.segment_key);
  const offer = getOffer(draft.offer_id);

  /** Only the templates that were written for this channel and this goal. */
  const templates = useMemo(
    () => templatesForGoal(draft.goal).filter((entry) => entry.channel === draft.channel),
    [draft.channel, draft.goal],
  );

  /** Goals this channel can honestly deliver. See `channels.ts`. */
  const goals = useMemo(
    () => marketingReference.goals.filter((entry) => goalFitsChannel(channel, entry.key)),
    [channel],
  );

  const primaryBranchName = useMemo(() => {
    const first = draft.branch_ids[0];
    return first
      ? (marketingReference.branches.find((branch) => branch.id === first)?.branch_name ??
          null)
      : null;
  }, [draft.branch_ids]);

  /* ---------------------------------------------------------------- load -- */

  const load = useCallback(async () => {
    if (!campaignId) {
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const campaign = await getCampaign(campaignId);
      if (campaign.status !== 'DRAFT' && campaign.status !== 'SCHEDULED') {
        setLoadError('This campaign has already been sent and can no longer be edited.');
        return;
      }
      setDraft(campaignToDraft(campaign));
      // The channel is already chosen, so reopening on the screen that asks
      // for it would be a question with an answer. Every step is unlocked,
      // and the badge beside the rail goes back to it in one click.
      setStep(STEP_GOAL);
      setFurthest(STEP_REVIEW);
    } catch (caught) {
      setLoadError(
        caught instanceof Error ? caught.message : 'That campaign could not be opened.',
      );
    } finally {
      setLoading(false);
    }
  }, [campaignId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    void listChannels()
      .then((rows) => {
        if (!cancelled) {
          setConnections(new Map(rows.map((row) => [row.channel, row])));
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setConnections(new Map());
          setConnectionsError(
            caught instanceof Error ? caught.message : 'We could not check your channels.',
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Fill in what a blank draft could not know at mount. Guarded on "still
  // empty" so it can never overwrite something the owner typed, and skipped
  // for an existing campaign, whose values came from the server.
  useEffect(() => {
    if (campaignId) {
      return;
    }
    let cancelled = false;
    void ensureReference()
      .then(() => {
        if (cancelled) {
          return;
        }
        setDraft((current) => {
          const active = marketingReference.branches
            .filter((branch) => branch.is_active)
            .map((branch) => branch.id);
          if (current.branch_ids.length > 0 || active.length === 0) {
            return {
              ...current,
              schedule: { ...current.schedule, timezone: marketingReference.timezone },
            };
          }
          return {
            ...current,
            branch_ids: active,
            schedule: { ...current.schedule, timezone: marketingReference.timezone },
          };
        });
      })
      .catch(() => {
        // The reach panel surfaces the failure; a blank draft is recoverable.
      });
    return () => {
      cancelled = true;
    };
  }, [campaignId]);

  /* --------------------------------------------------------------- reach -- */

  /**
   * Every direct channel this restaurant can send on, asked about at once.
   *
   * The picker promises a real number on every card, and asking only about
   * the selected channel left the others saying "Counting…" forever. One
   * request covers all of them — the endpoint takes a list and answers per
   * channel — and the marginal cost of three more counts over the same
   * audience is a few milliseconds.
   *
   * Social channels are left out: a follower count is not a reach estimate,
   * and the cards say "everyone who follows you" rather than a number.
   */
  const countableChannels = useMemo((): MarketingChannel[] => {
    const live = (connections ? [...connections.values()] : [])
      .filter((row) => row.connected && row.family === 'DIRECT')
      .map((row) => row.channel);
    // The draft's own channel is always included, even when it is not
    // connected: the reach panel on later steps is about this campaign.
    return [...new Set<MarketingChannel>([draft.channel, ...live])];
  }, [connections, draft.channel]);

  // Re-estimated whenever anything that changes who gets this message changes.
  // The request is cheap and the number is the thing the owner is watching.
  //
  // It runs for social campaigns too, even though nobody is targeted: the
  // channel picker needs a per-channel reachable count on its cards, and that
  // comes from the same call. Nothing on the social audience screen reads it.
  const reachRequest = useRef(0);
  useEffect(() => {
    const requestId = reachRequest.current + 1;
    reachRequest.current = requestId;
    setReachLoading(true);

    void estimateReach({
      segment_key: draft.segment_key,
      branch_ids: draft.branch_ids,
      channels: countableChannels,
      goal: draft.goal,
      send_at: draft.schedule.mode === 'SCHEDULED' ? draft.schedule.send_at : null,
    })
      .then((estimate) => {
        // A slower earlier request must not overwrite a newer answer.
        if (reachRequest.current === requestId) {
          setReach(estimate);
        }
      })
      .catch(() => {
        if (reachRequest.current === requestId) {
          setReach(null);
        }
      })
      .finally(() => {
        if (reachRequest.current === requestId) {
          setReachLoading(false);
        }
      });
  }, [
    countableChannels,
    draft.branch_ids,
    draft.goal,
    draft.schedule.mode,
    draft.schedule.send_at,
    draft.segment_key,
  ]);

  /* --------------------------------------------------------------- edits -- */

  const patch = (changes: Partial<CampaignDraft>) =>
    setDraft((current) => ({ ...current, ...changes }));

  const patchContent = (changes: Partial<CampaignDraft['content']>) =>
    setDraft((current) => ({ ...current, content: { ...current.content, ...changes } }));

  const patchExtra = (changes: Partial<CampaignContentExtra>) =>
    setDraft((current) => ({
      ...current,
      content: { ...current.content, extra: { ...current.content.extra, ...changes } },
    }));

  /**
   * Switch channel, keeping what carries and dropping what does not.
   *
   * The goal and the audience survive a switch; the words do not. A push title
   * is not an Instagram caption and an approved WhatsApp layout id means
   * nothing on Facebook, so carrying the copy over would leave an owner
   * editing something that looks finished and is not valid. Anything already
   * written is confirmed first — silently discarding typed work is the one
   * thing a wizard must never do.
   */
  const applyChannel = (next: MarketingChannel) => {
    setDraft((current) => {
      const nextGoal = goalFitsChannel(getChannel(next), current.goal)
        ? current.goal
        : (getChannel(next).goals[0] ?? current.goal);
      return {
        ...current,
        channel: next,
        goal: nextGoal,
        content: {
          title: '',
          body: '',
          deep_link: current.content.deep_link,
          template_id: null,
          // The promo code and the photo are about the campaign, not the
          // format, so they are the two things worth carrying across.
          extra: {
            image_url: current.content.extra.image_url ?? null,
            promo_code: current.content.extra.promo_code ?? null,
          },
        },
      };
    });
    setChannelSwitch(null);
  };

  const chooseChannel = (next: MarketingChannel) => {
    if (next === draft.channel) {
      return;
    }
    const hasWork =
      draft.content.title.trim().length > 0 || draft.content.body.trim().length > 0;
    if (hasWork) {
      setChannelSwitch(next);
      return;
    }
    applyChannel(next);
  };

  const chooseGoal = (key: CampaignGoalKey) => {
    const next = getGoal(key);
    const template = templatesForGoal(key).find((entry) => entry.channel === draft.channel);
    setDraft((current) => ({
      ...current,
      goal: key,
      segment_key: next.default_segment,
      // Only pre-fill copy the owner has not already written over.
      content:
        current.content.title.trim().length === 0 &&
        current.content.body.trim().length === 0
          ? {
              ...current.content,
              title: template?.title ?? '',
              body: template?.body ?? '',
              template_id: template?.id ?? null,
            }
          : current.content,
      offer_id: next.suggests_offer ? current.offer_id : null,
    }));
  };

  const toggleBranch = (branchId: string) =>
    setDraft((current) => ({
      ...current,
      branch_ids: current.branch_ids.includes(branchId)
        ? current.branch_ids.filter((id) => id !== branchId)
        : [...current.branch_ids, branchId],
    }));

  /* ---------------------------------------------------------- validation -- */

  const stepBlockers = useMemo((): string | null => {
    if (step === STEP_AUDIENCE) {
      if (draft.branch_ids.length === 0) {
        return isSocial ? 'Pick the branch this post is about.' : 'Pick at least one branch.';
      }
      // Consent, device and minimum-size rules are a DIRECT concept. A public
      // post has no audience to be too small.
      if (!isSocial && reach && reach.audience_size < reach.minimum_segment_size) {
        return `This audience is too small to send to. Campaigns need at least ${reach.minimum_segment_size} people.`;
      }
    }
    if (step === STEP_CONTENT) {
      return contentBlocker(draft.channel, draft.content);
    }
    if (step === STEP_SCHEDULE && draft.schedule.mode === 'SCHEDULED' && !draft.schedule.send_at) {
      return 'Pick the date and time it should go out.';
    }
    return null;
  }, [draft.branch_ids.length, draft.channel, draft.content, draft.schedule, isSocial, reach, step]);

  const channelReach = reach?.channels.find((entry) => entry.channel === draft.channel);

  /** Every card's own number, from the one estimate covering all of them. */
  const reachByChannel = useMemo(() => {
    const map: Partial<Record<MarketingChannel, number>> = {};
    for (const entry of reach?.channels ?? []) {
      if (entry.available) {
        map[entry.channel] = entry.reachable;
      }
    }
    return map;
  }, [reach]);
  const reachable = channelReach?.available ? channelReach.reachable : 0;
  const exposure = offer ? offer.max_discount_amount * reachable : 0;

  /**
   * Whether this campaign can leave the building at all.
   *
   * Separate from `stepBlockers`, and deliberately not enforced before the
   * last screen: a channel that is not connected yet can still be planned,
   * written and saved in full. Stopping at the door was the old behaviour and
   * it taught owners that five of six channels were decoration.
   *
   * Unknown counts as blocked. While the connection list is still loading we
   * do not know, and offering a Send button that the server will refuse is
   * worse than a moment of caution.
   */
  const connection = connections?.get(draft.channel) ?? null;
  const channelBlocked =
    channel.availability !== 'ALWAYS_ON' && !connection?.connected;

  const sendBlocked =
    channelBlocked ||
    Boolean(reach && !isSocial && hasBlockingNotice(reach.notices)) ||
    Boolean(stepBlockers) ||
    Boolean(contentBlocker(draft.channel, draft.content));

  /* -------------------------------------------------------------- actions -- */

  const persist = useCallback(
    async (nextStep: number) => {
      setSaving(true);
      try {
        const saved = await saveDraft(forSaving({ ...draft, last_step: nextStep }));
        // The first save is a create: the wizard's local `cmp-<random>` id is
        // replaced by the one the server minted. Without adopting it here every
        // later save would create another campaign instead of updating this one.
        if (saved.id !== draft.id) {
          setDraft((current) => ({ ...current, id: saved.id }));
        }
      } catch (caught) {
        onToast(
          'Draft not saved',
          caught instanceof Error ? caught.message : 'The draft could not be saved.',
          'error',
        );
      } finally {
        setSaving(false);
      }
    },
    [draft, onToast],
  );

  const goToStep = (next: number) => {
    setStep(next);
    setFurthest((current) => Math.max(current, next));
    window.scrollTo({ top: 0, behavior: 'smooth' });
    // Nothing is written until the channel screen is behind us: a draft saved
    // from it would be a row in the campaign list for a decision the owner has
    // not finished making.
    if (next > STEP_CHANNEL) {
      void persist(next);
    }
  };

  const handleContinue = () => {
    if (stepBlockers) {
      onToast('Not quite ready', stepBlockers, 'info');
      return;
    }
    goToStep(Math.min(step + 1, STEP_REVIEW));
  };

  const handleSaveAndExit = async () => {
    await persist(Math.max(step, STEP_GOAL));
    onToast('Draft saved', 'Pick it up from your campaign list whenever you like.', 'success');
    onNavigate('/marketing');
  };

  const handleTestSend = async () => {
    setTesting(true);
    try {
      // The copy as it stands in the wizard, not as last saved: seeing the
      // edit you just made on a real phone is the whole point of the button.
      const result = await sendTest(draft.channel, {
        title: draft.content.title,
        body: draft.content.body,
      });
      onToast(
        result.destination ? 'Test send' : 'Test sent to you',
        // The server says what happened — including "sending is switched off
        // in this environment", which a fixed sentence here would lie about.
        result.destination ||
          'Check your own device — that is exactly what your customers will see.',
        'success',
      );
    } catch (caught) {
      onToast(
        'Test send failed',
        caught instanceof Error ? caught.message : 'The test could not be sent.',
        'error',
      );
    } finally {
      setTesting(false);
    }
  };

  const handleConfirmedSend = async () => {
    setConfirmOpen(false);
    setSending(true);
    try {
      // Save first and use the id that comes back, not the one in state: on a
      // campaign that has never been persisted these are different.
      const saved = await saveDraft(forSaving({ ...draft, last_step: STEP_REVIEW }));
      if (saved.id !== draft.id) {
        setDraft((current) => ({ ...current, id: saved.id }));
      }
      if (draft.schedule.mode === 'SCHEDULED' && draft.schedule.send_at) {
        await scheduleCampaign(saved.id, draft.schedule.send_at);
        onToast(
          'Campaign scheduled',
          `It goes out ${formatDate(draft.schedule.send_at)}. You can cancel any time before then.`,
          'success',
        );
      } else {
        await sendNow(saved.id);
        onToast(
          `${channel.label} campaign sent`,
          'Delivery is updating now. Results build over the next few days.',
          'success',
        );
      }
      onNavigate(`/marketing/campaigns/${saved.id}`);
    } catch (caught) {
      onToast(
        'Send failed',
        caught instanceof Error ? caught.message : 'The campaign could not be sent.',
        'error',
      );
    } finally {
      setSending(false);
    }
  };

  /* --------------------------------------------------------------- render -- */

  if (loadError) {
    return (
      <div className="mkt">
        <div className="mkt-empty">
          <span className="mkt-empty__icon">
            <Ban size={26} strokeWidth={2} />
          </span>
          <strong>This campaign can't be edited</strong>
          <p>{loadError}</p>
          <button
            className="mkt-btn mkt-btn--ghost"
            onClick={() => onNavigate('/marketing')}
            type="button"
          >
            <ArrowLeft size={15} strokeWidth={2.3} />
            Back to Marketing
          </button>
        </div>
      </div>
    );
  }

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

  const branchSummary =
    draft.branch_ids
      .map(
        (id) =>
          marketingReference.branches.find((branch) => branch.id === id)?.branch_name ?? '',
      )
      .filter(Boolean)
      .join(', ') || 'no branch selected';

  const spend = estimateSpend(channel, reachable, draft.content.body);
  const ChannelIcon = channel.icon;

  /**
   * Where a test send actually goes — the signed-in staff member's own
   * address, never the address the channel sends *from*.
   *
   * Said out loud because the difference cost somebody a bounce: the panel
   * used to promise "your own phone" for every channel, so an owner who had
   * just configured Gmail pressed Send test expecting it at that address and
   * received a delivery failure for their seeded `@example.com` login
   * instead. Naming the destination makes the mismatch visible before the
   * click rather than after it.
   */
  const testDestination =
    draft.channel === 'EMAIL'
      ? (currentUser?.email ?? null)
      : draft.channel === 'SMS' || draft.channel === 'WHATSAPP'
        ? (currentUser?.phone_number ?? null)
        : null;

  // Reserved domains that cannot receive mail. The server refuses these too
  // — this only saves the round trip and explains it in place.
  const testUndeliverable =
    draft.channel === 'EMAIL' &&
    Boolean(testDestination) &&
    /(^|@)(example\.(com|org|net)|localhost)$|\.(example|invalid|test|local|localhost)$/i.test(
      (testDestination ?? '').split('@').pop() ?? '',
    );

  const STEP_COPY: Record<number, { title: string; sub: string }> = {
    [STEP_CHANNEL]: {
      title: 'Where do you want to run your campaign?',
      sub: 'Pick one place. Everything we ask after this is about that one place, so there is nothing to fill in that does not apply to you.',
    },
    [STEP_GOAL]: {
      title: `What do you want this ${channel.noun} to do?`,
      sub: 'Your answer picks a starting audience and a starting message. You can change both.',
    },
    [STEP_AUDIENCE]: isSocial
      ? {
          title: 'Who should see this post?',
          sub: 'Anyone can see a post. You choose whether to pay to put it in front of people who do not follow you yet.',
        }
      : {
          title: 'Who should get it?',
          sub: 'These groups are built from your own orders and recounted every morning. Pick one, then narrow it by branch.',
        },
    [STEP_CONTENT]: {
      title: isSocial ? 'What are you posting?' : 'What are you telling them?',
      sub: `Watch the ${isSocial ? 'post' : 'phone'} on the right as you type — that is exactly how it will look.`,
    },
    [STEP_SCHEDULE]: {
      title: isSocial ? 'When should it go up?' : 'When should it go out?',
      sub: `${channel.verb} it now, or pick a time.${channel.family === 'DIRECT' ? ' Test it on your own phone first — it is the fastest way to catch a mistake.' : ''}`,
    },
    [STEP_REVIEW]: {
      title: 'Ready?',
      sub: 'One last look at what is about to happen, in plain words.',
    },
  };

  const copy = STEP_COPY[step];

  return (
    <div className="mkt">
      <header className="mkt-card__head mkt-card__head--row">
        <div className="mkt-card__head">
          <button className="mkt-back" onClick={() => onNavigate('/marketing')} type="button">
            <ChevronLeft size={14} strokeWidth={2.5} />
            Marketing
          </button>
          <h1 className="mkt-h1">{draft.name.trim() || 'New campaign'}</h1>
        </div>
        {step > STEP_CHANNEL ? (
          <button
            className="mkt-btn mkt-btn--ghost mkt-btn--sm"
            disabled={saving}
            onClick={() => void handleSaveAndExit()}
            type="button"
          >
            <Save size={15} strokeWidth={2.3} />
            {saving ? 'Saving…' : 'Save & exit'}
          </button>
        ) : null}
      </header>

      {/* The rail appears once there is a channel to carry. On the first
          screen it would be a progress bar for a journey not yet begun. */}
      {step > STEP_CHANNEL ? (
        <div className="mkt-railrow">
          <button
            className="mkt-channel-badge"
            onClick={() => goToStep(STEP_CHANNEL)}
            title="Change where this campaign runs"
            type="button"
          >
            <ChannelIcon size={15} strokeWidth={2.2} />
            {channel.label}
          </button>
          <WizardSteps current={step} furthest={furthest} onSelect={goToStep} steps={STEPS} />
        </div>
      ) : null}

      <div className={step === STEP_CHANNEL ? 'mkt-builder mkt-builder--wide' : 'mkt-builder'}>
        <div className="mkt-builder__main">
          <section className="mkt-step">
            <div className="mkt-step__head">
              <span className="mkt-eyebrow">
                Step {step} of {STEPS.length}
              </span>
              <h2 className="mkt-h1">{copy.title}</h2>
              <p className="mkt-sub">{copy.sub}</p>
            </div>

            {/* ------------------------------------------- step 1: where -- */}
            {step === STEP_CHANNEL && connectionsError ? (
              <CampaignNotices
                notices={[
                  {
                    id: 'connections-unreadable',
                    tone: 'warn',
                    title: 'We could not check which channels you have set up',
                    description: `${connectionsError} Push notifications work regardless — everything else is shown as needing setup because we could not ask, not because we know it does.`,
                  },
                ]}
              />
            ) : null}

            {step === STEP_CHANNEL ? (
              <ChannelPicker
                connections={connections ?? undefined}
                loading={reachLoading}
                onManage={() => onNavigate('/marketing/channels')}
                onSelect={chooseChannel}
                reachByChannel={reachByChannel}
                selected={draft.channel}
              />
            ) : null}

            {/* --------------------------------------------- step 2: why -- */}
            {step === STEP_GOAL ? (
              <div className="mkt-grid mkt-grid--2">
                {goals.map((entry) => {
                  const Icon = GOAL_ICONS[entry.key] ?? FALLBACK_ICON;
                  const selected = draft.goal === entry.key;
                  return (
                    <button
                      aria-pressed={selected}
                      className={selected ? 'mkt-pick mkt-pick--selected' : 'mkt-pick'}
                      key={entry.key}
                      onClick={() => chooseGoal(entry.key)}
                      type="button"
                    >
                      <span aria-hidden="true" className="mkt-pick__tick">
                        <Check size={12} strokeWidth={3.4} />
                      </span>
                      <span aria-hidden="true" className="mkt-pick__icon">
                        <Icon size={19} strokeWidth={2.1} />
                      </span>
                      <span className="mkt-pick__title">{entry.label}</span>
                      <span className="mkt-pick__text">{entry.description}</span>
                      <span className="mkt-pick__foot">
                        <Sparkles size={11} strokeWidth={2.4} />
                        {entry.success_metric}
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : null}

            {/* --------------------------------------------- step 3: who -- */}
            {step === STEP_AUDIENCE && isSocial ? (
              <SocialAudienceStep
                branchIds={draft.branch_ids}
                channel={draft.channel}
                extra={draft.content.extra}
                onBranch={toggleBranch}
                onExtra={patchExtra}
              />
            ) : null}

            {step === STEP_AUDIENCE && !isSocial ? (
              <>
                <div className="mkt-section">
                  <span className="mkt-section__label">
                    Choose a group <span>Counts are for your selected branches</span>
                  </span>
                  <div className="mkt-grid mkt-grid--3">
                    {marketingReference.segments.map((entry) => {
                      const Icon = SEGMENT_ICONS[entry.key] ?? FALLBACK_ICON;
                      const selected = draft.segment_key === entry.key;
                      const inBranch = draft.branch_ids.reduce(
                        (total, id) => total + (entry.members_by_branch[id] ?? 0),
                        0,
                      );
                      return (
                        <button
                          aria-pressed={selected}
                          className={selected ? 'mkt-pick mkt-pick--selected' : 'mkt-pick'}
                          key={entry.key}
                          onClick={() => patch({ segment_key: entry.key as SegmentKey })}
                          type="button"
                        >
                          <span className="mkt-pick__row">
                            <span aria-hidden="true" className="mkt-pick__icon">
                              <Icon size={18} strokeWidth={2.1} />
                            </span>
                            <span className="mkt-pick__badge">{inBranch}</span>
                          </span>
                          <span className="mkt-pick__title">{entry.name}</span>
                          <span className="mkt-pick__text">{entry.definition}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="mkt-section">
                  <span className="mkt-section__label">
                    Which branches?{' '}
                    <span>
                      {draft.branch_ids.length} of {marketingReference.branches.length} selected
                    </span>
                  </span>
                  <div aria-label="Branches" className="mkt-grid mkt-grid--2" role="group">
                    {marketingReference.branches.map((branch) => {
                      const isSelected = draft.branch_ids.includes(branch.id);
                      const members = segment.members_by_branch[branch.id] ?? 0;
                      return (
                        <button
                          aria-checked={isSelected}
                          className={
                            isSelected
                              ? 'mkt-pick mkt-pick--row mkt-pick--selected'
                              : 'mkt-pick mkt-pick--row'
                          }
                          key={branch.id}
                          onClick={() => toggleBranch(branch.id)}
                          role="checkbox"
                          type="button"
                        >
                          <span aria-hidden="true" className="mkt-pick__icon">
                            <MapPin size={17} strokeWidth={2.2} />
                          </span>
                          <span className="mkt-pick__copy">
                            <span className="mkt-pick__title">
                              {branch.branch_name}
                              {branch.is_active ? '' : ' · inactive'}
                            </span>
                            <span className="mkt-pick__text">
                              {pluralize(members, 'person', 'people')} in this group
                            </span>
                          </span>
                          <span aria-hidden="true" className="mkt-pick__tick">
                            <Check size={12} strokeWidth={3.4} />
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </>
            ) : null}

            {/* ------------------------------------------- step 4: words -- */}
            {step === STEP_CONTENT ? (
              <ContentStep
                channel={draft.channel}
                content={draft.content}
                exposure={exposure}
                offerId={draft.offer_id}
                onContent={patchContent}
                onExtra={patchExtra}
                onOffer={(offer_id) => patch({ offer_id })}
                templates={templates}
              />
            ) : null}

            {/* -------------------------------------------- step 5: when -- */}
            {step === STEP_SCHEDULE ? (
              <>
                <div className="mkt-section">
                  <span className="mkt-section__label">
                    Timing <span>In {draft.schedule.timezone}</span>
                  </span>
                  <div className="mkt-grid mkt-grid--2">
                    <button
                      aria-pressed={draft.schedule.mode === 'NOW'}
                      className={
                        draft.schedule.mode === 'NOW' ? 'mkt-pick mkt-pick--selected' : 'mkt-pick'
                      }
                      onClick={() =>
                        patch({ schedule: { ...draft.schedule, mode: 'NOW', send_at: null } })
                      }
                      type="button"
                    >
                      <span aria-hidden="true" className="mkt-pick__tick">
                        <Check size={12} strokeWidth={3.4} />
                      </span>
                      <span aria-hidden="true" className="mkt-pick__icon">
                        <Send size={18} strokeWidth={2.1} />
                      </span>
                      <span className="mkt-pick__title">{channel.verb} now</span>
                      <span className="mkt-pick__text">
                        Goes out as soon as you confirm on the next screen.
                      </span>
                    </button>

                    <button
                      aria-pressed={draft.schedule.mode === 'SCHEDULED'}
                      className={
                        draft.schedule.mode === 'SCHEDULED'
                          ? 'mkt-pick mkt-pick--selected'
                          : 'mkt-pick'
                      }
                      onClick={() => patch({ schedule: { ...draft.schedule, mode: 'SCHEDULED' } })}
                      type="button"
                    >
                      <span aria-hidden="true" className="mkt-pick__tick">
                        <Check size={12} strokeWidth={3.4} />
                      </span>
                      <span aria-hidden="true" className="mkt-pick__icon">
                        <Clock size={18} strokeWidth={2.1} />
                      </span>
                      <span className="mkt-pick__title">Pick a time</span>
                      <span className="mkt-pick__text">
                        You can cancel any time until it starts.
                      </span>
                    </button>
                  </div>

                  {draft.schedule.mode === 'SCHEDULED' ? (
                    <label className="mkt-field">
                      <span className="mkt-field__label">
                        {isSocial ? 'Post at' : 'Send at'}
                      </span>
                      <input
                        onChange={(event) =>
                          patch({
                            schedule: {
                              ...draft.schedule,
                              send_at: fromLocalInput(event.target.value),
                            },
                          })
                        }
                        type="datetime-local"
                        value={toLocalInput(draft.schedule.send_at)}
                      />
                      <span className="mkt-field__hint">
                        Between 08:00 and 22:00, and while the branch is open.
                      </span>
                    </label>
                  ) : null}
                </div>

                {/* The frequency cap is enforced at send time whatever this
                    screen says; saying it here is the difference between a
                    number that looks wrong later and one that was explained. */}
                {!isSocial ? (
                  <p className="mkt-field__hint">
                    Anyone who has already had{' '}
                    {pluralize(marketingReference.frequencyCapPerWeek, 'message')} from you
                    this week is left out automatically, so nobody is bombarded.
                  </p>
                ) : null}

                {/* The test endpoint sends a push, whatever the draft names.
                    Offering it on a channel that is not switched on would put
                    a push notification on the owner's phone and let them
                    conclude that WhatsApp works. */}
                {channel.family === 'DIRECT' && !channelBlocked ? (
                  <div className="mkt-test">
                    <span aria-hidden="true" className="mkt-test__icon">
                      <Smartphone size={19} strokeWidth={2.1} />
                    </span>
                    <span className="mkt-test__copy">
                      <strong>
                        {testDestination
                          ? `Send a test to ${testDestination}`
                          : 'Send it to yourself first'}
                      </strong>
                      <span>
                        {testUndeliverable ? (
                          <>
                            That is the address on your staff account, and{' '}
                            <strong>it cannot receive mail</strong> — it is a reserved
                            example domain. Sign in with a real address, or change this
                            account&rsquo;s email, then try again.
                          </>
                        ) : (
                          <>
                            The real {channel.noun}, exactly as a customer would get it.
                            It goes to the address on your own staff account
                            {draft.channel === 'EMAIL'
                              ? ' — not to the address this channel sends from'
                              : ''}
                            .
                          </>
                        )}
                      </span>
                    </span>
                    <button
                      className="mkt-btn mkt-btn--ghost mkt-btn--sm"
                      disabled={testing || testUndeliverable}
                      onClick={() => void handleTestSend()}
                      type="button"
                    >
                      {testing ? 'Sending…' : 'Send test'}
                    </button>
                  </div>
                ) : null}
              </>
            ) : null}

            {/* ------------------------------------------- step 6: ready -- */}
            {step === STEP_REVIEW ? (
              <>
                <ReviewStep
                  branchSummary={branchSummary}
                  draft={draft}
                  exposure={exposure}
                  name={draft.name}
                  offer={offer}
                  onEdit={goToStep}
                  onName={(name) => patch({ name })}
                  reachable={reachable}
                  segment={segment}
                  successMetric={goal.success_metric}
                />

                {channelBlocked ? (
                  <CampaignNotices
                    notices={[
                      {
                        id: 'channel-not-live',
                        tone: 'block',
                        title:
                          connection?.status === 'DISABLED'
                            ? `${channel.label} is paused`
                            : `${channel.label} is not connected yet`,
                        description:
                          connection?.last_error ??
                          (connection?.status === 'DISABLED'
                            ? 'Switch it back on from Marketing → Channels and this campaign is ready to go.'
                            : `Everything here is saved. Connect it from Marketing → Channels and this campaign is ready to send. ${channel.setup[0] ?? ''}`),
                      },
                    ]}
                  />
                ) : null}
              </>
            ) : null}
          </section>

          <div className="mkt-actions">
            <button
              className="mkt-btn mkt-btn--quiet"
              disabled={step === STEP_CHANNEL}
              onClick={() => goToStep(Math.max(step - 1, STEP_CHANNEL))}
              type="button"
            >
              <ArrowLeft size={15} strokeWidth={2.3} />
              Back
            </button>

            {stepBlockers ? (
              <span className="mkt-actions__hint mkt-actions__hint--blocked">{stepBlockers}</span>
            ) : (
              <span className="mkt-actions__hint">
                {step < STEP_REVIEW
                  ? `Next: ${STEPS[step].label.toLowerCase()}`
                  : channelBlocked
                    ? `Saved as a draft until ${channel.label} is connected.`
                    : draft.schedule.mode === 'NOW'
                      ? 'This cannot be undone once it starts.'
                      : 'You can cancel any time before it sends.'}
              </span>
            )}

            {step < STEP_REVIEW ? (
              <button className="mkt-btn mkt-btn--primary" onClick={handleContinue} type="button">
                Continue
                <ArrowRight size={16} strokeWidth={2.4} />
              </button>
            ) : channelBlocked ? (
              <button
                className="mkt-btn mkt-btn--primary"
                disabled={saving}
                onClick={() => void handleSaveAndExit()}
                type="button"
              >
                <Save size={16} strokeWidth={2.4} />
                Save this campaign
              </button>
            ) : (
              <button
                className="mkt-btn mkt-btn--primary"
                disabled={sendBlocked || sending}
                onClick={() => setConfirmOpen(true)}
                type="button"
              >
                <Send size={16} strokeWidth={2.4} />
                {draft.schedule.mode === 'NOW'
                  ? `${channel.verb} it`
                  : `Schedule this ${channel.noun}`}
              </button>
            )}
          </div>
        </div>

        {/* -------------------------------------------------------- rail -- */}
        {step > STEP_CHANNEL ? (
          <aside className="mkt-builder__rail">
            <section className="mkt-card mkt-card--tight">
              <div className="mkt-card__head">
                <span className="mkt-eyebrow">Live preview</span>
                <h2 className="mkt-h2">
                  {isSocial ? `On ${channel.label}` : `On a customer's phone`}
                </h2>
              </div>
              <ChannelPreview
                appName="Spice Route"
                branchName={primaryBranchName}
                channel={draft.channel}
                content={draft.content}
              />
            </section>

            {/* A reach panel for a public post would be inventing a number.
                Social campaigns get the spend they committed to instead. */}
            {isSocial ? (
              <section className="mkt-card mkt-card--tight">
                <div className="mkt-card__head">
                  <span className="mkt-eyebrow">Spend</span>
                  <h2 className="mkt-h2">What this costs</h2>
                </div>
                <p className="mkt-field__hint">
                  {(draft.content.extra.boost_budget ?? 0) > 0
                    ? `${formatCurrency(draft.content.extra.boost_budget ?? 0)}, billed by Meta over ${draft.content.extra.boost_days ?? 3} days.`
                    : 'Nothing — this post goes to your followers for free.'}
                </p>
              </section>
            ) : (
              <section className="mkt-card mkt-card--tight">
                <div className="mkt-card__head">
                  <span className="mkt-eyebrow">Reach</span>
                  <h2 className="mkt-h2">Who this gets to</h2>
                </div>

                {reach ? (
                  <>
                    <ReachSummary
                      audienceSize={reach.audience_size}
                      channels={reach.channels}
                      loading={reachLoading}
                      segmentName={segment.name}
                    />
                    <CampaignNotices notices={reach.notices} />
                    {spend > 0 ? (
                      <p className="mkt-field__hint">
                        Sending it costs about <strong>{formatCurrency(spend)}</strong>.
                      </p>
                    ) : null}
                    <p className="mkt-field__hint">
                      Judged on: <strong>{goal.success_metric}</strong>.
                    </p>
                  </>
                ) : (
                  <div className="mkt-skeleton-stack">
                    <span className="mkt-skeleton mkt-skeleton--line" />
                    <span className="mkt-skeleton mkt-skeleton--line" />
                  </div>
                )}
              </section>
            )}
          </aside>
        ) : null}
      </div>

      {/* Switching channel throws the copy away, so it is confirmed. */}
      <ConfirmDialog
        confirmLabel={`Start again on ${channelSwitch ? getChannel(channelSwitch).label : ''}`}
        description={`A ${channel.noun} is not a ${channelSwitch ? getChannel(channelSwitch).noun : 'post'}, so the words you wrote will not carry over. Your goal, your audience and your photo stay as they are.`}
        eyebrow="Change channel"
        onCancel={() => setChannelSwitch(null)}
        onConfirm={() => channelSwitch && applyChannel(channelSwitch)}
        open={channelSwitch !== null}
        title={`Move this campaign to ${channelSwitch ? getChannel(channelSwitch).label : ''}?`}
      />

      <ConfirmDialog
        busy={sending}
        confirmLabel={draft.schedule.mode === 'NOW' ? `${channel.verb} now` : 'Schedule it'}
        description={[
          isSocial
            ? `${channel.label} post`
            : `${pluralize(reachable, 'person', 'people')} · ${channel.label}`,
          branchSummary,
          draft.schedule.mode === 'NOW'
            ? 'going out immediately'
            : draft.schedule.send_at
              ? formatDate(draft.schedule.send_at)
              : 'no time chosen',
          spend > 0 ? `about ${formatCurrency(spend)} to send` : null,
          offer ? `up to ${formatCurrency(exposure)} in discount` : null,
          'This cannot be undone once it starts.',
        ]
          .filter(Boolean)
          .join(' · ')}
        eyebrow="Confirm"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => void handleConfirmedSend()}
        open={confirmOpen}
        title={
          draft.schedule.mode === 'NOW'
            ? `${channel.verb} this ${channel.noun} now?`
            : `Schedule this ${channel.noun}?`
        }
      />
    </div>
  );
}
