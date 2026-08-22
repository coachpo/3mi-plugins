"""Focused public-CLI contract tests for adapter validation and legacy recovery."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    from .helpers import (
        campaign_path,
        json_output,
        make_adapter,
        make_case,
        read_json,
        run_cli,
        write_fix_for_latest_failure,
        write_json,
    )
except ImportError:  # unittest discovery with tests/ as the import root
    from helpers import (  # type: ignore
        campaign_path,
        json_output,
        make_adapter,
        make_case,
        read_json,
        run_cli,
        write_fix_for_latest_failure,
        write_json,
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class AdapterValidationCommandTests(unittest.TestCase):
    def test_validate_adapter_reports_bindings_without_campaign_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(
                project,
                [make_case("smoke", "smoke"), make_case("workflow", "workflow")],
            )
            before = _snapshot(project)

            completed = run_cli(adapter, "validate-adapter", expected=0)
            report = json_output(completed)

            self.assertEqual(
                "steward.closed-loop-adapter-validation",
                report["schemaId"],
            )
            self.assertTrue(report["ok"])
            self.assertEqual(1, report["adapterSchemaVersion"])
            self.assertEqual(str(adapter.resolve()), report["adapterPath"])
            self.assertEqual("closed-loop-kernel-test", report["projectId"])
            self.assertEqual(["smoke", "workflow"], report["caseIds"])
            self.assertEqual("none", report["traceabilityMode"])
            self.assertFalse(report["verificationBound"])
            self.assertEqual("NOT_EVALUATED", report["executionStatus"])
            self.assertEqual("INCOMPLETE", report["completionStatus"])
            self.assertEqual("narrow", report["coverage"]["mode"])
            self.assertEqual(
                ["smoke", "workflow"], report["coverage"]["presentTiers"]
            )
            self.assertEqual(
                report["coverage"]["missingTiers"],
                report["coverage"]["outOfScopeTiers"],
            )
            self.assertRegex(report["catalogFingerprint"], r"^sha256:[0-9a-f]{64}$")
            self.assertFalse(campaign_path(adapter).exists())
            self.assertEqual(before, _snapshot(project))

    def test_full_coverage_requires_all_five_risk_tiers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(
                project,
                [
                    make_case("smoke", "smoke"),
                    make_case("functional", "functional"),
                    make_case("integration", "integration"),
                    make_case("workflow", "workflow"),
                    make_case("optional-role-play", "role-play", required=False),
                ],
                coverage_mode="full",
            )

            completed = run_cli(adapter, "validate-adapter", expected=2)

            self.assertIn("coverageMode full requires all risk tiers", completed.stderr)
            self.assertIn("role-play", completed.stderr)
            self.assertFalse(campaign_path(adapter).exists())

    def test_narrow_coverage_keeps_optional_only_tiers_out_of_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(
                project,
                [make_case("optional-workflow", "workflow", required=False)],
                coverage_mode="narrow",
            )

            report = json_output(
                run_cli(adapter, "validate-adapter", expected=0)
            )

            self.assertEqual([], report["coverage"]["presentTiers"])
            self.assertIn("workflow", report["coverage"]["missingTiers"])
            self.assertEqual(
                report["coverage"]["missingTiers"],
                report["coverage"]["outOfScopeTiers"],
            )

    def test_validate_adapter_rejects_invalid_input_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            value = read_json(adapter)
            value["unexpected"] = True
            write_json(adapter, value)
            before = _snapshot(project)

            completed = run_cli(adapter, "validate-adapter", expected=2)

            self.assertIn("unknown fields", completed.stderr)
            self.assertFalse(campaign_path(adapter).exists())
            self.assertEqual(before, _snapshot(project))


class LegacyPendingFixDiagnosticsTests(unittest.TestCase):
    def test_source_drift_preserves_legacy_campaign_and_requires_new_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            runner = project / "runner.py"
            adapter = make_adapter(
                project,
                [
                    make_case(
                        "functional",
                        "functional",
                        argv=(sys.executable, "runner.py"),
                    )
                ],
                source_files=("runner.py",),
            )
            runner.write_text("raise SystemExit(8)\n", encoding="utf-8")

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            runner.write_text("raise SystemExit(0)\n", encoding="utf-8")
            fix = write_fix_for_latest_failure(
                adapter,
                changed_files=("runner.py",),
                external_condition=False,
            )
            run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)
            runner.write_text("# drift after fix\nraise SystemExit(0)\n", encoding="utf-8")

            rejected = run_cli(adapter, "retest", expected=2)

            self.assertIn("preserve this campaign", rejected.stderr)
            self.assertIn("new campaign root", rejected.stderr)
            self.assertNotIn("record a new fix audit", rejected.stderr)
            self.assertTrue(campaign_path(adapter).exists())


class PublicResultContractTests(unittest.TestCase):
    def test_state_transition_commands_share_public_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            runner = project / "runner.py"
            runner.write_text("raise SystemExit(8)\n", encoding="utf-8")
            adapter = make_adapter(
                project,
                [
                    make_case(
                        "functional",
                        "functional",
                        argv=(sys.executable, "runner.py"),
                    )
                ],
                source_files=("runner.py",),
            )

            reports: list[tuple[str, dict[str, object], str, str]] = []
            reports.append(
                (
                    "init",
                    json_output(run_cli(adapter, "init", expected=0)),
                    "PENDING",
                    "INCOMPLETE",
                )
            )
            reports.append(
                (
                    "initial-failure",
                    json_output(run_cli(adapter, "run", expected=1)),
                    "FAILED",
                    "INCOMPLETE",
                )
            )

            runner.write_text(
                "import os\n"
                "from pathlib import Path\n"
                "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
                "(evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n",
                encoding="utf-8",
            )
            fix = write_fix_for_latest_failure(
                adapter,
                changed_files=("runner.py",),
                external_condition=False,
            )
            reports.append(
                (
                    "record-fix",
                    json_output(
                        run_cli(
                            adapter,
                            "record-fix",
                            "--fix",
                            str(fix),
                            expected=0,
                        )
                    ),
                    "FAILED",
                    "INCOMPLETE",
                )
            )
            reports.append(
                (
                    "retest",
                    json_output(run_cli(adapter, "retest", expected=0)),
                    "READY_FOR_REGRESSION",
                    "INCOMPLETE",
                )
            )
            reports.append(
                (
                    "regression",
                    json_output(
                        run_cli(
                            adapter,
                            "run",
                            "--mode",
                            "regression",
                            expected=0,
                        )
                    ),
                    "COMPLETE",
                    "AUDIT_REQUIRED",
                )
            )

            for label, report, execution, completion in reports:
                with self.subTest(command=label):
                    self.assertEqual(execution, report["status"])
                    self.assertEqual(execution, report["executionStatus"])
                    self.assertEqual(completion, report["completionStatus"])
                    self.assertIsInstance(report["coverage"], dict)
                    self.assertEqual("narrow", report["coverage"]["mode"])

    def test_traceability_modes_have_one_shared_three_value_domain(self) -> None:
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from audit import adapter_traceability_mode, campaign_traceability_mode

        request_digest = "sha256:" + "a" * 64
        request = {"requestSha256": request_digest}
        adapters = (
            SimpleNamespace(traceability=None, review_attestation=None),
            SimpleNamespace(
                traceability={},
                review_attestation=None,
                review_request=None,
                review_bindings_verified=False,
            ),
            SimpleNamespace(
                traceability={},
                review_attestation={},
                review_request=None,
                review_bindings_verified=False,
            ),
            SimpleNamespace(
                traceability={
                    "reviewFindings": {"reviewRequestSha256": request_digest}
                },
                review_attestation={},
                review_request=request,
                review_bindings_verified=True,
            ),
        )
        campaigns = (
            SimpleNamespace(state={"catalog": {"traceability": None}}),
            SimpleNamespace(
                state={"catalog": {"traceability": {}}, "traceSnapshot": {}}
            ),
            SimpleNamespace(
                state={
                    "catalog": {
                        "traceability": {
                            "reviewFindings": {
                                "reviewRequestSha256": "sha256:request"
                            }
                        }
                    },
                    "traceSnapshot": {"reviewFindings": {"attestation": {}}},
                }
            ),
            SimpleNamespace(
                state={
                    "catalog": {
                        "traceability": {
                            "reviewFindings": {
                                "reviewRequestSha256": request_digest,
                            }
                        }
                    },
                    "traceSnapshot": {
                        "reviewFindings": {
                            "attestation": {},
                            "reviewRequest": request,
                            "reviewRequestSha256": request_digest,
                            "bindingsVerified": True,
                        }
                    },
                }
            ),
        )

        self.assertEqual(
            ["none", "legacy", "legacy", "attested"],
            [adapter_traceability_mode(adapter) for adapter in adapters],
        )
        self.assertEqual(
            ["none", "legacy", "legacy", "attested"],
            [campaign_traceability_mode(campaign) for campaign in campaigns],
        )

    def test_status_and_audit_distinguish_execution_from_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            run_cli(adapter, "init", expected=0)

            status = json_output(run_cli(adapter, "status", expected=0))
            self.assertEqual("PENDING", status["status"])
            self.assertEqual("PENDING", status["executionStatus"])
            self.assertEqual("INCOMPLETE", status["completionStatus"])
            self.assertIsNone(status["resumeMode"])
            self.assertEqual("none", status["traceabilityMode"])

            audit = json_output(run_cli(adapter, "audit", expected=1))
            self.assertFalse(audit["ok"])
            self.assertEqual("PENDING", audit["executionStatus"])
            self.assertEqual("INCOMPLETE", audit["completionStatus"])
            self.assertEqual("none", audit["traceabilityMode"])
            self.assertEqual("none", audit["traceability"]["mode"])
            self.assertTrue(audit["rejectionCodes"])
            self.assertIn("FINAL_REGRESSION_REQUIRED", audit["rejectionCodes"])
            self.assertIn("UNRESOLVED_STATE", audit["rejectionCodes"])

    def test_regression_requires_audit_before_public_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            initialized = json_output(run_cli(adapter, "init", expected=0))
            initial = json_output(run_cli(adapter, "run", expected=0))
            self.assertEqual("PENDING", initialized["executionStatus"])
            self.assertEqual("INCOMPLETE", initialized["completionStatus"])
            self.assertEqual("READY_FOR_REGRESSION", initial["executionStatus"])
            self.assertEqual("INCOMPLETE", initial["completionStatus"])
            self.assertEqual("narrow", initial["coverage"]["mode"])

            regression = json_output(
                run_cli(adapter, "run", "--mode", "regression", expected=0)
            )
            self.assertEqual("COMPLETE", regression["status"])
            self.assertEqual("COMPLETE", regression["executionStatus"])
            self.assertEqual("AUDIT_REQUIRED", regression["completionStatus"])

            status = json_output(run_cli(adapter, "status", expected=0))
            self.assertEqual("COMPLETE", status["executionStatus"])
            self.assertEqual("COMPLETE", status["completionStatus"])

            audit = json_output(run_cli(adapter, "audit", expected=0))
            self.assertTrue(audit["ok"])
            self.assertEqual("COMPLETE", audit["executionStatus"])
            self.assertEqual("COMPLETE", audit["completionStatus"])

    def test_evaluated_audit_failure_is_incomplete_not_audit_required(self) -> None:
        for drift_kind in ("source", "artifact"):
            with self.subTest(drift=drift_kind), tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary)
                adapter = make_adapter(project, [make_case("smoke", "smoke")])
                run_cli(adapter, "init", expected=0)
                run_cli(adapter, "run", expected=0)
                regression = json_output(
                    run_cli(adapter, "run", "--mode", "regression", expected=0)
                )
                self.assertEqual("AUDIT_REQUIRED", regression["completionStatus"])

                if drift_kind == "source":
                    (project / "source.txt").write_text(
                        "post-regression drift\n", encoding="utf-8"
                    )
                else:
                    state = read_json(campaign_path(adapter) / "state.json")
                    final_id = state["finalRegressionAttemptId"]
                    attempt = next(
                        item for item in state["attempts"] if item["id"] == final_id
                    )
                    artifact = (
                        campaign_path(adapter)
                        / attempt["caseRuns"][0]["artifactDir"]
                        / "proof.json"
                    )
                    artifact.write_text('{"ok":false}', encoding="utf-8")

                status = json_output(run_cli(adapter, "status", expected=0))
                self.assertEqual("COMPLETE", status["executionStatus"])
                self.assertEqual("INCOMPLETE", status["completionStatus"])

                audit = json_output(run_cli(adapter, "audit", expected=1))
                self.assertFalse(audit["ok"])
                self.assertEqual("COMPLETE", audit["executionStatus"])
                self.assertEqual("INCOMPLETE", audit["completionStatus"])
                self.assertTrue(audit["rejectionCodes"])


if __name__ == "__main__":
    unittest.main()
