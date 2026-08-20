import { API_BASE_URL, AUTH_INVALID_EVENT, ApiError } from './api';

/**
 * Server-sent events over `fetch`.
 *
 * `EventSource` cannot be used here: it only issues GET requests and cannot set
 * an `Authorization` header, while the chat endpoint is a POST behind a bearer
 * token. So the response body is read as a stream and the frames are parsed by
 * hand.
 */

export interface SseFrame {
  event: string;
  data: Record<string, unknown>;
}

/**
 * Pulls whole frames out of a growing buffer.
 *
 * Frames are separated by a blank line. A chunk from the network can split one
 * anywhere — mid-field, mid-JSON, even between the `\n\n` characters — so the
 * remainder is always handed back to be prepended to the next chunk.
 */
export function parseSseBuffer(buffer: string): {
  frames: SseFrame[];
  rest: string;
} {
  const frames: SseFrame[] = [];
  // Normalised so CRLF from a proxy parses the same as LF.
  const normalized = buffer.replace(/\r\n/g, '\n');
  const parts = normalized.split('\n\n');
  // The trailing element is either an incomplete frame or an empty string.
  const rest = parts.pop() ?? '';

  for (const part of parts) {
    const frame = parseSseFrame(part);
    if (frame) {
      frames.push(frame);
    }
  }

  return { frames, rest };
}

/** Parses one frame. Returns null for comments, keep-alives, or malformed JSON. */
export function parseSseFrame(raw: string): SseFrame | null {
  const lines = raw.split('\n');
  let event = 'message';
  const dataLines: string[] = [];

  for (const line of lines) {
    if (!line || line.startsWith(':')) {
      continue;
    }
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim();
      continue;
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trim());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  try {
    const parsed = JSON.parse(dataLines.join('\n'));
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return { event, data: parsed as Record<string, unknown> };
    }
    return { event, data: { value: parsed } };
  } catch {
    // A frame we cannot read is dropped rather than tearing down the stream:
    // the useful frames around it should still reach the user.
    return null;
  }
}

export interface ChatStreamHandlers {
  onMeta?: (data: Record<string, unknown>) => void;
  onToken?: (text: string) => void;
  onDone?: (data: Record<string, unknown>) => void;
  onError?: (message: string) => void;
}

export interface ChatStreamOptions {
  token: string;
  message: string;
  sessionId?: string | null;
  restaurantId?: string | null;
  signal?: AbortSignal;
}

/**
 * Streams one owner chat answer.
 *
 * Resolves when the stream ends. An aborted request resolves quietly, since the
 * usual cause is the user navigating away mid-answer.
 */
export async function streamOwnerChatMessage(
  options: ChatStreamOptions,
  handlers: ChatStreamHandlers,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/owner/insights/chat/message/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${options.token}`,
    },
    body: JSON.stringify({
      message: options.message,
      session_id: options.sessionId ?? null,
      restaurant_id: options.restaurantId ?? null,
    }),
    signal: options.signal,
  });

  if (response.status === 401) {
    // Same signal the rest of the client uses, so an expired token logs out
    // consistently rather than leaving a half-finished answer on screen.
    window.dispatchEvent(new CustomEvent(AUTH_INVALID_EVENT));
    throw new ApiError('Session expired', 401);
  }

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = undefined;
    }
    throw new ApiError('Unable to answer right now', response.status, detail);
  }

  if (!response.body) {
    throw new ApiError('Streaming is not supported by this browser', 500);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const { frames, rest } = parseSseBuffer(buffer);
      buffer = rest;

      for (const frame of frames) {
        dispatchFrame(frame, handlers);
      }
    }

    // A stream that ends without a trailing blank line still has one good frame
    // left in the buffer.
    const trailing = parseSseFrame(buffer);
    if (trailing) {
      dispatchFrame(trailing, handlers);
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return;
    }
    throw error;
  } finally {
    reader.releaseLock();
  }
}

function dispatchFrame(frame: SseFrame, handlers: ChatStreamHandlers): void {
  switch (frame.event) {
    case 'meta':
      handlers.onMeta?.(frame.data);
      break;
    case 'token': {
      const text = frame.data.text;
      if (typeof text === 'string') {
        handlers.onToken?.(text);
      }
      break;
    }
    case 'done':
      handlers.onDone?.(frame.data);
      break;
    case 'error': {
      const detail = frame.data.detail;
      handlers.onError?.(
        typeof detail === 'string' ? detail : 'Unable to answer right now',
      );
      break;
    }
    default:
      break;
  }
}
