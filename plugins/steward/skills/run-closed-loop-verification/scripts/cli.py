"""Public CLI for alias-scoped closed-loop verification."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from verifier import (
    Campaign,
    VerificationError,
    advance,
    campaign_lock,
    record_repair,
    status_report,
)

MAX_STDIN_BYTES = 16 * 1024 * 1024


def _read_stdin() -> bytes:
    if sys.stdin.buffer.isatty():
        raise VerificationError(
            "INPUT_TRANSPORT",
            "structured input must arrive through a finite non-TTY pipe",
        )
    data = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(data) > MAX_STDIN_BYTES:
        raise VerificationError("INVALID_JSON", "structured input is too large")
    return data


def _print_json(value: Any) -> None:
    sys.stdout.write(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify one alias-scoped Steward GOAL in the current worktree."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "advance", "record-repair"):
        command = sub.add_parser(name)
        command.add_argument(
            "--goal", required=True, help="Safe alias below .steward/goals/"
        )
        if name == "init":
            command.add_argument("--execution-plan", required=True, choices=["-"])
        if name == "record-repair":
            command.add_argument("--repair", required=True, choices=["-"])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            campaign = Campaign.initialize(args.goal, _read_stdin())
            _print_json(status_report(campaign))
            return 0
        campaign = Campaign.load(args.goal)
        if args.command == "status":
            _print_json(status_report(campaign))
            return 0
        with campaign_lock(campaign):
            campaign = Campaign.load(args.goal)
            if args.command == "record-repair":
                report = record_repair(campaign, _read_stdin())
                code = 0
            else:
                report, code = advance(campaign)
        _print_json(report)
        return code
    except VerificationError as exc:
        print("ERROR VERIFICATION: " + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "ERROR VERIFICATION: interrupted; the phase is journaled, run advance to resume",
            file=sys.stderr,
        )
        return 130
    except Exception as exc:  # noqa: BLE001
        print("ERROR VERIFICATION: UNEXPECTED: " + str(exc)[:2000], file=sys.stderr)
        return 2


__all__ = ["build_parser", "main"]
