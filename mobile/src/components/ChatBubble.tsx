import React from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from 'react-native';
import { GeneratedComboCard } from '@components/home/GeneratedComboCard';
import { OfferBannerCard } from '@components/home/OfferBannerCard';
import { formatCurrency, placeholderImage } from '@services/api';
import { dedupeById, splitBoldSegments } from '@utils/chatText';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type {
  ChatHistoryItem,
  ChatSuggestionItem,
  GeneratedCombo,
  PersonalizedOfferCard,
} from '@/types/app';

interface ChatBubbleProps {
  message: ChatHistoryItem;
  suggestions?: ChatSuggestionItem[];
  comboSuggestions?: GeneratedCombo[];
  offerSuggestions?: PersonalizedOfferCard[];
  onAddSuggestion: (item: ChatSuggestionItem) => void;
  onOpenSuggestion: (item: ChatSuggestionItem) => void;
  onAddCombo: (combo: GeneratedCombo) => void;
  onOpenCombo: (combo: GeneratedCombo) => void;
  onOpenOffer: (offer: PersonalizedOfferCard) => void;
}

function ChatBubbleComponent({
  message,
  suggestions = [],
  comboSuggestions = [],
  offerSuggestions = [],
  onAddSuggestion,
  onOpenSuggestion,
  onAddCombo,
  onOpenCombo,
  onOpenOffer,
}: ChatBubbleProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const isUser = message.role === 'USER';
  const { width } = useWindowDimensions();
  const comboCardWidth = Math.max(208, Math.min(Math.round(width * 0.62), 232));
  const uniqueSuggestions = dedupeById(suggestions);
  const uniqueComboSuggestions = dedupeById(comboSuggestions);
  const uniqueOfferSuggestions = dedupeById(offerSuggestions);
  const messageSegments = splitBoldSegments(message.message);

  return (
    <View style={[styles.row, isUser ? styles.rowUser : styles.rowAssistant]}>
      {!isUser ? (
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>AI</Text>
        </View>
      ) : null}
      <View
        style={[
          styles.bubble,
          isUser ? styles.userBubble : styles.assistantBubble,
        ]}
      >
        <Text
          style={[
            styles.message,
            isUser ? styles.userText : styles.assistantText,
          ]}
        >
          {messageSegments.map((segment, index) =>
            segment.bold ? (
              <Text key={index} style={styles.messageBold}>
                {segment.text}
              </Text>
            ) : (
              segment.text
            ),
          )}
        </Text>
        {!isUser && uniqueSuggestions.length > 0 ? (
          <View style={styles.suggestions}>
            {uniqueSuggestions.map(item => (
              <Pressable
                key={item.id}
                onPress={() => onOpenSuggestion(item)}
                style={styles.foodCard}
              >
                <Image
                  source={{
                    uri: item.image_url ?? placeholderImage(item.name),
                  }}
                  style={styles.foodImage}
                />
                <View style={styles.foodCopy}>
                  <Text style={styles.foodName}>{item.name}</Text>
                  <Text style={styles.foodMeta}>{item.restaurant_name}</Text>
                  <Text style={styles.foodMeta}>
                    {formatCurrency(item.price)}
                  </Text>
                </View>
                <TouchableOpacity
                  onPress={() => onAddSuggestion(item)}
                  style={styles.addButton}
                >
                  <Text style={styles.addText}>+ ADD</Text>
                </TouchableOpacity>
              </Pressable>
            ))}
          </View>
        ) : null}
        {!isUser && uniqueComboSuggestions.length > 0 ? (
          <ScrollView
            contentContainerStyle={styles.comboSuggestions}
            horizontal
            nestedScrollEnabled
            showsHorizontalScrollIndicator={false}
          >
            {uniqueComboSuggestions.map(combo => (
              <GeneratedComboCard
                cardWidth={comboCardWidth}
                combo={combo}
                key={combo.id}
                onAddCombo={onAddCombo}
                onPress={onOpenCombo}
                showHeartButton={false}
              />
            ))}
          </ScrollView>
        ) : null}
        {!isUser && uniqueOfferSuggestions.length > 0 ? (
          <ScrollView
            contentContainerStyle={styles.offerSuggestions}
            horizontal
            nestedScrollEnabled
            showsHorizontalScrollIndicator={false}
          >
            {uniqueOfferSuggestions.map(offer => (
              <OfferBannerCard
                key={offer.id}
                offer={offer}
                onPress={onOpenOffer}
              />
            ))}
          </ScrollView>
        ) : null}
      </View>
    </View>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    row: {
      flexDirection: 'row',
      gap: 10,
      marginBottom: 14,
      alignItems: 'flex-end',
    },
    rowUser: {
      justifyContent: 'flex-end',
    },
    rowAssistant: {
      justifyContent: 'flex-start',
    },
    avatar: {
      width: 36,
      height: 36,
      borderRadius: 18,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    avatarText: {
      color: theme.colors.white,
      fontWeight: '800',
    },
    bubble: {
      maxWidth: '84%',
      paddingHorizontal: 14,
      paddingVertical: 12,
    },
    userBubble: {
      backgroundColor: theme.colors.primary,
      borderTopLeftRadius: 18,
      borderTopRightRadius: 18,
      borderBottomLeftRadius: 18,
      borderBottomRightRadius: 4,
    },
    assistantBubble: {
      backgroundColor: theme.colors.card,
      borderTopLeftRadius: 18,
      borderTopRightRadius: 18,
      borderBottomLeftRadius: 4,
      borderBottomRightRadius: 18,
    },
    message: {
      fontSize: 15,
      lineHeight: 22,
    },
    messageBold: {
      fontWeight: '700',
    },
    userText: {
      color: theme.colors.white,
    },
    assistantText: {
      color: theme.colors.text,
    },
    suggestions: {
      marginTop: 12,
      gap: 10,
    },
    comboSuggestions: {
      marginTop: 12,
      paddingRight: 8,
    },
    offerSuggestions: {
      marginTop: 12,
      paddingRight: 8,
    },
    foodCard: {
      backgroundColor: theme.colors.background,
      borderRadius: 14,
      padding: 10,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
    },
    foodImage: {
      width: 58,
      height: 58,
      borderRadius: 10,
    },
    foodCopy: {
      flex: 1,
      gap: 2,
    },
    foodName: {
      color: theme.colors.text,
      fontWeight: '700',
    },
    foodMeta: {
      color: theme.colors.secondaryText,
      fontSize: 12,
    },
    addButton: {
      backgroundColor: theme.colors.primary,
      borderRadius: 8,
      paddingHorizontal: 12,
      paddingVertical: 8,
    },
    addText: {
      color: theme.colors.white,
      fontWeight: '800',
    },
  });

const styles = createStyles(theme);

/**
 * Memoized: these cards sit in lists whose parent re-renders on unrelated
 * state changes, and none of them depend on anything but their props.
 */
export const ChatBubble = React.memo(ChatBubbleComponent);
