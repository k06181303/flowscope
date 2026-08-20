from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations

import polars as pl


@dataclass(frozen=True)
class CorrelationPair:
    left: str
    right: str
    rho: float
    sample_size: int
    ci_low: float | None
    ci_high: float | None
    suggested_keep: str


def spearman_matrix(factors: pl.DataFrame) -> pl.DataFrame:
    wide, factor_ids = factor_values_wide(factors)
    rows: list[dict[str, object]] = []
    for left in factor_ids:
        row: dict[str, object] = {"factor_id": left}
        for right in factor_ids:
            if left == right:
                values = wide.select(left).drop_nulls()[left].to_list()
                row[right] = pairwise_spearman(values, values)
                continue
            pair = wide.select(left, right).drop_nulls()
            row[right] = pairwise_spearman(pair[left].to_list(), pair[right].to_list())
        rows.append(row)
    return pl.DataFrame(rows).sort("factor_id")


def correlation_pair_details(
    factors: pl.DataFrame,
    matrix: pl.DataFrame,
    threshold: float,
    factor_priority: list[str],
) -> list[CorrelationPair]:
    wide, factor_ids = factor_values_wide(factors)
    lookup = {str(row["factor_id"]): row for row in matrix.iter_rows(named=True)}
    priority = {factor_id: index for index, factor_id in enumerate(factor_priority)}
    missing_priority = sorted(set(factor_ids) - set(priority))
    if missing_priority:
        raise ValueError(f"factor_priority missing factor IDs: {', '.join(missing_priority)}")

    pairs: list[CorrelationPair] = []
    for left, right in combinations(factor_ids, 2):
        value = lookup[left][right]
        if value is None or abs(float(value)) <= threshold:
            continue
        rho = float(value)
        sample_size = wide.select(left, right).drop_nulls().height
        ci_low, ci_high = fisher_rho_confidence_interval(rho, sample_size)
        suggested_keep = left if priority[left] < priority[right] else right
        pairs.append(
            CorrelationPair(
                left=left,
                right=right,
                rho=rho,
                sample_size=sample_size,
                ci_low=ci_low,
                ci_high=ci_high,
                suggested_keep=suggested_keep,
            )
        )
    return sorted(pairs, key=lambda pair: (-abs(pair.rho), pair.left, pair.right))


def high_correlation_pairs(
    matrix: pl.DataFrame,
    threshold: float,
) -> list[tuple[str, str, float]]:
    factor_ids = [str(value) for value in matrix["factor_id"]]
    lookup = {str(row["factor_id"]): row for row in matrix.iter_rows(named=True)}
    pairs = []
    for left, right in combinations(factor_ids, 2):
        value = lookup[left][right]
        if value is not None and abs(float(value)) > threshold:
            pairs.append((left, right, float(value)))
    return sorted(pairs, key=lambda pair: (-abs(pair[2]), pair[0], pair[1]))


def effective_degrees_of_freedom(matrix: pl.DataFrame) -> float:
    factor_ids = [str(value) for value in matrix["factor_id"]]
    if not factor_ids:
        raise ValueError("correlation matrix is empty")
    squared_sum = 0.0
    for row in matrix.iter_rows(named=True):
        for factor_id in factor_ids:
            value = row[factor_id]
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError("n_eff requires a complete finite correlation matrix")
            squared_sum += float(value) ** 2
    return len(factor_ids) ** 2 / squared_sum


def render_spearman_report(
    matrix: pl.DataFrame,
    pairs: list[CorrelationPair],
    *,
    market: str,
    horizon: str,
    lookback: int,
    as_of_count: int,
    symbol_count: int,
    threshold: float,
) -> str:
    factor_ids = [str(value) for value in matrix["factor_id"]]
    rows = [
        f"Technical factor Spearman correlation (market={market}, horizon={horizon})",
        (
            f"lookback={lookback}, as_of_dates={as_of_count}, symbols={symbol_count}, "
            f"factors={len(factor_ids)}, n_eff={effective_degrees_of_freedom(matrix):.3f}"
        ),
        "factor " + " ".join(f"{factor_id:>7}" for factor_id in factor_ids),
    ]
    for record in matrix.iter_rows(named=True):
        rows.append(
            f"{record['factor_id']:<6}"
            + " ".join(format_correlation(record[factor_id]) for factor_id in factor_ids)
        )
    rows.append(f"High-correlation pairs (|rho| > {threshold:.2f}):")
    rows.extend(render_pair(pair) for pair in pairs)
    if not pairs:
        rows.append("  none")
    return "\n".join(rows)


def factor_values_wide(factors: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    required = {"as_of", "symbol", "factor_id", "raw_value"}
    missing = sorted(required - set(factors.columns))
    if missing:
        raise ValueError(f"factor values missing columns: {', '.join(missing)}")
    factor_ids = sorted(str(value) for value in factors["factor_id"].unique())
    if not factor_ids:
        raise ValueError("factor values are empty")
    wide = factors.pivot(
        on="factor_id",
        index=["as_of", "symbol"],
        values="raw_value",
    ).sort(["as_of", "symbol"])
    return wide, factor_ids


def pairwise_spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(right) != len(left):
        return None
    left_ranks = average_ranks(left)
    right_ranks = average_ranks(right)
    left_mean = sum(left_ranks) / len(left_ranks)
    right_mean = sum(right_ranks) / len(right_ranks)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left_ranks, right_ranks, strict=True)
    )
    left_sum = sum((value - left_mean) ** 2 for value in left_ranks)
    right_sum = sum((value - right_mean) ** 2 for value in right_ranks)
    denominator = math.sqrt(left_sum * right_sum)
    return None if denominator == 0 else numerator / denominator


def fisher_rho_confidence_interval(
    rho: float,
    sample_size: int,
) -> tuple[float | None, float | None]:
    if sample_size <= 3:
        return None, None
    if rho <= -1.0 or rho >= 1.0:
        bounded = -1.0 if rho < 0 else 1.0
        return bounded, bounded
    z = math.atanh(rho)
    margin = 1.959963984540054 / math.sqrt(sample_size - 3)
    return math.tanh(z - margin), math.tanh(z + margin)


def average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[ordered[position][0]] = average_rank
        start = end
    return ranks


def format_correlation(value: object) -> str:
    if value is None:
        return "   null"
    if not isinstance(value, (int, float)):
        raise TypeError("correlation matrix values must be numeric or null")
    return f"{float(value):7.3f}"


def render_pair(pair: CorrelationPair) -> str:
    ci = (
        "unavailable"
        if pair.ci_low is None or pair.ci_high is None
        else f"[{pair.ci_low:.4f}, {pair.ci_high:.4f}]"
    )
    return (
        f"  {pair.left}/{pair.right}: rho={pair.rho:.4f}, n={pair.sample_size}, "
        f"95% CI={ci}, suggested_keep={pair.suggested_keep}"
    )
