"""Recovery and bounded-restart tests through the public campaign CLI."""

from __future__ import annotations

import errno
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .helpers import (
        campaign_path,
        json_output,
        load_state,
        make_adapter,
        make_case,
        read_json,
        run_cli,
        write_fix_for_latest_failure,
    )
except ImportError:  # unittest discovery with tests/ as the import root
    from helpers import (  # type: ignore
        campaign_path,
        json_output,
        load_state,
        make_adapter,
        make_case,
        read_json,
        run_cli,
        write_fix_for_latest_failure,
    )


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = SKILL_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import journal_state as journal_runtime  # noqa: E402
from adapter_paths import validate_adapter  # noqa: E402
from engine import retest_locked, run_regression_locked  # noqa: E402
from journal_state import Campaign, CampaignLock  # noqa: E402
from runner_evidence import execute_case  # noqa: E402


def _proof_statement() -> str:
    return (
        "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
        "(evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n"
    )


def _counter_prelude(counter_name: str) -> str:
    return (
        "import os, signal, time\n"
        "from pathlib import Path\n"
        f"counter = Path({counter_name!r})\n"
        "count = int(counter.read_text(encoding='utf-8')) + 1 if counter.exists() else 1\n"
        "counter.write_text(str(count), encoding='utf-8')\n"
    )


def _interrupt_parent_statement() -> str:
    return (
        "os.kill(os.getppid(), signal.SIGINT)\n"
        "time.sleep(2)\n"
        "raise SystemExit(99)\n"
    )


def _events(adapter: Path) -> list[dict[str, object]]:
    journal = campaign_path(adapter) / "events.jsonl"
    return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]


def _attempts(state: dict[str, object], mode: str) -> list[dict[str, object]]:
    attempts = state.get("attempts")
    if not isinstance(attempts, list):
        raise AssertionError("state has no attempts array")
    return [attempt for attempt in attempts if attempt.get("mode") == mode]


@unittest.skipUnless(os.name == "posix", "signal-based interruption fixture requires POSIX")
class InterruptionRecoveryTests(unittest.TestCase):
    def test_initial_interruption_resumes_from_journal_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            script = (
                _counter_prelude("initial-count.txt")
                + "if count == 1:\n"
                + "    "
                + _interrupt_parent_statement().replace("\n", "\n    ").rstrip()
                + "\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                project,
                [make_case("smoke", "smoke", argv=(sys.executable, "-c", script))],
            )

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=130)

            interrupted = load_state(adapter)
            first_attempt_id = interrupted["currentAttemptId"]
            self.assertEqual(interrupted["status"], "RUNNING")
            self.assertEqual(interrupted["cases"]["smoke"]["status"], "RUNNING")

            # Running commands must be able to recreate disposable projections
            # from the authoritative append-only journal while holding the lock.
            root = campaign_path(adapter)
            (root / "state.json").unlink()
            (root / "summary.json").unlink()

            resumed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual(resumed["status"], "READY_FOR_REGRESSION")
            self.assertTrue((root / "state.json").is_file())
            self.assertTrue((root / "summary.json").is_file())
            state = load_state(adapter)
            initial_attempts = _attempts(state, "initial")
            self.assertEqual([item["status"] for item in initial_attempts], ["INTERRUPTED", "PASS"])
            self.assertEqual(initial_attempts[0]["id"], first_attempt_id)
            self.assertEqual(state["cases"]["smoke"]["status"], "PASS")

    def test_retest_interruption_reuses_fix_binding_and_continues_initial(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            retest_script = (
                _counter_prelude("retest-count.txt")
                + "if count == 1:\n"
                + "    raise SystemExit(7)\n"
                + "if count == 2:\n"
                + "    "
                + _interrupt_parent_statement().replace("\n", "\n    ").rstrip()
                + "\n"
                + _proof_statement()
            )
            continuation_script = (
                "from pathlib import Path\n"
                "import os\n"
                "marker = Path('continued.txt')\n"
                "marker.write_text('continued', encoding='utf-8')\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                project,
                [
                    make_case("functional", "functional", argv=(sys.executable, "-c", retest_script)),
                    make_case(
                        "workflow",
                        "workflow",
                        argv=(sys.executable, "-c", continuation_script),
                        depends_on=("functional",),
                    ),
                ],
            )

            run_cli(adapter, "init", expected=0)
            failed = json_output(run_cli(adapter, "run", expected=1))
            self.assertEqual(failed["status"], "FAILED")
            fix = write_fix_for_latest_failure(adapter)
            run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)

            run_cli(adapter, "retest", expected=130)
            interrupted_state = load_state(adapter)
            interrupted_attempt = _attempts(interrupted_state, "retest")[-1]
            self.assertEqual(interrupted_attempt["status"], "RUNNING")
            pending_fix = interrupted_state["pendingFix"]

            resumed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual(resumed["status"], "READY_FOR_REGRESSION")
            state = load_state(adapter)
            retests = _attempts(state, "retest")
            self.assertEqual([item["status"] for item in retests], ["INTERRUPTED", "RETEST_PASSED"])
            self.assertEqual(retests[-1].get("resumedFrom"), interrupted_attempt["id"])
            self.assertIsNone(state["pendingFix"])
            self.assertEqual(pending_fix["fixId"], state["fixes"][-1]["fixId"])
            self.assertEqual(state["cases"]["functional"]["status"], "RETEST_PASSED")
            self.assertEqual(state["cases"]["workflow"]["status"], "PASS")
            self.assertEqual((project / "continued.txt").read_text(encoding="utf-8"), "continued")

    def test_regression_interruption_restarts_clean_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            script = (
                _counter_prelude("regression-interrupt-count.txt")
                + "if count == 2:\n"
                + "    "
                + _interrupt_parent_statement().replace("\n", "\n    ").rstrip()
                + "\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                project,
                [make_case("integration", "integration", argv=(sys.executable, "-c", script))],
            )

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=130)
            resumed = json_output(run_cli(adapter, "resume", expected=0))

            self.assertEqual(resumed["status"], "COMPLETE")
            self.assertEqual(resumed["executionStatus"], "COMPLETE")
            self.assertEqual(resumed["completionStatus"], "AUDIT_REQUIRED")
            self.assertIsNone(resumed["resumeMode"])
            self.assertEqual(resumed["coverage"]["mode"], "narrow")
            state = load_state(adapter)
            regressions = _attempts(state, "regression")
            self.assertEqual([item["status"] for item in regressions], ["INTERRUPTED", "PASS"])
            self.assertEqual(state["finalRegressionAttemptId"], regressions[-1]["id"])

    def test_interruption_after_successful_retest_continues_initial_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            repaired_case = (
                _counter_prelude("repaired-count.txt")
                + "if count == 1:\n"
                + "    raise SystemExit(7)\n"
                + _proof_statement()
            )
            continuation = (
                _counter_prelude("continuation-count.txt")
                + "if count == 1:\n"
                + "    "
                + _interrupt_parent_statement().replace("\n", "\n    ").rstrip()
                + "\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                project,
                [
                    make_case(
                        "functional",
                        "functional",
                        argv=(sys.executable, "-c", repaired_case),
                    ),
                    make_case(
                        "workflow",
                        "workflow",
                        argv=(sys.executable, "-c", continuation),
                        depends_on=("functional",),
                    ),
                ],
            )

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            fix = write_fix_for_latest_failure(adapter)
            run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)
            run_cli(adapter, "retest", expected=130)

            interrupted = load_state(adapter)
            self.assertIsNone(interrupted["pendingFix"])
            self.assertEqual(interrupted["cases"]["functional"]["status"], "RETEST_PASSED")
            self.assertEqual(interrupted["cases"]["workflow"]["status"], "RUNNING")
            self.assertEqual(interrupted["resumeMode"], "initial")

            resumed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual(resumed["status"], "READY_FOR_REGRESSION")
            self.assertEqual(resumed["cases"]["functional"]["status"], "RETEST_PASSED")
            self.assertEqual(resumed["cases"]["workflow"]["status"], "PASS")


class BlockedAndFixRecoveryTests(unittest.TestCase):
    def test_quick_retest_checkpoint_survives_crash_before_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            runner = project / "runner.py"
            runner.write_text("raise SystemExit(8)\n", encoding="utf-8")
            quick_case = make_case(
                "quick-smoke",
                "smoke",
                argv=(sys.executable, "runner.py"),
            )
            quick_case["quick"] = True
            adapter = make_adapter(
                project,
                [quick_case],
                source_files=("runner.py",),
            )

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", "--phase", "quick", expected=1)
            runner.write_text(
                "import os\nfrom pathlib import Path\n" + _proof_statement(),
                encoding="utf-8",
            )
            fix = write_fix_for_latest_failure(
                adapter,
                changed_files=("runner.py",),
                external_condition=False,
            )
            run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)

            runtime_adapter = validate_adapter(adapter, observe_trace_drift=True)
            with CampaignLock(runtime_adapter.campaign_root):
                campaign = Campaign.load(runtime_adapter)
                with mock.patch(
                    "engine.run_quick_locked", side_effect=KeyboardInterrupt
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        retest_locked(campaign)

            checkpoint = load_state(adapter)
            self.assertEqual("PENDING", checkpoint["status"])
            self.assertEqual("quick", checkpoint["resumeMode"])
            self.assertEqual("RETEST_PASSED", checkpoint["attempts"][-1]["status"])
            retest_id = checkpoint["attempts"][-1]["id"]

            resumed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual("PENDING", resumed["status"])
            self.assertEqual("initial", resumed["resumeMode"])
            self.assertEqual("quick", resumed["attempts"][-1]["mode"])
            self.assertEqual(retest_id, resumed["attempts"][-1]["resumedFrom"])

    def test_regression_retest_checkpoint_resumes_from_latest_retest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            runner = project / "runner.py"
            runner.write_text(
                _counter_prelude("regression-repair-count.txt")
                + "if count == 2:\n    raise SystemExit(8)\n"
                + _proof_statement(),
                encoding="utf-8",
            )
            adapter = make_adapter(
                project,
                [
                    make_case(
                        "integration",
                        "integration",
                        argv=(sys.executable, "runner.py"),
                    )
                ],
                source_files=("runner.py",),
            )

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=1)
            runner.write_text(
                "import os\nfrom pathlib import Path\n" + _proof_statement(),
                encoding="utf-8",
            )
            fix = write_fix_for_latest_failure(
                adapter,
                changed_files=("runner.py",),
                external_condition=False,
            )
            run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)
            retested = json_output(run_cli(adapter, "retest", expected=0))
            self.assertEqual("READY_FOR_REGRESSION", retested["status"])
            self.assertEqual("regression", retested["resumeMode"])
            retest_id = retested["attempts"][-1]["id"]

            resumed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual("COMPLETE", resumed["executionStatus"])
            self.assertEqual("AUDIT_REQUIRED", resumed["completionStatus"])
            self.assertEqual(retest_id, resumed["attempts"][-1]["resumedFrom"])

    def test_blocked_initial_case_is_retried_once_by_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            script = (
                _counter_prelude("blocked-count.txt")
                + "if count == 1:\n"
                + "    print('pass' + 'word=' + 'fixture-value')\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                project,
                [make_case("smoke", "smoke", argv=(sys.executable, "-c", script))],
            )

            run_cli(adapter, "init", expected=0)
            blocked = json_output(run_cli(adapter, "run", expected=1))
            self.assertEqual(blocked["status"], "BLOCKED")

            resumed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual(resumed["status"], "READY_FOR_REGRESSION")
            state = load_state(adapter)
            initial_attempts = _attempts(state, "initial")
            self.assertEqual([item["status"] for item in initial_attempts], ["BLOCKED", "PASS"])
            self.assertEqual((project / "blocked-count.txt").read_text(encoding="utf-8"), "2")

    def test_resume_retries_a_still_blocked_case_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            script = (
                _counter_prelude("persistent-block-count.txt")
                + "print('pass' + 'word=' + 'fixture-value')\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                project,
                [make_case("smoke", "smoke", argv=(sys.executable, "-c", script))],
            )

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            retried = json_output(run_cli(adapter, "resume", expected=1))

            self.assertEqual(retried["status"], "BLOCKED")
            self.assertEqual((project / "persistent-block-count.txt").read_text(encoding="utf-8"), "2")
            state = load_state(adapter)
            initial_attempts = _attempts(state, "initial")
            self.assertEqual(len(initial_attempts), 2)
            self.assertEqual([item["status"] for item in initial_attempts], ["BLOCKED", "BLOCKED"])

    def test_failed_retest_clears_pending_fix_and_requires_a_new_fix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            script = (
                _counter_prelude("failed-retest-count.txt")
                + "if count <= 2:\n"
                + "    raise SystemExit(8)\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                project,
                [make_case("functional", "functional", argv=(sys.executable, "-c", script))],
            )

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            first_fix = write_fix_for_latest_failure(adapter, name="fix-1.json")
            run_cli(adapter, "record-fix", "--fix", str(first_fix), expected=0)

            failed_retest = json_output(run_cli(adapter, "retest", expected=1))
            self.assertEqual(failed_retest["status"], "FAILED")
            self.assertIsNone(failed_retest["pendingFix"])
            rejected = run_cli(adapter, "retest", expected=2)
            self.assertIn("recorded fix", rejected.stderr.lower())

            second_fix = write_fix_for_latest_failure(adapter, name="fix-2.json")
            recorded = json_output(
                run_cli(adapter, "record-fix", "--fix", str(second_fix), expected=0)
            )
            self.assertIsNotNone(recorded["pendingFix"])
            passed = json_output(run_cli(adapter, "retest", expected=0))
            self.assertEqual(passed["status"], "READY_FOR_REGRESSION")
            self.assertIsNone(passed["pendingFix"])
            self.assertEqual(len(passed["fixes"]), 2)

    def test_blocked_retest_resumes_with_the_same_fix_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            script = (
                _counter_prelude("blocked-retest-count.txt")
                + "if count == 1:\n"
                + "    raise SystemExit(8)\n"
                + "if count == 2:\n"
                + "    print('pass' + 'word=' + 'fixture-value')\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                project,
                [make_case("functional", "functional", argv=(sys.executable, "-c", script))],
            )

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            fix = write_fix_for_latest_failure(adapter)
            recorded = json_output(
                run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)
            )
            fix_id = recorded["pendingFix"]["fixId"]

            blocked = json_output(run_cli(adapter, "retest", expected=1))
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertEqual(blocked["pendingFix"]["fixId"], fix_id)
            blocked_attempt_id = blocked["attempts"][-1]["id"]

            resumed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual(resumed["status"], "READY_FOR_REGRESSION")
            self.assertIsNone(resumed["pendingFix"])
            state = load_state(adapter)
            retests = _attempts(state, "retest")
            self.assertEqual([item["status"] for item in retests], ["BLOCKED", "RETEST_PASSED"])
            self.assertEqual(retests[-1].get("resumedFrom"), blocked_attempt_id)

    def test_source_drift_during_retest_is_durable_and_requires_new_root(self) -> None:
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
                source_files=("runner.py", "source.txt"),
            )

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            runner.write_text(
                "import os\n"
                "from pathlib import Path\n"
                "Path('source.txt').write_text('drifted during retest\\n', encoding='utf-8')\n"
                "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
                "(evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n",
                encoding="utf-8",
            )
            fix = write_fix_for_latest_failure(
                adapter,
                changed_files=("runner.py",),
                external_condition=False,
            )
            recorded = json_output(
                run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)
            )
            fix_id = recorded["pendingFix"]["fixId"]

            blocked = json_output(run_cli(adapter, "retest", expected=1))
            self.assertEqual("BLOCKED", blocked["status"])
            self.assertEqual("BLOCKED", blocked["executionStatus"])
            self.assertEqual("BLOCKED", blocked["completionStatus"])
            self.assertEqual("retest", blocked["resumeMode"])
            self.assertEqual(fix_id, blocked["pendingFix"]["fixId"])
            self.assertEqual("retest", blocked["attempts"][-1]["mode"])
            self.assertEqual("BLOCKED", blocked["attempts"][-1]["status"])

            status = json_output(run_cli(adapter, "status", expected=0))
            self.assertEqual("BLOCKED", status["executionStatus"])
            self.assertEqual("BLOCKED", status["completionStatus"])
            self.assertEqual(fix_id, status["pendingFix"]["fixId"])
            rejected = run_cli(adapter, "resume", expected=2)
            self.assertIn("new campaign root", rejected.stderr)
            after = load_state(adapter)
            self.assertEqual("BLOCKED", after["status"])
            self.assertEqual("retest", after["resumeMode"])
            self.assertEqual(fix_id, after["pendingFix"]["fixId"])


class AllocationCrashRecoveryTests(unittest.TestCase):
    def _complete_and_audit(self, adapter: Path) -> None:
        run_cli(adapter, "run", "--mode", "regression", expected=0)
        audit = json_output(run_cli(adapter, "audit", expected=0))
        self.assertTrue(audit["ok"], audit)

    def test_attempt_directory_created_before_event_is_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            run_cli(adapter, "init", expected=0)
            validated = validate_adapter(adapter)
            with CampaignLock(validated.campaign_root):
                campaign = Campaign.load(validated)
                with mock.patch.object(
                    campaign,
                    "commit",
                    side_effect=RuntimeError("injected before attempt event"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "injected"):
                        campaign.start_attempt(
                            "initial", campaign.current_source()
                        )

            attempts_root = campaign_path(adapter) / "attempts"
            orphaned = list(attempts_root.iterdir())
            self.assertEqual(len(orphaned), 1)
            self.assertEqual(["cases"], [item.name for item in orphaned[0].iterdir()])

            run_cli(adapter, "run", expected=0)
            self.assertFalse(orphaned[0].exists())
            self._complete_and_audit(adapter)

    def test_case_directory_created_before_event_is_reconciled_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            case = make_case("smoke", "smoke")
            adapter = make_adapter(project, [case])
            run_cli(adapter, "init", expected=0)
            validated = validate_adapter(adapter)
            with CampaignLock(validated.campaign_root):
                campaign = Campaign.load(validated)
                source = campaign.current_source()
                attempt_id = campaign.start_attempt("initial", source)
                with mock.patch.object(
                    campaign,
                    "commit",
                    side_effect=RuntimeError("injected before case event"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "injected"):
                        execute_case(
                            campaign,
                            attempt_id,
                            case,
                            1,
                            source,
                            "initial",
                        )

            cases_root = next((campaign_path(adapter) / "attempts").iterdir()) / "cases"
            orphaned = list(cases_root.iterdir())
            self.assertEqual(len(orphaned), 1)
            self.assertEqual([], list(orphaned[0].iterdir()))

            resumed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual(resumed["status"], "READY_FOR_REGRESSION")
            self.assertFalse(orphaned[0].exists())
            state = load_state(adapter)
            self.assertEqual(state["attempts"][0]["status"], "INTERRUPTED")
            self._complete_and_audit(adapter)

    def test_allocation_directory_fsyncs_precede_journal_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            run_cli(adapter, "init", expected=0)
            validated = validate_adapter(adapter)
            with CampaignLock(validated.campaign_root):
                campaign = Campaign.load(validated)
                source = campaign.current_source()
                calls = mock.Mock()
                original_fsync = journal_runtime._fsync_directory
                with mock.patch.object(
                    journal_runtime,
                    "_fsync_directory",
                    wraps=original_fsync,
                ) as fsync_call, mock.patch.object(
                    campaign,
                    "commit",
                    wraps=campaign.commit,
                ) as commit_call:
                    calls.attach_mock(fsync_call, "fsync")
                    calls.attach_mock(commit_call, "commit")
                    attempt_id = campaign.start_attempt("initial", source)
                    names = [item[0] for item in calls.mock_calls]
                    self.assertEqual("commit", names[-1])
                    self.assertEqual(3, names.count("fsync"))

                    calls.reset_mock()
                    run_id, artifact_dir = campaign.allocate_case_artifact(
                        attempt_id, "smoke", 1
                    )
                    relative = artifact_dir.relative_to(
                        validated.campaign_root
                    ).as_posix()
                    campaign.commit(
                        "case_started",
                        {
                            "attemptId": attempt_id,
                            "runId": run_id,
                            "caseId": "smoke",
                            "ordinal": 1,
                            "artifactDir": relative,
                            "sourceFingerprint": source,
                        },
                    )
                    names = [item[0] for item in calls.mock_calls]
                    self.assertEqual(["fsync", "fsync", "commit"], names)

    def test_allocation_fsync_failure_prevents_journal_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            run_cli(adapter, "init", expected=0)
            validated = validate_adapter(adapter)
            journal = validated.campaign_root / "events.jsonl"
            original = journal.read_bytes()
            with CampaignLock(validated.campaign_root):
                campaign = Campaign.load(validated)
                with mock.patch.object(
                    journal_runtime.os,
                    "fsync",
                    side_effect=OSError("injected allocation fsync failure"),
                ), mock.patch.object(campaign, "commit") as commit_call:
                    with self.assertRaisesRegex(
                        journal_runtime.CampaignError, "durably persist"
                    ):
                        campaign.start_attempt(
                            "initial", campaign.current_source()
                        )
                    commit_call.assert_not_called()
            self.assertEqual(original, journal.read_bytes())

    def test_windows_unsupported_directory_flush_keeps_allocations_usable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            run_cli(adapter, "init", expected=0)
            validated = validate_adapter(adapter)
            with CampaignLock(validated.campaign_root):
                campaign = Campaign.load(validated)
                source = campaign.current_source()
                with mock.patch.object(
                    journal_runtime, "IS_WINDOWS", True
                ), mock.patch.object(
                    journal_runtime,
                    "_try_flush_windows_directory",
                    side_effect=OSError(
                        errno.EINVAL, "directory flushing is unsupported"
                    ),
                ) as flush_call:
                    attempt_id = campaign.start_attempt("initial", source)
                    run_id, artifact_dir = campaign.allocate_case_artifact(
                        attempt_id, "smoke", 1
                    )
                    relative = artifact_dir.relative_to(
                        validated.campaign_root
                    ).as_posix()
                    campaign.commit(
                        "case_started",
                        {
                            "attemptId": attempt_id,
                            "runId": run_id,
                            "caseId": "smoke",
                            "ordinal": 1,
                            "artifactDir": relative,
                            "sourceFingerprint": source,
                        },
                    )
                self.assertTrue(artifact_dir.is_dir())
                self.assertEqual(5, flush_call.call_count)


class ProjectionAndRestartTests(unittest.TestCase):
    def test_missing_and_stale_projections_are_rebuilt_by_mutating_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            run_cli(adapter, "init", expected=0)
            root = campaign_path(adapter)
            initialized_state = read_json(root / "state.json")
            initialized_summary = read_json(root / "summary.json")

            (root / "state.json").unlink()
            (root / "summary.json").unlink()
            initial = json_output(run_cli(adapter, "run", expected=0))
            self.assertEqual(initial["status"], "READY_FOR_REGRESSION")
            self.assertTrue((root / "state.json").is_file())
            self.assertTrue((root / "summary.json").is_file())

            # Restore valid but stale projections. The next mutating command must
            # replay the journal rather than trusting these cache files.
            (root / "state.json").write_text(
                json.dumps(initialized_state, sort_keys=True) + "\n", encoding="utf-8"
            )
            (root / "summary.json").write_text(
                json.dumps(initialized_summary, sort_keys=True) + "\n", encoding="utf-8"
            )
            completed = json_output(
                run_cli(adapter, "run", "--mode", "regression", expected=0)
            )
            self.assertEqual(completed["status"], "COMPLETE")
            status = json_output(run_cli(adapter, "status", expected=0))
            self.assertTrue(status["snapshotConsistent"])
            self.assertTrue(status["summaryConsistent"])

    def test_first_regression_source_drift_invalidates_and_fail_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            script = (
                _counter_prelude("drift-count.txt")
                + "if count > 1:\n"
                + "    source = Path('source.txt')\n"
                + "    source.write_text(source.read_text(encoding='utf-8') + str(count) + '\\n', encoding='utf-8')\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                project,
                [make_case("workflow", "workflow", argv=(sys.executable, "-c", script))],
            )

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=0)
            blocked = json_output(
                run_cli(adapter, "run", "--mode", "regression", expected=1)
            )

            self.assertEqual(blocked["status"], "BLOCKED")
            state = load_state(adapter)
            regressions = _attempts(state, "regression")
            self.assertEqual(len(regressions), 1)
            self.assertEqual([item["status"] for item in regressions], ["INVALIDATED"])
            invalidations = [event for event in _events(adapter) if event.get("type") == "attempt_invalidated"]
            self.assertEqual(len(invalidations), 1)
            self.assertEqual(
                invalidations[-1]["payload"]["campaignStatus"],
                "BLOCKED",
            )
            resumed = run_cli(adapter, "resume", expected=2)
            self.assertIn("choose a new campaign root", resumed.stderr)

    def test_source_drift_after_last_case_still_invalidates_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(
                project,
                [make_case("smoke", "smoke")],
            )
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=0)
            validated = validate_adapter(adapter)

            with CampaignLock(validated.campaign_root):
                campaign = Campaign.load(validated)
                current_source = campaign.current_source
                calls = 0

                def drift_on_final_check() -> str:
                    nonlocal calls
                    calls += 1
                    if calls == 4:
                        source = project / "source.txt"
                        source.write_text(
                            source.read_text(encoding="utf-8") + "late drift\n",
                            encoding="utf-8",
                        )
                    return current_source()

                with mock.patch.object(
                    campaign,
                    "current_source",
                    side_effect=drift_on_final_check,
                ):
                    blocked = run_regression_locked(campaign)

            self.assertEqual("BLOCKED", blocked["status"])
            self.assertEqual("INVALIDATED", blocked["attempts"][-1]["status"])
            self.assertIn(
                "before regression completion",
                blocked["attempts"][-1]["invalidationReason"],
            )


if __name__ == "__main__":
    unittest.main()
