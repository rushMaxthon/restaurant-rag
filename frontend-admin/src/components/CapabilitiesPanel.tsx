import { RotateCcw, ShieldOff } from 'lucide-react';
import { useEffect, useState } from 'react';

import { StatePanel } from './StatePanel';
import { ApiError, api, formatDate } from '../services/api';
import type { RestaurantCapability, UserRole } from '../types/app';

/**
 * What this restaurant has switched on, and why.
 *
 * The reason is the whole point. A per-restaurant allowlist existed in this
 * codebase and was deliberately deleted; `config/capabilities.py` carries the
 * note in full, but the short version is that it became a permanent split
 * where one restaurant got a feature, everyone else got less, and **nothing
 * on screen explained why**. A toggle with no explanation beside it would
 * rebuild exactly that.
 *
 * So every row says what it does in the owner's words, whether the platform
 * has decided anything, who decided, and when. An owner can read this screen
 * — deliberately: somebody who cannot see what they have cannot ask for what
 * they do not.
 */
interface CapabilitiesPanelProps {
  token: string;
  restaurantId: string;
  role: UserRole;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

export function CapabilitiesPanel({
  token,
  restaurantId,
  role,
  onToast,
}: CapabilitiesPanelProps) {
  const [rows, setRows] = useState<RestaurantCapability[]>([]);
  // Starts true and is only ever cleared. Setting it back to true at the top
  // of the effect below was a synchronous setState in an effect body, and it
  // bought nothing: the first render already says "loading", and on a switch
  // to another restaurant keeping the previous list on screen for a moment
  // reads better than a flash of skeletons.
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const isAdmin = role === 'ADMIN';

  useEffect(() => {
    let cancelled = false;
    void api
      .getRestaurantCapabilities(token, restaurantId)
      .then((loaded) => {
        if (!cancelled) {
          setRows(loaded);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof ApiError ? caught.message : 'Could not load features');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [restaurantId, token]);

  async function change(key: string, enabled: boolean | null): Promise<void> {
    setBusyKey(key);
    try {
      const updated = await api.setRestaurantCapability(token, restaurantId, key, { enabled });
      setRows(updated);
      const row = updated.find((entry) => entry.key === key);
      onToast(
        row ? `${row.label} is ${row.enabled ? 'on' : 'off'}` : 'Feature updated',
        enabled === null
          ? 'Back to the platform default for this feature.'
          : 'Customers see the change on their next page load.',
        'success',
      );
    } catch (caught: unknown) {
      onToast(
        'Could not change this feature',
        caught instanceof ApiError ? caught.message : 'Something went wrong',
        'error',
      );
    } finally {
      setBusyKey(null);
    }
  }

  if (loading) {
    return (
      <div className="capability-list">
        <span className="skeleton capability-skeleton" />
        <span className="skeleton capability-skeleton" />
      </div>
    );
  }

  if (error) {
    return (
      <StatePanel
        description={error}
        icon={ShieldOff}
        title="Features didn't load"
        tone="error"
      />
    );
  }

  return (
    <div className="capability-list">
      {rows.map((row) => (
        <article
          className={row.enabled ? 'capability' : 'capability capability--off'}
          key={row.key}
        >
          <div className="capability__copy">
            <div className="capability__title">
              <strong>{row.label}</strong>
              <span className={`status-pill status-pill--${row.enabled ? 'success' : 'muted'}`}>
                {row.enabled ? 'On' : 'Off'}
              </span>
            </div>
            <p>{row.owner_description}</p>
            {/* Never just "off". This line is the difference between this and
                the allowlist it replaced. */}
            <p className="capability__why">
              {row.explanation}
              {row.granted_by && row.granted_at ? (
                <>
                  {' '}
                  <span className="capability__actor">
                    {row.granted_by} · {formatDate(row.granted_at)}
                  </span>
                </>
              ) : null}
            </p>
            {row.note ? <p className="capability__note">“{row.note}”</p> : null}
          </div>

          {isAdmin ? (
            <div className="capability__actions">
              <button
                className={row.enabled ? 'secondary-button' : 'primary-button'}
                disabled={busyKey === row.key || row.reason === 'build_flag_off'}
                onClick={() => void change(row.key, !row.enabled)}
                type="button"
              >
                {row.enabled ? 'Turn off' : 'Turn on'}
              </button>
              {/* Distinct from turning it off: "treat this restaurant like
                  everyone else", so it follows the default if that changes. */}
              {row.is_customized ? (
                <button
                  className="capability__reset"
                  disabled={busyKey === row.key}
                  onClick={() => void change(row.key, null)}
                  title="Follow the platform default"
                  type="button"
                >
                  <RotateCcw size={13} strokeWidth={2.2} />
                  Use default
                </button>
              ) : null}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}
