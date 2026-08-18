from pathlib import Path

import pytest
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
    first.write_text(Path("configs/tw_swing.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    second.write_text(
        """
horizon: swing
market: TW
account: {value: 1000000, risk_per_trade_pct: 1.0, max_position_pct: 15.0}
universe: {top_n: 30}
gates:
  post_score:
    atr_pct_range: [2.0, 12.0]
    distribution_warning_reject: 3
    distribution_warning_flag: 2
  l1:
    altman_z_min: 1.8
    altman_z_min_nonmfg: 1.1
    beneish_m_flag: -1.78
    max_negative_ocf_quarters: 1
    max_capital_raise_pct: 20.0
    require_clean_audit: true
    ar_growth_spread_flag: 30.0
    inventory_growth_spread_flag: 30.0
  l0:
    min_avg_dollar_volume: 30000000
    min_price: 10.0
    min_listing_days: 250
    min_trading_day_ratio: 0.90
    exclude_types: [ETF, ETN, REIT, TDR, PREFERRED]
    exclude_markets: [EMERGING]
weights:
  dimensions: {financial: 0.20, theme: 0.20, chips: 0.30, technical: 0.30}
factors:
  theme:
    params: {M04: {ma_months: 3}, M01: {window: 20}}
    enabled: [M01, M02, M03, M04]
  chips:
    params:
      C11: {window: 20}
      C07: {window: 20}
      C06: {window: 20}
      C05: {slope_weeks: 8, zscore_weeks: 52}
    enabled: [C05, C06, C07, C08, C11, C12, C15, C17]
    holder_mode: composite
  technical:
    params:
      T19: {pivot_lookback: 60, min_base_days: 15, max_base_range: 0.25}
      T10: {bb_period: 20, bb_std: 2.0, percentile_window: 250}
      T05: {windows: [20, 60, 120], weights: [0.4, 0.4, 0.2]}
      T02: {window: 60}
    enabled: [T01, T02, T03, T05, T10, T11, T13, T15, T18, T19, T21]
scoring:
  missing:
    fill_value: 0.5
    max_missing_ratio_per_dimension: 0.4
    max_missing_ratio_total: 0.25
    redistribute_weight: true
  winsorize: [0.01, 0.99]
planner:
  time_stop_days: 10
  extended_atr_threshold: 1.5
  breakout_volume_multiple: 1.5
  pullback_volume_dryup: 0.7
  stop_atr_multiple: 2.0
  max_risk_per_share_pct: 10.0
output: {formats: [parquet, json, markdown], include_raw_factor_values: true}
""".lstrip(),
        encoding="utf-8",
    )

    assert config_hash(load_config(first)) == config_hash(load_config(second))


def test_invalid_weight_sum_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    content = Path("configs/tw_swing.yaml").read_text(encoding="utf-8")
    path.write_text(content.replace("financial: 0.20", "financial: 0.21"), encoding="utf-8")

    with pytest.raises(ValidationError, match="weights.dimensions must sum to 1.0"):
        load_config(path)
