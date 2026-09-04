"""Alias-scoped, journal-only Steward verification kernel."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import re
import signal
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
MAX_SOURCE_SNAPSHOT_BYTES = 512 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 256 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
MAX_OUTPUT_BYTES = 5 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
EXECUTION_SCHEMA_VERSION = 1
JOURNAL_SCHEMA_VERSION = 1
ARTIFACT_SCHEMA_VERSION = 1
ALLOWED_EVENT_TYPES = {
    "campaign_initialized",
    "attempt_started",
    "case_finished",
    "attempt_finished",
    "repair_recorded",
    "source_drift_blocked",
    "blocker_cleared",
    "audit_rejected",
    "audit_succeeded",
}
STATE_FIELDS = {
    "status",
    "resumeStatus",
    "sourceBaseline",
    "repairs",
    "attempts",
    "lastFailure",
    "finalRegressionAttemptId",
    "successfulAudit",
    "runtimePlatform",
    "authority",
}
ALLOWED_STATUSES = {
    "PENDING",
    "RUNNING",
    "REPAIR_REQUIRED",
    "RETEST_REQUIRED",
    "REGRESSION_REQUIRED",
    "AUDIT_REQUIRED",
    "BLOCKED",
    "COMPLETE",
}
SAFE_ENV = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TMP",
    "TEMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
}
SECRET_PATTERNS = [
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret|credential)\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
]


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


def _redact(value: str) -> tuple[str, bool]:
    found = False
    for pattern in SECRET_PATTERNS:
        value, count = pattern.subn("<REDACTED>", value)
        found = found or bool(count)
    return value, found


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


def persist_source_snapshot(
    campaign_root: Path, source: dict[str, Any], ordinal: int
) -> dict[str, Any]:
    relative = f"sources/source-{ordinal:04d}.json"
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
        if _redact(" ".join(argv))[1]:
            raise VerificationError(
                "EXECUTION_PLAN_INVALID",
                f"case {intended['id']} argv contains secret-like data",
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


class Campaign:
    def __init__(
        self,
        alias: str,
        root: Path,
        view: dict[str, Any],
        acceptance: dict[str, Any],
        execution: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        self.alias = alias
        self.root = root
        self.view = view
        self.acceptance = acceptance
        self.execution = execution
        self.bundle = root / ".steward" / "goals" / alias
        self.verification = self.bundle / "verification"
        self.campaign_root = self.verification / "campaign"
        self.events_path = self.campaign_root / "events.jsonl"
        self.events = events
        self.state = events[-1]["state"]

    @staticmethod
    def _event(
        previous: dict[str, Any] | None,
        event_type: str,
        state: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        base = {
            "journalSchemaVersion": JOURNAL_SCHEMA_VERSION,
            "sequence": 1 if previous is None else previous["sequence"] + 1,
            "previousHash": None if previous is None else previous["hash"],
            "timestamp": utc_now(),
            "type": event_type,
            "payload": payload,
            "state": state,
        }
        base["hash"] = sha256_bytes(canonical_bytes(base))
        return base

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
        try:
            verification.mkdir(mode=0o700)
            campaign_root.mkdir(mode=0o700)
            (campaign_root / "attempts").mkdir(mode=0o700)
            (campaign_root / "sources").mkdir(mode=0o700)
            with execution_path.open("xb") as handle:
                handle.write(execution_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            source_binding = persist_source_snapshot(campaign_root, source, 1)
            state = {
                "status": "PENDING",
                "resumeStatus": None,
                "sourceBaseline": source_binding,
                "repairs": [],
                "attempts": [],
                "lastFailure": None,
                "finalRegressionAttemptId": None,
                "successfulAudit": None,
                "runtimePlatform": current_platform(),
                "authority": {
                    "bundleManifestSha256": view["manifestSha256"],
                    "acceptancePlanSha256": view["acceptancePlan"]["sha256"],
                    "executionPlanSha256": sha256_bytes(execution_bytes),
                    "worktreeBinding": view["worktreeBinding"],
                },
            }
            event = cls._event(None, "campaign_initialized", state, {"alias": alias})
            with (campaign_root / "events.jsonl").open("xb") as handle:
                handle.write(canonical_bytes(event) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            # Leave partial state in place for fail-closed diagnosis; never replace it.
            raise
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
        events_path = verification / "campaign" / "events.jsonl"
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
            journal = goal_workspace.read_regular_bytes(
                events_path, label="campaign journal", max_bytes=256 * 1024 * 1024
            )
        except goal_workspace.GoalWorkspaceError as exc:
            raise VerificationError("CAMPAIGN_INVALID", str(exc)) from exc
        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(journal.splitlines(), 1):
            event = parse_json_bytes(line, f"journal line {line_number}")
            expected = {
                "journalSchemaVersion",
                "sequence",
                "previousHash",
                "timestamp",
                "type",
                "payload",
                "state",
                "hash",
            }
            if (
                not isinstance(event, dict)
                or set(event) != expected
                or event["journalSchemaVersion"] != 1
                or event["sequence"] != line_number
            ):
                raise VerificationError(
                    "JOURNAL_INVALID", f"journal line {line_number} has invalid fields"
                )
            if (
                event["type"] not in ALLOWED_EVENT_TYPES
                or not isinstance(event["payload"], dict)
                or not isinstance(event["state"], dict)
                or set(event["state"]) != STATE_FIELDS
                or event["state"].get("status") not in ALLOWED_STATUSES
            ):
                raise VerificationError(
                    "JOURNAL_INVALID",
                    f"journal line {line_number} has an invalid event or state",
                )
            if line_number == 1 and (
                event["type"] != "campaign_initialized"
                or event["state"]["status"] != "PENDING"
            ):
                raise VerificationError(
                    "JOURNAL_INVALID",
                    "journal must start with campaign_initialized/PENDING",
                )
            if event["previousHash"] != (None if not events else events[-1]["hash"]):
                raise VerificationError(
                    "JOURNAL_INVALID",
                    f"journal line {line_number} breaks the hash chain",
                )
            unhashed = dict(event)
            observed_hash = unhashed.pop("hash")
            if sha256_bytes(canonical_bytes(unhashed)) != observed_hash:
                raise VerificationError(
                    "JOURNAL_INVALID", f"journal line {line_number} has an invalid hash"
                )
            events.append(event)
        if not events:
            raise VerificationError("JOURNAL_INVALID", "campaign journal is empty")
        campaign = cls(alias, root, view, acceptance, execution, events)
        acceptance_by_id = {case["id"]: case for case in campaign.acceptance["cases"]}
        for attempt in campaign.state["attempts"]:
            waived_ids = attempt.get("waivedCaseIds")
            if attempt.get("status") != "WAIVED":
                if waived_ids is not None:
                    raise VerificationError(
                        "JOURNAL_INVALID",
                        f"attempt {attempt.get('id')} records waivers without WAIVED status",
                    )
                continue
            runs_by_id = {run.get("caseId"): run for run in attempt.get("runs", [])}
            if (
                not isinstance(waived_ids, list)
                or not waived_ids
                or any(item not in runs_by_id for item in waived_ids)
            ):
                raise VerificationError(
                    "JOURNAL_INVALID",
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
                        "JOURNAL_INVALID",
                        f"attempt {attempt.get('id')} waives {case_id} without a declared optional failure",
                    )
        authority = campaign.state.get("authority", {})
        if (
            authority.get("bundleManifestSha256") != view["manifestSha256"]
            or authority.get("acceptancePlanSha256") != view["acceptancePlan"]["sha256"]
            or authority.get("executionPlanSha256") != sha256_bytes(execution_bytes)
            or authority.get("worktreeBinding") != view["worktreeBinding"]
        ):
            raise VerificationError(
                "AUTHORITY_DRIFT", "goal or verification authority changed"
            )
        load_source_snapshot(campaign.campaign_root, campaign.state["sourceBaseline"])
        return campaign

    def commit(
        self, event_type: str, state: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        event = self._event(self.events[-1], event_type, state, payload)
        with self.events_path.open("ab") as handle:
            handle.write(canonical_bytes(event) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
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
    env = {key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV}
    env["CLOSED_LOOP_EVIDENCE_DIR"] = str(artifact)
    env["CLOSED_LOOP_CASE_ID"] = case_id
    return env


def _terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        pass
    with contextlib.suppress(subprocess.SubprocessError):
        process.wait(timeout=5)


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


def _redact_text_artifacts(directory: Path) -> bool:
    found = False
    for path in sorted(directory.rglob("*")):
        if path.is_dir() or path.name in {
            "stdout.txt",
            "stderr.txt",
            "result.json",
            "artifact-manifest.json",
        }:
            continue
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or metadata.st_size > MAX_ARTIFACT_BYTES
        ):
            continue
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            continue
        redacted, observed = _redact(text)
        if observed:
            path.write_text(redacted, encoding="utf-8")
            found = True
    return found


def _write_canonical(path: Path, value: Any) -> None:
    data = canonical_bytes(value) + b"\n"
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


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
    if before["fingerprint"] != campaign.state["sourceBaseline"]["fingerprint"]:
        result = {
            "caseId": case_id,
            "runId": run_id,
            "status": "BLOCKED",
            "reason": "source differs from the accepted baseline",
            "artifactDir": str(artifact.relative_to(campaign.campaign_root)),
            "sourceBeforeFingerprint": before["fingerprint"],
            "sourceAfterFingerprint": before["fingerprint"],
            "exitCode": None,
            "timedOut": False,
            "secretRedacted": False,
        }
        (artifact / "stdout.txt").write_text("", encoding="utf-8")
        (artifact / "stderr.txt").write_text("", encoding="utf-8")
    elif not platform_available(
        intended["platform"], campaign.state["runtimePlatform"]
    ):
        status = "BLOCKED" if intended["required"] else "NOT_RUN"
        result = {
            "caseId": case_id,
            "runId": run_id,
            "status": status,
            "reason": "case platform is unavailable",
            "artifactDir": str(artifact.relative_to(campaign.campaign_root)),
            "sourceBeforeFingerprint": before["fingerprint"],
            "sourceAfterFingerprint": before["fingerprint"],
            "exitCode": None,
            "timedOut": False,
            "secretRedacted": False,
        }
        (artifact / "stdout.txt").write_text("", encoding="utf-8")
        (artifact / "stderr.txt").write_text("", encoding="utf-8")
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
                start_new_session=(os.name == "posix"),
            )
        except OSError as exc:
            result = {
                "caseId": case_id,
                "runId": run_id,
                "status": "BLOCKED",
                "reason": f"cannot start command: {exc}",
                "artifactDir": str(artifact.relative_to(campaign.campaign_root)),
                "sourceBeforeFingerprint": before["fingerprint"],
                "sourceAfterFingerprint": before["fingerprint"],
                "exitCode": None,
                "timedOut": False,
                "secretRedacted": False,
            }
            (artifact / "stdout.txt").write_text("", encoding="utf-8")
            (artifact / "stderr.txt").write_text("", encoding="utf-8")
        else:
            timed_out = False
            try:
                stdout, stderr = process.communicate(
                    timeout=float(bound["timeoutSeconds"])
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate(process)
                stdout, stderr = process.communicate()
            exit_code = process.returncode
            _terminate(process)
            stdout = stdout[:MAX_OUTPUT_BYTES]
            stderr = stderr[:MAX_OUTPUT_BYTES]
            stdout_text, stdout_secret = _redact(stdout.decode("utf-8", "replace"))
            stderr_text, stderr_secret = _redact(stderr.decode("utf-8", "replace"))
            (artifact / "stdout.txt").write_text(stdout_text, encoding="utf-8")
            (artifact / "stderr.txt").write_text(stderr_text, encoding="utf-8")
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
            evidence_secret = _redact_text_artifacts(artifact)
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
                "secretRedacted": stdout_secret or stderr_secret or evidence_secret,
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
    if after["fingerprint"] != before["fingerprint"]:
        result["status"] = "BLOCKED"
        result["reason"] = (
            "case changed protected source; restore the accepted baseline"
        )
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


def _attempt_mode(status: str) -> str:
    return {
        "PENDING": "initial",
        "RETEST_REQUIRED": "retest",
        "REGRESSION_REQUIRED": "regression",
        "RUNNING": "resume",
    }.get(status, "unknown")


def run_phase(
    campaign: Campaign, requested_status: str | None = None
) -> tuple[dict[str, Any], int]:
    state = _copy_state(campaign.state)
    status = requested_status or state["status"]
    if status == "RUNNING":
        status = state.get("resumeStatus") or "PENDING"
    mode = _attempt_mode(status)
    if mode == "unknown":
        raise VerificationError(
            "INVALID_STATE", f"cannot run cases from state {status}"
        )
    if status == "RETEST_REQUIRED":
        case_ids = [state["lastFailure"]["caseId"]]
    else:
        case_ids = [case["id"] for case in campaign.acceptance["cases"]]
    attempt_id = f"attempt-{len(state['attempts']) + 1:04d}-{mode}-{state['sourceBaseline']['fingerprint'][7:15]}"
    attempt = {
        "id": attempt_id,
        "mode": mode,
        "sourceFingerprint": state["sourceBaseline"]["fingerprint"],
        "caseIds": case_ids,
        "runs": [],
        "status": "RUNNING",
    }
    state["attempts"].append(attempt)
    state["status"] = "RUNNING"
    state["resumeStatus"] = status
    campaign.commit("attempt_started", state, {"attemptId": attempt_id, "mode": mode})
    acceptance_by_id = {case["id"]: case for case in campaign.acceptance["cases"]}
    execution_by_id = {case["id"]: case for case in campaign.execution["cases"]}
    for ordinal, case_id in enumerate(case_ids, 1):
        result = execute_case(
            campaign,
            attempt_id,
            acceptance_by_id[case_id],
            execution_by_id[case_id],
            ordinal,
        )
        state = _copy_state(campaign.state)
        active = state["attempts"][-1]
        active["runs"].append(result)
        campaign.commit(
            "case_finished",
            state,
            {"attemptId": attempt_id, "caseId": case_id, "status": result["status"]},
        )
        if result["status"] in {"FAILED", "BLOCKED"} and not _case_waives_failure(
            acceptance_by_id[case_id]
        ):
            state = _copy_state(campaign.state)
            active = state["attempts"][-1]
            active["status"] = result["status"]
            state["lastFailure"] = result
            state["status"] = (
                "REPAIR_REQUIRED" if result["status"] == "FAILED" else "BLOCKED"
            )
            state["resumeStatus"] = status if result["status"] == "BLOCKED" else None
            campaign.commit(
                "attempt_finished",
                state,
                {"attemptId": attempt_id, "status": state["status"]},
            )
            return status_report(campaign), 1
    state = _copy_state(campaign.state)
    active = state["attempts"][-1]
    failed_ids = [run["caseId"] for run in active["runs"] if run["status"] == "FAILED"]
    waived = bool(failed_ids) and all(
        _case_waives_failure(acceptance_by_id[case_id]) for case_id in failed_ids
    )
    active["status"] = "WAIVED" if waived else "PASS"
    if waived:
        active["waivedCaseIds"] = failed_ids
    if mode == "retest":
        state["status"] = "REGRESSION_REQUIRED"
    else:
        state["status"] = "AUDIT_REQUIRED"
        state["finalRegressionAttemptId"] = attempt_id
    state["resumeStatus"] = None
    campaign.commit(
        "attempt_finished", state, {"attemptId": attempt_id, "status": state["status"]}
    )
    return status_report(campaign), 0


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
    state["sourceBaseline"] = persist_source_snapshot(
        campaign.campaign_root, after, len(state["repairs"]) + 2
    )
    state["status"] = "RETEST_REQUIRED"
    state["resumeStatus"] = None
    campaign.commit(
        "repair_recorded",
        state,
        {
            "failedCaseId": failure["caseId"],
            "acceptedSourceFingerprint": after["fingerprint"],
        },
    )
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


def audit(campaign: Campaign) -> tuple[dict[str, Any], int]:
    if campaign.state["status"] != "AUDIT_REQUIRED":
        raise VerificationError(
            "INVALID_STATE", "audit is not available in the current state"
        )
    first = observe_source(campaign.root, campaign.acceptance["sourcePolicy"])
    second = observe_source(campaign.root, campaign.acceptance["sourcePolicy"])
    errors: list[str] = []
    baseline = campaign.state["sourceBaseline"]["fingerprint"]
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
            errors.append("GOAL or execution authority changed during audit")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"cannot revalidate GOAL authority: {exc}")
    if first["fingerprint"] != baseline or second["fingerprint"] != baseline:
        errors.append("current source differs from the accepted final baseline")
    attempt = next(
        (
            item
            for item in campaign.state["attempts"]
            if item["id"] == campaign.state["finalRegressionAttemptId"]
        ),
        None,
    )
    expected_ids = [case["id"] for case in campaign.acceptance["cases"]]
    if (
        attempt is None
        or attempt["mode"] not in {"initial", "regression"}
        or attempt["caseIds"] != expected_ids
        or attempt["status"] not in {"PASS", "WAIVED"}
    ):
        errors.append("final regression attempt is incomplete")
        runs: list[dict[str, Any]] = []
    else:
        runs = attempt["runs"]
    by_id = {run["caseId"]: run for run in runs}
    waived_case_ids = (
        set(attempt.get("waivedCaseIds", [])) if attempt is not None else set()
    )
    for intended in campaign.acceptance["cases"]:
        run = by_id.get(intended["id"])
        expected_status = (
            "PASS"
            if platform_available(
                intended["platform"], campaign.state["runtimePlatform"]
            )
            else ("BLOCKED" if intended["required"] else "NOT_RUN")
        )
        if intended["id"] in waived_case_ids:
            expected_status = "FAILED"
        if (
            run is None
            or run["status"] != expected_status
            or run["sourceBeforeFingerprint"] != baseline
            or run["sourceAfterFingerprint"] != baseline
        ):
            errors.append(f"case {intended['id']} lacks final same-source evidence")
        elif run["status"] in {"PASS", "NOT_RUN"} or (
            run["status"] == "FAILED" and intended["id"] in waived_case_ids
        ):
            errors.extend(_verify_artifact(campaign, run))
        if (
            run is not None
            and run["status"] == "FAILED"
            and intended["id"] not in waived_case_ids
        ):
            errors.append(
                f"case {intended['id']} failed in the final regression without a declared waiver"
            )
    for criterion in campaign.view["goalContract"]["criteriaIds"]:
        if not any(
            case["required"]
            and criterion in case["coversCriteria"]
            and by_id.get(case["id"], {}).get("status") == "PASS"
            for case in campaign.acceptance["cases"]
        ):
            errors.append(f"criterion {criterion} lacks required final-PASS evidence")
    if errors:
        state = _copy_state(campaign.state)
        state["status"] = "BLOCKED"
        state["resumeStatus"] = "AUDIT_REQUIRED"
        campaign.commit("audit_rejected", state, {"errors": errors})
        return status_report(campaign, audit_errors=errors), 1
    final_source = observe_source(campaign.root, campaign.acceptance["sourcePolicy"])
    _, final_view, _ = load_bundle(campaign.alias)
    if final_source["fingerprint"] != baseline or final_view != campaign.view:
        errors = ["final audit authority changed before completion binding"]
        state = _copy_state(campaign.state)
        state["status"] = "BLOCKED"
        state["resumeStatus"] = "AUDIT_REQUIRED"
        campaign.commit("audit_rejected", state, {"errors": errors})
        return status_report(campaign, audit_errors=errors), 1
    binding = {
        "finalRegressionAttemptId": campaign.state["finalRegressionAttemptId"],
        "sourceFingerprint": baseline,
        "bundleManifestSha256": campaign.view["manifestSha256"],
        "executionPlanSha256": campaign.state["authority"]["executionPlanSha256"],
    }
    state = _copy_state(campaign.state)
    state["status"] = "COMPLETE"
    state["successfulAudit"] = binding
    state["resumeStatus"] = None
    campaign.commit("audit_succeeded", state, binding)
    return status_report(campaign), 0


def completion_status(campaign: Campaign) -> tuple[str, list[str]]:
    if (
        campaign.state["status"] != "COMPLETE"
        or campaign.state.get("successfulAudit") is None
    ):
        return "INCOMPLETE", []
    errors: list[str] = []
    try:
        source = observe_source(campaign.root, campaign.acceptance["sourcePolicy"])
        if (
            source["fingerprint"]
            != campaign.state["successfulAudit"]["sourceFingerprint"]
        ):
            errors.append("current source differs from the successful audit")
        attempt = next(
            item
            for item in campaign.state["attempts"]
            if item["id"]
            == campaign.state["successfulAudit"]["finalRegressionAttemptId"]
        )
        waived_case_ids = (
            set(attempt.get("waivedCaseIds", []))
            if attempt.get("status") == "WAIVED"
            else set()
        )
        for run in attempt["runs"]:
            if run["status"] in {"PASS", "NOT_RUN"} or (
                run["status"] == "FAILED" and run["caseId"] in waived_case_ids
            ):
                errors.extend(_verify_artifact(campaign, run))
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    return ("COMPLETE" if not errors else "INCOMPLETE"), errors


def status_report(
    campaign: Campaign, audit_errors: list[str] | None = None
) -> dict[str, Any]:
    status = campaign.state["status"]
    displayed = "INTERRUPTED" if status == "RUNNING" else status
    completion, current_errors = completion_status(campaign)
    return {
        "schemaId": "steward.verification-status",
        "schemaVersion": 1,
        "goal": campaign.alias,
        "goalPath": campaign.view["path"],
        "executionStatus": displayed,
        "resumeStatus": campaign.state.get("resumeStatus"),
        "completionStatus": completion,
        "sourceFingerprint": campaign.state["sourceBaseline"]["fingerprint"],
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
        "successfulAudit": campaign.state.get("successfulAudit"),
        "errors": list(audit_errors or []) + current_errors,
    }


def advance(campaign: Campaign) -> tuple[dict[str, Any], int]:
    """Run the campaign until it needs a human decision or reaches completion.

    Journal and state transitions are unchanged: each phase still commits its
    own event. Chaining only removes the per-phase re-invocation between
    mechanical steps (retest -> regression -> audit -> completion). advance
    stops before the states where the verifier must act or decide:
    REPAIR_REQUIRED, BLOCKED, or a rejected audit.
    """
    while True:
        status = campaign.state["status"]
        if status == "COMPLETE":
            report = status_report(campaign)
            return report, 0 if report["completionStatus"] == "COMPLETE" else 1
        if status == "REPAIR_REQUIRED":
            return status_report(campaign), 1
        if status == "BLOCKED":
            current = observe_source(campaign.root, campaign.acceptance["sourcePolicy"])
            if (
                current["fingerprint"]
                != campaign.state["sourceBaseline"]["fingerprint"]
            ):
                return status_report(campaign), 1
            resume = campaign.state.get("resumeStatus")
            state = _copy_state(campaign.state)
            state["status"] = resume or "PENDING"
            state["resumeStatus"] = None
            campaign.commit("blocker_cleared", state, {"resumeStatus": resume})
            continue
        if status == "AUDIT_REQUIRED":
            report, code = audit(campaign)
            if code != 0:
                return report, code
            continue
        if status in {"PENDING", "RETEST_REQUIRED", "REGRESSION_REQUIRED", "RUNNING"}:
            current = observe_source(campaign.root, campaign.acceptance["sourcePolicy"])
            if (
                current["fingerprint"]
                != campaign.state["sourceBaseline"]["fingerprint"]
            ):
                state = _copy_state(campaign.state)
                state["status"] = "BLOCKED"
                state["resumeStatus"] = status
                campaign.commit(
                    "source_drift_blocked",
                    state,
                    {"observedSourceFingerprint": current["fingerprint"]},
                )
                return status_report(campaign), 1
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
