import type { ReactNode } from "react";
import { TableActions, type TableAction } from "./TableActions";
import { EmptyPanel } from "./EmptyPanel";

export interface TableColumn<Row> {
  id: string;
  header: string;
  render: (row: Row) => ReactNode;
  mobileLabel?: string;
  mobileRender?: (row: Row) => ReactNode;
  hideOnMobile?: boolean;
  align?: "left" | "right";
  sortable?: boolean;
}

export interface TableSortState {
  id: string;
  direction: "asc" | "desc";
}

interface ResponsiveTableProps<Row> {
  rows: Row[];
  columns: Array<TableColumn<Row>>;
  keyExtractor: (row: Row) => string;
  actions?: Array<TableAction<Row>>;
  loading?: boolean;
  skeletonRows?: number;
  emptyTitle: string;
  emptyDescription: string;
  emptyAction?: ReactNode;
  mobileTitle: (row: Row) => ReactNode;
  mobileSubtitle?: (row: Row) => ReactNode;
  mobileStatus?: (row: Row) => ReactNode;
  onRowClick?: (row: Row) => void;
  sortState?: TableSortState | null;
  onSortChange?: (columnId: string) => void;
}

export function ResponsiveTable<Row>({
  rows,
  columns,
  keyExtractor,
  actions,
  loading = false,
  skeletonRows = 6,
  emptyTitle,
  emptyDescription,
  emptyAction,
  mobileTitle,
  mobileSubtitle,
  mobileStatus,
  onRowClick,
  sortState,
  onSortChange,
}: ResponsiveTableProps<Row>) {
  const renderHeader = (column: TableColumn<Row>) => {
    if (!column.sortable || !onSortChange) {
      return column.header;
    }
    const isActive = sortState?.id === column.id;
    return (
      <button
        aria-label={`Sort by ${column.header}`}
        className={
          isActive
            ? "admin-table__sort admin-table__sort--active"
            : "admin-table__sort"
        }
        onClick={() => onSortChange(column.id)}
        type="button"
      >
        {column.header}
        <span aria-hidden="true" className="admin-table__sort-arrow">
          {isActive ? (sortState?.direction === "asc" ? "↑" : "↓") : "↕"}
        </span>
      </button>
    );
  };

  if (loading) {
    return (
      <div className="table-container">
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.id}>{column.header}</th>
                ))}
                {actions?.length ? (
                  <th className="admin-table__actions-head">Actions</th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: skeletonRows }, (_, index) => (
                <tr key={`skeleton-${index}`}>
                  {columns.map((column) => (
                    <td key={`${column.id}-${index}`}>
                      <span className="table-skeleton table-skeleton--line" />
                    </td>
                  ))}
                  {actions?.length ? (
                    <td className="admin-table__actions-cell">
                      <span className="table-skeleton table-skeleton--button" />
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mobile-data-list">
          {Array.from({ length: skeletonRows }, (_, index) => (
            <article
              className="mobile-data-card"
              key={`mobile-skeleton-${index}`}
            >
              <div className="mobile-data-card__header">
                <div className="mobile-data-card__copy">
                  <span className="table-skeleton table-skeleton--title" />
                  <span className="table-skeleton table-skeleton--chip" />
                </div>
              </div>
              <div className="mobile-data-card__grid">
                <span className="table-skeleton table-skeleton--line" />
                <span className="table-skeleton table-skeleton--line" />
                <span className="table-skeleton table-skeleton--line" />
                <span className="table-skeleton table-skeleton--line" />
              </div>
            </article>
          ))}
        </div>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="table-container">
        <EmptyPanel action={emptyAction} description={emptyDescription} title={emptyTitle} />
      </div>
    );
  }

  return (
    <div className="table-container">
      <div className="table-scroll">
        <table className="admin-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  aria-sort={
                    sortState?.id === column.id
                      ? sortState.direction === "asc"
                        ? "ascending"
                        : "descending"
                      : undefined
                  }
                  className={
                    column.align === "right"
                      ? "admin-table__cell--right"
                      : undefined
                  }
                  key={column.id}
                >
                  {renderHeader(column)}
                </th>
              ))}
              {actions?.length ? (
                <th className="admin-table__actions-head">Actions</th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr
                className={
                  onRowClick
                    ? "admin-table__row admin-table__row--clickable"
                    : "admin-table__row"
                }
                key={keyExtractor(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((column) => (
                  <td
                    className={
                      column.align === "right"
                        ? "admin-table__cell--right"
                        : undefined
                    }
                    data-row-index={index}
                    key={column.id}
                  >
                    <div className="admin-table__cell-content">
                      {column.render(row)}
                    </div>
                  </td>
                ))}
                {actions?.length ? (
                  <td className="admin-table__actions-cell">
                    <TableActions actions={actions} row={row} />
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mobile-data-list">
        {rows.map((row) => (
          <article
            className={
              onRowClick
                ? "mobile-data-card mobile-data-card--clickable"
                : "mobile-data-card"
            }
            key={keyExtractor(row)}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
          >
            <div className="mobile-data-card__header">
              <div className="mobile-data-card__copy">
                <strong>{mobileTitle(row)}</strong>
                {mobileSubtitle ? <span>{mobileSubtitle(row)}</span> : null}
              </div>
              {mobileStatus ? (
                <div className="mobile-data-card__status">
                  {mobileStatus(row)}
                </div>
              ) : null}
            </div>
            <div className="mobile-data-card__grid">
              {columns
                .filter((column) => !column.hideOnMobile)
                .map((column) => (
                  <div className="mobile-data-card__field" key={column.id}>
                    <span>{column.mobileLabel ?? column.header}</span>
                    <strong>
                      {column.mobileRender
                        ? column.mobileRender(row)
                        : column.render(row)}
                    </strong>
                  </div>
                ))}
            </div>
            {actions?.length ? (
              <div className="mobile-data-card__actions">
                <TableActions actions={actions} compact row={row} />
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}
