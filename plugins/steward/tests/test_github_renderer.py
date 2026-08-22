from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - optional parser-level validation
    yaml = None


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SCRIPT = PLUGIN_ROOT / "scripts" / "verification_pipeline.py"
PUBLIC_CLI = PLUGIN_ROOT / "scripts" / "project_verification.py"
SPEC = importlib.util.spec_from_file_location(
    "steward_verification_pipeline_renderer_tests",
    PIPELINE_SCRIPT,
)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import setup guard
    raise RuntimeError("cannot load verification_pipeline.py")
verification_pipeline = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verification_pipeline
SPEC.loader.exec_module(verification_pipeline)


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def make_case(
    case_id: str,
    *,
    platform: str = "any",
    depends_on: tuple[str, ...] = (),
    quick: bool = False,
) -> dict[str, object]:
    return {
        "id": case_id,
        "category": "functional",
        "required": True,
        "quick": quick,
        "platform": platform,
        "dependsOn": list(depends_on),
        "argv": ["python3", "-c", "print('verified')"],
        "cwd": ".",
        "timeoutSeconds": 30,
        "fixture": None,
        "externalCapabilities": [],
        "evidence": {"requiredFiles": [], "nonEmptyFiles": []},
    }


class RendererFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.workflow_root = root / ".steward"
        self.workflow_root.mkdir(parents=True)
        (root / "source.txt").write_text("stable source\n", encoding="utf-8")
        self.adapter_path = self.workflow_root / "verification-adapter.json"
        self.profile_path = self.workflow_root / "verification-profile.json"

        self.cases = [
            make_case("selector-self-test", quick=True),
            make_case(
                "selector-helper",
                depends_on=("selector-self-test",),
                quick=True,
            ),
            make_case("linux-database", platform="linux"),
            make_case(
                "linux-api",
                platform="linux",
                depends_on=("linux-database",),
            ),
            make_case("portable-lint"),
            make_case("windows-paths", platform="windows"),
            make_case("darwin-keychain", platform="darwin"),
        ]
        self.adapter = {
            "schemaVersion": 1,
            "projectId": "renderer-fixture",
            "projectRoot": "..",
            "campaignRoot": ".steward/runtime/base-campaign",
            "source": {
                "provider": "files",
                "files": ["source.txt"],
                "excludes": [".steward/runtime/**"],
            },
            "localOnly": {
                "enabled": True,
                "allowedExternalCapabilities": [],
            },
            "cases": self.cases,
        }
        write_json(self.adapter_path, self.adapter)

        self.profile = {
            "schemaId": "steward.verification-profile",
            "schemaVersion": 1,
            "projectId": "renderer-fixture",
            "projectRoot": "..",
            "adapter": {"path": ".steward/verification-adapter.json"},
            "runtime": {
                "pluginRoot": None,
                "pythonExecutables": {"posix": "python3", "windows": "python"},
            },
            "changeDetection": {
                "provider": "git",
                "baseRef": None,
                "sources": [
                    "committed",
                    "staged",
                    "unstaged",
                    "untracked",
                ],
                "highImpactPaths": ["pyproject.toml", ".github/**"],
                "unknownPath": "full",
            },
            "packages": [],
            "guards": [
                {
                    "id": "selector-guard",
                    "paths": [".steward/**"],
                    "caseIds": ["selector-self-test"],
                    "alwaysRun": True,
                }
            ],
            "tiers": {
                "quick": {"selection": "impact-plan"},
                "full": {"selection": "all", "ignoreSelector": True},
            },
            "ci": {
                "platforms": [
                    {"id": "linux", "required": True, "shards": 2},
                    {"id": "windows", "required": True, "shards": 1},
                    {"id": "darwin", "required": True, "shards": 1},
                ],
                "portablePlatform": "linux",
                "posixPlatform": "linux",
                "selectorPlatform": "linux",
                "selectorCaseIds": ["selector-self-test"],
            },
            "outputs": {
                "profile": ".steward/verification-profile.json",
                "impactPlan": ".steward/runtime/impact-plan.json",
                "ciPlan": ".steward/ci-plan.json",
                "localEntry": ".steward/verify.py",
                "workflow": ".github/workflows/project-verification.yml",
                "derivedAdapters": ".steward/runtime/adapters",
                "campaigns": ".steward/runtime/campaigns",
                "evidenceBundles": ".steward/runtime/evidence",
                "aggregation": ".steward/runtime/aggregation.json",
            },
        }
        write_json(self.profile_path, self.profile)

    def load(self):
        return verification_pipeline.load_profile(self.profile_path, self.root)

    def rewrite_profile(self, value: dict[str, object]) -> None:
        write_json(self.profile_path, value)


class GithubRendererTests(unittest.TestCase):
    def fixture(self, temporary: str) -> RendererFixture:
        return RendererFixture(Path(temporary))

    def test_ci_plan_is_exact_deterministic_partition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(temporary)
            profile = fixture.load()

            first = verification_pipeline.build_ci_plan(profile)
            second = verification_pipeline.build_ci_plan(profile)

            self.assertEqual(first, second)
            self.assertEqual(
                [
                    {
                        "id": "selector-contract",
                        "kind": "selector",
                        "platform": "linux",
                        "shardIndex": 1,
                        "shardCount": 1,
                        "caseIds": ["selector-self-test", "selector-helper"],
                    },
                    {
                        "id": "darwin-01-of-01",
                        "kind": "platform",
                        "platform": "darwin",
                        "shardIndex": 1,
                        "shardCount": 1,
                        "caseIds": ["darwin-keychain"],
                    },
                    {
                        "id": "linux-01-of-02",
                        "kind": "platform",
                        "platform": "linux",
                        "shardIndex": 1,
                        "shardCount": 2,
                        "caseIds": ["linux-database", "linux-api"],
                    },
                    {
                        "id": "linux-02-of-02",
                        "kind": "platform",
                        "platform": "linux",
                        "shardIndex": 2,
                        "shardCount": 2,
                        "caseIds": ["portable-lint"],
                    },
                    {
                        "id": "windows-01-of-01",
                        "kind": "platform",
                        "platform": "windows",
                        "shardIndex": 1,
                        "shardCount": 1,
                        "caseIds": ["windows-paths"],
                    },
                ],
                first["entries"],
            )
            assigned = [
                case_id
                for entry in first["entries"]
                for case_id in entry["caseIds"]
            ]
            expected = [case["id"] for case in fixture.cases]
            self.assertEqual(set(expected), set(assigned))
            self.assertEqual(len(expected), len(assigned))
            self.assertEqual(len(assigned), len(set(assigned)))
            self.assertEqual(
                ["darwin", "linux", "windows"], first["requiredPlatforms"]
            )

    def test_selector_and_dependency_components_are_never_split(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(temporary)
            plan = verification_pipeline.build_ci_plan(fixture.load())
            entry_by_case = {
                case_id: entry["id"]
                for entry in plan["entries"]
                for case_id in entry["caseIds"]
            }

            self.assertEqual(
                "selector-contract", entry_by_case["selector-self-test"]
            )
            self.assertEqual(
                entry_by_case["selector-self-test"],
                entry_by_case["selector-helper"],
            )
            self.assertEqual(
                entry_by_case["linux-database"], entry_by_case["linux-api"]
            )

    def test_renderer_is_deterministic_and_matches_golden_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(temporary)
            profile = fixture.load()
            plan = verification_pipeline.build_ci_plan(profile)

            first = verification_pipeline.render_github_actions_bytes(profile, plan)
            second = verification_pipeline.render_github_actions_bytes(profile, plan)

            self.assertEqual(first, second)
            expected = """# Generated by Steward; edit the verification profile instead.
name: Project verification
"on":
  pull_request:
  push:
  workflow_dispatch:
permissions:
  contents: read
env:
  STEWARD_PLUGIN_ROOT: ${{ vars.STEWARD_PLUGIN_ROOT }}
jobs:
  full:
    name: full / ${{ matrix.id }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - id: \"selector-contract\"
            kind: \"selector\"
            platform: \"linux\"
            runner: \"ubuntu-24.04\"
            python: \"python3\"
            shard-index: 1
            shard-count: 1
          - id: \"darwin-01-of-01\"
            kind: \"platform\"
            platform: \"darwin\"
            runner: \"macos-15\"
            python: \"python3\"
            shard-index: 1
            shard-count: 1
          - id: \"linux-01-of-02\"
            kind: \"platform\"
            platform: \"linux\"
            runner: \"ubuntu-24.04\"
            python: \"python3\"
            shard-index: 1
            shard-count: 2
          - id: \"linux-02-of-02\"
            kind: \"platform\"
            platform: \"linux\"
            runner: \"ubuntu-24.04\"
            python: \"python3\"
            shard-index: 2
            shard-count: 2
          - id: \"windows-01-of-01\"
            kind: \"platform\"
            platform: \"windows\"
            runner: \"windows-2025\"
            python: \"python\"
            shard-index: 1
            shard-count: 1
    runs-on: ${{ matrix.runner }}
    steps:
      - name: Check out exact commit
        uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - name: Run full verification shard
        run: >-
          ${{ matrix.python }} \".steward/verify.py\" ci --entry ${{ matrix.id }}
      - name: Upload audited platform evidence
        uses: actions/upload-artifact@v7
        with:
          name: verification-${{ matrix.id }}
          path: \".steward/runtime/evidence/${{ matrix.id }}.json\"
          if-no-files-found: error
          retention-days: 7
  aggregate:
    name: aggregate platform evidence
    if: always()
    needs: full
    runs-on: \"ubuntu-24.04\"
    steps:
      - name: Check out exact commit
        uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - name: Download platform evidence
        uses: actions/download-artifact@v8
        with:
          pattern: verification-*
          path: \".steward/runtime/evidence\"
          merge-multiple: true
      - name: Aggregate and audit evidence
        run: >-
          python3 \".steward/verify.py\" aggregate --bundle-dir \".steward/runtime/evidence\"
      - name: Upload aggregation
        uses: actions/upload-artifact@v7
        with:
          name: verification-aggregation
          path: \".steward/runtime/aggregation.json\"
          if-no-files-found: error
          retention-days: 7
"""
            self.assertEqual(expected.encode("utf-8"), first)
            if yaml is not None:
                parsed = yaml.safe_load(first.decode("utf-8"))
                self.assertIn("on", parsed)
                self.assertNotIn(True, parsed)

    def test_full_workflow_has_no_impact_selector_or_branch_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(temporary)
            profile_data = copy.deepcopy(fixture.profile)
            profile_data["changeDetection"]["baseRef"] = "main"
            fixture.rewrite_profile(profile_data)
            profile = fixture.load()
            workflow = verification_pipeline.render_github_actions_bytes(
                profile, verification_pipeline.build_ci_plan(profile)
            ).decode("utf-8")

            self.assertIn('id: "selector-contract"', workflow)
            self.assertNotIn("impact", workflow.lower())
            self.assertNotIn("paths:", workflow)
            self.assertNotIn("paths-ignore:", workflow)
            self.assertNotIn("branches:", workflow)
            self.assertNotIn("default-branch", workflow)
            self.assertNotIn("main", workflow)
            self.assertNotIn("needs: selector", workflow)

    def test_runner_mapping_is_fixed_and_profile_cannot_override_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(temporary)
            profile = fixture.load()
            rendered = verification_pipeline.render_github_actions_bytes(
                profile, verification_pipeline.build_ci_plan(profile)
            ).decode("utf-8")
            self.assertIn('runner: "ubuntu-24.04"', rendered)
            self.assertIn('runner: "macos-15"', rendered)
            self.assertIn('runner: "windows-2025"', rendered)

            invalid = copy.deepcopy(fixture.profile)
            invalid["ci"]["platforms"][0]["runner"] = "self-hosted"
            fixture.rewrite_profile(invalid)
            with self.assertRaisesRegex(
                verification_pipeline.VerificationPipelineError,
                "unknown fields: runner",
            ):
                fixture.load()

    def test_profile_rejects_expression_injection_and_absolute_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(temporary)
            injected = copy.deepcopy(fixture.profile)
            injected["projectId"] = "${{ github.token }}"
            fixture.rewrite_profile(injected)
            with self.assertRaisesRegex(
                verification_pipeline.VerificationPipelineError,
                "stable identifier",
            ):
                fixture.load()

            absolute = copy.deepcopy(fixture.profile)
            absolute["outputs"]["workflow"] = "/tmp/injected.yml"
            fixture.rewrite_profile(absolute)
            with self.assertRaisesRegex(
                verification_pipeline.VerificationPipelineError,
                "project-relative path",
            ):
                fixture.load()

    def test_render_check_is_idempotent_and_detects_drift_without_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(temporary)
            profile = fixture.load()
            plan = verification_pipeline.build_ci_plan(profile)
            workflow = fixture.root / profile.view["outputs"]["workflow"]
            outputs = profile.view["outputs"]

            expected = verification_pipeline.render_github_actions_bytes(profile, plan)
            with self.assertRaisesRegex(
                verification_pipeline.VerificationPipelineError,
                "direct renderer writes are disabled",
            ):
                verification_pipeline.render_github_actions(profile, plan)
            self.assertFalse(workflow.exists())

            verification_pipeline.configure_project(
                profile.path,
                profile.project_root,
                [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]],
            )
            initial = workflow.read_bytes()
            self.assertEqual(expected, initial)
            with self.assertRaisesRegex(
                verification_pipeline.VerificationPipelineError,
                "direct renderer writes are disabled",
            ):
                verification_pipeline.render_github_actions(profile, plan)
            self.assertEqual(initial, workflow.read_bytes())
            self.assertEqual(
                expected,
                verification_pipeline.render_github_actions(
                    profile, plan, check=True
                ),
            )

            drifted = initial + b"# hand edited\n"
            workflow.write_bytes(drifted)
            with self.assertRaisesRegex(
                verification_pipeline.VerificationPipelineError,
                "workflow is stale",
            ):
                verification_pipeline.render_github_actions(
                    profile, plan, check=True
                )
            self.assertEqual(drifted, workflow.read_bytes())

    def test_public_cli_configure_and_check_detect_drift_without_direct_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(temporary)
            common = [
                "--profile",
                str(fixture.profile_path),
                "--project-root",
                str(fixture.root),
            ]

            configured = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(PUBLIC_CLI),
                    "configure",
                    *common,
                    "--allow-write",
                    ".steward/ci-plan.json",
                    "--allow-write",
                    ".steward/verify.py",
                    "--allow-write",
                    ".github/workflows/project-verification.yml",
                ],
                cwd=str(fixture.root),
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
            self.assertEqual(0, configured.returncode, configured.stderr)
            self.assertEqual("configure", json.loads(configured.stdout)["mode"])

            workflow = fixture.root / ".github/workflows/project-verification.yml"
            configured_workflow = workflow.read_bytes()

            direct = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(PUBLIC_CLI),
                    "render-github",
                    *common,
                ],
                cwd=str(fixture.root),
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
            self.assertEqual(2, direct.returncode)
            self.assertIn("direct renderer writes are disabled", direct.stderr)
            self.assertEqual(configured_workflow, workflow.read_bytes())

            checked = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(PUBLIC_CLI),
                    "render-github",
                    *common,
                    "--check",
                ],
                cwd=str(fixture.root),
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            self.assertTrue(json.loads(checked.stdout)["check"])

            unsupported = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(PUBLIC_CLI),
                    "render-github",
                    *common,
                    "--default-branch",
                    "main",
                ],
                cwd=str(fixture.root),
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
            self.assertEqual(2, unsupported.returncode)
            self.assertIn("unrecognized arguments", unsupported.stderr)

            drifted = workflow.read_bytes() + b"# drift\n"
            workflow.write_bytes(drifted)
            rejected = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(PUBLIC_CLI),
                    "render-github",
                    *common,
                    "--check",
                ],
                cwd=str(fixture.root),
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("GitHub Actions workflow", rejected.stderr)
            self.assertEqual(drifted, workflow.read_bytes())


if __name__ == "__main__":
    unittest.main()
