from datetime import date
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from flowscope.cli import app
from flowscope.factors.diagnostics import (
    correlation_pair_details,
    effective_degrees_of_freedom,
    fisher_rho_confidence_interval,
    high_correlation_pairs,
    pairwise_spearman,
    render_spearman_report,
    spearman_matrix,
)


def test_spearman_matrix_uses_average_tie_ranks_and_pairwise_nulls() -> None:
    factors = pl.DataFrame(
        {
            "as_of": [date(2026, 8, 20)] * 12,
            "symbol": ["A", "B", "C", "D"] * 3,
            "factor_id": ["T01"] * 4 + ["T02"] * 4 + ["T03"] * 4,
            "raw_value": [1.0, 2.0, 2.0, 4.0, 10.0, 20.0, 20.0, 40.0, None, 3.0, 2.0, 1.0],
        }
    )

    matrix = spearman_matrix(factors)

    # 獨立手算:T01/T02 的 average ranks 都是 [1,2.5,2.5,4]，rho=1。
    assert matrix.filter(pl.col("factor_id") == "T01")["T02"][0] == pytest.approx(1.0)
    # T01/T03 pairwise 排除 A 後，rank [1.5,1.5,3] vs [3,2,1]，rho=-sqrt(3)/2。
    assert matrix.filter(pl.col("factor_id") == "T01")["T03"][0] == pytest.approx(
        -(3**0.5) / 2
    )
    assert high_correlation_pairs(matrix, 0.7)[0] == ("T01", "T02", pytest.approx(1.0))


def test_pairwise_spearman_returns_null_for_constant_values() -> None:
    assert pairwise_spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_fisher_interval_and_effective_degrees_of_freedom() -> None:
    low, high = fisher_rho_confidence_interval(0.8077, 40)
    matrix = pl.DataFrame(
        {"factor_id": ["T01", "T02"], "T01": [1.0, -1.0], "T02": [-1.0, 1.0]}
    )

    assert low == pytest.approx(0.663, abs=0.001)
    assert high == pytest.approx(0.894, abs=0.001)
    # 完全共線的兩因子只有一個有效自由度：2^2 / sum(R_ij^2) = 4/4 = 1。
    assert effective_degrees_of_freedom(matrix) == pytest.approx(1.0)


def test_render_and_cli_output_correlation_matrix(tmp_path: Path) -> None:
    factors = pl.DataFrame(
        {
            "as_of": [date(2026, 8, 20)] * 6,
            "symbol": ["A", "B", "C", "A", "B", "C"],
            "factor_id": ["T01", "T01", "T01", "T02", "T02", "T02"],
            "raw_value": [1.0, 2.0, 3.0, 3.0, 2.0, 1.0],
        }
    )
    path = tmp_path / "factors.parquet"
    factors.write_parquet(path)
    matrix = spearman_matrix(factors)
    pairs = correlation_pair_details(factors, matrix, 0.7, ["T01", "T02"])
    report = render_spearman_report(
        matrix,
        pairs,
        market="TW",
        horizon="swing",
        lookback=250,
        as_of_count=1,
        symbol_count=3,
        threshold=0.7,
    )

    assert "T01/T02: rho=-1.0000, n=3" in report
    assert "suggested_keep=T01" in report
    csv_path = tmp_path / "matrix.csv"
    result = CliRunner().invoke(
        app,
        [
            "diagnose",
            "collinearity",
            "--market",
            "TW",
            "--horizon",
            "swing",
            "--input",
            str(path),
            "--csv-output",
            str(csv_path),
        ],
    )
    assert result.exit_code == 0
    assert "Technical factor Spearman correlation" in result.output
    assert "T01/T02: rho=-1.0000, n=3" in result.output
    assert csv_path.is_file()
