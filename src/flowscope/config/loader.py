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
    payload = config.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def config_hash(config: FlowScopeConfig) -> str:
    canonical = canonical_config_json(config).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return f"sha256:{digest}"


def load_config_with_hash(path: Path) -> LoadedConfig:
    config = load_config(path)
    return LoadedConfig(config=config, config_hash=config_hash(config))
