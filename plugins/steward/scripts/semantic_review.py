#!/usr/bin/env python3
"""Validate and expose canonical read-only semantic-risk review manifests."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

SCHEMA_ID = "steward.semantic-review"
SCHEMA_VERSION = 1
RESOLUTION_STATES = {"open", "resolved", "invalidated"}
SUPPORT_LEVELS = {"code-supported", "observed"}
CASE_CATEGORIES = {"smoke", "functional", "integration", "workflow", "role-play"}
CASE_PLATFORMS = {"any", "darwin", "linux", "windows", "posix"}
SCENARIO_TAGS = {"failure", "compatibility", "platform"}
REVIEW_OUTCOMES = {"findings", "no-findings", "incomplete"}
REVIEW_TARGET_KINDS = {"source", "diff"}
REVIEW_GAP_KINDS = {
    "insufficient-evidence",
    "unreviewed-scope",
    "unavailable-context",
}
MAX_TIMEOUT_SECONDS = 7 * 24 * 60 * 60
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_SOURCE_BYTES = 16 * 1024 * 1024
FORBIDDEN_SINGLE_LINE_CHARACTERS = {
    "\x00",
    "\n",
    "\v",
    "\f",
    "\r",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
}

RF_ID_RE = re.compile(r"^RF-[A-Z0-9][A-Z0-9-]*$")
RG_ID_RE = re.compile(r"^RG-[A-Z0-9][A-Z0-9-]*$")
CRITERION_ID_RE = re.compile(r"^C[1-9][0-9]*$")
INVARIANT_ID_RE = re.compile(r"^INV-[A-Z][A-Z0-9]*-[0-9A-F]{12}$")
CASE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
CAPABILITY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]*$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SOURCE_TEST_SUFFIXES = {
    ".c",
    ".cc",
    ".clj",
    ".cljs",
    ".cpp",
    ".cs",
    ".cxx",
    ".ex",
    ".exs",
    ".go",
    ".h",
    ".hh",
    ".hpp",
    ".hs",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".lua",
    ".mjs",
    ".php",
    ".pl",
    ".py",
    ".r",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".swift",
    ".test",
    ".ts",
    ".tsx",
    ".vue",
}
SECRET_VALUE_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret|credential)\s*[:=]\s*\S+"
)
SECRET_OPTION_RE = re.compile(
    r"^--?(?:api[-_]?key|access[-_]?token|auth[-_]?token|token|password|passwd|secret|credential|private[-_]?key)$",
    re.IGNORECASE,
)
PYTHON_INTERPRETER_RE = re.compile(
    r"^(?:py|python(?:[0-9]+(?:\.[0-9]+)*)?|pypy(?:[0-9]+(?:\.[0-9]+)*)?)$",
    re.IGNORECASE,
)
NODE_INTERPRETER_RE = re.compile(r"^(?:node|nodejs)$", re.IGNORECASE)
RUBY_INTERPRETER_RE = re.compile(
    r"^(?:ruby(?:[0-9]+(?:\.[0-9]+)*)?|jruby|truffleruby)$",
    re.IGNORECASE,
)
SHELL_INTERPRETER_RE = re.compile(
    r"^(?:sh|bash|dash|zsh|ksh(?:93)?|fish)$",
    re.IGNORECASE,
)
PERL_INTERPRETER_RE = re.compile(
    r"^perl(?:[0-9]+(?:\.[0-9]+)*)?$",
    re.IGNORECASE,
)
BUN_INTERPRETER_RE = re.compile(r"^bun$", re.IGNORECASE)


class SemanticReviewError(ValueError):
    """A stable, user-actionable semantic-review validation error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.code + ": " + self.message


@dataclass(frozen=True)
class ReviewFinding:
    id: str
    required: bool
    resolution_state: str
    criteria_ids: tuple[str, ...]
    invariant_ids: tuple[str, ...]
    case_candidate: dict[str, Any]
    view: dict[str, Any]


@dataclass(frozen=True)
class ReviewScopeFile:
    path: str
    sha256: str


@dataclass(frozen=True)
class ReviewGap:
    id: str
    kind: str
    detail: str
    needed_evidence: tuple[str, ...]
    paths: tuple[str, ...]


@dataclass(frozen=True)
class ReviewRequest:
    target_kind: str
    source_fingerprint: str
    requested_paths: tuple[str, ...]
    request_sha256: str
    _canonical_bytes: bytes

    @property
    def view(self) -> dict[str, Any]:
        """Return a fresh canonical request-binding view."""

        value = json.loads(self._canonical_bytes)
        if not isinstance(value, dict):  # pragma: no cover - construction invariant
            raise TypeError("canonical review request must be an object")
        return value


@dataclass(frozen=True)
class _ExpectedReviewRequestSnapshot:
    request: ReviewRequest
    file_identity: tuple[int, int, int, int, int, int]


@dataclass(frozen=True)
class _AttestedLocationSnapshot:
    line_count: int
    utf8_valid: bool


@dataclass(frozen=True)
class ReviewAttestation:
    source_fingerprint: str
    goal_contract_sha256: str
    invariants_sha256: str
    outcome: str
    scope: tuple[ReviewScopeFile, ...]
    gaps: tuple[ReviewGap, ...]
    _canonical_bytes: bytes

    @property
    def view(self) -> dict[str, Any]:
        """Return a fresh view so callers cannot mutate validated state."""

        value = json.loads(self._canonical_bytes)
        if not isinstance(value, dict):  # pragma: no cover - construction invariant
            raise TypeError("canonical semantic-review attestation must be an object")
        return value

    @property
    def scope_paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.scope)


@dataclass(frozen=True)
class ReviewManifest:
    path: Path | None
    findings: tuple[ReviewFinding, ...]
    attestation: ReviewAttestation | None
    review_request: ReviewRequest | None
    scope_verified: bool
    bindings_verified: bool
    _canonical_bytes: bytes

    @property
    def view(self) -> dict[str, Any]:
        """Return a fresh view so callers cannot mutate validated state."""

        value = json.loads(self._canonical_bytes)
        if not isinstance(value, dict):  # pragma: no cover - construction invariant
            raise TypeError("canonical semantic-review view must be an object")
        return value

    @property
    def required_finding_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.findings if item.required)

    @property
    def is_attested(self) -> bool:
        return self.attestation is not None

    @property
    def source_fingerprint(self) -> str | None:
        if self.attestation is None:
            return None
        return self.attestation.source_fingerprint

    @property
    def scope_paths(self) -> tuple[str, ...]:
        if self.attestation is None:
            return ()
        return self.attestation.scope_paths

    @property
    def baseline_verified(self) -> bool:
        """Compatibility alias for the earlier attested-scope verification flag."""

        return self.scope_verified


def _error(code: str, message: str) -> SemanticReviewError:
    return SemanticReviewError(code, message)


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise _error("REVIEW_JSON", "manifest is not canonical JSON") from exc


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _error("REVIEW_JSON", "JSON object has a duplicate key: " + key)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise _error("REVIEW_JSON", "JSON contains a non-finite number: " + value)


def _parse_json_bytes(value: bytes) -> Any:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _error("REVIEW_ENCODING", "review manifest must be valid UTF-8") from exc
    if text.startswith("\ufeff"):
        raise _error("REVIEW_ENCODING", "review manifest must not contain a BOM")
    if "\x00" in text:
        raise _error("REVIEW_ENCODING", "review manifest must not contain NUL")
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except SemanticReviewError:
        raise
    except (json.JSONDecodeError, RecursionError, UnicodeError) as exc:
        raise _error("REVIEW_JSON", "review manifest is not valid JSON") from exc


def _read_bounded(
    handle: Any,
    *,
    limit: int = MAX_MANIFEST_BYTES,
    label: str = "review manifest",
) -> bytes:
    data = handle.read(limit + 1)
    if len(data) > limit:
        raise _error(
            "REVIEW_SIZE",
            label + " exceeds the " + str(limit) + " byte input limit",
        )
    return data


def _read_regular_file(
    path: Path,
    *,
    limit: int = MAX_MANIFEST_BYTES,
    label: str = "review manifest",
    expected_stat: os.stat_result | None = None,
) -> bytes:
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise _error("REVIEW_IO", "cannot read " + label + ": " + str(path)) from exc
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise _error("REVIEW_IO", label + " must be a regular non-symlink file")
    if expected_stat is not None and not os.path.samestat(expected_stat, path_stat):
        raise _error("REVIEW_IO", label + " changed after path validation")

    flags = os.O_RDONLY
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(str(path), flags)
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise _error("REVIEW_IO", label + " must be a regular file")
        if not os.path.samestat(path_stat, opened_stat) or (
            expected_stat is not None
            and not os.path.samestat(expected_stat, opened_stat)
        ):
            raise _error("REVIEW_IO", label + " changed while being opened")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            return _read_bounded(handle, limit=limit, label=label)
    except SemanticReviewError:
        raise
    except OSError as exc:
        raise _error("REVIEW_IO", "cannot read " + label + ": " + str(path)) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _object(
    value: Any,
    label: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _error("REVIEW_SCHEMA", label + " must be an object")
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise _error("REVIEW_SCHEMA", label + " is missing: " + ", ".join(missing))
    if unknown:
        raise _error(
            "REVIEW_SCHEMA", label + " has unknown fields: " + ", ".join(unknown)
        )
    return value


def _string(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character in value for character in FORBIDDEN_SINGLE_LINE_CHARACTERS)
    ):
        raise _error(
            "REVIEW_SCHEMA", label + " must be a non-empty single-line string without surrounding whitespace"
        )
    return value


def _sha256(value: Any, label: str) -> str:
    digest = _string(value, label)
    if SHA256_RE.fullmatch(digest) is None:
        raise _error(
            "REVIEW_SCHEMA",
            label + " must be a lowercase sha256:<64 hex> digest",
        )
    return digest


def _bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise _error("REVIEW_SCHEMA", label + " must be a boolean")
    return value


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise _error("REVIEW_SCHEMA", label + " must be a positive integer")
    return value


def _string_array(
    value: Any,
    label: str,
    *,
    pattern: re.Pattern[str] | None = None,
    values: set[str] | None = None,
    allow_empty: bool = True,
) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _error("REVIEW_SCHEMA", label + " must be a string array")
    if not allow_empty and not value:
        raise _error("REVIEW_SCHEMA", label + " must not be empty")
    normalized: list[str] = []
    for index, item in enumerate(value):
        item = _string(item, f"{label}[{index}]")
        if pattern is not None and pattern.fullmatch(item) is None:
            raise _error("REVIEW_SCHEMA", label + " contains an invalid value: " + item)
        if values is not None and item not in values:
            raise _error("REVIEW_SCHEMA", label + " contains an unsupported value: " + item)
        normalized.append(item)
    if len(set(normalized)) != len(normalized):
        raise _error("REVIEW_SCHEMA", label + " contains duplicate values")
    return sorted(normalized)


def _relative_path(value: Any, label: str, *, allow_dot: bool = False) -> str:
    text = _string(value, label)
    if "\\" in text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise _error("REVIEW_PATH", label + " must be a POSIX project-relative path")
    path = PurePosixPath(text)
    parts = path.parts
    if ".." in parts or any(part in {"", "."} for part in parts if text != "."):
        raise _error("REVIEW_PATH", label + " contains traversal or is not normalized")
    normalized = path.as_posix()
    if normalized == "." and not allow_dot:
        raise _error("REVIEW_PATH", label + " must name a project child")
    if normalized != text:
        raise _error("REVIEW_PATH", label + " is not normalized")
    return text


def _review_request_digest(core: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json_bytes(core)).hexdigest()


def _review_request(value: Any, label: str) -> ReviewRequest:
    item = _object(
        value,
        label,
        required={"target", "requestedPaths", "requestSha256"},
    )
    target_item = item["target"]
    if not isinstance(target_item, dict):
        raise _error("REVIEW_REQUEST", label + ".target must be an object")
    kind = _string(target_item.get("kind"), label + ".target.kind")
    if kind not in REVIEW_TARGET_KINDS:
        raise _error("REVIEW_REQUEST", label + ".target.kind is unsupported")
    if kind == "source":
        target = _object(
            target_item,
            label + ".target",
            required={"kind", "sourceFingerprint"},
        )
        target_view = {
            "kind": "source",
            "sourceFingerprint": _sha256(
                target["sourceFingerprint"],
                label + ".target.sourceFingerprint",
            ),
        }
    else:
        target = _object(
            target_item,
            label + ".target",
            required={
                "kind",
                "sourceFingerprint",
                "baseIdentity",
                "headIdentity",
            },
        )
        target_view = {
            "kind": "diff",
            "sourceFingerprint": _sha256(
                target["sourceFingerprint"],
                label + ".target.sourceFingerprint",
            ),
            "baseIdentity": _string(
                target["baseIdentity"], label + ".target.baseIdentity"
            ),
            "headIdentity": _string(
                target["headIdentity"], label + ".target.headIdentity"
            ),
        }
    requested_paths = _string_array(
        item["requestedPaths"],
        label + ".requestedPaths",
        allow_empty=False,
    )
    requested_paths = [
        _relative_path(path, label + ".requestedPaths item")
        for path in requested_paths
    ]
    core = {
        "target": target_view,
        "requestedPaths": sorted(requested_paths),
    }
    expected_digest = _review_request_digest(core)
    supplied_digest = _sha256(item["requestSha256"], label + ".requestSha256")
    if supplied_digest != expected_digest:
        raise _error(
            "REVIEW_REQUEST_DIGEST",
            label + ".requestSha256 does not match the canonical request binding",
        )
    view = {**core, "requestSha256": supplied_digest}
    return ReviewRequest(
        target_kind=kind,
        source_fingerprint=target_view["sourceFingerprint"],
        requested_paths=tuple(sorted(requested_paths)),
        request_sha256=supplied_digest,
        _canonical_bytes=_canonical_json_bytes(view),
    )


def build_review_request(
    *,
    target_kind: str,
    source_fingerprint: str,
    requested_paths: Sequence[str],
    base_identity: str | None = None,
    head_identity: str | None = None,
) -> ReviewRequest:
    """Build a canonical request binding from explicit, already-resolved inputs."""

    kind = _string(target_kind, "review request target kind")
    if kind not in REVIEW_TARGET_KINDS:
        raise _error("REVIEW_REQUEST", "review request target kind is unsupported")
    if isinstance(requested_paths, (str, bytes)) or not isinstance(
        requested_paths, Sequence
    ):
        raise _error("REVIEW_SCHEMA", "review request paths must be a string array")
    normalized_paths = _string_array(
        list(requested_paths),
        "review request paths",
        allow_empty=False,
    )
    normalized_paths = [
        _relative_path(path, "review request paths item")
        for path in normalized_paths
    ]
    target: dict[str, Any] = {
        "kind": kind,
        "sourceFingerprint": _sha256(
            source_fingerprint,
            "review request source fingerprint",
        ),
    }
    if kind == "source":
        if base_identity is not None or head_identity is not None:
            raise _error(
                "REVIEW_REQUEST",
                "source review requests must not include base or head identity",
            )
    else:
        if base_identity is None or head_identity is None:
            raise _error(
                "REVIEW_REQUEST",
                "diff review requests require both base and head identity",
            )
        target.update(
            {
                "baseIdentity": _string(
                    base_identity,
                    "review request base identity",
                ),
                "headIdentity": _string(
                    head_identity,
                    "review request head identity",
                ),
            }
        )
    core = {
        "target": target,
        "requestedPaths": sorted(normalized_paths),
    }
    return _review_request(
        {
            **core,
            "requestSha256": _review_request_digest(core),
        },
        "review request",
    )


def review_request_view(request: ReviewRequest) -> dict[str, Any]:
    """Return a fresh deterministic JSON-compatible request-binding view."""

    if not isinstance(request, ReviewRequest):
        raise TypeError("request must be a ReviewRequest")
    return request.view


def canonical_review_request_bytes(request: ReviewRequest) -> bytes:
    """Serialize a canonical request binding; the digest excludes transport LF."""

    if not isinstance(request, ReviewRequest):
        raise TypeError("request must be a ReviewRequest")
    return request._canonical_bytes


def _safe_project_file(
    project_root: Path, relative: str, label: str
) -> tuple[Path, os.stat_result]:
    root = project_root.resolve()
    if not root.is_dir():
        raise _error("REVIEW_PATH", "project root is not an existing directory")
    candidate = root / relative
    current = root
    reference_stat: os.stat_result | None = None
    try:
        for part in PurePosixPath(relative).parts:
            current = current / part
            reference_stat = current.lstat()
            if stat.S_ISLNK(reference_stat.st_mode):
                raise _error("REVIEW_PATH", label + " uses a symlink")
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except FileNotFoundError as exc:
        raise _error("REVIEW_PATH", label + " does not exist: " + relative) from exc
    except (OSError, ValueError) as exc:
        raise _error("REVIEW_PATH", label + " escapes the project root") from exc
    if reference_stat is None or not stat.S_ISREG(reference_stat.st_mode):
        raise _error("REVIEW_PATH", label + " must be a regular file")
    return resolved, reference_stat


def _safe_project_directory(project_root: Path, relative: str, label: str) -> Path:
    root = project_root.resolve()
    candidate = root if relative == "." else root / relative
    try:
        candidate.resolve().relative_to(root)
    except (OSError, ValueError) as exc:
        raise _error("REVIEW_PATH", label + " escapes the project root") from exc
    if relative != ".":
        current = root
        try:
            for part in PurePosixPath(relative).parts:
                current = current / part
                if stat.S_ISLNK(current.lstat().st_mode):
                    raise _error("REVIEW_PATH", label + " uses a symlink")
        except FileNotFoundError as exc:
            raise _error("REVIEW_PATH", label + " does not exist") from exc
    if not candidate.is_dir():
        raise _error("REVIEW_PATH", label + " must be an existing directory")
    return candidate


def _location(
    value: Any,
    label: str,
    project_root: Path | None,
    *,
    location_snapshots: Mapping[str, _AttestedLocationSnapshot] | None = None,
) -> dict[str, Any]:
    item = _object(
        value,
        label,
        required={"path", "lineStart", "lineEnd"},
        optional={"symbol"},
    )
    path = _relative_path(item["path"], label + ".path")
    line_start = _positive_int(item["lineStart"], label + ".lineStart")
    line_end = _positive_int(item["lineEnd"], label + ".lineEnd")
    if line_end < line_start:
        raise _error("REVIEW_LOCATION", label + " lineEnd must not precede lineStart")
    result: dict[str, Any] = {
        "path": path,
        "lineStart": line_start,
        "lineEnd": line_end,
    }
    if "symbol" in item:
        result["symbol"] = _string(item["symbol"], label + ".symbol")
    if location_snapshots is not None:
        try:
            snapshot = location_snapshots[path]
        except KeyError as exc:
            raise _error(
                "REVIEW_TRACE",
                label + ".path is outside the attested content snapshot: " + path,
            ) from exc
        if not snapshot.utf8_valid:
            raise _error("REVIEW_LOCATION", label + " must reference UTF-8 text")
        line_count = snapshot.line_count
    elif project_root is not None:
        source, source_stat = _safe_project_file(
            project_root, path, label + ".path"
        )
        try:
            source_text = _read_regular_file(
                source,
                limit=MAX_EVIDENCE_SOURCE_BYTES,
                label=label + ".path",
                expected_stat=source_stat,
            ).decode("utf-8")
            line_count = len(source_text.splitlines())
        except SemanticReviewError:
            raise
        except UnicodeError as exc:
            raise _error("REVIEW_LOCATION", label + " must reference UTF-8 text") from exc
    if location_snapshots is not None or project_root is not None:
        if line_end > line_count:
            raise _error(
                "REVIEW_LOCATION",
                f"{label} lineEnd {line_end} exceeds {path} line count {line_count}",
            )
    return result


def _evidence(
    value: Any,
    label: str,
    project_root: Path | None,
    *,
    location_snapshots: Mapping[str, _AttestedLocationSnapshot] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise _error("REVIEW_EVIDENCE", label + " must be a non-empty array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        item = _object(
            raw,
            item_label,
            required={"location", "fact"},
        )
        result.append(
            {
                "location": _location(
                    item["location"],
                    item_label + ".location",
                    project_root,
                    location_snapshots=location_snapshots,
                ),
                "fact": _string(item["fact"], item_label + ".fact"),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["location"]["path"],
            item["location"]["lineStart"],
            item["location"]["lineEnd"],
            item["location"].get("symbol", ""),
            item.get("fact", ""),
        ),
    )


def _trigger_path(
    value: Any,
    label: str,
    project_root: Path | None,
    *,
    location_snapshots: Mapping[str, _AttestedLocationSnapshot] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise _error("REVIEW_TRIGGER", label + " must be a non-empty array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value, start=1):
        item_label = f"{label}[{index - 1}]"
        item = _object(
            raw,
            item_label,
            required={"step", "location", "condition", "transition"},
        )
        step = _positive_int(item["step"], item_label + ".step")
        if step != index:
            raise _error("REVIEW_TRIGGER", label + " steps must be contiguous from 1")
        result.append(
            {
                "step": step,
                "location": _location(
                    item["location"],
                    item_label + ".location",
                    project_root,
                    location_snapshots=location_snapshots,
                ),
                "condition": _string(item["condition"], item_label + ".condition"),
                "transition": _string(item["transition"], item_label + ".transition"),
            }
        )
    return result


def _counterexample(value: Any, label: str) -> dict[str, Any]:
    item = _object(
        value,
        label,
        required={
            "preconditions",
            "steps",
            "expectedOutcome",
            "riskOutcome",
            "falsifiedWhen",
        },
    )
    steps = item["steps"]
    if not isinstance(steps, list) or not steps:
        raise _error(
            "REVIEW_COUNTEREXAMPLE",
            label + ".steps must be a non-empty string array",
        )
    return {
        "preconditions": _string_array(
            item["preconditions"], label + ".preconditions", allow_empty=False
        ),
        "steps": [
            _string(step, f"{label}.steps[{index}]")
            for index, step in enumerate(steps)
        ],
        "expectedOutcome": _string(item["expectedOutcome"], label + ".expectedOutcome"),
        "riskOutcome": _string(item["riskOutcome"], label + ".riskOutcome"),
        "falsifiedWhen": _string(item["falsifiedWhen"], label + ".falsifiedWhen"),
}


def _evidence_contract(value: Any, label: str) -> dict[str, list[str]]:
    item = _object(
        value,
        label,
        required={"requiredFiles", "nonEmptyFiles"},
    )
    required_files = _string_array(
        item["requiredFiles"], label + ".requiredFiles", allow_empty=False
    )
    non_empty_files = _string_array(
        item["nonEmptyFiles"], label + ".nonEmptyFiles", allow_empty=False
    )
    required_files = [
        _relative_path(path, label + ".requiredFiles item") for path in required_files
    ]
    non_empty_files = [
        _relative_path(path, label + ".nonEmptyFiles item") for path in non_empty_files
    ]
    if not set(non_empty_files).issubset(set(required_files)):
        raise _error(
            "REVIEW_CASE", label + ".nonEmptyFiles must be a subset of requiredFiles"
        )
    return {
        "requiredFiles": sorted(required_files),
        "nonEmptyFiles": sorted(non_empty_files),
    }


def _argv_path_values(token: str) -> list[str]:
    """Expand the argv path spellings recognized by the campaign consumer."""

    if token.startswith("-"):
        values = [token.split("=", 1)[1]] if "=" in token else []
    elif token.startswith("@") and len(token) > 1:
        values = [token[1:]]
    else:
        values = [token]
    expanded: list[str] = []
    for value in values:
        expanded.append(value)
        if "::" in value:
            path_part, _ = value.split("::", 1)
            if path_part:
                expanded.append(path_part)
    return list(dict.fromkeys(expanded))


def _looks_like_source_test_path(value: str) -> bool:
    if not value or "://" in value or re.match(r"^[A-Za-z]:", value):
        return False
    return (
        "/" in value
        or "\\" in value
        or PurePosixPath(value).suffix.lower() in SOURCE_TEST_SUFFIXES
    )


def _existing_argv_project_file(
    value: str,
    cwd: str,
    project_root: Path,
    label: str,
) -> str | None:
    """Resolve an existing argv-owned project file without guessing bare commands."""

    if not value or "://" in value or any(character in value for character in "\r\n"):
        return None
    root = project_root.resolve()
    cwd_path = root if cwd == "." else root / PurePosixPath(cwd)
    raw = Path(value)
    candidate = raw if raw.is_absolute() else cwd_path / raw
    try:
        lexical = Path(os.path.abspath(str(candidate)))
        relative = lexical.relative_to(root).as_posix()
    except (OSError, ValueError):
        if not raw.is_absolute() and _looks_like_source_test_path(value):
            raise _error(
                "REVIEW_CASE",
                label + " argv project path escapes the project root: " + value,
            )
        return None

    try:
        exists = lexical.exists()
        is_link = lexical.is_symlink()
    except OSError:
        return None
    if not exists and not is_link:
        if _looks_like_source_test_path(value):
            raise _error(
                "REVIEW_CASE",
                label + " argv project file must exist and be regular: " + relative,
            )
        return None
    try:
        source, _ = _safe_project_file(root, relative, label + " argv project file")
    except SemanticReviewError as exc:
        if lexical.is_dir() and not _looks_like_source_test_path(value):
            return None
        raise _error(
            "REVIEW_CASE",
            label + " argv project file must be regular and non-symlink: " + relative,
        ) from exc
    return source.relative_to(root).as_posix()


def runner_inline_code_argv_indexes(
    argv: Sequence[str],
) -> tuple[frozenset[int], frozenset[int]]:
    """Return recognized interpreter option and inline-code argument indexes.

    Inline-code flags are executable-specific and only have interpreter semantics
    before the first execution target.  A later ``-c``/``-e`` belongs to the
    invoked program and must remain eligible for project-input discovery.
    """

    if not argv or not isinstance(argv[0], str):
        return frozenset(), frozenset()
    executable = PurePosixPath(argv[0].replace("\\", "/")).name
    if executable.lower().endswith(".exe"):
        executable = executable[:-4]
    if PYTHON_INTERPRETER_RE.fullmatch(executable):
        inline_options = ("-c",)
    elif NODE_INTERPRETER_RE.fullmatch(executable):
        inline_options = ("-e", "--eval")
    elif RUBY_INTERPRETER_RE.fullmatch(executable):
        inline_options = ("-e",)
    elif SHELL_INTERPRETER_RE.fullmatch(executable):
        inline_options = ("-c",)
    elif PERL_INTERPRETER_RE.fullmatch(executable):
        inline_options = ("-e",)
    elif BUN_INTERPRETER_RE.fullmatch(executable):
        inline_options = ("-e",)
    else:
        return frozenset(), frozenset()

    for index, token in enumerate(argv[1:], start=1):
        if not isinstance(token, str) or token == "--" or not token.startswith("-"):
            break
        for option in inline_options:
            if token == option:
                arguments = {index + 1} if index + 1 < len(argv) else set()
                return frozenset({index}), frozenset(arguments)
            if token.startswith(option + "="):
                return frozenset({index}), frozenset()
    return frozenset(), frozenset()


def _validate_runner_argv_provenance(
    argv: list[str],
    cwd: str,
    source_evidence: list[dict[str, Any]],
    project_root: Path,
    label: str,
) -> None:
    evidenced_paths = {
        item["location"]["path"]
        for item in source_evidence
    }
    inline_options, inline_arguments = runner_inline_code_argv_indexes(argv)
    for index, token in enumerate(argv):
        if index in inline_options or index in inline_arguments:
            continue
        for value in _argv_path_values(token):
            project_path = _existing_argv_project_file(
                value,
                cwd,
                project_root,
                f"{label}.argv[{index}]",
            )
            if project_path is None:
                continue
            if project_path not in evidenced_paths:
                raise _error(
                    "REVIEW_CASE",
                    f"{label}.argv[{index}] project file is not represented by "
                    f"{label}.sourceEvidence: {project_path}",
                )


def _runner(
    value: Any,
    label: str,
    project_root: Path | None,
    *,
    location_snapshots: Mapping[str, _AttestedLocationSnapshot] | None = None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    item = _object(
        value,
        label,
        required={
            "argv",
            "cwd",
            "timeoutSeconds",
            "fixture",
            "externalCapabilities",
            "evidence",
            "sourceEvidence",
        },
    )
    if not isinstance(item["argv"], list) or not item["argv"]:
        raise _error("REVIEW_CASE", label + ".argv must be a non-empty string array")
    # argv ordering and repeated values are executable semantics, not set metadata.
    argv = [
        _string(part, f"{label}.argv[{index}]")
        for index, part in enumerate(item["argv"])
    ]
    if any(SECRET_VALUE_RE.search(part) for part in argv) or any(
        SECRET_OPTION_RE.fullmatch(argv[index]) for index in range(len(argv) - 1)
    ):
        raise _error("REVIEW_SECRET", label + ".argv contains secret-like input")
    cwd = _relative_path(item["cwd"], label + ".cwd", allow_dot=True)
    timeout = item["timeoutSeconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
        or timeout > MAX_TIMEOUT_SECONDS
    ):
        raise _error("REVIEW_CASE", label + ".timeoutSeconds is invalid")
    fixture = item["fixture"]
    if fixture is not None:
        fixture = _relative_path(fixture, label + ".fixture")
    capabilities = _string_array(
        item["externalCapabilities"],
        label + ".externalCapabilities",
        pattern=CAPABILITY_RE,
    )
    source_evidence = _evidence(
        item["sourceEvidence"],
        label + ".sourceEvidence",
        project_root,
        location_snapshots=location_snapshots,
    )
    if project_root is not None:
        _safe_project_directory(project_root, cwd, label + ".cwd")
        if fixture is not None:
            _safe_project_file(project_root, fixture, label + ".fixture")
        _validate_runner_argv_provenance(
            argv,
            cwd,
            source_evidence,
            project_root,
            label,
        )
    return {
        "argv": argv,
        "cwd": cwd,
        "timeoutSeconds": timeout,
        "fixture": fixture,
        "externalCapabilities": capabilities,
        "evidence": _evidence_contract(item["evidence"], label + ".evidence"),
        "sourceEvidence": source_evidence,
    }


def _case_candidate(
    value: Any,
    label: str,
    *,
    finding_id: str,
    finding_required: bool,
    criteria_ids: list[str],
    invariant_ids: list[str],
    project_root: Path | None,
    location_snapshots: Mapping[str, _AttestedLocationSnapshot] | None = None,
) -> dict[str, Any]:
    item = _object(
        value,
        label,
        required={
            "id",
            "category",
            "required",
            "platform",
            "dependsOn",
            "coversCriteria",
            "coversInvariants",
            "reviewFindingIds",
            "scenarioTags",
            "quick",
            "runner",
            "conversionBlockers",
        },
    )
    case_id = _string(item["id"], label + ".id")
    if CASE_ID_RE.fullmatch(case_id) is None:
        raise _error("REVIEW_CASE", label + ".id is not a valid campaign case ID")
    category = _string(item["category"], label + ".category")
    if category not in CASE_CATEGORIES:
        raise _error("REVIEW_CASE", label + ".category is unsupported")
    required = _bool(item["required"], label + ".required")
    if required is not finding_required:
        raise _error("REVIEW_CASE", label + ".required must equal finding.required")
    platform = _string(item["platform"], label + ".platform")
    if platform not in CASE_PLATFORMS:
        raise _error("REVIEW_CASE", label + ".platform is unsupported")
    dependencies = _string_array(
        item["dependsOn"], label + ".dependsOn", pattern=CASE_ID_RE
    )
    if case_id in dependencies:
        raise _error("REVIEW_CASE", label + " cannot depend on itself")
    covers_criteria = _string_array(
        item["coversCriteria"], label + ".coversCriteria", pattern=CRITERION_ID_RE
    )
    covers_invariants = _string_array(
        item["coversInvariants"], label + ".coversInvariants", pattern=INVARIANT_ID_RE
    )
    review_ids = _string_array(
        item["reviewFindingIds"],
        label + ".reviewFindingIds",
        pattern=RF_ID_RE,
        allow_empty=False,
    )
    if covers_criteria != criteria_ids or covers_invariants != invariant_ids:
        raise _error(
            "REVIEW_TRACE",
            label + " coverage IDs must exactly match its finding",
        )
    if review_ids != [finding_id]:
        raise _error(
            "REVIEW_TRACE", label + ".reviewFindingIds must contain only " + finding_id
        )
    scenario_tags = _string_array(
        item["scenarioTags"],
        label + ".scenarioTags",
        values=SCENARIO_TAGS,
        allow_empty=False,
    )
    runner = _runner(
        item["runner"],
        label + ".runner",
        project_root,
        location_snapshots=location_snapshots,
    )
    blockers = _string_array(
        item["conversionBlockers"], label + ".conversionBlockers"
    )
    if runner is None and not blockers:
        raise _error(
            "REVIEW_CASE",
            label + " without a repository-evidenced runner needs conversionBlockers",
        )
    if runner is not None and blockers:
        raise _error(
            "REVIEW_CASE", label + " with a runner must have no conversionBlockers"
        )
    return {
        "id": case_id,
        "category": category,
        "required": required,
        "platform": platform,
        "dependsOn": dependencies,
        "coversCriteria": covers_criteria,
        "coversInvariants": covers_invariants,
        "reviewFindingIds": review_ids,
        "scenarioTags": scenario_tags,
        "quick": _bool(item["quick"], label + ".quick"),
        "runner": runner,
        "conversionBlockers": blockers,
    }


def _finding(
    value: Any,
    label: str,
    project_root: Path | None,
    *,
    location_snapshots: Mapping[str, _AttestedLocationSnapshot] | None = None,
) -> ReviewFinding:
    item = _object(
        value,
        label,
        required={
            "id",
            "title",
            "required",
            "resolutionState",
            "support",
            "criteriaIds",
            "invariantIds",
            "evidence",
            "triggerPath",
            "observableConsequence",
            "counterexample",
            "caseCandidate",
        },
    )
    finding_id = _string(item["id"], label + ".id")
    if RF_ID_RE.fullmatch(finding_id) is None:
        raise _error("REVIEW_ID", label + ".id must match RF-*")
    required = _bool(item["required"], label + ".required")
    resolution_state = _string(item["resolutionState"], label + ".resolutionState")
    if resolution_state not in RESOLUTION_STATES:
        raise _error("REVIEW_SCHEMA", label + ".resolutionState is unsupported")
    support = _string(item["support"], label + ".support")
    if support not in SUPPORT_LEVELS:
        raise _error("REVIEW_SCHEMA", label + ".support is unsupported")
    criteria_ids = _string_array(
        item["criteriaIds"], label + ".criteriaIds", pattern=CRITERION_ID_RE
    )
    invariant_ids = _string_array(
        item["invariantIds"], label + ".invariantIds", pattern=INVARIANT_ID_RE
    )
    candidate = _case_candidate(
        item["caseCandidate"],
        label + ".caseCandidate",
        finding_id=finding_id,
        finding_required=required,
        criteria_ids=criteria_ids,
        invariant_ids=invariant_ids,
        project_root=project_root,
        location_snapshots=location_snapshots,
    )
    view = {
        "id": finding_id,
        "title": _string(item["title"], label + ".title"),
        "required": required,
        "resolutionState": resolution_state,
        "support": support,
        "criteriaIds": criteria_ids,
        "invariantIds": invariant_ids,
        "evidence": _evidence(
            item["evidence"],
            label + ".evidence",
            project_root,
            location_snapshots=location_snapshots,
        ),
        "triggerPath": _trigger_path(
            item["triggerPath"],
            label + ".triggerPath",
            project_root,
            location_snapshots=location_snapshots,
        ),
        "observableConsequence": _string(
            item["observableConsequence"], label + ".observableConsequence"
        ),
        "counterexample": _counterexample(
            item["counterexample"], label + ".counterexample"
        ),
        "caseCandidate": candidate,
    }
    return ReviewFinding(
        id=finding_id,
        required=required,
        resolution_state=resolution_state,
        criteria_ids=tuple(criteria_ids),
        invariant_ids=tuple(invariant_ids),
        case_candidate=copy.deepcopy(candidate),
        view=view,
    )


def _validate_case_dependencies(findings: tuple[ReviewFinding, ...]) -> None:
    case_ids = {item.case_candidate["id"] for item in findings}
    dependencies = {
        item.case_candidate["id"]: tuple(item.case_candidate["dependsOn"])
        for item in findings
    }
    for case_id, referenced in dependencies.items():
        unknown = sorted(set(referenced) - case_ids)
        if unknown:
            raise _error(
                "REVIEW_CASE",
                "case candidate "
                + case_id
                + " depends on unknown case IDs: "
                + ", ".join(unknown),
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(case_id: str, chain: tuple[str, ...]) -> None:
        if case_id in visited:
            return
        if case_id in visiting:
            cycle_start = chain.index(case_id)
            cycle = (*chain[cycle_start:], case_id)
            raise _error(
                "REVIEW_CASE",
                "case candidate dependency cycle: " + " -> ".join(cycle),
            )
        visiting.add(case_id)
        for dependency in dependencies[case_id]:
            visit(dependency, (*chain, case_id))
        visiting.remove(case_id)
        visited.add(case_id)

    for case_id in sorted(case_ids):
        visit(case_id, ())


def _gap(value: Any, label: str) -> tuple[ReviewGap, dict[str, Any]]:
    item = _object(
        value,
        label,
        required={"id", "kind", "detail", "neededEvidence"},
        optional={"paths"},
    )
    gap_id = _string(item["id"], label + ".id")
    if RG_ID_RE.fullmatch(gap_id) is None:
        raise _error("REVIEW_ID", label + ".id must match RG-*")
    kind = _string(item["kind"], label + ".kind")
    if kind not in REVIEW_GAP_KINDS:
        raise _error("REVIEW_SCHEMA", label + ".kind is unsupported")
    detail = _string(item["detail"], label + ".detail")
    needed_evidence = _string_array(
        item["neededEvidence"],
        label + ".neededEvidence",
        allow_empty=False,
    )
    paths: list[str] = []
    if "paths" in item:
        paths = _string_array(
            item["paths"],
            label + ".paths",
            allow_empty=False,
        )
        paths = [
            _relative_path(path, label + ".paths item") for path in paths
        ]
        if kind != "unreviewed-scope":
            raise _error(
                "REVIEW_GAP",
                label + ".paths is allowed only for an unreviewed-scope gap",
            )
    gap_view: dict[str, Any] = {
        "id": gap_id,
        "kind": kind,
        "detail": detail,
        "neededEvidence": needed_evidence,
    }
    if paths:
        gap_view["paths"] = sorted(paths)
    return (
        ReviewGap(
            id=gap_id,
            kind=kind,
            detail=detail,
            needed_evidence=tuple(needed_evidence),
            paths=tuple(sorted(paths)),
        ),
        gap_view,
    )


def _scope_file(
    value: Any,
    label: str,
    project_root: Path | None,
    *,
    location_paths: set[str] | None = None,
    location_snapshots: dict[str, _AttestedLocationSnapshot] | None = None,
) -> tuple[ReviewScopeFile, dict[str, str]]:
    item = _object(value, label, required={"path", "sha256"})
    path = _relative_path(item["path"], label + ".path")
    expected_digest = _sha256(item["sha256"], label + ".sha256")
    if project_root is not None:
        try:
            source, source_stat = _safe_project_file(
                project_root,
                path,
                label + ".path",
            )
            content = _read_regular_file(
                source,
                limit=MAX_EVIDENCE_SOURCE_BYTES,
                label=label + ".path",
                expected_stat=source_stat,
            )
        except SemanticReviewError as exc:
            if exc.code in {"REVIEW_PATH", "REVIEW_IO"}:
                raise _error(
                    "REVIEW_BASELINE_DRIFT",
                    label + ".path is no longer the attested regular file: " + path,
                ) from exc
            raise
        actual_digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if actual_digest != expected_digest:
            raise _error(
                "REVIEW_BASELINE_DRIFT",
                label
                + ".sha256 does not match current project content for "
                + path,
            )
        if (
            location_paths is not None
            and location_snapshots is not None
            and path in location_paths
        ):
            try:
                line_count = len(content.decode("utf-8").splitlines())
            except UnicodeError:
                location_snapshots[path] = _AttestedLocationSnapshot(
                    line_count=0,
                    utf8_valid=False,
                )
            else:
                location_snapshots[path] = _AttestedLocationSnapshot(
                    line_count=line_count,
                    utf8_valid=True,
                )
    return (
        ReviewScopeFile(path=path, sha256=expected_digest),
        {"path": path, "sha256": expected_digest},
    )


def _finding_location_paths(finding: ReviewFinding) -> set[str]:
    value = finding.view
    result = {
        item["location"]["path"]
        for item in value["evidence"]
    }
    result.update(item["location"]["path"] for item in value["triggerPath"])
    runner = value["caseCandidate"]["runner"]
    if runner is not None:
        result.update(
            item["location"]["path"] for item in runner["sourceEvidence"]
        )
    return result


def _finding_attested_paths(finding: ReviewFinding) -> set[str]:
    result = _finding_location_paths(finding)
    runner = finding.view["caseCandidate"]["runner"]
    if runner is not None:
        if runner["fixture"] is not None:
            result.add(runner["fixture"])
    return result


def _attestation(
    value: Any,
    label: str,
    findings: tuple[ReviewFinding, ...],
    review_request: ReviewRequest | None,
    project_root: Path | None,
    *,
    location_snapshots: dict[str, _AttestedLocationSnapshot] | None = None,
) -> ReviewAttestation:
    item = _object(
        value,
        label,
        required={
            "sourceFingerprint",
            "goalContractSha256",
            "invariantsSha256",
            "outcome",
            "scope",
            "gaps",
        },
    )
    source_fingerprint = _sha256(
        item["sourceFingerprint"], label + ".sourceFingerprint"
    )
    goal_contract_sha256 = _sha256(
        item["goalContractSha256"], label + ".goalContractSha256"
    )
    invariants_sha256 = _sha256(
        item["invariantsSha256"], label + ".invariantsSha256"
    )
    outcome = _string(item["outcome"], label + ".outcome")
    if outcome not in REVIEW_OUTCOMES:
        raise _error("REVIEW_SCHEMA", label + ".outcome is unsupported")

    if not isinstance(item["scope"], list) or not item["scope"]:
        raise _error("REVIEW_SCHEMA", label + ".scope must be a non-empty array")
    location_paths: set[str] = set()
    for finding in findings:
        location_paths.update(_finding_location_paths(finding))
    scope_pairs = [
        _scope_file(
            raw,
            f"{label}.scope[{index}]",
            project_root,
            location_paths=location_paths,
            location_snapshots=location_snapshots,
        )
        for index, raw in enumerate(item["scope"])
    ]
    scope_pairs.sort(key=lambda pair: pair[0].path)
    scope = tuple(pair[0] for pair in scope_pairs)
    scope_view = [pair[1] for pair in scope_pairs]
    scope_paths = [entry.path for entry in scope]
    if len(set(scope_paths)) != len(scope_paths):
        raise _error("REVIEW_PATH", label + ".scope paths must be unique")

    if not isinstance(item["gaps"], list):
        raise _error("REVIEW_SCHEMA", label + ".gaps must be an array")
    gap_pairs = [
        _gap(raw, f"{label}.gaps[{index}]")
        for index, raw in enumerate(item["gaps"])
    ]
    gap_pairs.sort(key=lambda pair: pair[0].id)
    gaps = tuple(pair[0] for pair in gap_pairs)
    gaps_view = [pair[1] for pair in gap_pairs]
    gap_ids = [gap.id for gap in gaps]
    if len(set(gap_ids)) != len(gap_ids):
        raise _error("REVIEW_ID", "review gap IDs must be unique")

    expected_outcome = (
        "incomplete" if gaps else "findings" if findings else "no-findings"
    )
    if outcome != expected_outcome:
        raise _error(
            "REVIEW_SCHEMA",
            label
            + ".outcome must be "
            + expected_outcome
            + " for the supplied findings and gaps",
        )

    scope_path_set = set(scope_paths)
    for finding in findings:
        missing_paths = sorted(_finding_attested_paths(finding) - scope_path_set)
        if missing_paths:
            raise _error(
                "REVIEW_TRACE",
                "review finding "
                + finding.id
                + " references paths outside attestation.scope: "
                + ", ".join(missing_paths),
            )
    if review_request is not None:
        missing_requested_paths = sorted(
            set(review_request.requested_paths) - scope_path_set
        )
        unreviewed_scope_gaps = tuple(
            gap for gap in gaps if gap.kind == "unreviewed-scope"
        )
        gaps_without_paths = [gap.id for gap in unreviewed_scope_gaps if not gap.paths]
        if gaps_without_paths:
            raise _error(
                "REVIEW_REQUEST_SCOPE",
                "request-bound unreviewed-scope gaps require non-empty paths: "
                + ", ".join(gaps_without_paths),
            )
        gap_paths = sorted(
            {
                path
                for gap in unreviewed_scope_gaps
                for path in gap.paths
            }
        )
        if gap_paths != missing_requested_paths:
            raise _error(
                "REVIEW_REQUEST_SCOPE",
                "unreviewed-scope gap paths must exactly equal requested paths "
                "missing from attestation.scope; expected "
                + json.dumps(missing_requested_paths, ensure_ascii=False)
                + " but received "
                + json.dumps(gap_paths, ensure_ascii=False),
            )
        if missing_requested_paths and outcome != "incomplete":
            raise _error(
                "REVIEW_REQUEST_SCOPE",
                "a review with uncovered requested paths must be incomplete",
            )

    view = {
        "sourceFingerprint": source_fingerprint,
        "goalContractSha256": goal_contract_sha256,
        "invariantsSha256": invariants_sha256,
        "outcome": outcome,
        "scope": scope_view,
        "gaps": gaps_view,
    }
    return ReviewAttestation(
        source_fingerprint=source_fingerprint,
        goal_contract_sha256=goal_contract_sha256,
        invariants_sha256=invariants_sha256,
        outcome=outcome,
        scope=scope,
        gaps=gaps,
        _canonical_bytes=_canonical_json_bytes(view),
    )


def validate_review_manifest(
    value: Mapping[str, Any],
    *,
    project_root: str | Path | None = None,
    path: str | Path | None = None,
    verify_baseline: bool = True,
    expected_review_request: Mapping[str, Any] | None = None,
) -> ReviewManifest:
    """Validate v1; disable baseline checks only for pinned historical evidence."""

    root = Path(project_root) if project_root is not None else None
    validation_root = root if verify_baseline else None
    data = _object(
        value,
        "review manifest",
        required={"schemaId", "schemaVersion", "findings"},
        optional={"attestation", "reviewRequest"},
    )
    if data["schemaId"] != SCHEMA_ID:
        raise _error("REVIEW_SCHEMA", "unsupported semantic-review schemaId")
    if type(data["schemaVersion"]) is not int or data["schemaVersion"] != SCHEMA_VERSION:
        raise _error("REVIEW_SCHEMA", "semantic-review schemaVersion must be 1")
    if not isinstance(data["findings"], list):
        raise _error("REVIEW_SCHEMA", "review manifest.findings must be an array")
    review_request = (
        _review_request(data["reviewRequest"], "review manifest.reviewRequest")
        if "reviewRequest" in data
        else None
    )
    if review_request is not None and "attestation" not in data:
        raise _error(
            "REVIEW_REQUEST_ATTESTATION",
            "reviewRequest requires an attestation",
        )
    expected_request = (
        _review_request(expected_review_request, "expected review request")
        if expected_review_request is not None
        else None
    )
    if expected_request is not None and review_request is None:
        raise _error(
            "REVIEW_REQUEST_REQUIRED",
            "the trusted expected review request requires manifest.reviewRequest",
        )
    if expected_request is not None and (
        review_request is None
        or review_request._canonical_bytes != expected_request._canonical_bytes
    ):
        raise _error(
            "REVIEW_REQUEST_MISMATCH",
            "manifest.reviewRequest does not exactly match the trusted expected binding",
        )
    # For attested reviews, check the baseline before line bounds or runner paths so
    # any content change has the stable REVIEW_BASELINE_DRIFT failure direction.
    finding_root = (
        None if "attestation" in data and validation_root is not None else validation_root
    )
    findings = tuple(
        sorted(
            (
                _finding(item, f"review manifest.findings[{index}]", finding_root)
                for index, item in enumerate(data["findings"])
            ),
            key=lambda item: item.id,
        )
    )
    ids = [item.id for item in findings]
    if len(set(ids)) != len(ids):
        raise _error("REVIEW_ID", "review finding IDs must be unique")
    case_ids = [item.case_candidate["id"] for item in findings]
    if len(set(case_ids)) != len(case_ids):
        raise _error("REVIEW_CASE", "case candidate IDs must be unique")
    _validate_case_dependencies(findings)
    attestation = None
    if "attestation" in data:
        captured_locations: dict[str, _AttestedLocationSnapshot] | None = (
            {} if validation_root is not None else None
        )
        attestation = _attestation(
            data["attestation"],
            "review manifest.attestation",
            findings,
            review_request,
            validation_root,
            location_snapshots=captured_locations,
        )
        if (
            review_request is not None
            and review_request.source_fingerprint != attestation.source_fingerprint
        ):
            raise _error(
                "REVIEW_REQUEST_SOURCE",
                "reviewRequest target sourceFingerprint does not match attestation",
            )
        if validation_root is not None:
            if captured_locations is None:  # pragma: no cover - construction invariant
                raise RuntimeError("attested baseline snapshots were not captured")
            location_snapshots = MappingProxyType(captured_locations.copy())
            findings = tuple(
                sorted(
                    (
                        _finding(
                            item,
                            f"review manifest.findings[{index}]",
                            validation_root,
                            location_snapshots=location_snapshots,
                        )
                        for index, item in enumerate(data["findings"])
                    ),
                    key=lambda item: item.id,
                )
            )
            # Bind the returned strict location/runner view to a second exact
            # scope observation, closing replacement races between both passes.
            attestation = _attestation(
                data["attestation"],
                "review manifest.attestation",
                findings,
                review_request,
                validation_root,
            )
    view = {
        "schemaId": SCHEMA_ID,
        "schemaVersion": SCHEMA_VERSION,
        "findings": [copy.deepcopy(item.view) for item in findings],
    }
    if attestation is not None:
        view["attestation"] = attestation.view
    if review_request is not None:
        view["reviewRequest"] = review_request.view
    scope_verified = attestation is not None and validation_root is not None
    bindings_verified = expected_request is not None and review_request is not None
    return ReviewManifest(
        path=Path(path) if path is not None else None,
        findings=findings,
        attestation=attestation,
        review_request=review_request,
        scope_verified=scope_verified,
        bindings_verified=bindings_verified,
        _canonical_bytes=_canonical_json_bytes(view),
    )


def load_review_manifest(
    path: str | Path,
    *,
    project_root: str | Path | None = None,
    verify_baseline: bool = True,
    expected_review_request: Mapping[str, Any] | None = None,
) -> ReviewManifest:
    """Load v1 read-only; disable baseline checks only for pinned history."""

    manifest_path = Path(path)
    expected_stat: os.stat_result | None = None
    try:
        if project_root is not None:
            root_input = Path(os.path.abspath(str(project_root)))
            root = root_input.resolve()
            lexical = Path(os.path.abspath(str(manifest_path)))
            try:
                relative = lexical.relative_to(root_input)
            except ValueError as exc:
                raise _error(
                    "REVIEW_PATH", "review manifest must be inside the project root"
                ) from exc
            current = root_input
            for part in relative.parts:
                current = current / part
                expected_stat = current.lstat()
                if stat.S_ISLNK(expected_stat.st_mode):
                    raise _error("REVIEW_PATH", "review manifest uses a symlink")
            try:
                lexical.resolve().relative_to(root)
            except ValueError as exc:
                raise _error(
                    "REVIEW_PATH", "review manifest escapes the project root"
                ) from exc
            manifest_path = lexical
        raw = _read_regular_file(manifest_path, expected_stat=expected_stat)
    except SemanticReviewError:
        raise
    except OSError as exc:
        raise _error("REVIEW_IO", "cannot read review manifest: " + str(manifest_path)) from exc
    parsed = _parse_json_bytes(raw)
    if not isinstance(parsed, Mapping):
        raise _error("REVIEW_SCHEMA", "review manifest must be an object")
    return validate_review_manifest(
        parsed,
        project_root=project_root,
        path=manifest_path,
        verify_baseline=verify_baseline,
        expected_review_request=expected_review_request,
    )


def review_manifest_view(manifest: ReviewManifest) -> dict[str, Any]:
    """Return the deterministic JSON-compatible semantic-review v1 view."""

    if not isinstance(manifest, ReviewManifest):
        raise TypeError("manifest must be a ReviewManifest")
    return manifest.view


def canonical_review_manifest_bytes(manifest: ReviewManifest) -> bytes:
    """Serialize a canonical manifest; the digest excludes transport LF."""

    if not isinstance(manifest, ReviewManifest):
        raise TypeError("manifest must be a ReviewManifest")
    return manifest._canonical_bytes


def review_manifest_sha256(manifest: ReviewManifest) -> str:
    """Return the digest used by traceability.reviewFindings.sha256."""

    return "sha256:" + hashlib.sha256(canonical_review_manifest_bytes(manifest)).hexdigest()


def required_finding_ids(manifest: ReviewManifest) -> tuple[str, ...]:
    """Return stable IDs for every finding that requires final-regression proof."""

    if not isinstance(manifest, ReviewManifest):
        raise TypeError("manifest must be a ReviewManifest")
    return manifest.required_finding_ids


def case_candidates(manifest: ReviewManifest) -> tuple[dict[str, Any], ...]:
    """Return canonical case candidates without inventing missing runner contracts."""

    if not isinstance(manifest, ReviewManifest):
        raise TypeError("manifest must be a ReviewManifest")
    return tuple(copy.deepcopy(item.case_candidate) for item in manifest.findings)


def _stable_file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_expected_review_request_snapshot(
    path: str,
    project_root: Path,
) -> _ExpectedReviewRequestSnapshot:
    if path == "-":
        raise _error(
            "REVIEW_REQUEST_EXPECTED",
            "--expected-review-request cannot use stdin because stdin carries the manifest",
        )
    root_input = Path(os.path.abspath(str(project_root)))
    raw_path = Path(path)
    lexical = Path(
        os.path.abspath(str(raw_path if raw_path.is_absolute() else root_input / raw_path))
    )
    try:
        relative = lexical.relative_to(root_input).as_posix()
    except ValueError as exc:
        raise _error(
            "REVIEW_REQUEST_EXPECTED",
            "expected review request must be inside the project root",
        ) from exc
    expected_path, expected_stat = _safe_project_file(
        root_input,
        _relative_path(relative, "expected review request path"),
        "expected review request",
    )
    raw = _read_regular_file(
        expected_path,
        label="expected review request",
        expected_stat=expected_stat,
    )
    try:
        observed_stat = expected_path.lstat()
    except OSError as exc:
        raise _error(
            "REVIEW_IO",
            "cannot re-observe expected review request: " + str(expected_path),
        ) from exc
    expected_identity = _stable_file_identity(expected_stat)
    if (
        stat.S_ISLNK(observed_stat.st_mode)
        or not stat.S_ISREG(observed_stat.st_mode)
        or _stable_file_identity(observed_stat) != expected_identity
    ):
        raise _error(
            "REVIEW_IO",
            "expected review request changed while being read",
        )
    parsed = _parse_json_bytes(raw)
    if not isinstance(parsed, Mapping):
        raise _error(
            "REVIEW_REQUEST_EXPECTED",
            "expected review request must be a JSON object",
        )
    return _ExpectedReviewRequestSnapshot(
        request=_review_request(parsed, "expected review request"),
        file_identity=expected_identity,
    )


def _read_expected_review_request(path: str, project_root: Path) -> Mapping[str, Any]:
    return _read_expected_review_request_snapshot(path, project_root).request.view


def _require_current_expected_review_request(
    path: str,
    project_root: Path,
    initial: _ExpectedReviewRequestSnapshot,
) -> None:
    try:
        current = _read_expected_review_request_snapshot(path, project_root)
    except SemanticReviewError as exc:
        raise _error(
            "REVIEW_REQUEST_DRIFT",
            "expected review request became unavailable or invalid during validation",
        ) from exc
    if (
        current.file_identity != initial.file_identity
        or current.request._canonical_bytes != initial.request._canonical_bytes
    ):
        raise _error(
            "REVIEW_REQUEST_DRIFT",
            "expected review request changed during validation",
        )


def _read_cli(
    path: str,
    project_root: Path,
    expected_review_request: Mapping[str, Any] | None,
) -> ReviewManifest:
    if path == "-":
        parsed = _parse_json_bytes(_read_bounded(sys.stdin.buffer))
        if not isinstance(parsed, Mapping):
            raise _error("REVIEW_SCHEMA", "review manifest must be an object")
        return validate_review_manifest(
            parsed,
            project_root=project_root,
            expected_review_request=expected_review_request,
        )
    return load_review_manifest(
        path,
        project_root=project_root,
        expected_review_request=expected_review_request,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only validation and canonical views for semantic-review v1."
    )
    parser.add_argument(
        "command",
        choices=("check", "view", "digest", "case-candidates", "request-view"),
    )
    parser.add_argument("path", nargs="?", help="review JSON path or -")
    parser.add_argument(
        "--project-root",
        help="root used to verify project-relative evidence and runner paths",
    )
    parser.add_argument(
        "--expected-review-request",
        help=(
            "trusted project-local canonical reviewRequest JSON used for exact "
            "binding verification"
        ),
    )
    parser.add_argument(
        "--target-kind",
        choices=("source", "diff"),
        help="request-view target kind",
    )
    parser.add_argument(
        "--source-fingerprint",
        help="request-view observed source fingerprint",
    )
    parser.add_argument(
        "--base-identity",
        help="request-view exact diff base identity",
    )
    parser.add_argument(
        "--head-identity",
        help="request-view exact diff head identity",
    )
    parser.add_argument(
        "--requested-path",
        action="append",
        dest="requested_paths",
        help="request-view exact project-relative path; repeat for each path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "request-view":
            if args.path is not None:
                raise _error(
                    "REVIEW_REQUEST",
                    "request-view accepts request fields as named options only",
                )
            if args.expected_review_request is not None:
                raise _error(
                    "REVIEW_REQUEST",
                    "request-view cannot consume --expected-review-request",
                )
            if args.project_root is not None:
                raise _error(
                    "REVIEW_REQUEST",
                    "request-view does not read a project root",
                )
            request = build_review_request(
                target_kind=args.target_kind,
                source_fingerprint=args.source_fingerprint,
                requested_paths=args.requested_paths or [],
                base_identity=args.base_identity,
                head_identity=args.head_identity,
            )
            sys.stdout.buffer.write(canonical_review_request_bytes(request) + b"\n")
            return 0
        if any(
            value is not None
            for value in (
                args.target_kind,
                args.source_fingerprint,
                args.base_identity,
                args.head_identity,
                args.requested_paths,
            )
        ):
            raise _error(
                "REVIEW_REQUEST",
                "request construction options require the request-view command",
            )
        project_root = Path("." if args.project_root is None else args.project_root)
        expected_snapshot = (
            _read_expected_review_request_snapshot(
                args.expected_review_request,
                project_root,
            )
            if args.expected_review_request is not None
            else None
        )
        expected_review_request = (
            expected_snapshot.request.view if expected_snapshot is not None else None
        )
        manifest = _read_cli(
            "-" if args.path is None else args.path,
            project_root,
            expected_review_request,
        )
        if expected_snapshot is not None:
            _require_current_expected_review_request(
                args.expected_review_request,
                project_root,
                expected_snapshot,
            )
        digest = review_manifest_sha256(manifest)
        if args.command == "view":
            sys.stdout.buffer.write(canonical_review_manifest_bytes(manifest) + b"\n")
        elif args.command == "digest":
            print(digest)
        elif args.command == "case-candidates":
            sys.stdout.buffer.write(
                json.dumps(
                    list(case_candidates(manifest)),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                + b"\n"
            )
        else:
            result = (
                "VALID "
                + digest
                + " findings="
                + str(len(manifest.findings))
                + " required="
                + str(len(manifest.required_finding_ids))
            )
            if manifest.review_request is not None:
                result += (
                    " scopeVerified="
                    + str(manifest.scope_verified).lower()
                    + " bindingsVerified="
                    + str(manifest.bindings_verified).lower()
                )
            print(result)
        return 0
    except SemanticReviewError as exc:
        print("ERROR " + str(exc), file=sys.stderr)
        return 2 if exc.code == "REVIEW_IO" else 1
    except OSError as exc:
        print("ERROR REVIEW_IO: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
