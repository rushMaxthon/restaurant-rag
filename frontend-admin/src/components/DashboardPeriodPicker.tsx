import { CalendarRange } from "lucide-react";

import {
  PERIOD_OPTIONS,
  isoDay,
  isoMonth,
  periodFor,
  type DashboardPeriod,
  type PeriodKind,
} from "../services/dashboardPeriod";

/**
 * Today, yesterday, a week, a month, a chosen month or year, or any dates -
 * for the platform admin and the owner alike. The detail control appears
 * beside the menu only for the kinds that need one.
 */
export function DashboardPeriodPicker({
  period,
  onChange,
  years,
}: {
  period: DashboardPeriod;
  onChange: (period: DashboardPeriod) => void;
  /** The years there is anything to see in, newest first. */
  years: number[];
}) {
  const now = new Date();
  const today = isoDay(now);

  return (
    <div className="period-picker">
      <label className="period-picker__field">
        <CalendarRange aria-hidden="true" size={15} />
        <select
          aria-label="Show figures for"
          onChange={(event) => onChange(periodFor(event.target.value as PeriodKind, now))}
          value={period.kind}
        >
          {PERIOD_OPTIONS.map((option) => (
            <option key={option.kind} value={option.kind}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      {period.kind === "month" ? (
        <label className="period-picker__field">
          <input
            aria-label="Month"
            max={isoMonth(now)}
            onChange={(event) => event.target.value && onChange({ kind: "month", month: event.target.value })}
            type="month"
            value={period.month ?? ""}
          />
        </label>
      ) : null}

      {period.kind === "year" ? (
        <label className="period-picker__field">
          <select
            aria-label="Year"
            onChange={(event) => onChange({ kind: "year", year: Number(event.target.value) })}
            value={period.year ?? now.getFullYear()}
          >
            {years.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {period.kind === "custom" ? (
        <>
          <label className="period-picker__field">
            <span>From</span>
            <input
              aria-label="From"
              max={period.to || today}
              onChange={(event) => event.target.value && onChange({ ...period, from: event.target.value })}
              type="date"
              value={period.from ?? ""}
            />
          </label>
          <label className="period-picker__field">
            <span>To</span>
            <input
              aria-label="To"
              max={today}
              min={period.from}
              onChange={(event) => event.target.value && onChange({ ...period, to: event.target.value })}
              type="date"
              value={period.to ?? ""}
            />
          </label>
        </>
      ) : null}
    </div>
  );
}
