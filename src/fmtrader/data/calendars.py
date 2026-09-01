"""Session calendars for expected bar coverage and gap classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fmtrader.core.errors import DataError


@dataclass(frozen=True)
class SessionCalendar:
    """Defines when 1-minute bars are expected for an instrument.

    XAUUSD FX default: Sunday 22:00 UTC to Friday 21:00 UTC.
    Dukascopy fills the daily rollover window with flat bars, so that window
    remains in-session for coverage; flat-run detection marks it non-tradable.
    """

    name: str
    week_open_weekday: int  # Sunday = 6
    week_open_hour: int
    week_open_minute: int
    week_close_weekday: int  # Friday = 4
    week_close_hour: int
    week_close_minute: int
    daily_break_start_hour: int
    daily_break_end_hour: int
    holidays: frozenset[datetime]  # UTC midnights

    def is_in_session(self, ts: datetime) -> bool:
        """Return True if a 1m bar OPEN at ``ts`` is expected."""
        if ts.tzinfo is None:
            raise DataError("SessionCalendar requires tz-aware timestamps")
        utc = ts.astimezone(UTC)
        day = utc.replace(hour=0, minute=0, second=0, microsecond=0)
        if day in self.holidays:
            return False

        wd = utc.weekday()  # Mon=0 … Sun=6
        minutes = utc.hour * 60 + utc.minute
        week_open_m = self.week_open_hour * 60 + self.week_open_minute
        week_close_m = self.week_close_hour * 60 + self.week_close_minute

        if wd == 5:  # Saturday
            return False
        if wd == self.week_open_weekday and minutes < week_open_m:
            return False
        return not (wd == self.week_close_weekday and minutes >= week_close_m)

    def is_daily_break(self, ts: datetime) -> bool:
        """True during the Mon-Thu 21:00-22:00 UTC rollover window."""
        utc = ts.astimezone(UTC)
        wd = utc.weekday()
        minutes = utc.hour * 60 + utc.minute
        break_start = self.daily_break_start_hour * 60
        break_end = self.daily_break_end_hour * 60
        return wd in (0, 1, 2, 3) and break_start <= minutes < break_end

    def classify_gap(self, prev_ts: datetime, curr_ts: datetime) -> str:
        """Classify a gap between consecutive observed bars.

        Returns one of: ``weekend``, ``holiday``, ``rollover``, ``anomalous``, ``none``.
        """
        if prev_ts.tzinfo is None or curr_ts.tzinfo is None:
            raise DataError("classify_gap requires tz-aware timestamps")
        prev = prev_ts.astimezone(UTC)
        curr = curr_ts.astimezone(UTC)
        if curr - prev <= timedelta(minutes=1):
            return "none"

        cursor = prev + timedelta(minutes=1)
        saw_weekend = False
        saw_holiday = False
        saw_rollover = False
        steps = 0
        while cursor < curr and steps < 20_000:
            steps += 1
            day = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
            if day in self.holidays:
                saw_holiday = True
            elif self.is_in_session(cursor):
                return "anomalous"
            else:
                wd = cursor.weekday()
                minutes = cursor.hour * 60 + cursor.minute
                break_start = self.daily_break_start_hour * 60
                break_end = self.daily_break_end_hour * 60
                if wd in (5, 6) or (
                    wd == self.week_close_weekday
                    and minutes >= self.week_close_hour * 60 + self.week_close_minute
                ):
                    saw_weekend = True
                elif wd in (0, 1, 2, 3) and break_start <= minutes < break_end:
                    saw_rollover = True
                else:
                    saw_weekend = True
            cursor += timedelta(minutes=1)

        if saw_holiday and not saw_weekend:
            return "holiday"
        if saw_weekend:
            return "weekend"
        if saw_rollover:
            return "rollover"
        return "anomalous"


_XAU_HOLIDAYS = frozenset(
    {
        datetime(2021, 1, 1, tzinfo=UTC),
        datetime(2021, 12, 25, tzinfo=UTC),
        datetime(2022, 1, 1, tzinfo=UTC),
        datetime(2022, 12, 25, tzinfo=UTC),
        datetime(2023, 1, 1, tzinfo=UTC),
        datetime(2023, 12, 25, tzinfo=UTC),
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 12, 25, tzinfo=UTC),
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 12, 25, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
    }
)

XAUUSD_FX = SessionCalendar(
    name="xauusd_fx",
    week_open_weekday=6,
    week_open_hour=22,
    week_open_minute=0,
    week_close_weekday=4,
    week_close_hour=21,
    week_close_minute=0,
    daily_break_start_hour=21,
    daily_break_end_hour=22,
    holidays=_XAU_HOLIDAYS,
)

_REGISTRY: dict[str, SessionCalendar] = {
    XAUUSD_FX.name: XAUUSD_FX,
}


def get_calendar(name: str) -> SessionCalendar:
    """Look up a session calendar by registry key."""
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise DataError(f"Unknown session calendar: {name}") from exc
