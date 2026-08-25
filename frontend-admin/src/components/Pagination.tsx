import { buildPageWindow, GAP } from './paginationWindow';
interface PaginationProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  pageSize?: number;
  pageSizeOptions?: number[];
  onPageSizeChange?: (pageSize: number) => void;
  totalItems?: number;
}

export function Pagination({
  page,
  totalPages,
  onPageChange,
  pageSize,
  pageSizeOptions = [10, 25, 50],
  onPageSizeChange,
  totalItems,
}: PaginationProps) {
  if (totalPages <= 1) {
    if (!onPageSizeChange || pageSize === undefined) {
      return null;
    }
  }

  const pages = buildPageWindow(page, totalPages);
  const startItem =
    totalItems !== undefined && pageSize !== undefined
      ? Math.min((page - 1) * pageSize + 1, totalItems)
      : null;
  const endItem =
    totalItems !== undefined && pageSize !== undefined
      ? Math.min(page * pageSize, totalItems)
      : null;

  return (
    <div className="pagination">
      <div className="pagination__summary">
        {startItem !== null && endItem !== null ? (
          <span className="toolbar-meta">
            Showing {startItem}–{endItem} of {totalItems}
          </span>
        ) : null}
      </div>
      {totalPages > 1 ? (
        <div className="pagination__pages">
          {pages.map((entry, index) =>
            entry === GAP ? (
              <span
                aria-hidden="true"
                className="pagination__gap"
                // Index, because a window can legitimately contain two gaps and
                // the value itself is not unique.
                key={`gap-${index}`}
              >
                &hellip;
              </span>
            ) : (
              <button
                aria-current={entry === page ? 'page' : undefined}
                aria-label={`Page ${entry}`}
                className={entry === page ? 'pagination__page pagination__page--active' : 'pagination__page'}
                key={entry}
                onClick={() => onPageChange(entry)}
                type="button"
              >
                {entry}
              </button>
            ),
          )}
        </div>
      ) : (
        <div aria-hidden="true" className="pagination__pages pagination__pages--hidden" />
      )}
      <div className="pagination__controls">
        {onPageSizeChange && pageSize !== undefined ? (
          <label className="pagination__page-size">
            <span>Rows</span>
            <select
              className="page-search page-search--select"
              onChange={(event) => onPageSizeChange(Number(event.target.value))}
              value={pageSize}
            >
              {pageSizeOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {totalPages > 1 ? (
          <>
          <button
            className="secondary-button"
            disabled={page === 1}
            onClick={() => onPageChange(page - 1)}
            type="button"
          >
            Previous
          </button>
          <button
            className="secondary-button"
            disabled={page === totalPages}
            onClick={() => onPageChange(page + 1)}
            type="button"
          >
            Next
          </button>
          </>
        ) : null}
      </div>
    </div>
  );
}
