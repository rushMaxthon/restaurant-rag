/**
 * Words and chart data for the Traffic page. The counting itself is the
 * server's (`backend/app/services/traffic.py`); these only present it, and
 * live here so they can be tested without rendering the page.
 */

import type { ChartDatum } from "../components/AnimatedCharts";
import type { TrafficDay } from "../types/app";

const pluralVisitors = (count: number) => `${count} visitor${count === 1 ? "" : "s"}`;

export function hourLabel(hour: number): string {
  const twelve = hour % 12 === 0 ? 12 : hour % 12;
  return `${twelve} ${hour < 12 ? "AM" : "PM"}`;
}

function hourRange(hour: number): string {
  const start = hourLabel(hour);
  const end = hourLabel((hour + 1) % 24);
  // "8–9 PM" rather than "8 PM–9 PM" when both ends share the half of the day.
  return start.slice(-2) === end.slice(-2) ? `${start.slice(0, -3)}–${end}` : `${start}–${end}`;
}

/** The three hours with the most visitors, busiest first, or null. */
export function busiestHours(hours: number[]): string | null {
  const ranked = hours
    .map((count, hour) => ({ count, hour }))
    .filter((entry) => entry.count > 0)
    .sort((a, b) => b.count - a.count || a.hour - b.hour)
    .slice(0, 3);
  return ranked.length ? ranked.map((entry) => hourRange(entry.hour)).join(", ") : null;
}

export function hourChart(hours: number[]): ChartDatum[] {
  return hours.map((count, hour) => ({
    label: hourLabel(hour),
    value: count,
    meta: `${pluralVisitors(count)}, ${hourRange(hour)}`,
  }));
}

function dayLabel(isoDay: string): string {
  // The server sends the business day as YYYY-MM-DD. Read as a calendar date,
  // not an instant, or a browser west of UTC shows yesterday.
  const [year, month, day] = isoDay.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function dailyChart(daily: TrafficDay[]): ChartDatum[] {
  return daily.map((row) => {
    const label = dayLabel(row.day);
    return { label, value: row.visitors, meta: `${label}: ${pluralVisitors(row.visitors)}, ${row.ordered} ordered` };
  });
}

export function versusYesterday(today: number, yesterday: number): string | null {
  if (yesterday === 0) return today === 0 ? null : "None yesterday";
  const change = Math.round(((today - yesterday) / yesterday) * 100);
  if (change === 0) return "Same as yesterday";
  return `${change > 0 ? "+" : "−"}${Math.abs(change)}% vs yesterday`;
}

export function percentText(value: number | null): string {
  return value === null ? "—" : `${value}%`;
}
