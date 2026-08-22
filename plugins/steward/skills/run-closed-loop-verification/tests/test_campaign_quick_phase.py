from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import (
        json_output,
        load_state,
        make_adapter,
        make_case,
        run_cli,
        write_fix_for_latest_failure,
    )
except ImportError:
    from helpers import (  # type: ignore
        json_output,
        load_state,
        make_adapter,
        make_case,
        run_cli,
        write_fix_for_latest_failure,
    )


class QuickPhaseTests(unittest.TestCase):
    def test_quick_pass_is_history_only_until_full_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            quick_case = make_case("quick-smoke", "smoke")
            quick_case["quick"] = True
            full_case = make_case(
                "full-functional",
                "functional",
                depends_on=("quick-smoke",),
            )
            adapter = make_adapter(root, [quick_case, full_case])
            run_cli(adapter, "init", expected=0)

            quick = json_output(
                run_cli(adapter, "run", "--phase", "quick", expected=0)
            )
            self.assertEqual("PENDING", quick["status"])
            self.assertEqual("PENDING", quick["executionStatus"])
            self.assertEqual("INCOMPLETE", quick["completionStatus"])
            self.assertEqual("narrow", quick["coverage"]["mode"])
            self.assertEqual("PENDING", quick["cases"]["quick-smoke"]["status"])
            self.assertEqual("PASS", quick["cases"]["quick-smoke"]["quickStatus"])
            self.assertEqual("quick", quick["attempts"][-1]["mode"])
            self.assertEqual("initial", quick["resumeMode"])
            self.assertIsNone(quick["finalRegressionAttemptId"])

            initial = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual("READY_FOR_REGRESSION", initial["status"])
            self.assertEqual("READY_FOR_REGRESSION", initial["executionStatus"])
            self.assertEqual("INCOMPLETE", initial["completionStatus"])
            self.assertEqual("regression", initial["resumeMode"])
            self.assertEqual("narrow", initial["coverage"]["mode"])

            completed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual("COMPLETE", completed["status"])
            self.assertEqual("COMPLETE", completed["executionStatus"])
            self.assertEqual("AUDIT_REQUIRED", completed["completionStatus"])
            self.assertIsNone(completed["resumeMode"])
            attempt_count = len(completed["attempts"])
            observed = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual("COMPLETE", observed["executionStatus"])
            self.assertEqual("AUDIT_REQUIRED", observed["completionStatus"])
            self.assertIsNone(observed["resumeMode"])
            self.assertEqual(attempt_count, len(observed["attempts"]))
            self.assertTrue(json_output(run_cli(adapter, "audit", expected=0))["ok"])

    def test_quick_failure_fix_retest_restarts_quick_without_full_credit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = (
                "import os\n"
                "from pathlib import Path\n"
                "ready = Path('ready.txt').exists()\n"
                "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
                "if ready:\n"
                "    (evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n"
                "raise SystemExit(0 if ready else 1)\n"
            )
            case = make_case(
                "quick-fix",
                "smoke",
                argv=(sys.executable, "-c", command),
            )
            case["quick"] = True
            adapter = make_adapter(root, [case])
            run_cli(adapter, "init", expected=0)
            failed = json_output(
                run_cli(adapter, "run", "--phase", "quick", expected=1)
            )
            self.assertEqual("FAILED", failed["status"])

            (root / "ready.txt").write_text("restored\n", encoding="utf-8")
            fix = write_fix_for_latest_failure(adapter)
            run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)
            resumed = json_output(run_cli(adapter, "retest", expected=0))
            self.assertEqual("PENDING", resumed["status"])
            self.assertEqual(
                ["quick", "retest", "quick"],
                [item["mode"] for item in resumed["attempts"]],
            )
            self.assertEqual("PENDING", resumed["cases"]["quick-fix"]["status"])
            self.assertEqual("PASS", resumed["cases"]["quick-fix"]["quickStatus"])
            self.assertEqual("initial", resumed["resumeMode"])
            self.assertIsNone(load_state(adapter)["pendingFix"])

            continued = json_output(run_cli(adapter, "resume", expected=0))
            self.assertEqual("READY_FOR_REGRESSION", continued["status"])
            self.assertEqual("regression", continued["resumeMode"])
            self.assertEqual("INCOMPLETE", continued["completionStatus"])


if __name__ == "__main__":
    unittest.main()
