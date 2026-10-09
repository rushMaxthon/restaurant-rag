import account from './account';
import common from './common';
import confirm from './confirm';
import home from './home';
import money from './money';
import onboarding from './onboarding';
import reset from './reset';
import system from './system';
import trip from './trip';

/**
 * Every area's sentences, one file each so screens can be translated side by
 * side without two people editing one dictionary:
 * - common: days, months, small shared words
 * - home: Home and the Orders tab (shift strip, waiting orders)
 * - trip: the new-order alert, a delivery in progress, Delivered
 * - money: Earnings, History, a trip's detail
 * - account: Profile, sign-in, permissions, intro, the guide, tab bar
 * - system: notifications, the shift service, errors from the network
 * - onboarding: sign-up, the application steps and its status screen
 * - reset: forgot password
 */
const areas = [common, confirm, home, trip, money, account, system, onboarding, reset] as const;

type Area = (typeof areas)[number];
type Merge<U> = (U extends unknown ? (x: U) => void : never) extends (
  x: infer I,
) => void
  ? I
  : never;

export type English = Merge<Area['en']>;
export type Key = keyof English;

function merge(lang: 'en' | 'hi' | 'gu'): Record<Key, string> {
  return Object.assign({}, ...areas.map(a => a[lang])) as Record<Key, string>;
}

export const en = merge('en');
export const hi = merge('hi');
export const gu = merge('gu');
