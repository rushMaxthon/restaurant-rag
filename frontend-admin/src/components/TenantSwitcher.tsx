import { Building2, Check, ChevronsUpDown, Layers } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { useAdminStore } from '../hooks/useAdminStore';
import { api } from '../services/api';
import {
  getPageSnapshot,
  setPageSnapshot,
  tokenScope,
} from '../services/pageCache';
import type { TenantSummary } from '../types/app';

/**
 * Which restaurant the operator is working on, decided once.
 *
 * Four screens each used to keep their own answer — the AI Manager in its own
 * localStorage key, Reports, Offers and Generated Combos each in a `<select>`
 * that reset on navigation — so moving between them meant re-picking the same
 * restaurant up to four times, and two screens could be showing two different
 * restaurants at once with nothing on either saying so.
 *
 * ADMIN only. An owner has exactly one restaurant and the backend scopes them
 * to it whatever any client asks for, so a switcher would be furniture.
 *
 * Suspended and offboarded tenants stay in the list, labelled. They are
 * exactly the ones somebody needs to look at.
 */
interface TenantSwitcherProps {
  /** Closes the mobile drawer when a choice is made inside it. */
  onPicked?: () => void;
}

function tenantsCacheKey(scope: string): string {
  return `platform-tenants:${scope}`;
}

export function TenantSwitcher({ onPicked }: TenantSwitcherProps) {
  const { token, role, activeRestaurantId, setActiveRestaurantId } = useAdminStore();
  const scope = tokenScope(token ?? '');

  // Shares the Tenants page's cache entry, so opening one warms the other and
  // a lifecycle change made there is reflected here without a second fetch.
  const [tenants, setTenants] = useState<TenantSummary[]>(
    () => getPageSnapshot<TenantSummary[]>(tenantsCacheKey(scope)) ?? [],
  );
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!token || role !== 'ADMIN') {
      return;
    }
    let cancelled = false;
    void api
      .listTenants(token)
      .then((rows) => {
        if (cancelled) {
          return;
        }
        setTenants(rows);
        setPageSnapshot(tenantsCacheKey(scope), rows);
      })
      .catch(() => {
        // The switcher is navigation, not data. A failure here leaves the
        // panel on whatever scope it already had rather than interrupting
        // whatever the operator came to do.
      });
    return () => {
      cancelled = true;
    };
  }, [role, scope, token]);

  // Click-away and Escape, because this is a menu rather than a dialog: it
  // should not trap focus or lock the page behind it.
  useEffect(() => {
    if (!open) {
      return;
    }
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

  if (role !== 'ADMIN') {
    return null;
  }

  const withRestaurant = tenants.filter((tenant) => tenant.restaurant_id !== null);
  const active = withRestaurant.find((tenant) => tenant.restaurant_id === activeRestaurantId);

  function pick(restaurantId: string | null): void {
    setActiveRestaurantId(restaurantId);
    setOpen(false);
    onPicked?.();
  }

  return (
    <div className="tenant-switcher" ref={wrapRef}>
      <button
        aria-expanded={open}
        aria-haspopup="listbox"
        className="tenant-switcher__trigger"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span
          className="tenant-switcher__mark"
          style={
            active?.brand_primary_color
              ? { background: active.brand_primary_color }
              : undefined
          }
        >
          {active ? <Building2 size={13} strokeWidth={2.2} /> : <Layers size={13} strokeWidth={2.2} />}
        </span>
        <span className="tenant-switcher__copy">
          <span className="tenant-switcher__label">Working on</span>
          <strong>{active ? active.display_name : 'All restaurants'}</strong>
        </span>
        <ChevronsUpDown size={14} strokeWidth={2.2} />
      </button>

      {open ? (
        <div className="tenant-switcher__menu" role="listbox">
          <button
            aria-selected={activeRestaurantId === null}
            className="tenant-switcher__option"
            onClick={() => pick(null)}
            role="option"
            type="button"
          >
            <span className="tenant-switcher__option-copy">
              <strong>All restaurants</strong>
              <span>Everything on the platform</span>
            </span>
            {activeRestaurantId === null ? <Check size={14} strokeWidth={2.6} /> : null}
          </button>

          {withRestaurant.map((tenant) => (
            <button
              aria-selected={tenant.restaurant_id === activeRestaurantId}
              className="tenant-switcher__option"
              key={tenant.id}
              onClick={() => pick(tenant.restaurant_id)}
              role="option"
              type="button"
            >
              <span
                className="tenant-switcher__dot"
                style={
                  tenant.brand_primary_color
                    ? { background: tenant.brand_primary_color }
                    : undefined
                }
              />
              <span className="tenant-switcher__option-copy">
                <strong>{tenant.display_name}</strong>
                <span>
                  {tenant.status === 'ACTIVE'
                    ? (tenant.city ?? tenant.app_key)
                    : tenant.status === 'SUSPENDED'
                      ? 'Suspended'
                      : 'Offboarded'}
                </span>
              </span>
              {tenant.restaurant_id === activeRestaurantId ? (
                <Check size={14} strokeWidth={2.6} />
              ) : null}
            </button>
          ))}

          {withRestaurant.length === 0 ? (
            <p className="tenant-switcher__empty">No restaurants onboarded yet.</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
