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
    expect(THEME_OPTIONS.every(o => o.label.length > 0)).toBe(true);
  });
});
