from datetime import date

import polars as pl
import pytest
from typer.testing import CliRunner

from flowscope.cli import app
from flowscope.universe.builder import UniverseFunnel
from flowscope.universe.gates import GateApplication


def test_help_lists_spec_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.output
    assert "data" in result.output
    assert "diagnose" in result.output
    assert "report" in result.output


def test_run_loads_config() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", "--config", "configs/tw_swing.yaml", "--as-of", "2026-08-18"],
    )

    assert result.exit_code == 0
    assert "market=TW" in result.output
    assert "horizon=swing" in result.output
    assert "config_hash=sha256:" in result.output


def test_funnel_passes_explicit_price_and_current_warning_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, date | None] = {}

    def fake_build(
        config: object,
        as_of: date,
        data_provider: object,
        market_provider: object,
        *,
        price_as_of: date | None = None,
        warnings_snapshot: date | None = None,
    ) -> UniverseFunnel:
        del config, data_provider, market_provider
        captured.update(
            as_of=as_of,
            price_as_of=price_as_of,
            warnings_snapshot=warnings_snapshot,
        )
        empty = GateApplication(pl.DataFrame(schema={"symbol": pl.Utf8}), ())
        return UniverseFunnel(
            as_of=as_of,
            price_as_of=price_as_of or as_of,
            warnings_snapshot=warnings_snapshot or as_of,
            market="TW",
            initial_count=0,
            l0=empty,
            l1=empty,
            top_n=30,
        )

    monkeypatch.setattr("flowscope.cli.FinMindProvider", lambda **kwargs: object())
    monkeypatch.setattr("flowscope.cli.OfficialMarketProvider", lambda: object())
    monkeypatch.setattr("flowscope.cli.build_universe_funnel", fake_build)

    result = CliRunner().invoke(
        app,
        [
            "diagnose",
            "funnel",
            "--as-of",
            "2026-08-20",
            "--price-as-of",
            "2026-08-19",
            "--warnings-snapshot",
            "today",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "as_of": date(2026, 8, 20),
        "price_as_of": date(2026, 8, 19),
        "warnings_snapshot": date.today(),
    }
    assert "price_as_of=2026-08-19" in result.output
    assert f"warnings_snapshot={date.today().isoformat()}" in result.output
