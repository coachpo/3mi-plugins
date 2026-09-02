"""Append-only schema-6 campaign journal and derived in-memory state."""

from __future__ import annotations

import copy
import os
import stat
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any

from adapter_paths import (
    Adapter,
    current_platform,
    observe_source,
    path_has_symlink_component,
    path_uses_symlink,
)
from model import (
    JOURNAL_SCHEMA_VERSION,
    SCRIPT_VERSION,
    CampaignError,
    assert_persistable,
    canonical_bytes,
    parse_json_text,
    read_regular_bytes,
    sha256_bytes,
    slug,
    utc_now,
)

MAX_JOURNAL_BYTES = 256 * 1024 * 1024
MAX_STATE_BYTES = 512 * 1024 * 1024
EVENT_FIELDS = {
    "schemaVersion",
    "kernelVersion",
    "sequence",
    "timestamp",
    "type",
    "payload",
    "previousHash",
    "eventHash",
}
EVENT_PAYLOAD_FIELDS = {
    "initialized": {
        "adapterFingerprint",
        "goalSnapshot",
        "sourceSnapshot",
        "cases",
        "runtimePlatform",
        "worktreeBinding",
    },
    "attempt_started": {"attemptId", "mode", "sourceFingerprint", "caseIds"},
    "case_started": {
        "attemptId",
        "runId",
        "caseId",
        "ordinal",
        "artifactDir",
        "sourceFingerprint",
    },
    "case_finished": {
        "attemptId",
        "runId",
        "caseId",
        "ordinal",
        "artifactDir",
        "status",
        "reason",
        "exitCode",
        "timedOut",
        "evidence",
        "stdoutSha256",
        "stderrSha256",
        "sourceFingerprint",
        "sourceAfterFingerprint",
        "artifactManifest",
    },
    "attempt_finished": {"attemptId", "status", "resumeMode"},
    "attempt_interrupted": {"attemptId", "reason", "resumeMode"},
    "fix_recorded": {"fix"},
    "source_invalidated": {"attemptId", "reason", "observedSourceFingerprint"},
    "audit_succeeded": {
        "finalRegressionAttemptId",
        "currentSourceFingerprint",
        "catalogFingerprint",
    },
}
OWNED_FILES = {"events.jsonl", "campaign.lock"}


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def require_safe_campaign_root(root: Path, *, must_exist: bool = True) -> None:
    if path_has_symlink_component(root):
        raise CampaignError("campaignRoot uses a symlink/reparse path")
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        if must_exist:
            raise CampaignError("campaignRoot does not exist")
        return
    except OSError as exc:
        raise CampaignError("cannot inspect campaignRoot") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise CampaignError("campaignRoot must be a regular directory")


def _event_hash(value: dict[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("eventHash", None)
    return sha256_bytes(canonical_bytes(unsigned))


def _validate_hash(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
    ):
        raise CampaignError(label + " is not a SHA-256 digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise CampaignError(label + " is not a SHA-256 digest") from exc


def _validate_event(
    event: Any, expected_sequence: int, previous_hash: str | None
) -> None:
    if not isinstance(event, dict) or set(event) != EVENT_FIELDS:
        raise CampaignError("journal event has invalid fields")
    if (
        type(event["schemaVersion"]) is not int
        or event["schemaVersion"] != JOURNAL_SCHEMA_VERSION
    ):
        raise CampaignError(f"journal schemaVersion must be {JOURNAL_SCHEMA_VERSION}")
    if event["kernelVersion"] != SCRIPT_VERSION:
        raise CampaignError(f"journal kernelVersion must be {SCRIPT_VERSION}")
    if type(event["sequence"]) is not int or event["sequence"] != expected_sequence:
        raise CampaignError("journal sequence is not contiguous")
    if not isinstance(event["timestamp"], str) or not event["timestamp"]:
        raise CampaignError("journal event timestamp is invalid")
    event_type = event["type"]
    if event_type not in EVENT_PAYLOAD_FIELDS:
        raise CampaignError("journal event type is unsupported")
    payload = event["payload"]
    if (
        not isinstance(payload, dict)
        or set(payload) != EVENT_PAYLOAD_FIELDS[event_type]
    ):
        raise CampaignError("journal event payload has invalid fields")
    if event["previousHash"] != previous_hash:
        raise CampaignError("journal hash chain is broken")
    _validate_hash(event["eventHash"], "eventHash")
    if event["eventHash"] != _event_hash(event):
        raise CampaignError("journal event hash does not match its contents")
    assert_persistable(event)


def read_events(path: Path) -> list[dict[str, Any]]:
    content = read_regular_bytes(
        path, label="campaign journal", max_bytes=MAX_JOURNAL_BYTES
    )
    if not content or not content.endswith(b"\n"):
        raise CampaignError("campaign journal must be a non-empty LF-terminated stream")
    events: list[dict[str, Any]] = []
    previous_hash: str | None = None
    for sequence, raw in enumerate(content.splitlines(), start=1):
        try:
            event = parse_json_text(raw.decode("utf-8"), "campaign journal event")
        except UnicodeError as exc:
            raise CampaignError("campaign journal is not valid UTF-8") from exc
        _validate_event(event, sequence, previous_hash)
        events.append(event)
        previous_hash = event["eventHash"]
    if events[0]["type"] != "initialized":
        raise CampaignError("campaign journal must begin with initialized")
    if any(event["type"] == "initialized" for event in events[1:]):
        raise CampaignError("campaign journal contains multiple initialized events")
    return events


def _new_event(
    sequence: int, previous_hash: str | None, event_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if (
        event_type not in EVENT_PAYLOAD_FIELDS
        or set(payload) != EVENT_PAYLOAD_FIELDS[event_type]
    ):
        raise CampaignError("invalid event payload")
    event = {
        "schemaVersion": JOURNAL_SCHEMA_VERSION,
        "kernelVersion": SCRIPT_VERSION,
        "sequence": sequence,
        "timestamp": utc_now(),
        "type": event_type,
        "payload": payload,
        "previousHash": previous_hash,
    }
    assert_persistable(event)
    event["eventHash"] = _event_hash(event)
    return event


def _append_event(path: Path, event: dict[str, Any]) -> None:
    data = canonical_bytes(event) + b"\n"
    flags = os.O_WRONLY | os.O_APPEND
    for flag in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW"):
        flags |= getattr(os, flag, 0)
    try:
        descriptor = os.open(str(path), flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise CampaignError("campaign journal is not a regular file")
            if before.st_size + len(data) > MAX_JOURNAL_BYTES:
                raise CampaignError("campaign journal exceeds the safe size limit")
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise CampaignError("cannot append campaign journal")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except CampaignError:
        raise
    except OSError as exc:
        raise CampaignError("cannot append campaign journal") from exc


def _case_state_map(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        case["id"]: {
            "status": "PENDING",
            "lastRunId": None,
            "lastAttemptId": None,
            "lastRound": None,
            "reason": None,
        }
        for case in cases
    }


def _validate_worktree_binding(value: Any) -> None:
    expected = {
        "schemaId",
        "schemaVersion",
        "targetWorktreeRoot",
        "gitDir",
        "gitCommonDir",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schemaId") != "steward.target-worktree-binding"
        or type(value.get("schemaVersion")) is not int
        or value.get("schemaVersion") != 1
        or any(
            not isinstance(value.get(key), str) or not value[key]
            for key in ("targetWorktreeRoot", "gitDir", "gitCommonDir")
        )
    ):
        raise CampaignError("initialized worktreeBinding is invalid")


def _initial_state(payload: dict[str, Any]) -> dict[str, Any]:
    _validate_worktree_binding(payload["worktreeBinding"])
    if (
        not isinstance(payload["runtimePlatform"], str)
        or not payload["runtimePlatform"]
    ):
        raise CampaignError("initialized runtimePlatform is invalid")
    return {
        "schemaVersion": JOURNAL_SCHEMA_VERSION,
        "kernelVersion": SCRIPT_VERSION,
        "adapterFingerprint": payload["adapterFingerprint"],
        "goalSnapshot": copy.deepcopy(payload["goalSnapshot"]),
        "sourceBaseline": copy.deepcopy(payload["sourceSnapshot"]),
        "cases": copy.deepcopy(payload["cases"]),
        "runtimePlatform": payload["runtimePlatform"],
        "worktreeBinding": copy.deepcopy(payload["worktreeBinding"]),
        "repairCount": 0,
        "status": "PENDING",
        "resumeMode": "initial",
        "caseStates": _case_state_map(payload["cases"]),
        "attempts": [],
        "fixes": [],
        "pendingFixId": None,
        "finalRegressionAttemptId": None,
        "successfulAudit": None,
        "invalidation": None,
        "lastSequence": 0,
        "lastEventHash": None,
    }


def _find_attempt(state: dict[str, Any], attempt_id: str) -> dict[str, Any]:
    for attempt in state["attempts"]:
        if attempt["id"] == attempt_id:
            return attempt
    raise CampaignError("journal references an unknown attempt")


def apply_event(state: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    event_type = event["type"]
    payload = event["payload"]
    if event_type == "initialized":
        if state is not None:
            raise CampaignError("campaign has multiple initialization events")
        state = _initial_state(payload)
    elif state is None:
        raise CampaignError("campaign event precedes initialization")
    elif event_type == "attempt_started":
        if state["status"] == "RUNNING":
            raise CampaignError("campaign has overlapping attempts")
        if payload["mode"] not in {"initial", "retest", "regression"}:
            raise CampaignError("attempt mode is invalid")
        if any(item["id"] == payload["attemptId"] for item in state["attempts"]):
            raise CampaignError("attempt ID is duplicated")
        state["attempts"].append(
            {
                "id": payload["attemptId"],
                "mode": payload["mode"],
                "sourceFingerprint": payload["sourceFingerprint"],
                "caseIds": list(payload["caseIds"]),
                "runs": [],
                "status": "RUNNING",
            }
        )
        state["status"] = "RUNNING"
        state["resumeMode"] = payload["mode"]
    elif event_type == "case_started":
        attempt = _find_attempt(state, payload["attemptId"])
        if (
            attempt["status"] != "RUNNING"
            or payload["caseId"] not in attempt["caseIds"]
        ):
            raise CampaignError("case start does not belong to the active attempt")
        if any(run["runId"] == payload["runId"] for run in attempt["runs"]):
            raise CampaignError("run ID is duplicated")
        attempt["runs"].append(
            {
                "runId": payload["runId"],
                "caseId": payload["caseId"],
                "ordinal": payload["ordinal"],
                "artifactDir": payload["artifactDir"],
                "sourceFingerprint": payload["sourceFingerprint"],
                "status": "RUNNING",
            }
        )
        case_state = state["caseStates"][payload["caseId"]]
        case_state.update(
            {
                "status": "RUNNING",
                "lastRunId": payload["runId"],
                "lastAttemptId": payload["attemptId"],
                "lastRound": attempt["mode"],
                "reason": None,
            }
        )
    elif event_type == "case_finished":
        attempt = _find_attempt(state, payload["attemptId"])
        matches = [run for run in attempt["runs"] if run["runId"] == payload["runId"]]
        if len(matches) != 1 or matches[0]["status"] != "RUNNING":
            raise CampaignError("case finish does not match one running case")
        matches[0].update(copy.deepcopy(payload))
        case_state = state["caseStates"][payload["caseId"]]
        case_state.update(
            {
                "status": payload["status"],
                "lastRunId": payload["runId"],
                "lastAttemptId": payload["attemptId"],
                "lastRound": attempt["mode"],
                "reason": payload["reason"],
            }
        )
    elif event_type == "attempt_finished":
        attempt = _find_attempt(state, payload["attemptId"])
        if attempt["status"] != "RUNNING" or any(
            run["status"] == "RUNNING" for run in attempt["runs"]
        ):
            raise CampaignError("attempt cannot finish while a case is running")
        attempt["status"] = payload["status"]
        state["status"] = payload["status"]
        state["resumeMode"] = payload["resumeMode"]
        if attempt["mode"] == "retest":
            state["pendingFixId"] = None
        if payload["status"] == "AUDIT_REQUIRED":
            state["finalRegressionAttemptId"] = attempt["id"]
    elif event_type == "attempt_interrupted":
        attempt = _find_attempt(state, payload["attemptId"])
        if attempt["status"] != "RUNNING":
            raise CampaignError("only a running attempt can be interrupted")
        for run in attempt["runs"]:
            if run["status"] == "RUNNING":
                run["status"] = "INTERRUPTED"
                state["caseStates"][run["caseId"]].update(
                    {
                        "status": "INTERRUPTED",
                        "reason": payload["reason"],
                    }
                )
        attempt["status"] = "INTERRUPTED"
        state["status"] = "INTERRUPTED"
        state["resumeMode"] = payload["resumeMode"]
    elif event_type == "fix_recorded":
        fix = copy.deepcopy(payload["fix"])
        if any(item["fixId"] == fix["fixId"] for item in state["fixes"]):
            raise CampaignError("fix ID is duplicated")
        state["fixes"].append(fix)
        state["pendingFixId"] = fix["fixId"]
        state["repairCount"] += 1
        state["sourceBaseline"] = copy.deepcopy(fix["fixedSourceSnapshot"])
        state["status"] = "FIX_RECORDED"
        state["resumeMode"] = "retest"
    elif event_type == "source_invalidated":
        if payload["attemptId"]:
            attempt = _find_attempt(state, payload["attemptId"])
            attempt["status"] = "INVALIDATED"
        state["invalidation"] = copy.deepcopy(payload)
        state["status"] = "READY_FOR_REGRESSION"
        state["resumeMode"] = "regression"
    elif event_type == "audit_succeeded":
        if state["status"] != "AUDIT_REQUIRED":
            raise CampaignError("audit success requires AUDIT_REQUIRED state")
        if payload["finalRegressionAttemptId"] != state["finalRegressionAttemptId"]:
            raise CampaignError("audit success is bound to the wrong final regression")
        attempt = _find_attempt(state, payload["finalRegressionAttemptId"])
        if (
            attempt["mode"] not in {"initial", "regression"}
            or attempt["status"] != "AUDIT_REQUIRED"
        ):
            raise CampaignError("audit success is not bound to a successful regression")
        if (
            payload["currentSourceFingerprint"]
            != state["sourceBaseline"]["fingerprint"]
        ):
            raise CampaignError("audit success is bound to the wrong source")
        if payload["catalogFingerprint"] != state["adapterFingerprint"]:
            raise CampaignError("audit success is bound to the wrong catalog")
        state["successfulAudit"] = {
            **copy.deepcopy(payload),
            "eventSequence": event["sequence"],
            "eventHash": event["eventHash"],
        }
        state["status"] = "COMPLETE"
        state["resumeMode"] = None
    else:  # pragma: no cover - guarded by event validation
        raise CampaignError("unsupported event type")
    state["lastSequence"] = event["sequence"]
    state["lastEventHash"] = event["eventHash"]
    return state


def replay_state(events: list[dict[str, Any]]) -> dict[str, Any]:
    state: dict[str, Any] | None = None
    for event in events:
        state = apply_event(state, event)
    if state is None:
        raise CampaignError("campaign journal is empty")
    return state


def make_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": state["schemaVersion"],
        "kernelVersion": state["kernelVersion"],
        "status": state["status"],
        "resumeMode": state["resumeMode"],
        "repairCount": state["repairCount"],
        "goalSha256": state["goalSnapshot"]["sha256"],
        "worktreeBinding": copy.deepcopy(state["worktreeBinding"]),
        "sourceFingerprint": state["sourceBaseline"]["fingerprint"],
        "finalRegressionAttemptId": state["finalRegressionAttemptId"],
        "successfulAudit": copy.deepcopy(state["successfulAudit"]),
        "caseStatuses": {
            case_id: value["status"]
            for case_id, value in sorted(state["caseStates"].items())
        },
        "lastSequence": state["lastSequence"],
        "lastEventHash": state["lastEventHash"],
    }


class CampaignLock:
    def __init__(self, campaign_root: Path) -> None:
        self.root = campaign_root
        self.path = campaign_root / "campaign.lock"
        self.descriptor: int | None = None
        self.identity: tuple[int, int] | None = None

    def __enter__(self) -> CampaignLock:  # noqa: PYI034
        require_safe_campaign_root(self.root)
        if path_uses_symlink(self.path, self.root):
            raise CampaignError("campaign lock path is unsafe")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        for flag in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW"):
            flags |= getattr(os, flag, 0)
        for attempt in range(2):
            try:
                self.descriptor = os.open(str(self.path), flags, 0o600)
                payload = canonical_bytes({"pid": os.getpid()}) + b"\n"
                os.write(self.descriptor, payload)
                os.fsync(self.descriptor)
                metadata = os.fstat(self.descriptor)
                self.identity = (metadata.st_dev, metadata.st_ino)
                return self
            except FileExistsError as exc:
                if attempt or not self._remove_stale_lock():
                    raise CampaignError(
                        "campaign is locked by another operation"
                    ) from exc
            except OSError as exc:
                raise CampaignError("cannot create campaign lock") from exc
        raise CampaignError("cannot create campaign lock")

    def _remove_stale_lock(self) -> bool:
        try:
            metadata = self.path.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or _is_reparse(metadata)
                or not stat.S_ISREG(metadata.st_mode)
            ):
                return False
            value = parse_json_text(
                read_regular_bytes(
                    self.path, label="campaign lock", max_bytes=4096
                ).decode("utf-8"),
                "campaign lock",
            )
            if (
                not isinstance(value, dict)
                or set(value) != {"pid"}
                or type(value["pid"]) is not int
                or value["pid"] <= 0
            ):
                return False
            try:
                os.kill(value["pid"], 0)
                return False
            except ProcessLookupError:
                pass
            except (PermissionError, OSError):
                return False
            current = self.path.lstat()
            if not os.path.samestat(metadata, current):
                return False
            self.path.unlink()
            return True
        except (CampaignError, OSError, UnicodeError):
            return False

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None
        try:
            metadata = self.path.lstat()
            if self.identity == (metadata.st_dev, metadata.st_ino) and stat.S_ISREG(
                metadata.st_mode
            ):
                self.path.unlink()
        except OSError:
            pass


class Campaign:
    def __init__(
        self,
        adapter: Adapter,
        events: list[dict[str, Any]],
        state: dict[str, Any],
        *,
        worktree_binding_consistent: bool,
        runtime_platform_consistent: bool,
    ) -> None:
        self.adapter = adapter
        self.events = events
        self.state = state
        self.worktree_binding_consistent = worktree_binding_consistent
        self.runtime_platform_consistent = runtime_platform_consistent

    @property
    def events_path(self) -> Path:
        return self.adapter.campaign_root / "events.jsonl"

    @classmethod
    def initialize(
        cls, adapter: Adapter, *, observation: dict[str, Any] | None = None
    ) -> Campaign:
        if adapter.goal_errors:
            raise CampaignError(adapter.goal_errors[0])
        root = adapter.campaign_root
        require_safe_campaign_root(root, must_exist=False)
        if root.exists() or root.is_symlink():
            raise CampaignError("campaignRoot already exists")
        parent = root.parent
        if path_has_symlink_component(parent):
            raise CampaignError("campaignRoot parent uses a symlink/reparse path")
        parent.mkdir(parents=True, exist_ok=True)
        temp: Path | None = Path(
            tempfile.mkdtemp(prefix="campaign.create-", dir=str(parent))
        )
        try:
            observation = observation or observe_source(adapter)
            payload = {
                "adapterFingerprint": adapter.catalog_fingerprint,
                "goalSnapshot": copy.deepcopy(adapter.goal_snapshot),
                "sourceSnapshot": observation,
                "cases": adapter.case_metadata(),
                "runtimePlatform": current_platform(),
                "worktreeBinding": copy.deepcopy(adapter.worktree_binding),
            }
            event = _new_event(1, None, "initialized", payload)
            (temp / "events.jsonl").write_bytes(canonical_bytes(event) + b"\n")
            with (temp / "events.jsonl").open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp, root)
            temp = None
        finally:
            if temp is not None and temp.exists():
                for child in temp.iterdir():
                    child.unlink()
                temp.rmdir()
        return cls.load(adapter)

    @classmethod
    def load(cls, adapter: Adapter) -> Campaign:
        root = adapter.campaign_root
        require_safe_campaign_root(root)
        required = {"events.jsonl"}
        try:
            names = {entry.name for entry in root.iterdir()}
        except OSError as exc:
            raise CampaignError("cannot inspect campaignRoot") from exc
        missing = sorted(required - names)
        if missing:
            raise CampaignError(
                "campaignRoot is incomplete: missing " + ", ".join(missing)
            )
        unexpected = sorted(names - (required | {"attempts", "campaign.lock"}))
        if unexpected:
            raise CampaignError(
                "campaignRoot contains unexpected entries: " + ", ".join(unexpected)
            )
        for name in required:
            if path_uses_symlink(root / name, root):
                raise CampaignError("campaign-owned file uses a symlink/reparse path")
        if "attempts" in names:
            attempts_path = root / "attempts"
            try:
                metadata = attempts_path.lstat()
            except OSError as exc:
                raise CampaignError("cannot inspect campaign attempts") from exc
            if (
                stat.S_ISLNK(metadata.st_mode)
                or _is_reparse(metadata)
                or not stat.S_ISDIR(metadata.st_mode)
            ):
                raise CampaignError("campaign attempts must be a regular directory")
        if "campaign.lock" in names:
            lock_path = root / "campaign.lock"
            try:
                lock_metadata = lock_path.lstat()
            except OSError as exc:
                raise CampaignError("cannot inspect campaign lock") from exc
            if (
                stat.S_ISLNK(lock_metadata.st_mode)
                or _is_reparse(lock_metadata)
                or not stat.S_ISREG(lock_metadata.st_mode)
                or lock_metadata.st_size > 4096
            ):
                raise CampaignError("campaign lock is not a safe regular file")
        events = read_events(root / "events.jsonl")
        state = replay_state(events)
        return cls(
            adapter,
            events,
            state,
            worktree_binding_consistent=(
                adapter.worktree_binding == state["worktreeBinding"]
            ),
            runtime_platform_consistent=(
                current_platform() == state["runtimePlatform"]
            ),
        )

    def summary(self) -> dict[str, Any]:
        return make_summary(self.state)

    def current_source(self) -> str:
        return observe_source(self.adapter)["fingerprint"]

    def current_source_snapshot(self) -> dict[str, Any]:
        return observe_source(self.adapter)

    def catalog_drift_reason(self) -> str | None:
        if self.adapter.catalog_fingerprint != self.state["adapterFingerprint"]:
            return "adapter catalog changed after campaign initialization"
        if self.adapter.goal_errors:
            return self.adapter.goal_errors[0]
        if self.adapter.goal_workspace_errors:
            return self.adapter.goal_workspace_errors[0]
        if not self.worktree_binding_consistent:
            return "WORKTREE_BINDING_DRIFT: target worktree identity changed"
        if not self.runtime_platform_consistent:
            return (
                "RUNTIME_PLATFORM_DRIFT: runtime platform differs from initialization"
            )
        return None

    def ensure_mutable(self) -> None:
        if self.catalog_drift_reason():
            raise CampaignError(self.catalog_drift_reason() or "campaign drift")

    def commit(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = _new_event(
            self.state["lastSequence"] + 1,
            self.state["lastEventHash"],
            event_type,
            payload,
        )
        prospective = apply_event(copy.deepcopy(self.state), event)
        if len(canonical_bytes(prospective)) > MAX_STATE_BYTES:
            raise CampaignError("campaign derived state exceeds the safe size limit")
        _append_event(self.events_path, event)
        self.events.append(event)
        self.state = prospective
        return event

    def allocate_case_artifact(
        self, attempt_id: str, case_id: str, ordinal: int
    ) -> tuple[str, Path]:
        run_id = f"run-{ordinal:04d}-{slug(case_id)}"
        attempt_dir = self.adapter.campaign_root / "attempts" / attempt_id
        artifact_dir = attempt_dir / run_id
        if path_uses_symlink(attempt_dir, self.adapter.campaign_root):
            raise CampaignError("attempt artifact path uses a symlink/reparse point")
        attempt_dir.mkdir(parents=True, exist_ok=True)
        try:
            artifact_dir.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise CampaignError("case artifact directory already exists") from exc
        return run_id, artifact_dir


__all__ = [
    "Campaign",
    "CampaignLock",
    "apply_event",
    "make_summary",
    "read_events",
    "replay_state",
    "require_safe_campaign_root",
]
