import { en, gu, hi } from '@/i18n/strings';
import { decodePreference, resolveMode, THEME_OPTIONS } from './preference';

describe('the appearance choice', () => {
  it('follows the phone when set to system', () => {
    expect(resolveMode('system', 'light')).toBe('light');
    expect(resolveMode('system', 'dark')).toBe('dark');
    // No answer from the phone means dark: the map-first default.
    expect(resolveMode('system', null)).toBe('dark');
  });

  it('ignores the phone when the rider chose', () => {
    expect(resolveMode('light', 'dark')).toBe('light');
    expect(resolveMode('dark', 'light')).toBe('dark');
  });

  it('reads only the three known values from storage', () => {
    expect(decodePreference('light')).toBe('light');
    expect(decodePreference('dark')).toBe('dark');
    expect(decodePreference('system')).toBe('system');
    expect(decodePreference(null)).toBe('system');
    expect(decodePreference('blue')).toBe('system');
  });

  it('offers system, light and dark, each with a label', () => {
    expect(THEME_OPTIONS.map(o => o.key)).toEqual(['system', 'light', 'dark']);
    for (const dict of [en, hi, gu]) {
      expect(THEME_OPTIONS.every(o => dict[o.labelKey].length > 0)).toBe(true);
      expect(THEME_OPTIONS.every(o => dict[o.hintKey].length > 0)).toBe(true);
    }
  });
});
