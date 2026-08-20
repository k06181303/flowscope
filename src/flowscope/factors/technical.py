from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import fmean, pstdev
from typing import Any, Literal

import polars as pl

from flowscope.data.pit import as_of_filter
from flowscope.data.price_quality import PRICE_ACTIVITY_COLUMNS, is_invalid_price_row

Direction = Literal[-1, 0, 1]
FactorComputer = Callable[[list["PriceSeries"], Mapping[str, Any]], pl.DataFrame]

REQUIRED_PRICE_COLUMNS = {
    "symbol",
    "data_date",
    "publish_date",
    *PRICE_ACTIVITY_COLUMNS,
}


@dataclass(frozen=True)
class FactorDefinition:
    factor_id: str
    name: str
    direction: Direction
    min_history_days: int
    compute: FactorComputer
    dimension: Literal["technical"] = "technical"
    horizons: tuple[Literal["swing"], ...] = ("swing",)


@dataclass(frozen=True)
class PriceSeries:
    symbol: str
    dates: tuple[date, ...]
    opens: tuple[float, ...]
    highs: tuple[float, ...]
    lows: tuple[float, ...]
    closes: tuple[float, ...]
    volumes: tuple[float, ...]
    benchmark_closes: tuple[float | None, ...]

    @property
    def size(self) -> int:
        return len(self.dates)


def compute_technical_factor(
    factor_id: str,
    panel: pl.DataFrame,
    as_of: date,
    params: Mapping[str, Any],
) -> pl.DataFrame:
    try:
        definition = TECHNICAL_FACTORS[factor_id]
    except KeyError:
        raise ValueError(f"Unknown technical factor: {factor_id}") from None
    return (
        definition.compute(prepare_series(panel, as_of), params)
        .with_columns(pl.lit(as_of).cast(pl.Date).alias("as_of"))
        .sort("symbol")
    )


def compute_technical_factors(
    panel: pl.DataFrame,
    as_of: date,
    enabled: Sequence[str],
    params: Mapping[str, Mapping[str, Any]],
) -> pl.DataFrame:
    series = prepare_series(panel, as_of)
    frames: list[pl.DataFrame] = []
    for factor_id in enabled:
        try:
            definition = TECHNICAL_FACTORS[factor_id]
        except KeyError:
            raise ValueError(f"Unknown technical factor: {factor_id}") from None
        try:
            factor_params = params[factor_id]
        except KeyError:
            raise ValueError(f"Missing params for enabled technical factor: {factor_id}") from None
        frames.append(definition.compute(series, factor_params))
    if not frames:
        raise ValueError("enabled technical factors must not be empty")
    return (
        pl.concat(frames, how="diagonal_relaxed")
        .with_columns(pl.lit(as_of).cast(pl.Date).alias("as_of"))
        .sort(["as_of", "factor_id", "symbol"])
    )


def compute_technical_factor_history(
    panel: pl.DataFrame,
    as_of_dates: Sequence[date],
    factor_ids: Sequence[str],
    params: Mapping[str, Mapping[str, Any]],
) -> pl.DataFrame:
    ordered_dates = sorted(set(as_of_dates))
    if not ordered_dates:
        raise ValueError("as_of_dates must not be empty")
    frames = [
        compute_technical_factors(panel, as_of, factor_ids, params) for as_of in ordered_dates
    ]
    return pl.concat(frames, how="diagonal_relaxed").sort(
        ["as_of", "factor_id", "symbol"]
    )


def prepare_series(panel: pl.DataFrame, as_of: date) -> list[PriceSeries]:
    missing = sorted(REQUIRED_PRICE_COLUMNS - set(panel.columns))
    if missing:
        raise ValueError(f"technical panel missing columns: {', '.join(missing)}")
    point_in_time = as_of_filter(panel, as_of).filter(pl.col("data_date") <= as_of)
    if point_in_time.is_empty():
        raise ValueError("technical panel has no point-in-time rows")
    symbols = point_in_time["symbol"].cast(pl.Utf8).unique().sort().to_list()
    filtered = point_in_time.filter(~is_invalid_price_row()).sort(
        ["symbol", "data_date"]
    )
    frames_by_symbol = {
        str(symbol_frame["symbol"][0]): symbol_frame
        for symbol_frame in filtered.partition_by("symbol", maintain_order=True)
    }

    result: list[PriceSeries] = []
    for symbol in symbols:
        symbol_frame = frames_by_symbol.get(symbol)
        if symbol_frame is None:
            result.append(empty_price_series(symbol))
            continue
        benchmark = (
            [
                float(value) if value is not None else None
                for value in symbol_frame["benchmark_close"]
            ]
            if "benchmark_close" in symbol_frame.columns
            else [None] * symbol_frame.height
        )
        result.append(
            PriceSeries(
                symbol=symbol,
                dates=tuple(expect_date(value, "data_date") for value in symbol_frame["data_date"]),
                opens=tuple(float(value) for value in symbol_frame["open"]),
                highs=tuple(float(value) for value in symbol_frame["high"]),
                lows=tuple(float(value) for value in symbol_frame["low"]),
                closes=tuple(float(value) for value in symbol_frame["close"]),
                volumes=tuple(float(value) for value in symbol_frame["volume"]),
                benchmark_closes=tuple(benchmark),
            )
        )
    return result


def empty_price_series(symbol: str) -> PriceSeries:
    return PriceSeries(
        symbol=symbol,
        dates=(),
        opens=(),
        highs=(),
        lows=(),
        closes=(),
        volumes=(),
        benchmark_closes=(),
    )


def compute_t01(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    windows = int_list_param(params, "ma_windows")
    full_score_ma = int_param(params, "full_score_ma")
    pair_count = len(windows) * (len(windows) - 1) // 2
    if pair_count == 0:
        raise ValueError("T01 ma_windows must contain at least two windows")
    rows: list[dict[str, object]] = []
    for item in series:
        value: float | None = None
        if item.size >= max(max(windows), full_score_ma):
            averages = [fmean(item.closes[-window:]) for window in windows]
            aligned = sum(
                averages[left] > averages[right]
                for left in range(len(averages))
                for right in range(left + 1, len(averages))
            )
            value = aligned / pair_count
            if item.closes[-1] <= fmean(item.closes[-full_score_ma:]):
                value *= 0.8
        rows.append(factor_row(item.symbol, "T01", "ma_alignment_score", value))
    return factor_frame(rows)


def compute_t02(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    window = int_param(params, "window")
    annualization_days = int_param(params, "annualization_days")
    rows = []
    for item in series:
        value = None
        if item.size >= window and all(close > 0 for close in item.closes[-window:]):
            slope, r2 = ols([math.log(close) for close in item.closes[-window:]])
            value = slope * annualization_days * r2
        rows.append(factor_row(item.symbol, "T02", "linreg_slope_r2", value))
    return factor_frame(rows)


def compute_t03(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    period = int_param(params, "period")
    rows: list[dict[str, object]] = []
    for item in series:
        adx_value, plus_di, minus_di = adx(item.highs, item.lows, item.closes, period)
        value = None
        if adx_value is not None and plus_di is not None and minus_di is not None:
            value = adx_value if plus_di > minus_di else -adx_value
            if value == 0.0:
                value = 0.0
        row = factor_row(item.symbol, "T03", "adx", value)
        row.update(plus_di=plus_di, minus_di=minus_di)
        rows.append(row)
    return factor_frame(rows)


def compute_t04(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    period = int_param(params, "atr_period")
    multiplier = float_param(params, "multiplier")
    rows: list[dict[str, object]] = []
    for item in series:
        state, days = supertrend(item.highs, item.lows, item.closes, period, multiplier)
        row = factor_row(item.symbol, "T04", "supertrend_state", state)
        row["supertrend_days"] = days
        rows.append(row)
    return factor_frame(rows)


def compute_t05(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    windows = int_list_param(params, "windows")
    weights = float_list_param(params, "weights")
    if len(windows) != len(weights) or not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
        raise ValueError("T05 windows and weights must align and weights must sum to 1")
    rows = []
    for item in series:
        value = None
        if item.size > max(windows):
            components: list[float] = []
            for window in windows:
                benchmark_now = item.benchmark_closes[-1]
                benchmark_then = item.benchmark_closes[-window - 1]
                if benchmark_now is None or benchmark_then is None or benchmark_then == 0:
                    components = []
                    break
                stock_return = item.closes[-1] / item.closes[-window - 1] - 1.0
                benchmark_return = benchmark_now / benchmark_then - 1.0
                components.append((1.0 + stock_return) / (1.0 + benchmark_return) - 1.0)
            if components:
                value = sum(
                    weight * component
                    for weight, component in zip(weights, components, strict=True)
                )
        rows.append(factor_row(item.symbol, "T05", "relative_strength_pct", value))
    return factor_frame(rows)


def compute_t06(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    window = int_param(params, "window")
    rows = []
    for item in series:
        value = None
        if item.size >= window:
            relative = [
                close / benchmark if benchmark not in (None, 0.0) else None
                for close, benchmark in zip(
                    item.closes[-window:],
                    item.benchmark_closes[-window:],
                    strict=True,
                )
            ]
            if all(entry is not None for entry in relative):
                values = [float(entry) for entry in relative if entry is not None]
                average = fmean(values)
                if average != 0:
                    value = (values[-1] / average - 1.0) * 100.0
        rows.append(factor_row(item.symbol, "T06", "mansfield_rsi", value))
    return factor_frame(rows)


def compute_t07(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    fast = int_param(params, "fast_period")
    slow = int_param(params, "slow_period")
    signal_period = int_param(params, "signal_period")
    slope_window = int_param(params, "slope_window")
    atr_period = int_param(params, "atr_period")
    rows = []
    for item in series:
        value = None
        fast_ema = ema(item.closes, fast)
        slow_ema = ema(item.closes, slow)
        macd = [
            fast_value - slow_value
            if fast_value is not None and slow_value is not None
            else None
            for fast_value, slow_value in zip(fast_ema, slow_ema, strict=True)
        ]
        signal = ema_optional(macd, signal_period)
        histogram = [
            macd_value - signal_value
            if macd_value is not None and signal_value is not None
            else None
            for macd_value, signal_value in zip(macd, signal, strict=True)
        ]
        latest_histogram = trailing_non_null(histogram, slope_window)
        latest_atr = last_non_null(wilder_atr(item.highs, item.lows, item.closes, atr_period))
        if latest_histogram is not None and latest_atr not in (None, 0.0):
            value = ols(latest_histogram)[0] / latest_atr
        rows.append(factor_row(item.symbol, "T07", "macd_histogram_slope", value))
    return factor_frame(rows)


def compute_t08(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    windows = int_list_param(params, "windows")
    weights = float_list_param(params, "weights")
    if len(windows) != len(weights) or not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
        raise ValueError("T08 windows and weights must align and weights must sum to 1")
    raw: dict[str, list[float] | None] = {}
    for item in series:
        raw[item.symbol] = (
            [item.closes[-1] / item.closes[-window - 1] - 1.0 for window in windows]
            if item.size > max(windows)
            else None
        )
    percentiles: list[dict[str, float]] = []
    for index in range(len(windows)):
        values = {
            symbol: components[index]
            for symbol, components in raw.items()
            if components is not None
        }
        percentiles.append(cross_sectional_percentiles(values))
    rows = []
    for item in series:
        components = raw[item.symbol]
        value = (
            sum(weights[index] * percentiles[index][item.symbol] for index in range(len(windows)))
            if components is not None
            else None
        )
        rows.append(factor_row(item.symbol, "T08", "roc_rank_composite", value))
    return factor_frame(rows)


def compute_t09(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    period = int_param(params, "atr_period")
    rows = []
    for item in series:
        latest_atr = last_non_null(wilder_atr(item.highs, item.lows, item.closes, period))
        value = (
            latest_atr / item.closes[-1] * 100.0
            if latest_atr is not None and item.closes[-1] != 0
            else None
        )
        rows.append(factor_row(item.symbol, "T09", "atr_percent", value))
    return factor_frame(rows)


def compute_t10(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    period = int_param(params, "bb_period")
    deviations = float_param(params, "bb_std")
    percentile_window = int_param(params, "percentile_window")
    rows = []
    for item in series:
        widths = bollinger_widths(item.closes, period, deviations)
        recent = trailing_non_null(widths, percentile_window)
        value = percentile_of_last(recent) if recent is not None else None
        rows.append(factor_row(item.symbol, "T10", "bb_width_percentile", value))
    return factor_frame(rows)


def compute_t11(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    bb_period = int_param(params, "bb_period")
    bb_std = float_param(params, "bb_std")
    kc_period = int_param(params, "kc_period")
    kc_multiplier = float_param(params, "kc_atr_multiplier")
    rows: list[dict[str, object]] = []
    for item in series:
        states = squeeze_states(
            item.highs,
            item.lows,
            item.closes,
            bb_period,
            bb_std,
            kc_period,
            kc_multiplier,
        )
        valid = [state for state in states if state is not None]
        value: float | None = None
        released: bool | None = None
        if valid:
            current = valid[-1]
            released = len(valid) >= 2 and valid[-2] and not current
            days = 0
            if current:
                for state in reversed(valid):
                    if not state:
                        break
                    days += 1
            value = float(days)
        row = factor_row(item.symbol, "T11", "ttm_squeeze", value)
        row["squeeze_released"] = released
        rows.append(row)
    return factor_frame(rows)


def compute_t12(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    segment_days = int_param(params, "segment_days")
    segment_count = int_param(params, "segment_count")
    required = segment_days * segment_count
    rows: list[dict[str, object]] = []
    for item in series:
        value: float | None = None
        ratio: float | None = None
        if item.size >= required:
            ranges: list[float] = []
            start = item.size - required
            for segment in range(segment_count):
                left = start + segment * segment_days
                right = left + segment_days
                close = item.closes[right - 1]
                if close == 0:
                    ranges = []
                    break
                ranges.append(
                    (max(item.highs[left:right]) - min(item.lows[left:right])) / close
                )
            if not ranges:
                rows.append(
                    {
                        **factor_row(item.symbol, "T12", "volatility_contraction", None),
                        "contraction_ratio": None,
                    }
                )
                continue
            value = float(
                all(left > right for left, right in zip(ranges, ranges[1:], strict=False))
            )
            if ranges[0] != 0:
                ratio = ranges[-1] / ranges[0]
        row = factor_row(item.symbol, "T12", "volatility_contraction", value)
        row["contraction_ratio"] = ratio
        rows.append(row)
    return factor_frame(rows)


def compute_t13(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    window = int_param(params, "window")
    rows = []
    for item in series:
        value = None
        if item.size >= window:
            obv_values = obv(item.closes, item.volumes)
            close_window = item.closes[-window:]
            obv_window = obv_values[-window:]
            close_mean = fmean(close_window)
            obv_mean_abs = fmean(abs(entry) for entry in obv_window)
            if close_mean != 0 and obv_mean_abs != 0:
                price_slope = ols(close_window)[0] / close_mean
                obv_slope = ols(obv_window)[0] / obv_mean_abs
                value = obv_slope - price_slope
        rows.append(factor_row(item.symbol, "T13", "obv_divergence", value))
    return factor_frame(rows)


def compute_t14(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    period = int_param(params, "period")
    rows = []
    for item in series:
        value = None
        if item.size >= period:
            money_flow_volume = []
            for high, low, close, volume in zip(
                item.highs[-period:],
                item.lows[-period:],
                item.closes[-period:],
                item.volumes[-period:],
                strict=True,
            ):
                spread = high - low
                multiplier = ((close - low) - (high - close)) / spread if spread != 0 else 0.0
                money_flow_volume.append(multiplier * volume)
            volume_sum = sum(item.volumes[-period:])
            if volume_sum != 0:
                value = sum(money_flow_volume) / volume_sum
        rows.append(factor_row(item.symbol, "T14", "cmf", value))
    return factor_frame(rows)


def compute_t15(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    short_window = int_param(params, "short_window")
    long_window = int_param(params, "long_window")
    rows = []
    for item in series:
        value = None
        if item.size >= long_window:
            long_average = fmean(item.volumes[-long_window:])
            if long_average != 0:
                value = fmean(item.volumes[-short_window:]) / long_average
        rows.append(factor_row(item.symbol, "T15", "volume_dryup_ratio", value))
    return factor_frame(rows)


def compute_t16(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    window = int_param(params, "window")
    rows = []
    for item in series:
        value = None
        if item.size >= max(window, 2):
            average = fmean(item.volumes[-window:])
            if average != 0:
                value = item.volumes[-1] / average if item.closes[-1] > item.closes[-2] else 0.0
        rows.append(factor_row(item.symbol, "T16", "volume_surge", value))
    return factor_frame(rows)


def compute_t17(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    window = int_param(params, "window")
    rows = []
    for item in series:
        value = None
        if item.size > window:
            up_volume = 0.0
            down_volume = 0.0
            for index in range(item.size - window, item.size):
                if item.closes[index] > item.closes[index - 1]:
                    up_volume += item.volumes[index]
                elif item.closes[index] < item.closes[index - 1]:
                    down_volume += item.volumes[index]
            if down_volume != 0:
                value = up_volume / down_volume
        rows.append(factor_row(item.symbol, "T17", "up_down_volume_ratio", value))
    return factor_frame(rows)


def compute_t18(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    window = int_param(params, "window")
    rows = []
    for item in series:
        value = None
        if item.size >= window:
            period_high = max(item.highs[-window:])
            if period_high != 0:
                value = item.closes[-1] / period_high - 1.0
        rows.append(factor_row(item.symbol, "T18", "pct_from_52w_high", value))
    return factor_frame(rows)


def compute_t19(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    lookback = int_param(params, "pivot_lookback")
    pivot_span = int_param(params, "pivot_span")
    min_base_days = int_param(params, "min_base_days")
    max_base_range = float_param(params, "max_base_range")
    atr_period = int_param(params, "atr_period")
    rows: list[dict[str, object]] = []
    for item in series:
        base = find_base(item, lookback, pivot_span, min_base_days, max_base_range, atr_period)
        row = factor_row(
            item.symbol,
            "T19",
            "base_breakout",
            base[0] if base is not None else None,
        )
        row.update(
            base_high=base[1] if base is not None else None,
            base_low=base[2] if base is not None else None,
            base_start_date=base[3] if base is not None else None,
            base_length=base[4] if base is not None else None,
        )
        rows.append(row)
    return factor_frame(rows)


def compute_t20(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    ma_window = int_param(params, "ma_window")
    atr_period = int_param(params, "atr_period")
    rows = []
    for item in series:
        value = None
        latest_atr = last_non_null(wilder_atr(item.highs, item.lows, item.closes, atr_period))
        if item.size >= ma_window and latest_atr not in (None, 0.0):
            value = (item.closes[-1] - fmean(item.closes[-ma_window:])) / latest_atr
        rows.append(factor_row(item.symbol, "T20", "distance_to_ma20_atr", value))
    return factor_frame(rows)


def compute_t21(series: list[PriceSeries], params: Mapping[str, Any]) -> pl.DataFrame:
    lookback = int_param(params, "lookback")
    atr_period = int_param(params, "atr_period")
    threshold_atr = float_param(params, "threshold_atr")
    rows: list[dict[str, object]] = []
    for item in series:
        value: float | None = None
        last_swing_low: float | None = None
        if item.size >= max(lookback, atr_period + 1):
            swings = zigzag_swings(item, lookback, atr_period, threshold_atr)
            highs = [price for kind, price in swings if kind == "high"]
            lows = [price for kind, price in swings if kind == "low"]
            if lows:
                last_swing_low = lows[-1]
            if len(highs) >= 2 and len(lows) >= 2:
                higher_high = highs[-1] > highs[-2]
                higher_low = lows[-1] > lows[-2]
                value = 1.0 if higher_high and higher_low else 0.5 if higher_high else 0.0
        row = factor_row(item.symbol, "T21", "pivot_structure", value)
        row["last_swing_low"] = last_swing_low
        rows.append(row)
    return factor_frame(rows)


def factor_row(symbol: str, factor_id: str, name: str, value: float | None) -> dict[str, object]:
    return {"symbol": symbol, "factor_id": factor_id, "factor_name": name, "raw_value": value}


def factor_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows).with_columns(
        pl.col("symbol").cast(pl.Utf8),
        pl.col("factor_id").cast(pl.Utf8),
        pl.col("factor_name").cast(pl.Utf8),
        pl.col("raw_value").cast(pl.Float64),
    )


def int_param(params: Mapping[str, Any], key: str) -> int:
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value


def float_param(params: Mapping[str, Any], key: str) -> float:
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise ValueError(f"{key} must be a positive number")
    return float(value)


def int_list_param(params: Mapping[str, Any], key: str) -> list[int]:
    value = params[key]
    if not isinstance(value, list) or not value:
        raise ValueError(f"{key} must be a non-empty integer list")
    result = []
    for entry in value:
        if isinstance(entry, bool) or not isinstance(entry, int) or entry <= 0:
            raise ValueError(f"{key} must contain positive integers")
        result.append(entry)
    return result


def float_list_param(params: Mapping[str, Any], key: str) -> list[float]:
    value = params[key]
    if not isinstance(value, list) or not value:
        raise ValueError(f"{key} must be a non-empty number list")
    result = []
    for entry in value:
        if isinstance(entry, bool) or not isinstance(entry, (int, float)):
            raise ValueError(f"{key} must contain numbers")
        result.append(float(entry))
    return result


def ols(values: Sequence[float]) -> tuple[float, float]:
    if len(values) < 2:
        raise ValueError("OLS requires at least two values")
    x_mean = (len(values) - 1) / 2.0
    y_mean = fmean(values)
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
    slope /= denominator
    fitted = [y_mean + slope * (index - x_mean) for index in range(len(values))]
    total = sum((value - y_mean) ** 2 for value in values)
    residual = sum(
        (value - estimate) ** 2 for value, estimate in zip(values, fitted, strict=True)
    )
    r2 = 0.0 if total == 0 else max(0.0, 1.0 - residual / total)
    return slope, r2


def ema(values: Sequence[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    current = fmean(values[:period])
    result[period - 1] = current
    alpha = 2.0 / (period + 1.0)
    for index in range(period, len(values)):
        current = alpha * values[index] + (1.0 - alpha) * current
        result[index] = current
    return result


def ema_optional(values: Sequence[float | None], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    first = next((index for index, value in enumerate(values) if value is not None), None)
    if first is None:
        return result
    available = [float(value) for value in values[first:] if value is not None]
    computed = ema(available, period)
    for offset, value in enumerate(computed, start=first):
        result[offset] = value
    return result


def true_ranges(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> list[float]:
    result = []
    for index, (high, low) in enumerate(zip(highs, lows, strict=True)):
        if index == 0:
            result.append(high - low)
        else:
            result.append(
                max(
                    high - low,
                    abs(high - closes[index - 1]),
                    abs(low - closes[index - 1]),
                )
            )
    return result


def wilder_atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> list[float | None]:
    ranges = true_ranges(highs, lows, closes)
    result: list[float | None] = [None] * len(ranges)
    if len(ranges) < period:
        return result
    current = fmean(ranges[:period])
    result[period - 1] = current
    for index in range(period, len(ranges)):
        current = ((period - 1) * current + ranges[index]) / period
        result[index] = current
    return result


def adx(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> tuple[float | None, float | None, float | None]:
    if len(closes) < period * 2:
        return None, None, None
    ranges = true_ranges(highs, lows, closes)
    plus_dm = [0.0]
    minus_dm = [0.0]
    for index in range(1, len(closes)):
        up = highs[index] - highs[index - 1]
        down = lows[index - 1] - lows[index]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    smooth_tr = sum(ranges[1 : period + 1])
    smooth_plus = sum(plus_dm[1 : period + 1])
    smooth_minus = sum(minus_dm[1 : period + 1])
    dx_values: list[float] = []
    plus_di = 0.0
    minus_di = 0.0
    for index in range(period, len(closes)):
        if index > period:
            smooth_tr = smooth_tr - smooth_tr / period + ranges[index]
            smooth_plus = smooth_plus - smooth_plus / period + plus_dm[index]
            smooth_minus = smooth_minus - smooth_minus / period + minus_dm[index]
        if smooth_tr == 0:
            plus_di = minus_di = 0.0
        else:
            plus_di = 100.0 * smooth_plus / smooth_tr
            minus_di = 100.0 * smooth_minus / smooth_tr
        denominator = plus_di + minus_di
        dx_values.append(0.0 if denominator == 0 else 100.0 * abs(plus_di - minus_di) / denominator)
    if len(dx_values) < period:
        return None, None, None
    current_adx = fmean(dx_values[:period])
    for dx in dx_values[period:]:
        current_adx = ((period - 1) * current_adx + dx) / period
    return current_adx, plus_di, minus_di


def supertrend(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
    multiplier: float,
) -> tuple[float | None, int | None]:
    atr_values = wilder_atr(highs, lows, closes, period)
    start = next((index for index, value in enumerate(atr_values) if value is not None), None)
    if start is None:
        return None, None
    states: list[float] = []
    starting_atr = atr_values[start]
    if starting_atr is None:
        return None, None
    previous_upper = (highs[start] + lows[start]) / 2.0 + multiplier * starting_atr
    previous_lower = (highs[start] + lows[start]) / 2.0 - multiplier * starting_atr
    previous_supertrend = previous_upper
    states.append(-1.0)
    for index in range(start + 1, len(closes)):
        atr_value = atr_values[index]
        if atr_value is None:
            continue
        midpoint = (highs[index] + lows[index]) / 2.0
        basic_upper = midpoint + multiplier * atr_value
        basic_lower = midpoint - multiplier * atr_value
        final_upper = (
            basic_upper
            if basic_upper < previous_upper or closes[index - 1] > previous_upper
            else previous_upper
        )
        final_lower = (
            basic_lower
            if basic_lower > previous_lower or closes[index - 1] < previous_lower
            else previous_lower
        )
        if previous_supertrend == previous_upper:
            current_supertrend = final_upper if closes[index] <= final_upper else final_lower
        else:
            current_supertrend = final_lower if closes[index] >= final_lower else final_upper
        states.append(1.0 if closes[index] > current_supertrend else -1.0)
        previous_upper = final_upper
        previous_lower = final_lower
        previous_supertrend = current_supertrend
    latest = states[-1]
    days = 0
    for state in reversed(states):
        if state != latest:
            break
        days += 1
    return latest, days


def bollinger_widths(
    closes: Sequence[float],
    period: int,
    deviations: float,
) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    for index in range(period - 1, len(closes)):
        window = closes[index - period + 1 : index + 1]
        middle = fmean(window)
        result[index] = None if middle == 0 else 2.0 * deviations * pstdev(window) / middle
    return result


def squeeze_states(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    bb_period: int,
    bb_std: float,
    kc_period: int,
    kc_multiplier: float,
) -> list[bool | None]:
    atr_values = wilder_atr(highs, lows, closes, kc_period)
    kc_middle = ema(closes, kc_period)
    result: list[bool | None] = [None] * len(closes)
    for index in range(max(bb_period, kc_period) - 1, len(closes)):
        atr_value = atr_values[index]
        middle = kc_middle[index]
        if atr_value is None or middle is None:
            continue
        bb_window = closes[index - bb_period + 1 : index + 1]
        bb_middle = fmean(bb_window)
        deviation = pstdev(bb_window)
        upper_bb = bb_middle + bb_std * deviation
        lower_bb = bb_middle - bb_std * deviation
        upper_kc = middle + kc_multiplier * atr_value
        lower_kc = middle - kc_multiplier * atr_value
        result[index] = upper_bb < upper_kc and lower_bb > lower_kc
    return result


def obv(closes: Sequence[float], volumes: Sequence[float]) -> list[float]:
    result = [0.0]
    for index in range(1, len(closes)):
        change = volumes[index] if closes[index] > closes[index - 1] else -volumes[index]
        if closes[index] == closes[index - 1]:
            change = 0.0
        result.append(result[-1] + change)
    return result


def find_base(
    item: PriceSeries,
    lookback: int,
    pivot_span: int,
    min_base_days: int,
    max_base_range: float,
    atr_period: int,
) -> tuple[float, float, float, date, int] | None:
    if item.size < max(lookback, atr_period):
        return None
    latest_atr = last_non_null(wilder_atr(item.highs, item.lows, item.closes, atr_period))
    if latest_atr in (None, 0.0):
        return None
    first = item.size - lookback
    last_pivot = item.size - min_base_days
    for pivot in range(last_pivot, first + pivot_span - 1, -1):
        if pivot < pivot_span or pivot + pivot_span >= item.size:
            continue
        pivot_high = item.highs[pivot]
        neighbors = (
            item.highs[pivot - pivot_span : pivot]
            + item.highs[pivot + 1 : pivot + pivot_span + 1]
        )
        if not all(pivot_high > value for value in neighbors):
            continue
        base_low = min(item.lows[pivot:])
        if pivot_high == 0 or (pivot_high - base_low) / pivot_high > max_base_range:
            continue
        base_length = item.size - pivot
        value = (item.closes[-1] - pivot_high) / latest_atr
        return value, pivot_high, base_low, item.dates[pivot], base_length
    return None


def zigzag_swings(
    item: PriceSeries,
    lookback: int,
    atr_period: int,
    threshold_atr: float,
) -> list[tuple[str, float]]:
    start = item.size - lookback
    atr_values = wilder_atr(item.highs, item.lows, item.closes, atr_period)
    direction = 0
    extreme_high = item.highs[start]
    extreme_low = item.lows[start]
    swings: list[tuple[str, float]] = []
    for index in range(start + 1, item.size):
        atr_value = atr_values[index]
        if atr_value is None:
            continue
        threshold = threshold_atr * atr_value
        if direction == 0:
            extreme_high = max(extreme_high, item.highs[index])
            extreme_low = min(extreme_low, item.lows[index])
            if item.highs[index] - extreme_low >= threshold:
                swings.append(("low", extreme_low))
                direction = 1
                extreme_high = item.highs[index]
            elif extreme_high - item.lows[index] >= threshold:
                swings.append(("high", extreme_high))
                direction = -1
                extreme_low = item.lows[index]
        elif direction > 0:
            if item.highs[index] > extreme_high:
                extreme_high = item.highs[index]
            elif extreme_high - item.lows[index] >= threshold:
                swings.append(("high", extreme_high))
                direction = -1
                extreme_low = item.lows[index]
        else:
            if item.lows[index] < extreme_low:
                extreme_low = item.lows[index]
            elif item.highs[index] - extreme_low >= threshold:
                swings.append(("low", extreme_low))
                direction = 1
                extreme_high = item.highs[index]
    return swings


def cross_sectional_percentiles(values: Mapping[str, float]) -> dict[str, float]:
    return {symbol: percentile(value, list(values.values())) for symbol, value in values.items()}


def percentile(value: float, values: Sequence[float]) -> float:
    if len(values) <= 1:
        return 0.5
    less = sum(entry < value for entry in values)
    equal = sum(entry == value for entry in values)
    average_zero_based_rank = less + (equal - 1) / 2.0
    return average_zero_based_rank / (len(values) - 1)


def percentile_of_last(values: Sequence[float] | None) -> float | None:
    return None if values is None else percentile(values[-1], values)


def trailing_non_null(
    values: Sequence[float | None],
    count: int,
) -> list[float] | None:
    if len(values) < count:
        return None
    trailing = values[-count:]
    if any(value is None for value in trailing):
        return None
    return [float(value) for value in trailing if value is not None]


def last_non_null(values: Sequence[float | None]) -> float | None:
    return next((value for value in reversed(values) if value is not None), None)


def expect_date(value: object, column: str) -> date:
    if isinstance(value, date):
        return value
    raise TypeError(f"{column} must contain date values")


TECHNICAL_FACTORS: dict[str, FactorDefinition] = {
    "T01": FactorDefinition("T01", "ma_alignment_score", 1, 120, compute_t01),
    "T02": FactorDefinition("T02", "linreg_slope_r2", 1, 60, compute_t02),
    "T03": FactorDefinition("T03", "adx", 1, 28, compute_t03),
    "T04": FactorDefinition("T04", "supertrend_state", 1, 10, compute_t04),
    "T05": FactorDefinition("T05", "relative_strength_pct", 1, 121, compute_t05),
    "T06": FactorDefinition("T06", "mansfield_rsi", 1, 252, compute_t06),
    "T07": FactorDefinition("T07", "macd_histogram_slope", 1, 35, compute_t07),
    "T08": FactorDefinition("T08", "roc_rank_composite", 1, 121, compute_t08),
    "T09": FactorDefinition("T09", "atr_percent", 0, 14, compute_t09),
    "T10": FactorDefinition("T10", "bb_width_percentile", -1, 269, compute_t10),
    "T11": FactorDefinition("T11", "ttm_squeeze", 1, 20, compute_t11),
    "T12": FactorDefinition("T12", "volatility_contraction", 1, 60, compute_t12),
    "T13": FactorDefinition("T13", "obv_divergence", 1, 20, compute_t13),
    "T14": FactorDefinition("T14", "cmf", 1, 20, compute_t14),
    "T15": FactorDefinition("T15", "volume_dryup_ratio", -1, 20, compute_t15),
    "T16": FactorDefinition("T16", "volume_surge", 1, 20, compute_t16),
    "T17": FactorDefinition("T17", "up_down_volume_ratio", 1, 51, compute_t17),
    "T18": FactorDefinition("T18", "pct_from_52w_high", 1, 250, compute_t18),
    "T19": FactorDefinition("T19", "base_breakout", 1, 60, compute_t19),
    "T20": FactorDefinition("T20", "distance_to_ma20_atr", 0, 20, compute_t20),
    "T21": FactorDefinition("T21", "pivot_structure", 1, 90, compute_t21),
}
