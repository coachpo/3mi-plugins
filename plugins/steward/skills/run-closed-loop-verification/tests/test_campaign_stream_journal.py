"""Black-box coverage for bounded output and strict journal replay."""

from __future__ import annotations

import hashlib
import json
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
        write_json,
    )


_OUTPUT_LIMIT = 5 * 1024 * 1024
_TRUNCATION_MARKER = b"\n<OUTPUT_TRUNCATED>\n"


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
    lines: list[bytes] = []
    for sequence, original in enumerate(events, start=1):
        event = dict(original)
        event["seq"] = sequence
        event["prevHash"] = previous_hash
        event.pop("hash", None)
        event["hash"] = _event_hash(event)
        previous_hash = event["hash"]
        lines.append(_canonical_bytes(event))
    (campaign_path(adapter) / "events.jsonl").write_bytes(b"\n".join(lines) + b"\n")


def _append_rehashed_event(
    adapter: Path,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    events = _read_events(adapter)
    events.append(
        {
            "schemaVersion": 2,
            "seq": len(events) + 1,
            "timestamp": "2026-08-14T00:00:00.000Z",
            "type": event_type,
            "payload": payload,
            "prevHash": events[-1]["hash"],
        }
    )
    _write_rehashed_events(adapter, events)


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class BoundedOutputTests(unittest.TestCase):
    def test_large_nonsecret_stdout_is_truncated_without_blocking_campaign(self) -> None:
        script = (
            "import os, sys\n"
            "from pathlib import Path\n"
            "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            "(evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n"
            "sys.stdout.write('x' * (6 * 1024 * 1024))\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "large-output",
                        "smoke",
                        argv=(sys.executable, "-c", script),
                    )
                ],
            )

            json_output(run_cli(adapter, "init", expected=0))
            initial = json_output(run_cli(adapter, "run", expected=0, timeout=60))
            self.assertEqual("READY_FOR_REGRESSION", initial["status"])

            case_run = load_state(adapter)["attempts"][-1]["caseRuns"][0]
            artifact = campaign_path(adapter) / case_run["artifactDir"]
            stdout = (artifact / "stdout.txt").read_bytes()
            result = read_json(artifact / "result.json")

            self.assertLessEqual(len(stdout), _OUTPUT_LIMIT + len(_TRUNCATION_MARKER))
            self.assertTrue(stdout.endswith(_TRUNCATION_MARKER))
            self.assertTrue(result["stdoutTruncated"])
            self.assertFalse(result["stderrTruncated"])
            self.assertIn("secretDetected", result)
            self.assertFalse(result["secretDetected"])

            completed = json_output(
                run_cli(
                    adapter,
                    "run",
                    "--mode",
                    "regression",
                    expected=0,
                    timeout=60,
                )
            )
            self.assertEqual("COMPLETE", completed["status"])
            report = json_output(run_cli(adapter, "audit", expected=0, timeout=60))
            self.assertTrue(report["ok"], report)

    def test_simultaneous_multibyte_streams_are_bounded_without_deadlock(self) -> None:
        script = (
            "import os, threading\n"
            "from pathlib import Path\n"
            "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            "(evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n"
            "chunk = ('\u754c' * 4096).encode('utf-8')\n"
            "repetitions = (6 * 1024 * 1024 // len(chunk)) + 1\n"
            "def emit(descriptor):\n"
            "    for _ in range(repetitions):\n"
            "        os.write(descriptor, chunk)\n"
            "threads = [\n"
            "    threading.Thread(target=emit, args=(1,)),\n"
            "    threading.Thread(target=emit, args=(2,)),\n"
            "]\n"
            "for thread in threads:\n"
            "    thread.start()\n"
            "for thread in threads:\n"
            "    thread.join()\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "simultaneous-multibyte-output",
                        "smoke",
                        argv=(sys.executable, "-c", script),
                    )
                ],
            )

            json_output(run_cli(adapter, "init", expected=0))
            initial = json_output(run_cli(adapter, "run", expected=0, timeout=60))
            self.assertEqual("READY_FOR_REGRESSION", initial["status"])

            case_run = load_state(adapter)["attempts"][-1]["caseRuns"][0]
            artifact = campaign_path(adapter) / case_run["artifactDir"]
            stdout = (artifact / "stdout.txt").read_bytes()
            stderr = (artifact / "stderr.txt").read_bytes()
            result = read_json(artifact / "result.json")

            for stream in (stdout, stderr):
                self.assertLessEqual(
                    len(stream),
                    _OUTPUT_LIMIT + len(_TRUNCATION_MARKER),
                )
                self.assertTrue(stream.endswith(_TRUNCATION_MARKER))
            self.assertTrue(result["stdoutTruncated"])
            self.assertTrue(result["stderrTruncated"])
            self.assertFalse(result["secretDetected"])
            self.assertEqual("PASS", result["status"])


class JournalReplayTests(unittest.TestCase):
    def _initialized_adapter(self, root: Path) -> Path:
        adapter = make_adapter(root, [make_case("smoke", "smoke")])
        json_output(run_cli(adapter, "init", expected=0))
        return adapter

    def _assert_replay_error_does_not_mutate(self, adapter: Path) -> None:
        campaign = campaign_path(adapter)
        before = _tree_snapshot(campaign)
        completed = run_cli(adapter, "status", expected=2)
        diagnostic = completed.stdout + completed.stderr
        self.assertNotIn("Traceback", diagnostic)
        self.assertIn("ERROR:", diagnostic)
        self.assertEqual(before, _tree_snapshot(campaign))

    def test_initialization_event_pins_all_versions_used_by_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            events = _read_events(adapter)
            self.assertEqual(1, len(events))
            initialized = events[0]
            self.assertEqual(4, initialized["schemaVersion"])
            self.assertEqual("campaign_initialized", initialized["type"])
            self.assertEqual("0.4.0", initialized["payload"]["kernelVersion"])
            self.assertEqual(4, initialized["payload"]["journalSchemaVersion"])
            self.assertEqual(1, initialized["payload"]["artifactManifestVersion"])

            # Make both disposable projections disagree. Status must replay the
            # authoritative journal and expose its pinned kernel version.
            campaign = campaign_path(adapter)
            state = read_json(campaign / "state.json")
            summary = read_json(campaign / "summary.json")
            state["kernelVersion"] = "projection-only-version"
            summary["kernelVersion"] = "projection-only-version"
            write_json(campaign / "state.json", state)
            write_json(campaign / "summary.json", summary)

            status = json_output(run_cli(adapter, "status", expected=0))
            self.assertEqual(initialized["payload"]["kernelVersion"], status["kernelVersion"])
            self.assertFalse(status["snapshotConsistent"])
            self.assertFalse(status["summaryConsistent"])

    def test_schema_two_campaign_is_status_and_audit_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            campaign = campaign_path(adapter)
            initialized = _read_events(adapter)[0]
            initialized["schemaVersion"] = 2
            initialized["payload"]["kernelVersion"] = "0.2.0"
            initialized["payload"]["journalSchemaVersion"] = 2
            initialized["payload"].pop("traceSnapshot")
            initialized.pop("hash")
            initialized["hash"] = "sha256:" + hashlib.sha256(
                _canonical_bytes(initialized)
            ).hexdigest()
            (campaign / "events.jsonl").write_bytes(
                _canonical_bytes(initialized) + b"\n"
            )

            scripts = str(Path(__file__).resolve().parents[1] / "scripts")
            if scripts not in sys.path:
                sys.path.insert(0, scripts)
            from journal_state import make_summary, replay_projection

            state = replay_projection([initialized])
            state["lastEventSeq"] = initialized["seq"]
            state["lastEventHash"] = initialized["hash"]
            write_json(campaign / "state.json", state)
            write_json(campaign / "summary.json", make_summary(state))

            status = json_output(run_cli(adapter, "status", expected=0))
            self.assertEqual(2, status["schemaVersion"])
            self.assertEqual("0.2.0", status["kernelVersion"])
            audit = json_output(run_cli(adapter, "audit", expected=1))
            self.assertFalse(audit["ok"])
            mutation = run_cli(adapter, "run", expected=2)
            self.assertIn("read-only", mutation.stderr)

    def test_schema_three_campaign_replays_and_remains_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            run_cli(adapter, "run", expected=0)
            campaign = campaign_path(adapter)
            events = _read_events(adapter)
            for event in events:
                event["schemaVersion"] = 3
                if event["type"] == "campaign_initialized":
                    event["payload"]["kernelVersion"] = "0.3.0"
                    event["payload"]["journalSchemaVersion"] = 3
                if event["type"] == "attempt_started":
                    event["payload"].pop("sourceSnapshot")
            _write_rehashed_events(adapter, events)
            events = _read_events(adapter)

            scripts = str(Path(__file__).resolve().parents[1] / "scripts")
            if scripts not in sys.path:
                sys.path.insert(0, scripts)
            from journal_state import make_summary, replay_projection

            state = replay_projection(events)
            state["lastEventSeq"] = events[-1]["seq"]
            state["lastEventHash"] = events[-1]["hash"]
            write_json(campaign / "state.json", state)
            write_json(campaign / "summary.json", make_summary(state))

            status = json_output(run_cli(adapter, "status", expected=0))
            self.assertEqual(3, status["schemaVersion"])
            self.assertEqual("0.3.0", status["kernelVersion"])
            self.assertEqual("READY_FOR_REGRESSION", status["executionStatus"])
            mutation = run_cli(
                adapter, "run", "--mode", "regression", expected=2
            )
            self.assertIn("read-only", mutation.stderr)

    def test_unknown_rehashed_event_is_rejected_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            _append_rehashed_event(adapter, "unknown_future_event", {})
            self._assert_replay_error_does_not_mutate(adapter)

    def test_rehashed_event_missing_required_field_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            events = _read_events(adapter)
            del events[0]["payload"]["kernelVersion"]
            _write_rehashed_events(adapter, events)
            self._assert_replay_error_does_not_mutate(adapter)

    def test_rehashed_illegal_transition_is_rejected_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            json_output(run_cli(adapter, "run", expected=0))
            state = load_state(adapter)
            closed_attempt = state["attempts"][-1]
            _append_rehashed_event(
                adapter,
                "case_started",
                {
                    "attemptId": closed_attempt["id"],
                    "runId": "run-illegal-transition",
                    "caseId": "smoke",
                    "ordinal": 2,
                    "artifactDir": closed_attempt["artifactDir"] + "/cases/illegal",
                    "sourceFingerprint": closed_attempt["sourceFingerprint"],
                },
            )
            self._assert_replay_error_does_not_mutate(adapter)

    def test_torn_journal_tail_is_rejected_and_never_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            journal = campaign_path(adapter) / "events.jsonl"
            with journal.open("ab") as handle:
                handle.write(b'{"schemaVersion":2,"seq":2,"type":"case_started"')
            torn_bytes = journal.read_bytes()

            self._assert_replay_error_does_not_mutate(adapter)
            self.assertEqual(torn_bytes, journal.read_bytes())


if __name__ == "__main__":
    unittest.main()
