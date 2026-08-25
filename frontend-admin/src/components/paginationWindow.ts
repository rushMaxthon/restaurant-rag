/**
 * Page-window maths, kept out of `Pagination.tsx` so that file exports a
 * component and nothing else - which is what React Fast Refresh needs to
 * hot-swap it without remounting.
 */
/** Marks an elided run of pages. Not a valid page number, so it cannot collide. */
export const GAP = -1;

/**
 * The page numbers to render, with gaps for the runs that are elided.
 *
 * Without this the control rendered one button per page — forty pages of orders
 * produced forty buttons that wrapped across several rows and pushed the table
 * down the screen. The window keeps it a fixed height at any dataset size.
 *
 * Always shows the first and last page, the current page with one neighbour
 * either side, and widens near the ends so the strip does not change width as
 * you page through: a seven-slot window, which is the most that fits on a narrow
 * viewport without wrapping.
 */
export function buildPageWindow(page: number, totalPages: number): number[] {
  const SLOTS = 7;
  if (totalPages <= SLOTS) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const pages = new Set<number>([1, totalPages, page]);
  pages.add(Math.max(1, page - 1));
  pages.add(Math.min(totalPages, page + 1));

  // Near either end there is no gap to show on that side, so spend the freed
  // slots extending the run instead of leaving the strip narrower.
  if (page <= 4) {
    for (let entry = 2; entry <= 5; entry += 1) {
      pages.add(entry);
    }
  }
  if (page >= totalPages - 3) {
    for (let entry = totalPages - 4; entry < totalPages; entry += 1) {
      pages.add(entry);
    }
  }

  const ordered = [...pages].filter((entry) => entry >= 1 && entry <= totalPages).sort((a, b) => a - b);

  const withGaps: number[] = [];
  ordered.forEach((entry, index) => {
    const previous = ordered[index - 1];
    if (previous !== undefined && entry - previous > 1) {
      withGaps.push(GAP);
    }
    withGaps.push(entry);
  });
  return withGaps;
}
