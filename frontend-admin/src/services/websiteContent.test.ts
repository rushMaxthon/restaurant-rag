import { describe, expect, it } from 'vitest';

import {
  COPY_KEYS,
  changedCopy,
  EMPTY_FAQ,
  EMPTY_SECTION,
  faqProblem,
  moveRow,
  sectionProblem,
  usableFaqs,
  usableSections,
  usableHighlights,
  usableSpecialities,
  highlightProblem,
  yearProblem,
} from './websiteContent';
import type { StorefrontCopyKey } from '../types/app';

const LIMITS = { heading: 80, body: 1200, bullet: 180, question: 180, answer: 1200 };

function copy(overrides: Partial<Record<StorefrontCopyKey, string>> = {}) {
  const base = {} as Record<StorefrontCopyKey, string>;
  for (const key of COPY_KEYS) base[key] = `stored ${key}`;
  return { ...base, ...overrides };
}

describe('only the fields actually edited are sent', () => {
  /**
   * The failure this guards is quiet and permanent. The GET answers with every
   * key filled in — written values AND derived defaults — so a form that posts
   * all of them back turns every derived default into a value the owner
   * "wrote". Rename the restaurant afterwards and the page title keeps the old
   * name, with nothing on screen to say why.
   */
  it('sends nothing when nothing was touched', () => {
    const loaded = copy();
    expect(changedCopy(loaded, { ...loaded })).toEqual({});
  });

  it('sends only the field that changed', () => {
    const loaded = copy();
    const draft = { ...loaded, hero_headline: 'Baked fresh at four' };
    expect(changedCopy(loaded, draft)).toEqual({ hero_headline: 'Baked fresh at four' });
  });

  it('does not count whitespace as an edit', () => {
    // Tabbing through a field should not customize it.
    const loaded = copy({ meta_title: 'Bhagwati Bakery' });
    const draft = copy({ meta_title: '  Bhagwati Bakery  ' });
    expect(changedCopy(loaded, draft)).toEqual({});
  });

  it('sends an empty string when a field is cleared, which restores the default', () => {
    const loaded = copy({ hero_subcopy: 'Something the owner wrote' });
    const draft = copy({ hero_subcopy: '' });
    expect(changedCopy(loaded, draft)).toEqual({ hero_subcopy: '' });
  });
});

describe('blank rows are an editor state, not a mistake', () => {
  it('drops a wholly empty section rather than saving it', () => {
    expect(usableSections([EMPTY_SECTION])).toEqual([]);
  });

  it('keeps a section with bullets but no body', () => {
    const kept = usableSections([{ heading: 'What we do', body: '', bullets: ['Cakes', ' '] }]);
    expect(kept).toEqual([{ heading: 'What we do', body: '', bullets: ['Cakes'] }]);
  });

  it('drops a heading with nothing under it', () => {
    expect(usableSections([{ heading: 'Overview', body: '  ', bullets: [] }])).toEqual([]);
  });

  it('drops half a question-and-answer pair', () => {
    expect(usableFaqs([{ question: 'Vegan cakes?', answer: '' }])).toEqual([]);
    expect(usableFaqs([{ question: '', answer: 'Yes.' }])).toEqual([]);
  });

  it('says nothing is wrong with a blank row', () => {
    // Marking an empty row red the moment it appears is hostile.
    expect(sectionProblem(EMPTY_SECTION, LIMITS)).toBeNull();
    expect(faqProblem(EMPTY_FAQ, LIMITS)).toBeNull();
  });
});

describe('a half-filled row says what is missing', () => {
  it('asks for a heading', () => {
    expect(sectionProblem({ heading: '', body: 'Words.', bullets: [] }, LIMITS)).toMatch(/heading/i);
  });

  it('asks for something under the heading', () => {
    expect(sectionProblem({ heading: 'Overview', body: '', bullets: [] }, LIMITS)).toMatch(
      /words or a bullet/i,
    );
  });

  it('names the limit rather than just refusing', () => {
    const long = { heading: 'x'.repeat(81), body: 'y', bullets: [] };
    expect(sectionProblem(long, LIMITS)).toContain('80');
  });

  it('will not publish a question with no answer', () => {
    expect(faqProblem({ question: 'Do you deliver?', answer: '' }, LIMITS)).toMatch(/oversight/i);
  });
});

describe('rows can be reordered', () => {
  it('moves a row down', () => {
    expect(moveRow(['a', 'b', 'c'], 0, 1)).toEqual(['b', 'a', 'c']);
  });

  it('moves a row up', () => {
    expect(moveRow(['a', 'b', 'c'], 2, -1)).toEqual(['a', 'c', 'b']);
  });

  it('does nothing at either end, rather than wrapping around', () => {
    const rows = ['a', 'b', 'c'];
    expect(moveRow(rows, 0, -1)).toBe(rows);
    expect(moveRow(rows, 2, 1)).toBe(rows);
  });

  it('leaves the original array alone', () => {
    const rows = ['a', 'b'];
    moveRow(rows, 0, 1);
    expect(rows).toEqual(['a', 'b']);
  });
});

/**
 * The facts above the fold: the year, the specialities, the figures.
 *
 * Added for a storefront whose home page had three paragraphs and nothing a
 * customer could take in at a glance — while every listing site in Surat led
 * with the one thing it did not say: trading since 1999.
 */
describe('the facts above the fold', () => {
  const limits = {
    highlight_value: 24,
    highlight_label: 60,
    highlight_note: 60,
    earliest_year: 1800,
  };

  it('accepts a four-digit year and nothing else', () => {
    expect(yearProblem('1999', limits)).toBeNull();
    expect(yearProblem('  1999  ', limits)).toBeNull();
    expect(yearProblem('99', limits)).toMatch(/four-digit/);
    expect(yearProblem('nineteen', limits)).toMatch(/four-digit/);
  });

  it('says nothing about an empty box, which is the owner clearing it', () => {
    expect(yearProblem('', limits)).toBeNull();
    expect(yearProblem('   ', limits)).toBeNull();
  });

  it('refuses a year that cannot be true', () => {
    expect(yearProblem('1700', limits)).toMatch(/between/);
    expect(yearProblem(String(new Date().getFullYear() + 1), limits)).toMatch(/between/);
  });

  it('allows the current year, because restaurants open', () => {
    expect(yearProblem(String(new Date().getFullYear()), limits)).toBeNull();
  });

  it('keeps only the specialities with something in them', () => {
    expect(usableSpecialities([' Khari ', '', '   ', 'Nankhatai'])).toEqual([
      'Khari',
      'Nankhatai',
    ]);
  });

  it('keeps only the highlights with both halves', () => {
    // A figure with no caption says nothing; a caption with no figure is a
    // tile with a hole in it. The storefront drops both, so the editor does.
    expect(
      usableHighlights([
        { value: '4.6', label: '' },
        { value: '', label: 'Rated' },
        { value: ' 4.6 ', label: ' Rated ', note: ' 85 on JustDial ' },
      ]),
    ).toEqual([{ value: '4.6', label: 'Rated', note: '85 on JustDial' }]);
  });

  it('treats a wholly empty row as mid-typing rather than an error', () => {
    expect(highlightProblem({ value: '', label: '', note: '' }, limits)).toBeNull();
  });

  it('says which half of a started row is missing', () => {
    expect(highlightProblem({ value: '4.6', label: '' }, limits)).toMatch(/caption/);
    expect(highlightProblem({ value: '', label: 'Rated' }, limits)).toMatch(/figure/);
  });

  it('holds each box to its own limit', () => {
    expect(highlightProblem({ value: 'x'.repeat(25), label: 'Rated' }, limits)).toMatch(/figure/);
    expect(highlightProblem({ value: '4.6', label: 'y'.repeat(61) }, limits)).toMatch(/caption/);
    expect(
      highlightProblem({ value: '4.6', label: 'Rated', note: 'z'.repeat(61) }, limits),
    ).toMatch(/source/);
  });
});
