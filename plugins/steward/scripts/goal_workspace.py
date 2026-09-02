#!/usr/bin/env python3
"""Create and inspect immutable, alias-scoped Steward GOAL bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from goal_contract import GoalContract, GoalContractError, goal_contract_sha256, validate_goal_text
from worktree_binding import GIT_REPOSITORY_ENVIRONMENT, WorktreeBinding, WorktreeBindingError, bind_target_worktree

BUNDLE_SCHEMA_ID = "steward.goal-bundle"
BUNDLE_SCHEMA_VERSION = 1
VIEW_SCHEMA_ID = "steward.goal-bundle-view"
VIEW_SCHEMA_VERSION = 1
ROOT_SCHEMA_ID = "steward.workspace-root"
ROOT_SCHEMA_VERSION = 1
ACCEPTANCE_SCHEMA_VERSION = 1
IGNORE_BYTES = b"*\n"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_CONTEXT_BYTES = 1024 * 1024
MAX_PLAN_BYTES = 1024 * 1024
MAX_IGNORE_BYTES = 4096
ALIAS_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
CRITERION_ID_PATTERN = re.compile(r"^C[1-9][0-9]*$")
SUPPORTED_PLATFORMS = {"any", "linux", "darwin", "windows", "posix"}


class GoalWorkspaceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True)
class CreateRequest:
    contract: GoalContract
    goal_bytes: bytes
    context_bytes: bytes
    plan: dict[str, Any]
    plan_bytes: bytes


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GoalWorkspaceError("WORKSPACE_JSON", "value is not canonical JSON") from exc


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def validate_alias(alias: str) -> str:
    if not isinstance(alias, str) or len(alias) > 64 or ALIAS_PATTERN.fullmatch(alias) is None:
        raise GoalWorkspaceError("WORKSPACE_ALIAS", "goal alias must be 1-64 lowercase ASCII letters/digits joined by single hyphens")
    return alias


def _clean_git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in GIT_REPOSITORY_ENVIRONMENT:
        environment.pop(name, None)
    return environment


def _git(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(["git", "-C", str(cwd), *arguments], check=False, capture_output=True, env=_clean_git_environment())
    except OSError as exc:
        raise GoalWorkspaceError("WORKSPACE_GIT", f"cannot execute git: {exc}") from exc


def resolve_current_binding(cwd: str | Path | None = None) -> WorktreeBinding:
    supplied = Path.cwd() if cwd is None else Path(cwd)
    try:
        supplied = supplied.resolve(strict=True)
    except OSError as exc:
        raise GoalWorkspaceError("WORKSPACE_BINDING", f"cannot resolve cwd: {exc}") from exc
    result = _git(supplied, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip() or "not in a Git worktree"
        raise GoalWorkspaceError("WORKSPACE_BINDING", detail)
    try:
        root = Path(result.stdout.decode("utf-8").strip()).resolve(strict=True)
        return bind_target_worktree(str(root))
    except (UnicodeError, OSError, WorktreeBindingError) as exc:
        raise GoalWorkspaceError("WORKSPACE_BINDING", str(exc)) from exc


def _is_reparse(observed: os.stat_result) -> bool:
    return bool(getattr(observed, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _require_real_directory(path: Path, label: str) -> None:
    try:
        observed = path.lstat()
    except FileNotFoundError as exc:
        raise GoalWorkspaceError("WORKSPACE_MISSING", f"{label} does not exist") from exc
    except OSError as exc:
        raise GoalWorkspaceError("WORKSPACE_IO", f"cannot inspect {label}: {exc}") from exc
    if stat.S_ISLNK(observed.st_mode) or _is_reparse(observed) or not stat.S_ISDIR(observed.st_mode):
        raise GoalWorkspaceError("WORKSPACE_PATH", f"{label} must be a real directory")


def read_regular_bytes(path: Path, *, label: str, max_bytes: int) -> bytes:
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or _is_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise GoalWorkspaceError("WORKSPACE_PATH", f"{label} must be a regular non-link file")
        if before.st_size > max_bytes:
            raise GoalWorkspaceError("WORKSPACE_SIZE", f"{label} exceeds the safe size limit")
        flags = os.O_RDONLY
        for name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
            flags |= getattr(os, name, 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
            raise GoalWorkspaceError("WORKSPACE_RACE", f"{label} changed while opened")
        data = bytearray()
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > max_bytes:
                raise GoalWorkspaceError("WORKSPACE_SIZE", f"{label} exceeds the safe size limit")
        after = path.lstat()
        final = os.fstat(descriptor)
        if not os.path.samestat(before, final) or not os.path.samestat(before, after):
            raise GoalWorkspaceError("WORKSPACE_RACE", f"{label} changed while read")
        return bytes(data)
    except GoalWorkspaceError:
        raise
    except FileNotFoundError as exc:
        raise GoalWorkspaceError("WORKSPACE_MISSING", f"missing {label}") from exc
    except OSError as exc:
        raise GoalWorkspaceError("WORKSPACE_IO", f"cannot read {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_untracked_steward(root: Path) -> None:
    result = _git(root, "ls-files", "-z", "--", ".steward")
    if result.returncode != 0:
        raise GoalWorkspaceError("WORKSPACE_GIT", result.stderr.decode("utf-8", "replace").strip())
    if result.stdout:
        raise GoalWorkspaceError("WORKSPACE_TRACKED", ".steward must not contain tracked paths")


def _ensure_root(binding: WorktreeBinding) -> Path:
    root = Path(binding.target_worktree_root)
    _require_untracked_steward(root)
    steward = root / ".steward"
    try:
        steward.mkdir(mode=0o700)
    except FileExistsError:
        _require_real_directory(steward, ".steward")
    ignore = steward / ".gitignore"
    try:
        fd = os.open(ignore, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if read_regular_bytes(ignore, label=".steward/.gitignore", max_bytes=MAX_IGNORE_BYTES) != IGNORE_BYTES:
            raise GoalWorkspaceError("WORKSPACE_IGNORE", ".steward/.gitignore must contain exactly '*\\n'")
    else:
        with os.fdopen(fd, "wb") as handle:
            handle.write(IGNORE_BYTES)
            handle.flush()
            os.fsync(handle.fileno())
    goals = steward / "goals"
    try:
        goals.mkdir(mode=0o700)
    except FileExistsError:
        _require_real_directory(goals, ".steward/goals")
    _require_untracked_steward(root)
    if _git(root, "check-ignore", "-q", "--", ".steward/goals").returncode != 0:
        raise GoalWorkspaceError("WORKSPACE_IGNORE", ".steward/goals is not ignored")
    return goals


def ensure_workspace_root(raw_target: str) -> dict[str, Any]:
    try:
        binding = bind_target_worktree(raw_target)
    except WorktreeBindingError as exc:
        raise GoalWorkspaceError("WORKSPACE_BINDING", str(exc)) from exc
    _ensure_root(binding)
    return {"schemaId": ROOT_SCHEMA_ID, "schemaVersion": ROOT_SCHEMA_VERSION, "path": ".steward"}


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GoalWorkspaceError("WORKSPACE_INPUT", f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _canonical_text(value: Any, label: str, max_bytes: int) -> bytes:
    if not isinstance(value, str) or not value.strip():
        raise GoalWorkspaceError("WORKSPACE_INPUT", f"{label} must be non-empty text")
    if value.startswith("\ufeff") or "\x00" in value or "\r" in value:
        raise GoalWorkspaceError("WORKSPACE_INPUT", f"{label} must use UTF-8 LF text without BOM/NUL")
    if not value.endswith("\n"):
        value += "\n"
    data = value.encode("utf-8")
    if len(data) > max_bytes:
        raise GoalWorkspaceError("WORKSPACE_SIZE", f"{label} is too large")
    return data


def _unique_strings(value: Any, label: str, pattern: re.Pattern[str] | None = None) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise GoalWorkspaceError("WORKSPACE_PLAN", f"{label} must be a string array")
    if len(set(value)) != len(value):
        raise GoalWorkspaceError("WORKSPACE_PLAN", f"{label} contains duplicates")
    if pattern is not None and any(pattern.fullmatch(item) is None for item in value):
        raise GoalWorkspaceError("WORKSPACE_PLAN", f"{label} contains an invalid value")
    return list(value)


def validate_acceptance_plan(value: Any, criteria_ids: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "sourcePolicy", "cases"}:
        raise GoalWorkspaceError("WORKSPACE_PLAN", "acceptance plan has invalid top-level fields")
    if value.get("schemaVersion") != ACCEPTANCE_SCHEMA_VERSION or type(value.get("schemaVersion")) is not int:
        raise GoalWorkspaceError("WORKSPACE_PLAN", "acceptance plan schemaVersion must be 1")
    source = value.get("sourcePolicy")
    if not isinstance(source, dict):
        raise GoalWorkspaceError("WORKSPACE_PLAN", "sourcePolicy must be an object")
    mode = source.get("mode")
    if mode == "git-visible":
        if set(source) != {"mode"}:
            raise GoalWorkspaceError("WORKSPACE_PLAN", "git-visible sourcePolicy only accepts mode")
    elif mode == "files":
        if set(source) != {"mode", "files"}:
            raise GoalWorkspaceError("WORKSPACE_PLAN", "files sourcePolicy requires mode and files")
        files = _unique_strings(source.get("files"), "sourcePolicy.files")
        if not files:
            raise GoalWorkspaceError("WORKSPACE_PLAN", "sourcePolicy.files must not be empty")
        for item in files:
            path = PurePosixPath(item)
            if path.is_absolute() or path.as_posix() != item or ".." in path.parts or item.startswith(".steward/"):
                raise GoalWorkspaceError("WORKSPACE_PLAN", "sourcePolicy.files contains an unsafe path")
    else:
        raise GoalWorkspaceError("WORKSPACE_PLAN", "sourcePolicy.mode must be git-visible or files")
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise GoalWorkspaceError("WORKSPACE_PLAN", "cases must be a non-empty array")
    expected = {"id", "required", "platform", "coversCriteria", "assertion", "runnerHint", "evidence"}
    seen: set[str] = set()
    criteria = set(criteria_ids)
    normalized_cases: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or set(case) != expected:
            raise GoalWorkspaceError("WORKSPACE_PLAN", f"case {index} has invalid fields")
        case_id = case.get("id")
        if not isinstance(case_id, str) or CASE_ID_PATTERN.fullmatch(case_id) is None or case_id in seen:
            raise GoalWorkspaceError("WORKSPACE_PLAN", f"case {index} has invalid or duplicate id")
        seen.add(case_id)
        if type(case.get("required")) is not bool or case.get("platform") not in SUPPORTED_PLATFORMS:
            raise GoalWorkspaceError("WORKSPACE_PLAN", f"case {case_id} has invalid required/platform")
        covers = _unique_strings(case.get("coversCriteria"), f"case {case_id} coversCriteria", CRITERION_ID_PATTERN)
        if not covers or not set(covers).issubset(criteria):
            raise GoalWorkspaceError("WORKSPACE_PLAN", f"case {case_id} references unknown criteria")
        for name in ("assertion", "runnerHint"):
            item = case.get(name)
            if not isinstance(item, str) or not item.strip() or "replace-with" in item.lower() or "placeholder" in item.lower():
                raise GoalWorkspaceError("WORKSPACE_PLAN", f"case {case_id} {name} is empty or placeholder")
        evidence = case.get("evidence")
        if not isinstance(evidence, dict) or set(evidence) != {"requiredFiles", "nonEmptyFiles"}:
            raise GoalWorkspaceError("WORKSPACE_PLAN", f"case {case_id} evidence has invalid fields")
        required_files = _unique_strings(evidence.get("requiredFiles"), f"case {case_id} requiredFiles")
        nonempty = _unique_strings(evidence.get("nonEmptyFiles"), f"case {case_id} nonEmptyFiles")
        if not set(nonempty).issubset(set(required_files)):
            raise GoalWorkspaceError("WORKSPACE_PLAN", f"case {case_id} nonEmptyFiles must be required")
        for item in required_files:
            path = PurePosixPath(item)
            if path.is_absolute() or path.as_posix() != item or ".." in path.parts or item in {"", "."}:
                raise GoalWorkspaceError("WORKSPACE_PLAN", f"case {case_id} evidence path is unsafe")
        normalized_cases.append(dict(case))
    uncovered = [criterion for criterion in criteria_ids if not any(c["required"] and criterion in c["coversCriteria"] for c in normalized_cases)]
    if uncovered:
        raise GoalWorkspaceError("WORKSPACE_PLAN", "criteria lack required coverage: " + ", ".join(uncovered))
    normalized = {"schemaVersion": 1, "sourcePolicy": dict(source), "cases": normalized_cases}
    if len(canonical_json_bytes(normalized)) > MAX_PLAN_BYTES:
        raise GoalWorkspaceError("WORKSPACE_SIZE", "acceptance plan is too large")
    return normalized


def _context_reference(alias: str) -> str:
    return f".steward/goals/{alias}/context.md"


def _validate_context_reference(contract: GoalContract, alias: str) -> None:
    reference = _context_reference(alias)
    if contract.objective.count(reference) != 1:
        raise GoalWorkspaceError("WORKSPACE_CONTEXT_REFERENCE", f"GOAL must reference {reference} exactly once")
    evidence = next(field.value for field in contract.fields if field.key == "evidenceAndContext")
    if reference not in evidence:
        raise GoalWorkspaceError("WORKSPACE_CONTEXT_REFERENCE", "context reference must be in 证据与上下文")


def _load_create_request(raw: bytes, alias: str) -> CreateRequest:
    if len(raw) > MAX_INPUT_BYTES or raw.startswith(b"\xef\xbb\xbf"):
        raise GoalWorkspaceError("WORKSPACE_INPUT", "create payload is too large or has a BOM")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except GoalWorkspaceError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GoalWorkspaceError("WORKSPACE_INPUT", "create payload must be UTF-8 JSON") from exc
    if not isinstance(value, Mapping) or set(value) != {"objective", "context", "acceptancePlan"}:
        raise GoalWorkspaceError("WORKSPACE_INPUT", "payload fields must be objective, context, acceptancePlan")
    try:
        contract = validate_goal_text(value.get("objective"))
    except GoalContractError as exc:
        raise GoalWorkspaceError("WORKSPACE_GOAL", str(exc)) from exc
    _validate_context_reference(contract, alias)
    context_bytes = _canonical_text(value.get("context"), "context", MAX_CONTEXT_BYTES)
    criteria_ids = [criterion.id for criterion in contract.completion_criteria]
    plan = validate_acceptance_plan(value.get("acceptancePlan"), criteria_ids)
    goal_bytes = contract.objective.encode("utf-8") + b"\n"
    return CreateRequest(contract, goal_bytes, context_bytes, plan, canonical_json_bytes(plan) + b"\n")


def _manifest(alias: str, binding: WorktreeBinding, request: CreateRequest) -> dict[str, Any]:
    return {
        "schemaId": BUNDLE_SCHEMA_ID, "schemaVersion": BUNDLE_SCHEMA_VERSION, "alias": alias,
        "worktreeBinding": binding.view(),
        "goal": {"path": "goal.txt", "contractVersion": 1, "sha256": goal_contract_sha256(request.contract)},
        "context": {"path": "context.md", "sha256": sha256_bytes(request.context_bytes), "bytes": len(request.context_bytes)},
        "acceptancePlan": {"path": "acceptance-plan.json", "schemaVersion": 1, "sha256": sha256_bytes(request.plan_bytes)},
    }


def _bundle_view(alias: str, relative: str, manifest: dict[str, Any], contract: GoalContract, plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaId": VIEW_SCHEMA_ID, "schemaVersion": VIEW_SCHEMA_VERSION, "alias": alias, "path": relative,
        "manifestSha256": sha256_bytes(canonical_json_bytes(manifest) + b"\n"),
        "goalContract": {"path": f"{relative}/goal.txt", "contractVersion": 1, "sha256": goal_contract_sha256(contract), "objective": contract.objective, "criteriaIds": [item.id for item in contract.completion_criteria]},
        "context": {"path": f"{relative}/context.md", "sha256": manifest["context"]["sha256"]},
        "acceptancePlan": {"path": f"{relative}/acceptance-plan.json", "sha256": manifest["acceptancePlan"]["sha256"], "caseIds": [case["id"] for case in plan["cases"]]},
        "worktreeBinding": manifest["worktreeBinding"],
    }


def _validate_manifest(value: Any, alias: str, binding: WorktreeBinding) -> dict[str, Any]:
    expected = {"schemaId", "schemaVersion", "alias", "worktreeBinding", "goal", "context", "acceptancePlan"}
    if not isinstance(value, dict) or set(value) != expected or value.get("schemaId") != BUNDLE_SCHEMA_ID or value.get("schemaVersion") != 1 or value.get("alias") != alias:
        raise GoalWorkspaceError("WORKSPACE_MANIFEST", "manifest identity or fields are invalid")
    if value.get("worktreeBinding") != binding.view():
        raise GoalWorkspaceError("WORKSPACE_BINDING", "goal bundle belongs to a different worktree")
    if not isinstance(value.get("goal"), dict) or set(value["goal"]) != {"path", "contractVersion", "sha256"} or value["goal"].get("path") != "goal.txt" or value["goal"].get("contractVersion") != 1:
        raise GoalWorkspaceError("WORKSPACE_MANIFEST", "manifest goal binding is invalid")
    if not isinstance(value.get("context"), dict) or set(value["context"]) != {"path", "sha256", "bytes"} or value["context"].get("path") != "context.md":
        raise GoalWorkspaceError("WORKSPACE_MANIFEST", "manifest context binding is invalid")
    if not isinstance(value.get("acceptancePlan"), dict) or set(value["acceptancePlan"]) != {"path", "schemaVersion", "sha256"} or value["acceptancePlan"].get("path") != "acceptance-plan.json" or value["acceptancePlan"].get("schemaVersion") != 1:
        raise GoalWorkspaceError("WORKSPACE_MANIFEST", "manifest acceptance plan binding is invalid")
    return value


def view_goal_bundle(alias: str, cwd: str | Path | None = None) -> dict[str, Any]:
    alias = validate_alias(alias)
    binding = resolve_current_binding(cwd)
    root = Path(binding.target_worktree_root)
    bundle = root / ".steward" / "goals" / alias
    _require_real_directory(bundle, f"goal bundle {alias}")
    names = {item.name for item in bundle.iterdir()}
    required = {"manifest.json", "goal.txt", "context.md", "acceptance-plan.json"}
    if not required.issubset(names) or any(name not in required | {"verification"} for name in names):
        raise GoalWorkspaceError("WORKSPACE_LAYOUT", "goal bundle is partial or contains unexpected entries")
    if "verification" in names:
        _require_real_directory(bundle / "verification", "goal verification directory")
    manifest_bytes = read_regular_bytes(bundle / "manifest.json", label="goal manifest", max_bytes=MAX_PLAN_BYTES)
    try:
        manifest = _validate_manifest(json.loads(manifest_bytes.decode("utf-8"), object_pairs_hook=_strict_object), alias, binding)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GoalWorkspaceError("WORKSPACE_MANIFEST", "manifest is not UTF-8 JSON") from exc
    if manifest_bytes != canonical_json_bytes(manifest) + b"\n":
        raise GoalWorkspaceError("WORKSPACE_MANIFEST", "manifest is not canonical JSON")
    goal_bytes = read_regular_bytes(bundle / "goal.txt", label="goal.txt", max_bytes=20000)
    try:
        contract = validate_goal_text(goal_bytes)
    except GoalContractError as exc:
        raise GoalWorkspaceError("WORKSPACE_GOAL", str(exc)) from exc
    if goal_bytes != contract.objective.encode("utf-8") + b"\n" or goal_contract_sha256(contract) != manifest["goal"]["sha256"]:
        raise GoalWorkspaceError("WORKSPACE_GOAL", "goal.txt differs from its manifest")
    _validate_context_reference(contract, alias)
    context = read_regular_bytes(bundle / "context.md", label="context.md", max_bytes=MAX_CONTEXT_BYTES)
    try:
        canonical_context = _canonical_text(context.decode("utf-8"), "context", MAX_CONTEXT_BYTES)
    except UnicodeError as exc:
        raise GoalWorkspaceError("WORKSPACE_CONTEXT", "context.md is not UTF-8") from exc
    if sha256_bytes(context) != manifest["context"]["sha256"] or len(context) != manifest["context"]["bytes"] or canonical_context != context:
        raise GoalWorkspaceError("WORKSPACE_CONTEXT", "context.md differs from its manifest")
    plan_bytes = read_regular_bytes(bundle / "acceptance-plan.json", label="acceptance-plan.json", max_bytes=MAX_PLAN_BYTES)
    try:
        raw_plan = json.loads(plan_bytes.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GoalWorkspaceError("WORKSPACE_PLAN", "acceptance plan is not UTF-8 JSON") from exc
    plan = validate_acceptance_plan(raw_plan, [item.id for item in contract.completion_criteria])
    if plan_bytes != canonical_json_bytes(plan) + b"\n" or sha256_bytes(plan_bytes) != manifest["acceptancePlan"]["sha256"]:
        raise GoalWorkspaceError("WORKSPACE_PLAN", "acceptance plan differs from its manifest")
    return _bundle_view(alias, f".steward/goals/{alias}", manifest, contract, plan)


def validate_create_request(alias: str, raw: bytes, cwd: str | Path | None = None) -> dict[str, Any]:
    alias = validate_alias(alias)
    binding = resolve_current_binding(cwd)
    request = _load_create_request(raw, alias)
    return _bundle_view(alias, f".steward/goals/{alias}", _manifest(alias, binding, request), request.contract, request.plan)


def create_goal_bundle(alias: str, raw: bytes, cwd: str | Path | None = None) -> dict[str, Any]:
    alias = validate_alias(alias)
    binding = resolve_current_binding(cwd)
    request = _load_create_request(raw, alias)
    root = Path(binding.target_worktree_root)
    goals = _ensure_root(binding)
    target = goals / alias
    expected = _bundle_view(alias, f".steward/goals/{alias}", _manifest(alias, binding, request), request.contract, request.plan)
    if target.exists() or target.is_symlink():
        observed = view_goal_bundle(alias, root)
        if observed != expected:
            raise GoalWorkspaceError("WORKSPACE_CONFLICT", "goal alias already contains different content")
        return observed
    temporary = Path(tempfile.mkdtemp(prefix=f".{alias}.", dir=goals))
    try:
        files = {
            "goal.txt": request.goal_bytes,
            "context.md": request.context_bytes,
            "acceptance-plan.json": request.plan_bytes,
            "manifest.json": canonical_json_bytes(_manifest(alias, binding, request)) + b"\n",
        }
        for name, data in files.items():
            with (temporary / name).open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        if resolve_current_binding(root) != binding:
            raise GoalWorkspaceError("WORKSPACE_BINDING", "worktree binding changed during create")
        if target.exists() or target.is_symlink():
            raise GoalWorkspaceError("WORKSPACE_CONFLICT", "goal alias appeared during create")
        os.rename(temporary, target)
        return view_goal_bundle(alias, root)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def list_goal_bundles(cwd: str | Path | None = None) -> dict[str, Any]:
    binding = resolve_current_binding(cwd)
    goals = Path(binding.target_worktree_root) / ".steward" / "goals"
    if not goals.exists():
        aliases: list[str] = []
    else:
        _require_real_directory(goals, ".steward/goals")
        aliases = sorted(item.name for item in goals.iterdir() if ALIAS_PATTERN.fullmatch(item.name) and item.is_dir() and not item.is_symlink())
    return {"schemaId": "steward.goal-list", "schemaVersion": 1, "aliases": aliases}


def _read_stdin() -> bytes:
    if sys.stdin.buffer.isatty():
        raise GoalWorkspaceError("WORKSPACE_INPUT_TRANSPORT", "input must arrive through a finite non-TTY pipe")
    data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise GoalWorkspaceError("WORKSPACE_SIZE", "stdin input is too large")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage alias-scoped Steward GOAL bundles in the current worktree.")
    sub = parser.add_subparsers(dest="command", required=True)
    ensure = sub.add_parser("ensure-root")
    ensure.add_argument("target")
    for name in ("validate-create", "create"):
        command = sub.add_parser(name)
        command.add_argument("--goal", required=True)
        command.add_argument("input", choices=["-"])
    view = sub.add_parser("view")
    view.add_argument("--goal", required=True)
    sub.add_parser("list")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ensure-root":
            output = ensure_workspace_root(args.target)
        elif args.command == "validate-create":
            output = validate_create_request(args.goal, _read_stdin())
        elif args.command == "create":
            output = create_goal_bundle(args.goal, _read_stdin())
        elif args.command == "view":
            output = view_goal_bundle(args.goal)
        else:
            output = list_goal_bundles()
        sys.stdout.buffer.write(canonical_json_bytes(output) + b"\n")
        return 0
    except GoalWorkspaceError as exc:
        print("ERROR GOAL_WORKSPACE: " + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ERROR GOAL_WORKSPACE: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
