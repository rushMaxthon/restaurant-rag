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

/**
 * A fresh session id, in the UUID form `/suggestions` validates.
 *
 * Not `crypto.randomUUID()` alone: browsers only expose it in a secure context
 * (HTTPS or localhost), so opening the dev server by LAN address — the way a
 * phone reaches it — left it undefined, and the waiter prompt that calls this
 * on every page threw and took the whole route down to the error boundary.
 * `getRandomValues` has no such restriction and is all a v4 UUID needs.
 */
export function mintChatSessionId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40; // version 4
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80; // RFC 4122 variant
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

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
