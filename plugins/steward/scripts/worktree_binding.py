#!/usr/bin/env python3
"""Validate an explicitly supplied Steward target worktree without guessing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_ID = "steward.target-worktree-binding"
SCHEMA_VERSION = 1
MAX_EXPECTED_VIEW_BYTES = 16_384
GIT_REPOSITORY_ENVIRONMENT = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_WORK_TREE",
)


class WorktreeBindingError(Exception):
    """A caller-supplied worktree binding is missing, invalid, or stale."""


@dataclass(frozen=True)
class WorktreeBinding:
    target_worktree_root: str
    git_dir: str
    git_common_dir: str

    def view(self) -> dict[str, Any]:
        return {
            "gitCommonDir": self.git_common_dir,
            "gitDir": self.git_dir,
            "schemaId": SCHEMA_ID,
            "schemaVersion": SCHEMA_VERSION,
            "targetWorktreeRoot": self.target_worktree_root,
        }


def _canonical_directory(raw: str, label: str) -> Path:
    if not raw:
        raise WorktreeBindingError(f"{label} is required")
    supplied = Path(raw)
    if not supplied.is_absolute():
        raise WorktreeBindingError(f"{label} must be an absolute path")
    try:
        resolved = supplied.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorktreeBindingError(f"cannot resolve {label}: {exc}") from exc
    if not resolved.is_dir():
        raise WorktreeBindingError(f"{label} is not a directory")
    return resolved


def _git_path(root: Path, *arguments: str) -> Path:
    environment = os.environ.copy()
    for name in GIT_REPOSITORY_ENVIRONMENT:
        environment.pop(name, None)
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
    except OSError as exc:
        raise WorktreeBindingError(f"cannot execute git: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "git rev-parse failed"
        raise WorktreeBindingError(detail)
    lines = result.stdout.splitlines()
    if len(lines) != 1 or not lines[0]:
        raise WorktreeBindingError("git rev-parse returned an invalid path")
    return _canonical_directory(lines[0], "git result")


def bind_target_worktree(raw_target: str) -> WorktreeBinding:
    """Bind exactly one caller-provided absolute worktree root."""

    target = _canonical_directory(raw_target, "<target-worktree-root>")
    top_level = _git_path(target, "--show-toplevel")
    if top_level != target:
        raise WorktreeBindingError(
            "normalized Git top-level does not equal <target-worktree-root>"
        )
    git_dir = _git_path(target, "--absolute-git-dir")
    git_common_dir = _git_path(target, "--path-format=absolute", "--git-common-dir")
    return WorktreeBinding(
        target_worktree_root=str(target),
        git_dir=str(git_dir),
        git_common_dir=str(git_common_dir),
    )


def verify_observed_root(raw_target: str, raw_observed: str) -> WorktreeBinding:
    """Reject repository facts observed from any root except the target."""

    binding = bind_target_worktree(raw_target)
    observed = _canonical_directory(raw_observed, "observed project root")
    if str(observed) != binding.target_worktree_root:
        raise WorktreeBindingError(
            "observed project root does not equal <target-worktree-root>"
        )
    return binding


def canonical_view_bytes(binding: WorktreeBinding) -> bytes:
    return json.dumps(
        binding.view(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _load_expected_view(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_EXPECTED_VIEW_BYTES:
        raise WorktreeBindingError("expected binding view is too large")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorktreeBindingError("expected binding view is invalid JSON") from exc
    if not isinstance(value, dict):
        raise WorktreeBindingError("expected binding view must be an object")
    expected_keys = {
        "gitCommonDir",
        "gitDir",
        "schemaId",
        "schemaVersion",
        "targetWorktreeRoot",
    }
    if set(value) != expected_keys:
        raise WorktreeBindingError("expected binding view has invalid fields")
    if (
        value.get("schemaId") != SCHEMA_ID
        or value.get("schemaVersion") != SCHEMA_VERSION
    ):
        raise WorktreeBindingError("expected binding view has an unsupported schema")
    return value


def verify_frozen_view(
    raw_current_session_root: str, expected_data: bytes
) -> WorktreeBinding:
    """Reject a current session root different from the frozen target."""

    binding = bind_target_worktree(raw_current_session_root)
    if _load_expected_view(expected_data) != binding.view():
        raise WorktreeBindingError(
            "current session worktree differs from the frozen target binding"
        )
    return binding


def _usage_error() -> WorktreeBindingError:
    return WorktreeBindingError(
        "usage: worktree_binding.py view <target-worktree-root> | "
        "verify-root <target-worktree-root> <observed-project-root> | "
        "verify-view <current-session-worktree-root> -"
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(arguments) == 2 and arguments[0] == "view":
            binding = bind_target_worktree(arguments[1])
        elif len(arguments) == 3 and arguments[0] == "verify-root":
            binding = verify_observed_root(arguments[1], arguments[2])
        elif (
            len(arguments) == 3
            and arguments[0] == "verify-view"
            and arguments[2] == "-"
        ):
            binding = verify_frozen_view(
                arguments[1], sys.stdin.buffer.read(MAX_EXPECTED_VIEW_BYTES + 1)
            )
        else:
            raise _usage_error()
    except WorktreeBindingError as exc:
        print(f"ERROR WORKTREE_BINDING: {exc}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(canonical_view_bytes(binding) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
