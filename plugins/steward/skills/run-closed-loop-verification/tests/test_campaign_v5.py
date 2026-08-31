from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
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
from adapter_paths import (
    current_platform,
    observe_source,
    source_snapshot_changed_entries,
    validate_adapter,
)
from audit import audit_report, status_report
from journal_state import Campaign
from model import CampaignError


def output(result: object) -> dict:
    value = result.stdout
    if not value:
        raise AssertionError(result.stderr)
    return json.loads(value)


class CampaignV5Tests(unittest.TestCase):
    def _complete(self, path: Path) -> None:
        self.assertEqual(0, run_cli(path, "init").returncode)
        self.assertEqual(0, run_cli(path, "run", "--mode", "initial").returncode)
        self.assertEqual(0, run_cli(path, "run", "--mode", "regression").returncode)
        self.assertEqual(0, run_cli(path, "audit").returncode)

    def test_copied_complete_campaign_is_bound_to_its_original_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source_adapter = make_project(source)
            self._complete(source_adapter)
            successful_audit = output(run_cli(source_adapter, "status"))["successfulAudit"]

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

            other = base / "other"
            make_project(other)
            shutil.rmtree(other / ".steward")
            shutil.copytree(source / ".steward", other / ".steward")

            for copied in (sibling, other):
                with self.subTest(copied=copied.name):
                    adapter = copied / ".steward" / "project-adapter.json"
                    status = output(run_cli(adapter, "status"))
                    self.assertFalse(status["worktreeBindingConsistent"])
                    self.assertEqual("INCOMPLETE", status["completionStatus"])
                    self.assertIn(
                        "WORKTREE_BINDING_DRIFT",
                        status["currentAuditRejectionCodes"],
                    )
                    self.assertEqual(successful_audit, status["successfulAudit"])
                    rejected = run_cli(adapter, "audit")
                    self.assertEqual(1, rejected.returncode)
                    self.assertIn(
                        "WORKTREE_BINDING_DRIFT", output(rejected)["rejectionCodes"]
                    )
                    blocked = run_cli(adapter, "resume")
                    self.assertEqual(2, blocked.returncode)
                    self.assertIn("WORKTREE_BINDING_DRIFT", blocked.stderr)

    def test_runtime_platform_drift_blocks_mutation_and_current_completion(self) -> None:
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
            self.assertFalse(status["runtimePlatformConsistent"])
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
            self.assertIn(
                "GOAL_WORKSPACE_INVALID", status["currentAuditRejectionCodes"]
            )
            rejected = run_cli(path, "audit")
            self.assertEqual(1, rejected.returncode)
            self.assertIn("GOAL_WORKSPACE_INVALID", output(rejected)["rejectionCodes"])
            self.assertEqual(successful_history, events.read_bytes())

            fresh = make_project(Path(temporary) / "invalid-before-init")
            (fresh.parent / "goal-context" / "goal-context.md").unlink()
            blocked = run_cli(fresh, "init")
            self.assertEqual(2, blocked.returncode)
            self.assertIn("GOAL_WORKSPACE_INVALID", blocked.stderr)

    def test_optional_unavailable_case_is_not_run_but_required_case_blocks(self) -> None:
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
            self.assertEqual(0, run_cli(path, "run", "--mode", "initial").returncode)
            regression = run_cli(path, "run", "--mode", "regression")
            self.assertEqual(0, regression.returncode, regression.stderr)
            statuses = {
                item["id"]: item["finalStatus"]
                for item in output(regression)["coverage"]["cases"]
            }
            self.assertEqual("NOT_RUN", statuses["optional-host"])
            self.assertEqual(0, run_cli(path, "audit").returncode)

            path = make_project(root / "required", platform=unavailable)
            self.assertEqual(0, run_cli(path, "init").returncode)
            blocked = run_cli(path, "run", "--mode", "initial")
            self.assertEqual(1, blocked.returncode)
            self.assertEqual("BLOCKED", output(blocked)["executionStatus"])

    def test_source_drift_before_regression_permanently_blocks_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root)
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(0, run_cli(path, "run", "--mode", "initial").returncode)
            (root / "app.txt").write_text("changed\n", encoding="utf-8")
            regression = run_cli(path, "run", "--mode", "regression")
            self.assertEqual(1, regression.returncode)
            self.assertEqual("BLOCKED", output(regression)["executionStatus"])
            resumed = run_cli(path, "resume")
            self.assertEqual(2, resumed.returncode)
            self.assertIn("permanently blocked", resumed.stderr)

    def test_resume_records_interruption_and_restarts_the_authoritative_round(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            campaign = Campaign.load(validate_adapter(path))
            campaign.commit(
                "attempt_started",
                {
                    "attemptId": "attempt-simulated-interruption",
                    "mode": "initial",
                    "sourceFingerprint": campaign.state["sourceBaseline"]["fingerprint"],
                    "caseIds": ["acceptance"],
                },
            )

            resumed = run_cli(path, "resume")
            self.assertEqual(0, resumed.returncode, resumed.stderr)
            self.assertEqual("READY_FOR_REGRESSION", output(resumed)["executionStatus"])
            replayed = Campaign.load(validate_adapter(path))
            self.assertEqual("INTERRUPTED", replayed.state["attempts"][0]["status"])
            self.assertEqual("READY_FOR_REGRESSION", replayed.state["attempts"][1]["status"])

    def test_initial_regression_audit_completes_on_one_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            initial = run_cli(path, "run", "--mode", "initial")
            self.assertEqual(0, initial.returncode, initial.stderr)
            self.assertEqual("READY_FOR_REGRESSION", output(initial)["executionStatus"])
            regression = run_cli(path, "run", "--mode", "regression")
            self.assertEqual(0, regression.returncode, regression.stderr)
            self.assertEqual("AUDIT_REQUIRED", output(regression)["executionStatus"])
            audit = run_cli(path, "audit")
            self.assertEqual(0, audit.returncode, audit.stderr)
            report = output(audit)
            self.assertTrue(report["ok"])
            self.assertEqual("COMPLETE", report["completionStatus"])
            self.assertEqual("COMPLETE", report["executionStatus"])
            self.assertEqual(
                ["acceptance"], report["coverage"]["criteria"][0]["finalPassingCaseIds"]
            )
            status = output(run_cli(path, "status"))
            self.assertEqual("COMPLETE", status["executionStatus"])
            self.assertEqual("COMPLETE", status["completionStatus"])

    def test_successful_audit_is_durable_and_idempotent_after_context_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(0, run_cli(path, "run", "--mode", "initial").returncode)
            self.assertEqual(0, run_cli(path, "run", "--mode", "regression").returncode)
            events_path = path.parent / "verification" / "campaign" / "events.jsonl"
            before = events_path.read_text(encoding="utf-8").splitlines()

            first = run_cli(path, "audit")
            self.assertEqual(0, first.returncode, first.stderr)
            first_report = output(first)
            after_first = events_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(before) + 1, len(after_first))
            self.assertEqual("audit_succeeded", json.loads(after_first[-1])["type"])
            self.assertEqual("COMPLETE", first_report["executionStatus"])
            self.assertIsNone(first_report["resumeMode"])

            second = run_cli(path, "audit")
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(after_first, events_path.read_text(encoding="utf-8").splitlines())

            # A fresh command process reconstructs COMPLETE from journal authority.
            status = output(run_cli(path, "status"))
            self.assertEqual("COMPLETE", status["executionStatus"])
            self.assertEqual("COMPLETE", status["completionStatus"])
            self.assertIsNone(status["resumeMode"])
            self.assertEqual(
                first_report["successfulAudit"], status["successfulAudit"]
            )
            resumed = run_cli(path, "resume")
            self.assertEqual(0, resumed.returncode, resumed.stderr)
            self.assertEqual("COMPLETE", output(resumed)["completionStatus"])
            self.assertEqual(
                after_first, events_path.read_text(encoding="utf-8").splitlines()
            )

    def test_complete_resume_recovers_projections_from_durable_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self._complete(path)
            campaign_root = path.parent / "verification" / "campaign"
            write_json(campaign_root / "state.json", {"interruptedProjection": True})
            write_json(campaign_root / "summary.json", {"interruptedProjection": True})
            resumed = run_cli(path, "resume")
            self.assertEqual(0, resumed.returncode, resumed.stderr)
            self.assertEqual("COMPLETE", output(resumed)["completionStatus"])
            self.assertEqual("COMPLETE", read_json(campaign_root / "state.json")["status"])
            self.assertEqual("COMPLETE", read_json(campaign_root / "summary.json")["status"])

    def test_audit_revalidates_source_immediately_before_success_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root)
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(0, run_cli(path, "run", "--mode", "initial").returncode)
            self.assertEqual(0, run_cli(path, "run", "--mode", "regression").returncode)
            events_path = path.parent / "verification" / "campaign" / "events.jsonl"
            before = events_path.read_text(encoding="utf-8").splitlines()
            calls = 0

            def validating_with_final_drift(
                adapter_path: Path, *, observe_goal_drift: bool = False
            ) -> object:
                nonlocal calls
                calls += 1
                if calls == 3:
                    (root / "app.txt").write_text("changed-before-commit\n", encoding="utf-8")
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
                return_code = cli_module.main(
                    ["audit", "--adapter", str(path)]
                )
            self.assertEqual(1, return_code, stderr.getvalue())
            self.assertEqual(3, calls)
            report = json.loads(stdout.getvalue())
            self.assertIn("SOURCE_BASELINE_MISMATCH", report["rejectionCodes"])
            after = events_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(before, after)
            self.assertFalse(any(json.loads(line)["type"] == "audit_succeeded" for line in after))

    def test_failed_case_can_be_repaired_retested_and_regressed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root, command=marker_command())
            (root / "app.txt").write_text("bad\n", encoding="utf-8")
            self.assertEqual(0, run_cli(path, "init").returncode)
            failed = run_cli(path, "run", "--mode", "initial")
            self.assertEqual(1, failed.returncode, failed.stderr)
            failed_report = output(failed)
            self.assertEqual("FAILED", failed_report["executionStatus"])
            self.assertEqual("acceptance", failed_report["latestFailure"]["caseId"])
            self.assertEqual([], failed_report["fixContext"]["selectedSourceFiles"])
            self.assertEqual(1, failed_report["fixContext"]["failedSourceFileCount"])
            status_projection = output(
                run_cli(path, "status", "--source-path", "app.txt")
            )
            failed_file_projection = status_projection["fixContext"][
                "selectedSourceFiles"
            ][0]
            self.assertEqual("app.txt", failed_file_projection["path"])
            self.assertEqual(1, failed_file_projection["lineCount"])
            self.assertRegex(
                failed_file_projection["failedSha256"], r"^sha256:[0-9a-f]{64}$"
            )
            self.assertEqual(failed_report["latestFailure"], status_projection["latestFailure"])
            self.assertEqual(
                failed_report["fixContext"]["failureSignature"],
                status_projection["fixContext"]["failureSignature"],
            )

            adapter = validate_adapter(path)
            campaign = Campaign.load(adapter)
            attempt = campaign.state["attempts"][-1]
            run = attempt["runs"][-1]
            before = campaign.state["sourceBaseline"]
            (root / "app.txt").write_text("good\n", encoding="utf-8")
            after = observe_source(adapter)
            fix = {
                "schemaVersion": 1,
                "failedCaseId": run["caseId"],
                "failedRound": attempt["mode"],
                "failedAttemptId": attempt["id"],
                "failedRunId": run["runId"],
                "failedSourceFingerprint": run["sourceFingerprint"],
                "fixedSourceFingerprint": after["fingerprint"],
                "rootCause": "app.txt contained the rejected marker",
                "rootCauseSource": {
                    "path": "app.txt",
                    "lineStart": 1,
                    "lineEnd": 1,
                    "failedSha256": failed_file_projection["failedSha256"],
                },
                "affectedCriteria": ["C1"],
                "sourceDelta": source_snapshot_changed_entries(before, after),
                "fixSummary": "replace the rejected marker with the accepted marker",
                "newEvidence": ["the failing command reads app.txt and requires good"],
            }
            fix_path = root / ".steward" / "fix.json"
            write_json(fix_path, fix)
            recorded = run_cli(path, "record-fix", "--fix", str(fix_path))
            self.assertEqual(0, recorded.returncode, recorded.stderr)
            self.assertEqual(1, output(recorded)["repairCount"])
            retest = run_cli(path, "retest")
            self.assertEqual(0, retest.returncode, retest.stderr)
            self.assertEqual("READY_FOR_REGRESSION", output(retest)["executionStatus"])
            self.assertEqual(0, run_cli(path, "run", "--mode", "regression").returncode)
            self.assertEqual(0, run_cli(path, "audit").returncode)

    def test_deleted_faulty_file_keeps_failed_snapshot_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            command = [
                sys.executable,
                "-c",
                (
                    "import os,pathlib,sys; ok=not pathlib.Path('app.txt').exists(); "
                    "pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'],'proof.txt').write_text('ok',encoding='utf-8') if ok else None; "
                    "sys.exit(0 if ok else 1)"
                ),
            ]
            path = make_project(root, command=command)
            (root / "support.txt").write_text("support\n", encoding="utf-8")
            adapter_value = read_json(path)
            adapter_value["source"]["files"].append("support.txt")
            write_json(path, adapter_value)
            (root / "app.txt").write_text("faulty\n", encoding="utf-8")
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(1, run_cli(path, "run", "--mode", "initial").returncode)
            adapter = validate_adapter(path)
            campaign = Campaign.load(adapter)
            attempt = campaign.state["attempts"][-1]
            failed_run = attempt["runs"][-1]
            before = campaign.state["sourceBaseline"]
            failed_file = next(
                item for item in before["files"] if item["path"] == "app.txt"
            )
            (root / "app.txt").unlink()
            after = observe_source(adapter)
            fix = {
                "schemaVersion": 1,
                "failedCaseId": failed_run["caseId"],
                "failedRound": attempt["mode"],
                "failedAttemptId": attempt["id"],
                "failedRunId": failed_run["runId"],
                "failedSourceFingerprint": failed_run["sourceFingerprint"],
                "fixedSourceFingerprint": after["fingerprint"],
                "rootCause": "the obsolete file activated the failing path",
                "rootCauseSource": {
                    "path": "app.txt",
                    "lineStart": 1,
                    "lineEnd": 1,
                    "failedSha256": failed_file["sha256"],
                },
                "affectedCriteria": ["C1"],
                "sourceDelta": [{"path": "app.txt", "change": "deleted"}],
                "fixSummary": "remove the obsolete faulty file",
                "newEvidence": ["the acceptance command requires the obsolete file to be absent"],
            }
            fix_path = root / ".steward" / "fix.json"
            write_json(fix_path, fix)
            recorded = run_cli(path, "record-fix", "--fix", str(fix_path))
            self.assertEqual(0, recorded.returncode, recorded.stderr)
            persisted = Campaign.load(validate_adapter(path)).state["fixes"][-1]
            self.assertEqual(failed_file["sha256"], persisted["rootCauseSource"]["failedSha256"])
            self.assertEqual(0, run_cli(path, "retest").returncode)

    def test_multiple_repairs_allow_changed_failed_digest_without_numeric_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root, command=marker_command())
            (root / "app.txt").write_text("bad\n", encoding="utf-8")
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(1, run_cli(path, "run", "--mode", "initial").returncode)

            def record_repair(content: str, evidence: str) -> object:
                adapter = validate_adapter(path)
                campaign = Campaign.load(adapter)
                attempt = campaign.state["attempts"][-1]
                failed_run = attempt["runs"][-1]
                before = campaign.state["sourceBaseline"]
                (root / "app.txt").write_text(content + "\n", encoding="utf-8")
                after = observe_source(adapter)
                fix = {
                    "schemaVersion": 1,
                    "failedCaseId": failed_run["caseId"],
                    "failedRound": attempt["mode"],
                    "failedAttemptId": attempt["id"],
                    "failedRunId": failed_run["runId"],
                    "failedSourceFingerprint": failed_run["sourceFingerprint"],
                    "fixedSourceFingerprint": after["fingerprint"],
                    "rootCause": "app.txt still contains a rejected marker",
                    "rootCauseSource": {
                        "path": "app.txt",
                        "lineStart": 1,
                        "lineEnd": 1,
                        "failedSha256": before["files"][0]["sha256"],
                    },
                    "affectedCriteria": ["C1"],
                    "sourceDelta": source_snapshot_changed_entries(before, after),
                    "fixSummary": "advance app.txt toward the accepted marker",
                    "newEvidence": [evidence],
                }
                fix_path = root / ".steward" / "fix.json"
                write_json(fix_path, fix)
                return run_cli(path, "record-fix", "--fix", str(fix_path))

            first = record_repair("still-bad", "first distinct root-cause observation")
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(1, output(first)["repairCount"])
            self.assertEqual(1, run_cli(path, "retest").returncode)

            second = record_repair(
                "almost-good", "first distinct root-cause observation"
            )
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(2, output(second)["repairCount"])
            self.assertEqual(1, run_cli(path, "retest").returncode)

            third = record_repair("good", "first distinct root-cause observation")
            self.assertEqual(0, third.returncode, third.stderr)
            self.assertEqual(3, output(third)["repairCount"])
            self.assertEqual(0, run_cli(path, "retest").returncode)
            self.assertEqual(0, run_cli(path, "run", "--mode", "regression").returncode)
            self.assertEqual(0, run_cli(path, "audit").returncode)

    def test_rewording_cannot_bypass_repeated_machine_bound_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root, command=marker_command())
            (root / "app.txt").write_text("bad\n", encoding="utf-8")
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(1, run_cli(path, "run", "--mode", "initial").returncode)

            def repair(content: str, root_cause: str, evidence: str) -> object:
                adapter = validate_adapter(path)
                campaign = Campaign.load(adapter)
                attempt = campaign.state["attempts"][-1]
                failed_run = attempt["runs"][-1]
                before = campaign.state["sourceBaseline"]
                (root / "app.txt").write_text(content + "\n", encoding="utf-8")
                after = observe_source(adapter)
                fix = {
                    "schemaVersion": 1,
                    "failedCaseId": failed_run["caseId"],
                    "failedRound": attempt["mode"],
                    "failedAttemptId": attempt["id"],
                    "failedRunId": failed_run["runId"],
                    "failedSourceFingerprint": failed_run["sourceFingerprint"],
                    "fixedSourceFingerprint": after["fingerprint"],
                    "rootCause": root_cause,
                    "rootCauseSource": {
                        "path": "app.txt",
                        "lineStart": 1,
                        "lineEnd": 1,
                        "failedSha256": before["files"][0]["sha256"],
                    },
                    "affectedCriteria": ["C1"],
                    "sourceDelta": source_snapshot_changed_entries(before, after),
                    "fixSummary": "change the marker",
                    "newEvidence": [evidence],
                }
                fix_path = root / ".steward" / "fix.json"
                write_json(fix_path, fix)
                return run_cli(path, "record-fix", "--fix", str(fix_path))

            self.assertEqual(0, repair("still-bad", "first diagnosis", "first prose").returncode)
            self.assertEqual(1, run_cli(path, "retest").returncode)
            self.assertEqual(0, repair("bad", "second diagnosis", "second prose").returncode)
            self.assertEqual(1, run_cli(path, "retest").returncode)
            rejected = repair(
                "almost-good",
                "entirely reworded diagnosis",
                "entirely reworded evidence",
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("without new root-cause evidence", rejected.stderr)

    def test_verify_only_refuses_fix_recording(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root, command=marker_command())
            (root / "app.txt").write_text("bad\n", encoding="utf-8")
            self.assertEqual(0, run_cli(path, "init", "--repair-policy", "verify-only").returncode)
            self.assertEqual(1, run_cli(path, "run", "--mode", "initial").returncode)
            placeholder = root / ".steward" / "fix.json"
            write_json(placeholder, {})
            result = run_cli(path, "record-fix", "--fix", str(placeholder))
            self.assertEqual(2, result.returncode)
            self.assertIn("verify-only", result.stderr)

    def test_fix_context_source_selection_is_bounded_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root, command=marker_command())
            (root / "app.txt").write_text("bad\n", encoding="utf-8")
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(1, run_cli(path, "run", "--mode", "initial").returncode)

            default = output(run_cli(path, "status"))["fixContext"]
            self.assertEqual(1, default["failedSourceFileCount"])
            self.assertEqual([], default["selectedSourceFiles"])
            selected = output(
                run_cli(path, "status", "--source-path", "app.txt")
            )["fixContext"]["selectedSourceFiles"]
            self.assertEqual(["app.txt"], [item["path"] for item in selected])
            self.assertRegex(selected[0]["failedSha256"], r"^sha256:[0-9a-f]{64}$")

            duplicate = run_cli(
                path,
                "status",
                "--source-path",
                "app.txt",
                "--source-path",
                "app.txt",
            )
            self.assertEqual(2, duplicate.returncode)
            self.assertIn("must be unique", duplicate.stderr)
            missing = run_cli(path, "status", "--source-path", "missing.txt")
            self.assertEqual(2, missing.returncode)
            self.assertIn("not in the failed source baseline", missing.stderr)
            too_many_arguments: list[str] = []
            for index in range(65):
                too_many_arguments.extend(["--source-path", f"file-{index}.txt"])
            bounded = run_cli(path, "status", *too_many_arguments)
            self.assertEqual(2, bounded.returncode)
            self.assertIn("at most 64", bounded.stderr)

    def test_projection_tamper_is_reported_and_audit_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            state_path = path.parent / "verification" / "campaign" / "state.json"
            state = read_json(state_path)
            state["repairCount"] = 99
            write_json(state_path, state)
            self.assertFalse(output(run_cli(path, "status"))["projectionConsistent"])
            audit = run_cli(path, "audit")
            self.assertEqual(1, audit.returncode)
            self.assertIn("JOURNAL_PROJECTION_MISMATCH", output(audit)["rejectionCodes"])

    def test_missing_goal_is_reported_from_the_initialized_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            (path.parent / "goal.txt").unlink()

            status = run_cli(path, "status")
            self.assertEqual(0, status.returncode, status.stderr)
            self.assertEqual("C1", output(status)["coverage"]["criteria"][0]["id"])
            audit = run_cli(path, "audit")
            self.assertEqual(1, audit.returncode)
            self.assertIn("GOAL_CONTRACT_DRIFT", output(audit)["rejectionCodes"])

    def test_artifact_tamper_breaks_final_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(0, run_cli(path, "run", "--mode", "initial").returncode)
            self.assertEqual(0, run_cli(path, "run", "--mode", "regression").returncode)
            self.assertEqual(0, run_cli(path, "audit").returncode)
            campaign = Campaign.load(validate_adapter(path))
            successful_audit = campaign.state["successfulAudit"]
            run = campaign.state["attempts"][-1]["runs"][-1]
            artifact = campaign.adapter.campaign_root / run["artifactDir"] / "stdout.txt"
            artifact.write_text("tampered\n", encoding="utf-8")
            audit = run_cli(path, "audit")
            self.assertEqual(1, audit.returncode)
            self.assertIn("ARTIFACT_INVALID", output(audit)["rejectionCodes"])
            status = output(run_cli(path, "status"))
            self.assertEqual("COMPLETE", status["executionStatus"])
            self.assertEqual("INCOMPLETE", status["completionStatus"])
            self.assertEqual(successful_audit, status["successfulAudit"])

    def test_source_drift_after_completion_preserves_successful_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root)
            self.assertEqual(0, run_cli(path, "init").returncode)
            self.assertEqual(0, run_cli(path, "run", "--mode", "initial").returncode)
            self.assertEqual(0, run_cli(path, "run", "--mode", "regression").returncode)
            self.assertEqual(0, run_cli(path, "audit").returncode)
            events_path = path.parent / "verification" / "campaign" / "events.jsonl"
            completed_events = events_path.read_bytes()
            completed_binding = output(run_cli(path, "status"))["successfulAudit"]

            (root / "app.txt").write_text("drifted\n", encoding="utf-8")
            status = output(run_cli(path, "status"))
            self.assertEqual("COMPLETE", status["executionStatus"])
            self.assertEqual("INCOMPLETE", status["completionStatus"])
            self.assertIn("SOURCE_BASELINE_MISMATCH", status["currentAuditRejectionCodes"])
            rejected = run_cli(path, "audit")
            self.assertEqual(1, rejected.returncode)
            self.assertEqual(completed_events, events_path.read_bytes())
            self.assertEqual(completed_binding, output(rejected)["successfulAudit"])

    def test_journal_schema_and_kernel_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            events = path.parent / "verification" / "campaign" / "events.jsonl"
            event = json.loads(events.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(5, event["schemaVersion"])
            self.assertEqual("0.5.0", event["kernelVersion"])
            binding = event["payload"]["worktreeBinding"]
            self.assertEqual(str(path.parent.parent.resolve()), binding["targetWorktreeRoot"])
            state = read_json(path.parent / "verification" / "campaign" / "state.json")
            summary = read_json(path.parent / "verification" / "campaign" / "summary.json")
            self.assertEqual(binding, state["worktreeBinding"])
            self.assertEqual(binding, summary["worktreeBinding"])


if __name__ == "__main__":
    unittest.main()
