from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from flowscope.config.schema import FlowScopeConfig


@dataclass(frozen=True)
class LoadedConfig:
    config: FlowScopeConfig
    config_hash: str


def load_config(path: Path) -> FlowScopeConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"Config file must contain a YAML mapping: {path}"
        raise ValueError(msg)
    return FlowScopeConfig.model_validate(cast(dict[str, Any], raw))


def canonical_config_json(config: FlowScopeConfig) -> str:
    payload = _normalize_for_hash(config.model_dump(mode="json"))
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, child in value.items():
            if key == "enabled" and isinstance(child, list) and all(
                isinstance(item, str) for item in child
            ):
                # `enabled` 是啟用因子的集合語意；YAML 排列順序不應成為隱性策略參數。
                # 後續因子執行與輸出順序必須由 registry/排序規則明確決定。
                normalized[key] = sorted(child)
            else:
                normalized[key] = _normalize_for_hash(child)
        return normalized
    if isinstance(value, list):
        return [_normalize_for_hash(item) for item in value]
    return value


def config_hash(config: FlowScopeConfig) -> str:
    canonical = canonical_config_json(config).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return f"sha256:{digest}"


def load_config_with_hash(path: Path) -> LoadedConfig:
    config = load_config(path)
    return LoadedConfig(config=config, config_hash=config_hash(config))
