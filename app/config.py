"""Configuration loading for NWH V1.

Model names, temperatures, token limits, timeouts and structured-output modes
are per-role configuration values; nothing here is referenced inside agent
business logic beyond this module.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

ROLE_NAMES = ("architect", "writer", "critic", "patcher")


@dataclass
class RoleConfig:
    model: str = "gpt-4o-mini"
    temperature: float = 0.5
    max_output_tokens: int = 4000
    timeout_seconds: float = 180.0
    structured_mode: str = "auto"  # auto | json_object | none
    reasoning_effort: str = ""  # "" = provider default; e.g. low | medium | high

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoleConfig":
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in names})


@dataclass
class DecisionThresholds:
    max_moderate_issues: int = 2
    min_writing_quality: int = 24

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionThresholds":
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in names})


def _resolve(path_value: str | Path, base: Path) -> Path:
    p = Path(path_value)
    return p if p.is_absolute() else (base / p).resolve()


@dataclass
class Config:
    provider: str = "openai"
    api_key_env: str = "OPENAI_API_KEY"
    base_url_env: str = "OPENAI_BASE_URL"
    log_level: str = "INFO"
    judge_enabled: bool = False
    expected_language: str = "auto"  # zh | en | auto (docs/17)
    prompts_dir: Path = field(default_factory=lambda: REPO_ROOT / "prompts")
    schemas_dir: Path = field(default_factory=lambda: REPO_ROOT / "schemas")
    runs_dir: Path = field(default_factory=lambda: REPO_ROOT / "runs")
    benchmark_results_dir: Path = field(default_factory=lambda: REPO_ROOT / "benchmarks" / "results")
    thresholds: DecisionThresholds = field(default_factory=DecisionThresholds)
    roles: dict[str, RoleConfig] = field(
        default_factory=lambda: {
            "architect": RoleConfig(temperature=0.2),
            "writer": RoleConfig(temperature=0.7),
            "critic": RoleConfig(temperature=0.1),
            "patcher": RoleConfig(temperature=0.3),
        }
    )

    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any], base: Path | None = None) -> "Config":
        base = Path(base or REPO_ROOT)
        data = data or {}
        roles_in = data.get("roles") or {}
        roles = {name: RoleConfig.from_dict(roles_in.get(name) or {}) for name in ROLE_NAMES}
        cfg = cls(
            provider=data.get("provider", cls.provider),
            api_key_env=data.get("api_key_env", cls.api_key_env),
            base_url_env=data.get("base_url_env", cls.base_url_env),
            log_level=data.get("log_level", cls.log_level),
            judge_enabled=bool(data.get("judge_enabled", False)),
            expected_language=str(data.get("expected_language", cls.expected_language)),
            prompts_dir=_resolve(data.get("prompts_dir", "prompts"), base),
            schemas_dir=_resolve(data.get("schemas_dir", "schemas"), base),
            runs_dir=_resolve(data.get("runs_dir", "runs"), base),
            benchmark_results_dir=_resolve(
                data.get("benchmark_results_dir", "benchmarks/results"), base
            ),
            thresholds=DecisionThresholds.from_dict(data.get("thresholds") or {}),
            roles=roles,
        )
        return cfg

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path)
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls.from_dict(data, base=path.resolve().parent)

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env)

    @property
    def base_url(self) -> str | None:
        return os.environ.get(self.base_url_env)

    def role(self, name: str) -> RoleConfig:
        return self.roles[name]

    def setup_logging(self) -> None:
        level = getattr(logging, str(self.log_level).upper(), logging.INFO)
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
