from datetime import date

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
