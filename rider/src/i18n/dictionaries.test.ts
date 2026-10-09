import { en } from './en';
import { gu } from './gu';
import { hi } from './hi';

const placeholders = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort();

describe.each([
  ['Hindi', hi],
  ['Gujarati', gu],
])('the %s dictionary', (_name, dict) => {
  it('translates every English sentence', () => {
    expect(Object.keys(dict).sort()).toEqual(Object.keys(en).sort());
  });

  it('keeps every {value} the English sentence has', () => {
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect([key, placeholders(dict[key])]).toEqual([key, placeholders(en[key])]);
    }
  });

  it('has no empty sentence', () => {
    for (const [key, value] of Object.entries(dict)) {
      expect([key, value.trim().length > 0]).toEqual([key, true]);
    }
  });
});
