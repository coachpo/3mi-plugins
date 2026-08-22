from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable

try:
    from .helpers import json_output, read_json, run_cli, write_json
    from .test_campaign_traceability import (
        INV_ID,
        RF_ID,
        bind_review_request,
        make_review_trace_adapter,
        make_traceable_adapter,
        review_request,
    )
except ImportError:
    from helpers import json_output, read_json, run_cli, write_json  # type: ignore
    from test_campaign_traceability import (  # type: ignore
        INV_ID,
        RF_ID,
        bind_review_request,
        make_review_trace_adapter,
        make_traceable_adapter,
        review_request,
    )


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_rehashed_events(root: Path, events: list[dict]) -> None:
    previous = "0" * 64
    encoded: list[bytes] = []
    for sequence, source in enumerate(events, start=1):
        event = copy.deepcopy(source)
        event["seq"] = sequence
        event["prevHash"] = previous
        event.pop("hash", None)
        raw = json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        event["hash"] = "sha256:" + hashlib.sha256(raw).hexdigest()
        previous = event["hash"]
        encoded.append(
            json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
    (root / ".campaign" / "events.jsonl").write_bytes(b"\n".join(encoded) + b"\n")


def _attestation(
    root: Path,
    adapter: Path,
    *,
    source_fingerprint: str,
    outcome: str = "findings",
    gaps: list[dict] | None = None,
) -> dict:
    trace = read_json(adapter)["traceability"]
    return {
        "sourceFingerprint": source_fingerprint,
        "goalContractSha256": trace["goalContract"]["sha256"],
        "invariantsSha256": trace["invariants"]["sha256"],
        "outcome": outcome,
        "scope": [{"path": "source.txt", "sha256": _sha256(root / "source.txt")}],
        "gaps": list(gaps or []),
    }


def _refresh_review_digest(root: Path, adapter: Path) -> None:
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from semantic_review import load_review_manifest, review_manifest_sha256

    value = read_json(adapter)
    value["traceability"]["reviewFindings"]["sha256"] = review_manifest_sha256(
        load_review_manifest(root / "review-findings.json", project_root=root)
    )
    write_json(adapter, value)


def prepare_strict_failed_campaign(
    root: Path,
    *,
    request_kind: str = "source",
) -> tuple[Path, dict]:
    command = (
        "import os,pathlib; "
        "passing=pathlib.Path('behavior.txt').read_text(encoding='utf-8').strip()=='pass'; "
        "evidence=pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR']); "
        "evidence.joinpath('proof.json').write_text('{\"guardrail\":true}',encoding='utf-8') if passing else None; "
        "raise SystemExit(0 if passing else 1)"
    )
    (root / "behavior.txt").write_text("fail\n", encoding="utf-8")
    (root / "guardrail-test.txt").write_text(
        "permanent regression guardrail\n", encoding="utf-8"
    )
    adapter = make_review_trace_adapter(
        root,
        argv=(sys.executable, "-c", command),
    )
    source_manifest = read_json(root / "source-manifest.json")
    source_manifest["files"] = [
        item
        for item in source_manifest["files"]
        if item != "review-findings.json"
    ]
    source_manifest["files"].extend(["behavior.txt", "guardrail-test.txt"])
    write_json(root / "source-manifest.json", source_manifest)

    observed = json_output(run_cli(adapter, "observe-source", expected=0))
    review = read_json(root / "review-findings.json")
    review["attestation"] = _attestation(
        root,
        adapter,
        source_fingerprint=observed["sourceFingerprint"],
    )
    write_json(root / "review-findings.json", review)
    bind_review_request(
        root,
        adapter,
        observed["sourceFingerprint"],
        kind=request_kind,
    )

    initialized = json_output(run_cli(adapter, "init", expected=0))
    failed = json_output(run_cli(adapter, "run", expected=1))
    state = read_json(root / ".campaign" / "state.json")
    failed_run = next(
        run
        for attempt in state["attempts"]
        for run in attempt["caseRuns"]
        if run["status"] == "FAILED"
    )
    (root / "behavior.txt").write_text("pass\n", encoding="utf-8")
    fixed = json_output(run_cli(adapter, "status", expected=0))
    fix = {
        "failedCaseId": "counterexample-case",
        "failedRound": "initial",
        "failedAttemptId": failed["attempts"][-1]["id"],
        "failedSourceFingerprint": failed_run["sourceFingerprint"],
        "fixedSourceFingerprint": fixed["currentObservedSourceFingerprint"],
        "rootCause": "The fixture selected the unsafe transition.",
        "violatedInvariant": INV_ID,
        "rootCauseSource": {
            "path": "behavior.txt",
            "lineStart": 1,
            "lineEnd": 1,
        },
        "resolvedFindingIds": [RF_ID],
        "changedFiles": ["behavior.txt"],
        "fixSummary": "Select the guarded transition and retain its proof.",
        "externalCondition": False,
        "permanentGuardrail": {
            "kind": "test",
            "sourcePath": "guardrail-test.txt",
            "caseId": "counterexample-case",
            "evidenceFile": "proof.json",
        },
        "minimalRegression": {"evidence": ["proof.json"]},
    }
    fix_path = write_json(root / "fix.json", fix)
    recorded = json_output(
        run_cli(adapter, "record-fix", "--fix", str(fix_path), expected=0)
    )
    self_check = initialized["traceSnapshot"]["reviewFindings"]
    if "attestation" not in self_check or not recorded["pendingFix"]:
        raise AssertionError("strict fixture did not initialize its lifecycle")
    return adapter, fix


def write_post_fix_review(
    root: Path,
    adapter: Path,
    fix: dict,
    *,
    mutate: Callable[[dict], None] | None = None,
    name: str = "review-post-fix.json",
    head_identity: str | None = None,
) -> Path:
    review = copy.deepcopy(read_json(root / "review-findings.json"))
    review["findings"][0]["resolutionState"] = "resolved"
    review["attestation"] = _attestation(
        root,
        adapter,
        source_fingerprint=fix["fixedSourceFingerprint"],
    )
    initial_request = review["reviewRequest"]
    review["reviewRequest"] = review_request(
        fix["fixedSourceFingerprint"],
        requested_paths=tuple(initial_request["requestedPaths"]),
        kind=initial_request["target"]["kind"],
        base_identity=initial_request["target"].get("baseIdentity", "base-v1"),
        head_identity=(
            head_identity
            if head_identity is not None
            else initial_request["target"].get("headIdentity", "head-v1")
        ),
    )
    if mutate is not None:
        mutate(review)
    return write_json(root / name, review)


class ReviewHandoffTests(unittest.TestCase):
    def test_observe_source_is_read_only_and_emits_bounded_file_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_review_trace_adapter(root)
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            observed = json_output(run_cli(adapter, "observe-source", expected=0))
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            self.assertEqual(before, after)
            self.assertTrue(observed["sourceFingerprint"].startswith("sha256:"))
            self.assertEqual(observed["files"], sorted(observed["files"], key=lambda item: item["path"]))
            self.assertTrue(all(set(item) == {"path", "sha256"} for item in observed["files"]))

    def test_attested_no_findings_can_complete_without_a_fix_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_traceable_adapter(
                root,
                ("The declared behavior has deterministic evidence",),
                covered=("C1",),
            )
            source_manifest = read_json(root / "source-manifest.json")
            source_manifest["files"].remove("review-findings.json")
            write_json(root / "source-manifest.json", source_manifest)
            observed = json_output(run_cli(adapter, "observe-source", expected=0))
            review = read_json(root / "review-findings.json")
            review["attestation"] = _attestation(
                root,
                adapter,
                source_fingerprint=observed["sourceFingerprint"],
                outcome="no-findings",
            )
            write_json(root / "review-findings.json", review)
            bind_review_request(root, adapter, observed["sourceFingerprint"])
            initialized = json_output(run_cli(adapter, "init", expected=0))
            snapshot = initialized["traceSnapshot"]["reviewFindings"]
            self.assertTrue(snapshot["bindingsVerified"])
            self.assertEqual(
                snapshot["reviewRequest"]["requestSha256"],
                snapshot["reviewRequestSha256"],
            )
            status = json_output(run_cli(adapter, "status", expected=0))
            self.assertEqual("attested", status["traceabilityMode"])
            run_cli(adapter, "run", expected=0)
            original_source = (root / "source.txt").read_text(encoding="utf-8")
            (root / "source.txt").write_text(
                original_source + "drift\n", encoding="utf-8"
            )
            rejected = run_cli(
                adapter, "run", "--mode", "regression", expected=2
            )
            self.assertIn("REVIEW_HANDOFF_REQUIRED", rejected.stderr)
            (root / "source.txt").write_text(original_source, encoding="utf-8")
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            audit = json_output(run_cli(adapter, "audit", expected=0))
            self.assertTrue(audit["ok"])
            self.assertEqual([], audit["traceability"]["reviewHandoffs"])

    def test_attestation_without_request_remains_legacy_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_traceable_adapter(
                root,
                ("The declared behavior has deterministic evidence",),
                covered=("C1",),
            )
            source_manifest = read_json(root / "source-manifest.json")
            source_manifest["files"].remove("review-findings.json")
            write_json(root / "source-manifest.json", source_manifest)
            observed = json_output(run_cli(adapter, "observe-source", expected=0))
            review = read_json(root / "review-findings.json")
            review["attestation"] = _attestation(
                root,
                adapter,
                source_fingerprint=observed["sourceFingerprint"],
                outcome="no-findings",
            )
            write_json(root / "review-findings.json", review)
            _refresh_review_digest(root, adapter)

            initialized = json_output(run_cli(adapter, "init", expected=0))

            status = json_output(run_cli(adapter, "status", expected=0))
            self.assertEqual("legacy", status["traceabilityMode"])
            snapshot = initialized["traceSnapshot"]["reviewFindings"]
            self.assertIn("attestation", snapshot)
            self.assertNotIn("reviewRequest", snapshot)
            self.assertNotIn("bindingsVerified", snapshot)

    def test_review_request_and_catalog_pin_must_be_present_together(self) -> None:
        variants = (
            ("request-only", "REVIEW_REQUEST_REQUIRED"),
            ("pin-only", "REVIEW_REQUEST_REQUIRED"),
            ("mismatch", "REVIEW_REQUEST_MISMATCH"),
        )
        for variant, expected_error in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                adapter = make_traceable_adapter(
                    root,
                    ("The declared behavior has deterministic evidence",),
                    covered=("C1",),
                )
                source_manifest = read_json(root / "source-manifest.json")
                source_manifest["files"].remove("review-findings.json")
                write_json(root / "source-manifest.json", source_manifest)
                observed = json_output(
                    run_cli(adapter, "observe-source", expected=0)
                )
                review = read_json(root / "review-findings.json")
                review["attestation"] = _attestation(
                    root,
                    adapter,
                    source_fingerprint=observed["sourceFingerprint"],
                    outcome="no-findings",
                )
                request = review_request(observed["sourceFingerprint"])
                if variant != "pin-only":
                    review["reviewRequest"] = request
                write_json(root / "review-findings.json", review)
                _refresh_review_digest(root, adapter)
                if variant != "request-only":
                    adapter_value = read_json(adapter)
                    adapter_value["traceability"]["reviewFindings"][
                        "reviewRequestSha256"
                    ] = (
                        "sha256:" + "f" * 64
                        if variant == "mismatch"
                        else request["requestSha256"]
                    )
                    write_json(adapter, adapter_value)

                rejected = run_cli(adapter, "init", expected=2)

                self.assertIn(expected_error, rejected.stderr)

    def test_strict_fix_requires_handoff_then_same_source_full_regression_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_strict_failed_campaign(root)
            rejected = run_cli(adapter, "retest", expected=2)
            self.assertIn("REVIEW_HANDOFF_REQUIRED", rejected.stderr)
            observed = json_output(run_cli(adapter, "observe-source", expected=0))
            self.assertEqual(
                fix["fixedSourceFingerprint"], observed["sourceFingerprint"]
            )
            pre_audit = json_output(run_cli(adapter, "audit", expected=1))
            self.assertIn("REVIEW_HANDOFF_REQUIRED", pre_audit["rejectionCodes"])

            handoff = write_post_fix_review(root, adapter, fix)
            recorded = json_output(
                run_cli(
                    adapter,
                    "record-review",
                    "--review",
                    str(handoff),
                    expected=0,
                )
            )
            self.assertEqual(
                "resolved",
                recorded["pendingFix"]["reviewHandoff"]["resolutionStates"][RF_ID],
            )
            self.assertEqual("FAILED", recorded["executionStatus"])
            self.assertEqual("INCOMPLETE", recorded["completionStatus"])
            self.assertEqual("narrow", recorded["coverage"]["mode"])
            run_cli(adapter, "retest", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            audit = json_output(run_cli(adapter, "audit", expected=0))
            self.assertTrue(audit["ok"])
            self.assertTrue(audit["traceability"]["reviewHandoffs"][0]["ok"])

    def test_diff_handoff_requires_fresh_trusted_head_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_strict_failed_campaign(
                root,
                request_kind="diff",
            )
            handoff = write_post_fix_review(
                root,
                adapter,
                fix,
                head_identity="head-v2",
            )

            missing = run_cli(
                adapter,
                "record-review",
                "--review",
                str(handoff),
                expected=2,
            )
            self.assertIn("REVIEW_REQUEST_REQUIRED", missing.stderr)
            expected_request = read_json(handoff)["reviewRequest"]
            expected_path = write_json(
                root / "expected-post-fix-review-request.json",
                expected_request,
            )
            recorded = json_output(
                run_cli(
                    adapter,
                    "record-review",
                    "--review",
                    str(handoff),
                    "--expected-review-request",
                    str(expected_path),
                    expected=0,
                )
            )

            initial = recorded["traceSnapshot"]["reviewFindings"]["reviewRequest"]
            persisted = recorded["pendingFix"]["reviewHandoff"]["reviewRequest"]
            self.assertEqual("diff", persisted["target"]["kind"])
            self.assertEqual(
                initial["target"]["baseIdentity"],
                persisted["target"]["baseIdentity"],
            )
            self.assertEqual("head-v2", persisted["target"]["headIdentity"])
            self.assertEqual(
                fix["fixedSourceFingerprint"],
                persisted["target"]["sourceFingerprint"],
            )
            self.assertEqual(
                initial["requestedPaths"],
                persisted["requestedPaths"],
            )
            self.assertNotEqual(
                initial["requestSha256"],
                persisted["requestSha256"],
            )
            self.assertTrue(
                recorded["pendingFix"]["reviewHandoff"]["bindingsVerified"]
            )

    def test_stale_handoff_can_be_explicitly_superseded_and_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, first_fix = prepare_strict_failed_campaign(root)
            first_handoff = write_post_fix_review(root, adapter, first_fix)
            first_recorded = json_output(
                run_cli(
                    adapter,
                    "record-review",
                    "--review",
                    str(first_handoff),
                    expected=0,
                )
            )
            first_fix_id = first_recorded["pendingFix"]["fixId"]

            unchanged = run_cli(
                adapter,
                "supersede-fix",
                "--fix-id",
                first_fix_id,
                expected=2,
            )
            self.assertIn("requires source drift", unchanged.stderr)

            (root / "guardrail-test.txt").write_text(
                "permanent regression guardrail, revised\n",
                encoding="utf-8",
            )
            stale = run_cli(adapter, "retest", expected=2)
            self.assertIn("run supersede-fix", stale.stderr)
            wrong_id = run_cli(
                adapter,
                "supersede-fix",
                "--fix-id",
                "fix-000000000000",
                expected=2,
            )
            self.assertIn("does not match the pending fix", wrong_id.stderr)

            superseded = json_output(
                run_cli(
                    adapter,
                    "supersede-fix",
                    "--fix-id",
                    first_fix_id,
                    expected=0,
                )
            )
            self.assertIsNone(superseded["pendingFix"])
            self.assertEqual("FAILED", superseded["executionStatus"])
            self.assertEqual("INCOMPLETE", superseded["completionStatus"])
            self.assertEqual("narrow", superseded["coverage"]["mode"])
            self.assertEqual(
                superseded["currentSourceFingerprint"],
                superseded["fixes"][0]["supersession"]["sourceFingerprint"],
            )

            second_fix = copy.deepcopy(first_fix)
            second_fix["fixedSourceFingerprint"] = superseded[
                "currentSourceFingerprint"
            ]
            second_fix["changedFiles"] = ["behavior.txt", "guardrail-test.txt"]
            second_fix["rootCauseSource"] = {
                "path": "guardrail-test.txt",
                "lineStart": 1,
                "lineEnd": 1,
            }
            second_fix["fixSummary"] = (
                "Retain the guarded transition with the revised permanent check."
            )
            second_fix_path = write_json(root / "fix-2.json", second_fix)
            second_recorded = json_output(
                run_cli(
                    adapter,
                    "record-fix",
                    "--fix",
                    str(second_fix_path),
                    expected=0,
                )
            )
            second_fix_id = second_recorded["pendingFix"]["fixId"]
            self.assertNotEqual(first_fix_id, second_fix_id)

            second_handoff = write_post_fix_review(
                root,
                adapter,
                second_fix,
                name="review-post-fix-2.json",
            )
            run_cli(
                adapter,
                "record-review",
                "--review",
                str(second_handoff),
                expected=0,
            )
            run_cli(adapter, "retest", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            audit = json_output(run_cli(adapter, "audit", expected=0))
            self.assertTrue(audit["ok"])
            handoffs = audit["traceability"]["reviewHandoffs"]
            self.assertEqual([first_fix_id, second_fix_id], [item["fixId"] for item in handoffs])
            self.assertTrue(handoffs[0]["superseded"])
            self.assertFalse(handoffs[1]["superseded"])
            self.assertTrue(all(item["ok"] for item in handoffs))

    def test_source_drift_before_review_can_supersede_the_pending_fix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, first_fix = prepare_strict_failed_campaign(root)
            pending = json_output(run_cli(adapter, "status", expected=0))[
                "pendingFix"
            ]
            missing_review = run_cli(adapter, "run", expected=2)
            self.assertIn("requires record-review", missing_review.stderr)
            self.assertNotIn("run supersede-fix", missing_review.stderr)
            (root / "guardrail-test.txt").write_text(
                "permanent regression guardrail, revised before Review\n",
                encoding="utf-8",
            )
            superseded = json_output(
                run_cli(
                    adapter,
                    "supersede-fix",
                    "--fix-id",
                    pending["fixId"],
                    expected=0,
                )
            )
            self.assertEqual(
                "source-drift",
                superseded["fixes"][0]["supersession"]["reason"],
            )
            self.assertIsNone(
                superseded["fixes"][0]["supersession"][
                    "reviewManifestSha256"
                ]
            )

            second_fix = copy.deepcopy(first_fix)
            second_fix["fixedSourceFingerprint"] = superseded[
                "currentSourceFingerprint"
            ]
            second_fix["changedFiles"] = ["behavior.txt", "guardrail-test.txt"]
            second_fix["rootCauseSource"] = {
                "path": "guardrail-test.txt",
                "lineStart": 1,
                "lineEnd": 1,
            }
            second_fix_path = write_json(root / "fix-before-review-2.json", second_fix)
            run_cli(
                adapter,
                "record-fix",
                "--fix",
                str(second_fix_path),
                expected=0,
            )
            handoff = write_post_fix_review(
                root,
                adapter,
                second_fix,
                name="review-before-review-2.json",
            )
            run_cli(
                adapter,
                "record-review",
                "--review",
                str(handoff),
                expected=0,
            )
            run_cli(adapter, "retest", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            audit = json_output(run_cli(adapter, "audit", expected=0))
            self.assertTrue(audit["ok"])
            self.assertFalse(
                audit["traceability"]["reviewHandoffs"][0][
                    "historicalHandoffRecorded"
                ]
            )

    def test_manifest_drift_is_revalidated_and_can_be_superseded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, first_fix = prepare_strict_failed_campaign(root)
            first_handoff = write_post_fix_review(root, adapter, first_fix)
            recorded = json_output(
                run_cli(
                    adapter,
                    "record-review",
                    "--review",
                    str(first_handoff),
                    expected=0,
                )
            )
            pending = recorded["pendingFix"]
            still_valid = run_cli(
                adapter,
                "supersede-fix",
                "--fix-id",
                pending["fixId"],
                expected=2,
            )
            self.assertIn("verified stale Review manifest", still_valid.stderr)

            drifted = read_json(first_handoff)
            drifted["findings"][0]["title"] += " drifted"
            write_json(first_handoff, drifted)
            rejected = run_cli(adapter, "retest", expected=2)
            self.assertIn("active Review handoff", rejected.stderr)
            self.assertIn("run supersede-fix", rejected.stderr)

            superseded = json_output(
                run_cli(
                    adapter,
                    "supersede-fix",
                    "--fix-id",
                    pending["fixId"],
                    expected=0,
                )
            )
            self.assertEqual(
                "review-manifest-drift",
                superseded["fixes"][0]["supersession"]["reason"],
            )
            self.assertEqual(
                first_fix["fixedSourceFingerprint"],
                superseded["currentSourceFingerprint"],
            )

            second_fix = copy.deepcopy(first_fix)
            second_fix_path = write_json(root / "fix-manifest-drift-2.json", second_fix)
            run_cli(
                adapter,
                "record-fix",
                "--fix",
                str(second_fix_path),
                expected=0,
            )
            second_handoff = write_post_fix_review(
                root,
                adapter,
                second_fix,
                name="review-manifest-drift-2.json",
            )
            run_cli(
                adapter,
                "record-review",
                "--review",
                str(second_handoff),
                expected=0,
            )
            run_cli(adapter, "retest", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            audit = json_output(run_cli(adapter, "audit", expected=0))
            self.assertTrue(audit["ok"])
            historical = audit["traceability"]["reviewHandoffs"][0]
            self.assertTrue(historical["superseded"])
            self.assertFalse(historical["historicalManifestValid"])

    def test_record_review_rejects_incomplete_wrong_source_and_candidate_drift(self) -> None:
        mutations = (
            (
                "incomplete",
                lambda review: review.update(
                    {
                        "attestation": {
                            **review["attestation"],
                            "outcome": "incomplete",
                            "gaps": [
                                {
                                    "id": "RG-EVIDENCE-001",
                                    "kind": "insufficient-evidence",
                                    "detail": "The required evidence is unavailable",
                                    "neededEvidence": ["A reproducible local trace"],
                                }
                            ],
                        }
                    }
                ),
                "REVIEW_HANDOFF_INCOMPLETE",
            ),
            (
                "wrong-source",
                lambda review: review["attestation"].update(
                    {"sourceFingerprint": "sha256:" + "0" * 64}
                ),
                "REVIEW_HANDOFF_DRIFT",
            ),
            (
                "candidate",
                lambda review: review["findings"][0]["caseCandidate"].update(
                    {"quick": False}
                ),
                "REVIEW_HANDOFF_DRIFT",
            ),
        )
        for label, mutate, expected in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                adapter, fix = prepare_strict_failed_campaign(root)
                handoff = write_post_fix_review(root, adapter, fix, mutate=mutate)
                rejected = run_cli(
                    adapter,
                    "record-review",
                    "--review",
                    str(handoff),
                    expected=2,
                )
                self.assertIn(expected, rejected.stderr)

    def test_handoff_file_drift_fails_final_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_strict_failed_campaign(root)
            handoff = write_post_fix_review(root, adapter, fix)
            run_cli(
                adapter,
                "record-review",
                "--review",
                str(handoff),
                expected=0,
            )
            run_cli(adapter, "retest", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            value = read_json(handoff)
            value["findings"][0]["title"] += " changed"
            write_json(handoff, value)
            audit = json_output(run_cli(adapter, "audit", expected=1))
            self.assertIn("REVIEW_HANDOFF_DRIFT", audit["rejectionCodes"])

    def test_rehashed_handoff_candidate_tamper_fails_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_strict_failed_campaign(root)
            handoff = write_post_fix_review(root, adapter, fix)
            run_cli(
                adapter,
                "record-review",
                "--review",
                str(handoff),
                expected=0,
            )
            journal = root / ".campaign" / "events.jsonl"
            events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
            event = next(
                item for item in events if item["type"] == "review_handoff_recorded"
            )
            event["payload"]["caseCandidateSha256s"][RF_ID] = (
                "sha256:" + "0" * 64
            )
            _write_rehashed_events(root, events)
            rejected = run_cli(adapter, "status", expected=2)
            self.assertIn("case candidates differ", rejected.stderr)

    def test_rehashed_review_request_tamper_fails_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_strict_failed_campaign(root)
            handoff = write_post_fix_review(root, adapter, fix)
            run_cli(
                adapter,
                "record-review",
                "--review",
                str(handoff),
                expected=0,
            )
            journal = root / ".campaign" / "events.jsonl"
            events = [
                json.loads(line)
                for line in journal.read_text(encoding="utf-8").splitlines()
            ]
            event = next(
                item for item in events if item["type"] == "review_handoff_recorded"
            )
            changed = review_request(
                fix["fixedSourceFingerprint"],
                requested_paths=("behavior.txt",),
            )
            event["payload"]["reviewRequest"] = changed
            event["payload"]["reviewRequestSha256"] = changed["requestSha256"]
            _write_rehashed_events(root, events)

            rejected = run_cli(adapter, "status", expected=2)

            self.assertIn("differs from the initialized target", rejected.stderr)

    def test_rehashed_initialized_binding_downgrade_fails_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, _ = prepare_strict_failed_campaign(root)
            journal = root / ".campaign" / "events.jsonl"
            events = [
                json.loads(line)
                for line in journal.read_text(encoding="utf-8").splitlines()
            ]
            initialized = next(
                item for item in events if item["type"] == "campaign_initialized"
            )
            initialized["payload"]["traceSnapshot"]["reviewFindings"][
                "bindingsVerified"
            ] = False
            _write_rehashed_events(root, events)

            rejected = run_cli(adapter, "status", expected=2)

            self.assertIn("pinned Review request binding is invalid", rejected.stderr)

    def test_rehashed_supersession_reason_tamper_fails_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_strict_failed_campaign(root)
            handoff = write_post_fix_review(root, adapter, fix)
            recorded = json_output(
                run_cli(
                    adapter,
                    "record-review",
                    "--review",
                    str(handoff),
                    expected=0,
                )
            )
            value = read_json(handoff)
            value["findings"][0]["title"] += " drifted"
            write_json(handoff, value)
            run_cli(
                adapter,
                "supersede-fix",
                "--fix-id",
                recorded["pendingFix"]["fixId"],
                expected=0,
            )
            journal = root / ".campaign" / "events.jsonl"
            events = [
                json.loads(line)
                for line in journal.read_text(encoding="utf-8").splitlines()
            ]
            event = next(
                item for item in events if item["type"] == "pending_fix_superseded"
            )
            event["payload"]["reason"] = "source-drift"
            _write_rehashed_events(root, events)
            rejected = run_cli(adapter, "status", expected=2)
            self.assertIn("reason does not match", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
