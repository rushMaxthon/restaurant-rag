import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";

import { OwnerChatPanel } from "../components/ai/OwnerChatPanel";
import { useAdminStore } from "../hooks/useAdminStore";
import { ApiError, api } from "../services/api";
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
}

// scopeId and periodDays both change what gets fetched, so both are in the
// key: switching the period, or (for an admin) the restaurant, is exactly the
// "required scope/filter change" that should hit the network again.
function buildAIManagerKey(scope: string, scopeId: string | null, periodDays: number): string {
  return `ai-manager:${scope}:${scopeId ?? ""}:${periodDays}`;
}

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

  // Only true when this exact scope+period has never been fetched this
  // session - not on every mount, so revisiting the AI Manager keeps showing
  // its data instead of a skeleton.
  const [loading, setLoading] = useState(() => !hasPageSnapshot(aiManagerKey));
  const [busyId, setBusyId] = useState<string | null>(null);

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
          setLoading(false);
          return;
        }
      }

      setLoading(true);
      const options = { restaurantId: scopeId };

      // All three go out together on the same window. Recommendations and offer
      // performance are no longer fetched: this screen is a conversation, and
      // those two sections were removed from it.
      const [briefingResult, diagnosticsResult, feedResult] = await Promise.allSettled([
        api.getOwnerBriefing(token, scopeId, { windowDays: periodDays }),
        api.getOwnerDiagnostics(token, { ...options, windowDays: periodDays }),
        api.getOwnerInsightFeed(token, { ...options, windowDays: periodDays, limit: 20 }),
      ]);

      // A 404 here is the normal "nothing generated yet" state, not an error.
      const nextBriefing = briefingResult.status === "fulfilled" ? briefingResult.value : null;
      const nextDiagnostics =
        diagnosticsResult.status === "fulfilled" ? diagnosticsResult.value : null;
      const nextInsights = feedResult.status === "fulfilled" ? feedResult.value : [];
      setBriefing(nextBriefing);
      setDiagnostics(nextDiagnostics);
      setInsights(nextInsights);
      setPageSnapshot<AIManagerSnapshot>(aiManagerKey, {
        briefing: nextBriefing,
        diagnostics: nextDiagnostics,
        insights: nextInsights,
      });

      const failure = [diagnosticsResult, feedResult].find(
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

  /**
   * When the analysis on screen was computed, in the timezone the figures were
   * computed in. Formatting in the reader's own zone would put a time on the
   * bar that does not match the day boundaries every number below uses.
   */
  const computedAt = (() => {
    if (!diagnostics?.generated_at) {
      return null;
    }
    const when = new Date(diagnostics.generated_at);
    if (Number.isNaN(when.getTime())) {
      return null;
    }
    try {
      return new Intl.DateTimeFormat("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: diagnostics.scope.timezone,
      }).format(when);
    } catch {
      // An unknown zone from the API must not take the whole bar down.
      return null;
    }
  })();

  const needsRestaurant = isAdmin && !scopeId;
  const activePeriod =
    PERIOD_OPTIONS.find((option) => option.days === periodDays) ?? PERIOD_OPTIONS[0];

  // The feed is now scoped to the selected period server-side, from the same
  // analysis that produced the briefing, so there is nothing left to split here.

  return (
    // A conversation, not a dashboard. The nightly analysis is not a set of
    // panels above the chat - it is the assistant's opening messages, so the
    // whole screen is one thread from the briefing down to whatever you ask.
    <div className="page ai-page">
      {/* Everything the conversation is scoped to, on one slim line. A chat
          screen should not carry a page header; it should carry its context. */}
      <header className="ai-bar">
        {isAdmin ? (
          <select
            aria-label="Restaurant"
            className="ai-bar__scope"
            onChange={(event) => setSelectedRestaurantId(event.target.value)}
            value={selectedRestaurantId}
          >
            <option value="">Select a restaurant…</option>
            {restaurants.map((restaurant) => (
              <option key={restaurant.id} value={restaurant.id}>
                {restaurant.name}
              </option>
            ))}
          </select>
        ) : null}

        {/* The period every figure in the thread answers for. Stated, not
            implied: an owner reading a number has to know what it is of. */}
        <div aria-label="Period" className="ai-period" role="group">
          {PERIOD_OPTIONS.map((option) => (
            <button
              aria-pressed={periodDays === option.days}
              className={`ai-period__option${periodDays === option.days ? " is-active" : ""}`}
              disabled={loading}
              key={option.days}
              onClick={() => setPeriodDays(option.days)}
              type="button"
            >
              {option.label}
            </button>
          ))}
        </div>

        <span className="ai-bar__spacer" />

        {/* The context every figure in the thread depends on. It used to appear
            only inside the briefing message, where it scrolled away. */}
        {diagnostics ? (
          <p className="ai-bar__context">
            <span>{diagnostics.current_period.label}</span>
            {computedAt ? <em>updated {computedAt}</em> : null}
          </p>
        ) : null}

        <button
          className="ai-bar__refresh"
          disabled={loading || needsRestaurant}
          onClick={() => void load(true)}
          type="button"
        >
          <RefreshCw size={14} strokeWidth={2.2} />
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <OwnerChatPanel
        briefing={briefing}
        busyId={busyId}
        diagnostics={diagnostics}
        insights={insights}
        loading={loading}
        needsRestaurant={needsRestaurant}
        onError={(message) => pushToast("Chat error", message, "error")}
        onUpdateInsightStatus={updateInsightStatus}
        periodPhrase={activePeriod.phrase}
        restaurantId={scopeId}
        token={token}
      />
    </div>
  );
}
