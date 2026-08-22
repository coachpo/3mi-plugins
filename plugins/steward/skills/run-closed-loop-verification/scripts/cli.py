"""Public command-line interface for the verification kernel."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from adapter_paths import observe_source, validate_adapter
from audit import (
    adapter_traceability_mode,
    audit_report,
    campaign_coverage,
    completion_status,
    status_report,
)
from engine import (
    load_fix,
    record_fix_locked,
    record_review_locked,
    resume_locked,
    retest_locked,
    run_initial_locked,
    run_quick_locked,
    run_regression_locked,
    supersede_fix_locked,
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
    """Attach the public execution envelope without claiming an audit ran."""

    report = dict(summary)
    report["executionStatus"] = campaign.state["status"]
    report["completionStatus"] = completion_status(campaign, audit_ok=None)
    report["resumeMode"] = campaign.state.get("resumeMode")
    report["coverage"] = campaign_coverage(campaign)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a local, resumable, evidence-driven closed-loop verification campaign."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "validate-adapter",
        "init",
        "status",
        "observe-source",
        "run",
        "resume",
        "record-fix",
        "record-review",
        "supersede-fix",
        "retest",
        "audit",
    ):
        sub = subparsers.add_parser(name)
        sub.add_argument(
            "--adapter", required=True, help="Path to a schemaVersion 1 JSON adapter"
        )
        if name == "run":
            sub.add_argument(
                "--mode", choices=("initial", "regression"), default="initial"
            )
            sub.add_argument(
                "--phase", choices=("quick", "full"), default="full"
            )
        if name == "record-fix":
            sub.add_argument(
                "--fix", required=True, help="Path to a fix-audit JSON document"
            )
        if name == "record-review":
            sub.add_argument(
                "--review",
                required=True,
                help="Path to a fresh post-fix semantic Review manifest",
            )
            sub.add_argument(
                "--expected-review-request",
                help=(
                    "Trusted post-fix request JSON; required for diff-target "
                    "Review campaigns"
                ),
            )
        if name == "supersede-fix":
            sub.add_argument(
                "--fix-id",
                required=True,
                help="Exact pending fix ID whose stale Review handoff is superseded",
            )
    export = subparsers.add_parser("export-platform-evidence")
    export.add_argument(
        "--adapter", required=True, help="Path to a schemaVersion 1 JSON adapter"
    )
    export.add_argument("--profile", required=True)
    export.add_argument("--ci-plan", required=True)
    export.add_argument("--entry", required=True)
    export.add_argument("--output", required=True)

    aggregate = subparsers.add_parser("aggregate-platform-evidence")
    aggregate.add_argument("--profile", required=True)
    aggregate.add_argument("--ci-plan", required=True)
    aggregate.add_argument("--bundle", action="append", required=True)
    aggregate.add_argument("--output", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "aggregate-platform-evidence":
            from platform_evidence import aggregate_platform_evidence

            report = aggregate_platform_evidence(
                profile_path=Path(args.profile),
                ci_plan_path=Path(args.ci_plan),
                bundle_paths=[Path(item) for item in args.bundle],
                output_path=Path(args.output),
            )
            print_json(report)
            return 0 if report["ok"] else 1
        adapter = validate_adapter(
            Path(args.adapter),
            observe_trace_drift=args.command
            in {
                "status",
                "audit",
                "observe-source",
                "record-fix",
                "record-review",
                "supersede-fix",
                "retest",
                "run",
                "resume",
                "export-platform-evidence",
            },
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
                    "caseIds": [case["id"] for case in adapter.cases],
                    "traceabilityMode": adapter_traceability_mode(adapter),
                    "verificationBound": adapter.verification is not None,
                    "executionStatus": "NOT_EVALUATED",
                    "completionStatus": "INCOMPLETE",
                    "coverage": adapter.coverage_summary(),
                }
            )
            return 0
        if args.command == "observe-source":
            observation = observe_source(adapter)
            print_json(
                {
                    "sourceFingerprint": observation["fingerprint"],
                    "paths": sorted(observation["projectPaths"]),
                    "files": sorted(
                        (
                            {
                                "path": item["path"],
                                "sha256": item["sha256"],
                            }
                            for item in observation["files"]
                            if item.get("status") == "present"
                            and isinstance(item.get("sha256"), str)
                            and item.get("path")
                            in set(observation["projectPaths"])
                        ),
                        key=lambda item: item["path"],
                    ),
                }
            )
            return 0
        if args.command == "init":
            campaign = Campaign.initialize(adapter)
            print_json(execution_result_report(campaign, campaign.summary()))
            return 0
        campaign = Campaign.load(adapter)
        if args.command == "export-platform-evidence":
            from platform_evidence import export_platform_evidence

            bundle = export_platform_evidence(
                campaign,
                profile_path=Path(args.profile),
                ci_plan_path=Path(args.ci_plan),
                entry_id=args.entry,
                output_path=Path(args.output),
            )
            print_json(bundle)
            return 0
        if args.command == "status":
            print_json(status_report(campaign))
            return 0
        if args.command == "audit":
            report = audit_report(campaign)
            print_json(report)
            return 0 if report["ok"] else 1
        with CampaignLock(adapter.campaign_root):
            campaign = Campaign.load(adapter)
            campaign.ensure_mutable()
            if not campaign.snapshot_consistent or not campaign.summary_consistent:
                campaign.rebuild_projections()
            if args.command == "run":
                if args.phase == "quick":
                    if args.mode != "initial":
                        raise CampaignError(
                            "quick phase cannot be combined with regression mode"
                        )
                    summary = run_quick_locked(campaign)
                elif args.mode == "regression":
                    summary = run_regression_locked(campaign)
                else:
                    summary = run_initial_locked(campaign)
                summary = execution_result_report(campaign, summary)
                print_json(summary)
                return (
                    0
                    if summary["status"]
                    in (
                        "PENDING",
                        "READY_FOR_REGRESSION",
                        "RUNNING",
                        "COMPLETE",
                    )
                    else 1
                )
            if args.command == "resume":
                summary = resume_locked(campaign)
                summary = execution_result_report(campaign, summary)
                print_json(summary)
                return (
                    0
                    if summary["status"]
                    in (
                        "PENDING",
                        "READY_FOR_REGRESSION",
                        "RUNNING",
                        "COMPLETE",
                    )
                    else 1
                )
            if args.command == "record-fix":
                summary = record_fix_locked(campaign, load_fix(Path(args.fix)))
                summary = execution_result_report(campaign, summary)
                print_json(summary)
                return 0
            if args.command == "record-review":
                summary = record_review_locked(
                    campaign,
                    Path(args.review),
                    (
                        Path(args.expected_review_request)
                        if args.expected_review_request is not None
                        else None
                    ),
                )
                summary = execution_result_report(campaign, summary)
                print_json(summary)
                return 0
            if args.command == "supersede-fix":
                summary = supersede_fix_locked(campaign, args.fix_id)
                summary = execution_result_report(campaign, summary)
                print_json(summary)
                return 0
            if args.command == "retest":
                summary = retest_locked(campaign)
                summary = execution_result_report(campaign, summary)
                print_json(summary)
                return (
                    0
                    if summary["status"]
                    in (
                        "PENDING",
                        "READY_FOR_REGRESSION",
                        "RUNNING",
                        "COMPLETE",
                    )
                    else 1
                )
        raise CampaignError("unknown command")
    except CampaignError as exc:
        sys.stderr.write("ERROR: " + public_message(exc) + "\n")
        return 2
    except KeyboardInterrupt:
        sys.stderr.write("ERROR: interrupted; use resume to recover the campaign\n")
        return 130
    except Exception as exc:
        sys.stderr.write(
            "ERROR: unexpected local verification failure: "
            + public_message(exc)
            + "\n"
        )
        return 2
