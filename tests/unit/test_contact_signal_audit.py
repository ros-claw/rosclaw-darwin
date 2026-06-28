"""Unit tests for the contact signal audit script helpers."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "diagnostics" / "run_contact_signal_audit.py"
spec = __import__("importlib.util").util.spec_from_file_location("run_contact_signal_audit", SCRIPT)
module = __import__("importlib.util").util.module_from_spec(spec)
sys.modules["run_contact_signal_audit"] = module
spec.loader.exec_module(module)


class TestCompareStates:
    def test_full_agreement(self) -> None:
        records = [
            {"step": 0, "phase": "CONTACT_VERIFY", "contact_proxy": "no_contact", "contact_state": "no_contact"},
            {"step": 1, "phase": "CONTACT_VERIFY", "contact_proxy": "likely_contact", "contact_state": "likely_contact"},
        ]
        result = module._compare_states(records)
        assert result["compared_steps"] == 2
        assert result["agreed_steps"] == 2
        assert result["agreement_rate"] == 1.0
        assert result["state_distribution"]["no_contact"] == 1

    def test_disagreement(self) -> None:
        records = [
            {"step": 0, "phase": "CONTACT_VERIFY", "contact_proxy": "no_contact", "contact_state": "likely_contact"},
        ]
        result = module._compare_states(records)
        assert result["agreed_steps"] == 0
        assert result["agreement_rate"] == 0.0
        assert len(result["disagreement_examples"]) == 1
        assert result["disagreement_examples"][0]["proxy"] == "no_contact"
        assert result["disagreement_examples"][0]["state"] == "likely_contact"

    def test_missing_defaults_to_unknown_and_is_skipped(self) -> None:
        records = [{"step": 0, "phase": "CONTACT_VERIFY"}]
        result = module._compare_states(records)
        assert result["compared_steps"] == 0
        assert result["agreement_rate"] == 0.0
        assert result["state_distribution"] == {}

    def test_unknown_legacy_proxy_is_skipped(self) -> None:
        records = [
            {"step": 0, "phase": "CONTACT_VERIFY", "contact_proxy": "unknown", "contact_state": "likely_contact"},
            {"step": 1, "phase": "CONTACT_VERIFY", "contact_proxy": "likely_contact", "contact_state": "likely_contact"},
        ]
        result = module._compare_states(records)
        assert result["compared_steps"] == 1
        assert result["agreed_steps"] == 1
        assert result["agreement_rate"] == 1.0
        assert result["proxy_distribution"] == {"likely_contact": 1}
        assert result["state_distribution"] == {"likely_contact": 1}

    def test_non_contact_verify_steps_are_ignored(self) -> None:
        records = [
            {"step": 0, "phase": "APPROACH", "contact_proxy": "no_contact", "contact_state": "likely_contact"},
            {"step": 1, "phase": "GRASP", "contact_proxy": "likely_contact", "contact_state": "pushed_away"},
            {"step": 2, "phase": "CONTACT_VERIFY", "contact_proxy": "likely_contact", "contact_state": "likely_contact"},
        ]
        result = module._compare_states(records)
        assert result["compared_steps"] == 1
        assert result["agreed_steps"] == 1
        assert result["agreement_rate"] == 1.0


class TestParseSeedRange:
    def test_mixed_range_and_singleton(self) -> None:
        assert module._parse_seed_range("0,2:4,7") == [0, 2, 3, 4, 7]

    def test_single_seed(self) -> None:
        assert module._parse_seed_range("24") == [24]
