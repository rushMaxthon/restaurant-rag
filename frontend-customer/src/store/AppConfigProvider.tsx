import {
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from 'react';
import { api } from '../services/api';
import type { AppConfig } from '../types/app';
import { AppConfigContext, type AppConfigValue } from './AppConfigContext';

const CACHE_KEY = 'restaurant-rag-customer-app-config';

function readCache(): AppConfig | null {
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    return raw ? (JSON.parse(raw) as AppConfig) : null;
  } catch {
    return null;
  }
}

/**
 * Resolves which branded app this is, once, at startup.
 *
 * The last successful config is cached and served immediately on the next load
 * so the app opens already wearing the restaurant's colour instead of flashing
 * the default orange while a request is in flight. The network result then
 * overwrites it, which is how an owner's colour change reaches a returning
 * visitor.
 *
 * A failed fetch is not an error state: the cached config stands, and with no
 * cache the app falls back to marketplace behaviour, which is what it did
 * before this existed.
 */
export function AppConfigProvider({ children }: PropsWithChildren) {
  const [config, setConfig] = useState<AppConfig | null>(readCache);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getAppConfig(controller.signal)
      .then((resolved) => {
        setConfig(resolved);
        try {
          window.localStorage.setItem(CACHE_KEY, JSON.stringify(resolved));
        } catch {
          // Caching is an optimisation; a full quota must not break startup.
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (!controller.signal.aborted) {
          setReady(true);
        }
      });
    return () => controller.abort();
  }, []);

  const value = useMemo<AppConfigValue>(() => {
    const isSingleRestaurant =
      config?.app_mode === 'SINGLE_RESTAURANT' && Boolean(config.restaurant_id);
    return {
      config,
      restaurantId: isSingleRestaurant ? (config?.restaurant_id ?? null) : null,
      isSingleRestaurant,
      displayName: config?.display_name ?? 'QuickBite',
      brandColor: config?.branding?.primary_color ?? null,
      ready,
    };
  }, [config, ready]);

  return <AppConfigContext.Provider value={value}>{children}</AppConfigContext.Provider>;
}

