"""Fail-stop execution, evidence-bound repair recording, and recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from adapter_paths import (
    current_platform,
    normalize_relative,
    observe_source,
    platform_supported_on,
    source_snapshot_changed_entries,
)
from journal_state import Campaign
from model import (
    FIX_AUDIT_SCHEMA_VERSION,
    PASS_STATUSES,
    CampaignError,
    canonical_bytes,
    read_json,
    sha256_bytes,
    utc_now,
)
from runner_evidence import execute_case, record_blocked_case


def _attempt_id(campaign: Campaign, mode: str, source: str) -> str:
    ordinal = len(campaign.state["attempts"]) + 1
    return f"attempt-{ordinal:04d}-{mode}-{source[7:15]}"


def _latest_attempt(campaign: Campaign) -> dict[str, Any]:
    if not campaign.state["attempts"]:
        raise CampaignError("campaign has no attempt")
    return campaign.state["attempts"][-1]


def _initial_satisfied(campaign: Campaign) -> bool:
    for case in campaign.adapter.cases:
        status = campaign.state["caseStates"][case["id"]]["status"]
        if case["required"] and status not in PASS_STATUSES:
            return False
        if (
            not case["required"]
            and platform_supported_on(
                case["platform"], campaign.state["runtimePlatform"]
            )
            and status not in PASS_STATUSES
        ):
            return False
    return True


def _failed_finish(campaign: Campaign, attempt_id: str, status: str) -> dict[str, Any]:
    resume = "record-fix" if status == "FAILED" else None
    campaign.commit(
        "attempt_finished",
        {"attemptId": attempt_id, "status": status, "resumeMode": resume},
    )
    return campaign.summary()


def _invalidate(
    campaign: Campaign, attempt_id: str, reason: str, observed: str | None
) -> dict[str, Any]:
    campaign.commit(
        "source_invalidated",
        {
            "attemptId": attempt_id,
            "reason": reason,
            "observedSourceFingerprint": observed,
        },
    )
    return campaign.summary()


def _run_attempt(campaign: Campaign, mode: str, case_ids: list[str]) -> dict[str, Any]:
    if mode not in {"initial", "retest", "regression"}:
        raise CampaignError("attempt mode is invalid")
    if current_platform() != campaign.state["runtimePlatform"]:
        raise CampaignError(
            "RUNTIME_PLATFORM_DRIFT: runtime platform differs from initialization"
        )
    expected_source = campaign.state["sourceBaseline"]["fingerprint"]
    current = campaign.current_source()
    if current != expected_source:
        if mode == "regression":
            raise CampaignError(
                "source changed before regression; restore the recorded repair baseline"
            )
        raise CampaignError("source differs from the campaign repair baseline")

    attempt_id = _attempt_id(campaign, mode, expected_source)
    campaign.commit(
        "attempt_started",
        {
            "attemptId": attempt_id,
            "mode": mode,
            "sourceFingerprint": expected_source,
            "caseIds": case_ids,
        },
    )
    for ordinal, case_id in enumerate(case_ids, start=1):
        case = campaign.adapter.case_by_id[case_id]
        if not platform_supported_on(
            case["platform"], campaign.state["runtimePlatform"]
        ):
            status = "BLOCKED" if case["required"] else "NOT_RUN"
            result = record_blocked_case(
                campaign,
                attempt_id,
                case,
                ordinal,
                expected_source,
                "case platform is unavailable on this runtime",
                status=status,
            )
        else:
            result = execute_case(
                campaign, attempt_id, case, ordinal, expected_source, mode
            )
        campaign.commit("case_finished", result)
        if result["status"] in {"FAILED", "BLOCKED"}:
            if mode == "regression" and (
                result.get("sourceAfterFingerprint") != expected_source
                or "source fingerprint drifted" in str(result.get("reason"))
            ):
                return _invalidate(
                    campaign,
                    attempt_id,
                    "source changed during regression",
                    result.get("sourceAfterFingerprint"),
                )
            return _failed_finish(campaign, attempt_id, result["status"])

    if mode == "regression":
        status, resume = "AUDIT_REQUIRED", "audit"
    elif mode == "retest":
        failed_round = campaign.state["fixes"][-1]["failedRound"]
        if failed_round == "regression" or _initial_satisfied(campaign):
            status, resume = "READY_FOR_REGRESSION", "regression"
        else:
            status, resume = "PENDING", "initial"
    elif _initial_satisfied(campaign):
        complete_catalog = case_ids == [case["id"] for case in campaign.adapter.cases]
        if campaign.state["repairCount"] == 0 and complete_catalog:
            status, resume = "AUDIT_REQUIRED", "audit"
        else:
            status, resume = "READY_FOR_REGRESSION", "regression"
    else:
        status, resume = "PENDING", "initial"
    campaign.commit(
        "attempt_finished",
        {"attemptId": attempt_id, "status": status, "resumeMode": resume},
    )
    return campaign.summary()


def run_initial_locked(campaign: Campaign) -> dict[str, Any]:
    if campaign.state["status"] not in {"PENDING", "INTERRUPTED"}:
        raise CampaignError("initial execution is not available in the current state")
    if (
        campaign.state["status"] == "INTERRUPTED"
        and campaign.state["resumeMode"] != "initial"
    ):
        raise CampaignError("interrupted campaign must follow its journal resumeMode")
    case_ids = [
        case["id"]
        for case in campaign.adapter.cases
        if campaign.state["caseStates"][case["id"]]["status"]
        not in PASS_STATUSES | {"NOT_RUN"}
    ]
    if not case_ids:
        raise CampaignError("initial acceptance is already complete")
    return _run_attempt(campaign, "initial", case_ids)


def run_regression_locked(campaign: Campaign) -> dict[str, Any]:
    if campaign.state["status"] not in {"READY_FOR_REGRESSION", "INTERRUPTED"}:
        raise CampaignError("regression is not available in the current state")
    if (
        campaign.state["status"] == "INTERRUPTED"
        and campaign.state["resumeMode"] != "regression"
    ):
        raise CampaignError("interrupted campaign must follow its journal resumeMode")
    return _run_attempt(
        campaign, "regression", [case["id"] for case in campaign.adapter.cases]
    )


def latest_failed_run(campaign: Campaign) -> tuple[dict[str, Any], dict[str, Any]]:
    for attempt in reversed(campaign.state["attempts"]):
        for run in reversed(attempt["runs"]):
            if run["status"] == "FAILED":
                return attempt, run
    raise CampaignError("campaign has no failed case eligible for repair")


def load_fix(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise CampaignError("repair note must be a JSON object")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or "\n" in value
        or "\r" in value
    ):
        raise CampaignError(label + " must be a trimmed non-empty single-line string")
    return value


def _validate_root_cause_source(
    value: Any,
    failed_snapshot: dict[str, Any],
    fixed_snapshot: dict[str, Any],
    source_delta: list[dict[str, str]],
) -> dict[str, Any]:
    required = {"path", "lineStart", "lineEnd"}
    if (
        not isinstance(value, dict)
        or not required.issubset(value)
        or set(value) - (required | {"symbol"})
    ):
        raise CampaignError("rootCauseSource has invalid fields")
    path = normalize_relative(value["path"], "rootCauseSource.path")
    failed_metadata = next(
        (item for item in failed_snapshot["files"] if item["path"] == path), None
    )
    if failed_metadata is None or failed_metadata.get("status") != "present":
        raise CampaignError(
            "rootCauseSource.path must exist in the failed source snapshot"
        )
    start, end = value["lineStart"], value["lineEnd"]
    if type(start) is not int or type(end) is not int or start < 1 or end < start:
        raise CampaignError("rootCauseSource line range is invalid")
    line_count = failed_metadata.get("lineCount")
    if type(line_count) is not int:
        raise CampaignError(
            "rootCauseSource requires UTF-8 text in the failed snapshot"
        )
    if end > line_count:
        raise CampaignError("rootCauseSource line range exceeds the failed source file")
    fixed_metadata = next(
        (item for item in fixed_snapshot["files"] if item["path"] == path), None
    )
    if fixed_metadata is None or fixed_metadata.get("status") != "present":
        change = next(
            (item["change"] for item in source_delta if item["path"] == path), None
        )
        if change != "deleted":
            raise CampaignError(
                "deleted rootCauseSource.path requires an exact deleted sourceDelta entry"
            )
    result = {
        "path": path,
        "lineStart": start,
        "lineEnd": end,
        "failedSha256": failed_metadata["sha256"],
    }
    if "symbol" in value:
        result["symbol"] = _nonempty_string(value["symbol"], "rootCauseSource.symbol")
    return result


def _failure_signature(run: dict[str, Any]) -> str:
    return sha256_bytes(
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


def record_fix_locked(campaign: Campaign, value: dict[str, Any]) -> dict[str, Any]:
    if campaign.state["status"] != "FAILED":
        raise CampaignError("record-fix requires the latest attempt to be FAILED")
    if campaign.state["pendingFixId"] is not None:
        raise CampaignError("the recorded fix must be retested before another repair")
    expected_fields = {"rootCause", "rootCauseSource", "fixSummary"}
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise CampaignError("repair note has invalid fields")
    attempt, run = latest_failed_run(campaign)
    before = campaign.state["sourceBaseline"]
    if before["fingerprint"] != run["sourceFingerprint"]:
        raise CampaignError("latest failure source is not the campaign repair baseline")
    after = observe_source(campaign.adapter)
    expected_delta = source_snapshot_changed_entries(before, after)
    if not expected_delta:
        raise CampaignError("repair did not change project source")
    affected = list(campaign.adapter.case_by_id[run["caseId"]]["coversCriteria"])
    if not affected:
        raise CampaignError(
            "failed case does not cover a GOAL criterion eligible for repair"
        )
    root_cause = _nonempty_string(value["rootCause"], "rootCause")
    fix_summary = _nonempty_string(value["fixSummary"], "fixSummary")
    root_source = _validate_root_cause_source(
        value["rootCauseSource"], before, after, expected_delta
    )
    signature = _failure_signature(run)
    source_location = {
        key: root_source.get(key)
        for key in ("path", "lineStart", "lineEnd", "symbol", "failedSha256")
    }
    for prior in campaign.state["fixes"]:
        prior_location = {
            key: prior["rootCauseSource"].get(key)
            for key in ("path", "lineStart", "lineEnd", "symbol", "failedSha256")
        }
        if prior["failureSignature"] == signature and prior_location == source_location:
            raise CampaignError(
                "same failure recurred without new root-cause evidence in the machine-bound failure context"
            )
    fix = {
        "schemaVersion": FIX_AUDIT_SCHEMA_VERSION,
        "fixId": f"fix-{campaign.state['repairCount'] + 1:04d}",
        "failedCaseId": run["caseId"],
        "failedRound": attempt["mode"],
        "failedAttemptId": attempt["id"],
        "failedRunId": run["runId"],
        "failedSourceFingerprint": run["sourceFingerprint"],
        "fixedSourceFingerprint": after["fingerprint"],
        "rootCause": root_cause,
        "rootCauseSource": root_source,
        "affectedCriteria": affected,
        "sourceDelta": expected_delta,
        "fixSummary": fix_summary,
        "failureSignature": signature,
        "fixedSourceSnapshot": after,
        "recordedAt": utc_now(),
    }
    campaign.commit("fix_recorded", {"fix": fix})
    return campaign.summary()


def retest_locked(campaign: Campaign) -> dict[str, Any]:
    if campaign.state["status"] not in {"FIX_RECORDED", "INTERRUPTED"}:
        raise CampaignError("retest requires a recorded repair")
    if not campaign.state["fixes"] or campaign.state["pendingFixId"] is None:
        raise CampaignError("retest has no pending repair")
    if (
        campaign.state["status"] == "INTERRUPTED"
        and campaign.state["resumeMode"] != "retest"
    ):
        raise CampaignError("interrupted campaign must follow its journal resumeMode")
    return _run_attempt(
        campaign, "retest", [campaign.state["fixes"][-1]["failedCaseId"]]
    )


def resume_locked(campaign: Campaign) -> dict[str, Any]:
    if campaign.state["status"] == "RUNNING":
        attempt = _latest_attempt(campaign)
        campaign.commit(
            "attempt_interrupted",
            {
                "attemptId": attempt["id"],
                "reason": "previous operation ended before the attempt was closed",
                "resumeMode": attempt["mode"],
            },
        )
    mode = campaign.state["resumeMode"]
    if mode == "initial":
        return run_initial_locked(campaign)
    if mode == "regression":
        return run_regression_locked(campaign)
    if mode == "retest":
        return retest_locked(campaign)
    return campaign.summary()


__all__ = [
    "latest_failed_run",
    "load_fix",
    "record_fix_locked",
    "resume_locked",
    "retest_locked",
    "run_initial_locked",
    "run_regression_locked",
]
