#!/usr/bin/env python3
"""Stable snapshots and coordinated compare-before-replace Markdown writes."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
    import ctypes
    import msvcrt
    from ctypes import wintypes
else:  # pragma: no cover - branch selection is platform-specific
    import fcntl


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
    """Content and identity used for a coordinated optimistic comparison."""

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


def _lock_descriptor(descriptor: int, *, exclusive: bool) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
        os.lseek(descriptor, 0, os.SEEK_SET)
        mode = msvcrt.LK_LOCK if exclusive else msvcrt.LK_RLCK
        msvcrt.locking(descriptor, mode, 1)
    else:  # pragma: no cover - branch selection is platform-specific
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(descriptor, mode)


def _unlock_descriptor(descriptor: int) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:  # pragma: no cover - branch selection is platform-specific
        fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def _locked_file(path: Path, *, exclusive: bool) -> Iterator[None]:
    """Hold an advisory lock and ensure it still names the inspected file."""

    inspected = path.lstat()
    if not stat.S_ISREG(inspected.st_mode):
        raise ValueError(f"{path.name} 不是普通非符号链接文件")
    descriptor: int | None = None
    locked = False
    try:
        try:
            descriptor = os.open(
                path, _open_flags(writable=exclusive and os.name == "nt")
            )
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(
                inspected, opened
            ):
                raise ValueError(f"{path.name} 在加锁前发生变化")
            _lock_descriptor(descriptor, exclusive=exclusive)
            locked = True
            current = path.lstat()
            if not stat.S_ISREG(current.st_mode) or not os.path.samestat(
                opened, current
            ):
                raise ValueError(f"{path.name} 在加锁期间发生变化")
        except ValueError:
            raise
        except OSError as error:
            raise ValueError(f"{path.name} 无法安全加锁") from error
        yield
    finally:
        if descriptor is not None:
            try:
                if locked:
                    _unlock_descriptor(descriptor)
            finally:
                os.close(descriptor)


@contextmanager
def _windows_coordination_mutex(identity: str) -> Iterator[None]:
    """Use a session-local Windows kernel mutex without a shared lock path."""

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    create_mutex.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait_for_single_object.restype = wintypes.DWORD
    release_mutex = kernel32.ReleaseMutex
    release_mutex.argtypes = (wintypes.HANDLE,)
    release_mutex.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = create_mutex(None, False, f"Local\\write-project-docs-{identity}")
    if not handle:
        raise ValueError("无法创建 Windows 协调互斥量")
    acquired = False
    try:
        result = wait_for_single_object(handle, 0xFFFFFFFF)
        if result not in {0x00000000, 0x00000080}:
            raise ValueError("Windows 协调互斥量等待失败")
        acquired = True
        yield
    finally:
        if acquired:
            release_mutex(handle)
        close_handle(handle)


def _coordination_identity(target: Path) -> str:
    """Build a stable ordered-lock identity without the replaceable target inode."""

    try:
        parent = target.parent.resolve(strict=True)
        parent_state = parent.stat()
    except OSError as error:
        raise ValueError("无法确定协调锁目标目录") from error
    material = f"{parent_state.st_dev}:{parent_state.st_ino}"
    if os.name == "nt":  # pragma: no cover - Windows locks individual paths
        normalized_name = unicodedata.normalize(
            "NFC", os.path.normcase(target.name)
        ).casefold()
        material += f":{normalized_name}"
    return hashlib.sha256(material.encode("utf-8", "surrogatepass")).hexdigest()


def _set_descriptor_mode(descriptor: int, mode: int) -> None:
    """Apply POSIX permission bits or the Windows read-only attribute by handle."""

    if os.name != "nt":  # pragma: no branch - platform selection
        os.fchmod(descriptor, mode)
        return

    class FileBasicInfo(ctypes.Structure):
        _fields_ = (
            ("creation_time", ctypes.c_longlong),
            ("last_access_time", ctypes.c_longlong),
            ("last_write_time", ctypes.c_longlong),
            ("change_time", ctypes.c_longlong),
            ("file_attributes", wintypes.DWORD),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    get_information.restype = wintypes.BOOL
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    set_information.restype = wintypes.BOOL

    handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))
    information = FileBasicInfo()
    size = ctypes.sizeof(information)
    if not get_information(handle, 0, ctypes.byref(information), size):
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error))
    if mode & stat.S_IWRITE:
        information.file_attributes &= ~0x00000001
        if information.file_attributes == 0:
            information.file_attributes = 0x00000080
    else:
        information.file_attributes &= ~0x00000080
        information.file_attributes |= 0x00000001
    if not set_information(handle, 0, ctypes.byref(information), size):
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error))


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


@contextmanager
def _coordination_lock(
    target: Path, *, expected_identity: str | None = None
) -> Iterator[None]:
    """Serialize cooperating managed-file writers across inode replacement."""

    identity = _coordination_identity(target)
    if expected_identity is not None and identity != expected_identity:
        raise ValueError("协调目标目录在加锁前发生变化")
    if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
        with _windows_coordination_mutex(identity):
            if _coordination_identity(target) != identity:
                raise ValueError("协调目标目录在等待期间发生变化")
            yield
        return

    lock_directory = target.parent
    try:
        inspected = lock_directory.lstat()
    except OSError as error:
        raise ValueError("无法安全检查协调目标目录") from error
    if not stat.S_ISDIR(inspected.st_mode) or lock_directory.is_symlink():
        raise ValueError("协调目标目录不是普通目录")
    if _coordination_identity(target) != identity:
        raise ValueError("协调目标目录在打开前发生变化")

    descriptor: int | None = None
    locked = False
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    try:
        try:
            descriptor = os.open(lock_directory, flags)
            opened = os.fstat(descriptor)
            current = lock_directory.lstat()
            if (
                not stat.S_ISDIR(opened.st_mode)
                or not os.path.samestat(opened, current)
                or not os.path.samestat(inspected, opened)
            ):
                raise ValueError("协调目标目录在打开期间发生变化")
            _lock_descriptor(descriptor, exclusive=True)
            locked = True
            current = lock_directory.lstat()
            if not stat.S_ISDIR(current.st_mode) or not os.path.samestat(
                opened, current
            ):
                raise ValueError("协调目标目录在加锁期间发生变化")
        except ValueError:
            raise
        except OSError as error:
            raise ValueError("无法安全锁定协调目标目录") from error
        yield
    finally:
        if descriptor is not None:
            try:
                if locked:
                    _unlock_descriptor(descriptor)
            finally:
                os.close(descriptor)


def write_atomically(
    path: Path,
    text: str,
    expected: FileSnapshot,
    precommit_validate: Callable[[], None],
    *,
    input_snapshots: tuple[tuple[Path, FileSnapshot], ...] = (),
) -> None:
    """Coordinate writers, compare target/inputs, then atomically replace target."""

    temporary_path: Path | None = None
    temporary_descriptor: int | None = None
    commit_state = [False]
    unique_inputs = {
        candidate.absolute(): (candidate, snapshot)
        for candidate, snapshot in input_snapshots
        if candidate.absolute() != path.absolute()
    }
    with (
        _post_commit_error_boundary(path, lambda: commit_state[0]),
        ExitStack() as locks,
    ):
        coordination_paths = {
            _coordination_identity(candidate): candidate
            for candidate in (path, *(item[0] for item in unique_inputs.values()))
        }
        for _identity, candidate in sorted(coordination_paths.items()):
            locks.enter_context(
                _coordination_lock(candidate, expected_identity=_identity)
            )

        target_identity = (expected.device, expected.inode)
        input_lock_representatives: dict[
            tuple[int, int], tuple[Path, FileSnapshot]
        ] = {}
        for candidate, snapshot in unique_inputs.values():
            input_identity = (snapshot.device, snapshot.inode)
            if input_identity == target_identity:
                raise ValueError(f"{candidate.name} 不得是 {path.name} 的硬链接别名")
            prior = input_lock_representatives.get(input_identity)
            if prior is not None and prior[1] != snapshot:
                raise ValueError("绑定输入的硬链接快照不一致")
            input_lock_representatives[input_identity] = (candidate, snapshot)
        for candidate, _snapshot in sorted(
            input_lock_representatives.values(),
            key=lambda item: str(item[0].absolute()),
        ):
            if os.name != "nt":
                locks.enter_context(_locked_file(candidate, exclusive=False))

        try:
            if read_snapshot(path) != expected:
                raise ValueError(f"{path.name} 在写入期间发生变化")
            for candidate, snapshot in unique_inputs.values():
                if read_snapshot(candidate) != snapshot:
                    raise ValueError(f"{candidate.name} 在写入期间发生变化")
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
            _set_descriptor_mode(temporary_descriptor, expected.mode)
            os.fsync(temporary_descriptor)
            temporary_state = os.fstat(temporary_descriptor)
            current_temporary = temporary_path.lstat()
            if (
                not stat.S_ISREG(temporary_state.st_mode)
                or temporary_state.st_nlink != 1
                or not os.path.samestat(temporary_state, current_temporary)
                or temporary_state.st_size != len(encoded)
            ):
                raise ValueError("临时文件在写入期间发生变化")

            precommit_validate()
            if read_snapshot(path) != expected:
                raise ValueError(f"{path.name} 在写入期间发生变化")
            for candidate, snapshot in unique_inputs.values():
                if read_snapshot(candidate) != snapshot:
                    raise ValueError(f"{candidate.name} 在写入期间发生变化")
            before_content_check = os.fstat(temporary_descriptor)
            if (
                _metadata_changed(temporary_state, before_content_check)
                or stat.S_IMODE(before_content_check.st_mode) != expected.mode
            ):
                raise ValueError("临时文件在替换前发生变化")
            os.lseek(temporary_descriptor, 0, os.SEEK_SET)
            observed = bytearray()
            while len(observed) <= len(encoded):
                chunk = os.read(
                    temporary_descriptor,
                    min(64 * 1024, len(encoded) + 1 - len(observed)),
                )
                if not chunk:
                    break
                observed.extend(chunk)
            after_content_check = os.fstat(temporary_descriptor)
            if (
                bytes(observed) != encoded
                or _metadata_changed(temporary_state, after_content_check)
                or stat.S_IMODE(after_content_check.st_mode) != expected.mode
            ):
                raise ValueError("临时文件内容在替换前发生变化")
            current_temporary = temporary_path.lstat()
            if not stat.S_ISREG(current_temporary.st_mode) or not os.path.samestat(
                temporary_state, current_temporary
            ):
                raise ValueError("临时文件在替换前发生变化")
            if os.name == "nt":  # pragma: no cover - Windows denies open-file replace
                os.close(temporary_descriptor)
                temporary_descriptor = None
            os.replace(temporary_path, path)
            commit_state[0] = True
            temporary_path = None
            try:
                replaced_state = path.lstat()
                if not stat.S_ISREG(replaced_state.st_mode) or not os.path.samestat(
                    temporary_state, replaced_state
                ):
                    raise AtomicWriteCommittedError(
                        f"{path.name} 已替换，但替换结果身份无效"
                    )
                _fsync_parent_directory(path)
            except AtomicWriteCommittedError:
                raise
            except (OSError, ValueError) as error:
                raise AtomicWriteCommittedError(
                    f"{path.name} 已替换，但提交后校验失败"
                ) from error
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
