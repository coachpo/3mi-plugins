from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .helpers import make_project, marker_command, read_json, run_cli, write_json
except ImportError:
    from helpers import (  # type: ignore
        make_project,
        marker_command,
        read_json,
        run_cli,
        write_json,
    )

import cli as cli_module
from adapter_paths import current_platform, validate_adapter
from audit import audit_report, status_report
from journal_state import Campaign
from model import CampaignError, canonical_bytes, sha256_bytes


def output(result: object) -> dict:
    value = result.stdout
    if not value:
        raise AssertionError(result.stderr)
    return json.loads(value)


def repair_note(
    *,
    root_cause: str = "app.txt contains the rejected marker",
    summary: str = "replace the rejected marker",
) -> dict:
    return {
        "rootCause": root_cause,
        "rootCauseSource": {
            "path": "app.txt",
            "lineStart": 1,
            "lineEnd": 1,
        },
        "fixSummary": summary,
    }


class CampaignV6Tests(unittest.TestCase):
    def _complete(self, path: Path) -> None:
        self.assertEqual(0, run_cli(path, "init").returncode)
        self.assertEqual(
            "AUDIT_REQUIRED", output(run_cli(path, "advance"))["executionStatus"]
        )
        self.assertEqual(
            "COMPLETE", output(run_cli(path, "advance"))["completionStatus"]
        )

    def _record_repair(self, path: Path, note: dict | None = None):
        fix_path = path.parent / "repair-note.json"
        write_json(fix_path, note or repair_note())
        return run_cli(path, "record-fix", "--fix", str(fix_path))

    def test_copied_complete_campaign_is_bound_to_its_original_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source_adapter = make_project(source)
            self._complete(source_adapter)
            successful_audit = output(run_cli(source_adapter, "status"))[
                "successfulAudit"
            ]

            sibling = base / "sibling"
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "worktree",
                    "add",
                    "-q",
                    "-b",
                    "sibling-test",
                    str(sibling),
                ],
                check=True,
            )
            shutil.copytree(source / ".steward", sibling / ".steward")

            adapter = sibling / ".steward" / "project-adapter.json"
            status = output(run_cli(adapter, "status"))
            self.assertFalse(status["worktreeBindingConsistent"])
            self.assertEqual("INCOMPLETE", status["completionStatus"])
            self.assertEqual(successful_audit, status["successfulAudit"])
            blocked = run_cli(adapter, "advance")
            self.assertEqual(1, blocked.returncode)
            self.assertIn(
                "WORKTREE_BINDING_DRIFT", output(blocked)["currentAuditRejectionCodes"]
            )

    def test_runtime_platform_drift_blocks_mutation_and_current_completion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self._complete(path)
            adapter = validate_adapter(path)
            other = "windows" if current_platform() != "windows" else "linux"
            with mock.patch("journal_state.current_platform", return_value=other):
                campaign = Campaign.load(adapter)
            self.assertFalse(campaign.runtime_platform_consistent)
            with self.assertRaisesRegex(CampaignError, "RUNTIME_PLATFORM_DRIFT"):
                campaign.ensure_mutable()
            with mock.patch("audit.current_platform", return_value=other):
                status = status_report(campaign)
                audit = audit_report(campaign)
            self.assertEqual("INCOMPLETE", status["completionStatus"])
            self.assertIn("RUNTIME_PLATFORM_DRIFT", audit["rejectionCodes"])

    def test_goal_workspace_integrity_is_required_after_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self._complete(path)
            events = path.parent / "verification" / "campaign" / "events.jsonl"
            successful_history = events.read_bytes()
            (path.parent / "goal-context" / "goal-context.md").unlink()

            status = output(run_cli(path, "status"))
            self.assertFalse(status["goalWorkspaceValid"])
            self.assertEqual("INCOMPLETE", status["completionStatus"])
            rejected = run_cli(path, "advance")
            self.assertEqual(1, rejected.returncode)
            self.assertIn(
                "GOAL_WORKSPACE_INVALID",
                output(rejected)["currentAuditRejectionCodes"],
            )
            self.assertEqual(successful_history, events.read_bytes())

    def test_optional_unavailable_case_is_not_run_but_required_case_blocks(
        self,
    ) -> None:
        unavailable = "windows" if current_platform() != "windows" else "darwin"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = make_project(root / "optional")
            adapter_value = read_json(path)
            optional = dict(adapter_value["cases"][0])
            optional.update(
                {
                    "id": "optional-host",
                    "required": False,
                    "platform": unavailable,
                    "coversCriteria": [],
                }
            )
            adapter_value["cases"].append(optional)
            write_json(path, adapter_value)
            self.assertEqual(0, run_cli(path, "init").returncode)
            initial = output(run_cli(path, "advance"))
            statuses = {
                item["id"]: item["finalStatus"] for item in initial["coverage"]["cases"]
            }
            self.assertEqual("NOT_RUN", statuses["optional-host"])
            self.assertEqual("AUDIT_REQUIRED", initial["executionStatus"])
            self.assertEqual(0, run_cli(path, "advance").returncode)

            path = make_project(root / "required", platform=unavailable)
            self.assertEqual(0, run_cli(path, "init").returncode)
            blocked = run_cli(path, "advance")
            self.assertEqual(1, blocked.returncode)
            self.assertEqual("BLOCKED", output(blocked)["executionStatus"])

    def test_source_drift_before_regression_is_recoverable_after_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root, command=marker_command())
            (root / "app.txt").write_text("bad\n", encoding="utf-8")
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(1, run_cli(path, "advance").returncode)
            (root / "app.txt").write_text("good\n", encoding="utf-8")
            self.assertEqual(0, self._record_repair(path).returncode)
            self.assertEqual(
                "READY_FOR_REGRESSION",
                output(run_cli(path, "advance"))["executionStatus"],
            )

            (root / "app.txt").write_text("drifted\n", encoding="utf-8")
            rejected = run_cli(path, "advance")
            self.assertEqual(2, rejected.returncode)
            self.assertIn("restore the recorded repair baseline", rejected.stderr)
            (root / "app.txt").write_text("good\n", encoding="utf-8")
            self.assertEqual(
                "AUDIT_REQUIRED", output(run_cli(path, "advance"))["executionStatus"]
            )

    def test_resume_records_interruption_and_restarts_the_authoritative_round(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            campaign = Campaign.load(validate_adapter(path))
            campaign.commit(
                "attempt_started",
                {
                    "attemptId": "attempt-simulated-interruption",
                    "mode": "initial",
                    "sourceFingerprint": campaign.state["sourceBaseline"][
                        "fingerprint"
                    ],
                    "caseIds": ["acceptance"],
                },
            )
            resumed = run_cli(path, "advance")
            self.assertEqual(0, resumed.returncode, resumed.stderr)
            self.assertEqual("AUDIT_REQUIRED", output(resumed)["executionStatus"])
            replayed = Campaign.load(validate_adapter(path))
            self.assertEqual("INTERRUPTED", replayed.state["attempts"][0]["status"])

    def test_initial_regression_audit_completes_on_one_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            initial = output(run_cli(path, "advance"))
            self.assertEqual("AUDIT_REQUIRED", initial["executionStatus"])
            self.assertEqual(
                "initial",
                Campaign.load(validate_adapter(path)).state["attempts"][-1]["mode"],
            )

            audit = run_cli(path, "advance")
            self.assertEqual(0, audit.returncode, audit.stderr)
            report = output(audit)
            self.assertTrue(report["ok"])
            self.assertEqual("COMPLETE", report["completionStatus"])
            self.assertEqual(
                ["acceptance"], report["coverage"]["criteria"][0]["finalPassingCaseIds"]
            )

    def test_successful_audit_is_durable_and_idempotent_after_context_loss(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(0, run_cli(path, "advance").returncode)
            events_path = path.parent / "verification" / "campaign" / "events.jsonl"
            before = events_path.read_text(encoding="utf-8").splitlines()

            first = run_cli(path, "advance")
            self.assertEqual(0, first.returncode, first.stderr)
            after_first = events_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(before) + 1, len(after_first))
            self.assertEqual("audit_succeeded", json.loads(after_first[-1])["type"])

            second = run_cli(path, "advance")
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(
                after_first, events_path.read_text(encoding="utf-8").splitlines()
            )
            self.assertEqual(
                "COMPLETE", output(run_cli(path, "status"))["completionStatus"]
            )

    def test_audit_revalidates_source_immediately_before_success_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root)
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(0, run_cli(path, "advance").returncode)
            events_path = path.parent / "verification" / "campaign" / "events.jsonl"
            before = events_path.read_text(encoding="utf-8").splitlines()
            calls = 0

            def validating_with_final_drift(
                adapter_path: Path, *, observe_goal_drift: bool = False
            ):
                nonlocal calls
                calls += 1
                if calls == 3:
                    (root / "app.txt").write_text(
                        "changed-before-commit\n", encoding="utf-8"
                    )
                return validate_adapter(
                    adapter_path, observe_goal_drift=observe_goal_drift
                )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch(
                    "cli.validate_adapter", side_effect=validating_with_final_drift
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                return_code = cli_module.main(["advance", "--adapter", str(path)])
            self.assertEqual(1, return_code, stderr.getvalue())
            self.assertIn(
                "AUDIT_AUTHORITY_CHANGED",
                json.loads(stdout.getvalue())["rejectionCodes"],
            )
            self.assertEqual(
                before, events_path.read_text(encoding="utf-8").splitlines()
            )

    def test_failed_case_can_be_repaired_retested_and_regressed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root, command=marker_command())
            (root / "app.txt").write_text("bad\n", encoding="utf-8")
            self.assertEqual(0, run_cli(path, "init").returncode)
            failed = run_cli(path, "advance")
            self.assertEqual(1, failed.returncode)
            self.assertEqual("FAILED", output(failed)["executionStatus"])

            (root / "app.txt").write_text("good\n", encoding="utf-8")
            recorded = self._record_repair(path)
            self.assertEqual(0, recorded.returncode, recorded.stderr)
            persisted = Campaign.load(validate_adapter(path)).state["fixes"][-1]
            self.assertEqual(["C1"], persisted["affectedCriteria"])
            self.assertRegex(
                persisted["rootCauseSource"]["failedSha256"], r"^sha256:[0-9a-f]{64}$"
            )
            self.assertEqual(
                [{"path": "app.txt", "change": "modified"}], persisted["sourceDelta"]
            )

            self.assertEqual(
                "READY_FOR_REGRESSION",
                output(run_cli(path, "advance"))["executionStatus"],
            )
            self.assertEqual(
                "AUDIT_REQUIRED", output(run_cli(path, "advance"))["executionStatus"]
            )
            self.assertEqual(
                "COMPLETE", output(run_cli(path, "advance"))["completionStatus"]
            )

    def test_deleted_faulty_file_keeps_failed_snapshot_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            command = [
                __import__("sys").executable,
                "-c",
                "import pathlib,sys; sys.exit(1 if pathlib.Path('app.txt').exists() else 0)",
            ]
            path = make_project(root, command=command)
            (root / "support.txt").write_text("support\n", encoding="utf-8")
            adapter_value = read_json(path)
            adapter_value["source"]["files"].append("support.txt")
            write_json(path, adapter_value)
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(1, run_cli(path, "advance").returncode)
            failed_sha = Campaign.load(validate_adapter(path)).state["sourceBaseline"][
                "files"
            ][0]["sha256"]
            (root / "app.txt").unlink()
            recorded = self._record_repair(
                path,
                repair_note(
                    root_cause="the obsolete file activates the failing path",
                    summary="remove the obsolete faulty file",
                ),
            )
            self.assertEqual(0, recorded.returncode, recorded.stderr)
            persisted = Campaign.load(validate_adapter(path)).state["fixes"][-1]
            self.assertEqual(failed_sha, persisted["rootCauseSource"]["failedSha256"])
            self.assertEqual(
                [{"path": "app.txt", "change": "deleted"}], persisted["sourceDelta"]
            )

    def test_multiple_repairs_allow_changed_failed_digest_without_numeric_limit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root, command=marker_command())
            (root / "app.txt").write_text("bad\n", encoding="utf-8")
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(1, run_cli(path, "advance").returncode)

            for expected, content in enumerate(
                ("still-bad", "almost-good", "good"), start=1
            ):
                (root / "app.txt").write_text(content + "\n", encoding="utf-8")
                recorded = self._record_repair(path)
                self.assertEqual(0, recorded.returncode, recorded.stderr)
                self.assertEqual(expected, output(recorded)["repairCount"])
                retest = run_cli(path, "advance")
                self.assertEqual(0 if content == "good" else 1, retest.returncode)

            self.assertEqual(
                "AUDIT_REQUIRED", output(run_cli(path, "advance"))["executionStatus"]
            )
            self.assertEqual(
                "COMPLETE", output(run_cli(path, "advance"))["completionStatus"]
            )

    def test_rewording_cannot_bypass_repeated_machine_bound_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root, command=marker_command())
            (root / "app.txt").write_text("bad\n", encoding="utf-8")
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(1, run_cli(path, "advance").returncode)

            (root / "app.txt").write_text("still-bad\n", encoding="utf-8")
            self.assertEqual(0, self._record_repair(path).returncode)
            self.assertEqual(1, run_cli(path, "advance").returncode)
            (root / "app.txt").write_text("bad\n", encoding="utf-8")
            self.assertEqual(0, self._record_repair(path).returncode)
            self.assertEqual(1, run_cli(path, "advance").returncode)
            (root / "app.txt").write_text("almost-good\n", encoding="utf-8")
            rejected = self._record_repair(
                path,
                repair_note(root_cause="reworded diagnosis", summary="reworded change"),
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("without new root-cause evidence", rejected.stderr)

    def test_artifact_tamper_breaks_final_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self._complete(path)
            campaign = Campaign.load(validate_adapter(path))
            run = campaign.state["attempts"][-1]["runs"][-1]
            artifact = (
                campaign.adapter.campaign_root / run["artifactDir"] / "stdout.txt"
            )
            artifact.write_text("tampered\n", encoding="utf-8")
            status = output(run_cli(path, "status"))
            self.assertEqual("COMPLETE", status["executionStatus"])
            self.assertEqual("INCOMPLETE", status["completionStatus"])
            self.assertIn("ARTIFACT_INVALID", status["currentAuditRejectionCodes"])

    def test_source_drift_after_completion_preserves_successful_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root)
            self._complete(path)
            events_path = path.parent / "verification" / "campaign" / "events.jsonl"
            completed_events = events_path.read_bytes()
            (root / "app.txt").write_text("drifted\n", encoding="utf-8")
            status = output(run_cli(path, "status"))
            self.assertEqual("INCOMPLETE", status["completionStatus"])
            self.assertIn(
                "SOURCE_BASELINE_MISMATCH", status["currentAuditRejectionCodes"]
            )
            self.assertEqual(completed_events, events_path.read_bytes())

    def test_schema_five_campaign_is_preserved_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            events = path.parent / "verification" / "campaign" / "events.jsonl"
            event = json.loads(events.read_text(encoding="utf-8").splitlines()[0])
            event["schemaVersion"] = 5
            event["kernelVersion"] = "0.5.0"
            unsigned = dict(event)
            unsigned.pop("eventHash")
            event["eventHash"] = sha256_bytes(canonical_bytes(unsigned))
            events.write_bytes(canonical_bytes(event) + b"\n")
            preserved = events.read_bytes()

            result = run_cli(path, "status")
            self.assertEqual(2, result.returncode)
            self.assertIn("journal schemaVersion must be 6", result.stderr)
            self.assertEqual(preserved, events.read_bytes())


if __name__ == "__main__":
    unittest.main()
