from __future__ import annotations

import random
from datetime import date, timedelta

import polars as pl

from flowscope.data.pit import as_of_filter


def test_as_of_filter_rejects_future_rows_for_200_symbol_as_of_samples() -> None:
    symbols = [f"{index:04d}" for index in range(1, 41)]
    base = date(2024, 1, 1)
    rows: list[dict[str, object]] = []
    for symbol_index, symbol in enumerate(symbols):
        for offset in range(20):
            data_date = base + timedelta(days=offset)
            rows.append(
                {
                    "symbol": symbol,
                    "data_date": data_date,
                    "publish_date": data_date + timedelta(days=symbol_index % 5),
                    "value": symbol_index * 100 + offset,
                }
            )
    df = pl.DataFrame(rows)

    rng = random.Random(20260819)
    samples = [
        (rng.choice(symbols), base + timedelta(days=rng.randrange(0, 25))) for _ in range(200)
    ]

    for symbol, as_of in samples:
        result = as_of_filter(df.filter(pl.col("symbol") == symbol), as_of)
        expected_values = [
            row["value"]
            for row in rows
            if row["symbol"] == symbol and row["publish_date"] <= as_of
        ]
        # 期望值來源:獨立 list comprehension 手算 publish_date <= as_of 的列。
        assert result["value"].to_list() == expected_values
        assert all(value <= as_of for value in result["publish_date"].to_list())
