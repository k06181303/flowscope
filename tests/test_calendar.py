from datetime import date

import polars as pl
import pytest

from flowscope.data.calendar import TradingCalendar


def test_trading_calendar_uses_supplied_dates_not_weekend_rules() -> None:
    calendar = TradingCalendar.from_frame(
        pl.DataFrame({"date": [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 6)]})
    )

    assert calendar.contains(date(2024, 1, 6))
    assert calendar.on_or_after(date(2024, 1, 4)) == date(2024, 1, 6)
    assert calendar.add_trading_days(date(2024, 1, 2), 2) == date(2024, 1, 6)


def test_trading_calendar_rejects_unsorted_dates() -> None:
    with pytest.raises(ValueError, match="must be sorted"):
        TradingCalendar(dates=(date(2024, 1, 3), date(2024, 1, 2)))
