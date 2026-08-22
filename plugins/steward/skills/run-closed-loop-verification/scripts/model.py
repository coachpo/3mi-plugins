"""Shared schema constants, errors, canonical JSON, and persistence primitives."""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any, Optional, Tuple

ADAPTER_SCHEMA_VERSION = 1
JOURNAL_SCHEMA_VERSION = 4
READ_ONLY_JOURNAL_SCHEMA_VERSIONS = {2, 3}
ARTIFACT_MANIFEST_VERSION = 1
SCHEMA_VERSION = JOURNAL_SCHEMA_VERSION
SCRIPT_VERSION = "0.4.0"
LEGACY_KERNEL_VERSIONS = {2: "0.2.0", 3: "0.3.0"}
CASE_STATUSES = {
    "PENDING",
    "RUNNING",
    "PASS",
    "FAILED",
    "BLOCKED",
    "INTERRUPTED",
    "RETEST_PASSED",
    "NOT_RUN",
}
FINAL_RUN_STATUSES = {"PASS", "FAILED", "BLOCKED", "RETEST_PASSED"}
INITIAL_PASS_STATUSES = {"PASS", "RETEST_PASSED"}
SUPPORTED_CATEGORIES = {
    "smoke",
    "functional",
    "integration",
    "workflow",
    "role-play",
}
SUPPORTED_PROVIDERS = {"git", "manifest", "files"}
MAX_JSON_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024


class CampaignError(Exception):
    """A user-actionable campaign or adapter error."""


class AdapterError(CampaignError):
    """The adapter cannot be safely or deterministically executed."""


SECRET_PATTERNS = [
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret|credential)\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
]
SECRET_FIELD_PATTERN = re.compile(
    r"(?i)^(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret|credential|private[_-]?key)$"
)


def utc_now() -> str:
    return (
        _datetime.datetime.now(_datetime.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def canonical_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CampaignError("value is not canonical JSON") from exc
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CampaignError("value contains invalid Unicode") from exc


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def review_case_candidate_binding(value: Any) -> Any:
    """Return the immutable campaign-facing part of a Review case candidate.

    Review evidence and source citations may be refreshed after a fix.  The
    executable contract and trace mappings may not change inside a campaign.
    """

    if not isinstance(value, dict):
        raise CampaignError("semantic Review case candidate must be an object")
    candidate = dict(value)
    runner = candidate.get("runner")
    if isinstance(runner, dict):
        runner_binding = dict(runner)
        runner_binding.pop("sourceEvidence", None)
        candidate["runner"] = runner_binding
    return candidate


def review_case_candidate_sha256(value: Any) -> str:
    return sha256_bytes(canonical_bytes(review_case_candidate_binding(value)))


def has_secret_like(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def redact_text(value: str) -> Tuple[str, bool]:
    redacted = value
    found = False
    for pattern in SECRET_PATTERNS:
        redacted, count = pattern.subn("<REDACTED>", redacted)
        found = found or bool(count)
    return redacted, found


def public_message(value: Any) -> str:
    text, _ = redact_text(str(value))
    return text.replace("\x00", "\\0")[:2000]


def assert_persistable(value: Any) -> None:
    """Reject secret-like values before they reach state, journal, or summary."""

    if isinstance(value, str):
        if has_secret_like(value):
            raise CampaignError("refusing to persist a secret-like value")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            assert_persistable(str(key))
            if SECRET_FIELD_PATTERN.search(str(key)):
                raise CampaignError("refusing to persist a secret-like field")
            assert_persistable(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_persistable(item)


def atomic_write_json(path: Path, value: Any) -> None:
    assert_persistable(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(value) + b"\n"
    temp_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(path.parent),
            prefix="." + path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value.encode("utf-8", "replace")
    temp_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(path.parent),
            prefix="." + path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def reject_duplicate_pairs(pairs: Any) -> Any:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CampaignError("JSON object has a duplicate key: " + str(key))
        result[key] = value
    return result


def parse_json_text(value: str, label: str = "JSON") -> Any:
    try:
        return json.loads(value, object_pairs_hook=reject_duplicate_pairs)
    except CampaignError:
        raise
    except (json.JSONDecodeError, RecursionError, UnicodeError) as exc:
        raise CampaignError("cannot parse " + label) from exc


def read_regular_bytes(
    path: Path,
    *,
    label: str,
    max_bytes: int,
) -> bytes:
    """Read a stable regular file without following links or blocking on devices."""

    descriptor: Optional[int] = None
    try:
        before = path.lstat()
    except FileNotFoundError as exc:
        raise CampaignError("missing " + label + ": " + str(path)) from exc
    except OSError as exc:
        raise CampaignError("cannot inspect " + label + ": " + str(path)) from exc
    is_reparse = bool(
        getattr(before, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
    if stat.S_ISLNK(before.st_mode) or is_reparse:
        raise CampaignError(label + " uses a symlink/reparse path")
    if not stat.S_ISREG(before.st_mode):
        raise CampaignError(label + " is not a regular file")
    if before.st_size > max_bytes:
        raise CampaignError(label + " exceeds the safe size limit")

    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise CampaignError(label + " changed while it was opened")
        content = bytearray()
        while True:
            chunk = os.read(descriptor, READ_CHUNK_BYTES)
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > max_bytes:
                raise CampaignError(label + " exceeds the safe size limit")
        final = os.fstat(descriptor)
        try:
            after = path.lstat()
        except OSError as exc:
            raise CampaignError(label + " changed while it was read") from exc
        after_reparse = bool(
            getattr(after, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
        if (
            not stat.S_ISREG(final.st_mode)
            or stat.S_ISLNK(after.st_mode)
            or after_reparse
            or not stat.S_ISREG(after.st_mode)
            or (final.st_dev, final.st_ino) != (before.st_dev, before.st_ino)
            or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or final.st_size != len(content)
            or after.st_size != len(content)
            or getattr(final, "st_mtime_ns", None)
            != getattr(opened, "st_mtime_ns", None)
            or getattr(final, "st_ctime_ns", None)
            != getattr(opened, "st_ctime_ns", None)
            or getattr(after, "st_mtime_ns", None)
            != getattr(final, "st_mtime_ns", None)
            or getattr(after, "st_ctime_ns", None)
            != getattr(final, "st_ctime_ns", None)
        ):
            raise CampaignError(label + " changed while it was read")
        return bytes(content)
    except CampaignError:
        raise
    except OSError as exc:
        raise CampaignError("cannot read " + label + ": " + str(path)) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def read_json(path: Path) -> Any:
    try:
        content = read_regular_bytes(
            path,
            label="JSON file",
            max_bytes=MAX_JSON_BYTES,
        )
        return parse_json_text(
            content.decode("utf-8"), "JSON file: " + str(path)
        )
    except CampaignError:
        raise
    except (UnicodeError, RecursionError) as exc:
        raise CampaignError("cannot read JSON file: " + str(path)) from exc


def slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return result or "case"
