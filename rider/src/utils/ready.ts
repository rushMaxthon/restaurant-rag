/**
 * When the food will be ready (backend `ready_at`: the branch's preparation
 * time after the kitchen accepted). A rider who knows it rides over to arrive
 * as the bag is packed rather than to wait at the counter. Null when the
 * restaurant has no preparation time set - an unknown time is never guessed.
 */

import { translate } from '@/i18n/translate';
import { clockTime } from '@utils/format';

export function readyLabel(
  readyAt: string | null | undefined,
  now: Date = new Date(),
): string | null {
  if (!readyAt) return null;
  const at = Date.parse(readyAt);
  if (!Number.isFinite(at)) return null;
  const minutes = Math.ceil((at - now.getTime()) / 60_000);
  if (minutes <= 0) return translate('common.readyNow');
  return translate('common.readyAt', { time: clockTime(readyAt), n: minutes });
}
