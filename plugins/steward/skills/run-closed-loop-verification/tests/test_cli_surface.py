from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import make_project, run_cli
except ImportError:
    from helpers import make_project, run_cli  # type: ignore

from cli import build_parser


class CliSurfaceTests(unittest.TestCase):
    def test_public_command_set_is_exact(self) -> None:
        parser = build_parser()
        action = next(item for item in parser._actions if item.dest == "command")
        self.assertEqual(
            {
                "validate-adapter", "observe-source", "init", "status", "run",
                "resume", "record-fix", "retest", "audit",
            },
            set(action.choices),
        )

    def test_init_defaults_to_within_goal_and_accepts_verify_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            path = make_project(base / "default")
            result = run_cli(path, "init")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn('"repairPolicy": "within-goal"', result.stdout)
            path = make_project(base / "read-only")
            result = run_cli(path, "init", "--repair-policy", "verify-only")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn('"repairPolicy": "verify-only"', result.stdout)

    def test_run_requires_an_explicit_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            self.assertEqual(0, run_cli(path, "init").returncode)
            result = run_cli(path, "run")
            self.assertEqual(2, result.returncode)
            self.assertIn("--mode", result.stderr)


if __name__ == "__main__":
    unittest.main()
