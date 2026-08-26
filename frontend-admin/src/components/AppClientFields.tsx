import {
  BRAND_COLOR_PATTERN,
  DEFAULT_BRAND_PRIMARY_COLOR,
  type AppClientFormErrors,
  type AppClientFormValues,
  type DerivedAppClientField,
} from '../services/appClient';
import type { AppMode } from '../types/app';

interface AppClientFieldsProps {
  values: AppClientFormValues;
  errors: AppClientFormErrors;
  /** Called for fields that auto-derive from the restaurant name. */
  onDerivedFieldChange: (field: DerivedAppClientField, value: string) => void;
  onFieldChange: <Field extends keyof AppClientFormValues>(
    field: Field,
    value: AppClientFormValues[Field],
  ) => void;
  disabled?: boolean;
}

export function AppClientFields({
  values,
  errors,
  onDerivedFieldChange,
  onFieldChange,
  disabled = false,
}: AppClientFieldsProps) {
  return (
    <>
      <label className={`field${errors.app_key ? ' field--invalid' : ''}`}>
        <span>App Key</span>
        <input
          disabled={disabled}
          placeholder="spice_route"
          required
          value={values.app_key}
          onChange={(event) => onDerivedFieldChange('app_key', event.target.value.toLowerCase())}
        />
        <small className={errors.app_key ? 'field__error' : 'hint-text'}>
          {errors.app_key ?? 'Unique lowercase slug used to identify this app.'}
        </small>
      </label>
      <label className="field">
        <span>App Mode</span>
        <select
          disabled={disabled}
          required
          value={values.app_mode}
          onChange={(event) => onFieldChange('app_mode', event.target.value as AppMode)}
        >
          <option value="SINGLE_RESTAURANT">Single Restaurant</option>
          <option value="MARKETPLACE">Marketplace</option>
        </select>
        <small className="hint-text">
          {values.app_mode === 'MARKETPLACE'
            ? 'App browses every restaurant on the platform.'
            : 'App serves only this restaurant.'}
        </small>
      </label>
      <label className={`field${errors.ios_bundle_id ? ' field--invalid' : ''}`}>
        <span>iOS Bundle ID</span>
        <input
          disabled={disabled}
          placeholder="com.quickbite.spiceroute"
          required
          value={values.ios_bundle_id}
          onChange={(event) => onDerivedFieldChange('ios_bundle_id', event.target.value)}
        />
        <small className={errors.ios_bundle_id ? 'field__error' : 'hint-text'}>
          {errors.ios_bundle_id ?? 'Must be unique across all apps.'}
        </small>
      </label>
      <label className={`field${errors.android_package_name ? ' field--invalid' : ''}`}>
        <span>Android Package Name</span>
        <input
          disabled={disabled}
          placeholder="com.quickbite.spiceroute"
          required
          value={values.android_package_name}
          onChange={(event) => onDerivedFieldChange('android_package_name', event.target.value)}
        />
        <small className={errors.android_package_name ? 'field__error' : 'hint-text'}>
          {errors.android_package_name ?? 'Usually the same as the iOS bundle ID.'}
        </small>
      </label>
      <label className={`field${errors.order_number_prefix ? ' field--invalid' : ''}`}>
        <span>Order Number Prefix</span>
        <input
          disabled={disabled}
          maxLength={8}
          placeholder="SR"
          required
          value={values.order_number_prefix}
          onChange={(event) => onDerivedFieldChange('order_number_prefix', event.target.value.toUpperCase())}
        />
        <small className={errors.order_number_prefix ? 'field__error' : 'hint-text'}>
          {errors.order_number_prefix ?? 'Prefixes order numbers, e.g. SR-1042.'}
        </small>
      </label>
      <label className={`field${errors.minimum_supported_version ? ' field--invalid' : ''}`}>
        <span>Minimum Supported Version</span>
        <input
          disabled={disabled}
          placeholder="1.0.0"
          required
          value={values.minimum_supported_version}
          onChange={(event) => onFieldChange('minimum_supported_version', event.target.value)}
        />
        <small className={errors.minimum_supported_version ? 'field__error' : 'hint-text'}>
          {errors.minimum_supported_version ?? 'Older app builds are asked to update.'}
        </small>
      </label>
      <label className={`field form-grid__wide${errors.brand_primary_color ? ' field--invalid' : ''}`}>
        <span>Brand Primary Color</span>
        <div className="color-field__row">
          <input
            aria-label="Pick brand primary colour"
            disabled={disabled}
            type="color"
            value={
              BRAND_COLOR_PATTERN.test(values.brand_primary_color)
                ? values.brand_primary_color
                : DEFAULT_BRAND_PRIMARY_COLOR
            }
            onChange={(event) => onFieldChange('brand_primary_color', event.target.value.toUpperCase())}
          />
          <input
            aria-label="Brand primary colour hex value"
            disabled={disabled}
            maxLength={7}
            placeholder="#FF5200"
            required
            type="text"
            value={values.brand_primary_color}
            onChange={(event) => onFieldChange('brand_primary_color', event.target.value.toUpperCase())}
          />
        </div>
        <small className={errors.brand_primary_color ? 'field__error' : 'hint-text'}>
          {errors.brand_primary_color ?? 'Primary accent colour for the branded app.'}
        </small>
      </label>
    </>
  );
}
