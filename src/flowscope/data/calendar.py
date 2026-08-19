from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date

import polars as pl


@dataclass(frozen=True)
class TradingCalendar:
    dates: tuple[date, ...]

    def __post_init__(self) -> None:
        if not self.dates:
            raise ValueError("TradingCalendar requires at least one date")
        ordered = tuple(sorted(self.dates))
        if ordered != self.dates:
            raise ValueError("TradingCalendar dates must be sorted")

    @classmethod
    def from_frame(cls, df: pl.DataFrame) -> TradingCalendar:
        if "date" not in df.columns:
            raise ValueError("Trading calendar DataFrame must contain date")
        dates = tuple(df.select("date").to_series().to_list())
        if not all(isinstance(value, date) for value in dates):
            raise TypeError("Trading calendar date column must contain date values")
        return cls(dates=dates)

    def contains(self, value: date) -> bool:
        index = bisect_left(self.dates, value)
        return index < len(self.dates) and self.dates[index] == value

    def on_or_after(self, value: date) -> date:
        index = bisect_left(self.dates, value)
        if index >= len(self.dates):
            raise ValueError(f"No trading date on or after {value.isoformat()}")
        return self.dates[index]

    def on_or_before(self, value: date) -> date:
        index = bisect_right(self.dates, value) - 1
        if index < 0:
            raise ValueError(f"No trading date on or before {value.isoformat()}")
        return self.dates[index]

    def count_between(self, start: date, end: date) -> int:
        if start > end:
            return 0
        left = bisect_left(self.dates, start)
        right = bisect_right(self.dates, end)
        return right - left

    def trailing_dates(self, end: date, days: int) -> tuple[date, ...]:
        if days <= 0:
            raise ValueError("days must be positive")
        end_index = bisect_right(self.dates, end)
        start_index = max(0, end_index - days)
        return self.dates[start_index:end_index]

    def add_trading_days(self, value: date, days: int) -> date:
        if days < 0:
            raise ValueError("days must be non-negative")
        start_index = bisect_left(self.dates, value)
        target = start_index + days
        if target >= len(self.dates):
            raise ValueError(f"Trading calendar does not cover {days} days after {value}")
        return self.dates[target]
