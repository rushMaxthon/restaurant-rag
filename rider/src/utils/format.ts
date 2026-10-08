/** Money, distance and time, written the way a rider in India reads them. */

export function rupees(value: string | number | null | undefined, { decimals = false } = {}): string {
  const amount = Number(value ?? 0);
  if (!Number.isFinite(amount)) return '₹0';
  const fixed = decimals || !Number.isInteger(amount) ? amount.toFixed(2) : amount.toFixed(0);
  const [whole = '0', fraction] = fixed.split('.');
  // Indian grouping: 1,23,456
  const last3 = whole.slice(-3);
  const rest = whole.slice(0, -3);
  const grouped = rest ? `${rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',')},${last3}` : last3;
  return `₹${grouped}${fraction && fraction !== '00' ? `.${fraction}` : ''}`;
}

export function distance(metres: number | null | undefined): string {
  if (metres == null || !Number.isFinite(metres)) return '—';
  if (metres < 1000) return `${Math.max(50, Math.round(metres / 50) * 50)} m`;
  return `${(metres / 1000).toFixed(1)} km`;
}

export function km(value: number | null | undefined): string {
  return value == null ? '—' : `${value.toFixed(1)} km`;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1]?.[0] ?? '' : '')).toUpperCase() || 'R';
}

export function greeting(now: Date = new Date()): string {
  const h = now.getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

export function clockTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  let h = d.getHours();
  const m = d.getMinutes().toString().padStart(2, '0');
  const suffix = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  return `${h}:${m} ${suffix}`;
}

export function dayLabel(isoDate: string, today: Date = new Date()): string {
  const d = new Date(`${isoDate}T00:00:00`);
  const diff = Math.round((new Date(today.toDateString()).getTime() - d.getTime()) / 86_400_000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  return d.toLocaleDateString('en-IN', { weekday: 'short' });
}

/** Three-letter weekday of a YYYY-MM-DD date, e.g. "Wed". */
export function weekday(isoDate: string): string {
  return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][new Date(`${isoDate}T00:00:00`).getDay()] ?? '';
}

/** +919876543210 -> +91 98765 43210 */
export function prettyPhone(phone: string | null | undefined): string {
  const digits = (phone ?? '').replace(/\D/g, '');
  if (digits.length === 12 && digits.startsWith('91')) return `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`;
  return phone ?? '';
}

/** A unique id per tap, reused on retry so the server applies it once. */
export function actionId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
