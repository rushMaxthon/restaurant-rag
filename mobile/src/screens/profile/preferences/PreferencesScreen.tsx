import React, { useMemo, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { BottomTabBarHeightContext } from '@react-navigation/bottom-tabs';
import { useAppActions, usePreferences } from '@hooks/useAppStore';
import type {
  BudgetTier,
  DietPreference,
  SpiceLevel,
  UserPreferences,
} from '@/types/app';
import type { RootStackParamList } from '@/navigation/navigationTypes';
import { useThemedStyles } from '@/theme';
import { createStyles } from './styles';

type Props = NativeStackScreenProps<RootStackParamList, 'UserPreferences'>;

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

function SelectionChip({
  active,
  label,
  onPress,
}: {
  active: boolean;
  label: string;
  onPress: () => void;
}) {
  const styles = useThemedStyles(createStyles);
  return (
    <Pressable
      onPress={onPress}
      style={[styles.chip, active ? styles.chipActive : null]}
    >
      <Text style={[styles.chipText, active ? styles.chipTextActive : null]}>
        {label}
      </Text>
    </Pressable>
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

export function PreferencesScreen({
  navigation,
  route,
}: Props): React.JSX.Element {
  const styles = useThemedStyles(createStyles);
  const { preferences } = usePreferences();
  const { savePreferences, skipPreferencesOnboarding, pushToast } =
    useAppActions();
  const tabBarHeight = React.useContext(BottomTabBarHeightContext) ?? 0;
  const isOnboarding = route.params?.mode === 'onboarding';
  const initialPreferences = useMemo(
    () => normalizePreferences(preferences),
    [preferences],
  );

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
  const [submitting, setSubmitting] = useState(false);

  const hasAnySelection =
    cuisines.length > 0 ||
    Boolean(diet) ||
    Boolean(spiceLevel) ||
    Boolean(budget) ||
    favoriteItems.length > 0;

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

  async function handleSave() {
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
        'Recommendations will now align more closely with your tastes.',
        'success',
      );

      if (!isOnboarding && navigation.canGoBack()) {
        navigation.goBack();
      }
    } catch {
      // The store already surfaces the sync error and preserves local selections.
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

  return (
    <SafeAreaView edges={['top']} style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={[
          styles.content,
          { paddingBottom: Math.max(tabBarHeight + 16, 36) },
        ]}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.heroCard}>
          <View style={styles.heroGlowPrimary} />
          <View style={styles.heroGlowSecondary} />
          <View style={styles.topBar}>
            <Pressable
              onPress={() =>
                isOnboarding
                  ? handleSkip()
                  : navigation.canGoBack()
                  ? navigation.goBack()
                  : undefined
              }
              style={styles.topBarAction}
            >
              <Text style={styles.topBarActionText}>
                {isOnboarding ? 'Skip' : 'Back'}
              </Text>
            </Pressable>
            <View style={styles.heroBadge}>
              <Text style={styles.heroBadgeText}>Taste Profile</Text>
            </View>
            <View style={styles.topBarAction} />
          </View>

          <Text style={styles.heroTitle}>
            {isOnboarding
              ? 'Tell us what you like.'
              : 'Fine-tune your preferences.'}
          </Text>
          <Text style={styles.heroSubtitle}>
            {isOnboarding
              ? 'Set a few food signals once so we can make smarter picks from the very first session.'
              : 'Update cuisines, budget, spice, and favorite dishes anytime to keep recommendations fresh.'}
          </Text>
        </View>

        <View style={styles.sectionCard}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Favorite cuisines</Text>
            <Text style={styles.sectionSubtitle}>
              Pick a few cuisines you usually reach for.
            </Text>
          </View>
          <View style={styles.chipRow}>
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
        </View>

        <View style={styles.sectionCard}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Diet</Text>
            <Text style={styles.sectionSubtitle}>
              Choose the default style you want us to prefer.
            </Text>
          </View>
          <View style={styles.chipRow}>
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
        </View>

        <View style={styles.sectionCard}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Spice level</Text>
            <Text style={styles.sectionSubtitle}>
              We will bias suggestions toward your comfort zone.
            </Text>
          </View>
          <View style={styles.chipRow}>
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
        </View>

        <View style={styles.sectionCard}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Budget</Text>
            <Text style={styles.sectionSubtitle}>
              Keep recommendations within the price range you usually prefer.
            </Text>
          </View>
          <View style={styles.chipRow}>
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
        </View>

        <View style={styles.sectionCard}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Favorite items</Text>
            <Text style={styles.sectionSubtitle}>
              Optional, but helpful for faster early recommendations.
            </Text>
          </View>
          <View style={styles.chipRow}>
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
        </View>

        <View style={styles.footerCard}>
          <Text style={styles.footerTitle}>
            {hasAnySelection
              ? 'Looks good'
              : 'You can skip and we will start with crowd favorites'}
          </Text>
          <Text style={styles.footerText}>
            {isOnboarding
              ? 'You can edit these later from Profile > User Preferences.'
              : 'Changes are saved locally and synced to your account when available.'}
          </Text>

          <View style={styles.buttonRow}>
            {isOnboarding ? (
              <Pressable onPress={handleSkip} style={styles.secondaryButton}>
                <Text style={styles.secondaryButtonText}>Skip</Text>
              </Pressable>
            ) : null}
            <Pressable
              disabled={submitting}
              onPress={handleSave}
              style={[
                styles.primaryButton,
                submitting ? styles.primaryButtonDisabled : null,
              ]}
            >
              <Text style={styles.primaryButtonText}>
                {submitting
                  ? 'Saving...'
                  : isOnboarding
                  ? 'Continue'
                  : 'Save preferences'}
              </Text>
            </Pressable>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
