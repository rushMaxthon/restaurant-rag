import { Search, X } from 'lucide-react';
import type { ReactNode } from 'react';

interface DataToolbarProps {
  searchValue: string;
  searchPlaceholder: string;
  onSearchChange: (value: string) => void;
  filters?: ReactNode;
  actions?: ReactNode;
  /** Names what is being searched, for screen readers. */
  searchLabel?: string;
}

export function DataToolbar({
  searchValue,
  searchPlaceholder,
  onSearchChange,
  filters,
  actions,
  searchLabel = 'Search',
}: DataToolbarProps) {
  return (
    <div className="data-toolbar">
      <div className="data-toolbar__group data-toolbar__group--grow">
        {/* The field was a bare text input with a placeholder — no icon, no way
            to clear it, and nothing telling a screen reader it was a search. */}
        <div className="page-search-field">
          <Search className="page-search-field__icon" size={15} strokeWidth={2.2} />
          <input
            aria-label={searchLabel}
            className="page-search"
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={searchPlaceholder}
            type="search"
            value={searchValue}
          />
          {searchValue ? (
            <button
              aria-label="Clear search"
              className="page-search-field__clear"
              onClick={() => onSearchChange('')}
              type="button"
            >
              <X size={14} strokeWidth={2.4} />
            </button>
          ) : null}
        </div>
        {filters}
      </div>
      {actions ? <div className="data-toolbar__actions">{actions}</div> : null}
    </div>
  );
}
