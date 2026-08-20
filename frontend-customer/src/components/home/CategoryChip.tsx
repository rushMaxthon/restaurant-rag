interface CategoryChipProps {
  label: string;
  active?: boolean;
  onClick: () => void;
}

export function CategoryChip({ label, active = false, onClick }: CategoryChipProps) {
  return (
    <button
      className={active ? 'home-category-chip home-category-chip--active' : 'home-category-chip'}
      onClick={onClick}
      type="button"
    >
      <span className="home-category-chip__icon" aria-hidden="true">
        {label.slice(0, 1)}
      </span>
      <span>{label}</span>
    </button>
  );
}
