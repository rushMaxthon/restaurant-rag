// One load of finished orders. Infinite scroll asks for the next page as the
// list nears its end.
export const HISTORY_PAGE_SIZE = 20;

// Local midnight on the device as an ISO instant. "Today" is the kitchen's
// day, not UTC's: a board in Bangalore asking from UTC midnight would show
// yesterday evening's service until 05:30.
export const startOfToday = (now: Date = new Date()): string =>
  new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();

export const localDayKey = (now: Date = new Date()): string =>
  `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;

// What the search box sends, or null for "no search". The server matches the
// id case-insensitively; only a leading '#' has to go.
export const searchTerm = (raw: string): string | null => {
  const term = raw.trim().replace(/^#/, '').trim();
  return term === '' ? null : term;
};

// The payment line on a FINISHED order. Not the live ticket's wording:
// "Collect cash" on an order that already went out reads as money still owed.
export const settledPaymentLabel = (status: string): string => {
  switch (status.toUpperCase()) {
    case 'COD':
      return 'Cash on delivery';
    case 'PAID':
      return 'Paid online';
    case 'REFUNDED':
      return 'Refunded';
    default:
      return 'Unpaid';
  }
};

const sameLocalDay = (a: Date, b: Date): boolean =>
  a.getFullYear() === b.getFullYear() &&
  a.getMonth() === b.getMonth() &&
  a.getDate() === b.getDate();

// When something happened, as short as it can honestly be: a time for today,
// a date as well for anything older (a search spans all history, and "14:32"
// on last Tuesday's order would read as this afternoon). A missing instant
// says so — orders older than event tracking have no completion time.
export const completedLabel = (iso: string | null | undefined, now: Date = new Date()): string => {
  if (!iso) {
    return 'Time not recorded';
  }
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) {
    return 'Time not recorded';
  }
  const time = at.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  if (sameLocalDay(at, now)) {
    return time;
  }
  const date = at.toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });
  return `${date}, ${time}`;
};
