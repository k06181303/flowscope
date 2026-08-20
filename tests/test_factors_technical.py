from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from flowscope.config.loader import load_config
from flowscope.factors.technical import (
    TECHNICAL_FACTORS,
    compute_technical_factor,
    compute_technical_factors,
)

AS_OF = date(2026, 8, 20)

FACTOR_PARAMS: dict[str, dict[str, Any]] = {
    "T01": {"ma_windows": [2, 3, 4], "full_score_ma": 3},
    "T02": {"window": 5, "annualization_days": 252},
    "T03": {"period": 2},
    "T04": {"atr_period": 2, "multiplier": 1.0},
    "T05": {"windows": [1, 2], "weights": [0.5, 0.5]},
    "T06": {"window": 3},
    "T07": {
        "fast_period": 2,
        "slow_period": 3,
        "signal_period": 2,
        "slope_window": 2,
        "atr_period": 2,
    },
    "T08": {"windows": [1], "weights": [1.0]},
    "T09": {"atr_period": 2},
    "T10": {"bb_period": 2, "bb_std": 1.0, "percentile_window": 3},
    "T11": {
        "bb_period": 2,
        "bb_std": 2.0,
        "kc_period": 2,
        "kc_atr_multiplier": 1.5,
    },
    "T12": {"segment_days": 2, "segment_count": 3},
    "T13": {"window": 3},
    "T14": {"period": 2},
    "T15": {"short_window": 2, "long_window": 4},
    "T16": {"window": 4},
    "T17": {"window": 4},
    "T18": {"window": 4},
    "T19": {
        "pivot_lookback": 10,
        "pivot_span": 1,
        "min_base_days": 3,
        "max_base_range": 0.25,
        "atr_period": 2,
    },
    "T20": {"ma_window": 2, "atr_period": 2},
    "T21": {"lookback": 8, "atr_period": 2, "threshold_atr": 0.5},
}


def test_t01_ma_alignment_golden() -> None:
    result = compute("T01", panel([1, 2, 3, 4]))

    # 手算:MA2=3.5 > MA3=3 > MA4=2.5，三組全對；close 4 > MA3，故為 1。
    assert raw(result) == pytest.approx(1.0)


def test_t02_log_price_ols_golden() -> None:
    closes = [math.exp(0.01 * index) for index in range(5)]
    result = compute("T02", panel(closes))

    # 手算:log(close)=0,0.01,...,0.04，OLS slope=.01、R2=1；年化=.01*252=2.52。
    assert raw(result) == pytest.approx(2.52)


def test_t03_wilder_adx_golden() -> None:
    result = compute("T03", panel([1, 2, 3, 4, 5], spread=0.5))

    # 單調上升且 -DM=0，每期 DX=100，Wilder ADX=100，+DI>-DI 所以維持正號。
    assert raw(result) == pytest.approx(100.0)
    assert result["plus_di"][0] > result["minus_di"][0]


def test_t04_supertrend_golden() -> None:
    result = compute("T04", panel([1, 2, 3, 4, 5, 6], spread=0.5))

    # index3 突破上軌後，index3..5 連續維持多方，state=+1、days=3。
    assert raw(result) == pytest.approx(1.0)
    assert result["supertrend_days"][0] == 3


def test_t05_relative_strength_golden() -> None:
    result = compute(
        "T05",
        panel([100, 110, 121], benchmark=[100, 105, 110]),
    )

    # RS1=(121/110)/(110/105)-1=.05；RS2=(121/100)/(110/100)-1=.10；均權=.075。
    assert raw(result) == pytest.approx(0.075)


def test_t06_mansfield_golden() -> None:
    result = compute("T06", panel([1, 2, 3], benchmark=[1, 1, 1]))

    # RS line=1,2,3；SMA=2；(3/2-1)*100=50。
    assert raw(result) == pytest.approx(50.0)


def test_t07_macd_histogram_slope_golden() -> None:
    result = compute("T07", panel([1, 2, 3, 4, 6], spread=1.0))

    # 手算最後兩根 histogram=0、1/18，OLS slope=1/18；Wilder ATR2=2.5，值=1/45。
    assert raw(result) == pytest.approx(1.0 / 45.0)


def test_t08_cross_sectional_roc_rank_golden() -> None:
    frame = pl.concat(
        [
            panel([100, 100], symbol="A"),
            panel([100, 110], symbol="B"),
            panel([100, 120], symbol="C"),
        ]
    )
    result = compute("T08", frame)

    # 三檔 1 日 ROC 為 0%、10%、20%；average-rank 百分位為 0、0.5、1。
    assert dict(result.select("symbol", "raw_value").rows()) == {
        "A": pytest.approx(0.0),
        "B": pytest.approx(0.5),
        "C": pytest.approx(1.0),
    }


def test_t09_atr_percent_golden() -> None:
    result = compute("T09", panel([10, 10, 10], spread=1.0))

    # 每日 TR=2，Wilder ATR2=2；2/10*100=20%。
    assert raw(result) == pytest.approx(20.0)


def test_t10_bollinger_width_percentile_golden() -> None:
    result = compute("T10", panel([1, 1, 1, 2]))

    # BB width 序列最後三值為 0、0、2/3；最新值為唯一最大，百分位=1。
    assert raw(result) == pytest.approx(1.0)


def test_t11_ttm_squeeze_release_golden() -> None:
    result = compute("T11", panel([10, 10, 10, 12], spread=0.1))

    # 前一日 BB(寬度0)完全位於 KC 內；末日 BB 上軌超過 KC 上軌，故剛釋放。
    assert raw(result) == pytest.approx(0.0)
    assert result["squeeze_released"][0] is True


def test_t12_volatility_contraction_golden() -> None:
    result = compute(
        "T12",
        panel(
            [10] * 6,
            highs=[11.5, 11.5, 11.0, 11.0, 10.5, 10.5],
            lows=[8.5, 8.5, 9.0, 9.0, 9.5, 9.5],
        ),
    )

    # 三段平均振幅為 .3、.2、.1，逐段收斂；ratio=.1/.3=1/3。
    assert raw(result) == pytest.approx(1.0)
    assert result["contraction_ratio"][0] == pytest.approx(1.0 / 3.0)


def test_t13_obv_divergence_golden() -> None:
    result = compute("T13", panel([1, 2, 3], volumes=[1, 2, 3]))

    # OBV=0,2,5，slope=2.5/mean_abs(7/3)=15/14；price slope=1/mean(2)=1/2。
    assert raw(result) == pytest.approx(4.0 / 7.0)


def test_t14_cmf_golden() -> None:
    result = compute(
        "T14",
        panel([10, 0], highs=[10, 10], lows=[0, 0], volumes=[1, 1]),
    )

    # 兩日 money-flow multiplier 為 +1、-1，等量成交，CMF=0。
    assert raw(result) == pytest.approx(0.0)


def test_t15_volume_dryup_golden() -> None:
    result = compute("T15", panel([1, 1, 1, 1], volumes=[4, 4, 2, 2]))

    # MA5 的測試縮窗 MA2=2；MA20 的測試縮窗 MA4=3；ratio=2/3。
    assert raw(result) == pytest.approx(2.0 / 3.0)


def test_t16_volume_surge_golden() -> None:
    result = compute("T16", panel([1, 1, 1, 2], volumes=[1, 1, 1, 4]))

    # 今日上漲；volume=4，MA4=7/4，surge=4/(7/4)=16/7。
    assert raw(result) == pytest.approx(16.0 / 7.0)


def test_t17_up_down_volume_ratio_golden() -> None:
    result = compute("T17", panel([1, 2, 1, 2, 1], volumes=[0, 2, 1, 4, 2]))

    # 上漲日量=2+4=6；下跌日量=1+2=3；ratio=2。
    assert raw(result) == pytest.approx(2.0)


def test_t18_distance_from_high_golden() -> None:
    result = compute(
        "T18",
        panel([10, 15, 17, 18], highs=[11, 16, 20, 19]),
    )

    # close=18，四日最高價=20；18/20-1=-0.1。
    assert raw(result) == pytest.approx(-0.1)


def test_t19_base_breakout_outputs_planner_fields_golden() -> None:
    highs = [9, 9, 9, 9, 10, 9, 9, 9, 9, 10]
    lows = [value - 1 for value in highs]
    closes = [8, 8, 8, 8, 9, 8, 8, 8, 8, 10]
    result = compute("T19", panel(closes, highs=highs, lows=lows))

    # index4 是左右各一日較低的 pivot high=10；base low=8、長6日；close=base high。
    assert raw(result) == pytest.approx(0.0)
    assert result["base_high"][0] == pytest.approx(10.0)
    assert result["base_low"][0] == pytest.approx(8.0)
    assert result["base_start_date"][0] == AS_OF - timedelta(days=5)
    assert result["base_length"][0] == 6


def test_t20_distance_to_ma_atr_golden() -> None:
    result = compute("T20", panel([9, 9, 9, 11], spread=1.0))

    # MA2=10；末日 gap 使 TR=3，前值 ATR=2，Wilder ATR2=(2+3)/2=2.5；值=.4。
    assert raw(result) == pytest.approx(0.4)


def test_t21_pivot_structure_golden() -> None:
    closes = [10, 12, 11, 13, 12, 14, 13, 15]
    result = compute("T21", panel(closes, spread=0.25))

    # 獨立 ZigZag:確認高點 12.25<13.25<14.25、低點 10.75<11.75<12.75，為 HH+HL。
    assert raw(result) == pytest.approx(1.0)
    assert result["last_swing_low"][0] == pytest.approx(12.75)


def test_registry_metadata_and_enabled_config_are_executable() -> None:
    config = load_config(Path("configs/tw_swing.yaml"))
    technical = config.factors.technical
    result = compute_technical_factors(
        panel([10.0] * 300, benchmark=[10.0] * 300),
        AS_OF,
        sorted(TECHNICAL_FACTORS),
        technical.all_params,
    )

    assert sorted(TECHNICAL_FACTORS) == [f"T{index:02d}" for index in range(1, 22)]
    assert all(definition.min_history_days > 0 for definition in TECHNICAL_FACTORS.values())
    assert all(definition.dimension == "technical" for definition in TECHNICAL_FACTORS.values())
    assert result["factor_id"].unique().sort().to_list() == sorted(TECHNICAL_FACTORS)
    assert result["as_of"].unique().to_list() == [AS_OF]


@pytest.mark.parametrize("factor_id", sorted(TECHNICAL_FACTORS))
def test_each_technical_factor_returns_null_for_insufficient_history(factor_id: str) -> None:
    result = compute(factor_id, panel([10]))

    assert result.height == 1
    assert raw(result) is None


@pytest.mark.parametrize("factor_id", sorted(TECHNICAL_FACTORS))
def test_each_technical_factor_handles_identical_values(factor_id: str) -> None:
    result = compute(
        factor_id,
        panel([10] * 300, volumes=[100] * 300, benchmark=[10] * 300),
    )

    assert result.height == 1
    assert result["factor_id"][0] == factor_id
    value = raw(result)
    assert value is None or math.isfinite(value)

    expected_values = {
        "T02": 0.0,
        "T08": 0.5,
        "T09": 0.0,
        "T10": 0.5,
        "T15": 1.0,
        "T16": 0.0,
    }
    if factor_id in expected_values:
        assert value == pytest.approx(expected_values[factor_id])
    if factor_id == "T03":
        assert value == 0.0
        assert math.copysign(1.0, value) == 1.0


def test_all_technical_factors_ignore_mixed_complete_zero_price_row() -> None:
    clean = panel([10.0] * 300, volumes=[100.0] * 300, benchmark=[10.0] * 300)
    zero_day = AS_OF - timedelta(days=300)
    with_zero = pl.concat(
        [
            clean,
            pl.DataFrame(
                {
                    "symbol": ["2330"],
                    "data_date": [zero_day],
                    "publish_date": [zero_day],
                    "open": [0.0],
                    "high": [0.0],
                    "low": [0.0],
                    "close": [0.0],
                    "volume": [0.0],
                    "amount": [0.0],
                    "benchmark_close": [10.0],
                }
            ),
        ],
        how="diagonal_relaxed",
    )

    expected = compute_technical_factors(
        clean,
        AS_OF,
        sorted(TECHNICAL_FACTORS),
        FACTOR_PARAMS,
    )
    actual = compute_technical_factors(
        with_zero,
        AS_OF,
        sorted(TECHNICAL_FACTORS),
        FACTOR_PARAMS,
    )

    assert actual.equals(expected)


def test_all_technical_factors_ignore_odd_lot_only_price_row() -> None:
    clean = panel([10.0] * 300, volumes=[100.0] * 300, benchmark=[10.0] * 300)
    odd_lot_day = AS_OF - timedelta(days=300)
    with_odd_lot = pl.concat(
        [
            clean,
            pl.DataFrame(
                {
                    "symbol": ["2330"],
                    "data_date": [odd_lot_day],
                    "publish_date": [odd_lot_day],
                    "open": [0.0],
                    "high": [0.0],
                    "low": [0.0],
                    "close": [0.0],
                    "volume": [3.0],
                    "amount": [74.0],
                    "benchmark_close": [10.0],
                }
            ),
        ],
        how="diagonal_relaxed",
    )

    expected = compute_technical_factors(
        clean,
        AS_OF,
        sorted(TECHNICAL_FACTORS),
        FACTOR_PARAMS,
    )
    actual = compute_technical_factors(
        with_odd_lot,
        AS_OF,
        sorted(TECHNICAL_FACTORS),
        FACTOR_PARAMS,
    )

    assert actual.equals(expected)


def test_all_technical_factors_return_null_for_all_zero_price_rows() -> None:
    result = compute_technical_factors(
        panel(
            [0.0] * 300,
            volumes=[0.0] * 300,
            benchmark=[10.0] * 300,
        ),
        AS_OF,
        sorted(TECHNICAL_FACTORS),
        FACTOR_PARAMS,
    )

    assert result.height == 21
    assert result["raw_value"].null_count() == 21


def panel(
    closes: list[float],
    *,
    symbol: str = "2330",
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
    benchmark: list[float] | None = None,
    spread: float = 0.0,
) -> pl.DataFrame:
    count = len(closes)
    dates = [AS_OF - timedelta(days=count - index - 1) for index in range(count)]
    actual_highs = highs or [close + spread for close in closes]
    actual_lows = lows or [close - spread for close in closes]
    data: dict[str, list[object]] = {
        "symbol": [symbol] * count,
        "data_date": dates,
        "publish_date": dates,
        "open": closes,
        "high": actual_highs,
        "low": actual_lows,
        "close": closes,
        "volume": volumes or [100.0] * count,
        "amount": [
            close * volume
            for close, volume in zip(
                closes,
                volumes or [100.0] * count,
                strict=True,
            )
        ],
    }
    if benchmark is not None:
        data["benchmark_close"] = benchmark
    return pl.DataFrame(data)


def compute(factor_id: str, frame: pl.DataFrame) -> pl.DataFrame:
    return compute_technical_factor(factor_id, frame, AS_OF, FACTOR_PARAMS[factor_id])


def raw(result: pl.DataFrame) -> float | None:
    value = result["raw_value"][0]
    return float(value) if value is not None else None
