import {
  EMPTY_SELECTION,
  addFreeText,
  buildSelections,
  isComplete,
  selectionsToLegacy,
  toSubmissions,
  toggleOption,
  validateQuestion,
} from './preferenceForm';
import type {PreferenceQuestion, PreferenceSchema} from '@/types/app';

function question(overrides: Partial<PreferenceQuestion> = {}): PreferenceQuestion {
  return {
    id: 'q1',
    key: 'demo',
    prompt: 'Demo',
    input_type: 'MULTI_SELECT',
    is_required: false,
    min_selections: 0,
    max_selections: null,
    allows_free_text: false,
    signal_role: 'NONE',
    display_order: 1,
    options: [
      {id: 'a', value: 'a', label: 'Alpha', display_order: 1},
      {id: 'b', value: 'b', label: 'Beta', display_order: 2},
      {id: 'c', value: 'c', label: 'Gamma', display_order: 3},
    ],
    ...overrides,
  };
}

describe('toggleOption', () => {
  it('replaces rather than accumulates on a single-select', () => {
    const q = question({input_type: 'SINGLE_SELECT'});
    const first = toggleOption(q, EMPTY_SELECTION, 'a');
    const second = toggleOption(q, first, 'b');
    expect(second.optionIds).toEqual(['b']);
  });

  it('clears a single-select when the chosen option is tapped again', () => {
    const q = question({input_type: 'SINGLE_SELECT'});
    const chosen = toggleOption(q, EMPTY_SELECTION, 'a');
    expect(toggleOption(q, chosen, 'a').optionIds).toEqual([]);
  });

  it('refuses the extra pick at the cap instead of dropping an earlier one', () => {
    const q = question({max_selections: 2});
    let selection = toggleOption(q, EMPTY_SELECTION, 'a');
    selection = toggleOption(q, selection, 'b');
    selection = toggleOption(q, selection, 'c');
    expect(selection.optionIds).toEqual(['a', 'b']);
  });
});

describe('addFreeText', () => {
  it('is ignored when the question does not allow it', () => {
    const q = question({allows_free_text: false});
    expect(addFreeText(q, EMPTY_SELECTION, 'Khao Soi').freeText).toEqual([]);
  });

  it('de-duplicates case-insensitively, matching the database index', () => {
    const q = question({allows_free_text: true});
    let selection = addFreeText(q, EMPTY_SELECTION, 'Khao Soi');
    selection = addFreeText(q, selection, 'khao soi');
    expect(selection.freeText).toEqual(['Khao Soi']);
  });

  it('does not duplicate a value that is already a chosen option', () => {
    const q = question({allows_free_text: true});
    const chosen = toggleOption(q, EMPTY_SELECTION, 'a');
    expect(addFreeText(q, chosen, 'alpha').freeText).toEqual([]);
  });

  it('counts toward the cap alongside chosen options', () => {
    const q = question({allows_free_text: true, max_selections: 1});
    const chosen = toggleOption(q, EMPTY_SELECTION, 'a');
    expect(addFreeText(q, chosen, 'Extra').freeText).toEqual([]);
  });
});

describe('validateQuestion', () => {
  it('accepts an empty optional question', () => {
    expect(validateQuestion(question(), EMPTY_SELECTION)).toBeNull();
  });

  it('rejects an empty required question', () => {
    expect(validateQuestion(question({is_required: true}), EMPTY_SELECTION)).toMatch(
      /at least one/i,
    );
  });

  it('enforces a minimum once something is chosen', () => {
    const q = question({min_selections: 2});
    const one = toggleOption(q, EMPTY_SELECTION, 'a');
    expect(validateQuestion(q, one)).toMatch(/at least 2/i);
  });
});

describe('buildSelections', () => {
  it('drops an answer whose option has been withdrawn', () => {
    const schema: PreferenceSchema = {restaurant_id: null, questions: [question()]};
    const selections = buildSelections(schema, [
      {
        question_id: 'q1',
        question_key: 'demo',
        option_ids: ['a', 'retired'],
        free_text: [],
        labels: [],
        has_stale_selection: true,
      },
    ]);
    expect(selections.q1.optionIds).toEqual(['a']);
  });
});

describe('toSubmissions', () => {
  it('includes untouched questions so clearing one is explicit', () => {
    const schema: PreferenceSchema = {
      restaurant_id: null,
      questions: [question(), question({id: 'q2', key: 'other'})],
    };
    const submissions = toSubmissions(schema, {q1: {optionIds: ['a'], freeText: []}});
    expect(submissions).toHaveLength(2);
    expect(submissions[1]).toEqual({question_id: 'q2', option_ids: [], free_text: []});
  });
});

describe('selectionsToLegacy', () => {
  const schema: PreferenceSchema = {
    restaurant_id: null,
    questions: [
      question({id: 'c', key: 'cuisines', signal_role: 'CUISINE'}),
      question({
        id: 'd',
        key: 'diet',
        signal_role: 'DIET',
        input_type: 'SINGLE_SELECT',
        options: [
          {id: 'veg', value: 'VEG', label: 'Veg', display_order: 1},
          {id: 'nonveg', value: 'NON_VEG', label: 'Non-Veg', display_order: 2},
        ],
      }),
      question({id: 'x', key: 'custom', signal_role: 'NONE'}),
    ],
  };

  it('maps by role, not by question key', () => {
    const legacy = selectionsToLegacy(schema, {
      c: {optionIds: ['a'], freeText: []},
      d: {optionIds: ['veg'], freeText: []},
    });
    expect(legacy.cuisines).toEqual(['Alpha']);
    expect(legacy.diet).toBe('VEG');
  });

  it('never lets a custom question reach the ranking signals', () => {
    const legacy = selectionsToLegacy(schema, {x: {optionIds: ['a', 'b'], freeText: ['Typed']}});
    expect(legacy).toEqual({
      cuisines: [],
      diet: null,
      spice_level: null,
      budget: null,
      favorite_items: [],
    });
  });
});

describe('isComplete', () => {
  it('is false while a required question is unanswered', () => {
    const schema: PreferenceSchema = {
      restaurant_id: null,
      questions: [question({is_required: true})],
    };
    expect(isComplete(schema, {})).toBe(false);
    expect(isComplete(schema, {q1: {optionIds: ['a'], freeText: []}})).toBe(true);
  });
});
