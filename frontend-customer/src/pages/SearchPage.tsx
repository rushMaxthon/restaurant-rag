import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppIcon } from '../components/AppIcon';
import { MenuGridCard } from '../components/app/MenuGridCard';
import { api, formatCurrency } from '../services/api';
import { useAppStore } from '../hooks/useAppStore';
import { useAppConfig } from '../store/useAppConfig';
import type { MenuItem } from '../types/app';
import { checkAuthAndRedirect } from '../utils/authRedirect';
import { isCustomizableMenuItem } from '../utils/menuItemCustomization';

interface SearchPageProps {
  token: string | null;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

/** What the phone offers before anything is typed. */
const SUGGESTIONS = ['Spicy', 'Under ₹200', 'Vegetarian', 'Noodles', 'Curry', 'Something sweet'];

const RECENTS_KEY = 'restaurant-rag-customer-recent-searches';

function readRecents(): string[] {
  try {
    const raw = window.localStorage.getItem(RECENTS_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : [];
  } catch {
    return [];
  }
}

/**
 * `mobile/src/screens/search/SearchScreen.tsx`, narrowed to one kitchen.
 *
 * The marketplace screen searches restaurants and dishes; here there is one
 * restaurant, so it searches its menu — matching name, description and section
 * the way the phone's own matcher does, and ranking a name hit above a
 * description hit so "curry" leads with the curries.
 */
export function SearchPage({ token, onNavigate, onToast }: SearchPageProps) {
  const {
    cart,
    isAuthenticated,
    requestAddToCart,
    setPendingAuthRedirectPath,
    updateCartQuantity,
  } = useAppStore();
  const { displayName, restaurantId } = useAppConfig();
  const [items, setItems] = useState<MenuItem[]>([]);
  const [query, setQuery] = useState('');
  const [vegOnly, setVegOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [recents, setRecents] = useState<string[]>(readRecents);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!restaurantId) {
      return;
    }
    let active = true;
    api
      .getMenuItems(restaurantId, token)
      .then((rows) => {
        if (active) {
          setItems(rows);
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [restaurantId, token]);

  const rememberSearch = useCallback((value: string) => {
    const term = value.trim();
    if (term.length < 2) {
      return;
    }
    setRecents((current) => {
      const next = [term, ...current.filter((entry) => entry.toLowerCase() !== term.toLowerCase())].slice(0, 6);
      try {
        window.localStorage.setItem(RECENTS_KEY, JSON.stringify(next));
      } catch {
        // Recents are a convenience; a full quota must not break search.
      }
      return next;
    });
  }, []);

  const results = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const pool = vegOnly ? items.filter((item) => item.is_veg) : items;
    if (!needle) {
      return pool;
    }
    // Name hits first, then section, then description — so the dish you typed
    // the name of is never below something that merely mentions it.
    const rank = (item: MenuItem) => {
      if (item.name.toLowerCase().includes(needle)) {
        return 0;
      }
      if ((item.category ?? '').toLowerCase().includes(needle)) {
        return 1;
      }
      if ((item.description ?? '').toLowerCase().includes(needle)) {
        return 2;
      }
      return 3;
    };
    return pool
      .map((item) => ({ item, rank: rank(item) }))
      .filter((entry) => entry.rank < 3)
      .sort((a, b) => a.rank - b.rank || a.item.name.localeCompare(b.item.name))
      .map((entry) => entry.item);
  }, [items, query, vegOnly]);

  const quantityFor = useCallback(
    (menuItemId: string) =>
      cart.items
        .filter((entry) => entry.menuItem.id === menuItemId)
        .reduce((total, entry) => total + entry.quantity, 0),
    [cart.items],
  );

  const handleAdd = useCallback(
    (item: MenuItem) => {
      const allowed = checkAuthAndRedirect({
        isAuthenticated,
        redirectPath: '/search',
        onNavigate,
        pushToast: onToast,
        setPendingAuthRedirectPath,
      });
      if (!allowed) {
        return;
      }
      if (isCustomizableMenuItem(item)) {
        onNavigate(`/menu-item/${item.id}`);
        return;
      }
      void requestAddToCart({
        menuItem: item,
        restaurantId: item.restaurant_id,
        restaurantName: displayName,
      });
    },
    [displayName, isAuthenticated, onNavigate, onToast, requestAddToCart, setPendingAuthRedirectPath],
  );

  const handleDecrease = useCallback(
    (menuItemId: string) => {
      const entry = [...cart.items].reverse().find((row) => row.menuItem.id === menuItemId);
      if (entry) {
        updateCartQuantity(entry.id, entry.quantity - 1);
      }
    },
    [cart.items, updateCartQuantity],
  );

  const showDiscovery = query.trim().length === 0;
  // The skeleton means "a request is in flight". With no restaurant to query
  // there is no request, so there is nothing to wait for.
  const showSkeleton = loading && Boolean(restaurantId);

  return (
    <div className="screen screen--flush search-screen">
      <div className="search-field">
        <AppIcon name="search" size={20} />
        <input
          aria-label={`Search ${displayName}`}
          onBlur={() => rememberSearch(query)}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={`Search ${displayName}`}
          ref={inputRef}
          type="search"
          value={query}
        />
        {query ? (
          <button aria-label="Clear search" onClick={() => setQuery('')} type="button">
            <AppIcon name="close" size={17} />
          </button>
        ) : null}
      </div>

      <div className="rail filter-rail">
        <button
          aria-pressed={vegOnly}
          className={vegOnly ? 'filter-chip filter-chip--active' : 'filter-chip'}
          onClick={() => setVegOnly((value) => !value)}
          type="button"
        >
          <span className="diet-badge diet-badge--veg" />
          Veg only
        </button>
        {SUGGESTIONS.map((suggestion) => (
          <button
            className="filter-chip"
            key={suggestion}
            onClick={() => {
              setQuery(suggestion);
              rememberSearch(suggestion);
            }}
            type="button"
          >
            {suggestion}
          </button>
        ))}
      </div>

      {showDiscovery && recents.length > 0 ? (
        <section className="section">
          <div className="section-header">
            <div className="section-header__copy">
              <h2 className="section-header__title">Recent searches</h2>
            </div>
            <button
              className="section-header__action"
              onClick={() => {
                setRecents([]);
                try {
                  window.localStorage.removeItem(RECENTS_KEY);
                } catch {
                  // Nothing to recover from: the list is already cleared on screen.
                }
              }}
              type="button"
            >
              Clear
            </button>
          </div>
          <div className="rail filter-rail">
            {recents.map((term) => (
              <button className="filter-chip" key={term} onClick={() => setQuery(term)} type="button">
                <AppIcon name="time" size={14} />
                {term}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <section className="section">
        <div className="section-header">
          <div className="section-header__copy">
            <h2 className="section-header__title">
              {showDiscovery ? 'The full menu' : `${results.length} ${results.length === 1 ? 'result' : 'results'}`}
            </h2>
            <p className="section-header__subtitle">
              {showDiscovery
                ? `Everything ${displayName} is serving right now.`
                : `Matching “${query.trim()}” on the ${displayName} menu.`}
            </p>
          </div>
        </div>

        {showSkeleton ? (
          <div className="dish-grid">
            {Array.from({ length: 6 }, (_, index) => (
              <div className="dish-tile dish-tile--skeleton" key={index} />
            ))}
          </div>
        ) : results.length > 0 ? (
          <div className="dish-grid">
            {results.map((item) => (
              <MenuGridCard
                item={item}
                key={item.id}
                onAdd={handleAdd}
                onDecrease={handleDecrease}
                onOpen={(itemId) => onNavigate(`/menu-item/${itemId}`)}
                quantity={quantityFor(item.id)}
              />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <p className="empty-state__title">Nothing matched “{query.trim()}”</p>
            <p className="empty-state__text">
              Try a shorter word, or browse the sections on the home screen. The kitchen has{' '}
              {items.length} {items.length === 1 ? 'dish' : 'dishes'} in total
              {vegOnly ? ', and the veg filter is on' : ''}.
            </p>
          </div>
        )}
      </section>

      {results.length > 0 && !showDiscovery ? (
        <p className="screen-footnote">
          Cheapest match {formatCurrency(Math.min(...results.map((item) => Number(item.price))))}.
        </p>
      ) : null}
    </div>
  );
}
