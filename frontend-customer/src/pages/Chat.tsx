import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api } from '../services/api';
import { MessageBubble, type ChatTimelineMessage } from '../components/MessageBubble';
import { Skeleton } from '../components/Skeleton';
import { TypingIndicator } from '../components/TypingIndicator';
import type { ChatHistoryItem, ChatSuggestionItem, GeneratedCombo, PersonalizedOfferCard } from '../types/app';

interface ChatPageProps {
  token: string | null;
  sessionId: string | null;
  onSessionChange: (value: string | null) => void;
  onNavigate: (path: string) => void;
  onAddSuggestionToCart: (item: ChatSuggestionItem) => void;
  onAddComboToCart: (combo: GeneratedCombo) => void;
  onOpenOfferFromChat: (offer: PersonalizedOfferCard) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

const promptChips = [
  'Budget-friendly dinner ideas',
  'Recommend something spicy and veg',
  'What should I order for a group?',
];

function createMessageId(prefix: 'user' | 'ai'): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function extractSuggestions(entry: ChatHistoryItem): ChatSuggestionItem[] {
  if (entry.role !== 'ASSISTANT') {
    return [];
  }

  const rawSuggestions = entry.context_payload?.suggestions;
  return Array.isArray(rawSuggestions) ? (rawSuggestions as ChatSuggestionItem[]) : [];
}

function extractComboSuggestions(entry: ChatHistoryItem): GeneratedCombo[] {
  if (entry.role !== 'ASSISTANT') {
    return [];
  }

  const rawComboSuggestions = entry.context_payload?.combo_suggestions;
  return Array.isArray(rawComboSuggestions) ? (rawComboSuggestions as GeneratedCombo[]) : [];
}

function extractOfferSuggestions(entry: ChatHistoryItem): PersonalizedOfferCard[] {
  if (entry.role !== 'ASSISTANT') {
    return [];
  }

  const rawOfferSuggestions = entry.context_payload?.offer_suggestions;
  return Array.isArray(rawOfferSuggestions) ? (rawOfferSuggestions as PersonalizedOfferCard[]) : [];
}

function mapHistoryToTimeline(history: ChatHistoryItem[]): ChatTimelineMessage[] {
  return history.map((entry) => ({
    id: entry.id,
    type: entry.role === 'USER' ? 'user' : 'ai',
    text: entry.message,
    suggestions: extractSuggestions(entry),
    comboSuggestions: extractComboSuggestions(entry),
    offerSuggestions: extractOfferSuggestions(entry),
  }));
}

export function ChatPage({
  token,
  sessionId,
  onSessionChange,
  onNavigate,
  onAddSuggestionToCart,
  onAddComboToCart,
  onOpenOfferFromChat,
  onToast,
}: ChatPageProps) {
  const [messages, setMessages] = useState<ChatTimelineMessage[]>([]);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(Boolean(token));
  const [sending, setSending] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [clearing, setClearing] = useState(false);
  const bottomAnchorRef = useRef<HTMLDivElement | null>(null);
  const requestControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let active = true;

    async function loadChatHistory() {
      if (!token) {
        if (active) {
          setLoading(false);
          setMessages([]);
          setIsTyping(false);
        }
        return;
      }

      setLoading(true);
      try {
        const rows = await api.getChatHistory(token, sessionId);
        if (!active) {
          return;
        }
        setMessages(mapHistoryToTimeline(rows));
      } catch (error: unknown) {
        if (!active) {
          return;
        }
        const messageText = error instanceof ApiError ? error.message : 'Unable to load chat history.';
        onToast('Chat unavailable', messageText, 'error');
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadChatHistory();

    return () => {
      active = false;
    };
  }, [onToast, sessionId, token]);

  useEffect(() => {
    bottomAnchorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [isTyping, loading, messages]);

  useEffect(() => () => {
    requestControllerRef.current?.abort();
  }, []);

  const canSend = useMemo(() => message.trim().length > 0 && !sending, [message, sending]);
  const showPrompts = messages.length === 0 && !loading;
  const canClear = Boolean(token) && !loading && !sending && !clearing && messages.length > 0;

  const submitMessage = async (rawMessage: string) => {
    if (!token) {
      onNavigate('/auth/login');
      return;
    }

    const trimmedMessage = rawMessage.trim();
    if (!trimmedMessage || sending) {
      return;
    }

    const optimisticUserMessage: ChatTimelineMessage = {
      id: createMessageId('user'),
      type: 'user',
      text: trimmedMessage,
      suggestions: [],
      comboSuggestions: [],
      offerSuggestions: [],
    };
    const optimisticAssistantId = createMessageId('ai');
    const optimisticAssistantMessage: ChatTimelineMessage = {
      id: optimisticAssistantId,
      type: 'ai',
      text: '',
      suggestions: [],
      comboSuggestions: [],
      offerSuggestions: [],
    };

    setMessages((current) => [...current, optimisticUserMessage, optimisticAssistantMessage]);
    setMessage('');
    setSending(true);
    setIsTyping(true);

    const controller = new AbortController();
    requestControllerRef.current = controller;

    try {
      let resolvedSessionId = sessionId;
      let streamedReply = '';
      let streamedSuggestions: ChatSuggestionItem[] = [];
      let streamedComboSuggestions: GeneratedCombo[] = [];
      let streamedOfferSuggestions: PersonalizedOfferCard[] = [];

      await api.streamChatMessage(
        {
          message: trimmedMessage,
          session_id: sessionId,
        },
        token,
        {
          onMeta: (payload) => {
            resolvedSessionId = payload.session_id;
            streamedSuggestions = payload.suggestions;
            streamedComboSuggestions = payload.combo_suggestions;
            streamedOfferSuggestions = payload.offer_suggestions;
            onSessionChange(payload.session_id);
            setMessages((current) =>
              current.map((entry) =>
                entry.id === optimisticAssistantId
                  ? {
                      ...entry,
                      comboSuggestions: payload.combo_suggestions,
                      offerSuggestions: payload.offer_suggestions,
                      suggestions: payload.suggestions,
                    }
                  : entry,
              ),
            );
          },
          onToken: (tokenText) => {
            streamedReply += tokenText;
            setIsTyping(false);
            setMessages((current) =>
              current.map((entry) =>
                entry.id === optimisticAssistantId
                  ? {
                      ...entry,
                      text: streamedReply,
                    }
                  : entry,
              ),
            );
          },
          onDone: (payload) => {
            resolvedSessionId = payload.session_id;
            streamedSuggestions = payload.suggestions;
            streamedComboSuggestions = payload.combo_suggestions;
            streamedOfferSuggestions = payload.offer_suggestions;
            streamedReply = payload.reply;
            onSessionChange(payload.session_id);
            setMessages((current) =>
              current.map((entry) =>
                entry.id === optimisticAssistantId
                  ? {
                      ...entry,
                      comboSuggestions: payload.combo_suggestions,
                      offerSuggestions: payload.offer_suggestions,
                      text: payload.reply,
                      suggestions: payload.suggestions,
                    }
                  : entry,
              ),
            );
          },
        },
        controller.signal,
      );
      if (resolvedSessionId) {
        onSessionChange(resolvedSessionId);
      }
      if (streamedSuggestions.length > 0) {
        setMessages((current) =>
          current.map((entry) =>
            entry.id === optimisticAssistantId
              ? {
                  ...entry,
                  comboSuggestions: streamedComboSuggestions,
                  offerSuggestions: streamedOfferSuggestions,
                  suggestions: streamedSuggestions,
                }
              : entry,
          ),
        );
      }
      if (!streamedReply.trim()) {
        setMessages((current) =>
          current.map((entry) =>
            entry.id === optimisticAssistantId
              ? {
                  ...entry,
                  text: 'I found a few menu-backed options for you, but the final response was delayed. Please try again in a moment.',
                }
              : entry,
          ),
        );
      }
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return;
      }

      const messageText = error instanceof ApiError ? error.message : 'Unable to send your chat message.';
      onToast('Chat failed', messageText, 'error');
      setMessages((current) =>
        current.map((entry) =>
          entry.id === optimisticAssistantId
            ? {
                ...entry,
                text: entry.text || 'I hit a temporary connection issue while checking the menu. Please try again in a moment.',
              }
            : entry,
        ),
      );
    } finally {
      requestControllerRef.current = null;
      setSending(false);
      setIsTyping(false);
    }
  };

  const handleFormSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submitMessage(message);
  };

  const clearChat = async () => {
    if (!token || clearing || sending) {
      return;
    }

    setClearing(true);
    try {
      await api.clearChatHistory(token, sessionId ?? undefined);
      setMessages([]);
      setMessage('');
      setIsTyping(false);
      onSessionChange(null);
      onToast('Chat cleared', 'Your conversation has been reset.', 'success');
    } catch (error: unknown) {
      const messageText = error instanceof ApiError ? error.message : 'Unable to clear chat right now.';
      onToast('Unable to clear chat', messageText, 'error');
    } finally {
      setClearing(false);
    }
  };

  const handleComposerKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submitMessage(message);
    }
  };

  if (!token) {
    return (
      <div className="empty-state">
        <strong>Login to chat with the food assistant.</strong>
        <span>Your past orders and preferences help the recommendations feel personal.</span>
        <button
          className="primary-button primary-button--small"
          onClick={() => onNavigate('/auth/login')}
          type="button"
        >
          Login
        </button>
      </div>
    );
  }

  return (
    <div className="page-stack page-stack--chat">
      <section className="section-card section-card--chat">
        <div className="section-card__header">
          <div>
            <span className="eyebrow">AI concierge</span>
            <h2>Chat for personalized picks</h2>
            <p className="section-subtle">Ask by mood, spice level, budget, or dietary preference and let the assistant narrow it down.</p>
          </div>
          <button
            className="secondary-button secondary-button--small"
            disabled={!canClear}
            onClick={() => void clearChat()}
            type="button"
          >
            {clearing ? 'Clearing...' : 'Clear chat'}
          </button>
        </div>

        {showPrompts ? (
          <div className="chat-starter-card">
            <div>
              <strong>Start with a quick prompt</strong>
              <span>The assistant will use live menu context from the backend before replying.</span>
            </div>
            <div className="prompt-row">
              {promptChips.map((chip) => (
                <button
                  className="prompt-chip"
                  disabled={sending}
                  key={chip}
                  onClick={() => void submitMessage(chip)}
                  type="button"
                >
                  {chip}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div className="chat-layout">
          <div className="chat-thread" role="log" aria-live="polite" aria-relevant="additions text">
            {loading
              ? Array.from({ length: 4 }).map((_, index) => (
                  <Skeleton className="chat-skeleton" key={index} />
                ))
              : messages.map((entry) => (
                  <MessageBubble
                    key={entry.id}
                    message={entry}
                    onAddCombo={onAddComboToCart}
                    onAddSuggestion={onAddSuggestionToCart}
                    onOpenComboRestaurant={(restaurantId) => onNavigate(`/restaurant/${restaurantId}`)}
                    onOpenOffer={onOpenOfferFromChat}
                    onOpenSuggestion={(item) => onNavigate(`/menu-item/${item.id}`)}
                  />
                ))}
            {isTyping ? <TypingIndicator /> : null}
            <div className="chat-thread__bottom" ref={bottomAnchorRef} />
          </div>

          <form className="chat-composer" onSubmit={handleFormSubmit}>
            <textarea
              placeholder="Ask for recommendations, spice level, or budget-friendly combos..."
              rows={1}
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={handleComposerKeyDown}
            />
            <button className="primary-button chat-composer__button" disabled={!canSend} type="submit">
              {sending ? <span className="button-spinner" aria-hidden="true" /> : null}
              <span>{sending ? 'Sending' : 'Send'}</span>
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}
