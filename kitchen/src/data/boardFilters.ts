// Narrowing filters for the board. Stage is not one of them: the stage tabs
// (phone) and columns (tablet) already are the stage filter. There is no
// Dine-in — fulfillment is DELIVERY or PICKUP, and a filter for a third kind
// would always come back empty.
export type BoardFilter = 'ALL' | 'DELIVERY' | 'PICKUP' | 'PRIORITY';

export const BOARD_FILTERS: { key: BoardFilter; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'DELIVERY', label: 'Delivery' },
  { key: 'PICKUP', label: 'Pickup' },
  { key: 'PRIORITY', label: 'Priority' },
];
