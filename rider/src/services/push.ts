import notifee, {
  AndroidCategory,
  AndroidImportance,
  AndroidVisibility,
  AuthorizationStatus,
  EventType,
  type Event,
} from '@notifee/react-native';
import { getApps } from '@react-native-firebase/app';
import {
  getMessaging,
  getToken,
  onMessage,
  onTokenRefresh,
  setBackgroundMessageHandler,
} from '@react-native-firebase/messaging';
import { Platform } from 'react-native';

import { initLanguage } from '@/i18n';
import { translate } from '@/i18n/translate';
import { rupees } from '@utils/format';
import { offerAlertMs, parsePush, type RiderPush } from '@utils/push';

/**
 * Notifications that reach a rider whose app is not on screen.
 *
 * Two routes in, one way out:
 * - FCM (`notify.py` sends data-only, high priority) wakes the app even when
 *   it was killed. Needs `google-services.json`; without it `firebaseReady()`
 *   is false and nothing here touches Firebase.
 * - While on shift the foreground service keeps the app alive, so the
 *   socket/poll still sees a new offer; RiderProvider calls `showOfferAlert`
 *   itself. That works with no Firebase at all.
 * Either way the app draws the alert (Notifee), and a tap is parked here
 * until the navigator is mounted to act on it (`takePendingPush`).
 */

const OFFER_CHANNEL = 'rider-offers'; // must match OFFER_CHANNEL in notify.py
const UPDATES_CHANNEL = 'rider-updates';

let pending: RiderPush | null = null;
const listeners = new Set<(push: RiderPush) => void>();

function deliver(push: RiderPush | null): void {
  if (!push) return;
  if (listeners.size === 0) {
    pending = push; // the app is still starting: PushRouter takes it on mount
    return;
  }
  listeners.forEach(fn => fn(push));
}

/** The tap that opened (or woke) the app, if the navigator has not handled it yet. */
export function takePendingPush(): RiderPush | null {
  const push = pending;
  pending = null;
  return push;
}

export function onPushTap(fn: (push: RiderPush) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function firebaseReady(): boolean {
  try {
    return getApps().length > 0;
  } catch {
    return false;
  }
}

async function channels(): Promise<void> {
  await notifee.createChannel({
    id: OFFER_CHANNEL,
    // Shown in the phone's settings. A channel keeps the name it was first
    // created with (in the language in force then); the id never changes.
    name: translate('system.channelOffers'),
    description: translate('system.channelOffersDesc'),
    importance: AndroidImportance.HIGH,
    visibility: AndroidVisibility.PUBLIC,
    sound: 'default',
    vibration: true,
    vibrationPattern: [300, 500, 300, 500],
  });
  await notifee.createChannel({
    id: UPDATES_CHANNEL,
    name: translate('system.channelUpdates'),
    description: translate('system.channelUpdatesDesc'),
    importance: AndroidImportance.HIGH,
  });
}

/** A loud, full-screen alert that disappears the moment the offer expires. */
export async function showOfferAlert(
  offerId: string,
  expiresAt: string,
): Promise<void> {
  if (Platform.OS !== 'android') return;
  const ms = offerAlertMs(expiresAt);
  if (ms === null) return;
  try {
    await channels();
    await notifee.displayNotification({
      id: `offer-${offerId}`,
      title: translate('system.offerTitle'),
      body: translate('system.offerBody'),
      data: { type: 'rider_offer', offer_id: offerId, expires_at: expiresAt },
      android: {
        channelId: OFFER_CHANNEL,
        category: AndroidCategory.CALL,
        importance: AndroidImportance.HIGH,
        visibility: AndroidVisibility.PUBLIC,
        smallIcon: 'ic_notification',
        color: '#FF5200',
        timeoutAfter: ms,
        autoCancel: true,
        pressAction: { id: 'default', launchActivity: 'default' },
        // Over the lock screen, like a call: an offer lasts seconds.
        fullScreenAction: { id: 'default', launchActivity: 'default' },
      },
    });
  } catch {
    // No notification permission: the offer still shows when they open the app.
  }
}

/**
 * What a new order sounds like, on demand: the same channel, sound and
 * vibration as a real offer, so a rider hears it once before it matters.
 * Gone again after a few seconds; a tap opens the app and nothing more.
 */
export async function testOfferAlert(): Promise<boolean> {
  if (Platform.OS !== 'android') return false;
  try {
    await channels();
    // displayNotification resolves even when nothing can be heard: denied
    // notifications, or the order channel silenced in the phone's settings.
    const settings = await notifee.getNotificationSettings();
    if (settings.authorizationStatus !== AuthorizationStatus.AUTHORIZED)
      return false;
    const channel = await notifee.getChannel(OFFER_CHANNEL);
    if (channel?.blocked) return false;
    await notifee.displayNotification({
      id: 'offer-test',
      title: translate('system.testTitle'),
      body: translate('system.testBody'),
      data: { type: 'rider_test' },
      android: {
        channelId: OFFER_CHANNEL,
        importance: AndroidImportance.HIGH,
        visibility: AndroidVisibility.PUBLIC,
        smallIcon: 'ic_notification',
        color: '#FF5200',
        timeoutAfter: 6_000,
        autoCancel: true,
        pressAction: { id: 'default', launchActivity: 'default' },
      },
    });
    return true;
  } catch {
    return false;
  }
}

export async function clearOfferAlert(offerId: string): Promise<void> {
  try {
    await notifee.cancelNotification(`offer-${offerId}`);
  } catch {
    // nothing to clear
  }
}

async function showTripCancelled(tripId: string): Promise<void> {
  try {
    await channels();
    await notifee.displayNotification({
      id: `trip-${tripId}`,
      title: translate('system.cancelledTitle'),
      body: translate('system.cancelledBody'),
      data: { type: 'rider_trip_cancelled', trip_id: tripId },
      android: {
        channelId: UPDATES_CHANNEL,
        smallIcon: 'ic_notification',
        color: '#FF5200',
        pressAction: { id: 'default', launchActivity: 'default' },
      },
    });
  } catch {
    // ignored, as above
  }
}

/** Taken off shift because the phone stopped answering - most likely the app was killed. */
async function showShiftEnded(): Promise<void> {
  try {
    await channels();
    await notifee.displayNotification({
      id: 'rider-shift-ended',
      title: translate('system.shiftEndedTitle'),
      body: translate('system.shiftEndedBody'),
      data: { type: 'rider_shift_ended' },
      android: {
        channelId: UPDATES_CHANNEL,
        smallIcon: 'ic_notification',
        color: '#FF5200',
        pressAction: { id: 'default', launchActivity: 'default' },
      },
    });
  } catch {
    // ignored, as above: Home shows them offline when they open the app
  }
}

/** An admin decided on the rider's application: worth a notification, since they are rarely looking. */
async function showApplicationUpdate(status: string): Promise<void> {
  const body =
    status === 'APPROVED'
      ? translate('onboarding.push.approved')
      : status === 'REJECTED'
      ? translate('onboarding.push.rejected')
      : translate('onboarding.push.changes');
  try {
    await channels();
    await notifee.displayNotification({
      id: 'rider-application',
      title: translate('onboarding.push.title'),
      body,
      data: { type: 'rider_application', status },
      android: {
        channelId: UPDATES_CHANNEL,
        smallIcon: 'ic_notification',
        color: '#FF5200',
        pressAction: { id: 'default', launchActivity: 'default' },
      },
    });
  } catch {
    // ignored, as above: the status screen shows it when they open the app
  }
}

/** Refer & earn: a friend joined, was approved, or a step was earned (`queue_referral_push`). */
async function showReferral(
  push: Extract<RiderPush, { kind: 'referral' }>,
): Promise<void> {
  const vars = {
    name: push.name,
    amount: push.amount ? rupees(push.amount) : '',
    deliveries: push.deliveries,
    days: push.days,
  };
  const key = {
    joined: ['referral.push.joinedTitle', 'referral.push.joinedBody'],
    approved: ['referral.push.approvedTitle', 'referral.push.approvedBody'],
    earned: ['referral.push.earnedTitle', 'referral.push.earnedBody'],
  }[push.event] as [
    Parameters<typeof translate>[0],
    Parameters<typeof translate>[0],
  ];
  try {
    await channels();
    await notifee.displayNotification({
      // One per event and friend: a second earned step replaces nothing.
      id: `rider-referral-${push.event}-${push.name}-${push.amount}`,
      title: translate(key[0], vars),
      body: translate(key[1], vars),
      data: { type: 'rider_referral', event: push.event, name: push.name },
      android: {
        channelId: UPDATES_CHANNEL,
        smallIcon: 'ic_notification',
        color: '#FF5200',
        pressAction: { id: 'default', launchActivity: 'default' },
      },
    });
  } catch {
    // ignored, as above: Refer & earn shows it when they open the app
  }
}

/** The part of an FCM message we read (v26 does not export its RemoteMessage type). */
type PushMessage = { data?: { [key: string]: unknown } };

async function showPush(message: PushMessage): Promise<void> {
  const push = parsePush(message.data);
  if (!push) return;
  // A killed app is started headless for this: no LanguageProvider has run,
  // so read the rider's choice first or the alert speaks the phone's language.
  await initLanguage();
  if (push.kind === 'offer') await showOfferAlert(push.offerId, push.expiresAt);
  if (push.kind === 'trip_cancelled') await showTripCancelled(push.tripId);
  if (push.kind === 'shift_ended') await showShiftEnded();
  if (push.kind === 'application') await showApplicationUpdate(push.status);
  if (push.kind === 'referral') await showReferral(push);
}

function handleEvent({ type, detail }: Event): void {
  if (type === EventType.PRESS || type === EventType.ACTION_PRESS) {
    deliver(parsePush(detail.notification?.data));
  }
}

/**
 * index.js, before the app renders: a killed app is started headless for a
 * push, and these handlers must already exist when it is.
 */
export function registerBackgroundPush(): void {
  if (Platform.OS !== 'android') return;
  notifee.onBackgroundEvent(async event => handleEvent(event));
  if (firebaseReady()) {
    setBackgroundMessageHandler(getMessaging(), showPush);
  }
}

/** While the app is mounted: taps, the cold-start tap, and FCM while open. */
export function listenForPush(
  onForegroundMessage: (push: RiderPush | null) => void,
): () => void {
  const offEvents = notifee.onForegroundEvent(handleEvent);
  notifee
    .getInitialNotification()
    .then(initial => deliver(parsePush(initial?.notification?.data)))
    .catch(() => undefined);
  // On screen the socket/poll already shows it; a push just means "look now".
  const offMessages = firebaseReady()
    ? onMessage(getMessaging(), message =>
        onForegroundMessage(parsePush((message as PushMessage).data)),
      )
    : () => undefined;
  return () => {
    offEvents();
    offMessages();
  };
}

/** Tell the server where to push. Re-sent when Firebase rotates the token. */
export function registerDeviceToken(
  save: (token: string) => Promise<unknown>,
): () => void {
  if (!firebaseReady()) return () => undefined;
  const messaging = getMessaging();
  getToken(messaging)
    .then(token => save(token))
    .catch(() => undefined);
  return onTokenRefresh(messaging, token => {
    save(token).catch(() => undefined);
  });
}
