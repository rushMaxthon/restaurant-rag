import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, SendHorizonal, Sparkles, Trash2 } from "lucide-react";

import { AnswerText } from "./AnswerText";
import { BriefingMessage } from "./BriefingMessage";
import { ConversationRail } from "./ConversationRail";
import { groupChatSessions, type ChatSession } from "./chatSessions";
import { FindingsMessage } from "./FindingsMessage";
import type {
  OwnerChatHistoryItem,
  DiagnosticsSnapshot,
  OwnerBriefing,
  OwnerInsight,
  OwnerInsightStatus,
} from "../../types/app";
import { api } from "../../services/api";
import { streamOwnerChatMessage } from "../../services/aiManagerStream";

interface OwnerChatPanelProps {
  token: string;
  restaurantId: string | null;
  onError: (message: string) => void;
  /** The nightly analysis, rendered as the assistant's opening messages. */
  briefing: OwnerBriefing | null;
  diagnostics: DiagnosticsSnapshot | null;
  insights: OwnerInsight[];
  periodPhrase: string;
  loading: boolean;
  needsRestaurant: boolean;
  busyId: string | null;
  onUpdateInsightStatus: (insight: OwnerInsight, status: OwnerInsightStatus) => void;
}

interface ChatEntry {
  id: string;
  role: "USER" | "ASSISTANT";
  text: string;
  skill?: string | null;
  answerSource?: string | null;
  facts?: Record<string, unknown> | null;
  streaming?: boolean;
}

const STARTERS = [
  "Why are my sales down?",
  "What is my best selling dish?",
  "When am I busiest?",
  "How can I increase sales?",
];

let entryCounter = 0;
function nextId(): string {
  entryCounter += 1;
  return `entry-${entryCounter}`;
}

/** Whether a fact pack actually contains figures worth showing.
 *
 * Every answer carries a pack, but a greeting's is empty apart from its period
 * labels — and an empty object is truthy, so "Show the numbers" was offered on
 * replies that had none. */
function hasNumbers(facts?: Record<string, unknown> | null): boolean {
  if (!facts) return false;
  const headline = facts.headline as Record<string, unknown> | undefined;
  const findings = facts.findings as unknown[] | undefined;
  return Boolean(
    (headline && Object.keys(headline).length > 0) ||
      (Array.isArray(findings) && findings.length > 0),
  );
}

function labelise(key: string): string {
  const spaced = key.replaceAll("_", " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function formatFact(value: unknown): string {
  if (typeof value === "number") {
    return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value);
  }
  if (typeof value === "string" || typeof value === "boolean" || value === null) {
    return String(value);
  }
  return JSON.stringify(value);
}

/**
 * The figures behind an answer, as a labelled table.
 *
 * These used to render as `JSON.stringify(facts, null, 2)` inside a `<pre>` in a
 * 340px column - the right idea presented as a stack trace. The shape is known:
 * a `headline` object of metric totals and a `findings` array.
 */
function FactsTable({ facts }: { facts: Record<string, unknown> }) {
  const headline = (facts.headline ?? {}) as Record<string, unknown>;
  const findings = Array.isArray(facts.findings) ? (facts.findings as unknown[]) : [];

  return (
    <div className="ai-facts">
      {Object.keys(headline).length > 0 ? (
        <dl className="ai-facts__grid">
          {Object.entries(headline).map(([key, value]) => (
            <div className="ai-facts__row" key={key}>
              <dt>{labelise(key)}</dt>
              <dd>{formatFact(value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {findings.length > 0 ? (
        <ul className="ai-facts__findings">
          {findings.map((finding, index) => {
            const row = (finding ?? {}) as Record<string, unknown>;
            const title = row.title ?? row.subject ?? `Finding ${index + 1}`;
            return <li key={`finding-${index}`}>{formatFact(title)}</li>;
          })}
        </ul>
      ) : null}
    </div>
  );
}

export function OwnerChatPanel({
  token,
  restaurantId,
  onError,
  briefing,
  diagnostics,
  insights,
  periodPhrase,
  loading,
  needsRestaurant,
  busyId,
  onUpdateInsightStatus,
}: OwnerChatPanelProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [expandedFacts, setExpandedFacts] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  /** Replays stored messages into the thread. Facts are not persisted, so a
   *  restored answer has no "Show the numbers" - only live ones do. */
  const openSession = useCallback((session: ChatSession) => {
    setSessionId(session.id);
    setExpandedFacts(null);
    setEntries(
      session.messages.map((row: OwnerChatHistoryItem) => ({
        id: `history-${row.id}`,
        role: row.role,
        text: row.message,
      })),
    );
  }, []);

  /**
   * Restores the conversation on arrival.
   *
   * Every turn was already being stored against a session; the screen just
   * never read it, so leaving the page threw the thread away. On mount we load
   * the history, list it in the rail, and reopen the most recent conversation.
   */
  useEffect(() => {
    // Nothing to restore until a restaurant is chosen; the welcome state above
    // renders instead, so there is no state to reset here either.
    if (needsRestaurant) {
      return;
    }
    let active = true;
    // Wrapped rather than run in the effect body: setting state synchronously
    // there cascades a second render before the first has painted.
    const restore = async () => {
      setHistoryLoading(true);
      try {
        const grouped = groupChatSessions(await api.getOwnerChatHistory(token, { restaurantId }));
        if (!active) {
          return;
        }
        setSessions(grouped);
        if (grouped.length > 0) {
          openSession(grouped[0]);
        } else {
          setEntries([]);
          setSessionId(null);
        }
      } catch {
        // A missing history is not worth interrupting the screen for: the
        // briefing still renders and a new question still works.
        if (active) {
          setSessions([]);
        }
      } finally {
        if (active) {
          setHistoryLoading(false);
        }
      }
    };
    void restore();
    return () => {
      active = false;
    };
  }, [token, restaurantId, needsRestaurant, openSession]);

  /** Re-reads the rail after the stored history changes. */
  const refreshSessions = useCallback(async () => {
    try {
      setSessions(groupChatSessions(await api.getOwnerChatHistory(token, { restaurantId })));
    } catch {
      // The rail is a convenience; a failed refresh must not disturb the thread.
    }
  }, [restaurantId, token]);

  /** Starts a fresh thread. Past conversations stay in the rail. */
  const startNewChat = useCallback(() => {
    abortRef.current?.abort();
    setEntries([]);
    setSessionId(null);
    setExpandedFacts(null);
    setQuestion("");
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    // Abort any answer still streaming when the panel unmounts, so a navigation
    // mid-answer does not leave a dangling reader.
    return () => abortRef.current?.abort();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [entries]);

  const ask = async (raw: string) => {
    const text = raw.trim();
    if (!text || sending) {
      return;
    }

    const answerId = nextId();
    setEntries((current) => [
      ...current,
      { id: nextId(), role: "USER", text },
      { id: answerId, role: "ASSISTANT", text: "", streaming: true },
    ]);
    setQuestion("");
    setSending(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const patchAnswer = (patch: Partial<ChatEntry>) => {
      setEntries((current) =>
        current.map((entry) => (entry.id === answerId ? { ...entry, ...patch } : entry)),
      );
    };

    try {
      await streamOwnerChatMessage(
        { token, message: text, sessionId, restaurantId, signal: controller.signal },
        {
          onMeta: (data) => {
            if (typeof data.session_id === "string") {
              setSessionId(data.session_id);
            }
            patchAnswer({
              skill: typeof data.skill === "string" ? data.skill : null,
              answerSource:
                typeof data.answer_source === "string" ? data.answer_source : null,
            });
          },
          onToken: (chunk) => {
            setEntries((current) =>
              current.map((entry) =>
                entry.id === answerId ? { ...entry, text: entry.text + chunk } : entry,
              ),
            );
          },
          onDone: (data) => {
            patchAnswer({
              streaming: false,
              facts:
                data.facts && typeof data.facts === "object"
                  ? (data.facts as Record<string, unknown>)
                  : null,
              // The final frame carries the whole answer, so a dropped token
              // frame cannot leave a half-written reply on screen.
              ...(typeof data.answer === "string" ? { text: data.answer } : {}),
            });
          },
          onError: (message) => {
            patchAnswer({ streaming: false, text: message });
          },
        },
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unable to answer right now";
      patchAnswer({ streaming: false, text: message });
      onError(message);
    } finally {
      setSending(false);
      abortRef.current = null;
      // The first answer in a new thread is what creates the session
      // server-side, so this is the earliest the rail can list it.
      void refreshSessions();
    }
  };

  const clearHistory = async () => {
    try {
      await api.clearOwnerChatHistory(token, { restaurantId, sessionId });
      setEntries([]);
      setSessionId(null);
      setExpandedFacts(null);
      await refreshSessions();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Unable to clear the conversation");
    }
  };

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
        return;
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);

  // Driven by `open` alone. Tying it to `entries.length` meant Escape could
  // never collapse the surface once a question had been asked - the entries
  // survive in state either way, so reopening restores the conversation.
  if (needsRestaurant) {
    return (
      <div className="ai-thread">
        <div className="ai-thread__scroll">
          <div className="ai-welcome">
            <span className="ai-welcome__mark">
              <Sparkles size={22} strokeWidth={2.1} />
            </span>
            <h1>AI Restaurant Manager</h1>
            <p>Choose a restaurant above to see its briefing and ask about its data.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ai-workspace">
      <div className="ai-thread">
        <div className="ai-thread__scroll" ref={scrollRef}>
        <div className="ai-thread__column">
          {loading ? (
            <div className="ai-turn ai-turn--assistant">
              <span className="ai-turn__mark">
                <Sparkles size={15} strokeWidth={2.2} />
              </span>
              <div className="ai-turn__body">
                <span className="ai-msg__typing">Reading your data…</span>
              </div>
            </div>
          ) : (
            <>
              {/* The nightly analysis, said rather than displayed: the briefing
                  is the assistant's first message and the findings its second.
                  They sit outside `entries` so clearing the conversation does
                  not clear the analysis. */}
              <div className="ai-turn ai-turn--assistant">
                <span className="ai-turn__mark">
                  <Sparkles size={15} strokeWidth={2.2} />
                </span>
                <div className="ai-turn__body">
                  <BriefingMessage briefing={briefing} diagnostics={diagnostics} />
                </div>
              </div>

              <div className="ai-turn ai-turn--assistant">
                <span className="ai-turn__mark">
                  <Sparkles size={15} strokeWidth={2.2} />
                </span>
                <div className="ai-turn__body">
                  <FindingsMessage
                    busyId={busyId}
                    insights={insights}
                    onUpdateStatus={onUpdateInsightStatus}
                    periodPhrase={periodPhrase}
                  />
                </div>
              </div>
            </>
          )}

          {entries.map((entry) => (
            <div
              className={`ai-turn ai-turn--${entry.role.toLowerCase()}`}
              key={entry.id}
            >
              {entry.role === "ASSISTANT" ? (
                <span className="ai-turn__mark">
                  <Sparkles size={15} strokeWidth={2.2} />
                </span>
              ) : null}
              <div className="ai-turn__body">
                {/* The assistant's answer carries structure — headings, lists,
                    emphasis — so it is rendered rather than dumped into a <p>.
                    A question the owner typed is plain text and stays that way. */}
                {entry.role === "ASSISTANT" ? (
                  <>
                    <AnswerText text={entry.text} />
                    {entry.streaming && !entry.text ? (
                      <p>
                        <span className="ai-msg__typing">Thinking…</span>
                      </p>
                    ) : null}
                    {!entry.streaming && hasNumbers(entry.facts) ? (
                      <div className="ai-msg__meta">
                        {/* No skill name and no "AI wording" badge: they name
                            the machinery, which is ours to care about. "Show
                            the numbers" stays, because the figures behind an
                            answer are the owner's business. */}
                        <button
                          className="ai-facts-toggle"
                          onClick={() =>
                            setExpandedFacts((current) => (current === entry.id ? null : entry.id))
                          }
                          type="button"
                        >
                          {expandedFacts === entry.id ? (
                            <ChevronDown size={13} strokeWidth={2.3} />
                          ) : (
                            <ChevronRight size={13} strokeWidth={2.3} />
                          )}
                          Show the numbers
                        </button>
                      </div>
                    ) : null}
                    {expandedFacts === entry.id && hasNumbers(entry.facts) ? (
                      <FactsTable facts={entry.facts as Record<string, unknown>} />
                    ) : null}
                  </>
                ) : (
                  <p>{entry.text}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="ai-composer">
        <div className="ai-composer__column">
          {entries.length === 0 ? (
            <div className="ai-starters">
              {STARTERS.map((starter) => (
                <button
                  className="ai-starters__item"
                  key={starter}
                  onClick={() => ask(starter)}
                  type="button"
                >
                  {starter}
                </button>
              ))}
            </div>
          ) : null}

          <form
            className="ai-composer__form"
            onSubmit={(event) => {
              event.preventDefault();
              void ask(question);
            }}
          >
            <input
              aria-label="Ask about your data"
              disabled={sending}
              maxLength={500}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask about revenue, dishes, busy times, customers, offers…"
              ref={inputRef}
              type="text"
              value={question}
            />
            <button
              aria-label="Send"
              className="ai-composer__send"
              disabled={sending || !question.trim()}
              type="submit"
            >
              <SendHorizonal size={16} strokeWidth={2.2} />
            </button>
          </form>

          <div className="ai-composer__foot">
            <span>Answers are calculated from your data. Every figure can be checked.</span>
            {entries.length > 0 ? (
              // Scoped to this session, so deleting one thread leaves the rest
              // of the history in the rail.
              <button className="ai-composer__clear" onClick={clearHistory} type="button">
                <Trash2 size={12} strokeWidth={2.2} />
                Delete this chat
              </button>
            ) : null}
          </div>
          </div>
        </div>
      </div>

      <ConversationRail
        activeSessionId={sessionId}
        loading={historyLoading}
        onNewChat={startNewChat}
        onSelect={openSession}
        sessions={sessions}
      />
    </div>
  );
}
