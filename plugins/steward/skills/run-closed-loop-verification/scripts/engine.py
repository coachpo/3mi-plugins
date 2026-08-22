"""Campaign state-machine orchestration.

Adapter validation, durable journal state, command execution, artifact audit,
and CLI composition live in their responsibility modules.
"""

from __future__ import annotations

import copy
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adapter_paths import (
    normalize_relative,
    path_has_symlink_component,
    platform_supported,
    rebind_review_request_source,
    resolve_project_path,
    review_manifest_source_binding_errors,
    source_file_metadata,
    source_snapshot,
    source_snapshot_changed_paths,
    validate_pinned_review_request,
)
from journal_state import Campaign
from model import (
    INITIAL_PASS_STATUSES,
    CampaignError,
    assert_persistable,
    read_json,
    read_regular_bytes,
    review_case_candidate_sha256,
    sha256_bytes,
)
from runner_evidence import (
    execute_case,
    record_blocked_case,
)
from semantic_review import (
    SemanticReviewError,
    load_review_manifest,
    review_manifest_sha256,
)


def dependency_reason(campaign: Campaign, case: Dict[str, Any]) -> Optional[str]:
    for dependency in case.get("dependsOn", []):
        state_case = campaign.state["cases"][dependency]
        if state_case["status"] not in INITIAL_PASS_STATUSES:
            return "dependency not passed: " + dependency
    return None


def finish_attempt(
    campaign: Campaign,
    attempt_id: str,
    status: str,
    campaign_status: str,
    source_fingerprint: Optional[str] = None,
    reason: Optional[str] = None,
    clear_pending_fix: bool = False,
    resume_mode: Optional[str] = None,
) -> None:
    attempt_mode = next(
        attempt["mode"]
        for attempt in campaign.state["attempts"]
        if attempt["id"] == attempt_id
    )
    if resume_mode is None and status in {"FAILED", "BLOCKED"}:
        # A failed or blocked attempt retains its own phase as the durable
        # continuation. Successful transitions set the next phase explicitly;
        # a completed regression intentionally has no continuation.
        resume_mode = attempt_mode
    campaign.commit(
        "attempt_finished",
        {
            "attemptId": attempt_id,
            "status": status,
            "campaignStatus": campaign_status,
            "currentSourceFingerprint": source_fingerprint
            or campaign.state["currentSourceFingerprint"],
            "reason": reason,
            "clearPendingFix": clear_pending_fix,
            "resumeMode": resume_mode,
        },
    )


def fail_closed_source_drift(
    campaign: Campaign,
    attempt_id: str,
    expected: str,
    actual: Optional[str],
    resume_mode: str = "initial",
) -> Dict[str, Any]:
    reason = "source fingerprint drifted during execution"
    finish_attempt(
        campaign,
        attempt_id,
        "BLOCKED",
        "BLOCKED",
        # Preserve the replay projection: case_finished records its observed
        # post-run source, while drift detected before a case leaves the prior
        # fingerprint current. Neither path authorizes another attempt here.
        source_fingerprint=campaign.state["currentSourceFingerprint"],
        reason=reason,
        resume_mode=resume_mode,
    )
    return campaign.summary()


def blocked_retry_consumed(campaign: Campaign) -> bool:
    if not campaign.state["attempts"]:
        return False
    latest = campaign.state["attempts"][-1]
    previous_id = latest.get("resumedFrom")
    if latest.get("status") != "BLOCKED" or not previous_id:
        return False
    previous = next(
        (item for item in campaign.state["attempts"] if item["id"] == previous_id),
        None,
    )
    return bool(
        previous
        and previous.get("status") == "BLOCKED"
        and previous.get("mode") == latest.get("mode")
        and previous.get("targetCaseId") == latest.get("targetCaseId")
    )


def blocked_requires_new_root(campaign: Campaign) -> bool:
    if not campaign.state["attempts"]:
        return False
    reason = str(
        campaign.state["attempts"][-1].get("lastOutcome", {}).get("reason") or ""
    ).lower()
    return (
        "source drift" in reason
        or "source fingerprint drift" in reason
        or "catalog" in reason
    )


def _strict_review_snapshot(campaign: Campaign) -> Optional[Dict[str, Any]]:
    snapshot = campaign.state.get("traceSnapshot")
    findings = snapshot.get("reviewFindings") if isinstance(snapshot, dict) else None
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


def require_effective_review_source(campaign: Campaign) -> None:
    """Fail before execution when the latest strict Review binding is stale."""

    findings = _strict_review_snapshot(campaign)
    if findings is None:
        return
    effective = findings["attestation"].get("sourceFingerprint")
    fixes = [
        fix
        for fix in campaign.state.get("fixes", [])
        if not isinstance(fix.get("supersession"), dict)
    ]
    if fixes:
        handoff = fixes[-1].get("reviewHandoff")
        effective = (
            handoff.get("sourceFingerprint")
            if isinstance(handoff, dict)
            else None
        )
    source_observation = campaign.current_source_observation()
    current = source_observation["fingerprint"]
    pending = campaign.state.get("pendingFix")
    active_fix = fixes[-1] if fixes else None
    if (
        isinstance(active_fix, dict)
        and not isinstance(active_fix.get("reviewHandoff"), dict)
        and isinstance(pending, dict)
        and pending.get("fixId") == active_fix.get("fixId")
    ):
        if current == pending.get("fixedSourceFingerprint"):
            raise CampaignError(
                "REVIEW_HANDOFF_REQUIRED: the pending attested fix requires record-review before execution"
            )
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: source changed after the pending fix; run supersede-fix for the exact pending fix, then record a new fix audit and fresh Review handoff"
        )
    if effective != current:
        if isinstance(pending, dict) and pending.get("fixId") == (
            fixes[-1].get("fixId") if fixes else None
        ):
            raise CampaignError(
                "REVIEW_HANDOFF_DRIFT: source changed after the pending fix/Review binding; run supersede-fix for the exact pending fix, then record a new fix audit and fresh Review handoff"
            )
        raise CampaignError(
            "REVIEW_HANDOFF_REQUIRED: the effective semantic Review does not bind the current source; record an authorized fix and fresh Review handoff or initialize a new campaign"
        )
    handoff_error = _effective_review_handoff_error(
        campaign, source_observation
    )
    if handoff_error is not None:
        if isinstance(pending, dict) and pending.get("fixId") == (
            fixes[-1].get("fixId") if fixes else None
        ):
            raise CampaignError(
                "REVIEW_HANDOFF_DRIFT: "
                + handoff_error
                + "; run supersede-fix for the exact pending fix, then record a new fix audit and fresh Review handoff"
            )
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: "
            + handoff_error
            + "; initialize a new campaign before further execution"
        )


def quick_dependency_reason(
    campaign: Campaign, attempt_id: str, case: Dict[str, Any]
) -> Optional[str]:
    attempt = next(
        item for item in campaign.state["attempts"] if item["id"] == attempt_id
    )
    outcomes = {item["caseId"]: item["status"] for item in attempt["caseRuns"]}
    skipped = {item["caseId"] for item in attempt["skippedCases"]}
    for dependency in case.get("dependsOn", []):
        if outcomes.get(dependency) != "PASS":
            suffix = " (not runnable)" if dependency in skipped else ""
            return "quick dependency not passed: " + dependency + suffix
    return None


def run_quick_locked(
    campaign: Campaign, resumed_from: Optional[str] = None
) -> Dict[str, Any]:
    """Run the adapter's feedback selection without satisfying full coverage."""

    campaign.ensure_catalog()
    require_effective_review_source(campaign)
    verification = getattr(campaign.adapter, "verification", None)
    if isinstance(verification, dict) and verification.get("tier") == "full":
        raise CampaignError(
            "quick phase is unavailable for a full-tier verification adapter"
        )
    state = campaign.state
    selected = [case for case in campaign.adapter.cases if case.get("quick", False)]
    if not selected:
        raise CampaignError("quick phase has no selected cases")
    if state["status"] == "FAILED":
        raise CampaignError(
            "campaign has a FAILED quick case; record a fix audit before retest"
        )
    if state["status"] == "BLOCKED" and resumed_from is None:
        raise CampaignError("restore the blocked prerequisite, then use resume")
    if state.get("currentAttemptId"):
        raise CampaignError(
            "campaign is already running; use resume after an interruption"
        )
    if state["status"] not in {"PENDING", "INTERRUPTED", "BLOCKED"}:
        raise CampaignError("quick phase is only available before full execution")
    expected = state["currentSourceFingerprint"]
    actual = campaign.current_source()
    if actual != expected:
        raise CampaignError(
            "source drift detected before quick execution; reinitialize or record a bound fix"
        )
    attempt_id = campaign.start_attempt("quick", actual, resumed_from=resumed_from)
    for ordinal, case in enumerate(campaign.adapter.cases, start=1):
        if not case.get("quick", False):
            continue
        before = campaign.current_source()
        if before != actual:
            return fail_closed_source_drift(
                campaign, attempt_id, actual, before, resume_mode="quick"
            )
        catalog_reason = campaign.catalog_drift_reason()
        if catalog_reason:
            finish_attempt(
                campaign,
                attempt_id,
                "BLOCKED",
                "BLOCKED",
                reason=catalog_reason,
                resume_mode="quick",
            )
            return campaign.summary()
        dependency = quick_dependency_reason(campaign, attempt_id, case)
        if dependency:
            if not case.get("required", True):
                campaign.commit(
                    "case_skipped",
                    {
                        "attemptId": attempt_id,
                        "caseId": case["id"],
                        "ordinal": ordinal,
                        "reason": dependency,
                    },
                )
                continue
            outcome = record_blocked_case(
                campaign, attempt_id, case, ordinal, actual, dependency
            )
        elif not platform_supported(case.get("platform", "any")):
            reason = "required platform is not available: " + str(case.get("platform"))
            if not case.get("required", True):
                campaign.commit(
                    "case_skipped",
                    {
                        "attemptId": attempt_id,
                        "caseId": case["id"],
                        "ordinal": ordinal,
                        "reason": reason,
                    },
                )
                continue
            outcome = record_blocked_case(
                campaign, attempt_id, case, ordinal, actual, reason
            )
        else:
            outcome = execute_case(
                campaign, attempt_id, case, ordinal, actual, "quick"
            )
        campaign.commit(
            "case_finished",
            {
                "attemptId": attempt_id,
                "runId": outcome["runId"],
                "caseId": outcome["caseId"],
                "ordinal": ordinal,
                "artifactDir": outcome["artifactDir"],
                "status": outcome["status"],
                "reason": outcome["reason"],
                "exitCode": outcome["exitCode"],
                "timedOut": outcome["timedOut"],
                "evidence": outcome["evidence"],
                "stdoutSha256": outcome["stdoutSha256"],
                "stderrSha256": outcome["stderrSha256"],
                "sourceFingerprint": outcome["sourceFingerprint"],
                "sourceAfterFingerprint": outcome["sourceAfterFingerprint"],
                "artifactManifest": outcome["artifactManifest"],
            },
        )
        after = outcome["sourceAfterFingerprint"]
        if after is None or after != actual:
            return fail_closed_source_drift(
                campaign, attempt_id, actual, after, resume_mode="quick"
            )
        if outcome["status"] != "PASS":
            finish_attempt(
                campaign,
                attempt_id,
                outcome["status"],
                outcome["status"],
                source_fingerprint=actual,
                reason=outcome["reason"],
                resume_mode="quick",
            )
            return campaign.summary()
    finish_attempt(
        campaign,
        attempt_id,
        "PASS",
        "PENDING",
        source_fingerprint=actual,
        resume_mode="initial",
    )
    return campaign.summary()


def run_initial_locked(
    campaign: Campaign, resumed_from: Optional[str] = None
) -> Dict[str, Any]:
    campaign.ensure_catalog()
    require_effective_review_source(campaign)
    state = campaign.state
    if state["status"] == "FAILED":
        raise CampaignError(
            "campaign has a FAILED case; record a fix audit before retest"
        )
    if state["status"] == "BLOCKED" and resumed_from is None:
        raise CampaignError("restore the blocked prerequisite, then use resume")
    if state["currentAttemptId"] and state["status"] in (
        "REGRESSION_RUNNING",
        "RUNNING",
    ):
        raise CampaignError(
            "campaign is already running; use resume after an interruption"
        )
    if state["status"] == "COMPLETE":
        raise CampaignError(
            "campaign is complete; start a new campaign for a new initial round"
        )
    expected = state["currentSourceFingerprint"]
    actual = campaign.current_source()
    if actual != expected:
        raise CampaignError(
            "source drift detected before initial execution; reinitialize or record a bound fix"
        )
    attempt_id = campaign.start_attempt("initial", actual, resumed_from=resumed_from)
    for ordinal, case in enumerate(campaign.adapter.cases, start=1):
        state_case = campaign.state["cases"][case["id"]]
        if state_case["status"] in INITIAL_PASS_STATUSES:
            continue
        if (
            state_case["status"] == "NOT_RUN"
            and state_case["terminalSkip"]
            and not state_case["required"]
        ):
            continue
        before = campaign.current_source()
        if before != actual:
            return fail_closed_source_drift(campaign, attempt_id, actual, before)
        catalog_reason = campaign.catalog_drift_reason()
        if catalog_reason:
            finish_attempt(
                campaign, attempt_id, "BLOCKED", "BLOCKED", reason=catalog_reason
            )
            return campaign.summary()
        dependency = dependency_reason(campaign, case)
        if dependency:
            if not case.get("required", True):
                campaign.commit(
                    "case_skipped",
                    {
                        "attemptId": attempt_id,
                        "caseId": case["id"],
                        "ordinal": ordinal,
                        "reason": dependency,
                    },
                )
                continue
            outcome = record_blocked_case(
                campaign, attempt_id, case, ordinal, actual, dependency
            )
        elif not platform_supported(case.get("platform", "any")):
            reason = "required platform is not available: " + str(case.get("platform"))
            if not case.get("required", True):
                campaign.commit(
                    "case_skipped",
                    {
                        "attemptId": attempt_id,
                        "caseId": case["id"],
                        "ordinal": ordinal,
                        "reason": reason,
                    },
                )
                continue
            outcome = record_blocked_case(
                campaign, attempt_id, case, ordinal, actual, reason
            )
        else:
            outcome = execute_case(
                campaign, attempt_id, case, ordinal, actual, "initial"
            )
        campaign.commit(
            "case_finished",
            {
                "attemptId": attempt_id,
                "runId": outcome["runId"],
                "caseId": outcome["caseId"],
                "ordinal": ordinal,
                "artifactDir": outcome["artifactDir"],
                "status": outcome["status"],
                "reason": outcome["reason"],
                "exitCode": outcome["exitCode"],
                "timedOut": outcome["timedOut"],
                "evidence": outcome["evidence"],
                "stdoutSha256": outcome["stdoutSha256"],
                "stderrSha256": outcome["stderrSha256"],
                "sourceFingerprint": outcome["sourceFingerprint"],
                "sourceAfterFingerprint": outcome["sourceAfterFingerprint"],
                "artifactManifest": outcome["artifactManifest"],
            },
        )
        after = outcome["sourceAfterFingerprint"]
        if after is None or after != actual:
            return fail_closed_source_drift(campaign, attempt_id, actual, after)
        if outcome["status"] != "PASS":
            finish_attempt(
                campaign,
                attempt_id,
                outcome["status"],
                outcome["status"],
                source_fingerprint=actual,
                reason=outcome["reason"],
            )
            return campaign.summary()

    if campaign.initial_complete():
        finish_attempt(
            campaign,
            attempt_id,
            "PASS",
            "READY_FOR_REGRESSION",
            source_fingerprint=actual,
            resume_mode="regression",
        )
    else:
        finish_attempt(
            campaign,
            attempt_id,
            "PASS",
            "RUNNING",
            source_fingerprint=actual,
            resume_mode="initial",
        )
    return campaign.summary()


def run_regression_locked(
    campaign: Campaign, resumed_from: Optional[str] = None
) -> Dict[str, Any]:
    campaign.ensure_catalog()
    require_effective_review_source(campaign)
    status = campaign.state["status"]
    if campaign.state.get("currentAttemptId") and status in (
        "RUNNING",
        "REGRESSION_RUNNING",
    ):
        raise CampaignError(
            "campaign is already running; use resume after an interruption"
        )
    if status == "FAILED":
        raise CampaignError(
            "resolve the current FAILED case with record-fix and retest first"
        )
    if status == "BLOCKED" and resumed_from is None:
        raise CampaignError("restore the blocked prerequisite, then use resume")
    if status not in (
        "READY_FOR_REGRESSION",
        "REGRESSION_RUNNING",
        "INTERRUPTED",
        "BLOCKED",
    ):
        raise CampaignError(
            "clean regression requires all initial required cases to be complete"
        )
    campaign.ensure_catalog()
    require_effective_review_source(campaign)
    baseline = campaign.current_source()
    attempt_id = campaign.start_attempt(
        "regression", baseline, resumed_from=resumed_from
    )
    for ordinal, case in enumerate(campaign.adapter.cases, start=1):
        before = campaign.current_source()
        if before != baseline:
            campaign.commit(
                "attempt_invalidated",
                {
                    "attemptId": attempt_id,
                    "reason": "source drifted before regression case",
                    "sourceBeforeFingerprint": baseline,
                    "sourceAfterFingerprint": before,
                    "campaignStatus": "BLOCKED",
                },
            )
            return campaign.summary()
        catalog_reason = campaign.catalog_drift_reason()
        if catalog_reason:
            campaign.commit(
                "attempt_invalidated",
                {
                    "attemptId": attempt_id,
                    "reason": catalog_reason,
                    "sourceBeforeFingerprint": baseline,
                    "sourceAfterFingerprint": before,
                    "campaignStatus": "BLOCKED",
                },
            )
            return campaign.summary()
        dependency = dependency_reason(campaign, case)
        if dependency:
            if not case.get("required", True):
                campaign.commit(
                    "case_skipped",
                    {
                        "attemptId": attempt_id,
                        "caseId": case["id"],
                        "ordinal": ordinal,
                        "reason": dependency,
                    },
                )
                continue
            outcome = record_blocked_case(
                campaign, attempt_id, case, ordinal, baseline, dependency
            )
        elif not platform_supported(case.get("platform", "any")):
            reason = "required platform is not available: " + str(
                case.get("platform")
            )
            if not case.get("required", True):
                campaign.commit(
                    "case_skipped",
                    {
                        "attemptId": attempt_id,
                        "caseId": case["id"],
                        "ordinal": ordinal,
                        "reason": reason,
                    },
                )
                continue
            outcome = record_blocked_case(
                campaign, attempt_id, case, ordinal, baseline, reason
            )
        else:
            outcome = execute_case(
                campaign, attempt_id, case, ordinal, baseline, "regression"
            )
        campaign.commit(
            "case_finished",
            {
                "attemptId": attempt_id,
                "runId": outcome["runId"],
                "caseId": outcome["caseId"],
                "ordinal": ordinal,
                "artifactDir": outcome["artifactDir"],
                "status": outcome["status"],
                "reason": outcome["reason"],
                "exitCode": outcome["exitCode"],
                "timedOut": outcome["timedOut"],
                "evidence": outcome["evidence"],
                "stdoutSha256": outcome["stdoutSha256"],
                "stderrSha256": outcome["stderrSha256"],
                "sourceFingerprint": outcome["sourceFingerprint"],
                "sourceAfterFingerprint": outcome["sourceAfterFingerprint"],
                "artifactManifest": outcome["artifactManifest"],
            },
        )
        after = outcome["sourceAfterFingerprint"]
        if after is None or after != baseline:
            campaign.commit(
                "attempt_invalidated",
                {
                    "attemptId": attempt_id,
                    "reason": "source drifted during regression case",
                    "sourceBeforeFingerprint": baseline,
                    "sourceAfterFingerprint": after,
                    "campaignStatus": "BLOCKED",
                },
            )
            return campaign.summary()
        if outcome["status"] != "PASS":
            finish_attempt(
                campaign,
                attempt_id,
                outcome["status"],
                outcome["status"],
                source_fingerprint=baseline,
                reason=outcome["reason"],
            )
            return campaign.summary()
    final_source = campaign.current_source()
    if final_source != baseline:
        campaign.commit(
            "attempt_invalidated",
            {
                "attemptId": attempt_id,
                "reason": "source drifted before regression completion",
                "sourceBeforeFingerprint": baseline,
                "sourceAfterFingerprint": final_source,
                "campaignStatus": "BLOCKED",
            },
        )
        return campaign.summary()
    catalog_reason = campaign.catalog_drift_reason()
    if catalog_reason:
        campaign.commit(
            "attempt_invalidated",
            {
                "attemptId": attempt_id,
                "reason": catalog_reason,
                "sourceBeforeFingerprint": baseline,
                "sourceAfterFingerprint": final_source,
                "campaignStatus": "BLOCKED",
            },
        )
        return campaign.summary()
    finish_attempt(
        campaign, attempt_id, "PASS", "COMPLETE", source_fingerprint=baseline
    )
    return campaign.summary()


def latest_failed_run(
    state: Dict[str, Any],
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]]:
    for attempt in reversed(state["attempts"]):
        for case_run in reversed(attempt.get("caseRuns", [])):
            if case_run.get("status") == "FAILED":
                case_state = state["cases"][case_run["caseId"]]
                return attempt, case_run, case_state
    return None


def load_fix(path: Path) -> Dict[str, Any]:
    if path_has_symlink_component(path):
        raise CampaignError("fix audit path uses a symlink/reparse path")
    value = read_json(path)
    if not isinstance(value, dict):
        raise CampaignError("fix audit must be a JSON object")
    assert_persistable(value)
    return value


def fix_minimal_evidence(fix: Dict[str, Any]) -> List[str]:
    value = fix.get("minimalRegression")
    if isinstance(value, dict):
        evidence = value.get("evidence", [])
    else:
        evidence = fix.get("minimalRegressionEvidence", [])
    if not isinstance(evidence, list) or any(
        not isinstance(item, str) or not item.strip() for item in evidence
    ):
        return []
    return evidence


def record_fix_locked(campaign: Campaign, fix: Dict[str, Any]) -> Dict[str, Any]:
    campaign.ensure_catalog()
    if campaign.state["status"] != "FAILED":
        raise CampaignError("record-fix requires a current FAILED campaign")
    latest = latest_failed_run(campaign.state)
    if latest is None:
        raise CampaignError("no failed case is available for a fix audit")
    attempt, case_run, _ = latest
    fields = (
        "failedCaseId",
        "failedRound",
        "failedAttemptId",
        "failedSourceFingerprint",
        "fixedSourceFingerprint",
        "rootCause",
        "changedFiles",
        "fixSummary",
    )
    for field in fields:
        if field not in fix:
            raise CampaignError("fix audit missing " + field)
    if fix["failedCaseId"] != case_run["caseId"]:
        raise CampaignError("fix audit failedCaseId does not match the latest failure")
    if attempt["mode"] == "retest":
        origin = next(
            (
                item
                for item in reversed(campaign.state["fixes"])
                if item.get("failedCaseId") == case_run["caseId"]
                and item.get("fixedSourceFingerprint") == case_run["sourceFingerprint"]
            ),
            None,
        )
        if origin is None:
            raise CampaignError("failed retest lacks original failure provenance")
        expected_round = origin["failedRound"]
    else:
        expected_round = (
            attempt["mode"]
            if attempt["mode"] in {"quick", "regression"}
            else "initial"
        )
    if fix["failedRound"] != expected_round:
        raise CampaignError("fix audit failedRound does not match the failed attempt")
    if fix["failedAttemptId"] != attempt["id"]:
        raise CampaignError(
            "fix audit failedAttemptId does not match the latest failure"
        )
    if fix["failedSourceFingerprint"] != case_run["sourceFingerprint"]:
        raise CampaignError(
            "fix audit failedSourceFingerprint does not match the failed case"
        )
    source_observation = campaign.current_source_observation()
    current_source = source_observation["fingerprint"]
    fixed_source_snapshot = source_snapshot(
        campaign.adapter, source_observation
    )
    failed_source_snapshot = attempt.get("sourceSnapshot")
    if not isinstance(failed_source_snapshot, dict):
        raise CampaignError(
            "failed attempt lacks a schema-4 source snapshot; choose a new campaign root"
        )
    if (
        failed_source_snapshot.get("fingerprint")
        != fix["failedSourceFingerprint"]
        or failed_source_snapshot.get("provider")
        != fixed_source_snapshot.get("provider")
        or failed_source_snapshot.get("excludes")
        != fixed_source_snapshot.get("excludes")
    ):
        raise CampaignError("fix audit source snapshot provenance is invalid")
    actual_changed_files, _control_changes = source_snapshot_changed_paths(
        failed_source_snapshot, fixed_source_snapshot
    )
    source_inventory = set(fixed_source_snapshot["projectPaths"])
    observed_source_files = {
        entry["path"]: {key: value for key, value in entry.items() if key != "path"}
        for entry in source_observation["files"]
    }
    if fix["fixedSourceFingerprint"] != current_source:
        raise CampaignError(
            "fix audit fixedSourceFingerprint must match current source"
        )
    external_condition = fix.get("externalCondition", False)
    if not isinstance(external_condition, bool):
        raise CampaignError("fix audit externalCondition must be a boolean")
    if (
        not external_condition
        and fix["fixedSourceFingerprint"] == fix["failedSourceFingerprint"]
    ):
        raise CampaignError(
            "non-external fix must change the source fingerprint"
        )
    if not isinstance(fix["rootCause"], str) or not fix["rootCause"].strip():
        raise CampaignError("fix audit rootCause must be non-empty")
    if not isinstance(fix["fixSummary"], str) or not fix["fixSummary"].strip():
        raise CampaignError("fix audit fixSummary must be non-empty")
    changed_files = fix["changedFiles"]
    if not isinstance(changed_files, list) or any(
        not isinstance(item, str) for item in changed_files
    ):
        raise CampaignError("fix audit changedFiles must be a string array")
    normalized_changed_files: List[str] = []
    for item in changed_files:
        relative = normalize_relative(item, "fix audit changed file")
        if relative == "." or relative not in (
            set(failed_source_snapshot["projectPaths"])
            | set(fixed_source_snapshot["projectPaths"])
        ):
            raise CampaignError(
                "fix audit changedFiles entries must be in the source inventory at the failed or fixed baseline"
            )
        normalized_changed_files.append(relative)
    if len(normalized_changed_files) != len(set(normalized_changed_files)):
        raise CampaignError("fix audit changedFiles must not contain duplicates")
    normalized_changed_files = sorted(normalized_changed_files)
    if normalized_changed_files != actual_changed_files:
        raise CampaignError(
            "fix audit changedFiles must exactly match added, modified, deleted, and mode-changed source paths"
        )
    if not actual_changed_files and not external_condition:
        raise CampaignError("empty changedFiles requires externalCondition=true")
    evidence = fix_minimal_evidence(fix)
    if not evidence:
        raise CampaignError("fix audit requires minimalRegression evidence")
    traceable = campaign.adapter.traceability is not None
    violated_invariant: Optional[Any] = None
    root_cause_source: Optional[Dict[str, Any]] = None
    resolved_finding_ids: List[str] = []
    permanent_guardrail: Optional[Dict[str, Any]] = None
    if traceable:
        for field in (
            "violatedInvariant",
            "rootCauseSource",
            "resolvedFindingIds",
            "permanentGuardrail",
        ):
            if field not in fix:
                raise CampaignError("traceable fix audit missing " + field)
        failed_case = campaign.adapter.case_by_id[case_run["caseId"]]
        violated_raw = fix["violatedInvariant"]
        if isinstance(violated_raw, str):
            if violated_raw not in campaign.adapter.hard_invariant_ids:
                raise CampaignError(
                    "fix audit violatedInvariant must name a triggered hard invariant"
                )
            if violated_raw not in failed_case.get("coversInvariants", []):
                raise CampaignError(
                    "fix audit violatedInvariant is not covered by the failed case"
                )
            violated_invariant = violated_raw
        elif isinstance(violated_raw, dict):
            if (
                set(violated_raw) != {"notApplicable", "technicalReason"}
                or violated_raw.get("notApplicable") is not True
                or not isinstance(violated_raw.get("technicalReason"), str)
                or not violated_raw["technicalReason"].strip()
                or failed_case.get("coversInvariants", [])
            ):
                raise CampaignError(
                    "fix audit violatedInvariant fallback requires an invariant-free failed case and technicalReason"
                )
            violated_invariant = dict(violated_raw)
        else:
            raise CampaignError(
                "fix audit violatedInvariant must name a triggered hard invariant or use a technical fallback"
            )
        root_cause_source_raw = fix["rootCauseSource"]
        if not isinstance(root_cause_source_raw, dict):
            raise CampaignError("fix audit rootCauseSource must be an object")
        allowed_source_fields = {"path", "lineStart", "lineEnd", "symbol"}
        if (
            not {"path", "lineStart", "lineEnd"}.issubset(root_cause_source_raw)
            or set(root_cause_source_raw) - allowed_source_fields
            or type(root_cause_source_raw.get("lineStart")) is not int
            or type(root_cause_source_raw.get("lineEnd")) is not int
            or root_cause_source_raw["lineStart"] < 1
            or root_cause_source_raw["lineEnd"]
            < root_cause_source_raw["lineStart"]
        ):
            raise CampaignError("fix audit rootCauseSource shape is invalid")
        symbol = root_cause_source_raw.get("symbol")
        if symbol is not None and (
            not isinstance(symbol, str)
            or not symbol.strip()
            or symbol != symbol.strip()
            or any(character in symbol for character in "\r\n\x00")
        ):
            raise CampaignError("fix audit rootCauseSource symbol is invalid")
        root_cause_path = normalize_relative(
            root_cause_source_raw.get("path"), "fix audit rootCauseSource.path"
        )
        if root_cause_path == "." or root_cause_path not in source_inventory:
            raise CampaignError(
                "fix audit rootCauseSource.path must be in the source inventory"
            )
        resolved_root_cause_path = resolve_project_path(
            campaign.adapter.project_root,
            root_cause_path,
            "fix audit rootCauseSource.path",
        )
        if (
            path_has_symlink_component(
                campaign.adapter.project_root / root_cause_path
            )
            or not resolved_root_cause_path.is_file()
        ):
            raise CampaignError(
                "fix audit rootCauseSource.path must be a regular non-link file"
            )
        root_cause_content = read_regular_bytes(
            resolved_root_cause_path,
            label="fix audit rootCauseSource.path",
            max_bytes=16 * 1024 * 1024,
        )
        expected_root_cause = observed_source_files.get(root_cause_path)
        if (
            expected_root_cause is None
            or expected_root_cause.get("status") != "present"
            or expected_root_cause.get("sha256")
            != sha256_bytes(root_cause_content)
            or source_file_metadata(campaign.adapter, root_cause_path)
            != expected_root_cause
        ):
            raise CampaignError(
                "fix audit rootCauseSource.path changed after source fingerprinting"
            )
        line_count = len(root_cause_content.splitlines())
        if root_cause_source_raw["lineEnd"] > line_count:
            raise CampaignError("fix audit rootCauseSource line range is out of bounds")
        root_cause_source = {
            "path": root_cause_path,
            "lineStart": root_cause_source_raw["lineStart"],
            "lineEnd": root_cause_source_raw["lineEnd"],
        }
        if symbol is not None:
            root_cause_source["symbol"] = symbol
        resolved_raw = fix["resolvedFindingIds"]
        if (
            not isinstance(resolved_raw, list)
            or any(not isinstance(item, str) for item in resolved_raw)
            or len(resolved_raw) != len(set(resolved_raw))
            or not set(resolved_raw).issubset(
                set(failed_case.get("reviewFindingIds", []))
            )
        ):
            raise CampaignError(
                "fix audit resolvedFindingIds must be unique review findings linked to the failed case"
            )
        resolved_finding_ids = list(resolved_raw)
        guardrail = fix["permanentGuardrail"]
        if not isinstance(guardrail, dict):
            raise CampaignError("fix audit permanentGuardrail must be an object")
        if guardrail.get("notApplicable") is True:
            if set(guardrail) != {"notApplicable", "technicalReason"} or not isinstance(
                guardrail.get("technicalReason"), str
            ) or not guardrail["technicalReason"].strip():
                raise CampaignError(
                    "not-applicable guardrail requires a technicalReason"
                )
            permanent_guardrail = dict(guardrail)
        else:
            expected_guardrail_fields = {
                "kind",
                "sourcePath",
                "caseId",
                "evidenceFile",
            }
            if set(guardrail) != expected_guardrail_fields or guardrail.get(
                "kind"
            ) not in {"test", "guard", "rule", "adversarial-case"}:
                raise CampaignError("fix audit permanentGuardrail shape is invalid")
            guardrail_case_id = guardrail.get("caseId")
            guardrail_case = campaign.adapter.case_by_id.get(guardrail_case_id)
            if not guardrail_case or not guardrail_case.get("required", True):
                raise CampaignError(
                    "permanent guardrail caseId must name a required case"
                )
            if isinstance(violated_invariant, str) and violated_invariant not in (
                guardrail_case.get("coversInvariants", [])
            ):
                raise CampaignError(
                    "permanent guardrail case must cover the violated invariant"
                )
            if not set(resolved_finding_ids).issubset(
                set(guardrail_case.get("reviewFindingIds", []))
            ):
                raise CampaignError(
                    "permanent guardrail case must cover every resolved review finding"
                )
            evidence_file = normalize_relative(
                guardrail.get("evidenceFile"), "permanent guardrail evidenceFile"
            )
            if evidence_file not in (guardrail_case.get("evidence") or {}).get(
                "nonEmptyFiles", []
            ):
                raise CampaignError(
                    "permanent guardrail evidenceFile must be declared non-empty evidence"
                )
            source_path = normalize_relative(
                guardrail.get("sourcePath"), "permanent guardrail sourcePath"
            )
            if source_path == "." or source_path not in source_inventory:
                raise CampaignError(
                    "permanent guardrail sourcePath must be in the source inventory"
                )
            resolved_source_path = resolve_project_path(
                campaign.adapter.project_root,
                source_path,
                "permanent guardrail sourcePath",
            )
            if (
                path_has_symlink_component(
                    campaign.adapter.project_root / source_path
                )
                or not resolved_source_path.is_file()
            ):
                raise CampaignError(
                    "permanent guardrail sourcePath must be a regular non-link file"
                )
            expected_guardrail_source = observed_source_files.get(source_path)
            if (
                expected_guardrail_source is None
                or expected_guardrail_source.get("status") != "present"
                or source_file_metadata(campaign.adapter, source_path)
                != expected_guardrail_source
            ):
                raise CampaignError(
                    "permanent guardrail sourcePath changed after source fingerprinting"
                )
            permanent_guardrail = {
                "kind": guardrail["kind"],
                "sourcePath": source_path,
                "caseId": guardrail_case_id,
                "evidenceFile": evidence_file,
            }
    fix_id = "fix-" + uuid.uuid4().hex[:12]
    payload = {
        "fixId": fix_id,
        "failedCaseId": fix["failedCaseId"],
        "failedRound": fix["failedRound"],
        "failedAttemptId": fix["failedAttemptId"],
        "failedSourceFingerprint": fix["failedSourceFingerprint"],
        "fixedSourceFingerprint": fix["fixedSourceFingerprint"],
        "rootCause": fix["rootCause"],
        "changedFiles": sorted(normalized_changed_files),
        "fixSummary": fix["fixSummary"],
        "externalCondition": external_condition,
        "minimalRegressionEvidence": evidence,
        "violatedInvariant": violated_invariant,
        "rootCauseSource": root_cause_source,
        "resolvedFindingIds": resolved_finding_ids,
        "permanentGuardrail": permanent_guardrail,
        "fixedSourceSnapshot": fixed_source_snapshot,
        "changedFilesVerified": True,
    }
    if campaign.current_source_observation() != source_observation:
        raise CampaignError("source changed while the fix audit was being validated")
    campaign.commit("fix_recorded", payload)
    return campaign.summary()


def _handoff_manifest_relative(campaign: Campaign, path: Path) -> tuple[str, Path]:
    """Resolve a handoff manifest without accepting aliases or campaign files."""

    try:
        project_root = Path(
            os.path.realpath(str(campaign.adapter.project_root.absolute()))
        )
        supplied = path if path.is_absolute() else project_root / path
        if path_has_symlink_component(supplied.absolute()):
            raise CampaignError(
                "REVIEW_HANDOFF_DRIFT: review manifest path uses a symlink/reparse component"
            )
        lexical = Path(os.path.realpath(str(supplied.absolute())))
        relative = lexical.relative_to(project_root).as_posix()
    except CampaignError:
        raise
    except (OSError, ValueError) as exc:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: review manifest must be inside projectRoot"
        ) from exc
    relative = normalize_relative(relative, "review handoff manifest")
    if relative == ".":
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: review manifest must name a project file"
        )
    resolved = resolve_project_path(
        campaign.adapter.project_root, relative, "review handoff manifest"
    )
    if (
        path_has_symlink_component(campaign.adapter.project_root / relative)
        or not resolved.is_file()
    ):
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: review manifest must be a regular non-link file"
        )
    try:
        resolved.relative_to(campaign.adapter.campaign_root)
    except ValueError:
        pass
    else:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: review manifest cannot be inside campaignRoot"
        )
    return relative, resolved


def _expected_post_fix_review_request(
    campaign: Campaign,
    source_observation: Dict[str, Any],
    supplied: Optional[Path],
) -> Dict[str, Any]:
    """Build or read the trusted request binding for a post-fix Review."""

    findings = _strict_review_snapshot(campaign)
    if findings is None:
        raise CampaignError(
            "REVIEW_REQUEST_REQUIRED: campaign lacks an initialized Review request"
        )
    initial = validate_pinned_review_request(
        findings["reviewRequest"],
        "initialized Review request",
    )
    source_fingerprint = source_observation["fingerprint"]
    deterministic = initial["target"]["kind"] == "source"
    if supplied is None:
        if not deterministic:
            raise CampaignError(
                "REVIEW_REQUEST_REQUIRED: diff-target record-review requires "
                "--expected-review-request"
            )
        return rebind_review_request_source(
            initial,
            source_fingerprint,
            "post-fix Review request",
        )

    relative, expected_path = _handoff_manifest_relative(campaign, supplied)
    if relative in set(source_observation.get("projectPaths", [])):
        raise CampaignError(
            "REVIEW_REQUEST_MISMATCH: expected Review request file must be "
            "excluded from the source fingerprint"
        )
    expected = validate_pinned_review_request(
        read_json(expected_path),
        "expected post-fix Review request",
    )
    if deterministic:
        derived = rebind_review_request_source(
            initial,
            source_fingerprint,
            "post-fix Review request",
        )
        if expected != derived:
            raise CampaignError(
                "REVIEW_REQUEST_MISMATCH: supplied post-fix source request does "
                "not exactly match the deterministic binding"
            )
        return expected

    initial_target = initial["target"]
    expected_target = expected["target"]
    if (
        expected_target["kind"] != "diff"
        or expected_target["sourceFingerprint"] != source_fingerprint
        or expected_target["baseIdentity"] != initial_target["baseIdentity"]
        or expected["requestedPaths"] != initial["requestedPaths"]
    ):
        raise CampaignError(
            "REVIEW_REQUEST_MISMATCH: supplied post-fix diff request must "
            "preserve kind, base identity, and requested paths while binding "
            "the fixed source"
        )
    return expected


def _effective_review_handoff_error(
    campaign: Campaign,
    source_observation: Dict[str, Any],
) -> Optional[str]:
    """Return the first error for the latest non-superseded handoff."""

    active_fix = next(
        (
            fix
            for fix in reversed(campaign.state.get("fixes", []))
            if not isinstance(fix.get("supersession"), dict)
        ),
        None,
    )
    if active_fix is None:
        return None
    handoff = active_fix.get("reviewHandoff")
    if not isinstance(handoff, dict):
        return "the active attested fix lacks a Review handoff"
    relative = handoff.get("manifestPath")
    if not isinstance(relative, str):
        return "the active Review handoff path is invalid"
    try:
        expected_request = validate_pinned_review_request(
            handoff.get("reviewRequest"),
            "active Review handoff request",
        )
        observed_relative, manifest_path = _handoff_manifest_relative(
            campaign, Path(relative)
        )
        if observed_relative != relative:
            return "the active Review handoff path is not canonical"
        manifest = load_review_manifest(
            manifest_path,
            project_root=campaign.adapter.project_root,
            verify_baseline=True,
            expected_review_request=expected_request,
        )
    except (CampaignError, SemanticReviewError, OSError) as exc:
        return "the active Review handoff cannot be revalidated: " + str(exc)
    attestation = getattr(manifest, "attestation", None)
    if attestation is None:
        return "the active Review handoff lacks an attestation"
    fresh_errors = review_manifest_source_binding_errors(
        campaign.adapter,
        source_observation,
        manifest,
        require_attestation=True,
    )
    if fresh_errors:
        return fresh_errors[0]
    finding_ids = sorted(item.id for item in manifest.findings)
    required_ids = sorted(item.id for item in manifest.findings if item.required)
    resolution_states = {
        item.id: item.resolution_state for item in manifest.findings
    }
    candidate_digests = {
        item.id: review_case_candidate_sha256(item.case_candidate)
        for item in manifest.findings
    }
    scope = [
        {"path": item.path, "sha256": item.sha256}
        for item in attestation.scope
    ]
    observed = {
        "manifestSha256": review_manifest_sha256(manifest),
        "sourceFingerprint": attestation.source_fingerprint,
        "goalContractSha256": attestation.goal_contract_sha256,
        "invariantsSha256": attestation.invariants_sha256,
        "outcome": attestation.outcome,
        "scope": scope,
        "findingIds": finding_ids,
        "requiredFindingIds": required_ids,
        "resolutionStates": dict(sorted(resolution_states.items())),
        "caseCandidateSha256s": dict(sorted(candidate_digests.items())),
        "reviewRequest": copy.deepcopy(expected_request),
        "reviewRequestSha256": expected_request["requestSha256"],
        "bindingsVerified": True,
    }
    expected = {field: handoff.get(field) for field in observed}
    if observed != expected:
        return "the active Review handoff digest or semantic binding changed"
    return None


def supersede_fix_locked(campaign: Campaign, fix_id: str) -> Dict[str, Any]:
    """Invalidate one stale strict Review/fix binding without erasing history."""

    campaign.ensure_catalog()
    findings_snapshot = _strict_review_snapshot(campaign)
    if findings_snapshot is None:
        raise CampaignError(
            "REVIEW_HANDOFF_REQUIRED: supersede-fix requires a request-bound traceable campaign"
        )
    pending = campaign.state.get("pendingFix")
    if (
        campaign.state.get("status") != "FAILED"
        or campaign.state.get("currentAttemptId") is not None
        or not isinstance(pending, dict)
    ):
        raise CampaignError(
            "REVIEW_HANDOFF_REQUIRED: supersede-fix requires a closed FAILED campaign with a pending fix"
        )
    if pending.get("fixId") != fix_id:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: supersede-fix --fix-id does not match the pending fix"
        )
    handoff = pending.get("reviewHandoff")
    before = campaign.current_source_observation()
    current_source = before["fingerprint"]
    source_changed = current_source != pending.get("fixedSourceFingerprint")
    handoff_error = (
        _effective_review_handoff_error(campaign, before)
        if isinstance(handoff, dict)
        else None
    )
    if source_changed:
        reason = "source-drift"
    elif isinstance(handoff, dict) and handoff_error is not None:
        reason = "review-manifest-drift"
    else:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: supersede-fix requires source drift or a verified stale Review manifest"
        )
    payload = {
        "fixId": fix_id,
        "fixedSourceFingerprint": pending["fixedSourceFingerprint"],
        "reason": reason,
        "reviewManifestSha256": (
            handoff["manifestSha256"] if isinstance(handoff, dict) else None
        ),
        "supersedingSourceFingerprint": current_source,
    }
    if campaign.current_source_observation() != before:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: source changed while supersede-fix validated the stale binding"
        )
    campaign.commit("pending_fix_superseded", payload)
    return campaign.summary()


def record_review_locked(
    campaign: Campaign,
    path: Path,
    expected_request_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Bind a fresh, current-source Review attestation to the pending fix."""

    campaign.ensure_catalog()
    snapshot = campaign.state.get("traceSnapshot")
    findings_snapshot = _strict_review_snapshot(campaign)
    if findings_snapshot is None:
        raise CampaignError(
            "REVIEW_HANDOFF_REQUIRED: record-review requires a request-bound traceable campaign"
        )
    pending = campaign.state.get("pendingFix")
    if (
        campaign.state.get("status") != "FAILED"
        or campaign.state.get("currentAttemptId") is not None
        or not isinstance(pending, dict)
    ):
        raise CampaignError(
            "REVIEW_HANDOFF_REQUIRED: record-review requires a closed FAILED campaign with a pending fix"
        )
    if isinstance(pending.get("reviewHandoff"), dict):
        raise CampaignError(
            "REVIEW_HANDOFF_REQUIRED: the pending fix already has a Review handoff"
        )
    relative, manifest_path = _handoff_manifest_relative(campaign, path)
    initial_review_path = (
        campaign.state.get("catalog", {})
        .get("traceability", {})
        .get("reviewFindings", {})
        .get("path")
    )
    if relative == initial_review_path:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: a handoff must not replace the initialized Review manifest"
        )
    if any(
        fix.get("reviewHandoff", {}).get("manifestPath") == relative
        for fix in campaign.state.get("fixes", [])
        if isinstance(fix.get("reviewHandoff"), dict)
    ):
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: each fix requires a distinct handoff manifest path"
        )

    before = campaign.current_source_observation()
    if relative in set(before.get("projectPaths", [])):
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: review handoff manifest must be excluded from the source fingerprint"
        )
    expected_request = _expected_post_fix_review_request(
        campaign,
        before,
        expected_request_path,
    )
    try:
        manifest = load_review_manifest(
            manifest_path,
            project_root=campaign.adapter.project_root,
            verify_baseline=True,
            expected_review_request=expected_request,
        )
    except SemanticReviewError as exc:
        code = (
            "REVIEW_HANDOFF_INCOMPLETE"
            if getattr(exc, "code", "") == "REVIEW_ATTESTATION_INCOMPLETE"
            else "REVIEW_HANDOFF_DRIFT"
        )
        raise CampaignError(code + ": " + str(exc)) from exc
    attestation = getattr(manifest, "attestation", None)
    if attestation is None:
        raise CampaignError(
            "REVIEW_HANDOFF_REQUIRED: post-fix Review manifest lacks an attestation"
        )
    if attestation.outcome == "incomplete":
        raise CampaignError(
            "REVIEW_HANDOFF_INCOMPLETE: post-fix semantic Review is incomplete"
        )
    if attestation.outcome not in {"findings", "no-findings"}:
        raise CampaignError(
            "REVIEW_HANDOFF_INCOMPLETE: post-fix semantic Review outcome is not complete"
        )
    fresh_binding_errors = review_manifest_source_binding_errors(
        campaign.adapter,
        before,
        manifest,
        require_attestation=True,
    )
    if fresh_binding_errors:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: " + fresh_binding_errors[0]
        )
    current_source = before["fingerprint"]
    if current_source != pending.get("fixedSourceFingerprint"):
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: source changed after record-fix; run supersede-fix for the exact pending fix, then record a new fix audit and fresh Review handoff"
        )
    if attestation.source_fingerprint != current_source:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: Review attestation does not bind the fixed source fingerprint"
        )
    expected_goal = snapshot["goalContract"]["sha256"]
    expected_invariants = snapshot["invariants"]["sha256"]
    if (
        attestation.goal_contract_sha256 != expected_goal
        or attestation.invariants_sha256 != expected_invariants
    ):
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: Review attestation does not bind the pinned authorities"
        )
    finding_ids = sorted(item.id for item in manifest.findings)
    required_ids = sorted(item.id for item in manifest.findings if item.required)
    resolution_states = {
        item.id: item.resolution_state for item in manifest.findings
    }
    candidate_digests = {
        item.id: review_case_candidate_sha256(item.case_candidate)
        for item in manifest.findings
    }
    if (
        finding_ids != findings_snapshot.get("findingIds")
        or required_ids != findings_snapshot.get("requiredFindingIds")
        or candidate_digests != findings_snapshot.get("caseCandidateSha256s")
    ):
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: Review finding IDs, required flags, or case candidates differ from the initialized Review"
        )
    unresolved = sorted(
        finding_id
        for finding_id in pending.get("resolvedFindingIds", [])
        if resolution_states.get(finding_id) not in {"resolved", "invalidated"}
    )
    if unresolved:
        raise CampaignError(
            "REVIEW_HANDOFF_INCOMPLETE: fix-resolved findings remain open: "
            + ", ".join(unresolved)
        )
    scope = [
        {"path": item.path, "sha256": item.sha256}
        for item in attestation.scope
    ]
    unbound_scope = sorted(
        item["path"]
        for item in scope
        if item["path"] not in set(before.get("projectPaths", []))
    )
    if unbound_scope:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: Review attestation scope is not source-fingerprint bound: "
            + ", ".join(unbound_scope)
        )
    payload = {
        "fixId": pending["fixId"],
        "manifestPath": relative,
        "manifestSha256": review_manifest_sha256(manifest),
        "sourceFingerprint": current_source,
        "goalContractSha256": expected_goal,
        "invariantsSha256": expected_invariants,
        "outcome": attestation.outcome,
        "scope": scope,
        "findingIds": finding_ids,
        "requiredFindingIds": required_ids,
        "resolutionStates": dict(sorted(resolution_states.items())),
        "caseCandidateSha256s": dict(sorted(candidate_digests.items())),
        "reviewRequest": copy.deepcopy(expected_request),
        "reviewRequestSha256": expected_request["requestSha256"],
        "bindingsVerified": True,
    }
    if campaign.current_source_observation() != before:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: source changed while record-review validated the handoff"
        )
    try:
        stable_manifest = load_review_manifest(
            manifest_path,
            project_root=campaign.adapter.project_root,
            verify_baseline=True,
            expected_review_request=expected_request,
        )
    except SemanticReviewError as exc:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: review manifest changed before handoff recording: "
            + str(exc)
        ) from exc
    if review_manifest_sha256(stable_manifest) != payload["manifestSha256"]:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: review manifest changed before handoff recording"
        )
    if campaign.current_source_observation() != before:
        raise CampaignError(
            "REVIEW_HANDOFF_DRIFT: source changed before handoff recording"
        )
    campaign.commit("review_handoff_recorded", payload)
    return campaign.summary()


def retest_locked(
    campaign: Campaign, resumed_from: Optional[str] = None
) -> Dict[str, Any]:
    campaign.ensure_catalog()
    pending = campaign.state.get("pendingFix")
    if not pending:
        raise CampaignError("retest requires a recorded fix audit")
    findings_snapshot = _strict_review_snapshot(campaign)
    if findings_snapshot is not None and not isinstance(
        pending.get("reviewHandoff"), dict
    ):
        raise CampaignError(
            "REVIEW_HANDOFF_REQUIRED: request-bound campaigns require record-review before retest"
        )
    if campaign.state["status"] not in (
        {"FAILED", "BLOCKED", "INTERRUPTED"} if resumed_from else {"FAILED"}
    ):
        raise CampaignError("retest requires the campaign to be FAILED")
    require_effective_review_source(campaign)
    current_source = campaign.current_source()
    if current_source != pending["fixedSourceFingerprint"]:
        raise CampaignError(
            "source changed after record-fix in an unattested campaign; preserve "
            "this campaign and initialize a new campaign root"
        )
    case_id = pending["failedCaseId"]
    case = campaign.adapter.case_by_id[case_id]
    attempt_id = campaign.start_attempt(
        "retest", current_source, resumed_from=resumed_from, target_case_id=case_id
    )
    dependency = (
        None if pending.get("failedRound") == "quick" else dependency_reason(campaign, case)
    )
    if dependency:
        outcome = record_blocked_case(
            campaign, attempt_id, case, 1, current_source, dependency
        )
    elif not platform_supported(case.get("platform", "any")):
        outcome = record_blocked_case(
            campaign,
            attempt_id,
            case,
            1,
            current_source,
            "required platform is not available: " + str(case.get("platform")),
        )
    else:
        outcome = execute_case(campaign, attempt_id, case, 1, current_source, "retest")
    retest_status = (
        "RETEST_PASSED" if outcome["status"] == "PASS" else outcome["status"]
    )
    campaign.commit(
        "case_finished",
        {
            "attemptId": attempt_id,
            "runId": outcome["runId"],
            "caseId": outcome["caseId"],
            "ordinal": 1,
            "artifactDir": outcome["artifactDir"],
            "status": retest_status,
            "reason": outcome["reason"],
            "exitCode": outcome["exitCode"],
            "timedOut": outcome["timedOut"],
            "evidence": outcome["evidence"],
            "stdoutSha256": outcome["stdoutSha256"],
            "stderrSha256": outcome["stderrSha256"],
            "sourceFingerprint": outcome["sourceFingerprint"],
            "sourceAfterFingerprint": outcome["sourceAfterFingerprint"],
            "artifactManifest": outcome["artifactManifest"],
        },
    )
    after = outcome["sourceAfterFingerprint"]
    if after is None or after != current_source:
        finish_attempt(
            campaign,
            attempt_id,
            "BLOCKED",
            "BLOCKED",
            source_fingerprint=campaign.state["currentSourceFingerprint"],
            reason="source fingerprint drifted during retest",
            resume_mode="retest",
        )
        return campaign.summary()
    if retest_status != "RETEST_PASSED":
        finish_attempt(
            campaign,
            attempt_id,
            retest_status,
            retest_status,
            source_fingerprint=current_source,
            reason=outcome["reason"],
            clear_pending_fix=retest_status == "FAILED",
        )
        return campaign.summary()
    initial_done = campaign.initial_complete()
    failed_round = pending["failedRound"]
    if failed_round == "quick":
        finish_attempt(
            campaign,
            attempt_id,
            "RETEST_PASSED",
            "PENDING",
            source_fingerprint=current_source,
            clear_pending_fix=True,
            resume_mode="quick",
        )
        return run_quick_locked(campaign, resumed_from=attempt_id)
    if failed_round == "regression":
        finish_attempt(
            campaign,
            attempt_id,
            "RETEST_PASSED",
            "READY_FOR_REGRESSION",
            source_fingerprint=current_source,
            clear_pending_fix=True,
            resume_mode="regression",
        )
        return campaign.summary()
    next_status = "READY_FOR_REGRESSION" if initial_done else "RUNNING"
    finish_attempt(
        campaign,
        attempt_id,
        "RETEST_PASSED",
        next_status,
        source_fingerprint=current_source,
        clear_pending_fix=True,
        resume_mode="initial" if next_status == "RUNNING" else "regression",
    )
    if next_status == "RUNNING":
        return run_initial_locked(campaign, resumed_from=attempt_id)
    return campaign.summary()


def resume_locked(campaign: Campaign) -> Dict[str, Any]:
    campaign.ensure_catalog()
    status = campaign.state["status"]
    if status == "COMPLETE":
        # Completion has no next phase. Resume is an idempotent observation;
        # the caller still has to run the public audit command before claiming
        # final completion.
        return campaign.summary()
    resumed_from = campaign.state.get("currentAttemptId")
    pending_invalidation = campaign.state.get("pendingRegressionInvalidation")
    if pending_invalidation is not None:
        campaign.commit(
            "attempt_invalidated",
            {
                "attemptId": pending_invalidation["attemptId"],
                "reason": "source drifted during regression case",
                "sourceBeforeFingerprint": pending_invalidation[
                    "sourceBeforeFingerprint"
                ],
                "sourceAfterFingerprint": pending_invalidation[
                    "sourceAfterFingerprint"
                ],
                "campaignStatus": "BLOCKED",
            },
        )
        return campaign.summary()
    if status in ("RUNNING", "REGRESSION_RUNNING"):
        if campaign.state.get("currentAttemptId") is not None:
            campaign.mark_interrupted()
            status = campaign.state["status"]
    if status == "FAILED":
        if campaign.state.get("pendingFix"):
            raise CampaignError(
                "a fix audit is recorded; use retest rather than resume"
            )
        raise CampaignError("resume cannot bypass a FAILED case")
    if status == "BLOCKED":
        if blocked_requires_new_root(campaign):
            raise CampaignError(
                "source or catalog drift invalidated this campaign; choose a new campaign root"
            )
        if blocked_retry_consumed(campaign):
            return campaign.summary()
    mode = campaign.state.get("resumeMode")
    if mode is None and status == "PENDING" and not campaign.state["attempts"]:
        # A freshly initialized campaign intentionally has no prior phase to
        # resume, but `resume` is also its documented ordinary-initial entry.
        mode = "initial"
    attempts = campaign.state["attempts"]
    if (
        resumed_from is None
        and mode in {"quick", "initial", "regression"}
        and attempts
        and attempts[-1]["status"] == "RETEST_PASSED"
    ):
        # A successful retest is the durable checkpoint for every continuation
        # phase. A crash between closing the retest and opening that phase must
        # bind the new attempt to the latest retest, not an older same-mode run.
        resumed_from = attempts[-1]["id"]
    if mode == "retest":
        if resumed_from is None:
            candidates = [
                a for a in campaign.state["attempts"] if a["mode"] == "retest"
            ]
            resumed_from = candidates[-1]["id"] if candidates else None
        return retest_locked(campaign, resumed_from=resumed_from)
    if mode == "quick":
        if resumed_from is None:
            candidates = [a for a in campaign.state["attempts"] if a["mode"] == "quick"]
            resumed_from = candidates[-1]["id"] if candidates else None
        return run_quick_locked(campaign, resumed_from=resumed_from)
    if mode == "regression":
        if resumed_from is None:
            candidates = [
                a for a in campaign.state["attempts"] if a["mode"] == "regression"
            ]
            resumed_from = candidates[-1]["id"] if candidates else None
        return run_regression_locked(campaign, resumed_from=resumed_from)
    if mode == "initial":
        if resumed_from is None:
            candidates = [a for a in attempts if a["mode"] == "initial"]
            resumed_from = candidates[-1]["id"] if candidates else None
        return run_initial_locked(campaign, resumed_from=resumed_from)
    raise CampaignError("no resumable campaign mode is recorded")
