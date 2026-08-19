from __future__ import annotations

import random
from datetime import date, timedelta

import polars as pl

from flowscope.data.calendar import TradingCalendar
from flowscope.data.pit import as_of_filter
from flowscope.data.providers.finmind import align_holder_distribution_to_trading_days


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


def test_holder_distribution_daily_alignment_never_uses_unpublished_weekly_data() -> None:
    weekly = pl.DataFrame(
        [
            {
                "symbol": "2330",
                "data_date": date(2024, 1, 5),
                "publish_date": date(2024, 1, 12),
                "tier": 400_001,
                "holder_count": 1,
                "share_count": 800,
                "share_pct": 80.0,
                "share_pct_sum": 100.0,
                "share_pct_sum_ok": True,
            },
            {
                "symbol": "2330",
                "data_date": date(2024, 1, 12),
                "publish_date": date(2024, 1, 19),
                "tier": 400_001,
                "holder_count": 2,
                "share_count": 850,
                "share_pct": 85.0,
                "share_pct_sum": 100.0,
                "share_pct_sum_ok": True,
            },
        ]
    )
    calendar = TradingCalendar(
        (
            date(2024, 1, 8),
            date(2024, 1, 11),
            date(2024, 1, 12),
            date(2024, 1, 15),
            date(2024, 1, 19),
        )
    )

    daily = align_holder_distribution_to_trading_days(
        weekly,
        calendar,
        date(2024, 1, 8),
        date(2024, 1, 19),
    )

    # 期望值來源:集保 2024-01-05 資料在 2024-01-12 才公開,
    # 2024-01-12 資料在 2024-01-19 才公開；公布日前不得 forward fill。
    assert list(daily.select("as_of_date", "data_date", "share_pct").iter_rows()) == [
        (date(2024, 1, 12), date(2024, 1, 5), 80.0),
        (date(2024, 1, 15), date(2024, 1, 5), 80.0),
        (date(2024, 1, 19), date(2024, 1, 12), 85.0),
    ]
    assert all(
        row <= as_of
        for row, as_of in zip(daily["publish_date"], daily["as_of_date"], strict=True)
    )
