"""Provider-neutral verification profiles, impact plans, and CI projections.

This module configures and plans verification.  It never executes project cases
and never decides campaign completion; those effects belong to the bundled
``run-closed-loop-verification`` kernel.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional, Sequence

if os.name == "posix":
    import fcntl
else:  # pragma: no cover - exercised by the explicit platform guard
    fcntl = None  # type: ignore[assignment]


PROFILE_SCHEMA_ID = "steward.verification-profile"
IMPACT_SCHEMA_ID = "steward.impact-plan"
CI_PLAN_SCHEMA_ID = "steward.ci-plan"
SCHEMA_VERSION = 1
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OBJECT_ID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PACKAGE_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
EXECUTABLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
PORTABLE_OUTPUT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.+][A-Za-z0-9._+-]*$")
PLATFORMS = {"darwin", "linux", "windows"}
CASE_PLATFORMS = PLATFORMS | {"any", "posix"}
CHANGE_SOURCES = ["committed", "staged", "unstaged", "untracked"]
CHANGE_STATUSES = {"?", "A", "B", "C", "D", "M", "R", "T", "U", "X"}
IMPACT_REASON_CODES = {
    "AMBIGUOUS_PACKAGE_OWNER",
    "CHANGE_SNAPSHOT_UNSTABLE",
    "CHANGE_SNAPSHOT_UNTRUSTED",
    "HIGH_IMPACT_PATH",
    "MERGE_BASE_UNAVAILABLE",
    "UNMERGED_INDEX",
    "UNOWNED_PATH",
}
TRACE_CASE_FIELDS = {
    "coversCriteria",
    "coversInvariants",
    "reviewFindingIds",
    "scenarioTags",
}
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_GIT_OUTPUT = 64 * 1024 * 1024
MAX_STATIC_OUTPUT_BYTES = 64 * 1024 * 1024


class VerificationPipelineError(Exception):
    """A strict, user-actionable verification configuration failure."""


def _stable_stat(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _reject_duplicate_pairs(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise VerificationPipelineError("JSON object has a duplicate key: " + key)
        value[key] = item
    return value


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
        raise VerificationPipelineError("value is not canonical JSON") from exc


def sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _read_json(path: Path, label: str) -> Any:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise VerificationPipelineError("missing " + label + ": " + str(path)) from exc
    reparse = bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
    if stat.S_ISLNK(metadata.st_mode) or reparse or not stat.S_ISREG(metadata.st_mode):
        raise VerificationPipelineError(label + " must be a regular non-link file")
    if metadata.st_size > MAX_JSON_BYTES:
        raise VerificationPipelineError(label + " exceeds the safe size limit")
    try:
        raw = path.read_bytes()
        if _stable_stat(path.lstat()) != _stable_stat(metadata):
            raise VerificationPipelineError(label + " changed while it was read")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except VerificationPipelineError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise VerificationPipelineError("cannot parse " + label) from exc


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(path.parent),
            prefix="." + path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        name = None
        try:
            descriptor = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            pass
    finally:
        if name:
            try:
                os.unlink(name)
            except OSError:
                pass


@dataclass(frozen=True)
class _SafePathSnapshot:
    """Stable identity for one project-relative regular file or missing route."""

    parent_identity: Optional[tuple[int, int]]
    file_identity: Optional[tuple[int, int, int, int, int, int]]
    sha256: Optional[str]
    parent_route: tuple[_CreatedDirectory, ...] = ()
    missing_parent: Optional[str] = None


@dataclass(frozen=True)
class _CreatedDirectory:
    relative: str
    identity: tuple[int, int]


@dataclass
class _StagedProjection:
    relative: str
    parent_fd: int
    parent_identity: tuple[int, int]
    target_name: str
    temp_name: str
    temp_snapshot: _SafePathSnapshot
    expected_target: _SafePathSnapshot
    data: bytes
    created_directories: tuple[_CreatedDirectory, ...]


def _require_safe_configure_platform() -> None:
    """Fail closed where Python cannot provide no-follow directory-relative IO."""

    supports_dir_fd = getattr(os, "supports_dir_fd", ())
    required = (
        os.name == "posix",
        fcntl is not None,
        hasattr(os, "O_DIRECTORY"),
        hasattr(os, "O_NOFOLLOW"),
        os.open in supports_dir_fd,
        os.mkdir in supports_dir_fd,
        os.stat in supports_dir_fd,
        os.unlink in supports_dir_fd,
        os.rmdir in supports_dir_fd,
    )
    if not all(required):
        raise VerificationPipelineError(
            "configure safe batch writes are unavailable on this platform; "
            "use read-only expected reports and configure from a POSIX host"
        )


def _directory_identity(metadata: os.stat_result) -> tuple[int, int]:
    if not stat.S_ISDIR(metadata.st_mode):
        raise VerificationPipelineError("configuration path parent is not a directory")
    return (metadata.st_dev, metadata.st_ino)


def _safe_relative_parts(relative: str, label: str) -> tuple[str, ...]:
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise VerificationPipelineError(label + " must be a canonical project-relative path")
    return path.parts


def _open_root_fd(project_root: Path) -> int:
    _require_safe_configure_platform()
    descriptor: Optional[int] = None
    try:
        before = project_root.lstat()
        descriptor = os.open(
            str(project_root),
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        after = os.fstat(descriptor)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise VerificationPipelineError(
            "projectRoot cannot be opened for safe configuration"
        ) from exc
    assert descriptor is not None
    if (
        stat.S_ISLNK(before.st_mode)
        or _directory_identity(before) != _directory_identity(after)
    ):
        os.close(descriptor)
        raise VerificationPipelineError("projectRoot changed before configuration")
    return descriptor


def _assert_root_route(project_root: Path, root_fd: int) -> None:
    try:
        current = os.open(
            str(project_root),
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
    except OSError as exc:
        raise VerificationPipelineError(
            "projectRoot route changed during configuration"
        ) from exc
    try:
        if _directory_identity(os.fstat(current)) != _directory_identity(
            os.fstat(root_fd)
        ):
            raise VerificationPipelineError(
                "projectRoot route changed during configuration"
            )
    finally:
        os.close(current)


@contextmanager
def _locked_project_root(project_root: Path):
    root_fd = _open_root_fd(project_root)
    locked = False
    try:
        assert fcntl is not None
        try:
            fcntl.flock(root_fd, fcntl.LOCK_EX)
        except OSError as exc:
            raise VerificationPipelineError(
                "configure project-root locking is unavailable on this host"
            ) from exc
        locked = True
        _assert_root_route(project_root, root_fd)
        yield root_fd
    finally:
        try:
            if locked and fcntl is not None:
                try:
                    fcntl.flock(root_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            os.close(root_fd)


def _open_parent_from_root(
    root_fd: int,
    relative: str,
    label: str,
    *,
    create: bool,
) -> tuple[int, str, tuple[_CreatedDirectory, ...]]:
    parts = _safe_relative_parts(relative, label)
    try:
        current = os.dup(root_fd)
    except OSError as exc:
        raise VerificationPipelineError(
            label + " parent cannot be opened safely"
        ) from exc
    created: list[_CreatedDirectory] = []
    traversed: list[str] = []
    try:
        for part in parts[:-1]:
            made_directory = False
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current,
                )
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o755, dir_fd=current)
                except FileExistsError as exc:
                    raise VerificationPipelineError(
                        label + " parent changed during configuration"
                    ) from exc
                except OSError as exc:
                    raise VerificationPipelineError(
                        label + " parent could not be created safely"
                    ) from exc
                made_directory = True
                try:
                    child = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=current,
                    )
                except OSError as exc:
                    raise VerificationPipelineError(
                        label + " parent changed during configuration"
                    ) from exc
            except OSError as exc:
                raise VerificationPipelineError(
                    label + " parent is not a stable non-link directory"
                ) from exc
            identity = _directory_identity(os.fstat(child))
            traversed.append(part)
            if made_directory:
                created.append(
                    _CreatedDirectory("/".join(traversed), identity)
                )
            os.close(current)
            current = child
        return current, parts[-1], tuple(created)
    except Exception:
        os.close(current)
        _cleanup_created_directories(root_fd, created)
        raise


def _cleanup_created_directories(
    root_fd: int,
    created: Iterable[_CreatedDirectory],
) -> None:
    """Remove only empty directories still bound to this batch's identities."""

    unique = {item.relative: item for item in created}
    for item in sorted(
        unique.values(),
        key=lambda value: len(PurePosixPath(value.relative).parts),
        reverse=True,
    ):
        try:
            parent_fd, target_name, _ = _open_parent_from_root(
                root_fd,
                item.relative,
                "configuration temporary parent",
                create=False,
            )
        except (FileNotFoundError, VerificationPipelineError):
            continue
        try:
            try:
                metadata = os.stat(
                    target_name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except OSError:
                continue
            try:
                if _directory_identity(metadata) == item.identity:
                    os.rmdir(target_name, dir_fd=parent_fd)
            except OSError:
                pass
        finally:
            os.close(parent_fd)


def _snapshot_parent_file(
    parent_fd: int,
    target_name: str,
    label: str,
) -> _SafePathSnapshot:
    parent_identity = _directory_identity(os.fstat(parent_fd))
    try:
        metadata = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return _SafePathSnapshot(parent_identity, None, None)
    except OSError as exc:
        raise VerificationPipelineError(label + " cannot be inspected") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise VerificationPipelineError(label + " must be a regular non-link file")
    try:
        descriptor = os.open(
            target_name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise VerificationPipelineError(label + " cannot be opened safely") from exc
    try:
        opened = os.fstat(descriptor)
        if _stable_stat(opened) != _stable_stat(metadata):
            raise VerificationPipelineError(label + " changed while it was opened")
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_STATIC_OUTPUT_BYTES:
                raise VerificationPipelineError(label + " exceeds the safe size limit")
            digest.update(chunk)
        final = os.fstat(descriptor)
        if _stable_stat(final) != _stable_stat(opened):
            raise VerificationPipelineError(label + " changed while it was read")
        try:
            routed = os.stat(
                target_name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise VerificationPipelineError(
                label + " changed while it was read"
            ) from exc
        if _stable_stat(routed) != _stable_stat(final):
            raise VerificationPipelineError(label + " changed while it was read")
        return _SafePathSnapshot(
            parent_identity,
            _stable_stat(final),
            "sha256:" + digest.hexdigest(),
        )
    finally:
        os.close(descriptor)


def _snapshot_relative(
    root_fd: int,
    relative: str,
    label: str,
) -> _SafePathSnapshot:
    parts = _safe_relative_parts(relative, label)
    try:
        parent_fd = os.dup(root_fd)
    except OSError as exc:
        raise VerificationPipelineError(label + " cannot be inspected safely") from exc
    route: list[_CreatedDirectory] = []
    traversed: list[str] = []
    try:
        for part in parts[:-1]:
            traversed.append(part)
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                return _SafePathSnapshot(
                    None,
                    None,
                    None,
                    tuple(route),
                    "/".join(traversed),
                )
            except OSError as exc:
                raise VerificationPipelineError(
                    label + " parent is not a stable non-link directory"
                ) from exc
            identity = _directory_identity(os.fstat(child))
            route.append(_CreatedDirectory("/".join(traversed), identity))
            os.close(parent_fd)
            parent_fd = child
        observed = _snapshot_parent_file(parent_fd, parts[-1], label)
        return _SafePathSnapshot(
            observed.parent_identity,
            observed.file_identity,
            observed.sha256,
            tuple(route),
            None,
        )
    finally:
        os.close(parent_fd)


def _same_parent_file(
    left: _SafePathSnapshot,
    right: _SafePathSnapshot,
) -> bool:
    return (
        left.parent_identity == right.parent_identity
        and left.file_identity == right.file_identity
        and left.sha256 == right.sha256
    )


def _assert_distinct_frozen_paths(
    root_fd: int,
    paths: dict[str, str],
    snapshots: dict[str, _SafePathSnapshot],
) -> None:
    """Bind inputs/targets to distinct portable names, inodes, and dir slots."""

    root_identity = _directory_identity(os.fstat(root_fd))
    portable: dict[tuple[str, ...], str] = {}
    physical: dict[tuple[int, int], str] = {}
    slots: dict[tuple[tuple[int, int], tuple[str, ...]], str] = {}
    for label, relative in paths.items():
        path_key = _portable_path_key(relative)
        previous = portable.get(path_key)
        if previous is not None:
            raise VerificationPipelineError(
                label + " aliases " + previous + " in the frozen write set"
            )
        portable[path_key] = label
        snapshot = snapshots[label]
        if snapshot.file_identity is not None:
            identity = (snapshot.file_identity[0], snapshot.file_identity[1])
            previous = physical.get(identity)
            if previous is not None:
                raise VerificationPipelineError(
                    label + " physically aliases " + previous
                )
            physical[identity] = label
        if snapshot.parent_identity is not None:
            parent_identity = snapshot.parent_identity
            suffix = path_key[-1:]
        else:
            if snapshot.parent_route:
                parent_identity = snapshot.parent_route[-1].identity
                prefix_length = len(
                    PurePosixPath(snapshot.parent_route[-1].relative).parts
                )
            else:
                parent_identity = root_identity
                prefix_length = 0
            suffix = path_key[prefix_length:]
        slot = (parent_identity, suffix)
        previous = slots.get(slot)
        if previous is not None:
            raise VerificationPipelineError(
                label + " shares a filesystem-equivalent route with " + previous
            )
        slots[slot] = label


def _assert_frozen_parent_prefix(
    root_fd: int,
    relative: str,
    expected: _SafePathSnapshot,
    created: Sequence[_CreatedDirectory],
) -> None:
    for item in expected.parent_route:
        try:
            descriptor, _, _ = _open_parent_from_root(
                root_fd,
                item.relative + "/.route-check",
                "configuration output parent",
                create=False,
            )
        except FileNotFoundError as exc:
            raise VerificationPipelineError(
                "configuration output parent changed during configuration"
            ) from exc
        try:
            if _directory_identity(os.fstat(descriptor)) != item.identity:
                raise VerificationPipelineError(
                    "configuration output parent changed during configuration"
                )
        finally:
            os.close(descriptor)
    if expected.missing_parent is not None:
        parent_parts = _safe_relative_parts(relative, "configuration output")[:-1]
        prefixes = ["/".join(parent_parts[:index]) for index in range(1, len(parent_parts) + 1)]
        try:
            missing_index = prefixes.index(expected.missing_parent)
        except ValueError as exc:
            raise VerificationPipelineError(
                "configuration output parent snapshot is inconsistent"
            ) from exc
        created_by_path: dict[str, list[_CreatedDirectory]] = {}
        for item in created:
            created_by_path.setdefault(item.relative, []).append(item)
        for required in prefixes[missing_index:]:
            matches = created_by_path.get(required, [])
            if len(matches) != 1:
                raise VerificationPipelineError(
                    "configuration output parent changed during configuration"
                )
            try:
                descriptor, _, _ = _open_parent_from_root(
                    root_fd,
                    required + "/.route-check",
                    "configuration output parent",
                    create=False,
                )
            except FileNotFoundError as exc:
                raise VerificationPipelineError(
                    "configuration output parent changed during configuration"
                ) from exc
            try:
                if _directory_identity(os.fstat(descriptor)) != matches[0].identity:
                    raise VerificationPipelineError(
                        "configuration output parent changed during configuration"
                    )
            finally:
                os.close(descriptor)


def _snapshot_paths(
    project_root: Path,
    paths: dict[str, str],
) -> dict[str, _SafePathSnapshot]:
    with _locked_project_root(project_root) as root_fd:
        snapshots = {
            key: _snapshot_relative(root_fd, relative, key)
            for key, relative in paths.items()
        }
        _assert_distinct_frozen_paths(root_fd, paths, snapshots)
        return snapshots


def _assert_snapshots(
    root_fd: int,
    paths: dict[str, str],
    expected: dict[str, _SafePathSnapshot],
) -> None:
    for key, relative in paths.items():
        if _snapshot_relative(root_fd, relative, key) != expected[key]:
            raise VerificationPipelineError(key + " changed during configuration")


def _assert_parent_route(
    root_fd: int,
    relative: str,
    parent_fd: int,
    expected_identity: tuple[int, int],
) -> None:
    try:
        current, _, _ = _open_parent_from_root(
            root_fd,
            relative,
            "configuration output",
            create=False,
        )
    except FileNotFoundError as exc:
        raise VerificationPipelineError(
            "configuration output parent changed during configuration"
        ) from exc
    try:
        if (
            _directory_identity(os.fstat(parent_fd)) != expected_identity
            or _directory_identity(os.fstat(current)) != expected_identity
        ):
            raise VerificationPipelineError(
                "configuration output parent changed during configuration"
            )
    finally:
        os.close(current)


def _stage_projection(
    root_fd: int,
    relative: str,
    data: bytes,
    expected_target: _SafePathSnapshot,
    known_created_directories: Sequence[_CreatedDirectory] = (),
) -> _StagedProjection:
    if len(data) > MAX_STATIC_OUTPUT_BYTES:
        raise VerificationPipelineError("configuration output exceeds the safe size limit")
    parent_fd, target_name, created_directories = _open_parent_from_root(
        root_fd,
        relative,
        "configuration output",
        create=True,
    )
    temp_name: Optional[str] = None
    descriptor: Optional[int] = None
    try:
        _assert_frozen_parent_prefix(
            root_fd,
            relative,
            expected_target,
            (*known_created_directories, *created_directories),
        )
        parent_identity = _directory_identity(os.fstat(parent_fd))
        current_target = _snapshot_parent_file(
            parent_fd,
            target_name,
            "configuration output " + relative,
        )
        if expected_target.parent_identity is not None:
            if not _same_parent_file(current_target, expected_target):
                raise VerificationPipelineError(
                    "configuration output changed during configuration: " + relative
                )
        elif current_target.file_identity is not None:
            raise VerificationPipelineError(
                "configuration output changed during configuration: " + relative
            )
        temp_name = "." + target_name + "." + os.urandom(12).hex() + ".tmp"
        descriptor = os.open(
            temp_name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise VerificationPipelineError("configuration output write stalled")
            view = view[written:]
        mode = (
            stat.S_IMODE(expected_target.file_identity[2])
            if expected_target.file_identity is not None
            else 0o644
        )
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        temp_metadata = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        observed = bytearray()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            observed.extend(chunk)
        if bytes(observed) != data or _stable_stat(os.fstat(descriptor)) != _stable_stat(
            temp_metadata
        ):
            raise VerificationPipelineError(
                "configuration temporary output failed verification"
            )
        temp_snapshot = _SafePathSnapshot(
            parent_identity,
            _stable_stat(temp_metadata),
            "sha256:" + hashlib.sha256(data).hexdigest(),
        )
        return _StagedProjection(
            relative=relative,
            parent_fd=parent_fd,
            parent_identity=parent_identity,
            target_name=target_name,
            temp_name=temp_name,
            temp_snapshot=temp_snapshot,
            expected_target=current_target,
            data=data,
            created_directories=created_directories,
        )
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        if temp_name is not None:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)
        _cleanup_created_directories(root_fd, created_directories)
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _discard_staged(
    root_fd: int,
    staged: Sequence[_StagedProjection],
) -> None:
    created: list[_CreatedDirectory] = []
    for item in staged:
        created.extend(item.created_directories)
        if item.temp_name:
            try:
                os.unlink(item.temp_name, dir_fd=item.parent_fd)
            except OSError:
                pass
        try:
            os.close(item.parent_fd)
        except OSError:
            pass
    _cleanup_created_directories(root_fd, created)


def _commit_staged_projection(root_fd: int, item: _StagedProjection) -> None:
    _assert_parent_route(
        root_fd,
        item.relative,
        item.parent_fd,
        item.parent_identity,
    )
    if (
        _snapshot_parent_file(
            item.parent_fd,
            item.target_name,
            "configuration output " + item.relative,
        )
        != item.expected_target
    ):
        raise VerificationPipelineError(
            "configuration output changed during configuration: " + item.relative
        )
    if (
        _snapshot_parent_file(
            item.parent_fd,
            item.temp_name,
            "configuration temporary output",
        )
        != item.temp_snapshot
    ):
        raise VerificationPipelineError("configuration temporary output changed")
    try:
        os.replace(
            item.temp_name,
            item.target_name,
            src_dir_fd=item.parent_fd,
            dst_dir_fd=item.parent_fd,
        )
    except OSError as exc:
        raise VerificationPipelineError(
            "configuration output could not be committed: " + item.relative
        ) from exc
    item.temp_name = ""
    os.fsync(item.parent_fd)
    final = _snapshot_parent_file(
        item.parent_fd,
        item.target_name,
        "configuration output " + item.relative,
    )
    if final.sha256 != "sha256:" + hashlib.sha256(item.data).hexdigest():
        raise VerificationPipelineError(
            "configuration output verification failed: " + item.relative
        )
    _assert_parent_route(
        root_fd,
        item.relative,
        item.parent_fd,
        item.parent_identity,
    )


def write_json(path: Path, value: Any) -> None:
    _atomic_write(path, canonical_bytes(value) + b"\n")


def _text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character in value for character in "\x00\r\n")
    ):
        raise VerificationPipelineError(label + " must be a non-empty single-line string")
    return value


def _exact_fields(
    value: Any,
    label: str,
    required: set[str],
    optional: set[str] = frozenset(),
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VerificationPipelineError(label + " must be an object")
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing:
        raise VerificationPipelineError(label + " missing: " + ", ".join(missing))
    if unknown:
        raise VerificationPipelineError(label + " has unknown fields: " + ", ".join(unknown))
    return value


def _path(value: Any, label: str, *, allow_dot: bool = False) -> str:
    text = _text(value, label)
    if text == ".":
        if allow_dot:
            return text
        raise VerificationPipelineError(label + " cannot name projectRoot")
    if (
        "\\" in text
        or any(ord(character) < 32 for character in text)
        or PurePosixPath(text).is_absolute()
        or re.match(r"^[A-Za-z]:", text)
        or text.startswith("//")
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        raise VerificationPipelineError(
            label + " must be a canonical POSIX project-relative path"
        )
    return text


def _project_root_route(value: Any, label: str = "projectRoot") -> str:
    text = _text(value, label)
    if re.fullmatch(r"(?:\.|\.\.(?:/\.\.)*)", text) is None:
        raise VerificationPipelineError(
            label + " must be the canonical relative route to projectRoot"
        )
    return text


def _pattern(value: Any, label: str) -> str:
    text = _text(value, label)
    suffix = text.endswith("/**")
    base = text[:-3] if suffix else text
    normalized = _path(base, label)
    if any(token in normalized for token in ("*", "?", "[", "]")):
        raise VerificationPipelineError(label + " supports only exact paths or /** prefixes")
    return normalized + ("/**" if suffix else "")


def _output_path(value: Any, label: str) -> str:
    text = _path(value, label)
    if any(
        PORTABLE_OUTPUT_SEGMENT_RE.fullmatch(part) is None
        for part in text.split("/")
    ):
        raise VerificationPipelineError(
            label + " must use portable shell-safe path segments"
        )
    return text


def _matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        base = pattern[:-3].rstrip("/")
        return path == base or path.startswith(base + "/")
    return path == pattern


def _covered(path: str, excludes: Sequence[str]) -> bool:
    return any(
        path == (item[:-3].rstrip("/") if item.endswith("/**") else item.rstrip("/"))
        or path.startswith(
            (item[:-3].rstrip("/") if item.endswith("/**") else item.rstrip("/"))
            + "/"
        )
        for item in excludes
    )


def _resolve_inside(root: Path, relative: str, label: str, *, must_exist: bool = False) -> Path:
    candidate = root / relative
    if _path_has_link_component(candidate, root):
        raise VerificationPipelineError(label + " uses a symlink/reparse path")
    try:
        resolved = Path(os.path.realpath(str(candidate)))
        root_resolved = Path(os.path.realpath(str(root)))
        resolved.relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise VerificationPipelineError(label + " escapes projectRoot") from exc
    if must_exist and not resolved.exists():
        raise VerificationPipelineError(label + " does not exist")
    return resolved


def _kernel_validator():
    kernel_scripts = (
        Path(__file__).resolve().parent.parent
        / "skills"
        / "run-closed-loop-verification"
        / "scripts"
    )
    if str(kernel_scripts) not in sys.path:
        sys.path.insert(0, str(kernel_scripts))
    try:
        from adapter_paths import validate_adapter
    except Exception as exc:
        raise VerificationPipelineError("closed-loop adapter validator is unavailable") from exc
    return validate_adapter


def verification_catalog_fingerprint(adapter_data: dict[str, Any]) -> str:
    """Fingerprint a complete provider-neutral adapter catalog preimage."""

    if not isinstance(adapter_data, dict):
        raise VerificationPipelineError("adapter catalog must be an object")
    value = copy.deepcopy(adapter_data)
    value.pop("verification", None)
    return sha256_value(value)


@dataclass(frozen=True)
class VerificationProfile:
    path: Path
    project_root: Path
    adapter_path: Path
    adapter_data: dict[str, Any]
    adapter_catalog_fingerprint: str
    view: dict[str, Any]
    sha256: str


def _profile_digest_view(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result.pop("contentDigest", None)
    return result


def _portable_path_key(value: str) -> tuple[str, ...]:
    """Conservative name identity across case-folding/normalizing filesystems."""

    return tuple(
        unicodedata.normalize("NFC", part).casefold()
        for part in PurePosixPath(value).parts
    )


def _portable_path_is_nested(child: str, parent: str) -> bool:
    """Return whether *child* is below *parent* on portable filesystems."""

    child_parts = _portable_path_key(child)
    parent_parts = _portable_path_key(parent)
    return (
        len(child_parts) > len(parent_parts)
        and child_parts[: len(parent_parts)] == parent_parts
    )


def _assert_distinct_configuration_routes(
    project_root: Path,
    routes: dict[str, str],
) -> None:
    """Reject portable-name aliases and existing hard-link/inode aliases."""

    portable: dict[tuple[str, ...], str] = {}
    physical: dict[tuple[int, int], str] = {}
    for label, relative in routes.items():
        name_key = _portable_path_key(relative)
        previous = portable.get(name_key)
        if previous is not None:
            raise VerificationPipelineError(
                label + " aliases " + previous + " on a case-folding or "
                "Unicode-normalizing filesystem"
            )
        portable[name_key] = label
        path = project_root / relative
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise VerificationPipelineError(
                label + " cannot be inspected for physical aliases"
            ) from exc
        reparse = bool(
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
        if stat.S_ISLNK(metadata.st_mode) or reparse:
            raise VerificationPipelineError(label + " uses a symlink/reparse path")
        identity = (metadata.st_dev, metadata.st_ino)
        previous = physical.get(identity)
        if previous is not None:
            raise VerificationPipelineError(
                label + " physically aliases " + previous
            )
        physical[identity] = label


def profile_sha256(profile: VerificationProfile | dict[str, Any]) -> str:
    if isinstance(profile, VerificationProfile):
        return profile.sha256
    return sha256_value(_profile_digest_view(profile))


def profile_view(profile: VerificationProfile) -> dict[str, Any]:
    return copy.deepcopy(profile.view)


def profile_catalog_fingerprint(profile: VerificationProfile) -> str:
    return profile.adapter_catalog_fingerprint


def _case_ids(adapter_data: dict[str, Any]) -> list[str]:
    cases = adapter_data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise VerificationPipelineError("adapter cases are unavailable")
    result: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            raise VerificationPipelineError("adapter contains an invalid case")
        case_id = _text(case.get("id"), "adapter case ID")
        if ID_RE.fullmatch(case_id) is None:
            raise VerificationPipelineError(
                "profile adapter case IDs must be stable identifiers"
            )
        result.append(case_id)
    if len(result) != len(set(result)):
        raise VerificationPipelineError("adapter contains duplicate case IDs")
    return result


def _case_dependency_closure(adapter_data: dict[str, Any], case_ids: Iterable[str]) -> list[str]:
    by_id = {case["id"]: case for case in adapter_data["cases"]}
    selected = set(case_ids)
    pending = list(selected)
    while pending:
        case_id = pending.pop()
        case = by_id.get(case_id)
        if case is None:
            raise VerificationPipelineError("profile references unknown case: " + case_id)
        for dependency in case.get("dependsOn", []):
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    order = _case_ids(adapter_data)
    return [case_id for case_id in order if case_id in selected]


def _canonical_adapter_input_path(
    project_root: Path,
    value: Any,
    label: str,
) -> str:
    """Return a validated adapter input as a canonical project-relative path."""

    text = _text(value, label)
    candidate = Path(text) if Path(text).is_absolute() else project_root / text
    try:
        resolved_root = Path(os.path.realpath(str(project_root)))
        resolved = Path(os.path.realpath(str(candidate)))
        relative = resolved.relative_to(resolved_root).as_posix()
    except (OSError, ValueError) as exc:
        raise VerificationPipelineError(label + " escapes projectRoot") from exc
    if relative == ".":
        raise VerificationPipelineError(label + " cannot name projectRoot")
    return relative


def _adapter_explicit_input_paths(
    adapter: Any,
    project_root: Path,
) -> list[tuple[str, str]]:
    """Collect explicit adapter inputs that generated outputs must not replace."""

    protected: list[tuple[str, str]] = []
    source = adapter.data["source"]
    provider = source["provider"]
    if provider == "files":
        for index, value in enumerate(source["files"]):
            protected.append(
                (
                    "source.files[" + str(index) + "]",
                    _canonical_adapter_input_path(
                        project_root,
                        value,
                        "source.files[" + str(index) + "]",
                    ),
                )
            )
    elif provider == "manifest":
        manifest_relative = _canonical_adapter_input_path(
            project_root,
            source["manifest"],
            "source.manifest",
        )
        protected.append(("source.manifest", manifest_relative))
        manifest_data = _read_json(
            project_root / manifest_relative,
            "source manifest",
        )
        manifest_files = (
            manifest_data
            if isinstance(manifest_data, list)
            else manifest_data.get("files")
            if isinstance(manifest_data, dict)
            else None
        )
        if not isinstance(manifest_files, list) or any(
            not isinstance(item, str) for item in manifest_files
        ):
            # The kernel validator normally rejects this first.  Keep this
            # collection independently fail-closed if its contract changes.
            raise VerificationPipelineError(
                "source.manifest must contain a string array or {files: []}"
            )
        for index, value in enumerate(manifest_files):
            protected.append(
                (
                    "source.manifest files[" + str(index) + "]",
                    _canonical_adapter_input_path(
                        project_root,
                        value,
                        "source.manifest files[" + str(index) + "]",
                    ),
                )
            )

    traceability = adapter.data.get("traceability")
    if isinstance(traceability, dict):
        for key in ("goalContract", "invariants", "reviewFindings"):
            reference = traceability.get(key)
            if isinstance(reference, dict) and "path" in reference:
                label = "traceability." + key + ".path"
                protected.append(
                    (
                        label,
                        _canonical_adapter_input_path(
                            project_root,
                            reference["path"],
                            label,
                        ),
                    )
                )

    for index, case in enumerate(adapter.data["cases"]):
        fixture = case.get("fixture")
        if isinstance(fixture, str):
            label = "cases[" + str(index) + "].fixture"
            protected.append(
                (
                    label,
                    _canonical_adapter_input_path(
                        project_root,
                        fixture,
                        label,
                    ),
                )
            )
    return protected


def _validate_profile_data(data: Any, project_root: Path, profile_path: Path) -> tuple[dict[str, Any], Path, Any]:
    data = _exact_fields(
        data,
        "verification profile",
        {
            "schemaId",
            "schemaVersion",
            "projectId",
            "projectRoot",
            "adapter",
            "runtime",
            "changeDetection",
            "packages",
            "guards",
            "tiers",
            "ci",
            "outputs",
        },
        {"contentDigest"},
    )
    if (
        data["schemaId"] != PROFILE_SCHEMA_ID
        or type(data["schemaVersion"]) is not int
        or data["schemaVersion"] != SCHEMA_VERSION
    ):
        raise VerificationPipelineError("verification profile version is unsupported")
    project_id = _text(data["projectId"], "projectId")
    if ID_RE.fullmatch(project_id) is None:
        raise VerificationPipelineError("projectId must be a stable identifier")
    declared_root = _project_root_route(data["projectRoot"])
    candidate_root = profile_path.parent / declared_root
    if os.path.normcase(os.path.realpath(str(candidate_root))) != os.path.normcase(
        os.path.realpath(str(project_root))
    ):
        raise VerificationPipelineError("verification profile projectRoot does not match the supplied project root")
    canonical_root = os.path.relpath(project_root, profile_path.parent).replace(
        os.sep, "/"
    )
    if declared_root != canonical_root:
        raise VerificationPipelineError("verification profile projectRoot is not canonical")

    adapter_ref = _exact_fields(data["adapter"], "adapter reference", {"path"})
    adapter_relative = _path(adapter_ref["path"], "adapter.path")
    adapter_path = _resolve_inside(project_root, adapter_relative, "adapter.path", must_exist=True)
    try:
        adapter = _kernel_validator()(adapter_path)
    except Exception as exc:
        raise VerificationPipelineError("referenced closed-loop adapter is invalid: " + str(exc)) from exc
    adapter_data = copy.deepcopy(adapter.data)
    if adapter_data.get("verification") is not None:
        raise VerificationPipelineError("profile must reference a complete base adapter, not a derived adapter")
    if adapter_data.get("projectId") != project_id:
        raise VerificationPipelineError("profile projectId does not match its adapter")
    case_ids = _case_ids(adapter_data)
    case_by_id = {case["id"]: case for case in adapter_data["cases"]}

    runtime = _exact_fields(
        data["runtime"],
        "runtime",
        {"pluginRoot", "pythonExecutables"},
    )
    plugin_root: Optional[str]
    runtime_entry_relatives: list[str] = []
    if runtime["pluginRoot"] is None:
        plugin_root = None
    else:
        plugin_root = _path(
            runtime["pluginRoot"], "runtime.pluginRoot", allow_dot=True
        )
        runtime_root = _resolve_inside(
            project_root,
            plugin_root,
            "runtime.pluginRoot",
            must_exist=True,
        )
        if not runtime_root.is_dir():
            raise VerificationPipelineError("runtime.pluginRoot must be a directory")
        for relative in (
            "scripts/project_verification.py",
            "skills/run-closed-loop-verification/scripts/campaign.py",
        ):
            candidate = _resolve_inside(
                runtime_root,
                relative,
                "runtime entry",
                must_exist=True,
            )
            if not candidate.is_file():
                raise VerificationPipelineError("runtime entry must be a regular file")
            runtime_entry_relatives.append(
                candidate.relative_to(project_root).as_posix()
            )
    executables = _exact_fields(
        runtime["pythonExecutables"],
        "runtime.pythonExecutables",
        {"posix", "windows"},
    )
    python_executables: dict[str, str] = {}
    for key in ("posix", "windows"):
        executable = _text(
            executables[key], "runtime.pythonExecutables." + key
        )
        if EXECUTABLE_RE.fullmatch(executable) is None:
            raise VerificationPipelineError(
                "runtime Python executable must be a PATH-resolved command name"
            )
        python_executables[key] = executable

    change = _exact_fields(
        data["changeDetection"],
        "changeDetection",
        {"provider", "baseRef", "sources", "highImpactPaths", "unknownPath"},
    )
    if change["provider"] != "git":
        raise VerificationPipelineError("changeDetection.provider must be git")
    if change["baseRef"] is not None:
        _text(change["baseRef"], "changeDetection.baseRef")
    if change["sources"] != CHANGE_SOURCES:
        raise VerificationPipelineError("changeDetection.sources must list committed, staged, unstaged, untracked")
    if change["unknownPath"] != "full":
        raise VerificationPipelineError("changeDetection.unknownPath must be full")
    if not isinstance(change["highImpactPaths"], list):
        raise VerificationPipelineError("highImpactPaths must be an array")
    high_impact = [_pattern(item, "highImpactPaths entry") for item in change["highImpactPaths"]]
    if len(high_impact) != len(set(high_impact)):
        raise VerificationPipelineError("highImpactPaths contains duplicates")

    packages = data["packages"]
    if not isinstance(packages, list):
        raise VerificationPipelineError("packages must be an array")
    package_ids: set[str] = set()
    normalized_packages: list[dict[str, Any]] = []
    all_quick_candidates: set[str] = set()
    for index, raw in enumerate(packages):
        item = _exact_fields(
            raw,
            "package " + str(index),
            {"id", "paths", "dependsOn", "quickCaseIds", "typecheckCaseIds"},
        )
        package_id = _text(item["id"], "package.id")
        if PACKAGE_ID_RE.fullmatch(package_id) is None or package_id in package_ids:
            raise VerificationPipelineError("package IDs must be unique lowercase kebab-case")
        package_ids.add(package_id)
        paths = item["paths"]
        dependencies = item["dependsOn"]
        quick_ids = item["quickCaseIds"]
        typecheck_ids = item["typecheckCaseIds"]
        if not isinstance(paths, list) or not paths:
            raise VerificationPipelineError("package paths must be a non-empty array")
        normalized_paths = [_pattern(path, "package path") for path in paths]
        if len(normalized_paths) != len(set(normalized_paths)):
            raise VerificationPipelineError("package paths must be unique")
        for label, values in (("dependsOn", dependencies), ("quickCaseIds", quick_ids), ("typecheckCaseIds", typecheck_ids)):
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values) or len(values) != len(set(values)):
                raise VerificationPipelineError("package " + label + " must be a unique string array")
        unknown_cases = (set(quick_ids) | set(typecheck_ids)) - set(case_ids)
        if unknown_cases:
            raise VerificationPipelineError("package references unknown case: " + sorted(unknown_cases)[0])
        all_quick_candidates.update(quick_ids)
        all_quick_candidates.update(typecheck_ids)
        normalized_packages.append(
            {
                "id": package_id,
                "paths": normalized_paths,
                "dependsOn": list(dependencies),
                "quickCaseIds": list(quick_ids),
                "typecheckCaseIds": list(typecheck_ids),
            }
        )
    for package in normalized_packages:
        unknown = set(package["dependsOn"]) - package_ids
        if unknown:
            raise VerificationPipelineError("package depends on unknown package: " + sorted(unknown)[0])
    visiting: set[str] = set()
    visited: set[str] = set()
    package_by_id = {item["id"]: item for item in normalized_packages}

    def visit(package_id: str) -> None:
        if package_id in visiting:
            raise VerificationPipelineError("package dependency graph contains a cycle")
        if package_id in visited:
            return
        visiting.add(package_id)
        for dependency in package_by_id[package_id]["dependsOn"]:
            visit(dependency)
        visiting.remove(package_id)
        visited.add(package_id)

    for package_id in sorted(package_ids):
        visit(package_id)

    guards = data["guards"]
    if not isinstance(guards, list):
        raise VerificationPipelineError("guards must be an array")
    guard_ids: set[str] = set()
    normalized_guards: list[dict[str, Any]] = []
    for index, raw in enumerate(guards):
        item = _exact_fields(raw, "guard " + str(index), {"id", "paths", "caseIds", "alwaysRun"})
        guard_id = _text(item["id"], "guard.id")
        if ID_RE.fullmatch(guard_id) is None or guard_id in guard_ids:
            raise VerificationPipelineError("guard IDs must be unique stable IDs")
        guard_ids.add(guard_id)
        if not isinstance(item["alwaysRun"], bool):
            raise VerificationPipelineError("guard.alwaysRun must be a boolean")
        if not isinstance(item["paths"], list):
            raise VerificationPipelineError("guard.paths must be an array")
        paths = [_pattern(path, "guard path") for path in item["paths"]]
        if len(paths) != len(set(paths)):
            raise VerificationPipelineError("guard.paths must be unique")
        case_refs = _unique_identifiers(
            item["caseIds"], "guard.caseIds", nonempty=True
        )
        if any(case not in case_ids for case in case_refs):
            raise VerificationPipelineError("guard.caseIds must be non-empty unique known case IDs")
        all_quick_candidates.update(case_refs)
        normalized_guards.append({"id": guard_id, "paths": paths, "caseIds": list(case_refs), "alwaysRun": item["alwaysRun"]})

    tiers = _exact_fields(data["tiers"], "tiers", {"quick", "full"})
    if tiers["quick"] != {"selection": "impact-plan"} or tiers["full"] != {"selection": "all", "ignoreSelector": True}:
        raise VerificationPipelineError("tiers must fix quick to impact-plan and full to all with ignoreSelector=true")

    ci = _exact_fields(
        data["ci"],
        "ci",
        {"platforms", "portablePlatform", "posixPlatform", "selectorPlatform", "selectorCaseIds"},
    )
    if not isinstance(ci["platforms"], list) or not ci["platforms"]:
        raise VerificationPipelineError("ci.platforms must be a non-empty array")
    normalized_platforms: list[dict[str, Any]] = []
    platform_ids: set[str] = set()
    for raw in ci["platforms"]:
        item = _exact_fields(raw, "ci platform", {"id", "required", "shards"})
        platform = _text(item["id"], "ci platform id")
        if platform not in PLATFORMS or platform in platform_ids:
            raise VerificationPipelineError("ci platform IDs must be unique supported concrete platforms")
        if not isinstance(item["required"], bool) or type(item["shards"]) is not int or not 1 <= item["shards"] <= 64:
            raise VerificationPipelineError("ci platform required/shards values are invalid")
        platform_ids.add(platform)
        normalized_platforms.append({"id": platform, "required": item["required"], "shards": item["shards"]})
    if not any(item["required"] for item in normalized_platforms):
        raise VerificationPipelineError("ci.platforms must include a required platform")
    for key in ("portablePlatform", "posixPlatform", "selectorPlatform"):
        platform = _text(ci[key], "ci." + key)
        if platform not in platform_ids:
            raise VerificationPipelineError("ci." + key + " must name a configured platform")
        ci[key] = platform
    if ci["posixPlatform"] not in {"darwin", "linux"}:
        raise VerificationPipelineError("ci.posixPlatform must be darwin or linux")
    selector_ids = _unique_identifiers(
        ci["selectorCaseIds"], "ci.selectorCaseIds", nonempty=True
    )
    if any(case not in case_ids for case in selector_ids):
        raise VerificationPipelineError("ci.selectorCaseIds must be non-empty unique known case IDs")
    all_quick_candidates.update(selector_ids)
    closure = _case_dependency_closure(adapter_data, all_quick_candidates)
    for case_id in closure:
        if not case_by_id[case_id].get("quick", False):
            raise VerificationPipelineError("quick candidate dependency is not quick-eligible: " + case_id)
    for case_id in selector_ids:
        if not case_by_id[case_id].get("required", True):
            raise VerificationPipelineError("selector self-test cases must be required")

    outputs = _exact_fields(
        data["outputs"],
        "outputs",
        {
            "profile",
            "impactPlan",
            "ciPlan",
            "localEntry",
            "workflow",
            "derivedAdapters",
            "campaigns",
            "evidenceBundles",
            "aggregation",
        },
    )
    normalized_outputs = {
        key: _output_path(value, "outputs." + key)
        for key, value in outputs.items()
    }
    profile_relative = profile_path.relative_to(project_root).as_posix()
    explicit_input_paths = _adapter_explicit_input_paths(adapter, project_root)
    configuration_routes: dict[str, str] = {}

    def add_input_route(label: str, relative: str) -> None:
        # A files/manifest inventory may deliberately include another authority
        # such as the profile itself.  Bind that file once as an input, while
        # still adding every output separately so no generated route can alias it.
        if relative not in configuration_routes.values():
            configuration_routes[label] = relative

    add_input_route("verification profile", profile_relative)
    add_input_route("base adapter", adapter_relative)
    for index, runtime_entry in enumerate(runtime_entry_relatives):
        add_input_route("runtime entry " + str(index), runtime_entry)
    for input_label, input_path in explicit_input_paths:
        add_input_route("adapter input " + input_label, input_path)
    for output_key, output_path in normalized_outputs.items():
        if output_key != "profile":
            configuration_routes["outputs." + output_key] = output_path
    if len(set(normalized_outputs.values())) != len(normalized_outputs):
        raise VerificationPipelineError("outputs paths must be unique")
    directory_keys = ("derivedAdapters", "campaigns", "evidenceBundles")
    file_keys = (
        "profile",
        "impactPlan",
        "ciPlan",
        "localEntry",
        "workflow",
        "aggregation",
    )

    def is_nested(child: str, parent: str) -> bool:
        return _portable_path_is_nested(child, parent)

    for index, left_key in enumerate(directory_keys):
        for right_key in directory_keys[index + 1 :]:
            left = normalized_outputs[left_key]
            right = normalized_outputs[right_key]
            if is_nested(left, right) or is_nested(right, left):
                raise VerificationPipelineError(
                    "dynamic output directories cannot be nested"
                )
    for file_key in file_keys:
        for directory_key in directory_keys:
            file_path = normalized_outputs[file_key]
            directory_path = normalized_outputs[directory_key]
            if is_nested(file_path, directory_path) or is_nested(
                directory_path, file_path
            ):
                raise VerificationPipelineError(
                    "output files and dynamic output directories cannot overlap"
                )
    for index, left_key in enumerate(file_keys):
        for right_key in file_keys[index + 1 :]:
            left = normalized_outputs[left_key]
            right = normalized_outputs[right_key]
            if is_nested(left, right) or is_nested(right, left):
                raise VerificationPipelineError(
                    "output files cannot be nested beneath one another"
                )
    for output_key, output_path in normalized_outputs.items():
        if output_key != "profile" and (
            is_nested(output_path, profile_relative)
            or is_nested(profile_relative, output_path)
        ):
            raise VerificationPipelineError(
                "generated outputs cannot overlap the verification profile"
            )
        if (
            adapter_relative == output_path
            or is_nested(adapter_relative, output_path)
            or is_nested(output_path, adapter_relative)
        ):
            raise VerificationPipelineError(
                "base adapter cannot overlap a declared output path"
            )
        for runtime_entry in runtime_entry_relatives:
            if (
                output_path == runtime_entry
                or is_nested(output_path, runtime_entry)
                or is_nested(runtime_entry, output_path)
            ):
                raise VerificationPipelineError(
                    "declared output paths cannot overlap verification runtime entries"
                )
    for input_label, input_path in explicit_input_paths:
        for output_key, output_path in normalized_outputs.items():
            # The profile is the persisted authority being validated, not a
            # generated target of the public runtime commands.  It may be
            # included deliberately in a files/manifest source inventory.
            if output_key == "profile":
                continue
            if (
                output_path == input_path
                or is_nested(output_path, input_path)
                or is_nested(input_path, output_path)
            ):
                raise VerificationPipelineError(
                    "outputs."
                    + output_key
                    + " cannot overlap explicit adapter input "
                    + input_label
                )
    _assert_distinct_configuration_routes(
        project_root,
        configuration_routes,
    )
    if normalized_outputs["profile"] != profile_relative:
        raise VerificationPipelineError("outputs.profile must name the current profile")
    excludes = [
        _pattern(item, "adapter source exclude")
        for item in adapter_data.get("source", {}).get("excludes", [])
    ]
    for key in (
        "impactPlan",
        "derivedAdapters",
        "campaigns",
        "evidenceBundles",
        "aggregation",
    ):
        if not _covered(normalized_outputs[key], excludes):
            raise VerificationPipelineError(
                "outputs." + key + " must be covered by adapter source.excludes"
            )

    normalized = {
        "schemaId": PROFILE_SCHEMA_ID,
        "schemaVersion": SCHEMA_VERSION,
        "projectId": project_id,
        "projectRoot": os.path.relpath(project_root, profile_path.parent).replace(os.sep, "/"),
        "adapter": {"path": adapter_relative},
        "runtime": {
            "pluginRoot": plugin_root,
            "pythonExecutables": python_executables,
        },
        "changeDetection": {
            "provider": "git",
            "baseRef": change["baseRef"],
            "sources": list(CHANGE_SOURCES),
            "highImpactPaths": high_impact,
            "unknownPath": "full",
        },
        "packages": normalized_packages,
        "guards": normalized_guards,
        "tiers": {"quick": {"selection": "impact-plan"}, "full": {"selection": "all", "ignoreSelector": True}},
        "ci": {
            "platforms": normalized_platforms,
            "portablePlatform": ci["portablePlatform"],
            "posixPlatform": ci["posixPlatform"],
            "selectorPlatform": ci["selectorPlatform"],
            "selectorCaseIds": list(selector_ids),
        },
        "outputs": normalized_outputs,
        "adapterCatalogFingerprint": adapter.catalog_fingerprint,
        "adapterCaseIds": case_ids,
    }
    digest = sha256_value(_profile_digest_view(normalized))
    supplied_digest = data.get("contentDigest")
    if supplied_digest is not None and supplied_digest != digest:
        raise VerificationPipelineError("verification profile contentDigest mismatch")
    normalized["contentDigest"] = digest
    return normalized, adapter_path, adapter


def load_profile(path: Path, project_root: Optional[Path] = None) -> VerificationProfile:
    supplied_path = path.absolute()
    if _path_has_link_component(supplied_path, Path(supplied_path.anchor)):
        raise VerificationPipelineError(
            "verification profile path uses a symlink/reparse component"
        )
    try:
        supplied_metadata = supplied_path.lstat()
    except FileNotFoundError:
        supplied_metadata = None
    except OSError as exc:
        raise VerificationPipelineError("verification profile cannot be inspected") from exc
    if supplied_metadata is not None:
        reparse = bool(
            getattr(supplied_metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
        if stat.S_ISLNK(supplied_metadata.st_mode) or reparse:
            raise VerificationPipelineError(
                "verification profile uses a symlink/reparse path"
            )
    path = Path(os.path.realpath(str(supplied_path)))
    data = _read_json(path, "verification profile")
    if project_root is None:
        if not isinstance(data, dict):
            raise VerificationPipelineError("verification profile must be an object")
        declared_root = _project_root_route(data.get("projectRoot"))
        root_candidate = path.parent / declared_root
    else:
        raw_project_root = project_root.absolute()
        if _path_has_link_component(
            raw_project_root, Path(raw_project_root.anchor)
        ):
            raise VerificationPipelineError(
                "projectRoot uses a symlink/reparse component"
            )
        root_candidate = raw_project_root
    root = Path(os.path.realpath(str(root_candidate.absolute())))
    view, adapter_path, adapter = _validate_profile_data(data, root, path)
    return VerificationProfile(
        path=path,
        project_root=root,
        adapter_path=adapter_path,
        adapter_data=copy.deepcopy(adapter.data),
        adapter_catalog_fingerprint=adapter.catalog_fingerprint,
        view=view,
        sha256=view["contentDigest"],
    )


def _run_git(root: Path, args: Sequence[str], *, allow_failure: bool = False) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerificationPipelineError("git observation could not be executed") from exc
    if len(completed.stdout) > MAX_GIT_OUTPUT or len(completed.stderr) > MAX_GIT_OUTPUT:
        raise VerificationPipelineError("git observation exceeds the safe output limit")
    if completed.returncode != 0 and not allow_failure:
        raise VerificationPipelineError("git observation failed: " + " ".join(args))
    return completed.stdout if completed.returncode == 0 else b""


def _validate_git_path(text: Any, label: str = "git path") -> str:
    if not isinstance(text, str) or not text:
        raise VerificationPipelineError(label + " must be a non-empty string")
    if (
        "\\" in text
        or any(ord(character) < 32 for character in text)
        or text.startswith("/")
        or re.match(r"^[A-Za-z]:", text)
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        raise VerificationPipelineError(label + " is not a safe canonical POSIX path")
    return text


def _decode_git_path(value: bytes) -> str:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VerificationPipelineError("git path is not valid UTF-8") from exc
    return _validate_git_path(text)


def _parse_name_status(value: bytes) -> list[dict[str, str]]:
    if not value:
        return []
    parts = value.split(b"\x00")
    if parts[-1] == b"":
        parts.pop()
    if len(parts) % 2:
        raise VerificationPipelineError("git name-status output is malformed")
    result: list[dict[str, str]] = []
    for index in range(0, len(parts), 2):
        try:
            status = parts[index].decode("ascii")
        except UnicodeDecodeError as exc:
            raise VerificationPipelineError("git change status is malformed") from exc
        path = _decode_git_path(parts[index + 1])
        if status not in {"A", "C", "D", "M", "R", "T", "U", "X", "B"}:
            raise VerificationPipelineError("git change status is unsupported: " + status)
        result.append({"status": status, "path": path})
    return result


def _path_state(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"path": relative, "kind": "missing"}
    except OSError as exc:
        raise VerificationPipelineError("changed path cannot be inspected: " + relative) from exc
    reparse = bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
    if stat.S_ISLNK(metadata.st_mode) or reparse:
        raise VerificationPipelineError("changed path uses a symlink/reparse point: " + relative)
    if stat.S_ISDIR(metadata.st_mode):
        return {"path": relative, "kind": "directory"}
    if not stat.S_ISREG(metadata.st_mode):
        raise VerificationPipelineError("changed path is not a regular file: " + relative)
    if metadata.st_size > MAX_JSON_BYTES * 64:
        raise VerificationPipelineError("changed path exceeds the planning size limit: " + relative)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise VerificationPipelineError("changed path cannot be read: " + relative) from exc
    return {
        "path": relative,
        "kind": "file",
        "size": len(content),
        "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
    }


def _source_excluded(relative: str, excludes: Sequence[str]) -> bool:
    normalized = [
        item.replace("\\", "/") if os.name == "nt" else item
        for item in excludes
    ]
    return _covered(relative, normalized)


def _git_dirty_paths(root: Path) -> list[str]:
    raw = _run_git(
        root,
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored=no",
        ],
    )
    parts = raw.split(b"\x00")
    if parts and parts[-1] == b"":
        parts.pop()
    paths: list[str] = []
    index = 0
    while index < len(parts):
        record = parts[index]
        index += 1
        if len(record) < 4 or record[2:3] != b" ":
            raise VerificationPipelineError("Git status output is malformed")
        try:
            status_code = record[:2].decode("ascii")
        except UnicodeDecodeError as exc:
            raise VerificationPipelineError("Git status output is malformed") from exc
        paths.append(_decode_git_path(record[3:]))
        if "R" in status_code or "C" in status_code:
            if index >= len(parts):
                raise VerificationPipelineError("Git rename status is malformed")
            paths.append(_decode_git_path(parts[index]))
            index += 1
    return sorted(set(paths))


def portable_git_source_identity(
    project_root: Path,
    *,
    require_clean: bool = False,
    excludes: Sequence[str] = (),
) -> dict[str, str]:
    root = Path(os.path.realpath(str(project_root)))
    try:
        top_text = _run_git(root, ["rev-parse", "--show-toplevel"]).decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise VerificationPipelineError("Git root is not valid UTF-8") from exc
    if not top_text or "\x00" in top_text or "\r" in top_text or "\n" in top_text:
        raise VerificationPipelineError("Git returned an invalid repository root")
    if os.path.normcase(os.path.realpath(top_text)) != os.path.normcase(str(root)):
        raise VerificationPipelineError("Git root must equal projectRoot")
    commit = _run_git(root, ["rev-parse", "--verify", "HEAD^{commit}"]).decode("ascii").strip()
    tree = _run_git(root, ["rev-parse", "--verify", "HEAD^{tree}"]).decode("ascii").strip()
    if OBJECT_ID_RE.fullmatch(commit) is None or OBJECT_ID_RE.fullmatch(tree) is None:
        raise VerificationPipelineError("Git commit/tree identity is invalid")
    if require_clean:
        dirty = [
            path
            for path in _git_dirty_paths(root)
            if not _source_excluded(path, excludes)
        ]
        if dirty:
            raise VerificationPipelineError(
                "portable source requires a clean Git worktree outside declared excludes: "
                + dirty[0]
            )
    listing = _run_git(root, ["ls-tree", "-r", "-z", "--full-tree", "HEAD"])
    fingerprint = sha256_value(
        {
            "provider": "git",
            "commit": commit,
            "tree": tree,
            "treeListingSha256": "sha256:" + hashlib.sha256(listing).hexdigest(),
        }
    )
    return {
        "sourceProvider": "git",
        "commit": commit,
        "tree": tree,
        "fingerprint": fingerprint,
        # Compatibility alias consumed by callers that name the portable value
        # directly as the source fingerprint.
        "sourceFingerprint": fingerprint,
    }


def _git_observation(profile: VerificationProfile, base_ref: Optional[str]) -> dict[str, Any]:
    root = profile.project_root
    excludes = [
        _pattern(item, "source exclude")
        for item in profile.adapter_data.get("source", {}).get("excludes", [])
    ]
    identity = portable_git_source_identity(root)
    selected_base = base_ref if base_ref is not None else profile.view["changeDetection"]["baseRef"]
    if selected_base is None:
        raise VerificationPipelineError("merge-base input is unavailable")
    selected_base = _text(selected_base, "base ref")
    try:
        base_commit = _run_git(
            root,
            [
                "rev-parse",
                "--verify",
                "--end-of-options",
                selected_base + "^{commit}",
            ],
        ).decode("ascii").strip()
    except (UnicodeDecodeError, VerificationPipelineError) as exc:
        raise VerificationPipelineError("merge-base input is unavailable") from exc
    if OBJECT_ID_RE.fullmatch(base_commit) is None:
        raise VerificationPipelineError("merge-base input identity is invalid")
    merge_base = _run_git(root, ["merge-base", base_commit, "HEAD"]).decode("ascii").strip()
    if OBJECT_ID_RE.fullmatch(merge_base) is None:
        raise VerificationPipelineError("merge-base identity is invalid")
    if _run_git(root, ["ls-files", "-u", "-z"]):
        raise VerificationPipelineError("Git index contains unmerged entries")
    committed_raw = _run_git(root, ["diff", "--name-status", "-z", "--no-renames", merge_base + "..HEAD"])
    staged_raw = _run_git(root, ["diff", "--cached", "--name-status", "-z", "--no-renames"])
    unstaged_raw = _run_git(root, ["diff", "--name-status", "-z", "--no-renames"])
    untracked_raw = _run_git(root, ["ls-files", "--others", "--exclude-standard", "-z"])
    changes = {
        "committed": _parse_name_status(committed_raw),
        "staged": _parse_name_status(staged_raw),
        "unstaged": _parse_name_status(unstaged_raw),
        "untracked": [
            {"status": "?", "path": _decode_git_path(item)}
            for item in untracked_raw.split(b"\x00")
            if item
        ],
    }
    for source in CHANGE_SOURCES:
        changes[source] = [
            item for item in changes[source] if not _covered(item["path"], excludes)
        ]
    changed_paths = sorted(
        {
            item["path"]
            for source in CHANGE_SOURCES
            for item in changes[source]
        }
    )
    states = [_path_state(root, path) for path in changed_paths]
    snapshot = {
        "headCommit": identity["commit"],
        "headTree": identity["tree"],
        "baseInput": selected_base,
        "mergeBaseCommit": merge_base,
        "changes": changes,
        "pathStates": states,
    }
    return {
        "identity": identity,
        "baseInput": selected_base,
        "mergeBaseCommit": merge_base,
        "changes": changes,
        "changedPaths": changed_paths,
        "changeSnapshotFingerprint": sha256_value(snapshot),
    }


def _downstream_packages(profile: VerificationProfile, direct: set[str]) -> list[str]:
    packages = {item["id"]: item for item in profile.view["packages"]}
    selected = set(direct)
    changed = True
    while changed:
        changed = False
        for package_id, package in packages.items():
            if package_id not in selected and set(package["dependsOn"]) & selected:
                selected.add(package_id)
                changed = True
    return sorted(selected)


def _impact_digest(value: dict[str, Any]) -> str:
    result = copy.deepcopy(value)
    result.pop("contentDigest", None)
    return sha256_value(result)


def _hash_value(value: Any, label: str, *, nullable: bool = False) -> Optional[str]:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise VerificationPipelineError(label + " must be a sha256 fingerprint")
    return value


def _object_id_value(
    value: Any, label: str, *, nullable: bool = False
) -> Optional[str]:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or OBJECT_ID_RE.fullmatch(value) is None:
        raise VerificationPipelineError(label + " must be a Git object ID")
    return value


def _identifier(value: Any, label: str, pattern: re.Pattern[str] = ID_RE) -> str:
    text = _text(value, label)
    if pattern.fullmatch(text) is None:
        raise VerificationPipelineError(label + " must be a stable identifier")
    return text


def _unique_identifiers(
    value: Any,
    label: str,
    *,
    pattern: re.Pattern[str] = ID_RE,
    nonempty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        qualifier = "non-empty " if nonempty else ""
        raise VerificationPipelineError(label + " must be a " + qualifier + "array")
    result = [_identifier(item, label + " entry", pattern) for item in value]
    if len(result) != len(set(result)):
        raise VerificationPipelineError(label + " must contain unique identifiers")
    return result


def plan_impact(
    profile: VerificationProfile,
    project_root: Optional[Path] = None,
    base_ref: Optional[str] = None,
) -> dict[str, Any]:
    root = Path(os.path.realpath(str(project_root or profile.project_root)))
    if os.path.normcase(str(root)) != os.path.normcase(str(profile.project_root)):
        raise VerificationPipelineError("impact projectRoot does not match profile")
    fallback_codes: list[str] = []
    observation: Optional[dict[str, Any]] = None
    try:
        first = _git_observation(profile, base_ref)
        second = _git_observation(profile, base_ref)
        if first != second:
            fallback_codes.append("CHANGE_SNAPSHOT_UNSTABLE")
        else:
            observation = first
    except VerificationPipelineError as exc:
        message = str(exc)
        if "unmerged" in message:
            fallback_codes.append("UNMERGED_INDEX")
        elif "merge-base" in message or "base ref" in message:
            fallback_codes.append("MERGE_BASE_UNAVAILABLE")
        else:
            fallback_codes.append("CHANGE_SNAPSHOT_UNTRUSTED")

    all_case_ids = _case_ids(profile.adapter_data)
    direct: set[str] = set()
    guard_ids: set[str] = set()
    high_rules: list[str] = []
    changed_paths: list[str] = []
    if observation is not None:
        changed_paths = observation["changedPaths"]
        for pattern in profile.view["changeDetection"]["highImpactPaths"]:
            if any(_matches(path, pattern) for path in changed_paths):
                high_rules.append(pattern)
        if high_rules:
            fallback_codes.append("HIGH_IMPACT_PATH")
        for path in changed_paths:
            owners = [
                package["id"]
                for package in profile.view["packages"]
                if any(_matches(path, pattern) for pattern in package["paths"])
            ]
            if not owners:
                fallback_codes.append("UNOWNED_PATH")
            elif len(owners) > 1:
                fallback_codes.append("AMBIGUOUS_PACKAGE_OWNER")
            else:
                direct.add(owners[0])
        for guard in profile.view["guards"]:
            if guard["alwaysRun"] or any(
                _matches(path, pattern)
                for path in changed_paths
                for pattern in guard["paths"]
            ):
                guard_ids.add(guard["id"])

    affected = _downstream_packages(profile, direct)
    quick_ids: set[str] = set(profile.view["ci"]["selectorCaseIds"])
    typecheck_ids: set[str] = set()
    for guard in profile.view["guards"]:
        if guard["id"] in guard_ids or guard["alwaysRun"]:
            quick_ids.update(guard["caseIds"])
    by_package = {item["id"]: item for item in profile.view["packages"]}
    for package_id in affected:
        quick_ids.update(by_package[package_id]["quickCaseIds"])
        typecheck_ids.update(by_package[package_id]["typecheckCaseIds"])
    quick_ids.update(typecheck_ids)
    quick_selection = _case_dependency_closure(profile.adapter_data, quick_ids)
    mode = "full" if fallback_codes else "quick"
    selected = all_case_ids if mode == "full" else quick_selection
    identity = (
        (observation or {}).get("identity")
        or {
            "sourceProvider": "git",
            "commit": None,
            "tree": None,
            "fingerprint": None,
            "sourceFingerprint": None,
        }
    )
    plan: dict[str, Any] = {
        "schemaId": IMPACT_SCHEMA_ID,
        "schemaVersion": SCHEMA_VERSION,
        "projectId": profile.view["projectId"],
        "bindings": {
            "profileFingerprint": profile.sha256,
            "verificationCatalogFingerprint": profile.adapter_catalog_fingerprint,
            "portableSourceFingerprint": identity.get("fingerprint"),
        },
        "repository": {
            "provider": "git",
            "headCommit": identity.get("commit"),
            "headTree": identity.get("tree"),
            "baseInput": (observation or {}).get("baseInput", base_ref or profile.view["changeDetection"]["baseRef"]),
            "mergeBaseCommit": (observation or {}).get("mergeBaseCommit"),
            "changeSnapshotFingerprint": (observation or {}).get("changeSnapshotFingerprint"),
        },
        "changes": (observation or {}).get("changes", {source: [] for source in CHANGE_SOURCES}),
        "impact": {
            "mode": mode,
            "reasonCodes": sorted(set(fallback_codes)),
            "highImpactRules": sorted(high_rules),
            "directPackageIds": sorted(direct),
            "affectedPackageIds": affected,
            "guardIds": sorted(guard_ids),
            "typecheckCaseIds": [case_id for case_id in all_case_ids if case_id in typecheck_ids],
            "selectedCaseIds": selected,
            "fullCaseIds": all_case_ids,
        },
    }
    plan["contentDigest"] = _impact_digest(plan)
    return plan


def validate_impact_plan(
    value: Any,
    profile: VerificationProfile,
    project_root: Optional[Path] = None,
    *,
    reobserve: bool = True,
) -> dict[str, Any]:
    value = _exact_fields(
        value,
        "impact plan",
        {"schemaId", "schemaVersion", "projectId", "bindings", "repository", "changes", "impact", "contentDigest"},
    )
    if (
        value["schemaId"] != IMPACT_SCHEMA_ID
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != SCHEMA_VERSION
    ):
        raise VerificationPipelineError("impact plan version is unsupported")
    project_id = _identifier(value["projectId"], "impact projectId")
    if project_id != profile.view["projectId"]:
        raise VerificationPipelineError("impact plan projectId mismatch")
    bindings = _exact_fields(
        value["bindings"],
        "impact bindings",
        {
            "profileFingerprint",
            "verificationCatalogFingerprint",
            "portableSourceFingerprint",
        },
    )
    profile_fingerprint = _hash_value(
        bindings["profileFingerprint"], "impact profileFingerprint"
    )
    catalog_fingerprint = _hash_value(
        bindings["verificationCatalogFingerprint"],
        "impact verificationCatalogFingerprint",
    )
    _hash_value(
        bindings["portableSourceFingerprint"],
        "impact portableSourceFingerprint",
        nullable=True,
    )
    if (
        profile_fingerprint != profile.sha256
        or catalog_fingerprint != profile.adapter_catalog_fingerprint
    ):
        raise VerificationPipelineError("impact plan profile/catalog binding mismatch")

    repository = _exact_fields(
        value["repository"],
        "impact repository",
        {
            "provider",
            "headCommit",
            "headTree",
            "baseInput",
            "mergeBaseCommit",
            "changeSnapshotFingerprint",
        },
    )
    if repository["provider"] != "git":
        raise VerificationPipelineError("impact repository provider must be git")
    _object_id_value(repository["headCommit"], "impact headCommit", nullable=True)
    _object_id_value(repository["headTree"], "impact headTree", nullable=True)
    _object_id_value(
        repository["mergeBaseCommit"], "impact mergeBaseCommit", nullable=True
    )
    _hash_value(
        repository["changeSnapshotFingerprint"],
        "impact changeSnapshotFingerprint",
        nullable=True,
    )
    if repository["baseInput"] is not None:
        _text(repository["baseInput"], "impact baseInput")

    changes = _exact_fields(
        value["changes"], "impact changes", set(CHANGE_SOURCES)
    )
    for source in CHANGE_SOURCES:
        entries = changes[source]
        if not isinstance(entries, list):
            raise VerificationPipelineError(
                "impact changes." + source + " must be an array"
            )
        for index, raw_entry in enumerate(entries):
            entry = _exact_fields(
                raw_entry,
                "impact changes." + source + " entry " + str(index),
                {"status", "path"},
            )
            status_value = entry["status"]
            if not isinstance(status_value, str) or status_value not in CHANGE_STATUSES:
                raise VerificationPipelineError("impact change status is invalid")
            if (source == "untracked") != (status_value == "?"):
                raise VerificationPipelineError(
                    "impact change status does not match its source"
                )
            _validate_git_path(entry["path"], "impact change path")

    impact = _exact_fields(
        value["impact"],
        "impact result",
        {"mode", "reasonCodes", "highImpactRules", "directPackageIds", "affectedPackageIds", "guardIds", "typecheckCaseIds", "selectedCaseIds", "fullCaseIds"},
    )
    if not isinstance(impact["mode"], str) or impact["mode"] not in {
        "quick",
        "full",
    }:
        raise VerificationPipelineError("impact mode is invalid")
    reason_codes = impact["reasonCodes"]
    if (
        not isinstance(reason_codes, list)
        or any(
            not isinstance(reason, str) or reason not in IMPACT_REASON_CODES
            for reason in reason_codes
        )
        or len(reason_codes) != len(set(reason_codes))
    ):
        raise VerificationPipelineError("impact reasonCodes are invalid")
    if reason_codes != sorted(reason_codes):
        raise VerificationPipelineError("impact reasonCodes must be sorted")
    if (impact["mode"] == "full") != bool(reason_codes):
        raise VerificationPipelineError(
            "impact mode must fail closed exactly when reasonCodes are present"
        )

    high_impact_rules = impact["highImpactRules"]
    if not isinstance(high_impact_rules, list):
        raise VerificationPipelineError("impact highImpactRules must be an array")
    normalized_high_impact = [
        _pattern(pattern, "impact highImpactRules entry")
        for pattern in high_impact_rules
    ]
    if (
        len(normalized_high_impact) != len(set(normalized_high_impact))
        or normalized_high_impact != sorted(normalized_high_impact)
        or not set(normalized_high_impact).issubset(
            profile.view["changeDetection"]["highImpactPaths"]
        )
    ):
        raise VerificationPipelineError("impact highImpactRules are invalid")
    if ("HIGH_IMPACT_PATH" in reason_codes) != bool(normalized_high_impact):
        raise VerificationPipelineError(
            "impact highImpactRules do not match HIGH_IMPACT_PATH"
        )

    direct_package_ids = _unique_identifiers(
        impact["directPackageIds"],
        "impact directPackageIds",
        pattern=PACKAGE_ID_RE,
    )
    affected_package_ids = _unique_identifiers(
        impact["affectedPackageIds"],
        "impact affectedPackageIds",
        pattern=PACKAGE_ID_RE,
    )
    known_packages = {item["id"] for item in profile.view["packages"]}
    if (
        not set(direct_package_ids).issubset(known_packages)
        or not set(affected_package_ids).issubset(known_packages)
        or not set(direct_package_ids).issubset(affected_package_ids)
        or affected_package_ids
        != _downstream_packages(profile, set(direct_package_ids))
        or direct_package_ids != sorted(direct_package_ids)
    ):
        raise VerificationPipelineError("impact package IDs are inconsistent")

    guard_ids = _unique_identifiers(impact["guardIds"], "impact guardIds")
    known_guards = {item["id"] for item in profile.view["guards"]}
    if not set(guard_ids).issubset(known_guards) or guard_ids != sorted(guard_ids):
        raise VerificationPipelineError("impact guardIds are invalid")

    all_cases = _case_ids(profile.adapter_data)
    if impact["fullCaseIds"] != all_cases:
        raise VerificationPipelineError("impact fullCaseIds do not match the adapter catalog")
    _unique_identifiers(impact["fullCaseIds"], "impact fullCaseIds", nonempty=True)
    selected = _unique_identifiers(
        impact["selectedCaseIds"], "impact selectedCaseIds", nonempty=True
    )
    if any(case not in all_cases for case in selected):
        raise VerificationPipelineError("impact selectedCaseIds are invalid")
    typecheck_case_ids = _unique_identifiers(
        impact["typecheckCaseIds"], "impact typecheckCaseIds"
    )
    if (
        any(case not in all_cases for case in typecheck_case_ids)
        or not set(typecheck_case_ids).issubset(selected)
    ):
        raise VerificationPipelineError("impact typecheckCaseIds are invalid")
    if impact["mode"] == "full" and selected != all_cases:
        raise VerificationPipelineError("full fallback must select the complete catalog")
    if _case_dependency_closure(profile.adapter_data, selected) != selected:
        raise VerificationPipelineError("impact selection is not dependency closed")

    digest = _hash_value(value["contentDigest"], "impact contentDigest")
    if digest != _impact_digest(value):
        raise VerificationPipelineError("impact plan contentDigest mismatch")
    if reobserve:
        expected = plan_impact(
            profile,
            project_root or profile.project_root,
            repository["baseInput"],
        )
        if expected["contentDigest"] != value["contentDigest"]:
            raise VerificationPipelineError("impact plan is stale relative to the current repository")
    return copy.deepcopy(value)


def load_impact_plan(path: Path, profile: VerificationProfile, *, reobserve: bool = True) -> dict[str, Any]:
    return validate_impact_plan(_read_json(path, "impact plan"), profile, reobserve=reobserve)


def _ci_digest(value: dict[str, Any]) -> str:
    result = copy.deepcopy(value)
    result.pop("contentDigest", None)
    return sha256_value(result)


def ci_plan_sha256(plan: dict[str, Any]) -> str:
    if not isinstance(plan, dict):
        raise VerificationPipelineError("CI plan must be an object")
    digest = plan.get("contentDigest")
    if not isinstance(digest, str) or digest != _ci_digest(plan):
        raise VerificationPipelineError("CI plan contentDigest mismatch")
    return digest


def _case_components(adapter_data: dict[str, Any]) -> list[list[str]]:
    order = _case_ids(adapter_data)
    index = {case_id: ordinal for ordinal, case_id in enumerate(order)}
    graph = {case_id: set() for case_id in order}
    for case in adapter_data["cases"]:
        for dependency in case.get("dependsOn", []):
            graph[case["id"]].add(dependency)
            graph[dependency].add(case["id"])
    result: list[list[str]] = []
    unseen = set(order)
    while unseen:
        start = min(unseen, key=index.__getitem__)
        stack = [start]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(graph[current] - component)
        unseen -= component
        result.append(sorted(component, key=index.__getitem__))
    return result


def _component_platform(profile: VerificationProfile, component: list[str]) -> str:
    case_by_id = {case["id"]: case for case in profile.adapter_data["cases"]}
    concrete: set[str] = set()
    has_posix = False
    for case_id in component:
        platform = case_by_id[case_id].get("platform", "any")
        if platform == "posix":
            has_posix = True
        elif platform != "any":
            concrete.add(platform)
    if len(concrete) > 1:
        raise VerificationPipelineError("case dependency component spans incompatible platforms")
    if concrete:
        platform = next(iter(concrete))
        if has_posix and platform == "windows":
            raise VerificationPipelineError("POSIX case depends on a Windows-only case")
        return platform
    if has_posix:
        return profile.view["ci"]["posixPlatform"]
    return profile.view["ci"]["portablePlatform"]


def build_ci_plan(profile: VerificationProfile) -> dict[str, Any]:
    cases = _case_ids(profile.adapter_data)
    order = {case_id: index for index, case_id in enumerate(cases)}
    components = _case_components(profile.adapter_data)
    selector_ids = set(profile.view["ci"]["selectorCaseIds"])
    selector_components = [component for component in components if selector_ids & set(component)]
    selector_cases = sorted(
        {case_id for component in selector_components for case_id in component},
        key=order.__getitem__,
    )
    if not selector_ids.issubset(selector_cases):
        raise VerificationPipelineError("selector self-test assignment is incomplete")
    selector_platform = profile.view["ci"]["selectorPlatform"]
    if any(_component_platform(profile, component) != selector_platform for component in selector_components):
        raise VerificationPipelineError("selector dependency component is incompatible with selectorPlatform")

    remaining = [component for component in components if component not in selector_components]
    configured = {item["id"]: item for item in profile.view["ci"]["platforms"]}
    by_platform: dict[str, list[list[str]]] = {platform: [] for platform in configured}
    for component in remaining:
        platform = _component_platform(profile, component)
        if platform not in configured:
            raise VerificationPipelineError("case platform is absent from ci.platforms: " + platform)
        by_platform[platform].append(component)

    entries: list[dict[str, Any]] = []
    if selector_cases:
        entries.append(
            {
                "id": "selector-contract",
                "kind": "selector",
                "platform": selector_platform,
                "shardIndex": 1,
                "shardCount": 1,
                "caseIds": selector_cases,
            }
        )
    for platform in sorted(configured):
        items = by_platform[platform]
        if not items:
            continue
        target_count = min(configured[platform]["shards"], len(items))
        bins: list[list[list[str]]] = [[] for _ in range(target_count)]
        loads = [0] * target_count
        items = sorted(
            items,
            key=lambda component: (-len(component), min(order[item] for item in component), component[0]),
        )
        for component in items:
            target = min(range(target_count), key=lambda index: (loads[index], index))
            bins[target].append(component)
            loads[target] += len(component)
        for index, components_in_bin in enumerate(bins, start=1):
            case_ids = sorted(
                {case_id for component in components_in_bin for case_id in component},
                key=order.__getitem__,
            )
            entries.append(
                {
                    "id": f"{platform}-{index:02d}-of-{target_count:02d}",
                    "kind": "platform",
                    "platform": platform,
                    "shardIndex": index,
                    "shardCount": target_count,
                    "caseIds": case_ids,
                }
            )
    assigned = [case_id for entry in entries for case_id in entry["caseIds"]]
    if sorted(assigned, key=order.__getitem__) != cases or len(assigned) != len(set(assigned)):
        raise VerificationPipelineError("CI plan does not form an exact full-case partition")
    covered_platforms = {entry["platform"] for entry in entries}
    required_platforms = sorted(
        item["id"] for item in profile.view["ci"]["platforms"] if item["required"]
    )
    missing = set(required_platforms) - covered_platforms
    if missing:
        raise VerificationPipelineError("required CI platform has no assigned case: " + sorted(missing)[0])
    plan: dict[str, Any] = {
        "schemaId": CI_PLAN_SCHEMA_ID,
        "schemaVersion": SCHEMA_VERSION,
        "projectId": profile.view["projectId"],
        "profileSha256": profile.sha256,
        "verificationCatalogFingerprint": profile.adapter_catalog_fingerprint,
        "requiredPlatforms": required_platforms,
        "fullCaseIds": cases,
        "entries": entries,
    }
    plan["contentDigest"] = _ci_digest(plan)
    return plan


def validate_ci_plan(value: Any, profile: Optional[VerificationProfile] = None) -> dict[str, Any]:
    value = _exact_fields(
        value,
        "CI plan",
        {"schemaId", "schemaVersion", "projectId", "profileSha256", "verificationCatalogFingerprint", "requiredPlatforms", "fullCaseIds", "entries", "contentDigest"},
    )
    if (
        value["schemaId"] != CI_PLAN_SCHEMA_ID
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != SCHEMA_VERSION
    ):
        raise VerificationPipelineError("CI plan version is unsupported")
    _identifier(value["projectId"], "CI plan projectId")
    _hash_value(value["profileSha256"], "CI plan profileSha256")
    _hash_value(
        value["verificationCatalogFingerprint"],
        "CI plan verificationCatalogFingerprint",
    )
    required_platforms = value["requiredPlatforms"]
    if (
        not isinstance(required_platforms, list)
        or not required_platforms
        or any(
            not isinstance(platform, str) or platform not in PLATFORMS
            for platform in required_platforms
        )
        or len(required_platforms) != len(set(required_platforms))
        or required_platforms != sorted(required_platforms)
    ):
        raise VerificationPipelineError(
            "CI plan requiredPlatforms must be non-empty unique concrete platforms"
        )
    full_case_ids = _unique_identifiers(
        value["fullCaseIds"], "CI plan fullCaseIds", nonempty=True
    )
    if not isinstance(value["entries"], list) or not value["entries"]:
        raise VerificationPipelineError("CI plan entries must be non-empty")
    ids: set[str] = set()
    cases: list[str] = []
    shard_groups: dict[tuple[str, str], dict[str, Any]] = {}
    selector_count = 0
    for raw_entry in value["entries"]:
        entry = _exact_fields(
            raw_entry,
            "CI plan entry",
            {"id", "kind", "platform", "shardIndex", "shardCount", "caseIds"},
        )
        entry_id = _identifier(entry["id"], "CI entry id")
        if entry_id in ids:
            raise VerificationPipelineError("CI plan entry IDs are invalid or duplicate")
        ids.add(entry_id)
        if (
            not isinstance(entry["kind"], str)
            or entry["kind"] not in {"selector", "platform"}
            or not isinstance(entry["platform"], str)
            or entry["platform"] not in PLATFORMS
        ):
            raise VerificationPipelineError("CI plan entry kind/platform is invalid")
        if (
            type(entry["shardIndex"]) is not int
            or type(entry["shardCount"]) is not int
            or not 1 <= entry["shardIndex"] <= entry["shardCount"] <= 64
        ):
            raise VerificationPipelineError("CI plan shard coordinate is invalid")
        entry_case_ids = _unique_identifiers(
            entry["caseIds"], "CI plan entry caseIds", nonempty=True
        )
        cases.extend(entry_case_ids)
        group_key = (entry["kind"], entry["platform"])
        group = shard_groups.setdefault(
            group_key,
            {"count": entry["shardCount"], "indices": []},
        )
        if group["count"] != entry["shardCount"]:
            raise VerificationPipelineError("CI plan shard counts are inconsistent")
        group["indices"].append(entry["shardIndex"])
        if entry["kind"] == "selector":
            selector_count += 1
            if entry["shardIndex"] != 1 or entry["shardCount"] != 1:
                raise VerificationPipelineError(
                    "CI selector entry must be an unsharded self-test"
                )
    if selector_count > 1:
        raise VerificationPipelineError("CI plan has multiple selector entries")
    for group in shard_groups.values():
        if sorted(group["indices"]) != list(range(1, group["count"] + 1)):
            raise VerificationPipelineError(
                "CI plan shard coordinates have gaps or duplicates"
            )
    if len(cases) != len(set(cases)) or set(cases) != set(full_case_ids):
        raise VerificationPipelineError("CI plan case partition has gaps or duplicates")
    covered_platforms = {entry["platform"] for entry in value["entries"]}
    if not set(required_platforms).issubset(covered_platforms):
        raise VerificationPipelineError("CI plan omits a required platform")
    digest = _hash_value(value["contentDigest"], "CI plan contentDigest")
    if digest != _ci_digest(value):
        raise VerificationPipelineError("CI plan contentDigest mismatch")
    if profile is not None:
        expected = build_ci_plan(profile)
        if expected["contentDigest"] != value["contentDigest"]:
            raise VerificationPipelineError("CI plan is stale relative to its profile")
    return copy.deepcopy(value)


def load_ci_plan(path: Path, profile: Optional[VerificationProfile] = None) -> dict[str, Any]:
    return validate_ci_plan(_read_json(path, "CI plan"), profile)


def _relative_from_project(path: Path, root: Path, label: str) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError) as exc:
        raise VerificationPipelineError(label + " must be inside projectRoot") from exc


def _strip_trace_case(case: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(case)
    for field in TRACE_CASE_FIELDS:
        result.pop(field, None)
    return result


def _contract_reference(path: Path, project_root: Path, digest: str) -> dict[str, str]:
    return {"path": _relative_from_project(path, project_root, "contract reference"), "sha256": digest}


def derive_adapter_data(
    profile: VerificationProfile,
    *,
    tier: str,
    output: Path,
    campaign_root: Path,
    impact_plan: Optional[tuple[Path, dict[str, Any]]] = None,
    ci_plan: Optional[tuple[Path, dict[str, Any]]] = None,
    entry_id: Optional[str] = None,
) -> dict[str, Any]:
    if tier not in {"quick", "full"}:
        raise VerificationPipelineError("derived adapter tier must be quick or full")
    output = output if output.is_absolute() else profile.project_root / output
    campaign_root = campaign_root if campaign_root.is_absolute() else profile.project_root / campaign_root
    if _path_has_link_component(output, profile.project_root) or _path_has_link_component(
        campaign_root, profile.project_root
    ):
        raise VerificationPipelineError(
            "derived adapter output or campaignRoot uses a symlink/reparse path"
        )
    # Resolve platform aliases (for example macOS /var -> /private/var) once,
    # after link checks, so every relative route in the emitted adapter is
    # computed from the same canonical project root.
    output = Path(os.path.realpath(str(output)))
    campaign_root = Path(os.path.realpath(str(campaign_root)))
    if output.exists() and not output.is_file():
        raise VerificationPipelineError("derived adapter output must name a file")
    output_relative = _relative_from_project(output, profile.project_root, "adapter output")
    campaign_relative = _relative_from_project(campaign_root, profile.project_root, "campaignRoot")
    excludes = [
        _pattern(item, "source exclude")
        for item in profile.adapter_data.get("source", {}).get("excludes", [])
    ]
    if not _covered(output_relative, excludes) or not _covered(campaign_relative, excludes):
        raise VerificationPipelineError("derived adapter and campaignRoot must be covered by source.excludes")

    data = copy.deepcopy(profile.adapter_data)
    data.pop("verification", None)
    data["projectRoot"] = os.path.relpath(profile.project_root, output.parent).replace(os.sep, "/")
    data["campaignRoot"] = campaign_relative
    profile_ref = _contract_reference(profile.path, profile.project_root, profile.sha256)
    impact_ref: Optional[dict[str, str]] = None
    ci_ref: Optional[dict[str, str]] = None
    if tier == "quick":
        if impact_plan is None or ci_plan is not None or entry_id is not None:
            raise VerificationPipelineError("quick adapter requires only an impact plan")
        plan_path, plan = impact_plan
        plan = validate_impact_plan(plan, profile, reobserve=True)
        if plan["impact"]["mode"] != "quick":
            raise VerificationPipelineError("full fallback cannot be rendered as quick")
        selected = set(plan["impact"]["selectedCaseIds"])
        for case in data["cases"]:
            case["quick"] = case["id"] in selected
        impact_ref = _contract_reference(plan_path.resolve(), profile.project_root, plan["contentDigest"])
    elif ci_plan is not None:
        if impact_plan is not None or entry_id is None:
            raise VerificationPipelineError("CI full adapter requires a CI plan entry and no impact plan")
        plan_path, plan = ci_plan
        plan = validate_ci_plan(plan, profile)
        matches = [entry for entry in plan["entries"] if entry["id"] == entry_id]
        if len(matches) != 1:
            raise VerificationPipelineError("CI plan entry is unknown")
        selected_ids = matches[0]["caseIds"]
        by_id = {case["id"]: case for case in data["cases"]}
        data["cases"] = [_strip_trace_case(by_id[case_id]) for case_id in selected_ids]
        # One CI entry is a locally complete execution partition, not the
        # complete five-tier base catalog.  Keep the two claims separate.
        data["coverageMode"] = "narrow"
        data.pop("traceability", None)
        ci_ref = {
            **_contract_reference(plan_path.resolve(), profile.project_root, plan["contentDigest"]),
            "entryId": entry_id,
        }
    else:
        if impact_plan is None:
            raise VerificationPipelineError("local full adapter requires a full fallback impact plan")
        plan_path, plan = impact_plan
        plan = validate_impact_plan(plan, profile, reobserve=True)
        if plan["impact"]["mode"] != "full":
            raise VerificationPipelineError("full local adapter requires impact mode full")
        impact_ref = _contract_reference(plan_path.resolve(), profile.project_root, plan["contentDigest"])
    data["verification"] = {
        "contractVersion": 1,
        "profile": profile_ref,
        "verificationCatalogFingerprint": profile.adapter_catalog_fingerprint,
        "tier": tier,
        "impactPlan": impact_ref,
        "ciPlan": ci_ref,
    }
    return data


def render_derived_adapter(
    profile: VerificationProfile,
    *,
    tier: str,
    output: Path,
    campaign_root: Path,
    impact_plan: Optional[tuple[Path, dict[str, Any]]] = None,
    ci_plan: Optional[tuple[Path, dict[str, Any]]] = None,
    entry_id: Optional[str] = None,
) -> dict[str, Any]:
    output = output if output.is_absolute() else profile.project_root / output
    data = derive_adapter_data(
        profile,
        tier=tier,
        output=output,
        campaign_root=campaign_root,
        impact_plan=impact_plan,
        ci_plan=ci_plan,
        entry_id=entry_id,
    )
    write_json(output, data)
    return data


def _same_case_contract(candidate: dict[str, Any], base: dict[str, Any], *, ignore_quick: bool) -> bool:
    left = copy.deepcopy(candidate)
    right = copy.deepcopy(base)
    if ignore_quick:
        left.pop("quick", None)
        right.pop("quick", None)
    return left == right


def validate_adapter_verification(
    value: Any,
    adapter_data: dict[str, Any],
    project_root: Path,
    campaign_root: Path,
    adapter_path: Optional[Path] = None,
) -> dict[str, Any]:
    value = _exact_fields(
        value,
        "adapter verification",
        {"contractVersion", "profile", "verificationCatalogFingerprint", "tier", "impactPlan", "ciPlan"},
    )
    if (
        type(value["contractVersion"]) is not int
        or value["contractVersion"] != 1
        or not isinstance(value["tier"], str)
        or value["tier"] not in {"quick", "full"}
    ):
        raise VerificationPipelineError("adapter verification version/tier is invalid")
    profile_ref = _exact_fields(value["profile"], "verification.profile", {"path", "sha256"})
    profile_path = _resolve_inside(project_root, _path(profile_ref["path"], "verification.profile.path"), "verification.profile.path", must_exist=True)
    if profile_path == campaign_root or campaign_root in profile_path.parents:
        raise VerificationPipelineError("verification profile cannot be inside campaignRoot")
    profile = load_profile(profile_path, project_root)
    if profile.sha256 != profile_ref["sha256"] or profile.adapter_catalog_fingerprint != value["verificationCatalogFingerprint"]:
        raise VerificationPipelineError("adapter verification profile/catalog binding mismatch")
    if type(adapter_data.get("schemaVersion")) is not int:
        raise VerificationPipelineError(
            "derived adapter schemaVersion must be an integer"
        )
    for field in ("schemaVersion", "projectId", "source", "localOnly"):
        if adapter_data.get(field) != profile.adapter_data.get(field):
            raise VerificationPipelineError(
                "derived adapter changes immutable base field: " + field
            )

    campaign_output = _resolve_inside(
        project_root,
        profile.view["outputs"]["campaigns"],
        "outputs.campaigns",
    )
    canonical_campaign_root = Path(os.path.realpath(str(campaign_root)))
    try:
        campaign_suffix = canonical_campaign_root.relative_to(campaign_output)
    except ValueError as exc:
        raise VerificationPipelineError(
            "derived adapter campaignRoot must be under outputs.campaigns"
        ) from exc
    if not campaign_suffix.parts:
        raise VerificationPipelineError(
            "derived adapter campaignRoot must be strictly under outputs.campaigns"
        )

    if adapter_path is not None:
        supplied_adapter_path = (
            adapter_path
            if adapter_path.is_absolute()
            else project_root / adapter_path
        )
        if _path_has_link_component(supplied_adapter_path, project_root):
            raise VerificationPipelineError(
                "derived adapter path uses a symlink/reparse component"
            )
        canonical_adapter_path = Path(os.path.realpath(str(supplied_adapter_path)))
        derived_output = _resolve_inside(
            project_root,
            profile.view["outputs"]["derivedAdapters"],
            "outputs.derivedAdapters",
        )
        try:
            adapter_suffix = canonical_adapter_path.relative_to(derived_output)
        except ValueError as exc:
            raise VerificationPipelineError(
                "derived adapter file must be under outputs.derivedAdapters"
            ) from exc
        if not adapter_suffix.parts:
            raise VerificationPipelineError(
                "derived adapter file must be strictly under outputs.derivedAdapters"
            )
    base_by_id = {case["id"]: case for case in profile.adapter_data["cases"]}
    base_coverage_mode = profile.adapter_data.get("coverageMode", "narrow")
    candidate_coverage_mode = adapter_data.get("coverageMode", "narrow")
    candidate_ids = _case_ids(adapter_data)
    impact_ref = value["impactPlan"]
    ci_ref = value["ciPlan"]
    if value["tier"] == "quick" or impact_ref is not None:
        if ci_ref is not None or impact_ref is None:
            raise VerificationPipelineError("impact-derived adapter cannot bind a CI plan")
        if candidate_coverage_mode != base_coverage_mode:
            raise VerificationPipelineError(
                "impact-derived adapter changes base coverageMode"
            )
        impact_ref = _exact_fields(impact_ref, "verification.impactPlan", {"path", "sha256"})
        plan_path = _resolve_inside(project_root, _path(impact_ref["path"], "verification.impactPlan.path"), "verification.impactPlan.path", must_exist=True)
        if plan_path == campaign_root or campaign_root in plan_path.parents:
            raise VerificationPipelineError("impact plan cannot be inside campaignRoot")
        plan = load_impact_plan(plan_path, profile, reobserve=True)
        if plan["contentDigest"] != impact_ref["sha256"]:
            raise VerificationPipelineError("adapter impact-plan digest mismatch")
        if candidate_ids != _case_ids(profile.adapter_data):
            raise VerificationPipelineError("impact-derived adapter must retain the full case catalog")
        if value["tier"] == "quick":
            if plan["impact"]["mode"] != "quick":
                raise VerificationPipelineError("quick adapter binds a full fallback plan")
            selected = set(plan["impact"]["selectedCaseIds"])
            if [case["id"] for case in adapter_data["cases"] if case.get("quick", False)] != [case for case in candidate_ids if case in selected]:
                raise VerificationPipelineError("adapter quick flags differ from the impact plan")
            for case in adapter_data["cases"]:
                if not _same_case_contract(case, base_by_id[case["id"]], ignore_quick=True):
                    raise VerificationPipelineError("quick adapter changes a base case contract")
        else:
            if plan["impact"]["mode"] != "full":
                raise VerificationPipelineError("local full adapter requires full fallback")
            for case in adapter_data["cases"]:
                if not _same_case_contract(case, base_by_id[case["id"]], ignore_quick=False):
                    raise VerificationPipelineError("local full adapter changes a base case contract")
        if adapter_data.get("traceability") != profile.adapter_data.get(
            "traceability"
        ):
            raise VerificationPipelineError(
                "impact-derived adapter changes base traceability"
            )
    else:
        if value["tier"] != "full" or ci_ref is None:
            raise VerificationPipelineError("full CI adapter must bind a CI plan")
        if candidate_coverage_mode != "narrow":
            raise VerificationPipelineError(
                "CI shard adapter coverageMode must be narrow"
            )
        ci_ref = _exact_fields(ci_ref, "verification.ciPlan", {"path", "sha256", "entryId"})
        plan_path = _resolve_inside(project_root, _path(ci_ref["path"], "verification.ciPlan.path"), "verification.ciPlan.path", must_exist=True)
        if plan_path == campaign_root or campaign_root in plan_path.parents:
            raise VerificationPipelineError("CI plan cannot be inside campaignRoot")
        plan = load_ci_plan(plan_path, profile)
        if plan["contentDigest"] != ci_ref["sha256"]:
            raise VerificationPipelineError("adapter CI-plan digest mismatch")
        matches = [entry for entry in plan["entries"] if entry["id"] == ci_ref["entryId"]]
        if len(matches) != 1 or candidate_ids != matches[0]["caseIds"]:
            raise VerificationPipelineError("CI adapter case catalog differs from its entry")
        if adapter_data.get("traceability") is not None:
            raise VerificationPipelineError(
                "CI shard adapter must omit global traceability; "
                "cross-shard trace audit is not supported"
            )
        for case in adapter_data["cases"]:
            expected = _strip_trace_case(base_by_id[case["id"]])
            if case != expected:
                raise VerificationPipelineError("CI shard case differs from the base contract")
    return copy.deepcopy(value)


GITHUB_RUNNERS = {
    "linux": "ubuntu-24.04",
    "darwin": "macos-15",
    "windows": "windows-2025",
}
GITHUB_CHECKOUT_ACTION = "actions/checkout@v7"
GITHUB_UPLOAD_ACTION = "actions/upload-artifact@v7"
GITHUB_DOWNLOAD_ACTION = "actions/download-artifact@v8"


def _path_has_link_component(path: Path, root: Path) -> bool:
    path = path.absolute()
    root = root.absolute()
    if sys.platform == "darwin":
        for alias, target in (
            (Path("/var"), Path("/private/var")),
            (Path("/tmp"), Path("/private/tmp")),
            (Path("/etc"), Path("/private/etc")),
        ):
            try:
                suffix = path.relative_to(alias)
            except ValueError:
                continue
            translated = target / suffix
            try:
                translated.relative_to(root)
            except ValueError:
                continue
            path = translated
            break
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return True
        reparse = bool(
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
        if stat.S_ISLNK(metadata.st_mode) or reparse:
            return True
    return False


def _profile_output(profile: VerificationProfile, key: str) -> Path:
    relative = profile.view["outputs"][key]
    output = _resolve_inside(profile.project_root, relative, "outputs." + key)
    if _path_has_link_component(output, profile.project_root):
        raise VerificationPipelineError("outputs." + key + " uses a symlink/reparse path")
    if output.exists() and not output.is_file():
        raise VerificationPipelineError("outputs." + key + " must name a file")
    return output


def _preflight_profile_output_routes(profile: VerificationProfile) -> None:
    """Validate every declared output route without requiring it to exist."""

    directory_keys = {"derivedAdapters", "campaigns", "evidenceBundles"}
    for key, relative in profile.view["outputs"].items():
        output = _resolve_inside(
            profile.project_root,
            relative,
            "outputs." + key,
        )
        if not output.exists():
            continue
        if key in directory_keys:
            if not output.is_dir():
                raise VerificationPipelineError(
                    "outputs." + key + " must name a directory"
                )
        elif not output.is_file():
            raise VerificationPipelineError(
                "outputs." + key + " must name a file"
            )


def _read_regular_bytes(path: Path, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise VerificationPipelineError("missing " + label + ": " + str(path)) from exc
    reparse = bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
    if stat.S_ISLNK(metadata.st_mode) or reparse or not stat.S_ISREG(metadata.st_mode):
        raise VerificationPipelineError(label + " must be a regular non-link file")
    if metadata.st_size > MAX_JSON_BYTES:
        raise VerificationPipelineError(label + " exceeds the safe size limit")
    try:
        result = path.read_bytes()
        if _stable_stat(path.lstat()) != _stable_stat(metadata):
            raise VerificationPipelineError(label + " changed while it was read")
        return result
    except VerificationPipelineError:
        raise
    except OSError as exc:
        raise VerificationPipelineError("cannot read " + label) from exc


def _python_string(value: Any) -> str:
    if value is None:
        return "None"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def render_local_entry_bytes(profile: VerificationProfile) -> bytes:
    """Return a relocatable thin entry that delegates every effect to the kernel."""

    local_relative = profile.view["outputs"]["localEntry"]
    depth = len(PurePosixPath(local_relative).parts) - 1
    values = {
        "depth": str(depth),
        "profile": _python_string(profile.view["outputs"]["profile"]),
        "impact": _python_string(profile.view["outputs"]["impactPlan"]),
        "ci": _python_string(profile.view["outputs"]["ciPlan"]),
        "adapters": _python_string(profile.view["outputs"]["derivedAdapters"]),
        "campaigns": _python_string(profile.view["outputs"]["campaigns"]),
        "bundles": _python_string(profile.view["outputs"]["evidenceBundles"]),
        "aggregation": _python_string(profile.view["outputs"]["aggregation"]),
        "plugin": _python_string(profile.view["runtime"]["pluginRoot"]),
    }
    template = '''#!/usr/bin/env python3
"""Generated thin entry for steward verification; do not hand edit."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[__DEPTH__]
PROFILE = PROJECT_ROOT / __PROFILE__
IMPACT_PLAN = PROJECT_ROOT / __IMPACT__
CI_PLAN = PROJECT_ROOT / __CI__
ADAPTERS = PROJECT_ROOT / __ADAPTERS__
CAMPAIGNS = PROJECT_ROOT / __CAMPAIGNS__
BUNDLES = PROJECT_ROOT / __BUNDLES__
AGGREGATION = PROJECT_ROOT / __AGGREGATION__
CONFIGURED_PLUGIN_ROOT = __PLUGIN__


def plugin_root() -> Path:
    raw = os.environ.get("STEWARD_PLUGIN_ROOT")
    candidate = Path(raw) if raw else None
    if candidate is not None and not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    if candidate is None and CONFIGURED_PLUGIN_ROOT is not None:
        candidate = PROJECT_ROOT / CONFIGURED_PLUGIN_ROOT
    if candidate is None:
        raise SystemExit(
            "STEWARD_PLUGIN_ROOT is required because runtime.pluginRoot is null"
        )
    result = candidate.resolve()
    required = (
        result / "scripts" / "project_verification.py",
        result / "skills" / "run-closed-loop-verification" / "scripts" / "campaign.py",
    )
    if any(not path.is_file() for path in required):
        raise SystemExit("Steward runtime is incomplete: " + str(result))
    return result


def invoke(script: Path, *arguments: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    if completed.returncode:
        raise SystemExit(completed.returncode)


def machine_status(campaign_cli: Path, adapter: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(campaign_cli), "status", "--adapter", str(adapter)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        if completed.stdout:
            sys.stdout.buffer.write(completed.stdout)
        raise SystemExit(completed.returncode)
    try:
        report = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("campaign status did not return valid JSON") from exc
    if not isinstance(report, dict):
        raise SystemExit("campaign status did not return an object")
    status = report.get("executionStatus")
    resume_mode = report.get("resumeMode")
    last_event_seq = report.get("lastEventSeq")
    attempts = report.get("attempts")
    if (
        not isinstance(status, str)
        or (resume_mode is not None and resume_mode not in {
            "quick", "initial", "retest", "regression"
        })
        or type(last_event_seq) is not int
        or last_event_seq < 1
        or not isinstance(attempts, list)
    ):
        raise SystemExit("campaign status has an invalid lifecycle contract")
    return report


def initialize_if_needed(campaign_cli: Path, adapter: Path, campaign: Path) -> None:
    if not (campaign / "events.jsonl").exists():
        invoke(campaign_cli, "init", "--adapter", str(adapter))


def full_campaign(campaign_cli: Path, adapter: Path) -> None:
    previous_seq: int | None = None
    for _ in range(8):
        report = machine_status(campaign_cli, adapter)
        status = report["executionStatus"]
        resume_mode = report["resumeMode"]
        last_event_seq = report["lastEventSeq"]
        attempts = report["attempts"]
        if previous_seq is not None and last_event_seq <= previous_seq:
            raise SystemExit("campaign lifecycle made no durable progress")
        if status == "COMPLETE":
            invoke(campaign_cli, "audit", "--adapter", str(adapter))
            return
        if status == "FAILED":
            raise SystemExit(
                "campaign is FAILED; preserve the fix gate and use record-fix/retest"
            )
        previous_seq = last_event_seq
        if status == "PENDING":
            if not attempts:
                invoke(
                    campaign_cli,
                    "run",
                    "--adapter",
                    str(adapter),
                    "--phase",
                    "full",
                )
            elif resume_mode in {"initial", "retest", "regression"}:
                invoke(campaign_cli, "resume", "--adapter", str(adapter))
            else:
                raise SystemExit("PENDING campaign has no valid continuation")
        elif status == "READY_FOR_REGRESSION":
            if resume_mode not in {None, "regression"}:
                raise SystemExit("READY campaign has an invalid regression continuation")
            invoke(
                campaign_cli,
                "run",
                "--adapter",
                str(adapter),
                "--mode",
                "regression",
                "--phase",
                "full",
            )
        elif status in {"RUNNING", "REGRESSION_RUNNING", "INTERRUPTED"}:
            if resume_mode not in {"initial", "retest", "regression"}:
                raise SystemExit("active campaign has no valid resumable phase")
            invoke(campaign_cli, "resume", "--adapter", str(adapter))
        elif status == "BLOCKED":
            raise SystemExit(
                "campaign is BLOCKED; inspect status and use the dedicated kernel "
                "contract to choose resume or a new campaign root"
            )
        else:
            raise SystemExit("unsupported campaign lifecycle status: " + status)
    raise SystemExit("campaign lifecycle exceeded its bounded continuation limit")


def quick_campaign(campaign_cli: Path, adapter: Path) -> None:
    report = machine_status(campaign_cli, adapter)
    status = report["executionStatus"]
    resume_mode = report["resumeMode"]
    attempts = report["attempts"]
    if status == "FAILED":
        raise SystemExit(
            "campaign is FAILED; preserve the fix gate and use record-fix/retest"
        )
    if status == "PENDING" and not attempts:
        invoke(campaign_cli, "run", "--adapter", str(adapter), "--phase", "quick")
        return
    if status == "PENDING" and resume_mode == "initial":
        # Quick diagnostics remain repeatable history and never claim full
        # completion; preserve the existing explicit rerun behavior.
        invoke(campaign_cli, "run", "--adapter", str(adapter), "--phase", "quick")
        return
    if status in {"RUNNING", "INTERRUPTED"} and resume_mode == "quick":
        invoke(campaign_cli, "resume", "--adapter", str(adapter))
        return
    if status == "BLOCKED":
        raise SystemExit(
            "campaign is BLOCKED; inspect status and use the dedicated kernel "
            "contract to choose resume or a new campaign root"
        )
    if status == "COMPLETE":
        invoke(campaign_cli, "audit", "--adapter", str(adapter))
        return
    raise SystemExit("quick campaign has no valid continuation")


def local(base_ref: str | None) -> None:
    root = plugin_root()
    config_cli = root / "scripts" / "project_verification.py"
    campaign_cli = root / "skills" / "run-closed-loop-verification" / "scripts" / "campaign.py"
    arguments = [
        "plan-impact",
        "--profile",
        str(PROFILE),
        "--project-root",
        str(PROJECT_ROOT),
        "--output",
        str(IMPACT_PLAN),
    ]
    if base_ref is not None:
        arguments.extend(["--base-ref", base_ref])
    invoke(config_cli, *arguments)
    plan = json.loads(IMPACT_PLAN.read_text(encoding="utf-8"))
    mode = plan["impact"]["mode"]
    digest = plan["contentDigest"].split(":", 1)[1][:20]
    adapter = ADAPTERS / ("local-" + mode + "-" + digest + ".json")
    campaign = CAMPAIGNS / ("local-" + mode + "-" + digest)
    invoke(
        config_cli,
        "render-adapter",
        "--profile",
        str(PROFILE),
        "--project-root",
        str(PROJECT_ROOT),
        "--tier",
        mode,
        "--impact-plan",
        str(IMPACT_PLAN),
        "--output",
        str(adapter),
        "--campaign-root",
        str(campaign),
    )
    initialize_if_needed(campaign_cli, adapter, campaign)
    if mode == "quick":
        quick_campaign(campaign_cli, adapter)
        return
    full_campaign(campaign_cli, adapter)


def ci(entry: str) -> None:
    root = plugin_root()
    config_cli = root / "scripts" / "project_verification.py"
    campaign_cli = root / "skills" / "run-closed-loop-verification" / "scripts" / "campaign.py"
    adapter = ADAPTERS / ("ci-" + entry + ".json")
    campaign = CAMPAIGNS / ("ci-" + entry)
    bundle = BUNDLES / (entry + ".json")
    invoke(
        config_cli,
        "render-adapter",
        "--profile",
        str(PROFILE),
        "--project-root",
        str(PROJECT_ROOT),
        "--tier",
        "full",
        "--ci-plan",
        str(CI_PLAN),
        "--entry",
        entry,
        "--output",
        str(adapter),
        "--campaign-root",
        str(campaign),
    )
    initialize_if_needed(campaign_cli, adapter, campaign)
    full_campaign(campaign_cli, adapter)
    invoke(
        campaign_cli,
        "export-platform-evidence",
        "--adapter",
        str(adapter),
        "--profile",
        str(PROFILE),
        "--ci-plan",
        str(CI_PLAN),
        "--entry",
        entry,
        "--output",
        str(bundle),
    )


def aggregate(bundle_dir: Path) -> None:
    root = plugin_root()
    campaign_cli = root / "skills" / "run-closed-loop-verification" / "scripts" / "campaign.py"
    bundles = sorted(bundle_dir.rglob("*.json"))
    if not bundles:
        raise SystemExit("no platform evidence bundles were found")
    arguments = [
        "aggregate-platform-evidence",
        "--profile",
        str(PROFILE),
        "--ci-plan",
        str(CI_PLAN),
    ]
    for bundle in bundles:
        arguments.extend(["--bundle", str(bundle)])
    arguments.extend(["--output", str(AGGREGATION)])
    invoke(campaign_cli, *arguments)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run configured project verification")
    subparsers = parser.add_subparsers(dest="command", required=True)
    local_parser = subparsers.add_parser("local")
    local_parser.add_argument("--base-ref")
    ci_parser = subparsers.add_parser("ci")
    ci_parser.add_argument("--entry", required=True)
    aggregate_parser = subparsers.add_parser("aggregate")
    aggregate_parser.add_argument("--bundle-dir", required=True)
    args = parser.parse_args()
    if args.command == "local":
        local(args.base_ref)
    elif args.command == "ci":
        ci(args.entry)
    else:
        aggregate(Path(args.bundle_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    replacements = {
        "__" + key.upper() + "__": value for key, value in values.items()
    }
    token_pattern = re.compile(
        "|".join(re.escape(token) for token in replacements)
    )
    substitution_counts = {token: 0 for token in replacements}

    def substitute(match: re.Match[str]) -> str:
        token = match.group(0)
        substitution_counts[token] += 1
        return replacements[token]

    rendered = token_pattern.sub(substitute, template)
    if any(count != 1 for count in substitution_counts.values()):
        raise VerificationPipelineError(
            "local verification entry template placeholders are inconsistent"
        )
    return rendered.encode("utf-8")


def render_local_entry(
    profile: VerificationProfile,
    *,
    check: bool = False,
) -> bytes:
    output = _profile_output(profile, "localEntry")
    expected = render_local_entry_bytes(profile)
    if not check:
        raise VerificationPipelineError(
            "direct renderer writes are disabled; use configure with the complete "
            "authorized write set"
        )
    if _read_regular_bytes(output, "local verification entry") != expected:
        raise VerificationPipelineError("local verification entry is stale")
    return expected


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_github_actions_bytes(
    profile: VerificationProfile,
    ci_plan: dict[str, Any],
) -> bytes:
    """Render the fixed GitHub projection of a validated provider-neutral plan."""

    plan = validate_ci_plan(ci_plan, profile)
    local_entry = profile.view["outputs"]["localEntry"]
    bundle_directory = profile.view["outputs"]["evidenceBundles"]
    aggregation = profile.view["outputs"]["aggregation"]
    python_commands = profile.view["runtime"]["pythonExecutables"]
    aggregation_platform = profile.view["ci"]["portablePlatform"]
    aggregation_python = (
        python_commands["windows"]
        if aggregation_platform == "windows"
        else python_commands["posix"]
    )
    lines = [
        "# Generated by Steward; edit the verification profile instead.",
        "name: Project verification",
        '"on":',
        "  pull_request:",
        "  push:",
        "  workflow_dispatch:",
        "permissions:",
        "  contents: read",
        "env:",
        "  STEWARD_PLUGIN_ROOT: ${{ vars.STEWARD_PLUGIN_ROOT }}",
        "jobs:",
        "  full:",
        "    name: full / ${{ matrix.id }}",
        "    strategy:",
        "      fail-fast: false",
        "      matrix:",
        "        include:",
    ]
    for entry in plan["entries"]:
        platform = entry["platform"]
        python_command = (
            python_commands["windows"]
            if platform == "windows"
            else python_commands["posix"]
        )
        lines.extend(
            [
                "          - id: " + _yaml_string(entry["id"]),
                "            kind: " + _yaml_string(entry["kind"]),
                "            platform: " + _yaml_string(platform),
                "            runner: " + _yaml_string(GITHUB_RUNNERS[platform]),
                "            python: " + _yaml_string(python_command),
                "            shard-index: " + str(entry["shardIndex"]),
                "            shard-count: " + str(entry["shardCount"]),
            ]
        )
    lines.extend(
        [
            "    runs-on: ${{ matrix.runner }}",
            "    steps:",
            "      - name: Check out exact commit",
            "        uses: " + GITHUB_CHECKOUT_ACTION,
            "        with:",
            "          fetch-depth: 0",
            "      - name: Run full verification shard",
            "        run: >-",
            "          ${{ matrix.python }} "
            + _yaml_string(local_entry)
            + " ci --entry ${{ matrix.id }}",
            "      - name: Upload audited platform evidence",
            "        uses: " + GITHUB_UPLOAD_ACTION,
            "        with:",
            "          name: verification-${{ matrix.id }}",
            "          path: "
            + _yaml_string(bundle_directory + "/${{ matrix.id }}.json"),
            "          if-no-files-found: error",
            "          retention-days: 7",
            "  aggregate:",
            "    name: aggregate platform evidence",
            "    if: always()",
            "    needs: full",
            "    runs-on: "
            + _yaml_string(GITHUB_RUNNERS[aggregation_platform]),
            "    steps:",
            "      - name: Check out exact commit",
            "        uses: " + GITHUB_CHECKOUT_ACTION,
            "        with:",
            "          fetch-depth: 0",
            "      - name: Download platform evidence",
            "        uses: " + GITHUB_DOWNLOAD_ACTION,
            "        with:",
            "          pattern: verification-*",
            "          path: " + _yaml_string(bundle_directory),
            "          merge-multiple: true",
            "      - name: Aggregate and audit evidence",
            "        run: >-",
            "          "
            + aggregation_python
            + " "
            + _yaml_string(local_entry)
            + " aggregate --bundle-dir "
            + _yaml_string(bundle_directory),
            "      - name: Upload aggregation",
            "        uses: " + GITHUB_UPLOAD_ACTION,
            "        with:",
            "          name: verification-aggregation",
            "          path: " + _yaml_string(aggregation),
            "          if-no-files-found: error",
            "          retention-days: 7",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_github_actions(
    profile: VerificationProfile,
    ci_plan: dict[str, Any],
    *,
    check: bool = False,
) -> bytes:
    output = _profile_output(profile, "workflow")
    expected = render_github_actions_bytes(profile, ci_plan)
    if not check:
        raise VerificationPipelineError(
            "direct renderer writes are disabled; use configure with the complete "
            "authorized write set"
        )
    if _read_regular_bytes(output, "GitHub Actions workflow") != expected:
        raise VerificationPipelineError("GitHub Actions workflow is stale")
    return expected


def _static_check(
    label: str,
    path: Path,
    expected: bytes,
) -> dict[str, Any]:
    expected_sha256 = "sha256:" + hashlib.sha256(expected).hexdigest()
    expected_report = {
        "expectedSize": len(expected),
        "expectedSha256": expected_sha256,
    }
    try:
        actual = _read_regular_bytes(path, label)
    except VerificationPipelineError as exc:
        return {
            "id": label,
            "ok": False,
            "detail": str(exc),
            **expected_report,
        }
    if actual != expected:
        return {
            "id": label,
            "ok": False,
            "detail": label + " is stale",
            "actualSize": len(actual),
            "actualSha256": "sha256:" + hashlib.sha256(actual).hexdigest(),
            **expected_report,
        }
    return {
        "id": label,
        "ok": True,
        "sha256": expected_sha256,
        **expected_report,
    }


def review_configuration(
    profile_path: Path,
    project_root: Optional[Path] = None,
) -> dict[str, Any]:
    """Read and compare the complete static projection without writing anything."""

    profile = load_profile(profile_path, project_root)
    _preflight_profile_output_routes(profile)
    ci_plan = build_ci_plan(profile)
    ci_bytes = canonical_bytes(ci_plan) + b"\n"
    checks = [
        {
            "id": "profile",
            "ok": True,
            "sha256": profile.sha256,
        },
        {
            "id": "base-adapter",
            "ok": True,
            "sha256": profile.adapter_catalog_fingerprint,
        },
        _static_check(
            "CI plan",
            _profile_output(profile, "ciPlan"),
            ci_bytes,
        ),
        _static_check(
            "local verification entry",
            _profile_output(profile, "localEntry"),
            render_local_entry_bytes(profile),
        ),
        _static_check(
            "GitHub Actions workflow",
            _profile_output(profile, "workflow"),
            render_github_actions_bytes(profile, ci_plan),
        ),
    ]
    report: dict[str, Any] = {
        "mode": "review",
        "status": "reviewed",
        "ok": all(check["ok"] for check in checks),
        "writePerformed": False,
        "projectId": profile.view["projectId"],
        "profileFingerprint": profile.sha256,
        "verificationCatalogFingerprint": profile.adapter_catalog_fingerprint,
        "ciPlanFingerprint": ci_plan["contentDigest"],
        "checks": checks,
        "requiredPlatforms": ci_plan["requiredPlatforms"],
        "entryIds": [entry["id"] for entry in ci_plan["entries"]],
        "remoteCiExecuted": False,
    }
    return report


def _configuration_state_paths(
    profile: VerificationProfile,
) -> tuple[dict[str, str], dict[str, str]]:
    inputs: dict[str, str] = {
        "verification profile": _relative_from_project(
            profile.path,
            profile.project_root,
            "verification profile",
        ),
        "base adapter": _relative_from_project(
            profile.adapter_path,
            profile.project_root,
            "base adapter",
        ),
    }

    def add_input(label: str, relative: str) -> None:
        # Explicit inventories may intentionally name another input authority.
        # One frozen snapshot is sufficient for the exact same route.
        if relative not in inputs.values():
            inputs[label] = relative

    plugin_root = profile.view["runtime"]["pluginRoot"]
    if plugin_root is not None:
        runtime_root = PurePosixPath(plugin_root)
        for index, relative in enumerate(
            (
                "scripts/project_verification.py",
                "skills/run-closed-loop-verification/scripts/campaign.py",
            )
        ):
            add_input(
                "runtime entry " + str(index),
                (runtime_root / relative).as_posix(),
            )
    try:
        adapter = _kernel_validator()(profile.adapter_path)
    except Exception as exc:
        raise VerificationPipelineError(
            "referenced closed-loop adapter is invalid: " + str(exc)
        ) from exc
    for label, relative in _adapter_explicit_input_paths(
        adapter,
        profile.project_root,
    ):
        add_input("adapter input " + label, relative)

    targets = {
        "CI plan output": profile.view["outputs"]["ciPlan"],
        "local entry output": profile.view["outputs"]["localEntry"],
        "workflow output": profile.view["outputs"]["workflow"],
    }
    return inputs, targets


def _same_profile_contract(
    expected: VerificationProfile,
    observed: VerificationProfile,
) -> bool:
    return (
        observed.path == expected.path
        and observed.adapter_path == expected.adapter_path
        and observed.sha256 == expected.sha256
        and observed.adapter_catalog_fingerprint
        == expected.adapter_catalog_fingerprint
        and observed.view == expected.view
    )


def _commit_configuration_batch(
    profile: VerificationProfile,
    candidates: dict[str, bytes],
    input_paths: dict[str, str],
    target_paths: dict[str, str],
    frozen_inputs: dict[str, _SafePathSnapshot],
    frozen_targets: dict[str, _SafePathSnapshot],
) -> None:
    """Stage every projection, then validate the frozen batch before first commit."""

    staged: list[_StagedProjection] = []
    with _locked_project_root(profile.project_root) as root_fd:
        _assert_snapshots(root_fd, input_paths, frozen_inputs)
        _assert_snapshots(root_fd, target_paths, frozen_targets)
        observed = load_profile(profile.path, profile.project_root)
        if not _same_profile_contract(profile, observed):
            raise VerificationPipelineError(
                "profile or adapter changed during configuration"
            )
        _assert_snapshots(root_fd, input_paths, frozen_inputs)
        _assert_snapshots(root_fd, target_paths, frozen_targets)
        try:
            batch_created: list[_CreatedDirectory] = []
            for key in ("CI plan output", "local entry output", "workflow output"):
                item = _stage_projection(
                    root_fd,
                    target_paths[key],
                    candidates[key],
                    frozen_targets[key],
                    batch_created,
                )
                staged.append(item)
                batch_created.extend(item.created_directories)

            # Staging may create missing parents, but it has not changed any
            # declared output. Revalidate every source and final target as one
            # frozen batch immediately before the first replace.
            _assert_root_route(profile.project_root, root_fd)
            _assert_snapshots(root_fd, input_paths, frozen_inputs)
            observed = load_profile(profile.path, profile.project_root)
            if not _same_profile_contract(profile, observed):
                raise VerificationPipelineError(
                    "profile or adapter changed during configuration"
                )
            _assert_snapshots(root_fd, input_paths, frozen_inputs)
            for item in staged:
                _assert_parent_route(
                    root_fd,
                    item.relative,
                    item.parent_fd,
                    item.parent_identity,
                )
                if (
                    _snapshot_parent_file(
                        item.parent_fd,
                        item.target_name,
                        "configuration output " + item.relative,
                    )
                    != item.expected_target
                ):
                    raise VerificationPipelineError(
                        "configuration output changed during configuration: "
                        + item.relative
                    )

            for index, item in enumerate(staged):
                _assert_root_route(profile.project_root, root_fd)
                _assert_snapshots(root_fd, input_paths, frozen_inputs)
                for pending in staged[index:]:
                    if (
                        _snapshot_parent_file(
                            pending.parent_fd,
                            pending.target_name,
                            "configuration output " + pending.relative,
                        )
                        != pending.expected_target
                    ):
                        raise VerificationPipelineError(
                            "configuration output changed during configuration: "
                            + pending.relative
                        )
                _commit_staged_projection(root_fd, item)
        except VerificationPipelineError as exc:
            committed = [item.relative for item in staged if not item.temp_name]
            if committed:
                raise VerificationPipelineError(
                    "configuration batch stopped after committing "
                    + ", ".join(committed)
                    + "; "
                    + str(exc)
                ) from exc
            raise
        except OSError as exc:
            committed = [item.relative for item in staged if not item.temp_name]
            detail = "configuration safe batch IO failed"
            if committed:
                detail += " after committing " + ", ".join(committed)
            raise VerificationPipelineError(detail) from exc
        finally:
            _discard_staged(root_fd, staged)


def _assert_configure_report_binding(
    report: dict[str, Any],
    profile: VerificationProfile,
    ci_plan: dict[str, Any],
    candidates: dict[str, bytes],
) -> None:
    if (
        report.get("projectId") != profile.view["projectId"]
        or report.get("profileFingerprint") != profile.sha256
        or report.get("verificationCatalogFingerprint")
        != profile.adapter_catalog_fingerprint
        or report.get("ciPlanFingerprint") != ci_plan["contentDigest"]
    ):
        raise VerificationPipelineError(
            "configuration outputs were committed, but the final review does not "
            "bind the frozen inputs"
        )
    checks = {
        check.get("id"): check
        for check in report.get("checks", [])
        if isinstance(check, dict)
    }
    expected_checks = {
        "CI plan": candidates["CI plan output"],
        "local verification entry": candidates["local entry output"],
        "GitHub Actions workflow": candidates["workflow output"],
    }
    for check_id, data in expected_checks.items():
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        check = checks.get(check_id)
        if (
            not isinstance(check, dict)
            or check.get("ok") is not True
            or check.get("sha256") != digest
            or check.get("expectedSha256") != digest
            or check.get("expectedSize") != len(data)
        ):
            raise VerificationPipelineError(
                "configuration outputs were committed, but the final review does "
                "not bind the frozen candidates"
            )


def configure_project(
    profile_path: Path,
    project_root: Optional[Path],
    authorized_paths: Iterable[str],
) -> dict[str, Any]:
    """Write only the profile-declared static projections authorized by the caller."""

    profile = load_profile(profile_path, project_root)
    profile_relative = _relative_from_project(
        profile.path, profile.project_root, "verification profile"
    )
    adapter_relative = _relative_from_project(
        profile.adapter_path, profile.project_root, "base adapter"
    )
    declared = {
        profile_relative,
        adapter_relative,
        profile.view["outputs"]["ciPlan"],
        profile.view["outputs"]["localEntry"],
        profile.view["outputs"]["workflow"],
    }
    allowed = {
        _path(value, "authorized write path")
        for value in authorized_paths
    }
    unknown = sorted(allowed - declared)
    if unknown:
        raise VerificationPipelineError(
            "authorized write set contains an undeclared path: " + unknown[0]
        )
    required = {
        profile.view["outputs"]["ciPlan"],
        profile.view["outputs"]["localEntry"],
        profile.view["outputs"]["workflow"],
    }
    missing = sorted(required - allowed)
    if missing:
        raise VerificationPipelineError(
            "authorized write set omits a generated output: " + missing[0]
        )
    input_paths, target_paths = _configuration_state_paths(profile)
    frozen = _snapshot_paths(
        profile.project_root,
        {**input_paths, **target_paths},
    )
    frozen_inputs = {key: frozen[key] for key in input_paths}
    frozen_targets = {key: frozen[key] for key in target_paths}
    ci_plan = build_ci_plan(profile)
    candidates = {
        "CI plan output": canonical_bytes(ci_plan) + b"\n",
        "local entry output": render_local_entry_bytes(profile),
        "workflow output": render_github_actions_bytes(profile, ci_plan),
    }
    ci_output = _profile_output(profile, "ciPlan")
    local_output = _profile_output(profile, "localEntry")
    workflow_output = _profile_output(profile, "workflow")
    _commit_configuration_batch(
        profile,
        candidates,
        input_paths,
        target_paths,
        frozen_inputs,
        frozen_targets,
    )
    try:
        report = review_configuration(profile.path, profile.project_root)
    except VerificationPipelineError as exc:
        raise VerificationPipelineError(
            "configuration outputs were committed, but final static review failed; "
            + str(exc)
        ) from exc
    if not report["ok"]:
        raise VerificationPipelineError(
            "configuration outputs were committed, but final static review failed"
        )
    _assert_configure_report_binding(report, profile, ci_plan, candidates)
    report.update(
        {
            "mode": "configure",
            "status": "configured",
            "writePerformed": True,
            "writtenPaths": sorted(
                {
                    _relative_from_project(ci_output, profile.project_root, "CI plan"),
                    _relative_from_project(local_output, profile.project_root, "local entry"),
                    _relative_from_project(
                        workflow_output, profile.project_root, "workflow"
                    ),
                }
            ),
            "authorizedWriteSet": sorted(allowed),
        }
    )
    return report


__all__ = [
    "VerificationPipelineError",
    "VerificationProfile",
    "build_ci_plan",
    "canonical_bytes",
    "ci_plan_sha256",
    "configure_project",
    "derive_adapter_data",
    "load_ci_plan",
    "load_impact_plan",
    "load_profile",
    "plan_impact",
    "portable_git_source_identity",
    "profile_catalog_fingerprint",
    "profile_sha256",
    "profile_view",
    "render_derived_adapter",
    "render_github_actions",
    "render_github_actions_bytes",
    "render_local_entry",
    "render_local_entry_bytes",
    "review_configuration",
    "sha256_value",
    "validate_adapter_verification",
    "validate_ci_plan",
    "validate_impact_plan",
    "verification_catalog_fingerprint",
    "write_json",
]
