from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
PLUGIN_SCRIPTS = SKILL_ROOT.parents[1] / "scripts"
for path in (SCRIPTS, PLUGIN_SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import goal_workspace  # noqa: E402  (runtime sys.path injection above)
from verifier import (  # noqa: E402
    Campaign,
    VerificationError,
    advance,
    campaign_lock,
    record_repair,
    status_report,
)

CAMPAIGN_CLI = SCRIPTS / "campaign.py"


def goal_text(alias: str) -> str:
    return "\n".join(
        [
            "结果：交付经过验证的本地实现",
            f"证据与上下文：仓库文件；补充背景见 .steward/goals/{alias}/context.md",
            "范围：当前测试项目",
            "约束与授权：仅执行本地确定性命令",
            "完成标准：(C1) 命令通过并产生证明",
            "正当阻塞项：缺少本地运行环境",
            "最终交付：实现、回归结果和审计证据",
        ]
    )


def acceptance() -> dict:
    return {
        "schemaVersion": 1,
        "sourcePolicy": {"mode": "git-visible"},
        "cases": [
            {
                "id": "acceptance",
                "required": True,
                "platform": "any",
                "coversCriteria": ["C1"],
                "assertion": "app.txt 为 good 时命令成功并生成 proof.txt",
                "runnerHint": "运行读取 app.txt 的项目本地验收入口",
                "evidence": {
                    "requiredFiles": ["proof.txt"],
                    "nonEmptyFiles": ["proof.txt"],
                },
            }
        ],
    }


def marker_command() -> list[str]:
    return [
        sys.executable,
        "-c",
        (
            "import os,pathlib,sys; "
            "ok=pathlib.Path('app.txt').read_text(encoding='utf-8').strip()=='good'; "
            "pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'],'proof.txt').write_text('ok',encoding='utf-8') if ok else None; "
            "sys.exit(0 if ok else 1)"
        ),
    ]


def execution(command: list[str] | None = None) -> bytes:
    value = {
        "schemaVersion": 1,
        "cases": [
            {
                "id": "acceptance",
                "argv": command or marker_command(),
                "cwd": ".",
                "timeoutSeconds": 30,
                "bindingRationale": "该命令直接检查 app.txt 并生成 acceptance plan 要求的 proof.txt",
            }
        ],
    }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def waived_execution() -> bytes:
    """Required case plus an optional probe declared waive-with-report that always fails."""
    value = {
        "schemaVersion": 1,
        "cases": [
            {
                "id": "acceptance",
                "argv": marker_command(),
                "cwd": ".",
                "timeoutSeconds": 30,
                "bindingRationale": "该命令直接检查 app.txt 并生成 acceptance plan 要求的 proof.txt",
            },
            {
                "id": "probe",
                "argv": [sys.executable, "-c", "raise SystemExit(3)"],
                "cwd": ".",
                "timeoutSeconds": 30,
                "bindingRationale": "探针恒失败，用于验证 Draft 声明的 waive-with-report 行为",
            },
        ],
    }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def waived_acceptance() -> dict:
    plan = acceptance()
    plan["cases"].append(
        {
            "id": "probe",
            "required": False,
            "platform": "any",
            "coversCriteria": ["C1"],
            "assertion": "可选探针成功",
            "runnerHint": "运行可选探针入口",
            "evidence": {"requiredFiles": [], "nonEmptyFiles": []},
            "onFailure": "waive-with-report",
        }
    )
    return plan


def flip_acceptance() -> dict:
    """Two required cases whose assertions directly contradict each other,
    so that flipping flag.txt to satisfy one necessarily breaks the other."""

    def case(case_id: str, wants: str) -> dict:
        return {
            "id": case_id,
            "required": True,
            "platform": "any",
            "coversCriteria": ["C1"],
            "assertion": f"flag.txt 为 {wants} 时命令成功并生成 proof.txt",
            "runnerHint": "运行读取 flag.txt 的项目本地验收入口",
            "evidence": {"requiredFiles": ["proof.txt"], "nonEmptyFiles": ["proof.txt"]},
        }

    return {
        "schemaVersion": 1,
        "sourcePolicy": {"mode": "git-visible"},
        "cases": [case("flip-on", "on"), case("flip-off", "off")],
    }


def flip_runner(expected: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        (
            "import os,pathlib,sys; "
            f"ok=pathlib.Path('flag.txt').read_text(encoding='utf-8').strip()=='{expected}'; "
            "pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'],'proof.txt').write_text('ok',encoding='utf-8') if ok else None; "
            "sys.exit(0 if ok else 1)"
        ),
    ]


def flip_execution() -> bytes:
    value = {
        "schemaVersion": 1,
        "cases": [
            {
                "id": "flip-on",
                "argv": flip_runner("on"),
                "cwd": ".",
                "timeoutSeconds": 30,
                "bindingRationale": "检查 flag.txt 是否为 on 并生成 proof.txt",
            },
            {
                "id": "flip-off",
                "argv": flip_runner("off"),
                "cwd": ".",
                "timeoutSeconds": 30,
                "bindingRationale": "检查 flag.txt 是否为 off 并生成 proof.txt",
            },
        ],
    }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


class VerificationV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.name", "Verifier Tests"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "config",
                "user.email",
                "verify@example.invalid",
            ],
            check=True,
        )
        (self.root / "app.txt").write_text("good\n", encoding="utf-8")
        (self.root / ".gitignore").write_text("build/\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.root), "add", "app.txt", ".gitignore"], check=True
        )
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True
        )
        payload = {
            "objective": goal_text("goal-a"),
            "context": "# 已核实背景\n\n- 当前测试请求与 app.txt。\n",
            "acceptancePlan": acceptance(),
        }
        goal_workspace.create_goal_bundle(
            "goal-a", json.dumps(payload, ensure_ascii=False).encode(), self.root
        )
        self.previous = Path.cwd()
        os_chdir(self.root)

    def tearDown(self) -> None:
        os_chdir(self.previous)
        self.temporary.cleanup()

    def test_initial_run_completes(self) -> None:
        campaign = Campaign.initialize("goal-a", execution())
        with campaign_lock(campaign):
            report, code = advance(Campaign.load("goal-a"))
        self.assertEqual(0, code)
        self.assertEqual("COMPLETE", report["completionStatus"])
        self.assertEqual(
            "COMPLETE", status_report(Campaign.load("goal-a"))["completionStatus"]
        )
        # No repair ever happened, so the campaign owes no extra regression
        # sweep: the one initial attempt is the only attempt.
        self.assertEqual(["initial"], [a["mode"] for a in report["attempts"]])

    def test_failed_case_repair_and_targeted_retest_completes(self) -> None:
        (self.root / "app.txt").write_text("bad\n", encoding="utf-8")
        campaign = Campaign.initialize("goal-a", execution())
        with campaign_lock(campaign):
            report, code = advance(Campaign.load("goal-a"))
        self.assertEqual(1, code)
        self.assertEqual("REPAIR_REQUIRED", report["executionStatus"])
        (self.root / "app.txt").write_text("good\n", encoding="utf-8")
        repair = json.dumps(
            {
                "rootCause": "app.txt 使用了失败标记",
                "rootCauseSource": {"path": "app.txt", "lineStart": 1, "lineEnd": 1},
                "fixSummary": "将失败标记改为 good",
            },
            ensure_ascii=False,
        ).encode()
        with campaign_lock(Campaign.load("goal-a")):
            report = record_repair(Campaign.load("goal-a"), repair)
        self.assertEqual("PENDING", report["executionStatus"])
        with campaign_lock(Campaign.load("goal-a")):
            report, code = advance(Campaign.load("goal-a"))
        self.assertEqual(0, code)
        self.assertEqual(1, len(report["repairs"]))
        self.assertEqual("COMPLETE", report["completionStatus"])
        # The retest right after the repair only reran the repaired case; a
        # repair having happened at all then owes exactly one full regression
        # against the final source before completion is reported.
        self.assertEqual(
            ["initial", "retest", "regression"],
            [attempt["mode"] for attempt in report["attempts"]],
        )
        self.assertEqual(["acceptance"], report["attempts"][1]["caseIds"])
        self.assertEqual(["acceptance"], report["attempts"][2]["caseIds"])

    def test_final_regression_after_repair_catches_a_newly_broken_case(self) -> None:
        """A repair that fixes one required case can silently break another
        that was already passing. The retest right after the repair only
        reruns the fixed case and would miss this by itself; the final
        regression a repair now owes must catch it before completion."""
        shutil.rmtree(self.root / ".steward")
        payload = {
            "objective": goal_text("goal-a"),
            "context": "# 已核实背景\n",
            "acceptancePlan": flip_acceptance(),
        }
        goal_workspace.create_goal_bundle(
            "goal-a", json.dumps(payload, ensure_ascii=False).encode(), self.root
        )
        (self.root / "flag.txt").write_text("off\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "flag.txt"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "flag"], check=True)
        Campaign.initialize("goal-a", flip_execution())
        with campaign_lock(Campaign.load("goal-a")):
            report, code = advance(Campaign.load("goal-a"))
        self.assertEqual(1, code)
        self.assertEqual("REPAIR_REQUIRED", report["executionStatus"])
        self.assertEqual("flip-on", report["lastFailure"]["caseId"])
        initial = report["attempts"][0]
        flip_off_run = next(run for run in initial["runs"] if run["caseId"] == "flip-off")
        self.assertEqual("PASS", flip_off_run["status"])
        # The fix for "flip-on" flips the very flag "flip-off" depends on.
        (self.root / "flag.txt").write_text("on\n", encoding="utf-8")
        repair = json.dumps(
            {
                "rootCause": "flag.txt 处于 off，flip-on 要求 on",
                "rootCauseSource": {"path": "flag.txt", "lineStart": 1, "lineEnd": 1},
                "fixSummary": "将 flag.txt 改为 on",
            },
            ensure_ascii=False,
        ).encode()
        with campaign_lock(Campaign.load("goal-a")):
            record_repair(Campaign.load("goal-a"), repair)
        with campaign_lock(Campaign.load("goal-a")):
            report, code = advance(Campaign.load("goal-a"))
        # Without the final regression this would wrongly report COMPLETE:
        # the targeted retest only reruns "flip-on", and stale "flip-off"
        # evidence from before the repair would still look valid. The
        # regression sweep reruns "flip-off" too and must catch that the
        # repair broke it.
        self.assertEqual(1, code)
        self.assertEqual("REPAIR_REQUIRED", report["executionStatus"])
        self.assertEqual("flip-off", report["lastFailure"]["caseId"])
        self.assertEqual(
            ["initial", "retest", "regression"],
            [attempt["mode"] for attempt in report["attempts"]],
        )

    def test_source_drift_is_recorded_as_a_warning_and_does_not_block(self) -> None:
        Campaign.initialize("goal-a", execution())
        # Trailing whitespace changes the file's bytes (and so its fingerprint)
        # without affecting the stripped marker check, isolating the drift
        # warning from an actual acceptance failure.
        (self.root / "app.txt").write_text("good \n", encoding="utf-8")
        with campaign_lock(Campaign.load("goal-a")):
            report, code = advance(Campaign.load("goal-a"))
        self.assertEqual(0, code)
        self.assertEqual("COMPLETE", report["completionStatus"])
        self.assertEqual(1, len(report["driftWarnings"]))

    def test_index_drift_is_recorded_as_a_warning(self) -> None:
        Campaign.initialize("goal-a", execution())
        (self.root / "app.txt").write_text("staged\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "app.txt"], check=True)
        (self.root / "app.txt").write_text("good\n", encoding="utf-8")
        with campaign_lock(Campaign.load("goal-a")):
            report, code = advance(Campaign.load("goal-a"))
        self.assertEqual(0, code)
        self.assertEqual("COMPLETE", report["completionStatus"])
        self.assertEqual(1, len(report["driftWarnings"]))

    def test_ignored_build_outputs_do_not_drift_source(self) -> None:
        Campaign.initialize("goal-a", execution())
        build = self.root / "build"
        build.mkdir()
        (build / "cache.bin").write_bytes(b"ignored")
        with campaign_lock(Campaign.load("goal-a")):
            report, code = advance(Campaign.load("goal-a"))
        self.assertEqual(0, code)
        self.assertEqual("COMPLETE", report["completionStatus"])
        self.assertEqual([], report["driftWarnings"])

    def test_execution_plan_cannot_change_case_identity_or_use_bad_cwd(self) -> None:
        value = json.loads(execution())
        value["cases"][0]["id"] = "other"
        with self.assertRaisesRegex(VerificationError, "order"):
            Campaign.initialize("goal-a", json.dumps(value).encode())
        value = json.loads(execution())
        value["cases"][0]["cwd"] = "../outside"
        with self.assertRaises(VerificationError):
            Campaign.initialize("goal-a", json.dumps(value).encode())

    def test_artifact_tamper_makes_completion_incomplete(self) -> None:
        Campaign.initialize("goal-a", execution())
        with campaign_lock(Campaign.load("goal-a")):
            _, code = advance(Campaign.load("goal-a"))
        self.assertEqual(0, code)
        complete = Campaign.load("goal-a")
        run = complete.state["attempts"][0]["runs"][0]
        artifact = complete.campaign_root / run["artifactDir"] / "stdout.txt"
        artifact.write_text("tampered\n", encoding="utf-8")
        self.assertEqual(
            "INCOMPLETE", status_report(Campaign.load("goal-a"))["completionStatus"]
        )

    def test_bundle_or_execution_plan_tamper_blocks_loading(self) -> None:
        Campaign.initialize("goal-a", execution())
        path = self.root / ".steward" / "goals" / "goal-a" / "execution-plan.json"
        path.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(VerificationError):
            Campaign.load("goal-a")

    def test_tampered_state_status_is_rejected(self) -> None:
        campaign = Campaign.initialize("goal-a", execution())
        state = json.loads(campaign.state_path.read_text(encoding="utf-8"))
        state["status"] = "NOT-A-REAL-STATUS"
        campaign.state_path.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(VerificationError):
            Campaign.load("goal-a")

    def test_public_cli_completes_the_no_repair_flow(self) -> None:
        initialized = subprocess.run(
            [
                sys.executable,
                "-B",
                str(CAMPAIGN_CLI),
                "init",
                "--goal",
                "goal-a",
                "--execution-plan",
                "-",
            ],
            cwd=self.root,
            input=execution(),
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, initialized.returncode, initialized.stderr.decode())
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(CAMPAIGN_CLI),
                "advance",
                "--goal",
                "goal-a",
            ],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr.decode())
        self.assertEqual("COMPLETE", json.loads(result.stdout)["completionStatus"])

    def test_stale_per_goal_lock_is_recovered(self) -> None:
        campaign = Campaign.initialize("goal-a", execution())
        lock = campaign.campaign_root / "campaign.lock"
        lock.write_text(
            json.dumps({"pid": 99_999_999, "createdAt": "stale"}) + "\n",
            encoding="utf-8",
        )
        with campaign_lock(campaign):
            self.assertTrue(lock.exists())
        self.assertFalse(lock.exists())

    def recreate_goal_with_waived_plan(self, alias: str = "goal-a") -> None:
        shutil.rmtree(self.root / ".steward")
        payload = {
            "objective": goal_text(alias),
            "context": "# 已核实背景\n\n- 当前测试请求与 app.txt。\n",
            "acceptancePlan": waived_acceptance(),
        }
        goal_workspace.create_goal_bundle(
            alias, json.dumps(payload, ensure_ascii=False).encode(), self.root
        )

    def test_waived_optional_failure_records_evidence_and_completes(self) -> None:
        self.recreate_goal_with_waived_plan()
        Campaign.initialize("goal-a", waived_execution())
        with campaign_lock(Campaign.load("goal-a")):
            report, code = advance(Campaign.load("goal-a"))
        self.assertEqual(0, code)
        self.assertEqual("COMPLETE", report["completionStatus"])
        attempt = report["attempts"][0]
        self.assertEqual("WAIVED", attempt["status"])
        self.assertEqual(["probe"], attempt["waivedCaseIds"])
        probe_run = next(run for run in attempt["runs"] if run["caseId"] == "probe")
        self.assertEqual("FAILED", probe_run["status"])
        self.assertEqual(["probe"], report["waivedCaseIds"])

    def test_waived_failure_survives_targeted_retest_of_a_different_case(self) -> None:
        """A required case and an unrelated waived-optional case fail in the
        same initial attempt. Repairing the required case reruns only that
        case for fast feedback, but the repair still owes one final
        regression before completion, which reruns "probe" too and must
        still tolerate its declared-waivable failure."""
        self.recreate_goal_with_waived_plan()
        (self.root / "app.txt").write_text("bad\n", encoding="utf-8")
        Campaign.initialize("goal-a", waived_execution())
        with campaign_lock(Campaign.load("goal-a")):
            report, code = advance(Campaign.load("goal-a"))
        self.assertEqual("REPAIR_REQUIRED", report["executionStatus"])
        self.assertEqual("acceptance", report["lastFailure"]["caseId"])
        # Both cases ran in the initial attempt even though "acceptance" failed
        # first; "probe" was not skipped by an early exit.
        initial = report["attempts"][0]
        self.assertEqual(
            {"acceptance", "probe"}, {run["caseId"] for run in initial["runs"]}
        )
        self.assertEqual(["probe"], initial["waivedCaseIds"])
        (self.root / "app.txt").write_text("good\n", encoding="utf-8")
        repair = json.dumps(
            {
                "rootCause": "app.txt 使用了失败标记",
                "rootCauseSource": {"path": "app.txt", "lineStart": 1, "lineEnd": 1},
                "fixSummary": "将失败标记改为 good",
            },
            ensure_ascii=False,
        ).encode()
        with campaign_lock(Campaign.load("goal-a")):
            record_repair(Campaign.load("goal-a"), repair)
        with campaign_lock(Campaign.load("goal-a")):
            report, code = advance(Campaign.load("goal-a"))
        self.assertEqual(0, code)
        self.assertEqual("COMPLETE", report["completionStatus"])
        retest, regression = report["attempts"][1], report["attempts"][2]
        self.assertEqual("retest", retest["mode"])
        self.assertEqual(["acceptance"], retest["caseIds"])
        self.assertEqual("regression", regression["mode"])
        self.assertEqual(["acceptance", "probe"], regression["caseIds"])
        self.assertEqual(["probe"], regression["waivedCaseIds"])
        self.assertEqual(["probe"], report["waivedCaseIds"])
        # "probe" evidence now points at the final regression's run, not the
        # initial attempt's — the repair made that case owe one more proof
        # that it still only fails in the same tolerated way.
        probe_run_id = next(
            run["runId"] for run in regression["runs"] if run["caseId"] == "probe"
        )
        self.assertNotEqual(
            next(run["runId"] for run in initial["runs"] if run["caseId"] == "probe"),
            probe_run_id,
        )
        self.assertEqual(probe_run_id, report["completion"]["evidenceRunIds"]["probe"])

    def test_declared_writable_files_rollback_and_stay_out_of_source_identity(
        self,
    ) -> None:
        plan = waived_acceptance()
        plan["cases"] = plan["cases"][:1]
        plan["sourcePolicy"] = {
            "mode": "git-visible",
            "writable": ["coverage.lcov", "fresh-artifact.txt", "notes.txt"],
        }
        (self.root / "notes.txt").write_text("keep\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "notes.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-qm", "notes"], check=True
        )
        payload = {
            "objective": goal_text("goal-b"),
            "context": "# 已核实背景\n",
            "acceptancePlan": plan,
        }
        goal_workspace.create_goal_bundle(
            "goal-b", json.dumps(payload, ensure_ascii=False).encode(), self.root
        )
        runner = (
            "import os,pathlib,sys; "
            "ok=pathlib.Path('app.txt').read_text(encoding='utf-8').strip()=='good'; "
            "pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'],'proof.txt').write_text('ok') if ok else None; "
            "pathlib.Path('coverage.lcov').write_text('DA:1,1'); "
            "p=pathlib.Path('fresh-artifact.txt'); p.write_text('v1') if not p.exists() else p.write_text('v2'); "
            "pathlib.Path('notes.txt').write_text('mutated\\n'); "
            "sys.exit(0 if ok else 1)"
        )
        value = {
            "schemaVersion": 1,
            "cases": [
                {
                    "id": "acceptance",
                    "argv": [sys.executable, "-c", runner],
                    "cwd": ".",
                    "timeoutSeconds": 30,
                    "bindingRationale": "生成 proof 并写声明可写文件",
                }
            ],
        }
        Campaign.initialize("goal-b", json.dumps(value, ensure_ascii=False).encode())
        with campaign_lock(Campaign.load("goal-b")):
            report, code = advance(Campaign.load("goal-b"))
        self.assertEqual(0, code)
        self.assertEqual("COMPLETE", report["completionStatus"])
        run = report["attempts"][0]["runs"][0]
        actions = {item["path"]: item["action"] for item in run["writableMutations"]}
        self.assertEqual(
            {
                "coverage.lcov": "deleted",
                "fresh-artifact.txt": "deleted",
                "notes.txt": "restored",
            },
            actions,
        )
        self.assertFalse((self.root / "coverage.lcov").exists())
        self.assertFalse((self.root / "fresh-artifact.txt").exists())
        self.assertEqual(
            "keep\n", (self.root / "notes.txt").read_text(encoding="utf-8")
        )
        artifact_dir = Campaign.load("goal-b").campaign_root / run["artifactDir"]
        capture = json.loads(
            (artifact_dir / "writable-capture.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            ["coverage.lcov", "fresh-artifact.txt", "notes.txt"], capture["captured"]
        )

    def test_case_writing_undeclared_source_requires_repair(self) -> None:
        runner = [
            sys.executable,
            "-c",
            "import pathlib,sys; pathlib.Path('app.txt').write_text('mutated\\n'); sys.exit(0)",
        ]
        Campaign.initialize("goal-a", execution(runner))
        with campaign_lock(Campaign.load("goal-a")):
            report, code = advance(Campaign.load("goal-a"))
        self.assertEqual(1, code)
        self.assertEqual("REPAIR_REQUIRED", report["executionStatus"])
        self.assertIn("protected source", report["attempts"][0]["runs"][0]["reason"])

    def test_journal_claiming_undeclared_waiver_is_rejected(self) -> None:
        campaign = Campaign.initialize("goal-a", execution())
        with campaign_lock(campaign):
            _, code = advance(Campaign.load("goal-a"))
        self.assertEqual(0, code)
        state = json.loads(campaign.state_path.read_text(encoding="utf-8"))
        state["attempts"][-1]["status"] = "WAIVED"
        state["attempts"][-1]["waivedCaseIds"] = ["acceptance"]
        campaign.state_path.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(VerificationError, "waives"):
            Campaign.load("goal-a")


def os_chdir(path: Path) -> None:
    import os

    os.chdir(path)


if __name__ == "__main__":
    unittest.main()
