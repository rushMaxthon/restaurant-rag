/**
 * Merge-field resolution for campaign copy.
 *
 * Kept as a pure module rather than inside the preview component because the
 * failure it guards against is invisible in the happy path: a customer with no
 * first name on file. Rendering `Hi {first_name}` or, worse, `Hi null` to a
 * real person is the single most embarrassing thing a campaign can do, so every
 * field has a fallback and the preview cycles through recipients who exercise
 * them.
 */

export interface MergeContext {
  first_name: string | null;
  branch: string | null;
}

/** Sample recipients the preview steps through, worst case included. */
export interface PreviewRecipient extends MergeContext {
  id: string;
  /** Why this recipient is worth previewing, shown under the device. */
  note: string;
}

const FALLBACKS: Record<keyof MergeContext, string> = {
  // "there" rather than "customer": it reads as a greeting instead of a
  // database row, and it works in both "Hi {first_name}" and "We miss you,
  // {first_name}".
  first_name: 'there',
  branch: 'our kitchen',
};

export const MERGE_FIELDS: Array<{ token: string; label: string; hint: string }> = [
  { token: '{first_name}', label: 'First name', hint: `Falls back to "${FALLBACKS.first_name}"` },
  { token: '{branch}', label: 'Branch name', hint: `Falls back to "${FALLBACKS.branch}"` },
];

export function resolveMergeFields(text: string, context: MergeContext): string {
  return text
    .replaceAll('{first_name}', context.first_name?.trim() || FALLBACKS.first_name)
    .replaceAll('{branch}', context.branch?.trim() || FALLBACKS.branch);
}

/**
 * Builds the preview cast for a given branch selection.
 *
 * Always ends with someone missing a name, because that is the case an owner
 * will never think to check and the one that goes wrong.
 */
export function buildPreviewRecipients(branchName: string | null): PreviewRecipient[] {
  return [
    {
      id: 'preview-1',
      first_name: 'Priya',
      branch: branchName,
      note: 'A typical recipient',
    },
    {
      id: 'preview-2',
      first_name: 'Arjun',
      branch: branchName,
      note: 'A second recipient, to check the copy reads naturally',
    },
    {
      id: 'preview-3',
      first_name: null,
      branch: branchName,
      note: 'No first name on file — this is what the fallback looks like',
    },
  ];
}

/** Every `{token}` in the text that is not one we know how to fill. */
export function findUnknownTokens(text: string): string[] {
  const known = new Set(MERGE_FIELDS.map((field) => field.token));
  const found = text.match(/\{[a-z_]+\}/gi) ?? [];
  return [...new Set(found.filter((token) => !known.has(token)))];
}
