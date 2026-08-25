import type { OwnerChatHistoryItem } from '../../types/app';

/**
 * One past conversation, built from the flat message list the API returns.
 *
 * Every question and answer is already persisted server-side against a
 * `session_id`; until now the screen never read any of it, so leaving the page
 * lost the thread and "Clear conversation" deleted history nobody had seen.
 */
export interface ChatSession {
  id: string;
  /** Derived from the first thing the owner asked, the way chat apps title threads. */
  title: string;
  messageCount: number;
  /** Timestamp of the newest message, used for ordering. */
  lastActivity: string;
  messages: OwnerChatHistoryItem[];
}

/** Long questions become unreadable in a 300px rail; cut on a word boundary. */
function toTitle(text: string): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (clean.length <= 44) {
    return clean || 'Untitled conversation';
  }
  const cut = clean.slice(0, 44);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > 20 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}

/**
 * Groups the flat history into conversations, newest first.
 *
 * The API returns every message oldest-first across all sessions, so both the
 * grouping and the ordering have to happen here.
 */
export function groupChatSessions(history: OwnerChatHistoryItem[]): ChatSession[] {
  const bySession = new Map<string, OwnerChatHistoryItem[]>();
  for (const row of history) {
    const existing = bySession.get(row.session_id);
    if (existing) {
      existing.push(row);
    } else {
      bySession.set(row.session_id, [row]);
    }
  }

  const sessions: ChatSession[] = [];
  for (const [id, rows] of bySession) {
    const ordered = [...rows].sort((a, b) => a.created_at.localeCompare(b.created_at));
    // The owner's own first question names the thread. An assistant-only
    // session (which shouldn't happen, but would render as "Untitled") falls
    // back to whatever the first message was.
    const firstUser = ordered.find((row) => row.role === 'USER') ?? ordered[0];
    sessions.push({
      id,
      title: toTitle(firstUser?.message ?? ''),
      messageCount: ordered.length,
      lastActivity: ordered[ordered.length - 1]?.created_at ?? '',
      messages: ordered,
    });
  }

  return sessions.sort((a, b) => b.lastActivity.localeCompare(a.lastActivity));
}

/** Relative age for the rail: exact timestamps are noise in a list of threads. */
export function describeAge(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) {
    return '';
  }
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short' }).format(then);
}
