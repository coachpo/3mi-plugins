"""End-to-end tests for the closed-loop campaign public CLI."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import (
        campaign_path,
        json_output,
        load_state,
        make_adapter,
        make_case,
        read_json,
        run_cli,
        write_fix_for_latest_failure,
    )
except ImportError:  # unittest discovery with tests/ as the import root
    from helpers import (  # type: ignore
        campaign_path,
        json_output,
        load_state,
        make_adapter,
        make_case,
        read_json,
        run_cli,
        write_fix_for_latest_failure,
    )


CATEGORIES = ("smoke", "functional", "integration", "workflow", "role-play")


def _passing_runner() -> str:
    return (
        "import os\n"
        "from pathlib import Path\n"
        "target = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR']) / 'proof.json'\n"
        "target.write_text('{\"ok\":true}', encoding='utf-8')\n"
    )


class CampaignEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _five_layer_cases(self) -> list[dict[str, object]]:
        cases: list[dict[str, object]] = []
        dependency: tuple[str, ...] = ()
        for index, category in enumerate(CATEGORIES, start=1):
            case_id = f"{index:02d}-{category}"
            cases.append(
                make_case(case_id, category, depends_on=dependency)
            )
            dependency = (case_id,)
        return cases

    def test_five_layer_all_pass_campaign_reaches_audited_completion(self) -> None:
        adapter = make_adapter(
            self.root, self._five_layer_cases(), coverage_mode="full"
        )

        initialized = json_output(run_cli(adapter, "init", expected=0))
        self.assertEqual("PENDING", initialized["status"])
        initialized_event = json.loads(
            (campaign_path(adapter) / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        self.assertEqual(4, initialized_event["schemaVersion"])
        self.assertEqual("0.4.0", initialized_event["payload"]["kernelVersion"])
        self.assertEqual(4, initialized_event["payload"]["journalSchemaVersion"])
        self.assertEqual(1, initialized_event["payload"]["artifactManifestVersion"])

        initial = json_output(run_cli(adapter, "run", expected=0))
        self.assertEqual("READY_FOR_REGRESSION", initial["status"])
        self.assertEqual(set(CATEGORIES), {item["category"] for item in initial["cases"].values()})
        self.assertTrue(all(item["status"] == "PASS" for item in initial["cases"].values()))

        completed = json_output(
            run_cli(adapter, "run", "--mode", "regression", expected=0)
        )
        self.assertEqual("COMPLETE", completed["status"])
        self.assertEqual("AUDIT_REQUIRED", completed["completionStatus"])
        self.assertEqual("full", completed["coverage"]["mode"])
        self.assertEqual([], completed["coverage"]["missingTiers"])
        self.assertEqual(set(CATEGORIES), set(completed["coverage"]["verifiedTiers"]))
        self.assertEqual([], completed["coverage"]["unverifiedTiers"])
        self.assertIsNotNone(completed["finalRegressionAttemptId"])

        state = load_state(adapter)
        self.assertEqual("0.4.0", state["kernelVersion"])
        final_attempt = next(
            attempt
            for attempt in state["attempts"]
            if attempt["id"] == state["finalRegressionAttemptId"]
        )
        self.assertEqual("regression", final_attempt["mode"])
        self.assertEqual("PASS", final_attempt["status"])
        self.assertEqual(5, len(final_attempt["caseRuns"]))
        baseline = final_attempt["sourceFingerprint"]
        for case_run in final_attempt["caseRuns"]:
            self.assertEqual("PASS", case_run["status"])
            self.assertEqual(baseline, case_run["sourceFingerprint"])
            self.assertEqual(baseline, case_run["sourceAfterFingerprint"])
            artifact = campaign_path(adapter) / case_run["artifactDir"]
            manifest = read_json(artifact / "artifact-manifest.json")
            self.assertEqual(1, manifest["artifactManifestVersion"])

        audited = json_output(run_cli(adapter, "audit", expected=0))
        self.assertTrue(audited["ok"])
        self.assertTrue(audited["allRequiredPassed"])
        self.assertTrue(audited["sameBaseline"])
        self.assertTrue(audited["evidenceComplete"])
        self.assertTrue(audited["journalReplayable"])
        self.assertEqual("full", audited["coverage"]["mode"])
        self.assertEqual(set(CATEGORIES), set(audited["coverage"]["presentTiers"]))

    def test_failure_stops_then_fix_retest_continues_initial_and_regresses(self) -> None:
        runner = self.root / "runner.py"
        runner.write_text("raise SystemExit(7)\n", encoding="utf-8")
        cases = self._five_layer_cases()
        cases[0]["argv"] = [sys.executable, "runner.py"]
        adapter = make_adapter(self.root, cases, source_files=("runner.py",))
        run_cli(adapter, "init", expected=0)

        failed = json_output(run_cli(adapter, "run", expected=1))
        self.assertEqual("FAILED", failed["status"])
        self.assertEqual("FAILED", failed["cases"]["01-smoke"]["status"])
        self.assertTrue(
            all(
                failed["cases"][f"{index:02d}-{category}"]["status"] == "PENDING"
                for index, category in enumerate(CATEGORIES[1:], start=2)
            )
        )
        failed_artifact = campaign_path(adapter) / failed["cases"]["01-smoke"]["artifactDir"]
        failed_result = read_json(failed_artifact / "result.json")
        self.assertEqual("FAILED", failed_result["status"])

        runner.write_text(_passing_runner(), encoding="utf-8")
        fix = write_fix_for_latest_failure(
            adapter,
            changed_files=("runner.py",),
            external_condition=False,
        )
        recorded = json_output(
            run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)
        )
        self.assertIsNotNone(recorded["pendingFix"])

        retested = json_output(run_cli(adapter, "retest", expected=0))
        self.assertEqual("READY_FOR_REGRESSION", retested["status"])
        self.assertEqual("RETEST_PASSED", retested["cases"]["01-smoke"]["status"])
        self.assertTrue(
            all(
                retested["cases"][f"{index:02d}-{category}"]["status"] == "PASS"
                for index, category in enumerate(CATEGORIES[1:], start=2)
            )
        )
        self.assertIsNone(retested["pendingFix"])
        self.assertEqual(
            ["initial", "retest", "initial"],
            [attempt["mode"] for attempt in retested["attempts"]],
        )
        self.assertEqual(
            retested["attempts"][1]["id"],
            retested["attempts"][2]["resumedFrom"],
        )

        completed = json_output(
            run_cli(adapter, "run", "--mode", "regression", expected=0)
        )
        self.assertEqual("COMPLETE", completed["status"])
        self.assertTrue(failed_artifact.is_dir(), "the original failure evidence was removed")
        self.assertEqual(failed_result, read_json(failed_artifact / "result.json"))

        state = load_state(adapter)
        final_attempt = next(
            attempt
            for attempt in state["attempts"]
            if attempt["id"] == state["finalRegressionAttemptId"]
        )
        self.assertEqual(5, len(final_attempt["caseRuns"]))
        self.assertTrue(all(run["status"] == "PASS" for run in final_attempt["caseRuns"]))
        baseline = final_attempt["sourceFingerprint"]
        self.assertTrue(
            all(
                run["sourceFingerprint"] == baseline
                and run["sourceAfterFingerprint"] == baseline
                for run in final_attempt["caseRuns"]
            )
        )
        self.assertTrue(json_output(run_cli(adapter, "audit", expected=0))["ok"])

    def test_unsupported_optional_case_is_not_run_and_is_reported(self) -> None:
        unavailable = "windows" if os.name != "nt" else "darwin"
        cases = [
            make_case("required-smoke", "smoke"),
            make_case(
                "optional-platform",
                "functional",
                required=False,
                platform=unavailable,
                depends_on=("required-smoke",),
            ),
        ]
        adapter = make_adapter(self.root, cases)
        run_cli(adapter, "init", expected=0)
        initial = json_output(run_cli(adapter, "run", expected=0))
        self.assertEqual("NOT_RUN", initial["cases"]["optional-platform"]["status"])
        completed = json_output(
            run_cli(adapter, "run", "--mode", "regression", expected=0)
        )
        self.assertEqual("COMPLETE", completed["status"])
        self.assertEqual("NOT_RUN", completed["cases"]["optional-platform"]["status"])
        report = json_output(run_cli(adapter, "audit", expected=0))
        self.assertTrue(report["ok"])

    def test_runnable_optional_failure_prevents_regression_completion(self) -> None:
        counter = self.root / "counter.json"
        counter.write_text("0\n", encoding="utf-8")
        script = (
            "import json, os\n"
            "from pathlib import Path\n"
            "counter = Path('counter.json')\n"
            "value = int(counter.read_text(encoding='utf-8')) + 1\n"
            "counter.write_text(str(value), encoding='utf-8')\n"
            "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            "(evidence / 'proof.json').write_text(json.dumps({'run': value}), encoding='utf-8')\n"
            "raise SystemExit(9 if value == 2 else 0)\n"
        )
        cases = [
            make_case("required-smoke", "smoke"),
            make_case(
                "optional-runnable",
                "functional",
                argv=(sys.executable, "-c", script),
                required=False,
                depends_on=("required-smoke",),
            ),
        ]
        adapter = make_adapter(self.root, cases)
        run_cli(adapter, "init", expected=0)
        run_cli(adapter, "run", expected=0)
        regression = json_output(
            run_cli(adapter, "run", "--mode", "regression", expected=1)
        )
        self.assertEqual("FAILED", regression["status"])
        self.assertEqual("FAILED", regression["cases"]["optional-runnable"]["status"])
        report = json_output(run_cli(adapter, "audit", expected=1))
        self.assertFalse(report["ok"])


if __name__ == "__main__":
    unittest.main()
