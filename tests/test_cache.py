import os
from datetime import date, datetime

import polars as pl

from flowscope.data.cache import CacheKey, ParquetCache, stable_symbol_hash


def test_cache_key_uses_sorted_symbol_hash() -> None:
    assert stable_symbol_hash(["2330", "2317"]) == stable_symbol_hash(["2317", "2330"])


def test_no_cache_forces_fetch(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cache = ParquetCache(tmp_path)
    key = CacheKey(
        provider="finmind",
        method="get_ohlcv_raw",
        symbol_hash="abc",
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
    )
    calls = 0

    def fetch() -> pl.DataFrame:
        nonlocal calls
        calls += 1
        return pl.DataFrame({"value": [calls]})

    first = cache.get_or_fetch(key, fetch, no_cache=False, today=date(2024, 1, 2))
    second = cache.get_or_fetch(key, fetch, no_cache=False, today=date(2024, 1, 2))
    third = cache.get_or_fetch(key, fetch, no_cache=True, today=date(2024, 1, 2))

    assert first["value"].to_list() == [1]
    assert second["value"].to_list() == [1]
    assert third["value"].to_list() == [2]


def test_explicitly_allowed_empty_result_is_cached(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cache = ParquetCache(tmp_path)
    key = CacheKey(
        provider="finmind",
        method="daily_bulk_TaiwanStockDividendResult",
        symbol_hash="all",
        start=date(2024, 1, 2),
        end=date(2024, 1, 2),
    )
    calls = 0

    def fetch() -> pl.DataFrame:
        nonlocal calls
        calls += 1
        return pl.DataFrame(schema={"date": pl.Utf8, "stock_id": pl.Utf8})

    first = cache.get_or_fetch(key, fetch, no_cache=False, cache_empty=True)
    second = cache.get_or_fetch(key, fetch, no_cache=False, cache_empty=True)

    assert first.is_empty()
    assert second.is_empty()
    assert calls == 1


def test_financial_cache_refreshes_until_publish_deadline_then_becomes_immutable(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    cache = ParquetCache(tmp_path)
    key = CacheKey(
        provider="finmind",
        method="get_financials",
        symbol_hash="abc",
        start=date(2024, 1, 1),
        end=date(2024, 6, 30),
    )
    calls = 0

    def fetch() -> pl.DataFrame:
        nonlocal calls
        calls += 1
        return pl.DataFrame({"value": [calls]})

    cache.get_or_fetch(
        key,
        fetch,
        no_cache=False,
        today=date(2024, 8, 1),
        immutable_after=date(2024, 8, 14),
    )
    path = cache.path_for(key)
    old_timestamp = datetime(2024, 8, 1).timestamp()
    os.utime(path, (old_timestamp, old_timestamp))

    refreshed = cache.get_or_fetch(
        key,
        fetch,
        no_cache=False,
        today=date(2024, 8, 2),
        immutable_after=date(2024, 8, 14),
    )
    os.utime(path, (old_timestamp, old_timestamp))
    immutable = cache.get_or_fetch(
        key,
        fetch,
        no_cache=False,
        today=date(2024, 8, 15),
        immutable_after=date(2024, 8, 14),
    )

    assert refreshed["value"].to_list() == [2]
    assert immutable["value"].to_list() == [2]
    assert calls == 2
