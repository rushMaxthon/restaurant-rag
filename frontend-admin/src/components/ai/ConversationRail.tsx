import { MessageSquare, Plus } from "lucide-react";

import { describeAge, type ChatSession } from "./chatSessions";

interface ConversationRailProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  loading: boolean;
  onSelect: (session: ChatSession) => void;
  onNewChat: () => void;
}

/**
 * Past conversations, beside the thread.
 *
 * The screen was a 780px column centred in ~1630px of empty space; this fills it
 * with something the product already had and never showed. It sits on the
 * right rather than the left because the console's navigation is already a
 * dark left rail, and two rails on the same side read as two navigations.
 */
export function ConversationRail({
  sessions,
  activeSessionId,
  loading,
  onSelect,
  onNewChat,
}: ConversationRailProps) {
  return (
    <aside aria-label="Conversations" className="ai-rail">
      <button className="ai-rail__new" onClick={onNewChat} type="button">
        <Plus size={15} strokeWidth={2.4} />
        New chat
      </button>

      <div className="ai-rail__list">
        {loading ? (
          <p className="ai-rail__note">Loading conversations…</p>
        ) : sessions.length === 0 ? (
          <p className="ai-rail__note">
            Your past conversations will appear here once you have asked something.
          </p>
        ) : (
          <>
            <p className="ai-rail__label">Recent</p>
            <ul>
              {sessions.map((session) => (
                <li key={session.id}>
                  <button
                    aria-current={session.id === activeSessionId ? "true" : undefined}
                    className={`ai-rail__item${
                      session.id === activeSessionId ? " is-active" : ""
                    }`}
                    onClick={() => onSelect(session)}
                    type="button"
                  >
                    <MessageSquare size={13} strokeWidth={2.2} />
                    <span className="ai-rail__item-copy">
                      <strong>{session.title}</strong>
                      <span>{describeAge(session.lastActivity)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </aside>
  );
}
