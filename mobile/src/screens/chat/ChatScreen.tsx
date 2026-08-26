import React, { useEffect, useMemo, useRef, useState } from 'react';
import type { ListRenderItem } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Alert,
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import { useBottomTabBarHeight } from '@react-navigation/bottom-tabs';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import { ChatBubble } from '@components/ChatBubble';
import { SkeletonBlock } from '@components/SkeletonBlock';
import { useAppActions, useChatSession, useSession } from '@hooks/useAppStore';
import { api } from '@services/api';
import { buildMenuItemFromGeneratedComboItem } from '@utils/generatedComboCart';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type {
  ChatHistoryItem,
  ChatMessageResponse,
  ChatSuggestionItem,
  GeneratedCombo,
  MenuItem,
  PersonalizedOfferCard,
  Restaurant,
} from '@/types/app';
import type { RootStackParamList } from '@/navigation/AppNavigator';

const promptChips = [
  'Budget-friendly dinner ideas',
  'Recommend something spicy and veg',
  'What should I order for a group?',
];
const THINKING_INDICATOR_DELAY_MS = 250;

function sortChatHistory(rows: ChatHistoryItem[]): ChatHistoryItem[] {
  return [...rows].sort((left, right) => {
    const leftTime = Date.parse(left.created_at);
    const rightTime = Date.parse(right.created_at);

    if (
      Number.isFinite(leftTime) &&
      Number.isFinite(rightTime) &&
      leftTime !== rightTime
    ) {
      return leftTime - rightTime;
    }

    if (left.role !== right.role) {
      return left.role === 'USER' ? -1 : 1;
    }

    return left.id.localeCompare(right.id);
  });
}

function extractHistorySuggestions(
  entry: ChatHistoryItem,
): ChatSuggestionItem[] {
  if (entry.role !== 'ASSISTANT') {
    return [];
  }
  const rawSuggestions = entry.context_payload?.suggestions;
  return Array.isArray(rawSuggestions)
    ? (rawSuggestions as ChatSuggestionItem[])
    : [];
}

function extractHistoryComboSuggestions(
  entry: ChatHistoryItem,
): GeneratedCombo[] {
  if (entry.role !== 'ASSISTANT') {
    return [];
  }
  const rawComboSuggestions = entry.context_payload?.combo_suggestions;
  return Array.isArray(rawComboSuggestions)
    ? (rawComboSuggestions as GeneratedCombo[])
    : [];
}

function extractHistoryOfferSuggestions(
  entry: ChatHistoryItem,
): PersonalizedOfferCard[] {
  if (entry.role !== 'ASSISTANT') {
    return [];
  }
  const rawOfferSuggestions = entry.context_payload?.offer_suggestions;
  return Array.isArray(rawOfferSuggestions)
    ? (rawOfferSuggestions as PersonalizedOfferCard[])
    : [];
}

function ChatHero({
  title,
  subtitle,
  statLabel,
  statValue,
}: {
  title: string;
  subtitle: string;
  statLabel: string;
  statValue: string;
}) {
  // Subscribes to the ACTIVE theme. This file used to also export a
  // `createStyles(theme)` stylesheet evaluated once at import time against the
  // light theme; that export, and the 40-odd others like it, have been removed.
  const styles = useThemedStyles(createStyles);

  return (
    <View style={styles.heroCard}>
      <View style={styles.heroGlowPrimary} />
      <View style={styles.heroGlowSecondary} />
      <View style={styles.heroBadge}>
        <Text style={styles.heroBadgeText}>AI Concierge</Text>
      </View>
      <Text style={styles.heroTitle}>{title}</Text>
      <Text style={styles.heroSubtitle}>{subtitle}</Text>
      <View style={styles.heroStat}>
        <Text style={styles.heroStatLabel}>{statLabel}</Text>
        <Text style={styles.heroStatValue}>{statValue}</Text>
      </View>
    </View>
  );
}

function LoginPromptCard({ onPress }: { onPress: () => void }) {
  // Same fix as ChatHero: both the styles AND the icon colour below were read
  // from the frozen light-theme module exports.
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);

  return (
    <View style={styles.loginCard}>
      <View style={styles.loginCardIcon}>
        <Icon
          color={theme.colors.primary}
          name="person-circle-outline"
          size={20}
        />
      </View>
      <Text style={styles.loginCardTitle}>Your chat is waiting.</Text>
      <Text style={styles.loginCardText}>
        Login to get personalized dish ideas, account-aware suggestions, and
        live restaurant context.
      </Text>
      <Pressable onPress={onPress} style={styles.loginCardButton}>
        <Text style={styles.loginCardButtonText}>Login</Text>
      </Pressable>
    </View>
  );
}

export function ChatScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation =
    useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const tabBarHeight = useBottomTabBarHeight();
  const { width } = useWindowDimensions();
  const { token } = useSession();
  const chatSessionId = useChatSession();
  const {
    setChatSessionId,
    addToCart,
    requestAddToCart,
    setSelectedPersonalizedOffer,
    pushToast,
  } = useAppActions();
  const listRef = useRef<FlatList<ChatHistoryItem>>(null);
  const thinkingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [history, setHistory] = useState<ChatHistoryItem[]>([]);
  const [message, setMessage] = useState('');
  const [assistantSuggestions, setAssistantSuggestions] = useState<
    Record<string, ChatSuggestionItem[]>
  >({});
  const [assistantComboSuggestions, setAssistantComboSuggestions] = useState<
    Record<string, GeneratedCombo[]>
  >({});
  const [assistantOfferSuggestions, setAssistantOfferSuggestions] = useState<
    Record<string, PersonalizedOfferCard[]>
  >({});
  const [loading, setLoading] = useState(Boolean(token));
  const [sending, setSending] = useState(false);
  const [showThinkingIndicator, setShowThinkingIndicator] = useState(false);
  const [keyboardVisible, setKeyboardVisible] = useState(false);
  const [clearing, setClearing] = useState(false);
  const showStarterPrompts = Boolean(token) && history.length === 0 && !sending;
  const horizontalScreenPadding = width < 380 ? 16 : theme.spacing.screen;
  const keyboardVerticalOffset = Platform.OS === 'ios' ? 0 : 0;
  const composerBottomSpacing = keyboardVisible
    ? Platform.OS === 'ios'
      ? 4
      : 8
    : Platform.OS === 'ios'
    ? 8
    : Math.max(tabBarHeight - 46, 10);
  const threadBottomPadding = keyboardVisible
    ? Platform.OS === 'ios'
      ? 8
      : 10
    : width < 380
    ? 18
    : 22;

  useEffect(() => {
    return () => {
      if (thinkingTimerRef.current) {
        clearTimeout(thinkingTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const showEvent =
      Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvent =
      Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';

    const handleKeyboardShow = () => {
      setKeyboardVisible(true);
      requestAnimationFrame(() => {
        listRef.current?.scrollToEnd({ animated: true });
      });
    };
    const handleKeyboardHide = () => {
      setKeyboardVisible(false);
    };

    const showSubscription = Keyboard.addListener(
      showEvent,
      handleKeyboardShow,
    );
    const hideSubscription = Keyboard.addListener(
      hideEvent,
      handleKeyboardHide,
    );

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, []);

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }

    let active = true;
    api
      .getChatHistory(token, chatSessionId)
      .then(rows => {
        if (active) {
          setHistory(sortChatHistory(rows));
        }
      })
      .catch(error => {
        if (active) {
          pushToast(
            'Chat unavailable',
            error instanceof Error ? error.message : 'Unable to load chat.',
            'error',
          );
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [chatSessionId, pushToast, token]);

  const listData = useMemo(() => sortChatHistory(history), [history]);

  // Keyed on the message count, not the array: per-token text growth is
  // pinned by onContentSizeChange, so animating here for every token would
  // just queue redundant scroll work.
  const listLength = listData.length;
  useEffect(() => {
    if (listLength === 0) {
      return;
    }
    const timer = setTimeout(() => {
      listRef.current?.scrollToEnd({ animated: true });
    }, 80);
    return () => clearTimeout(timer);
  }, [listLength]);

  const addSuggestionToCart = React.useCallback((item: ChatSuggestionItem) => {
    navigation.navigate('MenuItemDetail', {
      itemId: item.id,
      restaurantId: item.restaurant_id,
      restaurantName: item.restaurant_name,
    });
  }, [navigation]);

  const addGeneratedComboToCart = React.useCallback((combo: GeneratedCombo) => {
    for (const item of combo.items) {
      addToCart(
        buildMenuItemFromGeneratedComboItem(item, {
          source: 'home-generated-combo',
          restaurantId: combo.restaurant_id,
          restaurantLocationId: combo.restaurant_location_id,
          restaurantLocationName: combo.restaurant_location_name,
          restaurantCuisineType: null,
          createdAt: combo.created_at,
          updatedAt: combo.updated_at,
        }),
        combo.restaurant_id,
        combo.restaurant_name,
        {
          quantity: item.quantity,
          silent: true,
        },
      );
    }
    pushToast(
      'Combo added',
      `${combo.combo_name} is now in your cart.`,
      'success',
    );
  }, [addToCart, pushToast]);

  const openSuggestionDetail = React.useCallback((item: ChatSuggestionItem) => {
    navigation.navigate('MenuItemDetail', {
      itemId: item.id,
      restaurantId: item.restaurant_id,
      restaurantName: item.restaurant_name,
    });
  }, [navigation]);

  const openGeneratedCombo = React.useCallback((combo: GeneratedCombo) => {
    navigation.navigate('Restaurant', {
      restaurantId: combo.restaurant_id,
      restaurantName: combo.restaurant_name,
    });
  }, [navigation]);

  const openOffer = React.useCallback((offer: PersonalizedOfferCard) => {
    setSelectedPersonalizedOffer({
      generatedOfferId: offer.generated_offer_id,
      generatedOfferUserMatchId: offer.generated_offer_user_match_id,
      offerId: offer.offer_id,
      offerName: offer.offer_name,
      offerType: offer.offer_type,
      audienceType: offer.audience_type,
      targetType: offer.target_type,
      restaurantId: offer.restaurant_id,
      restaurantName: offer.restaurant_name,
      restaurantLocationId: offer.restaurant_location_id,
      restaurantLocationName: offer.restaurant_location_name,
      offerRestaurantLocationId: offer.offer_restaurant_location_id,
      menuItemId: offer.menu_item_id,
      generatedComboId: offer.generated_combo_id,
      cuisineType: offer.cuisine_type,
      title: offer.title,
      ctaLabel: offer.cta_label,
      discountType: offer.discount_type,
      discountValue: offer.discount_value,
      discountLabel: offer.discount_label,
      maxDiscountAmount: offer.max_discount_amount,
      minimumOrderAmount: offer.minimum_order_amount,
      termsLabel: offer.terms_label,
      expiresAt: offer.expires_at,
    });
    if (token) {
      void api
        .trackPersonalizedOfferEvents(token, [
          {
            offer_id: offer.offer_id,
            generated_offer_id: offer.generated_offer_id,
            generated_offer_user_match_id: offer.generated_offer_user_match_id,
            event_type: 'CLICKED',
            target_type: offer.target_type,
            target_id:
              offer.menu_item_id ??
              offer.generated_combo_id ??
              offer.restaurant_location_id ??
              offer.restaurant_id,
          },
        ])
        .catch(() => undefined);
    }

    if (offer.target_type === 'ITEM' && offer.menu_item_id) {
      navigation.navigate('MenuItemDetail', {
        itemId: offer.menu_item_id,
        restaurantId: offer.restaurant_id,
        restaurantName: offer.restaurant_name,
      });
      return;
    }

    navigation.navigate('Restaurant', {
      restaurantId: offer.restaurant_id,
      restaurantName: offer.restaurant_name,
    });
  }, [navigation, setSelectedPersonalizedOffer, token]);

  const send = async (nextMessage: string) => {
    if (!token) {
      pushToast(
        'Login required',
        'Please login to use the chat assistant.',
        'error',
      );
      navigation.navigate('Login');
      return;
    }
    if (!nextMessage.trim()) {
      return;
    }

    const trimmedMessage = nextMessage.trim();
    const optimisticId = `user-${Date.now()}`;
    const optimisticTimestamp = new Date().toISOString();
    const optimisticUserMessage: ChatHistoryItem = {
      id: optimisticId,
      session_id: chatSessionId ?? 'pending-session',
      restaurant_id: null,
      restaurant_location_id: null,
      role: 'USER',
      message: trimmedMessage,
      context_payload: {},
      created_at: optimisticTimestamp,
      updated_at: optimisticTimestamp,
    };

    setHistory(current => [...current, optimisticUserMessage]);
    setMessage('');
    setSending(true);
    setShowThinkingIndicator(false);
    if (thinkingTimerRef.current) {
      clearTimeout(thinkingTimerRef.current);
    }
    thinkingTimerRef.current = setTimeout(() => {
      setShowThinkingIndicator(true);
    }, THINKING_INDICATOR_DELAY_MS);
    // Progressive rendering state for the streamed assistant bubble. Cards
    // are intentionally NOT rendered during streaming: they register from the
    // done payload so the reply text always finishes before cards appear.
    const streamedAssistantId = `assistant-stream-${optimisticId}`;
    let streamBubbleVisible = false;
    let streamedText = '';

    const hideThinkingIndicator = () => {
      if (thinkingTimerRef.current) {
        clearTimeout(thinkingTimerRef.current);
        thinkingTimerRef.current = null;
      }
      setShowThinkingIndicator(false);
    };

    const upsertStreamedBubble = (text: string) => {
      const now = new Date().toISOString();
      setHistory(current => {
        const index = current.findIndex(
          item => item.id === streamedAssistantId,
        );
        if (index === -1) {
          return current.concat({
            id: streamedAssistantId,
            session_id: chatSessionId ?? 'pending-session',
            restaurant_id: null,
            restaurant_location_id: null,
            role: 'ASSISTANT',
            message: text,
            context_payload: {},
            created_at: now,
            updated_at: now,
          });
        }
        const next = [...current];
        next[index] = { ...next[index], message: text, updated_at: now };
        return next;
      });
    };

    try {
      let response: ChatMessageResponse;
      let assistantMessageId = streamedAssistantId;
      try {
        response = await api.streamChatMessage(
          token,
          {
            message: trimmedMessage,
            session_id: chatSessionId,
          },
          {
            onToken: text => {
              streamedText += text;
              if (!streamBubbleVisible) {
                streamBubbleVisible = true;
                hideThinkingIndicator();
              }
              upsertStreamedBubble(streamedText);
            },
          },
        );
      } catch (streamError) {
        // The stream failed before completing: drop any partial bubble and
        // retry once over the non-streaming endpoint, which keeps the
        // pre-existing fallback behavior.
        if (streamBubbleVisible) {
          streamBubbleVisible = false;
          setHistory(current =>
            current.filter(item => item.id !== streamedAssistantId),
          );
        }
        setShowThinkingIndicator(true);
        response = await api.sendChatMessage(token, {
          message: trimmedMessage,
          session_id: chatSessionId,
        });
        assistantMessageId = `assistant-${new Date().toISOString()}`;
      }

      const timestamp = new Date().toISOString();
      const userMessage: ChatHistoryItem = {
        id: optimisticId,
        session_id: response.session_id,
        restaurant_id: null,
        restaurant_location_id: null,
        role: 'USER',
        message: trimmedMessage,
        context_payload: {},
        created_at: optimisticTimestamp,
        updated_at: timestamp,
      };
      const assistantMessage: ChatHistoryItem = {
        id: assistantMessageId,
        session_id: response.session_id,
        restaurant_id: null,
        restaurant_location_id: null,
        role: 'ASSISTANT',
        message: response.reply,
        context_payload: {},
        created_at: timestamp,
        updated_at: timestamp,
      };
      setHistory(current => {
        const withUser = current.map(item =>
          item.id === optimisticId ? userMessage : item,
        );
        const streamedIndex = withUser.findIndex(
          item => item.id === assistantMessageId,
        );
        if (streamedIndex === -1) {
          return withUser.concat(assistantMessage);
        }
        const next = [...withUser];
        next[streamedIndex] = assistantMessage;
        return next;
      });
      setAssistantSuggestions(current => ({
        ...current,
        [assistantMessage.id]: response.suggestions,
      }));
      setAssistantComboSuggestions(current => ({
        ...current,
        [assistantMessage.id]: response.combo_suggestions,
      }));
      setAssistantOfferSuggestions(current => ({
        ...current,
        [assistantMessage.id]: response.offer_suggestions,
      }));
      setChatSessionId(response.session_id);
    } catch (error) {
      setHistory(current =>
        current.filter(
          item => item.id !== optimisticId && item.id !== streamedAssistantId,
        ),
      );
      pushToast(
        'Chat failed',
        error instanceof Error ? error.message : 'Unable to send chat message.',
        'error',
      );
    } finally {
      if (thinkingTimerRef.current) {
        clearTimeout(thinkingTimerRef.current);
        thinkingTimerRef.current = null;
      }
      setShowThinkingIndicator(false);
      setSending(false);
    }
  };

  const confirmClearChat = () => {
    if (!token || clearing || sending) {
      return;
    }

    Alert.alert(
      'Clear chat',
      'This will remove the current chat conversation and start fresh.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Clear',
          style: 'destructive',
          onPress: () => {
            void clearChat();
          },
        },
      ],
    );
  };

  const clearChat = async () => {
    if (!token) {
      return;
    }

    setClearing(true);
    try {
      await api.clearChatHistory(token, chatSessionId ?? undefined);
      setHistory([]);
      setAssistantSuggestions({});
      setAssistantComboSuggestions({});
      setAssistantOfferSuggestions({});
      setMessage('');
      setChatSessionId(null);
      pushToast('Chat cleared', 'Your conversation has been reset.', 'success');
    } catch (error) {
      pushToast(
        'Unable to clear chat',
        error instanceof Error ? error.message : 'Please try again.',
        'error',
      );
    } finally {
      setClearing(false);
    }
  };

  // Hoisted out of the JSX so the thread is not rebuilt on every keystroke
  // in the composer.
  const renderChatMessage = React.useCallback<ListRenderItem<ChatHistoryItem>>(
    ({ item }) => (
      <ChatBubble
        message={item}
        comboSuggestions={
          item.role === 'ASSISTANT'
            ? assistantComboSuggestions[item.id] ??
              extractHistoryComboSuggestions(item)
            : []
        }
        offerSuggestions={
          item.role === 'ASSISTANT'
            ? assistantOfferSuggestions[item.id] ??
              extractHistoryOfferSuggestions(item)
            : []
        }
        onAddCombo={addGeneratedComboToCart}
        onOpenCombo={openGeneratedCombo}
        onOpenOffer={openOffer}
        onOpenSuggestion={openSuggestionDetail}
        onAddSuggestion={addSuggestionToCart}
        suggestions={
          item.role === 'ASSISTANT'
            ? assistantSuggestions[item.id] ?? extractHistorySuggestions(item)
            : []
        }
      />
    ),
    [
      addGeneratedComboToCart,
      addSuggestionToCart,
      assistantComboSuggestions,
      assistantOfferSuggestions,
      assistantSuggestions,
      openGeneratedCombo,
      openOffer,
      openSuggestionDetail,
    ],
  );

  if (!token) {
    return (
      <SafeAreaView edges={['top']} style={styles.safeArea}>
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          keyboardVerticalOffset={keyboardVerticalOffset}
          style={styles.keyboard}
        >
          <View
            style={[
              styles.loggedOutLayout,
              {
                paddingBottom: 8,
                paddingHorizontal: horizontalScreenPadding,
              },
            ]}
          >
            <View style={styles.loggedOutTopStack}>
              <ChatHero
                statLabel="Chat access"
                statValue="Login to unlock personalized suggestions"
                subtitle="I can suggest dishes by budget, spice level, meal mood, or group size."
                title="Tell me your craving."
              />
              <LoginPromptCard onPress={() => navigation.navigate('Login')} />
            </View>
            <View style={styles.loggedOutSpacer} />
            <View
              style={[
                styles.composerShell,
                styles.composerShellStatic,
                {
                  paddingBottom: composerBottomSpacing,
                },
              ]}
            >
              <View style={styles.loggedOutComposer}>
                <View style={styles.inputWrap}>
                  <TextInput
                    editable={false}
                    multiline
                    placeholder="Login to start chatting"
                    placeholderTextColor={theme.colors.hint}
                    style={styles.input}
                    value=""
                  />
                </View>
                <Pressable disabled style={styles.sendButtonDisabledStatic}>
                  <Icon color={theme.colors.white} name="send" size={18} />
                </Pressable>
              </View>
            </View>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} style={styles.safeArea}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={keyboardVerticalOffset}
        style={styles.keyboard}
      >
        <View
          style={[
            styles.header,
            { paddingHorizontal: horizontalScreenPadding },
          ]}
        >
          <View style={styles.headerTopRow}>
            <View style={styles.headerBadge}>
              <Text style={styles.headerBadgeText}>AI Concierge</Text>
            </View>
            <Pressable
              disabled={clearing || sending || loading || history.length === 0}
              onPress={confirmClearChat}
              style={[
                styles.clearChatButton,
                (clearing || sending || loading || history.length === 0) &&
                  styles.clearChatButtonDisabled,
              ]}
            >
              <Icon
                color={
                  clearing || sending || loading || history.length === 0
                    ? theme.colors.hint
                    : theme.colors.primary
                }
                name="trash-outline"
                size={14}
              />
              <Text
                style={[
                  styles.clearChatButtonText,
                  (clearing || sending || loading || history.length === 0) &&
                    styles.clearChatButtonTextDisabled,
                ]}
              >
                {clearing ? 'Clearing...' : 'Clear chat'}
              </Text>
            </Pressable>
          </View>
          <Text style={styles.title}>Tell me your craving.</Text>
          <Text style={styles.subtitle}>
            I can suggest dishes by budget, spice level, meal mood, or group
            size.
          </Text>
        </View>

        <View style={styles.threadWrap}>
          <FlatList
            ref={listRef}
            automaticallyAdjustKeyboardInsets={Platform.OS === 'ios'}
            contentContainerStyle={[
              styles.thread,
              {
                paddingBottom: threadBottomPadding,
                paddingHorizontal: horizontalScreenPadding,
              },
            ]}
            data={listData}
            keyboardDismissMode={
              Platform.OS === 'ios' ? 'interactive' : 'on-drag'
            }
            keyExtractor={item => item.id}
            keyboardShouldPersistTaps="handled"
            onContentSizeChange={() =>
              // Non-animated: this fires for every streamed token, and
              // overlapping scroll animations stutter; an instant pin to the
              // bottom keeps streaming smooth.
              listRef.current?.scrollToEnd({ animated: false })
            }
            ListHeaderComponent={
              showStarterPrompts ? (
                <View style={styles.starterCard}>
                  <View style={styles.starterHeader}>
                    <View style={styles.starterIcon}>
                      <Text style={styles.starterIconText}>AI</Text>
                    </View>
                    <View style={styles.starterCopy}>
                      <Text style={styles.starterTitle}>
                        Start with a quick prompt
                      </Text>
                      <Text style={styles.starterText}>
                        I will use live restaurant context to recommend
                        something useful.
                      </Text>
                    </View>
                  </View>
                  <ScrollView
                    contentContainerStyle={styles.promptRow}
                    horizontal
                    showsHorizontalScrollIndicator={false}
                  >
                    {promptChips.map(chip => (
                      <Pressable
                        key={chip}
                        onPress={() => send(chip)}
                        style={styles.promptChip}
                      >
                        <Text style={styles.promptText}>{chip}</Text>
                      </Pressable>
                    ))}
                  </ScrollView>
                </View>
              ) : null
            }
            ListFooterComponent={
              showThinkingIndicator ? (
                <View style={styles.typingRow}>
                  <View style={styles.typingAvatar}>
                    <Text style={styles.typingAvatarText}>AI</Text>
                  </View>
                  <View style={styles.typingBubble}>
                    <Text style={styles.typingText}>Thinking...</Text>
                  </View>
                </View>
              ) : null
            }
            renderItem={renderChatMessage}
            showsVerticalScrollIndicator={false}
            ListEmptyComponent={
              loading ? (
                <View style={styles.skeletonStack}>
                  <SkeletonBlock height={78} />
                  <SkeletonBlock height={92} />
                  <SkeletonBlock height={78} />
                </View>
              ) : (
                <View style={styles.empty}>
                  <Text style={styles.emptyTitle}>
                    Ask for recommendations, spice, or budget help.
                  </Text>
                  <Text style={styles.emptyText}>
                    The assistant will only use available menu context from the
                    backend.
                  </Text>
                </View>
              )
            }
          />
        </View>

        <View
          style={[
            styles.composerShell,
            {
              paddingHorizontal: horizontalScreenPadding,
              paddingBottom: composerBottomSpacing,
            },
          ]}
        >
          <View style={styles.composer}>
            <View style={styles.inputWrap}>
              <TextInput
                editable={Boolean(token)}
                multiline
                onChangeText={setMessage}
                placeholder={
                  token ? 'Type your question...' : 'Login to start chatting'
                }
                placeholderTextColor={theme.colors.hint}
                style={styles.input}
                value={message}
              />
            </View>
            <Pressable
              disabled={sending || !message.trim()}
              onPress={() => send(message)}
              style={[
                styles.sendButton,
                (sending || !message.trim()) && styles.sendButtonDisabled,
              ]}
            >
              <Icon
                color={theme.colors.white}
                name={showThinkingIndicator ? 'time-outline' : 'send'}
                size={18}
              />
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    keyboard: {
      flex: 1,
    },
    header: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 10,
      paddingBottom: 8,
    },
    headerTopRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
    },
    loggedOutLayout: {
      flex: 1,
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 10,
    },
    loggedOutTopStack: {
      gap: 14,
    },
    loggedOutSpacer: {
      flex: 1,
    },
    heroCard: {
      borderRadius: 28,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceRaised : theme.tone('#FFF4EC'),
      paddingHorizontal: 18,
      paddingVertical: 18,
      gap: 10,
      overflow: 'hidden',
      position: 'relative',
    },
    heroGlowPrimary: {
      position: 'absolute',
      width: 160,
      height: 160,
      borderRadius: 80,
      top: -48,
      right: -18,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.primaryTint(0.08)
          : theme.primaryTint(0.10),
    },
    heroGlowSecondary: {
      position: 'absolute',
      width: 120,
      height: 120,
      borderRadius: 60,
      bottom: -42,
      left: -18,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.primaryTint(0.06)
          : theme.tone('rgba(255,189,153,0.30)'),
    },
    heroBadge: {
      alignSelf: 'flex-start',
      minHeight: 32,
      borderRadius: 16,
      paddingHorizontal: 12,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : 'rgba(255,255,255,0.72)',
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : 'rgba(255,255,255,0.56)',
      alignItems: 'center',
      justifyContent: 'center',
    },
    heroBadgeText: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
    },
    heroTitle: {
      color: theme.colors.text,
      fontSize: 28,
      fontWeight: '900',
      lineHeight: 34,
    },
    heroSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 22,
    },
    heroStat: {
      marginTop: 4,
      paddingTop: 12,
      borderTopWidth: 1,
      borderTopColor: theme.colors.divider,
      gap: 4,
    },
    heroStatLabel: {
      color: theme.colors.hint,
      fontSize: 12,
      fontWeight: '600',
    },
    heroStatValue: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
    },
    headerBadge: {
      alignSelf: 'flex-start',
      borderRadius: 999,
      backgroundColor: theme.colors.primarySoft,
      paddingHorizontal: 12,
      paddingVertical: 7,
      marginBottom: 10,
    },
    headerBadgeText: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
    },
    clearChatButton: {
      minHeight: 34,
      borderRadius: 17,
      paddingHorizontal: 12,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
    },
    clearChatButtonDisabled: {
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.card,
    },
    clearChatButtonText: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
    },
    clearChatButtonTextDisabled: {
      color: theme.colors.hint,
    },
    title: {
      color: theme.colors.text,
      fontSize: 28,
      fontWeight: '900',
    },
    subtitle: {
      color: theme.colors.secondaryText,
      marginTop: 4,
      lineHeight: 20,
    },
    promptRow: {
      flexDirection: 'row',
      gap: 8,
    },
    promptChip: {
      borderRadius: 999,
      borderWidth: 1,
      borderColor: theme.colors.border,
      paddingHorizontal: 16,
      paddingVertical: 10,
      backgroundColor: theme.colors.surfaceRaised,
    },
    promptText: {
      color: theme.colors.primary,
      fontWeight: '700',
      fontSize: 12,
    },
    loginCard: {
      borderRadius: 20,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 18,
      gap: 10,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.05,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 14,
      elevation: 3,
    },
    loginCardIcon: {
      width: 44,
      height: 44,
      borderRadius: 22,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: 4,
    },
    loginCardTitle: {
      color: theme.colors.text,
      fontSize: 22,
      fontWeight: '900',
      lineHeight: 28,
    },
    loginCardText: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 22,
    },
    loginCardButton: {
      marginTop: 4,
      alignSelf: 'flex-start',
      minHeight: 46,
      borderRadius: 23,
      paddingHorizontal: 22,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    loginCardButtonText: {
      color: theme.colors.white,
      fontWeight: '800',
    },
    threadWrap: {
      flex: 1,
      minHeight: 0,
    },
    thread: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 4,
      paddingBottom: 24,
      gap: 8,
    },
    skeletonStack: {
      gap: 12,
    },
    empty: {
      borderRadius: 16,
      backgroundColor: theme.colors.card,
      padding: 18,
      gap: 6,
    },
    emptyTitle: {
      color: theme.colors.text,
      fontWeight: '800',
    },
    emptyText: {
      color: theme.colors.secondaryText,
    },
    starterCard: {
      borderRadius: 24,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceRaised : theme.tone('#FFF6F0'),
      padding: 16,
      gap: 14,
      marginBottom: 14,
    },
    starterHeader: {
      flexDirection: 'row',
      gap: 12,
    },
    starterIcon: {
      width: 42,
      height: 42,
      borderRadius: 21,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    starterIconText: {
      color: theme.colors.white,
      fontWeight: '800',
    },
    starterCopy: {
      flex: 1,
      gap: 4,
    },
    starterTitle: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
    },
    starterText: {
      color: theme.colors.secondaryText,
      lineHeight: 19,
      fontSize: 13,
    },
    typingRow: {
      flexDirection: 'row',
      alignItems: 'flex-end',
      gap: 10,
      marginTop: 8,
    },
    typingAvatar: {
      width: 34,
      height: 34,
      borderRadius: 17,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    typingAvatarText: {
      color: theme.colors.white,
      fontWeight: '800',
      fontSize: 12,
    },
    typingBubble: {
      maxWidth: '72%',
      borderRadius: 20,
      borderBottomLeftRadius: 6,
      backgroundColor: theme.colors.card,
      paddingHorizontal: 14,
      paddingVertical: 12,
    },
    typingText: {
      color: theme.colors.secondaryText,
      fontWeight: '700',
    },
    composerShell: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 6,
      backgroundColor: theme.colors.background,
      flexShrink: 0,
    },
    composerShellStatic: {
      marginBottom: 0,
    },
    composer: {
      borderRadius: 28,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.modalSurface : theme.tone('#FFF8F3'),
      padding: 6,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.1,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 6,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : theme.primaryTint(0.08),
    },
    loggedOutComposer: {
      borderRadius: 28,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.modalSurface : theme.tone('#FFF8F3'),
      padding: 6,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : theme.primaryTint(0.08),
    },
    inputWrap: {
      flex: 1,
      minHeight: 52,
      maxHeight: 128,
      borderRadius: 24,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      paddingHorizontal: 8,
    },
    input: {
      flex: 1,
      minHeight: 52,
      maxHeight: 120,
      textAlignVertical: 'top',
      color: theme.colors.text,
      paddingHorizontal: 8,
      paddingTop: 14,
      paddingBottom: 12,
      fontSize: 15,
      lineHeight: 20,
    },
    sendButton: {
      backgroundColor: theme.colors.primary,
      width: 52,
      height: 52,
      borderRadius: 26,
      alignItems: 'center',
      justifyContent: 'center',
      shadowColor: theme.colors.primary,
      shadowOpacity: 0.22,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 14,
      elevation: 6,
    },
    sendButtonDisabled: {
      opacity: 0.45,
    },
    sendButtonDisabledStatic: {
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : theme.tone('#FFB18A'),
      width: 52,
      height: 52,
      borderRadius: 26,
      alignItems: 'center',
      justifyContent: 'center',
    },
  });
