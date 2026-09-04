"""Alias-scoped Steward verification kernel."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import stat
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parents[2]
PLUGIN_SCRIPTS = PLUGIN_ROOT / "scripts"
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_STATE_BYTES = 32 * 1024 * 1024
MAX_SOURCE_SNAPSHOT_BYTES = 512 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 256 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
MAX_OUTPUT_BYTES = 5 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
EXECUTION_SCHEMA_VERSION = 1
ARTIFACT_SCHEMA_VERSION = 1
STATE_FIELDS = {
    "status",
    "sourceBaseline",
    "driftWarnings",
    "repairs",
    "attempts",
    "nextCaseIds",
    "lastFailure",
    "completion",
    "runtimePlatform",
    "authority",
}
ALLOWED_STATUSES = {"PENDING", "REPAIR_REQUIRED", "BLOCKED", "COMPLETE"}


def _load_shared(name: str):
    path = PLUGIN_SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"steward_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load shared module {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


goal_workspace = _load_shared("goal_workspace")


class VerificationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise VerificationError("INVALID_JSON", "value is not canonical JSON") from exc


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise VerificationError("INVALID_JSON", f"duplicate key: {key}")
        value[key] = item
    return value


def parse_json_bytes(raw: bytes, label: str) -> Any:
    if len(raw) > MAX_JSON_BYTES or raw.startswith(b"\xef\xbb\xbf"):
        raise VerificationError("INVALID_JSON", f"{label} is too large or has a BOM")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except VerificationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError("INVALID_JSON", f"cannot parse {label}") from exc


def _safe_relative(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise VerificationError(
            "UNSAFE_PATH", f"{label} is not a safe project-relative path"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or ".." in path.parts:
        raise VerificationError(
            "UNSAFE_PATH", f"{label} is not a safe project-relative path"
        )
    return value


def _resolve_project_path(root: Path, value: str, label: str) -> Path:
    relative = _safe_relative(value, label)
    unresolved = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or bool(
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise VerificationError(
                "UNSAFE_PATH", f"{label} uses a symlink/reparse path"
            )
    try:
        resolved = unresolved.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise VerificationError("UNSAFE_PATH", f"{label} escapes the worktree") from exc
    return unresolved


def _require_real_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise VerificationError("CAMPAIGN_INVALID", f"missing {label}") from exc
    except OSError as exc:
        raise VerificationError(
            "CAMPAIGN_INVALID", f"cannot inspect {label}: {exc}"
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or bool(
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    ):
        raise VerificationError("CAMPAIGN_INVALID", f"{label} must be a real directory")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    for key in getattr(
        goal_workspace, "GIT_REPOSITORY_ENVIRONMENT", ("GIT_DIR", "GIT_WORK_TREE")
    ):
        environment.pop(key, None)
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            env=environment,
        )
    except OSError as exc:
        raise VerificationError("GIT_ERROR", f"cannot execute git: {exc}") from exc


def _git_output(root: Path, *args: str) -> bytes:
    result = _git(root, *args)
    if result.returncode != 0:
        raise VerificationError(
            "GIT_ERROR",
            result.stderr.decode("utf-8", "replace").strip() or "git command failed",
        )
    return result.stdout


def _file_entry(root: Path, relative: str) -> dict[str, Any]:
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"path": relative, "kind": "missing"}
    except OSError as exc:
        raise VerificationError(
            "SOURCE_ERROR", f"cannot inspect source path {relative}: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        try:
            target = os.readlink(path).encode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise VerificationError(
                "SOURCE_ERROR", f"cannot read symlink {relative}"
            ) from exc
        return {
            "path": relative,
            "kind": "symlink",
            "mode": stat.S_IMODE(metadata.st_mode),
            "bytes": len(target),
            "sha256": sha256_bytes(target),
        }
    if not stat.S_ISREG(metadata.st_mode):
        raise VerificationError(
            "SOURCE_ERROR", f"source path is not a regular file: {relative}"
        )
    if metadata.st_size > MAX_SOURCE_FILE_BYTES:
        raise VerificationError("SOURCE_ERROR", f"source file is too large: {relative}")
    try:
        data = goal_workspace.read_regular_bytes(
            path, label=f"source file {relative}", max_bytes=MAX_SOURCE_FILE_BYTES
        )
        after = path.lstat()
    except (OSError, goal_workspace.GoalWorkspaceError) as exc:
        raise VerificationError(
            "SOURCE_ERROR", f"cannot read source file {relative}"
        ) from exc
    if (
        metadata.st_size != after.st_size
        or getattr(metadata, "st_mtime_ns", None) != getattr(after, "st_mtime_ns", None)
        or getattr(metadata, "st_ctime_ns", None) != getattr(after, "st_ctime_ns", None)
    ):
        raise VerificationError(
            "SOURCE_ERROR", f"source file changed while observed: {relative}"
        )
    return {
        "path": relative,
        "kind": "file",
        "mode": stat.S_IMODE(metadata.st_mode),
        "bytes": len(data),
        "lines": data.count(b"\n"),
        "sha256": sha256_bytes(data),
    }


def observe_source(root: Path, source_policy: dict[str, Any]) -> dict[str, Any]:
    head = _git_output(root, "rev-parse", "HEAD").decode("ascii", "strict").strip()
    index_digest = sha256_bytes(_git_output(root, "ls-files", "--stage", "-z"))
    writable = _writable_relative_paths(source_policy)
    if source_policy["mode"] == "git-visible":
        raw = _git_output(
            root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
        )
        try:
            candidates = [item.decode("utf-8") for item in raw.split(b"\0") if item]
        except UnicodeError as exc:
            raise VerificationError(
                "SOURCE_ERROR", "Git source paths are not UTF-8"
            ) from exc
        paths = sorted(
            {
                item
                for item in candidates
                if item != ".steward"
                and not item.startswith(".steward/")
                and item not in writable
            }
        )
    else:
        paths = sorted(set(source_policy["files"]) - writable)
    entries = [_file_entry(root, _safe_relative(path, "source path")) for path in paths]
    total = sum(item.get("bytes", 0) for item in entries)
    if total > MAX_SOURCE_TOTAL_BYTES:
        raise VerificationError("SOURCE_ERROR", "source set exceeds safe total size")
    value = {
        "mode": source_policy["mode"],
        "head": head,
        "indexSha256": index_digest,
        "entries": entries,
    }
    value["fingerprint"] = sha256_bytes(canonical_bytes(value))
    return value


def source_delta(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    old = {item["path"]: item for item in before["entries"]}
    new = {item["path"]: item for item in after["entries"]}
    changes: list[dict[str, Any]] = []
    for path in sorted(set(old) | set(new)):
        if old.get(path) != new.get(path):
            changes.append(
                {"path": path, "before": old.get(path), "after": new.get(path)}
            )
    if before.get("head") != after.get("head"):
        changes.append(
            {"path": "@HEAD", "before": before.get("head"), "after": after.get("head")}
        )
    if before.get("indexSha256") != after.get("indexSha256"):
        changes.append(
            {
                "path": "@INDEX",
                "before": before.get("indexSha256"),
                "after": after.get("indexSha256"),
            }
        )
    return changes


def persist_source_snapshot(campaign_root: Path, source: dict[str, Any]) -> dict[str, Any]:
    relative = f"sources/source-{uuid.uuid4().hex}.json"
    path = campaign_root / relative
    data = canonical_bytes(source) + b"\n"
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "fingerprint": source["fingerprint"],
        "snapshotPath": relative,
        "snapshotSha256": sha256_bytes(data),
    }


def load_source_snapshot(
    campaign_root: Path, binding: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(binding, dict) or set(binding) != {
        "fingerprint",
        "snapshotPath",
        "snapshotSha256",
    }:
        raise VerificationError(
            "SOURCE_SNAPSHOT_INVALID", "source baseline binding is invalid"
        )
    path = _resolve_project_path(
        campaign_root, binding["snapshotPath"], "source snapshot"
    )
    try:
        data = goal_workspace.read_regular_bytes(
            path, label="source snapshot", max_bytes=MAX_SOURCE_SNAPSHOT_BYTES
        )
    except goal_workspace.GoalWorkspaceError as exc:
        raise VerificationError("SOURCE_SNAPSHOT_INVALID", str(exc)) from exc
    if sha256_bytes(data) != binding["snapshotSha256"]:
        raise VerificationError(
            "SOURCE_SNAPSHOT_INVALID", "source snapshot digest changed"
        )
    value = parse_json_bytes(data, "source snapshot")
    if (
        not isinstance(value, dict)
        or value.get("fingerprint") != binding["fingerprint"]
        or data != canonical_bytes(value) + b"\n"
    ):
        raise VerificationError(
            "SOURCE_SNAPSHOT_INVALID", "source snapshot is not canonical or bound"
        )
    return value


def load_bundle(alias: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    try:
        view = goal_workspace.view_goal_bundle(alias)
        root = Path(view["worktreeBinding"]["targetWorktreeRoot"])
        plan_path = root / view["acceptancePlan"]["path"]
        plan = parse_json_bytes(
            goal_workspace.read_regular_bytes(
                plan_path, label="acceptance plan", max_bytes=MAX_JSON_BYTES
            ),
            "acceptance plan",
        )
        return root, view, plan
    except goal_workspace.GoalWorkspaceError as exc:
        raise VerificationError("GOAL_BUNDLE_INVALID", str(exc)) from exc


def validate_execution_plan(
    value: Any, acceptance: dict[str, Any], root: Path
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"schemaVersion", "cases"}
        or value.get("schemaVersion") != EXECUTION_SCHEMA_VERSION
        or type(value.get("schemaVersion")) is not int
    ):
        raise VerificationError(
            "EXECUTION_PLAN_INVALID", "execution plan fields/schemaVersion are invalid"
        )
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != len(acceptance["cases"]):
        raise VerificationError(
            "EXECUTION_PLAN_INVALID",
            "execution plan must bind every acceptance case in order",
        )
    normalized: list[dict[str, Any]] = []
    expected_fields = {"id", "argv", "cwd", "timeoutSeconds", "bindingRationale"}
    for intended, bound in zip(acceptance["cases"], cases, strict=True):
        if (
            not isinstance(bound, dict)
            or set(bound) != expected_fields
            or bound.get("id") != intended["id"]
        ):
            raise VerificationError(
                "EXECUTION_PLAN_INVALID",
                "execution case order/fields do not match acceptance plan",
            )
        argv = bound.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or any(
                not isinstance(item, str) or not item or "\x00" in item for item in argv
            )
        ):
            raise VerificationError(
                "EXECUTION_PLAN_INVALID", f"case {intended['id']} argv is invalid"
            )
        rationale = bound.get("bindingRationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise VerificationError(
                "EXECUTION_PLAN_INVALID",
                f"case {intended['id']} bindingRationale is required",
            )
        timeout = bound.get("timeoutSeconds")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
            or timeout > 7 * 24 * 3600
        ):
            raise VerificationError(
                "EXECUTION_PLAN_INVALID",
                f"case {intended['id']} timeoutSeconds is invalid",
            )
        cwd_value = bound.get("cwd")
        if not isinstance(cwd_value, str):
            raise VerificationError(
                "EXECUTION_PLAN_INVALID", f"case {intended['id']} cwd is invalid"
            )
        cwd = _resolve_project_path(root, cwd_value, f"case {intended['id']} cwd")
        if not cwd.is_dir():
            raise VerificationError(
                "EXECUTION_PLAN_INVALID", f"case {intended['id']} cwd does not exist"
            )
        normalized.append(dict(bound))
    return {"schemaVersion": 1, "cases": normalized}


def current_platform() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    return "posix"


def platform_available(requested: str, actual: str) -> bool:
    return (
        requested == "any"
        or requested == actual
        or (requested == "posix" and actual in {"linux", "darwin", "posix"})
    )


def _write_canonical(path: Path, value: Any) -> None:
    data = canonical_bytes(value) + b"\n"
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _write_state_atomic(path: Path, value: Any) -> None:
    data = canonical_bytes(value) + b"\n"
    tmp = path.parent / f"{path.name}.tmp-{uuid.uuid4().hex}"
    with tmp.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class Campaign:
    def __init__(
        self,
        alias: str,
        root: Path,
        view: dict[str, Any],
        acceptance: dict[str, Any],
        execution: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        self.alias = alias
        self.root = root
        self.view = view
        self.acceptance = acceptance
        self.execution = execution
        self.bundle = root / ".steward" / "goals" / alias
        self.verification = self.bundle / "verification"
        self.campaign_root = self.verification / "campaign"
        self.state_path = self.campaign_root / "state.json"
        self.state = state

    @classmethod
    def initialize(cls, alias: str, execution_raw: bytes) -> Campaign:
        root, view, acceptance = load_bundle(alias)
        execution = validate_execution_plan(
            parse_json_bytes(execution_raw, "execution plan"), acceptance, root
        )
        bundle = root / ".steward" / "goals" / alias
        verification = bundle / "verification"
        campaign_root = verification / "campaign"
        execution_path = verification / "execution-plan.json"
        execution_bytes = canonical_bytes(execution) + b"\n"
        if verification.exists():
            campaign = cls.load(alias)
            if (
                goal_workspace.read_regular_bytes(
                    execution_path, label="execution plan", max_bytes=MAX_JSON_BYTES
                )
                != execution_bytes
            ):
                raise VerificationError(
                    "CAMPAIGN_CONFLICT",
                    "verification already uses a different execution plan",
                )
            return campaign
        source = observe_source(root, acceptance["sourcePolicy"])
        verification.mkdir(mode=0o700)
        campaign_root.mkdir(mode=0o700)
        (campaign_root / "attempts").mkdir(mode=0o700)
        (campaign_root / "sources").mkdir(mode=0o700)
        with execution_path.open("xb") as handle:
            handle.write(execution_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        source_binding = persist_source_snapshot(campaign_root, source)
        state = {
            "status": "PENDING",
            "sourceBaseline": source_binding,
            "driftWarnings": [],
            "repairs": [],
            "attempts": [],
            "nextCaseIds": None,
            "lastFailure": None,
            "completion": None,
            "runtimePlatform": current_platform(),
            "authority": {
                "bundleManifestSha256": view["manifestSha256"],
                "acceptancePlanSha256": view["acceptancePlan"]["sha256"],
                "executionPlanSha256": sha256_bytes(execution_bytes),
                "worktreeBinding": view["worktreeBinding"],
            },
        }
        _write_canonical(campaign_root / "state.json", state)
        return cls.load(alias)

    @classmethod
    def load(cls, alias: str) -> Campaign:
        root, view, acceptance = load_bundle(alias)
        verification = root / ".steward" / "goals" / alias / "verification"
        _require_real_directory(verification, "verification directory")
        _require_real_directory(verification / "campaign", "campaign directory")
        _require_real_directory(
            verification / "campaign" / "attempts", "attempts directory"
        )
        _require_real_directory(
            verification / "campaign" / "sources", "source snapshots directory"
        )
        execution_path = verification / "execution-plan.json"
        state_path = verification / "campaign" / "state.json"
        try:
            execution_bytes = goal_workspace.read_regular_bytes(
                execution_path, label="execution plan", max_bytes=MAX_JSON_BYTES
            )
            execution = validate_execution_plan(
                parse_json_bytes(execution_bytes, "execution plan"), acceptance, root
            )
            if execution_bytes != canonical_bytes(execution) + b"\n":
                raise VerificationError(
                    "EXECUTION_PLAN_INVALID", "execution plan is not canonical JSON"
                )
            state_bytes = goal_workspace.read_regular_bytes(
                state_path, label="campaign state", max_bytes=MAX_STATE_BYTES
            )
        except goal_workspace.GoalWorkspaceError as exc:
            raise VerificationError("CAMPAIGN_INVALID", str(exc)) from exc
        state = parse_json_bytes(state_bytes, "campaign state")
        if (
            not isinstance(state, dict)
            or set(state) != STATE_FIELDS
            or state.get("status") not in ALLOWED_STATUSES
        ):
            raise VerificationError("STATE_INVALID", "campaign state has invalid fields")
        if state_bytes != canonical_bytes(state) + b"\n":
            raise VerificationError(
                "STATE_INVALID", "campaign state is not canonical JSON"
            )
        acceptance_by_id = {case["id"]: case for case in acceptance["cases"]}
        for attempt in state["attempts"]:
            waived_ids = attempt.get("waivedCaseIds")
            if waived_ids is None:
                continue
            if attempt.get("status") not in {"WAIVED", "FAILED"}:
                raise VerificationError(
                    "STATE_INVALID",
                    f"attempt {attempt.get('id')} records waivers with status {attempt.get('status')}",
                )
            runs_by_id = {run.get("caseId"): run for run in attempt.get("runs", [])}
            if (
                not isinstance(waived_ids, list)
                or not waived_ids
                or any(item not in runs_by_id for item in waived_ids)
            ):
                raise VerificationError(
                    "STATE_INVALID",
                    f"attempt {attempt.get('id')} records invalid waived cases",
                )
            for case_id in waived_ids:
                intended = acceptance_by_id.get(case_id)
                if (
                    runs_by_id[case_id].get("status") != "FAILED"
                    or intended is None
                    or not _case_waives_failure(intended)
                ):
                    raise VerificationError(
                        "STATE_INVALID",
                        f"attempt {attempt.get('id')} waives {case_id} without a declared optional failure",
                    )
        authority = state.get("authority", {})
        if (
            authority.get("bundleManifestSha256") != view["manifestSha256"]
            or authority.get("acceptancePlanSha256") != view["acceptancePlan"]["sha256"]
            or authority.get("executionPlanSha256") != sha256_bytes(execution_bytes)
            or authority.get("worktreeBinding") != view["worktreeBinding"]
        ):
            raise VerificationError(
                "AUTHORITY_DRIFT", "goal or verification authority changed"
            )
        load_source_snapshot(verification / "campaign", state["sourceBaseline"])
        return cls(alias, root, view, acceptance, execution, state)

    def save(self, state: dict[str, Any]) -> None:
        _write_state_atomic(self.state_path, state)
        self.state = state


def _clear_stale_lock(path: Path) -> bool:
    try:
        lock = parse_json_bytes(
            goal_workspace.read_regular_bytes(
                path, label="campaign lock", max_bytes=4096
            ),
            "campaign lock",
        )
    except goal_workspace.GoalWorkspaceError as read_error:
        raise VerificationError(
            "CAMPAIGN_LOCKED", f"cannot validate campaign lock: {read_error}"
        ) from read_error
    pid = lock.get("pid") if isinstance(lock, dict) else None
    if not isinstance(pid, int) or pid <= 0:
        raise VerificationError("CAMPAIGN_LOCKED", "campaign lock is malformed")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        path.unlink()
        return True
    except PermissionError:
        pass
    return False


@contextlib.contextmanager
def campaign_lock(campaign: Campaign) -> Iterator[None]:
    path = campaign.campaign_root / "campaign.lock"
    fd = -1
    for attempt in range(2):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError as exc:
            if attempt != 0:
                raise VerificationError(
                    "CAMPAIGN_LOCKED", "this GOAL campaign is already running"
                ) from exc
            if _clear_stale_lock(path):
                continue
            raise VerificationError(
                "CAMPAIGN_LOCKED", "this GOAL campaign is already running"
            ) from None
    if fd < 0:
        raise VerificationError("CAMPAIGN_LOCKED", "cannot acquire campaign lock")
    try:
        os.write(
            fd, canonical_bytes({"pid": os.getpid(), "createdAt": utc_now()}) + b"\n"
        )
        os.close(fd)
        fd = -1
        yield
    finally:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def _child_environment(artifact: Path, case_id: str) -> dict[str, str]:
    env = dict(os.environ)
    env["CLOSED_LOOP_EVIDENCE_DIR"] = str(artifact)
    env["CLOSED_LOOP_CASE_ID"] = case_id
    return env


def _artifact_manifest(directory: Path) -> dict[str, Any]:
    _require_real_directory(directory, "artifact directory")
    files: list[dict[str, Any]] = []
    total = 0
    for path in sorted(
        directory.rglob("*"), key=lambda item: item.relative_to(directory).as_posix()
    ):
        relative = path.relative_to(directory).as_posix()
        if relative == "artifact-manifest.json":
            continue
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode) and not path.is_symlink():
            continue
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise VerificationError(
                "ARTIFACT_INVALID", "artifact directory contains an unsafe entry"
            )
        data = goal_workspace.read_regular_bytes(
            path, label=f"artifact {relative}", max_bytes=MAX_ARTIFACT_BYTES
        )
        total += len(data)
        if total > MAX_ARTIFACT_BYTES:
            raise VerificationError(
                "ARTIFACT_INVALID", "artifacts exceed the safe total size"
            )
        files.append(
            {"path": relative, "bytes": len(data), "sha256": sha256_bytes(data)}
        )
    return {"artifactManifestVersion": ARTIFACT_SCHEMA_VERSION, "files": files}


_WRITABLE_CAPTURE_LIMIT_BYTES = 16 * 1024 * 1024


def _writable_relative_paths(source_policy: dict[str, Any]) -> frozenset[str]:
    writable = source_policy.get("writable")
    if not isinstance(writable, list):
        return frozenset()
    return frozenset(item for item in writable if isinstance(item, str))


def _capture_writable(
    root: Path, writable: frozenset[str]
) -> dict[str, dict[str, Any] | None]:
    """Snapshot the pre-run bytes and mode of every declared writable file.

    Fail closed when a pre-run writable state cannot be restored exactly; the
    rollback guarantee must never degrade into a silent absorb of the case's
    mutations.
    """
    captured: dict[str, dict[str, Any] | None] = {}
    for relative in sorted(writable):
        path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            captured[relative] = None
            continue
        except OSError as exc:
            raise VerificationError(
                "SOURCE_ERROR", f"cannot inspect writable path {relative}: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise VerificationError(
                "SOURCE_ERROR", f"writable path is not a regular file: {relative}"
            )
        if metadata.st_size > _WRITABLE_CAPTURE_LIMIT_BYTES:
            raise VerificationError(
                "SOURCE_ERROR",
                f"writable file is too large to snapshot for rollback: {relative}",
            )
        try:
            captured[relative] = {
                "mode": stat.S_IMODE(metadata.st_mode),
                "data": path.read_bytes(),
            }
        except OSError as exc:
            raise VerificationError(
                "SOURCE_ERROR", f"cannot read writable path {relative}: {exc}"
            ) from exc
    return captured


def _restore_writable_file(path: Path, original: dict[str, Any]) -> None:
    path.write_bytes(original["data"])
    os.chmod(path, original["mode"])


def _revert_writable(
    root: Path, captured: dict[str, dict[str, Any] | None]
) -> list[dict[str, str]]:
    """Undo case-run mutations of declared writable files; never touch anything else."""
    mutations: list[dict[str, str]] = []
    for relative, original in sorted(captured.items()):
        path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            if original is not None:
                _restore_writable_file(path, original)
                mutations.append({"path": relative, "action": "restored"})
            continue
        except OSError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            if original is None:
                continue
            if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                raise VerificationError(
                    "SOURCE_ERROR",
                    f"writable path was replaced by a directory: {relative}",
                )
            with contextlib.suppress(OSError):
                path.unlink()
            _restore_writable_file(path, original)
            mutations.append({"path": relative, "action": "restored"})
            continue
        if original is None:
            # File was absent before the run and now exists as a regular file
            # created by the case; remove it so the baseline holds.
            with contextlib.suppress(OSError):
                path.unlink()
                mutations.append({"path": relative, "action": "deleted"})
            continue
        try:
            changed = (
                path.read_bytes() != original["data"]
                or stat.S_IMODE(metadata.st_mode) != original["mode"]
            )
        except OSError:
            continue
        if changed:
            _restore_writable_file(path, original)
            mutations.append({"path": relative, "action": "restored"})
    return mutations


def _empty_run(
    campaign_root: Path, artifact: Path, case_id: str, run_id: str, status: str, reason: str, fingerprint: str
) -> dict[str, Any]:
    (artifact / "stdout.txt").write_text("", encoding="utf-8")
    (artifact / "stderr.txt").write_text("", encoding="utf-8")
    return {
        "caseId": case_id,
        "runId": run_id,
        "status": status,
        "reason": reason,
        "artifactDir": str(artifact.relative_to(campaign_root)),
        "sourceBeforeFingerprint": fingerprint,
        "sourceAfterFingerprint": fingerprint,
        "exitCode": None,
        "timedOut": False,
    }


def execute_case(
    campaign: Campaign,
    attempt_id: str,
    intended: dict[str, Any],
    bound: dict[str, Any],
    ordinal: int,
) -> dict[str, Any]:
    case_id = intended["id"]
    run_id = f"run-{ordinal:04d}-{case_id}-{uuid.uuid4().hex[:8]}"
    artifact = campaign.campaign_root / "attempts" / attempt_id / run_id
    artifact.mkdir(parents=True, mode=0o700)
    writable = _writable_relative_paths(campaign.acceptance["sourcePolicy"])
    captured = _capture_writable(campaign.root, writable) if writable else {}
    before = observe_source(campaign.root, campaign.acceptance["sourcePolicy"])
    if not platform_available(intended["platform"], campaign.state["runtimePlatform"]):
        status = "BLOCKED" if intended["required"] else "NOT_RUN"
        result = _empty_run(
            campaign.campaign_root,
            artifact,
            case_id,
            run_id,
            status,
            "case platform is unavailable",
            before["fingerprint"],
        )
    else:
        cwd = _resolve_project_path(campaign.root, bound["cwd"], f"case {case_id} cwd")
        try:
            process = subprocess.Popen(
                bound["argv"],
                cwd=cwd,
                env=_child_environment(artifact, case_id),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except OSError as exc:
            result = _empty_run(
                campaign.campaign_root,
                artifact,
                case_id,
                run_id,
                "BLOCKED",
                f"cannot start command: {exc}",
                before["fingerprint"],
            )
        else:
            timed_out = False
            try:
                stdout, stderr = process.communicate(
                    timeout=float(bound["timeoutSeconds"])
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                stdout, stderr = process.communicate()
            exit_code = process.returncode
            stdout = stdout[:MAX_OUTPUT_BYTES]
            stderr = stderr[:MAX_OUTPUT_BYTES]
            (artifact / "stdout.txt").write_text(
                stdout.decode("utf-8", "replace"), encoding="utf-8"
            )
            (artifact / "stderr.txt").write_text(
                stderr.decode("utf-8", "replace"), encoding="utf-8"
            )
            missing: list[str] = []
            empty: list[str] = []
            evidence = intended["evidence"]
            for relative in evidence["requiredFiles"]:
                path = _resolve_project_path(
                    artifact, relative, f"case {case_id} evidence"
                )
                if not path.is_file() or path.is_symlink():
                    missing.append(relative)
            for relative in evidence["nonEmptyFiles"]:
                path = _resolve_project_path(
                    artifact, relative, f"case {case_id} evidence"
                )
                if path.is_file() and path.stat().st_size == 0:
                    empty.append(relative)
            status = (
                "PASS"
                if exit_code == 0 and not timed_out and not missing and not empty
                else "FAILED"
            )
            reason = (
                "case passed"
                if status == "PASS"
                else "command failed, timed out, or declared evidence is missing"
            )
            result = {
                "caseId": case_id,
                "runId": run_id,
                "status": status,
                "reason": reason,
                "artifactDir": str(artifact.relative_to(campaign.campaign_root)),
                "sourceBeforeFingerprint": before["fingerprint"],
                "sourceAfterFingerprint": None,
                "exitCode": exit_code,
                "timedOut": timed_out,
                "missingEvidence": missing,
                "emptyEvidence": empty,
            }
    mutations = _revert_writable(campaign.root, captured)
    if captured:
        _write_canonical(
            artifact / "writable-capture.json",
            {"captured": sorted(captured), "mutations": mutations},
        )
    after = observe_source(campaign.root, campaign.acceptance["sourcePolicy"])
    result["sourceAfterFingerprint"] = after["fingerprint"]
    result["writableMutations"] = mutations
    if result["status"] not in {"BLOCKED", "NOT_RUN"} and after["fingerprint"] != before["fingerprint"]:
        result["status"] = "FAILED"
        result["reason"] = "case modified protected source; treat as a required fix"
        result["sourceDelta"] = source_delta(before, after)
    result["failureSignature"] = sha256_bytes(
        canonical_bytes(
            {
                "caseId": case_id,
                "status": result["status"],
                "reason": result["reason"],
                "exitCode": result.get("exitCode"),
                "stdout": sha256_bytes((artifact / "stdout.txt").read_bytes()),
                "stderr": sha256_bytes((artifact / "stderr.txt").read_bytes()),
            }
        )
    )
    _write_canonical(artifact / "result.json", result)
    manifest = _artifact_manifest(artifact)
    _write_canonical(artifact / "artifact-manifest.json", manifest)
    result["artifactManifestSha256"] = sha256_bytes(canonical_bytes(manifest) + b"\n")
    return result


def _copy_state(state: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(state))
    except (TypeError, ValueError, RecursionError) as exc:
        raise VerificationError(
            "INVALID_STATE", "campaign state is not JSON-representable"
        ) from exc


def _case_waives_failure(intended: dict[str, Any]) -> bool:
    return intended.get("onFailure") == "waive-with-report" and not intended["required"]


def _refresh_baseline(campaign: Campaign) -> None:
    """Absorb source edits made between calls as the new baseline instead of blocking."""
    state = _copy_state(campaign.state)
    current = observe_source(campaign.root, campaign.acceptance["sourcePolicy"])
    if current["fingerprint"] == state["sourceBaseline"]["fingerprint"]:
        return
    before = load_source_snapshot(campaign.campaign_root, state["sourceBaseline"])
    state["driftWarnings"].append(
        {"at": utc_now(), "changes": source_delta(before, current)}
    )
    state["sourceBaseline"] = persist_source_snapshot(campaign.campaign_root, current)
    campaign.save(state)


def _first_unresolved_failure(
    acceptance: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    """Latest evidence per case, in acceptance order; None once every failure
    still standing is individually tolerated by its own plan declaration."""
    evidence: dict[str, dict[str, Any]] = {}
    for attempt in state["attempts"]:
        for run in attempt["runs"]:
            evidence[run["caseId"]] = run
    for case in acceptance["cases"]:
        run = evidence.get(case["id"])
        if run is not None and run["status"] == "FAILED" and not _case_waives_failure(case):
            return run
    return None


def run_phase(campaign: Campaign) -> tuple[dict[str, Any], int]:
    state = _copy_state(campaign.state)
    case_ids = state["nextCaseIds"] or [case["id"] for case in campaign.acceptance["cases"]]
    mode = "retest" if state["nextCaseIds"] else "initial"
    attempts = state["attempts"]
    if attempts and attempts[-1]["caseIds"] == case_ids and attempts[-1]["status"] in {
        "RUNNING",
        "BLOCKED",
    }:
        attempt = attempts[-1]
        attempt["status"] = "RUNNING"
        attempt["runs"] = [run for run in attempt["runs"] if run["status"] != "BLOCKED"]
    else:
        attempt_id = f"attempt-{len(attempts) + 1:04d}-{mode}-{uuid.uuid4().hex[:8]}"
        attempt = {
            "id": attempt_id,
            "mode": mode,
            "sourceFingerprint": state["sourceBaseline"]["fingerprint"],
            "caseIds": case_ids,
            "runs": [],
            "status": "RUNNING",
        }
        attempts.append(attempt)
    campaign.save(state)
    already_run = {run["caseId"] for run in attempt["runs"]}
    acceptance_by_id = {case["id"]: case for case in campaign.acceptance["cases"]}
    execution_by_id = {case["id"]: case for case in campaign.execution["cases"]}
    for ordinal, case_id in enumerate(case_ids, 1):
        if case_id in already_run:
            continue
        result = execute_case(
            campaign, attempt["id"], acceptance_by_id[case_id], execution_by_id[case_id], ordinal
        )
        state = _copy_state(campaign.state)
        state["attempts"][-1]["runs"].append(result)
        campaign.save(state)
        if result["status"] == "BLOCKED":
            state = _copy_state(campaign.state)
            state["attempts"][-1]["status"] = "BLOCKED"
            state["status"] = "BLOCKED"
            campaign.save(state)
            return status_report(campaign), 1
    # Every case_id in this attempt now has a terminal, non-blocked run. A
    # required (or otherwise undeclared) failure does not stop the sweep
    # anymore, so every other case in the same attempt still gets recorded
    # evidence instead of being silently skipped by an early exit.
    state = _copy_state(campaign.state)
    active = state["attempts"][-1]
    failed_ids = [run["caseId"] for run in active["runs"] if run["status"] == "FAILED"]
    waived_ids = [cid for cid in failed_ids if _case_waives_failure(acceptance_by_id[cid])]
    blocking_ids = [cid for cid in failed_ids if cid not in waived_ids]
    active["status"] = "FAILED" if blocking_ids else ("WAIVED" if waived_ids else "PASS")
    if waived_ids:
        active["waivedCaseIds"] = waived_ids
    pending = _first_unresolved_failure(campaign.acceptance, state)
    if pending is not None:
        state["lastFailure"] = pending
        state["status"] = "REPAIR_REQUIRED"
        state["nextCaseIds"] = [pending["caseId"]]
        campaign.save(state)
        return status_report(campaign), 1
    state["lastFailure"] = None
    state["nextCaseIds"] = None
    campaign.save(state)
    return finalize(campaign)


def record_repair(campaign: Campaign, raw: bytes) -> dict[str, Any]:
    if campaign.state["status"] != "REPAIR_REQUIRED" or not campaign.state.get(
        "lastFailure"
    ):
        raise VerificationError(
            "INVALID_STATE", "record-repair requires a failed project-source case"
        )
    value = parse_json_bytes(raw, "repair payload")
    expected = {"rootCause", "rootCauseSource", "fixSummary"}
    if not isinstance(value, dict) or set(value) != expected:
        raise VerificationError("REPAIR_INVALID", "repair fields are invalid")
    for field in ("rootCause", "fixSummary"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise VerificationError("REPAIR_INVALID", f"{field} is required")
    source = value.get("rootCauseSource")
    if not isinstance(source, dict) or set(source) not in (
        {"path", "lineStart", "lineEnd"},
        {"path", "lineStart", "lineEnd", "symbol"},
    ):
        raise VerificationError("REPAIR_INVALID", "rootCauseSource fields are invalid")
    source_path = source.get("path")
    if not isinstance(source_path, str):
        raise VerificationError("REPAIR_INVALID", "rootCauseSource.path is invalid")
    path = _safe_relative(source_path, "rootCauseSource.path")
    if (
        isinstance(source.get("lineStart"), bool)
        or not isinstance(source.get("lineStart"), int)
        or not isinstance(source.get("lineEnd"), int)
        or source["lineStart"] < 1
        or source["lineEnd"] < source["lineStart"]
    ):
        raise VerificationError(
            "REPAIR_INVALID", "rootCauseSource line range is invalid"
        )
    before = load_source_snapshot(
        campaign.campaign_root, campaign.state["sourceBaseline"]
    )
    old_entry = next((item for item in before["entries"] if item["path"] == path), None)
    if (
        old_entry is None
        or old_entry.get("kind") != "file"
        or source["lineEnd"] > max(1, old_entry.get("lines", 0))
    ):
        raise VerificationError(
            "REPAIR_INVALID",
            "rootCauseSource is not proven by the failed source snapshot",
        )
    after = observe_source(campaign.root, campaign.acceptance["sourcePolicy"])
    delta = source_delta(before, after)
    if not delta:
        raise VerificationError(
            "REPAIR_INVALID", "repair did not change protected source"
        )
    failure = campaign.state["lastFailure"]
    repeat_key = sha256_bytes(
        canonical_bytes(
            {
                "failureSignature": failure["failureSignature"],
                "rootCauseSource": source,
                "failedSource": before["fingerprint"],
            }
        )
    )
    if any(item["repeatKey"] == repeat_key for item in campaign.state["repairs"]):
        raise VerificationError(
            "NO_PROGRESS",
            "the same machine-bound failure and source location already has a repair",
        )
    repair = {
        "rootCause": value["rootCause"],
        "rootCauseSource": source,
        "fixSummary": value["fixSummary"],
        "failedCaseId": failure["caseId"],
        "failedSourceFingerprint": before["fingerprint"],
        "acceptedSourceFingerprint": after["fingerprint"],
        "sourceDelta": delta,
        "repeatKey": repeat_key,
    }
    state = _copy_state(campaign.state)
    state["repairs"].append(repair)
    state["sourceBaseline"] = persist_source_snapshot(campaign.campaign_root, after)
    state["nextCaseIds"] = [failure["caseId"]]
    state["status"] = "PENDING"
    campaign.save(state)
    return status_report(campaign)


def _verify_artifact(campaign: Campaign, run: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    directory = campaign.campaign_root / run["artifactDir"]
    try:
        manifest_bytes = goal_workspace.read_regular_bytes(
            directory / "artifact-manifest.json",
            label="artifact manifest",
            max_bytes=MAX_JSON_BYTES,
        )
        if sha256_bytes(manifest_bytes) != run.get("artifactManifestSha256"):
            errors.append(f"artifact manifest digest changed for {run['caseId']}")
            return errors
        manifest = parse_json_bytes(manifest_bytes, "artifact manifest")
        if manifest != _artifact_manifest(directory):
            errors.append(f"artifact files changed for {run['caseId']}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"cannot validate artifacts for {run['caseId']}: {exc}")
    return errors


def _evaluate(campaign: Campaign) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Compute whether current attempts plus current disk state count as complete.

    Later attempts supply fresher per-case evidence than earlier ones, so a
    targeted retest naturally overrides only the case(s) it re-ran.
    """
    evidence: dict[str, dict[str, Any]] = {}
    for attempt in campaign.state["attempts"]:
        for run in attempt["runs"]:
            evidence[run["caseId"]] = run
    errors: list[str] = []
    try:
        final_root, final_view, final_acceptance = load_bundle(campaign.alias)
        execution_bytes = goal_workspace.read_regular_bytes(
            campaign.verification / "execution-plan.json",
            label="execution plan",
            max_bytes=MAX_JSON_BYTES,
        )
        if (
            final_root != campaign.root
            or final_view != campaign.view
            or final_acceptance != campaign.acceptance
            or sha256_bytes(execution_bytes)
            != campaign.state["authority"]["executionPlanSha256"]
        ):
            errors.append("GOAL or execution authority changed")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"cannot revalidate GOAL authority: {exc}")
    for intended in campaign.acceptance["cases"]:
        run = evidence.get(intended["id"])
        if run is None:
            errors.append(f"case {intended['id']} lacks evidence")
            continue
        tolerated = run["status"] == "FAILED" and _case_waives_failure(intended)
        if run["status"] == "FAILED" and not tolerated:
            errors.append(f"case {intended['id']} failed without a declared waiver")
        if run["status"] in {"PASS", "NOT_RUN"} or tolerated:
            errors.extend(_verify_artifact(campaign, run))
    for criterion in campaign.view["goalContract"]["criteriaIds"]:
        if not any(
            case["required"]
            and criterion in case["coversCriteria"]
            and evidence.get(case["id"], {}).get("status") == "PASS"
            for case in campaign.acceptance["cases"]
        ):
            errors.append(f"criterion {criterion} lacks required PASS evidence")
    return errors, evidence


def finalize(campaign: Campaign) -> tuple[dict[str, Any], int]:
    errors, evidence = _evaluate(campaign)
    state = _copy_state(campaign.state)
    if errors:
        state["status"] = "BLOCKED"
        campaign.save(state)
        return status_report(campaign, errors), 1
    source = observe_source(campaign.root, campaign.acceptance["sourcePolicy"])
    state["status"] = "COMPLETE"
    state["completion"] = {
        "sourceFingerprint": source["fingerprint"],
        "bundleManifestSha256": campaign.view["manifestSha256"],
        "executionPlanSha256": campaign.state["authority"]["executionPlanSha256"],
        "evidenceRunIds": {
            case_id: run["runId"] for case_id, run in evidence.items()
        },
    }
    campaign.save(state)
    return status_report(campaign), 0


def completion_status(campaign: Campaign) -> tuple[str, list[str]]:
    if campaign.state["status"] != "COMPLETE" or campaign.state.get("completion") is None:
        return "INCOMPLETE", []
    errors, _ = _evaluate(campaign)
    return ("COMPLETE" if not errors else "INCOMPLETE"), errors


def status_report(
    campaign: Campaign, errors: list[str] | None = None
) -> dict[str, Any]:
    completion, current_errors = completion_status(campaign)
    return {
        "schemaId": "steward.verification-status",
        "schemaVersion": 1,
        "goal": campaign.alias,
        "goalPath": campaign.view["path"],
        "executionStatus": campaign.state["status"],
        "completionStatus": completion,
        "sourceFingerprint": campaign.state["sourceBaseline"]["fingerprint"],
        "driftWarnings": campaign.state["driftWarnings"],
        "repairs": campaign.state["repairs"],
        "attempts": campaign.state["attempts"],
        "lastFailure": campaign.state.get("lastFailure"),
        "waivedCaseIds": sorted(
            set().union(
                *(
                    set(item.get("waivedCaseIds", []))
                    for item in campaign.state["attempts"]
                )
            )
        )
        if campaign.state["attempts"]
        else [],
        "completion": campaign.state.get("completion"),
        "errors": list(errors or []) + current_errors,
    }


def advance(campaign: Campaign) -> tuple[dict[str, Any], int]:
    """Run the campaign until it needs a human decision or reaches completion.

    Stops only at REPAIR_REQUIRED, BLOCKED, or COMPLETE; each phase still
    saves its own state so an interruption resumes the in-progress attempt.
    """
    while True:
        status = campaign.state["status"]
        if status == "COMPLETE":
            report = status_report(campaign)
            return report, 0 if report["completionStatus"] == "COMPLETE" else 1
        if status == "REPAIR_REQUIRED":
            return status_report(campaign), 1
        if status in {"PENDING", "BLOCKED"}:
            _refresh_baseline(campaign)
            report, code = run_phase(campaign)
            if code != 0:
                return report, code
            continue
        raise VerificationError("INVALID_STATE", f"cannot advance state {status}")


__all__ = [
    "Campaign",
    "VerificationError",
    "advance",
    "campaign_lock",
    "canonical_bytes",
    "record_repair",
    "status_report",
]
