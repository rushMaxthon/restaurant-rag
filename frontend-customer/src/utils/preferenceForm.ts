/**
 * Driving a questionnaire the client knows nothing about at build time.
 *
 * Every rule here comes from the question itself - `input_type`, `is_required`,
 * `min_selections`, `max_selections`, `allows_free_text` - so a question an
 * owner adds tomorrow validates correctly today. Nothing in this file names a
 * cuisine, a diet or a budget.
 *
 * Deliberately free of React: the same logic runs in the onboarding wizard, the
 * profile editor and the tests.
 */

import type {
  PreferenceAnswer,
  PreferenceAnswerSubmission,
  PreferenceQuestion,
  PreferenceSchema,
} from '../types/app';

export interface QuestionSelection {
  optionIds: string[];
  freeText: string[];
}

export type SelectionMap = Record<string, QuestionSelection>;

export const EMPTY_SELECTION: QuestionSelection = {
  optionIds: [],
  freeText: [],
};

function normalizeText(value: string): string {
  return value.trim().replace(/\s+/g, ' ');
}

/** Total answers given, counting a typed entry the same as a chosen option. */
export function selectionCount(selection: QuestionSelection): number {
  return selection.optionIds.length + selection.freeText.length;
}

/**
 * Seed the form from what the customer already answered.
 *
 * Answers to questions that are no longer in the schema are dropped from the
 * form - they stay in the database untouched, but there is nothing to render
 * them against.
 */
export function buildSelections(
  schema: PreferenceSchema,
  answers: PreferenceAnswer[],
): SelectionMap {
  const byQuestion = new Map(answers.map(answer => [answer.question_id, answer]));
  const selections: SelectionMap = {};

  for (const question of schema.questions) {
    const answer = byQuestion.get(question.id);
    if (!answer) {
      selections[question.id] = {optionIds: [], freeText: []};
      continue;
    }
    // An option that has since been withdrawn is not offered any more, so a
    // stored answer pointing at it cannot be represented as a selected chip.
    const liveOptionIds = new Set(question.options.map(option => option.id));
    selections[question.id] = {
      optionIds: answer.option_ids.filter(id => liveOptionIds.has(id)),
      freeText: question.allows_free_text ? [...answer.free_text] : [],
    };
  }

  return selections;
}

/**
 * Toggle one option, honouring the question's own shape.
 *
 * A single-select replaces rather than accumulates; a multi-select at its cap
 * refuses the extra rather than silently dropping an earlier choice.
 */
export function toggleOption(
  question: PreferenceQuestion,
  selection: QuestionSelection,
  optionId: string,
): QuestionSelection {
  const isSelected = selection.optionIds.includes(optionId);

  if (question.input_type === 'SINGLE_SELECT') {
    // Tapping the chosen one again clears it, which is how an optional
    // single-select is un-answered.
    return {
      optionIds: isSelected ? [] : [optionId],
      freeText: [],
    };
  }

  if (isSelected) {
    return {
      ...selection,
      optionIds: selection.optionIds.filter(id => id !== optionId),
    };
  }

  if (isAtCapacity(question, selection)) {
    return selection;
  }

  return {...selection, optionIds: [...selection.optionIds, optionId]};
}

export function isAtCapacity(
  question: PreferenceQuestion,
  selection: QuestionSelection,
): boolean {
  if (question.max_selections == null) {
    return false;
  }
  return selectionCount(selection) >= question.max_selections;
}

/**
 * Add a typed answer.
 *
 * Case-insensitive de-duplication mirrors the unique index on the server, so a
 * customer typing "Pasta" twice gets one entry rather than a rejected save.
 */
export function addFreeText(
  question: PreferenceQuestion,
  selection: QuestionSelection,
  raw: string,
): QuestionSelection {
  if (!question.allows_free_text) {
    return selection;
  }
  const value = normalizeText(raw);
  if (!value) {
    return selection;
  }

  const existing = new Set(
    [
      ...selection.freeText,
      ...question.options
        .filter(option => selection.optionIds.includes(option.id))
        .map(option => option.label),
    ].map(entry => entry.toLowerCase()),
  );
  if (existing.has(value.toLowerCase())) {
    return selection;
  }
  if (isAtCapacity(question, selection)) {
    return selection;
  }
  if (question.input_type === 'SINGLE_SELECT') {
    return {optionIds: [], freeText: [value]};
  }
  return {...selection, freeText: [...selection.freeText, value]};
}

export function removeFreeText(
  selection: QuestionSelection,
  value: string,
): QuestionSelection {
  return {
    ...selection,
    freeText: selection.freeText.filter(entry => entry !== value),
  };
}

/**
 * Why this question cannot be submitted yet, or null when it is fine.
 *
 * The message is what the customer reads, so it names the constraint in their
 * terms rather than echoing the field that produced it.
 */
export function validateQuestion(
  question: PreferenceQuestion,
  selection: QuestionSelection,
): string | null {
  const count = selectionCount(selection);
  const minimum = question.is_required
    ? Math.max(question.min_selections, 1)
    : question.min_selections;

  if (question.is_required && count === 0) {
    return 'Pick at least one to continue.';
  }
  if (count > 0 && count < minimum) {
    return `Pick at least ${minimum}.`;
  }
  if (question.max_selections != null && count > question.max_selections) {
    return `Pick up to ${question.max_selections}.`;
  }
  return null;
}

/** True when every question in the schema is satisfied. */
export function isComplete(
  schema: PreferenceSchema,
  selections: SelectionMap,
): boolean {
  return schema.questions.every(
    question =>
      validateQuestion(question, selections[question.id] ?? EMPTY_SELECTION) === null,
  );
}

/**
 * The payload for `PUT /preferences/me/answers`.
 *
 * Every question in the schema is included, including the ones left blank -
 * omitting a question leaves its previous answer in place, so clearing one has
 * to be stated explicitly.
 */
export function toSubmissions(
  schema: PreferenceSchema,
  selections: SelectionMap,
): PreferenceAnswerSubmission[] {
  return schema.questions.map(question => {
    const selection = selections[question.id] ?? EMPTY_SELECTION;
    return {
      question_id: question.id,
      option_ids: selection.optionIds,
      free_text: selection.freeText,
    };
  });
}

/** A short summary of what is chosen, for a collapsed row in the profile. */
export function describeSelection(
  question: PreferenceQuestion,
  selection: QuestionSelection,
): string {
  const labels = [
    ...question.options
      .filter(option => selection.optionIds.includes(option.id))
      .map(option => option.label),
    ...selection.freeText,
  ];
  return labels.length > 0 ? labels.join(', ') : 'Not set';
}

/**
 * Collapse answers into the legacy preference shape, client-side.
 *
 * Needed for exactly one case: someone completing onboarding before they have
 * an account. There is no server row to project from yet, but the home feed
 * still ranks from a local profile, so the client has to build one.
 *
 * Driven by `signal_role`, never by question keys, so a question an owner
 * renames keeps working and a question they invent (`NONE`) correctly
 * contributes nothing to ranking.
 *
 * Once the customer signs in, the server projection takes over and this is
 * never consulted again.
 */
export function selectionsToLegacy(
  schema: PreferenceSchema,
  selections: SelectionMap,
): {
  cuisines: string[];
  diet: 'VEG' | 'NON_VEG' | null;
  spice_level: 'LOW' | 'MEDIUM' | 'HIGH' | null;
  budget: 'LOW' | 'MID' | 'HIGH' | null;
  favorite_items: string[];
} {
  const cuisines: string[] = [];
  const favorites: string[] = [];
  let diet: string | null = null;
  let spice: string | null = null;
  let budget: string | null = null;

  for (const question of schema.questions) {
    const selection = selections[question.id] ?? EMPTY_SELECTION;
    const chosen = question.options.filter(option =>
      selection.optionIds.includes(option.id),
    );
    const labels = [...chosen.map(option => option.label), ...selection.freeText];
    if (labels.length === 0) {
      continue;
    }

    switch (question.signal_role) {
      case 'CUISINE':
        cuisines.push(...labels);
        break;
      case 'FAVORITE_ITEM':
        favorites.push(...labels);
        break;
      case 'DIET':
        diet = chosen[0]?.value.toUpperCase() ?? null;
        break;
      case 'SPICE':
        spice = chosen[0]?.value.toUpperCase() ?? null;
        break;
      case 'BUDGET':
        budget = chosen[0]?.value.toUpperCase() ?? null;
        break;
      default:
        // DISLIKED_CUISINE has no legacy home, and NONE must not reach ranking.
        break;
    }
  }

  const oneOf = <T extends string>(value: string | null, allowed: T[]): T | null =>
    value && (allowed as string[]).includes(value) ? (value as T) : null;

  return {
    cuisines,
    diet: oneOf(diet, ['VEG', 'NON_VEG']),
    spice_level: oneOf(spice, ['LOW', 'MEDIUM', 'HIGH']),
    budget: oneOf(budget, ['LOW', 'MID', 'HIGH']),
    favorite_items: favorites,
  };
}
