"""MockWritingEngine — deterministic, LLM-free engine for tests and offline dev.

Interface is identical to RealWritingEngine (both satisfy WritingEngine).
"""

from __future__ import annotations

from . import (DiscoveryFailed, GenerateResult, LockConflict,
               map_beats_to_paragraphs, split_paragraphs)

_MOCK_CANDIDATES = [
    {"id": "A1", "label": "The topic as loss", "mechanism": "subtraction",
     "core_question": "What is taken away?",
     "deep_meaning": "The topic names a loss the reader has not priced.",
     "reader_end_state": "the reader feels the missing thing precisely"},
    {"id": "A2", "label": "The topic as disguised self-question",
     "mechanism": "projection",
     "core_question": "What does the reader really ask about themselves?",
     "deep_meaning": "The topic stands in for a question about identity.",
     "reader_end_state": "the reader recognizes their own question"},
    {"id": "A3", "label": "The topic as revaluation", "mechanism": "repricing",
     "core_question": "What changes value once the topic is faced?",
     "deep_meaning": "The topic re-prices what the reader already paid.",
     "reader_end_state": "the reader sees past effort in a new light"},
]

_MOCK_WIR = {
    "kind": "mock_wir",
    "beats": [
        {"id": "B1", "function": {"primary": "ground"},
         "reader_transition": {"from": "curious", "to": "oriented"},
         "meaning_gain": "reader learns the situation"},
        {"id": "B2", "function": {"primary": "complicate"},
         "reader_transition": {"from": "oriented", "to": "tense"},
         "meaning_gain": "the tension becomes felt"},
        {"id": "B3", "function": {"primary": "turn"},
         "reader_transition": {"from": "tense", "to": "shifted"},
         "meaning_gain": "the meaning pivots on a detail"},
        {"id": "B4", "function": {"primary": "land"},
         "reader_transition": {"from": "shifted", "to": "settled"},
         "meaning_gain": "the reader sits with the aftertaste"},
    ],
}


class MockWritingEngine:
    name = "mock"

    def discover_meaning(self, *, topic, writing_mode, angle_mode,
                         custom_angle, avoid, config, emit=None) -> dict:
        if emit:
            emit("stage", {"stage": "discovery"})
        if not topic.strip():
            raise DiscoveryFailed("Enter a topic to write about.")
        if angle_mode == "custom":
            candidates = [dict(_MOCK_CANDIDATES[0])]
            candidates[0].update({"id": "A0", "label": custom_angle})
            selected = "A0"
        else:
            candidates = [dict(c) for c in _MOCK_CANDIDATES]
            fresh = [c for c in candidates if c["label"] not in set(avoid or [])]
            if not fresh:
                raise DiscoveryFailed("No distinct angles remain to try.")
            selected = fresh[-1]["id"] if len(fresh) > 1 else fresh[0]["id"]
        sel = next(c for c in candidates if c["id"] == selected)
        return {
            "topic": topic, "surface_question": f"Why {topic}?",
            "candidate_tensions": ["wanting it vs. fearing it"],
            "candidate_angles": candidates,
            "selected_angle_id": selected,
            "selection_reason": "mock: most generative framing",
            "core_question": sel["core_question"],
            "deep_meaning": sel["deep_meaning"],
            "common_reading": "a generic answer",
            "new_reading": sel["deep_meaning"],
            "reader_end_state": sel["reader_end_state"],
            "key_tensions": ["wanting vs. fearing"],
            "constraints": [], "fact_heavy": False, "language": "en",
        }

    def generate(self, *, material, instruction, task_type, config,
                 meaning=None, emit=None, on_delta=None) -> GenerateResult:
        if emit:
            emit("stage", {"stage": "structure"})
            emit("stage", {"stage": "writing"})
        topic = (instruction or material or "the subject").strip().split("\n")[0][:40]
        if meaning and meaning.get("selected_angle"):
            topic = f"{topic} — {meaning['selected_angle']}".strip(" —")[:80]
        paras = [
            f"{topic} began quietly, in a way no one thought to record.",
            "The details accumulated: a door left open, a sentence repeated, "
            "and a small silence at the far end of the table that nobody named.",
            "What mattered was never said directly, only circled.",
            "By the end, the reader understands what the character refused to.",
        ]
        plan = dict(_MOCK_WIR)
        if meaning:
            plan["meaning"] = meaning
        text = "\n\n".join(paras)
        if on_delta:
            import time as _t
            for i in range(0, len(text), 24):
                on_delta(text[i:i + 24])
                _t.sleep(0.005)
        return GenerateResult(text=text, plan=plan)

    def review(self, *, content, material, instruction, plan, config) -> dict:
        paras = split_paragraphs(content)
        issues = []
        for i, p in enumerate(paras, 1):
            if len(p) > 90:
                issues.append({
                    "id": f"issue_{i}",
                    "location": {"paragraph_start": i, "paragraph_end": i},
                    "type": "over_explanation",
                    "message": "This paragraph may explain more than the reader needs.",
                    "fixable": True,
                })
        return {
            "summary": {
                "progression": "strong",
                "meaning_density": "good",
                "immersion": "good",
                "restraint": "needs_attention" if issues else "good",
                "coherence": "strong",
            },
            "issues": issues,
        }

    def patch(self, *, content, before_text, instruction, locks, config) -> str:
        if locks.get("facts") and "invent" in instruction.lower():
            raise LockConflict("This revision would alter source facts.")
        if "shorter" in instruction.lower() or "shorten" in instruction.lower():
            after = before_text[: max(20, len(before_text) // 2)].rstrip() + "。"
        else:
            after = before_text.replace("  ", " ").strip()
            if after == before_text:
                after = before_text.rstrip().removesuffix(".") + " — and it settled there."
        return after

    def writing_map(self, *, plan, content) -> list[dict]:
        beats = (plan or {}).get("beats", _MOCK_WIR["beats"])
        return map_beats_to_paragraphs(beats, content)
