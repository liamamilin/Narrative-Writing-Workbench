"""Prompt loading. Production prompts live in /prompts as markdown files."""

from __future__ import annotations

from pathlib import Path

from .utils import sha256_text


class PromptNotFoundError(FileNotFoundError):
    pass


def prompt_path(prompts_dir: str | Path, role: str) -> Path:
    return Path(prompts_dir) / f"{role}.md"


def load_prompt(prompts_dir: str | Path, role: str) -> str:
    path = prompt_path(prompts_dir, role)
    if not path.is_file():
        raise PromptNotFoundError(f"prompt file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise PromptNotFoundError(f"prompt file is empty: {path}")
    return text


def prompt_version_info(prompts_dir: str | Path, roles: list[str]) -> dict[str, dict[str, str]]:
    """File name + content hash per role, for reproducibility tracking."""
    info: dict[str, dict[str, str]] = {}
    for role in roles:
        path = prompt_path(prompts_dir, role)
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            info[role] = {"file": str(path.name), "sha256": sha256_text(text)}
    return info
