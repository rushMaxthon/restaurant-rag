/**
 * The questionnaire to fall back on when `/preferences/schema` cannot be
 * reached.
 *
 * Onboarding is the very first thing a new customer sees and it gates the rest
 * of the app, so a dead network must not produce a dead end. This mirrors the
 * platform questions seeded by migration `0051`, which means a customer who
 * onboards offline answers the same questions as everyone else.
 *
 * The ids are deliberately not real: an answer collected against this schema
 * cannot be saved by id. The wizard detects the fallback and stores the result
 * through the legacy preferences endpoint instead, which accepts values rather
 * than ids. That path is the one the app used before any of this existed, so it
 * is known to work.
 */

import type {PreferenceSchema} from '@/types/app';

export const FALLBACK_SCHEMA_ID = 'fallback';

function option(value: string, label: string, order: number) {
  return {
    id: `${FALLBACK_SCHEMA_ID}:${value}`,
    value,
    label,
    display_order: order,
  };
}

export const FALLBACK_PREFERENCE_SCHEMA: PreferenceSchema = {
  restaurant_id: null,
  questions: [
    {
      id: `${FALLBACK_SCHEMA_ID}:cuisines`,
      key: 'cuisines',
      signal_role: 'CUISINE',
      prompt: 'Pick your favorite cuisines',
      help_text: 'Choose a few tastes you want us to prioritize from the start.',
      input_type: 'MULTI_SELECT',
      is_required: false,
      min_selections: 0,
      max_selections: null,
      allows_free_text: false,
      display_order: 1,
      options: [
        'Pizza',
        'Burgers',
        'Chinese',
        'Healthy',
        'Desserts',
        'Biryani',
        'South Indian',
        'North Indian',
        'Italian',
      ].map((label, index) =>
        option(label.toLowerCase().replace(/\s+/g, '_'), label, index + 1),
      ),
    },
    {
      id: `${FALLBACK_SCHEMA_ID}:diet`,
      key: 'diet',
      signal_role: 'DIET',
      prompt: 'What diet should we prefer?',
      help_text: 'We will use this to avoid irrelevant recommendations.',
      input_type: 'SINGLE_SELECT',
      is_required: false,
      min_selections: 0,
      max_selections: null,
      allows_free_text: false,
      display_order: 2,
      options: [option('VEG', 'Veg', 1), option('NON_VEG', 'Non-Veg', 2)],
    },
    {
      id: `${FALLBACK_SCHEMA_ID}:spice`,
      key: 'spice',
      signal_role: 'SPICE',
      prompt: 'How spicy do you like it?',
      help_text: 'We will bias recommendations toward your comfort zone.',
      input_type: 'SINGLE_SELECT',
      is_required: false,
      min_selections: 0,
      max_selections: null,
      allows_free_text: false,
      display_order: 3,
      options: [
        option('LOW', 'Low', 1),
        option('MEDIUM', 'Medium', 2),
        option('HIGH', 'High', 3),
      ],
    },
    {
      id: `${FALLBACK_SCHEMA_ID}:budget`,
      key: 'budget',
      signal_role: 'BUDGET',
      prompt: 'Set your typical budget',
      help_text: 'This helps us keep early suggestions realistic and useful.',
      input_type: 'SINGLE_SELECT',
      is_required: false,
      min_selections: 0,
      max_selections: null,
      allows_free_text: false,
      display_order: 4,
      options: [
        option('LOW', 'Low', 1),
        option('MID', 'Mid', 2),
        option('HIGH', 'High', 3),
      ],
    },
    {
      id: `${FALLBACK_SCHEMA_ID}:favorite_items`,
      key: 'favorite_items',
      signal_role: 'FAVORITE_ITEM',
      prompt: 'Any favorite items?',
      help_text: 'Optional, but helpful for faster personalization.',
      input_type: 'MULTI_SELECT',
      is_required: false,
      min_selections: 0,
      max_selections: null,
      allows_free_text: true,
      display_order: 5,
      options: [
        'Margherita Pizza',
        'Paneer Tikka',
        'Chicken Biryani',
        'Veg Burger',
        'Pasta',
        'Momos',
        'Salad Bowl',
        'Ice Cream',
      ].map((label, index) =>
        option(label.toLowerCase().replace(/\s+/g, '_'), label, index + 1),
      ),
    },
  ],
};

export function isFallbackSchema(schema: {questions: Array<{id: string}>}): boolean {
  return schema.questions.some(question =>
    question.id.startsWith(`${FALLBACK_SCHEMA_ID}:`),
  );
}
