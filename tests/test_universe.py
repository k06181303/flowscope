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
    apply_l0_gates,
    apply_l1_gates,
    is_nonmanufacturing_industry,
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


def test_l1_negative_ocf_uses_cash_flow_statement_and_removes_symbol() -> None:
    l1 = apply_l1_gates(
        pl.DataFrame(
            [
                listing("MFG", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24"),
                listing("NEG", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24"),
            ]
        ),
        empty_warnings(),
        pl.DataFrame(
            financial_records("MFG")
            + financial_records("NEG", operating_cash_flows=(-1.0, -2.0))
        ),
        pl.DataFrame(
            [
                {"symbol": "MFG", "data_date": date(2024, 1, 20), "market_value": 2000.0},
                {"symbol": "NEG", "data_date": date(2024, 1, 20), "market_value": 2000.0},
            ]
        ),
        l1_config(),
    )

    assert [(step.name, step.before, step.after) for step in l1.steps] == [
        ("L1 warning_disposition_full_delivery", 2, 2),
        ("L1 altman_z", 2, 2),
        ("L1 negative_ocf", 2, 1),
    ]
    assert l1.frame["symbol"].to_list() == ["MFG"]


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


def test_render_funnel_matches_spec_shape() -> None:
    funnel = UniverseFunnel(
        as_of=date(2024, 8, 18),
        market="TW",
        initial_count=1812,
        l0=GateApplication(pl.DataFrame({"symbol": ["A"] * 672}), (GateStep("L0", 1812, 672),)),
        l1=GateApplication(pl.DataFrame({"symbol": ["A"] * 589}), (GateStep("L1", 672, 589),)),
        top_n=30,
    )

    assert render_funnel(funnel).splitlines() == [
        "Universe funnel (as_of=2024-08-18, market=TW)",
        "  全市場上市櫃              1,812",
        "  L0 流動性             △  1,140  ->    672",
        "  L1 排雷              △     83  ->    589",
        "  資料完整度 >= 門檻        △      0  ->    589",
        "  評分後 Top N                      ->     30",
    ]


def test_builder_fetches_exact_trailing_20_trading_days_for_l0() -> None:
    config = load_config(Path("configs/tw_swing.yaml"))
    as_of = date(2025, 5, 15)
    calendar = TradingCalendar(
        tuple(date(2024, 1, 1) + timedelta(days=index) for index in range(501))
    )
    data_provider = StaticPriceProvider(calendar)

    funnel = build_universe_funnel(config, as_of, data_provider, StaticMarketProvider())

    assert data_provider.price_request == (calendar.trailing_dates(as_of, 20)[0], as_of)
    assert funnel.initial_count == 1
    assert funnel.l0.frame.height == 1
    assert funnel.l1.frame.height == 1


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
    operating_cash_flows: tuple[float, float] = (100.0, 120.0),
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for period, ocf in zip(
        (date(2023, 12, 31), date(2024, 3, 31)),
        operating_cash_flows,
        strict=True,
    ):
        publish_date = date(2024, 3, 15) if period.month == 12 else date(2024, 5, 15)
        values = {
            "CurrentAssets": current_assets,
            "TotalAssets": total_assets,
            "CurrentLiabilities": current_liabilities,
            "Liabilities": total_liabilities,
            "RetainedEarnings": retained_earnings,
            "OperatingIncome": operating_income,
            "Revenue": revenue,
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
        return financial_rows().filter(pl.col("symbol").is_in(symbols))


class StaticMarketProvider:
    def get_listings(self, as_of: date) -> pl.DataFrame:
        return pl.DataFrame(
            [listing("MFG", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24")]
        )

    def get_warnings(self, as_of: date) -> pl.DataFrame:
        return empty_warnings()
