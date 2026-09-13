/**
 * Profile → Taste preferences.
 *
 * The same questionnaire the onboarding wizard asks, on one page instead of a
 * sequence — editing is a review task, not a guided one, so everything is
 * visible at once and Save applies the lot.
 *
 * Like the wizard, it knows nothing about the questions in advance. It also has
 * one job the wizard does not: showing an answer the customer gave to something
 * the restaurant has since hidden or withdrawn. That answer is theirs, so it is
 * surfaced and removable rather than quietly dropped.
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
import {SafeAreaView} from 'react-native-safe-area-context';
import type {NativeStackScreenProps} from '@react-navigation/native-stack';
import {useAppActions, useSession} from '@hooks/useAppStore';
import {api} from '@services/api';
import type {
  PreferenceAnswer,
  PreferenceSchema,
} from '@/types/app';
import type {RootStackParamList} from '@/navigation/navigationTypes';
import {useTheme, useThemedStyles} from '@/theme';
import {FALLBACK_PREFERENCE_SCHEMA} from '@/data/preferenceFallbackSchema';
import {
  EMPTY_SELECTION,
  addFreeText,
  buildSelections,
  isAtCapacity,
  removeFreeText,
  selectionsToLegacy,
  toSubmissions,
  toggleOption,
  validateQuestion,
  type SelectionMap,
} from '@utils/preferenceForm';
import {createStyles} from './styles';

type Props = NativeStackScreenProps<RootStackParamList, 'UserPreferences'>;

function SelectionChip({
  active,
  label,
  disabled = false,
  onPress,
}: {
  active: boolean;
  label: string;
  disabled?: boolean;
  onPress: () => void;
}): React.JSX.Element {
  const styles = useThemedStyles(createStyles);
  return (
    <Pressable
      disabled={disabled}
      onPress={onPress}
      style={[
        styles.chip,
        active ? styles.chipActive : null,
        disabled ? {opacity: 0.45} : null,
      ]}
    >
      <Text style={[styles.chipText, active ? styles.chipTextActive : null]}>
        {label}
      </Text>
    </Pressable>
  );
}

export function PreferencesScreen({navigation, route}: Props): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const {savePreferences, skipPreferencesOnboarding, pushToast} = useAppActions();
  const {token} = useSession();
  const isOnboarding = route.params?.mode === 'onboarding';

  const [schema, setSchema] = useState<PreferenceSchema | null>(null);
  const [answers, setAnswers] = useState<PreferenceAnswer[]>([]);
  const [selections, setSelections] = useState<SelectionMap>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [usingFallback, setUsingFallback] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    let active = true;

    async function load() {
      let resolved: PreferenceSchema;
      let fallback = false;
      try {
        resolved = await api.getPreferenceSchema();
        if (resolved.questions.length === 0) {
          resolved = FALLBACK_PREFERENCE_SCHEMA;
          fallback = true;
        }
      } catch {
        resolved = FALLBACK_PREFERENCE_SCHEMA;
        fallback = true;
      }

      let existing: PreferenceAnswer[] = [];
      if (token && !fallback) {
        try {
          existing = (await api.getPreferenceAnswers(token)).answers;
        } catch {
          // Editing still works; they just start from what is on screen.
        }
      }

      if (!active) {
        return;
      }
      setSchema(resolved);
      setUsingFallback(fallback);
      setAnswers(existing);
      setSelections(buildSelections(resolved, existing));
      setLoading(false);
    }

    void load();
    return () => {
      active = false;
    };
  }, [token]);

  const questions = schema?.questions ?? [];

  /**
   * Answers the questionnaire can no longer represent: the restaurant hid the
   * question, or withdrew the option. Kept visible so nothing a customer told
   * us disappears without explanation.
   */
  const strandedAnswers = useMemo(() => {
    const liveIds = new Set(questions.map(question => question.id));
    return answers.filter(
      answer => answer.has_stale_selection || !liveIds.has(answer.question_id),
    );
  }, [answers, questions]);

  const setSelection = useCallback(
    (questionId: string, next: ReturnType<typeof toggleOption>) => {
      setSelections(current => ({...current, [questionId]: next}));
    },
    [],
  );

  const firstError = useMemo(() => {
    for (const question of questions) {
      const error = validateQuestion(
        question,
        selections[question.id] ?? EMPTY_SELECTION,
      );
      if (error) {
        return `${question.prompt}: ${error}`;
      }
    }
    return null;
  }, [questions, selections]);

  const handleSave = async () => {
    if (!schema) {
      return;
    }
    if (firstError) {
      setTouched(true);
      return;
    }

    setSubmitting(true);
    try {
      if (usingFallback || !token) {
        await savePreferences(
          {
            ...selectionsToLegacy(schema, selections),
            updated_at: new Date().toISOString(),
          },
          {sync: Boolean(token), markOnboardingCompleted: isOnboarding || undefined},
        );
      } else {
        const saved = await api.savePreferenceAnswers(
          token,
          toSubmissions(schema, selections),
        );
        await savePreferences(saved.legacy, {
          sync: false,
          markOnboardingCompleted: isOnboarding || undefined,
        });
      }
      pushToast(
        'Preferences updated',
        'Your recommendations will use this from now on.',
        'success',
      );
      if (isOnboarding) {
        skipPreferencesOnboarding();
      } else {
        navigation.goBack();
      }
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

  if (loading) {
    return (
      <SafeAreaView edges={['bottom']} style={styles.safeArea}>
        <View style={styles.loadingWrap}>
          <ActivityIndicator color={theme.colors.primary} />
          <Text style={styles.loadingText}>Loading your preferences…</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.heroCard}>
          <View style={styles.heroGlowPrimary} />
          <View style={styles.heroGlowSecondary} />
          <View style={styles.heroBadge}>
            <Text style={styles.heroBadgeText}>Taste Profile</Text>
          </View>
          <Text style={styles.heroTitle}>Fine-tune your preferences.</Text>
          <Text style={styles.heroSubtitle}>
            Everything here feeds your recommendations. Change as much or as little
            as you like.
          </Text>
        </View>

        {questions.map(question => {
          const selection = selections[question.id] ?? EMPTY_SELECTION;
          const error = validateQuestion(question, selection);
          return (
            <View key={question.id} style={styles.sectionCard}>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>{question.prompt}</Text>
                {question.help_text ? (
                  <Text style={styles.sectionSubtitle}>{question.help_text}</Text>
                ) : null}
              </View>

              <View style={styles.chipRow}>
                {question.options.map(option => {
                  const active = selection.optionIds.includes(option.id);
                  return (
                    <SelectionChip
                      active={active}
                      disabled={!active && isAtCapacity(question, selection)}
                      key={option.id}
                      label={option.label}
                      onPress={() =>
                        setSelection(
                          question.id,
                          toggleOption(question, selection, option.id),
                        )
                      }
                    />
                  );
                })}
                {selection.freeText.map(value => (
                  <SelectionChip
                    active
                    key={`typed:${value}`}
                    label={`${value}  ×`}
                    onPress={() =>
                      setSelection(question.id, removeFreeText(selection, value))
                    }
                  />
                ))}
              </View>

              {question.allows_free_text ? (
                <View style={styles.freeTextRow}>
                  <TextInput
                    onChangeText={value =>
                      setDrafts(current => ({...current, [question.id]: value}))
                    }
                    onSubmitEditing={() => {
                      setSelection(
                        question.id,
                        addFreeText(question, selection, drafts[question.id] ?? ''),
                      );
                      setDrafts(current => ({...current, [question.id]: ''}));
                    }}
                    placeholder="Add your own"
                    placeholderTextColor={theme.colors.hint}
                    returnKeyType="done"
                    style={styles.freeTextInput}
                    value={drafts[question.id] ?? ''}
                  />
                  <Pressable
                    disabled={!(drafts[question.id] ?? '').trim()}
                    onPress={() => {
                      setSelection(
                        question.id,
                        addFreeText(question, selection, drafts[question.id] ?? ''),
                      );
                      setDrafts(current => ({...current, [question.id]: ''}));
                    }}
                    style={[
                      styles.freeTextAdd,
                      !(drafts[question.id] ?? '').trim() ? {opacity: 0.5} : null,
                    ]}
                  >
                    <Text style={styles.freeTextAddLabel}>Add</Text>
                  </Pressable>
                </View>
              ) : null}

              {touched && error ? (
                <Text style={styles.errorText}>{error}</Text>
              ) : null}
            </View>
          );
        })}

        {strandedAnswers.length > 0 ? (
          <View style={styles.sectionCard}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>No longer asked</Text>
              <Text style={styles.sectionSubtitle}>
                {`${
                  strandedAnswers.length === 1 ? 'This answer' : 'These answers'
                } came from a question the restaurant has since changed. It is kept
                 for you, and still counts toward recommendations.`}
              </Text>
            </View>
            <View style={styles.staleNotice}>
              {strandedAnswers.map(answer => (
                <Text key={answer.question_id} style={styles.staleNoticeText}>
                  {`${answer.question_key}: ${answer.labels.join(', ')}`}
                </Text>
              ))}
            </View>
          </View>
        ) : null}

        <View style={styles.footerCard}>
          <Text style={styles.footerTitle}>Ready when you are</Text>
          <Text style={styles.footerText}>
            Saving updates your home feed straight away.
          </Text>
          {touched && firstError ? (
            <Text style={styles.errorText}>{firstError}</Text>
          ) : null}
          <View style={styles.buttonRow}>
            {isOnboarding ? (
              <Pressable onPress={skipPreferencesOnboarding} style={styles.secondaryButton}>
                <Text style={styles.secondaryButtonText}>Skip</Text>
              </Pressable>
            ) : (
              <Pressable onPress={() => navigation.goBack()} style={styles.secondaryButton}>
                <Text style={styles.secondaryButtonText}>Cancel</Text>
              </Pressable>
            )}
            <Pressable
              disabled={submitting}
              onPress={() => void handleSave()}
              style={[
                styles.primaryButton,
                submitting ? styles.primaryButtonDisabled : null,
              ]}
            >
              <Text style={styles.primaryButtonText}>
                {submitting ? 'Saving…' : 'Save preferences'}
              </Text>
            </Pressable>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
