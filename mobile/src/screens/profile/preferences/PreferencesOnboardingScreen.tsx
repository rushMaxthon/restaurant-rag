import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import {
  SafeAreaView,
  useSafeAreaInsets,
} from 'react-native-safe-area-context';
import Animated, {
  FadeInLeft,
  FadeInRight,
  FadeOutLeft,
  FadeOutRight,
  interpolateColor,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import { useAppActions, usePreferences } from '@hooks/useAppStore';
import type {
  BudgetTier,
  DietPreference,
  SpiceLevel,
  UserPreferences,
} from '@/types/app';
import { useTheme, useThemedStyles } from '@/theme';
import { createStyles } from './wizardStyles';

const AnimatedText = Animated.createAnimatedComponent(Text);

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

const DIET_OPTIONS: Array<{ label: string; value: DietPreference }> = [
  { label: 'Veg', value: 'VEG' },
  { label: 'Non-Veg', value: 'NON_VEG' },
];

const SPICE_OPTIONS: Array<{ label: string; value: SpiceLevel }> = [
  { label: 'Low', value: 'LOW' },
  { label: 'Medium', value: 'MEDIUM' },
  { label: 'High', value: 'HIGH' },
];

const BUDGET_OPTIONS: Array<{ label: string; value: BudgetTier }> = [
  { label: 'Low', value: 'LOW' },
  { label: 'Mid', value: 'MID' },
  { label: 'High', value: 'HIGH' },
];

type WizardStep = {
  key: string;
  eyebrow: string;
  title: string;
  description: string;
};

const STEPS: WizardStep[] = [
  {
    key: 'cuisines',
    eyebrow: 'Step 1 of 5',
    title: 'Pick your favorite cuisines',
    description:
      'Choose a few tastes you want us to prioritize from the start.',
  },
  {
    key: 'diet',
    eyebrow: 'Step 2 of 5',
    title: 'What diet should we prefer?',
    description: 'We will use this to avoid irrelevant recommendations.',
  },
  {
    key: 'spice',
    eyebrow: 'Step 3 of 5',
    title: 'How spicy do you like it?',
    description: 'We will bias recommendations toward your comfort zone.',
  },
  {
    key: 'budget',
    eyebrow: 'Step 4 of 5',
    title: 'Set your typical budget',
    description: 'This helps us keep early suggestions realistic and useful.',
  },
  {
    key: 'items',
    eyebrow: 'Step 5 of 5',
    title: 'Any favorite items?',
    description: 'Optional, but helpful for faster personalization.',
  },
];

type SelectionChipProps = {
  active: boolean;
  label: string;
  onPress: () => void;
};

function SelectionChip({
  active,
  label,
  onPress,
}: SelectionChipProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const progress = useSharedValue(active ? 1 : 0);
  const scale = useSharedValue(active ? 1.02 : 1);

  useEffect(() => {
    progress.value = withTiming(active ? 1 : 0, { duration: 180 });
    scale.value = withSpring(active ? 1.02 : 1, {
      damping: 15,
      stiffness: 180,
    });
  }, [active, progress, scale]);

  const containerStyle = useAnimatedStyle(() => ({
    backgroundColor: interpolateColor(
      progress.value,
      [0, 1],
      [theme.colors.surfaceRaised, theme.colors.primary],
    ),
    borderColor: interpolateColor(
      progress.value,
      [0, 1],
      [theme.colors.border, theme.colors.primary],
    ),
    transform: [{ scale: scale.value }],
  }));

  const textStyle = useAnimatedStyle(() => ({
    color: interpolateColor(
      progress.value,
      [0, 1],
      [theme.colors.secondaryText, theme.colors.onPrimary],
    ),
  }));

  return (
    <Animated.View style={[styles.chip, containerStyle]}>
      <Pressable onPress={onPress} style={styles.chipPressable}>
        <AnimatedText style={[styles.chipText, textStyle]}>
          {label}
        </AnimatedText>
      </Pressable>
    </Animated.View>
  );
}

function normalizePreferences(
  preferences: UserPreferences | null,
): UserPreferences {
  return {
    cuisines: preferences?.cuisines ?? [],
    diet: preferences?.diet ?? null,
    spice_level: preferences?.spice_level ?? null,
    budget: preferences?.budget ?? null,
    favorite_items: preferences?.favorite_items ?? [],
    updated_at: preferences?.updated_at ?? null,
  };
}

export function PreferencesOnboardingScreen(): React.JSX.Element {
  const styles = useThemedStyles(createStyles);
  const { preferences } = usePreferences();
  const { savePreferences, skipPreferencesOnboarding, pushToast } =
    useAppActions();
  const insets = useSafeAreaInsets();
  const initialPreferences = useMemo(
    () => normalizePreferences(preferences),
    [preferences],
  );

  const [stepIndex, setStepIndex] = useState(0);
  const [direction, setDirection] = useState<'forward' | 'backward'>('forward');
  const [submitting, setSubmitting] = useState(false);
  const [cuisines, setCuisines] = useState(initialPreferences.cuisines);
  const [diet, setDiet] = useState<DietPreference | null>(
    initialPreferences.diet,
  );
  const [spiceLevel, setSpiceLevel] = useState<SpiceLevel | null>(
    initialPreferences.spice_level,
  );
  const [budget, setBudget] = useState<BudgetTier | null>(
    initialPreferences.budget,
  );
  const [favoriteItems, setFavoriteItems] = useState(
    initialPreferences.favorite_items,
  );
  const [progressTrackWidth, setProgressTrackWidth] = useState(0);
  const progressWidth = useSharedValue(0);

  const currentStep = STEPS[stepIndex];
  const progress = (stepIndex + 1) / STEPS.length;

  useEffect(() => {
    if (progressTrackWidth <= 0) {
      return;
    }
    progressWidth.value = withTiming(progressTrackWidth * progress, {
      duration: 220,
    });
  }, [progress, progressTrackWidth, progressWidth]);

  const progressBarStyle = useAnimatedStyle(() => ({
    width: progressWidth.value,
  }));

  const enteringAnimation =
    direction === 'forward'
      ? FadeInRight.duration(220)
      : FadeInLeft.duration(220);
  const exitingAnimation =
    direction === 'forward'
      ? FadeOutLeft.duration(180)
      : FadeOutRight.duration(180);

  function toggleListValue(
    currentValues: string[],
    value: string,
    nextSetter: (next: string[]) => void,
  ) {
    if (currentValues.includes(value)) {
      nextSetter(currentValues.filter(entry => entry !== value));
      return;
    }
    nextSetter([...currentValues, value]);
  }

  function handleBack() {
    if (stepIndex === 0) {
      return;
    }
    setDirection('backward');
    setStepIndex(current => current - 1);
  }

  async function handleNext() {
    if (stepIndex < STEPS.length - 1) {
      setDirection('forward');
      setStepIndex(current => current + 1);
      return;
    }

    setSubmitting(true);
    const nextPreferences: UserPreferences = {
      cuisines,
      diet,
      spice_level: spiceLevel,
      budget,
      favorite_items: favoriteItems,
      updated_at: new Date().toISOString(),
    };

    try {
      await savePreferences(nextPreferences, {
        sync: true,
        markOnboardingCompleted: true,
      });
      pushToast(
        'Preferences saved',
        'Your home feed is ready with smarter starting recommendations.',
        'success',
      );
    } catch {
      // The store already surfaces the sync error and keeps the local preference state.
    } finally {
      setSubmitting(false);
    }
  }

  function handleSkip() {
    skipPreferencesOnboarding();
    pushToast(
      'Skipped for now',
      'We will start with highly rated and popular picks.',
      'info',
    );
  }

  function renderStepContent() {
    switch (currentStep.key) {
      case 'cuisines':
        return (
          <View style={styles.optionGrid}>
            {CUISINE_OPTIONS.map(option => (
              <SelectionChip
                key={option}
                active={cuisines.includes(option)}
                label={option}
                onPress={() =>
                  toggleListValue(cuisines, option, next => setCuisines(next))
                }
              />
            ))}
          </View>
        );
      case 'diet':
        return (
          <View style={styles.optionGrid}>
            {DIET_OPTIONS.map(option => (
              <SelectionChip
                key={option.value}
                active={diet === option.value}
                label={option.label}
                onPress={() =>
                  setDiet(current =>
                    current === option.value ? null : option.value,
                  )
                }
              />
            ))}
          </View>
        );
      case 'spice':
        return (
          <View style={styles.optionGrid}>
            {SPICE_OPTIONS.map(option => (
              <SelectionChip
                key={option.value}
                active={spiceLevel === option.value}
                label={option.label}
                onPress={() =>
                  setSpiceLevel(current =>
                    current === option.value ? null : option.value,
                  )
                }
              />
            ))}
          </View>
        );
      case 'budget':
        return (
          <View style={styles.optionGrid}>
            {BUDGET_OPTIONS.map(option => (
              <SelectionChip
                key={option.value}
                active={budget === option.value}
                label={option.label}
                onPress={() =>
                  setBudget(current =>
                    current === option.value ? null : option.value,
                  )
                }
              />
            ))}
          </View>
        );
      case 'items':
        return (
          <View style={styles.optionGrid}>
            {FAVORITE_ITEM_OPTIONS.map(option => (
              <SelectionChip
                key={option}
                active={favoriteItems.includes(option)}
                label={option}
                onPress={() =>
                  toggleListValue(favoriteItems, option, next =>
                    setFavoriteItems(next),
                  )
                }
              />
            ))}
          </View>
        );
      default:
        return null;
    }
  }

  return (
    <SafeAreaView edges={['top']} style={styles.safeArea}>
      <View style={styles.screen}>
        <View style={styles.topSection}>
          <View style={styles.progressMetaRow}>
            <Text style={styles.progressLabel}>{currentStep.eyebrow}</Text>
            <Pressable onPress={handleSkip} style={styles.skipButton}>
              <Text style={styles.skipButtonText}>Skip</Text>
            </Pressable>
          </View>
          <View
            onLayout={event =>
              setProgressTrackWidth(event.nativeEvent.layout.width)
            }
            style={styles.progressTrack}
          >
            <Animated.View style={[styles.progressFill, progressBarStyle]} />
          </View>
        </View>

        <View style={styles.heroCard}>
          <View style={styles.heroGlowPrimary} />
          <View style={styles.heroGlowSecondary} />
          <View style={styles.heroBadge}>
            <Text style={styles.heroBadgeText}>Taste Profile</Text>
          </View>
          <Text style={styles.heroTitle}>
            Build your first recommendation feed.
          </Text>
          <Text style={styles.heroSubtitle}>
            Five quick steps. No pressure. You can edit everything later from
            Profile.
          </Text>
        </View>

        <ScrollView
          contentContainerStyle={styles.stepContentWrap}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.stepCard}>
            <Animated.View
              entering={enteringAnimation}
              exiting={exitingAnimation}
              key={currentStep.key}
              style={styles.stepInner}
            >
              <Text style={styles.stepTitle}>{currentStep.title}</Text>
              <Text style={styles.stepDescription}>
                {currentStep.description}
              </Text>
              {renderStepContent()}
            </Animated.View>
          </View>
        </ScrollView>

        <View
          style={[
            styles.footerBar,
            { paddingBottom: Math.max(insets.bottom + 8, 18) },
          ]}
        >
          <View style={styles.footerButtons}>
            {stepIndex > 0 ? (
              <Pressable onPress={handleBack} style={styles.backButton}>
                <Text style={styles.backButtonText}>Back</Text>
              </Pressable>
            ) : (
              <View style={styles.backButtonPlaceholder} />
            )}
            <Pressable
              disabled={submitting}
              onPress={handleNext}
              style={[
                styles.nextButton,
                submitting ? styles.nextButtonDisabled : null,
              ]}
            >
              <Text style={styles.nextButtonText}>
                {submitting
                  ? 'Saving...'
                  : stepIndex === STEPS.length - 1
                  ? 'Finish'
                  : 'Next'}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </SafeAreaView>
  );
}
