import { AppIcon } from '../AppIcon';

/**
 * The assistant's invitation.
 *
 * On the phone this is the app's tinted card; on a desktop it is the page's
 * one full-width inked banner, and the copy block and the call to action split
 * left and right. `ai-card__lede` is what makes both readings possible from
 * one tree — see `styles/home.css`.
 */
export function AiPromptCard({ onPress }: { onPress: () => void }) {
  return (
    <button className="ai-card" onClick={onPress} type="button">
      <span aria-hidden="true" className="ai-card__glow ai-card__glow--primary" />
      <span aria-hidden="true" className="ai-card__glow ai-card__glow--secondary" />

      <span className="ai-card__lede">
        <span className="ai-card__header">
          <span className="ai-card__icon">
            <AppIcon filled name="sparkles" size={18} />
          </span>
          <span className="ai-card__copy">
            <span className="ai-card__eyebrow">AI-powered picks</span>
            <span className="ai-card__title">Not sure what to eat?</span>
          </span>
        </span>

        <span className="ai-card__subtitle">
          Describe the craving, the budget or the mood, and the assistant builds the order
          around it — from this kitchen&rsquo;s menu, not a generic one.
        </span>

        {/* Not decoration: these are the three shapes of question the assistant
            answers best, shown so the reader knows what to type. */}
        <span className="ai-card__hints">
          <span className="ai-card__hint">Something spicy</span>
          <span className="ai-card__hint">Under Rs. 250</span>
          <span className="ai-card__hint">Vegetarian</span>
        </span>
      </span>

      <span className="ai-card__footer">
        <span className="ai-card__cta">
          Ask AI
          <AppIcon name="arrow-forward" size={14} />
        </span>
      </span>
    </button>
  );
}
