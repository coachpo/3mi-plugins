"""Tests for the read-only semantic-review v1 contract."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "semantic_review.py"
SCHEMA = PLUGIN_ROOT / "references" / "semantic-review-v1.schema.json"
REVIEW_SKILL = PLUGIN_ROOT / "skills" / "review-semantic-risks" / "SKILL.md"
REVIEW_AGENT = (
    PLUGIN_ROOT / "skills" / "review-semantic-risks" / "agents" / "openai.yaml"
)
LOOP_SKILL = (
    PLUGIN_ROOT / "skills" / "run-engineering-control-loop" / "SKILL.md"
)
LOOP_AGENT = (
    PLUGIN_ROOT
    / "skills"
    / "run-engineering-control-loop"
    / "agents"
    / "openai.yaml"
)

SPEC = importlib.util.spec_from_file_location("steward_semantic_review", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import setup guard
    raise RuntimeError("cannot load semantic_review.py")
semantic_review = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = semantic_review
SPEC.loader.exec_module(semantic_review)


INV_ID = "INV-PYTHON-0123456789AB"


def location(path: str = "src/service.py", start: int = 2, end: int = 3) -> dict:
    return {
        "path": path,
        "lineStart": start,
        "lineEnd": end,
        "symbol": "process",
    }


def finding(
    *,
    finding_id: str = "RF-RETRY-001",
    case_id: str = "semantic-retry-001",
    required: bool = True,
    resolution: str = "open",
    runner: dict | None = None,
    blockers: list[str] | None = None,
) -> dict:
    blockers = ["No repository-owned counterexample runner exists"] if blockers is None else blockers
    return {
        "id": finding_id,
        "title": "A replay can apply the state transition twice",
        "required": required,
        "resolutionState": resolution,
        "support": "code-supported",
        "criteriaIds": ["C1"],
        "invariantIds": [INV_ID],
        "evidence": [
            {
                "location": location(),
                "fact": "The replay branch reaches the write before duplicate detection",
            }
        ],
        "triggerPath": [
            {
                "step": 1,
                "location": location(start=2, end=2),
                "condition": "A previously accepted event is replayed",
                "transition": "The event enters process",
            },
            {
                "step": 2,
                "location": location(start=3, end=3),
                "condition": "The event identifier is not checked before the write",
                "transition": "The state mutation is applied a second time",
            },
        ],
        "observableConsequence": "The persisted balance includes the event twice",
        "counterexample": {
            "preconditions": ["A local store contains one accepted event"],
            "steps": ["Replay the same event identifier", "Read the persisted balance"],
            "expectedOutcome": "The balance changes exactly once",
            "riskOutcome": "The balance changes twice",
            "falsifiedWhen": "Evidence shows the second replay is rejected before mutation",
        },
        "caseCandidate": {
            "id": case_id,
            "category": "functional",
            "required": required,
            "platform": "any",
            "dependsOn": [],
            "coversCriteria": ["C1"],
            "coversInvariants": [INV_ID],
            "reviewFindingIds": [finding_id],
            "scenarioTags": ["failure"],
            "quick": True,
            "runner": runner,
            "conversionBlockers": blockers,
        },
    }


def manifest(*findings: dict) -> dict:
    return {
        "schemaId": "steward.semantic-review",
        "schemaVersion": 1,
        "findings": list(findings),
    }


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def attestation(
    root: Path,
    *paths: str,
    outcome: str = "findings",
    gaps: list[dict] | None = None,
) -> dict:
    return {
        "sourceFingerprint": "sha256:" + "1" * 64,
        "goalContractSha256": "sha256:" + "2" * 64,
        "invariantsSha256": "sha256:" + "3" * 64,
        "outcome": outcome,
        "scope": [
            {"path": path, "sha256": file_digest(root / path)}
            for path in paths
        ],
        "gaps": [] if gaps is None else gaps,
    }


def review_request(
    *paths: str,
    kind: str = "source",
    source_fingerprint: str = "sha256:" + "1" * 64,
    base_identity: str = "git:base",
    head_identity: str = "git:head",
) -> dict:
    target = {
        "kind": kind,
        "sourceFingerprint": source_fingerprint,
    }
    if kind == "diff":
        target.update(
            {
                "baseIdentity": base_identity,
                "headIdentity": head_identity,
            }
        )
    core = {
        "target": target,
        "requestedPaths": sorted(paths),
    }
    return {
        **core,
        "requestSha256": semantic_review._review_request_digest(core),
    }


def gap(
    gap_id: str = "RG-EVIDENCE-001",
    *,
    paths: list[str] | None = None,
) -> dict:
    value = {
        "id": gap_id,
        "kind": "insufficient-evidence",
        "detail": "The retry-store behavior is not observable from available artifacts",
        "neededEvidence": ["A repository-owned replay fixture", "Store behavior source"],
    }
    if paths is not None:
        value["paths"] = paths
    return value


def project_fixture(root: Path) -> dict:
    (root / "src").mkdir()
    (root / "tests" / "fixtures").mkdir(parents=True)
    (root / "src" / "service.py").write_text(
        "def process(event):\n"
        "    value = event['value']\n"
        "    return persist(value)\n"
        "\n"
        "def persist(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    (root / "tests" / "run_counterexample.py").write_text(
        "print('counterexample')\n", encoding="utf-8"
    )
    (root / "tests" / "fixtures" / "event.json").write_text(
        '{"value":1}\n', encoding="utf-8"
    )
    return {
        "argv": ["python3", "tests/run_counterexample.py"],
        "cwd": ".",
        "timeoutSeconds": 30,
        "fixture": "tests/fixtures/event.json",
        "externalCapabilities": [],
        "evidence": {
            "requiredFiles": ["proof.json"],
            "nonEmptyFiles": ["proof.json"],
        },
        "sourceEvidence": [
            {
                "location": {
                    "path": "tests/run_counterexample.py",
                    "lineStart": 1,
                    "lineEnd": 1,
                    "symbol": "module",
                },
                "fact": "This project-owned runner exercises the counterexample",
            }
        ],
    }


class SemanticReviewTests(unittest.TestCase):
    def assert_invalid(
        self,
        value: dict,
        code: str | None = None,
        *,
        project_root: Path | None = None,
        verify_baseline: bool = True,
    ) -> None:
        with self.assertRaises(semantic_review.SemanticReviewError) as raised:
            semantic_review.validate_review_manifest(
                value,
                project_root=project_root,
                verify_baseline=verify_baseline,
            )
        if code is not None:
            self.assertEqual(code, raised.exception.code)

    def test_valid_manifest_has_stable_public_api_and_digest(self) -> None:
        contract = semantic_review.validate_review_manifest(manifest(finding()))
        self.assertEqual(("RF-RETRY-001",), contract.required_finding_ids)
        self.assertEqual(
            ("RF-RETRY-001",), semantic_review.required_finding_ids(contract)
        )
        self.assertEqual("open", contract.findings[0].resolution_state)
        self.assertEqual(("C1",), contract.findings[0].criteria_ids)
        self.assertEqual((INV_ID,), contract.findings[0].invariant_ids)
        self.assertEqual(
            "semantic-retry-001", semantic_review.case_candidates(contract)[0]["id"]
        )
        digest = semantic_review.review_manifest_sha256(contract)
        self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(digest, semantic_review.review_manifest_sha256(contract))
        self.assertEqual(
            semantic_review.review_manifest_view(contract),
            json.loads(semantic_review.canonical_review_manifest_bytes(contract)),
        )

    def test_legacy_manifest_digest_remains_byte_for_byte_stable(self) -> None:
        contract = semantic_review.validate_review_manifest(manifest(finding()))
        self.assertFalse(contract.is_attested)
        self.assertFalse(contract.baseline_verified)
        self.assertIsNone(contract.attestation)
        self.assertIsNone(contract.source_fingerprint)
        self.assertEqual((), contract.scope_paths)
        self.assertNotIn("attestation", contract.view)
        self.assertEqual(
            "sha256:29e2629cd8718e5c019f940669bc6f71c286741ad9aa89ad547b4cce63e8abd2",
            semantic_review.review_manifest_sha256(contract),
        )

    def test_attested_findings_expose_authority_and_scope_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            value = manifest(finding())
            value["attestation"] = attestation(root, "src/service.py")
            contract = semantic_review.validate_review_manifest(
                value, project_root=root
            )

            self.assertTrue(contract.is_attested)
            self.assertTrue(contract.scope_verified)
            self.assertFalse(contract.bindings_verified)
            self.assertTrue(contract.baseline_verified)
            self.assertIsNotNone(contract.attestation)
            assert contract.attestation is not None
            self.assertEqual("findings", contract.attestation.outcome)
            self.assertEqual(("src/service.py",), contract.scope_paths)
            self.assertEqual("sha256:" + "1" * 64, contract.source_fingerprint)
            self.assertEqual(
                "sha256:" + "2" * 64,
                contract.attestation.goal_contract_sha256,
            )
            self.assertEqual(
                "sha256:" + "3" * 64,
                contract.attestation.invariants_sha256,
            )
            exposed = contract.attestation.view
            exposed["outcome"] = "incomplete"
            self.assertEqual("findings", contract.attestation.view["outcome"])
            self.assertNotEqual(
                semantic_review.review_manifest_sha256(contract),
                semantic_review.review_manifest_sha256(
                    semantic_review.validate_review_manifest(manifest(finding()))
                ),
            )

    def test_attested_no_findings_and_incomplete_outcomes_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)

            no_findings = manifest()
            no_findings["attestation"] = attestation(
                root,
                "src/service.py",
                outcome="no-findings",
            )
            contract = semantic_review.validate_review_manifest(
                no_findings, project_root=root
            )
            assert contract.attestation is not None
            self.assertEqual("no-findings", contract.attestation.outcome)
            self.assertEqual((), contract.attestation.gaps)

            incomplete = manifest(finding())
            incomplete["attestation"] = attestation(
                root,
                "src/service.py",
                outcome="incomplete",
                gaps=[gap()],
            )
            contract = semantic_review.validate_review_manifest(
                incomplete, project_root=root
            )
            assert contract.attestation is not None
            self.assertEqual("incomplete", contract.attestation.outcome)
            self.assertEqual("RG-EVIDENCE-001", contract.attestation.gaps[0].id)
            self.assertEqual(
                ("A repository-owned replay fixture", "Store behavior source"),
                contract.attestation.gaps[0].needed_evidence,
            )

            incomplete_without_findings = manifest()
            incomplete_without_findings["attestation"] = attestation(
                root,
                "src/service.py",
                outcome="incomplete",
                gaps=[gap()],
            )
            semantic_review.validate_review_manifest(
                incomplete_without_findings, project_root=root
            )

            legacy_unreviewed_scope = manifest()
            legacy_unreviewed_scope["attestation"] = attestation(
                root,
                "src/service.py",
                outcome="incomplete",
                gaps=[
                    {
                        **gap("RG-SCOPE-LEGACY"),
                        "kind": "unreviewed-scope",
                    }
                ],
            )
            semantic_review.validate_review_manifest(
                legacy_unreviewed_scope,
                project_root=root,
            )

    def test_review_request_source_and_diff_bindings_are_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)

            source_request = review_request("src/service.py")
            source_value = manifest(finding())
            source_value["attestation"] = attestation(root, "src/service.py")
            source_value["reviewRequest"] = source_request
            source_contract = semantic_review.validate_review_manifest(
                source_value,
                project_root=root,
                expected_review_request=copy.deepcopy(source_request),
            )
            self.assertIsNotNone(source_contract.review_request)
            self.assertTrue(source_contract.scope_verified)
            self.assertTrue(source_contract.bindings_verified)
            self.assertTrue(source_contract.baseline_verified)
            assert source_contract.review_request is not None
            self.assertEqual("source", source_contract.review_request.target_kind)
            self.assertEqual(
                ("src/service.py",), source_contract.review_request.requested_paths
            )

            diff_request = review_request(
                "src/service.py",
                kind="diff",
                base_identity="git:0123456789abcdef",
                head_identity="worktree:sha256:abcdef",
            )
            diff_value = copy.deepcopy(source_value)
            diff_value["reviewRequest"] = diff_request
            diff_contract = semantic_review.validate_review_manifest(
                diff_value,
                project_root=root,
                expected_review_request=copy.deepcopy(diff_request),
            )
            assert diff_contract.review_request is not None
            self.assertEqual("diff", diff_contract.review_request.target_kind)
            self.assertNotEqual(
                source_contract.review_request.request_sha256,
                diff_contract.review_request.request_sha256,
            )

    def test_public_review_request_builder_canonicalizes_source_and_diff(self) -> None:
        fingerprint = "sha256:" + "4" * 64
        source = semantic_review.build_review_request(
            target_kind="source",
            source_fingerprint=fingerprint,
            requested_paths=("src/z.py", "src/a.py"),
        )
        self.assertEqual(("src/a.py", "src/z.py"), source.requested_paths)
        self.assertEqual(
            {
                "requestSha256": source.request_sha256,
                "requestedPaths": ["src/a.py", "src/z.py"],
                "target": {
                    "kind": "source",
                    "sourceFingerprint": fingerprint,
                },
            },
            semantic_review.review_request_view(source),
        )
        self.assertEqual(
            semantic_review._canonical_json_bytes(source.view),
            semantic_review.canonical_review_request_bytes(source),
        )

        diff = semantic_review.build_review_request(
            target_kind="diff",
            source_fingerprint=fingerprint,
            requested_paths=("src/a.py",),
            base_identity="git:base",
            head_identity="git:head",
        )
        self.assertEqual("diff", diff.target_kind)
        self.assertEqual("git:base", diff.view["target"]["baseIdentity"])
        self.assertEqual("git:head", diff.view["target"]["headIdentity"])
        self.assertNotEqual(source.request_sha256, diff.request_sha256)

    def test_public_review_request_builder_rejects_ambiguous_inputs(self) -> None:
        fingerprint = "sha256:" + "4" * 64
        cases = (
            ({"requested_paths": ("src/a.py", "src/a.py")}, "REVIEW_SCHEMA"),
            ({"requested_paths": ("/src/a.py",)}, "REVIEW_PATH"),
            ({"requested_paths": ("src/../a.py",)}, "REVIEW_PATH"),
            ({"requested_paths": ("src\\a.py",)}, "REVIEW_PATH"),
            ({"requested_paths": (".",)}, "REVIEW_PATH"),
            ({"requested_paths": ()}, "REVIEW_SCHEMA"),
        )
        for override, expected_code in cases:
            with self.subTest(override=override), self.assertRaises(
                semantic_review.SemanticReviewError
            ) as raised:
                semantic_review.build_review_request(
                    target_kind="source",
                    source_fingerprint=fingerprint,
                    requested_paths=override["requested_paths"],
                )
            self.assertEqual(expected_code, raised.exception.code)

        for kwargs in (
            {
                "target_kind": "source",
                "base_identity": "git:base",
            },
            {
                "target_kind": "diff",
                "base_identity": "git:base",
            },
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(
                semantic_review.SemanticReviewError
            ) as raised:
                semantic_review.build_review_request(
                    source_fingerprint=fingerprint,
                    requested_paths=("src/a.py",),
                    **kwargs,
                )
            self.assertEqual("REVIEW_REQUEST", raised.exception.code)

    def test_review_request_rejects_untrusted_or_inconsistent_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            request = review_request("src/service.py")
            value = manifest(finding())
            value["attestation"] = attestation(root, "src/service.py")
            value["reviewRequest"] = copy.deepcopy(request)

            missing = copy.deepcopy(value)
            del missing["reviewRequest"]
            with self.assertRaises(semantic_review.SemanticReviewError) as raised:
                semantic_review.validate_review_manifest(
                    missing,
                    project_root=root,
                    expected_review_request=request,
                )
            self.assertEqual("REVIEW_REQUEST_REQUIRED", raised.exception.code)

            mismatched = review_request(
                "src/service.py",
                kind="diff",
                base_identity="git:other",
                head_identity="git:head",
            )
            with self.assertRaises(semantic_review.SemanticReviewError) as raised:
                semantic_review.validate_review_manifest(
                    value,
                    project_root=root,
                    expected_review_request=mismatched,
                )
            self.assertEqual("REVIEW_REQUEST_MISMATCH", raised.exception.code)

            bad_digest = copy.deepcopy(value)
            bad_digest["reviewRequest"]["requestSha256"] = "sha256:" + "f" * 64
            self.assert_invalid(
                bad_digest,
                "REVIEW_REQUEST_DIGEST",
                project_root=root,
            )

            wrong_source = copy.deepcopy(value)
            wrong_source["reviewRequest"] = review_request(
                "src/service.py",
                source_fingerprint="sha256:" + "9" * 64,
            )
            self.assert_invalid(
                wrong_source,
                "REVIEW_REQUEST_SOURCE",
                project_root=root,
            )

            unattested = manifest(finding())
            unattested["reviewRequest"] = request
            self.assert_invalid(
                unattested,
                "REVIEW_REQUEST_ATTESTATION",
                project_root=root,
            )

    def test_review_request_requires_requested_scope_or_unreviewed_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            request = review_request(
                "src/service.py",
                "tests/run_counterexample.py",
            )
            incomplete = manifest()
            incomplete["attestation"] = attestation(
                root,
                "src/service.py",
                outcome="no-findings",
            )
            incomplete["reviewRequest"] = request
            self.assert_invalid(
                incomplete,
                "REVIEW_REQUEST_SCOPE",
                project_root=root,
            )

            wrong_gap = copy.deepcopy(incomplete)
            wrong_gap["attestation"]["outcome"] = "incomplete"
            wrong_gap["attestation"]["gaps"] = [gap()]
            self.assert_invalid(
                wrong_gap,
                "REVIEW_REQUEST_SCOPE",
                project_root=root,
            )

            missing_gap_paths = copy.deepcopy(wrong_gap)
            missing_gap_paths["attestation"]["gaps"][0]["kind"] = (
                "unreviewed-scope"
            )
            self.assert_invalid(
                missing_gap_paths,
                "REVIEW_REQUEST_SCOPE",
                project_root=root,
            )

            with_gap = copy.deepcopy(incomplete)
            with_gap["attestation"]["outcome"] = "incomplete"
            with_gap["attestation"]["gaps"] = [
                {
                    **gap("RG-SCOPE-001"),
                    "kind": "unreviewed-scope",
                    "detail": "The requested runner path was not reviewed",
                    "neededEvidence": ["Review tests/run_counterexample.py"],
                    "paths": ["tests/run_counterexample.py"],
                }
            ]
            contract = semantic_review.validate_review_manifest(
                with_gap,
                project_root=root,
            )
            assert contract.attestation is not None
            self.assertEqual("incomplete", contract.attestation.outcome)

            split_gaps = copy.deepcopy(incomplete)
            split_gaps["reviewRequest"] = review_request(
                "src/service.py",
                "tests/fixtures/event.json",
                "tests/run_counterexample.py",
            )
            split_gaps["attestation"]["outcome"] = "incomplete"
            split_gaps["attestation"]["gaps"] = [
                {
                    **gap("RG-SCOPE-001"),
                    "kind": "unreviewed-scope",
                    "paths": ["tests/run_counterexample.py"],
                },
                {
                    **gap("RG-SCOPE-002"),
                    "kind": "unreviewed-scope",
                    "paths": ["tests/fixtures/event.json"],
                },
            ]
            semantic_review.validate_review_manifest(
                split_gaps,
                project_root=root,
            )

            wrong_paths = copy.deepcopy(with_gap)
            wrong_paths["attestation"]["gaps"][0]["paths"] = ["src/service.py"]
            self.assert_invalid(
                wrong_paths,
                "REVIEW_REQUEST_SCOPE",
                project_root=root,
            )

            complete = copy.deepcopy(incomplete)
            complete["attestation"] = attestation(
                root,
                "src/service.py",
                "tests/run_counterexample.py",
                outcome="no-findings",
            )
            contract = semantic_review.validate_review_manifest(
                complete,
                project_root=root,
                expected_review_request=request,
            )
            assert contract.attestation is not None
            self.assertEqual("no-findings", contract.attestation.outcome)
            self.assertTrue(contract.baseline_verified)

            complete_with_gap = copy.deepcopy(complete)
            complete_with_gap["attestation"]["outcome"] = "incomplete"
            complete_with_gap["attestation"]["gaps"] = [
                {
                    **gap("RG-SCOPE-EXTRA"),
                    "kind": "unreviewed-scope",
                    "paths": ["tests/run_counterexample.py"],
                }
            ]
            self.assert_invalid(
                complete_with_gap,
                "REVIEW_REQUEST_SCOPE",
                project_root=root,
            )

    def test_attestation_outcome_is_derived_from_findings_and_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            invalid_values = []
            wrong_findings = manifest(finding())
            wrong_findings["attestation"] = attestation(
                root, "src/service.py", outcome="no-findings"
            )
            invalid_values.append(wrong_findings)
            wrong_empty = manifest()
            wrong_empty["attestation"] = attestation(
                root, "src/service.py", outcome="findings"
            )
            invalid_values.append(wrong_empty)
            wrong_incomplete = manifest()
            wrong_incomplete["attestation"] = attestation(
                root, "src/service.py", outcome="incomplete"
            )
            invalid_values.append(wrong_incomplete)
            hidden_gap = manifest(finding())
            hidden_gap["attestation"] = attestation(
                root,
                "src/service.py",
                outcome="findings",
                gaps=[gap()],
            )
            invalid_values.append(hidden_gap)
            for value in invalid_values:
                with self.subTest(outcome=value["attestation"]["outcome"]):
                    self.assert_invalid(value, "REVIEW_SCHEMA", project_root=root)

    def test_attestation_hashes_use_strict_authority_digest_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            for field, invalid_digest in (
                ("sourceFingerprint", "1" * 64),
                ("goalContractSha256", "sha256:" + "A" * 64),
                ("invariantsSha256", "sha512:" + "3" * 64),
            ):
                with self.subTest(field=field):
                    value = manifest(finding())
                    value["attestation"] = attestation(root, "src/service.py")
                    value["attestation"][field] = invalid_digest
                    self.assert_invalid(value, "REVIEW_SCHEMA", project_root=root)

    def test_attestation_scope_and_gaps_are_unique_and_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            value = manifest()
            second_gap = {
                **gap("RG-SCOPE-002"),
                "kind": "unreviewed-scope",
                "detail": "A generated integration subtree was not available",
                "neededEvidence": ["Generated integration subtree"],
            }
            value["attestation"] = attestation(
                root,
                "tests/run_counterexample.py",
                "src/service.py",
                outcome="incomplete",
                gaps=[second_gap, gap()],
            )
            contract = semantic_review.validate_review_manifest(
                value, project_root=root
            )
            assert contract.attestation is not None
            self.assertEqual(
                ("src/service.py", "tests/run_counterexample.py"),
                contract.attestation.scope_paths,
            )
            self.assertEqual(
                ("RG-EVIDENCE-001", "RG-SCOPE-002"),
                tuple(item.id for item in contract.attestation.gaps),
            )
            permuted = copy.deepcopy(value)
            permuted["attestation"]["scope"].reverse()
            permuted["attestation"]["gaps"].reverse()
            permuted_contract = semantic_review.validate_review_manifest(
                permuted, project_root=root
            )
            self.assertEqual(
                semantic_review.review_manifest_sha256(contract),
                semantic_review.review_manifest_sha256(permuted_contract),
            )

            duplicate_gap = copy.deepcopy(value)
            duplicate_gap["attestation"]["gaps"].append(gap())
            self.assert_invalid(duplicate_gap, "REVIEW_ID", project_root=root)

            duplicate_needed = copy.deepcopy(value)
            duplicate_needed["attestation"]["gaps"][0]["neededEvidence"] = [
                "same",
                "same",
            ]
            self.assert_invalid(duplicate_needed, "REVIEW_SCHEMA", project_root=root)

            bad_kind = copy.deepcopy(value)
            bad_kind["attestation"]["gaps"][0]["kind"] = "unknown"
            self.assert_invalid(bad_kind, "REVIEW_SCHEMA", project_root=root)

            paths_on_other_kind = copy.deepcopy(value)
            paths_on_other_kind["attestation"]["gaps"][0]["kind"] = (
                "insufficient-evidence"
            )
            paths_on_other_kind["attestation"]["gaps"][0]["paths"] = [
                "src/service.py"
            ]
            self.assert_invalid(
                paths_on_other_kind,
                "REVIEW_GAP",
                project_root=root,
            )

            multiline = copy.deepcopy(value)
            multiline["attestation"]["gaps"][0]["detail"] = "line one\nline two"
            self.assert_invalid(multiline, "REVIEW_SCHEMA", project_root=root)

    def test_attestation_detects_source_drift_and_can_parse_pinned_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            value = manifest(finding())
            value["attestation"] = attestation(root, "src/service.py")
            path = root / "review.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            original = semantic_review.load_review_manifest(path, project_root=root)

            (root / "src" / "service.py").write_text(
                "def replaced():\n    return True\n",
                encoding="utf-8",
            )
            with self.assertRaises(semantic_review.SemanticReviewError) as raised:
                semantic_review.load_review_manifest(path, project_root=root)
            self.assertEqual("REVIEW_BASELINE_DRIFT", raised.exception.code)

            pinned = semantic_review.load_review_manifest(
                path,
                project_root=root,
                verify_baseline=False,
            )
            self.assertFalse(pinned.baseline_verified)
            self.assertEqual(
                semantic_review.review_manifest_sha256(original),
                semantic_review.review_manifest_sha256(pinned),
            )

            (root / "src" / "service.py").unlink()
            pinned_after_delete = semantic_review.load_review_manifest(
                path,
                project_root=root,
                verify_baseline=False,
            )
            self.assertEqual(original.view, pinned_after_delete.view)

    def test_attested_location_bounds_use_the_hashed_content_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            source = root / "src" / "service.py"
            attested_bytes = source.read_bytes()
            temporary_bytes = attested_bytes + b"temporary_line = True\n"

            value = manifest(finding())
            value["findings"][0]["evidence"][0]["location"].update(
                {"lineStart": 7, "lineEnd": 7}
            )
            value["attestation"] = attestation(root, "src/service.py")

            original_reader = semantic_review._read_regular_file
            observations: list[str] = []

            def read_with_temporary_location_content(
                path: Path,
                **kwargs: object,
            ) -> bytes:
                if Path(path).resolve() != source.resolve():
                    return original_reader(path, **kwargs)
                label = str(kwargs.get("label", ""))
                if ".attestation.scope[" in label:
                    source.write_bytes(attested_bytes)
                    observations.append("scope")
                    content = original_reader(path, **kwargs)
                    if observations == ["scope"]:
                        source.write_bytes(temporary_bytes)
                    return content
                observations.append("location")
                return original_reader(path, **kwargs)

            try:
                with mock.patch.object(
                    semantic_review,
                    "_read_regular_file",
                    side_effect=read_with_temporary_location_content,
                ), self.assertRaises(semantic_review.SemanticReviewError) as raised:
                    semantic_review.validate_review_manifest(value, project_root=root)
            finally:
                source.write_bytes(attested_bytes)

            self.assertEqual("REVIEW_LOCATION", raised.exception.code)
            self.assertEqual(["scope"], observations)
            self.assertEqual(attested_bytes, source.read_bytes())

    def test_attested_snapshot_retains_only_line_metadata_not_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = project_fixture(root)
            binary_fixture = root / "tests" / "fixtures" / "opaque.bin"
            binary_fixture.write_bytes(b"\xff\xfe\x00binary-fixture")
            runner["fixture"] = "tests/fixtures/opaque.bin"

            value = manifest(finding(runner=runner, blockers=[]))
            value["attestation"] = attestation(
                root,
                "src/service.py",
                "tests/run_counterexample.py",
                "tests/fixtures/opaque.bin",
            )
            parsed_findings = (
                semantic_review._finding(
                    value["findings"][0],
                    "review manifest.findings[0]",
                    None,
                ),
            )
            snapshots: dict[
                str, semantic_review._AttestedLocationSnapshot
            ] = {}
            semantic_review._attestation(
                value["attestation"],
                "review manifest.attestation",
                parsed_findings,
                None,
                root,
                location_snapshots=snapshots,
            )

            self.assertEqual(
                {"src/service.py", "tests/run_counterexample.py"},
                set(snapshots),
            )
            self.assertTrue(all(item.utf8_valid for item in snapshots.values()))
            self.assertTrue(all(item.line_count > 0 for item in snapshots.values()))
            self.assertFalse(
                any(isinstance(item, (bytes, bytearray)) for item in snapshots.values())
            )
            semantic_review.validate_review_manifest(value, project_root=root)

    @unittest.skipIf(not hasattr(Path, "symlink_to"), "symlinks unsupported")
    def test_attestation_scope_rejects_symlinked_baseline_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            linked = root / "src" / "linked.py"
            try:
                linked.symlink_to(root / "src" / "service.py")
            except OSError:
                return
            value = manifest()
            value["attestation"] = attestation(
                root,
                "src/linked.py",
                outcome="no-findings",
            )
            self.assert_invalid(
                value,
                "REVIEW_BASELINE_DRIFT",
                project_root=root,
            )

    def test_empty_manifest_is_valid_and_does_not_claim_safety(self) -> None:
        contract = semantic_review.validate_review_manifest(manifest())
        self.assertEqual((), contract.findings)
        self.assertEqual((), contract.required_finding_ids)
        self.assertEqual([], semantic_review.review_manifest_view(contract)["findings"])

    def test_canonical_view_sorts_findings_and_unordered_id_sets(self) -> None:
        second = finding(
            finding_id="RF-AUTH-001",
            case_id="semantic-auth-001",
            required=False,
            resolution="resolved",
        )
        second["criteriaIds"] = ["C2", "C1"]
        second["caseCandidate"]["coversCriteria"] = ["C2", "C1"]
        first = finding()
        contract = semantic_review.validate_review_manifest(manifest(first, second))
        view = semantic_review.review_manifest_view(contract)
        self.assertEqual(
            ["RF-AUTH-001", "RF-RETRY-001"],
            [item["id"] for item in view["findings"]],
        )
        self.assertEqual(["C1", "C2"], view["findings"][0]["criteriaIds"])
        reversed_contract = semantic_review.validate_review_manifest(
            manifest(second, first)
        )
        self.assertEqual(
            semantic_review.review_manifest_sha256(contract),
            semantic_review.review_manifest_sha256(reversed_contract),
        )

    def test_evidence_symbol_participates_in_canonical_sorting(self) -> None:
        first = finding()
        first["evidence"] = [
            {
                "location": location(),
                "fact": "The same source range supports both symbol-specific facts",
            },
            {
                "location": {**location(), "symbol": "apply"},
                "fact": "The same source range supports both symbol-specific facts",
            },
        ]
        reversed_evidence = copy.deepcopy(first)
        reversed_evidence["evidence"].reverse()

        contract = semantic_review.validate_review_manifest(manifest(first))
        permuted = semantic_review.validate_review_manifest(
            manifest(reversed_evidence)
        )
        self.assertEqual(
            semantic_review.review_manifest_sha256(contract),
            semantic_review.review_manifest_sha256(permuted),
        )
        self.assertEqual(
            ["apply", "process"],
            [
                item["location"]["symbol"]
                for item in semantic_review.review_manifest_view(contract)["findings"][0][
                    "evidence"
                ]
            ],
        )

    def test_exposed_manifest_view_cannot_change_the_validated_digest(self) -> None:
        contract = semantic_review.validate_review_manifest(manifest(finding()))
        original_digest = semantic_review.review_manifest_sha256(contract)
        exposed = contract.view
        exposed["schemaVersion"] = 999
        exposed["findings"][0]["title"] = "tampered after validation"

        self.assertEqual(original_digest, semantic_review.review_manifest_sha256(contract))
        fresh = semantic_review.review_manifest_view(contract)
        self.assertEqual(1, fresh["schemaVersion"])
        self.assertEqual(
            "A replay can apply the state transition twice",
            fresh["findings"][0]["title"],
        )

    def test_all_resolution_states_still_preserve_required_ids(self) -> None:
        values = [
            finding(
                finding_id="RF-STATE-" + state.upper().replace("_", "-"),
                case_id="case-" + state,
                resolution=state,
            )
            for state in ("open", "resolved", "invalidated")
        ]
        contract = semantic_review.validate_review_manifest(manifest(*values))
        self.assertEqual(3, len(contract.required_finding_ids))
        self.assertEqual(
            {"open", "resolved", "invalidated"},
            {item.resolution_state for item in contract.findings},
        )

    def test_rejects_unknown_missing_and_wrong_scalar_fields(self) -> None:
        base = manifest(finding())
        mutations: list[tuple[dict, str]] = []
        unknown_root = copy.deepcopy(base)
        unknown_root["unknown"] = True
        mutations.append((unknown_root, "REVIEW_SCHEMA"))
        unknown_finding = copy.deepcopy(base)
        unknown_finding["findings"][0]["severity"] = "high"
        mutations.append((unknown_finding, "REVIEW_SCHEMA"))
        missing_trigger = copy.deepcopy(base)
        del missing_trigger["findings"][0]["triggerPath"]
        mutations.append((missing_trigger, "REVIEW_SCHEMA"))
        wrong_required = copy.deepcopy(base)
        wrong_required["findings"][0]["required"] = 1
        mutations.append((wrong_required, "REVIEW_SCHEMA"))
        wrong_version = copy.deepcopy(base)
        wrong_version["schemaVersion"] = True
        mutations.append((wrong_version, "REVIEW_SCHEMA"))
        bad_support = copy.deepcopy(base)
        bad_support["findings"][0]["support"] = "certain"
        mutations.append((bad_support, "REVIEW_SCHEMA"))
        for value, code in mutations:
            with self.subTest(value=value):
                self.assert_invalid(value, code)

    def test_all_forbidden_single_line_separators_are_rejected(self) -> None:
        for character in (
            "\x00",
            "\n",
            "\v",
            "\f",
            "\r",
            "\x1c",
            "\x1d",
            "\x1e",
            "\x85",
            "\u2028",
            "\u2029",
        ):
            with self.subTest(character=repr(character)):
                value = manifest(finding())
                value["findings"][0]["observableConsequence"] = (
                    "wrong" + character + "result"
                )
                self.assert_invalid(value, "REVIEW_SCHEMA")

    def test_ids_are_strict_unique_and_cross_linked(self) -> None:
        base = manifest(finding())
        mutations = []
        bad_rf = copy.deepcopy(base)
        bad_rf["findings"][0]["id"] = "rf-1"
        mutations.append(bad_rf)
        bad_c = copy.deepcopy(base)
        bad_c["findings"][0]["criteriaIds"] = ["C0"]
        mutations.append(bad_c)
        bad_inv = copy.deepcopy(base)
        bad_inv["findings"][0]["invariantIds"] = ["INV-UNKNOWN"]
        mutations.append(bad_inv)
        drifted_coverage = copy.deepcopy(base)
        drifted_coverage["findings"][0]["caseCandidate"]["coversCriteria"] = []
        mutations.append(drifted_coverage)
        wrong_finding_link = copy.deepcopy(base)
        wrong_finding_link["findings"][0]["caseCandidate"]["reviewFindingIds"] = [
            "RF-OTHER-001"
        ]
        mutations.append(wrong_finding_link)
        duplicate = manifest(finding(), finding(case_id="other-case"))
        mutations.append(duplicate)
        duplicate_case = manifest(
            finding(), finding(finding_id="RF-OTHER-001")
        )
        mutations.append(duplicate_case)
        for value in mutations:
            with self.subTest(value=value):
                self.assert_invalid(value)

    def test_case_candidate_dependencies_must_exist_and_be_acyclic(self) -> None:
        unknown = manifest(finding())
        unknown["findings"][0]["caseCandidate"]["dependsOn"] = ["missing-case"]
        self.assert_invalid(unknown, "REVIEW_CASE")

        first = finding()
        second = finding(
            finding_id="RF-AUTH-001",
            case_id="semantic-auth-001",
            required=False,
        )
        first["caseCandidate"]["dependsOn"] = ["semantic-auth-001"]
        second["caseCandidate"]["dependsOn"] = ["semantic-retry-001"]
        self.assert_invalid(manifest(first, second), "REVIEW_CASE")

        second["caseCandidate"]["dependsOn"] = []
        contract = semantic_review.validate_review_manifest(manifest(first, second))
        candidates = {
            item["id"]: item for item in semantic_review.case_candidates(contract)
        }
        self.assertEqual(
            ["semantic-auth-001"], candidates["semantic-retry-001"]["dependsOn"]
        )

    def test_trigger_and_counterexample_are_falsifiable_structures(self) -> None:
        base = manifest(finding())
        skipped_step = copy.deepcopy(base)
        skipped_step["findings"][0]["triggerPath"][1]["step"] = 3
        self.assert_invalid(skipped_step, "REVIEW_TRIGGER")

        empty_steps = copy.deepcopy(base)
        empty_steps["findings"][0]["counterexample"]["steps"] = []
        self.assert_invalid(empty_steps, "REVIEW_COUNTEREXAMPLE")

        missing_falsifier = copy.deepcopy(base)
        del missing_falsifier["findings"][0]["counterexample"]["falsifiedWhen"]
        self.assert_invalid(missing_falsifier, "REVIEW_SCHEMA")

    def test_exact_locations_are_project_relative_and_in_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            semantic_review.validate_review_manifest(
                manifest(finding()), project_root=root
            )

            outside = copy.deepcopy(manifest(finding()))
            outside["findings"][0]["evidence"][0]["location"]["path"] = "../outside.py"
            self.assert_invalid(outside, "REVIEW_PATH", project_root=root)

            too_far = copy.deepcopy(manifest(finding()))
            too_far["findings"][0]["evidence"][0]["location"]["lineEnd"] = 99
            self.assert_invalid(too_far, "REVIEW_LOCATION", project_root=root)

            reversed_lines = copy.deepcopy(manifest(finding()))
            reversed_lines["findings"][0]["evidence"][0]["location"].update(
                {"lineStart": 4, "lineEnd": 2}
            )
            self.assert_invalid(reversed_lines, "REVIEW_LOCATION", project_root=root)

            with mock.patch.object(
                semantic_review, "MAX_EVIDENCE_SOURCE_BYTES", 8
            ), self.assertRaises(semantic_review.SemanticReviewError) as raised:
                semantic_review.validate_review_manifest(
                    manifest(finding()), project_root=root
                )
            self.assertEqual("REVIEW_SIZE", raised.exception.code)

    def test_attested_references_and_fixture_must_belong_to_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = project_fixture(root)
            base = manifest(finding(runner=runner, blockers=[]))
            all_paths = (
                "src/service.py",
                "tests/run_counterexample.py",
                "tests/fixtures/event.json",
            )
            base["attestation"] = attestation(root, *all_paths)
            semantic_review.validate_review_manifest(base, project_root=root)

            for omitted in all_paths:
                with self.subTest(omitted=omitted):
                    value = copy.deepcopy(base)
                    value["attestation"]["scope"] = [
                        item
                        for item in value["attestation"]["scope"]
                        if item["path"] != omitted
                    ]
                    self.assert_invalid(value, "REVIEW_TRACE", project_root=root)

            duplicate = copy.deepcopy(base)
            duplicate["attestation"]["scope"].append(
                copy.deepcopy(duplicate["attestation"]["scope"][0])
            )
            self.assert_invalid(duplicate, "REVIEW_PATH")

            missing_file = copy.deepcopy(base)
            missing_file["attestation"]["scope"][0]["path"] = "src/missing.py"
            self.assert_invalid(
                missing_file, "REVIEW_BASELINE_DRIFT", project_root=root
            )

            stale_without_io = copy.deepcopy(base)
            stale_without_io["attestation"]["scope"] = [
                item
                for item in stale_without_io["attestation"]["scope"]
                if item["path"] != "src/service.py"
            ]
            self.assert_invalid(
                stale_without_io,
                "REVIEW_TRACE",
                project_root=root,
                verify_baseline=False,
            )

    def test_relative_paths_are_normalized_and_only_cwd_allows_dot(self) -> None:
        for invalid_path in ("a//b", "./a", "."):
            with self.subTest(field="location.path", value=invalid_path):
                value = manifest(finding())
                value["findings"][0]["evidence"][0]["location"]["path"] = invalid_path
                self.assert_invalid(value, "REVIEW_PATH")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = project_fixture(root)
            semantic_review.validate_review_manifest(
                manifest(finding(runner=runner, blockers=[])), project_root=root
            )
            for invalid_cwd in ("a//b", "./a"):
                with self.subTest(field="runner.cwd", value=invalid_cwd):
                    value = manifest(finding(runner=copy.deepcopy(runner), blockers=[]))
                    value["findings"][0]["caseCandidate"]["runner"]["cwd"] = invalid_cwd
                    self.assert_invalid(value, "REVIEW_PATH", project_root=root)

            dot_fixture = manifest(
                finding(runner=copy.deepcopy(runner), blockers=[])
            )
            dot_fixture["findings"][0]["caseCandidate"]["runner"]["fixture"] = "."
            self.assert_invalid(dot_fixture, "REVIEW_PATH", project_root=root)

    @unittest.skipIf(not hasattr(Path, "symlink_to"), "symlinks unsupported")
    def test_evidence_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            (root / "src" / "linked.py").symlink_to(root / "src" / "service.py")
            value = manifest(finding())
            value["findings"][0]["evidence"][0]["location"]["path"] = "src/linked.py"
            self.assert_invalid(value, "REVIEW_PATH", project_root=root)

    def test_candidate_without_runner_requires_explicit_blocker(self) -> None:
        value = manifest(finding(blockers=[]))
        self.assert_invalid(value, "REVIEW_CASE")

        contract = semantic_review.validate_review_manifest(manifest(finding()))
        candidate = semantic_review.case_candidates(contract)[0]
        self.assertIsNone(candidate["runner"])
        self.assertNotIn("argv", candidate)
        self.assertEqual(
            ["No repository-owned counterexample runner exists"],
            candidate["conversionBlockers"],
        )

    def test_repository_evidenced_runner_is_valid_and_blockers_are_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = project_fixture(root)
            value = manifest(finding(runner=runner, blockers=[]))
            contract = semantic_review.validate_review_manifest(
                value, project_root=root
            )
            candidate = semantic_review.case_candidates(contract)[0]
            self.assertEqual(["python3", "tests/run_counterexample.py"], candidate["runner"]["argv"])
            self.assertEqual([], candidate["conversionBlockers"])

            both = manifest(finding(runner=runner, blockers=["invented blocker"]))
            self.assert_invalid(both, "REVIEW_CASE", project_root=root)

            missing_fixture = copy.deepcopy(value)
            missing_fixture["findings"][0]["caseCandidate"]["runner"]["fixture"] = "tests/fixtures/missing.json"
            self.assert_invalid(missing_fixture, "REVIEW_PATH", project_root=root)

            secret = copy.deepcopy(value)
            secret["findings"][0]["caseCandidate"]["runner"]["argv"] = [
                "python3",
                "--token",
                "not-for-a-manifest",
            ]
            self.assert_invalid(secret, "REVIEW_SECRET", project_root=root)

            repeated_argv = copy.deepcopy(value)
            repeated_argv["findings"][0]["caseCandidate"]["runner"]["argv"] = [
                "python3",
                "tests/run_counterexample.py",
                "tests/run_counterexample.py",
            ]
            contract = semantic_review.validate_review_manifest(
                repeated_argv, project_root=root
            )
            self.assertEqual(
                repeated_argv["findings"][0]["caseCandidate"]["runner"]["argv"],
                semantic_review.case_candidates(contract)[0]["runner"]["argv"],
            )

    def test_runner_argv_project_paths_require_existing_source_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = project_fixture(root)

            unproven = copy.deepcopy(runner)
            unproven["sourceEvidence"] = [
                {
                    "location": location(),
                    "fact": "This source does not prove the counterexample runner",
                }
            ]
            self.assert_invalid(
                manifest(finding(runner=unproven, blockers=[])),
                "REVIEW_CASE",
                project_root=root,
            )

            missing = copy.deepcopy(runner)
            missing["argv"] = ["python3", "tests/missing_counterexample.py"]
            self.assert_invalid(
                manifest(finding(runner=missing, blockers=[])),
                "REVIEW_CASE",
                project_root=root,
            )

            cwd_relative = copy.deepcopy(runner)
            cwd_relative["cwd"] = "tests"
            cwd_relative["argv"] = ["python3", "run_counterexample.py"]
            contract = semantic_review.validate_review_manifest(
                manifest(finding(runner=cwd_relative, blockers=[])),
                project_root=root,
            )
            self.assertEqual(
                ["python3", "run_counterexample.py"],
                semantic_review.case_candidates(contract)[0]["runner"]["argv"],
            )

            project_executable = copy.deepcopy(runner)
            project_executable["argv"] = ["./tests/run_counterexample.py"]
            semantic_review.validate_review_manifest(
                manifest(finding(runner=project_executable, blockers=[])),
                project_root=root,
            )
            unproven_executable = copy.deepcopy(project_executable)
            unproven_executable["sourceEvidence"] = [
                {
                    "location": location(),
                    "fact": "This source does not prove the project executable",
                }
            ]
            self.assert_invalid(
                manifest(finding(runner=unproven_executable, blockers=[])),
                "REVIEW_CASE",
                project_root=root,
            )

            absolute_project_input = copy.deepcopy(runner)
            absolute_project_input["argv"] = [
                "/usr/bin/python3",
                str((root / "tests" / "run_counterexample.py").resolve()),
            ]
            semantic_review.validate_review_manifest(
                manifest(finding(runner=absolute_project_input, blockers=[])),
                project_root=root,
            )
            unproven_absolute = copy.deepcopy(absolute_project_input)
            unproven_absolute["sourceEvidence"] = [
                {
                    "location": location(),
                    "fact": "This source does not prove the absolute project input",
                }
            ]
            self.assert_invalid(
                manifest(finding(runner=unproven_absolute, blockers=[])),
                "REVIEW_CASE",
                project_root=root,
            )

            bare_commands = copy.deepcopy(runner)
            bare_commands["argv"] = [
                "python3",
                "-m",
                "pytest",
                "-k",
                "process",
            ]
            semantic_review.validate_review_manifest(
                manifest(finding(runner=bare_commands, blockers=[])),
                project_root=root,
            )

            inline_commands = (
                ["python3", "-c", "open('tests/not-a-runner.py')"],
                ["node", "--eval", "require('./tests/not-a-runner.js')"],
                ["ruby", "-e", "File.read('tests/not-a-runner.rb')"],
                ["perl", "-e", "open my $fh, '<', 'tests/not-a-runner.pl'"],
                ["bun", "-e", "await Bun.file('tests/not-a-runner.ts').text()"],
                *(
                    [shell, "-c", "cat tests/not-a-runner.txt"]
                    for shell in ("sh", "bash", "dash", "zsh", "ksh", "fish")
                ),
            )
            for inline_argv in inline_commands:
                with self.subTest(inline_executable=inline_argv[0]):
                    inline_code = copy.deepcopy(runner)
                    inline_code["argv"] = inline_argv
                    semantic_review.validate_review_manifest(
                        manifest(finding(runner=inline_code, blockers=[])),
                        project_root=root,
                    )

            config_argument = copy.deepcopy(runner)
            config_argument["argv"] = [
                "tests/run_counterexample.py",
                "-c",
                "tests/fixtures/event.json",
            ]
            self.assert_invalid(
                manifest(finding(runner=config_argument, blockers=[])),
                "REVIEW_CASE",
                project_root=root,
            )
            config_argument["sourceEvidence"].append(
                {
                    "location": {
                        "path": "tests/fixtures/event.json",
                        "lineStart": 1,
                        "lineEnd": 1,
                    },
                    "fact": "The non-interpreter -c option consumes this config file",
                }
            )
            semantic_review.validate_review_manifest(
                manifest(finding(runner=config_argument, blockers=[])),
                project_root=root,
            )

            for name, token in (
                ("config.json", "config.json"),
                ("Makefile", "Makefile"),
                ("args.txt", "@args.txt"),
                ("options.json", "--config=options.json"),
            ):
                with self.subTest(bare_existing_project_input=token):
                    project_input = root / name
                    project_input.write_text("bound input\n", encoding="utf-8")
                    unbound = copy.deepcopy(runner)
                    unbound["argv"] = [
                        "python3",
                        "tests/run_counterexample.py",
                        token,
                    ]
                    self.assert_invalid(
                        manifest(finding(runner=unbound, blockers=[])),
                        "REVIEW_CASE",
                        project_root=root,
                    )
                    unbound["sourceEvidence"].append(
                        {
                            "location": {
                                "path": name,
                                "lineStart": 1,
                                "lineEnd": 1,
                            },
                            "fact": "The runner consumes this existing project input",
                        }
                    )
                    semantic_review.validate_review_manifest(
                        manifest(finding(runner=unbound, blockers=[])),
                        project_root=root,
                    )

            cwd_config = root / "tests" / "cwd-config.json"
            cwd_config.write_text("{}\n", encoding="utf-8")
            cwd_input = copy.deepcopy(runner)
            cwd_input["cwd"] = "tests"
            cwd_input["argv"] = [
                "python3",
                "run_counterexample.py",
                "cwd-config.json",
            ]
            self.assert_invalid(
                manifest(finding(runner=cwd_input, blockers=[])),
                "REVIEW_CASE",
                project_root=root,
            )
            cwd_input["sourceEvidence"].append(
                {
                    "location": {
                        "path": "tests/cwd-config.json",
                        "lineStart": 1,
                        "lineEnd": 1,
                    },
                    "fact": "The cwd-relative runner consumes this config",
                }
            )
            semantic_review.validate_review_manifest(
                manifest(finding(runner=cwd_input, blockers=[])),
                project_root=root,
            )

            absolute_config = root / "absolute-config.json"
            absolute_config.write_text("{}\n", encoding="utf-8")
            absolute_input = copy.deepcopy(runner)
            absolute_input["argv"] = [
                "python3",
                "tests/run_counterexample.py",
                str(absolute_config.resolve()),
            ]
            self.assert_invalid(
                manifest(finding(runner=absolute_input, blockers=[])),
                "REVIEW_CASE",
                project_root=root,
            )
            absolute_input["sourceEvidence"].append(
                {
                    "location": {
                        "path": "absolute-config.json",
                        "lineStart": 1,
                        "lineEnd": 1,
                    },
                    "fact": "The absolute runner input is project-owned",
                }
            )
            semantic_review.validate_review_manifest(
                manifest(finding(runner=absolute_input, blockers=[])),
                project_root=root,
            )

            if hasattr(Path, "symlink_to"):
                linked = root / "tests" / "linked_counterexample.py"
                try:
                    linked.symlink_to(root / "tests" / "run_counterexample.py")
                except OSError:
                    return
                symlink_runner = copy.deepcopy(runner)
                symlink_runner["argv"] = [
                    "python3",
                    "tests/linked_counterexample.py",
                ]
                self.assert_invalid(
                    manifest(finding(runner=symlink_runner, blockers=[])),
                    "REVIEW_CASE",
                    project_root=root,
                )

    def test_manifest_path_must_stay_inside_project_without_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            project_fixture(root)
            manifest_path = root / "review.json"
            manifest_path.write_text(json.dumps(manifest(finding())), encoding="utf-8")
            semantic_review.load_review_manifest(manifest_path, project_root=root)

            outside = Path(directory) / "outside.json"
            outside.write_text(json.dumps(manifest()), encoding="utf-8")
            with self.assertRaises(semantic_review.SemanticReviewError) as raised:
                semantic_review.load_review_manifest(outside, project_root=root)
            self.assertEqual("REVIEW_PATH", raised.exception.code)

            linked = root / "linked.json"
            try:
                linked.symlink_to(manifest_path)
            except OSError:
                return
            with self.assertRaises(semantic_review.SemanticReviewError) as raised:
                semantic_review.load_review_manifest(linked, project_root=root)
            self.assertEqual("REVIEW_PATH", raised.exception.code)

            real_directory = root / "real"
            real_directory.mkdir()
            nested_manifest = real_directory / "review.json"
            nested_manifest.write_text(json.dumps(manifest()), encoding="utf-8")
            linked_directory = root / "linked-directory"
            try:
                linked_directory.symlink_to(real_directory, target_is_directory=True)
            except OSError:
                return
            with self.assertRaises(semantic_review.SemanticReviewError) as raised:
                semantic_review.load_review_manifest(
                    linked_directory / "review.json", project_root=root
                )
            self.assertEqual("REVIEW_PATH", raised.exception.code)

    def test_scenario_tags_are_evidence_bound_enums(self) -> None:
        base = manifest(finding())
        unsupported = copy.deepcopy(base)
        unsupported["findings"][0]["caseCandidate"]["scenarioTags"] = ["security"]
        self.assert_invalid(unsupported)
        empty = copy.deepcopy(base)
        empty["findings"][0]["caseCandidate"]["scenarioTags"] = []
        self.assert_invalid(empty)

        valid = copy.deepcopy(base)
        valid["findings"][0]["caseCandidate"]["scenarioTags"] = [
            "platform",
            "compatibility",
            "failure",
        ]
        contract = semantic_review.validate_review_manifest(valid)
        self.assertEqual(
            ["compatibility", "failure", "platform"],
            semantic_review.case_candidates(contract)[0]["scenarioTags"],
        )

    def test_duplicate_keys_and_nonfinite_numbers_are_rejected(self) -> None:
        duplicate = b'{"schemaId":"a","schemaId":"b","schemaVersion":1,"findings":[]}'
        with self.assertRaises(semantic_review.SemanticReviewError) as raised:
            semantic_review._parse_json_bytes(duplicate)
        self.assertEqual("REVIEW_JSON", raised.exception.code)

        nonfinite = b'{"schemaId":"steward.semantic-review","schemaVersion":NaN,"findings":[]}'
        with self.assertRaises(semantic_review.SemanticReviewError):
            semantic_review._parse_json_bytes(nonfinite)

    def test_bounded_reader_rejects_oversized_input(self) -> None:
        stream = io.BytesIO(b"x" * (semantic_review.MAX_MANIFEST_BYTES + 1))
        with self.assertRaises(semantic_review.SemanticReviewError) as raised:
            semantic_review._read_bounded(stream)
        self.assertEqual("REVIEW_SIZE", raised.exception.code)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs unsupported")
    def test_regular_file_reader_rejects_fifo_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "review.fifo"
            os.mkfifo(fifo)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "check",
                    str(fifo),
                    "--project-root",
                    directory,
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=3,
            )
            self.assertEqual(2, completed.returncode)
            self.assertTrue(completed.stderr.startswith("ERROR REVIEW_IO:"))

    def test_regular_file_reader_rejects_identity_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "review.json"
            replacement = root / "replacement.json"
            target.write_text("original", encoding="utf-8")
            replacement.write_text("replacement", encoding="utf-8")

            real_open = os.open
            with mock.patch.object(
                semantic_review.os, "open", wraps=real_open
            ) as opened:
                self.assertEqual(b"original", semantic_review._read_regular_file(target))
            flags = opened.call_args.args[1]
            if hasattr(os, "O_NONBLOCK"):
                self.assertTrue(flags & os.O_NONBLOCK)
            if hasattr(os, "O_NOFOLLOW"):
                self.assertTrue(flags & os.O_NOFOLLOW)

            def replace_during_open(path: str, flags: int) -> int:
                target.unlink()
                replacement.replace(target)
                return real_open(path, flags)

            with mock.patch.object(
                semantic_review.os, "open", side_effect=replace_during_open
            ), self.assertRaises(semantic_review.SemanticReviewError) as raised:
                semantic_review._read_regular_file(target)
            self.assertEqual("REVIEW_IO", raised.exception.code)

            expected_path, expected_stat = semantic_review._safe_project_file(
                root, "review.json", "review"
            )
            newer = root / "newer.json"
            newer.write_text("newer", encoding="utf-8")
            newer.replace(target)
            with self.assertRaises(semantic_review.SemanticReviewError) as raised:
                semantic_review._read_regular_file(
                    expected_path, expected_stat=expected_stat
                )
            self.assertEqual("REVIEW_IO", raised.exception.code)

    def test_schema_resource_matches_runtime_contract(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(
            "https://json-schema.org/draft/2020-12/schema",
            schema["$schema"],
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            "steward.semantic-review",
            schema["properties"]["schemaId"]["const"],
        )
        self.assertEqual(1, schema["properties"]["schemaVersion"]["const"])
        self.assertEqual(
            "#/$defs/attestation", schema["properties"]["attestation"]["$ref"]
        )
        self.assertEqual(
            "#/$defs/reviewRequest",
            schema["properties"]["reviewRequest"]["$ref"],
        )
        request_condition = next(
            item
            for item in schema["allOf"]
            if item.get("if") == {"required": ["reviewRequest"]}
        )
        self.assertEqual(["attestation"], request_condition["then"]["required"])
        request_bound_gap_items = request_condition["then"]["properties"][
            "attestation"
        ]["properties"]["gaps"]["items"]
        self.assertEqual(
            {
                "required": ["kind"],
                "properties": {"kind": {"const": "unreviewed-scope"}},
            },
            request_bound_gap_items["if"],
        )
        self.assertEqual(
            {"required": ["paths"]},
            request_bound_gap_items["then"],
        )
        attestation_schema = schema["$defs"]["attestation"]
        for field in (
            "sourceFingerprint",
            "goalContractSha256",
            "invariantsSha256",
            "outcome",
            "scope",
            "gaps",
        ):
            self.assertIn(field, attestation_schema["required"])
        self.assertEqual(
            "^sha256:[0-9a-f]{64}$", schema["$defs"]["sha256"]["pattern"]
        )
        self.assertEqual(
            ["findings", "no-findings", "incomplete"],
            attestation_schema["properties"]["outcome"]["enum"],
        )
        request_schema = schema["$defs"]["reviewRequest"]
        self.assertEqual(
            {"target", "requestedPaths", "requestSha256"},
            set(request_schema["required"]),
        )
        self.assertEqual(
            1,
            request_schema["properties"]["requestedPaths"]["minItems"],
        )
        self.assertEqual(
            {"kind", "sourceFingerprint"},
            set(schema["$defs"]["sourceReviewTarget"]["required"]),
        )
        self.assertEqual(
            {"kind", "sourceFingerprint", "baseIdentity", "headIdentity"},
            set(schema["$defs"]["diffReviewTarget"]["required"]),
        )
        gap_schema = schema["$defs"]["reviewGap"]
        self.assertEqual(
            {"id", "kind", "detail", "neededEvidence"},
            set(gap_schema["required"]),
        )
        self.assertEqual(
            1,
            gap_schema["properties"]["paths"]["minItems"],
        )
        self.assertEqual(
            [
                {
                    "if": {
                        "required": ["kind"],
                        "properties": {"kind": {"const": "unreviewed-scope"}},
                    },
                    "else": {"properties": {"paths": False}},
                }
            ],
            gap_schema["allOf"],
        )
        finding_schema = schema["$defs"]["finding"]
        for field in (
            "id",
            "required",
            "resolutionState",
            "evidence",
            "triggerPath",
            "observableConsequence",
            "counterexample",
            "criteriaIds",
            "invariantIds",
            "caseCandidate",
        ):
            self.assertIn(field, finding_schema["required"])
        candidate = schema["$defs"]["caseCandidate"]
        for field in (
            "coversCriteria",
            "coversInvariants",
            "reviewFindingIds",
            "scenarioTags",
            "quick",
        ):
            self.assertIn(field, candidate["required"])

        def matches(definition_name: str, value: str) -> bool:
            def evaluate(definition: dict) -> bool:
                if "$ref" in definition:
                    prefix = "#/$defs/"
                    self.assertTrue(definition["$ref"].startswith(prefix))
                    return evaluate(schema["$defs"][definition["$ref"][len(prefix) :]])
                if "const" in definition and value != definition["const"]:
                    return False
                if definition.get("type") == "string" and not isinstance(value, str):
                    return False
                if len(value) < definition.get("minLength", 0):
                    return False
                if "pattern" in definition and re.search(definition["pattern"], value) is None:
                    return False
                if "allOf" in definition and not all(
                    evaluate(item) for item in definition["allOf"]
                ):
                    return False
                return "oneOf" not in definition or sum(
                    evaluate(item) for item in definition["oneOf"]
                ) == 1

            return evaluate(schema["$defs"][definition_name])

        self.assertTrue(matches("relativePath", "a/b"))
        for invalid_path in ("a//b", "./a", "."):
            with self.subTest(schema_definition="relativePath", value=invalid_path):
                self.assertFalse(matches("relativePath", invalid_path))
        self.assertTrue(matches("cwdPath", "."))
        for invalid_cwd in ("a//b", "./a"):
            with self.subTest(schema_definition="cwdPath", value=invalid_cwd):
                self.assertFalse(matches("cwdPath", invalid_cwd))

    def test_cli_modes_are_canonical_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            path = root / "review.json"
            value = manifest(finding())
            path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            before = path.read_bytes()
            commands = {}
            for command in ("check", "view", "digest", "case-candidates"):
                commands[command] = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        command,
                        str(path),
                        "--project-root",
                        str(root),
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, commands[command].returncode, commands[command].stderr)
            self.assertRegex(
                commands["check"].stdout,
                r"^VALID sha256:[0-9a-f]{64} findings=1 required=1\n$",
            )
            self.assertEqual(
                commands["digest"].stdout.strip(),
                commands["check"].stdout.split()[1],
            )
            self.assertEqual(
                semantic_review.review_manifest_view(
                    semantic_review.load_review_manifest(path, project_root=root)
                ),
                json.loads(commands["view"].stdout),
            )
            candidates = json.loads(commands["case-candidates"].stdout)
            self.assertEqual("RF-RETRY-001", candidates[0]["reviewFindingIds"][0])
            self.assertEqual(before, path.read_bytes())

    def test_request_view_cli_builds_canonical_source_and_diff_without_writes(self) -> None:
        fingerprint = "sha256:" + "4" * 64
        with tempfile.TemporaryDirectory() as directory:
            empty_cwd = Path(directory)
            source = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "request-view",
                    "--target-kind",
                    "source",
                    "--source-fingerprint",
                    fingerprint,
                    "--requested-path",
                    "src/z.py",
                    "--requested-path",
                    "src/a.py",
                ],
                text=True,
                capture_output=True,
                check=False,
                cwd=empty_cwd,
            )
            self.assertEqual(0, source.returncode, source.stderr)
            source_value = json.loads(source.stdout)
            self.assertEqual(["src/a.py", "src/z.py"], source_value["requestedPaths"])
            built = semantic_review.build_review_request(
                target_kind="source",
                source_fingerprint=fingerprint,
                requested_paths=("src/z.py", "src/a.py"),
            )
            self.assertEqual(
                semantic_review.canonical_review_request_bytes(built) + b"\n",
                source.stdout.encode("utf-8"),
            )

            diff = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "request-view",
                    "--target-kind",
                    "diff",
                    "--source-fingerprint",
                    fingerprint,
                    "--base-identity",
                    "git:base",
                    "--head-identity",
                    "git:head",
                    "--requested-path",
                    "src/a.py",
                ],
                text=True,
                capture_output=True,
                check=False,
                cwd=empty_cwd,
            )
            self.assertEqual(0, diff.returncode, diff.stderr)
            self.assertEqual("diff", json.loads(diff.stdout)["target"]["kind"])
            self.assertEqual([], list(empty_cwd.iterdir()))

    def test_request_view_cli_rejects_duplicate_and_invalid_paths(self) -> None:
        fingerprint = "sha256:" + "4" * 64
        cases = (
            (["src/a.py", "src/a.py"], "REVIEW_SCHEMA"),
            (["/src/a.py"], "REVIEW_PATH"),
            (["../src/a.py"], "REVIEW_PATH"),
            (["src//a.py"], "REVIEW_PATH"),
        )
        for paths, expected_code in cases:
            argv = [
                sys.executable,
                "-B",
                str(SCRIPT),
                "request-view",
                "--target-kind",
                "source",
                "--source-fingerprint",
                fingerprint,
            ]
            for path in paths:
                argv.extend(("--requested-path", path))
            rejected = subprocess.run(
                argv,
                text=True,
                capture_output=True,
                check=False,
            )
            with self.subTest(paths=paths):
                self.assertEqual(1, rejected.returncode)
                self.assertEqual("", rejected.stdout)
                self.assertIn("ERROR " + expected_code + ":", rejected.stderr)

    def test_request_view_output_is_consumed_as_expected_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            generated = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "request-view",
                    "--target-kind",
                    "source",
                    "--source-fingerprint",
                    "sha256:" + "1" * 64,
                    "--requested-path",
                    "src/service.py",
                ],
                text=True,
                capture_output=True,
                check=False,
                cwd=root,
            )
            self.assertEqual(0, generated.returncode, generated.stderr)
            request = json.loads(generated.stdout)
            request_path = root / "expected-review-request.json"
            request_path.write_text(generated.stdout, encoding="utf-8")
            value = manifest(finding())
            value["attestation"] = attestation(root, "src/service.py")
            value["reviewRequest"] = request
            manifest_path = root / "review.json"
            manifest_path.write_text(json.dumps(value), encoding="utf-8")

            checked = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "check",
                    str(manifest_path),
                    "--project-root",
                    str(root),
                    "--expected-review-request",
                    request_path.name,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            self.assertRegex(
                checked.stdout,
                r"scopeVerified=true bindingsVerified=true\n$",
            )

    def test_cli_exact_expected_request_reports_binding_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            request = review_request("src/service.py")
            request_path = root / "expected-review-request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            value = manifest(finding())
            value["attestation"] = attestation(root, "src/service.py")
            value["reviewRequest"] = request
            manifest_path = root / "review.json"
            manifest_path.write_text(json.dumps(value), encoding="utf-8")
            other_cwd = root / "other-cwd"
            other_cwd.mkdir()

            compatibility_checked = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "check",
                    str(manifest_path),
                    "--project-root",
                    str(root),
                ],
                text=True,
                capture_output=True,
                check=False,
                cwd=other_cwd,
            )
            self.assertEqual(
                0,
                compatibility_checked.returncode,
                compatibility_checked.stderr,
            )
            self.assertRegex(
                compatibility_checked.stdout,
                r"scopeVerified=true bindingsVerified=false\n$",
            )

            checked = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "check",
                    str(manifest_path),
                    "--project-root",
                    str(root),
                    "--expected-review-request",
                    request_path.name,
                ],
                text=True,
                capture_output=True,
                check=False,
                cwd=other_cwd,
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            self.assertRegex(
                checked.stdout,
                r"scopeVerified=true bindingsVerified=true\n$",
            )

            changed = review_request(
                "src/service.py",
                kind="diff",
                base_identity="git:other",
                head_identity="git:head",
            )
            request_path.write_text(json.dumps(changed), encoding="utf-8")
            rejected = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "check",
                    str(manifest_path),
                    "--project-root",
                    str(root),
                    "--expected-review-request",
                    request_path.name,
                ],
                text=True,
                capture_output=True,
                check=False,
                cwd=other_cwd,
            )
            self.assertEqual(1, rejected.returncode)
            self.assertIn("REVIEW_REQUEST_MISMATCH", rejected.stderr)

    def test_expected_review_request_reader_binds_regular_file_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            expected = root / "expected.json"
            replacement = root / "replacement.json"
            expected.write_text(
                json.dumps(review_request("src/service.py")),
                encoding="utf-8",
            )
            replacement.write_text(
                json.dumps(
                    review_request(
                        "src/service.py",
                        kind="diff",
                        base_identity="git:other",
                        head_identity="git:head",
                    )
                ),
                encoding="utf-8",
            )
            real_reader = semantic_review._read_regular_file

            def replace_before_read(path: Path, **kwargs: object) -> bytes:
                replacement.replace(expected)
                return real_reader(path, **kwargs)

            with mock.patch.object(
                semantic_review,
                "_read_regular_file",
                side_effect=replace_before_read,
            ), self.assertRaises(semantic_review.SemanticReviewError) as raised:
                semantic_review._read_expected_review_request("expected.json", root)
            self.assertEqual("REVIEW_IO", raised.exception.code)

    def test_cli_rejects_expected_request_content_or_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_fixture(root)
            request = review_request("src/service.py")
            changed_request = review_request(
                "src/service.py",
                kind="diff",
                base_identity="git:base",
                head_identity="git:head",
            )
            value = manifest(finding())
            value["attestation"] = attestation(root, "src/service.py")
            value["reviewRequest"] = request
            manifest_path = root / "review.json"
            manifest_path.write_text(json.dumps(value), encoding="utf-8")
            request_path = root / "expected.json"
            replacement_path = root / "replacement.json"
            real_read_cli = semantic_review._read_cli

            for command, replacement_request in (
                ("check", changed_request),
                ("view", request),
            ):
                with self.subTest(command=command):
                    request_path.write_text(json.dumps(request), encoding="utf-8")
                    replacement_path.write_text(
                        json.dumps(replacement_request),
                        encoding="utf-8",
                    )

                    def replace_after_manifest_read(
                        *args: object,
                        **kwargs: object,
                    ) -> semantic_review.ReviewManifest:
                        contract = real_read_cli(*args, **kwargs)
                        replacement_path.replace(request_path)
                        return contract

                    stdout_bytes = io.BytesIO()
                    stdout = io.TextIOWrapper(
                        stdout_bytes,
                        encoding="utf-8",
                        write_through=True,
                    )
                    stderr = io.StringIO()
                    with mock.patch.object(
                        semantic_review,
                        "_read_cli",
                        side_effect=replace_after_manifest_read,
                    ), mock.patch.object(sys, "stdout", stdout), mock.patch.object(
                        sys,
                        "stderr",
                        stderr,
                    ):
                        return_code = semantic_review.main(
                            [
                                command,
                                str(manifest_path),
                                "--project-root",
                                str(root),
                                "--expected-review-request",
                                request_path.name,
                            ]
                        )
                    self.assertEqual(1, return_code)
                    self.assertEqual(b"", stdout_bytes.getvalue())
                    self.assertTrue(
                        stderr.getvalue().startswith(
                            "ERROR REVIEW_REQUEST_DRIFT:"
                        )
                    )

    def test_cli_stdin_and_error_codes(self) -> None:
        value = json.dumps(manifest())
        stdin = subprocess.run(
            [sys.executable, str(SCRIPT), "digest", "-", "--project-root", "."],
            input=value,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, stdin.returncode, stdin.stderr)
        self.assertRegex(stdin.stdout, r"^sha256:[0-9a-f]{64}\n$")
        implicit_stdin = subprocess.run(
            [sys.executable, str(SCRIPT), "digest"],
            input=value,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, implicit_stdin.returncode, implicit_stdin.stderr)
        self.assertEqual(stdin.stdout, implicit_stdin.stdout)

        invalid = subprocess.run(
            [sys.executable, str(SCRIPT), "check", "-"],
            input="{}",
            text=True,
            capture_output=True,
            check=False,
        )
        missing = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "check",
                "plugins/steward/definitely-missing-review.json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, invalid.returncode)
        self.assertTrue(invalid.stderr.startswith("ERROR REVIEW_SCHEMA:"))
        self.assertEqual(2, missing.returncode)
        self.assertTrue(missing.stderr.startswith("ERROR REVIEW_IO:"))

    def test_skill_contracts_are_explicit_thin_and_non_authorizing(self) -> None:
        review = REVIEW_SKILL.read_text(encoding="utf-8")
        strict = (
            REVIEW_SKILL.parent / "references" / "strict-handoff.md"
        ).read_text(encoding="utf-8")
        loop = LOOP_SKILL.read_text(encoding="utf-8")
        self.assertEqual(1, review.count("references/strict-handoff.md"))
        self.assertIn("`standalone`", review)
        self.assertIn("`strict-handoff`", review)
        self.assertIn("The coordinator alone owns", review)
        self.assertIn("request/path selection and persistence", review)
        self.assertIn("Do not edit, create a review file, execute project behavior or tests", review)
        self.assertIn("lint, type-only diagnostics", review)
        self.assertIn("incomplete hypothesis in gaps", review)
        self.assertNotIn("request-view --target-kind source", review)

        self.assertIn("request-view --target-kind source", strict)
        self.assertIn("request-view --target-kind diff", strict)
        self.assertIn("reads and writes no project file", strict)
        self.assertIn("check - --project-root", strict)
        self.assertIn("scopeVerified=true", strict)
        self.assertIn("bindingsVerified=true", strict)
        self.assertIn("The Reviewer never chooses, widens, refreshes, or saves", strict)
        self.assertIn("Post-fix review", strict)
        self.assertEqual(1, loop.count("../../references/control-plane-contracts.md"))
        self.assertIn("Resolve, freeze, and disclose the exact", loop)
        self.assertIn("quick evidence is not completion", loop)
        self.assertIn("RequestedCoverageSatisfied ∧ audit.ok", loop)
        for path in (REVIEW_AGENT, LOOP_AGENT):
            metadata = path.read_text(encoding="utf-8")
            self.assertIn("allow_implicit_invocation: false", metadata)
            self.assertIn("$steward:", metadata)


if __name__ == "__main__":
    unittest.main()
