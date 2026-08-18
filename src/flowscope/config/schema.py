from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, model_validator

Market = Literal["TW"]
Horizon = Literal["swing"]
OutputFormat = Literal["parquet", "json", "markdown"]
HolderMode = Literal["composite"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AccountConfig(StrictModel):
    value: PositiveFloat
    risk_per_trade_pct: PositiveFloat
    max_position_pct: PositiveFloat


class UniverseConfig(StrictModel):
    top_n: PositiveInt


class L0GateConfig(StrictModel):
    min_avg_dollar_volume: PositiveFloat
    min_price: PositiveFloat
    min_listing_days: PositiveInt
    min_trading_day_ratio: float = Field(ge=0.0, le=1.0)
    exclude_types: list[str]
    exclude_markets: list[str]


class L1GateConfig(StrictModel):
    altman_z_min: float
    altman_z_min_nonmfg: float
    beneish_m_flag: float
    max_negative_ocf_quarters: int = Field(ge=0)
    max_capital_raise_pct: float = Field(ge=0.0)
    require_clean_audit: bool
    ar_growth_spread_flag: float = Field(ge=0.0)
    inventory_growth_spread_flag: float = Field(ge=0.0)


class PostScoreGateConfig(StrictModel):
    atr_pct_range: tuple[float, float]
    distribution_warning_reject: int = Field(ge=0)
    distribution_warning_flag: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_atr_range(self) -> PostScoreGateConfig:
        low, high = self.atr_pct_range
        if low >= high:
            raise ValueError("post_score.atr_pct_range must be ascending")
        return self


class GatesConfig(StrictModel):
    l0: L0GateConfig
    l1: L1GateConfig
    post_score: PostScoreGateConfig


class DimensionWeights(StrictModel):
    technical: float = Field(ge=0.0)
    chips: float = Field(ge=0.0)
    theme: float = Field(ge=0.0)
    financial: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_sum(self) -> DimensionWeights:
        total = self.technical + self.chips + self.theme + self.financial
        if abs(total - 1.0) > 1e-6:
            raise ValueError("weights.dimensions must sum to 1.0")
        return self


class WeightsConfig(StrictModel):
    dimensions: DimensionWeights


class FactorGroupConfig(StrictModel):
    enabled: list[str]
    params: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ChipsFactorGroupConfig(FactorGroupConfig):
    holder_mode: HolderMode


class FactorsConfig(StrictModel):
    technical: FactorGroupConfig
    chips: ChipsFactorGroupConfig
    theme: FactorGroupConfig


class MissingScoringConfig(StrictModel):
    fill_value: float = Field(ge=0.0, le=1.0)
    max_missing_ratio_per_dimension: float = Field(ge=0.0, le=1.0)
    max_missing_ratio_total: float = Field(ge=0.0, le=1.0)
    redistribute_weight: bool


class ScoringConfig(StrictModel):
    winsorize: tuple[float, float]
    missing: MissingScoringConfig

    @model_validator(mode="after")
    def validate_winsorize(self) -> ScoringConfig:
        low, high = self.winsorize
        if not 0.0 <= low < high <= 1.0:
            raise ValueError("scoring.winsorize must be in ascending [0, 1] bounds")
        return self


class PlannerConfig(StrictModel):
    time_stop_days: PositiveInt
    extended_atr_threshold: PositiveFloat
    breakout_volume_multiple: PositiveFloat
    pullback_volume_dryup: PositiveFloat
    stop_atr_multiple: PositiveFloat
    max_risk_per_share_pct: PositiveFloat


class OutputConfig(StrictModel):
    formats: list[OutputFormat]
    include_raw_factor_values: bool


class FlowScopeConfig(StrictModel):
    market: Market
    horizon: Horizon
    account: AccountConfig
    universe: UniverseConfig
    gates: GatesConfig
    weights: WeightsConfig
    factors: FactorsConfig
    scoring: ScoringConfig
    planner: PlannerConfig
    output: OutputConfig
