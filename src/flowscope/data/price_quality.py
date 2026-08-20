from __future__ import annotations

import polars as pl

PRICE_ACTIVITY_COLUMNS = ("open", "high", "low", "close", "volume", "amount")
PRICE_QUOTE_COLUMNS = ("open", "high", "low", "close")


def is_invalid_price_row() -> pl.Expr:
    """辨識只有零股量額、但沒有整股 OHLC 的價格列。"""
    return pl.all_horizontal(pl.col(column) == 0 for column in PRICE_QUOTE_COLUMNS)
