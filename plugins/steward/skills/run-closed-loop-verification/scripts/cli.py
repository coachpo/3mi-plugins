"""Public command-line interface for the verification campaign."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from adapter_paths import observe_source, validate_adapter
from audit import (
    audit_report,
    campaign_coverage,
    completion_status,
    failure_fix_context,
    status_report,
)
from engine import (
    load_fix,
    record_fix_locked,
    resume_locked,
    retest_locked,
    run_initial_locked,
    run_regression_locked,
)
from journal_state import Campaign, CampaignLock
from model import CampaignError, public_message


def print_json(value: Any) -> None:
    sys.stdout.write(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )


def execution_result_report(
    campaign: Campaign, summary: dict[str, Any]
) -> dict[str, Any]:
    report = dict(summary)
    report["executionStatus"] = campaign.state["status"]
    report["completionStatus"] = completion_status(campaign, audit_ok=None)
    report["resumeMode"] = campaign.state["resumeMode"]
    report["coverage"] = campaign_coverage(campaign)
    latest_failure, fix_context = failure_fix_context(campaign)
    report["latestFailure"] = latest_failure
    report["fixContext"] = fix_context
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a local, resumable, evidence-driven GOAL acceptance campaign."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "advance", "record-fix"):
        command = subparsers.add_parser(name)
        command.add_argument(
            "--adapter",
            required=True,
            help="Path to .steward/project-adapter.json (schemaVersion 2)",
        )
        if name == "record-fix":
            command.add_argument(
                "--fix",
                required=True,
                help="Path to a minimal repair-note JSON document",
            )
    return parser


def _finish_audit(campaign: Campaign, adapter_path: Path) -> dict[str, Any]:
    report = audit_report(campaign)
    if not report["ok"] or campaign.state["status"] != "AUDIT_REQUIRED":
        return report

    final_adapter = validate_adapter(adapter_path, observe_goal_drift=True)
    final_campaign = Campaign.load(final_adapter)
    final_source = observe_source(final_adapter)["fingerprint"]
    same_authority = (
        final_adapter.catalog_fingerprint == campaign.adapter.catalog_fingerprint
        and final_adapter.goal_snapshot == campaign.adapter.goal_snapshot
        and final_adapter.goal_errors == campaign.adapter.goal_errors
        and final_adapter.goal_workspace_errors
        == campaign.adapter.goal_workspace_errors
        and final_adapter.worktree_binding == campaign.adapter.worktree_binding
        and final_campaign.state == campaign.state
        and final_source == report["currentSourceFingerprint"]
    )
    if not same_authority:
        report["ok"] = False
        report["completionStatus"] = "INCOMPLETE"
        report["rejectionCodes"] = sorted(
            set(report["rejectionCodes"] + ["AUDIT_AUTHORITY_CHANGED"])
        )
        report["errors"] = sorted(
            set(
                report["errors"]
                + ["final audit authority changed before completion binding"]
            )
        )
        return report

    campaign = final_campaign
    campaign.commit(
        "audit_succeeded",
        {
            "finalRegressionAttemptId": campaign.state["finalRegressionAttemptId"],
            "currentSourceFingerprint": final_source,
            "catalogFingerprint": campaign.adapter.catalog_fingerprint,
        },
    )
    report.update(
        {
            "executionStatus": "COMPLETE",
            "completionStatus": "COMPLETE",
            "resumeMode": None,
            "successfulAudit": campaign.state["successfulAudit"],
        }
    )
    return report


def _advance(campaign: Campaign, adapter_path: Path) -> tuple[dict[str, Any], int]:
    status = campaign.state["status"]
    if status == "COMPLETE":
        report = status_report(campaign)
        return report, 0 if report["completionStatus"] == "COMPLETE" else 1
    if status == "AUDIT_REQUIRED":
        report = _finish_audit(campaign, adapter_path)
        return report, 0 if report["ok"] else 1

    campaign.ensure_mutable()
    if status in {"RUNNING", "INTERRUPTED"}:
        summary = resume_locked(campaign)
    elif status == "PENDING":
        summary = run_initial_locked(campaign)
    elif status == "FIX_RECORDED":
        summary = retest_locked(campaign)
    elif status == "READY_FOR_REGRESSION":
        summary = run_regression_locked(campaign)
    else:
        report = status_report(campaign)
        return report, 1
    report = execution_result_report(campaign, summary)
    return report, 0 if report["executionStatus"] not in {"FAILED", "BLOCKED"} else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    adapter_path = Path(args.adapter)
    try:
        adapter = validate_adapter(
            adapter_path,
            observe_goal_drift=args.command in {"status", "advance"},
        )
        if args.command == "init":
            observation = observe_source(adapter)
            campaign = Campaign.initialize(adapter, observation=observation)
            print_json(execution_result_report(campaign, campaign.summary()))
            return 0
        if args.command == "status":
            print_json(status_report(Campaign.load(adapter)))
            return 0

        with CampaignLock(adapter.campaign_root):
            adapter = validate_adapter(
                adapter_path,
                observe_goal_drift=args.command == "advance",
            )
            campaign = Campaign.load(adapter)
            if args.command == "record-fix":
                campaign.ensure_mutable()
                summary = record_fix_locked(campaign, load_fix(Path(args.fix)))
                report = execution_result_report(campaign, summary)
                return_code = 0
            else:
                report, return_code = _advance(campaign, adapter_path)
        print_json(report)
        return return_code
    except CampaignError as exc:
        sys.stderr.write("ERROR: " + public_message(exc) + "\n")
        return 2
    except KeyboardInterrupt:
        sys.stderr.write("ERROR: interrupted; use advance to recover the campaign\n")
        return 130
    except Exception as exc:  # noqa: BLE001 - keep the CLI failure envelope stable.
        sys.stderr.write(
            "ERROR: unexpected local verification failure: "
            + public_message(exc)
            + "\n"
        )
        return 2


__all__ = ["build_parser", "execution_result_report", "main"]
