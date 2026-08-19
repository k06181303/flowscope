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
    if events.is_empty():
        return raw

    raw_with_id = raw.with_row_index("__row_id")
    factors = (
        raw_with_id.select("__row_id", "symbol", "data_date")
        .join(events, on="symbol", how="inner")
        .filter(pl.col("data_date") < pl.col("event_date"))
        .group_by("__row_id")
        .agg(pl.col("ratio").product().alias("__adjustment_factor"))
    )
    return (
        raw_with_id.join(factors, on="__row_id", how="left")
        .with_columns(pl.col("__adjustment_factor").fill_null(1.0))
        .with_columns(
            [
                (pl.col(column).cast(pl.Float64) * pl.col("__adjustment_factor")).alias(column)
                for column in PRICE_COLUMNS
            ]
        )
        .drop("__row_id", "__adjustment_factor")
        .select(raw.columns)
    )


def _valid_adjustment_events(
    dividend_events: pl.DataFrame,
    as_of: date,
) -> pl.DataFrame:
    required = {"symbol", "data_date", "before_price", "after_price"}
    missing = required - set(dividend_events.columns)
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(f"Dividend events are missing required columns: {joined}")

    return (
        dividend_events.with_columns(
            pl.col("symbol").cast(pl.Utf8),
            pl.col("data_date").alias("event_date"),
            pl.col("before_price").cast(pl.Float64),
            pl.col("after_price").cast(pl.Float64),
        )
        .filter(
            (pl.col("event_date") <= as_of)
            & (pl.col("before_price") > 0)
            & (pl.col("after_price") > 0)
        )
        .with_columns((pl.col("after_price") / pl.col("before_price")).alias("ratio"))
        .select("symbol", "event_date", "ratio")
        .sort(["symbol", "event_date"])
    )
