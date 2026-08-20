import {toNumber} from '../services/api';
import type {MenuItem, RecommendationItem} from '../types/app';

export function sortMenuItemsByRecommendationSignal(
  items: MenuItem[],
  recommendations: RecommendationItem[],
): MenuItem[] {
  if (items.length <= 1) {
    return items;
  }

  const recommendationScores = new Map(
    recommendations.map((item) => [item.id, item.score]),
  );

  return [...items].sort((left, right) => {
    const scoreDelta =
      (recommendationScores.get(right.id) ?? -1) -
      (recommendationScores.get(left.id) ?? -1);
    if (scoreDelta !== 0) {
      return scoreDelta;
    }

    if (left.is_bestseller !== right.is_bestseller) {
      return left.is_bestseller ? -1 : 1;
    }

    const popularityDelta =
      toNumber(right.popularity_score) - toNumber(left.popularity_score);
    if (popularityDelta !== 0) {
      return popularityDelta;
    }

    const categoryCompare = left.category.localeCompare(right.category);
    if (categoryCompare !== 0) {
      return categoryCompare;
    }

    return left.name.localeCompare(right.name);
  });
}
