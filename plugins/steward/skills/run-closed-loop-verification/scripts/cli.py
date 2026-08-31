"""Public command-line interface for the verification kernel."""

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
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def execution_result_report(campaign: Campaign, summary: dict[str, Any]) -> dict[str, Any]:
    report = dict(summary)
    report["executionStatus"] = campaign.state["status"]
    current_audit = (
        audit_report(campaign) if campaign.state["status"] == "COMPLETE" else None
    )
    report["completionStatus"] = completion_status(
        campaign,
        audit_ok=(current_audit["ok"] if current_audit is not None else None),
    )
    report["currentAuditRejectionCodes"] = (
        current_audit["rejectionCodes"] if current_audit is not None else []
    )
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
    for name in (
        "validate-adapter", "observe-source", "init", "status", "run", "resume",
        "record-fix", "retest", "audit",
    ):
        command = subparsers.add_parser(name)
        command.add_argument(
            "--adapter", required=True,
            help="Path to .steward/project-adapter.json (schemaVersion 2)",
        )
        if name == "init":
            command.add_argument(
                "--repair-policy",
                choices=("within-goal", "verify-only"),
                default="within-goal",
            )
        elif name == "run":
            command.add_argument(
                "--mode", choices=("initial", "regression"), required=True
            )
        elif name == "record-fix":
            command.add_argument(
                "--fix", required=True, help="Path to a fix-audit schemaVersion 1 document"
            )
        elif name == "status":
            command.add_argument(
                "--source-path",
                action="append",
                default=[],
                help="Select one failed-baseline project source path (repeatable, max 64)",
            )
    return parser


def _success_status(status: str) -> bool:
    return status in {
        "PENDING", "READY_FOR_REGRESSION", "RUNNING", "AUDIT_REQUIRED",
        "FIX_RECORDED", "COMPLETE",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        drift_tolerant = args.command in {"status", "audit", "resume"}
        adapter = validate_adapter(
            Path(args.adapter), observe_goal_drift=drift_tolerant
        )
        if args.command == "validate-adapter":
            print_json(
                {
                    "schemaId": "steward.closed-loop-adapter-validation",
                    "ok": True,
                    "adapterSchemaVersion": adapter.data["schemaVersion"],
                    "adapterPath": str(adapter.path),
                    "projectId": adapter.data["projectId"],
                    "projectRoot": str(adapter.project_root),
                    "campaignRoot": str(adapter.campaign_root),
                    "catalogFingerprint": adapter.catalog_fingerprint,
                    "goalContract": adapter.goal_snapshot,
                    "worktreeBinding": adapter.worktree_binding,
                    "goalWorkspaceValid": not adapter.goal_workspace_errors,
                    "caseIds": [case["id"] for case in adapter.cases],
                    "criteria": adapter.criteria_configuration(),
                    "executionStatus": "NOT_EVALUATED",
                    "completionStatus": "INCOMPLETE",
                }
            )
            return 0
        if args.command == "observe-source":
            observation = observe_source(adapter)
            print_json(observation)
            return 0
        if args.command == "init":
            campaign = Campaign.initialize(adapter, args.repair_policy)
            print_json(execution_result_report(campaign, campaign.summary()))
            return 0

        campaign = Campaign.load(adapter)
        if args.command == "status":
            print_json(status_report(campaign, args.source_path))
            return 0
        if args.command == "audit":
            with CampaignLock(adapter.campaign_root):
                adapter = validate_adapter(
                    Path(args.adapter), observe_goal_drift=True
                )
                campaign = Campaign.load(adapter)
                adapter = campaign.adapter
                report = audit_report(campaign)
                if report["ok"] and campaign.state["status"] == "AUDIT_REQUIRED":
                    final_adapter = validate_adapter(
                        Path(args.adapter), observe_goal_drift=True
                    )
                    final_campaign = Campaign.load(final_adapter)
                    final_adapter = final_campaign.adapter
                    final_report = audit_report(final_campaign)
                    same_authority = (
                        final_adapter.catalog_fingerprint
                        == adapter.catalog_fingerprint
                        and final_adapter.goal_snapshot == adapter.goal_snapshot
                        and final_adapter.goal_errors == adapter.goal_errors
                        and final_adapter.goal_workspace_errors
                        == adapter.goal_workspace_errors
                        and final_adapter.worktree_binding
                        == adapter.worktree_binding
                        and final_report["currentSourceFingerprint"]
                        == report["currentSourceFingerprint"]
                        and final_report["currentCatalogFingerprint"]
                        == report["currentCatalogFingerprint"]
                        and final_report["currentWorktreeBinding"]
                        == report["currentWorktreeBinding"]
                        and final_report["currentRuntimePlatform"]
                        == report["currentRuntimePlatform"]
                    )
                    report = final_report
                    if report["ok"] and same_authority:
                        campaign = final_campaign
                        campaign.commit(
                            "audit_succeeded",
                            {
                                "finalRegressionAttemptId": campaign.state[
                                    "finalRegressionAttemptId"
                                ],
                                "currentSourceFingerprint": report[
                                    "currentSourceFingerprint"
                                ],
                                "catalogFingerprint": campaign.adapter.catalog_fingerprint,
                            },
                        )
                        report = audit_report(campaign)
                    elif report["ok"]:
                        raise CampaignError(
                            "final audit authority changed before completion binding"
                        )
            print_json(report)
            return 0 if report["ok"] else 1
        with CampaignLock(adapter.campaign_root):
            campaign = Campaign.load(adapter)
            campaign.ensure_mutable()
            if not campaign.snapshot_consistent or not campaign.summary_consistent:
                campaign.rebuild_projections()
            if args.command == "resume" and campaign.state["status"] == "COMPLETE":
                report = status_report(campaign)
                print_json(report)
                return 0 if report["completionStatus"] == "COMPLETE" else 1
            if args.command == "run":
                if args.mode == "regression":
                    summary = run_regression_locked(campaign)
                else:
                    summary = run_initial_locked(campaign)
            elif args.command == "resume":
                summary = resume_locked(campaign)
            elif args.command == "record-fix":
                summary = record_fix_locked(campaign, load_fix(Path(args.fix)))
            elif args.command == "retest":
                summary = retest_locked(campaign)
            else:  # pragma: no cover - argparse guarantees the command set
                raise CampaignError("unknown command")
            report = execution_result_report(campaign, summary)
            print_json(report)
            if report["executionStatus"] == "COMPLETE":
                return 0 if report["completionStatus"] == "COMPLETE" else 1
            return 0 if _success_status(report["executionStatus"]) else 1
    except CampaignError as exc:
        sys.stderr.write("ERROR: " + public_message(exc) + "\n")
        return 2
    except KeyboardInterrupt:
        sys.stderr.write("ERROR: interrupted; use resume to recover the campaign\n")
        return 130
    except Exception as exc:  # noqa: BLE001 - keep the CLI failure envelope stable.
        sys.stderr.write(
            "ERROR: unexpected local verification failure: " + public_message(exc) + "\n"
        )
        return 2


__all__ = ["build_parser", "execution_result_report", "main"]
