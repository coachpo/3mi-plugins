"""Raw-journal and initialized-metadata black-box regression tests."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, Sequence
from unittest import mock

try:
    from .helpers import (
        campaign_path,
        json_output,
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
        make_adapter,
        make_case,
        read_json,
        run_cli,
        write_json,
    )


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import journal_state as journal_runtime  # noqa: E402
from adapter_paths import source_snapshot, validate_adapter  # noqa: E402


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _event_hash(event_without_hash: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_bytes(event_without_hash)).hexdigest()
    return "sha256:" + digest


def _read_events(adapter: Path) -> list[dict[str, Any]]:
    journal = campaign_path(adapter) / "events.jsonl"
    events: list[dict[str, Any]] = []
    for raw_line in journal.read_bytes().split(b"\n"):
        if raw_line.strip():
            events.append(json.loads(raw_line.decode("utf-8")))
    return events


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
        events[sequence - 1] = event
        encoded.append(_canonical_bytes(event))
    journal = campaign_path(adapter) / "events.jsonl"
    journal.write_bytes(b"\n".join(encoded) + b"\n")


def _set_nested(root: Any, path: Sequence[str | int], value: Any) -> None:
    current = root
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = copy.deepcopy(value)


def _inject_duplicate_key(canonical: str, level: str) -> str:
    if level == "event":
        return canonical[:1] + '"type":"forged",' + canonical[1:]

    payload_marker = '"payload":{'
    payload_start = canonical.index(payload_marker) + len(payload_marker)
    if level == "payload":
        return (
            canonical[:payload_start]
            + '"projectId":"forged",'
            + canonical[payload_start:]
        )

    if level == "nested case":
        # The init payload now also contains a complete catalog preimage. Limit
        # this lookup to the direct payload.cases value, before payload.catalog,
        # instead of ambiguously replacing catalog.cases as the schema evolves.
        catalog_start = canonical.index('"catalog":{', payload_start)
        cases_marker = '"cases":[{'
        cases_start = canonical.index(
            cases_marker,
            payload_start,
            catalog_start,
        ) + len(cases_marker)
        return (
            canonical[:cases_start]
            + '"required":false,'
            + canonical[cases_start:]
        )

    raise AssertionError("unknown duplicate-key injection level: " + level)


def _sync_projection_hashes(
    adapter: Path,
    state: dict[str, Any],
    summary: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    last_event = events[-1]
    state["lastEventSeq"] = last_event["seq"]
    state["lastEventHash"] = last_event["hash"]
    summary["lastEventSeq"] = last_event["seq"]
    summary["lastEventHash"] = last_event["hash"]
    campaign = campaign_path(adapter)
    write_json(campaign / "state.json", state)
    write_json(campaign / "summary.json", summary)


class RawJournalTests(unittest.TestCase):
    def _initialized_adapter(self, root: Path) -> Path:
        adapter = make_adapter(root, [make_case("smoke", "smoke")])
        json_output(run_cli(adapter, "init", expected=0))
        return adapter

    def _assert_load_rejects(self, adapter: Path) -> None:
        journal = campaign_path(adapter) / "events.jsonl"
        forged = journal.read_bytes()
        for command in ("status", "audit"):
            with self.subTest(command=command):
                completed = run_cli(adapter, command, expected=2)
                diagnostic = completed.stdout + completed.stderr
                self.assertNotIn("Traceback", diagnostic)
                self.assertIn("ERROR:", diagnostic)
                self.assertEqual(forged, journal.read_bytes())

    def test_unicode_line_separator_remains_one_physical_journal_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(root, [make_case("smoke", "smoke")])
            data = read_json(adapter)
            data["projectId"] = "project\u2028identifier"
            data["cases"][0]["fixture"] = {
                "kind": "temporary",
                "description": "fixture\u2028description",
            }
            write_json(adapter, data)

            initialized = json_output(run_cli(adapter, "init", expected=0))
            self.assertEqual("project\u2028identifier", initialized["projectId"])
            observed = json_output(run_cli(adapter, "status", expected=0))
            self.assertEqual("project\u2028identifier", observed["projectId"])
            executed = json_output(run_cli(adapter, "run", expected=0))
            self.assertEqual("READY_FOR_REGRESSION", executed["status"])
            observed = json_output(run_cli(adapter, "status", expected=0))
            self.assertEqual("READY_FOR_REGRESSION", observed["status"])

            raw_journal = (campaign_path(adapter) / "events.jsonl").read_bytes()
            self.assertIn("\u2028".encode("utf-8"), raw_journal)
            physical_lines = [
                line for line in raw_journal.split(b"\n") if line.strip()
            ]
            decoded = [json.loads(line.decode("utf-8")) for line in physical_lines]
            self.assertEqual(decoded[-1]["seq"], len(decoded))
            self.assertEqual("project\u2028identifier", decoded[0]["payload"]["projectId"])

    def test_duplicate_keys_are_rejected_before_hash_validation(self) -> None:
        for name in ("event", "payload", "nested case"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                adapter = self._initialized_adapter(Path(temporary))
                journal = campaign_path(adapter) / "events.jsonl"
                original = _read_events(adapter)[0]
                canonical = _canonical_bytes(original).decode("utf-8")
                forged = _inject_duplicate_key(canonical, name)

                # A permissive last-key-wins parser sees the original event, so
                # its canonical event hash remains valid despite the raw duplicate.
                permissive = json.loads(forged)
                self.assertEqual(original, permissive)
                unhashed = dict(permissive)
                supplied_hash = unhashed.pop("hash")
                self.assertEqual(supplied_hash, _event_hash(unhashed))

                journal.write_bytes(forged.encode("utf-8") + b"\n")
                self._assert_load_rejects(adapter)

    def test_append_crossing_journal_limit_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            validated = validate_adapter(adapter)
            journal = validated.campaign_root / "events.jsonl"
            original = journal.read_bytes()
            with journal_runtime.CampaignLock(validated.campaign_root):
                campaign = journal_runtime.Campaign.load(validated)
                with mock.patch.object(
                    journal_runtime,
                    "MAX_JOURNAL_BYTES",
                    len(original) + 64,
                ):
                    with self.assertRaisesRegex(
                        journal_runtime.CampaignError, "safe size limit"
                    ):
                        campaign.start_attempt(
                            "initial", campaign.current_source()
                        )
            self.assertEqual(original, journal.read_bytes())

    def test_journal_metadata_change_during_read_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            journal = campaign_path(adapter) / "events.jsonl"
            before = journal.lstat()
            changed = types.SimpleNamespace(
                st_mode=before.st_mode,
                st_dev=before.st_dev,
                st_ino=before.st_ino,
                st_size=before.st_size + 1,
                st_mtime_ns=before.st_mtime_ns,
                st_ctime_ns=before.st_ctime_ns,
            )
            with mock.patch.object(
                journal_runtime,
                "require_safe_owned_path",
                side_effect=[before, changed],
            ):
                with self.assertRaisesRegex(
                    journal_runtime.CampaignError, "changed while it was read"
                ):
                    journal_runtime.read_events(journal)

    def test_append_rejects_non_newline_terminated_journal_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            validated = validate_adapter(adapter)
            journal = validated.campaign_root / "events.jsonl"
            initialized = journal_runtime.Campaign.load(validated)
            source = initialized.current_source()
            original = journal.read_bytes()
            self.assertTrue(original.endswith(b"\n"))
            unterminated = original[:-1]
            journal.write_bytes(unterminated)

            with self.assertRaisesRegex(
                journal_runtime.CampaignError, "newline-terminated"
            ):
                journal_runtime.append_event(
                    validated.campaign_root,
                    "attempt_started",
                    {
                        "attemptId": "attempt-0001-initial-deadbeef",
                        "mode": "initial",
                        "sourceFingerprint": source,
                        "catalogFingerprint": initialized.state[
                            "catalogFingerprint"
                        ],
                        "artifactDir": "attempts/attempt-0001-initial-deadbeef",
                        "resumedFrom": None,
                        "targetCaseId": None,
                        "sourceSnapshot": source_snapshot(validated),
                    },
                )
            self.assertEqual(unterminated, journal.read_bytes())

    def test_attempt_ordinal_exhaustion_precedes_allocation_and_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            validated = validate_adapter(adapter)
            journal = validated.campaign_root / "events.jsonl"
            attempts_root = validated.campaign_root / "attempts"
            original_journal = journal.read_bytes()
            original_entries = list(attempts_root.iterdir())

            with journal_runtime.CampaignLock(validated.campaign_root):
                campaign = journal_runtime.Campaign.load(validated)
                campaign.state["attempts"] = [
                    {} for _ in range(journal_runtime.MAX_ATTEMPT_ORDINAL)
                ]
                with self.assertRaisesRegex(
                    journal_runtime.CampaignError, "attempt limit"
                ):
                    campaign.start_attempt("quick", campaign.current_source())

            self.assertEqual(original_journal, journal.read_bytes())
            self.assertEqual(original_entries, list(attempts_root.iterdir()))

    def test_case_evidence_projection_limit_is_preflighted_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self._initialized_adapter(Path(temporary))
            validated = validate_adapter(adapter)
            journal = validated.campaign_root / "events.jsonl"
            digest = "sha256:" + "0" * 64

            with journal_runtime.CampaignLock(validated.campaign_root):
                campaign = journal_runtime.Campaign.load(validated)
                source = campaign.current_source()
                attempt_id = campaign.start_attempt("initial", source)
                run_id, artifact_dir = campaign.allocate_case_artifact(
                    attempt_id, "smoke", 1
                )
                relative = artifact_dir.relative_to(validated.campaign_root).as_posix()
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
                evidence_path = "proof-" + "x" * 4096 + ".json"
                payload = {
                    "attemptId": attempt_id,
                    "runId": run_id,
                    "caseId": "smoke",
                    "ordinal": 1,
                    "artifactDir": relative,
                    "status": "PASS",
                    "reason": None,
                    "exitCode": 0,
                    "timedOut": False,
                    "evidence": {
                        "requiredFiles": [evidence_path],
                        "nonEmptyFiles": [evidence_path],
                        "missingFiles": [],
                        "emptyFiles": [],
                        "files": [
                            {"path": evidence_path, "size": 1, "sha256": digest}
                        ],
                        "secretLikeContent": False,
                    },
                    "stdoutSha256": digest,
                    "stderrSha256": digest,
                    "sourceFingerprint": source,
                    "sourceAfterFingerprint": source,
                    "artifactManifest": {
                        "relativePath": relative + "/artifact-manifest.json",
                        "size": 1,
                        "sha256": digest,
                    },
                }
                current_limit = max(
                    len(_canonical_bytes(campaign.state)) + 1,
                    len(_canonical_bytes(journal_runtime.make_summary(campaign.state)))
                    + 1,
                )
                original = journal.read_bytes()
                original_state = copy.deepcopy(campaign.state)
                with mock.patch.object(
                    journal_runtime, "MAX_PROJECTION_BYTES", current_limit
                ):
                    with self.assertRaisesRegex(
                        journal_runtime.CampaignError, "projection.*safe size limit"
                    ):
                        campaign.commit("case_finished", payload)
                self.assertEqual(original, journal.read_bytes())
                self.assertEqual(original_state, campaign.state)

                # A raw but otherwise valid event cannot bypass the same bound:
                # replay rejects it instead of producing an unreadable cache.
                journal_runtime.append_event(
                    validated.campaign_root, "case_finished", payload
                )
                with mock.patch.object(
                    journal_runtime, "MAX_PROJECTION_BYTES", current_limit
                ):
                    with self.assertRaisesRegex(
                        journal_runtime.CampaignError, "projection.*safe size limit"
                    ):
                        journal_runtime.Campaign.load(validated)


class InitializedMetadataBindingTests(unittest.TestCase):
    def _forge_initialized_metadata(
        self,
        adapter: Path,
        event_path: Sequence[str | int],
        state_path: Sequence[str | int],
        summary_path: Sequence[str | int] | None,
        value: Any,
    ) -> None:
        events = _read_events(adapter)
        state = read_json(campaign_path(adapter) / "state.json")
        summary = read_json(campaign_path(adapter) / "summary.json")
        _set_nested(events[0]["payload"], event_path, value)
        _set_nested(state, state_path, value)
        if summary_path is not None:
            _set_nested(summary, summary_path, value)
        _write_rehashed_events(adapter, events)
        _sync_projection_hashes(adapter, state, summary, events)

    def test_rehashed_initialized_metadata_must_match_current_adapter(self) -> None:
        forged_evidence = {
            "requiredFiles": ["forged.json"],
            "nonEmptyFiles": ["forged.json"],
        }
        mutations = (
            (
                "case required",
                ("cases", 0, "required"),
                ("cases", "smoke", "required"),
                ("cases", "smoke", "required"),
                False,
            ),
            (
                "case category",
                ("cases", 0, "category"),
                ("cases", "smoke", "category"),
                ("cases", "smoke", "category"),
                "functional",
            ),
            (
                "case platform",
                ("cases", 0, "platform"),
                ("cases", "smoke", "platform"),
                None,
                "windows",
            ),
            (
                "case evidence",
                ("cases", 0, "evidence"),
                ("cases", "smoke", "evidence"),
                None,
                forged_evidence,
            ),
            (
                "project id",
                ("projectId",),
                ("projectId",),
                ("projectId",),
                "forged-project",
            ),
            (
                "source provider",
                ("sourceProvider",),
                ("sourceProvider",),
                None,
                "files",
            ),
            (
                "catalog fingerprint",
                ("catalogFingerprint",),
                ("catalogFingerprint",),
                ("catalogFingerprint",),
                "sha256:" + "f" * 64,
            ),
        )
        for name, event_path, state_path, summary_path, value in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                adapter = make_adapter(root, [make_case("smoke", "smoke")])
                json_output(run_cli(adapter, "init", expected=0))
                self._forge_initialized_metadata(
                    adapter,
                    event_path,
                    state_path,
                    summary_path,
                    value,
                )
                self._assert_consistent_projection_rejected(adapter)

    def _assert_consistent_projection_rejected(self, adapter: Path) -> None:
        for command in ("status", "audit"):
            with self.subTest(command=command):
                completed = run_cli(adapter, command, expected=2)
                diagnostic = completed.stdout + completed.stderr
                self.assertNotIn("Traceback", diagnostic)
                self.assertIn("ERROR:", diagnostic)


class OptionalFinalOutcomeTests(unittest.TestCase):
    def test_rehashed_optional_final_pass_cannot_become_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case("required-smoke", "smoke"),
                    make_case(
                        "optional-final",
                        "functional",
                        required=False,
                        depends_on=("required-smoke",),
                    ),
                ],
            )
            json_output(run_cli(adapter, "init", expected=0))
            json_output(run_cli(adapter, "run", expected=0))
            completed = json_output(
                run_cli(adapter, "run", "--mode", "regression", expected=0)
            )
            self.assertEqual("COMPLETE", completed["status"])
            self.assertTrue(json_output(run_cli(adapter, "audit", expected=0))["ok"])

            campaign = campaign_path(adapter)
            events = _read_events(adapter)
            state = read_json(campaign / "state.json")
            summary = read_json(campaign / "summary.json")
            final_attempt_id = state["finalRegressionAttemptId"]
            finished = next(
                event
                for event in events
                if event["type"] == "case_finished"
                and event["payload"]["attemptId"] == final_attempt_id
                and event["payload"]["caseId"] == "optional-final"
            )
            run_id = finished["payload"]["runId"]
            finished["payload"]["status"] = "NOT_RUN"
            _write_rehashed_events(adapter, events)

            final_attempt = next(
                attempt
                for attempt in state["attempts"]
                if attempt["id"] == final_attempt_id
            )
            final_run = next(
                run for run in final_attempt["caseRuns"] if run["runId"] == run_id
            )
            final_run["status"] = "NOT_RUN"
            case_state = state["cases"]["optional-final"]
            case_state["status"] = "NOT_RUN"
            case_state["lastOutcome"]["status"] = "NOT_RUN"
            stored_run = next(
                run for run in case_state["runs"] if run["runId"] == run_id
            )
            stored_run["status"] = "NOT_RUN"

            summary_case = summary["cases"]["optional-final"]
            summary_case["status"] = "NOT_RUN"
            summary_case["lastOutcome"]["status"] = "NOT_RUN"
            summary["counts"]["PASS"] -= 1
            summary["counts"]["NOT_RUN"] += 1
            _sync_projection_hashes(adapter, state, summary, events)

            status = run_cli(adapter, "status", expected=(0, 2))
            diagnostic = status.stdout + status.stderr
            self.assertNotIn("Traceback", diagnostic)
            if status.returncode == 0:
                report = json_output(status)
                self.assertTrue(report["snapshotConsistent"], report)
                self.assertTrue(report["summaryConsistent"], report)

            audited = run_cli(adapter, "audit", expected=(1, 2))
            diagnostic = audited.stdout + audited.stderr
            self.assertNotIn("Traceback", diagnostic)
            if audited.returncode == 1:
                report = json_output(audited)
                self.assertFalse(report["ok"], report)
            else:
                self.assertIn("ERROR:", diagnostic)


if __name__ == "__main__":
    unittest.main()
