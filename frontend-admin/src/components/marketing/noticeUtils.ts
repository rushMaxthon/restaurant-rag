/**
 * Notice logic, kept out of `CampaignNotices.tsx` so that file exports a
 * component and nothing else - which is what React Fast Refresh requires to
 * hot-swap it without remounting the tree. Same reasoning as
 * `components/statusPillUtils.ts`.
 */
import type { CampaignNotice } from '../../services/marketing/types';

/** True when anything in the list must stop the send. */
export function hasBlockingNotice(notices: CampaignNotice[]): boolean {
  return notices.some((notice) => notice.tone === 'block');
}
