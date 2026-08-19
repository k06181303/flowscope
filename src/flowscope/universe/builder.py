from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

import polars as pl

from flowscope.config.schema import FlowScopeConfig
from flowscope.data.calendar import TradingCalendar
from flowscope.universe.gates import GateApplication, GateStep, apply_l0_gates, apply_l1_gates

LISTING_DAY_LOOKBACK_CALENDAR_DAYS = 500


class PriceDataProvider(Protocol):
    def get_trading_calendar(self, start: date, end: date) -> TradingCalendar: ...

    def get_price_history(self, symbols: list[str], start: date, end: date) -> pl.DataFrame: ...

    def get_market_values(self, symbols: list[str], start: date, end: date) -> pl.DataFrame: ...


class MarketMetaProvider(Protocol):
    def get_listings(self, as_of: date) -> pl.DataFrame: ...

    def get_warnings(self, as_of: date) -> pl.DataFrame: ...

    def get_financial_snapshot(self, as_of: date) -> pl.DataFrame: ...


@dataclass(frozen=True)
class UniverseFunnel:
    as_of: date
    market: str
    initial_count: int
    l0: GateApplication
    l1: GateApplication
    top_n: int

    @property
    def completeness_count(self) -> int:
        return self.l1.frame.height

    @property
    def final_count(self) -> int:
        return min(self.top_n, self.completeness_count)

    @property
    def final_symbols(self) -> list[str]:
        return [str(symbol) for symbol in self.l1.frame["symbol"].head(self.final_count)]


def build_universe_funnel(
    config: FlowScopeConfig,
    as_of: date,
    data_provider: PriceDataProvider,
    market_provider: MarketMetaProvider,
) -> UniverseFunnel:
    listings = market_provider.get_listings(as_of)
    calendar_start = as_of - timedelta(days=LISTING_DAY_LOOKBACK_CALENDAR_DAYS)
    calendar = data_provider.get_trading_calendar(calendar_start, as_of)
    latest_trade_date = calendar.on_or_before(as_of)
    trailing_dates = calendar.trailing_dates(latest_trade_date, 20)
    price_start = trailing_dates[0]

    symbols = [str(symbol) for symbol in listings["symbol"]]
    prices = data_provider.get_price_history(symbols, price_start, latest_trade_date)
    l0 = apply_l0_gates(listings, prices, calendar, as_of, config.gates.l0)

    l0_symbols = [str(symbol) for symbol in l0.frame["symbol"]]
    warnings = market_provider.get_warnings(as_of)
    financials = market_provider.get_financial_snapshot(as_of)
    market_values = (
        data_provider.get_market_values(l0_symbols, latest_trade_date, latest_trade_date)
        if l0_symbols
        else empty_market_values()
    )
    l1 = apply_l1_gates(l0.frame, warnings, financials, market_values, config.gates.l1)
    return UniverseFunnel(
        as_of=as_of,
        market=config.market,
        initial_count=listings.height,
        l0=l0,
        l1=l1,
        top_n=config.universe.top_n,
    )


def render_funnel(funnel: UniverseFunnel) -> str:
    l0_after = funnel.l0.frame.height
    l1_after = funnel.l1.frame.height
    lines = [
        f"Universe funnel (as_of={funnel.as_of.isoformat()}, market={funnel.market})",
        f"  {'全市場上市櫃':<18} {funnel.initial_count:>6,}",
        render_count_line("L0 流動性", funnel.initial_count, l0_after),
        render_count_line("L1 排雷", l0_after, l1_after),
        render_count_line("資料完整度 >= 門檻", l1_after, funnel.completeness_count),
        f"  {'評分後 Top N':<18} {'':>10}  -> {funnel.final_count:>6,}",
    ]
    return "\n".join(lines)


def render_count_line(label: str, before: int, after: int) -> str:
    removed = before - after
    return f"  {label:<18} △ {removed:>6,}  -> {after:>6,}"


def empty_market_values() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "symbol": pl.Utf8,
            "data_date": pl.Date,
            "publish_date": pl.Date,
            "market_value": pl.Float64,
        }
    )


def summarize_gate_steps(steps: tuple[GateStep, ...]) -> list[str]:
    return [f"{step.name}: {step.before}->{step.after}" for step in steps]
