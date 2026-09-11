"""Thesis judge tests — independent sharpness review after Meaning Discovery.

Covers: verdict schema, pass-through, fail→feedback retry (avoid + hint),
two fails = honest DiscoveryFailed, judge crash degrades to accept,
crack-vs-common semantic rule, review decision wiring.
"""

from __future__ import annotations

import json

import pytest

from app.config import Config
from workbench.engine import DiscoveryFailed
from workbench.engine.mock import MockWritingEngine
from workbench.engine.real import RealWritingEngine
from workbench import meaning_schema


def _good_discovery() -> dict:
    return MockWritingEngine().discover_meaning(
        topic="谈谈失败", writing_mode="deep_narrative", angle_mode="auto",
        custom_angle="", avoid=[], config={})


def _verdict(v, sharp=4, weakest="none", hint="sharpen further"):
    return {"verdict": v, "sharpness": sharp,
            "checks": {"crack_real": True, "counterexample_strong": True,
                       "boundary_clear": True, "frame_migrated": True},
            "weakest": weakest, "hint": hint}


class FakeClient:
    """Returns scripted payloads in order; records (role, user) per call."""

    def __init__(self, payloads, crash_at=None):
        self.payloads = list(payloads)
        self.calls = []
        self.crash_at = crash_at

    def generate_structured(self, messages, role, role_cfg):
        user = messages[-1]["content"]
        if self.crash_at is not None and len(self.calls) == self.crash_at:
            raise RuntimeError("judge transport down")
        self.calls.append({"role": role, "user": user})
        text = json.dumps(self.payloads.pop(0), ensure_ascii=False)

        class R:
            pass
        r = R()
        r.text = text
        r.input_tokens = r.output_tokens = r.latency_seconds = 0
        return r


def _engine(client) -> RealWritingEngine:
    eng = RealWritingEngine.__new__(RealWritingEngine)
    eng.config = Config.default()
    eng.client = client
    return eng


def _kw(avoid=()):
    return dict(topic="谈谈失败", writing_mode="deep_narrative",
                angle_mode="auto", custom_angle="", avoid=list(avoid),
                config={}, emit=None, on_delta=None)


# ---------------------------------------------------- verdict schema ----

def test_judge_verdict_schema():
    assert meaning_schema.validate_judge(_verdict("pass")) == []
    bad = _verdict("maybe")
    assert meaning_schema.validate_judge(bad)
    bad = _verdict("pass"); bad["sharpness"] = 6
    assert meaning_schema.validate_judge(bad)
    assert meaning_schema.validate_judge("nope")


def test_judge_failed_only_for_fail():
    assert meaning_schema.judge_failed(_verdict("fail"))
    assert not meaning_schema.judge_failed(_verdict("pass"))
    assert not meaning_schema.judge_failed(_verdict("borderline"))
    assert not meaning_schema.judge_failed(None)


# ------------------------------------------------- discover pipeline ----

def test_discover_passes_when_judge_accepts():
    d = _good_discovery()
    client = FakeClient([d, _verdict("pass")])
    out = _engine(client).discover_meaning(**_kw())
    assert out["selected_angle_id"] == d["selected_angle_id"]
    assert [c["role"] for c in client.calls] == ["meaning_discovery", "thesis_judge"]


def test_discover_borderline_is_accepted():
    d = _good_discovery()
    client = FakeClient([d, _verdict("borderline", sharp=3)])
    out = _engine(client).discover_meaning(**_kw())
    assert out == d


def test_discover_fail_retries_with_feedback_and_avoid():
    d1, d2 = _good_discovery(), _good_discovery()
    d2["selected_angle_id"] = d2["candidate_angles"][-1]["id"]
    client = FakeClient([d1, _verdict("fail", weakest="crack太浅",
                                      hint="往权力结构推"), d2, _verdict("pass")])
    out = _engine(client).discover_meaning(**_kw(avoid=["旧角度"]))
    assert out["selected_angle_id"] == d2["selected_angle_id"]
    retry_user = client.calls[2]["user"]
    assert "Previous attempt rejected" in retry_user
    assert "crack太浅" in retry_user and "往权力结构推" in retry_user
    assert "旧角度" in retry_user                       # original avoid kept
    assert d1["candidate_angles"][-1]["label"] in retry_user  # rejected angle added


def test_discover_two_fails_raises_with_hint():
    d = _good_discovery()
    client = FakeClient([d, _verdict("fail", hint="推到机制层"),
                         d, _verdict("fail", sharp=1, hint="换实例域")])
    with pytest.raises(DiscoveryFailed) as ei:
        _engine(client).discover_meaning(**_kw())
    msg = str(ei.value)
    assert "评审方向" in msg and "换实例域" in msg


def test_judge_crash_degrades_to_accept():
    d = _good_discovery()
    client = FakeClient([d], crash_at=1)
    out = _engine(client).discover_meaning(**_kw())
    assert out == d                                    # first attempt accepted


# ------------------------------------------------ semantic: crack rule ----

def test_validate_meaning_rejects_crack_restating_common():
    d = _good_discovery()
    d["crack"] = d["common_reading"]
    errs = meaning_schema.validate_meaning(d)
    assert any("crack must differ" in e for e in errs)


def test_validate_meaning_allows_distinct_crack():
    assert meaning_schema.validate_meaning(_good_discovery()) == []


# -------------------------------------------------- review decision ----

class FakeCritic:
    def __init__(self, decision, detail):
        self._d, self._detail = decision, detail

    def run(self, *a, **k):
        class S:
            pass
        s = S()
        s.data = {"quality": {"progression": 5, "meaning_density": 5,
                              "immersion": 5, "restraint": 5, "coherence": 5},
                  "issues": [], "decision": self._d}
        s.decision_detail = self._detail
        return s


def _engine_with_critic(critic) -> RealWritingEngine:
    eng = _engine(FakeClient([]))
    eng.critic = critic
    return eng


def test_review_summary_carries_decision_and_wq():
    eng = _engine_with_critic(
        FakeCritic("PASS", {"wq": 25, "severity_counts": {"minor": 1}}))
    payload = eng.review(content="A paragraph.", material="", instruction="",
                         plan=None, config={})
    assert payload["summary"]["decision"] == "PASS"
    assert payload["summary"]["wq"] == 25
    assert payload["issues"] == []


def test_review_summary_text_patch_required_warning():
    from workbench.service import _review_summary_text
    payload = {"summary": {"progression": "strong", "meaning_density": "needs_attention",
                           "immersion": "good", "restraint": "good", "coherence": "good",
                           "decision": "PATCH_REQUIRED", "wq": 18},
               "issues": [{}]}
    text = _review_summary_text(payload)
    assert "⚠ 未通过检查" in text and "换角度重写" in text
    assert "decision" not in text and "wq" not in text   # internal keys not rendered


def test_review_summary_text_pass_no_warning():
    from workbench.service import _review_summary_text
    payload = {"summary": {"progression": "strong", "meaning_density": "strong",
                           "immersion": "good", "restraint": "good", "coherence": "good",
                           "decision": "PASS", "wq": 25},
               "issues": []}
    text = _review_summary_text(payload)
    assert "⚠" not in text and "未发现明显问题" in text


# ---------------------------- goal function: precision/residue contract ----

def test_progression_contract_carries_distinction_and_residue():
    from workbench.meaning_schema import PROGRESSION_CONTRACT
    assert "conceptual distinction" in PROGRESSION_CONTRACT
    assert "Residue" in PROGRESSION_CONTRACT
    assert "总结陈词" in PROGRESSION_CONTRACT          # closing = tool, not summary


def test_discover_prompt_demands_distinction_and_residue():
    import pathlib
    base = pathlib.Path(Config.default().prompts_dir)
    text = (base / "meaning_discovery.md").read_text(encoding="utf-8")
    assert "conceptual distinction" in text and "X ≠ Y" in text
    assert "portable mental tool" in text
    assert "Residue" in text


def test_critic_prompt_has_thesis_gates():
    import pathlib
    base = pathlib.Path(Config.default().prompts_dir)
    text = (base / "critic.md").read_text(encoding="utf-8")
    assert "Gate 2, FATAL" in text and "Gate 3, FATAL" in text
    assert "delete test" in text
    assert "Core quality decides; delivery amplifies" in text
    assert "Applies only when the draft carries a thesis" in text  # skip for non-thesis tasks
