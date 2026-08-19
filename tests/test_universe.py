from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from flowscope.config.loader import load_config
from flowscope.config.schema import L0GateConfig, L1GateConfig
from flowscope.data.calendar import TradingCalendar
from flowscope.universe.builder import UniverseFunnel, build_universe_funnel, render_funnel
from flowscope.universe.gates import GateApplication, GateStep, apply_l0_gates, apply_l1_gates


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
        [
            financial("MFG", 500.0, 2000.0, 300.0, 800.0, 600.0, 200.0, 1000.0),
            financial("FIN", 800.0, 1000.0, 100.0, 500.0, 100.0, 50.0, None),
            financial("BAD", 100.0, 2000.0, 100.0, 1800.0, 0.0, -100.0, 100.0),
            financial("WARN", 500.0, 2000.0, 300.0, 800.0, 600.0, 200.0, 1000.0),
        ]
    )


def financial(
    symbol: str,
    current_assets: float,
    total_assets: float,
    current_liabilities: float,
    total_liabilities: float,
    retained_earnings: float,
    operating_income: float,
    revenue: float | None,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "publish_date": date(2024, 5, 15),
        "current_assets": current_assets,
        "total_assets": total_assets,
        "current_liabilities": current_liabilities,
        "total_liabilities": total_liabilities,
        "retained_earnings": retained_earnings,
        "operating_income": operating_income,
        "revenue": revenue,
    }


def market_values() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"symbol": "MFG", "data_date": date(2024, 1, 20), "market_value": 2_000_000.0},
            {"symbol": "FIN", "data_date": date(2024, 1, 20), "market_value": 500_000.0},
            {"symbol": "BAD", "data_date": date(2024, 1, 20), "market_value": 1_000.0},
            {"symbol": "WARN", "data_date": date(2024, 1, 20), "market_value": 2_000_000.0},
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
                    "market_value": 2_000_000.0,
                }
            ]
        )


class StaticMarketProvider:
    def get_listings(self, as_of: date) -> pl.DataFrame:
        return pl.DataFrame(
            [listing("MFG", "TWSE", "COMMON_STOCK", date(2024, 1, 1), industry="24")]
        )

    def get_warnings(self, as_of: date) -> pl.DataFrame:
        return empty_warnings()

    def get_financial_snapshot(self, as_of: date) -> pl.DataFrame:
        return financial_rows().filter(pl.col("symbol") == "MFG")
