"""Step 3 tests 1-4: valid/invalid WIR and critique acceptance/rejection."""

from __future__ import annotations

import pytest

from conftest import make_beat, make_critique, make_issue, make_wir


class TestWIRSchema:
    def test_valid_wir_accepted(self, schemas):
        assert schemas.validate_wir(make_wir()) == []

    def test_missing_required_field_rejected(self, schemas):
        wir = make_wir()
        del wir["meaning"]
        errors = schemas.validate_wir(wir)
        assert errors and any("meaning" in e for e in errors)

    def test_wrong_wir_version_rejected(self, schemas):
        wir = make_wir()
        wir["wir_version"] = "0.2"
        assert schemas.validate_wir(wir)

    def test_invalid_beat_function_rejected(self, schemas):
        wir = make_wir()
        wir["beats"][0]["function"]["primary"] = "explosion"
        assert schemas.validate_wir(wir)

    def test_invalid_device_rejected(self, schemas):
        wir = make_wir()
        wir["devices"] = ["literary"]
        assert schemas.validate_wir(wir)

    def test_too_few_beats_rejected(self, schemas):
        wir = make_wir()
        wir["beats"] = [make_beat("B1")]
        assert schemas.validate_wir(wir)

    def test_bad_beat_id_rejected(self, schemas):
        wir = make_wir()
        wir["beats"][0]["id"] = "beat1"
        assert schemas.validate_wir(wir)

    def test_additional_properties_rejected(self, schemas):
        wir = make_wir()
        wir["mood"] = "melancholy"
        assert schemas.validate_wir(wir)

    def test_non_object_rejected(self, schemas):
        assert schemas.validate_wir(["not", "a", "wir"])


class TestCritiqueSchema:
    def test_valid_critique_accepted(self, schemas):
        assert schemas.validate_critique(make_critique()) == []

    def test_invalid_decision_rejected(self, schemas):
        critique = make_critique()
        critique["decision"] = "MAYBE"
        assert schemas.validate_critique(critique)

    def test_issue_missing_action_rejected(self, schemas):
        critique = make_critique()
        issue = make_issue()
        del issue["action"]
        critique["issues"] = [issue]
        errors = schemas.validate_critique(critique)
        assert errors and any("action" in e for e in errors)

    def test_invalid_severity_rejected(self, schemas):
        critique = make_critique()
        critique["issues"] = [make_issue("catastrophic")]
        assert schemas.validate_critique(critique)

    def test_quality_out_of_range_rejected(self, schemas):
        critique = make_critique()
        critique["quality"]["immersion"] = 6
        assert schemas.validate_critique(critique)

    def test_invalid_anti_pattern_type_rejected(self, schemas):
        critique = make_critique()
        critique["anti_patterns"] = [
            {"type": "too_pretty", "count": 1, "locations": ["P1"]}
        ]
        assert schemas.validate_critique(critique)

    def test_non_object_rejected(self, schemas):
        assert schemas.validate_critique("nope")


class TestRunSchema:
    def test_metadata_shape_valid(self, schemas):
        metadata = {
            "run_id": "000001",
            "timestamp": "2026-08-29T00:00:00+00:00",
            "models": {
                "architect": "m", "writer": "m", "critic": "m", "patcher": "m"
            },
            "parameters": {},
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost": 0.0,
                "latency_seconds": 0.0,
            },
            "patched": False,
            "status": "success",
        }
        assert schemas.validate_run_metadata(metadata) == []

    def test_status_enum_enforced(self, schemas):
        metadata = {
            "run_id": "1", "timestamp": "t",
            "models": {"architect": "m", "writer": "m", "critic": "m", "patcher": "m"},
            "parameters": {},
            "usage": {"input_tokens": 0, "output_tokens": 0,
                       "estimated_cost": 0.0, "latency_seconds": 0.0},
            "patched": False,
            "status": "partial",
        }
        assert schemas.validate_run_metadata(metadata)
