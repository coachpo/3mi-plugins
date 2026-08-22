"""Read-only status and artifact-bound completion audit."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adapter_paths import (
    RISK_TIER_CATEGORIES,
    current_platform,
    path_has_symlink_component,
    path_uses_symlink,
    platform_supported_on,
    rebind_review_request_source,
    resolve_project_path,
    review_manifest_source_binding_errors,
    source_file_metadata,
    trace_source_binding_errors,
    validate_pinned_review_request,
)
from journal_state import Campaign, get_attempt
from model import (
    ARTIFACT_MANIFEST_VERSION,
    FINAL_RUN_STATUSES,
    CampaignError,
    canonical_bytes,
    parse_json_text,
    public_message,
    review_case_candidate_sha256,
    sha256_bytes,
)
from runner_evidence import (
    MAX_ARTIFACT_FILE_BYTES,
    MAX_ARTIFACT_FILES,
    MAX_ARTIFACT_TOTAL_BYTES,
    artifact_metadata_is_reparse,
    artifact_tree_entries,
    evidence_file_path,
    inspect_evidence,
    scan_artifact_text_files,
)
from semantic_review import (
    SemanticReviewError,
    load_review_manifest,
    review_manifest_sha256,
)

RESULT_FIELDS = {
    "schemaVersion",
    "kernelVersion",
    "runId",
    "caseId",
    "round",
    "status",
    "exitCode",
    "timedOut",
    "durationMs",
    "reason",
    "argvFingerprint",
    "sourceFingerprintBefore",
    "sourceFingerprintAfter",
    "stdoutSha256",
    "stderrSha256",
    "secretLikeOutput",
    "secretDetected",
    "stdoutTruncated",
    "stderrTruncated",
    "evidence",
}
MAX_AUDIT_ARTIFACT_BYTES = MAX_ARTIFACT_FILE_BYTES
MAX_AUDIT_JSON_BYTES = 16 * 1024 * 1024
MAX_AUDIT_CASE_BYTES = MAX_ARTIFACT_TOTAL_BYTES


def adapter_traceability_mode(adapter: Any) -> str:
    """Return the public traceability mode for a validated adapter."""

    if adapter.traceability is None:
        return "none"
    reference = adapter.traceability.get("reviewFindings", {})
    review_request = getattr(adapter, "review_request", None)
    if (
        isinstance(getattr(adapter, "review_attestation", None), dict)
        and isinstance(review_request, dict)
        and getattr(adapter, "review_bindings_verified", False) is True
        and review_request.get("requestSha256")
        == reference.get("reviewRequestSha256")
    ):
        return "attested"
    return "legacy"


def campaign_traceability_mode(campaign: Campaign) -> str:
    """Return the journal-pinned public traceability mode for a campaign."""

    traceability = campaign.state.get("catalog", {}).get("traceability")
    if traceability is None:
        return "none"
    snapshot = campaign.state.get("traceSnapshot")
    pinned_request = traceability.get("reviewFindings", {}).get(
        "reviewRequestSha256"
    )
    if (
        isinstance(snapshot, dict)
        and isinstance(snapshot.get("reviewFindings"), dict)
        and isinstance(snapshot["reviewFindings"].get("attestation"), dict)
        and isinstance(snapshot["reviewFindings"].get("reviewRequest"), dict)
        and snapshot["reviewFindings"].get("bindingsVerified") is True
        and snapshot["reviewFindings"].get("reviewRequestSha256")
        == snapshot["reviewFindings"]["reviewRequest"].get("requestSha256")
        and snapshot["reviewFindings"].get("reviewRequestSha256")
        == pinned_request
    ):
        return "attested"
    return "legacy"


def campaign_coverage(campaign: Campaign) -> Dict[str, Any]:
    """Return the journal-pinned risk-tier coverage declaration."""

    catalog = campaign.state.get("catalog", {})
    mode = catalog.get("coverageMode", "narrow")
    required_cases = {
        case.get("id"): case.get("category")
        for case in catalog.get("cases", [])
        if case.get("required", True)
        and case.get("category") in RISK_TIER_CATEGORIES
    }
    present = sorted(set(required_cases.values()))
    missing = sorted(set(RISK_TIER_CATEGORIES) - set(present))
    verified: set[str] = set()
    final_id = campaign.state.get("finalRegressionAttemptId")
    if isinstance(final_id, str):
        try:
            final_attempt = get_attempt(campaign.state, final_id)
        except CampaignError:
            final_attempt = None
        if (
            isinstance(final_attempt, dict)
            and final_attempt.get("mode") == "regression"
            and final_attempt.get("status") == "PASS"
        ):
            verified = {
                required_cases[case_run["caseId"]]
                for case_run in final_attempt.get("caseRuns", [])
                if case_run.get("status") == "PASS"
                and case_run.get("caseId") in required_cases
            }
    return {
        "mode": mode,
        "presentTiers": present,
        "missingTiers": missing,
        "outOfScopeTiers": missing if mode == "narrow" else [],
        "verifiedTiers": sorted(verified),
        "unverifiedTiers": sorted(set(present) - verified),
    }


def completion_status(campaign: Campaign, *, audit_ok: Optional[bool]) -> str:
    """Derive completion while preserving whether audit was evaluated."""

    if audit_ok is True:
        return "COMPLETE"
    if campaign.state.get("status") == "BLOCKED":
        return "BLOCKED"
    if audit_ok is False:
        return "INCOMPLETE"
    final_id = campaign.state.get("finalRegressionAttemptId")
    if isinstance(final_id, str):
        try:
            final_attempt = get_attempt(campaign.state, final_id)
        except CampaignError:
            final_attempt = None
        if (
            final_attempt is not None
            and final_attempt.get("mode") == "regression"
            and final_attempt.get("status") == "PASS"
        ):
            return "AUDIT_REQUIRED"
    return "INCOMPLETE"


def _strict_review_snapshot(campaign: Campaign) -> Optional[Dict[str, Any]]:
    snapshot = campaign.state.get("traceSnapshot")
    if not isinstance(snapshot, dict):
        return None
    findings = snapshot.get("reviewFindings")
    if (
        not isinstance(findings, dict)
        or not isinstance(findings.get("attestation"), dict)
        or not isinstance(findings.get("reviewRequest"), dict)
        or findings.get("bindingsVerified") is not True
        or findings.get("reviewRequestSha256")
        != findings["reviewRequest"].get("requestSha256")
    ):
        return None
    return findings


def _fix_is_superseded(fix: Dict[str, Any]) -> bool:
    return isinstance(fix.get("supersession"), dict)


def _active_fixes(campaign: Campaign) -> List[Dict[str, Any]]:
    return [
        fix
        for fix in campaign.state.get("fixes", [])
        if isinstance(fix, dict) and not _fix_is_superseded(fix)
    ]


def _effective_review_source(campaign: Campaign) -> Optional[str]:
    findings = _strict_review_snapshot(campaign)
    if findings is None:
        return None
    fixes = _active_fixes(campaign)
    if fixes:
        handoff = fixes[-1].get("reviewHandoff")
        return (
            handoff.get("sourceFingerprint")
            if isinstance(handoff, dict)
            else None
        )
    return findings["attestation"].get("sourceFingerprint")


def review_handoff_audit(
    campaign: Campaign,
    current_source: Optional[str],
    final_attempt: Optional[Dict[str, Any]],
    source_observation: Optional[Dict[str, Any]],
) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    """Revalidate immutable post-fix Review handoffs and their final binding."""

    findings_snapshot = _strict_review_snapshot(campaign)
    if findings_snapshot is None:
        return [], [], []
    codes: List[str] = []
    errors: List[str] = []
    report: List[Dict[str, Any]] = []
    fixes = campaign.state.get("fixes", [])
    active_fixes = _active_fixes(campaign)
    latest_active_fix_id = (
        active_fixes[-1].get("fixId") if active_fixes else None
    )
    expected_goal = campaign.state["traceSnapshot"]["goalContract"]["sha256"]
    expected_invariants = campaign.state["traceSnapshot"]["invariants"]["sha256"]
    inventory = set((source_observation or {}).get("projectPaths", []))

    for fix in fixes:
        handoff = fix.get("reviewHandoff")
        superseded = _fix_is_superseded(fix)
        item: Dict[str, Any] = {
            "fixId": fix.get("fixId"),
            "ok": False,
            "superseded": superseded,
        }
        if superseded:
            item["supersessionReason"] = fix["supersession"].get("reason")
        report.append(item)
        if not isinstance(handoff, dict):
            if superseded:
                item.update(
                    {
                        "ok": True,
                        "historicalHandoffRecorded": False,
                    }
                )
                continue
            codes.append("REVIEW_HANDOFF_REQUIRED")
            errors.append(
                "attested campaign fix lacks a semantic Review handoff: "
                + str(fix.get("fixId"))
            )
            continue
        item["manifestPath"] = handoff.get("manifestPath")
        if handoff.get("outcome") == "incomplete":
            codes.append("REVIEW_HANDOFF_INCOMPLETE")
            errors.append(
                "semantic Review handoff is incomplete: " + str(fix.get("fixId"))
            )
            continue
        relative = handoff.get("manifestPath")
        if not isinstance(relative, str) or relative in inventory:
            codes.append("REVIEW_HANDOFF_DRIFT")
            errors.append(
                "semantic Review handoff path is unsafe or source-included: "
                + str(fix.get("fixId"))
            )
            continue
        manifest_path = campaign.adapter.project_root / relative
        latest = fix.get("fixId") == latest_active_fix_id
        try:
            expected_request = validate_pinned_review_request(
                handoff.get("reviewRequest"),
                "Review handoff request",
            )
            manifest = load_review_manifest(
                manifest_path,
                project_root=campaign.adapter.project_root,
                verify_baseline=latest,
                expected_review_request=expected_request,
            )
        except (SemanticReviewError, OSError) as exc:
            if superseded:
                item.update(
                    {
                        "ok": True,
                        "historicalHandoffRecorded": True,
                        "historicalManifestAvailable": False,
                    }
                )
                continue
            codes.append("REVIEW_HANDOFF_DRIFT")
            errors.append(
                "semantic Review handoff cannot be revalidated: "
                + str(fix.get("fixId"))
                + ": "
                + public_message(exc)
            )
            continue
        fresh_binding_errors: List[str] = []
        if latest and source_observation is not None:
            fresh_binding_errors = review_manifest_source_binding_errors(
                campaign.adapter,
                source_observation,
                manifest,
                require_attestation=True,
            )
        attestation = getattr(manifest, "attestation", None)
        finding_ids = sorted(finding.id for finding in manifest.findings)
        required_ids = sorted(
            finding.id for finding in manifest.findings if finding.required
        )
        resolution_states = {
            finding.id: finding.resolution_state for finding in manifest.findings
        }
        candidate_digests = {
            finding.id: review_case_candidate_sha256(finding.case_candidate)
            for finding in manifest.findings
        }
        scope = (
            [
                {"path": scope_file.path, "sha256": scope_file.sha256}
                for scope_file in attestation.scope
            ]
            if attestation is not None
            else None
        )
        observed = {
            "manifestSha256": review_manifest_sha256(manifest),
            "sourceFingerprint": getattr(attestation, "source_fingerprint", None),
            "goalContractSha256": getattr(
                attestation, "goal_contract_sha256", None
            ),
            "invariantsSha256": getattr(attestation, "invariants_sha256", None),
            "outcome": getattr(attestation, "outcome", None),
            "scope": scope,
            "findingIds": finding_ids,
            "requiredFindingIds": required_ids,
            "resolutionStates": dict(sorted(resolution_states.items())),
            "caseCandidateSha256s": dict(sorted(candidate_digests.items())),
            "reviewRequest": expected_request,
            "reviewRequestSha256": expected_request["requestSha256"],
            "bindingsVerified": True,
        }
        expected = {
            field: handoff.get(field)
            for field in observed
        }
        unresolved = sorted(
            finding_id
            for finding_id in fix.get("resolvedFindingIds", [])
            if resolution_states.get(finding_id) not in {"resolved", "invalidated"}
        )
        immutable_mismatch = (
            finding_ids != findings_snapshot.get("findingIds")
            or required_ids != findings_snapshot.get("requiredFindingIds")
            or candidate_digests
            != findings_snapshot.get("caseCandidateSha256s")
        )
        initial_request = validate_pinned_review_request(
            findings_snapshot["reviewRequest"],
            "initialized Review request",
        )
        initial_target = initial_request["target"]
        handoff_target = expected_request["target"]
        request_identity_mismatch = (
            handoff_target["kind"] != initial_target["kind"]
            or handoff_target["sourceFingerprint"]
            != observed["sourceFingerprint"]
            or expected_request["requestedPaths"]
            != initial_request["requestedPaths"]
            or (
                initial_target["kind"] == "source"
                and expected_request
                != rebind_review_request_source(
                    initial_request,
                    str(observed["sourceFingerprint"]),
                    "post-fix Review request",
                )
            )
            or (
                initial_target["kind"] == "diff"
                and handoff_target["baseIdentity"]
                != initial_target["baseIdentity"]
            )
        )
        unbound_scope = bool(
            latest
            and (
                scope is None
                or any(scope_file["path"] not in inventory for scope_file in scope)
            )
        )
        if (
            attestation is None
            or observed != expected
            or immutable_mismatch
            or request_identity_mismatch
            or unbound_scope
            or fresh_binding_errors
            or attestation.goal_contract_sha256 != expected_goal
            or attestation.invariants_sha256 != expected_invariants
            or unresolved
        ):
            if superseded:
                item.update(
                    {
                        "ok": True,
                        "historicalHandoffRecorded": True,
                        "historicalManifestAvailable": True,
                        "historicalManifestValid": False,
                    }
                )
                continue
            codes.append("REVIEW_HANDOFF_DRIFT")
            errors.append(
                "semantic Review handoff binding drifted: "
                + str(fix.get("fixId"))
            )
            continue
        try:
            stable_manifest = load_review_manifest(
                manifest_path,
                project_root=campaign.adapter.project_root,
                verify_baseline=latest,
                expected_review_request=expected_request,
            )
        except (SemanticReviewError, OSError):
            stable_manifest = None
        if (
            stable_manifest is None
            or review_manifest_sha256(stable_manifest)
            != observed["manifestSha256"]
        ):
            codes.append("REVIEW_HANDOFF_DRIFT")
            errors.append(
                "semantic Review handoff changed while it was audited: "
                + str(fix.get("fixId"))
            )
            continue
        item.update(
            {
                "ok": True,
                "manifestSha256": observed["manifestSha256"],
                "sourceFingerprint": observed["sourceFingerprint"],
                "outcome": observed["outcome"],
                "historicalHandoffRecorded": True,
                "historicalManifestAvailable": True,
                "historicalManifestValid": True,
            }
        )

    effective_source = _effective_review_source(campaign)
    final_source = (
        final_attempt.get("sourceFingerprint")
        if isinstance(final_attempt, dict)
        else None
    )
    if (
        current_source is None
        or final_source is None
        or effective_source != current_source
        or effective_source != final_source
    ):
        codes.append("SOURCE_BASELINE_MISMATCH")
        errors.append(
            "latest semantic Review attestation does not bind the current final-regression source"
        )
    return sorted(set(codes)), errors, report


def _unexpected_tree_entries(
    directory: Path,
    expected: Dict[str, str],
    label: str,
) -> List[str]:
    """Return exact-tree errors without following any directory entry."""

    errors: List[str] = []
    observed: set[str] = set()
    try:
        directory_metadata = directory.lstat()
        if (
            stat.S_ISLNK(directory_metadata.st_mode)
            or artifact_metadata_is_reparse(directory_metadata)
            or not stat.S_ISDIR(directory_metadata.st_mode)
        ):
            return [label + " is a symlink/reparse or non-directory"]
        with os.scandir(str(directory)) as entries:
            for entry in entries:
                name = entry.name
                observed.add(name)
                expected_kind = expected.get(name)
                if expected_kind is None:
                    errors.append("unexpected " + label + " entry: " + name)
                    continue
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    errors.append(label + " entry cannot be inspected: " + name)
                    continue
                is_valid = (
                    not entry.is_symlink()
                    and not artifact_metadata_is_reparse(metadata)
                    and (
                        stat.S_ISDIR(metadata.st_mode)
                        if expected_kind == "directory"
                        else stat.S_ISREG(metadata.st_mode)
                    )
                )
                if not is_valid:
                    errors.append(label + " entry has an invalid type or link: " + name)
    except OSError:
        return [label + " cannot be enumerated safely"]
    for name in sorted(set(expected) - observed):
        errors.append("missing " + label + " entry: " + name)
    return errors


def audit_campaign_tree(campaign: Campaign) -> List[str]:
    """Verify that journal-owned containers have no undeclared objects."""

    errors = _unexpected_tree_entries(
        campaign.adapter.campaign_root,
        {
            "campaign.lock": "file",
            "events.jsonl": "file",
            "state.json": "file",
            "summary.json": "file",
            "attempts": "directory",
        },
        "campaign root",
    )
    attempts_root = campaign.adapter.campaign_root / "attempts"
    expected_attempts = {
        Path(attempt["artifactDir"]).name: "directory"
        for attempt in campaign.state["attempts"]
    }
    errors.extend(
        _unexpected_tree_entries(attempts_root, expected_attempts, "attempts")
    )
    for attempt in campaign.state["attempts"]:
        attempt_root = campaign.adapter.campaign_root / attempt["artifactDir"]
        errors.extend(
            _unexpected_tree_entries(
                attempt_root,
                {"cases": "directory"},
                "attempt " + attempt["id"],
            )
        )
        cases_root = attempt_root / "cases"
        expected_runs = {
            Path(case_run["artifactDir"]).name: "directory"
            for case_run in attempt.get("caseRuns", [])
        }
        errors.extend(
            _unexpected_tree_entries(
                cases_root,
                expected_runs,
                "case containers for " + attempt["id"],
            )
        )
    return errors


def stream_regular_file(
    path: Path, *, capture_limit: Optional[int] = None
) -> Tuple[int, str, Optional[bytes]]:
    """Read a non-link regular file with bounded memory and a stable digest."""

    try:
        before = path.lstat()
    except OSError as exc:
        raise CampaignError("artifact file cannot be inspected") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or artifact_metadata_is_reparse(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise CampaignError("artifact is a symlink/reparse or non-regular file")
    if before.st_size > MAX_AUDIT_ARTIFACT_BYTES:
        raise CampaignError("artifact exceeds the audit size limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: Optional[int] = None
    digest = hashlib.sha256()
    total = 0
    captured = bytearray() if capture_limit is not None else None
    try:
        descriptor = os.open(str(path), flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or artifact_metadata_is_reparse(opened)
            or (opened.st_dev, opened.st_ino)
            != (before.st_dev, before.st_ino)
        ):
            raise CampaignError("artifact changed while it was opened")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_AUDIT_ARTIFACT_BYTES:
                    raise CampaignError("artifact exceeds the audit size limit")
                digest.update(chunk)
                if captured is not None:
                    if total > capture_limit:
                        raise CampaignError(
                            "JSON artifact exceeds the audit size limit"
                        )
                    captured.extend(chunk)
        after = path.lstat()
        if (
            stat.S_ISLNK(after.st_mode)
            or artifact_metadata_is_reparse(after)
            or not stat.S_ISREG(after.st_mode)
            or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or after.st_size != total
        ):
            raise CampaignError("artifact changed while it was audited")
    except OSError as exc:
        raise CampaignError("artifact file cannot be read safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return (
        total,
        "sha256:" + digest.hexdigest(),
        bytes(captured) if captured is not None else None,
    )


def status_report(campaign: Campaign) -> Dict[str, Any]:
    report = campaign.summary()
    report["executionStatus"] = campaign.state["status"]
    report["resumeMode"] = campaign.state.get("resumeMode")
    report["journalReplayable"] = True
    report["snapshotConsistent"] = campaign.snapshot_consistent
    report["summaryConsistent"] = campaign.summary_consistent
    try:
        report["catalogDrift"] = (
            campaign.adapter.catalog_fingerprint != campaign.state["catalogFingerprint"]
        )
    except (KeyError, TypeError):
        report["catalogDrift"] = True
    report["runtimePlatform"] = campaign.state.get("runtimePlatform")
    report["currentRuntimePlatform"] = current_platform()
    report["runtimePlatformMatch"] = (
        campaign.state.get("runtimePlatform") == current_platform()
    )
    report["traceabilityMode"] = campaign_traceability_mode(campaign)
    report["coverage"] = campaign_coverage(campaign)
    missing_current_trace = (
        report["traceabilityMode"] in {"legacy", "attested"}
        and campaign.adapter.traceability is None
    )
    trace_input_errors = list(campaign.adapter.trace_input_errors)
    if missing_current_trace:
        trace_input_errors.append(
            "initialized traceability is missing from the current adapter"
        )
    try:
        source_observation = campaign.current_source_observation()
        current_source = source_observation["fingerprint"]
        trace_input_errors.extend(
            trace_source_binding_errors(campaign.adapter, source_observation)
        )
        report["currentObservedSourceFingerprint"] = current_source
        report["sourceDriftFromRecorded"] = (
            current_source != campaign.state["currentSourceFingerprint"]
        )
    except CampaignError as exc:
        report["currentObservedSourceFingerprint"] = None
        report["sourceDriftFromRecorded"] = True
        report["sourceObservationError"] = public_message(exc)
    report["traceInputErrors"] = list(dict.fromkeys(trace_input_errors))
    report["traceInputDrift"] = bool(
        report["traceInputErrors"] or missing_current_trace
    )
    report["completionStatus"] = completion_status(
        campaign,
        audit_ok=audit_report(campaign)["ok"],
    )
    return report


def runnable_case_ids(campaign: Campaign) -> List[str]:
    """Return cases that must PASS on the journal-pinned runtime.

    Required cases are always obligations.  An optional case is runnable only
    when its own platform is available and every dependency is runnable.  This
    mirrors execution: an optional case whose optional prerequisite was
    legitimately skipped is itself a legitimate terminal skip, including
    transitively through multiple optional dependency layers.
    """

    cases = campaign.state["cases"]
    runtime = campaign.state["runtimePlatform"]
    memo: Dict[str, bool] = {}

    def runnable(case_id: str) -> bool:
        if case_id in memo:
            return memo[case_id]
        case = cases[case_id]
        if case["required"]:
            memo[case_id] = True
            return True
        result = platform_supported_on(case["platform"], runtime) and all(
            runnable(dependency) for dependency in case["dependsOn"]
        )
        memo[case_id] = result
        return result

    return [case_id for case_id in cases if runnable(case_id)]


def audit_artifacts(
    campaign: Campaign,
) -> Tuple[
    List[str],
    List[str],
    Dict[str, Dict[str, Dict[str, Any]]],
]:
    errors: List[str] = audit_campaign_tree(campaign)
    checked: List[str] = []
    validated_files: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for attempt in campaign.state["attempts"]:
        for case_run in attempt.get("caseRuns", []):
            status = case_run["status"]
            if status not in FINAL_RUN_STATUSES:
                if status == "INTERRUPTED":
                    artifact = campaign.adapter.campaign_root / case_run["artifactDir"]
                    try:
                        artifact_metadata = artifact.lstat()
                    except OSError:
                        artifact_metadata = None
                    if (
                        path_uses_symlink(artifact, campaign.adapter.campaign_root)
                        or artifact_metadata is not None
                        and (
                            stat.S_ISLNK(artifact_metadata.st_mode)
                            or artifact_metadata_is_reparse(artifact_metadata)
                        )
                    ):
                        errors.append(
                            "interrupted artifact uses symlink/reparse: "
                            + case_run["runId"]
                        )
                    elif artifact_metadata is None or not stat.S_ISDIR(
                        artifact_metadata.st_mode
                    ):
                        errors.append(
                            "interrupted artifact missing: " + case_run["runId"]
                        )
                continue
            run_error_count = len(errors)
            artifact = campaign.adapter.campaign_root / case_run["artifactDir"]
            try:
                artifact_metadata = artifact.lstat()
            except OSError:
                artifact_metadata = None
            if (
                path_uses_symlink(artifact, campaign.adapter.campaign_root)
                or artifact_metadata is not None
                and (
                    stat.S_ISLNK(artifact_metadata.st_mode)
                    or artifact_metadata_is_reparse(artifact_metadata)
                )
            ):
                errors.append(
                    "artifact directory uses symlink/reparse: " + case_run["runId"]
                )
                continue
            if artifact_metadata is None or not stat.S_ISDIR(artifact_metadata.st_mode):
                errors.append("artifact directory missing: " + case_run["runId"])
                continue
            manifest_path = artifact / "artifact-manifest.json"
            binding = case_run.get("artifactManifest")
            try:
                manifest_metadata = manifest_path.lstat()
            except OSError:
                manifest_metadata = None
            if (
                manifest_metadata is None
                or stat.S_ISLNK(manifest_metadata.st_mode)
                or artifact_metadata_is_reparse(manifest_metadata)
                or not stat.S_ISREG(manifest_metadata.st_mode)
                or not isinstance(binding, dict)
            ):
                errors.append(
                    "artifact manifest missing or unbound: " + case_run["runId"]
                )
                continue
            expected_manifest_relative = (
                case_run["artifactDir"] + "/artifact-manifest.json"
            )
            if (
                set(binding) != {"relativePath", "size", "sha256"}
                or binding.get("relativePath") != expected_manifest_relative
            ):
                errors.append("artifact manifest binding invalid: " + case_run["runId"])
            try:
                manifest_size, manifest_hash, manifest_bytes = stream_regular_file(
                    manifest_path, capture_limit=MAX_AUDIT_JSON_BYTES
                )
                assert manifest_bytes is not None
                manifest = parse_json_text(
                    manifest_bytes.decode("utf-8"), "artifact manifest"
                )
            except (OSError, UnicodeDecodeError, CampaignError):
                errors.append("artifact manifest unreadable: " + case_run["runId"])
                continue
            if (
                binding.get("size") != manifest_size
                or binding.get("sha256") != manifest_hash
            ):
                errors.append("artifact manifest tampered: " + case_run["runId"])
                continue
            if not isinstance(manifest, dict) or set(manifest) != {
                "artifactManifestVersion",
                "files",
            }:
                errors.append("artifact manifest shape invalid: " + case_run["runId"])
                continue
            if (
                type(manifest.get("artifactManifestVersion")) is not int
                or manifest["artifactManifestVersion"] != ARTIFACT_MANIFEST_VERSION
            ):
                errors.append(
                    "artifact manifest version mismatch: " + case_run["runId"]
                )
                continue
            listed = manifest.get("files")
            if not isinstance(listed, list):
                errors.append("artifact manifest files invalid: " + case_run["runId"])
                continue
            if len(listed) > MAX_ARTIFACT_FILES:
                errors.append(
                    "artifact manifest count exceeds limit: " + case_run["runId"]
                )
                continue
            declared_total = sum(
                max(0, item.get("size", 0))
                for item in listed
                if isinstance(item, dict) and type(item.get("size")) is int
            )
            if declared_total > MAX_AUDIT_CASE_BYTES:
                errors.append(
                    "artifact manifest byte budget exceeded: " + case_run["runId"]
                )
                continue
            actual_names: set[str] = set()
            actual_directories: set[str] = set()
            actual_total_bytes = 0
            artifact_budget_exceeded = False
            try:
                artifact_entries = artifact_tree_entries(artifact)
            except CampaignError as exc:
                errors.append(
                    "artifact tree cannot be inspected safely: "
                    + case_run["runId"]
                    + " ("
                    + public_message(exc)
                    + ")"
                )
                continue
            for path, metadata in artifact_entries:
                relative = path.relative_to(artifact).as_posix()
                if relative == "artifact-manifest.json":
                    continue
                if stat.S_ISLNK(metadata.st_mode) or artifact_metadata_is_reparse(
                    metadata
                ):
                    errors.append(
                        "artifact symlink/reparse or non-regular file: "
                        + case_run["runId"]
                    )
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    actual_directories.add(relative)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    errors.append(
                        "artifact symlink/reparse or non-regular file: "
                        + case_run["runId"]
                    )
                    continue
                size = metadata.st_size
                if size > MAX_ARTIFACT_FILE_BYTES:
                    errors.append(
                        "artifact exceeds file size limit: " + case_run["runId"]
                    )
                    artifact_budget_exceeded = True
                    break
                actual_total_bytes += size
                if actual_total_bytes > MAX_AUDIT_CASE_BYTES:
                    errors.append(
                        "artifact set exceeds audit byte limit: " + case_run["runId"]
                    )
                    artifact_budget_exceeded = True
                    break
                actual_names.add(relative)
            if artifact_budget_exceeded:
                continue
            listed_names: set[str] = set()
            declared_directories: set[str] = set()
            listed_hashes: Dict[str, str] = {}
            for item in listed:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"relativePath", "size", "sha256"}
                    or not isinstance(item.get("relativePath"), str)
                    or type(item.get("size")) is not int
                    or not isinstance(item.get("sha256"), str)
                ):
                    errors.append(
                        "artifact manifest entry invalid: " + case_run["runId"]
                    )
                    continue
                relative = item["relativePath"]
                if relative in listed_names:
                    errors.append(
                        "artifact manifest has duplicate entry: "
                        + relative
                        + " "
                        + case_run["runId"]
                    )
                    continue
                try:
                    path = evidence_file_path(artifact, relative)
                except CampaignError:
                    errors.append(
                        "artifact manifest path is unsafe: "
                        + relative
                        + " "
                        + case_run["runId"]
                    )
                    continue
                listed_names.add(relative)
                parent = Path(relative).parent
                while parent != Path("."):
                    declared_directories.add(parent.as_posix())
                    parent = parent.parent
                try:
                    content_size, content_hash, _ = stream_regular_file(path)
                except (CampaignError, OSError):
                    errors.append(
                        "artifact missing or symlink: "
                        + relative
                        + " "
                        + case_run["runId"]
                    )
                    continue
                if (
                    item.get("size") != content_size
                    or item.get("sha256") != content_hash
                ):
                    kind = (
                        "output"
                        if relative in ("stdout.txt", "stderr.txt")
                        else ("result" if relative == "result.json" else "evidence")
                    )
                    errors.append(
                        kind
                        + " artifact tampered: "
                        + relative
                        + " "
                        + case_run["runId"]
                    )
                listed_hashes[relative] = content_hash
            if actual_names != listed_names:
                errors.append(
                    "artifact set differs from manifest: " + case_run["runId"]
                )
            if actual_directories != declared_directories:
                errors.append(
                    "artifact directory set differs from manifest: " + case_run["runId"]
                )
            if not {"result.json", "stdout.txt", "stderr.txt"}.issubset(listed_names):
                errors.append(
                    "artifact manifest lacks kernel result/output files: "
                    + case_run["runId"]
                )
            result_path = artifact / "result.json"
            try:
                _result_size, _result_hash, result_bytes = stream_regular_file(
                    result_path, capture_limit=MAX_AUDIT_JSON_BYTES
                )
                assert result_bytes is not None
                result = parse_json_text(result_bytes.decode("utf-8"), "result.json")
            except (CampaignError, UnicodeDecodeError):
                errors.append("result.json unreadable: " + case_run["runId"])
                continue
            if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
                errors.append("result.json schema fields invalid: " + case_run["runId"])
                continue
            if (
                type(result["schemaVersion"]) is not int
                or result["schemaVersion"]
                != campaign.state["journalSchemaVersion"]
                or result["kernelVersion"] != campaign.state["kernelVersion"]
            ):
                errors.append("result.json version mismatch: " + case_run["runId"])
            case_definition = next(
                (
                    item
                    for item in campaign.state["catalog"]["cases"]
                    if item.get("id") == case_run["caseId"]
                ),
                None,
            )
            if not isinstance(case_definition, dict) or not isinstance(
                case_definition.get("argv"), list
            ):
                errors.append(
                    "initialized case definition missing: " + case_run["runId"]
                )
                continue
            expected_values = {
                "runId": case_run["runId"],
                "caseId": case_run["caseId"],
                "round": attempt["mode"],
                "status": case_run["status"],
                "reason": case_run.get("reason"),
                "exitCode": case_run.get("exitCode"),
                "timedOut": case_run.get("timedOut"),
                "sourceFingerprintBefore": case_run.get("sourceFingerprint"),
                "sourceFingerprintAfter": case_run.get("sourceAfterFingerprint"),
                "stdoutSha256": case_run.get("stdoutSha256"),
                "stderrSha256": case_run.get("stderrSha256"),
                "evidence": case_run.get("evidence"),
                "argvFingerprint": sha256_bytes(
                    canonical_bytes(case_definition["argv"])
                ),
            }
            for field, expected in expected_values.items():
                if result.get(field) != expected:
                    errors.append(
                        "result/journal " + field + " mismatch: " + case_run["runId"]
                    )
            if (
                not isinstance(result["timedOut"], bool)
                or type(result["durationMs"]) is not int
                or result["durationMs"] < 0
                or any(
                    not isinstance(result[field], bool)
                    for field in (
                        "secretLikeOutput",
                        "secretDetected",
                        "stdoutTruncated",
                        "stderrTruncated",
                    )
                )
                or result["secretLikeOutput"] != result["secretDetected"]
            ):
                errors.append("result.json scalar types invalid: " + case_run["runId"])
            bound_invalidated_regression_drift = (
                attempt["mode"] == "regression"
                and attempt["status"] == "INVALIDATED"
                and attempt.get("sourceFingerprint")
                == result["sourceFingerprintBefore"]
                and attempt.get("sourceAfterFingerprint")
                == result["sourceFingerprintAfter"]
                and result["sourceFingerprintAfter"]
                != result["sourceFingerprintBefore"]
                and bool(attempt.get("caseRuns"))
                and attempt["caseRuns"][-1]["runId"] == result["runId"]
            )
            if result["status"] in {"PASS", "RETEST_PASSED"} and (
                result["exitCode"] != 0
                or result["timedOut"]
                or result["reason"] is not None
                or result["secretDetected"]
                or result["secretLikeOutput"]
                or result["sourceFingerprintAfter"] is None
                or (
                    result["sourceFingerprintAfter"]
                    != result["sourceFingerprintBefore"]
                    and not bound_invalidated_regression_drift
                )
                or result["evidence"].get("missingFiles")
                or result["evidence"].get("emptyFiles")
                or result["evidence"].get("secretLikeContent")
            ):
                errors.append(
                    "passing result.json outcome is invalid: " + case_run["runId"]
                )
            if result["status"] in {"FAILED", "BLOCKED"} and (
                not isinstance(result["reason"], str) or not result["reason"]
            ):
                errors.append("failed result.json lacks a reason: " + case_run["runId"])
            for name in ("stdout.txt", "stderr.txt"):
                try:
                    output_metadata = (artifact / name).lstat()
                except OSError:
                    output_metadata = None
                if (
                    output_metadata is None
                    or stat.S_ISLNK(output_metadata.st_mode)
                    or artifact_metadata_is_reparse(output_metadata)
                    or not stat.S_ISREG(output_metadata.st_mode)
                ):
                    errors.append(name + " missing: " + case_run["runId"])
            for name, field in (
                ("stdout.txt", "stdoutSha256"),
                ("stderr.txt", "stderrSha256"),
            ):
                actual_hash = listed_hashes.get(name)
                if actual_hash != case_run.get(field) or actual_hash != result.get(
                    field
                ):
                    errors.append(
                        name
                        + " hash does not match journal/result: "
                        + case_run["runId"]
                    )
            case_state = campaign.state["cases"][case_run["caseId"]]
            contract = case_state.get("evidence") or {}
            try:
                evidence, _ = inspect_evidence(artifact, contract, redact_files=False)
            except CampaignError as exc:
                errors.append(
                    "evidence path rejected: "
                    + case_run["runId"]
                    + " ("
                    + public_message(exc)
                    + ")"
                )
                continue
            for field in (
                "requiredFiles",
                "nonEmptyFiles",
                "missingFiles",
                "emptyFiles",
                "files",
            ):
                if evidence.get(field) != result["evidence"].get(field):
                    errors.append(
                        "evidence report mismatch for "
                        + field
                        + ": "
                        + case_run["runId"]
                    )
            try:
                secret_artifact = scan_artifact_text_files(artifact, redact_files=False)
            except CampaignError as exc:
                errors.append(
                    "artifact secret scan rejected: "
                    + case_run["runId"]
                    + " ("
                    + public_message(exc)
                    + ")"
                )
                continue
            if secret_artifact:
                errors.append(
                    "secret-like artifact content detected: " + case_run["runId"]
                )
            if status in ("PASS", "RETEST_PASSED") and (
                evidence["missingFiles"] or evidence["emptyFiles"]
            ):
                errors.append("evidence contract incomplete: " + case_run["runId"])
            checked.append(case_run["runId"])
            if len(errors) == run_error_count:
                validated_files[case_run["runId"]] = {
                    item["relativePath"]: {
                        "size": item["size"],
                        "sha256": item["sha256"],
                    }
                    for item in listed
                }
    return errors, checked, validated_files


def traceability_audit(
    campaign: Campaign,
    final_attempt: Optional[Dict[str, Any]],
    current_source: Optional[str],
    source_observation: Optional[Dict[str, Any]],
    validated_artifact_files: Dict[str, Dict[str, Dict[str, Any]]],
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """Evaluate stable trace obligations using only final-regression PASS runs."""

    initialized_traceability = campaign.state.get("catalog", {}).get("traceability")
    if initialized_traceability is None:
        return [], [], {
            "mode": campaign_traceability_mode(campaign),
            "criteria": {},
            "invariants": {},
            "requiredScenarios": {},
            "reviewFindings": {},
            "guardrails": [],
        }
    codes: List[str] = []
    errors: List[str] = []
    report: Dict[str, Any] = {
        "mode": campaign_traceability_mode(campaign),
        "criteria": {},
        "invariants": {},
        "requiredScenarios": {},
        "reviewFindings": {},
        "reviewHandoffs": [],
        "guardrails": [],
    }
    effective_review_bound = (
        _strict_review_snapshot(campaign) is not None
        and current_source is not None
        and _effective_review_source(campaign) == current_source
    )
    if campaign.adapter.traceability is None:
        codes.append("TRACE_INPUT_DRIFT")
        errors.append("initialized traceability is missing from the current adapter")
    trace_input_errors = list(campaign.adapter.trace_input_errors)
    if effective_review_bound:
        trace_input_errors = [
            error
            for error in trace_input_errors
            if "REVIEW_BASELINE_DRIFT" not in error
        ]
    if trace_input_errors:
        codes.append("TRACE_INPUT_DRIFT")
        errors.extend(trace_input_errors)
    if source_observation is not None and not effective_review_bound:
        source_binding_errors = trace_source_binding_errors(
            campaign.adapter, source_observation
        )
        if source_binding_errors:
            codes.append("TRACE_INPUT_DRIFT")
            errors.extend(source_binding_errors)
    snapshot = campaign.state.get("traceSnapshot")
    if not isinstance(snapshot, dict):
        codes.append("TRACE_INPUT_DRIFT")
        errors.append("initialized trace snapshot is unavailable")
        return sorted(set(codes)), errors, report

    final_pass_ids = {
        run["caseId"]
        for run in (final_attempt or {}).get("caseRuns", [])
        if run.get("status") == "PASS"
    }
    cases = campaign.state["catalog"]["cases"]

    def passing_required_cases(field: str, value: str) -> List[str]:
        return sorted(
            case["id"]
            for case in cases
            if case.get("required", True)
            and value in case.get(field, [])
            and case["id"] in final_pass_ids
        )

    for criterion_id in snapshot["goalContract"]["criteriaIds"]:
        covered = passing_required_cases("coversCriteria", criterion_id)
        report["criteria"][criterion_id] = covered
        if not covered:
            codes.append("CRITERION_UNCOVERED")
            errors.append(
                "goal criterion lacks a required final-regression PASS: "
                + criterion_id
            )
    for invariant_id in snapshot["invariants"]["hardInvariantIds"]:
        covered = passing_required_cases("coversInvariants", invariant_id)
        report["invariants"][invariant_id] = covered
        if not covered:
            codes.append("INVARIANT_UNCOVERED")
            errors.append(
                "triggered hard invariant lacks a required final-regression PASS: "
                + invariant_id
            )
    for scenario in sorted(
        snapshot["requiredScenarios"]
    ):
        covered = passing_required_cases("scenarioTags", scenario)
        report["requiredScenarios"][scenario] = covered
        if not covered:
            codes.append("REQUIRED_SCENARIO_UNCOVERED")
            errors.append(
                "required scenario lacks a required final-regression PASS: "
                + scenario
            )

    for finding_id in snapshot["reviewFindings"]["requiredFindingIds"]:
        linked = sorted(
            case["id"]
            for case in cases
            if case.get("required", True)
            and finding_id in case.get("reviewFindingIds", [])
        )
        passing = [case_id for case_id in linked if case_id in final_pass_ids]
        resolved_cases: List[str] = []
        effective_resolution_states = snapshot["reviewFindings"][
            "resolutionStates"
        ]
        active_fixes = _active_fixes(campaign)
        if _strict_review_snapshot(campaign) is not None and active_fixes:
            latest_handoff = active_fixes[-1].get("reviewHandoff")
            if isinstance(latest_handoff, dict):
                effective_resolution_states = latest_handoff.get(
                    "resolutionStates", effective_resolution_states
                )
        for case_id in passing:
            failures = [
                (attempt["id"], run)
                for attempt in campaign.state["attempts"]
                if attempt.get("status") == "FAILED"
                for run in attempt.get("caseRuns", [])
                if run.get("caseId") == case_id and run.get("status") == "FAILED"
            ]
            all_failures_bound = all(
                any(
                    fix.get("failedAttemptId") == attempt_id
                    and fix.get("failedCaseId") == case_id
                    and finding_id in fix.get("resolvedFindingIds", [])
                    for fix in active_fixes
                )
                for attempt_id, _run in failures
            )
            if all_failures_bound and (
                _strict_review_snapshot(campaign) is None
                or effective_resolution_states.get(finding_id)
                in {"resolved", "invalidated"}
            ):
                resolved_cases.append(case_id)
        report["reviewFindings"][finding_id] = {
            "linkedRequiredCases": linked,
            "finalPassingCases": passing,
            "resolvedCases": resolved_cases,
            "effectiveResolutionState": effective_resolution_states.get(
                finding_id
            ),
        }
        if not linked:
            codes.append("REQUIRED_FINDING_UNLINKED")
            errors.append("required review finding has no required case: " + finding_id)
        if not resolved_cases:
            codes.append("REQUIRED_FINDING_UNRESOLVED")
            errors.append(
                "required review finding lacks resolved final proof: " + finding_id
            )

    inventory = set((source_observation or {}).get("projectPaths", []))
    observed_source_files = {
        entry["path"]: {key: value for key, value in entry.items() if key != "path"}
        for entry in (source_observation or {}).get("files", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    final_runs = {
        run["caseId"]: run
        for run in (final_attempt or {}).get("caseRuns", [])
        if run.get("status") == "PASS"
    }
    for fix in _active_fixes(campaign):
        guardrail = fix.get("permanentGuardrail")
        item = {"fixId": fix.get("fixId"), "ok": False}
        report["guardrails"].append(item)
        if not isinstance(guardrail, dict):
            codes.append("GUARDRAIL_MISSING")
            errors.append("traceable fix lacks a permanent guardrail: " + fix["fixId"])
            continue
        if guardrail.get("notApplicable") is True:
            item.update({"ok": True, "notApplicable": True})
            continue
        source_path = guardrail.get("sourcePath")
        case_id = guardrail.get("caseId")
        evidence_file = guardrail.get("evidenceFile")
        guardrail_case = next(
            (
                case
                for case in cases
                if case.get("id") == case_id and case.get("required", True)
            ),
            None,
        )
        violated_invariant = fix.get("violatedInvariant")
        if (
            guardrail_case is None
            or (
                isinstance(violated_invariant, str)
                and violated_invariant
                not in guardrail_case.get("coversInvariants", [])
            )
            or not set(fix.get("resolvedFindingIds", [])).issubset(
                set(guardrail_case.get("reviewFindingIds", []))
            )
        ):
            codes.append("GUARDRAIL_MISSING")
            errors.append(
                "guardrail case does not bind its invariant and findings: "
                + fix["fixId"]
            )
            continue
        source_exists = False
        if isinstance(source_path, str):
            try:
                source_file = resolve_project_path(
                    campaign.adapter.project_root,
                    source_path,
                    "guardrail sourcePath",
                )
                source_exists = (
                    not path_has_symlink_component(
                        campaign.adapter.project_root / source_path
                    )
                    and source_file.is_file()
                    and observed_source_files.get(source_path, {}).get("status")
                    == "present"
                    and source_file_metadata(campaign.adapter, source_path)
                    == observed_source_files.get(source_path)
                )
            except CampaignError:
                source_exists = False
        final_source_bound = bool(
            final_attempt is not None
            and current_source is not None
            and current_source == final_attempt.get("sourceFingerprint")
        )
        if source_path not in inventory or not source_exists or not final_source_bound:
            codes.append("GUARDRAIL_SOURCE_UNBOUND")
            errors.append(
                "guardrail source is not a regular final-fingerprinted file: "
                + fix["fixId"]
            )
            continue
        run = final_runs.get(case_id)
        if (
            run is None
            or final_attempt is None
            or run.get("sourceFingerprint")
            != final_attempt.get("sourceFingerprint")
        ):
            codes.append("GUARDRAIL_CASE_NOT_FINAL_PASS")
            errors.append("guardrail case lacks final PASS: " + fix["fixId"])
            continue
        evidence = run.get("evidence") or {}
        bound = {
            entry.get("path"): entry
            for entry in evidence.get("files", [])
            if isinstance(entry, dict)
        }
        artifact_file = validated_artifact_files.get(run.get("runId", ""), {}).get(
            evidence_file
        )
        journal_file = bound.get(evidence_file)
        if (
            not isinstance(journal_file, dict)
            or journal_file.get("size", 0) <= 0
            or not isinstance(artifact_file, dict)
            or artifact_file.get("size") != journal_file.get("size")
            or artifact_file.get("sha256") != journal_file.get("sha256")
        ):
            codes.append("GUARDRAIL_EVIDENCE_MISSING")
            errors.append(
                "guardrail evidence is absent, empty, or not artifact-verified: "
                + fix["fixId"]
            )
            continue
        item.update(
            {
                "ok": True,
                "sourcePath": source_path,
                "caseId": case_id,
                "evidenceFile": evidence_file,
            }
        )
    return sorted(set(codes)), errors, report


def audit_report(campaign: Campaign) -> Dict[str, Any]:
    errors: List[str] = []
    rejection_codes: List[str] = []
    artifact_errors, checked, validated_artifact_files = audit_artifacts(campaign)
    errors.extend(artifact_errors)
    catalog_drift = (
        campaign.adapter.catalog_fingerprint != campaign.state["catalogFingerprint"]
    )
    if catalog_drift:
        errors.append("adapter catalog drift detected")
        rejection_codes.append("CATALOG_DRIFT")
    current_source: Optional[str] = None
    source_observation: Optional[Dict[str, Any]] = None
    try:
        source_observation = campaign.current_source_observation()
        current_source = source_observation["fingerprint"]
    except CampaignError as exc:
        errors.append("current source fingerprint unavailable: " + public_message(exc))
        rejection_codes.append("SOURCE_OBSERVATION_FAILED")
    if not campaign.snapshot_consistent:
        errors.append("state.json does not match journal replay")
        rejection_codes.append("JOURNAL_PROJECTION_MISMATCH")
    if not campaign.summary_consistent:
        errors.append("summary.json does not match journal replay")
        rejection_codes.append("JOURNAL_PROJECTION_MISMATCH")

    final_id = campaign.state.get("finalRegressionAttemptId")
    final_attempt: Optional[Dict[str, Any]] = None
    if final_id:
        try:
            final_attempt = get_attempt(campaign.state, final_id)
        except CampaignError:
            final_attempt = None
    all_required_passed = False
    same_baseline = False
    final_evidence = True
    if (
        final_attempt is None
        or final_attempt.get("mode") != "regression"
        or final_attempt.get("status") != "PASS"
    ):
        errors.append("no successful final regression attempt")
        rejection_codes.append("FINAL_REGRESSION_REQUIRED")
        if any(
            attempt.get("mode") == "quick"
            for attempt in campaign.state["attempts"]
        ):
            rejection_codes.append("FULL_REGRESSION_REQUIRED")
        if any(
            attempt.get("status") == "RETEST_PASSED"
            for attempt in campaign.state["attempts"]
        ):
            rejection_codes.append("RETEST_WITHOUT_FULL_REGRESSION")
    else:
        run_by_case = {
            run["caseId"]: run
            for run in final_attempt.get("caseRuns", [])
            if run["status"] == "PASS"
        }
        runnable_ids = runnable_case_ids(campaign)
        all_required_passed = all(case_id in run_by_case for case_id in runnable_ids)
        if not all_required_passed:
            errors.append(
                "a required or runnable optional case lacks PASS in final regression"
            )
            rejection_codes.append("REQUIRED_CASES_INCOMPLETE")
        baseline = final_attempt["sourceFingerprint"]
        same_baseline = current_source == baseline and all(
            run.get("sourceFingerprint") == baseline
            and run.get("sourceAfterFingerprint") == baseline
            for run in run_by_case.values()
        )
        if not same_baseline:
            errors.append("final regression does not share the current source baseline")
            rejection_codes.append("SOURCE_BASELINE_MISMATCH")
        for case_id in runnable_ids:
            run = run_by_case.get(case_id)
            if not run:
                final_evidence = False
                continue
            artifact = campaign.adapter.campaign_root / run["artifactDir"]
            contract = campaign.state["cases"][case_id].get("evidence") or {}
            try:
                evidence, _ = inspect_evidence(artifact, contract, redact_files=False)
            except CampaignError:
                evidence = {"missingFiles": ["<rejected>"], "emptyFiles": []}
            if evidence["missingFiles"] or evidence["emptyFiles"]:
                final_evidence = False
        if not final_evidence:
            errors.append("final regression evidence is incomplete")
            rejection_codes.append("EVIDENCE_INCOMPLETE")

    handoff_codes, handoff_errors, handoff_report = review_handoff_audit(
        campaign,
        current_source,
        final_attempt,
        source_observation,
    )
    rejection_codes.extend(handoff_codes)
    errors.extend(handoff_errors)

    trace_codes, trace_errors, trace_report = traceability_audit(
        campaign,
        final_attempt,
        current_source,
        source_observation,
        validated_artifact_files,
    )
    rejection_codes.extend(trace_codes)
    errors.extend(trace_errors)
    trace_report["reviewHandoffs"] = handoff_report

    if current_source is not None and final_attempt is not None:
        for attempt in campaign.state["attempts"]:
            if (
                attempt["mode"] == "regression"
                and attempt["status"] == "PASS"
                and attempt["id"] != final_id
            ):
                if attempt.get("sourceFingerprint") == current_source:
                    errors.append(
                        "more than one successful regression shares the current source baseline"
                    )
                    rejection_codes.append("DUPLICATE_FINAL_BASELINE")

    if source_observation is not None:
        try:
            if campaign.current_source_observation() != source_observation:
                errors.append("source changed while the audit was in progress")
                rejection_codes.append("SOURCE_CHANGED_DURING_AUDIT")
        except CampaignError as exc:
            errors.append(
                "source stability recheck failed: " + public_message(exc)
            )
            rejection_codes.append("SOURCE_CHANGED_DURING_AUDIT")

    unresolved_statuses = {"RUNNING", "FAILED", "BLOCKED", "INTERRUPTED"}
    no_unresolved = (
        campaign.state["status"] == "COMPLETE"
        and campaign.state.get("pendingFix") is None
        and campaign.state.get("currentAttemptId") is None
        and not any(
            attempt["status"] in unresolved_statuses
            for attempt in campaign.state["attempts"]
            if attempt["id"] == final_id
        )
    )
    if not no_unresolved:
        errors.append("campaign has unresolved state")
        rejection_codes.append("UNRESOLVED_STATE")
    journal_replayable = True
    evidence_complete = not artifact_errors and final_evidence
    if artifact_errors:
        rejection_codes.append("ARTIFACT_INVALID")
    ok = bool(
        all_required_passed
        and same_baseline
        and no_unresolved
        and evidence_complete
        and journal_replayable
        and not catalog_drift
        and not errors
    )
    if not ok and not rejection_codes:
        rejection_codes.append("AUDIT_INCOMPLETE")
    return {
        "ok": ok,
        "campaignId": campaign.state["campaignId"],
        "status": campaign.state["status"],
        "executionStatus": campaign.state["status"],
        "completionStatus": completion_status(campaign, audit_ok=ok),
        "traceabilityMode": campaign_traceability_mode(campaign),
        "coverage": campaign_coverage(campaign),
        "allRequiredPassed": all_required_passed,
        "sameBaseline": same_baseline,
        "noUnresolvedState": no_unresolved,
        "evidenceComplete": evidence_complete,
        "journalReplayable": journal_replayable,
        "catalogDrift": catalog_drift,
        "finalRegressionAttemptId": final_id,
        "checkedArtifactRuns": checked,
        "traceability": trace_report,
        "rejectionCodes": sorted(set(rejection_codes)),
        "errors": errors,
    }


__all__ = [
    "adapter_traceability_mode",
    "audit_artifacts",
    "audit_report",
    "campaign_traceability_mode",
    "campaign_coverage",
    "completion_status",
    "status_report",
]
