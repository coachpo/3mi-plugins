"""Regression coverage for long Steward stdin payloads and explicit replay."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pty
except ImportError:  # pragma: no cover - the bridge is POSIX-only by contract.
    pty = None


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = PLUGIN_ROOT / "scripts" / "pty_stdin_bridge.py"
WORKSPACE_SCRIPT = PLUGIN_ROOT / "scripts" / "goal_workspace.py"
READY_LINE = b"READY STEWARD_PTY_STDIN\n"


@unittest.skipIf(pty is None, "PTY regression requires a POSIX host")
class PtyStdinBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        subprocess.run(
            ["git", "init", "-q", str(self.root)],
            check=True,
            capture_output=True,
        )
        self.context_path = ".steward/goal-context/persist-goal-workspace.md"
        self.objective = "\n".join(
            (
                "结果：Persist Goal Workspace",
                f"证据与上下文：已核实背景见 {self.context_path}",
                "范围：仅建立目标 worktree 的 GOAL 控制文件",
                "约束与授权：不开始执行 GOAL",
                "完成标准：(C1) goal.txt 是规范七行合同；(C2) context 与 GOAL 引用一致",
                "正当阻塞项：目标绑定漂移或控制路径不安全时停止",
                "最终交付：持久化 GOAL 并返回相同 objective",
            )
        )
        self.context = "# 已核实来源\n\n" + ("长上下文证据。" * 1_024) + "\n"
        self.payload = json.dumps(
            {
                "objective": self.objective,
                "context": {"path": self.context_path, "content": self.context},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertGreater(len(self.payload), 8_192)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _workspace_command(self) -> list[str]:
        return [
            sys.executable,
            str(WORKSPACE_SCRIPT),
            "create",
            str(self.root),
            "-",
        ]

    def _run_bridge(
        self,
        *,
        payload: bytes | None = None,
        frame_argument: str = "--line",
        command: list[str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        assert pty is not None
        import termios

        payload = self.payload if payload is None else payload
        command = self._workspace_command() if command is None else command
        master, slave = pty.openpty()
        inspection = os.dup(slave)
        original_settings = termios.tcgetattr(inspection)
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(BRIDGE_SCRIPT),
                    frame_argument,
                    "--",
                    *command,
                ],
                stdin=slave,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            os.close(slave)
            slave = -1
            assert process.stderr is not None
            readable, _, _ = select.select([process.stderr], [], [], 5)
            self.assertTrue(readable, "bridge did not signal readiness")
            self.assertEqual(READY_LINE, process.stderr.readline())

            written = 0
            frame = payload + (b"\n" if frame_argument == "--line" else b"")
            while written < len(frame):
                written += os.write(master, frame[written:])

            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(original_settings, termios.tcgetattr(inspection))
            return subprocess.CompletedProcess(
                process.args,
                process.returncode,
                stdout,
                stderr,
            )
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
            os.close(inspection)
            if slave >= 0:
                os.close(slave)

    def test_workspace_rejects_direct_pty_before_writing(self) -> None:
        assert pty is not None
        master, slave = pty.openpty()
        try:
            result = subprocess.run(
                self._workspace_command(),
                stdin=slave,
                capture_output=True,
                timeout=5,
                check=False,
            )
        finally:
            os.close(master)
            os.close(slave)

        self.assertEqual(1, result.returncode)
        self.assertIn(b"WORKSPACE_INPUT_TRANSPORT", result.stderr)
        self.assertFalse((self.root / ".steward").exists())

    def test_long_payload_replays_after_truncated_zero_write_attempt(self) -> None:
        truncated = subprocess.run(
            self._workspace_command(),
            input=self.payload[:4_096],
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, truncated.returncode)
        self.assertIn(b"WORKSPACE_INPUT", truncated.stderr)
        self.assertFalse((self.root / ".steward").exists())

        created = self._run_bridge()
        self.assertEqual(0, created.returncode, created.stderr.decode())
        self.assertEqual(b"", created.stderr)
        view = json.loads(created.stdout)
        self.assertEqual(self.objective, view["goalContract"]["objective"])
        self.assertEqual(
            self.context.encode("utf-8"),
            (self.root / self.context_path).read_bytes(),
        )
        goal_path = self.root / ".steward" / "goal.txt"
        initial_stats = (goal_path.stat(), (self.root / self.context_path).stat())

        replayed = self._run_bridge()
        self.assertEqual(created.stdout, replayed.stdout)
        self.assertEqual(0, replayed.returncode, replayed.stderr.decode())
        final_stats = (goal_path.stat(), (self.root / self.context_path).stat())
        self.assertEqual(
            [(item.st_ino, item.st_mtime_ns) for item in initial_stats],
            [(item.st_ino, item.st_mtime_ns) for item in final_stats],
        )
        status = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("", status.stdout)

    def test_byte_count_mode_preserves_terminal_control_bytes(self) -> None:
        payload = b"A\rB\x13C\nD\x00E"
        command = [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
        ]

        relayed = self._run_bridge(
            payload=payload,
            frame_argument=str(len(payload)),
            command=command,
        )

        self.assertEqual(0, relayed.returncode, relayed.stderr.decode())
        self.assertEqual(payload, relayed.stdout)
        self.assertEqual(b"", relayed.stderr)

    def test_sigterm_restores_terminal_before_exit(self) -> None:
        assert pty is not None
        import termios

        master, slave = pty.openpty()
        inspection = os.dup(slave)
        original_settings = termios.tcgetattr(inspection)
        process = subprocess.Popen(
            [
                sys.executable,
                str(BRIDGE_SCRIPT),
                "--line",
                "--",
                *self._workspace_command(),
            ],
            stdin=slave,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        os.close(slave)
        try:
            assert process.stderr is not None
            readable, _, _ = select.select([process.stderr], [], [], 5)
            self.assertTrue(readable, "bridge did not signal readiness")
            self.assertEqual(READY_LINE, process.stderr.readline())
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)

            self.assertEqual(128 + signal.SIGTERM, process.returncode)
            self.assertEqual(b"", stdout)
            self.assertIn(b"interrupted by signal", stderr)
            self.assertEqual(original_settings, termios.tcgetattr(inspection))
            self.assertFalse((self.root / ".steward").exists())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
            os.close(inspection)


if __name__ == "__main__":
    unittest.main()
