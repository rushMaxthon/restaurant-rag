import type { HomeCategory } from './menuCategories';

export function CategoryRail({
  categories,
  selectedId,
  onSelect,
}: {
  categories: HomeCategory[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="rail category-rail">
      {categories.map((category) => {
        const active = category.id === selectedId;
        return (
          <button
            key={category.id}
            aria-pressed={active}
            className={active ? 'category-tile category-tile--active' : 'category-tile'}
            onClick={() => onSelect(category.id)}
            type="button"
          >
            {/* Decorative: the label beside it already names the section, and a
                screen reader announcing "pot of food, Curry" is worse than
                "Curry". */}
            <span aria-hidden="true" className="category-tile__icon">
              {category.emoji}
            </span>
            <span className="category-tile__label">{category.label}</span>
          </button>
        );
      })}
    </div>
  );
}
