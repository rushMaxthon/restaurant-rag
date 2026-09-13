/**
 * Onboarding, rendered from whatever the restaurant configured.
 *
 * There are no steps in this file. The wizard asks `/preferences/schema` what to
 * ask, renders one step per question, and validates each from the question's own
 * `input_type`, `is_required`, `min_selections`, `max_selections` and
 * `allows_free_text`. An owner adding a question, withdrawing an option or
 * hiding an inherited question changes this screen with no release.
 *
 * The one thing it still hardcodes is a fallback questionnaire, used only when
 * the schema cannot be fetched. Onboarding gates the whole app, so a dead
 * network has to produce a questionnaire rather than a dead end.
 */

import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';
import {SafeAreaView, useSafeAreaInsets} from 'react-native-safe-area-context';
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
import {useAppActions, usePreferences, useSession} from '@hooks/useAppStore';
import {api} from '@services/api';
import type {
  PreferenceQuestion,
  PreferenceSchema,
  UserPreferences,
} from '@/types/app';
import {useTheme, useThemedStyles} from '@/theme';
import {FALLBACK_PREFERENCE_SCHEMA} from '@/data/preferenceFallbackSchema';
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
} from '@utils/preferenceForm';
import {createStyles} from './wizardStyles';

const AnimatedText = Animated.createAnimatedComponent(Text);

type SelectionChipProps = {
  active: boolean;
  label: string;
  disabled?: boolean;
  onPress: () => void;
};

function SelectionChip({
  active,
  label,
  disabled = false,
  onPress,
}: SelectionChipProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const progress = useSharedValue(active ? 1 : 0);
  const scale = useSharedValue(active ? 1.02 : 1);

  useEffect(() => {
    progress.value = withTiming(active ? 1 : 0, {duration: 180});
    scale.value = withSpring(active ? 1.02 : 1, {damping: 15, stiffness: 180});
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
    transform: [{scale: scale.value}],
  }));

  const textStyle = useAnimatedStyle(() => ({
    color: interpolateColor(
      progress.value,
      [0, 1],
      [theme.colors.secondaryText, theme.colors.onPrimary],
    ),
  }));

  return (
    <Animated.View
      style={[styles.chip, containerStyle, disabled ? {opacity: 0.45} : null]}
    >
      <Pressable disabled={disabled} onPress={onPress} style={styles.chipPressable}>
        <AnimatedText style={[styles.chipText, textStyle]}>{label}</AnimatedText>
      </Pressable>
    </Animated.View>
  );
}

export function PreferencesOnboardingScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const insets = useSafeAreaInsets();
  const {savePreferences, skipPreferencesOnboarding, pushToast} = useAppActions();
  const {preferences} = usePreferences();
  const {token} = useSession();

  const [schema, setSchema] = useState<PreferenceSchema | null>(null);
  const [loading, setLoading] = useState(true);
  const [usingFallback, setUsingFallback] = useState(false);
  const [selections, setSelections] = useState<SelectionMap>({});
  const [stepIndex, setStepIndex] = useState(0);
  const [direction, setDirection] = useState<'forward' | 'backward'>('forward');
  const [submitting, setSubmitting] = useState(false);
  const [touched, setTouched] = useState(false);
  const [draftText, setDraftText] = useState('');
  const [progressTrackWidth, setProgressTrackWidth] = useState(0);

  useEffect(() => {
    let active = true;

    async function load() {
      let resolved: PreferenceSchema;
      let fallback = false;
      try {
        resolved = await api.getPreferenceSchema();
        // An owner who hid everything would otherwise strand the customer on an
        // empty wizard with nothing to press.
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
      // Someone re-running onboarding keeps what they already chose.
      if (token && !fallback) {
        try {
          const existing = await api.getPreferenceAnswers(token);
          if (active) {
            initial = buildSelections(resolved, existing.answers);
          }
        } catch {
          // Not fatal - they simply start from a blank questionnaire.
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
  }, [token]);

  const questions = schema?.questions ?? [];
  const currentQuestion: PreferenceQuestion | undefined = questions[stepIndex];
  const currentSelection = currentQuestion
    ? selections[currentQuestion.id] ?? EMPTY_SELECTION
    : EMPTY_SELECTION;
  const currentError = currentQuestion
    ? validateQuestion(currentQuestion, currentSelection)
    : null;

  const progress = questions.length > 0 ? (stepIndex + 1) / questions.length : 0;
  const progressBarStyle = useAnimatedStyle(() => ({
    width: progressTrackWidth * progress,
  }));

  const setSelection = useCallback(
    (questionId: string, next: ReturnType<typeof toggleOption>) => {
      setSelections(current => ({...current, [questionId]: next}));
    },
    [],
  );

  const handleBack = () => {
    if (stepIndex === 0) {
      return;
    }
    setTouched(false);
    setDraftText('');
    setDirection('backward');
    setStepIndex(current => current - 1);
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
      setStepIndex(current => current + 1);
      return;
    }

    setSubmitting(true);
    try {
      if (usingFallback || !token) {
        // No account yet, or the schema came from the offline fallback where the
        // ids mean nothing to the server. Either way the answers are projected
        // here and kept locally, so the first home feed is still personalised.
        const legacy = selectionsToLegacy(schema, selections);
        await savePreferences(
          {...legacy, updated_at: preferences?.updated_at ?? null} as UserPreferences,
          {sync: Boolean(token)},
        );
      } else {
        const saved = await api.savePreferenceAnswers(
          token,
          toSubmissions(schema, selections),
        );
        // The server already persisted this; storing the projection locally
        // without re-syncing keeps the ranked feed consistent immediately.
        await savePreferences(saved.legacy, {sync: false});
      }
    } catch (error) {
      pushToast(
        'Preferences not saved',
        error instanceof Error
          ? error.message
          : 'Unable to save your preferences right now.',
        'error',
      );
      setSubmitting(false);
      return;
    }
    setSubmitting(false);
  };

  const enteringAnimation = direction === 'forward' ? FadeInRight : FadeInLeft;
  const exitingAnimation = direction === 'forward' ? FadeOutLeft : FadeOutRight;

  const capacityHint = useMemo(() => {
    if (!currentQuestion) {
      return null;
    }
    const parts: string[] = [];
    if (currentQuestion.max_selections != null) {
      parts.push(`Choose up to ${currentQuestion.max_selections}`);
    }
    if (currentQuestion.is_required) {
      parts.push('Required');
    } else {
      parts.push('Optional');
    }
    return parts.join(' · ');
  }, [currentQuestion]);

  if (loading) {
    return (
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.loadingWrap}>
          <ActivityIndicator color={theme.colors.primary} />
          <Text style={styles.loadingText}>Setting up your taste profile…</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!schema || !currentQuestion) {
    // Reachable only if the fallback itself were emptied. Skipping is the one
    // sane exit, since onboarding gates the rest of the app.
    return (
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.loadingWrap}>
          <Text style={styles.loadingText}>
            No preference questions are set up right now.
          </Text>
          <Pressable onPress={skipPreferencesOnboarding} style={styles.nextButton}>
            <Text style={styles.nextButtonText}>Continue</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
      <View style={styles.screen}>
        <View style={styles.topSection}>
          <View style={styles.progressMetaRow}>
            <Text style={styles.progressLabel}>
              Step {stepIndex + 1} of {questions.length}
            </Text>
            <Pressable onPress={skipPreferencesOnboarding} style={styles.skipButton}>
              <Text style={styles.skipButtonText}>Skip</Text>
            </Pressable>
          </View>
          <View
            onLayout={event => setProgressTrackWidth(event.nativeEvent.layout.width)}
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
            {questions.length} quick {questions.length === 1 ? 'step' : 'steps'}. No
            pressure. You can edit everything later from Profile.
          </Text>
        </View>

        <ScrollView
          contentContainerStyle={styles.stepContentWrap}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.stepCard}>
            <Animated.View
              entering={enteringAnimation}
              exiting={exitingAnimation}
              key={currentQuestion.id}
              style={styles.stepInner}
            >
              <Text style={styles.stepTitle}>{currentQuestion.prompt}</Text>
              {currentQuestion.help_text ? (
                <Text style={styles.stepDescription}>{currentQuestion.help_text}</Text>
              ) : null}

              <View style={styles.optionGrid}>
                {currentQuestion.options.map(option => {
                  const active = currentSelection.optionIds.includes(option.id);
                  return (
                    <SelectionChip
                      active={active}
                      disabled={!active && isAtCapacity(currentQuestion, currentSelection)}
                      key={option.id}
                      label={option.label}
                      onPress={() =>
                        setSelection(
                          currentQuestion.id,
                          toggleOption(currentQuestion, currentSelection, option.id),
                        )
                      }
                    />
                  );
                })}

                {currentSelection.freeText.map(value => (
                  <Pressable
                    key={`typed:${value}`}
                    onPress={() =>
                      setSelection(
                        currentQuestion.id,
                        removeFreeText(currentSelection, value),
                      )
                    }
                    style={styles.typedChip}
                  >
                    <Text style={styles.typedChipText}>{value}</Text>
                    <Text style={styles.typedChipRemove}>×</Text>
                  </Pressable>
                ))}
              </View>

              {currentQuestion.allows_free_text ? (
                <View style={styles.freeTextRow}>
                  <TextInput
                    onChangeText={setDraftText}
                    onSubmitEditing={() => {
                      setSelection(
                        currentQuestion.id,
                        addFreeText(currentQuestion, currentSelection, draftText),
                      );
                      setDraftText('');
                    }}
                    placeholder="Add your own"
                    placeholderTextColor={theme.colors.hint}
                    returnKeyType="done"
                    style={styles.freeTextInput}
                    value={draftText}
                  />
                  <Pressable
                    disabled={!draftText.trim()}
                    onPress={() => {
                      setSelection(
                        currentQuestion.id,
                        addFreeText(currentQuestion, currentSelection, draftText),
                      );
                      setDraftText('');
                    }}
                    style={[
                      styles.freeTextAdd,
                      !draftText.trim() ? {opacity: 0.5} : null,
                    ]}
                  >
                    <Text style={styles.freeTextAddLabel}>Add</Text>
                  </Pressable>
                </View>
              ) : null}

              {touched && currentError ? (
                <Text style={styles.errorText}>{currentError}</Text>
              ) : (
                <Text style={styles.helperText}>
                  {capacityHint}
                  {selectionCount(currentSelection) > 0
                    ? ` · ${describeSelection(currentQuestion, currentSelection)}`
                    : ''}
                </Text>
              )}
            </Animated.View>
          </View>
        </ScrollView>

        <View
          style={[
            styles.footerBar,
            {paddingBottom: Math.max(insets.bottom + 8, 18)},
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
              style={[styles.nextButton, submitting ? styles.nextButtonDisabled : null]}
            >
              <Text style={styles.nextButtonText}>
                {submitting
                  ? 'Saving…'
                  : stepIndex === questions.length - 1
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
