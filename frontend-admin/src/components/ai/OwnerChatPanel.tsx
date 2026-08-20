import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, SendHorizonal, Trash2 } from "lucide-react";

import { AnswerText } from "./AnswerText";
import { api } from "../../services/api";
import { streamOwnerChatMessage } from "../../services/aiManagerStream";

interface OwnerChatPanelProps {
  token: string;
  restaurantId: string | null;
  onError: (message: string) => void;
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

export function OwnerChatPanel({ token, restaurantId, onError }: OwnerChatPanelProps) {
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [expandedFacts, setExpandedFacts] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

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
    }
  };

  const clearHistory = async () => {
    try {
      await api.clearOwnerChatHistory(token, { restaurantId, sessionId });
      setEntries([]);
      setSessionId(null);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Unable to clear the conversation");
    }
  };

  return (
    <section className="ai-card ai-chat">
      <header className="ai-card__head">
        <div className="ai-card__title">
          <span className="ai-eyebrow">Ask your data</span>
          <h2>Questions about this restaurant</h2>
        </div>
        {entries.length > 0 ? (
          <button type="button" className="secondary-button ai-btn" onClick={clearHistory}>
            <Trash2 size={14} strokeWidth={2.2} />
            Clear
          </button>
        ) : null}
      </header>

      <div className="ai-chat__log" ref={scrollRef}>
        {entries.length === 0 ? (
          <div className="ai-chat__intro">
            <p>
              Ask about revenue, dishes, busy times, customers, offers, or what to do next.
              Answers are calculated from your data, and every figure can be checked.
            </p>
            <div className="ai-chat__starters">
              {STARTERS.map((starter) => (
                <button
                  key={starter}
                  type="button"
                  className="secondary-button ai-btn"
                  onClick={() => ask(starter)}
                >
                  {starter}
                </button>
              ))}
            </div>
          </div>
        ) : (
          entries.map((entry) => (
            <article
              key={entry.id}
              className={`ai-msg ai-msg--${entry.role.toLowerCase()}`}
            >
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
                </>
              ) : (
                <p>{entry.text}</p>
              )}

              {entry.role === "ASSISTANT" && !entry.streaming ? (
                <div className="ai-msg__meta">
                  {/* No skill name and no "AI wording" / "Direct from data"
                      badge. They name the machinery — an owner reading
                      "multi part" or "tool answer" learns nothing about their
                      restaurant and everything about our internals. How the
                      answer was produced is a developer concern; it stays in
                      the logs and in the stored turn. "Show the numbers" is
                      kept, because the figures behind an answer are the
                      owner's business. */}
                  {hasNumbers(entry.facts) ? (
                    <button
                      type="button"
                      className="ai-facts-toggle"
                      onClick={() =>
                        setExpandedFacts((current) =>
                          current === entry.id ? null : entry.id,
                        )
                      }
                    >
                      {expandedFacts === entry.id ? (
                        <ChevronDown size={13} strokeWidth={2.3} />
                      ) : (
                        <ChevronRight size={13} strokeWidth={2.3} />
                      )}
                      Show the numbers
                    </button>
                  ) : null}
                </div>
              ) : null}

              {expandedFacts === entry.id && hasNumbers(entry.facts) ? (
                <pre className="ai-facts">{JSON.stringify(entry.facts, null, 2)}</pre>
              ) : null}
            </article>
          ))
        )}
      </div>

      <form
        className="ai-chat__composer"
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
      >
        <input
          type="text"
          value={question}
          placeholder="Ask about revenue, dishes, customers…"
          maxLength={500}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={sending}
        />
        <button type="submit" className="primary-button" disabled={sending || !question.trim()}>
          <SendHorizonal size={15} strokeWidth={2.2} />
          {sending ? "Asking…" : "Ask"}
        </button>
      </form>
    </section>
  );
}
