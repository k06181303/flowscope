from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from flowscope.data.providers.finmind import FinMindClient, FinMindError, FinMindRequest


class Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_finmind_client_extracts_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    def urlopen(url: str, timeout: int) -> Response:
        assert "token=secret" in url
        assert timeout == 60
        return Response({"msg": "success", "data": [{"stock_id": "2330"}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = FinMindClient("secret", request_interval_seconds=0)

    rows = client.fetch_rows(FinMindRequest("TaiwanStockPrice", "2330", None, None))

    assert rows == [{"stock_id": "2330"}]


def test_finmind_client_rejects_permission_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def urlopen(url: str, timeout: int) -> Response:
        return Response({"msg": "Your level is register", "data": []})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = FinMindClient("secret", request_interval_seconds=0, max_attempts=1)

    with pytest.raises(FinMindError, match="permission denied"):
        client.fetch_rows(FinMindRequest("TaiwanStockPriceAdj", "2330", None, None))


def test_finmind_client_rejects_empty_data(monkeypatch: pytest.MonkeyPatch) -> None:
    def urlopen(url: str, timeout: int) -> Response:
        return Response({"msg": "success", "data": []})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = FinMindClient("secret", request_interval_seconds=0, max_attempts=1)

    with pytest.raises(FinMindError, match="returned no rows"):
        client.fetch_rows(FinMindRequest("TaiwanStockPrice", "2330", None, None))


def test_finmind_client_retries_transient_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def urlopen(url: str, timeout: int) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(url, 500, "server error", {}, None)
        return Response({"msg": "success", "data": [{"stock_id": "2330"}]})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    client = FinMindClient("secret", request_interval_seconds=0, max_attempts=2)

    rows = client.fetch_rows(FinMindRequest("TaiwanStockPrice", "2330", None, None))

    assert calls == 2
    assert rows == [{"stock_id": "2330"}]
