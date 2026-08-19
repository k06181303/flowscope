from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from flowscope.data.calendar import TradingCalendar
from flowscope.data.providers.finmind import (
    FinMindError,
    FinMindProvider,
    FinMindRequest,
    align_holder_distribution_to_trading_days,
    balance_shares_as_of,
    financial_publish_date,
    latest_balance_lookup,
    month_end,
    next_month_tenth,
    parse_holding_level,
)


class StaticClient:
    def __init__(self) -> None:
        self.calls: list[FinMindRequest] = []

    def fetch_rows(self, request: FinMindRequest) -> list[dict[str, Any]]:
        self.calls.append(request)
        if request.dataset == "TaiwanStockPrice":
            if request.data_id is None:
                assert request.start == request.end
                return [
                    price_row_for_symbol("2330", request.start.isoformat(), 100.0),
                    price_row_for_symbol("2317", request.start.isoformat(), 200.0),
                    price_row_for_symbol("2454", request.start.isoformat(), 300.0),
                ]
            return [
                price_row("2024-01-02", 100.0),
                price_row("2024-01-03", 110.0),
                price_row("2024-01-04", 90.0),
            ]
        if request.dataset == "TaiwanStockMarketValue":
            if request.data_id is None:
                assert request.start == request.end
                return [
                    market_value_row("2330", request.start.isoformat(), 100_000.0),
                    market_value_row("2317", request.start.isoformat(), 200_000.0),
                    market_value_row("2454", request.start.isoformat(), 300_000.0),
                ]
            return [
                {"date": "2024-01-02", "stock_id": "2330", "market_value": 100_000.0},
                {"date": "2024-01-03", "stock_id": "2330", "market_value": 110_000.0},
                {"date": "2024-01-04", "stock_id": "2330", "market_value": 90_000.0},
            ]
        if request.dataset == "TaiwanStockBalanceSheet":
            return [
                {
                    "date": "2023-09-30",
                    "stock_id": request.data_id or "2330",
                    "type": "OrdinaryShare",
                    "value": 10_000.0,
                    "origin_name": "ordinary share",
                },
                {
                    "date": "2024-03-31",
                    "stock_id": request.data_id or "2330",
                    "type": "OrdinaryShare",
                    "value": 10_000.0,
                    "origin_name": "ordinary share",
                },
            ]
        if request.dataset == "TaiwanStockDividendResult":
            return [
                {
                    "date": "2024-01-04",
                    "stock_id": "2330",
                    "before_price": 100.0,
                    "after_price": 90.0,
                }
            ]
        if request.dataset == "TaiwanStockTradingDate":
            return filter_requested_dates(
                [
                    {"date": "2024-01-02"},
                    {"date": "2024-01-03"},
                    {"date": "2024-01-04"},
                    {"date": "2024-01-08"},
                    {"date": "2024-01-09"},
                    {"date": "2024-01-10"},
                    {"date": "2024-01-11"},
                    {"date": "2024-01-15"},
                    {"date": "2024-01-16"},
                ],
                request,
            )
        if request.dataset == "TaiwanStockMarginPurchaseShortSale":
            return [
                margin_row("2024-01-02"),
                margin_row("2024-01-03"),
                margin_row("2024-01-04"),
            ]
        if request.dataset == "TaiwanStockMonthRevenue":
            return [
                {
                    "date": "2024-02-01",
                    "stock_id": "2330",
                    "revenue_year": 2024,
                    "revenue_month": 1,
                    "revenue": 123.0,
                }
            ]
        if request.dataset in {
            "TaiwanStockFinancialStatements",
            "TaiwanStockCashFlowsStatement",
        }:
            return [
                {
                    "date": "2024-03-31",
                    "stock_id": "2330",
                    "type": "Revenue",
                    "value": 123.0,
                    "origin_name": "revenue",
                }
            ]
        if request.dataset == "TaiwanStockHoldingSharesPer":
            if request.data_id is None:
                assert request.start == request.end
                return holder_rows("2330", request.start.isoformat()) + holder_rows(
                    "2317",
                    request.start.isoformat(),
                )
            symbol = request.data_id or "2330"
            return holder_rows(symbol, "2024-01-05") + holder_rows(symbol, "2024-01-12")
        raise AssertionError(f"unexpected dataset {request.dataset}")


def price_row(day: str, close: float) -> dict[str, object]:
    return price_row_for_symbol("2330", day, close)


def price_row_for_symbol(symbol: str, day: str, close: float) -> dict[str, object]:
    return {
        "date": day,
        "stock_id": symbol,
        "open": close,
        "max": close,
        "min": close,
        "close": close,
        "Trading_Volume": 100,
        "Trading_money": close * 100,
    }


def market_value_row(symbol: str, day: str, value: float) -> dict[str, object]:
    return {"date": day, "stock_id": symbol, "market_value": value}


def test_get_ohlcv_returns_adjusted_prices_and_cross_checked_shares(tmp_path: Path) -> None:
    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=StaticClient())  # type: ignore[arg-type]

    df = provider.get_ohlcv(["2330"], date(2024, 1, 2), date(2024, 1, 4), adjusted=True)

    assert df.columns == [
        "symbol",
        "data_date",
        "publish_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "shares_outstanding",
    ]
    # 手算來源:OrdinaryShare=10,000 元,面額 10 元 → 1,000 股。
    # market_value / raw close 也都是 1,000 股,通過雙推導交叉驗證。
    assert df["shares_outstanding"].to_list() == pytest.approx([1000.0, 1000.0, 1000.0])
    assert df["close"].to_list() == pytest.approx([90.0, 99.0, 90.0])


def test_provider_uses_one_bulk_request_per_trading_date_for_multiple_symbols(
    tmp_path: Path,
) -> None:
    client = StaticClient()
    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=client)  # type: ignore[arg-type]

    provider.get_ohlcv(
        ["2330", "2317", "2454"],
        date(2024, 1, 2),
        date(2024, 1, 4),
        adjusted=False,
    )

    price_bulk_calls = [
        call for call in client.calls if call.dataset == "TaiwanStockPrice" and call.data_id is None
    ]
    assert price_bulk_calls
    assert all(call.start == call.end for call in price_bulk_calls)
    assert {call.start for call in price_bulk_calls} == {
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
    }


def test_daily_bulk_fetch_raises_when_returned_dates_do_not_match_calendar(
    tmp_path: Path,
) -> None:
    class BadBulkClient(StaticClient):
        def fetch_rows(self, request: FinMindRequest) -> list[dict[str, Any]]:
            if request.dataset == "TaiwanStockPrice" and request.data_id is None:
                return [price_row_for_symbol("2330", "2024-01-02", 100.0)]
            return super().fetch_rows(request)

    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=BadBulkClient())  # type: ignore[arg-type]

    with pytest.raises(FinMindError, match="returned dates do not match trading calendar"):
        provider.get_ohlcv(["2330", "2317"], date(2024, 1, 2), date(2024, 1, 4), adjusted=False)


def test_financial_datasets_are_fetched_per_symbol_for_multiple_symbols(tmp_path: Path) -> None:
    client = StaticClient()
    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=client)  # type: ignore[arg-type]

    provider.get_financials(["2330", "2317", "2454"], date(2024, 1, 1), date(2024, 6, 30))

    financial_calls = [
        call
        for call in client.calls
        if call.dataset
        in {
            "TaiwanStockFinancialStatements",
            "TaiwanStockBalanceSheet",
            "TaiwanStockCashFlowsStatement",
        }
    ]
    assert all(call.data_id in {"2330", "2317", "2454"} for call in financial_calls)
    assert len(financial_calls) == 9


def test_get_institutional_flow_maps_daily_publish_date(tmp_path: Path) -> None:
    class InstitutionalClient(StaticClient):
        def fetch_rows(self, request: FinMindRequest) -> list[dict[str, Any]]:
            if request.dataset == "TaiwanStockInstitutionalInvestorsBuySell":
                return [
                    investor_row("Foreign_Investor", 100, 40),
                    investor_row("Foreign_Dealer_Self", 10, 20),
                    investor_row("Investment_Trust", 30, 5),
                    investor_row("Dealer_self", 7, 2),
                    investor_row("Dealer_Hedging", 4, 9),
                ]
            return super().fetch_rows(request)

    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=InstitutionalClient())  # type: ignore[arg-type]

    df = provider.get_institutional_flow(["2330"], date(2024, 1, 2), date(2024, 1, 2))

    assert df["publish_date"].to_list() == [date(2024, 1, 2)]
    assert df["foreign_net"].to_list() == [50]
    assert df["trust_net"].to_list() == [25]
    assert df["dealer_net"].to_list() == [0]


def test_institutional_flow_raises_when_expected_columns_are_missing(tmp_path: Path) -> None:
    class RenamedInstitutionalClient(StaticClient):
        def fetch_rows(self, request: FinMindRequest) -> list[dict[str, Any]]:
            if request.dataset == "TaiwanStockInstitutionalInvestorsBuySell":
                return [investor_row("Unexpected_Investor", 100, 40)]
            return super().fetch_rows(request)

    provider = FinMindProvider(
        data_root=tmp_path,
        no_cache=True,
        client=RenamedInstitutionalClient(),  # type: ignore[arg-type]
    )

    with pytest.raises(FinMindError, match="expected institutional columns"):
        provider.get_institutional_flow(["2330"], date(2024, 1, 2), date(2024, 1, 2))


def test_get_margin_maps_daily_publish_date(tmp_path: Path) -> None:
    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=StaticClient())  # type: ignore[arg-type]

    df = provider.get_margin(["2330"], date(2024, 1, 2), date(2024, 1, 4))

    assert df["publish_date"].to_list() == [
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
    ]
    assert df["margin_balance"].to_list() == [100, 100, 100]
    assert df["short_balance"].to_list() == [10, 10, 10]
    assert df["margin_quota_used_pct"].to_list() == pytest.approx([10.0, 10.0, 10.0])


def test_get_holder_distribution_parses_levels_and_aligns_publish_date(tmp_path: Path) -> None:
    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=StaticClient())  # type: ignore[arg-type]

    df = provider.get_holder_distribution(["2330"], date(2024, 1, 5), date(2024, 1, 16))

    assert df.columns == [
        "symbol",
        "data_date",
        "publish_date",
        "tier",
        "holder_count",
        "share_count",
        "share_pct",
        "share_pct_sum",
        "share_pct_sum_ok",
    ]
    assert df["publish_date"].to_list() == [
        date(2024, 1, 15),
        date(2024, 1, 15),
    ]
    assert df["tier"].to_list() == [1, 400_001]
    assert df["share_pct"].to_list() == pytest.approx([20.0, 80.0])
    assert df["share_pct_sum_ok"].to_list() == [True, True]


def test_get_holder_distribution_saves_raw_payload_by_data_date(tmp_path: Path) -> None:
    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=StaticClient())  # type: ignore[arg-type]

    provider.get_holder_distribution(["2330"], date(2024, 1, 5), date(2024, 1, 16))

    first_raw_dir = tmp_path / "raw" / "tdcc" / "2024-01-05"
    second_raw_dir = tmp_path / "raw" / "tdcc" / "2024-01-12"
    assert list(first_raw_dir.glob("TaiwanStockHoldingSharesPer_2330_*.json"))
    assert list(second_raw_dir.glob("TaiwanStockHoldingSharesPer_2330_*.json"))


def test_holder_distribution_for_multiple_symbols_uses_bulk_per_holder_date(
    tmp_path: Path,
) -> None:
    client = StaticClient()
    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=client)  # type: ignore[arg-type]

    df = provider.get_holder_distribution(
        ["2330", "2317"],
        date(2024, 1, 5),
        date(2024, 1, 16),
    )

    bulk_calls = [
        call
        for call in client.calls
        if call.dataset == "TaiwanStockHoldingSharesPer" and call.data_id is None
    ]
    assert {call.start for call in bulk_calls} == {date(2024, 1, 5), date(2024, 1, 12)}
    assert set(df["symbol"].to_list()) == {"2330", "2317"}


def test_holder_distribution_marks_bad_share_pct_sum(tmp_path: Path) -> None:
    class BadPctClient(StaticClient):
        def fetch_rows(self, request: FinMindRequest) -> list[dict[str, Any]]:
            if request.dataset == "TaiwanStockHoldingSharesPer":
                return [
                    holder_row("2330", "2024-01-05", "1-999", 10, 10.0, 100),
                    holder_row("2330", "2024-01-05", "400,001-600,000", 1, 80.0, 800),
                    holder_row("2330", "2024-01-05", "total", 11, 90.0, 900),
                ]
            return super().fetch_rows(request)

    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=BadPctClient())  # type: ignore[arg-type]

    df = provider.get_holder_distribution(["2330"], date(2024, 1, 5), date(2024, 1, 16))

    assert df["share_pct_sum"].to_list() == pytest.approx([90.0, 90.0])
    assert df["share_pct_sum_ok"].to_list() == [False, False]


def test_unknown_nonzero_holder_level_raises() -> None:
    with pytest.raises(FinMindError, match="Unknown holder share level"):
        parse_holding_level("new unexpected level", {"percent": 1.0, "unit": 100})


def test_holder_daily_alignment_does_not_forward_fill_before_publish_date() -> None:
    import polars as pl

    weekly = pl.DataFrame(
        [
            {
                "symbol": "2330",
                "data_date": date(2024, 1, 5),
                "publish_date": date(2024, 1, 12),
                "tier": 400_001,
                "holder_count": 1,
                "share_count": 800,
                "share_pct": 80.0,
                "share_pct_sum": 100.0,
                "share_pct_sum_ok": True,
            }
        ]
    )
    calendar = TradingCalendar(
        (
            date(2024, 1, 8),
            date(2024, 1, 11),
            date(2024, 1, 12),
            date(2024, 1, 15),
        )
    )

    daily = align_holder_distribution_to_trading_days(
        weekly,
        calendar,
        date(2024, 1, 8),
        date(2024, 1, 15),
    )

    assert daily["as_of_date"].to_list() == [date(2024, 1, 12), date(2024, 1, 15)]
    assert all(
        row <= as_of
        for row, as_of in zip(daily["publish_date"], daily["as_of_date"], strict=True)
    )


def test_monthly_revenue_uses_revenue_month_not_api_date(tmp_path: Path) -> None:
    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=StaticClient())  # type: ignore[arg-type]

    df = provider.get_monthly_revenue(["2330"], date(2024, 1, 1), date(2024, 2, 10))

    assert df["data_date"].to_list() == [date(2024, 1, 31)]
    assert df["publish_date"].to_list() == [date(2024, 2, 10)]
    assert df["revenue"].to_list() == pytest.approx([123.0])


def test_financials_include_statement_and_derived_publish_date(tmp_path: Path) -> None:
    provider = FinMindProvider(data_root=tmp_path, no_cache=True, client=StaticClient())  # type: ignore[arg-type]

    df = provider.get_financials(["2330"], date(2024, 1, 1), date(2024, 6, 30))

    assert set(df["statement"].to_list()) == {"income", "balance", "cash_flow"}
    assert set(df["publish_date"].to_list()) == {date(2024, 5, 15)}


def test_shares_outstanding_cross_check_mismatch_raises(tmp_path: Path) -> None:
    class BadMarketValueClient(StaticClient):
        def fetch_rows(self, request: FinMindRequest) -> list[dict[str, Any]]:
            if request.dataset == "TaiwanStockMarketValue":
                return [
                    {"date": "2024-01-02", "stock_id": "2330", "market_value": 50_000.0},
                    {"date": "2024-01-03", "stock_id": "2330", "market_value": 55_000.0},
                    {"date": "2024-01-04", "stock_id": "2330", "market_value": 45_000.0},
                ]
            return super().fetch_rows(request)

    provider = FinMindProvider(
        data_root=tmp_path,
        no_cache=True,
        client=BadMarketValueClient(),  # type: ignore[arg-type]
    )

    with pytest.raises(FinMindError, match="shares_outstanding cross-check failed"):
        provider.get_ohlcv(["2330"], date(2024, 1, 2), date(2024, 1, 4), adjusted=False)


def test_financial_publish_date_uses_q4_75_days_and_other_quarters_45_days() -> None:
    assert financial_publish_date(date(2024, 3, 31)) == date(2024, 5, 15)
    assert financial_publish_date(date(2024, 12, 31)) == date(2025, 3, 16)


def test_monthly_revenue_publish_date_uses_next_month_tenth() -> None:
    assert month_end(2024, 2) == date(2024, 2, 29)
    assert next_month_tenth(date(2024, 12, 31)) == date(2025, 1, 10)


def test_balance_shares_lookup_is_point_in_time() -> None:
    import polars as pl

    lookup = latest_balance_lookup(
        pl.DataFrame(
            [
                {
                    "symbol": "2330",
                    "publish_date": date(2024, 5, 15),
                    "shares_from_balance_sheet": 1000.0,
                },
                {
                    "symbol": "2330",
                    "publish_date": date(2024, 8, 14),
                    "shares_from_balance_sheet": 1200.0,
                },
            ]
        )
    )

    assert balance_shares_as_of(lookup, "2330", date(2024, 5, 14)) is None
    assert balance_shares_as_of(lookup, "2330", date(2024, 5, 15)) == pytest.approx(1000.0)
    assert balance_shares_as_of(lookup, "2330", date(2024, 8, 13)) == pytest.approx(1000.0)
    assert balance_shares_as_of(lookup, "2330", date(2024, 8, 14)) == pytest.approx(1200.0)


def investor_row(name: str, buy: int, sell: int) -> dict[str, object]:
    return {"date": "2024-01-02", "stock_id": "2330", "name": name, "buy": buy, "sell": sell}


def margin_row(day: str) -> dict[str, object]:
    return {
        "date": day,
        "stock_id": "2330",
        "MarginPurchaseTodayBalance": 100,
        "ShortSaleTodayBalance": 10,
        "MarginPurchaseLimit": 1000,
    }


def holder_rows(symbol: str, day: str) -> list[dict[str, object]]:
    return [
        holder_row(symbol, day, "1-999", 10, 20.0, 200),
        holder_row(symbol, day, "400,001-600,000", 1, 80.0, 800),
        holder_row(symbol, day, "total", 11, 100.0, 1000),
        holder_row(symbol, day, "adjustment", 1, 0.0, -1),
    ]


def holder_row(
    symbol: str,
    day: str,
    level: str,
    people: int,
    percent: float,
    unit: int,
) -> dict[str, object]:
    return {
        "date": day,
        "stock_id": symbol,
        "HoldingSharesLevel": level,
        "people": people,
        "percent": percent,
        "unit": unit,
    }


def filter_requested_dates(
    rows: list[dict[str, object]],
    request: FinMindRequest,
) -> list[dict[str, object]]:
    if request.start is None or request.end is None:
        return rows
    return [
        row
        for row in rows
        if request.start <= date.fromisoformat(str(row["date"])) <= request.end
    ]
