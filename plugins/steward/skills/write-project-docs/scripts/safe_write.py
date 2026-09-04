#!/usr/bin/env python3
"""Stable snapshots and compare-before-replace atomic Markdown writes."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class AtomicWriteCommittedError(OSError):
    """The replacement committed, but a post-commit guarantee failed."""


class AtomicWriteDurabilityError(AtomicWriteCommittedError):
    """The replacement committed, but its directory durability is unconfirmed."""


@contextmanager
def _post_commit_error_boundary(
    path: Path, committed: Callable[[], bool]
) -> Iterator[None]:
    """Classify every ordinary exception after replace as a committed error."""

    try:
        yield
    except AtomicWriteCommittedError:
        raise
    except Exception as error:
        if committed():
            raise AtomicWriteCommittedError(
                f"{path.name} 已替换，但提交后清理或校验失败"
            ) from error
        raise


@dataclass(frozen=True)
class FileSnapshot:
    """Content and identity used for a single-writer optimistic comparison."""

    data: bytes
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int


def _open_flags(*, writable: bool) -> int:
    flags = os.O_RDWR if writable else os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _metadata_changed(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        not os.path.samestat(before, after)
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    )


def read_snapshot(path: Path) -> FileSnapshot:
    """Read one regular non-symlink file and reject identity/content races."""

    try:
        inspected = path.lstat()
    except OSError as error:
        raise ValueError(f"{path.name} 无法安全读取") from error
    if not stat.S_ISREG(inspected.st_mode):
        raise ValueError(f"{path.name} 不是普通非符号链接文件")

    descriptor: int | None = None
    try:
        descriptor = os.open(path, _open_flags(writable=False))
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(inspected, opened):
            raise ValueError(f"{path.name} 在打开期间发生变化")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            data = handle.read()
            final = os.fstat(handle.fileno())
        current = path.lstat()
    except ValueError:
        raise
    except OSError as error:
        raise ValueError(f"{path.name} 无法安全读取") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    if (
        not stat.S_ISREG(current.st_mode)
        or len(data) != final.st_size
        or _metadata_changed(opened, final)
        or _metadata_changed(final, current)
    ):
        raise ValueError(f"{path.name} 在读取期间发生变化")
    return FileSnapshot(
        data=data,
        device=final.st_dev,
        inode=final.st_ino,
        mode=stat.S_IMODE(final.st_mode),
        size=final.st_size,
        mtime_ns=final.st_mtime_ns,
        ctime_ns=final.st_ctime_ns,
    )


def _set_file_mode(descriptor: int, path: Path, mode: int) -> None:
    """Apply the original file's permission bits to the replacement file."""

    if hasattr(os, "fchmod"):  # pragma: no branch - platform selection
        os.fchmod(descriptor, mode)
    else:  # pragma: no cover - Windows has no fd-based chmod
        os.chmod(path, mode)


def _fsync_parent_directory(path: Path) -> None:
    """Persist a POSIX rename; Windows has no portable directory fsync."""

    if os.name == "nt":  # pragma: no cover - Windows durability is weaker
        return
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path.parent, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise AtomicWriteDurabilityError(
            f"{path.name} 已替换，但父目录持久化未确认"
        ) from error


def write_atomically(
    path: Path,
    text: str,
    expected: FileSnapshot,
    precommit_validate: Callable[[], None],
    *,
    input_snapshots: tuple[tuple[Path, FileSnapshot], ...] = (),
) -> None:
    """Compare target/inputs against their snapshots, then atomically replace target."""

    unique_inputs = {
        candidate.absolute(): (candidate, snapshot)
        for candidate, snapshot in input_snapshots
        if candidate.absolute() != path.absolute()
    }
    target_identity = (expected.device, expected.inode)
    for candidate, snapshot in unique_inputs.values():
        if (snapshot.device, snapshot.inode) == target_identity:
            raise ValueError(f"{candidate.name} 不得是 {path.name} 的硬链接别名")

    def _check_unchanged() -> None:
        if read_snapshot(path) != expected:
            raise ValueError(f"{path.name} 在写入期间发生变化")
        for candidate, snapshot in unique_inputs.values():
            if read_snapshot(candidate) != snapshot:
                raise ValueError(f"{candidate.name} 在写入期间发生变化")

    temporary_path: Path | None = None
    temporary_descriptor: int | None = None
    commit_state = [False]
    with _post_commit_error_boundary(path, lambda: commit_state[0]):
        try:
            _check_unchanged()
            precommit_validate()

            temporary_descriptor, temporary_name = tempfile.mkstemp(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            encoded = text.encode("utf-8")
            written = 0
            while written < len(encoded):
                count = os.write(temporary_descriptor, encoded[written:])
                if count == 0:
                    raise OSError("临时文件写入未前进")
                written += count
            _set_file_mode(temporary_descriptor, temporary_path, expected.mode)
            os.fsync(temporary_descriptor)

            # 重新核对一次，缩小写入耗时与替换之间的竞态窗口。
            _check_unchanged()
            precommit_validate()

            if os.name == "nt":  # pragma: no cover - Windows denies open-file replace
                os.close(temporary_descriptor)
                temporary_descriptor = None
            os.replace(temporary_path, path)
            commit_state[0] = True
            temporary_path = None
            _fsync_parent_directory(path)
        finally:
            if temporary_descriptor is not None:
                try:
                    os.close(temporary_descriptor)
                except OSError:
                    pass
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
