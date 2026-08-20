import {useEffect, useMemo, useState} from 'react';
import type {
  BudgetTier,
  DietPreference,
  SpiceLevel,
  UserPreferences,
} from '../types/app';
import {useAppStore} from '../hooks/useAppStore';

interface PreferencesOnboardingPageProps {
  mode?: 'onboarding' | 'edit';
  onNavigate: (path: string) => void;
}

const CUISINE_OPTIONS = [
  'Pizza',
  'Burgers',
  'Chinese',
  'Healthy',
  'Desserts',
  'Biryani',
  'South Indian',
  'North Indian',
  'Italian',
];

const FAVORITE_ITEM_OPTIONS = [
  'Margherita Pizza',
  'Paneer Tikka',
  'Chicken Biryani',
  'Veg Burger',
  'Pasta',
  'Momos',
  'Salad Bowl',
  'Ice Cream',
];

const DIET_OPTIONS: Array<{label: string; value: DietPreference}> = [
  {label: 'Veg', value: 'VEG'},
  {label: 'Non-Veg', value: 'NON_VEG'},
];

const SPICE_OPTIONS: Array<{label: string; value: SpiceLevel}> = [
  {label: 'Low', value: 'LOW'},
  {label: 'Medium', value: 'MEDIUM'},
  {label: 'High', value: 'HIGH'},
];

const BUDGET_OPTIONS: Array<{label: string; value: BudgetTier}> = [
  {label: 'Low', value: 'LOW'},
  {label: 'Mid', value: 'MID'},
  {label: 'High', value: 'HIGH'},
];

const STEPS = [
  {
    key: 'cuisines',
    title: 'Pick your favorite cuisines',
    subtitle: 'Choose a few tastes you want us to prioritize from the start.',
  },
  {
    key: 'diet',
    title: 'What diet should we prefer?',
    subtitle: 'We will use this to avoid irrelevant recommendations.',
  },
  {
    key: 'spice',
    title: 'How spicy do you like it?',
    subtitle: 'We will bias recommendations toward your comfort zone.',
  },
  {
    key: 'budget',
    title: 'Set your typical budget',
    subtitle: 'This helps us keep early suggestions realistic and useful.',
  },
  {
    key: 'items',
    title: 'Any favorite items?',
    subtitle: 'Optional, but helpful for faster personalization.',
  },
] as const;

function normalizePreferences(preferences: UserPreferences | null): UserPreferences {
  return {
    cuisines: preferences?.cuisines ?? [],
    diet: preferences?.diet ?? null,
    spice_level: preferences?.spice_level ?? null,
    budget: preferences?.budget ?? null,
    favorite_items: preferences?.favorite_items ?? [],
    updated_at: preferences?.updated_at ?? null,
  };
}

export function PreferencesOnboardingPage({
  mode = 'onboarding',
  onNavigate,
}: PreferencesOnboardingPageProps) {
  const {
    preferences,
    savePreferences,
    skipPreferencesOnboarding,
    pushToast,
  } = useAppStore();
  const initialPreferences = useMemo(
    () => normalizePreferences(preferences),
    [preferences],
  );
  const [stepIndex, setStepIndex] = useState(0);
  const [direction, setDirection] = useState<'forward' | 'backward'>('forward');
  const [submitting, setSubmitting] = useState(false);
  const [cuisines, setCuisines] = useState(initialPreferences.cuisines);
  const [diet, setDiet] = useState<DietPreference | null>(initialPreferences.diet);
  const [spiceLevel, setSpiceLevel] = useState<SpiceLevel | null>(initialPreferences.spice_level);
  const [budget, setBudget] = useState<BudgetTier | null>(initialPreferences.budget);
  const [favoriteItems, setFavoriteItems] = useState(initialPreferences.favorite_items);
  const currentStep = STEPS[stepIndex];
  const progress = ((stepIndex + 1) / STEPS.length) * 100;

  useEffect(() => {
    window.scrollTo({top: 0, behavior: 'smooth'});
  }, [stepIndex]);

  const toggleListValue = (
    currentValues: string[],
    value: string,
    setter: (next: string[]) => void,
  ) => {
    if (currentValues.includes(value)) {
      setter(currentValues.filter((entry) => entry !== value));
      return;
    }
    setter([...currentValues, value]);
  };

  const handleBack = () => {
    if (stepIndex === 0) {
      return;
    }
    setDirection('backward');
    setStepIndex((current) => current - 1);
  };

  const handleSkip = () => {
    skipPreferencesOnboarding();
    pushToast(
      'Skipped for now',
      'We will start with highly rated and popular picks.',
      'info',
    );
    onNavigate('/');
  };

  const handleFinish = async () => {
    setSubmitting(true);
    try {
      await savePreferences(
        {
          cuisines,
          diet,
          spice_level: spiceLevel,
          budget,
          favorite_items: favoriteItems,
          updated_at: new Date().toISOString(),
        },
        {
          sync: true,
          markOnboardingCompleted: true,
        },
      );
      pushToast(
        'Preferences saved',
        mode === 'onboarding'
          ? 'Your home feed is ready with smarter starting recommendations.'
          : 'Your recommendation profile has been updated.',
        'success',
      );
      onNavigate(mode === 'onboarding' ? '/' : '/profile');
    } catch {
      // The store already surfaced the sync failure and kept the local preference state.
    } finally {
      setSubmitting(false);
    }
  };

  const handleNext = async () => {
    if (stepIndex < STEPS.length - 1) {
      setDirection('forward');
      setStepIndex((current) => current + 1);
      return;
    }
    await handleFinish();
  };

  const renderOptions = () => {
    switch (currentStep.key) {
      case 'cuisines':
        return (
          <div className="preference-chip-grid">
            {CUISINE_OPTIONS.map((option) => (
              <button
                key={option}
                className={
                  cuisines.includes(option)
                    ? 'preference-chip preference-chip--active'
                    : 'preference-chip'
                }
                onClick={() => toggleListValue(cuisines, option, setCuisines)}
                type="button"
              >
                {option}
              </button>
            ))}
          </div>
        );
      case 'diet':
        return (
          <div className="preference-chip-grid">
            {DIET_OPTIONS.map((option) => (
              <button
                key={option.value}
                className={
                  diet === option.value
                    ? 'preference-chip preference-chip--active'
                    : 'preference-chip'
                }
                onClick={() =>
                  setDiet((current) => (current === option.value ? null : option.value))
                }
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
        );
      case 'spice':
        return (
          <div className="preference-chip-grid">
            {SPICE_OPTIONS.map((option) => (
              <button
                key={option.value}
                className={
                  spiceLevel === option.value
                    ? 'preference-chip preference-chip--active'
                    : 'preference-chip'
                }
                onClick={() =>
                  setSpiceLevel((current) => (current === option.value ? null : option.value))
                }
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
        );
      case 'budget':
        return (
          <div className="preference-chip-grid">
            {BUDGET_OPTIONS.map((option) => (
              <button
                key={option.value}
                className={
                  budget === option.value
                    ? 'preference-chip preference-chip--active'
                    : 'preference-chip'
                }
                onClick={() =>
                  setBudget((current) => (current === option.value ? null : option.value))
                }
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
        );
      case 'items':
        return (
          <div className="preference-chip-grid">
            {FAVORITE_ITEM_OPTIONS.map((option) => (
              <button
                key={option}
                className={
                  favoriteItems.includes(option)
                    ? 'preference-chip preference-chip--active'
                    : 'preference-chip'
                }
                onClick={() =>
                  toggleListValue(favoriteItems, option, setFavoriteItems)
                }
                type="button"
              >
                {option}
              </button>
            ))}
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="page-stack">
      <section className="preferences-wizard">
        <div className="preferences-wizard__meta">
          <span className="eyebrow">
            Step {stepIndex + 1}/{STEPS.length}
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
            style={{width: `${progress}%`}}
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
              ? 'Five quick steps. No pressure. You can edit everything later from Profile.'
              : 'Update cuisines, spice, budget, and favorites to keep recommendations fresh.'}
          </p>
        </div>

        <div className="preferences-wizard__card">
          <div
            className={
              direction === 'forward'
                ? 'preferences-wizard__step preferences-wizard__step--forward'
                : 'preferences-wizard__step preferences-wizard__step--backward'
            }
            key={currentStep.key}
          >
            <h2>{currentStep.title}</h2>
            <p>{currentStep.subtitle}</p>
            {renderOptions()}
          </div>
        </div>

        <div className="preferences-wizard__footer">
          <div className="preferences-wizard__footer-actions">
            {stepIndex > 0 ? (
              <button className="secondary-button" onClick={handleBack} type="button">
                Back
              </button>
            ) : (
              <div />
            )}
            <button
              className="primary-button"
              disabled={submitting}
              onClick={() => void handleNext()}
              type="button"
            >
              {submitting
                ? 'Saving...'
                : stepIndex === STEPS.length - 1
                  ? 'Finish'
                  : 'Next'}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
