import type { LucideIcon } from 'lucide-react';

export interface StatTileItem<K extends string = string> {
  key: K;
  label: string;
  icon: LucideIcon;
  value: string | number;
  hint?: string;
  isStatic?: boolean;
}

interface StatTilesProps<K extends string> {
  tiles: Array<StatTileItem<K>>;
  ariaLabel: string;
  active?: K;
  onSelect?: (key: K) => void;
  loading?: boolean;
}

export function StatTiles<K extends string>({
  tiles,
  ariaLabel,
  active,
  onSelect,
  loading = false,
}: StatTilesProps<K>) {
  return (
    <section aria-label={ariaLabel} className="usr-stats">
      {tiles.map((tile) => {
        const Icon = tile.icon;
        const isActive = active === tile.key && !tile.isStatic;
        const content = (
          <>
            <span className="usr-stat__icon">
              <Icon size={15} strokeWidth={2.1} />
            </span>
            <span className="usr-stat__copy">
              <span className="usr-stat__label">{tile.label}</span>
              <strong>{loading ? '…' : tile.value}</strong>
              {tile.hint ? (
                <span className="usr-stat__hint">{loading ? 'Loading' : tile.hint}</span>
              ) : null}
            </span>
          </>
        );

        const reactKey = `${tile.key}-${tile.label}`;

        if (tile.isStatic || !onSelect) {
          return (
            <article className="usr-stat usr-stat--static" key={reactKey}>
              {content}
            </article>
          );
        }

        return (
          <button
            aria-pressed={isActive}
            className={isActive ? 'usr-stat usr-stat--active' : 'usr-stat'}
            key={reactKey}
            onClick={() => onSelect(tile.key)}
            type="button"
          >
            {content}
          </button>
        );
      })}
    </section>
  );
}
