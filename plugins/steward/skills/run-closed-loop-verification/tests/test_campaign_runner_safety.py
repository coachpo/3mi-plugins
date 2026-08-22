"""Focused process, stream, and evidence safety coverage for the local runner."""

from __future__ import annotations

import inspect
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

try:
    from .helpers import (
        KERNEL,
        campaign_path,
        json_output,
        load_state,
        make_adapter,
        make_case,
        read_json,
        run_cli,
    )
except ImportError:  # unittest discovery with tests/ as the import root
    from helpers import (  # type: ignore
        KERNEL,
        campaign_path,
        json_output,
        load_state,
        make_adapter,
        make_case,
        read_json,
        run_cli,
    )

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import runner_evidence as runner  # noqa: E402


def _process_is_live(pid: int) -> bool:
    table = runner._posix_process_table()
    if table is not None:
        entry = table.get(pid)
        return entry is not None and not entry[2].startswith("Z")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_file(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for " + str(path))


class _GeneratedStream:
    def __init__(self) -> None:
        self.index = 0
        self.closed = False

    def read(self, _size: int) -> bytes:
        self.index += 1
        if self.index <= 96:
            return b"x" * runner.OUTPUT_READ_BYTES
        if self.index == 97:
            return b"\npass"
        if self.index == 98:
            return b"word=hunter2\n"
        return b""

    def close(self) -> None:
        self.closed = True


class BoundedStreamingSafetyTests(unittest.TestCase):
    def test_truncation_marker_is_inside_the_five_mib_limit(self) -> None:
        stream = _GeneratedStream()
        collector = runner._BoundedStreamCollector(stream)
        collector.start()
        collector.thread.join(5)
        text, _secret, truncated, capture_ok = collector.snapshot()
        self.assertTrue(capture_ok)
        self.assertTrue(truncated)
        self.assertLessEqual(len(text.encode("utf-8")), runner.MAX_OUTPUT_BYTES)

    def test_child_environment_is_an_allowlist(self) -> None:
        with mock.patch.dict(
            runner.os.environ,
            {
                "PATH": "/trusted/bin",
                "LANG": "C.UTF-8",
                "DATABASE_URL": "postgres://credential",
                "SSH_AUTH_SOCK": "/tmp/agent.sock",
                "COOKIE": "session-value",
                "HOME": "/private/home",
            },
            clear=True,
        ):
            environment = runner.safe_child_environment(Path("/tmp/evidence"))
        self.assertEqual("/trusted/bin", environment["PATH"])
        self.assertEqual("C.UTF-8", environment["LANG"])
        for denied in ("DATABASE_URL", "SSH_AUTH_SOCK", "COOKIE", "HOME"):
            self.assertNotIn(denied, environment)

    def test_stream_retention_is_bounded_and_scans_past_the_prefix(self) -> None:
        stream = _GeneratedStream()
        collector = runner._BoundedStreamCollector(stream)
        collector.start()
        collector.thread.join(5)
        text, secret, truncated, capture_ok = collector.snapshot()

        self.assertTrue(capture_ok)
        self.assertTrue(secret)
        self.assertTrue(truncated)
        self.assertLessEqual(len(collector._prefix), runner.MAX_OUTPUT_BYTES)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("TemporaryFile", inspect.getsource(runner.execute_case))

    def test_secret_assignment_scans_across_unbounded_whitespace(self) -> None:
        class Fragmented:
            def __init__(self) -> None:
                self.chunks = iter(
                    [
                        b"x" * runner.MAX_OUTPUT_BYTES,
                        b" password",
                        b" " * 10000,
                        b"=hunter2",
                        b"",
                    ]
                )

            def read(self, _size: int) -> bytes:
                return next(self.chunks)

            def close(self) -> None:
                pass

        collector = runner._BoundedStreamCollector(Fragmented())
        collector.start()
        collector.thread.join(5)
        text, secret, truncated, capture_ok = collector.snapshot()
        self.assertTrue(capture_ok)
        self.assertTrue(secret)
        self.assertTrue(truncated)
        self.assertLessEqual(len(text.encode("utf-8")), runner.MAX_OUTPUT_BYTES)

    def test_invalid_utf8_secret_evidence_is_redacted_and_blocks(self) -> None:
        payload = [255] + list(b" password=hunter2")
        script = (
            "import os\n"
            "from pathlib import Path\n"
            "artifact = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            f"(artifact / 'proof.bin').write_bytes(bytes({payload!r}))\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "invalid-utf8",
                        "smoke",
                        argv=(sys.executable, "-c", script),
                        required_files=("proof.bin",),
                        non_empty_files=("proof.bin",),
                    )
                ],
            )
            json_output(run_cli(adapter, "init", expected=0))
            summary = json_output(run_cli(adapter, "run", expected=1))
            self.assertEqual("BLOCKED", summary["status"])

            case_run = load_state(adapter)["attempts"][-1]["caseRuns"][-1]
            artifact = campaign_path(adapter) / case_run["artifactDir"]
            content = (artifact / "proof.bin").read_bytes()
            result = read_json(artifact / "result.json")
            self.assertNotIn(b"hunter2", content)
            self.assertIn(b"<REDACTED", content)
            self.assertTrue(result["secretDetected"])
            self.assertEqual("BLOCKED", result["status"])

    def test_audit_scanner_detects_invalid_utf8_secret_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary)
            path = artifact / "proof.bin"
            path.write_bytes(b"prefix\xff password=hunter2\xff")
            self.assertTrue(
                runner.scan_artifact_text_files(artifact, redact_files=False)
            )
            self.assertTrue(
                runner.scan_artifact_text_files(artifact, redact_files=True)
            )
            self.assertNotIn(b"hunter2", path.read_bytes())


class WindowsCleanupMockTests(unittest.TestCase):
    class _ExitedProcess:
        pid = 4321

        @staticmethod
        def poll() -> int:
            return 9

    def test_taskkill_is_absolute_and_only_rc_zero_is_certain(self) -> None:
        completed = subprocess.CompletedProcess([], 1)
        with (
            mock.patch.object(runner.os, "name", "nt"),
            mock.patch.object(
                runner,
                "_trusted_windows_system_directory",
                return_value=r"D:\TrustedWindows\System32",
            ),
            mock.patch.object(runner.subprocess, "run", return_value=completed) as run,
        ):
            certain = runner.terminate_process_tree(self._ExitedProcess())  # type: ignore[arg-type]
        self.assertFalse(certain)
        self.assertEqual(
            r"D:\TrustedWindows\System32\taskkill.exe",
            run.call_args.args[0][0],
        )

        completed = subprocess.CompletedProcess([], 0)
        with (
            mock.patch.object(runner.os, "name", "nt"),
            mock.patch.object(
                runner,
                "_trusted_windows_system_directory",
                return_value=r"D:\TrustedWindows\System32",
            ),
            mock.patch.object(runner.subprocess, "run", return_value=completed),
        ):
            self.assertTrue(
                runner.terminate_process_tree(self._ExitedProcess())  # type: ignore[arg-type]
            )

    def test_untrusted_systemroot_is_not_used_when_system_lookup_fails(self) -> None:
        with (
            mock.patch.object(runner.os, "name", "nt"),
            mock.patch.object(
                runner, "_trusted_windows_system_directory", return_value=None
            ),
            mock.patch.object(runner.subprocess, "run") as run,
        ):
            self.assertFalse(
                runner.terminate_process_tree(self._ExitedProcess())  # type: ignore[arg-type]
            )
        run.assert_not_called()


class ResultConsistencyTests(unittest.TestCase):
    def test_oversize_sparse_artifact_becomes_structured_blocked(self) -> None:
        script = (
            "import os\n"
            "from pathlib import Path\n"
            "artifact = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            f"with (artifact / 'huge.bin').open('wb') as handle: handle.truncate({runner.MAX_ARTIFACT_FILE_BYTES + 1})\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "oversize",
                        "smoke",
                        argv=(sys.executable, "-c", script),
                        required_files=("huge.bin",),
                        non_empty_files=("huge.bin",),
                    )
                ],
            )
            json_output(run_cli(adapter, "init", expected=0))
            summary = json_output(run_cli(adapter, "run", expected=1, timeout=15))
            self.assertEqual("BLOCKED", summary["status"])
            case_run = load_state(adapter)["attempts"][-1]["caseRuns"][-1]
            artifact = campaign_path(adapter) / case_run["artifactDir"]
            result = read_json(artifact / "result.json")
            self.assertEqual("BLOCKED", result["status"])
            self.assertIn("safe size limit", result["reason"])
            self.assertLess((artifact / "huge.bin").stat().st_size, 1024)

    def test_execution_boundary_rejects_retargeted_cwd_without_starting(self) -> None:
        fake_process = mock.Mock()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            cwd = root / "work"
            cwd.mkdir()
            with (
                mock.patch.object(
                    runner,
                    "path_uses_symlink",
                    side_effect=[False, True],
                ),
                mock.patch.object(
                    runner.subprocess, "Popen", return_value=fake_process
                ) as popen,
            ):
                with self.assertRaisesRegex(
                    runner.CampaignError, "changed to a symlink"
                ):
                    runner._start_case_process([], root, "work", "case cwd", {})
            popen.assert_not_called()

    def test_artifact_root_swap_is_quarantined_without_outside_write(self) -> None:
        script = (
            "import os\n"
            "from pathlib import Path\n"
            "artifact = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            "outside = Path('outside')\n"
            "outside.mkdir(exist_ok=True)\n"
            "moved = artifact.with_name(artifact.name + '.moved')\n"
            "artifact.rename(moved)\n"
            "artifact.symlink_to(outside.resolve(), target_is_directory=True)\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "root-swap",
                        "smoke",
                        argv=(sys.executable, "-c", script),
                        required_files=(),
                        non_empty_files=(),
                    )
                ],
            )
            json_output(run_cli(adapter, "init", expected=0))
            summary = json_output(run_cli(adapter, "run", expected=1))
            self.assertEqual("BLOCKED", summary["status"])
            self.assertEqual([], list((root / "outside").iterdir()))
            case_run = load_state(adapter)["attempts"][-1]["caseRuns"][-1]
            artifact = campaign_path(adapter) / case_run["artifactDir"]
            self.assertTrue(artifact.is_dir())
            self.assertFalse(artifact.is_symlink())
            self.assertEqual("BLOCKED", read_json(artifact / "result.json")["status"])

    def test_catalog_drift_during_case_blocks_before_result(self) -> None:
        script = (
            "import os, json\n"
            "from pathlib import Path\n"
            "artifact = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            "(artifact / 'proof.json').write_text('{\"ok\":true}')\n"
            "adapter = Path('adapter.json')\n"
            "data = json.loads(adapter.read_text())\n"
            "data['cases'][0]['timeoutSeconds'] = 11\n"
            "adapter.write_text(json.dumps(data))\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "catalog-drift", "smoke", argv=(sys.executable, "-c", script)
                    )
                ],
            )
            json_output(run_cli(adapter, "init", expected=0))
            summary = json_output(run_cli(adapter, "run", expected=1))
            self.assertEqual("BLOCKED", summary["status"])
            case_run = load_state(adapter)["attempts"][-1]["caseRuns"][-1]
            result = read_json(
                campaign_path(adapter) / case_run["artifactDir"] / "result.json"
            )
            self.assertEqual("BLOCKED", result["status"])
            self.assertIn("catalog drifted", result["reason"])

    def test_kernel_blocked_result_has_execute_result_shape_and_attempt_round(
        self,
    ) -> None:
        unavailable = "windows" if os.name != "nt" else "darwin"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "optional-unavailable",
                        "smoke",
                        required=False,
                        platform=unavailable,
                    ),
                    make_case(
                        "dependent-required",
                        "functional",
                        depends_on=("optional-unavailable",),
                    ),
                ],
            )
            json_output(run_cli(adapter, "init", expected=0))
            json_output(run_cli(adapter, "run", expected=1))
            case_run = load_state(adapter)["attempts"][-1]["caseRuns"][-1]
            artifact = campaign_path(adapter) / case_run["artifactDir"]
            result = read_json(artifact / "result.json")
            self.assertEqual("initial", result["round"])
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual(
                {
                    "argvFingerprint",
                    "caseId",
                    "durationMs",
                    "evidence",
                    "exitCode",
                    "kernelVersion",
                    "reason",
                    "round",
                    "runId",
                    "schemaVersion",
                    "secretDetected",
                    "secretLikeOutput",
                    "sourceFingerprintAfter",
                    "sourceFingerprintBefore",
                    "stderrSha256",
                    "stderrTruncated",
                    "stdoutSha256",
                    "stdoutTruncated",
                    "status",
                    "timedOut",
                },
                set(result),
            )


@unittest.skipUnless(os.name == "posix", "requires POSIX signals and sessions")
class PosixCleanupTests(unittest.TestCase):
    @staticmethod
    def _detached_case_script(*, write_marker: bool) -> str:
        child = (
            "import os, time\n"
            "from pathlib import Path\n"
            "os.setsid()\n"
            "Path('descendant.ready').write_text('ready')\n"
            "time.sleep(5.0)\n"
            + (
                "Path('escaped-marker.txt').write_text('alive')\n"
                if write_marker
                else ""
            )
            + "time.sleep(30)\n"
        )
        return (
            "import subprocess, sys, time\n"
            "from pathlib import Path\n"
            f"child = subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            "Path('descendant.pid').write_text(str(child.pid), encoding='ascii')\n"
            "deadline = time.monotonic() + 5\n"
            "while not Path('descendant.ready').exists():\n"
            "    if time.monotonic() >= deadline: raise SystemExit(4)\n"
            "    time.sleep(0.005)\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(30)\n"
        )

    def test_timeout_kills_observed_setsid_descendant_but_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "detached-timeout",
                        "smoke",
                        argv=(
                            sys.executable,
                            "-c",
                            self._detached_case_script(write_marker=True),
                        ),
                        # Leave enough startup time under full-suite load for the
                        # child to publish the post-setsid readiness handshake.
                        timeout_seconds=2.0,
                        required_files=(),
                        non_empty_files=(),
                    )
                ],
            )
            json_output(run_cli(adapter, "init", expected=0))
            summary = json_output(run_cli(adapter, "run", expected=1, timeout=15))
            self.assertEqual("BLOCKED", summary["status"])
            case_run = load_state(adapter)["attempts"][-1]["caseRuns"][-1]
            self.assertIn("cleanup could not be verified", case_run["reason"])
            pid = int((root / "descendant.pid").read_text(encoding="ascii"))
            time.sleep(1.2)
            self.assertFalse(_process_is_live(pid))
            self.assertFalse((root / "escaped-marker.txt").exists())

    def test_normal_exit_with_inherited_pipe_descendant_does_not_hang(self) -> None:
        child = "import os,time; os.setsid(); time.sleep(30)"
        script = (
            "import os,subprocess,sys\n"
            "from pathlib import Path\n"
            f"child=subprocess.Popen([sys.executable,'-c',{child!r}], stdout=sys.stdout, stderr=sys.stderr)\n"
            "Path('descendant.pid').write_text(str(child.pid))\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "inherited-pipe",
                        "smoke",
                        argv=(sys.executable, "-c", script),
                        required_files=(),
                        non_empty_files=(),
                    )
                ],
            )
            json_output(run_cli(adapter, "init", expected=0))
            summary = json_output(run_cli(adapter, "run", expected=1, timeout=10))
            self.assertEqual("BLOCKED", summary["status"])
            pid = int((root / "descendant.pid").read_text())
            time.sleep(0.2)
            self.assertFalse(_process_is_live(pid))

    def test_keyboard_interrupt_cleans_detached_descendant_and_returns_130(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "detached-interrupt",
                        "smoke",
                        argv=(
                            sys.executable,
                            "-c",
                            self._detached_case_script(write_marker=True),
                        ),
                        timeout_seconds=20,
                        required_files=(),
                        non_empty_files=(),
                    )
                ],
            )
            json_output(run_cli(adapter, "init", expected=0))
            cli = subprocess.Popen(
                [sys.executable, str(KERNEL), "run", "--adapter", str(adapter)],
                cwd=str(root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            pidfile = root / "descendant.pid"
            try:
                _wait_for_file(pidfile)
                os.kill(cli.pid, signal.SIGINT)
                _stdout, stderr = cli.communicate(timeout=10)
            finally:
                if cli.poll() is None:
                    cli.kill()
                    cli.wait()
            self.assertEqual(130, cli.returncode)
            self.assertIn("interrupted", stderr)
            descendant_pid = int(pidfile.read_text(encoding="ascii"))
            time.sleep(1.2)
            self.assertFalse(_process_is_live(descendant_pid))
            self.assertFalse((root / "escaped-marker.txt").exists())

    def test_initial_source_drift_is_blocked_before_result_commit(self) -> None:
        script = (
            "import os\n"
            "from pathlib import Path\n"
            "Path('source.txt').write_text('changed during case\\n')\n"
            "artifact = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            "(artifact / 'proof.json').write_text('{\"ok\":true}')\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(
                root,
                [
                    make_case(
                        "source-drift", "smoke", argv=(sys.executable, "-c", script)
                    )
                ],
            )
            json_output(run_cli(adapter, "init", expected=0))
            summary = json_output(run_cli(adapter, "run", expected=1))
            self.assertEqual("BLOCKED", summary["status"])
            case_run = load_state(adapter)["attempts"][-1]["caseRuns"][-1]
            artifact = campaign_path(adapter) / case_run["artifactDir"]
            result = read_json(artifact / "result.json")
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual(case_run["reason"], result["reason"])
            self.assertIn("fingerprint drifted", result["reason"])


if __name__ == "__main__":
    unittest.main()
