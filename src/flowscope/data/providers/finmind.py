from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from flowscope.data.adjust import backward_adjust_ohlcv
from flowscope.data.cache import CacheKey, ParquetCache, stable_symbol_hash
from flowscope.data.calendar import TradingCalendar
from flowscope.data.pit import as_of_filter

FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
SHARES_OUTSTANDING_TOLERANCE = 0.005
REQUEST_INTERVAL_SECONDS = 2.25
DAILY_BULK_DATASETS = frozenset(
    {
        "TaiwanStockPrice",
        "TaiwanStockMarketValue",
        "TaiwanStockInstitutionalInvestorsBuySell",
        "TaiwanStockMarginPurchaseShortSale",
    }
)
PER_SYMBOL_DATASETS = frozenset(
    {
        "TaiwanStockFinancialStatements",
        "TaiwanStockBalanceSheet",
        "TaiwanStockCashFlowsStatement",
        "TaiwanStockDividendResult",
        "TaiwanStockMonthRevenue",
    }
)


class FinMindError(RuntimeError):
    """Raised when FinMind cannot provide a required dataset."""


@dataclass(frozen=True)
class FinMindRequest:
    dataset: str
    data_id: str | None
    start: date | None
    end: date | None


class FinMindClient:
    def __init__(
        self,
        token: str,
        *,
        api_url: str = FINMIND_API_URL,
        request_interval_seconds: float = REQUEST_INTERVAL_SECONDS,
        max_attempts: int = 3,
    ) -> None:
        if not token:
            raise FinMindError("FINMIND_TOKEN is required")
        self._token = token
        self._api_url = api_url
        self._request_interval_seconds = request_interval_seconds
        self._max_attempts = max_attempts
        self._last_request_at = 0.0

    def fetch_rows(self, request: FinMindRequest) -> list[dict[str, Any]]:
        params = self._params(request)
        last_error: FinMindError | None = None
        for attempt in range(1, self._max_attempts + 1):
            self._rate_limit()
            url = f"{self._api_url}?{urllib.parse.urlencode(params)}"
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                return self._extract_rows(payload, request.dataset)
            except urllib.error.HTTPError as exc:
                last_error = self._from_http_error(exc, request.dataset)
            except urllib.error.URLError as exc:
                last_error = FinMindError(f"{request.dataset} connection failed: {exc.reason}")
            except json.JSONDecodeError as exc:
                last_error = FinMindError(f"{request.dataset} returned invalid JSON: {exc.msg}")

            if attempt < self._max_attempts:
                time.sleep(2 ** (attempt - 1))

        if last_error is not None:
            raise last_error
        raise FinMindError(f"{request.dataset} request failed")

    def _params(self, request: FinMindRequest) -> dict[str, str]:
        params = {"dataset": request.dataset, "token": self._token}
        if request.data_id is not None:
            params["data_id"] = request.data_id
        if request.start is not None:
            params["start_date"] = request.start.isoformat()
        if request.end is not None:
            params["end_date"] = request.end.isoformat()
        return params

    def _rate_limit(self) -> None:
        if self._request_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._request_interval_seconds:
            time.sleep(self._request_interval_seconds - elapsed)
        self._last_request_at = time.monotonic()

    def _extract_rows(self, payload: object, dataset: str) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise FinMindError(f"{dataset} returned a non-object payload")
        msg = str(payload.get("msg", ""))
        lowered = msg.lower()
        if any(term in lowered for term in ("level", "sponsor", "upgrade", "permission")):
            raise FinMindError(f"{dataset} permission denied: {msg}")
        if any(term in lowered for term in ("limit", "too many requests", "rate")):
            raise FinMindError(f"{dataset} rate limited: {msg}")
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            raise FinMindError(f"{dataset} returned no rows")
        if not all(isinstance(row, dict) for row in rows):
            raise FinMindError(f"{dataset} returned malformed rows")
        return rows

    def _from_http_error(self, exc: urllib.error.HTTPError, dataset: str) -> FinMindError:
        body = exc.read().decode("utf-8", errors="replace")[:200]
        if exc.code == 429:
            return FinMindError(f"{dataset} rate limited: HTTP 429")
        if exc.code in (401, 402, 403):
            return FinMindError(f"{dataset} permission denied: HTTP {exc.code}")
        return FinMindError(f"{dataset} HTTP {exc.code}: {body}")


class FinMindProvider:
    def __init__(
        self,
        *,
        data_root: Path = Path("data"),
        token: str | None = None,
        no_cache: bool = False,
        client: FinMindClient | None = None,
    ) -> None:
        self._no_cache = no_cache
        self._cache = ParquetCache(data_root / "raw")
        self._client = client or FinMindClient(token or load_finmind_token())

    def get_ohlcv(
        self,
        symbols: list[str],
        start: date,
        end: date,
        adjusted: bool,
    ) -> pl.DataFrame:
        validate_symbols(symbols)
        method = "get_ohlcv_adjusted" if adjusted else "get_ohlcv_raw"
        key = cache_key(method, symbols, start, end)

        def fetch() -> pl.DataFrame:
            raw = self._get_price_frame(symbols, start, end)
            with_shares = self._attach_shares_outstanding(raw, symbols, start, end)
            if not adjusted:
                return with_shares
            dividends = self._get_dividend_result_frame(symbols, start, end)
            return backward_adjust_ohlcv(with_shares, dividends, end)

        return as_of_filter(self._cache.get_or_fetch(key, fetch, no_cache=self._no_cache), end)

    def get_trading_calendar(self, start: date, end: date) -> TradingCalendar:
        key = cache_key("get_trading_calendar", ["ALL"], start, end)

        def fetch() -> pl.DataFrame:
            rows = self._fetch_dataset("TaiwanStockTradingDate", None, start, end)
            return frame_from_rows(rows).select(pl.col("date").str.strptime(pl.Date).alias("date"))

        df = self._cache.get_or_fetch(key, fetch, no_cache=self._no_cache)
        return TradingCalendar.from_frame(df)

    def get_institutional_flow(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        validate_symbols(symbols)
        key = cache_key("get_institutional_flow", symbols, start, end)

        def fetch() -> pl.DataFrame:
            rows = self._fetch_dataset_for_symbols(
                "TaiwanStockInstitutionalInvestorsBuySell",
                symbols,
                start,
                end,
            )
            df = frame_from_rows(rows).with_columns(
                pl.col("stock_id").cast(pl.Utf8).alias("symbol"),
                pl.col("date").str.strptime(pl.Date).alias("data_date"),
            )
            grouped = (
                df.with_columns((pl.col("buy") - pl.col("sell")).alias("net"))
                .group_by(["symbol", "data_date", "name"])
                .agg(pl.col("net").sum())
                .pivot(
                    index=["symbol", "data_date"],
                    on="name",
                    values="net",
                    aggregate_function="sum",
                )
                .with_columns(pl.col("data_date").alias("publish_date"))
            )
            return grouped.select(
                "symbol",
                "data_date",
                "publish_date",
                institutional_sum(grouped, ["Foreign_Investor", "Foreign_Dealer_Self"]).alias(
                    "foreign_net"
                ),
                institutional_sum(grouped, ["Investment_Trust"]).alias("trust_net"),
                institutional_sum(grouped, ["Dealer_self", "Dealer_Hedging"]).alias("dealer_net"),
            )

        return as_of_filter(self._cache.get_or_fetch(key, fetch, no_cache=self._no_cache), end)

    def get_margin(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        validate_symbols(symbols)
        key = cache_key("get_margin", symbols, start, end)

        def fetch() -> pl.DataFrame:
            rows = self._fetch_dataset_for_symbols(
                "TaiwanStockMarginPurchaseShortSale",
                symbols,
                start,
                end,
            )
            return (
                frame_from_rows(rows)
                .with_columns(
                    pl.col("stock_id").cast(pl.Utf8).alias("symbol"),
                    pl.col("date").str.strptime(pl.Date).alias("data_date"),
                )
                .with_columns(pl.col("data_date").alias("publish_date"))
                .rename(
                    {
                        "MarginPurchaseTodayBalance": "margin_balance",
                        "ShortSaleTodayBalance": "short_balance",
                        "MarginPurchaseLimit": "margin_limit",
                    }
                )
                .with_columns(
                    (pl.col("margin_balance") / pl.col("margin_limit") * 100).alias(
                        "margin_quota_used_pct"
                    ),
                    # FinMind `TaiwanStockSecuritiesLending` 是交易明細,不是餘額。
                    # 沒有期初餘額時不得把區間內淨額假裝成 balance。
                    pl.lit(None, dtype=pl.Float64).alias("securities_lending_balance"),
                )
                .select(
                    "symbol",
                    "data_date",
                    "publish_date",
                    "margin_balance",
                    "short_balance",
                    "margin_quota_used_pct",
                    "securities_lending_balance",
                )
            )

        return as_of_filter(self._cache.get_or_fetch(key, fetch, no_cache=self._no_cache), end)

    def get_monthly_revenue(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        validate_symbols(symbols)
        key = cache_key("get_monthly_revenue", symbols, start, end)

        def fetch() -> pl.DataFrame:
            rows = self._fetch_dataset_for_symbols("TaiwanStockMonthRevenue", symbols, start, end)
            records: list[dict[str, object]] = []
            for row in rows:
                year = int(row["revenue_year"])
                month = int(row["revenue_month"])
                data_date = month_end(year, month)
                records.append(
                    {
                        "symbol": str(row["stock_id"]),
                        "data_date": data_date,
                        "publish_date": next_month_tenth(data_date),
                        "revenue": float(row["revenue"]),
                    }
                )
            return pl.DataFrame(records).sort(["symbol", "data_date"])

        return as_of_filter(self._cache.get_or_fetch(key, fetch, no_cache=self._no_cache), end)

    def get_financials(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        validate_symbols(symbols)
        key = cache_key("get_financials", symbols, start, end)

        def fetch() -> pl.DataFrame:
            rows: list[dict[str, Any]] = []
            for dataset, statement in [
                ("TaiwanStockFinancialStatements", "income"),
                ("TaiwanStockBalanceSheet", "balance"),
                ("TaiwanStockCashFlowsStatement", "cash_flow"),
            ]:
                for row in self._fetch_dataset_for_symbols(dataset, symbols, start, end):
                    enriched = dict(row)
                    enriched["statement"] = statement
                    rows.append(enriched)
            df = frame_from_rows(rows).with_columns(
                pl.col("stock_id").cast(pl.Utf8).alias("symbol"),
                pl.col("date").str.strptime(pl.Date).alias("data_date"),
                pl.col("value").cast(pl.Float64),
            )
            return df.with_columns(
                pl.col("data_date")
                .map_elements(financial_publish_date, return_dtype=pl.Date)
                .alias("publish_date")
            ).select("symbol", "data_date", "publish_date", "statement", "type", "value")

        return as_of_filter(self._cache.get_or_fetch(key, fetch, no_cache=self._no_cache), end)

    def _get_price_frame(self, symbols: list[str], start: date, end: date) -> pl.DataFrame:
        rows = self._fetch_dataset_for_symbols("TaiwanStockPrice", symbols, start, end)
        return (
            frame_from_rows(rows)
            .with_columns(
                pl.col("stock_id").cast(pl.Utf8).alias("symbol"),
                pl.col("date").str.strptime(pl.Date).alias("data_date"),
                pl.col("open").cast(pl.Float64),
                pl.col("max").cast(pl.Float64).alias("high"),
                pl.col("min").cast(pl.Float64).alias("low"),
                pl.col("close").cast(pl.Float64),
                pl.col("Trading_Volume").cast(pl.Int64).alias("volume"),
                pl.col("Trading_money").cast(pl.Float64).alias("amount"),
            )
            .with_columns(pl.col("data_date").alias("publish_date"))
            .select(
                "symbol",
                "data_date",
                "publish_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
            )
            .sort(["symbol", "data_date"])
        )

    def _get_dividend_result_frame(
        self,
        symbols: list[str],
        start: date,
        end: date,
    ) -> pl.DataFrame:
        dividend_start = start - timedelta(days=370)
        rows = self._fetch_dataset_for_symbols(
            "TaiwanStockDividendResult",
            symbols,
            dividend_start,
            end,
        )
        return (
            frame_from_rows(rows)
            .with_columns(
                pl.col("stock_id").cast(pl.Utf8).alias("symbol"),
                pl.col("date").str.strptime(pl.Date).alias("data_date"),
                pl.col("before_price").cast(pl.Float64),
                pl.col("after_price").cast(pl.Float64),
            )
            .select("symbol", "data_date", "before_price", "after_price")
            .sort(["symbol", "data_date"])
        )

    def _attach_shares_outstanding(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
        start: date,
        end: date,
    ) -> pl.DataFrame:
        market = self._get_market_value_shares(symbols, start, end)
        balance = self._get_balance_sheet_shares(symbols, start - timedelta(days=730), end)
        balance_lookup = latest_balance_lookup(balance)
        market_lookup = {
            (str(row["symbol"]), expect_date(row["data_date"], "data_date")): float(
                row["shares_from_market_value"]
            )
            for row in market.iter_rows(named=True)
        }

        records: list[dict[str, object]] = []
        for row in prices.iter_rows(named=True):
            symbol = str(row["symbol"])
            data_date = expect_date(row["data_date"], "data_date")
            market_shares = market_lookup.get((symbol, data_date))
            balance_shares = balance_shares_as_of(balance_lookup, symbol, data_date)
            if market_shares is None or balance_shares is None:
                raise FinMindError(
                    f"Cannot derive shares_outstanding for {symbol} on {data_date.isoformat()}"
                )
            relative_diff = abs(balance_shares - market_shares) / balance_shares
            if relative_diff > SHARES_OUTSTANDING_TOLERANCE:
                raise FinMindError(
                    "shares_outstanding cross-check failed for "
                    f"{symbol} on {data_date.isoformat()}: "
                    f"balance={balance_shares:.0f}, market={market_shares:.0f}, "
                    f"diff={relative_diff:.4%}"
                )
            enriched = dict(row)
            enriched["shares_outstanding"] = balance_shares
            records.append(enriched)

        return pl.DataFrame(records, schema={**prices.schema, "shares_outstanding": pl.Float64})

    def _get_market_value_shares(
        self,
        symbols: list[str],
        start: date,
        end: date,
    ) -> pl.DataFrame:
        rows = self._fetch_dataset_for_symbols("TaiwanStockMarketValue", symbols, start, end)
        market = frame_from_rows(rows).with_columns(
            pl.col("stock_id").cast(pl.Utf8).alias("symbol"),
            pl.col("date").str.strptime(pl.Date).alias("data_date"),
            pl.col("market_value").cast(pl.Float64),
        )
        close = self._get_price_frame(symbols, start, end).select("symbol", "data_date", "close")
        return (
            market.join(close, on=["symbol", "data_date"], how="inner")
            .with_columns(
                (pl.col("market_value") / pl.col("close")).alias("shares_from_market_value")
            )
            .select("symbol", "data_date", "shares_from_market_value")
            .sort(["symbol", "data_date"])
        )

    def _get_balance_sheet_shares(
        self,
        symbols: list[str],
        start: date,
        end: date,
    ) -> pl.DataFrame:
        rows = self._fetch_dataset_for_symbols("TaiwanStockBalanceSheet", symbols, start, end)
        return (
            frame_from_rows(rows)
            .filter(pl.col("type") == "OrdinaryShare")
            .with_columns(
                pl.col("stock_id").cast(pl.Utf8).alias("symbol"),
                pl.col("date").str.strptime(pl.Date).alias("data_date"),
                (pl.col("value").cast(pl.Float64) / 10.0).alias("shares_from_balance_sheet"),
            )
            .with_columns(
                pl.col("data_date")
                .map_elements(financial_publish_date, return_dtype=pl.Date)
                .alias("publish_date")
            )
            .select("symbol", "data_date", "publish_date", "shares_from_balance_sheet")
            .sort(["symbol", "publish_date"])
        )

    def _fetch_dataset_for_symbols(
        self,
        dataset: str,
        symbols: list[str],
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        if len(symbols) == 1:
            rows = self._fetch_dataset(dataset, symbols[0], start, end)
        elif dataset in DAILY_BULK_DATASETS:
            rows = self._fetch_daily_bulk_dataset_for_symbols(dataset, symbols, start, end)
        elif dataset in PER_SYMBOL_DATASETS:
            rows = self._fetch_per_symbol_dataset(dataset, symbols, start, end)
        else:
            raise FinMindError(f"{dataset} multi-symbol fetch strategy is not defined")
        wanted = set(symbols)
        return [
            row
            for row in rows
            if str(row.get("stock_id")) in wanted
            and start <= date.fromisoformat(str(row["date"])) <= end
        ]

    def _fetch_daily_bulk_dataset_for_symbols(
        self,
        dataset: str,
        symbols: list[str],
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        requested_dates = self._trading_dates(start, end)
        rows: list[dict[str, Any]] = []
        for trading_date in requested_dates:
            rows.extend(self._fetch_dataset(dataset, None, trading_date, trading_date))
        returned_dates = {
            date.fromisoformat(str(row["date"]))
            for row in rows
            if str(row.get("stock_id")) in set(symbols)
        }
        if returned_dates != set(requested_dates):
            missing = sorted(set(requested_dates) - returned_dates)
            extra = sorted(returned_dates - set(requested_dates))
            raise FinMindError(
                f"{dataset} daily bulk returned dates do not match trading calendar: "
                f"missing={format_dates(missing)}, extra={format_dates(extra)}"
            )
        return rows

    def _fetch_per_symbol_dataset(
        self,
        dataset: str,
        symbols: list[str],
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for symbol in symbols:
            rows.extend(self._fetch_dataset(dataset, symbol, start, end))
        return rows

    def _trading_dates(self, start: date, end: date) -> tuple[date, ...]:
        rows = self._fetch_dataset("TaiwanStockTradingDate", None, start, end)
        dates = tuple(date.fromisoformat(str(row["date"])) for row in rows)
        if not dates:
            raise FinMindError(f"TaiwanStockTradingDate returned no dates for {start}..{end}")
        return dates

    def _fetch_dataset(
        self,
        dataset: str,
        data_id: str | None,
        start: date | None,
        end: date | None,
    ) -> list[dict[str, Any]]:
        return self._client.fetch_rows(FinMindRequest(dataset, data_id, start, end))


def load_finmind_token(env_path: Path = Path(".env")) -> str:
    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if token:
        return token
    if env_path.is_file():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "FINMIND_TOKEN" and value.strip():
                return value.strip()
    raise FinMindError("FINMIND_TOKEN is required")


def cache_key(method: str, symbols: list[str], start: date, end: date) -> CacheKey:
    return CacheKey(
        provider="finmind",
        method=method,
        symbol_hash=stable_symbol_hash(symbols),
        start=start,
        end=end,
    )


def validate_symbols(symbols: list[str]) -> None:
    if not symbols:
        raise ValueError("symbols must not be empty")
    if len(set(symbols)) != len(symbols):
        raise ValueError("symbols must not contain duplicates")


def frame_from_rows(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if not rows:
        raise FinMindError("FinMind returned no rows after local filtering")
    return pl.DataFrame(rows)


def financial_publish_date(period_end: date) -> date:
    delay_days = 75 if period_end.month == 12 else 45
    return period_end + timedelta(days=delay_days)


def next_month_tenth(data_date: date) -> date:
    year = data_date.year + (1 if data_date.month == 12 else 0)
    month = 1 if data_date.month == 12 else data_date.month + 1
    return date(year, month, 10)


def month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def expect_date(value: object, column: str) -> date:
    if isinstance(value, date):
        return value
    raise TypeError(f"{column} must contain date values")


def latest_balance_lookup(balance: pl.DataFrame) -> dict[str, list[tuple[date, float]]]:
    lookup: dict[str, list[tuple[date, float]]] = {}
    for row in balance.iter_rows(named=True):
        symbol = str(row["symbol"])
        publish_date = expect_date(row["publish_date"], "publish_date")
        shares = float(row["shares_from_balance_sheet"])
        lookup.setdefault(symbol, []).append((publish_date, shares))
    for items in lookup.values():
        items.sort(key=lambda item: item[0])
    return lookup


def balance_shares_as_of(
    lookup: dict[str, list[tuple[date, float]]],
    symbol: str,
    as_of: date,
) -> float | None:
    latest: float | None = None
    for publish_date, shares in lookup.get(symbol, []):
        if publish_date <= as_of:
            latest = shares
        else:
            break
    return latest


def institutional_sum(df: pl.DataFrame, columns: Iterable[str]) -> pl.Expr:
    expected = list(columns)
    found = [column for column in expected if column in df.columns]
    if not found:
        joined = ", ".join(expected)
        raise FinMindError(f"None of the expected institutional columns exist: {joined}")
    expression = pl.lit(0, dtype=pl.Int64)
    for column in found:
        expression += pl.col(column).fill_null(0)
    return expression


def format_dates(values: list[date]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(value.isoformat() for value in values) + "]"
