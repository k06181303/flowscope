from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from flowscope.config.loader import load_config_with_hash

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
    typer.echo(f"{command} is not implemented in Step 1.")


def _parse_iso_date(value: str | None, option_name: str) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise typer.BadParameter(f"{option_name} must be YYYY-MM-DD") from None


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
    weekly: Annotated[
        bool,
        typer.Option("--weekly", help="Synchronize the weekly source cadence."),
    ] = False,
) -> None:
    source_text = f"source={source}"
    parsed_start = _parse_iso_date(start, "--start")
    start_text = f", start={parsed_start}" if parsed_start is not None else ""
    weekly_text = ", weekly=true" if weekly else ""
    typer.echo(f"{source_text}{start_text}{weekly_text}")
    _step_message("data sync")


@data_app.command("validate")
def data_validate() -> None:
    _step_message("data validate")


@diagnose_app.command()
def collinearity(
    market: Annotated[str, typer.Option("--market", help="Market code.")],
    horizon: Annotated[str, typer.Option("--horizon", help="Selection horizon.")],
) -> None:
    typer.echo(f"market={market}, horizon={horizon}")
    _step_message("diagnose collinearity")


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
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="Point-in-time execution date."),
    ] = None,
) -> None:
    parsed_as_of = _parse_iso_date(as_of, "--as-of")
    if parsed_as_of is not None:
        typer.echo(f"as_of={parsed_as_of}")
    _step_message("diagnose funnel")


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
