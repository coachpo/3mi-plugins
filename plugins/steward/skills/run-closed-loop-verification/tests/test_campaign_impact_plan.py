"""Closed-loop bindings for provider-neutral verification plans."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .helpers import (
        json_output,
        make_adapter,
        make_case,
        read_json,
        run_cli,
        write_json,
    )
except ImportError:
    from helpers import (  # type: ignore
        json_output,
        make_adapter,
        make_case,
        read_json,
        run_cli,
        write_json,
    )


SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import adapter_paths
from engine import run_quick_locked
from journal_state import Campaign, CampaignLock
from model import CampaignError


def attach_verification(adapter: Path, *, tier: str) -> dict[str, object]:
    value = read_json(adapter)
    verification: dict[str, object] = {
        "contractVersion": 1,
        "profile": {
            "path": ".steward/verification-profile.json",
            "sha256": "sha256:" + "1" * 64,
        },
        "verificationCatalogFingerprint": "sha256:" + "2" * 64,
        "tier": tier,
        "impactPlan": None,
        "ciPlan": None,
    }
    value["verification"] = verification
    write_json(adapter, value)
    return verification


class ImpactPlanCampaignTests(unittest.TestCase):
    def test_legacy_adapter_does_not_load_verification_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(root, [make_case("smoke", "smoke")])
            with mock.patch.object(
                adapter_paths,
                "_verification_validator",
                side_effect=AssertionError("unexpected shared-contract load"),
            ):
                validated = adapter_paths.validate_adapter(adapter)

            self.assertIsNone(validated.verification)

    def test_verification_binding_is_saved_in_initialized_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(root, [make_case("smoke", "smoke")])
            raw = attach_verification(adapter, tier="quick")
            normalized = {**raw, "observed": True}
            with mock.patch.object(
                adapter_paths,
                "validate_adapter_verification",
                return_value=normalized,
            ):
                validated = adapter_paths.validate_adapter(adapter)
                initialized = Campaign.initialize(validated)

            self.assertEqual(normalized, validated.verification)
            self.assertEqual(raw, initialized.state["catalog"]["verification"])

    def test_quick_tier_uses_existing_quick_case_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = make_case("selected", "smoke")
            selected["quick"] = True
            adapter = make_adapter(
                root,
                [selected, make_case("full-only", "functional")],
            )
            raw = attach_verification(adapter, tier="quick")
            with mock.patch.object(
                adapter_paths,
                "validate_adapter_verification",
                return_value=raw,
            ):
                validated = adapter_paths.validate_adapter(adapter)
                Campaign.initialize(validated)
                with CampaignLock(validated.campaign_root):
                    campaign = Campaign.load(validated)
                    summary = run_quick_locked(campaign)

            self.assertEqual("PENDING", summary["status"])
            self.assertEqual("PASS", summary["cases"]["selected"]["quickStatus"])
            self.assertEqual(
                "PENDING", summary["cases"]["full-only"]["quickStatus"]
            )
            self.assertIsNone(summary["finalRegressionAttemptId"])

    def test_full_tier_rejects_explicit_quick_execution_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = make_case("full", "smoke")
            case["quick"] = True
            adapter = make_adapter(root, [case])
            raw = attach_verification(adapter, tier="full")
            with mock.patch.object(
                adapter_paths,
                "validate_adapter_verification",
                return_value=raw,
            ):
                validated = adapter_paths.validate_adapter(adapter)
                Campaign.initialize(validated)
                with CampaignLock(validated.campaign_root):
                    campaign = Campaign.load(validated)
                    before = campaign.state["lastEventHash"]
                    with self.assertRaisesRegex(
                        CampaignError, "unavailable for a full-tier"
                    ):
                        run_quick_locked(campaign)
                    self.assertEqual(before, campaign.state["lastEventHash"])

    def test_quick_history_gets_stable_full_regression_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = make_case("quick", "smoke")
            case["quick"] = True
            adapter = make_adapter(root, [case])
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", "--phase", "quick", expected=0)
            report = json_output(run_cli(adapter, "audit", expected=1))
            self.assertFalse(report["ok"])
            self.assertIn("FULL_REGRESSION_REQUIRED", report["rejectionCodes"])


if __name__ == "__main__":
    unittest.main()
