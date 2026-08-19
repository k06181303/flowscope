from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from flowscope.data.providers.twse import OfficialMarketDataError, OfficialMarketProvider


class StaticOfficialClient:
    def fetch_rows(self, url: str) -> list[dict[str, Any]]:
        if url.endswith("t187ap03_L"):
            return [
                {
                    "公司代號": "2330",
                    "公司簡稱": "台積電",
                    "產業別": "24",
                    "上市日期": "19940905",
                },
                {
                    "公司代號": "9999",
                    "公司簡稱": "未來股",
                    "產業別": "20",
                    "上市日期": "20250101",
                },
            ]
        if url.endswith("mopsfin_t187ap03_O"):
            return [
                {
                    "SecuritiesCompanyCode": "6488",
                    "CompanyAbbreviation": "環球晶",
                    "SecuritiesIndustryCode": "24",
                    "DateOfListing": "20150925",
                }
            ]
        if url.endswith("announcement/notice"):
            return [{"Code": "", "Date": "1130102", "TradingInfoForAttention": "placeholder"}]
        if url.endswith("announcement/punish"):
            return [{"Code": "2330", "Date": "1130103", "DispositionMeasures": "處置"}]
        if url.endswith("exchangeReport/TWT85U"):
            return [{"Code": "2317", "Name": "鴻海"}]
        if url.endswith("tpex_trading_warning_information"):
            return [
                {
                    "SecuritiesCompanyCode": "6488",
                    "Date": "1130104",
                    "TradingInformation": "注意",
                }
            ]
        if url.endswith("tpex_disposal_information"):
            return []
        if url.endswith("tpex_cmode"):
            return [
                {
                    "SecuritiesCompanyCode": "8069",
                    "AlteredTrading": "Y",
                    "ManagedStock": "N",
                    "SuspensionOfTrading": "N",
                }
            ]
        raise AssertionError(f"unexpected url {url}")


def test_official_provider_rebuilds_current_listing_snapshot() -> None:
    provider = OfficialMarketProvider(client=StaticOfficialClient())  # type: ignore[arg-type]

    df = provider.get_listings(date(2024, 8, 18))

    assert df.select("symbol", "market", "listing_date").rows() == [
        ("2330", "TWSE", date(1994, 9, 5)),
        ("6488", "TPEX", date(2015, 9, 25)),
    ]


def test_official_provider_drops_placeholder_warning_rows_and_keeps_active_flags() -> None:
    provider = OfficialMarketProvider(  # type: ignore[arg-type]
        client=StaticOfficialClient(),
        today=date(2024, 8, 18),
    )

    df = provider.get_warnings(date(2024, 8, 18))

    assert df.select("symbol", "warning_type", "data_date").rows() == [
        ("2317", "altered_trading", date(2024, 8, 18)),
        ("2330", "disposition", date(2024, 1, 3)),
        ("6488", "attention", date(2024, 1, 4)),
        ("8069", "altered_trading", date(2024, 8, 18)),
    ]


def test_official_provider_rejects_historical_warning_snapshot() -> None:
    provider = OfficialMarketProvider(  # type: ignore[arg-type]
        client=StaticOfficialClient(),
        today=date(2026, 8, 20),
    )

    with pytest.raises(OfficialMarketDataError, match="historical as_of=2025-08-19"):
        provider.get_warnings(date(2025, 8, 19))


def test_official_provider_rejects_dated_warning_row_without_source_date() -> None:
    class MissingDateClient(StaticOfficialClient):
        def fetch_rows(self, url: str) -> list[dict[str, Any]]:
            if url.endswith("announcement/notice"):
                return [{"Code": "2330", "TradingInfoForAttention": "注意"}]
            return super().fetch_rows(url)

    provider = OfficialMarketProvider(  # type: ignore[arg-type]
        client=MissingDateClient(),
        today=date(2024, 8, 18),
    )

    with pytest.raises(OfficialMarketDataError, match="has no valid source date"):
        provider.get_warnings(date(2024, 8, 18))


def test_official_provider_uses_position_fallback_for_mojibake_twse_keys() -> None:
    class MojibakeTwseClient(StaticOfficialClient):
        def fetch_rows(self, url: str) -> list[dict[str, Any]]:
            if url.endswith("t187ap03_L"):
                return [
                    {
                        "k0": "1130818",
                        "k1": "2330",
                        "k2": "台灣積體電路製造股份有限公司",
                        "k3": "台積電",
                        "k4": "",
                        "k5": "24",
                        "k6": "",
                        "k7": "",
                        "k8": "",
                        "k9": "",
                        "k10": "",
                        "k11": "",
                        "k12": "",
                        "k13": "",
                        "k14": "19870221",
                        "k15": "19940905",
                    }
                ]
            if url.endswith("mopsfin_t187ap03_O"):
                return []
            return super().fetch_rows(url)

    provider = OfficialMarketProvider(client=MojibakeTwseClient())  # type: ignore[arg-type]

    listings = provider.get_listings(date(2024, 8, 18))

    assert listings.select("symbol", "name", "industry", "listing_date").rows() == [
        ("2330", "台積電", "24", date(1994, 9, 5))
    ]


def test_official_provider_rejects_empty_listings() -> None:
    class EmptyClient(StaticOfficialClient):
        def fetch_rows(self, url: str) -> list[dict[str, Any]]:
            if url.endswith("t187ap03_L") or url.endswith("mopsfin_t187ap03_O"):
                return []
            return super().fetch_rows(url)

    provider = OfficialMarketProvider(client=EmptyClient())  # type: ignore[arg-type]

    with pytest.raises(OfficialMarketDataError, match="no usable rows"):
        provider.get_listings(date(2024, 8, 18))
