from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from flowscope.config.loader import load_config_with_hash
from flowscope.config.schema import FlowScopeConfig
from flowscope.data.providers.finmind import FinMindError, FinMindProvider
from flowscope.data.providers.twse import OfficialMarketDataError, OfficialMarketProvider
from flowscope.factors.diagnostics import (
    correlation_pair_details,
    render_spearman_report,
    spearman_matrix,
)
from flowscope.factors.technical import (
    TECHNICAL_FACTORS,
    compute_technical_factor_history,
)
from flowscope.universe.builder import build_l0_universe, build_universe_funnel, render_funnel
from flowscope.universe.gates import UniverseGateError

app = typer.Typer(
    help="FlowScope Taiwan stock selection and trade plan generator.",
    no_args_is_help=True,
)
data_app = typer.Typer(help="Data maintenance commands.", no_args_is_help=True)
diagnose_app = typer.Typer(help="Diagnostic commands.", no_args_is_help=True)
report_app = typer.Typer(help="Report commands.", no_args_is_help=True)

app.add_typer(data_app, name="data")
app.add_typer(diagnose_app, name="diagnose")
app.add_typer(report_app, name="report")


def _step_message(command: str) -> None:
    typer.echo(f"{command} is not implemented in the current SPEC step.")


def _parse_iso_date(value: str | None, option_name: str) -> str | None:
    parsed = _parse_date(value, option_name)
    return parsed.isoformat() if parsed is not None else None


def _parse_date(value: str | None, option_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise typer.BadParameter(f"{option_name} must be YYYY-MM-DD") from None


def _parse_snapshot_date(value: str | None, option_name: str) -> date | None:
    if value == "today":
        return date.today()
    return _parse_date(value, option_name)


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Path to a FlowScope YAML config.",
        ),
    ],
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="Point-in-time execution date."),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Bypass local data cache."),
    ] = False,
) -> None:
    loaded = load_config_with_hash(config)
    as_of_text = _parse_iso_date(as_of, "--as-of") or "latest available date"
    cache_text = "disabled" if no_cache else "enabled"
    typer.echo(
        "Config loaded: "
        f"market={loaded.config.market}, "
        f"horizon={loaded.config.horizon}, "
        f"as_of={as_of_text}, "
        f"cache={cache_text}, "
        f"config_hash={loaded.config_hash}"
    )
    _step_message("run")


@data_app.command("sync")
def data_sync(
    source: Annotated[str, typer.Option("--source", help="Data source identifier.")],
    start: Annotated[
        str | None,
        typer.Option("--start", help="First data date to synchronize."),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option("--end", help="Last data date to synchronize."),
    ] = None,
    symbol: Annotated[
        str,
        typer.Option("--symbol", help="Single symbol used for Step 2 OHLCV verification."),
    ] = "2330",
    weekly: Annotated[
        bool,
        typer.Option("--weekly", help="Synchronize the weekly source cadence."),
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Bypass local data cache."),
    ] = False,
) -> None:
    if source != "finmind":
        raise typer.BadParameter("data sync currently supports --source finmind")

    parsed_end = _parse_date(end, "--end") or date.today()
    parsed_start = _parse_date(start, "--start") or parsed_end - timedelta(days=366 * 3)
    if parsed_start > parsed_end:
        raise typer.BadParameter("--start must be on or before --end")

    try:
        provider = FinMindProvider(no_cache=no_cache)
        if weekly:
            holder = provider.get_holder_distribution([symbol], parsed_start, parsed_end)
            typer.echo(
                "Synced holder distribution: "
                f"source=finmind, symbol={symbol}, start={parsed_start.isoformat()}, "
                f"end={parsed_end.isoformat()}, rows={holder.height}"
            )
            return
        ohlcv = provider.get_ohlcv([symbol], parsed_start, parsed_end, adjusted=True)
    except FinMindError as exc:
        typer.secho(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(
        "Synced adjusted OHLCV: "
        f"source=finmind, symbol={symbol}, start={parsed_start.isoformat()}, "
        f"end={parsed_end.isoformat()}, rows={ohlcv.height}"
    )


@data_app.command("validate")
def data_validate() -> None:
    _step_message("data validate")


@diagnose_app.command()
def collinearity(
    market: Annotated[str, typer.Option("--market", help="Market code.")],
    horizon: Annotated[str, typer.Option("--horizon", help="Selection horizon.")],
    input_path: Annotated[
        Path | None,
        typer.Option(
            "--input",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Parquet file containing symbol/factor_id/raw_value.",
        ),
    ] = None,
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Path to a FlowScope YAML config.",
        ),
    ] = Path("configs/tw_swing.yaml"),
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="Point-in-time end date."),
    ] = None,
    lookback: Annotated[
        int,
        typer.Option("--lookback", min=2, help="Number of trading-day cross-sections."),
    ] = 250,
    factor_output: Annotated[
        Path,
        typer.Option("--factor-output", help="PIT factor-history Parquet output path."),
    ] = Path("data/processed/technical_factors.parquet"),
    csv_output: Annotated[
        Path,
        typer.Option("--csv-output", help="Spearman matrix CSV output path."),
    ] = Path("data/processed/technical_factor_spearman.csv"),
    threshold: Annotated[
        float,
        typer.Option("--threshold", min=0.0, max=1.0, help="Absolute rho warning threshold."),
    ] = 0.7,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Bypass local data cache."),
    ] = False,
) -> None:
    loaded = load_config_with_hash(config)
    technical = loaded.config.factors.technical
    if market != loaded.config.market or horizon != loaded.config.horizon:
        raise typer.BadParameter("--market/--horizon must match the loaded config")
    try:
        factors = (
            pl.read_parquet(input_path)
            if input_path is not None
            else build_collinearity_factor_history(
                loaded.config,
                _parse_date(as_of, "--as-of") or date.today(),
                lookback,
                factor_output,
                no_cache=no_cache,
            )
        )
        matrix = spearman_matrix(factors)
        pairs = correlation_pair_details(
            factors,
            matrix,
            threshold,
            technical.factor_priority,
        )
        csv_output.parent.mkdir(parents=True, exist_ok=True)
        matrix.write_csv(csv_output)
    except (
        FinMindError,
        OfficialMarketDataError,
        UniverseGateError,
        OSError,
        ValueError,
        pl.exceptions.PolarsError,
    ) as exc:
        typer.secho(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        render_spearman_report(
            matrix,
            pairs,
            market=market,
            horizon=horizon,
            lookback=lookback,
            as_of_count=factors["as_of"].n_unique(),
            symbol_count=factors["symbol"].n_unique(),
            threshold=threshold,
        )
    )
    typer.echo(f"CSV: {csv_output}")


def build_collinearity_factor_history(
    config: FlowScopeConfig,
    as_of: date,
    lookback: int,
    output_path: Path,
    *,
    no_cache: bool,
) -> pl.DataFrame:
    provider = FinMindProvider(no_cache=no_cache)
    l0 = build_l0_universe(config, as_of, provider, OfficialMarketProvider())
    symbols = [str(symbol) for symbol in l0.application.frame["symbol"]]
    if not symbols:
        raise UniverseGateError("L0 universe is empty")

    maximum_history = max(factor.min_history_days for factor in TECHNICAL_FACTORS.values())
    required_sessions = lookback + maximum_history - 1
    calendar_start = l0.latest_trade_date - timedelta(days=required_sessions * 2 + 60)
    calendar = provider.get_trading_calendar(calendar_start, l0.latest_trade_date)
    history_dates = calendar.trailing_dates(l0.latest_trade_date, required_sessions)
    if len(history_dates) != required_sessions:
        raise FinMindError(
            f"Trading calendar has {len(history_dates)} sessions; "
            f"collinearity requires {required_sessions}"
        )
    as_of_dates = history_dates[-lookback:]
    prices = provider.get_adjusted_price_history(
        symbols,
        history_dates[0],
        l0.latest_trade_date,
    )
    benchmark = provider.get_benchmark_history(
        history_dates[0],
        l0.latest_trade_date,
    ).select("data_date", "benchmark_close")
    panel = prices.join(benchmark, on="data_date", how="left")
    factors = compute_technical_factor_history(
        panel,
        as_of_dates,
        sorted(TECHNICAL_FACTORS),
        config.factors.technical.all_params,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    factors.write_parquet(output_path)
    return factors


@diagnose_app.command()
def sensitivity(
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="Point-in-time execution date."),
    ] = None,
) -> None:
    parsed_as_of = _parse_iso_date(as_of, "--as-of")
    if parsed_as_of is not None:
        typer.echo(f"as_of={parsed_as_of}")
    _step_message("diagnose sensitivity")


@diagnose_app.command()
def funnel(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Path to a FlowScope YAML config.",
        ),
    ] = Path("configs/tw_swing.yaml"),
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="Point-in-time data cutoff date."),
    ] = None,
    price_as_of: Annotated[
        str | None,
        typer.Option(
            "--price-as-of",
            help="Price cutoff; set to the latest completed trading date before market close.",
        ),
    ] = None,
    warnings_snapshot: Annotated[
        str | None,
        typer.Option(
            "--warnings-snapshot",
            help="Official warning snapshot date (YYYY-MM-DD or 'today').",
        ),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Bypass local data cache."),
    ] = False,
) -> None:
    loaded = load_config_with_hash(config)
    parsed_as_of = _parse_date(as_of, "--as-of") or date.today()
    parsed_price_as_of = _parse_date(price_as_of, "--price-as-of") or parsed_as_of
    parsed_warnings_snapshot = (
        _parse_snapshot_date(warnings_snapshot, "--warnings-snapshot") or parsed_as_of
    )
    try:
        report = build_universe_funnel(
            loaded.config,
            parsed_as_of,
            FinMindProvider(no_cache=no_cache),
            OfficialMarketProvider(),
            price_as_of=parsed_price_as_of,
            warnings_snapshot=parsed_warnings_snapshot,
        )
    except (FinMindError, OfficialMarketDataError, UniverseGateError) as exc:
        typer.secho(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(render_funnel(report))


@app.command()
def backfill(
    horizon_days: Annotated[
        int,
        typer.Option("--horizon-days", min=1, help="Forward-return horizon in trading days."),
    ] = 20,
) -> None:
    typer.echo(f"horizon_days={horizon_days}")
    _step_message("backfill")


@report_app.command("performance")
def report_performance(
    since: Annotated[
        str | None,
        typer.Option("--since", help="First run date included in the report."),
    ] = None,
    group_by: Annotated[
        str | None,
        typer.Option("--group-by", help="Report grouping key."),
    ] = None,
) -> None:
    parsed_since = _parse_iso_date(since, "--since")
    if parsed_since is not None:
        typer.echo(f"since={parsed_since}")
    if group_by is not None:
        typer.echo(f"group_by={group_by}")
    _step_message("report performance")


@report_app.command("run")
def report_run(
    run_id: Annotated[str, typer.Option("--run-id", help="Run identifier.")],
) -> None:
    typer.echo(f"run_id={run_id}")
    _step_message("report run")


def main() -> None:
    app()
