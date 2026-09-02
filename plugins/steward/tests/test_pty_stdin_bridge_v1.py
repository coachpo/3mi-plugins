from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pty_stdin_bridge


class PtyBridgeV1Tests(unittest.TestCase):
    def test_line_and_bounded_frames_cover_goal_payload_limit(self) -> None:
        self.assertEqual((None, ["child", "arg"]), pty_stdin_bridge._parse_arguments(["--line", "--", "child", "arg"]))
        size = 2 * 1024 * 1024
        self.assertEqual((size, ["child"]), pty_stdin_bridge._parse_arguments([str(size), "--", "child"]))
        with self.assertRaises(pty_stdin_bridge.PtyStdinBridgeError):
            pty_stdin_bridge._parse_arguments([str(size + 1), "--", "child"])


if __name__ == "__main__":
    unittest.main()
