export function TypingIndicator() {
  return (
    <div className="chat-row chat-row--assistant chat-row--typing" aria-live="polite" aria-label="AI is typing">
      <div className="chat-avatar">AI</div>
      <div className="chat-bubble chat-bubble--assistant chat-bubble--typing">
        <div className="typing-indicator" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}
