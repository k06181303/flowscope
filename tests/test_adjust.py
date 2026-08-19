from datetime import date

import polars as pl
import pytest

from flowscope.data.adjust import backward_adjust_ohlcv


def test_backward_adjust_uses_only_events_not_later_than_as_of() -> None:
    raw = pl.DataFrame(
        [
            ohlcv_row(date(2024, 1, 2), 100.0, 110.0, 90.0, 100.0),
            ohlcv_row(date(2024, 1, 3), 110.0, 121.0, 99.0, 110.0),
            ohlcv_row(date(2024, 1, 4), 90.0, 99.0, 81.0, 90.0),
        ]
    )
    dividends = pl.DataFrame(
        [
            {
                "symbol": "2330",
                "data_date": date(2024, 1, 4),
                "before_price": 100.0,
                "after_price": 90.0,
            },
            {
                "symbol": "2330",
                "data_date": date(2024, 2, 1),
                "before_price": 100.0,
                "after_price": 50.0,
            },
        ]
    )

    adjusted = backward_adjust_ohlcv(raw, dividends, date(2024, 1, 31))

    # 手算來源:2024-01-04 除權息比率 = after/before = 90/100 = 0.9。
    # as_of=2024-01-31,所以 2024-02-01 的未來事件不可用。
    assert adjusted["open"].to_list() == pytest.approx([90.0, 99.0, 90.0])
    assert adjusted["close"].to_list() == pytest.approx([90.0, 99.0, 90.0])


def test_backward_adjust_preserves_returns_when_later_event_adds_common_scale() -> None:
    raw = pl.DataFrame(
        [
            ohlcv_row(date(2024, 1, 2), 100.0, 100.0, 100.0, 100.0),
            ohlcv_row(date(2024, 1, 3), 110.0, 110.0, 110.0, 110.0),
        ]
    )
    dividends = pl.DataFrame(
        [
            {
                "symbol": "2330",
                "data_date": date(2024, 2, 1),
                "before_price": 100.0,
                "after_price": 50.0,
            }
        ]
    )

    before_future_event = backward_adjust_ohlcv(raw, dividends, date(2024, 1, 31))
    after_future_event = backward_adjust_ohlcv(raw, dividends, date(2024, 2, 1))

    # 獨立驗算:兩日報酬均為 110/100 - 1 = 10%。未來事件只會把兩日同乘 0.5。
    before_return = before_future_event["close"][1] / before_future_event["close"][0] - 1
    after_return = after_future_event["close"][1] / after_future_event["close"][0] - 1
    assert before_return == pytest.approx(0.10)
    assert after_return == pytest.approx(0.10)


def ohlcv_row(
    data_date: date,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> dict[str, object]:
    return {
        "symbol": "2330",
        "data_date": data_date,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
    }
