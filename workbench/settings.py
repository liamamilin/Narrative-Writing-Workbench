"""User-editable runtime settings (Settings screen), persisted in
workbench/settings.json. Precedence: settings.json > process env > defaults.

Local desktop app: the API key is stored in a local file, same trust
boundary as workbench/env.sh. It is never returned by the API in full.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"

FIELDS = ("engine", "api_key", "base_url", "model", "timeout_seconds",
          "writer_temperature", "stream_debug")

# Preset providers for the Settings dropdown (OpenAI-compatible endpoints).
PROVIDERS = [
    {"id": "opencode", "name": "OpenCode Go",
     "base_url": "https://opencode.ai/zen/go/v1", "needs_key": True,
     "models": ["mimo-v2.5", "mimo-v2.5-pro", "deepseek-v4-flash",
                "kimi-k2.5"]},
    {"id": "ollama", "name": "Ollama (本地)",
     "base_url": "http://127.0.0.1:11434/v1", "needs_key": False,
     "models": []},
    {"id": "lmstudio", "name": "LM Studio (本地)",
     "base_url": "http://127.0.0.1:1234/v1", "needs_key": False,
     "models": []},
    {"id": "openai", "name": "OpenAI 官方",
     "base_url": "https://api.openai.com/v1", "needs_key": True,
     "models": ["gpt-4o-mini", "gpt-4o"]},
    {"id": "custom", "name": "自定义…", "base_url": "", "needs_key": True,
     "models": []},
]
LOCAL_KEY_PLACEHOLDER = "ollama"   # local servers accept any non-empty key


def load() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save(patch: dict) -> dict:
    cur = load()
    for key in FIELDS:
        if key not in patch:
            continue
        value = patch[key]
        if key == "stream_debug":
            if isinstance(value, str) and value.strip().lower() in ("false", "0", "no", "off"):
                value = False
            elif value != "":              # "" keeps the current value
                value = bool(value)
        elif isinstance(value, str):
            value = value.strip()
        if value == "" or value is None:      # empty means "keep current"
            continue
        cur[key] = value
    SETTINGS_PATH.write_text(
        json.dumps(cur, indent=2, ensure_ascii=False), encoding="utf-8")
    return cur


def apply_env(s: dict | None = None):
    """Push stored credentials/engine into the process env for the engine."""
    s = s if s is not None else load()
    if s.get("api_key"):
        os.environ["OPENAI_API_KEY"] = s["api_key"]
    if s.get("base_url"):
        os.environ["OPENAI_BASE_URL"] = s["base_url"]
    if s.get("engine"):
        os.environ["WORKBENCH_ENGINE"] = s["engine"]


def engine_mode() -> str:
    return load().get("engine") or os.environ.get("WORKBENCH_ENGINE", "mock")


def mask_key(key: str | None) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}…{key[-4:]}"


def view(s: dict | None = None) -> dict:
    """Settings for the UI — key is masked, never full."""
    s = s if s is not None else load()
    api_key = s.get("api_key") or os.environ.get("OPENAI_API_KEY") or ""
    out = {
        "engine": s.get("engine") or os.environ.get("WORKBENCH_ENGINE", "mock"),
        "base_url": s.get("base_url") or os.environ.get("OPENAI_BASE_URL") or "",
        "api_key_masked": mask_key(api_key),
        "has_key": bool(api_key),
        "model": s.get("model") or "",
        "timeout_seconds": s.get("timeout_seconds"),
        "writer_temperature": s.get("writer_temperature"),
        "stream_debug": bool(s.get("stream_debug", False)),
    }
    if not out["model"]:
        out["model"] = _model_from_config_yaml() or ""
    return out


def _model_from_config_yaml() -> str | None:
    """Fall back to the model in config.live.yaml for display."""
    try:
        import yaml
        cfg = Path(__file__).resolve().parent.parent / "config.live.yaml"
        if cfg.exists():
            roles = (yaml.safe_load(cfg.read_text()) or {}).get("roles") or {}
            first = next(iter(roles.values()), {})
            return (first or {}).get("model")
    except Exception:
        pass
    return None
