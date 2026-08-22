from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import verification_pipeline as pipeline


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def case(
    case_id: str,
    *,
    quick: bool,
    category: str = "functional",
    platform: str = "any",
    depends_on: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "id": case_id,
        "category": category,
        "required": True,
        "quick": quick,
        "platform": platform,
        "dependsOn": list(depends_on),
        "argv": [sys.executable, "-c", "pass"],
        "cwd": ".",
        "timeoutSeconds": 30,
        "fixture": None,
        "externalCapabilities": [],
        "evidence": {"requiredFiles": [], "nonEmptyFiles": []},
    }


class GitProject:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.workflow = root / ".steward"
        self.profile_path = self.workflow / "verification-profile.json"
        self.adapter_path = self.workflow / "base-adapter.json"
        self.git("init", "-q")
        self.git("config", "user.email", "verification@example.invalid")
        self.git("config", "user.name", "Verification Fixture")

        for relative in (
            "packages/core/committed.py",
            "packages/core/staged.py",
            "packages/core/unstaged.py",
            "packages/app/app.py",
            "root.lock",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("baseline\n", encoding="utf-8")

        self.adapter_data = {
            "schemaVersion": 1,
            "projectId": "verification-fixture",
            "projectRoot": "..",
            "campaignRoot": ".steward/verification/campaigns/base",
            "source": {
                "provider": "git",
                "excludes": [".steward/verification/**"],
            },
            "localOnly": {
                "enabled": True,
                "allowedExternalCapabilities": [],
            },
            "cases": [
                case("selector-contract", quick=True),
                case("core-test", quick=True),
                case("core-typecheck", quick=True),
                case("app-test", quick=True, depends_on=("core-test",)),
                case("app-typecheck", quick=True),
                case("core-guard", quick=True),
                case("linux-integration", quick=False, platform="linux"),
                case("windows-integration", quick=False, platform="windows"),
                case("posix-integration", quick=False, platform="posix"),
            ],
        }
        write_json(self.adapter_path, self.adapter_data)

        self.profile_data = {
            "schemaId": "steward.verification-profile",
            "schemaVersion": 1,
            "projectId": "verification-fixture",
            "projectRoot": "..",
            "adapter": {"path": ".steward/base-adapter.json"},
            "runtime": {
                "pluginRoot": None,
                "pythonExecutables": {"posix": "python3", "windows": "py"},
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
                "highImpactPaths": ["root.lock"],
                "unknownPath": "full",
            },
            "packages": [
                {
                    "id": "core",
                    "paths": ["packages/core/**"],
                    "dependsOn": [],
                    "quickCaseIds": ["core-test"],
                    "typecheckCaseIds": ["core-typecheck"],
                },
                {
                    "id": "app",
                    "paths": ["packages/app/**"],
                    "dependsOn": ["core"],
                    "quickCaseIds": ["app-test"],
                    "typecheckCaseIds": ["app-typecheck"],
                },
            ],
            "guards": [
                {
                    "id": "selector-guard",
                    "paths": [],
                    "caseIds": ["selector-contract"],
                    "alwaysRun": True,
                },
                {
                    "id": "core-path-guard",
                    "paths": ["packages/core/**"],
                    "caseIds": ["core-guard"],
                    "alwaysRun": False,
                },
            ],
            "tiers": {
                "quick": {"selection": "impact-plan"},
                "full": {"selection": "all", "ignoreSelector": True},
            },
            "ci": {
                "platforms": [
                    {"id": "linux", "required": True, "shards": 2},
                    {"id": "windows", "required": True, "shards": 1},
                ],
                "portablePlatform": "linux",
                "posixPlatform": "linux",
                "selectorPlatform": "linux",
                "selectorCaseIds": ["selector-contract"],
            },
            "outputs": {
                "profile": ".steward/verification-profile.json",
                "impactPlan": ".steward/verification/impact-plan.json",
                "ciPlan": ".steward/verification/ci-plan.json",
                "localEntry": ".steward/verify-project.py",
                "workflow": ".github/workflows/project-verification.yml",
                "derivedAdapters": ".steward/verification/derived-adapters",
                "campaigns": ".steward/verification/campaigns",
                "evidenceBundles": ".steward/verification/evidence",
                "aggregation": ".steward/verification/aggregation.json",
            },
        }
        self.write_profile()
        self.git("add", "--all")
        self.git("commit", "-qm", "baseline")
        self.baseline = self.text_git("rev-parse", "HEAD")

    def git(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode:
            raise AssertionError(
                f"git {' '.join(arguments)} failed:\n"
                + completed.stderr.decode("utf-8", "replace")
            )
        return completed

    def text_git(self, *arguments: str) -> str:
        return self.git(*arguments).stdout.decode("ascii").strip()

    def write_profile(self, value: dict[str, object] | None = None) -> Path:
        return write_json(self.profile_path, value or self.profile_data)

    def load_profile(self) -> pipeline.VerificationProfile:
        return pipeline.load_profile(self.profile_path, self.root)

    def change(self, relative: str, text: str = "changed\n") -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def file_snapshot(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(self.root).parts
        }

    def tree_snapshot(self) -> dict[str, tuple[str, bytes]]:
        result: dict[str, tuple[str, bytes]] = {}
        for path in self.root.rglob("*"):
            relative = path.relative_to(self.root)
            if ".git" in relative.parts:
                continue
            name = relative.as_posix()
            if path.is_symlink():
                result[name] = ("link", os.readlink(path).encode("utf-8"))
            elif path.is_dir():
                result[name] = ("directory", b"")
            elif path.is_file():
                result[name] = ("file", path.read_bytes())
        return result


class VerificationProfileContractTests(unittest.TestCase):
    def test_profile_rejects_portable_name_aliases_between_static_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            value = copy.deepcopy(project.profile_data)
            value["outputs"]["localEntry"] = (
                ".steward/Verification-Entry.py"
            )
            value["outputs"]["workflow"] = (
                ".STEWARD/verification-entry.PY"
            )
            project.write_profile(value)
            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "case-folding or Unicode-normalizing filesystem",
            ):
                project.load_profile()

    def test_portable_route_identity_normalizes_unicode_without_a_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = set(root.iterdir())
            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "case-folding or Unicode-normalizing filesystem",
            ):
                pipeline._assert_distinct_configuration_routes(
                    root,
                    {
                        "composed input": "generated/\u00e9.json",
                        "decomposed target": "generated/e\u0301.json",
                    },
                )
            self.assertEqual(before, set(root.iterdir()))

    def test_profile_rejects_portable_prefix_overlap_across_all_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            value = copy.deepcopy(project.profile_data)
            value["outputs"]["derivedAdapters"] = "Generated/BAR"
            value["outputs"]["workflow"] = "generated/bar/workflow.yml"
            project.write_profile(value)
            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "output files and dynamic output directories cannot overlap",
            ):
                project.load_profile()

            value = copy.deepcopy(project.profile_data)
            value["outputs"]["workflow"] = (
                ".STEWARD/VERIFICATION-PROFILE.JSON/child.yml"
            )
            project.write_profile(value)
            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "output files cannot be nested beneath one another",
            ):
                project.load_profile()

    def test_profile_rejects_static_target_aliases_to_explicit_and_runtime_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            fixture = project.root / "fixtures" / "input.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("{}\n", encoding="utf-8")
            adapter = copy.deepcopy(project.adapter_data)
            adapter["cases"][0]["fixture"] = "fixtures/input.json"
            write_json(project.adapter_path, adapter)

            explicit_alias = copy.deepcopy(project.profile_data)
            explicit_alias["outputs"]["workflow"] = "FIXTURES/input.JSON"
            project.write_profile(explicit_alias)
            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "aliases adapter input cases\\[0\\]\\.fixture",
            ):
                project.load_profile()

            runtime_root = project.root / "runtime-plugin"
            for relative in (
                "scripts/project_verification.py",
                "skills/run-closed-loop-verification/scripts/campaign.py",
            ):
                entry_path = runtime_root / relative
                entry_path.parent.mkdir(parents=True, exist_ok=True)
                entry_path.write_text("# runtime\n", encoding="utf-8")
            runtime_alias = copy.deepcopy(project.profile_data)
            runtime_alias["runtime"]["pluginRoot"] = "runtime-plugin"
            runtime_alias["outputs"]["localEntry"] = (
                "RUNTIME-PLUGIN/SCRIPTS/PROJECT_VERIFICATION.PY"
            )
            project.write_profile(runtime_alias)
            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "aliases runtime entry 0",
            ):
                project.load_profile()

    def test_profile_rejects_existing_hardlink_from_target_to_explicit_input(
        self,
    ) -> None:
        if not hasattr(os, "link"):
            self.skipTest("hard links are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            fixture = project.root / "fixtures" / "input.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("{}\n", encoding="utf-8")
            adapter = copy.deepcopy(project.adapter_data)
            adapter["cases"][0]["fixture"] = "fixtures/input.json"
            write_json(project.adapter_path, adapter)
            workflow = project.root / project.profile_data["outputs"]["workflow"]
            workflow.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(fixture, workflow)
            except OSError as exc:
                self.skipTest("cannot create a hard link: " + str(exc))
            before = project.tree_snapshot()

            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "physically aliases adapter input cases\\[0\\]\\.fixture",
            ):
                project.load_profile()
            self.assertEqual(before, project.tree_snapshot())

    def test_profile_rejects_an_existing_hardlink_alias_to_its_authority(self) -> None:
        if not hasattr(os, "link"):
            self.skipTest("hard links are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            ci_output = project.root / project.profile_data["outputs"]["ciPlan"]
            ci_output.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(project.profile_path, ci_output)
            except OSError as exc:
                self.skipTest("cannot create a hard link: " + str(exc))
            before = project.tree_snapshot()

            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "physically aliases verification profile",
            ):
                project.load_profile()

            self.assertEqual(before, project.tree_snapshot())

    @unittest.skipUnless(sys.platform == "darwin", "macOS filesystem check")
    def test_macos_case_insensitive_profile_alias_is_rejected_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            alternate = project.profile_path.with_name(
                project.profile_path.name.upper()
            )
            try:
                same = alternate.exists() and os.path.samefile(
                    alternate,
                    project.profile_path,
                )
            except OSError:
                same = False
            if not same:
                self.skipTest("temporary filesystem is case-sensitive")
            value = copy.deepcopy(project.profile_data)
            value["outputs"]["ciPlan"] = alternate.relative_to(
                project.root
            ).as_posix()
            project.write_profile(value)
            before = project.tree_snapshot()

            with self.assertRaises(pipeline.VerificationPipelineError):
                project.load_profile()

            self.assertEqual(before, project.tree_snapshot())

    def test_exact_profile_validates_runtime_and_all_nine_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            profile = project.load_profile()

            self.assertEqual(1, profile.view["schemaVersion"])
            self.assertEqual(
                {"pluginRoot": None, "pythonExecutables": {"posix": "python3", "windows": "py"}},
                profile.view["runtime"],
            )
            self.assertEqual(
                {
                    "profile",
                    "impactPlan",
                    "ciPlan",
                    "localEntry",
                    "workflow",
                    "derivedAdapters",
                    "campaigns",
                    "evidenceBundles",
                    "aggregation",
                },
                set(profile.view["outputs"]),
            )
            self.assertEqual(profile.sha256, pipeline.profile_sha256(profile))
            self.assertEqual(
                profile.adapter_catalog_fingerprint,
                pipeline.profile_catalog_fingerprint(profile),
            )

    def test_profile_rejects_unknown_fields_bad_runtime_missing_output_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            mutations = []

            unknown = copy.deepcopy(project.profile_data)
            unknown["unexpected"] = True
            mutations.append(("unknown fields", unknown))

            bad_runtime = copy.deepcopy(project.profile_data)
            bad_runtime["runtime"]["pythonExecutables"]["posix"] = "../python3"
            mutations.append(("runtime executable", bad_runtime))

            shell_injection = copy.deepcopy(project.profile_data)
            shell_injection["runtime"]["pythonExecutables"]["posix"] = (
                "python3;echo-injected"
            )
            mutations.append(("runtime shell injection", shell_injection))

            expression_injection = copy.deepcopy(project.profile_data)
            expression_injection["runtime"]["pythonExecutables"]["windows"] = (
                "${{ github.token }}"
            )
            mutations.append(("runtime expression injection", expression_injection))

            missing_output = copy.deepcopy(project.profile_data)
            del missing_output["outputs"]["aggregation"]
            mutations.append(("nine outputs", missing_output))

            wrong_digest = copy.deepcopy(project.profile_data)
            wrong_digest["contentDigest"] = "sha256:" + "0" * 64
            mutations.append(("content digest", wrong_digest))

            for label, value in mutations:
                with self.subTest(label=label):
                    project.write_profile(value)
                    with self.assertRaises(pipeline.VerificationPipelineError):
                        project.load_profile()

    def test_profile_rejects_boolean_versions_and_unhashable_ci_or_case_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            mutations = []

            boolean_version = copy.deepcopy(project.profile_data)
            boolean_version["schemaVersion"] = True
            mutations.append(("boolean schema version", boolean_version))

            platform_id = copy.deepcopy(project.profile_data)
            platform_id["ci"]["platforms"][0]["id"] = []
            mutations.append(("unhashable platform id", platform_id))

            portable_platform = copy.deepcopy(project.profile_data)
            portable_platform["ci"]["portablePlatform"] = []
            mutations.append(("unhashable portable platform", portable_platform))

            selector_cases = copy.deepcopy(project.profile_data)
            selector_cases["ci"]["selectorCaseIds"] = [[]]
            mutations.append(("unhashable selector case", selector_cases))

            guard_cases = copy.deepcopy(project.profile_data)
            guard_cases["guards"][0]["caseIds"] = [[]]
            mutations.append(("unhashable guard case", guard_cases))

            for label, value in mutations:
                with self.subTest(label=label):
                    project.write_profile(value)
                    with self.assertRaises(pipeline.VerificationPipelineError):
                        project.load_profile()

    def test_profile_rejects_noncanonical_duplicate_paths_and_bad_adapter_case_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            mutations: list[tuple[str, dict[str, object]]] = []

            bad_root = copy.deepcopy(project.profile_data)
            bad_root["projectRoot"] = "./.."
            mutations.append(("noncanonical projectRoot", bad_root))

            repeated_separator = copy.deepcopy(project.profile_data)
            repeated_separator["outputs"]["workflow"] = (
                ".github//workflows/project-verification.yml"
            )
            mutations.append(("repeated separator", repeated_separator))

            dot_segment = copy.deepcopy(project.profile_data)
            dot_segment["changeDetection"]["highImpactPaths"] = [
                "packages/./core/**"
            ]
            mutations.append(("dot segment", dot_segment))

            backslash = copy.deepcopy(project.profile_data)
            backslash["adapter"]["path"] = ".steward\\base-adapter.json"
            mutations.append(("backslash", backslash))

            duplicate_package_path = copy.deepcopy(project.profile_data)
            duplicate_package_path["packages"][0]["paths"] = [
                "packages/core/**",
                "packages/core/**",
            ]
            mutations.append(("duplicate package path", duplicate_package_path))

            duplicate_guard_path = copy.deepcopy(project.profile_data)
            duplicate_guard_path["guards"][1]["paths"] = [
                "packages/core/**",
                "packages/core/**",
            ]
            mutations.append(("duplicate guard path", duplicate_guard_path))

            github_expression = copy.deepcopy(project.profile_data)
            github_expression["outputs"]["localEntry"] = (
                ".steward/${{github.token}}.py"
            )
            mutations.append(("GitHub expression output", github_expression))

            command_substitution = copy.deepcopy(project.profile_data)
            command_substitution["outputs"]["evidenceBundles"] = (
                ".steward/verification/$(touch-pwned)"
            )
            mutations.append(("command substitution output", command_substitution))

            for label, value in mutations:
                with self.subTest(label=label):
                    project.write_profile(value)
                    with self.assertRaises(pipeline.VerificationPipelineError):
                        project.load_profile()

            project.write_profile()
            invalid_adapter = copy.deepcopy(project.adapter_data)
            invalid_adapter["cases"].append(case(".invalid", quick=False))
            write_json(project.adapter_path, invalid_adapter)
            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "profile adapter case IDs",
            ):
                project.load_profile()

    def test_shared_loader_rejects_symlinked_profile_parent_and_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            real_root = container / "real"
            real_root.mkdir()
            project = GitProject(real_root)
            alias_root = container / "alias"
            try:
                alias_root.symlink_to(real_root, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest("directory symlinks are unavailable: " + str(exc))

            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "profile path uses a symlink/reparse component",
            ):
                pipeline.load_profile(
                    alias_root / ".steward/verification-profile.json",
                    real_root,
                )

            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "projectRoot uses a symlink/reparse component",
            ):
                pipeline.load_profile(project.profile_path, alias_root)

    def test_local_entry_substitutes_original_template_tokens_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            runtime = project.root / "runtime-__PROFILE__"
            for relative in (
                "scripts/project_verification.py",
                "skills/run-closed-loop-verification/scripts/campaign.py",
            ):
                entry = runtime / relative
                entry.parent.mkdir(parents=True, exist_ok=True)
                entry.write_text("# fixture runtime\n", encoding="utf-8")

            value = copy.deepcopy(project.profile_data)
            value["projectRoot"] = ".."
            value["runtime"]["pluginRoot"] = "runtime-__PROFILE__"
            value["outputs"].update(
                {
                    "profile": "__IMPACT__/profile.json",
                    "impactPlan": (
                        ".steward/verification/__CI__/impact.json"
                    ),
                    "ciPlan": (
                        ".steward/verification/__ADAPTERS__/ci.json"
                    ),
                    "derivedAdapters": (
                        ".steward/verification/"
                        "__CAMPAIGNS__-adapters"
                    ),
                    "campaigns": (
                        ".steward/verification/__BUNDLES__-campaigns"
                    ),
                    "evidenceBundles": (
                        ".steward/verification/"
                        "__AGGREGATION__-bundles"
                    ),
                    "aggregation": (
                        ".steward/verification/"
                        "__PLUGIN__-aggregation.json"
                    ),
                }
            )
            profile_path = write_json(
                project.root / value["outputs"]["profile"], value
            )
            profile = pipeline.load_profile(profile_path, project.root)

            rendered = pipeline.render_local_entry_bytes(profile).decode("utf-8")
            compile(rendered, "<generated-local-entry>", "exec")

            self.assertIn(
                'PROFILE = PROJECT_ROOT / "__IMPACT__/profile.json"', rendered
            )
            self.assertIn(
                'IMPACT_PLAN = PROJECT_ROOT / '
                '".steward/verification/__CI__/impact.json"',
                rendered,
            )
            self.assertIn(
                'CI_PLAN = PROJECT_ROOT / '
                '".steward/verification/__ADAPTERS__/ci.json"',
                rendered,
            )
            self.assertIn(
                'ADAPTERS = PROJECT_ROOT / '
                '".steward/verification/__CAMPAIGNS__-adapters"',
                rendered,
            )
            self.assertIn(
                'CAMPAIGNS = PROJECT_ROOT / '
                '".steward/verification/__BUNDLES__-campaigns"',
                rendered,
            )
            self.assertIn(
                'BUNDLES = PROJECT_ROOT / '
                '".steward/verification/__AGGREGATION__-bundles"',
                rendered,
            )
            self.assertIn(
                'AGGREGATION = PROJECT_ROOT / '
                '".steward/verification/__PLUGIN__-aggregation.json"',
                rendered,
            )
            self.assertIn(
                'CONFIGURED_PLUGIN_ROOT = "runtime-__PROFILE__"', rendered
            )


class ImpactPlanningTests(unittest.TestCase):
    def test_four_change_sources_and_merge_base_are_preserved_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            project.change("packages/core/committed.py", "committed\n")
            project.git("add", "packages/core/committed.py")
            project.git("commit", "-qm", "committed change")
            project.change("packages/core/staged.py", "staged\n")
            project.git("add", "packages/core/staged.py")
            project.change("packages/core/unstaged.py", "unstaged\n")
            project.change("packages/app/untracked.py", "untracked\n")

            plan = pipeline.plan_impact(
                project.load_profile(), project.root, project.baseline
            )

            self.assertEqual(project.baseline, plan["repository"]["mergeBaseCommit"])
            self.assertEqual(
                {
                    "committed": ["packages/core/committed.py"],
                    "staged": ["packages/core/staged.py"],
                    "unstaged": ["packages/core/unstaged.py"],
                    "untracked": ["packages/app/untracked.py"],
                },
                {
                    source: [entry["path"] for entry in plan["changes"][source]]
                    for source in pipeline.CHANGE_SOURCES
                },
            )
            self.assertRegex(
                plan["repository"]["changeSnapshotFingerprint"],
                r"^sha256:[0-9a-f]{64}$",
            )

    def test_downstream_packages_typechecks_and_guards_join_quick_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            project.change("packages/core/unstaged.py")

            plan = pipeline.plan_impact(
                project.load_profile(), project.root, project.baseline
            )

            self.assertEqual("quick", plan["impact"]["mode"])
            self.assertEqual(["core"], plan["impact"]["directPackageIds"])
            self.assertEqual(["app", "core"], plan["impact"]["affectedPackageIds"])
            self.assertEqual(
                ["core-path-guard", "selector-guard"],
                plan["impact"]["guardIds"],
            )
            self.assertEqual(
                {"core-typecheck", "app-typecheck"},
                set(plan["impact"]["typecheckCaseIds"]),
            )
            self.assertEqual(
                {
                    "selector-contract",
                    "core-test",
                    "core-typecheck",
                    "app-test",
                    "app-typecheck",
                    "core-guard",
                },
                set(plan["impact"]["selectedCaseIds"]),
            )

    def test_high_impact_unowned_and_unstable_observations_fail_closed_full(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            high = GitProject(Path(temporary))
            high.change("root.lock", "new lock\n")
            plan = pipeline.plan_impact(high.load_profile(), high.root, high.baseline)
            self.assertEqual("full", plan["impact"]["mode"])
            self.assertIn("HIGH_IMPACT_PATH", plan["impact"]["reasonCodes"])
            self.assertEqual(plan["impact"]["fullCaseIds"], plan["impact"]["selectedCaseIds"])

        with tempfile.TemporaryDirectory() as temporary:
            unknown = GitProject(Path(temporary))
            unknown.change("mystery.txt")
            plan = pipeline.plan_impact(
                unknown.load_profile(), unknown.root, unknown.baseline
            )
            self.assertEqual("full", plan["impact"]["mode"])
            self.assertIn("UNOWNED_PATH", plan["impact"]["reasonCodes"])

        with tempfile.TemporaryDirectory() as temporary:
            unstable = GitProject(Path(temporary))
            profile = unstable.load_profile()
            first = pipeline._git_observation(profile, unstable.baseline)
            second = copy.deepcopy(first)
            second["changeSnapshotFingerprint"] = "sha256:" + "1" * 64
            with mock.patch.object(
                pipeline,
                "_git_observation",
                side_effect=[first, second],
            ):
                plan = pipeline.plan_impact(profile, unstable.root, unstable.baseline)
            self.assertEqual("full", plan["impact"]["mode"])
            self.assertIn("CHANGE_SNAPSHOT_UNSTABLE", plan["impact"]["reasonCodes"])

    def test_impact_plan_reobservation_rejects_repository_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            project.change("packages/core/unstaged.py", "first\n")
            profile = project.load_profile()
            plan = pipeline.plan_impact(profile, project.root, project.baseline)
            pipeline.validate_impact_plan(plan, profile, project.root)

            project.change("packages/core/unstaged.py", "second\n")
            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "stale relative to the current repository",
            ):
                pipeline.validate_impact_plan(plan, profile, project.root)

    def test_git_paths_reject_backslashes_and_control_characters(self) -> None:
        for raw in (b"packages/core/bad\\name.py", b"packages/core/bad\tname.py"):
            with self.subTest(raw=raw):
                with self.assertRaises(pipeline.VerificationPipelineError):
                    pipeline._decode_git_path(raw)

        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            profile = project.load_profile()
            with mock.patch.object(
                pipeline,
                "_git_observation",
                side_effect=lambda *_: pipeline._decode_git_path(b"bad\\path"),
            ):
                plan = pipeline.plan_impact(profile, project.root, project.baseline)
            self.assertEqual("full", plan["impact"]["mode"])
            self.assertIn(
                "CHANGE_SNAPSHOT_UNTRUSTED", plan["impact"]["reasonCodes"]
            )

    def test_offline_impact_validation_is_structural_and_exception_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            project.change("packages/core/unstaged.py")
            profile = project.load_profile()
            plan = pipeline.plan_impact(profile, project.root, project.baseline)
            pipeline.validate_impact_plan(plan, profile, reobserve=False)

            mutations = []

            def add(label: str, mutate) -> None:
                candidate = copy.deepcopy(plan)
                mutate(candidate)
                candidate["contentDigest"] = pipeline._impact_digest(candidate)
                mutations.append((label, candidate))

            add("boolean schema version", lambda item: item.__setitem__("schemaVersion", True))
            add("non-object repository", lambda item: item.__setitem__("repository", []))
            add(
                "bad portable binding",
                lambda item: item["bindings"].__setitem__(
                    "portableSourceFingerprint", "not-a-hash"
                ),
            )
            add(
                "unsafe change path",
                lambda item: item["changes"].__setitem__(
                    "unstaged", [{"status": "M", "path": "packages\\bad.py"}]
                ),
            )
            add(
                "wrong source status",
                lambda item: item["changes"].__setitem__(
                    "untracked", [{"status": "M", "path": "new.py"}]
                ),
            )
            add(
                "unknown reason",
                lambda item: item["impact"].__setitem__(
                    "reasonCodes", ["NOT_A_REASON"]
                ),
            )
            add(
                "unknown package",
                lambda item: item["impact"].__setitem__(
                    "directPackageIds", ["missing"]
                ),
            )
            add(
                "unhashable mode",
                lambda item: item["impact"].__setitem__("mode", []),
            )

            for label, candidate in mutations:
                with self.subTest(label=label):
                    with self.assertRaises(pipeline.VerificationPipelineError):
                        pipeline.validate_impact_plan(
                            candidate, profile, reobserve=False
                        )

            bad_digest = copy.deepcopy(plan)
            bad_digest["contentDigest"] = "not-a-hash"
            with self.assertRaises(pipeline.VerificationPipelineError):
                pipeline.validate_impact_plan(bad_digest, profile, reobserve=False)


class CiAndDerivedAdapterTests(unittest.TestCase):
    def test_full_base_catalog_derives_honest_narrow_ci_shards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            base = copy.deepcopy(project.adapter_data)
            categories = (
                "smoke",
                "functional",
                "integration",
                "workflow",
                "role-play",
            )
            base["coverageMode"] = "full"
            for index, item in enumerate(base["cases"]):
                item["category"] = categories[index % len(categories)]
            write_json(project.adapter_path, base)
            profile = project.load_profile()
            self.assertEqual("full", profile.adapter_data["coverageMode"])

            plan = pipeline.build_ci_plan(profile)
            plan_path = write_json(
                project.root / profile.view["outputs"]["ciPlan"],
                plan,
            )
            assigned: list[str] = []
            derived_adapters: list[dict[str, object]] = []
            validator = pipeline._kernel_validator()
            for entry in plan["entries"]:
                output = (
                    project.root
                    / profile.view["outputs"]["derivedAdapters"]
                    / (entry["id"] + ".json")
                )
                campaign = (
                    project.root
                    / profile.view["outputs"]["campaigns"]
                    / entry["id"]
                )
                derived = pipeline.render_derived_adapter(
                    profile,
                    tier="full",
                    output=output,
                    campaign_root=campaign,
                    ci_plan=(plan_path, plan),
                    entry_id=entry["id"],
                )
                derived_adapters.append(derived)
                assigned.extend(entry["caseIds"])
                self.assertEqual("narrow", derived["coverageMode"])
                self.assertEqual("full", derived["verification"]["tier"])
                self.assertEqual(
                    profile.adapter_catalog_fingerprint,
                    derived["verification"]["verificationCatalogFingerprint"],
                )
                self.assertEqual(
                    entry["id"],
                    derived["verification"]["ciPlan"]["entryId"],
                )
                pipeline.validate_adapter_verification(
                    derived["verification"],
                    derived,
                    project.root,
                    campaign,
                    output,
                )
                validated = validator(output)
                self.assertEqual("narrow", validated.coverage_mode)

            self.assertEqual(set(plan["fullCaseIds"]), set(assigned))
            self.assertEqual(len(assigned), len(set(assigned)))
            self.assertTrue(
                any(
                    len({item["category"] for item in derived["cases"]})
                    < len(categories)
                    for derived in derived_adapters
                )
            )

            tampered = copy.deepcopy(derived_adapters[0])
            tampered["coverageMode"] = "full"
            first_entry = plan["entries"][0]
            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "CI shard adapter coverageMode must be narrow",
            ):
                pipeline.validate_adapter_verification(
                    tampered["verification"],
                    tampered,
                    project.root,
                    project.root
                    / profile.view["outputs"]["campaigns"]
                    / first_entry["id"],
                )

            project.change("root.lock", "force full\n")
            impact = pipeline.plan_impact(profile, project.root, project.baseline)
            self.assertEqual("full", impact["impact"]["mode"])
            impact_path = write_json(
                project.root / profile.view["outputs"]["impactPlan"],
                impact,
            )
            local = pipeline.derive_adapter_data(
                profile,
                tier="full",
                output=project.root
                / profile.view["outputs"]["derivedAdapters"]
                / "local-full.json",
                campaign_root=project.root
                / profile.view["outputs"]["campaigns"]
                / "local-full",
                impact_plan=(impact_path, impact),
            )
            self.assertEqual("full", local["coverageMode"])

    def test_ci_plan_is_deterministic_selector_first_and_exactly_partitioned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            profile = project.load_profile()
            first = pipeline.build_ci_plan(profile)
            second = pipeline.build_ci_plan(profile)

            self.assertEqual(first, second)
            self.assertEqual(first["contentDigest"], pipeline.ci_plan_sha256(first))
            self.assertEqual("selector", first["entries"][0]["kind"])
            self.assertEqual(
                ["selector-contract"], first["entries"][0]["caseIds"]
            )
            assigned = [
                case_id
                for entry in first["entries"]
                for case_id in entry["caseIds"]
            ]
            self.assertEqual(set(first["fullCaseIds"]), set(assigned))
            self.assertEqual(len(assigned), len(set(assigned)))
            core_entry = next(
                entry for entry in first["entries"] if "core-test" in entry["caseIds"]
            )
            self.assertIn("app-test", core_entry["caseIds"])
            self.assertEqual(["linux", "windows"], first["requiredPlatforms"])

    def test_context_free_ci_validation_enforces_complete_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            plan = pipeline.build_ci_plan(project.load_profile())
            pipeline.validate_ci_plan(plan)

            mutations = []

            def add(label: str, mutate) -> None:
                candidate = copy.deepcopy(plan)
                mutate(candidate)
                candidate["contentDigest"] = pipeline._ci_digest(candidate)
                mutations.append((label, candidate))

            add("boolean schema version", lambda item: item.__setitem__("schemaVersion", True))
            add("bad project ID", lambda item: item.__setitem__("projectId", ".bad"))
            add("bad profile hash", lambda item: item.__setitem__("profileSha256", "bad"))
            add("no required platform", lambda item: item.__setitem__("requiredPlatforms", []))
            add(
                "uncovered required platform",
                lambda item: item.__setitem__("requiredPlatforms", ["darwin"]),
            )
            add(
                "bad entry ID",
                lambda item: item["entries"][0].__setitem__("id", ".bad"),
            )
            add(
                "unhashable kind",
                lambda item: item["entries"][0].__setitem__("kind", []),
            )
            add(
                "oversized shard count",
                lambda item: item["entries"][0].update(
                    {"shardIndex": 1, "shardCount": 65}
                ),
            )

            def duplicate_shard_index(item) -> None:
                group = next(
                    entry
                    for entry in item["entries"]
                    if entry["kind"] == "platform" and entry["shardCount"] > 1
                )
                for entry in item["entries"]:
                    if (
                        entry["kind"] == group["kind"]
                        and entry["platform"] == group["platform"]
                    ):
                        entry["shardIndex"] = 1

            add("duplicate shard index", duplicate_shard_index)

            def invalid_case_id(item) -> None:
                item["fullCaseIds"].append(".bad")
                item["entries"][0]["caseIds"].append(".bad")

            add("invalid case ID", invalid_case_id)

            for label, candidate in mutations:
                with self.subTest(label=label):
                    with self.assertRaises(pipeline.VerificationPipelineError):
                        pipeline.validate_ci_plan(candidate)

            bad_digest = copy.deepcopy(plan)
            bad_digest["contentDigest"] = "bad"
            with self.assertRaises(pipeline.VerificationPipelineError):
                pipeline.validate_ci_plan(bad_digest)

    def test_quick_local_full_and_ci_full_adapters_bind_their_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            profile = project.load_profile()

            project.change("packages/core/unstaged.py")
            quick_plan = pipeline.plan_impact(profile, project.root, project.baseline)
            quick_plan_path = write_json(
                project.root / profile.view["outputs"]["impactPlan"], quick_plan
            )
            quick_output = project.root / profile.view["outputs"]["derivedAdapters"] / "quick.json"
            quick_campaign = project.root / profile.view["outputs"]["campaigns"] / "quick"
            quick = pipeline.render_derived_adapter(
                profile,
                tier="quick",
                output=quick_output,
                campaign_root=quick_campaign,
                impact_plan=(quick_plan_path, quick_plan),
            )
            self.assertEqual(
                set(quick_plan["impact"]["selectedCaseIds"]),
                {item["id"] for item in quick["cases"] if item["quick"]},
            )
            pipeline.validate_adapter_verification(
                quick["verification"], quick, project.root, quick_campaign
            )
            validated_quick = pipeline._kernel_validator()(quick_output)
            self.assertEqual(profile.project_root, validated_quick.project_root)

            project.change("root.lock", "high impact\n")
            full_plan = pipeline.plan_impact(profile, project.root, project.baseline)
            self.assertEqual("full", full_plan["impact"]["mode"])
            full_plan_path = write_json(
                project.root / profile.view["outputs"]["impactPlan"], full_plan
            )
            full_output = project.root / profile.view["outputs"]["derivedAdapters"] / "full.json"
            full_campaign = project.root / profile.view["outputs"]["campaigns"] / "full"
            full = pipeline.render_derived_adapter(
                profile,
                tier="full",
                output=full_output,
                campaign_root=full_campaign,
                impact_plan=(full_plan_path, full_plan),
            )
            self.assertEqual(
                [item["id"] for item in profile.adapter_data["cases"]],
                [item["id"] for item in full["cases"]],
            )
            pipeline.validate_adapter_verification(
                full["verification"], full, project.root, full_campaign
            )

            ci_plan = pipeline.build_ci_plan(profile)
            ci_plan_path = write_json(
                project.root / profile.view["outputs"]["ciPlan"], ci_plan
            )
            entry = ci_plan["entries"][0]
            ci_output = project.root / profile.view["outputs"]["derivedAdapters"] / "ci.json"
            ci_campaign = project.root / profile.view["outputs"]["campaigns"] / "ci"
            ci_adapter = pipeline.render_derived_adapter(
                profile,
                tier="full",
                output=ci_output,
                campaign_root=ci_campaign,
                ci_plan=(ci_plan_path, ci_plan),
                entry_id=entry["id"],
            )
            self.assertEqual(entry["caseIds"], [item["id"] for item in ci_adapter["cases"]])
            self.assertIsNone(ci_adapter["verification"]["impactPlan"])
            pipeline.validate_adapter_verification(
                ci_adapter["verification"], ci_adapter, project.root, ci_campaign
            )

    def test_derived_adapter_rejects_base_tampering_and_output_rebinding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            profile = project.load_profile()
            project.change("packages/core/unstaged.py")
            impact_plan = pipeline.plan_impact(
                profile, project.root, project.baseline
            )
            impact_path = write_json(
                project.root / profile.view["outputs"]["impactPlan"],
                impact_plan,
            )
            output = (
                project.root
                / profile.view["outputs"]["derivedAdapters"]
                / "quick.json"
            )
            campaign = (
                project.root / profile.view["outputs"]["campaigns"] / "quick"
            )
            derived = pipeline.render_derived_adapter(
                profile,
                tier="quick",
                output=output,
                campaign_root=campaign,
                impact_plan=(impact_path, impact_plan),
            )
            validator = pipeline._kernel_validator()
            validator(output)

            source_tamper = copy.deepcopy(derived)
            source_tamper["source"] = {
                "provider": "files",
                "files": ["packages/core/committed.py"],
                "excludes": [".steward/verification/**"],
            }
            project_id_tamper = copy.deepcopy(derived)
            project_id_tamper["projectId"] = "different-project"
            local_only_tamper = copy.deepcopy(derived)
            local_only_tamper["localOnly"]["allowedExternalCapabilities"] = [
                "network"
            ]
            contract_version_tamper = copy.deepcopy(derived)
            contract_version_tamper["verification"]["contractVersion"] = True

            for label, candidate, pattern in (
                ("source", source_tamper, "immutable base field: source"),
                (
                    "projectId",
                    project_id_tamper,
                    "immutable base field: projectId",
                ),
                (
                    "localOnly",
                    local_only_tamper,
                    "immutable base field: localOnly",
                ),
                (
                    "contractVersion",
                    contract_version_tamper,
                    "verification version/tier is invalid",
                ),
            ):
                with self.subTest(label=label):
                    write_json(output, candidate)
                    with self.assertRaisesRegex(Exception, pattern) as rejected:
                        validator(output)
                    self.assertNotIsInstance(rejected.exception, TypeError)

            for label, campaign_root in (
                (
                    "outside configured campaigns",
                    ".steward/verification/rogue-campaign",
                ),
                (
                    "campaign output itself",
                    profile.view["outputs"]["campaigns"],
                ),
            ):
                with self.subTest(label=label):
                    candidate = copy.deepcopy(derived)
                    candidate["campaignRoot"] = campaign_root
                    write_json(output, candidate)
                    with self.assertRaisesRegex(
                        Exception, "strictly under|under outputs.campaigns"
                    ):
                        validator(output)

            rogue_output = (
                project.root
                / ".steward"
                / "verification"
                / "rogue-adapter.json"
            )
            rogue = copy.deepcopy(derived)
            rogue["projectRoot"] = "../.."
            write_json(rogue_output, rogue)
            with self.assertRaisesRegex(
                Exception, "under outputs.derivedAdapters"
            ):
                validator(rogue_output)


@unittest.skipUnless(os.name == "posix", "safe generated configuration is POSIX-only")
class GeneratedEntryLifecycleTests(unittest.TestCase):
    def run_kernel(
        self,
        project: GitProject,
        *arguments: str,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        campaign_cli = (
            PLUGIN_ROOT
            / "skills"
            / "run-closed-loop-verification"
            / "scripts"
            / "campaign.py"
        )
        completed = subprocess.run(
            [sys.executable, str(campaign_cli), *arguments],
            cwd=project.root,
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
        if completed.returncode != expected:
            self.fail(
                "unexpected kernel result\nstdout="
                + completed.stdout
                + "\nstderr="
                + completed.stderr
            )
        return completed

    def run_generated(
        self,
        project: GitProject,
        entry_id: str,
        *,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        local_entry = project.root / project.profile_data["outputs"]["localEntry"]
        environment = os.environ.copy()
        environment["STEWARD_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        completed = subprocess.run(
            [sys.executable, str(local_entry), "ci", "--entry", entry_id],
            cwd=project.root,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=90,
        )
        if completed.returncode != expected:
            self.fail(
                "generated entry failed\nstdout="
                + completed.stdout
                + "\nstderr="
                + completed.stderr
            )
        return completed

    def test_generated_ci_entry_resumes_boundaries_and_is_complete_idempotent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            pipeline._kernel_validator()
            from adapter_paths import current_platform
            from engine import finish_attempt
            from journal_state import Campaign, CampaignLock

            platform = current_platform()
            if platform not in {"darwin", "linux"}:
                self.skipTest("fixture requires a POSIX CI platform")
            adapter = copy.deepcopy(project.adapter_data)
            for item in adapter["cases"]:
                item["platform"] = "any"
            write_json(project.adapter_path, adapter)
            profile_data = copy.deepcopy(project.profile_data)
            profile_data["ci"].update(
                {
                    "platforms": [
                        {"id": platform, "required": True, "shards": 2}
                    ],
                    "portablePlatform": platform,
                    "posixPlatform": platform,
                    "selectorPlatform": platform,
                }
            )
            project.write_profile(profile_data)
            project.profile_data = profile_data
            profile = project.load_profile()
            outputs = profile.view["outputs"]
            pipeline.configure_project(
                project.profile_path,
                project.root,
                [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]],
            )
            project.git("add", "--all")
            project.git("commit", "-qm", "configured lifecycle fixture")
            plan_path = project.root / outputs["ciPlan"]
            plan = pipeline.load_ci_plan(plan_path, profile)
            self.assertGreaterEqual(len(plan["entries"]), 3)

            def derived(entry_id: str) -> tuple[Path, Path]:
                adapter_path = (
                    project.root
                    / outputs["derivedAdapters"]
                    / ("ci-" + entry_id + ".json")
                )
                campaign_root = (
                    project.root
                    / outputs["campaigns"]
                    / ("ci-" + entry_id)
                )
                pipeline.render_derived_adapter(
                    profile,
                    tier="full",
                    output=adapter_path,
                    campaign_root=campaign_root,
                    ci_plan=(plan_path, plan),
                    entry_id=entry_id,
                )
                return adapter_path, campaign_root

            ready_entry = plan["entries"][0]["id"]
            ready_adapter, _ = derived(ready_entry)
            self.run_kernel(project, "init", "--adapter", str(ready_adapter))
            initial = json.loads(
                self.run_kernel(
                    project,
                    "run",
                    "--adapter",
                    str(ready_adapter),
                    "--phase",
                    "full",
                ).stdout
            )
            self.assertEqual("READY_FOR_REGRESSION", initial["executionStatus"])
            self.run_generated(project, ready_entry)
            ready_state = Campaign.load(
                pipeline._kernel_validator()(ready_adapter)
            ).state
            self.assertEqual("COMPLETE", ready_state["status"])
            self.assertEqual(
                ["initial", "regression"],
                [item["mode"] for item in ready_state["attempts"]],
            )
            self.assertEqual(
                ["PASS", "PASS"],
                [item["status"] for item in ready_state["attempts"]],
            )

            active_entry = plan["entries"][1]["id"]
            active_adapter, active_campaign = derived(active_entry)
            self.run_kernel(project, "init", "--adapter", str(active_adapter))
            validated = pipeline._kernel_validator()(active_adapter)
            with CampaignLock(active_campaign):
                active = Campaign.load(validated)
                interrupted_id = active.start_attempt(
                    "initial",
                    active.current_source(),
                )
            self.assertEqual("RUNNING", Campaign.load(validated).state["status"])

            self.run_generated(project, active_entry)
            completed = Campaign.load(validated)
            self.assertEqual("COMPLETE", completed.state["status"])
            self.assertEqual(
                ["initial", "initial", "regression"],
                [item["mode"] for item in completed.state["attempts"]],
            )
            self.assertEqual(
                ["INTERRUPTED", "PASS", "PASS"],
                [item["status"] for item in completed.state["attempts"]],
            )
            self.assertEqual(
                interrupted_id,
                completed.state["attempts"][1]["resumedFrom"],
            )

            before = {
                path.relative_to(active_campaign).as_posix(): path.read_bytes()
                for path in active_campaign.rglob("*")
                if path.is_file()
            }
            self.run_generated(project, active_entry)
            after = {
                path.relative_to(active_campaign).as_posix(): path.read_bytes()
                for path in active_campaign.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertEqual(3, len(Campaign.load(validated).state["attempts"]))

            blocked_entry = plan["entries"][2]["id"]
            blocked_adapter, blocked_campaign = derived(blocked_entry)
            self.run_kernel(project, "init", "--adapter", str(blocked_adapter))
            blocked_validated = pipeline._kernel_validator()(blocked_adapter)
            with CampaignLock(blocked_campaign):
                blocked = Campaign.load(blocked_validated)
                blocked_attempt = blocked.start_attempt(
                    "initial",
                    blocked.current_source(),
                )
                finish_attempt(
                    blocked,
                    blocked_attempt,
                    "BLOCKED",
                    "BLOCKED",
                    reason="temporary local prerequisite is unavailable",
                )
            blocked_before = {
                path.relative_to(blocked_campaign).as_posix(): path.read_bytes()
                for path in blocked_campaign.rglob("*")
                if path.is_file()
            }
            stopped = self.run_generated(project, blocked_entry, expected=1)
            self.assertIn("campaign is BLOCKED", stopped.stderr)
            blocked_after = {
                path.relative_to(blocked_campaign).as_posix(): path.read_bytes()
                for path in blocked_campaign.rglob("*")
                if path.is_file()
            }
            self.assertEqual(blocked_before, blocked_after)
            self.assertEqual("BLOCKED", Campaign.load(blocked_validated).state["status"])


class ConfigurationBoundaryTests(unittest.TestCase):
    def test_configure_freezes_explicit_fixture_inputs_before_first_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            fixture = project.root / "fixtures" / "input.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("{}\n", encoding="utf-8")
            adapter = copy.deepcopy(project.adapter_data)
            adapter["cases"][0]["fixture"] = "fixtures/input.json"
            write_json(project.adapter_path, adapter)
            outputs = project.profile_data["outputs"]
            required = [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]]
            original = pipeline.render_local_entry_bytes

            def mutate_fixture(profile: pipeline.VerificationProfile) -> bytes:
                candidate = original(profile)
                fixture.write_text('{"changed": true}\n', encoding="utf-8")
                return candidate

            with mock.patch.object(
                pipeline,
                "render_local_entry_bytes",
                side_effect=mutate_fixture,
            ):
                with self.assertRaisesRegex(
                    pipeline.VerificationPipelineError,
                    "adapter input cases\\[0\\]\\.fixture changed",
                ):
                    pipeline.configure_project(
                        project.profile_path,
                        project.root,
                        required,
                    )

            for key in ("ciPlan", "localEntry", "workflow"):
                self.assertFalse((project.root / outputs[key]).exists())

    def test_configure_freeze_rejects_a_late_hardlink_alias_without_commits(self) -> None:
        if not hasattr(os, "link"):
            self.skipTest("hard links are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            outputs = project.profile_data["outputs"]
            required = [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]]
            original = pipeline._snapshot_paths

            def link_before_freeze(
                project_root: Path,
                paths: dict[str, str],
            ) -> dict[str, pipeline._SafePathSnapshot]:
                target = project.root / outputs["ciPlan"]
                target.parent.mkdir(parents=True, exist_ok=True)
                os.link(project.profile_path, target)
                return original(project_root, paths)

            with mock.patch.object(
                pipeline,
                "_snapshot_paths",
                side_effect=link_before_freeze,
            ):
                with self.assertRaisesRegex(
                    pipeline.VerificationPipelineError,
                    "physically aliases verification profile",
                ):
                    pipeline.configure_project(
                        project.profile_path,
                        project.root,
                        required,
                    )

            self.assertTrue((project.root / outputs["ciPlan"]).samefile(project.profile_path))
            self.assertFalse((project.root / outputs["localEntry"]).exists())
            self.assertFalse((project.root / outputs["workflow"]).exists())

    def test_exported_static_renderers_are_check_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            profile = project.load_profile()
            plan = pipeline.build_ci_plan(profile)

            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "direct renderer writes are disabled",
            ):
                pipeline.render_local_entry(profile)
            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "direct renderer writes are disabled",
            ):
                pipeline.render_github_actions(profile, plan)

            outputs = project.profile_data["outputs"]
            for key in ("ciPlan", "localEntry", "workflow"):
                self.assertFalse((project.root / outputs[key]).exists())

    def test_review_is_read_only_even_when_generated_files_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            before = project.file_snapshot()

            report = pipeline.review_configuration(project.profile_path, project.root)

            self.assertEqual("review", report["mode"])
            self.assertFalse(report["writePerformed"])
            self.assertFalse(report["ok"])
            self.assertEqual(before, project.file_snapshot())

    def test_direct_review_rejects_an_unreferenced_output_symlink_without_writing(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project_root = base / "project"
            project_root.mkdir()
            project = GitProject(project_root)
            outside = base / "outside"
            outside.mkdir()
            sentinel = outside / "sentinel.txt"
            sentinel.write_text("preserve\n", encoding="utf-8")
            evidence_output = (
                project.root
                / project.profile_data["outputs"]["evidenceBundles"]
            )
            evidence_output.parent.mkdir(parents=True, exist_ok=True)
            try:
                evidence_output.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest("cannot create a directory symlink: " + str(exc))

            with self.assertRaisesRegex(
                pipeline.VerificationPipelineError,
                "outputs.evidenceBundles uses a symlink/reparse path",
            ):
                pipeline.review_configuration(
                    project.profile_path,
                    project.root,
                )

            self.assertEqual("preserve\n", sentinel.read_text(encoding="utf-8"))
            self.assertFalse(
                (outside / "aggregation.json").exists()
            )

    def test_configure_rejects_missing_or_extra_authority_then_writes_only_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            outputs = project.profile_data["outputs"]
            required = [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]]
            before = project.file_snapshot()

            with self.assertRaises(pipeline.VerificationPipelineError):
                pipeline.configure_project(
                    project.profile_path,
                    project.root,
                    required[:-1],
                )
            self.assertEqual(before, project.file_snapshot())

            with self.assertRaises(pipeline.VerificationPipelineError):
                pipeline.configure_project(
                    project.profile_path,
                    project.root,
                    [*required, "outside.txt"],
                )
            self.assertEqual(before, project.file_snapshot())

            report = pipeline.configure_project(
                project.profile_path,
                project.root,
                required,
            )
            after = project.file_snapshot()
            self.assertEqual("configure", report["mode"])
            self.assertTrue(report["writePerformed"])
            self.assertEqual(set(required), set(report["writtenPaths"]))
            self.assertEqual(set(required), set(after) - set(before))
            self.assertTrue(report["ok"])

    def test_configure_detects_input_drift_before_any_projection_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            outputs = project.profile_data["outputs"]
            required = [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]]
            before = project.file_snapshot()
            original = pipeline.render_local_entry_bytes

            def mutate_adapter(profile: pipeline.VerificationProfile) -> bytes:
                candidate = original(profile)
                adapter = json.loads(project.adapter_path.read_text(encoding="utf-8"))
                adapter["cases"][0]["timeoutSeconds"] += 1
                write_json(project.adapter_path, adapter)
                return candidate

            with mock.patch.object(
                pipeline,
                "render_local_entry_bytes",
                side_effect=mutate_adapter,
            ):
                with self.assertRaisesRegex(
                    pipeline.VerificationPipelineError,
                    "base adapter changed|profile or adapter changed",
                ):
                    pipeline.configure_project(
                        project.profile_path,
                        project.root,
                        required,
                    )

            after = project.file_snapshot()
            changed = {
                path
                for path in set(before) | set(after)
                if before.get(path) != after.get(path)
            }
            self.assertEqual(
                {project.adapter_path.relative_to(project.root).as_posix()},
                changed,
            )
            for key in ("ciPlan", "localEntry", "workflow"):
                self.assertFalse((project.root / outputs[key]).exists())

    def test_configure_fail_stops_without_safe_host_primitives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            outputs = project.profile_data["outputs"]
            required = [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]]
            before = project.file_snapshot()

            with mock.patch.object(pipeline, "fcntl", None):
                with self.assertRaisesRegex(
                    pipeline.VerificationPipelineError,
                    "safe batch writes are unavailable",
                ):
                    pipeline.configure_project(
                        project.profile_path,
                        project.root,
                        required,
                    )

            self.assertEqual(before, project.file_snapshot())

    def test_configure_cleans_staging_files_and_created_parents_on_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            outputs = project.profile_data["outputs"]
            required = [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]]
            before = project.tree_snapshot()
            original = pipeline._stage_projection
            staged_count = 0

            def replace_input_after_staging(*args: object, **kwargs: object):
                nonlocal staged_count
                staged = original(*args, **kwargs)
                staged_count += 1
                if staged_count == 3:
                    replacement = project.adapter_path.with_suffix(".replacement")
                    replacement.write_bytes(project.adapter_path.read_bytes())
                    os.replace(replacement, project.adapter_path)
                return staged

            with mock.patch.object(
                pipeline,
                "_stage_projection",
                side_effect=replace_input_after_staging,
            ):
                with self.assertRaisesRegex(
                    pipeline.VerificationPipelineError,
                    "base adapter changed",
                ):
                    pipeline.configure_project(
                        project.profile_path,
                        project.root,
                        required,
                    )

            self.assertEqual(3, staged_count)
            self.assertEqual(before, project.tree_snapshot())

    def test_configure_rejects_a_concurrently_created_missing_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            outputs = project.profile_data["outputs"]
            required = [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]]
            original = pipeline._stage_projection
            injected = False

            def create_frozen_missing_parent(*args: object, **kwargs: object):
                nonlocal injected
                if not injected:
                    injected = True
                    (project.root / outputs["ciPlan"]).parent.mkdir(
                        parents=True,
                        exist_ok=False,
                    )
                return original(*args, **kwargs)

            with mock.patch.object(
                pipeline,
                "_stage_projection",
                side_effect=create_frozen_missing_parent,
            ):
                with self.assertRaisesRegex(
                    pipeline.VerificationPipelineError,
                    "output parent changed",
                ):
                    pipeline.configure_project(
                        project.profile_path,
                        project.root,
                        required,
                    )

            self.assertTrue(injected)
            for key in ("ciPlan", "localEntry", "workflow"):
                self.assertFalse((project.root / outputs[key]).exists())

    def test_configure_rejects_an_external_suffix_below_a_batch_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            project.profile_data["outputs"].update(
                {
                    "ciPlan": "generated/a/ci-plan.json",
                    "localEntry": "generated/a/verify.py",
                    "workflow": "generated/b/workflow.yml",
                }
            )
            project.write_profile()
            outputs = project.profile_data["outputs"]
            required = [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]]
            original = pipeline._stage_projection

            def create_external_suffix(*args: object, **kwargs: object):
                relative = args[1]
                if relative == outputs["workflow"]:
                    (project.root / "generated/b").mkdir(exist_ok=False)
                return original(*args, **kwargs)

            with mock.patch.object(
                pipeline,
                "_stage_projection",
                side_effect=create_external_suffix,
            ):
                with self.assertRaisesRegex(
                    pipeline.VerificationPipelineError,
                    "output parent changed",
                ):
                    pipeline.configure_project(
                        project.profile_path,
                        project.root,
                        required,
                    )

            self.assertTrue((project.root / "generated/b").is_dir())
            for key in ("ciPlan", "localEntry", "workflow"):
                self.assertFalse((project.root / outputs[key]).exists())

    def test_configure_preserves_concurrent_target_change_without_partial_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            outputs = project.profile_data["outputs"]
            required = [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]]
            pipeline.configure_project(project.profile_path, project.root, required)
            before = {
                key: (project.root / outputs[key]).read_bytes()
                for key in ("ciPlan", "localEntry", "workflow")
            }
            original = pipeline.render_github_actions_bytes

            def mutate_target(
                profile: pipeline.VerificationProfile,
                plan: dict[str, object],
            ) -> bytes:
                candidate = original(profile, plan)
                (project.root / outputs["ciPlan"]).write_text(
                    "concurrent-user-change\n",
                    encoding="utf-8",
                )
                return candidate

            with mock.patch.object(
                pipeline,
                "render_github_actions_bytes",
                side_effect=mutate_target,
            ):
                with self.assertRaisesRegex(
                    pipeline.VerificationPipelineError,
                    "CI plan output changed",
                ):
                    pipeline.configure_project(
                        project.profile_path,
                        project.root,
                        required,
                    )

            self.assertEqual(
                b"concurrent-user-change\n",
                (project.root / outputs["ciPlan"]).read_bytes(),
            )
            self.assertEqual(
                before["localEntry"],
                (project.root / outputs["localEntry"]).read_bytes(),
            )
            self.assertEqual(
                before["workflow"],
                (project.root / outputs["workflow"]).read_bytes(),
            )

    def test_configure_rejects_a_final_review_not_bound_to_its_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = GitProject(Path(temporary))
            outputs = project.profile_data["outputs"]
            required = [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]]
            original = pipeline.review_configuration

            def unbound_review(*args: object, **kwargs: object) -> dict[str, object]:
                report = original(*args, **kwargs)
                report["profileFingerprint"] = "sha256:" + "0" * 64
                return report

            with mock.patch.object(
                pipeline,
                "review_configuration",
                side_effect=unbound_review,
            ):
                with self.assertRaisesRegex(
                    pipeline.VerificationPipelineError,
                    "outputs were committed.*does not bind the frozen inputs",
                ):
                    pipeline.configure_project(
                        project.profile_path,
                        project.root,
                        required,
                    )

            for key in ("ciPlan", "localEntry", "workflow"):
                self.assertTrue((project.root / outputs[key]).is_file())

    def test_configure_rejects_parent_symlink_swap_before_batch_write(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project_root = base / "project"
            project_root.mkdir()
            project = GitProject(project_root)
            outputs = project.profile_data["outputs"]
            required = [outputs["ciPlan"], outputs["localEntry"], outputs["workflow"]]
            workflow_parent = (project.root / outputs["workflow"]).parent
            workflow_parent.mkdir(parents=True, exist_ok=True)
            github_root = project.root / ".github"
            held_root = project.root / ".github-held"
            outside = base / "outside"
            outside.mkdir()
            original = pipeline._commit_configuration_batch

            def swap_parent(*args: object, **kwargs: object) -> None:
                github_root.rename(held_root)
                github_root.symlink_to(outside, target_is_directory=True)
                original(*args, **kwargs)

            with mock.patch.object(
                pipeline,
                "_commit_configuration_batch",
                side_effect=swap_parent,
            ):
                with self.assertRaisesRegex(
                    pipeline.VerificationPipelineError,
                    "stable non-link directory|changed during configuration",
                ):
                    pipeline.configure_project(
                        project.profile_path,
                        project.root,
                        required,
                    )

            self.assertEqual([], list(outside.iterdir()))
            self.assertFalse((project.root / outputs["ciPlan"]).exists())
            self.assertFalse((project.root / outputs["localEntry"]).exists())


if __name__ == "__main__":
    unittest.main()
