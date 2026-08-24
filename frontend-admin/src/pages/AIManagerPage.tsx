import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";

import { BriefingPanel } from "../components/ai/BriefingPanel";
import { InsightFeed } from "../components/ai/InsightFeed";
import { OfferPerformanceTable } from "../components/ai/OfferPerformanceTable";
import { OwnerChatPanel } from "../components/ai/OwnerChatPanel";
import { RecommendationList } from "../components/ai/RecommendationList";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PageIntro } from "../components/PageIntro";
import { useAdminStore } from "../hooks/useAdminStore";
import { ApiError, api, formatCurrency } from "../services/api";
import { DEFAULT_PERIOD_DAYS, PERIOD_OPTIONS } from "../services/insightFormat";
import { buildAdminRestaurantsCacheKeyPrefix } from "./AdminRestaurantsPage";
import {
  getPageSnapshot,
  hasPageSnapshot,
  invalidatePageSnapshotsByPrefix,
  setPageSnapshot,
  tokenScope,
} from "../services/pageCache";
import type {
  DiagnosticsSnapshot,
  OfferPerformanceSnapshot,
  OwnerActionProposal,
  OwnerBriefing,
  OwnerInsight,
  OwnerInsightStatus,
  Restaurant,
} from "../types/app";

const RESTAURANT_STORAGE_KEY = "ai-manager:restaurant";

interface AIManagerSnapshot {
  briefing: OwnerBriefing | null;
  diagnostics: DiagnosticsSnapshot | null;
  insights: OwnerInsight[];
  proposals: OwnerActionProposal[];
  offers: OfferPerformanceSnapshot | null;
}

// scopeId and periodDays both change what gets fetched, so both are in the
// key: switching the period, or (for an admin) the restaurant, is exactly the
// "required scope/filter change" that should hit the network again.
function buildAIManagerKey(scope: string, scopeId: string | null, periodDays: number): string {
  return `ai-manager:${scope}:${scopeId ?? ""}:${periodDays}`;
}

type PendingAction =
  | { kind: "approve"; proposal: OwnerActionProposal }
  | { kind: "reject"; proposal: OwnerActionProposal }
  | null;

export function AIManagerPage() {
  const { token: sessionToken, role, pushToast } = useAdminStore();
  const token = sessionToken ?? "";
  const isAdmin = role === "ADMIN";
  const scope = tokenScope(token);
  const adminRestaurantsKey = buildAdminRestaurantsCacheKeyPrefix(scope);

  // An owner is pinned to their own restaurant by the backend; an admin must
  // name one, because there is no sensible cross-restaurant diagnosis.
  const [restaurants, setRestaurants] = useState<Restaurant[]>(
    () => getPageSnapshot<Restaurant[]>(adminRestaurantsKey) ?? [],
  );
  // Remembered across reloads: an admin working through one restaurant's
  // numbers had to re-pick it after every refresh, and the page silently
  // reverted to whichever restaurant happened to sort first.
  const [selectedRestaurantId, setSelectedRestaurantId] = useState<string>(
    () => window.localStorage.getItem(RESTAURANT_STORAGE_KEY) ?? "",
  );

  // One period for the whole screen. Every panel used to pick its own — the
  // briefing described 60 days, the KPI tiles followed it, offers showed 7, and
  // the feed interleaved rows from two different runs. Four windows, one
  // screen, and only a footnote saying so.
  const [periodDays, setPeriodDays] = useState<number>(DEFAULT_PERIOD_DAYS);

  const scopeId = useMemo(
    () => (isAdmin ? selectedRestaurantId || null : null),
    [isAdmin, selectedRestaurantId],
  );
  const aiManagerKey = buildAIManagerKey(scope, scopeId, periodDays);
  const cachedAIManager = getPageSnapshot<AIManagerSnapshot>(aiManagerKey);

  const [briefing, setBriefing] = useState<OwnerBriefing | null>(
    () => cachedAIManager?.briefing ?? null,
  );
  const [diagnostics, setDiagnostics] = useState<DiagnosticsSnapshot | null>(
    () => cachedAIManager?.diagnostics ?? null,
  );
  const [insights, setInsights] = useState<OwnerInsight[]>(
    () => cachedAIManager?.insights ?? [],
  );
  const [proposals, setProposals] = useState<OwnerActionProposal[]>(
    () => cachedAIManager?.proposals ?? [],
  );
  const [offers, setOffers] = useState<OfferPerformanceSnapshot | null>(
    () => cachedAIManager?.offers ?? null,
  );

  // Only true when this exact scope+period has never been fetched this
  // session - not on every mount, so revisiting the AI Manager keeps showing
  // its data instead of a skeleton.
  const [loading, setLoading] = useState(() => !hasPageSnapshot(aiManagerKey));
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [actionBusy, setActionBusy] = useState(false);

  useEffect(() => {
    if (!isAdmin || !selectedRestaurantId) {
      return;
    }
    window.localStorage.setItem(RESTAURANT_STORAGE_KEY, selectedRestaurantId);
  }, [isAdmin, selectedRestaurantId]);

  useEffect(() => {
    if (!isAdmin || !token) {
      return;
    }

    const cachedRestaurants = getPageSnapshot<Restaurant[]>(adminRestaurantsKey);
    if (cachedRestaurants) {
      setRestaurants(cachedRestaurants);
      setSelectedRestaurantId((current) => {
        const remembered = cachedRestaurants.some((row) => row.id === current) ? current : "";
        return remembered || cachedRestaurants[0]?.id || "";
      });
      return;
    }

    api
      .getAdminRestaurants(token)
      .then((rows) => {
        setRestaurants(rows);
        setPageSnapshot(adminRestaurantsKey, rows);
        setSelectedRestaurantId((current) => {
          // A remembered id the admin can no longer see must not stick.
          const remembered = rows.some((row) => row.id === current) ? current : "";
          return remembered || rows[0]?.id || "";
        });
      })
      .catch(() => {
        // Non-fatal: the page still works once a restaurant is chosen.
        setRestaurants([]);
      });
  }, [adminRestaurantsKey, isAdmin, token]);

  // `force`: bypasses the cache. Used by the explicit Refresh button below and
  // never by the mount effect, which is what makes revisiting this page free.
  const load = useCallback(
    async (force = false) => {
      if (!token || (isAdmin && !scopeId)) {
        setLoading(false);
        return;
      }

      if (!force) {
        const cached = getPageSnapshot<AIManagerSnapshot>(aiManagerKey);
        if (cached) {
          setBriefing(cached.briefing);
          setDiagnostics(cached.diagnostics);
          setInsights(cached.insights);
          setProposals(cached.proposals);
          setOffers(cached.offers);
          setLoading(false);
          return;
        }
      }

      setLoading(true);
      const options = { restaurantId: scopeId };

      // Every panel gets the same window, and they all go out together. The
      // briefing no longer has to be fetched first to tell the others which
      // period to use, so this is one round trip instead of two.
      const [briefingResult, diagnosticsResult, feedResult, proposalResult, offerResult] =
        await Promise.allSettled([
          api.getOwnerBriefing(token, scopeId, { windowDays: periodDays }),
          api.getOwnerDiagnostics(token, { ...options, windowDays: periodDays }),
          api.getOwnerInsightFeed(token, { ...options, windowDays: periodDays, limit: 20 }),
          api.getOwnerRecommendations(token, { ...options, statuses: ["PROPOSED"] }),
          api.getOwnerOfferPerformance(token, { ...options, windowDays: periodDays }),
        ]);

      // A 404 here is the normal "nothing generated yet" state, not an error.
      const nextBriefing = briefingResult.status === "fulfilled" ? briefingResult.value : null;
      const nextDiagnostics =
        diagnosticsResult.status === "fulfilled" ? diagnosticsResult.value : null;
      const nextInsights = feedResult.status === "fulfilled" ? feedResult.value : [];
      const nextProposals = proposalResult.status === "fulfilled" ? proposalResult.value : [];
      const nextOffers = offerResult.status === "fulfilled" ? offerResult.value : null;

      setBriefing(nextBriefing);
      setDiagnostics(nextDiagnostics);
      setInsights(nextInsights);
      setProposals(nextProposals);
      setOffers(nextOffers);
      setPageSnapshot<AIManagerSnapshot>(aiManagerKey, {
        briefing: nextBriefing,
        diagnostics: nextDiagnostics,
        insights: nextInsights,
        proposals: nextProposals,
        offers: nextOffers,
      });

      const failure = [diagnosticsResult, feedResult, proposalResult, offerResult].find(
        (result) =>
          result.status === "rejected" &&
          !(result.reason instanceof ApiError && result.reason.status === 404),
      );
      if (failure && failure.status === "rejected") {
        const message =
          failure.reason instanceof Error
            ? failure.reason.message
            : "Unable to load the AI manager";
        pushToast("Could not load everything", message, "error");
      }

      setLoading(false);
    },
    [token, isAdmin, scopeId, periodDays, pushToast, aiManagerKey],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const updateInsightStatus = async (insight: OwnerInsight, status: OwnerInsightStatus) => {
    setBusyId(insight.id);
    try {
      const updated = await api.updateOwnerInsightStatus(token, insight.id, status, scopeId);
      setInsights((current) =>
        current.map((row) => (row.id === updated.id ? updated : row)),
      );
      // Genuine data change: the current view stays showing the just-patched
      // state above; this only affects what the NEXT visit to any period for
      // this scope fetches.
      invalidatePageSnapshotsByPrefix(`ai-manager:${scope}:${scopeId ?? ""}:`);
    } catch (error) {
      pushToast(
        "Could not update the insight",
        error instanceof Error ? error.message : "Please try again",
        "error",
      );
    } finally {
      setBusyId(null);
    }
  };

  const runPendingAction = async () => {
    if (!pendingAction) {
      return;
    }
    const { kind, proposal } = pendingAction;
    setActionBusy(true);
    setBusyId(proposal.id);

    try {
      if (kind === "approve") {
        const result = await api.approveOwnerRecommendation(token, proposal.id, scopeId);
        pushToast(
          result.offer_id ? "Offer created" : "Recommendation acknowledged",
          result.detail,
          "success",
        );
      } else {
        await api.rejectOwnerRecommendation(token, proposal.id, scopeId);
        pushToast("Recommendation rejected", "It will not be suggested again soon.", "info");
      }
      setProposals((current) => current.filter((row) => row.id !== proposal.id));
      // Approving may create a live offer, which the offers panel would show
      // under a different period than the one open right now - simplest to
      // invalidate every period for this scope so whichever one is revisited
      // next re-fetches, rather than patching just the current one and
      // guessing whether it was affected.
      invalidatePageSnapshotsByPrefix(`ai-manager:${scope}:${scopeId ?? ""}:`);
    } catch (error) {
      pushToast(
        kind === "approve" ? "Could not create the offer" : "Could not reject",
        error instanceof Error ? error.message : "Please try again",
        "error",
      );
    } finally {
      setActionBusy(false);
      setBusyId(null);
      setPendingAction(null);
    }
  };

  const confirmCopy = () => {
    if (!pendingAction) {
      return { title: "", description: "", confirmLabel: "" };
    }
    const { kind, proposal } = pendingAction;
    if (kind === "reject") {
      return {
        title: "Reject this recommendation?",
        description: `"${proposal.title}" will be dismissed and will not be suggested again for a while.`,
        confirmLabel: "Reject",
      };
    }

    const payload = proposal.action_payload ?? {};
    const discountType = typeof payload.discount_type === "string" ? payload.discount_type : "";
    const discountValue = Number(payload.discount_value ?? 0);
    const minimumOrder = Number(payload.minimum_order_amount ?? 0);
    const terms =
      discountType === "PERCENTAGE"
        ? `${discountValue}% off on orders over ${formatCurrency(minimumOrder)}`
        : `${formatCurrency(discountValue)} off on orders over ${formatCurrency(minimumOrder)}`;

    return {
      title: proposal.is_executable ? "Create this offer?" : "Acknowledge this recommendation?",
      description: proposal.is_executable
        ? `This creates a live offer: ${terms}. It will be visible to customers immediately. The expected impact is an estimate, not a guarantee.`
        : `"${proposal.title}" is advisory, so nothing will be created.`,
      confirmLabel: proposal.is_executable ? "Create offer" : "Acknowledge",
    };
  };

  const copy = confirmCopy();
  const needsRestaurant = isAdmin && !scopeId;
  const activePeriod =
    PERIOD_OPTIONS.find((option) => option.days === periodDays) ?? PERIOD_OPTIONS[0];

  // The feed is now scoped to the selected period server-side, from the same
  // analysis that produced the briefing, so there is nothing left to split here.

  return (
    // `ai-page` opts this one page into a viewport-bounded layout: the reading
    // column scrolls on its own and the chat stays in view beside it.
    <div className="page ai-page">
      <div className="ai-layout">
        <div className="ai-col--left">
          <PageIntro
        eyebrow="Intelligence"
        title="AI Restaurant Manager"
        description={`Your briefing, what changed and why, what to do about it, and a place to ask questions about your own data. Everything below covers ${activePeriod.phrase}.`}
        actions={
          <div className="ai-toolbar">
            {/* The period every panel below answers for. Stated, not implied:
                an owner reading a figure has to know what it is a figure of. */}
            <div className="ai-period" role="group" aria-label="Period">
              {PERIOD_OPTIONS.map((option) => (
                <button
                  key={option.days}
                  type="button"
                  className={`ai-period__option${
                    periodDays === option.days ? " is-active" : ""
                  }`}
                  aria-pressed={periodDays === option.days}
                  disabled={loading}
                  onClick={() => setPeriodDays(option.days)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            {isAdmin ? (
              <select
                value={selectedRestaurantId}
                onChange={(event) => setSelectedRestaurantId(event.target.value)}
                aria-label="Restaurant"
              >
                <option value="">Select a restaurant…</option>
                {restaurants.map((restaurant) => (
                  <option key={restaurant.id} value={restaurant.id}>
                    {restaurant.name}
                  </option>
                ))}
              </select>
            ) : null}
            <button
              type="button"
              className="secondary-button"
              onClick={() => void load(true)}
              disabled={loading || needsRestaurant}
            >
              <RefreshCw size={15} strokeWidth={2.2} />
              Refresh
            </button>
              </div>
            }
          />

          <div className="ai-col ai-col--main">
            {needsRestaurant ? (
              <section className="ai-card">
                <p className="ai-lede">
                  Choose a restaurant to see its briefing, insights, and recommendations.
                </p>
              </section>
            ) : (
              <>
                <BriefingPanel
                  briefing={briefing}
                  diagnostics={diagnostics}
                  loading={loading}
                />
                <InsightFeed
                  insights={insights}
                  periodPhrase={activePeriod.phrase}
                  loading={loading}
                  busyId={busyId}
                  onUpdateStatus={updateInsightStatus}
                />
                <RecommendationList
                  proposals={proposals}
                  loading={loading}
                  busyId={busyId}
                  onApprove={(proposal) => setPendingAction({ kind: "approve", proposal })}
                  onReject={(proposal) => setPendingAction({ kind: "reject", proposal })}
                />
                <OfferPerformanceTable snapshot={offers} loading={loading} />
              </>
            )}
          </div>
        </div>

        <div className="ai-col ai-col--side">
          <OwnerChatPanel
            token={token}
            restaurantId={scopeId}
            onError={(message) => pushToast("Chat error", message, "error")}
          />
        </div>
      </div>

      <ConfirmDialog
        open={pendingAction !== null}
        eyebrow="Confirm action"
        title={copy.title}
        description={copy.description}
        confirmLabel={copy.confirmLabel}
        tone={pendingAction?.kind === "reject" ? "danger" : "default"}
        busy={actionBusy}
        onConfirm={() => void runPendingAction()}
        onCancel={() => setPendingAction(null)}
      />
    </div>
  );
}
