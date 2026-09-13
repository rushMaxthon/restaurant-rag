/**
 * Onboarding and preference editing, rendered from the restaurant's own schema.
 *
 * There are no steps in this file. It asks `/preferences/schema` what to ask and
 * validates each answer from the question's own `input_type`, `is_required`,
 * `min_selections`, `max_selections` and `allows_free_text`, so a question an
 * owner adds or hides changes this screen with no release.
 *
 * `mode` is what makes the same component serve both jobs: `onboarding` gates a
 * new customer and offers a skip; `edit` is Profile → Taste preferences, seeded
 * with what they already chose.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../services/api';
import { useAppStore } from '../hooks/useAppStore';
import { useAppConfig } from '../store/useAppConfig';
import type { PreferenceSchema, UserPreferences } from '../types/app';
import { FALLBACK_PREFERENCE_SCHEMA } from '../data/preferenceFallbackSchema';
import {
  EMPTY_SELECTION,
  addFreeText,
  buildSelections,
  describeSelection,
  isAtCapacity,
  removeFreeText,
  selectionCount,
  selectionsToLegacy,
  toSubmissions,
  toggleOption,
  validateQuestion,
  type SelectionMap,
} from '../utils/preferenceForm';

interface PreferencesOnboardingPageProps {
  mode?: 'onboarding' | 'edit';
  onNavigate: (path: string) => void;
}

export function PreferencesOnboardingPage({
  mode = 'onboarding',
  onNavigate,
}: PreferencesOnboardingPageProps) {
  const { savePreferences, skipPreferencesOnboarding, pushToast, token } = useAppStore();
  const { restaurantId } = useAppConfig();

  const [schema, setSchema] = useState<PreferenceSchema | null>(null);
  const [loading, setLoading] = useState(true);
  const [usingFallback, setUsingFallback] = useState(false);
  const [selections, setSelections] = useState<SelectionMap>({});
  const [stepIndex, setStepIndex] = useState(0);
  const [direction, setDirection] = useState<'forward' | 'backward'>('forward');
  const [submitting, setSubmitting] = useState(false);
  const [touched, setTouched] = useState(false);
  const [draftText, setDraftText] = useState('');

  useEffect(() => {
    let active = true;

    async function load() {
      let resolved: PreferenceSchema;
      let fallback = false;
      try {
        resolved = await api.getPreferenceSchema(restaurantId);
        // An owner who hid every question would otherwise strand the customer on
        // an empty wizard with nothing to press.
        if (resolved.questions.length === 0) {
          resolved = FALLBACK_PREFERENCE_SCHEMA;
          fallback = true;
        }
      } catch {
        resolved = FALLBACK_PREFERENCE_SCHEMA;
        fallback = true;
      }
      if (!active) {
        return;
      }

      let initial = buildSelections(resolved, []);
      if (token && !fallback) {
        try {
          const existing = await api.getPreferenceAnswers(token, restaurantId);
          if (active) {
            initial = buildSelections(resolved, existing.answers);
          }
        } catch {
          // Not fatal — they start from a blank questionnaire.
        }
      }

      if (!active) {
        return;
      }
      setSchema(resolved);
      setUsingFallback(fallback);
      setSelections(initial);
      setLoading(false);
    }

    void load();
    return () => {
      active = false;
    };
  }, [restaurantId, token]);

  const questions = schema?.questions ?? [];
  const currentQuestion = questions[stepIndex];
  const currentSelection = currentQuestion
    ? selections[currentQuestion.id] ?? EMPTY_SELECTION
    : EMPTY_SELECTION;
  const currentError = currentQuestion
    ? validateQuestion(currentQuestion, currentSelection)
    : null;
  const progress = questions.length > 0 ? ((stepIndex + 1) / questions.length) * 100 : 0;

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [stepIndex]);

  const setSelection = useCallback(
    (questionId: string, next: ReturnType<typeof toggleOption>) => {
      setSelections((current) => ({ ...current, [questionId]: next }));
    },
    [],
  );

  const handleSkip = () => {
    skipPreferencesOnboarding();
    onNavigate('/');
  };

  const handleBack = () => {
    if (stepIndex === 0) {
      return;
    }
    setTouched(false);
    setDraftText('');
    setDirection('backward');
    setStepIndex((current) => current - 1);
  };

  const handleNext = async () => {
    if (!schema || !currentQuestion) {
      return;
    }
    if (currentError) {
      setTouched(true);
      return;
    }
    if (stepIndex < questions.length - 1) {
      setTouched(false);
      setDraftText('');
      setDirection('forward');
      setStepIndex((current) => current + 1);
      return;
    }

    setSubmitting(true);
    try {
      if (usingFallback || !token) {
        // No account yet, or the schema came from the offline fallback where the
        // ids mean nothing to the server. Either way the answers are projected
        // here and kept locally, so the first home feed is still personalised;
        // `savePreferences` syncs through the value-based legacy endpoint when a
        // token exists.
        const legacy = selectionsToLegacy(schema, selections);
        await savePreferences(
          { ...legacy, updated_at: new Date().toISOString() } as UserPreferences,
          { sync: Boolean(token), markOnboardingCompleted: true },
        );
      } else {
        const saved = await api.savePreferenceAnswers(
          token,
          toSubmissions(schema, selections),
          restaurantId,
        );
        // Already persisted server-side; storing the projection locally without
        // re-syncing keeps the ranked feed consistent immediately.
        await savePreferences(saved.legacy, {
          sync: false,
          markOnboardingCompleted: true,
        });
      }
      pushToast(
        'Preferences saved',
        mode === 'onboarding'
          ? 'Your home feed is ready with smarter starting recommendations.'
          : 'Your recommendation profile has been updated.',
        'success',
      );
      onNavigate(mode === 'onboarding' ? '/' : '/profile');
    } catch (error) {
      pushToast(
        'Preferences not saved',
        error instanceof Error
          ? error.message
          : 'Unable to save your preferences right now.',
        'error',
      );
    } finally {
      setSubmitting(false);
    }
  };

  const capacityHint = useMemo(() => {
    if (!currentQuestion) {
      return '';
    }
    const parts: string[] = [];
    if (currentQuestion.max_selections != null) {
      parts.push(`Choose up to ${currentQuestion.max_selections}`);
    }
    parts.push(currentQuestion.is_required ? 'Required' : 'Optional');
    return parts.join(' · ');
  }, [currentQuestion]);

  if (loading) {
    return (
      <div className="page-stack">
        <section className="preferences-wizard">
          <div className="preferences-wizard__hero">
            <span className="micro-chip">Taste Profile</span>
            <h1>Setting up your taste profile…</h1>
          </div>
        </section>
      </div>
    );
  }

  if (!schema || !currentQuestion) {
    // Reachable only if the fallback itself were emptied. Continuing is the one
    // sane exit, since onboarding gates the rest of the app.
    return (
      <div className="page-stack">
        <section className="preferences-wizard">
          <div className="preferences-wizard__hero">
            <span className="micro-chip">Taste Profile</span>
            <h1>No preference questions are set up right now.</h1>
            <p>You can start browsing and set these later from your profile.</p>
          </div>
          <div className="preferences-wizard__footer-actions">
            <button className="primary-button" onClick={handleSkip} type="button">
              Continue
            </button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="preferences-wizard">
        <div className="preferences-wizard__meta">
          <span className="eyebrow">
            Step {stepIndex + 1}/{questions.length}
          </span>
          {mode === 'onboarding' ? (
            <button className="text-link" onClick={handleSkip} type="button">
              Skip
            </button>
          ) : null}
        </div>
        <div className="preferences-wizard__progress">
          <div
            className="preferences-wizard__progress-fill"
            style={{ width: `${progress}%` }}
          />
        </div>

        <div className="preferences-wizard__hero">
          <span className="micro-chip">Taste Profile</span>
          <h1>
            {mode === 'onboarding'
              ? 'Build your first recommendation feed.'
              : 'Fine-tune your preferences.'}
          </h1>
          <p>
            {mode === 'onboarding'
              ? `${questions.length} quick ${
                  questions.length === 1 ? 'step' : 'steps'
                }. No pressure. You can edit everything later from Profile.`
              : 'Update what you like to keep recommendations fresh.'}
          </p>
        </div>

        <div className="preferences-wizard__card">
          <div
            className={
              direction === 'forward'
                ? 'preferences-wizard__step preferences-wizard__step--forward'
                : 'preferences-wizard__step preferences-wizard__step--backward'
            }
            key={currentQuestion.id}
          >
            <h2>{currentQuestion.prompt}</h2>
            {currentQuestion.help_text ? <p>{currentQuestion.help_text}</p> : null}

            <div className="preference-chip-grid">
              {currentQuestion.options.map((option) => {
                const active = currentSelection.optionIds.includes(option.id);
                const blocked = !active && isAtCapacity(currentQuestion, currentSelection);
                return (
                  <button
                    key={option.id}
                    aria-pressed={active}
                    className={
                      active ? 'preference-chip preference-chip--active' : 'preference-chip'
                    }
                    disabled={blocked}
                    onClick={() =>
                      setSelection(
                        currentQuestion.id,
                        toggleOption(currentQuestion, currentSelection, option.id),
                      )
                    }
                    type="button"
                  >
                    {option.label}
                  </button>
                );
              })}

              {currentSelection.freeText.map((value) => (
                <button
                  key={`typed:${value}`}
                  className="preference-chip preference-chip--active preference-chip--typed"
                  onClick={() =>
                    setSelection(currentQuestion.id, removeFreeText(currentSelection, value))
                  }
                  title="Remove"
                  type="button"
                >
                  {value} <span aria-hidden="true">×</span>
                </button>
              ))}
            </div>

            {currentQuestion.allows_free_text ? (
              <form
                className="preference-free-text"
                onSubmit={(event) => {
                  event.preventDefault();
                  setSelection(
                    currentQuestion.id,
                    addFreeText(currentQuestion, currentSelection, draftText),
                  );
                  setDraftText('');
                }}
              >
                <input
                  aria-label={`Add your own answer for ${currentQuestion.prompt}`}
                  onChange={(event) => setDraftText(event.target.value)}
                  placeholder="Add your own"
                  value={draftText}
                />
                <button
                  className="secondary-button"
                  disabled={!draftText.trim()}
                  type="submit"
                >
                  Add
                </button>
              </form>
            ) : null}

            {touched && currentError ? (
              <p className="preference-error">{currentError}</p>
            ) : (
              <p className="preference-hint">
                {capacityHint}
                {selectionCount(currentSelection) > 0
                  ? ` · ${describeSelection(currentQuestion, currentSelection)}`
                  : ''}
              </p>
            )}
          </div>
        </div>

        <div className="preferences-wizard__footer">
          <div className="preferences-wizard__footer-actions">
            {stepIndex > 0 ? (
              <button className="secondary-button" onClick={handleBack} type="button">
                Back
              </button>
            ) : (
              <span />
            )}
            <button
              className="primary-button"
              disabled={submitting}
              onClick={() => void handleNext()}
              type="button"
            >
              {submitting
                ? 'Saving…'
                : stepIndex === questions.length - 1
                  ? mode === 'onboarding'
                    ? 'Finish'
                    : 'Save changes'
                  : 'Next'}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
