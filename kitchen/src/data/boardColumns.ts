import type { LiveStatus } from '@/types/app';

export interface BoardColumn {
  status: LiveStatus;
  title: string;
  // Empty-state wording. Written as reassurance, not as a definition: an
  // empty column mid-service should read "you are on top of it", never as a
  // screen that failed to load.
  emptyTitle: string;
  emptyBody: string;
}

// The stages a kitchen works in, in the order the work happens.
export const BOARD_COLUMNS: BoardColumn[] = [
  {
    status: 'PLACED',
    title: 'New',
    emptyTitle: 'No new orders',
    emptyBody: 'You’re all caught up.',
  },
  {
    status: 'ACCEPTED',
    title: 'Accepted',
    emptyTitle: 'Nothing waiting',
    emptyBody: 'Nothing waiting to start.',
  },
  {
    status: 'PREPARING',
    title: 'Cooking',
    emptyTitle: 'Nothing on the pass',
    emptyBody: 'The pass is clear.',
  },
  {
    status: 'OUT_FOR_DELIVERY',
    title: 'Ready',
    emptyTitle: 'All handed over',
    emptyBody: 'Nothing waiting to go out.',
  },
];
