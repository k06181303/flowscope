from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl


def stable_symbol_hash(symbols: list[str]) -> str:
    normalized = "\n".join(sorted(symbols))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class CacheKey:
    provider: str
    method: str
    symbol_hash: str
    start: date
    end: date

    def filename(self) -> str:
        raw = "|".join(
            [
                self.provider,
                self.method,
                self.symbol_hash,
                self.start.isoformat(),
                self.end.isoformat(),
            ]
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"{digest}.parquet"


class ParquetCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: CacheKey) -> Path:
        return self.root / key.provider / key.method / key.filename()

    def get_or_fetch(
        self,
        key: CacheKey,
        fetch: Callable[[], pl.DataFrame],
        *,
        no_cache: bool,
        today: date | None = None,
        immutable_after: date | None = None,
        cache_empty: bool = False,
    ) -> pl.DataFrame:
        path = self.path_for(key)
        if not no_cache and path.is_file() and self._is_valid(
            path,
            key.end,
            today,
            immutable_after,
        ):
            return pl.read_parquet(path)

        df = fetch()
        if df.is_empty() and not cache_empty:
            raise ValueError(f"Refusing to cache an empty result for {key.provider}.{key.method}")
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
        return df

    def _is_valid(
        self,
        path: Path,
        end: date,
        today: date | None,
        immutable_after: date | None,
    ) -> bool:
        effective_today = today or datetime.now().date()
        if immutable_after is not None:
            if effective_today > immutable_after:
                return True
            modified_date = datetime.fromtimestamp(path.stat().st_mtime).date()
            return modified_date >= effective_today
        if end < effective_today - timedelta(days=30):
            return True
        modified_date = datetime.fromtimestamp(path.stat().st_mtime).date()
        return modified_date >= effective_today
