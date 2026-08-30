"""Step 3 test 9: prompt file loading."""

from __future__ import annotations

import pytest

from app.prompts import PromptNotFoundError, load_prompt, prompt_version_info


def test_load_all_four_prompts(repo_root):
    for role in ("architect", "writer", "critic", "patcher"):
        text = load_prompt(repo_root / "prompts", role)
        assert text.strip()


def test_prompts_contain_contract_phrases(repo_root):
    arch = load_prompt(repo_root / "prompts", "architect").lower()
    assert "narrative architect" in arch
    assert "do not write prose" in arch
    writer = load_prompt(repo_root / "prompts", "writer").lower()
    assert "prose only" in writer
    critic = load_prompt(repo_root / "prompts", "critic").lower()
    assert "do not rewrite" in critic
    patcher = load_prompt(repo_root / "prompts", "patcher").lower()
    assert "patch" in patcher and "rewrite" in patcher


def test_missing_prompt_raises(tmp_path):
    with pytest.raises(PromptNotFoundError):
        load_prompt(tmp_path, "nonexistent")


def test_empty_prompt_raises(tmp_path):
    (tmp_path / "blank.md").write_text("   ", encoding="utf-8")
    with pytest.raises(PromptNotFoundError):
        load_prompt(tmp_path, "blank")


def test_prompt_version_info_has_hashes(repo_root):
    info = prompt_version_info(repo_root / "prompts", ["architect", "writer"])
    assert set(info) == {"architect", "writer"}
    for entry in info.values():
        assert entry["file"].endswith(".md")
        assert len(entry["sha256"]) == 64
