"""Business-timezone period resolution for insights.

Two rules this module exists to enforce:

1. A "day" is a day in the restaurant's local timezone, not in UTC. With the
   default `Asia/Kolkata` (+05:30), a UTC-bucketed day boundary cuts the dinner
   rush in half and shifts every hour bucket by five and a half hours.
2. A window runs up to and including today. An owner asking for "the last 7
   days" on the 19th means the 13th to the 19th, and a screen that quietly
   answered for the 12th to the 18th was describing a week they did not ask
   about — most visibly first thing in the morning, when today's trade is the
   thing they opened the page to look at.

   Today is a partial day, and every caller is told so: `includes_partial_day`
   is set, the diagnostics notes say it in words, and the comparison shortens
   its cache lifetime accordingly. That is the honest way to include a day in
   progress — state it, rather than drop it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from app.config import get_settings

settings = get_settings()


@dataclass(frozen=True, slots=True)
class AnalysisPeriod:
    """An inclusive local-date range plus its half-open UTC instant bounds."""

    start_date: date
    end_date: date
    start_at: datetime
    end_at: datetime
    timezone_name: str

    @property
    def day_count(self) -> int:
        return (self.end_date - self.start_date).days + 1

    def label(self) -> str:
        if self.start_date == self.end_date:
            return self.start_date.strftime("%d %b %Y")
        return f"{self.start_date.strftime('%d %b')} - {self.end_date.strftime('%d %b %Y')}"


@dataclass(frozen=True, slots=True)
class PeriodComparison:
    current: AnalysisPeriod
    previous: AnalysisPeriod
    timezone_name: str
    # True when both windows cover the same weekday mix, which only holds for
    # whole-week lengths. A 5-day window compared against the prior 5 days puts
    # a weekend against weekdays, and callers should say so rather than imply
    # the delta is like-for-like.
    weekday_aligned: bool
    # True when the caller explicitly asked for a range running into today, so
    # the current window holds a partial day.
    includes_partial_day: bool


def business_timezone(timezone_name: str | None = None) -> ZoneInfo:
    if timezone_name is None:
        return settings.business_timezone_info
    return ZoneInfo(timezone_name)


def local_today(timezone_name: str | None = None) -> date:
    return datetime.now(business_timezone(timezone_name)).date()


def _to_utc_bounds(
    start_date: date,
    end_date: date,
    tzinfo: ZoneInfo,
) -> tuple[datetime, datetime]:
    """Return the half-open [start, end) UTC instants for an inclusive local range."""

    start_at = datetime.combine(start_date, time.min, tzinfo=tzinfo).astimezone(UTC)
    end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tzinfo).astimezone(UTC)
    return start_at, end_at


def build_period(
    start_date: date,
    end_date: date,
    *,
    timezone_name: str | None = None,
) -> AnalysisPeriod:
    tz_name = timezone_name or settings.business_timezone
    tzinfo = business_timezone(tz_name)
    start_at, end_at = _to_utc_bounds(start_date, end_date, tzinfo)
    return AnalysisPeriod(
        start_date=start_date,
        end_date=end_date,
        start_at=start_at,
        end_at=end_at,
        timezone_name=tz_name,
    )


def previous_period(current: AnalysisPeriod) -> AnalysisPeriod:
    """The equally long window ending the day before `current` starts."""

    end_date = current.start_date - timedelta(days=1)
    start_date = end_date - timedelta(days=current.day_count - 1)
    return build_period(start_date, end_date, timezone_name=current.timezone_name)


def resolve_period_comparison(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    window_days: int | None = None,
    timezone_name: str | None = None,
) -> PeriodComparison:
    """Resolve the current and previous analysis windows.

    With no dates supplied, the current window is the last
    `insights_default_window_days` local days **ending today**, and the previous
    window is the equally long stretch immediately before it. On 19 Aug a
    7-day window is 13-19 Aug, compared against 6-12 Aug.
    """

    tz_name = timezone_name or settings.business_timezone
    today = local_today(tz_name)

    if date_from is not None and date_to is not None and date_from > date_to:
        date_from, date_to = date_to, date_from

    if date_from is None and date_to is None:
        length = window_days or settings.insights_default_window_days
        # Today counts. It is a day in progress rather than a missing one, and
        # `includes_partial_day` carries that fact to everything downstream.
        end_date = today
        start_date = end_date - timedelta(days=length - 1)
    elif date_from is not None and date_to is None:
        length = window_days or settings.insights_default_window_days
        start_date = date_from
        end_date = min(date_from + timedelta(days=length - 1), today)
    elif date_from is None and date_to is not None:
        length = window_days or settings.insights_default_window_days
        end_date = date_to
        start_date = end_date - timedelta(days=length - 1)
    else:
        assert date_from is not None and date_to is not None
        start_date = date_from
        end_date = date_to

    day_count = (end_date - start_date).days + 1
    if day_count < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Analysis window must cover at least one day",
        )
    if day_count > settings.insights_max_window_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Analysis window is limited to "
                f"{settings.insights_max_window_days} days"
            ),
        )

    current = build_period(start_date, end_date, timezone_name=tz_name)
    return PeriodComparison(
        current=current,
        previous=previous_period(current),
        timezone_name=tz_name,
        weekday_aligned=day_count % 7 == 0,
        includes_partial_day=end_date >= today,
    )


def baseline_period(
    current: AnalysisPeriod,
    *,
    baseline_days: int | None = None,
) -> AnalysisPeriod:
    """The trailing daily-series window used for anomaly detection.

    It ends the day before `current` starts, so the window under investigation
    never contributes to the baseline it is being judged against.
    """

    days = baseline_days or settings.insights_anomaly_baseline_days
    end_date = current.start_date - timedelta(days=1)
    start_date = end_date - timedelta(days=days - 1)
    return build_period(start_date, end_date, timezone_name=current.timezone_name)


__all__ = [
    "AnalysisPeriod",
    "PeriodComparison",
    "baseline_period",
    "build_period",
    "business_timezone",
    "local_today",
    "previous_period",
    "resolve_period_comparison",
]
