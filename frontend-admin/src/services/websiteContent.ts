/**
 * The rules behind the Website screen, kept out of the component.
 *
 * Same reason `kitchenStaff.ts` exists: a rule inside a form cannot be tested
 * without rendering the form, a store and a router, so it goes untested and
 * the first person to change it finds out in production.
 *
 * The trap this module exists to prevent is specific and silent.
 * `GET /restaurants/{id}/storefront` answers with every key FILLED IN —
 * whatever the owner wrote, or the default derived from the restaurant's name,
 * cuisine and city. A form that loads those values and sends them all back on
 * save turns all eight into values the owner "wrote", so they stop tracking
 * the restaurant's own details forever after. Rename the restaurant and the
 * page title keeps the old name, with nothing on screen to explain why.
 *
 * So `changedCopy` sends only the fields actually edited. The server's
 * `exclude_unset` does the rest.
 */

import type {
  BrandFaq,
  BrandHighlight,
  BrandSection,
  StorefrontCopyKey,
} from '../types/app';

export interface CopyField {
  key: StorefrontCopyKey;
  label: string;
  /** What this string is FOR, in the place the owner is deciding about it. */
  hint: string;
  /** Multi-line fields get a textarea; a page title must stay one line. */
  multiline: boolean;
}

/**
 * The eight strings, in the order somebody writing a website thinks about
 * them: what the page is called, then what it says, then the two screens that
 * borrow a sentence from it.
 *
 * Grouped rather than listed flat, because "the words in a search result" and
 * "the words on the page" are different jobs and an owner editing one is not
 * usually editing the other.
 */
export const COPY_GROUPS: { title: string; blurb: string; fields: CopyField[] }[] = [
  {
    title: 'On the page',
    blurb: 'What somebody reads when they arrive.',
    fields: [
      {
        key: 'hero_headline',
        label: 'Headline',
        hint: 'The first line on the home page. Your name, or a line you are known for.',
        multiline: false,
      },
      {
        key: 'hero_subcopy',
        label: 'Opening line',
        hint: 'One sentence under the headline saying what you cook and where.',
        multiline: true,
      },
    ],
  },
  {
    title: 'In a search result and a shared link',
    blurb:
      'What Google and WhatsApp show. These are read far more often than the page itself, and by people deciding whether to open it.',
    fields: [
      {
        key: 'meta_title',
        label: 'Search title',
        hint: 'Truncated past about 60 characters in a result.',
        multiline: false,
      },
      {
        key: 'meta_description',
        label: 'Search description',
        hint: 'Truncated past about 160 characters.',
        multiline: true,
      },
      {
        key: 'og_title',
        label: 'Shared-link title',
        hint: 'Shown when somebody pastes your address into a chat.',
        multiline: false,
      },
      {
        key: 'og_description',
        label: 'Shared-link description',
        hint: 'The grey line under it in the preview card.',
        multiline: true,
      },
    ],
  },
  {
    title: 'Elsewhere',
    blurb: 'Two screens that borrow a sentence from you.',
    fields: [
      {
        key: 'concierge_intro',
        label: 'Chat assistant greeting',
        hint: 'Only shown where the assistant is switched on for you.',
        multiline: true,
      },
      {
        key: 'login_blurb',
        label: 'Sign-in line',
        hint: 'Under the sign-in form.',
        multiline: true,
      },
    ],
  },
  {
    title: 'What you claim about the food',
    blurb:
      'Both of these say something about how you work, so they are yours to ' +
      'write rather than ours. They start as the weakest true version.',
    fields: [
      {
        key: 'kitchen_headline',
        label: 'Over your photographs',
        hint: 'On the home page, above the pictures of your food.',
        multiline: false,
      },
      {
        key: 'promise_note',
        label: 'The line in your footer',
        hint: 'The last thing on every page.',
        multiline: false,
      },
    ],
  },
];

export const COPY_KEYS: StorefrontCopyKey[] = COPY_GROUPS.flatMap((group) =>
  group.fields.map((field) => field.key),
);

/**
 * Only the fields the owner actually edited.
 *
 * Compared against what was LOADED, not against the defaults: a field the
 * owner wrote last week and has not touched today must not be sent again
 * (harmless but noisy), and a field showing a derived default must not be sent
 * at all (harmful — it would freeze that default in place as a written value).
 *
 * Trailing and leading whitespace is dropped before comparing, so tabbing
 * through a field without changing it is not an edit.
 */
export function changedCopy(
  loaded: Record<StorefrontCopyKey, string>,
  draft: Record<StorefrontCopyKey, string>,
): Partial<Record<StorefrontCopyKey, string>> {
  const changed: Partial<Record<StorefrontCopyKey, string>> = {};
  for (const key of COPY_KEYS) {
    const before = (loaded[key] ?? '').trim();
    const after = (draft[key] ?? '').trim();
    if (before !== after) {
      changed[key] = after;
    }
  }
  return changed;
}

/** Blank rows are normal while editing; they are simply not saved. */
export function usableSections(sections: BrandSection[]): BrandSection[] {
  return sections
    .map((section) => ({
      heading: section.heading.trim(),
      body: section.body.trim(),
      bullets: (section.bullets ?? []).map((bullet) => bullet.trim()).filter(Boolean),
    }))
    .filter((section) => section.heading && (section.body || section.bullets.length > 0));
}

/** Half a pair is worse than none — see `restaurant_brand.py`. */
export function usableFaqs(faqs: BrandFaq[]): BrandFaq[] {
  return faqs
    .map((faq) => ({ question: faq.question.trim(), answer: faq.answer.trim() }))
    .filter((faq) => faq.question && faq.answer);
}

/**
 * What is wrong with a row, for the message beside it.
 *
 * Returns null for a row that is entirely blank: that is an empty editor row,
 * not a mistake, and marking it red the moment it appears is hostile.
 */
export function sectionProblem(section: BrandSection, limits: Record<string, number>): string | null {
  const heading = section.heading.trim();
  const body = section.body.trim();
  const bullets = (section.bullets ?? []).map((bullet) => bullet.trim()).filter(Boolean);
  if (!heading && !body && bullets.length === 0) return null;
  if (!heading) return 'Give this section a heading, or clear it.';
  if (!body && bullets.length === 0) return 'Add some words or a bullet point under this heading.';
  if (heading.length > (limits['heading'] ?? Infinity)) {
    return `Headings are limited to ${limits['heading']} characters.`;
  }
  if (body.length > (limits['body'] ?? Infinity)) {
    return `Keep this to ${limits['body']} characters.`;
  }
  return null;
}

export function faqProblem(faq: BrandFaq, limits: Record<string, number>): string | null {
  const question = faq.question.trim();
  const answer = faq.answer.trim();
  if (!question && !answer) return null;
  if (!question) return 'Write the question, or clear this row.';
  if (!answer) return 'An unanswered question on your website reads as an oversight.';
  if (question.length > (limits['question'] ?? Infinity)) {
    return `Questions are limited to ${limits['question']} characters.`;
  }
  if (answer.length > (limits['answer'] ?? Infinity)) {
    return `Keep this to ${limits['answer']} characters.`;
  }
  return null;
}

export const EMPTY_SECTION: BrandSection = { heading: '', body: '', bullets: [] };
export const EMPTY_FAQ: BrandFaq = { question: '', answer: '' };
export const EMPTY_HIGHLIGHT: BrandHighlight = { value: '', label: '', note: '' };

/**
 * The highlights worth saving: both halves filled in.
 *
 * A figure with no caption says nothing and a caption with no figure is a
 * tile with a hole in it, so the storefront drops either. Dropping them here
 * too means the owner sees the same rule they will see on their own page,
 * rather than saving a row that silently never appears.
 */
export function usableHighlights(highlights: BrandHighlight[]): BrandHighlight[] {
  return highlights
    .map((highlight) => ({
      value: highlight.value.trim(),
      label: highlight.label.trim(),
      note: (highlight.note ?? '').trim(),
    }))
    .filter((highlight) => highlight.value !== '' && highlight.label !== '');
}

/** The specialities worth saving, trimmed and with the blanks dropped. */
export function usableSpecialities(specialities: string[]): string[] {
  return specialities.map((entry) => entry.trim()).filter((entry) => entry !== '');
}

/** What is wrong with one highlight, in the owner's words, or null. */
export function highlightProblem(
  highlight: BrandHighlight,
  limits: Record<string, number>,
): string | null {
  const value = highlight.value.trim();
  const label = highlight.label.trim();
  const note = (highlight.note ?? '').trim();
  // A half-filled row is a prompt, not an error: the owner is mid-typing.
  if (value === '' && label === '' && note === '') return null;
  if (value === '') return 'Add the figure, or clear the row.';
  if (label === '') return 'Add a caption, or clear the row.';
  const valueLimit = limits['highlight_value'] ?? 24;
  const labelLimit = limits['highlight_label'] ?? 60;
  const noteLimit = limits['highlight_note'] ?? 60;
  if (value.length > valueLimit) return `Keep the figure under ${valueLimit} characters.`;
  if (label.length > labelLimit) return `Keep the caption under ${labelLimit} characters.`;
  if (note.length > noteLimit) return `Keep the source under ${noteLimit} characters.`;
  return null;
}

/**
 * What is wrong with the year founded, or null.
 *
 * Mirrors `restaurant_brand.py`, which is the authority — this exists so an
 * owner is told before they save rather than by a 422 afterwards.
 */
export function yearProblem(value: string, limits: Record<string, number>): string | null {
  const typed = value.trim();
  if (typed === '') return null;
  if (!/^\d{4}$/.test(typed)) return 'Use a four-digit year, like 1999.';
  const year = Number(typed);
  const earliest = limits['earliest_year'] ?? 1800;
  const latest = new Date().getFullYear();
  if (year < earliest || year > latest) return `Use a year between ${earliest} and ${latest}.`;
  return null;
}

/** Move a row one place up or down, or return the list unchanged at an end. */
export function moveRow<T>(rows: T[], from: number, direction: -1 | 1): T[] {
  const to = from + direction;
  if (from < 0 || from >= rows.length || to < 0 || to >= rows.length) return rows;
  const next = [...rows];
  const [row] = next.splice(from, 1);
  next.splice(to, 0, row as T);
  return next;
}

/**
 * Headings worth having, offered as placeholders rather than written in.
 *
 * The difference matters: a placeholder prompts the owner, a default would
 * publish our words under their name. Nothing here is ever saved unless they
 * type it.
 */
export const SECTION_PROMPTS = [
  'Overview',
  'What we are known for',
  'How ordering works',
  'Our standards',
];

/**
 * Specialities worth having, offered as placeholders rather than written in.
 *
 * Same rule as the section headings: a placeholder prompts, a default would
 * publish our words under their name.
 */
export const SPECIALITY_PROMPTS = [
  'The thing people queue for',
  'What you are known for locally',
  'A speciality nobody else nearby makes',
];

export const HIGHLIGHT_PROMPTS: BrandHighlight[] = [
  { value: '4.6', label: 'Rated by customers', note: '85 reviews on JustDial' },
  { value: '11-25', label: 'Bakers and staff', note: 'Family-run' },
];

export const FAQ_PROMPTS = [
  'Do you take custom orders?',
  'How far ahead should I order?',
  'Do you deliver to my area?',
];
