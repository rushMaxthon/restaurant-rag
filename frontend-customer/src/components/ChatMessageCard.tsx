import { GeneratedComboCard } from './home/GeneratedComboCard';
import { OfferCard } from './home/OfferCard';
import type { ChatHistoryItem, ChatSuggestionItem, GeneratedCombo, PersonalizedOfferCard } from '../types/app';
import { createPlaceholderImage, formatCurrency } from '../services/api';
import type { MouseEvent } from 'react';

interface ChatMessageCardProps {
  message: ChatHistoryItem;
  suggestions?: ChatSuggestionItem[];
  comboSuggestions?: GeneratedCombo[];
  offerSuggestions?: PersonalizedOfferCard[];
  onAddSuggestion: (item: ChatSuggestionItem) => void;
  onAddCombo: (combo: GeneratedCombo) => void;
  onOpenComboRestaurant: (restaurantId: string) => void;
  onOpenOffer: (offer: PersonalizedOfferCard) => void;
}

export function ChatMessageCard({
  message,
  suggestions = [],
  comboSuggestions = [],
  offerSuggestions = [],
  onAddSuggestion,
  onAddCombo,
  onOpenComboRestaurant,
  onOpenOffer,
}: ChatMessageCardProps) {
  const isUser = message.role === 'USER';
  const handleAddSuggestion = (
    event: MouseEvent<HTMLButtonElement>,
    item: ChatSuggestionItem,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    onAddSuggestion(item);
  };

  return (
    <div className={`chat-row ${isUser ? 'chat-row--user' : 'chat-row--assistant'}`}>
      {!isUser ? <div className="chat-avatar">AI</div> : null}
      <div className={`chat-bubble ${isUser ? 'chat-bubble--user' : 'chat-bubble--assistant'}`}>
        <p>{message.message}</p>
        {!isUser && suggestions.length > 0 ? (
          <div className="chat-suggestions">
            {suggestions.map((item) => (
              <article className="chat-food-card" key={item.id}>
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
        {!isUser && comboSuggestions.length > 0 ? (
          <div className="chat-combo-suggestions">
            {comboSuggestions.map((combo) => (
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
        {!isUser && offerSuggestions.length > 0 ? (
          <div className="chat-offer-suggestions">
            {offerSuggestions.map((offer) => (
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
