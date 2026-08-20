import type { ReactNode } from 'react';

interface DataToolbarProps {
  searchValue: string;
  searchPlaceholder: string;
  onSearchChange: (value: string) => void;
  filters?: ReactNode;
  actions?: ReactNode;
}

export function DataToolbar({
  searchValue,
  searchPlaceholder,
  onSearchChange,
  filters,
  actions,
}: DataToolbarProps) {
  return (
    <div className="data-toolbar">
      <div className="data-toolbar__group data-toolbar__group--grow">
        <input
          className="page-search"
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={searchPlaceholder}
          value={searchValue}
        />
        {filters}
      </div>
      {actions ? <div className="data-toolbar__actions">{actions}</div> : null}
    </div>
  );
}
