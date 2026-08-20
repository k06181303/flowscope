from __future__ import annotations

from datetime import date
from typing import Protocol

import polars as pl


class PriceProvider(Protocol):
    def get_ohlcv(
        self,
        symbols: list[str],
        start: date,
        end: date,
        adjusted: bool,
    ) -> pl.DataFrame:
        """Return symbol, data_date, publish_date, OHLCV, amount, shares_outstanding."""

    def get_benchmark_history(self, start: date, end: date) -> pl.DataFrame:
        """Return TAIEX total-return index with publish_date."""

    def get_adjusted_price_history(
        self,
        symbols: list[str],
        start: date,
        end: date,
    ) -> pl.DataFrame:
        """Return PIT-safe backward-adjusted OHLCV without share enrichment."""


class ChipProvider(Protocol):
    def get_institutional_flow(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        """Return institutional flows with publish_date."""

    def get_margin(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        """Return margin and short-sale balances with publish_date."""

    def get_holder_distribution(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        """Return holder distribution with publish_date."""


class FundamentalProvider(Protocol):
    def get_financials(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        """Return PIT financial statement rows."""

    def get_monthly_revenue(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        """Return PIT monthly revenue rows."""


class MetaProvider(Protocol):
    def get_listings(self, as_of: date) -> pl.DataFrame:
        """Return symbol, name, market, industry, listing_date, delisting_date."""

    def get_warnings(self, as_of: date) -> pl.DataFrame:
        """Return warning/disposition rows."""
