from __future__ import annotations

from datetime import date

import polars as pl


def as_of_filter(df: pl.DataFrame, as_of: date) -> pl.DataFrame:
    """所有資料離開 provider 前都必須經過這個 PIT 過濾。"""
    if "publish_date" not in df.columns:
        raise ValueError("DataFrame must contain publish_date before PIT filtering")
    return df.filter(pl.col("publish_date") <= as_of)
