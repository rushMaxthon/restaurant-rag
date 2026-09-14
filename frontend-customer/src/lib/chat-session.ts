/**
 * The session this browser is continuing.
 *
 * Held in localStorage, not just a ref: the backend has always written every
 * turn to `chat_history` keyed by session, so the only thing standing between a
 * reload and the conversation coming back was the client forgetting which
 * session it had been in.
 *
 * Shared between `/concierge` and the in-page waiter prompt (home, cart) on
 * purpose: suggestion suppression is keyed by this id, and a prompt dismissed
 * on the home page must not reappear in the chat, or vice versa.
 */
const SESSION_KEY = "bangkok-bowl-chat-session";

export function readChatSession(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

export function storeChatSession(sessionId: string): void {
  try {
    window.localStorage.setItem(SESSION_KEY, sessionId);
  } catch {
    // A browser refusing storage costs continuity across reloads, nothing more.
  }
}

export function clearChatSession(): void {
  try {
    window.localStorage.removeItem(SESSION_KEY);
  } catch {
    // Same as above: losing the reset is cosmetic, throwing here would not be.
  }
}
