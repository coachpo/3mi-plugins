"""Bounded subprocess execution and immutable artifact evidence."""

from __future__ import annotations

import codecs
import ctypes
import hashlib
import ntpath
import os
import re
import select
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from adapter_paths import (
    is_within,
    path_has_symlink_component,
    path_has_traversal,
    path_uses_symlink,
    relative_to_root,
    resolve_project_path,
)
from journal_state import Campaign
from model import (
    ARTIFACT_MANIFEST_VERSION,
    SCHEMA_VERSION,
    SCRIPT_VERSION,
    CampaignError,
    atomic_write_json,
    atomic_write_text,
    canonical_bytes,
    has_secret_like,
    public_message,
    read_regular_bytes,
    redact_text,
    sha256_bytes,
)

MAX_OUTPUT_BYTES = 5 * 1024 * 1024
OUTPUT_READ_BYTES = 64 * 1024
SECRET_SCAN_CARRY_CHARS = 4096
READER_JOIN_SECONDS = 2.0
PROCESS_SAMPLE_SECONDS = 0.005
OUTPUT_TRUNCATION_MARKER = b"\n<OUTPUT_TRUNCATED>\n"
MAX_ARTIFACT_FILES = 4096
MAX_ARTIFACT_FILE_BYTES = 256 * 1024 * 1024
MAX_ARTIFACT_TOTAL_BYTES = 256 * 1024 * 1024
PR_SET_CHILD_SUBREAPER = 36
SECRET_ENV_PATTERN = re.compile(
    r"(?i)(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL|AUTH)"
)
SAFE_CHILD_ENV_KEYS = {
    "COMSPEC",
    "LANG",
    "PATH",
    "PATHEXT",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "WINDIR",
}
SECRET_ASSIGNMENT_PREFIX = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9_])"
    r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret|credential)"
    r"\s*(?::|=)?\s*$"
)


def artifact_metadata_is_reparse(metadata: os.stat_result) -> bool:
    """Return whether metadata identifies a Windows reparse point."""

    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def artifact_tree_entries(
    artifact_dir: Path,
) -> list[tuple[Path, os.stat_result]]:
    """Enumerate a bounded artifact tree without following links/reparse points."""

    try:
        root_metadata = artifact_dir.lstat()
    except OSError as exc:
        raise CampaignError("cannot inspect artifact directory safely") from exc
    if (
        stat.S_ISLNK(root_metadata.st_mode)
        or artifact_metadata_is_reparse(root_metadata)
        or not stat.S_ISDIR(root_metadata.st_mode)
    ):
        raise CampaignError("artifact directory is a symlink/reparse or non-directory")

    observed: list[tuple[Path, os.stat_result]] = []
    pending = [artifact_dir]
    while pending:
        directory = pending.pop()
        try:
            before = directory.lstat()
            if (
                stat.S_ISLNK(before.st_mode)
                or artifact_metadata_is_reparse(before)
                or not stat.S_ISDIR(before.st_mode)
            ):
                raise CampaignError(
                    "artifact directory changed to a symlink/reparse or non-directory"
                )
            with os.scandir(str(directory)) as entries:
                for entry in entries:
                    metadata = entry.stat(follow_symlinks=False)
                    path = directory / entry.name
                    observed.append((path, metadata))
                    if len(observed) > MAX_ARTIFACT_FILES:
                        raise CampaignError(
                            "case artifact count exceeds the safe limit"
                        )
                    if (
                        stat.S_ISDIR(metadata.st_mode)
                        and not stat.S_ISLNK(metadata.st_mode)
                        and not artifact_metadata_is_reparse(metadata)
                    ):
                        pending.append(path)
            after = directory.lstat()
            if (
                stat.S_ISLNK(after.st_mode)
                or artifact_metadata_is_reparse(after)
                or not stat.S_ISDIR(after.st_mode)
                or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise CampaignError("artifact directory changed while enumerated")
        except CampaignError:
            raise
        except OSError as exc:
            raise CampaignError("cannot enumerate artifact safely") from exc
    return observed


class _BoundedStreamCollector:
    """Drain one pipe while retaining only a bounded, UTF-8-safe prefix."""

    def __init__(self, handle: Any) -> None:
        self.handle = handle
        self._prefix = bytearray()
        self._total_bytes = 0
        self._truncated = False
        self._secret_detected = False
        self._scan_carry = ""
        self._pending_assignment = False
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._error = False
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self._drain, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _scan_text(self, decoded: str) -> None:
        if not decoded:
            return
        if self._pending_assignment:
            for character in decoded:
                if character.isspace():
                    continue
                if character not in ",;":
                    self._secret_detected = True
                self._pending_assignment = False
                break
        window = self._scan_carry + decoded
        if has_secret_like(window):
            self._secret_detected = True
        assignment_window = window.rstrip()
        if SECRET_ASSIGNMENT_PREFIX.search(assignment_window):
            self._pending_assignment = True
        self._scan_carry = window[-SECRET_SCAN_CARRY_CHARS:]

    def _drain(self) -> None:
        try:
            read = getattr(self.handle, "read1", self.handle.read)
            while True:
                chunk = read(OUTPUT_READ_BYTES)
                if not chunk:
                    break
                with self._lock:
                    self._total_bytes += len(chunk)
                    remaining = MAX_OUTPUT_BYTES - len(self._prefix)
                    if remaining > 0:
                        self._prefix.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        self._truncated = True
                    self._scan_text(self._decoder.decode(chunk, final=False))
        except (OSError, ValueError):
            with self._lock:
                self._error = True
        finally:
            with self._lock:
                try:
                    self._scan_text(self._decoder.decode(b"", final=True))
                except UnicodeError:
                    # The replacement decoder should not fail. Treat a platform
                    # decoder anomaly as an incomplete capture if it ever does.
                    self._error = True

    def close(self) -> None:
        try:
            self.handle.close()
        except OSError:
            pass

    def snapshot(self) -> tuple[str, bool, bool, bool]:
        with self._lock:
            prefix = bytes(self._prefix)
            secret_detected = self._secret_detected
            truncated = self._truncated or self._total_bytes > MAX_OUTPUT_BYTES
            capture_ok = not self._error and not self.thread.is_alive()

        text = prefix.decode("utf-8", "replace")
        text, saved_secret = redact_text(text)
        secret_detected = secret_detected or saved_secret
        encoded = text.encode("utf-8", "replace")
        if len(encoded) > MAX_OUTPUT_BYTES:
            truncated = True
        if truncated:
            retained_limit = MAX_OUTPUT_BYTES - len(OUTPUT_TRUNCATION_MARKER)
            encoded = encoded[:retained_limit]
            text = encoded.decode("utf-8", "ignore") + OUTPUT_TRUNCATION_MARKER.decode(
                "ascii"
            )
        else:
            text = encoded.decode("utf-8", "strict")
        return text, secret_detected, truncated, capture_ok


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / ("." + path.name + ".redact-" + uuid.uuid4().hex)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(str(temporary), flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _stream_file(path: Path, redact: bool) -> tuple[int, str, bool]:
    """Hash and secret-scan a file with bounded memory; rewrite only if needed."""

    total = 0
    digest = hashlib.sha256()
    scanner = _BoundedStreamCollector.__new__(_BoundedStreamCollector)
    scanner._secret_detected = False
    scanner._scan_carry = ""
    scanner._pending_assignment = False
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    descriptor: int | None = None
    try:
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or artifact_metadata_is_reparse(metadata)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise CampaignError("artifact is not a regular non-link file")
        if metadata.st_size > MAX_ARTIFACT_FILE_BYTES:
            raise CampaignError("artifact file exceeds the safe size limit")
        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        descriptor = os.open(str(path), flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or artifact_metadata_is_reparse(opened)
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
        ):
            raise CampaignError("artifact changed while it was opened")
        with os.fdopen(descriptor, "rb", buffering=0, closefd=True) as handle:
            descriptor = None
            while True:
                chunk = handle.read(OUTPUT_READ_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
                scanner._scan_text(decoder.decode(chunk, final=False))
            scanner._scan_text(decoder.decode(b"", final=True))
        after = path.lstat()
        if (
            stat.S_ISLNK(after.st_mode)
            or artifact_metadata_is_reparse(after)
            or not stat.S_ISREG(after.st_mode)
            or (after.st_dev, after.st_ino) != (metadata.st_dev, metadata.st_ino)
            or after.st_size != total
        ):
            raise CampaignError("artifact changed while it was read")
    except CampaignError:
        raise
    except OSError as exc:
        raise CampaignError("cannot read artifact safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    found = scanner._secret_detected
    if found and redact:
        # Exact byte-preserving streaming substitution for all current patterns
        # is not generally possible with unbounded regex whitespace. Replace the
        # whole unsafe artifact with a fixed marker, never buffering its contents.
        marker = b"<REDACTED_SECRET_LIKE_ARTIFACT>\n"
        _atomic_write_bytes(path, marker)
        total = len(marker)
        digest = hashlib.sha256(marker)
    return total, "sha256:" + digest.hexdigest(), found


def _absolute_ps_path() -> str | None:
    for candidate in ("/bin/ps", "/usr/bin/ps"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _linux_process_table() -> dict[int, tuple[int, int, str]] | None:
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None
    table: dict[int, tuple[int, int, str]] = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            line = (entry / "stat").read_text(encoding="ascii")
            fields = line[line.rfind(")") + 2 :].split()
            table[int(entry.name)] = (int(fields[1]), int(fields[2]), fields[0])
        except (OSError, ValueError, IndexError):
            continue
    return table


def _enable_linux_subreaper() -> bool:
    """Adopt orphaned grandchildren so double-fork cannot escape cleanup."""

    if not sys.platform.startswith("linux"):
        return True
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    except (AttributeError, OSError):
        return False


class _DarwinProcBSDInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _darwin_process_table() -> dict[int, tuple[int, int, str]] | None:
    if sys.platform != "darwin":
        return None
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        libproc.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        libproc.proc_listallpids.restype = ctypes.c_int
        libproc.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        libproc.proc_pidinfo.restype = ctypes.c_int
        count = libproc.proc_listallpids(None, 0)
        if count <= 0:
            return None
        pids = (ctypes.c_int * (count + 128))()
        returned = libproc.proc_listallpids(pids, ctypes.sizeof(pids))
        if returned <= 0:
            return None
    except (AttributeError, OSError):
        return None

    status_names = {5: "Z"}
    table: dict[int, tuple[int, int, str]] = {}
    for pid in pids[:returned]:
        if pid <= 0:
            continue
        info = _DarwinProcBSDInfo()
        size = libproc.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        if size != ctypes.sizeof(info):
            continue
        table[pid] = (
            int(info.pbi_ppid),
            int(info.pbi_pgid),
            status_names.get(int(info.pbi_status), "?"),
        )
    return table


def _posix_process_table() -> dict[int, tuple[int, int, str]] | None:
    """Return pid -> (ppid, pgid, state) without consulting PATH."""

    native = _linux_process_table()
    if native is None:
        native = _darwin_process_table()
    if native is not None:
        return native
    ps_path = _absolute_ps_path()
    if ps_path is None:
        return None
    try:
        completed = subprocess.run(
            [ps_path, "-axo", "pid=,ppid=,pgid=,stat="],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    table: dict[int, tuple[int, int, str]] = {}
    try:
        output = completed.stdout.decode("ascii", "strict")
        for line in output.splitlines():
            fields = line.split(None, 3)
            if len(fields) != 4:
                return None
            pid, ppid, pgid = (int(field) for field in fields[:3])
            table[pid] = (ppid, pgid, fields[3])
    except (UnicodeDecodeError, ValueError):
        return None
    return table


def _descendant_pids(root_pid: int, table: dict[int, tuple[int, int, str]]) -> set[int]:
    descendants: set[int] = set()
    frontier = {root_pid}
    while frontier:
        children = {
            pid
            for pid, (ppid, _pgid, _state) in table.items()
            if ppid in frontier and pid not in descendants and pid != root_pid
        }
        if not children:
            break
        descendants.update(children)
        frontier = children
    return descendants


def _send_signal(pid: int, requested_signal: int) -> bool:
    try:
        os.kill(pid, requested_signal)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        return False


class _PosixProcessMonitor:
    """Continuously remember descendants before they can reparent or escape."""

    def __init__(self, root_pid: int) -> None:
        self.root_pid = root_pid
        self.known: set[int] = set()
        self.escaped = False
        self.enumeration_failed = False
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._kqueue: Any = None
        self.tracking_unavailable = False
        self.thread = threading.Thread(target=self._watch, daemon=True)

    def start(self) -> None:
        if sys.platform == "darwin" and hasattr(select, "kqueue"):
            try:
                self._kqueue = select.kqueue()
                event = select.kevent(
                    self.root_pid,
                    filter=select.KQ_FILTER_PROC,
                    flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                    fflags=select.KQ_NOTE_FORK
                    | select.KQ_NOTE_TRACK
                    | select.KQ_NOTE_EXIT,
                )
                self._kqueue.control([event], 0, 0)
            except (OSError, ValueError):
                if self._kqueue is not None:
                    self._kqueue.close()
                    self._kqueue = None
                self.tracking_unavailable = True
        elif sys.platform.startswith("linux") and not _enable_linux_subreaper():
            self.enumeration_failed = True
        self._sample()
        self.thread.start()

    def _sample(self) -> None:
        table = _posix_process_table()
        if table is None:
            with self._lock:
                self.enumeration_failed = True
            return
        with self._lock:
            ancestors = {self.root_pid} | self.known
            discovered = {
                pid
                for pid, (ppid, pgid, _state) in table.items()
                if pid != self.root_pid and (ppid in ancestors or pgid == self.root_pid)
            }
            # Close over descendants of processes learned in this same sample.
            while True:
                more = {
                    pid
                    for pid, (ppid, _pgid, _state) in table.items()
                    if pid != self.root_pid
                    and ppid in (ancestors | discovered)
                    and pid not in discovered
                }
                if not more:
                    break
                discovered.update(more)
            self.known.update(discovered)
            if any(
                table[pid][1] != self.root_pid for pid in discovered if pid in table
            ):
                self.escaped = True

    def _watch(self) -> None:
        while not self._stop.is_set():
            if self._kqueue is not None:
                try:
                    events = self._kqueue.control(None, 64, PROCESS_SAMPLE_SECONDS)
                    with self._lock:
                        for event in events:
                            if event.fflags & getattr(select, "KQ_NOTE_TRACKERR", 0):
                                self.enumeration_failed = True
                    if events:
                        # EVFILT_PROC data is event-specific (for NOTE_EXIT it is
                        # not a child PID). Use it only as a wakeup and derive
                        # identities from the native process table.
                        self._sample()
                except (OSError, ValueError):
                    with self._lock:
                        self.enumeration_failed = True
            elif self._stop.wait(PROCESS_SAMPLE_SECONDS):
                break
            self._sample()

    def stop(self) -> tuple[set[int], bool, bool, bool]:
        # A final sample closes the normal-exit race before the watcher stops.
        self._sample()
        self._stop.set()
        self.thread.join(1.0)
        if self._kqueue is not None:
            self._kqueue.close()
            self._kqueue = None
        with self._lock:
            return (
                set(self.known),
                self.escaped,
                self.enumeration_failed,
                self.tracking_unavailable,
            )


def _terminate_posix_tree(
    process: subprocess.Popen[bytes],
    extra_pids: set[int] | None = None,
    escaped_seen: bool = False,
    enumeration_failed: bool = False,
) -> bool:
    """Kill the isolated group and visible descendants, failing closed on escape."""

    root_pid = process.pid
    certain = not enumeration_failed
    escaped_group = escaped_seen
    known: set[int] = set(extra_pids or ())
    previous_discovered: set[int] | None = None

    # Freeze the isolated group before walking PPID relationships. A descendant
    # that has created another session is also stopped as soon as it is found.
    try:
        os.killpg(root_pid, signal.SIGSTOP)
    except ProcessLookupError:
        pass
    except OSError:
        certain = False

    for _ in range(3):
        table = _posix_process_table()
        if table is None:
            certain = False
            break
        descendants = _descendant_pids(root_pid, table)
        group_members = {
            pid for pid, (_ppid, pgid, _state) in table.items() if pgid == root_pid
        }
        discovered = (descendants | group_members) - {root_pid}
        for pid in discovered - known:
            if not _send_signal(pid, signal.SIGSTOP):
                certain = False
        known.update(discovered)
        escaped_group = escaped_group or any(
            table[pid][1] != root_pid for pid in descendants if pid in table
        )
        escaped_group = escaped_group or any(
            table[pid][1] != root_pid for pid in known if pid in table
        )
        if previous_discovered == discovered:
            break
        previous_discovered = discovered

    for pid in sorted(known, reverse=True):
        if not _send_signal(pid, signal.SIGKILL):
            certain = False
    try:
        os.killpg(root_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        if process.poll() is None:
            certain = False
            try:
                process.kill()
            except OSError:
                pass

    try:
        process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        certain = False

    final_table = _posix_process_table()
    if final_table is None:
        certain = False
    else:
        for pid in known:
            entry = final_table.get(pid)
            if entry is not None and not entry[2].startswith("Z"):
                certain = False
        for pid, (_ppid, pgid, state) in final_table.items():
            if pid != root_pid and pgid == root_pid and not state.startswith("Z"):
                certain = False

    # POSIX process groups cannot account for a descendant that successfully
    # escaped into another session. We terminate every escaped PID observed, but
    # do not claim cleanup certainty because a double-fork can evade PPID scans.
    return certain and not escaped_group


def terminate_process_tree(
    process: subprocess.Popen[bytes],
    extra_pids: set[int] | None = None,
    escaped_seen: bool = False,
    enumeration_failed: bool = False,
) -> bool:
    """Terminate the isolated command tree; return whether cleanup was certain."""

    if os.name == "posix":
        return _terminate_posix_tree(
            process, extra_pids, escaped_seen, enumeration_failed
        )

    # Windows has no stdlib Job Object wrapper. taskkill /T is the OS-provided
    # tree primitive; a direct kill remains the fail-safe when it is unavailable.
    if os.name == "nt":  # pragma: no cover - exercised with mocks on POSIX
        system_directory = _trusted_windows_system_directory()
        taskkill = (
            ntpath.join(system_directory, "taskkill.exe")
            if system_directory is not None
            else None
        )
        certain = False
        try:
            if taskkill is not None and ntpath.isabs(taskkill):
                completed = subprocess.run(
                    [taskkill, "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                )
                certain = completed.returncode == 0
        except (OSError, subprocess.SubprocessError):
            certain = False
        if process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                return False
        return certain and process.poll() is not None

    if process.poll() is None:  # pragma: no cover - unknown Python platform
        process.kill()
        process.wait()
    return False


def _trusted_windows_system_directory() -> str | None:
    if os.name != "nt":
        return None
    try:  # pragma: no cover - exercised through mocks on POSIX
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
        if length <= 0 or length >= len(buffer):
            return None
        directory = buffer.value
        return directory if ntpath.isabs(directory) else None
    except (AttributeError, OSError, ValueError):
        return None


def safe_child_environment(artifact_dir: Path) -> dict[str, str]:
    environment: dict[str, str] = {}
    for key, value in os.environ.items():
        uppercase = key.upper()
        if (
            uppercase in SAFE_CHILD_ENV_KEYS or uppercase.startswith("LC_")
        ) and not SECRET_ENV_PATTERN.search(key):
            environment[key] = value
    environment["CLOSED_LOOP_EVIDENCE_DIR"] = str(artifact_dir)
    environment["CLOSED_LOOP_CASE_ID"] = artifact_dir.name
    return environment


def _join_collectors(collectors: list[_BoundedStreamCollector], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    for collector in collectors:
        collector.thread.join(max(0.0, deadline - time.monotonic()))
    return all(not collector.thread.is_alive() for collector in collectors)


def _finish_stream_capture(
    process: subprocess.Popen[bytes],
    collectors: list[_BoundedStreamCollector],
    tree_cleanup_certain: bool,
    monitor: _PosixProcessMonitor | None = None,
) -> tuple[list[tuple[str, bool, bool, bool]], bool]:
    """Finish both drains without waiting forever on inherited pipe handles."""

    known: set[int] = set()
    escaped = False
    enumeration_failed = False
    if not _join_collectors(collectors, 0.25):
        if monitor is not None:
            known, escaped, enumeration_failed, _tracking_unavailable = monitor.stop()
            monitor = None
        tree_cleanup_certain = (
            terminate_process_tree(process, known, escaped, enumeration_failed)
            and tree_cleanup_certain
        )
        if not _join_collectors(collectors, READER_JOIN_SECONDS):
            tree_cleanup_certain = False
    elif monitor is not None:
        known, escaped, enumeration_failed, _tracking_unavailable = monitor.stop()
        table = _posix_process_table()
        live_known = bool(
            table is not None
            and any(pid in table and not table[pid][2].startswith("Z") for pid in known)
        )
        if live_known or escaped or enumeration_failed:
            tree_cleanup_certain = (
                terminate_process_tree(process, known, escaped, enumeration_failed)
                and tree_cleanup_certain
            )

    snapshots = [collector.snapshot() for collector in collectors]
    for collector in collectors:
        if not collector.thread.is_alive():
            collector.close()
    if not all(snapshot[3] for snapshot in snapshots):
        tree_cleanup_certain = False
    if escaped:
        tree_cleanup_certain = False
    return snapshots, tree_cleanup_certain


def evidence_file_path(artifact_dir: Path, relative: str) -> Path:
    if path_has_symlink_component(artifact_dir):
        raise CampaignError("case artifact directory uses a symlink/reparse path")
    if path_has_traversal(relative) or Path(relative).is_absolute():
        raise CampaignError("evidence path escapes case artifact")
    unresolved = artifact_dir / relative
    if path_uses_symlink(unresolved, artifact_dir):
        raise CampaignError("evidence path uses a symlink/reparse point")
    candidate = Path(os.path.realpath(str(unresolved)))
    artifact_real = Path(os.path.realpath(str(artifact_dir)))
    if not is_within(candidate, artifact_real):
        raise CampaignError("evidence path escapes case artifact")
    return candidate


def inspect_evidence(
    artifact_dir: Path,
    contract: dict[str, list[str]],
    redact_files: bool = True,
) -> tuple[dict[str, Any], bool]:
    required = contract.get("requiredFiles", [])
    non_empty = set(contract.get("nonEmptyFiles", []))
    files: list[dict[str, Any]] = []
    missing: list[str] = []
    empty: list[str] = []
    secret_detected = False
    for relative in required:
        path = evidence_file_path(artifact_dir, relative)
        if (
            path_uses_symlink(artifact_dir / relative, artifact_dir)
            or not path.is_file()
        ):
            missing.append(relative)
            continue
        try:
            size, digest, found = _stream_file(path, redact_files)
        except CampaignError:
            missing.append(relative)
            continue
        if relative in non_empty and size == 0:
            empty.append(relative)
        if found:
            secret_detected = True
        files.append(
            {
                "path": relative,
                "size": size,
                "sha256": digest,
            }
        )
    report = {
        "requiredFiles": list(required),
        "nonEmptyFiles": sorted(non_empty),
        "missingFiles": sorted(missing),
        "emptyFiles": sorted(empty),
        "files": files,
        "secretLikeContent": secret_detected,
    }
    return report, secret_detected


def scan_artifact_text_files(artifact_dir: Path, redact_files: bool = True) -> bool:
    """Redact or detect recognizable secrets in any text artifact, not only required files."""

    found_any = False
    total_bytes = 0
    for path, metadata in artifact_tree_entries(artifact_dir):
        if stat.S_ISLNK(metadata.st_mode) or artifact_metadata_is_reparse(metadata):
            raise CampaignError("artifact tree contains a symlink/reparse point")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise CampaignError("artifact tree contains a non-regular file")
        if path.name == "result.json":
            continue
        total_bytes += metadata.st_size
        if total_bytes > MAX_ARTIFACT_TOTAL_BYTES:
            raise CampaignError("case artifacts exceed the safe total size limit")
        _size, _digest, found = _stream_file(path, redact_files)
        if not found:
            continue
        found_any = True
    return found_any


def write_case_result(artifact_dir: Path, result: dict[str, Any]) -> None:
    atomic_write_json(artifact_dir / "result.json", result)


def write_artifact_manifest(
    artifact_dir: Path, artifact_relative: str
) -> tuple[dict[str, Any], list[str]]:
    """Bind every regular case artifact except the manifest itself."""

    files: list[dict[str, Any]] = []
    unsafe: list[str] = []
    total_bytes = 0
    entries = artifact_tree_entries(artifact_dir)
    for path, metadata in sorted(entries, key=lambda item: item[0].as_posix()):
        relative = path.relative_to(artifact_dir).as_posix()
        if relative == "artifact-manifest.json":
            continue
        if stat.S_ISLNK(metadata.st_mode) or artifact_metadata_is_reparse(metadata):
            unsafe.append(relative)
            continue
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise CampaignError("artifact is not a regular file: " + relative)
        size, digest, _found = _stream_file(path, False)
        total_bytes += size
        if total_bytes > MAX_ARTIFACT_TOTAL_BYTES:
            raise CampaignError("case artifacts exceed the safe total size limit")
        files.append({"relativePath": relative, "size": size, "sha256": digest})
    manifest = {
        "artifactManifestVersion": ARTIFACT_MANIFEST_VERSION,
        "files": files,
    }
    manifest_path = artifact_dir / "artifact-manifest.json"
    atomic_write_json(manifest_path, manifest)
    content = read_regular_bytes(
        manifest_path,
        label="artifact manifest",
        max_bytes=MAX_ARTIFACT_FILE_BYTES,
    )
    return (
        {
            "relativePath": artifact_relative + "/artifact-manifest.json",
            "size": len(content),
            "sha256": sha256_bytes(content),
        },
        unsafe,
    )


def _start_case_process(
    argv: list[str],
    project_root: Path,
    cwd_value: str,
    cwd_label: str,
    environment: dict[str, str],
) -> subprocess.Popen[bytes]:
    """Start an isolated child without leaving an interrupt-before-return gap."""

    popen_options: dict[str, Any] = {}
    if os.name == "posix":
        popen_options["start_new_session"] = True
    elif os.name == "nt":  # pragma: no cover - exercised with mocks
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    process: subprocess.Popen[bytes] | None = None
    previous_mask: set[signal.Signals] | None = None
    if os.name == "posix" and hasattr(signal, "pthread_sigmask"):
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    try:
        # Repeat path checks at the execution boundary. Adapter validation may
        # have happened much earlier, and an existing component can be replaced
        # with a symlink/reparse point while the campaign remains loaded.
        if path_has_symlink_component(project_root):
            raise CampaignError("projectRoot uses a symlink/reparse path at execution")
        unresolved_cwd = project_root / cwd_value
        if path_uses_symlink(unresolved_cwd, project_root):
            raise CampaignError(cwd_label + " uses a symlink/reparse path at execution")
        cwd = resolve_project_path(project_root, cwd_value, cwd_label)
        root_real = Path(os.path.realpath(str(project_root)))
        if root_real != project_root or not is_within(cwd, root_real):
            raise CampaignError(cwd_label + " changed outside projectRoot at execution")
        if not cwd.is_dir():
            raise CampaignError(cwd_label + " is not a directory at execution")
        if path_has_symlink_component(project_root) or path_uses_symlink(
            unresolved_cwd, project_root
        ):
            raise CampaignError(
                cwd_label + " changed to a symlink/reparse path at execution"
            )
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            **popen_options,
        )
        if previous_mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            previous_mask = None
        return process
    except BaseException:
        if process is not None:
            terminate_process_tree(process)
        raise
    finally:
        if previous_mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def execute_case(
    campaign: Campaign,
    attempt_id: str,
    case: dict[str, Any],
    ordinal: int,
    source_fingerprint: str,
    round_mode: str,
) -> dict[str, Any]:
    case_id = case["id"]
    run_id, artifact_dir = campaign.allocate_case_artifact(attempt_id, case_id, ordinal)
    artifact_relative = relative_to_root(campaign.adapter.campaign_root, artifact_dir)
    campaign.commit(
        "case_started",
        {
            "attemptId": attempt_id,
            "runId": run_id,
            "caseId": case_id,
            "ordinal": ordinal,
            "artifactDir": artifact_relative,
            "sourceFingerprint": source_fingerprint,
        },
    )

    started = time.monotonic()
    artifact_identity = artifact_dir.lstat()
    stdout_text = ""
    stderr_text = ""
    stdout_secret = False
    stderr_secret = False
    stdout_truncated = False
    stderr_truncated = False
    exit_code: int | None = None
    timed_out = False
    command_error: str | None = None
    execution_safety_error: str | None = None
    tree_cleanup_certain = True
    try:
        process = _start_case_process(
            list(case["argv"]),
            campaign.adapter.project_root,
            case.get("cwd", "."),
            "case " + case_id + " cwd",
            safe_child_environment(artifact_dir),
        )
        if process.stdout is None or process.stderr is None:  # pragma: no cover
            tree_cleanup_certain = terminate_process_tree(process)
            raise CampaignError("command output pipes could not be created")

        process_monitor: _PosixProcessMonitor | None = None
        if os.name == "posix":
            process_monitor = _PosixProcessMonitor(process.pid)
            process_monitor.start()
        collectors: list[_BoundedStreamCollector] = []
        try:
            for handle in (process.stdout, process.stderr):
                collector = _BoundedStreamCollector(handle)
                collector.start()
                collectors.append(collector)
            try:
                exit_code = process.wait(timeout=float(case.get("timeoutSeconds", 60)))
            except subprocess.TimeoutExpired:
                timed_out = True
                command_error = "command timed out"
                known: set[int] = set()
                escaped = False
                enumeration_failed = False
                if process_monitor is not None:
                    (
                        known,
                        escaped,
                        enumeration_failed,
                        _tracking_unavailable,
                    ) = process_monitor.stop()
                    process_monitor = None
                tree_cleanup_certain = terminate_process_tree(
                    process, known, escaped, enumeration_failed
                )
            except KeyboardInterrupt:
                raise
            except BaseException as exc:
                if isinstance(exc, (SystemExit, GeneratorExit)):
                    raise
                raise CampaignError("command execution failed safely") from exc

            snapshots, tree_cleanup_certain = _finish_stream_capture(
                process, collectors, tree_cleanup_certain, process_monitor
            )
            process_monitor = None
            (
                (stdout_text, stdout_secret, stdout_truncated, stdout_ok),
                (stderr_text, stderr_secret, stderr_truncated, stderr_ok),
            ) = snapshots
            if not stdout_ok or not stderr_ok:
                command_error = command_error or "command output capture was incomplete"
        except BaseException as exc:
            # Collector startup itself can fail after the child exists. Always
            # clean up before propagating, including on an asynchronous interrupt.
            known = set()
            escaped = False
            enumeration_failed = False
            if process_monitor is not None:
                known, escaped, enumeration_failed, _tracking_unavailable = (
                    process_monitor.stop()
                )
            terminate_process_tree(process, known, escaped, enumeration_failed)
            _join_collectors(collectors, READER_JOIN_SECONDS)
            if isinstance(
                exc, (KeyboardInterrupt, SystemExit, GeneratorExit, CampaignError)
            ):
                raise
            raise CampaignError("command execution failed safely") from exc
    except FileNotFoundError:
        command_error = "command executable was not found"
    except PermissionError:
        command_error = "command executable was not permitted"
    except CampaignError as exc:
        execution_safety_error = public_message(exc)
    except OSError:
        command_error = "command could not be started"
    duration_ms = int((time.monotonic() - started) * 1000)

    try:
        current_identity = artifact_dir.lstat()
        artifact_safe = (
            not artifact_dir.is_symlink()
            and current_identity.st_dev == artifact_identity.st_dev
            and current_identity.st_ino == artifact_identity.st_ino
            and not path_has_symlink_component(artifact_dir)
        )
    except OSError:
        artifact_safe = False
    if not artifact_safe:
        # Never follow a case-controlled replacement. Restore a fresh directory
        # at the already journal-bound path only when the parent remains trusted.
        parent = artifact_dir.parent
        if path_has_symlink_component(parent) or not parent.is_dir():
            raise CampaignError("case artifact parent became unsafe during execution")
        if artifact_dir.exists() or artifact_dir.is_symlink():
            quarantine = parent / (
                artifact_dir.name + ".unsafe-" + uuid.uuid4().hex[:8]
            )
            os.replace(artifact_dir, quarantine)
        artifact_dir.mkdir(mode=0o700)
        execution_safety_error = "case artifact directory changed during execution"

    atomic_write_text(artifact_dir / "stdout.txt", stdout_text)
    atomic_write_text(artifact_dir / "stderr.txt", stderr_text)
    evidence_error: str | None = None
    try:
        evidence_report, evidence_secret = inspect_evidence(
            artifact_dir, case.get("evidence") or {}
        )
    except CampaignError as exc:
        contract = case.get("evidence") or {}
        evidence_report = {
            "requiredFiles": list(contract.get("requiredFiles", [])),
            "nonEmptyFiles": list(contract.get("nonEmptyFiles", [])),
            "missingFiles": list(contract.get("requiredFiles", [])),
            "emptyFiles": [],
            "files": [],
            "secretLikeContent": False,
        }
        evidence_secret = False
        evidence_error = public_message(exc)
    try:
        artifact_secret = scan_artifact_text_files(artifact_dir, redact_files=True)
    except CampaignError as exc:
        artifact_secret = False
        evidence_error = public_message(exc)
    secret_detected = (
        stdout_secret or stderr_secret or evidence_secret or artifact_secret
    )

    source_after: str | None
    source_error: str | None = None
    try:
        source_after = campaign.current_source()
    except CampaignError:
        source_after = None
        source_error = "source fingerprint could not be recomputed"
    catalog_drift = campaign.catalog_drift_reason()

    if execution_safety_error:
        status = "BLOCKED"
        reason = execution_safety_error
    elif catalog_drift:
        status = "BLOCKED"
        reason = catalog_drift
    elif source_error:
        status = "BLOCKED"
        reason = source_error
    elif (
        round_mode in {"initial", "retest", "regression"}
        and source_after != source_fingerprint
    ):
        status = "BLOCKED"
        reason = "source fingerprint drifted during execution"
    elif not tree_cleanup_certain:
        status = "BLOCKED"
        reason = "command process-tree cleanup could not be verified"
    elif secret_detected:
        status = "BLOCKED"
        reason = "secret-like output or evidence detected; output was redacted"
    elif evidence_error:
        status = "BLOCKED"
        reason = evidence_error
    elif command_error:
        status = "FAILED"
        reason = command_error
    elif timed_out:
        status = "FAILED"
        reason = "command timed out"
    elif exit_code != 0:
        status = "FAILED"
        reason = "command exited non-zero"
    elif evidence_report["missingFiles"] or evidence_report["emptyFiles"]:
        status = "FAILED"
        reason = "evidence contract not satisfied"
    else:
        status = "PASS"
        reason = None
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "kernelVersion": SCRIPT_VERSION,
        "runId": run_id,
        "caseId": case_id,
        "round": round_mode,
        "status": status,
        "exitCode": exit_code,
        "timedOut": timed_out,
        "durationMs": duration_ms,
        "reason": reason,
        "argvFingerprint": sha256_bytes(canonical_bytes(case["argv"])),
        "sourceFingerprintBefore": source_fingerprint,
        "sourceFingerprintAfter": source_after,
        "stdoutSha256": sha256_bytes(stdout_text.encode("utf-8")),
        "stderrSha256": sha256_bytes(stderr_text.encode("utf-8")),
        "secretLikeOutput": secret_detected,
        "secretDetected": secret_detected,
        "stdoutTruncated": stdout_truncated,
        "stderrTruncated": stderr_truncated,
        "evidence": evidence_report,
    }
    write_case_result(artifact_dir, result)
    try:
        artifact_manifest, unsafe_artifacts = write_artifact_manifest(
            artifact_dir, artifact_relative
        )
    except CampaignError as exc:
        status = "BLOCKED"
        reason = public_message(exc)
        result["status"] = status
        result["reason"] = reason
        # Replace oversized/unrepresentable non-kernel artifacts so the final
        # terminal artifact remains bounded and can itself be audited.
        try:
            cleanup_entries = artifact_tree_entries(artifact_dir)
        except CampaignError:
            cleanup_entries = []
        for path, metadata in cleanup_entries:
            if stat.S_ISREG(metadata.st_mode) and path.name not in {
                "stdout.txt",
                "stderr.txt",
                "result.json",
                "artifact-manifest.json",
            }:
                try:
                    if metadata.st_size > MAX_ARTIFACT_FILE_BYTES:
                        _atomic_write_bytes(path, b"<ARTIFACT_REJECTED_OVERSIZE>\n")
                except OSError:
                    continue
        write_case_result(artifact_dir, result)
        artifact_manifest, unsafe_artifacts = write_artifact_manifest(
            artifact_dir, artifact_relative
        )
    if unsafe_artifacts and status == "PASS":
        status = "BLOCKED"
        reason = "artifact symlink or non-regular file detected"
        result["status"] = status
        result["reason"] = reason
        write_case_result(artifact_dir, result)
        artifact_manifest, _ = write_artifact_manifest(artifact_dir, artifact_relative)
    return {
        "attemptId": attempt_id,
        "runId": run_id,
        "caseId": case_id,
        "ordinal": ordinal,
        "artifactDir": artifact_relative,
        "status": status,
        "reason": reason,
        "exitCode": exit_code,
        "timedOut": timed_out,
        "evidence": evidence_report,
        "stdoutSha256": result["stdoutSha256"],
        "stderrSha256": result["stderrSha256"],
        "sourceFingerprint": source_fingerprint,
        "sourceAfterFingerprint": source_after,
        "artifactManifest": artifact_manifest,
    }


def record_blocked_case(
    campaign: Campaign,
    attempt_id: str,
    case: dict[str, Any],
    ordinal: int,
    source_fingerprint: str,
    reason: str,
    *,
    status: str = "BLOCKED",
) -> dict[str, Any]:
    case_id = case["id"]
    round_mode = next(
        (
            attempt.get("mode")
            for attempt in campaign.state.get("attempts", [])
            if attempt.get("id") == attempt_id
        ),
        None,
    )
    if round_mode not in {"initial", "retest", "regression"}:
        raise CampaignError("blocked case does not belong to a valid attempt")
    if status not in {"BLOCKED", "NOT_RUN"}:
        raise CampaignError("unavailable case status is invalid")
    run_id, artifact_dir = campaign.allocate_case_artifact(attempt_id, case_id, ordinal)
    artifact_relative = relative_to_root(campaign.adapter.campaign_root, artifact_dir)
    campaign.commit(
        "case_started",
        {
            "attemptId": attempt_id,
            "runId": run_id,
            "caseId": case_id,
            "ordinal": ordinal,
            "artifactDir": artifact_relative,
            "sourceFingerprint": source_fingerprint,
        },
    )
    atomic_write_text(artifact_dir / "stdout.txt", "")
    atomic_write_text(artifact_dir / "stderr.txt", "")
    evidence_report = {
        "requiredFiles": list((case.get("evidence") or {}).get("requiredFiles", [])),
        "nonEmptyFiles": list((case.get("evidence") or {}).get("nonEmptyFiles", [])),
        "missingFiles": list((case.get("evidence") or {}).get("requiredFiles", [])),
        "emptyFiles": [],
        "files": [],
        "secretLikeContent": False,
    }
    write_case_result(
        artifact_dir,
        {
            "schemaVersion": SCHEMA_VERSION,
            "kernelVersion": SCRIPT_VERSION,
            "runId": run_id,
            "caseId": case_id,
            "round": round_mode,
            "status": status,
            "exitCode": None,
            "timedOut": False,
            "durationMs": 0,
            "reason": reason,
            "argvFingerprint": sha256_bytes(canonical_bytes(case["argv"])),
            "sourceFingerprintBefore": source_fingerprint,
            "sourceFingerprintAfter": source_fingerprint,
            "stdoutSha256": sha256_bytes(b""),
            "stderrSha256": sha256_bytes(b""),
            "secretLikeOutput": False,
            "secretDetected": False,
            "stdoutTruncated": False,
            "stderrTruncated": False,
            "evidence": evidence_report,
        },
    )
    artifact_manifest, _ = write_artifact_manifest(artifact_dir, artifact_relative)
    return {
        "attemptId": attempt_id,
        "runId": run_id,
        "caseId": case_id,
        "ordinal": ordinal,
        "artifactDir": artifact_relative,
        "status": status,
        "reason": reason,
        "exitCode": None,
        "timedOut": False,
        "evidence": evidence_report,
        "stdoutSha256": sha256_bytes(b""),
        "stderrSha256": sha256_bytes(b""),
        "sourceFingerprint": source_fingerprint,
        "sourceAfterFingerprint": source_fingerprint,
        "artifactManifest": artifact_manifest,
    }


__all__ = [
    "execute_case",
    "inspect_evidence",
    "record_blocked_case",
    "safe_child_environment",
]
