from __future__ import annotations

import http.client
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

import polars as pl

TWSE_BASE_URL = "https://openapi.twse.com.tw/v1"
TPEX_BASE_URL = "https://www.tpex.org.tw/openapi/v1"
USER_AGENT = "FlowScope/0.1"


class OfficialMarketDataError(RuntimeError):
    """Raised when official TWSE/TPEx OpenAPI data cannot be used."""


@dataclass(frozen=True)
class OfficialEndpoint:
    market: str
    source: str
    url: str


LISTING_ENDPOINTS = (
    OfficialEndpoint("TWSE", "twse_company_profile", f"{TWSE_BASE_URL}/opendata/t187ap03_L"),
    OfficialEndpoint("TPEX", "tpex_company_profile", f"{TPEX_BASE_URL}/mopsfin_t187ap03_O"),
)

WARNING_ENDPOINTS = (
    OfficialEndpoint("TWSE", "twse_attention", f"{TWSE_BASE_URL}/announcement/notice"),
    OfficialEndpoint("TWSE", "twse_disposition", f"{TWSE_BASE_URL}/announcement/punish"),
    OfficialEndpoint("TWSE", "twse_altered_trading", f"{TWSE_BASE_URL}/exchangeReport/TWT85U"),
    OfficialEndpoint("TPEX", "tpex_attention", f"{TPEX_BASE_URL}/tpex_trading_warning_information"),
    OfficialEndpoint("TPEX", "tpex_disposition", f"{TPEX_BASE_URL}/tpex_disposal_information"),
    OfficialEndpoint("TPEX", "tpex_altered_trading", f"{TPEX_BASE_URL}/tpex_cmode"),
)

class OfficialOpenApiClient:
    def fetch_rows(self, url: str) -> list[dict[str, Any]]:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8-sig"))
        except urllib.error.HTTPError as exc:
            raise OfficialMarketDataError(f"Official OpenAPI HTTP {exc.code}: {url}") from exc
        except urllib.error.URLError as exc:
            if not isinstance(exc.reason, ssl.SSLError):
                raise OfficialMarketDataError(
                    f"Official OpenAPI request failed: {url}: {exc.reason}"
                ) from exc
            try:
                # Windows 的本機憑證鏈偶爾無法驗過 TWSE OpenAPI；只在 SSL 驗證失敗時重試。
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(request, timeout=30, context=context) as response:
                    payload = json.loads(response.read().decode("utf-8-sig"))
            except (urllib.error.URLError, json.JSONDecodeError) as retry_exc:
                raise OfficialMarketDataError(
                    f"Official OpenAPI request failed after SSL fallback: {url}"
                ) from retry_exc
        except http.client.IncompleteRead:
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8-sig"))
            except (
                http.client.IncompleteRead,
                urllib.error.HTTPError,
                urllib.error.URLError,
                json.JSONDecodeError,
            ) as retry_exc:
                raise OfficialMarketDataError(
                    f"Official OpenAPI response remained incomplete after retry: {url}"
                ) from retry_exc
        except json.JSONDecodeError as exc:
            raise OfficialMarketDataError(f"Official OpenAPI returned invalid JSON: {url}") from exc

        if not isinstance(payload, list):
            raise OfficialMarketDataError(f"Official OpenAPI returned non-list payload: {url}")
        if not all(isinstance(row, dict) for row in payload):
            raise OfficialMarketDataError(f"Official OpenAPI returned malformed rows: {url}")
        return payload


class OfficialMarketProvider:
    def __init__(
        self,
        client: OfficialOpenApiClient | None = None,
        *,
        today: date | None = None,
    ) -> None:
        self._client = client or OfficialOpenApiClient()
        self._today = today or date.today()

    def get_listings(self, as_of: date) -> pl.DataFrame:
        rows: list[dict[str, object]] = []
        for endpoint in LISTING_ENDPOINTS:
            for row in self._client.fetch_rows(endpoint.url):
                parsed = parse_listing_row(endpoint, row, as_of)
                if parsed is not None:
                    rows.append(parsed)
        if not rows:
            raise OfficialMarketDataError("Official listings returned no usable rows")
        return pl.DataFrame(rows).unique(subset=["symbol"], keep="first").sort("symbol")

    def get_warnings(self, as_of: date) -> pl.DataFrame:
        if as_of != self._today:
            snapshot_direction = "historical" if as_of < self._today else "future"
            raise OfficialMarketDataError(
                "Official altered-trading endpoints are undated current snapshots; "
                f"{snapshot_direction} as_of={as_of.isoformat()} cannot be evaluated "
                "without misdating the snapshot"
            )
        rows: list[dict[str, object]] = []
        raw_source_count = 0
        for endpoint in WARNING_ENDPOINTS:
            source_rows = self._client.fetch_rows(endpoint.url)
            raw_source_count += len(source_rows)
            rows.extend(parse_warning_rows(endpoint, source_rows, as_of))
        if raw_source_count == 0:
            raise OfficialMarketDataError("Official warning endpoints returned no source rows")
        return warning_frame(rows)


def parse_listing_row(
    endpoint: OfficialEndpoint,
    row: dict[str, Any],
    as_of: date,
) -> dict[str, object] | None:
    if endpoint.market == "TWSE":
        symbol = normalize_symbol(row_value(row, ("公司代號",), 1))
        name = str(row_value(row, ("公司簡稱",), 3) or "").strip()
        industry = str(row_value(row, ("產業別",), 5) or "").strip()
        listed_at = parse_yyyymmdd(str(row_value(row, ("上市日期",), 15) or ""))
    else:
        symbol = normalize_symbol(row.get("SecuritiesCompanyCode"))
        name = str(row.get("CompanyAbbreviation", "")).strip()
        industry = str(row.get("SecuritiesIndustryCode", "")).strip()
        listed_at = parse_yyyymmdd(str(row.get("DateOfListing", "")))
    if symbol is None or listed_at is None or listed_at > as_of:
        return None
    return {
        "symbol": symbol,
        "name": name,
        "market": endpoint.market,
        "industry": industry,
        "listing_date": listed_at,
        "delisting_date": None,
        "security_type": "COMMON_STOCK",
        "source": endpoint.source,
    }


def parse_warning_rows(
    endpoint: OfficialEndpoint,
    rows: list[dict[str, Any]],
    as_of: date,
) -> list[dict[str, object]]:
    parsed: list[dict[str, object]] = []
    for row in rows:
        record = parse_warning_row(endpoint, row, as_of)
        if record is not None:
            parsed.append(record)
    return parsed


def parse_warning_row(
    endpoint: OfficialEndpoint,
    row: dict[str, Any],
    as_of: date,
) -> dict[str, object] | None:
    symbol = warning_symbol(endpoint, row)
    if symbol is None:
        return None
    warning_type = warning_type_for(endpoint, row)
    if warning_type is None:
        return None
    data_date = warning_date(endpoint, row, as_of)
    return {
        "symbol": symbol,
        "data_date": data_date,
        "publish_date": data_date,
        "warning_type": warning_type,
        "market": endpoint.market,
        "source": endpoint.source,
        "reason": warning_reason(endpoint, row),
    }


def warning_symbol(endpoint: OfficialEndpoint, row: dict[str, Any]) -> str | None:
    if endpoint.market == "TWSE":
        return normalize_symbol(row.get("Code"))
    return normalize_symbol(row.get("SecuritiesCompanyCode"))


def warning_date(endpoint: OfficialEndpoint, row: dict[str, Any], as_of: date) -> date:
    if endpoint.source in {"twse_altered_trading", "tpex_altered_trading"}:
        return as_of
    parsed = parse_roc_compact(str(row.get("Date", "")))
    if parsed is None:
        raise OfficialMarketDataError(
            f"{endpoint.source} warning row has no valid source date"
        )
    return parsed


def warning_type_for(endpoint: OfficialEndpoint, row: dict[str, Any]) -> str | None:
    if "attention" in endpoint.source:
        return "attention"
    if "disposition" in endpoint.source:
        return "disposition"
    if endpoint.source == "twse_altered_trading":
        return "altered_trading"
    if endpoint.source == "tpex_altered_trading":
        active_flags = [
            str(row.get("AlteredTrading", "")).strip(),
            str(row.get("ManagedStock", "")).strip(),
            str(row.get("SuspensionOfTrading", "")).strip(),
        ]
        return "altered_trading" if any(flag in {"Y", "是"} for flag in active_flags) else None
    return None


def warning_reason(endpoint: OfficialEndpoint, row: dict[str, Any]) -> str:
    for key in (
        "TradingInfoForAttention",
        "ReasonsOfDisposition",
        "DispositionMeasures",
        "TradingInformation",
        "DispositionReasons",
        "DisposalCondition",
    ):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return endpoint.source


def warning_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    schema = {
        "symbol": pl.Utf8,
        "data_date": pl.Date,
        "publish_date": pl.Date,
        "warning_type": pl.Utf8,
        "market": pl.Utf8,
        "source": pl.Utf8,
        "reason": pl.Utf8,
    }
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(rows, schema=schema).unique().sort(["symbol", "warning_type"])


def row_value(row: dict[str, Any], keys: tuple[str, ...], position: int) -> object | None:
    for key in keys:
        if key in row:
            return cast(object, row[key])
    values = list(row.values())
    if 0 <= position < len(values):
        return cast(object, values[position])
    return None


def normalize_symbol(value: object) -> str | None:
    symbol = str(value or "").strip()
    if not symbol:
        return None
    return symbol


def parse_yyyymmdd(text: str) -> date | None:
    raw = text.strip().replace("/", "")
    if len(raw) != 8 or not raw.isdigit():
        return None
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def parse_roc_compact(text: str) -> date | None:
    raw = text.strip().replace("/", "").replace("-", "")
    if len(raw) != 7 or not raw.isdigit():
        return None
    return date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:7]))
