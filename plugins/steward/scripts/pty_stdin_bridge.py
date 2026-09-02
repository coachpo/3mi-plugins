#!/usr/bin/env python3
"""Relay one bounded in-memory payload from a PTY to a child's stdin pipe."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from types import FrameType

MAX_FRAME_BYTES = 2 * 1024 * 1024
READY_LINE = "READY STEWARD_PTY_STDIN"


class PtyStdinBridgeError(Exception):
    """The PTY frame or child command is invalid or unavailable."""


class PtyStdinBridgeInterrupted(Exception):
    """A termination signal interrupted the PTY frame."""

    def __init__(self, signum: int) -> None:
        super().__init__(f"interrupted by signal {signum}")
        self.signum = signum


def _interrupt(signum: int, _frame: FrameType | None) -> None:
    raise PtyStdinBridgeInterrupted(signum)


def _bridge_signals() -> tuple[signal.Signals, ...]:
    return tuple(
        candidate
        for name in ("SIGHUP", "SIGINT", "SIGQUIT", "SIGTERM")
        if (candidate := getattr(signal, name, None)) is not None
    )


def _parse_arguments(argv: list[str]) -> tuple[int | None, list[str]]:
    if len(argv) < 3 or argv[1] != "--" or not argv[2]:
        raise PtyStdinBridgeError(
            "usage: pty_stdin_bridge.py (--line | <utf8-byte-count>) -- "
            "<command> [args ...]"
        )
    raw_size = argv[0]
    if raw_size == "--line":
        return None, argv[2:]
    if not raw_size.isascii() or not raw_size.isdecimal():
        raise PtyStdinBridgeError("frame must be --line or a decimal byte count")
    size = int(raw_size)
    if size > MAX_FRAME_BYTES:
        raise PtyStdinBridgeError(
            f"payload exceeds the {MAX_FRAME_BYTES}-byte bridge limit"
        )
    return size, argv[2:]


def _read_tty_frame(size: int | None) -> bytes:
    try:
        import termios
    except ImportError as exc:
        raise PtyStdinBridgeError(
            "PTY relay requires POSIX termios; use a finite non-TTY pipe"
        ) from exc

    descriptor = sys.stdin.fileno()
    if not os.isatty(descriptor):
        raise PtyStdinBridgeError(
            "stdin is not a PTY; pass the payload directly through a finite pipe"
        )

    try:
        original = termios.tcgetattr(descriptor)
    except (OSError, termios.error) as exc:
        raise PtyStdinBridgeError(f"cannot inspect PTY settings: {exc}") from exc

    raw = list(original)
    raw[6] = list(original[6])
    raw[0] &= ~(
        termios.IGNBRK
        | termios.BRKINT
        | termios.PARMRK
        | termios.ISTRIP
        | termios.INLCR
        | termios.IGNCR
        | termios.ICRNL
        | termios.IXON
    )
    raw[1] &= ~termios.OPOST
    raw[2] &= ~(termios.CSIZE | termios.PARENB)
    raw[2] |= termios.CS8
    raw[3] &= ~(
        termios.ECHO
        | getattr(termios, "ECHONL", 0)
        | termios.ICANON
        | termios.ISIG
        | termios.IEXTEN
    )
    raw[6][termios.VMIN] = 1
    raw[6][termios.VTIME] = 0

    previous_handlers = {
        handled: signal.getsignal(handled) for handled in _bridge_signals()
    }

    try:
        for handled in previous_handlers:
            signal.signal(handled, _interrupt)
        termios.tcflush(descriptor, termios.TCIFLUSH)
        termios.tcsetattr(descriptor, termios.TCSANOW, raw)
        print(READY_LINE, file=sys.stderr, flush=True)
        chunks: list[bytes] = []
        if size is None:
            observed = 0
            while True:
                chunk = os.read(descriptor, 65_536)
                if not chunk:
                    raise PtyStdinBridgeError(
                        "PTY input ended before the line-frame delimiter"
                    )
                delimiter = chunk.find(b"\n")
                content = chunk if delimiter < 0 else chunk[:delimiter]
                observed += len(content)
                if observed > MAX_FRAME_BYTES:
                    raise PtyStdinBridgeError(
                        f"payload exceeds the {MAX_FRAME_BYTES}-byte bridge limit"
                    )
                chunks.append(content)
                if delimiter >= 0:
                    if chunk[delimiter + 1 :]:
                        raise PtyStdinBridgeError(
                            "line frame contains bytes after its delimiter"
                        )
                    break
        else:
            remaining = size
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    raise PtyStdinBridgeError(
                        "PTY input ended before the declared byte count"
                    )
                chunks.append(chunk)
                remaining -= len(chunk)
        termios.tcflush(descriptor, termios.TCIFLUSH)
        return b"".join(chunks)
    except PtyStdinBridgeError:
        raise
    except (OSError, termios.error) as exc:
        raise PtyStdinBridgeError(f"cannot read PTY payload: {exc}") from exc
    finally:
        restore_error: PtyStdinBridgeError | None = None
        try:
            termios.tcsetattr(descriptor, termios.TCSANOW, original)
        except (OSError, termios.error) as exc:
            restore_error = PtyStdinBridgeError(f"cannot restore PTY settings: {exc}")
        for handled, previous in previous_handlers.items():
            signal.signal(handled, previous)
        if restore_error is not None:
            raise restore_error


def main(argv: list[str] | None = None) -> int:
    try:
        size, command = _parse_arguments(list(sys.argv[1:] if argv is None else argv))
        payload = _read_tty_frame(size)
        try:
            completed = subprocess.run(command, input=payload, check=False)
        except OSError as exc:
            raise PtyStdinBridgeError(f"cannot execute child command: {exc}") from exc
        if completed.returncode < 0:
            return 128 + min(-completed.returncode, 127)
        return completed.returncode
    except PtyStdinBridgeInterrupted as exc:
        print("ERROR STEWARD_PTY_STDIN: " + str(exc), file=sys.stderr)
        return 128 + exc.signum
    except PtyStdinBridgeError as exc:
        print("ERROR STEWARD_PTY_STDIN: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
