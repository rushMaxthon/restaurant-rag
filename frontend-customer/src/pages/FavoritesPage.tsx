import { useEffect, useMemo, useState } from 'react';
import { useAppStore } from '../hooks/useAppStore';
import { ApiError, api, createPlaceholderImage, formatCurrency } from '../services/api';
import type { FavoriteItem } from '../types/app';
import { isCustomizableMenuItem } from '../utils/menuItemCustomization';

interface FavoritesPageProps {
  token: string | null;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

export function FavoritesPage({ token, onNavigate, onToast }: FavoritesPageProps) {
  const {
    favoriteVersion,
    favoritesHydrated,
    isFavorite,
    isFavoritePending,
    requestAddToCart,
    setPendingAuthRedirectPath,
    toggleFavorite,
  } = useAppStore();
  const [items, setItems] = useState<FavoriteItem[]>([]);
  const [loading, setLoading] = useState(Boolean(token));
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;

    async function loadFavorites() {
      if (!token) {
        setItems([]);
        setLoading(false);
        setError(null);
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const rows = await api.getFavorites(token);
        if (active) {
          setItems(rows);
        }
      } catch (nextError) {
        if (!active) {
          return;
        }
        setError(nextError instanceof Error ? nextError.message : 'Unable to load favorites right now.');
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadFavorites();
    return () => {
      active = false;
    };
  }, [favoriteVersion, reloadKey, token]);

  const visibleItems = useMemo(
    () => (favoritesHydrated ? items.filter((item) => isFavorite(item.id)) : items),
    [favoritesHydrated, isFavorite, items],
  );

  if (!token) {
    return (
      <div className="page-stack">
        <section className="hero-panel hero-panel--compact">
          <div className="hero-panel__copy">
            <span className="eyebrow">Favorites</span>
            <h1>Save dishes you want to come back to.</h1>
            <p>Login to keep favorites synced between the customer site and the mobile app.</p>
            <div className="hero-panel__actions">
              <button
                className="primary-button"
                onClick={() => {
                  setPendingAuthRedirectPath('/favorites');
                  onNavigate('/auth/login');
                }}
                type="button"
              >
                Login to view favorites
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="hero-panel hero-panel--compact">
        <div className="hero-panel__copy">
          <span className="eyebrow">Favorites</span>
          <h1>Your saved dishes</h1>
          <p>Quick access to the menu items you want ready across web and mobile.</p>
        </div>
      </section>

      <section className="section-card">
        {loading ? (
          <div className="favorites-grid favorites-grid--loading">
            {Array.from({ length: 4 }).map((_, index) => (
              <div className="favorite-card favorite-card--skeleton" key={index} />
            ))}
          </div>
        ) : error ? (
          <div className="empty-state empty-state--with-actions">
            <strong>We couldn’t load your favorites.</strong>
            <span>{error}</span>
            <div className="empty-state__actions">
              <button
                className="primary-button primary-button--small"
                onClick={() => setReloadKey((current) => current + 1)}
                type="button"
              >
                Retry
              </button>
            </div>
          </div>
        ) : visibleItems.length === 0 ? (
          <div className="empty-state">
            <strong>No favorites yet.</strong>
            <span>Tap the heart on any menu card to build your personal shortlist.</span>
          </div>
        ) : (
          <div className="favorites-grid">
            {visibleItems.map((item) => {
              const unavailable = !item.is_orderable;
              return (
                <article className="favorite-card" key={item.id}>
                  <button
                    className="favorite-card__media"
                    onClick={() => onNavigate(`/menu-item/${item.id}`)}
                    type="button"
                  >
                    <img
                      alt={item.name}
                      loading="lazy"
                      src={item.image_url ?? createPlaceholderImage(item.name)}
                    />
                  </button>
                  <div className="favorite-card__body">
                    <div className="favorite-card__top">
                      <div>
                        <div className="favorite-card__badges">
                          <span className={`food-dot ${item.is_veg ? 'food-dot--veg' : 'food-dot--nonveg'}`} />
                          <span className="chip chip--muted">{item.category}</span>
                          {unavailable ? <span className="chip chip--muted">Unavailable</span> : null}
                        </div>
                        <h3>{item.name}</h3>
                        <button
                          className="favorite-card__restaurant"
                          onClick={() => onNavigate(`/restaurant/${item.restaurant_id}`)}
                          type="button"
                        >
                          {item.restaurant_name}
                        </button>
                      </div>
                      <button
                        className="favorite-card__remove"
                        disabled={isFavoritePending(item.id)}
                        onClick={async () => {
                          try {
                            await toggleFavorite({ menuItemId: item.id, shouldFavorite: false });
                            onToast('Removed from favorites', `${item.name} has been removed.`, 'info');
                          } catch (nextError) {
                            const message =
                              nextError instanceof ApiError
                                ? nextError.message
                                : 'Unable to update favorites right now.';
                            onToast('Favorites unavailable', message, 'error');
                          }
                        }}
                        type="button"
                      >
                        Remove
                      </button>
                    </div>
                    <p>{item.description ?? 'Saved for the next time this craving shows up.'}</p>
                    <div className="favorite-card__footer">
                      <div>
                        <strong>{formatCurrency(item.price)}</strong>
                        <span>{unavailable ? 'Currently unavailable' : 'Available to order'}</span>
                      </div>
                      <button
                        className="primary-button primary-button--small"
                        disabled={unavailable}
                        onClick={() => {
                          if (isCustomizableMenuItem(item)) {
                            onNavigate(`/menu-item/${item.id}`);
                            return;
                          }
                          void requestAddToCart({
                            menuItem: item,
                            restaurantId: item.restaurant_id,
                            restaurantName: item.restaurant_name,
                            restaurantLocationId: item.restaurant_location_id,
                            restaurantLocationName: item.restaurant_location_name,
                          });
                        }}
                        type="button"
                      >
                        Add to cart
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
