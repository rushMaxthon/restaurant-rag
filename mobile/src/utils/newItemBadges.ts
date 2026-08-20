type NewItemBadgePayload = {
  is_new?: boolean;
  is_bestseller?: boolean;
  popularity_score?: number | string | null;
  score?: number | string | null;
  recommendation_label?: string | null;
  recommendation_reason?: string | null;
  new_item_reason?: string | null;
};

export function getNewItemBadgeMeta(item: NewItemBadgePayload): {
  label: string | null;
} {
  const label = item.recommendation_label?.trim() ?? null;
  return {label: label || null};
}
