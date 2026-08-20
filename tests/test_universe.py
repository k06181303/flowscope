from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from flowscope.config.loader import load_config
from flowscope.config.schema import L0GateConfig, L1GateConfig
from flowscope.data.calendar import TradingCalendar
from flowscope.universe.builder import UniverseFunnel, build_universe_funnel, render_funnel
from flowscope.universe.gates import (
    GateApplication,
    GateStep,
    UniverseGateError,
    apply_l0_gates,
    apply_l1_gates,
    is_nonmanufacturing_industry,
    latest_financials,
)


def test_l0_gates_are_applied_in_spec_order() -> None:
    calendar = TradingCalendar(
        tuple(date(2024, 1, 1) + timedelta(days=index) for index in range(20))
    )
    listings = pl.DataFrame(
        [
            listing("A", "TWSE", "COMMON_STOCK", date(2024, 1, 1)),
            listing("B", "TWSE", "COMMON_STOCK", date(2024, 1, 1)),
            listing("C", "TWSE", "COMMON_STOCK", date(2024, 1, 15)),
            listing("D", "TWSE", "COMMON_STOCK", date(2024, 1, 1)),
            listing("E", "TWSE", "COMMON_STOCK", date(2024, 1, 1)),
            listing("F", "TWSE", "ETF", date(2024, 1, 1)),
            listing("G", "EMERGING", "COMMON_STOCK", date(2024, 1, 1)),
        ]
    )
    prices = pl.DataFrame(
        price_rows("A", calendar.dates, 20.0, 200.0)
        + price_rows("B", calendar.dates, 20.0, 50.0)
        + price_rows("C", calendar.dates, 20.0, 200.0)
        + price_rows("D", calendar.dates[1:], 20.0, 200.0)
        + price_rows("E", calendar.dates, 5.0, 200.0)
        + price_rows("F", calendar.dates, 20.0, 200.0)
        + price_rows("G", calendar.dates, 20.0, 200.0)
    )
    config = L0GateConfig(
        min_avg_dollar_volume=100.0,
        min_price=10.0,
        min_listing_days=10,
        min_trading_day_ratio=1.0,
        exclude_types=["ETF"],
        exclude_markets=["EMERGING"],
    )

    result = apply_l0_gates(listings, prices, calendar, date(2024, 1, 20), config)

    assert [(step.name, step.before, step.after) for step in result.steps] == [
        ("L0 avg_20d_dollar_volume", 7, 6),
        ("L0 close", 6, 5),
        ("L0 listing_days", 5, 4),
        ("L0 trading_day_ratio", 4, 3),
        ("L0 security_type", 3, 2),
        ("L0 market", 2, 1),
    ]
    assert result.frame["symbol"].to_list() == ["A"]


def test_l1_altman_uses_manufacturing_and_nonmanufacturing_models() -> None:
    l1 = apply_l1_gates(
        pl.DataFrame(
            [
                listing("FIN", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="17"),
                listing("MFG", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24"),
                listing("BAD", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24"),
                listing("WARN", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24"),
            ]
        ),
        pl.DataFrame(
            [
                {
                    "symbol": "WARN",
                    "warning_type": "disposition",
                    "data_date": date(2024, 1, 20),
                    "publish_date": date(2024, 1, 20),
                }
            ]
        ),
        financial_rows(),
        market_values(),
        l1_config(),
    )

    assert [(step.name, step.before, step.after) for step in l1.steps] == [
        ("L1 warning_disposition_full_delivery", 4, 3),
        ("L1 altman_z", 3, 2),
        ("L1 negative_ocf", 2, 2),
        ("L1 capital_raise", 2, 2),
    ]
    scores = dict(l1.frame.select("symbol", "altman_z").rows())
    # MFG: 1.2*0.1 + 1.4*0.3 + 3.3*0.1 + 0.6*2.5 + 1.0*0.5 = 2.87
    assert scores["MFG"] == pytest.approx(2.87)
    # FIN: 6.56*0.7 + 3.26*0.1 + 6.72*0.05 + 1.05*1.0 = 6.304
    assert scores["FIN"] == pytest.approx(6.304)


def test_l1_nonmanufacturing_industry_codes_cover_twse_and_tpex_tables() -> None:
    codes = ("14", "15", "16", "17", "18", "20", "23", "29", "30", "32", "34", "36", "37", "38")
    for code in codes:
        assert is_nonmanufacturing_industry("TWSE", code)
        assert is_nonmanufacturing_industry("TPEX", code)
    assert not is_nonmanufacturing_industry("TWSE", "24")
    assert not is_nonmanufacturing_industry("TPEX", "24")


def test_l1_negative_ocf_converts_positive_cumulative_values_to_negative_quarters() -> None:
    financials = pl.DataFrame(
        financial_records("HEALTHY")
        + financial_records("BURN", operating_cash_flows=(500.0, 400.0, 300.0, 200.0))
    )
    counts = dict(
        latest_financials(financials).select("symbol", "negative_ocf_quarters").rows()
    )
    # 獨立手算:500, 400-500, 300-400, 200-300 = 500, -100, -100, -100。
    assert counts["BURN"] == 3

    l1 = apply_l1_gates(
        pl.DataFrame(
            [
                listing("HEALTHY", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24"),
                listing("BURN", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24"),
            ]
        ),
        empty_warnings(),
        financials,
        pl.DataFrame(
            [
                {"symbol": "HEALTHY", "data_date": date(2024, 1, 20), "market_value": 2000.0},
                {"symbol": "BURN", "data_date": date(2024, 1, 20), "market_value": 2000.0},
            ]
        ),
        l1_config(),
    )

    assert [(step.name, step.before, step.after) for step in l1.steps] == [
        ("L1 warning_disposition_full_delivery", 2, 2),
        ("L1 altman_z", 2, 2),
        ("L1 negative_ocf", 2, 1),
        ("L1 capital_raise", 1, 1),
    ]
    assert l1.steps[-1].skipped_reason == "no data"
    assert l1.frame["symbol"].to_list() == ["HEALTHY"]


def test_l1_negative_ocf_detects_latest_positive_quarter_from_negative_cumulative() -> None:
    financials = pl.DataFrame(
        financial_records(
            "RECOVERED",
            operating_cash_flows=(-100.0, -200.0, -300.0, -295.0),
        )
    )

    row = latest_financials(financials).row(0, named=True)

    # 獨立手算:-100, -100, -100, +5；最新一季已轉正，所以連續負季數為 0。
    assert row["negative_ocf_quarters"] == 0


def test_l1_negative_ocf_streak_crosses_fiscal_year_after_yearly_differencing() -> None:
    financials = pl.DataFrame(
        financial_records(
            "YEAR_BOUNDARY",
            periods=(
                date(2024, 3, 31),
                date(2024, 6, 30),
                date(2024, 9, 30),
                date(2024, 12, 31),
                date(2025, 3, 31),
                date(2025, 6, 30),
            ),
            operating_cash_flows=(-10.0, -20.0, -30.0, -40.0, -5.0, -15.0),
        )
    )

    row = latest_financials(financials).row(0, named=True)

    # 獨立手算:2024 單季均 -10；2025Q1=-5、Q2=-15-(-5)=-10，共連續 6 季。
    assert row["negative_ocf_quarters"] == 6


def test_l1_negative_ocf_q1_keeps_previous_year_streak() -> None:
    financials = pl.DataFrame(
        financial_records(
            "Q1_AS_OF",
            periods=(
                date(2024, 3, 31),
                date(2024, 6, 30),
                date(2024, 9, 30),
                date(2024, 12, 31),
                date(2025, 3, 31),
            ),
            operating_cash_flows=(-10.0, -20.0, -30.0, -40.0, -5.0),
        )
    )

    row = latest_financials(financials).row(0, named=True)

    # 獨立手算:前一年四個單季均 -10，2025Q1=-5；Q1 as_of 應保留跨年連續 5 季。
    assert row["negative_ocf_quarters"] == 5


def test_l1_altman_uses_four_quarter_ttm_and_rejects_short_history() -> None:
    full = pl.DataFrame(
        financial_records(
            "TTM",
            quarterly_operating_incomes=(10.0, 20.0, 30.0, 40.0),
            quarterly_revenues=(100.0, 200.0, 300.0, 400.0),
        )
    )
    short = full.filter(pl.col("data_date") > date(2024, 3, 31)).with_columns(
        pl.lit("SHORT").alias("symbol")
    )
    latest = latest_financials(pl.concat([full, short]))
    rows = {row["symbol"]: row for row in latest.iter_rows(named=True)}

    # 獨立手算:EBIT TTM=10+20+30+40=100；Sales TTM=100+200+300+400=1,000。
    assert rows["TTM"]["operating_income_ttm"] == pytest.approx(100.0)
    assert rows["TTM"]["revenue_ttm"] == pytest.approx(1000.0)
    assert rows["SHORT"]["operating_income_ttm"] is None
    assert rows["SHORT"]["revenue_ttm"] is None


def test_l1_beneish_missing_is_flagged_not_zero() -> None:
    l1 = apply_l1_gates(
        pl.DataFrame([listing("MFG", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24")]),
        empty_warnings(),
        financial_rows().filter(pl.col("symbol") == "MFG"),
        market_values().filter(pl.col("symbol") == "MFG"),
        l1_config(),
    )

    row = l1.frame.row(0, named=True)
    assert row["beneish_m_score"] is None
    assert row["beneish_m_unavailable"] is True
    assert row["beneish_m_flagged"] is False


def test_l1_gates_disclose_skipped_when_optional_source_has_no_data() -> None:
    financials = financial_rows().filter(pl.col("statement") != "cash_flow")

    l1 = apply_l1_gates(
        pl.DataFrame(
            [listing("MFG", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24")]
        ),
        empty_warnings(),
        financials.filter(pl.col("symbol") == "MFG"),
        market_values().filter(pl.col("symbol") == "MFG"),
        l1_config(),
    )

    assert [(step.name, step.skipped_reason) for step in l1.steps[-2:]] == [
        ("L1 negative_ocf", "no data"),
        ("L1 capital_raise", "no data"),
    ]


def test_render_funnel_matches_spec_shape() -> None:
    funnel = UniverseFunnel(
        as_of=date(2024, 8, 18),
        price_as_of=date(2024, 8, 16),
        warnings_snapshot=date(2024, 8, 18),
        market="TW",
        initial_count=1812,
        l0=GateApplication(pl.DataFrame({"symbol": ["A"] * 672}), (GateStep("L0", 1812, 672),)),
        l1=GateApplication(pl.DataFrame({"symbol": ["A"] * 589}), (GateStep("L1", 672, 589),)),
        top_n=30,
    )

    assert render_funnel(funnel).splitlines() == [
        "Universe funnel (as_of=2024-08-18, price_as_of=2024-08-16, "
        "warnings_snapshot=2024-08-18, market=TW)",
        "  全市場上市櫃              1,812",
        "  L0 流動性             △  1,140  ->    672",
        "  L1 排雷              △     83  ->    589",
        "  資料完整度 >= 門檻        △      0  ->    589",
        "  評分後 Top N                      ->     30",
    ]


def test_render_funnel_discloses_gate_skipped_for_no_data() -> None:
    funnel = UniverseFunnel(
        as_of=date(2024, 8, 18),
        price_as_of=date(2024, 8, 16),
        warnings_snapshot=date(2024, 8, 18),
        market="TW",
        initial_count=1,
        l0=GateApplication(pl.DataFrame({"symbol": ["A"]}), ()),
        l1=GateApplication(
            pl.DataFrame({"symbol": ["A"]}),
            (GateStep("L1 capital_raise", 1, 1, skipped_reason="no data"),),
        ),
        top_n=1,
    )

    assert render_funnel(funnel).splitlines()[-1].strip() == (
        "L1 capital_raise               skipped (no data)"
    )


def test_builder_fetches_exact_trailing_20_trading_days_for_l0() -> None:
    config = load_config(Path("configs/tw_swing.yaml"))
    as_of = date(2025, 5, 15)
    price_as_of = date(2025, 5, 14)
    warnings_snapshot = date(2025, 5, 15)
    calendar = TradingCalendar(
        tuple(date(2024, 1, 1) + timedelta(days=index) for index in range(501))
    )
    data_provider = StaticPriceProvider(calendar)

    market_provider = StaticMarketProvider()
    funnel = build_universe_funnel(
        config,
        as_of,
        data_provider,
        market_provider,
        price_as_of=price_as_of,
        warnings_snapshot=warnings_snapshot,
    )

    assert data_provider.price_request == (
        calendar.trailing_dates(price_as_of, 20)[0],
        price_as_of,
    )
    assert data_provider.financial_request is not None
    assert data_provider.financial_request[1] == as_of
    assert market_provider.warning_request == warnings_snapshot
    assert market_provider.listing_request == price_as_of
    assert funnel.price_as_of == price_as_of
    assert funnel.warnings_snapshot == warnings_snapshot
    assert funnel.initial_count == 1
    assert funnel.l0.frame.height == 1
    assert funnel.l1.frame.height == 1


def test_builder_rejects_price_cutoff_after_data_cutoff() -> None:
    config = load_config(Path("configs/tw_swing.yaml"))
    calendar = TradingCalendar(
        tuple(date(2024, 1, 1) + timedelta(days=index) for index in range(501))
    )

    with pytest.raises(UniverseGateError, match="price_as_of=2025-05-16"):
        build_universe_funnel(
            config,
            date(2025, 5, 15),
            StaticPriceProvider(calendar),
            StaticMarketProvider(),
            price_as_of=date(2025, 5, 16),
        )


def test_builder_rejects_warning_snapshot_after_data_cutoff() -> None:
    config = load_config(Path("configs/tw_swing.yaml"))
    calendar = TradingCalendar(
        tuple(date(2024, 1, 1) + timedelta(days=index) for index in range(501))
    )

    with pytest.raises(UniverseGateError, match="warnings_snapshot=2025-05-16"):
        build_universe_funnel(
            config,
            date(2025, 5, 15),
            StaticPriceProvider(calendar),
            StaticMarketProvider(),
            warnings_snapshot=date(2025, 5, 16),
        )


def listing(
    symbol: str,
    market: str,
    security_type: str,
    listing_date: date,
    *,
    industry: str = "24",
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "market": market,
        "industry": industry,
        "listing_date": listing_date,
        "delisting_date": None,
        "security_type": security_type,
    }


def price_rows(
    symbol: str,
    days: tuple[date, ...],
    close: float,
    amount: float,
) -> list[dict[str, object]]:
    return [
        {
            "symbol": symbol,
            "data_date": day,
            "publish_date": day,
            "close": close,
            "amount": amount,
        }
        for day in days
    ]


def financial_rows() -> pl.DataFrame:
    return pl.DataFrame(
        financial_records("MFG")
        + financial_records(
            "FIN",
            current_assets=800.0,
            total_assets=1000.0,
            current_liabilities=100.0,
            total_liabilities=500.0,
            retained_earnings=100.0,
            operating_income=50.0,
            revenue=None,
        )
        + financial_records(
            "BAD",
            current_assets=100.0,
            total_assets=2000.0,
            current_liabilities=100.0,
            total_liabilities=1800.0,
            retained_earnings=0.0,
            operating_income=-100.0,
            revenue=100.0,
        )
        + financial_records("WARN")
    )


def financial_records(
    symbol: str,
    current_assets: float = 500.0,
    total_assets: float = 2000.0,
    current_liabilities: float = 300.0,
    total_liabilities: float = 800.0,
    retained_earnings: float = 600.0,
    operating_income: float = 200.0,
    revenue: float | None = 1000.0,
    periods: tuple[date, ...] = (
        date(2024, 3, 31),
        date(2024, 6, 30),
        date(2024, 9, 30),
        date(2024, 12, 31),
    ),
    operating_cash_flows: tuple[float, ...] = (100.0, 220.0, 350.0, 500.0),
    quarterly_operating_incomes: tuple[float, ...] | None = None,
    quarterly_revenues: tuple[float, ...] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    income_values = quarterly_operating_incomes or tuple(
        operating_income / len(periods) for _ in periods
    )
    revenue_values = quarterly_revenues or tuple(
        None if revenue is None else revenue / len(periods) for _ in periods
    )
    for period, ocf, quarter_income, quarter_revenue in zip(
        periods,
        operating_cash_flows,
        income_values,
        revenue_values,
        strict=True,
    ):
        publish_date = period + timedelta(days=75 if period.month == 12 else 45)
        values = {
            "CurrentAssets": current_assets,
            "TotalAssets": total_assets,
            "CurrentLiabilities": current_liabilities,
            "Liabilities": total_liabilities,
            "RetainedEarnings": retained_earnings,
            "OperatingIncome": quarter_income,
            "Revenue": quarter_revenue,
            "CashFlowsFromOperatingActivities": ocf,
        }
        rows.extend(
            {
                "symbol": symbol,
                "data_date": period,
                "publish_date": publish_date,
                "statement": (
                    "cash_flow" if key == "CashFlowsFromOperatingActivities" else "statement"
                ),
                "type": key,
                "value": value,
            }
            for key, value in values.items()
            if value is not None
        )
    return rows


def market_values() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"symbol": "MFG", "data_date": date(2024, 1, 20), "market_value": 2000.0},
            {"symbol": "FIN", "data_date": date(2024, 1, 20), "market_value": 500.0},
            {"symbol": "BAD", "data_date": date(2024, 1, 20), "market_value": 1.0},
            {"symbol": "WARN", "data_date": date(2024, 1, 20), "market_value": 2000.0},
        ]
    )


def empty_warnings() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "symbol": pl.Utf8,
            "warning_type": pl.Utf8,
            "data_date": pl.Date,
            "publish_date": pl.Date,
        }
    )


def l1_config() -> L1GateConfig:
    return L1GateConfig(
        altman_z_min=1.8,
        altman_z_min_nonmfg=1.1,
        beneish_m_flag=-1.78,
        max_negative_ocf_quarters=1,
        max_capital_raise_pct=20.0,
        require_clean_audit=True,
        ar_growth_spread_flag=30.0,
        inventory_growth_spread_flag=30.0,
    )


class StaticPriceProvider:
    def __init__(self, calendar: TradingCalendar) -> None:
        self._calendar = calendar
        self.price_request: tuple[date, date] | None = None
        self.financial_request: tuple[date, date] | None = None

    def get_trading_calendar(self, start: date, end: date) -> TradingCalendar:
        return self._calendar

    def get_price_history(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        self.price_request = (start, end)
        days = tuple(day for day in self._calendar.dates if start <= day <= end)
        return pl.DataFrame(price_rows(symbols[0], days, 20.0, 40_000_000.0))

    def get_market_values(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        return pl.DataFrame(
            [
                {
                    "symbol": symbols[0],
                    "data_date": end,
                    "publish_date": end,
                    "market_value": 2000.0,
                }
            ]
        )

    def get_financials(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        self.financial_request = (start, end)
        return financial_rows().filter(pl.col("symbol").is_in(symbols))


class StaticMarketProvider:
    def __init__(self) -> None:
        self.listing_request: date | None = None
        self.warning_request: date | None = None

    def get_listings(self, as_of: date) -> pl.DataFrame:
        self.listing_request = as_of
        return pl.DataFrame(
            [listing("MFG", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24")]
        )

    def get_warnings(self, as_of: date) -> pl.DataFrame:
        self.warning_request = as_of
        return empty_warnings()
