import { GeneratedComboCard } from './home/GeneratedComboCard';
import { OfferCard } from './home/OfferCard';
import { createPlaceholderImage, formatCurrency } from '../services/api';
import type { ChatSuggestionItem, GeneratedCombo, PersonalizedOfferCard } from '../types/app';
import type { MouseEvent } from 'react';

export interface ChatTimelineMessage {
  id: string;
  type: 'user' | 'ai';
  text: string;
  suggestions: ChatSuggestionItem[];
  comboSuggestions: GeneratedCombo[];
  offerSuggestions: PersonalizedOfferCard[];
}

interface MessageBubbleProps {
  message: ChatTimelineMessage;
  onAddSuggestion: (item: ChatSuggestionItem) => void;
  onOpenSuggestion: (item: ChatSuggestionItem) => void;
  onAddCombo: (combo: GeneratedCombo) => void;
  onOpenComboRestaurant: (restaurantId: string) => void;
  onOpenOffer: (offer: PersonalizedOfferCard) => void;
}

export function MessageBubble({
  message,
  onAddSuggestion,
  onOpenSuggestion,
  onAddCombo,
  onOpenComboRestaurant,
  onOpenOffer,
}: MessageBubbleProps) {
  const isUser = message.type === 'user';
  const handleAddSuggestion = (
    event: MouseEvent<HTMLButtonElement>,
    item: ChatSuggestionItem,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    onAddSuggestion(item);
  };
  const handleOpenSuggestion = (item: ChatSuggestionItem) => {
    onOpenSuggestion(item);
  };

  return (
    <div className={`chat-row ${isUser ? 'chat-row--user' : 'chat-row--assistant'}`}>
      {!isUser ? <div className="chat-avatar">AI</div> : null}
      <div className={`chat-bubble ${isUser ? 'chat-bubble--user' : 'chat-bubble--assistant'}`}>
        <p>{message.text}</p>
        {!isUser && message.suggestions.length > 0 ? (
          <div className="chat-suggestions">
            {message.suggestions.map((item) => (
              <article
                className="chat-food-card"
                key={item.id}
                onClick={() => handleOpenSuggestion(item)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    handleOpenSuggestion(item);
                  }
                }}
                role="button"
                tabIndex={0}
              >
                <img loading="lazy" decoding="async" src={item.image_url ?? createPlaceholderImage(item.name)} alt={item.name} />
                <div className="chat-food-card__copy">
                  <strong>{item.name}</strong>
                  <span>{item.restaurant_name}</span>
                  <span>{formatCurrency(item.price)}</span>
                </div>
                <button
                  className="add-button"
                  onClick={(event) => handleAddSuggestion(event, item)}
                  type="button"
                >
                  + ADD
                </button>
              </article>
            ))}
          </div>
        ) : null}
        {!isUser && message.comboSuggestions.length > 0 ? (
          <div className="chat-combo-suggestions">
            {message.comboSuggestions.map((combo) => (
              <GeneratedComboCard
                combo={combo}
                disabled={false}
                key={combo.id}
                onAddCombo={onAddCombo}
                onOpenRestaurant={onOpenComboRestaurant}
              />
            ))}
          </div>
        ) : null}
        {!isUser && message.offerSuggestions.length > 0 ? (
          <div className="chat-offer-suggestions">
            {message.offerSuggestions.map((offer) => (
              <OfferCard
                disabled={false}
                key={offer.id}
                offer={offer}
                onOpen={onOpenOffer}
              />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
