from __future__ import annotations

from collections import Counter
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, model_validator

Market = Literal["TW"]
Horizon = Literal["swing"]
OutputFormat = Literal["parquet", "json", "markdown"]
HolderMode = Literal["composite"]
TECHNICAL_FACTOR_IDS = frozenset(f"T{index:02d}" for index in range(1, 22))
CHIPS_FACTOR_IDS = frozenset(f"C{index:02d}" for index in range(1, 18))
THEME_FACTOR_IDS = frozenset(f"M{index:02d}" for index in range(1, 6))


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
    def validate_post_score_gates(self) -> PostScoreGateConfig:
        low, high = self.atr_pct_range
        if low >= high:
            raise ValueError("post_score.atr_pct_range must be ascending")
        if self.distribution_warning_reject <= self.distribution_warning_flag:
            raise ValueError(
                "post_score.distribution_warning_reject must be greater than "
                "distribution_warning_flag"
            )
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
    allowed_factor_ids: ClassVar[frozenset[str]] = frozenset()

    enabled: list[str]
    params: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_enabled(self) -> FactorGroupConfig:
        if not self.enabled:
            raise ValueError("factor enabled list must not be empty")
        counts = Counter(self.enabled)
        duplicates = sorted(factor_id for factor_id, count in counts.items() if count > 1)
        if duplicates:
            joined = ", ".join(duplicates)
            raise ValueError(f"factor enabled list contains duplicate IDs: {joined}")
        unknown_ids = sorted(set(self.enabled) - self.allowed_factor_ids)
        if unknown_ids:
            joined = ", ".join(unknown_ids)
            raise ValueError(f"factor enabled list contains unknown IDs: {joined}")
        return self

    @model_validator(mode="after")
    def validate_params_enabled_subset(self) -> FactorGroupConfig:
        unknown_keys = sorted(set(self.params) - set(self.enabled))
        if unknown_keys:
            joined = ", ".join(unknown_keys)
            raise ValueError(f"factor params contain keys that are not enabled: {joined}")
        return self


class TechnicalFactorGroupConfig(FactorGroupConfig):
    allowed_factor_ids: ClassVar[frozenset[str]] = TECHNICAL_FACTOR_IDS
    diagnostic_params: dict[str, dict[str, Any]]
    factor_priority: list[str]

    @model_validator(mode="after")
    def validate_enabled_params_exist(self) -> TechnicalFactorGroupConfig:
        missing = sorted(set(self.enabled) - set(self.params))
        if missing:
            raise ValueError(f"enabled technical factors missing params: {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def validate_diagnostic_config(self) -> TechnicalFactorGroupConfig:
        diagnostic_ids = set(self.diagnostic_params)
        enabled_ids = set(self.enabled)
        overlap = sorted(diagnostic_ids & enabled_ids)
        if overlap:
            raise ValueError(
                "technical diagnostic_params must contain only disabled factors: "
                f"{', '.join(overlap)}"
            )
        unknown_diagnostic_ids = sorted(diagnostic_ids - self.allowed_factor_ids)
        if unknown_diagnostic_ids:
            raise ValueError(
                "technical diagnostic_params contain unknown IDs: "
                f"{', '.join(unknown_diagnostic_ids)}"
            )
        missing_diagnostic_ids = sorted(
            self.allowed_factor_ids - enabled_ids - diagnostic_ids
        )
        if missing_diagnostic_ids:
            raise ValueError(
                "technical diagnostics missing params: "
                f"{', '.join(missing_diagnostic_ids)}"
            )

        priority_counts = Counter(self.factor_priority)
        duplicate_priorities = sorted(
            factor_id for factor_id, count in priority_counts.items() if count > 1
        )
        if duplicate_priorities:
            raise ValueError(
                "technical factor_priority contains duplicate IDs: "
                f"{', '.join(duplicate_priorities)}"
            )
        missing_priorities = sorted(self.allowed_factor_ids - set(self.factor_priority))
        unknown_priorities = sorted(set(self.factor_priority) - self.allowed_factor_ids)
        if missing_priorities or unknown_priorities:
            raise ValueError(
                "technical factor_priority must contain every T01-T21 ID exactly once: "
                f"missing={', '.join(missing_priorities) or 'none'}, "
                f"unknown={', '.join(unknown_priorities) or 'none'}"
            )
        return self

    @property
    def all_params(self) -> dict[str, dict[str, Any]]:
        return {**self.params, **self.diagnostic_params}


class ChipsFactorGroupConfig(FactorGroupConfig):
    allowed_factor_ids: ClassVar[frozenset[str]] = CHIPS_FACTOR_IDS

    holder_mode: HolderMode


class ThemeFactorGroupConfig(FactorGroupConfig):
    allowed_factor_ids: ClassVar[frozenset[str]] = THEME_FACTOR_IDS


class FactorsConfig(StrictModel):
    technical: TechnicalFactorGroupConfig
    chips: ChipsFactorGroupConfig
    theme: ThemeFactorGroupConfig


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
