from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Optional

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = PLUGIN_ROOT / "scripts"
PROFILES_ROOT = PLUGIN_ROOT / "references" / "architecture-profiles"
PROFILE_CLI = SHARED_SCRIPTS / "architecture_profiles.py"
GOAL_CLI = SHARED_SCRIPTS / "goal_contract.py"
SEMANTIC_CLI = SHARED_SCRIPTS / "semantic_review.py"
ROUTER_UPDATE = (
    PLUGIN_ROOT
    / "skills"
    / "write-agent-guides"
    / "scripts"
    / "update_engineering_router.py"
)
ROUTER_VALIDATE = ROUTER_UPDATE.with_name("validate_engineering_router.py")
CLOSED_LOOP_CLI = (
    PLUGIN_ROOT / "skills" / "run-closed-loop-verification" / "scripts" / "campaign.py"
)

if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

from goal_contract import goal_contract_sha256, load_goal_contract
from invariant_contract import (
    aggregate_applicability,
    load_invariant_map,
)
from semantic_review import (
    case_candidates,
    load_review_manifest,
    review_manifest_sha256,
)


def write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    expected: int = 0,
    env: Optional[Mapping[str, str]] = None,  # noqa: UP045 -- Python 3.9 syntax
) -> subprocess.CompletedProcess[str]:
    child_env = os.environ.copy()
    if env is not None:
        child_env.update(env)
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd),
        env=child_env,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if completed.returncode != expected:
        raise AssertionError(
            "unexpected command result\n"
            f"argv={list(argv)!r}\n"
            f"returncode={completed.returncode}, expected={expected}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    return completed


def json_stdout(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            "command did not emit JSON\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        ) from error
    if not isinstance(value, dict):
        raise TypeError(f"command JSON is not an object: {value!r}")
    return value


def goal_text() -> str:
    return (
        "结果：交付可追踪的工程控制闭环\n"
        "证据与上下文：使用项目内绑定的目标、不变量、审查与测试证据\n"
        "范围：验证一个本地 Python 服务的代表性行为\n"
        "约束与授权：仅执行无外部副作用的本地命令\n"
        "完成标准：(C1) 最终完整回归覆盖目标、不变量和语义反例\n"
        "正当阻塞项：缺少已声明且不可替代的本地执行条件\n"
        "最终交付：报告同源完整回归和审计证据\n"
    )


def build_minimal_document_project(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True)
    for relative, title in (
        ("README.md", "Demo"),
        ("STATUS.md", "Status"),
        ("CONTRIBUTING.md", "Contributing"),
        ("AGENTS.md", "Agents"),
    ):
        (root / relative).write_text(f"# {title}\n", encoding="utf-8")
    for relative, title in (
        ("README.md", "Documentation"),
        ("product.md", "Product"),
        ("development-rules.md", "Development Rules"),
        ("source-code-size-and-responsibility-rules.md", "Source Rules"),
    ):
        (docs / relative).write_text(f"# {title}\n", encoding="utf-8")


class RelocationSmokeTests(unittest.TestCase):
    def test_packaged_entry_points_run_outside_checkout_with_empty_pythonpath(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            relocated = temporary_root / "installed" / "steward"
            shutil.copytree(
                PLUGIN_ROOT,
                relocated,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            outside = temporary_root / "outside"
            outside.mkdir()
            goal = outside / "goal.txt"
            goal.write_text(goal_text(), encoding="utf-8")
            review = write_json(
                outside / "semantic-review.json",
                {
                    "schemaId": "steward.semantic-review",
                    "schemaVersion": 1,
                    "findings": [],
                },
            )
            isolated_env = {"PYTHONPATH": "", "PYTHONNOUSERSITE": "1"}
            commands = (
                (
                    relocated / "scripts" / "architecture_profiles.py",
                    ("validate",),
                    "architecture profiles valid: 7",
                ),
                (
                    relocated / "scripts" / "goal_contract.py",
                    ("check", str(goal)),
                    "VALID sha256:",
                ),
                (
                    relocated / "scripts" / "semantic_review.py",
                    ("check", str(review), "--project-root", str(outside)),
                    "VALID sha256:",
                ),
                (
                    relocated
                    / "skills"
                    / "write-agent-guides"
                    / "scripts"
                    / "update_engineering_router.py",
                    ("--help",),
                    "engineering router",
                ),
                (
                    relocated
                    / "skills"
                    / "write-project-docs"
                    / "scripts"
                    / "validate_project_docs.py",
                    ("--help",),
                    "project_root",
                ),
                (
                    relocated
                    / "skills"
                    / "run-closed-loop-verification"
                    / "scripts"
                    / "campaign.py",
                    ("--help",),
                    "evidence-driven closed-loop verification campaign",
                ),
            )
            for script, arguments, expected_text in commands:
                with self.subTest(script=script.relative_to(relocated)):
                    result = run_command(
                        [sys.executable, str(script), *arguments],
                        cwd=outside,
                        env=isolated_env,
                    )
                    combined = result.stdout + result.stderr
                    self.assertIn(expected_text, combined)
                    self.assertNotIn(str(PLUGIN_ROOT), combined)


class FullControlPlaneChainTests(unittest.TestCase):
    def test_profile_router_review_and_closed_loop_share_one_evidence_chain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_minimal_document_project(root)
            workflow = root / ".steward"
            workflow.mkdir()
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "service.py").write_text(
                "def guarded_transition():\n    return 'safe'\n",
                encoding="utf-8",
            )
            runner_path = root / "tests" / "run_semantic_case.py"
            runner_path.write_text(
                "import json\n"
                "import os\n"
                "from pathlib import Path\n"
                "\n"
                "safe = Path('tests/semantic-fixture.txt').read_text(encoding='utf-8').strip() == 'safe'\n"
                "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
                "(evidence / 'proof.json').write_text(json.dumps({'safe': safe}), encoding='utf-8')\n"
                "raise SystemExit(0 if safe else 1)\n",
                encoding="utf-8",
            )
            (root / "tests" / "semantic-fixture.txt").write_text(
                "safe\n", encoding="utf-8"
            )

            evidence_path = write_json(
                workflow / "profile-evidence.json",
                {
                    "schemaVersion": 1,
                    "components": [
                        {
                            "scope": "services/api",
                            "signals": ["manifest:python", "source:python"],
                            "capabilities": {},
                        }
                    ],
                },
            )
            selection_path = workflow / "profile-selection.json"
            compiled_path = workflow / "compiled-profiles.json"
            run_command(
                [
                    sys.executable,
                    str(PROFILE_CLI),
                    "--profiles-root",
                    str(PROFILES_ROOT),
                    "select",
                    "--evidence",
                    str(evidence_path),
                    "--output",
                    str(selection_path),
                ],
                cwd=root,
            )
            run_command(
                [
                    sys.executable,
                    str(PROFILE_CLI),
                    "--profiles-root",
                    str(PROFILES_ROOT),
                    "compile",
                    "--selection",
                    str(selection_path),
                    "--output",
                    str(compiled_path),
                ],
                cwd=root,
            )
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            compiled = json.loads(compiled_path.read_text(encoding="utf-8"))
            self.assertEqual(["python"], [item["id"] for item in selection["profiles"]])
            self.assertTrue(compiled["invariants"])

            invariant_ids = sorted(item["id"] for item in compiled["invariants"])
            architecture_lines = ["# Architecture", ""]
            bindings = []
            for invariant in compiled["invariants"]:
                architecture_lines.extend(
                    [
                        f'<a id="{invariant["id"].lower()}"></a>',
                        f"## {invariant['id']}",
                        invariant["outcome"],
                        "",
                    ]
                )
                scope_states = invariant["applicabilityByScope"]
                applicability = aggregate_applicability(
                    item["state"] for item in scope_states
                )
                binding = {
                    "invariantId": invariant["id"],
                    "source": {
                        "kind": "profile",
                        "profileId": invariant["profileId"],
                        "profileVersion": invariant["profileVersion"],
                        "profileDigest": invariant["profileDigest"],
                    },
                    "scopes": invariant["scopes"],
                    "trigger": "changing selected Python service behavior",
                    "authority": {
                        "path": "docs/architecture.md",
                        "anchor": invariant["id"].lower(),
                    },
                    "applicability": applicability,
                    "applicabilityByScope": scope_states,
                    "status": "direct"
                    if applicability == "applicable"
                    else applicability,
                    "evidence": ["tests/run_semantic_case.py"],
                    "enforcement": {
                        "kind": "mechanical",
                        "evidence": ["tests/run_semantic_case.py"],
                        "validationEntry": "`python3 tests/run_semantic_case.py`",
                    },
                }
                if applicability == "not_applicable":
                    binding["notApplicableReason"] = (
                        "Every compiled project scope is technically not applicable"
                    )
                bindings.append(binding)
            (root / "docs" / "architecture.md").write_text(
                "\n".join(architecture_lines), encoding="utf-8"
            )
            invariant_path = write_json(
                workflow / "invariants.json",
                {
                    "schemaVersion": 1,
                    "profileSelection": {
                        "path": ".steward/profile-selection.json",
                        "digest": selection["contentDigest"],
                    },
                    "bindings": sorted(bindings, key=lambda item: item["invariantId"]),
                },
            )
            invariant_map = load_invariant_map(
                invariant_path, PROFILES_ROOT, project_root=root
            )
            self.assertEqual(
                invariant_ids,
                list(invariant_map.hard_invariant_ids),
            )
            self.assertEqual(
                invariant_ids,
                list(invariant_map.triggered_hard_invariant_ids),
            )

            run_command(
                [
                    sys.executable,
                    str(ROUTER_UPDATE),
                    str(root),
                    "--profiles-root",
                    str(PROFILES_ROOT),
                ],
                cwd=root,
            )
            run_command(
                [
                    sys.executable,
                    str(ROUTER_VALIDATE),
                    str(root),
                    "--profiles-root",
                    str(PROFILES_ROOT),
                ],
                cwd=root,
            )
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(
                1,
                agents.count("<!-- write-agent-guides:engineering-router:start -->"),
            )
            for invariant_id in invariant_ids:
                self.assertIn(invariant_id, agents)

            goal_path = root / ".steward" / "goal.txt"
            goal_path.write_text(goal_text(), encoding="utf-8")
            goal = load_goal_contract(goal_path)
            goal_digest = goal_contract_sha256(goal)
            goal_cli_digest = run_command(
                [sys.executable, str(GOAL_CLI), "digest", str(goal_path)],
                cwd=root,
            ).stdout.strip()
            self.assertEqual(goal_digest, goal_cli_digest)

            location = {"path": "src/service.py", "lineStart": 1, "lineEnd": 2}
            runner_location = {
                "path": "tests/run_semantic_case.py",
                "lineStart": 1,
                "lineEnd": len(runner_path.read_text(encoding="utf-8").splitlines()),
            }
            runner = {
                "argv": [sys.executable, "tests/run_semantic_case.py"],
                "cwd": ".",
                "timeoutSeconds": 10,
                "fixture": "tests/semantic-fixture.txt",
                "externalCapabilities": [],
                "evidence": {
                    "requiredFiles": ["proof.json"],
                    "nonEmptyFiles": ["proof.json"],
                },
                "sourceEvidence": [
                    {
                        "location": runner_location,
                        "fact": "This source defines the exact deterministic counterexample runner",
                    }
                ],
            }
            finding_id = "RF-FULL-CHAIN-001"
            case_id = "semantic-counterexample"
            review_path = write_json(
                workflow / "semantic-review.json",
                {
                    "schemaId": "steward.semantic-review",
                    "schemaVersion": 1,
                    "findings": [
                        {
                            "id": finding_id,
                            "title": "Unsafe transition must remain unreachable",
                            "required": True,
                            "resolutionState": "open",
                            "support": "code-supported",
                            "criteriaIds": ["C1"],
                            "invariantIds": invariant_ids,
                            "evidence": [
                                {
                                    "location": location,
                                    "fact": "The selected service exposes the guarded transition",
                                }
                            ],
                            "triggerPath": [
                                {
                                    "step": 1,
                                    "location": location,
                                    "condition": "The deterministic counterexample fixture is applied",
                                    "transition": "The guarded transition produces an observable result",
                                }
                            ],
                            "observableConsequence": (
                                "The evidence file records whether the transition remained safe"
                            ),
                            "counterexample": {
                                "preconditions": [
                                    "The repository fixture is available"
                                ],
                                "steps": [
                                    "Execute the exact repository-evidenced runner"
                                ],
                                "expectedOutcome": "The runner writes a non-empty safe proof",
                                "riskOutcome": "The runner fails or reports an unsafe transition",
                                "falsifiedWhen": "Final regression records the safe proof",
                            },
                            "caseCandidate": {
                                "id": case_id,
                                "category": "functional",
                                "required": True,
                                "platform": "any",
                                "dependsOn": [],
                                "coversCriteria": ["C1"],
                                "coversInvariants": invariant_ids,
                                "reviewFindingIds": [finding_id],
                                "scenarioTags": ["failure"],
                                "quick": True,
                                "runner": runner,
                                "conversionBlockers": [],
                            },
                        }
                    ],
                },
            )
            review_manifest = load_review_manifest(review_path, project_root=root)
            review_digest = review_manifest_sha256(review_manifest)
            semantic_check = run_command(
                [
                    sys.executable,
                    str(SEMANTIC_CLI),
                    "check",
                    str(review_path),
                    "--project-root",
                    str(root),
                ],
                cwd=root,
            )
            self.assertIn(review_digest, semantic_check.stdout)
            exported_candidates = json.loads(
                run_command(
                    [
                        sys.executable,
                        str(SEMANTIC_CLI),
                        "case-candidates",
                        str(review_path),
                        "--project-root",
                        str(root),
                    ],
                    cwd=root,
                ).stdout
            )
            self.assertEqual(
                list(case_candidates(review_manifest)), exported_candidates
            )

            source_files = sorted(
                {
                    ".steward/compiled-profiles.json",
                    ".steward/goal.txt",
                    ".steward/invariants.json",
                    ".steward/profile-evidence.json",
                    ".steward/profile-selection.json",
                    ".steward/semantic-review.json",
                    "AGENTS.md",
                    "docs/architecture.md",
                    "src/service.py",
                    "tests/run_semantic_case.py",
                    "tests/semantic-fixture.txt",
                }
            )
            write_json(root / "source-manifest.json", {"files": source_files})
            candidate = exported_candidates[0]
            exact_runner = candidate["runner"]
            self.assertIsNotNone(exact_runner)
            case = {
                "id": candidate["id"],
                "category": candidate["category"],
                "required": candidate["required"],
                "platform": candidate["platform"],
                "dependsOn": candidate["dependsOn"],
                "coversCriteria": candidate["coversCriteria"],
                "coversInvariants": candidate["coversInvariants"],
                "reviewFindingIds": candidate["reviewFindingIds"],
                "scenarioTags": candidate["scenarioTags"],
                "quick": candidate["quick"],
                "argv": exact_runner["argv"],
                "cwd": exact_runner["cwd"],
                "timeoutSeconds": exact_runner["timeoutSeconds"],
                "fixture": exact_runner["fixture"],
                "externalCapabilities": exact_runner["externalCapabilities"],
                "evidence": exact_runner["evidence"],
            }
            adapter_path = write_json(
                root / "adapter.json",
                {
                    "schemaVersion": 1,
                    "projectId": "full-chain-fixture",
                    "projectRoot": ".",
                    "campaignRoot": ".campaign",
                    "source": {
                        "provider": "manifest",
                        "manifest": "source-manifest.json",
                        "excludes": [".campaign"],
                    },
                    "localOnly": {
                        "enabled": True,
                        "allowedExternalCapabilities": [],
                    },
                    "traceability": {
                        "goalContract": {
                            "path": ".steward/goal.txt",
                            "contractVersion": 1,
                            "sha256": goal_digest,
                        },
                        "invariants": {
                            "path": ".steward/invariants.json",
                            "sha256": invariant_map.invariant_map_sha256,
                        },
                        "reviewFindings": {
                            "path": ".steward/semantic-review.json",
                            "sha256": review_digest,
                        },
                        "requiredScenarios": ["failure"],
                    },
                    "cases": [case],
                },
            )

            def campaign(*arguments: str, expected: int = 0) -> dict[str, Any]:
                return json_stdout(
                    run_command(
                        [
                            sys.executable,
                            str(CLOSED_LOOP_CLI),
                            *arguments,
                            "--adapter",
                            str(adapter_path),
                        ],
                        cwd=root,
                        expected=expected,
                    )
                )

            initialized = campaign("init")
            self.assertEqual(
                invariant_ids,
                initialized["traceSnapshot"]["invariants"]["hardInvariantIds"],
            )
            quick = campaign("run", "--phase", "quick")
            self.assertEqual("PASS", quick["cases"][case_id]["quickStatus"])
            self.assertEqual("PENDING", quick["status"])
            quick_audit = campaign("audit", expected=1)
            self.assertFalse(quick_audit["ok"])

            campaign("run", "--phase", "full", "--mode", "initial")
            final = campaign("run", "--phase", "full", "--mode", "regression")
            self.assertEqual("COMPLETE", final["status"])
            audit = campaign("audit")
            self.assertTrue(audit["ok"])
            self.assertEqual([case_id], audit["traceability"]["criteria"]["C1"])
            self.assertEqual(
                {invariant_id: [case_id] for invariant_id in invariant_ids},
                audit["traceability"]["invariants"],
            )
            self.assertEqual(
                [case_id],
                audit["traceability"]["requiredScenarios"]["failure"],
            )
            self.assertEqual(
                [case_id],
                audit["traceability"]["reviewFindings"][finding_id]["resolvedCases"],
            )


class ControlSkillLifecycleContractTests(unittest.TestCase):
    def test_orchestrator_delegates_phase_specific_repair_continuation(self) -> None:
        skill = (
            PLUGIN_ROOT / "skills" / "run-engineering-control-loop" / "SKILL.md"
        ).read_text(encoding="utf-8")
        state = (
            PLUGIN_ROOT
            / "skills"
            / "run-closed-loop-verification"
            / "references"
            / "state-and-evidence.md"
        ).read_text(encoding="utf-8")
        self.assertIn("run-closed-loop-verification", skill)
        self.assertIn("retest, recovery, new-root", skill)
        self.assertIn("audit contracts", skill)
        self.assertNotIn("quick failure reruns the complete quick phase", skill)
        self.assertNotIn("regression failure returns directly", skill)
        self.assertIn("`resumeMode`", state)
        self.assertIn("quick PASS transitions it to `initial`", state)
        self.assertIn("initial PASS to `regression`", state)
        self.assertNotIn("retest → remaining ordinary full initial coverage", skill)

    def test_configure_contract_binds_goal_and_safe_read_only_candidates(self) -> None:
        directory = PLUGIN_ROOT / "skills" / "configure-project-verification"
        skill = (directory / "SKILL.md").read_text(encoding="utf-8")
        contract = (directory / "references" / "configuration-contract.md").read_text(
            encoding="utf-8"
        )
        agent = (directory / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("Call `get_goal` only when", skill)
        self.assertIn("this skill never creates or updates it", skill)
        self.assertIn("renderer `--check`/`--expected`", skill)
        self.assertIn("configuration-contract.md", skill)
        self.assertNotIn("case/Unicode-equivalent portable collisions", skill)
        self.assertIn("base64 candidate bytes", contract)
        self.assertIn("case/Unicode-equivalent portable collisions", contract)
        self.assertIn("other hosts remain review-only", contract)
        self.assertIn("configure-project-verification", agent)
        self.assertIn("不要运行 campaign", agent)


if __name__ == "__main__":
    unittest.main()
