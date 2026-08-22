"""Black-box semantic replay and descendant-cleanup tests."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from typing import Any, Callable

try:
    from .helpers import (
        campaign_path,
        json_output,
        load_state,
        make_adapter,
        make_case,
        read_json,
        run_cli,
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
    )


_CATEGORIES = ("smoke", "functional", "integration", "workflow", "role-play")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _event_hash(event_without_hash: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(event_without_hash)).hexdigest()


def _read_events(adapter: Path) -> list[dict[str, Any]]:
    journal = campaign_path(adapter) / "events.jsonl"
    return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]


def _write_rehashed_events(adapter: Path, events: list[dict[str, Any]]) -> None:
    previous_hash = "0" * 64
    encoded: list[bytes] = []
    for sequence, original in enumerate(events, start=1):
        event = copy.deepcopy(original)
        event["seq"] = sequence
        event["prevHash"] = previous_hash
        event.pop("hash", None)
        event["hash"] = _event_hash(event)
        previous_hash = event["hash"]
        encoded.append(_canonical_bytes(event))
    (campaign_path(adapter) / "events.jsonl").write_bytes(
        b"\n".join(encoded) + b"\n"
    )


def _event(
    events: list[dict[str, Any]],
    event_type: str,
    *,
    attempt_id: str | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    for item in events:
        payload = item.get("payload", {})
        if item.get("type") != event_type:
            continue
        if attempt_id is not None and payload.get("attemptId") != attempt_id:
            continue
        if case_id is not None and payload.get("caseId") != case_id:
            continue
        return item
    raise AssertionError(
        f"event not found: type={event_type!r}, "
        f"attempt={attempt_id!r}, case={case_id!r}"
    )


def _process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class FinalRegressionSemanticTests(unittest.TestCase):
    def _complete_campaign(self, root: Path) -> tuple[Path, str, str]:
        cases: list[dict[str, Any]] = []
        dependency: tuple[str, ...] = ()
        for index, category in enumerate(_CATEGORIES, start=1):
            case_id = f"{index:02d}-{category}"
            cases.append(
                make_case(
                    case_id,
                    category,
                    required=category != "role-play",
                    depends_on=dependency,
                )
            )
            dependency = (case_id,)
        adapter = make_adapter(root, cases)
        json_output(run_cli(adapter, "init", expected=0))
        initial = json_output(run_cli(adapter, "run", expected=0))
        self.assertEqual("READY_FOR_REGRESSION", initial["status"])
        complete = json_output(
            run_cli(adapter, "run", "--mode", "regression", expected=0)
        )
        self.assertEqual("COMPLETE", complete["status"])
        self.assertTrue(json_output(run_cli(adapter, "audit", expected=0))["ok"])
        final_attempt_id = complete.get("finalRegressionAttemptId")
        self.assertIsInstance(final_attempt_id, str)
        return adapter, final_attempt_id, "05-role-play"

    def _assert_status_rejects_or_audit_fails(self, adapter: Path) -> None:
        journal = campaign_path(adapter) / "events.jsonl"
        malicious_journal = journal.read_bytes()
        status = run_cli(adapter, "status", expected=(0, 2))
        diagnostic = status.stdout + status.stderr
        self.assertNotIn("Traceback", diagnostic)
        if status.returncode == 0:
            audited = run_cli(adapter, "audit", expected=(1, 2))
            diagnostic += audited.stdout + audited.stderr
            self.assertNotIn("Traceback", diagnostic)
            if audited.returncode == 1:
                report = json_output(audited)
                self.assertFalse(report["ok"], report)
        else:
            self.assertIn("ERROR:", diagnostic)
        self.assertEqual(malicious_journal, journal.read_bytes())

    def test_runnable_optional_case_cannot_be_forged_as_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter, attempt_id, case_id = self._complete_campaign(Path(temporary))
            events = _read_events(adapter)
            started = _event(
                events,
                "case_started",
                attempt_id=attempt_id,
                case_id=case_id,
            )
            finished = _event(
                events,
                "case_finished",
                attempt_id=attempt_id,
                case_id=case_id,
            )
            start_index = events.index(started)
            finish_index = events.index(finished)
            forged_skip = {
                "schemaVersion": started["schemaVersion"],
                "seq": started["seq"],
                "timestamp": started["timestamp"],
                "type": "case_skipped",
                "payload": {
                    "attemptId": attempt_id,
                    "caseId": case_id,
                    "ordinal": started["payload"]["ordinal"],
                    "reason": "forged unsupported platform",
                },
                "prevHash": started["prevHash"],
                "hash": started["hash"],
            }
            events[start_index : finish_index + 1] = [forged_skip]
            _write_rehashed_events(adapter, events)

            self._assert_status_rejects_or_audit_fails(adapter)

    def test_runnable_optional_case_cannot_be_deleted_from_final_regression(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter, attempt_id, case_id = self._complete_campaign(Path(temporary))
            events = [
                item
                for item in _read_events(adapter)
                if not (
                    item["type"] in {"case_started", "case_finished"}
                    and item["payload"].get("attemptId") == attempt_id
                    and item["payload"].get("caseId") == case_id
                )
            ]
            _write_rehashed_events(adapter, events)

            self._assert_status_rejects_or_audit_fails(adapter)


class StrictJournalSemanticTests(unittest.TestCase):
    def _complete_campaign(self, root: Path) -> Path:
        cases = [
            make_case("smoke", "smoke"),
            make_case(
                "optional-functional",
                "functional",
                required=False,
                depends_on=("smoke",),
            ),
        ]
        adapter = make_adapter(root, cases)
        json_output(run_cli(adapter, "init", expected=0))
        json_output(run_cli(adapter, "run", expected=0))
        completed = json_output(
            run_cli(adapter, "run", "--mode", "regression", expected=0)
        )
        self.assertEqual("COMPLETE", completed["status"])
        return adapter

    def _assert_rejected_without_journal_write(self, adapter: Path) -> None:
        journal = campaign_path(adapter) / "events.jsonl"
        malicious_journal = journal.read_bytes()
        completed = run_cli(adapter, "status", expected=2)
        diagnostic = completed.stdout + completed.stderr
        self.assertNotIn("Traceback", diagnostic)
        self.assertIn("ERROR:", diagnostic)
        self.assertEqual(malicious_journal, journal.read_bytes())

    def test_hash_valid_semantic_corruption_is_rejected(self) -> None:
        def unknown_top_level(events: list[dict[str, Any]]) -> None:
            events[0]["unexpected"] = "attacker-controlled"

        def unknown_payload(events: list[dict[str, Any]]) -> None:
            _event(events, "case_finished")["payload"]["unexpected"] = False

        def wrong_payload_type(events: list[dict[str, Any]]) -> None:
            _event(events, "case_finished")["payload"]["timedOut"] = "false"

        def mismatched_case_identity(events: list[dict[str, Any]]) -> None:
            _event(events, "case_finished", case_id="smoke")["payload"][
                "caseId"
            ] = "optional-functional"

        def duplicate_attempt_finished(events: list[dict[str, Any]]) -> None:
            events.append(copy.deepcopy(_event(events, "attempt_finished")))

        def illegal_attempt_status(events: list[dict[str, Any]]) -> None:
            events[-1]["payload"]["status"] = "RUNNING"

        mutations: tuple[
            tuple[str, Callable[[list[dict[str, Any]]], None]], ...
        ] = (
            ("unknown top-level field", unknown_top_level),
            ("unknown payload field", unknown_payload),
            ("wrong payload type", wrong_payload_type),
            ("case_finished identity mismatch", mismatched_case_identity),
            ("duplicate attempt_finished", duplicate_attempt_finished),
            ("illegal attempt_finished status", illegal_attempt_status),
        )

        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._complete_campaign(Path(temporary))
            journal = campaign_path(adapter) / "events.jsonl"
            pristine_journal = journal.read_bytes()
            pristine_events = _read_events(adapter)
            for name, mutate in mutations:
                with self.subTest(name=name):
                    events = copy.deepcopy(pristine_events)
                    mutate(events)
                    _write_rehashed_events(adapter, events)
                    self._assert_rejected_without_journal_write(adapter)
                    journal.write_bytes(pristine_journal)


@unittest.skipUnless(
    os.name == "posix" and hasattr(os, "killpg"),
    "process-group cleanup test requires POSIX",
)
class TimeoutProcessGroupTests(unittest.TestCase):
    def test_timeout_terminates_descendants_before_they_can_write(self) -> None:
        child_script = (
            "import os, time\n"
            "from pathlib import Path\n"
            "time.sleep(5.0)\n"
            "Path('source.txt').write_text('late descendant write\\n', "
            "encoding='utf-8')\n"
            "artifact = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            "(artifact / 'late-evidence.txt').write_text('late', encoding='utf-8')\n"
            "time.sleep(30)\n"
        )
        parent_script = (
            "import subprocess, sys, time\n"
            f"child_script = {child_script!r}\n"
            "child = subprocess.Popen([sys.executable, '-c', child_script])\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(30)\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(
                project,
                [
                    make_case(
                        "timeout-tree",
                        "smoke",
                        argv=(sys.executable, "-c", parent_script),
                        # Allow process startup under full-suite load while the
                        # descendant's delayed write remains after the timeout.
                        timeout_seconds=2.0,
                        required_files=(),
                        non_empty_files=(),
                    )
                ],
            )
            json_output(run_cli(adapter, "init", expected=0))
            failed = json_output(run_cli(adapter, "run", expected=1, timeout=15))
            self.assertIn(failed["status"], {"FAILED", "BLOCKED"})

            state = load_state(adapter)
            case_run = state["attempts"][-1]["caseRuns"][-1]
            self.assertEqual(failed["status"], case_run["status"])
            self.assertTrue(case_run["timedOut"])
            artifact = campaign_path(adapter) / case_run["artifactDir"]
            result = read_json(artifact / "result.json")
            self.assertEqual(failed["status"], result["status"])
            self.assertTrue(result["timedOut"])
            expected_reason = (
                "command timed out"
                if failed["status"] == "FAILED"
                else "command process-tree cleanup could not be verified"
            )
            self.assertEqual(expected_reason, result["reason"])

            output_lines = (artifact / "stdout.txt").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertTrue(output_lines, "parent did not report the descendant PID")
            descendant_pid = int(output_lines[0])
            alive = False
            try:
                time.sleep(1.3)
                alive = _process_exists(descendant_pid)
                source_after_delay = (project / "source.txt").read_text(
                    encoding="utf-8"
                )
                late_evidence = (artifact / "late-evidence.txt").exists()
            finally:
                if _process_exists(descendant_pid):
                    try:
                        os.kill(descendant_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            self.assertFalse(alive, "timed-out descendant is still alive")
            self.assertEqual("stable source\n", source_after_delay)
            self.assertFalse(late_evidence, "descendant wrote evidence after timeout")


if __name__ == "__main__":
    unittest.main()
