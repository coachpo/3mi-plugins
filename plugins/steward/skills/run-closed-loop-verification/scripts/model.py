"""Shared constants and fail-closed persistence primitives for the verifier."""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

ADAPTER_SCHEMA_VERSION = 2
JOURNAL_SCHEMA_VERSION = 6
ARTIFACT_MANIFEST_VERSION = 1
FIX_AUDIT_SCHEMA_VERSION = 1
SCHEMA_VERSION = JOURNAL_SCHEMA_VERSION
SCRIPT_VERSION = "0.6.0"
PASS_STATUSES = {"PASS"}
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
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CampaignError("value is not canonical JSON") from exc


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def has_secret_like(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def redact_text(value: str) -> tuple[str, bool]:
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
    """Reject secret-like values before they reach durable evidence."""

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


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
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
        _fsync_directory(path.parent)
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def atomic_write_json(path: Path, value: Any) -> None:
    assert_persistable(value)
    atomic_write_bytes(path, canonical_bytes(value) + b"\n")


def atomic_write_text(path: Path, value: str) -> None:
    atomic_write_bytes(path, value.encode("utf-8", "replace"))


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


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def read_regular_bytes(path: Path, *, label: str, max_bytes: int) -> bytes:
    """Read one stable regular file without following links or special files."""

    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
            raise CampaignError(label + " uses a symlink/reparse path")
        if not stat.S_ISREG(before.st_mode):
            raise CampaignError(label + " is not a regular file")
        if before.st_size > max_bytes:
            raise CampaignError(label + " exceeds the safe size limit")
        flags = os.O_RDONLY
        for flag in ("O_BINARY", "O_CLOEXEC", "O_NONBLOCK", "O_NOFOLLOW"):
            flags |= getattr(os, flag, 0)
        descriptor = os.open(str(path), flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
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
        after = path.lstat()
        if (
            not stat.S_ISREG(final.st_mode)
            or stat.S_ISLNK(after.st_mode)
            or _is_reparse(after)
            or not stat.S_ISREG(after.st_mode)
            or not os.path.samestat(before, final)
            or not os.path.samestat(before, after)
            or final.st_size != len(content)
            or after.st_size != len(content)
            or getattr(opened, "st_mtime_ns", None)
            != getattr(final, "st_mtime_ns", None)
            or getattr(opened, "st_ctime_ns", None)
            != getattr(final, "st_ctime_ns", None)
            or getattr(after, "st_mtime_ns", None)
            != getattr(final, "st_mtime_ns", None)
            or getattr(after, "st_ctime_ns", None)
            != getattr(final, "st_ctime_ns", None)
        ):
            raise CampaignError(label + " changed while it was read")
        return bytes(content)
    except FileNotFoundError as exc:
        raise CampaignError("missing " + label + ": " + str(path)) from exc
    except CampaignError:
        raise
    except OSError as exc:
        raise CampaignError("cannot read " + label + ": " + str(path)) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def read_json(path: Path) -> Any:
    content = read_regular_bytes(path, label="JSON file", max_bytes=MAX_JSON_BYTES)
    try:
        return parse_json_text(content.decode("utf-8"), "JSON file: " + str(path))
    except UnicodeError as exc:
        raise CampaignError("cannot read JSON file: " + str(path)) from exc


def slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return result or "case"
