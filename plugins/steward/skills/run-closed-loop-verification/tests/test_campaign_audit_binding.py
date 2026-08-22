"""Black-box audit tests for journal/result/artifact semantic bindings."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from typing import Any, Callable

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


_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _read_events(adapter: Path) -> list[dict[str, Any]]:
    journal = campaign_path(adapter) / "events.jsonl"
    return [
        json.loads(line.decode("utf-8"))
        for line in journal.read_bytes().split(b"\n")
        if line.strip()
    ]


def _write_rehashed_events(adapter: Path, events: list[dict[str, Any]]) -> None:
    """Write a valid hash chain without trying to replay the forged journal."""

    previous_hash = "0" * 64
    encoded: list[bytes] = []
    for sequence, original in enumerate(events, start=1):
        event = copy.deepcopy(original)
        event["seq"] = sequence
        event["prevHash"] = previous_hash
        event.pop("hash", None)
        event["hash"] = _sha256(_canonical_bytes(event))
        previous_hash = event["hash"]
        events[sequence - 1] = event
        encoded.append(_canonical_bytes(event))
    campaign = campaign_path(adapter)
    (campaign / "events.jsonl").write_bytes(b"\n".join(encoded) + b"\n")


def _rehash_and_sync_projection(
    adapter: Path, events: list[dict[str, Any]]
) -> None:
    """Write a valid hash chain and exact projections for a replayable forgery."""

    _write_rehashed_events(adapter, events)

    scripts = str(_SCRIPTS)
    added_path = scripts not in sys.path
    if added_path:
        sys.path.insert(0, scripts)
    try:
        journal_state = importlib.import_module("journal_state")
        state = journal_state.replay_projection(copy.deepcopy(events))
        summary = journal_state.make_summary(state)
    finally:
        if added_path:
            sys.path.remove(scripts)
    campaign = campaign_path(adapter)
    write_json(campaign / "state.json", state)
    write_json(campaign / "summary.json", summary)


def _sync_saved_exit_code_projection(
    adapter: Path,
    events: list[dict[str, Any]],
    finished: dict[str, Any],
) -> None:
    """Make saved projections match a forgery that strict replay must reject."""

    campaign = campaign_path(adapter)
    state = read_json(campaign / "state.json")
    summary = read_json(campaign / "summary.json")
    payload = finished["payload"]
    run_id = payload["runId"]
    binding = copy.deepcopy(payload["artifactManifest"])
    matched_attempt_run = False
    for attempt in state["attempts"]:
        for case_run in attempt["caseRuns"]:
            if case_run["runId"] == run_id:
                case_run["exitCode"] = payload["exitCode"]
                case_run["artifactManifest"] = copy.deepcopy(binding)
                matched_attempt_run = True
    matched_case_run = False
    for case_run in state["cases"][payload["caseId"]]["runs"]:
        if case_run["runId"] == run_id:
            case_run["exitCode"] = payload["exitCode"]
            case_run["artifactManifest"] = copy.deepcopy(binding)
            matched_case_run = True
    if not matched_attempt_run or not matched_case_run:
        raise AssertionError("forged final run is absent from the saved projection")
    state["lastEventSeq"] = events[-1]["seq"]
    state["lastEventHash"] = events[-1]["hash"]
    summary["lastEventSeq"] = events[-1]["seq"]
    summary["lastEventHash"] = events[-1]["hash"]
    write_json(campaign / "state.json", state)
    write_json(campaign / "summary.json", summary)


def _case_finished(
    events: list[dict[str, Any]],
    *,
    attempt_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    for event in events:
        payload = event.get("payload", {})
        if event.get("type") != "case_finished":
            continue
        if attempt_id is not None and payload.get("attemptId") != attempt_id:
            continue
        if status is not None and payload.get("status") != status:
            continue
        return event
    raise AssertionError(
        f"case_finished event not found: attempt={attempt_id!r}, status={status!r}"
    )


def _artifact_for_event(adapter: Path, event: dict[str, Any]) -> Path:
    return campaign_path(adapter) / event["payload"]["artifactDir"]


def _rewrite_result_and_manifest(
    adapter: Path,
    event: dict[str, Any],
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """Change result.json while preserving every file and manifest hash binding."""

    artifact = _artifact_for_event(adapter, event)
    result_path = artifact / "result.json"
    result = read_json(result_path)
    mutate(result)
    write_json(result_path, result)

    _rebind_result_file(adapter, event)


def _rebind_result_file(adapter: Path, event: dict[str, Any]) -> None:
    """Refresh the result entry and outer manifest binding after a raw rewrite."""

    artifact = _artifact_for_event(adapter, event)
    result_path = artifact / "result.json"
    result_bytes = result_path.read_bytes()
    manifest_path = artifact / "artifact-manifest.json"
    manifest = read_json(manifest_path)
    result_entry = next(
        item for item in manifest["files"] if item["relativePath"] == "result.json"
    )
    result_entry["size"] = len(result_bytes)
    result_entry["sha256"] = _sha256(result_bytes)
    write_json(manifest_path, manifest)

    _rebind_manifest(event, manifest_path)


def _rebind_manifest(event: dict[str, Any], manifest_path: Path) -> None:
    """Refresh the case-finished binding for an intentionally rewritten manifest."""

    manifest_bytes = manifest_path.read_bytes()
    event["payload"]["artifactManifest"]["size"] = len(manifest_bytes)
    event["payload"]["artifactManifest"]["sha256"] = _sha256(manifest_bytes)


def _passing_script() -> str:
    return (
        "import os, sys\n"
        "from pathlib import Path\n"
        "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
        "(evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n"
        "print('known stdout')\n"
        "print('known stderr', file=sys.stderr)\n"
    )


class CampaignAuditBindingTests(unittest.TestCase):
    maxDiff = None

    def _complete_campaign(self, root: Path) -> tuple[Path, str]:
        adapter = make_adapter(
            root,
            [
                make_case(
                    "smoke",
                    "smoke",
                    argv=(sys.executable, "-c", _passing_script()),
                )
            ],
        )
        json_output(run_cli(adapter, "init", expected=0))
        initial = json_output(run_cli(adapter, "run", expected=0))
        self.assertEqual("READY_FOR_REGRESSION", initial["status"])
        complete = json_output(
            run_cli(adapter, "run", "--mode", "regression", expected=0)
        )
        self.assertEqual("COMPLETE", complete["status"])
        self.assertTrue(json_output(run_cli(adapter, "audit", expected=0))["ok"])
        final_attempt_id = complete["finalRegressionAttemptId"]
        self.assertIsInstance(final_attempt_id, str)
        return adapter, final_attempt_id

    def _complete_after_historical_failure(self, root: Path) -> Path:
        script = (
            "import os, sys\n"
            "from pathlib import Path\n"
            "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            "(evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n"
            "raise SystemExit(7 if Path('mode.txt').read_text(encoding='utf-8').strip() "
            "== 'fail' else 0)\n"
        )
        (root / "mode.txt").write_text("fail\n", encoding="utf-8")
        adapter = make_adapter(
            root,
            [
                make_case(
                    "smoke",
                    "smoke",
                    argv=(sys.executable, "-c", script),
                )
            ],
        )
        json_output(run_cli(adapter, "init", expected=0))
        failed = json_output(run_cli(adapter, "run", expected=1))
        self.assertEqual("FAILED", failed["status"])

        (root / "mode.txt").write_text("pass\n", encoding="utf-8")
        fix = write_fix_for_latest_failure(adapter)
        json_output(run_cli(adapter, "record-fix", "--fix", str(fix), expected=0))
        retested = json_output(run_cli(adapter, "retest", expected=0))
        self.assertEqual("READY_FOR_REGRESSION", retested["status"])
        complete = json_output(
            run_cli(adapter, "run", "--mode", "regression", expected=0)
        )
        self.assertEqual("COMPLETE", complete["status"])
        self.assertTrue(json_output(run_cli(adapter, "audit", expected=0))["ok"])
        return adapter

    def _assert_audit_binding_rejected(self, adapter: Path) -> None:
        status = json_output(run_cli(adapter, "status", expected=0))
        self.assertTrue(status["snapshotConsistent"], status)
        self.assertTrue(status["summaryConsistent"], status)

        completed = run_cli(adapter, "audit", expected=(0, 1))
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)
        report = json_output(completed)
        self.assertEqual(1, completed.returncode, report)
        self.assertFalse(report["ok"], report)
        errors = "\n".join(report.get("errors", [])).lower()
        self.assertNotIn("state.json does not match journal replay", errors)
        self.assertNotIn("summary.json does not match journal replay", errors)

    def _assert_journal_rejected(self, adapter: Path) -> None:
        journal = campaign_path(adapter) / "events.jsonl"
        forged = journal.read_bytes()
        for command in ("status", "audit"):
            with self.subTest(command=command):
                completed = run_cli(adapter, command, expected=2)
                diagnostic = completed.stdout + completed.stderr
                self.assertNotIn("Traceback", diagnostic)
                self.assertIn("ERROR:", diagnostic)
                self.assertEqual(forged, journal.read_bytes())

    def test_final_output_hashes_in_journal_must_match_result_and_files(self) -> None:
        mutations = {
            "stdoutSha256": _sha256(b"forged stdout\n"),
            "stderrSha256": _sha256(b"forged stderr\n"),
        }
        for field, forged_hash in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                adapter, final_attempt_id = self._complete_campaign(Path(temporary))
                events = _read_events(adapter)
                finished = _case_finished(events, attempt_id=final_attempt_id)
                finished["payload"][field] = forged_hash
                _rehash_and_sync_projection(adapter, events)
                self._assert_audit_binding_rejected(adapter)

    def test_result_semantics_must_match_final_journal_outcome(self) -> None:
        def forge_evidence(result: dict[str, Any]) -> None:
            result["evidence"]["missingFiles"] = ["proof.json"]

        mutations: tuple[
            tuple[str, Callable[[dict[str, Any]], None]], ...
        ] = (
            ("reason", lambda result: result.__setitem__("reason", "forged reason")),
            ("exitCode", lambda result: result.__setitem__("exitCode", 19)),
            ("timedOut", lambda result: result.__setitem__("timedOut", True)),
            (
                "sourceFingerprintBefore",
                lambda result: result.__setitem__(
                    "sourceFingerprintBefore", "sha256:" + "a" * 64
                ),
            ),
            (
                "sourceFingerprintAfter",
                lambda result: result.__setitem__(
                    "sourceFingerprintAfter", "sha256:" + "b" * 64
                ),
            ),
            ("evidence", forge_evidence),
        )
        for field, mutate in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                adapter, final_attempt_id = self._complete_campaign(Path(temporary))
                events = _read_events(adapter)
                finished = _case_finished(events, attempt_id=final_attempt_id)
                _rewrite_result_and_manifest(adapter, finished, mutate)
                _rehash_and_sync_projection(adapter, events)
                self._assert_audit_binding_rejected(adapter)

    def test_historical_failed_result_status_must_match_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._complete_after_historical_failure(Path(temporary))
            events = _read_events(adapter)
            failed = _case_finished(events, status="FAILED")
            _rewrite_result_and_manifest(
                adapter,
                failed,
                lambda result: result.__setitem__("status", "PASS"),
            )
            _rehash_and_sync_projection(adapter, events)
            self._assert_audit_binding_rejected(adapter)

    def test_artifact_manifest_binding_relative_path_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter, final_attempt_id = self._complete_campaign(Path(temporary))
            events = _read_events(adapter)
            finished = _case_finished(events, attempt_id=final_attempt_id)
            finished["payload"]["artifactManifest"]["relativePath"] = (
                "attempts/forged/artifact-manifest.json"
            )
            _write_rehashed_events(adapter, events)
            self._assert_journal_rejected(adapter)

    def test_pass_with_nonzero_exit_is_rejected_when_all_bindings_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter, final_attempt_id = self._complete_campaign(Path(temporary))
            events = _read_events(adapter)
            finished = _case_finished(events, attempt_id=final_attempt_id)
            finished["payload"]["exitCode"] = 19
            _rewrite_result_and_manifest(
                adapter,
                finished,
                lambda result: result.__setitem__("exitCode", 19),
            )
            _write_rehashed_events(adapter, events)
            _sync_saved_exit_code_projection(adapter, events, finished)
            self._assert_journal_rejected(adapter)

    def test_pass_with_secret_flag_is_rejected_when_all_bindings_match(self) -> None:
        def forge_secret_flags(result: dict[str, Any]) -> None:
            result["secretDetected"] = True
            result["secretLikeOutput"] = True

        with tempfile.TemporaryDirectory() as temporary:
            adapter, final_attempt_id = self._complete_campaign(Path(temporary))
            events = _read_events(adapter)
            finished = _case_finished(events, attempt_id=final_attempt_id)
            _rewrite_result_and_manifest(adapter, finished, forge_secret_flags)
            _rehash_and_sync_projection(adapter, events)
            self._assert_audit_binding_rejected(adapter)

    def test_result_and_manifest_malformed_shapes_are_rejected(self) -> None:
        def result_array(adapter: Path, event: dict[str, Any]) -> None:
            artifact = _artifact_for_event(adapter, event)
            (artifact / "result.json").write_bytes(b"[]\n")
            _rebind_result_file(adapter, event)

        def result_unknown_field(adapter: Path, event: dict[str, Any]) -> None:
            _rewrite_result_and_manifest(
                adapter,
                event,
                lambda result: result.__setitem__("unknown", False),
            )

        def result_duplicate_key(adapter: Path, event: dict[str, Any]) -> None:
            artifact = _artifact_for_event(adapter, event)
            result_path = artifact / "result.json"
            original = read_json(result_path)
            raw = _canonical_bytes(original).decode("utf-8")
            needle = '"status":"PASS"'
            self.assertEqual(1, raw.count(needle))
            forged = raw.replace(
                needle,
                '"status":"FAILED","status":"PASS"',
                1,
            )
            self.assertEqual(original, json.loads(forged))
            result_path.write_bytes(forged.encode("utf-8") + b"\n")
            _rebind_result_file(adapter, event)

        def manifest_unknown_field(adapter: Path, event: dict[str, Any]) -> None:
            manifest_path = _artifact_for_event(adapter, event) / "artifact-manifest.json"
            manifest = read_json(manifest_path)
            manifest["unknown"] = False
            write_json(manifest_path, manifest)
            _rebind_manifest(event, manifest_path)

        def manifest_duplicate_entry(adapter: Path, event: dict[str, Any]) -> None:
            manifest_path = _artifact_for_event(adapter, event) / "artifact-manifest.json"
            manifest = read_json(manifest_path)
            manifest["files"].append(copy.deepcopy(manifest["files"][0]))
            write_json(manifest_path, manifest)
            _rebind_manifest(event, manifest_path)

        def manifest_duplicate_key(adapter: Path, event: dict[str, Any]) -> None:
            manifest_path = _artifact_for_event(adapter, event) / "artifact-manifest.json"
            original = read_json(manifest_path)
            raw = _canonical_bytes(original).decode("utf-8")
            needle = '"files":'
            self.assertEqual(1, raw.count(needle))
            forged = raw.replace(needle, '"files":[],"files":', 1)
            self.assertEqual(original, json.loads(forged))
            manifest_path.write_bytes(forged.encode("utf-8") + b"\n")
            _rebind_manifest(event, manifest_path)

        mutations: tuple[
            tuple[str, Callable[[Path, dict[str, Any]], None]], ...
        ] = (
            ("result array", result_array),
            ("result unknown field", result_unknown_field),
            ("result duplicate key", result_duplicate_key),
            ("manifest unknown field", manifest_unknown_field),
            ("manifest duplicate relativePath", manifest_duplicate_entry),
            ("manifest duplicate key", manifest_duplicate_key),
        )
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                adapter, final_attempt_id = self._complete_campaign(Path(temporary))
                events = _read_events(adapter)
                finished = _case_finished(events, attempt_id=final_attempt_id)
                mutate(adapter, finished)
                _rehash_and_sync_projection(adapter, events)
                self._assert_audit_binding_rejected(adapter)


if __name__ == "__main__":
    unittest.main()
