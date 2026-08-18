from typer.testing import CliRunner

from flowscope.cli import app


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
