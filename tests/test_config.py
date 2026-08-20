from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from flowscope.config.loader import config_hash, load_config


def test_load_spec_example_config() -> None:
    config = load_config(Path("configs/tw_swing.yaml"))

    assert config.market == "TW"
    assert config.horizon == "swing"
    assert config.weights.dimensions.technical == pytest.approx(0.30)
    assert config.scoring.winsorize == pytest.approx((0.01, 0.99))


def test_config_hash_is_independent_of_yaml_key_order(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    first.write_text(content, encoding="utf-8")
    parsed = yaml.safe_load(content)
    second.write_text(yaml.safe_dump(parsed, sort_keys=True), encoding="utf-8")

    assert first.read_text(encoding="utf-8") != second.read_text(encoding="utf-8")

    assert config_hash(load_config(first)) == config_hash(load_config(second))


def test_config_hash_is_independent_of_enabled_order(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    first.write_text(content, encoding="utf-8")
    second.write_text(
        content.replace(
            "enabled: [T03, T05, T10, T11, T13, T15, T18, T21]",
            "enabled: [T21, T18, T15, T13, T11, T10, T05, T03]",
        ),
        encoding="utf-8",
    )

    assert config_hash(load_config(first)) == config_hash(load_config(second))


def test_config_hash_changes_when_enabled_factor_set_changes(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    first.write_text(content, encoding="utf-8")
    second.write_text(
        content.replace(
            "enabled: [T03, T05, T10, T11, T13, T15, T18, T21]",
            "enabled: [T03, T05, T10, T11, T13, T15, T18]",
        )
        .replace("      T21: { lookback: 90, atr_period: 14, threshold_atr: 1.5 }\n", "")
        .replace(
            "    diagnostic_params:\n",
            "    diagnostic_params:\n"
            "      T21: { lookback: 90, atr_period: 14, threshold_atr: 1.5 }\n",
        ),
        encoding="utf-8",
    )

    assert config_hash(load_config(first)) != config_hash(load_config(second))


def test_invalid_weight_sum_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    path.write_text(content.replace("financial: 0.20", "financial: 0.21"), encoding="utf-8")

    with pytest.raises(ValidationError, match="weights.dimensions must sum to 1.0"):
        load_config(path)


def test_enabled_factor_ids_must_be_known_for_dimension(tmp_path: Path) -> None:
    path = tmp_path / "bad_enabled.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    path.write_text(
        content.replace(
            "enabled: [T03, T05, T10, T11, T13, T15, T18, T21]",
            "enabled: [T99, T05, T10, T11, T13, T15, T18, T21]",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="unknown IDs: T99"):
        load_config(path)


def test_enabled_factor_ids_must_match_dimension_prefix(tmp_path: Path) -> None:
    path = tmp_path / "wrong_dimension.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    path.write_text(
        content.replace(
            "enabled: [M01, M02, M03, M04]",
            "enabled: [M01, M02, M03, C01]",
        ).replace("M04: { ma_months: 3 }", "M03: { ma_months: 3 }"),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="unknown IDs: C01"):
        load_config(path)


def test_enabled_factor_ids_must_not_repeat(tmp_path: Path) -> None:
    path = tmp_path / "duplicate_enabled.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    path.write_text(
        content.replace(
            "enabled: [T03, T05, T10, T11, T13, T15, T18, T21]",
            "enabled: [T03, T03, T10, T11, T13, T15, T18, T21]",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="duplicate IDs: T03"):
        load_config(path)


def test_enabled_factor_ids_must_not_be_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty_enabled.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    path.write_text(
        content.replace(
            "enabled: [T03, T05, T10, T11, T13, T15, T18, T21]",
            "enabled: []",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="enabled list must not be empty"):
        load_config(path)


def test_factor_params_must_belong_to_enabled_factors(tmp_path: Path) -> None:
    path = tmp_path / "bad_params.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    path.write_text(
        content.replace(
            "T05: { windows: [20, 60, 120], weights: [0.4, 0.4, 0.2] }",
            "T99: { windows: [20, 60, 120], weights: [0.4, 0.4, 0.2] }",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="not enabled: T99"):
        load_config(path)


def test_enabled_technical_factor_must_have_params(tmp_path: Path) -> None:
    path = tmp_path / "missing_params.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    path.write_text(
        content.replace(
            "      T03: { period: 14 }\n",
            "",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="missing params: T03"):
        load_config(path)


def test_technical_diagnostic_params_cover_every_disabled_factor(tmp_path: Path) -> None:
    path = tmp_path / "missing_diagnostic_params.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    path.write_text(
        content.replace("      T04: { atr_period: 10, multiplier: 3.0 }\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="diagnostics missing params: T04"):
        load_config(path)


def test_technical_factor_priority_must_cover_every_factor_once(tmp_path: Path) -> None:
    path = tmp_path / "bad_factor_priority.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    valid_priority = (
        "factor_priority: [T05, T02, T03, T01, T10, T11, T13, T15, T18, T19, T21, "
        "T04, T06, T07, T08, T09, T12, T14, T16, T17, T20]"
    )
    duplicate_priority = (
        "factor_priority: [T05, T02, T03, T01, T10, T11, T13, T15, T18, T19, T21, "
        "T04, T06, T07, T08, T09, T12, T14, T16, T17, T17]"
    )
    path.write_text(
        content.replace(valid_priority, duplicate_priority),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="duplicate IDs: T17"):
        load_config(path)


def test_technical_enabled_set_matches_full_history_collinearity_decision() -> None:
    technical = load_config(Path("configs/tw_swing.yaml")).factors.technical

    # 2025-08-08..2026-08-19、749 檔、250 日正式診斷後，依 factor_priority
    # 移除 T01/T02/T19；參數保留供全 21 因子後續診斷。
    assert technical.enabled == ["T03", "T05", "T10", "T11", "T13", "T15", "T18", "T21"]
    assert {"T01", "T02", "T19"} <= set(technical.diagnostic_params)
    assert set(technical.all_params) == {f"T{index:02d}" for index in range(1, 22)}


def test_distribution_warning_reject_must_exceed_flag(tmp_path: Path) -> None:
    path = tmp_path / "bad_distribution_warning.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    path.write_text(
        content.replace("distribution_warning_reject: 3", "distribution_warning_reject: 2"),
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="distribution_warning_reject must be greater than distribution_warning_flag",
    ):
        load_config(path)
