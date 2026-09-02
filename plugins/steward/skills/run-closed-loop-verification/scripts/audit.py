"""Status and final same-source acceptance audit."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

from adapter_paths import (
    current_platform,
    normalize_relative,
    observe_source,
    path_uses_symlink,
    platform_supported_on,
)
from journal_state import Campaign
from model import (
    ARTIFACT_MANIFEST_VERSION,
    JOURNAL_SCHEMA_VERSION,
    SCRIPT_VERSION,
    CampaignError,
    canonical_bytes,
    read_json,
    read_regular_bytes,
    sha256_bytes,
)
from runner_evidence import (
    MAX_ARTIFACT_FILE_BYTES,
    MAX_ARTIFACT_FILES,
    MAX_ARTIFACT_TOTAL_BYTES,
    artifact_metadata_is_reparse,
    artifact_tree_entries,
)


def completion_status(campaign: Campaign, *, audit_ok: bool | None) -> str:
    if audit_ok is True:
        return "COMPLETE"
    if campaign.state["status"] == "BLOCKED":
        return "BLOCKED"
    if campaign.state["status"] == "AUDIT_REQUIRED":
        return "AUDIT_REQUIRED"
    return "INCOMPLETE"


def _final_attempt(campaign: Campaign) -> dict[str, Any] | None:
    attempt_id = campaign.state.get("finalRegressionAttemptId")
    if not attempt_id:
        return None
    return next(
        (item for item in campaign.state["attempts"] if item["id"] == attempt_id),
        None,
    )


def criterion_coverage(campaign: Campaign) -> list[dict[str, Any]]:
    final = _final_attempt(campaign)
    final_pass = {
        run["caseId"]
        for run in (final or {}).get("runs", [])
        if run["status"] == "PASS"
    }
    configured = [
        {
            "id": criterion,
            "requiredCaseIds": [
                case["id"]
                for case in campaign.state["cases"]
                if case["required"] and criterion in case["coversCriteria"]
            ],
        }
        for criterion in campaign.state["goalSnapshot"]["criteriaIds"]
    ]
    return [
        {
            **item,
            "finalPassingCaseIds": [
                case_id for case_id in item["requiredCaseIds"] if case_id in final_pass
            ],
        }
        for item in configured
    ]


def campaign_coverage(campaign: Campaign) -> dict[str, Any]:
    final = _final_attempt(campaign)
    final_statuses = {
        run["caseId"]: run["status"] for run in (final or {}).get("runs", [])
    }
    return {
        "criteria": criterion_coverage(campaign),
        "cases": [
            {
                "id": case["id"],
                "required": case["required"],
                "runnable": platform_supported_on(
                    case["platform"], campaign.state["runtimePlatform"]
                ),
                "finalStatus": final_statuses.get(case["id"]),
            }
            for case in campaign.state["cases"]
        ],
    }


def failure_fix_context(
    campaign: Campaign,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if campaign.state["status"] != "FAILED":
        return None, None
    for attempt in reversed(campaign.state["attempts"]):
        for run in reversed(attempt["runs"]):
            if run["status"] != "FAILED":
                continue
            failure_signature = sha256_bytes(
                canonical_bytes(
                    {
                        "caseId": run["caseId"],
                        "reason": run.get("reason"),
                        "exitCode": run.get("exitCode"),
                        "timedOut": run.get("timedOut"),
                        "evidence": run.get("evidence"),
                    }
                )
            )
            return (
                {
                    "attemptId": attempt["id"],
                    "runId": run["runId"],
                    "caseId": run["caseId"],
                    "round": attempt["mode"],
                    "sourceFingerprint": run["sourceFingerprint"],
                    "failureSignature": failure_signature,
                },
                {
                    "failedAttemptId": attempt["id"],
                    "failedRunId": run["runId"],
                    "failedCaseId": run["caseId"],
                    "failedRound": attempt["mode"],
                    "failureSignature": failure_signature,
                    "failedSourceFingerprint": campaign.state["sourceBaseline"][
                        "fingerprint"
                    ],
                    "affectedCriteria": list(
                        campaign.adapter.case_by_id[run["caseId"]]["coversCriteria"]
                    ),
                },
            )
    return None, None


def status_report(campaign: Campaign) -> dict[str, Any]:
    current_source: str | None = None
    source_error: str | None = None
    try:
        current_source = observe_source(campaign.adapter)["fingerprint"]
    except CampaignError as exc:
        source_error = str(exc)
    current_audit: dict[str, Any] | None = None
    if campaign.state["status"] == "COMPLETE":
        current_audit = audit_report(campaign)
    latest_failure, fix_context = failure_fix_context(campaign)
    return {
        "schemaId": "steward.closed-loop-status",
        "schemaVersion": JOURNAL_SCHEMA_VERSION,
        "kernelVersion": SCRIPT_VERSION,
        "executionStatus": campaign.state["status"],
        "completionStatus": completion_status(
            campaign,
            audit_ok=(current_audit["ok"] if current_audit is not None else None),
        ),
        "resumeMode": campaign.state["resumeMode"],
        "repairCount": campaign.state["repairCount"],
        "goalContract": campaign.state["goalSnapshot"],
        "goalWorkspaceValid": not campaign.adapter.goal_workspace_errors,
        "goalWorkspaceErrors": campaign.adapter.goal_workspace_errors,
        "sourceFingerprint": campaign.state["sourceBaseline"]["fingerprint"],
        "currentSourceFingerprint": current_source,
        "sourceObservationError": source_error,
        "catalogFingerprint": campaign.state["adapterFingerprint"],
        "currentCatalogFingerprint": campaign.adapter.catalog_fingerprint,
        "worktreeBinding": campaign.state["worktreeBinding"],
        "currentWorktreeBinding": campaign.adapter.worktree_binding,
        "worktreeBindingConsistent": campaign.worktree_binding_consistent,
        "runtimePlatform": campaign.state["runtimePlatform"],
        "currentRuntimePlatform": current_platform(),
        "runtimePlatformConsistent": campaign.runtime_platform_consistent,
        "successfulAudit": campaign.state["successfulAudit"],
        "currentAuditRejectionCodes": (
            current_audit["rejectionCodes"] if current_audit is not None else []
        ),
        "latestFailure": latest_failure,
        "fixContext": fix_context,
        "coverage": campaign_coverage(campaign),
    }


def _audit_binding_errors(campaign: Campaign) -> list[str]:
    binding = campaign.state.get("successfulAudit")
    if campaign.state["status"] == "AUDIT_REQUIRED":
        return (
            []
            if binding is None
            else ["audit binding exists before durable completion"]
        )
    if campaign.state["status"] != "COMPLETE":
        return (
            [] if binding is None else ["audit binding exists in a non-complete state"]
        )
    if not isinstance(binding, dict) or set(binding) != {
        "finalRegressionAttemptId",
        "currentSourceFingerprint",
        "catalogFingerprint",
        "eventSequence",
        "eventHash",
    }:
        return ["durable audit binding has invalid fields"]
    expected = {
        "finalRegressionAttemptId": campaign.state["finalRegressionAttemptId"],
        "currentSourceFingerprint": campaign.state["sourceBaseline"]["fingerprint"],
        "catalogFingerprint": campaign.state["adapterFingerprint"],
        "eventSequence": campaign.state["lastSequence"],
        "eventHash": campaign.state["lastEventHash"],
    }
    if binding != expected:
        return ["durable audit binding does not match final campaign authority"]
    event = campaign.events[binding["eventSequence"] - 1]
    if (
        event["type"] != "audit_succeeded"
        or event["eventHash"] != binding["eventHash"]
        or event["payload"]
        != {
            "finalRegressionAttemptId": binding["finalRegressionAttemptId"],
            "currentSourceFingerprint": binding["currentSourceFingerprint"],
            "catalogFingerprint": binding["catalogFingerprint"],
        }
    ):
        return ["durable audit binding does not match its journal event"]
    return []


def _stream_digest(path: Path) -> tuple[int, str]:
    content = read_regular_bytes(
        path, label="campaign artifact", max_bytes=MAX_ARTIFACT_FILE_BYTES
    )
    return len(content), sha256_bytes(content)


def _artifact_errors(campaign: Campaign, run: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    binding = run.get("artifactManifest")
    if not isinstance(binding, dict) or set(binding) != {
        "relativePath",
        "size",
        "sha256",
    }:
        return ["run has an invalid artifact-manifest binding"]
    relative = binding["relativePath"]
    if not isinstance(relative, str) or not relative.endswith(
        "/artifact-manifest.json"
    ):
        return ["run artifact-manifest path is invalid"]
    try:
        if normalize_relative(relative, "artifact-manifest path") != relative:
            return ["run artifact-manifest path is invalid"]
    except CampaignError:
        return ["run artifact-manifest path is invalid"]
    manifest_path = campaign.adapter.campaign_root / relative
    if path_uses_symlink(manifest_path, campaign.adapter.campaign_root):
        return ["run artifact-manifest path uses a symlink/reparse point"]
    try:
        size, digest = _stream_digest(manifest_path)
    except CampaignError as exc:
        return [str(exc)]
    if size != binding["size"] or digest != binding["sha256"]:
        errors.append("artifact-manifest binding does not match disk")
    try:
        manifest = read_json(manifest_path)
    except CampaignError as exc:
        return errors + [str(exc)]
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"artifactManifestVersion", "files"}
        or manifest.get("artifactManifestVersion") != ARTIFACT_MANIFEST_VERSION
        or not isinstance(manifest.get("files"), list)
    ):
        return errors + ["artifact manifest has invalid fields"]
    artifact_dir = manifest_path.parent
    try:
        entries = artifact_tree_entries(artifact_dir)
    except CampaignError as exc:
        return errors + [str(exc)]
    disk_files: set[str] = set()
    total = 0
    for path, metadata in entries:
        name = path.relative_to(artifact_dir).as_posix()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if (
            stat.S_ISLNK(metadata.st_mode)
            or artifact_metadata_is_reparse(metadata)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            errors.append("artifact tree contains an unsafe entry: " + name)
            continue
        disk_files.add(name)
        total += metadata.st_size
    if len(disk_files) > MAX_ARTIFACT_FILES or total > MAX_ARTIFACT_TOTAL_BYTES:
        errors.append("artifact tree exceeds safety bounds")
    declared: set[str] = set()
    for item in manifest["files"]:
        if not isinstance(item, dict) or set(item) != {
            "relativePath",
            "size",
            "sha256",
        }:
            errors.append("artifact manifest file entry is invalid")
            continue
        name = item["relativePath"]
        try:
            normalized_name = normalize_relative(name, "artifact manifest file")
        except CampaignError:
            normalized_name = None
        if (
            not isinstance(name, str)
            or normalized_name != name
            or name in declared
            or name in {"", ".", "..", "artifact-manifest.json"}
        ):
            errors.append("artifact manifest file path is invalid")
            continue
        declared.add(name)
        if path_uses_symlink(artifact_dir / name, artifact_dir):
            errors.append("artifact file path uses a symlink/reparse point: " + name)
            continue
        try:
            observed_size, observed_digest = _stream_digest(artifact_dir / name)
        except CampaignError as exc:
            errors.append(str(exc))
            continue
        if observed_size != item["size"] or observed_digest != item["sha256"]:
            errors.append("artifact file binding does not match disk: " + name)
    if disk_files != declared | {"artifact-manifest.json"}:
        errors.append("artifact tree differs from its manifest")
    try:
        result = read_json(artifact_dir / "result.json")
    except CampaignError as exc:
        errors.append(str(exc))
        result = None
    if not isinstance(result, dict):
        errors.append("case result is not a JSON object")
    else:
        for key, expected in {
            "schemaVersion": JOURNAL_SCHEMA_VERSION,
            "kernelVersion": SCRIPT_VERSION,
            "runId": run["runId"],
            "caseId": run["caseId"],
            "status": run["status"],
            "sourceFingerprintBefore": run["sourceFingerprint"],
            "sourceFingerprintAfter": run["sourceAfterFingerprint"],
            "stdoutSha256": run["stdoutSha256"],
            "stderrSha256": run["stderrSha256"],
        }.items():
            if result.get(key) != expected:
                errors.append("case result disagrees with journal field " + key)
    return errors


def _final_case_errors(
    campaign: Campaign, final: dict[str, Any]
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    codes: list[str] = []
    expected_ids = [case["id"] for case in campaign.adapter.cases]
    if (
        final.get("caseIds") != expected_ids
        or [run["caseId"] for run in final.get("runs", [])] != expected_ids
    ):
        errors.append(
            "final regression does not contain the complete ordered case catalog"
        )
        codes.append("REQUIRED_CASES_INCOMPLETE")
        return codes, errors
    baseline = campaign.state["sourceBaseline"]["fingerprint"]
    for case, run in zip(campaign.adapter.cases, final["runs"]):
        runnable = platform_supported_on(
            case["platform"], campaign.state["runtimePlatform"]
        )
        expected = "PASS" if case["required"] or runnable else "NOT_RUN"
        if run["status"] != expected:
            errors.append(
                "final regression case " + case["id"] + " has status " + run["status"]
            )
            codes.append("REQUIRED_CASES_INCOMPLETE")
        if (
            run["sourceFingerprint"] != baseline
            or run["sourceAfterFingerprint"] != baseline
        ):
            errors.append(
                "final regression case "
                + case["id"]
                + " is not bound to the final source"
            )
            codes.append("SOURCE_BASELINE_MISMATCH")
        artifact_errors = _artifact_errors(campaign, run)
        if artifact_errors:
            errors.extend(artifact_errors)
            codes.append("ARTIFACT_INVALID")
        if run["status"] == "PASS" and (
            run["evidence"].get("missingFiles") or run["evidence"].get("emptyFiles")
        ):
            errors.append("final regression evidence is incomplete for " + case["id"])
            codes.append("EVIDENCE_INCOMPLETE")
    return codes, errors


def audit_report(campaign: Campaign) -> dict[str, Any]:
    codes: list[str] = []
    errors: list[str] = []
    if (
        campaign.adapter.goal_errors
        or campaign.adapter.goal_snapshot != campaign.state["goalSnapshot"]
    ):
        codes.append("GOAL_CONTRACT_DRIFT")
        errors.append("the current GOAL contract differs from the initialized snapshot")
    if campaign.adapter.goal_workspace_errors:
        codes.append("GOAL_WORKSPACE_INVALID")
        errors.append("the current Steward GOAL workspace is invalid")
    if campaign.adapter.catalog_fingerprint != campaign.state["adapterFingerprint"]:
        codes.append("CATALOG_DRIFT")
        errors.append("the adapter differs from the initialized catalog")
    if not campaign.worktree_binding_consistent:
        codes.append("WORKTREE_BINDING_DRIFT")
        errors.append(
            "the current target worktree identity differs from initialization"
        )
    if not campaign.runtime_platform_consistent:
        codes.append("RUNTIME_PLATFORM_DRIFT")
        errors.append("the current runtime platform differs from initialization")
    binding_errors = _audit_binding_errors(campaign)
    if binding_errors:
        codes.append("AUDIT_BINDING_INVALID")
        errors.extend(binding_errors)
    current_source: str | None = None
    try:
        first = observe_source(campaign.adapter)["fingerprint"]
        second = observe_source(campaign.adapter)["fingerprint"]
        if first != second:
            codes.append("SOURCE_CHANGED_DURING_AUDIT")
            errors.append("source identity changed during audit")
        current_source = second
        if current_source != campaign.state["sourceBaseline"]["fingerprint"]:
            codes.append("SOURCE_BASELINE_MISMATCH")
            errors.append("current source differs from the campaign repair baseline")
    except CampaignError as exc:
        codes.append("SOURCE_OBSERVATION_FAILED")
        errors.append(str(exc))

    final = _final_attempt(campaign)
    if (
        final is None
        or final.get("mode") not in {"initial", "regression"}
        or final.get("status") != "AUDIT_REQUIRED"
    ):
        codes.append("FINAL_REGRESSION_REQUIRED")
        errors.append("a successful full regression is required")
    else:
        final_codes, final_errors = _final_case_errors(campaign, final)
        codes.extend(final_codes)
        errors.extend(final_errors)
    for criterion in criterion_coverage(campaign):
        if not criterion["finalPassingCaseIds"]:
            codes.append("CRITERION_UNCOVERED")
            errors.append(
                "GOAL criterion lacks a required final-PASS case: " + criterion["id"]
            )
    if campaign.state["status"] not in {"AUDIT_REQUIRED", "COMPLETE"}:
        codes.append("UNRESOLVED_STATE")
        errors.append("campaign is not ready for final audit")

    codes = sorted(set(codes))
    errors = sorted(set(errors))
    ok = not codes
    return {
        "schemaId": "steward.closed-loop-audit",
        "schemaVersion": JOURNAL_SCHEMA_VERSION,
        "kernelVersion": SCRIPT_VERSION,
        "ok": ok,
        "executionStatus": campaign.state["status"],
        "completionStatus": completion_status(campaign, audit_ok=ok),
        "resumeMode": campaign.state["resumeMode"],
        "rejectionCodes": codes,
        "errors": errors,
        "repairCount": campaign.state["repairCount"],
        "goalContract": campaign.state["goalSnapshot"],
        "goalWorkspaceValid": not campaign.adapter.goal_workspace_errors,
        "goalWorkspaceErrors": campaign.adapter.goal_workspace_errors,
        "sourceFingerprint": campaign.state["sourceBaseline"]["fingerprint"],
        "currentSourceFingerprint": current_source,
        "catalogFingerprint": campaign.state["adapterFingerprint"],
        "currentCatalogFingerprint": campaign.adapter.catalog_fingerprint,
        "worktreeBinding": campaign.state["worktreeBinding"],
        "currentWorktreeBinding": campaign.adapter.worktree_binding,
        "worktreeBindingConsistent": campaign.worktree_binding_consistent,
        "runtimePlatform": campaign.state["runtimePlatform"],
        "currentRuntimePlatform": current_platform(),
        "runtimePlatformConsistent": campaign.runtime_platform_consistent,
        "coverage": campaign_coverage(campaign),
        "finalRegressionAttemptId": campaign.state["finalRegressionAttemptId"],
        "successfulAudit": campaign.state["successfulAudit"],
    }


__all__ = [
    "audit_report",
    "campaign_coverage",
    "completion_status",
    "criterion_coverage",
    "failure_fix_context",
    "status_report",
]
