"""Black-box contracts for strict replay and bounded campaign recovery."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

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
        write_json,
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
        write_json,
    )


SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import engine as campaign_engine  # noqa: E402
from adapter_paths import validate_adapter  # noqa: E402
from journal_state import Campaign, CampaignLock  # noqa: E402
from model import canonical_bytes, sha256_bytes  # noqa: E402


def _proof_statement() -> str:
    return (
        "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
        "(evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n"
    )


def _counter_prelude(name: str = "count.txt") -> str:
    return (
        "import os\n"
        "from pathlib import Path\n"
        f"counter = Path({name!r})\n"
        "count = int(counter.read_text(encoding='utf-8')) + 1 if counter.exists() else 1\n"
        "counter.write_text(str(count), encoding='utf-8')\n"
    )


def _append_event(
    adapter: Path,
    event_type: str,
    payload: dict[str, Any],
    *,
    timestamp: Any = "2026-08-14T00:00:00.000Z",
) -> bytes:
    journal = campaign_path(adapter) / "events.jsonl"
    events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    event = {
        "schemaVersion": events[-1]["schemaVersion"],
        "seq": len(events) + 1,
        "timestamp": timestamp,
        "type": event_type,
        "payload": payload,
        "prevHash": events[-1]["hash"],
    }
    event["hash"] = sha256_bytes(canonical_bytes(event))
    original = journal.read_bytes()
    with journal.open("ab") as handle:
        handle.write(canonical_bytes(event) + b"\n")
    return original


class RecoveryContractTests(unittest.TestCase):
    def test_crash_after_successful_retest_resumes_initial_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repaired = (
                _counter_prelude("repaired-count.txt")
                + "if count == 1:\n    raise SystemExit(7)\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "functional",
                        "functional",
                        argv=(sys.executable, "-c", repaired),
                    ),
                    make_case(
                        "workflow",
                        "workflow",
                        depends_on=("functional",),
                    ),
                ],
            )
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            fix = write_fix_for_latest_failure(adapter)
            run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)

            validated = validate_adapter(adapter)
            original = campaign_engine.run_initial_locked

            def crash_before_continuation(*args: Any, **kwargs: Any) -> dict[str, Any]:
                raise KeyboardInterrupt

            campaign_engine.run_initial_locked = crash_before_continuation
            try:
                with CampaignLock(validated.campaign_root):
                    with self.assertRaises(KeyboardInterrupt):
                        campaign_engine.retest_locked(Campaign.load(validated))
            finally:
                campaign_engine.run_initial_locked = original

            interrupted = load_state(adapter)
            self.assertEqual("RUNNING", interrupted["status"])
            self.assertEqual("initial", interrupted["resumeMode"])
            self.assertIsNone(interrupted["pendingFix"])
            self.assertEqual("RETEST_PASSED", interrupted["cases"]["functional"]["status"])

            resumed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual("READY_FOR_REGRESSION", resumed["status"])
            self.assertEqual("PASS", resumed["cases"]["workflow"]["status"])

    def test_still_blocked_case_stops_after_one_resume_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unsupported = "windows" if not sys.platform.startswith("win") else "linux"
            adapter = make_adapter(
                root,
                [make_case("platform-case", "smoke", platform=unsupported)],
            )
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            twice_blocked = json_output(run_cli(adapter, "resume", expected=1))
            self.assertEqual("BLOCKED", twice_blocked["status"])
            self.assertEqual(2, len(twice_blocked["attempts"]))

            campaign = campaign_path(adapter)
            journal = campaign / "events.jsonl"
            before = journal.read_bytes()
            (campaign / "state.json").unlink()
            (campaign / "summary.json").unlink()
            stopped = json_output(run_cli(adapter, "resume", expected=1))
            self.assertEqual("BLOCKED", stopped["status"])
            self.assertEqual(2, len(stopped["attempts"]))
            self.assertEqual(before, journal.read_bytes())
            self.assertTrue((campaign / "state.json").is_file())
            self.assertTrue((campaign / "summary.json").is_file())

    def test_regression_blocked_case_gets_one_recoverable_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = (
                _counter_prelude("regression-block-count.txt")
                + "if count == 2:\n"
                + "    print('pass' + 'word=' + 'temporary-fixture')\n"
                + "else:\n"
                + "    "
                + _proof_statement().replace("\n", "\n    ").rstrip()
                + "\n"
            )
            adapter = make_adapter(
                root,
                [make_case("workflow", "workflow", argv=(sys.executable, "-c", script))],
            )
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=0)
            blocked = json_output(
                run_cli(adapter, "run", "--mode", "regression", expected=1)
            )
            self.assertEqual("BLOCKED", blocked["status"])

            completed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual("COMPLETE", completed["status"])
            regressions = [
                attempt for attempt in completed["attempts"] if attempt["mode"] == "regression"
            ]
            self.assertEqual(["BLOCKED", "PASS"], [attempt["status"] for attempt in regressions])

    def test_regression_invalidation_has_no_restart_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = (
                _counter_prelude("drift-once-count.txt")
                + "if count == 2:\n"
                + "    source = Path('source.txt')\n"
                + "    source.write_text(source.read_text(encoding='utf-8') + 'drift\\n', encoding='utf-8')\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                root,
                [make_case("workflow", "workflow", argv=(sys.executable, "-c", script))],
            )
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=0)

            blocked = json_output(
                run_cli(adapter, "run", "--mode", "regression", expected=1)
            )
            self.assertEqual("BLOCKED", blocked["status"])

            checkpoint = json_output(run_cli(adapter, "status", expected=0))
            self.assertEqual("BLOCKED", checkpoint["status"])
            self.assertIsNone(checkpoint["currentAttemptId"])
            self.assertEqual("INVALIDATED", checkpoint["attempts"][-1]["status"])

            resume = run_cli(adapter, "resume", expected=2)
            self.assertIn("choose a new campaign root", resume.stderr)

    def test_initial_source_drift_requires_a_new_campaign_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = (
                "import os\n"
                "from pathlib import Path\n"
                "source = Path('source.txt')\n"
                "source.write_text(source.read_text(encoding='utf-8') + 'changed\\n', encoding='utf-8')\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                root,
                [make_case("source-drift", "smoke", argv=(sys.executable, "-c", script))],
            )
            run_cli(adapter, "init", expected=0)
            blocked = json_output(run_cli(adapter, "run", expected=1))
            self.assertEqual("BLOCKED", blocked["status"])
            self.assertEqual("BLOCKED", blocked["cases"]["source-drift"]["status"])

            journal = campaign_path(adapter) / "events.jsonl"
            before = journal.read_bytes()
            rejected = run_cli(adapter, "resume", expected=2)
            self.assertIn("new campaign root", rejected.stderr.lower())
            self.assertEqual(before, journal.read_bytes())

    def test_catalog_drift_during_last_initial_case_cannot_report_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = (
                "import json, os\n"
                "from pathlib import Path\n"
                "adapter = Path('adapter.json')\n"
                "value = json.loads(adapter.read_text(encoding='utf-8'))\n"
                "value['projectId'] = 'changed-during-case'\n"
                "adapter.write_text(json.dumps(value), encoding='utf-8')\n"
                + _proof_statement()
            )
            adapter = make_adapter(
                root,
                [make_case("catalog-drift", "smoke", argv=(sys.executable, "-c", script))],
            )
            run_cli(adapter, "init", expected=0)
            blocked = json_output(run_cli(adapter, "run", expected=1))
            self.assertEqual("BLOCKED", blocked["status"])
            observed = json_output(run_cli(adapter, "status", expected=0))
            self.assertTrue(observed["catalogDrift"])

    def test_failed_retest_preserves_regression_fix_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = (
                _counter_prelude("regression-fix-count.txt")
                + _proof_statement()
                + "if count in (2, 3):\n    raise SystemExit(7)\n"
            )
            adapter = make_adapter(
                root,
                [make_case("smoke", "smoke", argv=(sys.executable, "-c", script))],
            )
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=1)
            first_fix = write_fix_for_latest_failure(adapter, name="first-fix.json")
            self.assertEqual("regression", read_json(first_fix)["failedRound"])
            run_cli(adapter, "record-fix", "--fix", str(first_fix), expected=0)
            failed_retest = json_output(run_cli(adapter, "retest", expected=1))
            self.assertIsNone(failed_retest["pendingFix"])

            second_fix = write_fix_for_latest_failure(adapter, name="second-fix.json")
            value = read_json(second_fix)
            value["failedRound"] = "regression"
            write_json(second_fix, value)
            recorded = json_output(
                run_cli(adapter, "record-fix", "--fix", str(second_fix), expected=0)
            )
            self.assertEqual("regression", recorded["pendingFix"]["failedRound"])


class StrictReplayContractTests(unittest.TestCase):
    def test_hash_valid_illegal_state_transitions_are_rejected(self) -> None:
        def begin_attempt(adapter: Path, initialized: dict[str, Any]) -> tuple[str, str]:
            attempt_id = "attempt-0001-initial-deadbeef"
            _append_event(
                adapter,
                "attempt_started",
                {
                    "attemptId": attempt_id,
                    "mode": "initial",
                    "sourceFingerprint": initialized["currentSourceFingerprint"],
                    "catalogFingerprint": initialized["catalogFingerprint"],
                    "artifactDir": "attempts/" + attempt_id,
                    "resumedFrom": None,
                    "targetCaseId": None,
                },
            )
            return attempt_id, initialized["currentSourceFingerprint"]

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(root, [make_case("smoke", "smoke")])
            initialized = json_output(run_cli(adapter, "init", expected=0))
            attempt_id, source = begin_attempt(adapter, initialized)
            _append_event(
                adapter,
                "attempt_finished",
                {
                    "attemptId": attempt_id,
                    "status": "PASS",
                    "campaignStatus": "READY_FOR_REGRESSION",
                    "currentSourceFingerprint": source,
                    "reason": None,
                    "clearPendingFix": False,
                    "resumeMode": "regression",
                },
            )
            forged = (campaign_path(adapter) / "events.jsonl").read_bytes()
            rejected = run_cli(adapter, "status", expected=2)
            self.assertNotIn("Traceback", rejected.stdout + rejected.stderr)
            self.assertEqual(forged, (campaign_path(adapter) / "events.jsonl").read_bytes())

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(root, [make_case("smoke", "smoke")])
            initialized = json_output(run_cli(adapter, "init", expected=0))
            attempt_id, source = begin_attempt(adapter, initialized)
            run_id = attempt_id + "-001-smoke-deadbeef"
            _append_event(
                adapter,
                "case_started",
                {
                    "attemptId": attempt_id,
                    "runId": run_id,
                    "caseId": "smoke",
                    "ordinal": 1,
                    "artifactDir": "attempts/" + attempt_id + "/cases/" + run_id,
                    "sourceFingerprint": source,
                },
            )
            _append_event(
                adapter,
                "attempt_interrupted",
                {
                    "attemptId": attempt_id,
                    "interruptedRunIds": [],
                    "reason": "forged omission of the active run",
                },
            )
            forged = (campaign_path(adapter) / "events.jsonl").read_bytes()
            rejected = run_cli(adapter, "status", expected=2)
            self.assertNotIn("Traceback", rejected.stdout + rejected.stderr)
            self.assertEqual(forged, (campaign_path(adapter) / "events.jsonl").read_bytes())

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(root, [make_case("smoke", "smoke")])
            initialized = json_output(run_cli(adapter, "init", expected=0))
            source = initialized["currentSourceFingerprint"]
            _append_event(
                adapter,
                "fix_recorded",
                {
                    "fixId": "fix-deadbeefdead",
                    "failedCaseId": "smoke",
                    "failedRound": "initial",
                    "failedAttemptId": "attempt-0001-initial-deadbeef",
                    "failedSourceFingerprint": source,
                    "fixedSourceFingerprint": source,
                    "rootCause": "forged fix without a failure",
                    "changedFiles": [],
                    "fixSummary": "forged transition",
                    "externalCondition": True,
                    "minimalRegressionEvidence": ["proof.json"],
                },
            )
            forged = (campaign_path(adapter) / "events.jsonl").read_bytes()
            rejected = run_cli(adapter, "status", expected=2)
            self.assertNotIn("Traceback", rejected.stdout + rejected.stderr)
            self.assertEqual(forged, (campaign_path(adapter) / "events.jsonl").read_bytes())

    def test_case_skip_cannot_be_appended_to_a_closed_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case("required", "smoke"),
                    make_case(
                        "optional",
                        "functional",
                        required=False,
                        depends_on=("required",),
                    ),
                ],
            )
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=0)
            completed = json_output(
                run_cli(adapter, "run", "--mode", "regression", expected=0)
            )
            original = _append_event(
                adapter,
                "case_skipped",
                {
                    "attemptId": completed["finalRegressionAttemptId"],
                    "caseId": "optional",
                    "ordinal": 2,
                    "reason": "late invalid skip",
                },
            )
            journal = campaign_path(adapter) / "events.jsonl"
            forged = journal.read_bytes()
            rejected = run_cli(adapter, "status", expected=2)
            self.assertNotIn("Traceback", rejected.stdout + rejected.stderr)
            self.assertIn("current running attempt", rejected.stderr.lower())
            self.assertNotEqual(original, forged)
            self.assertEqual(forged, journal.read_bytes())

    def test_invalid_attempt_mode_and_timestamp_are_rejected(self) -> None:
        mutations = (("bogus", "2026-08-14T00:00:00.000Z"), ("initial", 0))
        for mode, timestamp in mutations:
            with self.subTest(mode=mode, timestamp=timestamp), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                adapter = make_adapter(root, [make_case("smoke", "smoke")])
                initialized = json_output(run_cli(adapter, "init", expected=0))
                _append_event(
                    adapter,
                    "attempt_started",
                    {
                        "attemptId": "attempt-0001-invalid",
                        "mode": mode,
                        "sourceFingerprint": initialized["currentSourceFingerprint"],
                        "catalogFingerprint": initialized["catalogFingerprint"],
                        "artifactDir": "attempts/attempt-0001-invalid",
                        "resumedFrom": None,
                        "targetCaseId": None,
                    },
                    timestamp=timestamp,
                )
                journal = campaign_path(adapter) / "events.jsonl"
                forged = journal.read_bytes()
                rejected = run_cli(adapter, "status", expected=2)
                self.assertNotIn("Traceback", rejected.stdout + rejected.stderr)
                self.assertEqual(forged, journal.read_bytes())

    def test_audit_catalog_drift_is_json_failure_using_initialized_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(root, [make_case("historical", "smoke")])
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)

            value = read_json(adapter)
            value["projectId"] = "replacement-catalog"
            value["cases"] = [make_case("replacement", "smoke")]
            write_json(adapter, value)
            journal = campaign_path(adapter) / "events.jsonl"
            before = journal.read_bytes()

            audited = run_cli(adapter, "audit", expected=1)
            self.assertNotIn("Traceback", audited.stdout + audited.stderr)
            report = json_output(audited)
            self.assertFalse(report["ok"])
            self.assertTrue(report["catalogDrift"])
            self.assertTrue(any("catalog drift" in item for item in report["errors"]))
            self.assertEqual(before, journal.read_bytes())


@unittest.skipIf(os.name == "nt", "POSIX mode-bit proof is not portable to Windows")
class ExactFixDeltaContractTests(unittest.TestCase):
    def test_record_fix_requires_exact_add_modify_delete_and_mode_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = root / "runner.py"
            added = root / "added.txt"
            deleted = root / "deleted.txt"
            mode_only = root / "mode-only.txt"
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "functional",
                        "functional",
                        argv=(sys.executable, "runner.py"),
                    )
                ],
                source_files=(
                    "runner.py",
                    "added.txt",
                    "deleted.txt",
                    "mode-only.txt",
                ),
            )
            added.unlink()
            runner.write_text("raise SystemExit(7)\n", encoding="utf-8")
            original_mode = mode_only.stat().st_mode & 0o777

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            failed_state = load_state(adapter)
            failed_snapshot = failed_state["attempts"][-1]["sourceSnapshot"]
            failed_entries = {
                item["path"]: item for item in failed_snapshot["files"]
            }
            self.assertEqual("missing", failed_entries["added.txt"]["status"])
            self.assertEqual("present", failed_entries["deleted.txt"]["status"])
            self.assertEqual(original_mode, failed_entries["mode-only.txt"]["mode"])

            runner.write_text(
                "import os\n"
                "from pathlib import Path\n"
                "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
                "(evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n",
                encoding="utf-8",
            )
            added.write_text("added by fix\n", encoding="utf-8")
            deleted.unlink()
            mode_only.chmod(original_mode ^ 0o100)

            incomplete = write_fix_for_latest_failure(
                adapter,
                changed_files=("runner.py",),
                external_condition=False,
                name="incomplete-fix.json",
            )
            rejected = run_cli(
                adapter, "record-fix", "--fix", str(incomplete), expected=2
            )
            self.assertIn("exactly match", rejected.stderr)

            complete = write_fix_for_latest_failure(
                adapter,
                changed_files=(
                    "runner.py",
                    "added.txt",
                    "deleted.txt",
                    "mode-only.txt",
                ),
                external_condition=False,
                name="complete-fix.json",
            )
            recorded = json_output(
                run_cli(adapter, "record-fix", "--fix", str(complete), expected=0)
            )
            self.assertTrue(recorded["pendingFix"]["changedFilesVerified"])
            self.assertEqual(
                sorted(("runner.py", "added.txt", "deleted.txt", "mode-only.txt")),
                recorded["pendingFix"]["changedFiles"],
            )
            state = load_state(adapter)
            fixed_snapshot = state["pendingFix"]["fixedSourceSnapshot"]
            fixed_entries = {item["path"]: item for item in fixed_snapshot["files"]}
            self.assertEqual("present", fixed_entries["added.txt"]["status"])
            self.assertEqual("missing", fixed_entries["deleted.txt"]["status"])
            self.assertNotEqual(original_mode, fixed_entries["mode-only.txt"]["mode"])


class OptionalCoverageContractTests(unittest.TestCase):
    def test_optional_dependency_chain_can_be_not_run_and_audit_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unavailable = "windows" if os.name != "nt" else "darwin"
            adapter = make_adapter(
                root,
                [
                    make_case("required", "smoke"),
                    make_case(
                        "optional-platform",
                        "functional",
                        required=False,
                        platform=unavailable,
                        depends_on=("required",),
                    ),
                    make_case(
                        "optional-dependent",
                        "integration",
                        required=False,
                        depends_on=("optional-platform",),
                    ),
                ],
            )
            run_cli(adapter, "init", expected=0)

            initial = json_output(run_cli(adapter, "run", expected=0))
            self.assertEqual("READY_FOR_REGRESSION", initial["status"])
            self.assertEqual("NOT_RUN", initial["cases"]["optional-platform"]["status"])
            self.assertEqual("NOT_RUN", initial["cases"]["optional-dependent"]["status"])

            regression = json_output(
                run_cli(adapter, "run", "--mode", "regression", expected=0)
            )
            self.assertEqual("COMPLETE", regression["status"])
            self.assertEqual(
                "NOT_RUN", regression["cases"]["optional-platform"]["status"]
            )
            self.assertEqual(
                "NOT_RUN", regression["cases"]["optional-dependent"]["status"]
            )

            report = json_output(run_cli(adapter, "audit", expected=0))
            self.assertTrue(report["ok"], report)

    def test_required_case_blocked_by_unavailable_optional_cannot_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unavailable = "windows" if os.name != "nt" else "darwin"
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "optional-platform",
                        "smoke",
                        required=False,
                        platform=unavailable,
                    ),
                    make_case(
                        "required-dependent",
                        "functional",
                        depends_on=("optional-platform",),
                    ),
                ],
            )
            run_cli(adapter, "init", expected=0)

            blocked = json_output(run_cli(adapter, "run", expected=1))
            self.assertEqual("BLOCKED", blocked["status"])
            self.assertEqual(
                "NOT_RUN", blocked["cases"]["optional-platform"]["status"]
            )
            self.assertEqual(
                "BLOCKED", blocked["cases"]["required-dependent"]["status"]
            )

            report = json_output(run_cli(adapter, "audit", expected=1))
            self.assertFalse(report["ok"])
            self.assertFalse(report["allRequiredPassed"])
            self.assertFalse(report["noUnresolvedState"])


if __name__ == "__main__":
    unittest.main()
