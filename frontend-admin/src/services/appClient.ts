import type { AppClient, AppMode } from '../types/app';

export const BUNDLE_ID_NAMESPACE = 'com.quickbite';
export const DEFAULT_BRAND_PRIMARY_COLOR = '#E23744';
export const DEFAULT_MINIMUM_SUPPORTED_VERSION = '1.0.0';

export const APP_KEY_PATTERN = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/;
export const BUNDLE_ID_PATTERN = /^[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*)+$/;
export const ORDER_NUMBER_PREFIX_PATTERN = /^[A-Z][A-Z0-9]{1,7}$/;
export const BRAND_COLOR_PATTERN = /^#[0-9A-F]{6}$/;
export const APP_VERSION_PATTERN = /^\d+\.\d+\.\d+$/;

export interface AppClientFormValues {
  app_key: string;
  app_mode: AppMode;
  ios_bundle_id: string;
  android_package_name: string;
  order_number_prefix: string;
  brand_primary_color: string;
  minimum_supported_version: string;
}

export type AppClientFormErrors = Partial<Record<keyof AppClientFormValues, string>>;

/** Fields that auto-derive from the restaurant name until edited by hand. */
export type DerivedAppClientField =
  | 'app_key'
  | 'ios_bundle_id'
  | 'android_package_name'
  | 'order_number_prefix';

export const emptyAppClientForm: AppClientFormValues = {
  app_key: '',
  app_mode: 'SINGLE_RESTAURANT',
  ios_bundle_id: '',
  android_package_name: '',
  order_number_prefix: '',
  brand_primary_color: DEFAULT_BRAND_PRIMARY_COLOR,
  minimum_supported_version: DEFAULT_MINIMUM_SUPPORTED_VERSION,
};

export function toAppKey(restaurantName: string): string {
  const normalized = restaurantName
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  if (!normalized) {
    return '';
  }
  return (/^[a-z]/.test(normalized) ? normalized : `app_${normalized}`).slice(0, 64);
}

export function toBundleId(appKey: string): string {
  const segment = appKey.replace(/_/g, '');
  if (!segment) {
    return '';
  }
  return `${BUNDLE_ID_NAMESPACE}.${/^[a-z]/.test(segment) ? segment : `app${segment}`}`;
}

export function toOrderNumberPrefix(restaurantName: string): string {
  const words = restaurantName.split(/[^A-Za-z0-9]+/).filter(Boolean);
  const initials = words
    .map((word) => word[0])
    .filter((character) => /[A-Za-z]/.test(character))
    .join('')
    .toUpperCase();
  if (initials.length >= 2) {
    return initials.slice(0, 8);
  }

  const letters = restaurantName.replace(/[^A-Za-z]/g, '').toUpperCase();
  return letters.length >= 2 ? letters.slice(0, 4) : '';
}

/** Mirrors the validation the backend applies to the same fields. */
export function validateAppClientForm(values: AppClientFormValues): AppClientFormErrors {
  const errors: AppClientFormErrors = {};

  if (!APP_KEY_PATTERN.test(values.app_key)) {
    errors.app_key =
      'Use lowercase letters, numbers and underscores, starting with a letter (e.g. spice_route).';
  } else if (values.app_key.length > 64) {
    errors.app_key = 'App key must be 64 characters or fewer.';
  }

  if (!BUNDLE_ID_PATTERN.test(values.ios_bundle_id)) {
    errors.ios_bundle_id = 'Use reverse-domain form, e.g. com.quickbite.spiceroute.';
  }

  if (!BUNDLE_ID_PATTERN.test(values.android_package_name)) {
    errors.android_package_name = 'Use reverse-domain form, e.g. com.quickbite.spiceroute.';
  }

  if (!ORDER_NUMBER_PREFIX_PATTERN.test(values.order_number_prefix)) {
    errors.order_number_prefix = 'Use 2-8 uppercase letters or numbers, starting with a letter (e.g. SR).';
  }

  if (!BRAND_COLOR_PATTERN.test(values.brand_primary_color)) {
    errors.brand_primary_color = 'Use a 6-digit hex colour, e.g. #E23744.';
  }

  if (!APP_VERSION_PATTERN.test(values.minimum_supported_version)) {
    errors.minimum_supported_version = 'Use a three-part version, e.g. 1.0.0.';
  }

  return errors;
}

export function trimAppClientForm(values: AppClientFormValues): AppClientFormValues {
  return {
    app_key: values.app_key.trim(),
    app_mode: values.app_mode,
    ios_bundle_id: values.ios_bundle_id.trim(),
    android_package_name: values.android_package_name.trim(),
    order_number_prefix: values.order_number_prefix.trim(),
    brand_primary_color: values.brand_primary_color.trim().toUpperCase(),
    minimum_supported_version: values.minimum_supported_version.trim(),
  };
}

/**
 * Builds the edit form for an existing app client, falling back to derived or
 * default values for anything an older record never stored.
 */
export function toAppClientForm(
  appClient: AppClient | null,
  restaurantName: string,
): AppClientFormValues {
  if (!appClient) {
    const appKey = toAppKey(restaurantName);
    const bundleId = toBundleId(appKey);
    return {
      ...emptyAppClientForm,
      app_key: appKey,
      ios_bundle_id: bundleId,
      android_package_name: bundleId,
      order_number_prefix: toOrderNumberPrefix(restaurantName),
    };
  }

  const fallbackBundleId = appClient.ios_bundle_id ?? appClient.android_package_name ?? toBundleId(appClient.app_key);
  return {
    app_key: appClient.app_key,
    app_mode: appClient.app_mode,
    ios_bundle_id: appClient.ios_bundle_id ?? fallbackBundleId,
    android_package_name: appClient.android_package_name ?? fallbackBundleId,
    order_number_prefix: appClient.order_number_prefix,
    brand_primary_color: (appClient.brand_primary_color ?? DEFAULT_BRAND_PRIMARY_COLOR).toUpperCase(),
    minimum_supported_version: appClient.minimum_supported_version ?? DEFAULT_MINIMUM_SUPPORTED_VERSION,
  };
}
