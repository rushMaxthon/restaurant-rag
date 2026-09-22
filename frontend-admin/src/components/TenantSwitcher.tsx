import { ArrowRight, Check, ChevronDown, Layers, Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useAdminStore } from '../hooks/useAdminStore';
import type { TenantSummary } from '../types/app';

/**
 * Which restaurant the operator is working on — and, while they are, whose
 * panel this is.
 *
 * It replaces the sidebar's brand block rather than sitting underneath it.
 * The first version was a labelled `<select>` bolted below the logo, which
 * put two identity blocks on top of each other and made the most important
 * control in the panel look like a form field. A workspace switcher is not a
 * filter: it is the panel's own identity, so it takes the place where the
 * identity already was.
 *
 * When a restaurant is picked the avatar takes that restaurant's brand colour
 * and a hairline of it runs along the top of the rail — ambient rather than
 * stated, so an operator three screens deep still knows whose data they are
 * changing without reading a label.
 *
 * ADMIN only. An owner has exactly one restaurant and the backend scopes them
 * to it whatever any client asks, so they get the plain brand block instead —
 * this returns null and `Sidebar` renders it.
 */
interface TenantSwitcherProps {
  onNavigate: (path: string) => void;
  /** Closes the mobile drawer once a choice is made inside it. */
  onPicked?: () => void;
}

/** Above this many, hunting beats reading, so the menu grows a search field. */
const SEARCH_THRESHOLD = 6;

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return '··';
  }
  const first = parts[0][0] ?? '';
  const second = parts.length > 1 ? (parts[1][0] ?? '') : (parts[0][1] ?? '');
  return `${first}${second}`.toUpperCase();
}

function branchesOf(tenant: TenantSummary): string {
  return `${tenant.location_count} branch${tenant.location_count === 1 ? '' : 'es'}`;
}

/**
 * What sits under the tenant's name in the MENU, which is 296px wide and can
 * afford the city. The trigger lives in a 220px rail and gets the branch
 * count alone — "Ahmedabad · 3 branches" arrived there as "3 branc…", and a
 * word cut in half looks careless in a way that saying less does not.
 */
function subtitleOf(tenant: TenantSummary): string {
  return tenant.city ? `${tenant.city} · ${branchesOf(tenant)}` : branchesOf(tenant);
}

export function TenantSwitcher({ onNavigate, onPicked }: TenantSwitcherProps) {
  // Read, not fetched. This component used to load the tenant list for
  // itself while the store loaded the same list for its currencies, so every
  // admin page made two identical requests for it.
  const { role, activeRestaurantId, setActiveRestaurantId, tenants, tenantsLoaded } =
    useAdminStore();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const wrapRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Click-away and Escape. A menu, not a dialog: it should not trap focus or
  // lock the page behind it.
  useEffect(() => {
    if (!open) {
      return;
    }
    searchRef.current?.focus();
    const onPointerDown = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const withRestaurant = useMemo(
    () => tenants.filter((tenant) => tenant.restaurant_id !== null),
    [tenants],
  );
  const active = withRestaurant.find((tenant) => tenant.restaurant_id === activeRestaurantId);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) {
      return withRestaurant;
    }
    return withRestaurant.filter((tenant) =>
      [tenant.display_name, tenant.city, tenant.cuisine_type, tenant.app_key]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(needle),
    );
  }, [query, withRestaurant]);

  if (role !== 'ADMIN') {
    return null;
  }

  const accent = active?.brand_primary_color ?? null;

  function choose(restaurantId: string | null): void {
    setActiveRestaurantId(restaurantId);
    setOpen(false);
    setQuery('');
    onPicked?.();
  }

  return (
    <div
      className={active ? 'workspace workspace--scoped' : 'workspace'}
      ref={wrapRef}
      style={accent ? ({ '--tenant-accent': accent } as React.CSSProperties) : undefined}
    >
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={
          active ? `Working on ${active.display_name}. Switch restaurant` : 'Switch restaurant'
        }
        className="workspace__trigger"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span className="workspace__avatar">
          {active ? initialsOf(active.display_name) : 'RR'}
        </span>
        <span className="workspace__copy">
          <strong>{active ? active.display_name : 'Restaurant RAG'}</strong>
          <span>
            {active
              ? branchesOf(active)
              : tenantsLoaded
                ? `${withRestaurant.length} restaurant${withRestaurant.length === 1 ? '' : 's'}`
                : 'Every restaurant'}
          </span>
        </span>
        <ChevronDown
          className={open ? 'workspace__chevron workspace__chevron--open' : 'workspace__chevron'}
          size={15}
          strokeWidth={2.4}
        />
      </button>

      {open ? (
        <div className="workspace__menu" role="menu">
          {withRestaurant.length > SEARCH_THRESHOLD ? (
            <div className="workspace__search">
              <Search size={14} strokeWidth={2.2} />
              <input
                aria-label="Find a restaurant"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Find a restaurant"
                ref={searchRef}
                type="search"
                value={query}
              />
            </div>
          ) : null}

          <div className="workspace__list">
            <button
              className="workspace__item"
              onClick={() => choose(null)}
              role="menuitem"
              type="button"
            >
              <span className="workspace__item-avatar workspace__item-avatar--all">
                <Layers size={13} strokeWidth={2.3} />
              </span>
              <span className="workspace__item-copy">
                <strong>All restaurants</strong>
                <span>Everything on the platform</span>
              </span>
              {activeRestaurantId === null ? <Check size={15} strokeWidth={2.8} /> : null}
            </button>

            {matches.map((tenant) => (
              <button
                className="workspace__item"
                key={tenant.id}
                onClick={() => choose(tenant.restaurant_id)}
                role="menuitem"
                style={
                  tenant.brand_primary_color
                    ? ({ '--tenant-accent': tenant.brand_primary_color } as React.CSSProperties)
                    : undefined
                }
                type="button"
              >
                <span className="workspace__item-avatar">{initialsOf(tenant.display_name)}</span>
                <span className="workspace__item-copy">
                  <strong>{tenant.display_name}</strong>
                  <span>
                    {/* Suspended and offboarded tenants stay in the list,
                        labelled. They are exactly the ones somebody needs to
                        look at, and hiding them would make a storefront that
                        is down harder to find, not easier. */}
                    {tenant.status === 'ACTIVE' ? subtitleOf(tenant) : null}
                    {tenant.status !== 'ACTIVE' ? (
                      <em className="workspace__flag">
                        {tenant.status === 'SUSPENDED' ? 'Suspended' : 'Offboarded'}
                      </em>
                    ) : null}
                  </span>
                </span>
                {tenant.restaurant_id === activeRestaurantId ? (
                  <Check size={15} strokeWidth={2.8} />
                ) : null}
              </button>
            ))}

            {matches.length === 0 ? (
              <p className="workspace__empty">
                {withRestaurant.length > 0
                  ? `Nothing matches “${query.trim()}”.`
                  : tenantsLoaded
                    ? 'No restaurants onboarded yet.'
                    : 'Loading restaurants…'}
              </p>
            ) : null}
          </div>

          <button
            className="workspace__footer"
            onClick={() => {
              setOpen(false);
              onNavigate('/tenants');
              onPicked?.();
            }}
            role="menuitem"
            type="button"
          >
            Manage tenants
            <ArrowRight size={13} strokeWidth={2.4} />
          </button>
        </div>
      ) : null}
    </div>
  );
}
