#!/usr/bin/env python3
"""Create and inspect one self-ignored Steward GOAL workspace per worktree."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from goal_contract import (
    GoalContract,
    GoalContractError,
    goal_contract_sha256,
    validate_goal_text,
)
from worktree_binding import (
    GIT_REPOSITORY_ENVIRONMENT,
    WorktreeBinding,
    WorktreeBindingError,
    bind_target_worktree,
)

SCHEMA_ID = "steward.goal-workspace"
SCHEMA_VERSION = 1
ROOT_SCHEMA_ID = "steward.goal-workspace-root"
ROOT_SCHEMA_VERSION = 1
GOAL_PATH = PurePosixPath(".steward/goal.txt")
CONTEXT_DIRECTORY = PurePosixPath(".steward/goal-context")
IGNORE_PATH = PurePosixPath(".steward/.gitignore")
IGNORE_BYTES = b"*\n"
MAX_IGNORE_BYTES = 4_096
MAX_CREATE_INPUT_BYTES = 1_100_000
MAX_CONTEXT_BYTES = 1_048_576
_SAFE_CONTEXT_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.md")
_CONTEXT_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9._/-])"
    r"(\.steward/goal-context/[a-z0-9](?:[a-z0-9-]{0,63})?\.md)"
    r"(?![A-Za-z0-9._/-])"
)


class GoalWorkspaceError(Exception):
    """A GOAL workspace is invalid, unsafe, incomplete, or conflicting."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.code + ": " + self.message


@dataclass(frozen=True)
class CreateRequest:
    contract: GoalContract
    context_path: PurePosixPath
    context_bytes: bytes


@dataclass
class _CreatedFile:
    path: Path
    content: bytes
    device: int
    inode: int


@dataclass
class _Transaction:
    files: list[_CreatedFile] = field(default_factory=list)
    directories: list[Path] = field(default_factory=list)
    committed: bool = False

    def record_file(self, path: Path, content: bytes, opened: os.stat_result) -> None:
        self.files.append(
            _CreatedFile(
                path=path,
                content=content,
                device=opened.st_dev,
                inode=opened.st_ino,
            )
        )

    def rollback(self) -> list[str]:
        if self.committed:
            return []
        residuals: list[str] = []
        for created in reversed(self.files):
            try:
                observed = created.path.lstat()
                if (
                    stat.S_ISREG(observed.st_mode)
                    and not _is_reparse(observed)
                    and observed.st_dev == created.device
                    and observed.st_ino == created.inode
                    and _read_regular_file(
                        created.path, max_bytes=max(len(created.content), 1)
                    )
                    == created.content
                ):
                    created.path.unlink()
                else:
                    residuals.append(str(created.path))
            except FileNotFoundError:
                pass
            except (GoalWorkspaceError, OSError):
                residuals.append(str(created.path))
        for directory in reversed(self.directories):
            try:
                directory.rmdir()
            except FileNotFoundError:
                pass
            except OSError:
                residuals.append(str(directory))
        return residuals


def _is_reparse(observed: os.stat_result) -> bool:
    return bool(
        getattr(observed, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _require_real_directory(path: Path, label: str) -> None:
    try:
        observed = path.lstat()
    except FileNotFoundError as exc:
        raise GoalWorkspaceError("WORKSPACE_MISSING", f"{label} does not exist") from exc
    except OSError as exc:
        raise GoalWorkspaceError("WORKSPACE_IO", f"cannot inspect {label}: {exc}") from exc
    if stat.S_ISLNK(observed.st_mode) or _is_reparse(observed) or not stat.S_ISDIR(
        observed.st_mode
    ):
        raise GoalWorkspaceError(
            "WORKSPACE_PATH", f"{label} must be a real, non-symbolic directory"
        )


def _read_regular_file(path: Path, *, max_bytes: int) -> bytes:
    descriptor: int | None = None
    try:
        initial = path.lstat()
        if stat.S_ISLNK(initial.st_mode) or _is_reparse(initial) or not stat.S_ISREG(
            initial.st_mode
        ):
            raise GoalWorkspaceError(
                "WORKSPACE_PATH", f"{path} must be a regular non-symbolic file"
            )
        if initial.st_size > max_bytes:
            raise GoalWorkspaceError("WORKSPACE_SIZE", f"{path} is too large")
        flags = os.O_RDONLY
        for optional in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
            flags |= getattr(os, optional, 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(initial, opened):
            raise GoalWorkspaceError(
                "WORKSPACE_RACE", f"{path} changed while it was opened"
            )
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise GoalWorkspaceError("WORKSPACE_SIZE", f"{path} is too large")
        return data
    except GoalWorkspaceError:
        raise
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise GoalWorkspaceError("WORKSPACE_IO", f"cannot read {path}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _clean_git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in GIT_REPOSITORY_ENVIRONMENT:
        environment.pop(name, None)
    return environment


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            env=_clean_git_environment(),
        )
    except OSError as exc:
        raise GoalWorkspaceError("WORKSPACE_GIT", f"cannot execute git: {exc}") from exc


def _require_untracked_steward(root: Path) -> None:
    result = _git(root, "ls-files", "-z", "--", ".steward")
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip() or "git ls-files failed"
        raise GoalWorkspaceError("WORKSPACE_GIT", detail)
    if result.stdout:
        raise GoalWorkspaceError(
            "WORKSPACE_TRACKED", ".steward must not contain tracked paths"
        )


def _require_ignored(root: Path, relative_path: PurePosixPath) -> None:
    result = _git(root, "check-ignore", "-q", "--", relative_path.as_posix())
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        if not detail:
            detail = f"{relative_path.as_posix()} is not ignored by .steward/.gitignore"
        raise GoalWorkspaceError("WORKSPACE_IGNORE", detail)


def _write_new_regular(path: Path, content: bytes, transaction: _Transaction) -> None:
    descriptor: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        for optional in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW"):
            flags |= getattr(os, optional, 0)
        descriptor = os.open(path, flags, 0o600)
        opened = os.fstat(descriptor)
        transaction.record_file(path, content, opened)
        written = 0
        while written < len(content):
            count = os.write(descriptor, content[written:])
            if count <= 0:
                raise OSError("short write")
            written += count
        os.fsync(descriptor)
    except FileExistsError as exc:
        raise GoalWorkspaceError(
            "WORKSPACE_EXISTS", f"refusing to overwrite existing path {path}"
        ) from exc
    except OSError as exc:
        raise GoalWorkspaceError("WORKSPACE_IO", f"cannot create {path}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _mkdir_new(path: Path, transaction: _Transaction) -> None:
    try:
        path.mkdir(mode=0o700)
        transaction.directories.append(path)
    except FileExistsError as exc:
        raise GoalWorkspaceError(
            "WORKSPACE_EXISTS", f"refusing to replace existing path {path}"
        ) from exc
    except OSError as exc:
        raise GoalWorkspaceError("WORKSPACE_IO", f"cannot create {path}: {exc}") from exc


def _has_goal_artifacts(root: Path) -> bool:
    steward = root / ".steward"
    try:
        observed = steward.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(observed.st_mode) or _is_reparse(observed) or not stat.S_ISDIR(
        observed.st_mode
    ):
        return False
    return _lexists(steward / "goal.txt") or _lexists(steward / "goal-context")


def _lexists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise GoalWorkspaceError(
            "WORKSPACE_IO", f"cannot inspect {path}: {exc}"
        ) from exc
    return True


def _ensure_root(binding: WorktreeBinding, transaction: _Transaction) -> Path:
    root = Path(binding.target_worktree_root)
    _require_untracked_steward(root)
    steward = root / ".steward"
    ignore = steward / ".gitignore"

    try:
        observed = steward.lstat()
    except FileNotFoundError:
        _mkdir_new(steward, transaction)
    except OSError as exc:
        raise GoalWorkspaceError(
            "WORKSPACE_IO", f"cannot inspect .steward: {exc}"
        ) from exc
    else:
        if stat.S_ISLNK(observed.st_mode) or _is_reparse(observed) or not stat.S_ISDIR(
            observed.st_mode
        ):
            raise GoalWorkspaceError(
                "WORKSPACE_PATH", ".steward must be a real, non-symbolic directory"
            )

    try:
        ignore_bytes = _read_regular_file(ignore, max_bytes=MAX_IGNORE_BYTES)
    except FileNotFoundError:
        _write_new_regular(ignore, IGNORE_BYTES, transaction)
    else:
        if ignore_bytes != IGNORE_BYTES:
            raise GoalWorkspaceError(
                "WORKSPACE_IGNORE",
                ".steward/.gitignore must contain exactly the bytes '*\\n'",
            )

    _require_untracked_steward(root)
    _require_ignored(root, GOAL_PATH)
    _require_ignored(root, IGNORE_PATH)
    return steward


def _revalidate_binding(binding: WorktreeBinding) -> None:
    try:
        observed = bind_target_worktree(binding.target_worktree_root)
    except WorktreeBindingError as exc:
        raise GoalWorkspaceError("WORKSPACE_BINDING", str(exc)) from exc
    if observed != binding:
        raise GoalWorkspaceError(
            "WORKSPACE_BINDING", "target worktree binding changed during the operation"
        )


def _validate_context_path(raw_path: str) -> PurePosixPath:
    if not isinstance(raw_path, str) or not raw_path:
        raise GoalWorkspaceError("WORKSPACE_INPUT", "context.path must be a string")
    if "\\" in raw_path or "\x00" in raw_path:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT_PATH", "context.path must use a safe project-relative path"
        )
    path = PurePosixPath(raw_path)
    parts = path.parts
    if (
        path.is_absolute()
        or path.as_posix() != raw_path
        or len(parts) != 3
        or parts[:2] != CONTEXT_DIRECTORY.parts
        or not _SAFE_CONTEXT_NAME.fullmatch(parts[2])
        or len(parts[2][:-3]) > 64
    ):
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT_PATH",
            "context.path must be .steward/goal-context/<safe-slug>.md",
        )
    return path


def _context_path_for_contract(contract: GoalContract) -> PurePosixPath:
    result = next(item.value for item in contract.fields if item.key == "result")
    ascii_result = "".join(
        chr(ord(character) + 32)
        if "A" <= character <= "Z"
        else character
        if "a" <= character <= "z" or "0" <= character <= "9"
        else "-"
        for character in result
    )
    slug = re.sub(r"-+", "-", ascii_result).strip("-")
    slug = slug[:64].rstrip("-") or "goal-context"
    return CONTEXT_DIRECTORY / f"{slug}.md"


def _context_bytes(raw_content: str) -> bytes:
    if not isinstance(raw_content, str):
        raise GoalWorkspaceError("WORKSPACE_INPUT", "context.content must be a string")
    if raw_content.startswith("\ufeff") or "\x00" in raw_content or "\r" in raw_content:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT", "context.content must be UTF-8 text using LF without BOM or NUL"
        )
    if not raw_content.strip():
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT", "context.content must contain verified source material"
        )
    if not raw_content.endswith("\n"):
        raw_content += "\n"
    try:
        content = raw_content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT", "context.content must be valid UTF-8"
        ) from exc
    if len(content) > MAX_CONTEXT_BYTES:
        raise GoalWorkspaceError("WORKSPACE_CONTEXT", "context.content is too large")
    return content


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise GoalWorkspaceError(
                "WORKSPACE_INPUT", f"duplicate JSON field: {key}"
            )
        value[key] = item
    return value


def _load_create_request(raw_input: bytes) -> CreateRequest:
    if len(raw_input) > MAX_CREATE_INPUT_BYTES:
        raise GoalWorkspaceError("WORKSPACE_INPUT", "create input is too large")
    if raw_input.startswith(b"\xef\xbb\xbf"):
        raise GoalWorkspaceError("WORKSPACE_INPUT", "create input must not contain a BOM")
    try:
        value = json.loads(raw_input.decode("utf-8"), object_pairs_hook=_strict_object)
    except GoalWorkspaceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoalWorkspaceError(
            "WORKSPACE_INPUT", "create input must be valid UTF-8 JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != {"objective", "context"}:
        raise GoalWorkspaceError(
            "WORKSPACE_INPUT", "create input fields must be exactly objective and context"
        )
    context = value.get("context")
    if not isinstance(context, Mapping) or set(context) != {"path", "content"}:
        raise GoalWorkspaceError(
            "WORKSPACE_INPUT", "context fields must be exactly path and content"
        )
    objective = value.get("objective")
    if not isinstance(objective, str):
        raise GoalWorkspaceError("WORKSPACE_INPUT", "objective must be a string")
    try:
        contract = validate_goal_text(objective)
    except GoalContractError as exc:
        raise GoalWorkspaceError("WORKSPACE_GOAL", str(exc)) from exc
    context_path = _validate_context_path(context.get("path"))
    content = _context_bytes(context.get("content"))
    derived_path = _context_path_for_contract(contract)
    if context_path != derived_path:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT_PATH",
            "context.path must use the safe slug derived from 结果; expected "
            + derived_path.as_posix(),
        )
    _require_contract_reference(contract, context_path)
    return CreateRequest(contract, context_path, content)


def validate_create_request(raw_input: bytes) -> dict[str, Any]:
    """Validate an exact creator payload without inspecting or writing a worktree."""

    request = _load_create_request(raw_input)
    return _workspace_view(request.contract, request.context_path)


def _require_contract_reference(
    contract: GoalContract, expected_path: PurePosixPath | None = None
) -> PurePosixPath:
    prefix = CONTEXT_DIRECTORY.as_posix() + "/"
    matches = _CONTEXT_REFERENCE.findall(contract.objective)
    if contract.objective.count(prefix) != 1 or len(matches) != 1:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT_REFERENCE",
            "GOAL must contain exactly one safe .steward/goal-context/*.md reference",
        )
    context_path = _validate_context_path(matches[0])
    derived_path = _context_path_for_contract(contract)
    if context_path != derived_path:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT_PATH",
            "GOAL context path must use the safe slug derived from 结果; expected "
            + derived_path.as_posix(),
        )
    evidence = next(
        item.value for item in contract.fields if item.key == "evidenceAndContext"
    )
    if context_path.as_posix() not in evidence:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT_REFERENCE", "the context reference must be in 证据与上下文"
        )
    if expected_path is not None and context_path != expected_path:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT_REFERENCE", "GOAL context reference differs from context.path"
        )
    return context_path


def _workspace_view(contract: GoalContract, context_path: PurePosixPath) -> dict[str, Any]:
    return {
        "schemaId": SCHEMA_ID,
        "schemaVersion": SCHEMA_VERSION,
        "goalContract": {
            "path": GOAL_PATH.as_posix(),
            "contractVersion": 1,
            "sha256": goal_contract_sha256(contract),
            "objective": contract.objective,
            "criteriaIds": [criterion.id for criterion in contract.completion_criteria],
        },
        "context": {"path": context_path.as_posix()},
    }


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _inspect_workspace(
    binding: WorktreeBinding, *, allow_absent: bool
) -> tuple[dict[str, Any], bytes] | None:
    root = Path(binding.target_worktree_root)
    _require_untracked_steward(root)
    steward = root / ".steward"
    _require_real_directory(steward, ".steward")
    ignore = _read_regular_file(steward / ".gitignore", max_bytes=MAX_IGNORE_BYTES)
    if ignore != IGNORE_BYTES:
        raise GoalWorkspaceError(
            "WORKSPACE_IGNORE", ".steward/.gitignore must contain exactly the bytes '*\\n'"
        )
    _require_ignored(root, GOAL_PATH)

    goal_path = root / GOAL_PATH
    context_directory = root / CONTEXT_DIRECTORY
    goal_exists = goal_path.exists() or goal_path.is_symlink()
    context_exists = context_directory.exists() or context_directory.is_symlink()
    if not goal_exists and not context_exists:
        if allow_absent:
            return None
        raise GoalWorkspaceError("WORKSPACE_MISSING", "no GOAL workspace exists")
    if not goal_exists or not context_exists:
        raise GoalWorkspaceError(
            "WORKSPACE_PARTIAL", "GOAL workspace is partially initialized"
        )

    goal_bytes = _read_regular_file(goal_path, max_bytes=16_001)
    try:
        contract = validate_goal_text(goal_bytes)
    except GoalContractError as exc:
        raise GoalWorkspaceError("WORKSPACE_GOAL", str(exc)) from exc
    canonical_goal = contract.objective.encode("utf-8") + b"\n"
    if goal_bytes != canonical_goal:
        raise GoalWorkspaceError(
            "WORKSPACE_GOAL", ".steward/goal.txt is not canonical UTF-8 with one final LF"
        )

    _require_real_directory(context_directory, ".steward/goal-context")
    try:
        entries = sorted(context_directory.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise GoalWorkspaceError(
            "WORKSPACE_IO", f"cannot list .steward/goal-context: {exc}"
        ) from exc
    if len(entries) != 1:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT", "GOAL workspace must contain exactly one context file"
        )
    context_path = _require_contract_reference(contract)
    expected = root / context_path
    if entries[0] != expected:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT", "the sole context file differs from the GOAL reference"
        )
    context_bytes = _read_regular_file(expected, max_bytes=MAX_CONTEXT_BYTES)
    try:
        decoded = context_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT", "context file must be valid UTF-8"
        ) from exc
    if _context_bytes(decoded) != context_bytes:
        raise GoalWorkspaceError(
            "WORKSPACE_CONTEXT", "context file is not canonical UTF-8 text"
        )
    return _workspace_view(contract, context_path), context_bytes


def ensure_workspace_root(raw_target: str) -> dict[str, Any]:
    """Create or validate the self-ignored .steward root without replacing content."""

    try:
        binding = bind_target_worktree(raw_target)
    except WorktreeBindingError as exc:
        raise GoalWorkspaceError("WORKSPACE_BINDING", str(exc)) from exc
    root = Path(binding.target_worktree_root)
    ignore = root / IGNORE_PATH
    if _has_goal_artifacts(root) and not _lexists(ignore):
        raise GoalWorkspaceError(
            "WORKSPACE_LAYOUT", "existing GOAL artifacts lack the required root ignore contract"
        )
    transaction = _Transaction()
    try:
        _ensure_root(binding, transaction)
        _revalidate_binding(binding)
        _inspect_workspace(binding, allow_absent=True)
        transaction.committed = True
    except Exception as exc:
        residuals = transaction.rollback()
        if residuals:
            raise GoalWorkspaceError(
                "WORKSPACE_ROLLBACK",
                f"{exc}; rollback left: {', '.join(residuals)}",
            ) from exc
        raise
    return {
        "schemaId": ROOT_SCHEMA_ID,
        "schemaVersion": ROOT_SCHEMA_VERSION,
        "path": ".steward",
    }


def create_goal_workspace(raw_target: str, raw_input: bytes) -> dict[str, Any]:
    """Create the sole GOAL and context, or reuse an identical complete workspace."""

    request = _load_create_request(raw_input)
    try:
        binding = bind_target_worktree(raw_target)
    except WorktreeBindingError as exc:
        raise GoalWorkspaceError("WORKSPACE_BINDING", str(exc)) from exc
    root = Path(binding.target_worktree_root)
    ignore = root / IGNORE_PATH
    if _has_goal_artifacts(root) and not _lexists(ignore):
        raise GoalWorkspaceError(
            "WORKSPACE_LAYOUT", "existing GOAL artifacts lack the required root ignore contract"
        )

    transaction = _Transaction()
    try:
        steward = _ensure_root(binding, transaction)
        existing = _inspect_workspace(binding, allow_absent=True)
        expected_view = _workspace_view(request.contract, request.context_path)
        if existing is not None:
            existing_view, existing_context = existing
            if existing_view != expected_view or existing_context != request.context_bytes:
                raise GoalWorkspaceError(
                    "WORKSPACE_CONFLICT",
                    "this worktree already contains a different GOAL workspace",
                )
            transaction.committed = True
            return existing_view

        context_directory = steward / "goal-context"
        _mkdir_new(context_directory, transaction)
        _revalidate_binding(binding)
        _write_new_regular(
            root / request.context_path, request.context_bytes, transaction
        )
        _revalidate_binding(binding)
        _write_new_regular(
            root / GOAL_PATH,
            request.contract.objective.encode("utf-8") + b"\n",
            transaction,
        )
        inspected = _inspect_workspace(binding, allow_absent=False)
        assert inspected is not None
        observed_view, observed_context = inspected
        if observed_view != expected_view or observed_context != request.context_bytes:
            raise GoalWorkspaceError(
                "WORKSPACE_RACE", "created GOAL workspace differs from requested content"
            )
        transaction.committed = True
        return observed_view
    except Exception as exc:
        residuals = transaction.rollback()
        if residuals:
            raise GoalWorkspaceError(
                "WORKSPACE_ROLLBACK",
                f"{exc}; rollback left: {', '.join(residuals)}",
            ) from exc
        raise


def view_goal_workspace(raw_target: str) -> dict[str, Any]:
    """Validate and return the canonical view of an existing GOAL workspace."""

    try:
        binding = bind_target_worktree(raw_target)
    except WorktreeBindingError as exc:
        raise GoalWorkspaceError("WORKSPACE_BINDING", str(exc)) from exc
    inspected = _inspect_workspace(binding, allow_absent=False)
    assert inspected is not None
    return inspected[0]


def _read_stdin() -> bytes:
    if sys.stdin.buffer.isatty():
        raise GoalWorkspaceError(
            "WORKSPACE_INPUT_TRANSPORT",
            "create input must arrive through a finite non-TTY pipe; use "
            "pty_stdin_bridge.py when the host only exposes delayed PTY input",
        )
    data = sys.stdin.buffer.read(MAX_CREATE_INPUT_BYTES + 1)
    if len(data) > MAX_CREATE_INPUT_BYTES:
        raise GoalWorkspaceError("WORKSPACE_INPUT", "create input is too large")
    return data


def _usage_error() -> GoalWorkspaceError:
    return GoalWorkspaceError(
        "WORKSPACE_USAGE",
        "usage: goal_workspace.py ensure-root <target-worktree-root> | "
        "validate-create - | create <target-worktree-root> - | "
        "view <target-worktree-root>",
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(arguments) == 2 and arguments[0] == "ensure-root":
            output = ensure_workspace_root(arguments[1])
        elif (
            len(arguments) == 2
            and arguments[0] == "validate-create"
            and arguments[1] == "-"
        ):
            output = validate_create_request(_read_stdin())
        elif len(arguments) == 3 and arguments[0] == "create" and arguments[2] == "-":
            output = create_goal_workspace(arguments[1], _read_stdin())
        elif len(arguments) == 2 and arguments[0] == "view":
            output = view_goal_workspace(arguments[1])
        else:
            raise _usage_error()
        sys.stdout.buffer.write(_canonical_json(output) + b"\n")
        return 0
    except GoalWorkspaceError as exc:
        print("ERROR GOAL_WORKSPACE: " + str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print("ERROR GOAL_WORKSPACE: WORKSPACE_IO: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
