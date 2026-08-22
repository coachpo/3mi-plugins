from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .helpers import (
        json_output,
        make_adapter,
        make_case,
        read_json,
        run_cli,
        write_fix_for_latest_failure,
        write_json,
    )
except ImportError:
    from helpers import (  # type: ignore
        json_output,
        make_adapter,
        make_case,
        read_json,
        run_cli,
        write_fix_for_latest_failure,
        write_json,
    )


PLUGIN_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))

from goal_contract import goal_contract_sha256, load_goal_contract
from invariant_contract import load_invariant_map
from semantic_review import load_review_manifest, review_manifest_sha256

INV_ID = "INV-APP-0123456789AB"
OTHER_INV_ID = "INV-ZZZ-ABCDEF012346"
RF_ID = "RF-COUNTEREXAMPLE-001"
OTHER_RF_ID = "RF-UNRELATED-002"


def review_request(
    source_fingerprint: str,
    *,
    requested_paths: tuple[str, ...] = ("source.txt",),
    kind: str = "source",
    base_identity: str = "base-v1",
    head_identity: str = "head-v1",
) -> dict:
    target = {
        "kind": kind,
        "sourceFingerprint": source_fingerprint,
    }
    if kind == "diff":
        target.update(
            {
                "baseIdentity": base_identity,
                "headIdentity": head_identity,
            }
        )
    core = {
        "target": target,
        "requestedPaths": sorted(requested_paths),
    }
    encoded = json.dumps(
        core,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        **core,
        "requestSha256": "sha256:" + hashlib.sha256(encoded).hexdigest(),
    }


def goal_text(*criteria: str) -> str:
    entries = "；".join(
        "(C%d) %s" % (index, text) for index, text in enumerate(criteria, start=1)
    )
    return (
        "结果：交付可验证的本地实现\n"
        "证据与上下文：使用仓库内的确定性证据\n"
        "范围：覆盖声明的验收行为\n"
        "约束与授权：仅执行无外部副作用的本地验证\n"
        "完成标准：" + entries + "\n"
        "正当阻塞项：缺少已声明的本地前置条件\n"
        "最终交付：报告验证结果和证据路径\n"
    )


def make_traceable_adapter(
    root: Path,
    criteria: tuple[str, ...],
    *,
    covered: tuple[str, ...],
    required_scenarios: tuple[str, ...] = (),
    scenario_tags: tuple[str, ...] = (),
) -> Path:
    (root / "source.txt").write_text("stable source\n", encoding="utf-8")
    goal_path = root / "GOAL.md"
    goal_path.write_text(goal_text(*criteria), encoding="utf-8")
    authority_path = root / "AGENTS.md"
    authority_path.write_text(
        "# Local contract\n\n<a id=\"inv-none-abcdef012345\"></a>\nRule.\n",
        encoding="utf-8",
    )
    authority_digest = "sha256:" + hashlib.sha256(
        authority_path.read_bytes()
    ).hexdigest()
    invariants_path = write_json(
        root / "invariants.json",
        {
            "schemaVersion": 1,
            "bindings": [
                {
                    "invariantId": "INV-NONE-ABCDEF012345",
                    "source": {
                        "kind": "project",
                        "version": "1.0.0",
                        "digest": authority_digest,
                    },
                    "scopes": ["."],
                    "trigger": "This fixture deliberately leaves the rule out of scope",
                    "authority": {
                        "path": "AGENTS.md",
                        "anchor": "inv-none-abcdef012345",
                    },
                    "applicability": "not_applicable",
                    "status": "not_applicable",
                    "evidence": ["source.txt"],
                    "notApplicableReason": "No architecture behavior is exercised",
                    "enforcement": {"kind": "manual", "evidence": []},
                }
            ],
        },
    )
    review_path = write_json(
        root / "review-findings.json",
        {
            "schemaId": "steward.semantic-review",
            "schemaVersion": 1,
            "findings": [],
        },
    )
    goal_digest = goal_contract_sha256(load_goal_contract(goal_path))
    invariant_digest = load_invariant_map(invariants_path).invariant_map_sha256
    review_digest = review_manifest_sha256(
        load_review_manifest(review_path, project_root=root)
    )
    case = make_case("trace-case", "functional")
    case.update(
        {
            "coversCriteria": list(covered),
            "coversInvariants": [],
            "reviewFindingIds": [],
            "scenarioTags": list(scenario_tags),
            "quick": True,
        }
    )
    adapter = make_adapter(
        root,
        [case],
        source_files=(
            "source.txt",
            "AGENTS.md",
            "GOAL.md",
            "invariants.json",
            "review-findings.json",
        ),
    )
    value = read_json(adapter)
    value["traceability"] = {
        "goalContract": {
            "path": "GOAL.md",
            "contractVersion": 1,
            "sha256": goal_digest,
        },
        "invariants": {
            "path": "invariants.json",
            "sha256": invariant_digest,
        },
        "reviewFindings": {
            "path": "review-findings.json",
            "sha256": review_digest,
        },
        "requiredScenarios": list(required_scenarios),
    }
    return write_json(adapter, value)


def review_finding(case: dict) -> dict:
    location = {"path": "source.txt", "lineStart": 1, "lineEnd": 1}
    return {
        "id": RF_ID,
        "title": "The counterexample reaches the unsafe outcome",
        "required": True,
        "resolutionState": "open",
        "support": "code-supported",
        "criteriaIds": ["C1"],
        "invariantIds": [INV_ID],
        "evidence": [
            {
                "location": location,
                "fact": "The repository fixture represents the risky transition",
            }
        ],
        "triggerPath": [
            {
                "step": 1,
                "location": location,
                "condition": "The counterexample input is applied",
                "transition": "The guarded transition executes",
            }
        ],
        "observableConsequence": "The evidence distinguishes safe and unsafe behavior",
        "counterexample": {
            "preconditions": ["The local deterministic fixture exists"],
            "steps": ["Execute the required campaign case"],
            "expectedOutcome": "The guardrail evidence is non-empty",
            "riskOutcome": "The case fails or omits its evidence",
            "falsifiedWhen": "The final regression binds passing guardrail evidence",
        },
        "caseCandidate": {
            "id": case["id"],
            "category": "functional",
            "required": True,
            "platform": "any",
            "dependsOn": [],
            "coversCriteria": ["C1"],
            "coversInvariants": [INV_ID],
            "reviewFindingIds": [RF_ID],
            "scenarioTags": ["failure"],
            "quick": True,
            "runner": {
                "argv": list(case["argv"]),
                "cwd": case["cwd"],
                "timeoutSeconds": case["timeoutSeconds"],
                "fixture": case["fixture"],
                "externalCapabilities": list(case["externalCapabilities"]),
                "evidence": dict(case["evidence"]),
                "sourceEvidence": [
                    {
                        "location": location,
                        "fact": "The executable counterexample is bound to this source",
                    }
                ],
            },
            "conversionBlockers": [],
        },
    }


def make_review_trace_adapter(
    root: Path,
    *,
    argv: tuple[str, ...] | None = None,
) -> Path:
    (root / "source.txt").write_text("stable source\n", encoding="utf-8")
    goal_path = root / "GOAL.md"
    goal_path.write_text(goal_text("反例由永久防护覆盖"), encoding="utf-8")
    authority_path = root / "AGENTS.md"
    authority_path.write_text(
        "# Local contract\n\n<a id=\""
        + INV_ID.lower()
        + "\"></a>\nRule.\n",
        encoding="utf-8",
    )
    authority_digest = "sha256:" + hashlib.sha256(
        authority_path.read_bytes()
    ).hexdigest()
    runner_argv = argv or (
        sys.executable,
        "-c",
        "import os,pathlib; pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR']).joinpath('proof.json').write_text('{\"ok\":true}',encoding='utf-8')",
    )
    case = make_case(
        "counterexample-case",
        "functional",
        argv=runner_argv,
    )
    case["fixture"] = None
    case.update(
        {
            "coversCriteria": ["C1"],
            "coversInvariants": [INV_ID],
            "reviewFindingIds": [RF_ID],
            "scenarioTags": ["failure"],
            "quick": True,
        }
    )
    invariant_path = write_json(
        root / "invariants.json",
        {
            "schemaVersion": 1,
            "bindings": [
                {
                    "invariantId": INV_ID,
                    "source": {
                        "kind": "project",
                        "version": "1.0.0",
                        "digest": authority_digest,
                    },
                    "scopes": ["."],
                    "trigger": "The counterexample case is in scope",
                    "authority": {
                        "path": "AGENTS.md",
                        "anchor": INV_ID.lower(),
                    },
                    "applicability": "applicable",
                    "status": "direct",
                    "evidence": ["source.txt"],
                    "enforcement": {"kind": "manual", "evidence": ["source.txt"]},
                }
            ],
        },
    )
    review_path = write_json(
        root / "review-findings.json",
        {
            "schemaId": "steward.semantic-review",
            "schemaVersion": 1,
            "findings": [review_finding(case)],
        },
    )
    goal_digest = goal_contract_sha256(load_goal_contract(goal_path))
    invariant_digest = load_invariant_map(invariant_path).invariant_map_sha256
    review_digest = review_manifest_sha256(
        load_review_manifest(review_path, project_root=root)
    )
    adapter = make_adapter(
        root,
        [case],
        source_files=(
            "source.txt",
            "AGENTS.md",
            "GOAL.md",
            "invariants.json",
            "review-findings.json",
        ),
    )
    value = read_json(adapter)
    value["traceability"] = {
        "goalContract": {
            "path": "GOAL.md",
            "contractVersion": 1,
            "sha256": goal_digest,
        },
        "invariants": {"path": "invariants.json", "sha256": invariant_digest},
        "reviewFindings": {
            "path": "review-findings.json",
            "sha256": review_digest,
        },
        "requiredScenarios": ["failure"],
    }
    return write_json(adapter, value)


def add_second_triggered_invariant(root: Path, adapter: Path) -> None:
    authority = root / "SECOND.md"
    authority.write_text(
        "# Second contract\n\n<a id=\""
        + OTHER_INV_ID.lower()
        + "\"></a>\nRule.\n",
        encoding="utf-8",
    )
    authority_digest = "sha256:" + hashlib.sha256(authority.read_bytes()).hexdigest()
    invariant_value = read_json(root / "invariants.json")
    invariant_value["bindings"].append(
        {
            "invariantId": OTHER_INV_ID,
            "source": {
                "kind": "project",
                "version": "1.0.0",
                "digest": authority_digest,
            },
            "scopes": ["."],
            "trigger": "The second invariant is independently in scope",
            "authority": {
                "path": "SECOND.md",
                "anchor": OTHER_INV_ID.lower(),
            },
            "applicability": "applicable",
            "status": "direct",
            "evidence": ["source.txt"],
            "enforcement": {"kind": "manual", "evidence": ["source.txt"]},
        }
    )
    write_json(root / "invariants.json", invariant_value)
    adapter_value = read_json(adapter)
    adapter_value["traceability"]["invariants"]["sha256"] = load_invariant_map(
        root / "invariants.json"
    ).invariant_map_sha256
    write_json(adapter, adapter_value)
    source_manifest = read_json(root / "source-manifest.json")
    source_manifest["files"].append("SECOND.md")
    write_json(root / "source-manifest.json", source_manifest)


def refresh_review_digest(root: Path, adapter: Path) -> None:
    adapter_value = read_json(adapter)
    adapter_value["traceability"]["reviewFindings"]["sha256"] = (
        review_manifest_sha256(
            load_review_manifest(root / "review-findings.json", project_root=root)
        )
    )
    write_json(adapter, adapter_value)


def bind_review_request(
    root: Path,
    adapter: Path,
    source_fingerprint: str,
    *,
    kind: str = "source",
    base_identity: str = "base-v1",
    head_identity: str = "head-v1",
) -> dict:
    request = review_request(
        source_fingerprint,
        kind=kind,
        base_identity=base_identity,
        head_identity=head_identity,
    )
    review = read_json(root / "review-findings.json")
    review["reviewRequest"] = request
    write_json(root / "review-findings.json", review)
    adapter_value = read_json(adapter)
    adapter_value["traceability"]["reviewFindings"][
        "reviewRequestSha256"
    ] = request["requestSha256"]
    write_json(adapter, adapter_value)
    refresh_review_digest(root, adapter)
    return request


def add_unrelated_review_finding(root: Path, adapter: Path) -> None:
    unrelated_case = make_case(
        "unrelated-review-case",
        "functional",
        argv=(
            sys.executable,
            "-c",
            "import os,pathlib; pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR']).joinpath('proof.json').write_text('{\"ok\":true}',encoding='utf-8')",
        ),
    )
    unrelated_case["fixture"] = None
    unrelated_case.update(
        {
            "required": False,
            "coversCriteria": ["C1"],
            "coversInvariants": [INV_ID],
            "reviewFindingIds": [OTHER_RF_ID],
            "scenarioTags": ["failure"],
            "quick": True,
        }
    )
    adapter_value = read_json(adapter)
    adapter_value["cases"].append(unrelated_case)
    write_json(adapter, adapter_value)

    finding = review_finding(unrelated_case)
    finding["id"] = OTHER_RF_ID
    finding["title"] = "An unrelated case owns a distinct review finding"
    finding["required"] = False
    finding["caseCandidate"]["required"] = False
    finding["caseCandidate"]["reviewFindingIds"] = [OTHER_RF_ID]
    review = read_json(root / "review-findings.json")
    review["findings"].append(finding)
    write_json(root / "review-findings.json", review)
    refresh_review_digest(root, adapter)


def add_blocked_optional_review_finding(
    root: Path,
    adapter: Path,
    *,
    criteria_ids: tuple[str, ...] = ("C1",),
    invariant_ids: tuple[str, ...] = (INV_ID,),
    evidence_path: str = "source.txt",
) -> None:
    case = make_case("blocked-optional-case", "functional")
    case["fixture"] = None
    finding = review_finding(case)
    finding.update(
        {
            "id": OTHER_RF_ID,
            "title": "Optional evidence remains explicitly blocked",
            "required": False,
            "criteriaIds": list(criteria_ids),
            "invariantIds": list(invariant_ids),
        }
    )
    finding["evidence"][0]["location"]["path"] = evidence_path
    candidate = finding["caseCandidate"]
    candidate.update(
        {
            "id": "blocked-optional-case",
            "required": False,
            "coversCriteria": list(criteria_ids),
            "coversInvariants": list(invariant_ids),
            "reviewFindingIds": [OTHER_RF_ID],
            "runner": None,
            "conversionBlockers": [
                "No repository-evidenced executable runner is available"
            ],
        }
    )
    review = read_json(root / "review-findings.json")
    review["findings"].append(finding)
    write_json(root / "review-findings.json", review)
    refresh_review_digest(root, adapter)


def prepare_failed_review_campaign(
    root: Path,
    *,
    unrelated_guardrail_case: bool = False,
    invariant_only_guardrail_case: bool = False,
    second_invariant: bool = False,
    second_review_finding: bool = False,
) -> tuple[Path, dict]:
    command = "import os,pathlib; passing=pathlib.Path('behavior.txt').read_text(encoding='utf-8').strip()=='pass'; evidence=pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR']); evidence.joinpath('proof.json').write_text('{\"guardrail\":true}',encoding='utf-8') if passing else None; raise SystemExit(0 if passing else 1)"
    (root / "behavior.txt").write_text("fail\n", encoding="utf-8")
    adapter = make_review_trace_adapter(root, argv=(sys.executable, "-c", command))
    adapter_value = read_json(adapter)
    if unrelated_guardrail_case or invariant_only_guardrail_case:
        unrelated = make_case("unrelated-guardrail", "integration")
        if invariant_only_guardrail_case:
            unrelated["coversInvariants"] = [INV_ID]
        adapter_value["cases"].append(unrelated)
        write_json(adapter, adapter_value)
    if second_invariant:
        add_second_triggered_invariant(root, adapter)
    if second_review_finding:
        add_unrelated_review_finding(root, adapter)
    manifest = read_json(root / "source-manifest.json")
    manifest["files"].append("behavior.txt")
    write_json(root / "source-manifest.json", manifest)
    run_cli(adapter, "init", expected=0)
    failed = json_output(run_cli(adapter, "run", expected=1))
    failed_attempt = failed["attempts"][-1]
    failed_run = next(
        run
        for attempt in read_json(root / ".campaign" / "state.json")["attempts"]
        for run in attempt["caseRuns"]
        if run["status"] == "FAILED"
    )
    (root / "behavior.txt").write_text("pass\n", encoding="utf-8")
    (root / "guardrail-test.txt").write_text(
        "permanent regression guardrail\n", encoding="utf-8"
    )
    manifest = read_json(root / "source-manifest.json")
    manifest["files"].append("guardrail-test.txt")
    write_json(root / "source-manifest.json", manifest)
    observed = json_output(run_cli(adapter, "status", expected=0))
    fix = {
        "failedCaseId": "counterexample-case",
        "failedRound": "initial",
        "failedAttemptId": failed_attempt["id"],
        "failedSourceFingerprint": failed_run["sourceFingerprint"],
        "fixedSourceFingerprint": observed["currentObservedSourceFingerprint"],
        "rootCause": "The fixture selected the unsafe transition.",
        "violatedInvariant": INV_ID,
        "rootCauseSource": {
            "path": "behavior.txt",
            "lineStart": 1,
            "lineEnd": 1,
        },
        "resolvedFindingIds": [RF_ID],
        "changedFiles": [
            "behavior.txt",
            "guardrail-test.txt",
        ],
        "fixSummary": "Select the guarded transition and retain its regression proof.",
        "externalCondition": False,
        "permanentGuardrail": {
            "kind": "test",
            "sourcePath": "guardrail-test.txt",
            "caseId": "counterexample-case",
            "evidenceFile": "proof.json",
        },
        "minimalRegression": {"evidence": ["proof.json"]},
    }
    return adapter, fix


class TraceabilityTests(unittest.TestCase):
    def _complete(self, adapter: Path) -> None:
        run_cli(adapter, "init", expected=0)
        run_cli(adapter, "run", expected=0)
        run_cli(adapter, "run", "--mode", "regression", expected=0)

    def test_final_regression_satisfies_pinned_criterion_and_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = make_traceable_adapter(
                Path(temporary),
                ("关键行为产生证据",),
                covered=("C1",),
                required_scenarios=("failure",),
                scenario_tags=("failure",),
            )
            initialized = json_output(run_cli(adapter, "init", expected=0))
            self.assertEqual(["C1"], initialized["traceSnapshot"]["goalContract"]["criteriaIds"])
            run_cli(adapter, "run", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            audit = json_output(run_cli(adapter, "audit", expected=0))
            self.assertTrue(audit["ok"])
            self.assertEqual(["trace-case"], audit["traceability"]["criteria"]["C1"])
            self.assertEqual(
                ["trace-case"],
                audit["traceability"]["requiredScenarios"]["failure"],
            )

    def test_audit_rejects_uncovered_criterion_and_required_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = make_traceable_adapter(
                Path(temporary),
                ("第一项证据", "第二项证据"),
                covered=("C1",),
                required_scenarios=("compatibility",),
            )
            self._complete(adapter)
            audit = json_output(run_cli(adapter, "audit", expected=1))
            self.assertIn("CRITERION_UNCOVERED", audit["rejectionCodes"])
            self.assertIn("REQUIRED_SCENARIO_UNCOVERED", audit["rejectionCodes"])

    def test_status_observes_trace_drift_and_audit_rejects_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_traceable_adapter(
                root,
                ("原始验收证据",),
                covered=("C1",),
            )
            self._complete(adapter)
            (root / "GOAL.md").write_text(
                goal_text("已改变的验收证据"), encoding="utf-8"
            )
            status = json_output(run_cli(adapter, "status", expected=0))
            self.assertTrue(status["traceInputDrift"])
            audit = json_output(run_cli(adapter, "audit", expected=1))
            self.assertIn("TRACE_INPUT_DRIFT", audit["rejectionCodes"])

    def test_trace_mapping_without_traceability_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = make_case("invalid-trace", "smoke")
            case["coversCriteria"] = ["C1"]
            adapter = make_adapter(root, [case])
            rejected = run_cli(adapter, "init", expected=2)
            self.assertIn("require top-level traceability", rejected.stderr)

    def test_review_finding_requires_exact_executable_runner_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_review_trace_adapter(root)
            review = read_json(root / "review-findings.json")
            candidate = review["findings"][0]["caseCandidate"]
            candidate["runner"] = None
            candidate["conversionBlockers"] = ["No executable runner is proven"]
            write_json(root / "review-findings.json", review)
            adapter_value = read_json(adapter)
            adapter_value["traceability"]["reviewFindings"]["sha256"] = (
                review_manifest_sha256(
                    load_review_manifest(
                        root / "review-findings.json", project_root=root
                    )
                )
            )
            write_json(adapter, adapter_value)
            rejected = run_cli(adapter, "init", expected=2)
            self.assertIn("lacks an executable runner", rejected.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_review_trace_adapter(root)
            adapter_value = read_json(adapter)
            adapter_value["cases"][0]["argv"] = [
                sys.executable,
                "-c",
                "raise SystemExit(0)",
            ]
            write_json(adapter, adapter_value)
            rejected = run_cli(adapter, "init", expected=2)
            self.assertIn("execution contract differs", rejected.stderr)

    def test_optional_unlinked_review_mappings_are_still_validated(self) -> None:
        variants = (
            (
                {"criteria_ids": ("C2",)},
                "references an unknown goal criterion",
            ),
            (
                {"invariant_ids": (OTHER_INV_ID,)},
                "references an unknown triggered hard invariant",
            ),
        )
        for options, expected_message in variants:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                adapter = make_review_trace_adapter(root)
                add_blocked_optional_review_finding(root, adapter, **options)
                rejected = run_cli(adapter, "init", expected=2)
                self.assertIn(expected_message, rejected.stderr)

    def test_all_unlinked_review_source_locations_must_be_fingerprinted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_review_trace_adapter(root)
            (root / "unbound-optional.txt").write_text(
                "unbound optional evidence\n", encoding="utf-8"
            )
            add_blocked_optional_review_finding(
                root,
                adapter,
                evidence_path="unbound-optional.txt",
            )
            rejected = run_cli(adapter, "init", expected=2)
            self.assertIn(OTHER_RF_ID, rejected.stderr)
            self.assertIn("not source-fingerprint bound", rejected.stderr)

    def test_project_owned_runner_and_fixture_inputs_must_be_fingerprinted(self) -> None:
        variants = ("argv", "fixture")
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "runner.py").write_text(
                    "raise SystemExit(0)\n", encoding="utf-8"
                )
                (root / "fixture.json").write_text("{}\n", encoding="utf-8")
                case = make_case("project-input", "functional")
                if variant == "argv":
                    case["argv"] = [sys.executable, "runner.py"]
                else:
                    case["fixture"] = "fixture.json"
                adapter = make_adapter(root, [case])
                rejected = run_cli(adapter, "init", expected=2)
                self.assertIn("execution input", rejected.stderr)
                self.assertIn("not source-fingerprint bound", rejected.stderr)

    def test_non_interpreter_c_config_input_must_be_fingerprinted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as tools:
            root = Path(temporary)
            config_runner = Path(tools) / "config-runner"
            config_runner.write_text(
                "#!/bin/sh\n[ -f \"$2\" ]\n",
                encoding="utf-8",
            )
            config_runner.chmod(0o755)
            (root / "hidden.cfg").write_text("project input\n", encoding="utf-8")
            adapter = make_review_trace_adapter(root)
            adapter_value = read_json(adapter)
            adapter_value["cases"][0]["argv"] = [
                str(config_runner),
                "-c",
                "hidden.cfg",
            ]
            write_json(adapter, adapter_value)
            review = read_json(root / "review-findings.json")
            runner = review["findings"][0]["caseCandidate"]["runner"]
            runner["argv"] = [str(config_runner), "-c", "hidden.cfg"]
            runner["sourceEvidence"].append(
                {
                    "location": {
                        "path": "hidden.cfg",
                        "lineStart": 1,
                        "lineEnd": 1,
                    },
                    "fact": "The non-interpreter configuration is an execution input",
                }
            )
            write_json(root / "review-findings.json", review)
            refresh_review_digest(root, adapter)

            rejected = run_cli(adapter, "init", expected=2)
            self.assertIn("execution input", rejected.stderr)
            self.assertIn("not source-fingerprint bound", rejected.stderr)
            self.assertIn("hidden.cfg", rejected.stderr)

    def test_review_and_adapter_argv_path_discovery_are_equivalent(self) -> None:
        variants = (
            ("bare", "hidden.cfg", ".", "hidden.cfg"),
            ("response", "@hidden.cfg", ".", "hidden.cfg"),
            ("option", "--config=hidden.cfg", ".", "hidden.cfg"),
            ("cwd", "hidden.cfg", "nested", "nested/hidden.cfg"),
            ("absolute", None, ".", "hidden.cfg"),
        )
        for label, token, cwd, source_path in variants:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                project_input = root / source_path
                project_input.parent.mkdir(parents=True, exist_ok=True)
                project_input.write_text("project input\n", encoding="utf-8")
                adapter = make_review_trace_adapter(root)
                argv_token = str(project_input.resolve()) if token is None else token
                argv = ["external-config-runner", argv_token]
                adapter_value = read_json(adapter)
                adapter_value["cases"][0]["argv"] = argv
                adapter_value["cases"][0]["cwd"] = cwd
                write_json(adapter, adapter_value)
                review = read_json(root / "review-findings.json")
                runner = review["findings"][0]["caseCandidate"]["runner"]
                runner["argv"] = argv
                runner["cwd"] = cwd
                runner["sourceEvidence"].append(
                    {
                        "location": {
                            "path": source_path,
                            "lineStart": 1,
                            "lineEnd": 1,
                        },
                        "fact": "Both Review and adapter consumers bind this input",
                    }
                )
                write_json(root / "review-findings.json", review)
                refresh_review_digest(root, adapter)

                rejected = run_cli(adapter, "init", expected=2)

                self.assertIn("not source-fingerprint bound", rejected.stderr)
                self.assertIn(source_path, rejected.stderr)

    def test_review_runner_project_file_must_be_source_fingerprinted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runner.py").write_text(
                "raise SystemExit(0)\n", encoding="utf-8"
            )
            adapter = make_review_trace_adapter(root)
            adapter_value = read_json(adapter)
            adapter_value["cases"][0]["argv"] = [sys.executable, "runner.py"]
            write_json(adapter, adapter_value)
            review = read_json(root / "review-findings.json")
            runner = review["findings"][0]["caseCandidate"]["runner"]
            runner["argv"] = [sys.executable, "runner.py"]
            runner["sourceEvidence"].append(
                {
                    "location": {
                        "path": "runner.py",
                        "lineStart": 1,
                        "lineEnd": 1,
                    },
                    "fact": "This file is the exact counterexample entry point",
                }
            )
            write_json(root / "review-findings.json", review)
            refresh_review_digest(root, adapter)

            rejected = run_cli(adapter, "init", expected=2)
            self.assertIn("not source-fingerprint bound", rejected.stderr)
            self.assertIn("runner.py", rejected.stderr)

    def test_all_linked_review_source_locations_must_be_fingerprinted(self) -> None:
        location_fields = (
            ("primary evidence", ("evidence", 0, "location")),
            ("triggerPath", ("triggerPath", 0, "location")),
            (
                "runner source evidence",
                ("caseCandidate", "runner", "sourceEvidence", 0, "location"),
            ),
        )

        def set_location(finding: dict, route: tuple[object, ...], path: str) -> None:
            current = finding
            for component in route:
                current = current[component]
            current["path"] = path

        for field, route in location_fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                adapter = make_review_trace_adapter(root)
                (root / "unbound-source.txt").write_text(
                    "unbound review source\n", encoding="utf-8"
                )
                review = read_json(root / "review-findings.json")
                set_location(review["findings"][0], route, "unbound-source.txt")
                write_json(root / "review-findings.json", review)
                refresh_review_digest(root, adapter)
                rejected = run_cli(adapter, "init", expected=2)
                self.assertIn(field, rejected.stderr)
                self.assertIn("not source-fingerprint bound", rejected.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_review_trace_adapter(root)
            bound_paths = {
                "primary evidence": "primary-evidence.txt",
                "triggerPath": "trigger-path.txt",
                "runner source evidence": "runner-source.txt",
            }
            for path in bound_paths.values():
                (root / path).write_text("bound review source\n", encoding="utf-8")
            review = read_json(root / "review-findings.json")
            finding = review["findings"][0]
            for field, route in location_fields:
                set_location(finding, route, bound_paths[field])
            write_json(root / "review-findings.json", review)
            refresh_review_digest(root, adapter)
            source_manifest = read_json(root / "source-manifest.json")
            source_manifest["files"].extend(bound_paths.values())
            write_json(root / "source-manifest.json", source_manifest)
            self._complete(adapter)

            for field, path in bound_paths.items():
                with self.subTest(post_completion_field=field):
                    source_manifest = read_json(root / "source-manifest.json")
                    source_manifest["files"].remove(path)
                    write_json(root / "source-manifest.json", source_manifest)
                    status = json_output(run_cli(adapter, "status", expected=0))
                    self.assertTrue(status["traceInputDrift"])
                    self.assertTrue(
                        any(field in error for error in status["traceInputErrors"]),
                        status,
                    )
                    audit = json_output(run_cli(adapter, "audit", expected=1))
                    self.assertIn("TRACE_INPUT_DRIFT", audit["rejectionCodes"])
                    source_manifest["files"].append(path)
                    write_json(root / "source-manifest.json", source_manifest)
                    restored = json_output(run_cli(adapter, "status", expected=0))
                    self.assertFalse(restored["traceInputDrift"], restored)

    def test_manifest_control_is_not_a_review_source_location(self) -> None:
        location_fields = (
            ("primary evidence", ("evidence", 0, "location")),
            ("triggerPath", ("triggerPath", 0, "location")),
            (
                "runner source evidence",
                ("caseCandidate", "runner", "sourceEvidence", 0, "location"),
            ),
        )

        for field, route in location_fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                adapter = make_review_trace_adapter(root)
                review = read_json(root / "review-findings.json")
                location = review["findings"][0]
                for component in route:
                    location = location[component]
                location["path"] = "source-manifest.json"
                write_json(root / "review-findings.json", review)
                refresh_review_digest(root, adapter)

                rejected = run_cli(adapter, "init", expected=2)
                self.assertIn(field, rejected.stderr)
                self.assertIn("not source-fingerprint bound", rejected.stderr)

    def test_initialize_rebinds_trace_locations_to_its_exact_source_observation(
        self,
    ) -> None:
        scripts = SKILL_ROOT / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from adapter_paths import validate_adapter
        from journal_state import Campaign
        from model import CampaignError

        for mutation in ("unlist", "delete"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                adapter_path = make_review_trace_adapter(root)
                adapter = validate_adapter(adapter_path)
                if mutation == "unlist":
                    manifest = read_json(root / "source-manifest.json")
                    manifest["files"].remove("source.txt")
                    write_json(root / "source-manifest.json", manifest)
                else:
                    (root / "source.txt").unlink()

                with self.assertRaisesRegex(
                    CampaignError, "primary evidence is not source-fingerprint bound"
                ):
                    Campaign.initialize(adapter)

    def test_status_and_audit_rebind_trace_locations_to_their_observation(
        self,
    ) -> None:
        scripts = SKILL_ROOT / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from adapter_paths import validate_adapter
        from audit import audit_report, status_report
        from journal_state import Campaign

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter_path = make_review_trace_adapter(root)
            self._complete(adapter_path)
            adapter = validate_adapter(adapter_path, observe_trace_drift=True)
            manifest = read_json(root / "source-manifest.json")
            manifest["files"].remove("source.txt")
            write_json(root / "source-manifest.json", manifest)
            campaign = Campaign.load(adapter)

            status = status_report(campaign)
            self.assertTrue(status["traceInputDrift"], status)
            self.assertTrue(
                any(
                    "primary evidence is not source-fingerprint bound" in error
                    for error in status["traceInputErrors"]
                ),
                status,
            )
            audit = audit_report(campaign)
            self.assertIn("TRACE_INPUT_DRIFT", audit["rejectionCodes"])

    def test_invariant_reference_drift_is_rejected_at_init_status_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_traceable_adapter(root, ("可审计",), covered=("C1",))
            (root / "AGENTS.md").write_text("# Broken authority\n", encoding="utf-8")
            rejected = run_cli(adapter, "init", expected=2)
            self.assertIn("invariant project reference is invalid", rejected.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_traceable_adapter(root, ("可审计",), covered=("C1",))
            self._complete(adapter)
            (root / "AGENTS.md").write_text("# Broken authority\n", encoding="utf-8")
            status = json_output(run_cli(adapter, "status", expected=0))
            self.assertTrue(status["traceInputDrift"])
            self.assertTrue(
                any("invariant project reference" in item for item in status["traceInputErrors"])
            )
            audit = json_output(run_cli(adapter, "audit", expected=1))
            self.assertIn("TRACE_INPUT_DRIFT", audit["rejectionCodes"])

    def test_enhanced_fix_rejects_false_invariant_and_root_cause_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_failed_review_campaign(
                root, second_invariant=True
            )
            fix["violatedInvariant"] = OTHER_INV_ID
            fix_path = write_json(root / "invalid-fix.json", fix)
            rejected = run_cli(
                adapter, "record-fix", "--fix", str(fix_path), expected=2
            )
            self.assertIn("not covered by the failed case", rejected.stderr)
            fix["violatedInvariant"] = {
                "notApplicable": True,
                "technicalReason": "Attempt to bypass an available invariant.",
            }
            write_json(fix_path, fix)
            rejected = run_cli(
                adapter, "record-fix", "--fix", str(fix_path), expected=2
            )
            self.assertIn("invariant-free failed case", rejected.stderr)

        for source_value, expected_message in (
            (
                {"path": "outside.txt", "lineStart": 1, "lineEnd": 1},
                "must be in the source inventory",
            ),
            (
                {"path": "behavior.txt", "lineStart": 1, "lineEnd": 2},
                "line range is out of bounds",
            ),
        ):
            with self.subTest(source=source_value):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    adapter, fix = prepare_failed_review_campaign(root)
                    (root / "outside.txt").write_text(
                        "outside inventory\n", encoding="utf-8"
                    )
                    fix["rootCauseSource"] = source_value
                    fix_path = write_json(root / "invalid-fix.json", fix)
                    rejected = run_cli(
                        adapter,
                        "record-fix",
                        "--fix",
                        str(fix_path),
                        expected=2,
                    )
                    self.assertIn(expected_message, rejected.stderr)

        for field in ("rootCauseSource", "permanentGuardrail"):
            with self.subTest(manifest_control_field=field):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    adapter, fix = prepare_failed_review_campaign(root)
                    if field == "rootCauseSource":
                        fix[field]["path"] = "source-manifest.json"
                    else:
                        fix[field]["sourcePath"] = "source-manifest.json"
                    fix_path = write_json(root / "invalid-fix.json", fix)
                    rejected = run_cli(
                        adapter,
                        "record-fix",
                        "--fix",
                        str(fix_path),
                        expected=2,
                    )
                    self.assertIn("source inventory", rejected.stderr)

    def test_fix_can_resolve_only_findings_linked_to_the_failed_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_failed_review_campaign(
                root, second_review_finding=True
            )
            fix["resolvedFindingIds"] = [OTHER_RF_ID]
            fix_path = write_json(root / "invalid-fix.json", fix)
            rejected = run_cli(
                adapter, "record-fix", "--fix", str(fix_path), expected=2
            )
            self.assertIn("linked to the failed case", rejected.stderr)

            scripts = SKILL_ROOT / "scripts"
            sys.path.insert(0, str(scripts))
            try:
                from adapter_paths import source_snapshot, validate_adapter
                from journal_state import append_event
            finally:
                sys.path.remove(str(scripts))
            fixed_snapshot = source_snapshot(validate_adapter(adapter))
            append_event(
                root / ".campaign",
                "fix_recorded",
                {
                    "fixId": "fix-000000000001",
                    "failedCaseId": fix["failedCaseId"],
                    "failedRound": fix["failedRound"],
                    "failedAttemptId": fix["failedAttemptId"],
                    "failedSourceFingerprint": fix["failedSourceFingerprint"],
                    "fixedSourceFingerprint": fix["fixedSourceFingerprint"],
                    "rootCause": fix["rootCause"],
                    "changedFiles": fix["changedFiles"],
                    "fixSummary": fix["fixSummary"],
                    "externalCondition": fix["externalCondition"],
                    "minimalRegressionEvidence": fix["minimalRegression"][
                        "evidence"
                    ],
                    "violatedInvariant": fix["violatedInvariant"],
                    "rootCauseSource": fix["rootCauseSource"],
                    "resolvedFindingIds": [OTHER_RF_ID],
                    "permanentGuardrail": fix["permanentGuardrail"],
                    "fixedSourceSnapshot": fixed_snapshot,
                    "changedFilesVerified": True,
                },
            )
            replay_rejected = run_cli(adapter, "status", expected=2)
            self.assertIn("not linked to the failed case", replay_rejected.stderr)

    def test_fix_and_audit_reject_source_inventory_change_mid_observation(self) -> None:
        scripts = SKILL_ROOT / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from adapter_paths import validate_adapter
        from audit import audit_report
        from engine import record_fix_locked
        from journal_state import Campaign, CampaignLock
        from model import CampaignError

        def remove_guardrail_from_manifest(root: Path) -> None:
            manifest = read_json(root / "source-manifest.json")
            manifest["files"].remove("guardrail-test.txt")
            write_json(root / "source-manifest.json", manifest)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_failed_review_campaign(root)
            validated = validate_adapter(adapter)
            with CampaignLock(validated.campaign_root):
                campaign = Campaign.load(validated)
                observe = campaign.current_source_observation
                calls = 0

                def changing_observation() -> dict:
                    nonlocal calls
                    observation = observe()
                    if calls == 0:
                        remove_guardrail_from_manifest(root)
                    calls += 1
                    return observation

                with mock.patch.object(
                    campaign,
                    "current_source_observation",
                    side_effect=changing_observation,
                ):
                    with self.assertRaisesRegex(
                        CampaignError, "source changed while the fix audit"
                    ):
                        record_fix_locked(campaign, fix)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_failed_review_campaign(root)
            fix_path = write_json(root / "fix.json", fix)
            run_cli(adapter, "record-fix", "--fix", str(fix_path), expected=0)
            run_cli(adapter, "retest", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            validated = validate_adapter(adapter)
            campaign = Campaign.load(validated)
            observe = campaign.current_source_observation
            calls = 0

            def changing_audit_observation() -> dict:
                nonlocal calls
                observation = observe()
                if calls == 0:
                    remove_guardrail_from_manifest(root)
                calls += 1
                return observation

            with mock.patch.object(
                campaign,
                "current_source_observation",
                side_effect=changing_audit_observation,
            ):
                report = audit_report(campaign)
            self.assertFalse(report["ok"], report)
            self.assertIn(
                "source changed while the audit was in progress",
                report["errors"],
            )

    def test_enhanced_fix_rejects_unbound_guardrail_fields(self) -> None:
        variants = (
            ("source", {"sourcePath": "unbound-guardrail.txt"}, "sourcePath"),
            ("case", {"caseId": "missing-case"}, "caseId"),
            ("evidence", {"evidenceFile": "missing.json"}, "evidenceFile"),
        )
        for label, changes, expected_message in variants:
            with self.subTest(field=label):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    adapter, fix = prepare_failed_review_campaign(root)
                    (root / "unbound-guardrail.txt").write_text(
                        "not inventoried\n", encoding="utf-8"
                    )
                    fix["permanentGuardrail"].update(changes)
                    fix_path = write_json(root / "invalid-fix.json", fix)
                    rejected = run_cli(
                        adapter,
                        "record-fix",
                        "--fix",
                        str(fix_path),
                        expected=2,
                    )
                    self.assertIn(expected_message, rejected.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_failed_review_campaign(
                root, unrelated_guardrail_case=True
            )
            fix["permanentGuardrail"]["caseId"] = "unrelated-guardrail"
            fix_path = write_json(root / "invalid-fix.json", fix)
            rejected = run_cli(
                adapter, "record-fix", "--fix", str(fix_path), expected=2
            )
            self.assertIn("must cover the violated invariant", rejected.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_failed_review_campaign(
                root, invariant_only_guardrail_case=True
            )
            fix["permanentGuardrail"]["caseId"] = "unrelated-guardrail"
            fix_path = write_json(root / "invalid-fix.json", fix)
            rejected = run_cli(
                adapter, "record-fix", "--fix", str(fix_path), expected=2
            )
            self.assertIn("every resolved review finding", rejected.stderr)

    def test_not_applicable_guardrail_requires_reason_and_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_failed_review_campaign(root)
            fix_path = write_json(root / "trace-fix.json", fix)
            for disposition in (
                {"notApplicable": True},
                {"notApplicable": True, "technicalReason": ""},
            ):
                fix["permanentGuardrail"] = disposition
                write_json(fix_path, fix)
                rejected = run_cli(
                    adapter, "record-fix", "--fix", str(fix_path), expected=2
                )
                self.assertIn("technicalReason", rejected.stderr)
            fix["permanentGuardrail"] = {
                "notApplicable": True,
                "technicalReason": (
                    "The invariant is enforced by an immutable generated boundary."
                ),
            }
            write_json(fix_path, fix)
            run_cli(adapter, "record-fix", "--fix", str(fix_path), expected=0)
            run_cli(adapter, "retest", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            audit = json_output(run_cli(adapter, "audit", expected=0))
            self.assertTrue(audit["traceability"]["guardrails"][0]["notApplicable"])

    def test_invariant_free_failure_uses_truthful_technical_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "behavior.txt").write_text("fail\n", encoding="utf-8")
            adapter = make_traceable_adapter(root, ("行为恢复",), covered=("C1",))
            adapter_value = read_json(adapter)
            adapter_value["cases"][0]["argv"] = [
                sys.executable,
                "-c",
                "import os,pathlib; passing=pathlib.Path('behavior.txt').read_text(encoding='utf-8').strip()=='pass'; evidence=pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR']); evidence.joinpath('proof.json').write_text('{\"ok\":true}',encoding='utf-8') if passing else None; raise SystemExit(0 if passing else 1)",
            ]
            write_json(adapter, adapter_value)
            manifest = read_json(root / "source-manifest.json")
            manifest["files"].append("behavior.txt")
            write_json(root / "source-manifest.json", manifest)
            run_cli(adapter, "init", expected=0)
            failed = json_output(run_cli(adapter, "run", expected=1))
            state = read_json(root / ".campaign" / "state.json")
            failed_run = state["attempts"][-1]["caseRuns"][-1]
            (root / "behavior.txt").write_text("pass\n", encoding="utf-8")
            observed = json_output(run_cli(adapter, "status", expected=0))
            fix = write_json(
                root / "fallback-fix.json",
                {
                    "failedCaseId": "trace-case",
                    "failedRound": "initial",
                    "failedAttemptId": failed["attempts"][-1]["id"],
                    "failedSourceFingerprint": failed_run["sourceFingerprint"],
                    "fixedSourceFingerprint": observed[
                        "currentObservedSourceFingerprint"
                    ],
                    "rootCause": "The local fixture selected the failing path.",
                    "violatedInvariant": {
                        "notApplicable": True,
                        "technicalReason": "This criterion-only case has no triggered invariant mapping.",
                    },
                    "rootCauseSource": {
                        "path": "behavior.txt",
                        "lineStart": 1,
                        "lineEnd": 1,
                    },
                    "resolvedFindingIds": [],
                    "changedFiles": ["behavior.txt"],
                    "fixSummary": "Restore the passing local fixture.",
                    "externalCondition": False,
                    "permanentGuardrail": {
                        "notApplicable": True,
                        "technicalReason": "No durable project guard can own this isolated fixture state.",
                    },
                    "minimalRegression": {"evidence": ["proof.json"]},
                },
            )
            run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)
            run_cli(adapter, "retest", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            self.assertTrue(json_output(run_cli(adapter, "audit", expected=0))["ok"])

    def test_public_adapter_and_fix_templates_materialize_through_retest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = "import os,pathlib; passing=pathlib.Path('behavior.txt').read_text(encoding='utf-8').strip()=='pass'; evidence=pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR']); evidence.joinpath('proof.json').write_text('{\"template\":true}',encoding='utf-8') if passing else None; raise SystemExit(0 if passing else 1)"
            (root / "behavior.txt").write_text("fail\n", encoding="utf-8")
            generated_adapter = make_review_trace_adapter(
                root, argv=(sys.executable, "-c", command)
            )
            generated = read_json(generated_adapter)
            manifest = read_json(root / "source-manifest.json")
            manifest["files"].append("behavior.txt")
            write_json(root / "source-manifest.json", manifest)

            adapter_template = read_json(
                SKILL_ROOT / "assets" / "project-adapter.template.json"
            )
            self.assertIsNone(adapter_template["cases"][0]["fixture"])
            self.assertEqual(
                set(adapter_template["cases"][0]), set(generated["cases"][0])
            )
            adapter_template.update(
                {
                    "projectId": "public-template-regression",
                    "projectRoot": ".",
                    "campaignRoot": ".template-campaign",
                    "source": {
                        "provider": "manifest",
                        "manifest": "source-manifest.json",
                        "excludes": [".template-campaign"],
                    },
                    "traceability": copy.deepcopy(generated["traceability"]),
                    "cases": copy.deepcopy(generated["cases"]),
                }
            )
            adapter = write_json(root / "template-adapter.json", adapter_template)
            run_cli(adapter, "init", expected=0)
            failed = json_output(run_cli(adapter, "run", expected=1))
            state = read_json(root / ".template-campaign" / "state.json")
            failed_run = state["attempts"][-1]["caseRuns"][-1]
            (root / "behavior.txt").write_text("pass\n", encoding="utf-8")
            observed = json_output(run_cli(adapter, "status", expected=0))

            fix_template = read_json(
                SKILL_ROOT / "assets" / "fix-audit.template.json"
            )
            self.assertEqual(
                {"path", "lineStart", "lineEnd", "symbol"},
                set(fix_template["rootCauseSource"]),
            )
            fix_template.update(
                {
                    "failedCaseId": "counterexample-case",
                    "failedRound": "initial",
                    "failedAttemptId": failed["attempts"][-1]["id"],
                    "failedSourceFingerprint": failed_run["sourceFingerprint"],
                    "fixedSourceFingerprint": observed[
                        "currentObservedSourceFingerprint"
                    ],
                    "rootCause": "The template fixture selected the failing branch.",
                    "violatedInvariant": INV_ID,
                    "rootCauseSource": {
                        "path": "behavior.txt",
                        "lineStart": 1,
                        "lineEnd": 1,
                        "symbol": "template_fixture",
                    },
                    "resolvedFindingIds": [RF_ID],
                    "changedFiles": ["behavior.txt"],
                    "fixSummary": "Switch the template fixture to the passing branch.",
                    "externalCondition": False,
                    "permanentGuardrail": {
                        "kind": "test",
                        "sourcePath": "behavior.txt",
                        "caseId": "counterexample-case",
                        "evidenceFile": "proof.json",
                    },
                    "minimalRegression": {"evidence": ["proof.json"]},
                }
            )
            fix_path = write_json(root / "template-fix.json", fix_template)
            run_cli(adapter, "record-fix", "--fix", str(fix_path), expected=0)
            run_cli(adapter, "retest", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            self.assertTrue(json_output(run_cli(adapter, "audit", expected=0))["ok"])

    def test_required_invariant_and_review_finding_use_final_linked_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = make_review_trace_adapter(Path(temporary))
            self._complete(adapter)
            audit = json_output(run_cli(adapter, "audit", expected=0))
            self.assertEqual(
                ["counterexample-case"],
                audit["traceability"]["invariants"][INV_ID],
            )
            finding = audit["traceability"]["reviewFindings"][RF_ID]
            self.assertEqual(["counterexample-case"], finding["resolvedCases"])

    def test_invalidated_regression_failure_is_not_an_actionable_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "regression-state.txt").write_text("first\n", encoding="utf-8")
            command = (
                "import os,pathlib; "
                "evidence=pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR']); "
                "state=pathlib.Path('regression-state.txt'); "
                "invalidate='-regression' in evidence.as_posix() and "
                "state.read_text(encoding='utf-8').strip()=='first'; "
                "state.write_text('second\\n',encoding='utf-8') if invalidate else None; "
                "evidence.joinpath('proof.json').write_text('{\"ok\":true}',encoding='utf-8') "
                "if not invalidate else None; "
                "raise SystemExit(1 if invalidate else 0)"
            )
            adapter = make_review_trace_adapter(
                root, argv=(sys.executable, "-c", command)
            )
            manifest = read_json(root / "source-manifest.json")
            manifest["files"].append("regression-state.txt")
            write_json(root / "source-manifest.json", manifest)

            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=0)
            completed = json_output(
                run_cli(adapter, "run", "--mode", "regression", expected=1)
            )
            self.assertEqual("BLOCKED", completed["status"])
            self.assertEqual("BLOCKED", completed["completionStatus"])
            invalidated = [
                attempt
                for attempt in completed["attempts"]
                if attempt["status"] == "INVALIDATED"
            ]
            self.assertEqual(1, len(invalidated))
            state = read_json(root / ".campaign" / "state.json")
            invalidated_state = next(
                attempt
                for attempt in state["attempts"]
                if attempt["id"] == invalidated[0]["id"]
            )
            self.assertEqual("FAILED", invalidated_state["caseRuns"][0]["status"])

            resume = run_cli(adapter, "resume", expected=2)
            self.assertIn("choose a new campaign root", resume.stderr)
            audit = json_output(run_cli(adapter, "audit", expected=1))
            self.assertFalse(audit["ok"], audit)
            self.assertIn("FINAL_REGRESSION_REQUIRED", audit["rejectionCodes"])

    def test_bound_fix_installs_and_proves_permanent_guardrail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = "import os,pathlib; passing=pathlib.Path('behavior.txt').read_text(encoding='utf-8').strip()=='pass'; evidence=pathlib.Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR']); evidence.joinpath('proof.json').write_text('{\"guardrail\":true}',encoding='utf-8') if passing else None; raise SystemExit(0 if passing else 1)"
            (root / "behavior.txt").write_text("fail\n", encoding="utf-8")
            adapter = make_review_trace_adapter(
                root, argv=(sys.executable, "-c", command)
            )
            manifest = read_json(root / "source-manifest.json")
            manifest["files"].append("behavior.txt")
            write_json(root / "source-manifest.json", manifest)
            run_cli(adapter, "init", expected=0)
            failed = json_output(run_cli(adapter, "run", expected=1))
            failed_attempt = failed["attempts"][-1]
            failed_run = next(
                run
                for attempt in read_json(root / ".campaign" / "state.json")["attempts"]
                for run in attempt["caseRuns"]
                if run["status"] == "FAILED"
            )

            (root / "behavior.txt").write_text("pass\n", encoding="utf-8")
            (root / "guardrail-test.txt").write_text(
                "permanent regression guardrail\n", encoding="utf-8"
            )
            manifest = read_json(root / "source-manifest.json")
            manifest["files"].append("guardrail-test.txt")
            write_json(root / "source-manifest.json", manifest)
            observed = json_output(run_cli(adapter, "status", expected=0))
            fix = write_json(
                root / "trace-fix.json",
                {
                    "failedCaseId": "counterexample-case",
                    "failedRound": "initial",
                    "failedAttemptId": failed_attempt["id"],
                    "failedSourceFingerprint": failed_run["sourceFingerprint"],
                    "fixedSourceFingerprint": observed[
                        "currentObservedSourceFingerprint"
                    ],
                    "rootCause": "The fixture selected the unsafe transition.",
                    "violatedInvariant": INV_ID,
                    "rootCauseSource": {
                        "path": "behavior.txt",
                        "lineStart": 1,
                        "lineEnd": 1,
                    },
                    "resolvedFindingIds": [RF_ID],
                    "changedFiles": [
                        "behavior.txt",
                        "guardrail-test.txt",
                    ],
                    "fixSummary": "Select the guarded transition and retain its regression proof.",
                    "externalCondition": False,
                    "permanentGuardrail": {
                        "kind": "test",
                        "sourcePath": "guardrail-test.txt",
                        "caseId": "counterexample-case",
                        "evidenceFile": "proof.json",
                    },
                    "minimalRegression": {"evidence": ["proof.json"]},
                },
            )
            run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)
            recorded = read_json(root / ".campaign" / "state.json")["fixes"][-1]
            self.assertEqual(
                {"path": "behavior.txt", "lineStart": 1, "lineEnd": 1},
                recorded["rootCauseSource"],
            )
            run_cli(adapter, "retest", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)
            audit = json_output(run_cli(adapter, "audit", expected=0))
            self.assertTrue(audit["ok"])
            self.assertTrue(audit["traceability"]["guardrails"][0]["ok"])
            (root / "guardrail-test.txt").unlink()
            drifted = json_output(run_cli(adapter, "audit", expected=1))
            self.assertIn("GUARDRAIL_SOURCE_UNBOUND", drifted["rejectionCodes"])

    def test_fix_rejects_changed_file_outside_source_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = root / "runner.py"
            runner.write_text("raise SystemExit(7)\n", encoding="utf-8")
            case = make_case(
                "failing-runner",
                "functional",
                argv=(sys.executable, "runner.py"),
            )
            adapter = make_adapter(root, [case], source_files=("runner.py",))
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            runner.write_text("raise SystemExit(0)\n", encoding="utf-8")
            (root / "unbound-fix.py").write_text("fixed = True\n", encoding="utf-8")
            fix = write_fix_for_latest_failure(
                adapter,
                changed_files=("unbound-fix.py",),
                external_condition=False,
            )
            rejected = run_cli(
                adapter,
                "record-fix",
                "--fix",
                str(fix),
                expected=2,
            )
            self.assertIn("must be in the source inventory", rejected.stderr)

    def test_non_external_fix_must_change_source_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = root / "runner.py"
            runner.write_text("raise SystemExit(7)\n", encoding="utf-8")
            case = make_case(
                "unchanged-runner",
                "functional",
                argv=(sys.executable, "runner.py"),
            )
            adapter = make_adapter(root, [case], source_files=("runner.py",))
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            fix = write_fix_for_latest_failure(
                adapter,
                changed_files=("runner.py",),
                external_condition=False,
            )
            rejected = run_cli(
                adapter,
                "record-fix",
                "--fix",
                str(fix),
                expected=2,
            )
            self.assertIn("must change the source fingerprint", rejected.stderr)

    def test_fix_can_truthfully_record_deleted_inventory_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = make_case(
                "deletion-failure",
                "functional",
                argv=(sys.executable, "-c", "raise SystemExit(7)"),
            )
            adapter = make_adapter(
                root,
                [case],
                source_files=("deleted-source.txt",),
            )
            run_cli(adapter, "init", expected=0)
            run_cli(adapter, "run", expected=1)
            (root / "deleted-source.txt").unlink()
            fix = write_fix_for_latest_failure(
                adapter,
                changed_files=("deleted-source.txt",),
                external_condition=False,
            )
            recorded = json_output(
                run_cli(
                    adapter,
                    "record-fix",
                    "--fix",
                    str(fix),
                    expected=0,
                )
            )
            self.assertEqual(
                ["deleted-source.txt"],
                recorded["pendingFix"]["changedFiles"],
            )

    def test_tampered_guardrail_evidence_is_not_reported_as_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, fix = prepare_failed_review_campaign(root)
            fix_path = write_json(root / "trace-fix.json", fix)
            run_cli(adapter, "record-fix", "--fix", str(fix_path), expected=0)
            run_cli(adapter, "retest", expected=0)
            run_cli(adapter, "run", "--mode", "regression", expected=0)

            state = read_json(root / ".campaign" / "state.json")
            final_attempt = next(
                attempt
                for attempt in state["attempts"]
                if attempt["id"] == state["finalRegressionAttemptId"]
            )
            final_run = next(
                run
                for run in final_attempt["caseRuns"]
                if run["caseId"] == "counterexample-case"
            )
            artifact = root / ".campaign" / final_run["artifactDir"]
            (artifact / "proof.json").write_text(
                '{"guardrail":null}', encoding="utf-8"
            )

            audit = json_output(run_cli(adapter, "audit", expected=1))
            self.assertIn("GUARDRAIL_EVIDENCE_MISSING", audit["rejectionCodes"])
            self.assertFalse(audit["traceability"]["guardrails"][0]["ok"])
            self.assertTrue(
                any("evidence artifact tampered" in error for error in audit["errors"]),
                audit,
            )


if __name__ == "__main__":
    unittest.main()
