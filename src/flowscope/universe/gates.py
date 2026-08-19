from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import polars as pl

from flowscope.config.schema import L0GateConfig, L1GateConfig
from flowscope.data.calendar import TradingCalendar

MARKET_VALUE_UNIT_SCALE = 1.0
TWSE_NONMANUFACTURING_INDUSTRY_CODES = frozenset(
    {
        "14",  # 建材營造
        "15",  # 航運
        "16",  # 觀光餐旅
        "17",  # 金融保險
        "18",  # 貿易百貨
        "20",  # 其他
        "23",  # 油電燃氣
        "29",  # 電子通路
        "30",  # 資訊服務
        "32",  # 文化創意
        "34",  # 電子商務
        "36",  # 數位雲端
        "37",  # 運動休閒
        "38",  # 居家生活
    }
)
TPEX_NONMANUFACTURING_INDUSTRY_CODES = frozenset(
    {
        "14",  # 建材營造
        "15",  # 航運
        "16",  # 觀光餐旅
        "17",  # 金融保險
        "18",  # 貿易百貨
        "20",  # 其他
        "23",  # 油電燃氣
        "29",  # 電子通路
        "30",  # 資訊服務
        "32",  # 文化創意
        "34",  # 電子商務
        "36",  # 數位雲端
        "37",  # 運動休閒
        "38",  # 居家生活
    }
)
NONMANUFACTURING_TEXT_MARKERS = frozenset(
    {
        "金融",
        "保險",
        "證券",
        "期貨",
        "建材",
        "營造",
        "航運",
        "觀光",
        "餐旅",
        "貿易",
        "百貨",
        "油電",
        "燃氣",
        "電子通路",
        "資訊服務",
        "文化創意",
        "電子商務",
        "數位雲端",
        "運動休閒",
        "居家生活",
    }
)
FINANCIAL_TYPE_ALIASES = {
    "CurrentAssets": "current_assets",
    "TotalAssets": "total_assets",
    "CurrentLiabilities": "current_liabilities",
    "Liabilities": "total_liabilities",
    "RetainedEarnings": "retained_earnings",
    "OperatingIncome": "operating_income",
    "Revenue": "revenue",
    "CashFlowsFromOperatingActivities": "operating_cash_flow",
    "NetCashInflowFromOperatingActivities": "operating_cash_flow",
}


class UniverseGateError(RuntimeError):
    """Raised when universe gates cannot be evaluated with trustworthy data."""


@dataclass(frozen=True)
class GateStep:
    name: str
    before: int
    after: int

    @property
    def removed(self) -> int:
        return self.before - self.after


@dataclass(frozen=True)
class GateApplication:
    frame: pl.DataFrame
    steps: tuple[GateStep, ...]


def apply_l0_gates(
    listings: pl.DataFrame,
    prices: pl.DataFrame,
    calendar: TradingCalendar,
    as_of: date,
    config: L0GateConfig,
) -> GateApplication:
    ensure_columns(
        listings,
        {
            "symbol",
            "market",
            "industry",
            "listing_date",
            "delisting_date",
            "security_type",
        },
        "listings",
    )
    ensure_columns(prices, {"symbol", "data_date", "close", "amount"}, "prices")

    latest_trade_date = calendar.on_or_before(as_of)
    trailing_dates = calendar.trailing_dates(latest_trade_date, 20)
    if len(trailing_dates) < 20:
        raise UniverseGateError("Trading calendar does not cover 20 trailing trading days")

    active = (
        listings.filter(
            (pl.col("listing_date") <= as_of)
            & (pl.col("delisting_date").is_null() | (pl.col("delisting_date") > as_of))
        )
        .unique(subset=["symbol"], keep="first")
        .sort("symbol")
    )
    metrics = price_metrics(prices, trailing_dates, latest_trade_date)
    frame = active.join(metrics, on="symbol", how="left").with_columns(
        pl.Series(
            "listing_trading_days",
            [listing_trading_days(row, calendar, as_of) for row in active.iter_rows(named=True)],
            dtype=pl.Int64,
        )
    )

    steps: list[GateStep] = []
    frame = apply_filter(
        frame,
        "L0 avg_20d_dollar_volume",
        pl.col("avg_20d_dollar_volume") >= config.min_avg_dollar_volume,
        steps,
    )
    frame = apply_filter(frame, "L0 close", pl.col("latest_close") >= config.min_price, steps)
    frame = apply_filter(
        frame,
        "L0 listing_days",
        pl.col("listing_trading_days") >= config.min_listing_days,
        steps,
    )
    frame = apply_filter(
        frame,
        "L0 trading_day_ratio",
        pl.col("trading_day_ratio_20d") >= config.min_trading_day_ratio,
        steps,
    )
    frame = apply_filter(
        frame,
        "L0 security_type",
        ~pl.col("security_type").is_in(config.exclude_types),
        steps,
    )
    frame = apply_filter(
        frame,
        "L0 market",
        ~pl.col("market").is_in(config.exclude_markets),
        steps,
    )
    return GateApplication(frame=frame.sort("symbol"), steps=tuple(steps))


def apply_l1_gates(
    universe: pl.DataFrame,
    warnings: pl.DataFrame,
    financials: pl.DataFrame,
    market_values: pl.DataFrame,
    config: L1GateConfig,
) -> GateApplication:
    ensure_columns(universe, {"symbol", "market", "industry"}, "universe")
    ensure_columns(warnings, {"symbol", "warning_type"}, "warnings")
    ensure_columns(market_values, {"symbol", "market_value"}, "market_values")

    warning_symbols = warnings.select("symbol").unique()
    market_latest = (
        market_values.sort(["symbol", "data_date"])
        .group_by("symbol")
        .tail(1)
        .select(
            "symbol",
            # Step 4 L1 財務已改用 FinMind long format；財報與市值皆為元級。
            (pl.col("market_value") / MARKET_VALUE_UNIT_SCALE).alias("market_value_statement_unit"),
        )
    )
    warning_flags = warning_symbols.with_columns(pl.lit(True).alias("is_warning_symbol"))
    frame = (
        universe.join(warning_flags, on="symbol", how="left")
        .with_columns(pl.col("is_warning_symbol").fill_null(False))
        .join(latest_financials(financials), on="symbol", how="left")
        .join(market_latest, on="symbol", how="left")
    )
    frame = with_altman_z(frame, config)
    frame = with_optional_l1_fields(frame, config)

    steps: list[GateStep] = []
    frame = apply_filter(
        frame,
        "L1 warning_disposition_full_delivery",
        ~pl.col("is_warning_symbol"),
        steps,
    )
    frame = apply_filter(
        frame,
        "L1 altman_z",
        pl.col("altman_z").is_null() | (pl.col("altman_z") >= pl.col("altman_z_threshold")),
        steps,
    )
    if has_non_null_values(frame, "negative_ocf_quarters"):
        frame = apply_filter(
            frame,
            "L1 negative_ocf",
            pl.col("negative_ocf_quarters") <= config.max_negative_ocf_quarters,
            steps,
        )
    if has_non_null_values(frame, "capital_raise_pct"):
        frame = apply_filter(
            frame,
            "L1 capital_raise",
            pl.col("capital_raise_pct") <= config.max_capital_raise_pct,
            steps,
        )
    return GateApplication(frame=frame.sort("symbol"), steps=tuple(steps))


def price_metrics(
    prices: pl.DataFrame,
    trailing_dates: tuple[date, ...],
    latest_trade_date: date,
) -> pl.DataFrame:
    trailing = prices.filter(pl.col("data_date").is_in(trailing_dates))
    if trailing.is_empty():
        raise UniverseGateError("Price history returned no rows for trailing L0 window")
    latest = (
        prices.filter(pl.col("data_date") == latest_trade_date)
        .select("symbol", pl.col("close").alias("latest_close"))
        .unique(subset=["symbol"], keep="last")
    )
    return (
        trailing.group_by("symbol")
        .agg(
            pl.col("amount").mean().alias("avg_20d_dollar_volume"),
            pl.col("data_date").n_unique().alias("trading_days_with_price_20d"),
        )
        .with_columns(
            (pl.col("trading_days_with_price_20d") / len(trailing_dates)).alias(
                "trading_day_ratio_20d"
            )
        )
        .join(latest, on="symbol", how="left")
    )


def latest_financials(financials: pl.DataFrame) -> pl.DataFrame:
    if financials.is_empty():
        return empty_latest_financials()
    ensure_columns(
        financials,
        {"symbol", "data_date", "publish_date", "type", "value"},
        "financials",
    )
    normalized = normalize_financial_long_frame(financials)
    if normalized.is_empty():
        return empty_latest_financials()
    latest_columns_to_drop = (
        ["operating_cash_flow"] if "operating_cash_flow" in normalized.columns else []
    )
    latest = (
        normalized.sort(["symbol", "publish_date", "data_date"])
        .group_by("symbol")
        .tail(1)
        .drop(latest_columns_to_drop)
    )
    negative_ocf = negative_ocf_quarters(normalized)
    return latest.join(negative_ocf, on="symbol", how="left")


def empty_latest_financials() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "symbol": pl.Utf8,
            "publish_date": pl.Date,
            "current_assets": pl.Float64,
            "total_assets": pl.Float64,
            "current_liabilities": pl.Float64,
            "total_liabilities": pl.Float64,
            "retained_earnings": pl.Float64,
            "operating_income": pl.Float64,
            "revenue": pl.Float64,
            "negative_ocf_quarters": pl.Int64,
        }
    )


def with_altman_z(frame: pl.DataFrame, config: L1GateConfig) -> pl.DataFrame:
    for column in (
        "current_assets",
        "total_assets",
        "current_liabilities",
        "total_liabilities",
        "retained_earnings",
        "operating_income",
        "revenue",
        "market_value_statement_unit",
    ):
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias(column))

    is_nonmanufacturing = pl.struct(["market", "industry"]).map_elements(
        lambda row: is_nonmanufacturing_industry(str(row["market"]), str(row["industry"])),
        return_dtype=pl.Boolean,
    )
    x1 = (pl.col("current_assets") - pl.col("current_liabilities")) / pl.col("total_assets")
    x2 = pl.col("retained_earnings") / pl.col("total_assets")
    x3 = pl.col("operating_income") / pl.col("total_assets")
    x4 = pl.col("market_value_statement_unit") / pl.col("total_liabilities")
    x5 = pl.col("revenue") / pl.col("total_assets")
    has_altman_inputs = (
        pl.col("total_assets").is_not_null()
        & (pl.col("total_assets") > 0)
        & pl.col("total_liabilities").is_not_null()
        & (pl.col("total_liabilities") > 0)
        & pl.col("current_assets").is_not_null()
        & pl.col("current_liabilities").is_not_null()
        & pl.col("retained_earnings").is_not_null()
        & pl.col("operating_income").is_not_null()
        & pl.col("market_value_statement_unit").is_not_null()
    )
    manufacturing_score = (1.2 * x1) + (1.4 * x2) + (3.3 * x3) + (0.6 * x4) + x5
    nonmanufacturing_score = (6.56 * x1) + (3.26 * x2) + (6.72 * x3) + (1.05 * x4)
    return frame.with_columns(
        is_nonmanufacturing.alias("is_nonmanufacturing"),
        pl.when(has_altman_inputs & (~is_nonmanufacturing) & pl.col("revenue").is_not_null())
        .then(manufacturing_score)
        .when(has_altman_inputs & is_nonmanufacturing)
        .then(nonmanufacturing_score)
        .otherwise(None)
        .alias("altman_z"),
        pl.when(is_nonmanufacturing)
        .then(pl.lit(config.altman_z_min_nonmfg))
        .otherwise(pl.lit(config.altman_z_min))
        .alias("altman_z_threshold"),
    ).with_columns(pl.col("altman_z").is_null().alias("altman_z_unavailable"))


def with_optional_l1_fields(frame: pl.DataFrame, config: L1GateConfig) -> pl.DataFrame:
    if "negative_ocf_quarters" not in frame.columns:
        frame = frame.with_columns(pl.lit(None, dtype=pl.Int64).alias("negative_ocf_quarters"))
    if "capital_raise_pct" not in frame.columns:
        frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("capital_raise_pct"))
    # Beneish M 需要跨期輸入；Step 4 僅揭露缺資料狀態，不以 0 取代。
    if "beneish_m_score" not in frame.columns:
        frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("beneish_m_score"))
    return frame.with_columns(
        pl.col("beneish_m_score").is_null().alias("beneish_m_unavailable"),
        (
            pl.col("beneish_m_score").is_not_null()
            & (pl.col("beneish_m_score") > config.beneish_m_flag)
        ).alias("beneish_m_flagged"),
    )


def normalize_financial_long_frame(financials: pl.DataFrame) -> pl.DataFrame:
    records: list[dict[str, object]] = []
    for row in financials.iter_rows(named=True):
        alias = FINANCIAL_TYPE_ALIASES.get(str(row["type"]))
        if alias is None:
            continue
        data_date = row["data_date"]
        publish_date = row["publish_date"]
        if not isinstance(data_date, date) or not isinstance(publish_date, date):
            raise UniverseGateError("financials data_date/publish_date must contain date values")
        records.append(
            {
                "symbol": str(row["symbol"]),
                "data_date": data_date,
                "publish_date": publish_date,
                "field": alias,
                "value": float(row["value"]),
            }
        )
    if not records:
        return empty_normalized_financials()
    return (
        pl.DataFrame(records)
        .pivot(
            index=["symbol", "data_date", "publish_date"],
            on="field",
            values="value",
            aggregate_function="first",
        )
        .sort(["symbol", "data_date"])
    )


def empty_normalized_financials() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "symbol": pl.Utf8,
            "data_date": pl.Date,
            "publish_date": pl.Date,
            "current_assets": pl.Float64,
            "total_assets": pl.Float64,
            "current_liabilities": pl.Float64,
            "total_liabilities": pl.Float64,
            "retained_earnings": pl.Float64,
            "operating_income": pl.Float64,
            "revenue": pl.Float64,
            "operating_cash_flow": pl.Float64,
        }
    )


def negative_ocf_quarters(financials: pl.DataFrame) -> pl.DataFrame:
    if "operating_cash_flow" not in financials.columns:
        return pl.DataFrame(schema={"symbol": pl.Utf8, "negative_ocf_quarters": pl.Int64})
    records: list[dict[str, object]] = []
    for (symbol,), group in financials.sort(["symbol", "data_date"]).group_by("symbol"):
        count = 0
        rows = list(group.iter_rows(named=True))
        for row in reversed(rows):
            value = row.get("operating_cash_flow")
            if value is None:
                continue
            if float(value) < 0:
                count += 1
                continue
            break
        records.append({"symbol": str(symbol), "negative_ocf_quarters": count})
    return pl.DataFrame(records, schema={"symbol": pl.Utf8, "negative_ocf_quarters": pl.Int64})


def apply_filter(
    frame: pl.DataFrame,
    name: str,
    predicate: pl.Expr,
    steps: list[GateStep],
) -> pl.DataFrame:
    before = frame.height
    filtered = frame.filter(predicate).sort("symbol")
    steps.append(GateStep(name=name, before=before, after=filtered.height))
    return filtered


def listing_trading_days(row: dict[str, Any], calendar: TradingCalendar, as_of: date) -> int:
    listing_date = row["listing_date"]
    if not isinstance(listing_date, date):
        raise UniverseGateError("listing_date must contain date values")
    return calendar.count_between(listing_date, as_of)


def is_nonmanufacturing_industry(market: str, industry: str) -> bool:
    code = industry.strip().zfill(2) if industry.strip().isdigit() else industry.strip()
    if market == "TWSE" and code in TWSE_NONMANUFACTURING_INDUSTRY_CODES:
        return True
    if market == "TPEX" and code in TPEX_NONMANUFACTURING_INDUSTRY_CODES:
        return True
    return any(marker in industry for marker in NONMANUFACTURING_TEXT_MARKERS)


def has_non_null_values(frame: pl.DataFrame, column: str) -> bool:
    return column in frame.columns and frame.select(pl.col(column).is_not_null().any()).item()


def ensure_columns(frame: pl.DataFrame, columns: set[str], label: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        joined = ", ".join(missing)
        raise UniverseGateError(f"{label} missing required columns: {joined}")
