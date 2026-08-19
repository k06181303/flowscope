from __future__ import annotations

from datetime import date

import polars as pl

PRICE_COLUMNS = ("open", "high", "low", "close")


def backward_adjust_ohlcv(
    raw: pl.DataFrame,
    dividend_events: pl.DataFrame,
    as_of: date,
) -> pl.DataFrame:
    """用不晚於 as_of 的除權息事件做向後還原，避免最新基準日造成 PIT 洩漏。"""
    required = {"symbol", "data_date", *PRICE_COLUMNS}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Raw OHLCV is missing required columns: {', '.join(sorted(missing))}")
    if dividend_events.is_empty():
        return raw

    events = _valid_adjustment_events(dividend_events, as_of)
    if not events:
        return raw

    adjusted_rows: list[dict[str, object]] = []
    for row in raw.sort(["symbol", "data_date"]).iter_rows(named=True):
        symbol = str(row["symbol"])
        data_date = _expect_date(row["data_date"], "data_date")
        factor = 1.0
        for event_symbol, event_date, ratio in events:
            if event_symbol == symbol and data_date < event_date:
                factor *= ratio
        adjusted = dict(row)
        for column in PRICE_COLUMNS:
            value = row[column]
            adjusted[column] = None if value is None else float(value) * factor
        adjusted_rows.append(adjusted)

    return pl.DataFrame(adjusted_rows, schema=raw.schema)


def _valid_adjustment_events(
    dividend_events: pl.DataFrame,
    as_of: date,
) -> list[tuple[str, date, float]]:
    required = {"symbol", "data_date", "before_price", "after_price"}
    missing = required - set(dividend_events.columns)
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(f"Dividend events are missing required columns: {joined}")

    events: list[tuple[str, date, float]] = []
    for row in dividend_events.sort(["symbol", "data_date"]).iter_rows(named=True):
        event_date = _expect_date(row["data_date"], "data_date")
        before = float(row["before_price"])
        after = float(row["after_price"])
        if event_date <= as_of and before > 0 and after > 0:
            events.append((str(row["symbol"]), event_date, after / before))
    return events


def _expect_date(value: object, column: str) -> date:
    if isinstance(value, date):
        return value
    raise TypeError(f"{column} must contain date values")
