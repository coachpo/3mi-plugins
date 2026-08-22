"""Public-CLI safety tests for project verification configuration.

The fixtures are deliberately ordinary Git repositories.  The tests avoid
importing implementation modules so refactors cannot bypass the externally
observable fail-closed and write-boundary contracts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterable

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "scripts" / "project_verification.py"
GIT = shutil.which("git")


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _case(
    case_id: str,
    *,
    quick: bool,
    depends_on: Iterable[str] = (),
) -> dict[str, Any]:
    sentinel = (
        "from pathlib import Path; "
        "Path('adapter-command-ran').write_text('ran', encoding='utf-8')"
    )
    return {
        "id": case_id,
        "category": "functional",
        "required": True,
        "quick": quick,
        "platform": "any",
        "dependsOn": list(depends_on),
        "argv": [sys.executable, "-c", sentinel],
        "cwd": ".",
        "timeoutSeconds": 10,
        "fixture": None,
        "externalCapabilities": [],
        "evidence": {"requiredFiles": [], "nonEmptyFiles": []},
    }


class ProjectFixture:
    PROJECT_ID = "verification-safety"
    PROFILE = "verification-profile.json"
    ADAPTER = "adapter.json"
    IMPACT = ".steward/verification/impact-plan.json"
    CI_PLAN = ".steward/verification/ci-plan.json"
    LOCAL_ENTRY = ".steward/verify-project.py"
    WORKFLOW = ".github/workflows/project-verification.yml"
    DERIVED = ".steward/verification/derived-adapters"
    CAMPAIGNS = ".steward/verification/campaigns"
    EVIDENCE = ".steward/verification/evidence"
    AGGREGATION = ".steward/verification/aggregation.json"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True)
        self.profile_path = self.root / self.PROFILE
        self.adapter_path = self.root / self.ADAPTER

        (self.root / "packages/core").mkdir(parents=True)
        (self.root / "packages/app").mkdir(parents=True)
        (self.root / "packages/core/base.py").write_text(
            "CORE = 1\n", encoding="utf-8"
        )
        (self.root / "packages/app/base.py").write_text(
            "APP = 1\n", encoding="utf-8"
        )

        cases = [
            _case("selector-contract", quick=True),
            _case("always-guard", quick=True),
            _case("core-quick", quick=True),
            _case("core-typecheck", quick=True),
            _case("app-quick", quick=True, depends_on=("core-quick",)),
            _case(
                "app-typecheck",
                quick=True,
                depends_on=("core-typecheck",),
            ),
            _case("full-only", quick=False),
        ]
        self.adapter = {
            "schemaVersion": 1,
            "projectId": self.PROJECT_ID,
            "projectRoot": ".",
            "campaignRoot": self.CAMPAIGNS + "/base",
            "source": {
                "provider": "git",
                "excludes": [".steward/**"],
            },
            "localOnly": {
                "enabled": True,
                "allowedExternalCapabilities": [],
            },
            "cases": cases,
        }
        _write_json(self.adapter_path, self.adapter)

        self.profile = {
            "schemaId": "steward.verification-profile",
            "schemaVersion": 1,
            "projectId": self.PROJECT_ID,
            "projectRoot": ".",
            "adapter": {"path": self.ADAPTER},
            "runtime": {
                "pluginRoot": None,
                "pythonExecutables": {"posix": "python3", "windows": "py"},
            },
            "changeDetection": {
                "provider": "git",
                "baseRef": "HEAD",
                "sources": [
                    "committed",
                    "staged",
                    "unstaged",
                    "untracked",
                ],
                "highImpactPaths": ["packages/core/critical.txt"],
                "unknownPath": "full",
            },
            "packages": [
                {
                    "id": "core",
                    "paths": ["packages/core/**"],
                    "dependsOn": [],
                    "quickCaseIds": ["core-quick"],
                    "typecheckCaseIds": ["core-typecheck"],
                },
                {
                    "id": "app",
                    "paths": ["packages/app/**"],
                    "dependsOn": ["core"],
                    "quickCaseIds": ["app-quick"],
                    "typecheckCaseIds": ["app-typecheck"],
                },
            ],
            "guards": [
                {
                    "id": "verification-guard",
                    "paths": ["verification-profile.json", "adapter.json"],
                    "caseIds": ["always-guard"],
                    "alwaysRun": True,
                }
            ],
            "tiers": {
                "quick": {"selection": "impact-plan"},
                "full": {"selection": "all", "ignoreSelector": True},
            },
            "ci": {
                "platforms": [{"id": "linux", "required": True, "shards": 3}],
                "portablePlatform": "linux",
                "posixPlatform": "linux",
                "selectorPlatform": "linux",
                "selectorCaseIds": ["selector-contract"],
            },
            "outputs": {
                "profile": self.PROFILE,
                "impactPlan": self.IMPACT,
                "ciPlan": self.CI_PLAN,
                "localEntry": self.LOCAL_ENTRY,
                "workflow": self.WORKFLOW,
                "derivedAdapters": self.DERIVED,
                "campaigns": self.CAMPAIGNS,
                "evidenceBundles": self.EVIDENCE,
                "aggregation": self.AGGREGATION,
            },
        }
        _write_json(self.profile_path, self.profile)

        self.git("init", "-q")
        self.git("config", "user.email", "verification@example.invalid")
        self.git("config", "user.name", "Verification Safety")
        self.git("add", "--all")
        self.git("commit", "-q", "-m", "baseline")
        self.baseline = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        assert GIT is not None
        completed = subprocess.run(
            [GIT, *args],
            cwd=self.root,
            capture_output=True,
            check=False,
            text=True,
            timeout=20,
        )
        if completed.returncode != expected:
            raise AssertionError(
                f"git {' '.join(args)} returned {completed.returncode}\n"
                f"stdout={completed.stdout}\nstderr={completed.stderr}"
            )
        return completed

    def cli(
        self,
        command: str,
        *args: str,
        expected: int = 0,
        profile: Path | None = None,
        project_root: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [
                sys.executable,
                str(CLI),
                command,
                "--profile",
                str(profile or self.profile_path),
                "--project-root",
                str(project_root or self.root),
                *args,
            ],
            cwd=self.root,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if completed.returncode != expected:
            raise AssertionError(
                f"{command} {args!r} returned {completed.returncode}\n"
                f"stdout={completed.stdout}\nstderr={completed.stderr}"
            )
        return completed

    def json_cli(self, command: str, *args: str) -> dict[str, Any]:
        completed = self.cli(command, *args)
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"CLI did not emit JSON: {completed.stdout!r}"
            ) from exc
        if not isinstance(value, dict):
            raise AssertionError("CLI JSON result is not an object")
        return value

    def plan(self, *extra: str) -> dict[str, Any]:
        return self.json_cli(
            "plan-impact",
            *extra,
            "--output",
            self.IMPACT,
        )


def _tree_snapshot(root: Path) -> dict[str, tuple[Any, ...]]:
    """Snapshot non-Git entries, including ignored files and link targets."""

    result: dict[str, tuple[Any, ...]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".git":
            continue
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        name = relative.as_posix()
        if path.is_symlink():
            result[name] = ("link", mode, os.readlink(path))
        elif path.is_file():
            content = path.read_bytes()
            result[name] = (
                "file",
                mode,
                len(content),
                hashlib.sha256(content).hexdigest(),
            )
    return result


@unittest.skipUnless(GIT is not None, "git is required")
class VerificationSafetyTests(unittest.TestCase):
    def test_validate_profile_emits_a_distinct_input_compatible_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")

            report = fixture.json_cli("validate-profile")

            self.assertTrue(report["ok"])
            self.assertEqual(
                "steward.verification-profile-validation",
                report["schemaId"],
            )
            self.assertEqual(1, report["schemaVersion"])
            self.assertEqual(
                fixture.profile["projectId"],
                report["normalizedProfile"]["projectId"],
            )
            self.assertEqual(
                [case["id"] for case in fixture.adapter["cases"]],
                report["adapterCaseIds"],
            )
            self.assertIn("profileFingerprint", report)
            self.assertIn("verificationCatalogFingerprint", report)
            self.assertNotIn(
                "adapterCatalogFingerprint", report["normalizedProfile"]
            )
            self.assertNotIn("adapterCaseIds", report["normalizedProfile"])

    def test_review_is_zero_write_and_does_not_execute_adapter_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            before = _tree_snapshot(fixture.root)

            report = fixture.json_cli("review")

            self.assertEqual("review", report["mode"])
            self.assertFalse(report["writePerformed"])
            self.assertFalse((fixture.root / "adapter-command-ran").exists())
            self.assertEqual(before, _tree_snapshot(fixture.root))

    def test_review_rejects_unsafe_dynamic_output_without_writes(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = ProjectFixture(base / "project")
            outside = base / "outside-evidence"
            outside.mkdir()
            evidence = fixture.root / fixture.EVIDENCE
            evidence.parent.mkdir(parents=True, exist_ok=True)
            try:
                evidence.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"cannot create a directory symlink: {exc}")
            before = _tree_snapshot(fixture.root)

            rejected = fixture.cli("review", expected=2)

            self.assertRegex(rejected.stderr, r"symlink|reparse")
            self.assertEqual(before, _tree_snapshot(fixture.root))
            self.assertEqual([], list(outside.iterdir()))

    def test_expected_reports_are_reproducible_and_strictly_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            before = _tree_snapshot(fixture.root)

            direct_ci = fixture.cli(
                "build-ci-plan",
                "--output",
                fixture.CI_PLAN,
                expected=2,
            )
            direct_local = fixture.cli("render-local", expected=2)
            direct_github = fixture.cli("render-github", expected=2)
            self.assertIn("direct CI plan writes are disabled", direct_ci.stderr)
            self.assertIn("direct renderer writes are disabled", direct_local.stderr)
            self.assertIn("direct renderer writes are disabled", direct_github.stderr)
            self.assertEqual(before, _tree_snapshot(fixture.root))

            local_first = fixture.json_cli("render-local", "--expected")
            local_second = fixture.json_cli("render-local", "--expected")
            github_first = fixture.json_cli("render-github", "--expected")
            github_second = fixture.json_cli("render-github", "--expected")

            self.assertEqual(local_first, local_second)
            self.assertEqual(github_first, github_second)
            for report, output in (
                (local_first, fixture.LOCAL_ENTRY),
                (github_first, fixture.WORKFLOW),
            ):
                self.assertEqual("expected", report["mode"])
                self.assertFalse(report["writePerformed"])
                self.assertEqual(output, report["output"])
                candidate = base64.b64decode(report["contentBase64"], validate=True)
                self.assertEqual(report["size"], len(candidate))
                self.assertEqual(
                    report["sha256"],
                    "sha256:" + hashlib.sha256(candidate).hexdigest(),
                )
            self.assertIn(
                b"project_verification.py", base64.b64decode(local_first["contentBase64"])
            )
            self.assertIn(
                b"actions/checkout@", base64.b64decode(github_first["contentBase64"])
            )
            self.assertEqual(before, _tree_snapshot(fixture.root))

            review = fixture.json_cli("review")
            self.assertFalse(review["ok"])
            for check in review["checks"]:
                if check["id"] in {
                    "CI plan",
                    "local verification entry",
                    "GitHub Actions workflow",
                }:
                    self.assertIn("expectedSha256", check)
                    self.assertIn("expectedSize", check)
            self.assertEqual(before, _tree_snapshot(fixture.root))

            for relative in (fixture.CI_PLAN, fixture.LOCAL_ENTRY, fixture.WORKFLOW):
                path = fixture.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"stale\n")
            stale = _tree_snapshot(fixture.root)
            self.assertEqual(local_first, fixture.json_cli("render-local", "--expected"))
            self.assertEqual(
                github_first,
                fixture.json_cli("render-github", "--expected"),
            )
            self.assertEqual(stale, _tree_snapshot(fixture.root))

    def test_configure_writes_only_the_frozen_explicit_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            before = _tree_snapshot(fixture.root)
            allowed = [fixture.CI_PLAN, fixture.LOCAL_ENTRY, fixture.WORKFLOW]
            arguments = [item for path in allowed for item in ("--allow-write", path)]

            report = fixture.json_cli("configure", *arguments)

            self.assertEqual("configure", report["mode"])
            self.assertTrue(report["writePerformed"])
            self.assertEqual(sorted(allowed), report["authorizedWriteSet"])
            self.assertEqual(sorted(allowed), report["writtenPaths"])
            self.assertFalse((fixture.root / "adapter-command-ran").exists())
            after = _tree_snapshot(fixture.root)
            changed = {
                path
                for path in set(before) | set(after)
                if before.get(path) != after.get(path)
            }
            self.assertEqual(set(allowed), changed)

    def test_configure_rejects_unlisted_or_incomplete_write_sets_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            before = _tree_snapshot(fixture.root)
            rejected = fixture.cli(
                "configure",
                "--allow-write",
                fixture.CI_PLAN,
                "--allow-write",
                fixture.LOCAL_ENTRY,
                "--allow-write",
                fixture.WORKFLOW,
                "--allow-write",
                "packages/core/base.py",
                expected=2,
            )
            self.assertIn("undeclared path", rejected.stderr)
            self.assertEqual(before, _tree_snapshot(fixture.root))

            rejected = fixture.cli(
                "configure",
                "--allow-write",
                fixture.CI_PLAN,
                "--allow-write",
                fixture.LOCAL_ENTRY,
                expected=2,
            )
            self.assertIn("omits a generated output", rejected.stderr)
            self.assertEqual(before, _tree_snapshot(fixture.root))

    def test_configure_rejects_adapter_or_runtime_output_overlap_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            profile = _read_json(fixture.profile_path)
            profile["outputs"]["ciPlan"] = fixture.ADAPTER
            _write_json(fixture.profile_path, profile)
            before = _tree_snapshot(fixture.root)

            rejected = fixture.cli(
                "configure",
                "--allow-write",
                fixture.ADAPTER,
                "--allow-write",
                fixture.LOCAL_ENTRY,
                "--allow-write",
                fixture.WORKFLOW,
                expected=2,
            )

            self.assertIn("base adapter", rejected.stderr)
            self.assertEqual(before, _tree_snapshot(fixture.root))
            self.assertEqual(fixture.adapter, _read_json(fixture.adapter_path))

        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            runtime = fixture.root / "runtime"
            (runtime / "scripts").mkdir(parents=True)
            (runtime / "skills/run-closed-loop-verification/scripts").mkdir(
                parents=True
            )
            config_entry = runtime / "scripts/project_verification.py"
            campaign_entry = (
                runtime
                / "skills/run-closed-loop-verification/scripts/campaign.py"
            )
            config_entry.write_text("# config runtime\n", encoding="utf-8")
            campaign_entry.write_text("# campaign runtime\n", encoding="utf-8")
            profile = _read_json(fixture.profile_path)
            profile["runtime"]["pluginRoot"] = "runtime"
            profile["outputs"]["ciPlan"] = (
                "runtime/scripts/project_verification.py"
            )
            _write_json(fixture.profile_path, profile)
            before = _tree_snapshot(fixture.root)

            rejected = fixture.cli(
                "configure",
                "--allow-write",
                "runtime/scripts/project_verification.py",
                "--allow-write",
                fixture.LOCAL_ENTRY,
                "--allow-write",
                fixture.WORKFLOW,
                expected=2,
            )

            self.assertIn(
                "cannot overlap verification runtime entries",
                rejected.stderr,
            )
            self.assertEqual(before, _tree_snapshot(fixture.root))
            self.assertEqual(
                "# config runtime\n", config_entry.read_text(encoding="utf-8")
            )

    def test_configure_rejects_explicit_source_input_overlap_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            source_path = "packages/core/base.py"
            adapter = _read_json(fixture.adapter_path)
            adapter["source"] = {
                "provider": "files",
                "files": [source_path],
                "excludes": [".steward/**"],
            }
            _write_json(fixture.adapter_path, adapter)
            profile = _read_json(fixture.profile_path)
            profile["outputs"]["ciPlan"] = source_path
            _write_json(fixture.profile_path, profile)
            before = _tree_snapshot(fixture.root)

            rejected = fixture.cli(
                "configure",
                "--allow-write",
                source_path,
                "--allow-write",
                fixture.LOCAL_ENTRY,
                "--allow-write",
                fixture.WORKFLOW,
                expected=2,
            )

            self.assertIn(
                "cannot overlap explicit adapter input source.files[0]",
                rejected.stderr,
            )
            self.assertEqual(before, _tree_snapshot(fixture.root))
            self.assertEqual(
                "CORE = 1\n",
                (fixture.root / source_path).read_text(encoding="utf-8"),
            )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            adapter = _read_json(fixture.adapter_path)
            adapter["source"] = {
                "provider": "files",
                "files": [fixture.PROFILE, "packages/core/base.py"],
                "excludes": [".steward/**"],
            }
            _write_json(fixture.adapter_path, adapter)

            accepted = fixture.cli("validate-profile")

            self.assertEqual(0, accepted.returncode)

    def test_path_escape_and_symlinked_output_parent_are_rejected_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = ProjectFixture(base / "project")
            profile = _read_json(fixture.profile_path)
            profile["outputs"]["workflow"] = "../escaped.yml"
            _write_json(fixture.profile_path, profile)
            rejected = fixture.cli("validate-profile", expected=2)
            self.assertIn("project-relative path", rejected.stderr)
            self.assertFalse((base / "escaped.yml").exists())

        if not hasattr(os, "symlink"):
            return
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = ProjectFixture(base / "project")
            outside = base / "outside"
            outside.mkdir()
            try:
                (fixture.root / ".github").symlink_to(
                    outside, target_is_directory=True
                )
            except OSError as exc:
                self.skipTest(f"cannot create a directory symlink: {exc}")
            before = _tree_snapshot(fixture.root)
            rejected = fixture.cli(
                "configure",
                "--allow-write",
                fixture.CI_PLAN,
                "--allow-write",
                fixture.LOCAL_ENTRY,
                "--allow-write",
                fixture.WORKFLOW,
                expected=2,
            )
            self.assertRegex(rejected.stderr, r"symlink|reparse")
            self.assertEqual(before, _tree_snapshot(fixture.root))
            self.assertFalse((outside / "workflows/project-verification.yml").exists())

    def test_symlinked_project_root_and_profile_are_rejected_without_writes(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = ProjectFixture(base / "project")
            root_link = base / "project-link"
            profile_link = fixture.root / "verification-profile-link.json"
            try:
                root_link.symlink_to(fixture.root, target_is_directory=True)
                profile_link.symlink_to(fixture.profile_path)
            except OSError as exc:
                self.skipTest(f"cannot create symlinks: {exc}")
            before = _tree_snapshot(fixture.root)

            rejected_root = fixture.cli(
                "validate-profile",
                profile=root_link / fixture.PROFILE,
                project_root=root_link,
                expected=2,
            )
            self.assertRegex(rejected_root.stderr, r"symlink|reparse")
            self.assertNotIn("Traceback", rejected_root.stderr)
            self.assertEqual(before, _tree_snapshot(fixture.root))

            rejected_profile = fixture.cli(
                "validate-profile",
                profile=profile_link,
                expected=2,
            )
            self.assertRegex(rejected_profile.stderr, r"symlink|reparse")
            self.assertNotIn("Traceback", rejected_profile.stderr)
            self.assertEqual(before, _tree_snapshot(fixture.root))

            parent_link = base / "project-parent-link"
            try:
                parent_link.symlink_to(base, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"cannot create a parent symlink: {exc}")
            rejected_parent = fixture.cli(
                "validate-profile",
                profile=parent_link / "project" / fixture.PROFILE,
                project_root=parent_link / "project",
                expected=2,
            )
            self.assertRegex(rejected_parent.stderr, r"symlink|reparse")
            self.assertNotIn("Traceback", rejected_parent.stderr)
            self.assertEqual(before, _tree_snapshot(fixture.root))

    def test_renderers_reject_in_root_symlink_redirects_without_writes(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = ProjectFixture(base / "project")
            outside = base / "outside-local"
            outside.mkdir()
            profile = _read_json(fixture.profile_path)
            profile["outputs"]["localEntry"] = "local-output/verify-project.py"
            _write_json(fixture.profile_path, profile)
            try:
                (fixture.root / "local-output").symlink_to(
                    outside, target_is_directory=True
                )
            except OSError as exc:
                self.skipTest(f"cannot create a directory symlink: {exc}")
            before = _tree_snapshot(fixture.root)

            rejected = fixture.cli("render-local", "--check", expected=2)

            self.assertRegex(rejected.stderr, r"symlink|reparse")
            self.assertNotIn("Traceback", rejected.stderr)
            self.assertEqual(before, _tree_snapshot(fixture.root))
            self.assertEqual([], list(outside.iterdir()))

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = ProjectFixture(base / "project")
            _write_json(
                fixture.root / fixture.CI_PLAN,
                fixture.json_cli("build-ci-plan"),
            )
            outside = base / "outside-github"
            outside.mkdir()
            try:
                (fixture.root / ".github").symlink_to(
                    outside, target_is_directory=True
                )
            except OSError as exc:
                self.skipTest(f"cannot create a directory symlink: {exc}")
            before = _tree_snapshot(fixture.root)

            rejected = fixture.cli("render-github", "--check", expected=2)

            self.assertRegex(rejected.stderr, r"symlink|reparse")
            self.assertNotIn("Traceback", rejected.stderr)
            self.assertEqual(before, _tree_snapshot(fixture.root))
            self.assertEqual([], list(outside.iterdir()))

    def test_render_github_rejects_a_symlinked_ci_source_parent(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = ProjectFixture(base / "project")
            plan = fixture.json_cli("build-ci-plan")
            outside = base / "outside-source"
            _write_json(outside / "ci-plan.json", plan)
            source_link = fixture.root / "ci-source"
            try:
                source_link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"cannot create a directory symlink: {exc}")
            before = _tree_snapshot(fixture.root)

            rejected = fixture.cli(
                "render-github",
                "--ci-plan",
                "ci-source/ci-plan.json",
                "--check",
                expected=2,
            )

            self.assertRegex(rejected.stderr, r"symlink|reparse")
            self.assertNotIn("Traceback", rejected.stderr)
            self.assertEqual(before, _tree_snapshot(fixture.root))
            self.assertFalse((fixture.root / fixture.WORKFLOW).exists())

    def test_unknown_high_impact_and_missing_merge_base_fail_closed_to_full(self) -> None:
        scenarios = (
            (
                "unknown",
                "docs/unowned.txt",
                "UNOWNED_PATH",
                (),
            ),
            (
                "high-impact",
                "packages/core/critical.txt",
                "HIGH_IMPACT_PATH",
                (),
            ),
            (
                "merge-base",
                None,
                "MERGE_BASE_UNAVAILABLE",
                ("--base-ref", "refs/heads/does-not-exist"),
            ),
        )
        for label, changed_path, reason, extra in scenarios:
            with self.subTest(scenario=label), tempfile.TemporaryDirectory() as temporary:
                fixture = ProjectFixture(Path(temporary) / "project")
                if changed_path is not None:
                    path = fixture.root / changed_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(label + "\n", encoding="utf-8")

                plan = fixture.plan(*extra)

                self.assertEqual("full", plan["impact"]["mode"])
                self.assertIn(reason, plan["impact"]["reasonCodes"])
                self.assertEqual(
                    plan["impact"]["fullCaseIds"],
                    plan["impact"]["selectedCaseIds"],
                )

    def test_all_git_change_sources_are_preserved_and_select_downstream_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")

            committed = fixture.root / "packages/core/committed.py"
            committed.write_text("COMMITTED = 1\n", encoding="utf-8")
            fixture.git("add", committed.relative_to(fixture.root).as_posix())
            fixture.git("commit", "-q", "-m", "committed source")

            staged = fixture.root / "packages/app/staged.py"
            staged.write_text("STAGED = 1\n", encoding="utf-8")
            fixture.git("add", staged.relative_to(fixture.root).as_posix())

            unstaged = fixture.root / "packages/core/base.py"
            unstaged.write_text("CORE = 2\n", encoding="utf-8")

            untracked = fixture.root / "packages/app/untracked.py"
            untracked.write_text("UNTRACKED = 1\n", encoding="utf-8")

            plan = fixture.plan("--base-ref", fixture.baseline)

            self.assertEqual("quick", plan["impact"]["mode"])
            expected_paths = {
                "committed": "packages/core/committed.py",
                "staged": "packages/app/staged.py",
                "unstaged": "packages/core/base.py",
                "untracked": "packages/app/untracked.py",
            }
            for source, expected_path in expected_paths.items():
                self.assertIn(
                    expected_path,
                    {entry["path"] for entry in plan["changes"][source]},
                )
            self.assertEqual({"core", "app"}, set(plan["impact"]["directPackageIds"]))
            self.assertEqual({"core", "app"}, set(plan["impact"]["affectedPackageIds"]))
            self.assertEqual(
                {"core-typecheck", "app-typecheck"},
                set(plan["impact"]["typecheckCaseIds"]),
            )
            self.assertIn("verification-guard", plan["impact"]["guardIds"])
            self.assertTrue(
                {
                    "selector-contract",
                    "always-guard",
                    "core-quick",
                    "core-typecheck",
                    "app-quick",
                    "app-typecheck",
                }.issubset(set(plan["impact"]["selectedCaseIds"]))
            )
            self.assertNotIn("full-only", plan["impact"]["selectedCaseIds"])

    def test_core_change_selects_transitive_downstream_typecheck_and_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            (fixture.root / "packages/core/base.py").write_text(
                "CORE = 2\n", encoding="utf-8"
            )

            plan = fixture.plan()

            self.assertEqual("quick", plan["impact"]["mode"])
            self.assertEqual(["core"], plan["impact"]["directPackageIds"])
            self.assertEqual({"core", "app"}, set(plan["impact"]["affectedPackageIds"]))
            self.assertEqual(
                {"core-typecheck", "app-typecheck"},
                set(plan["impact"]["typecheckCaseIds"]),
            )
            self.assertEqual(["verification-guard"], plan["impact"]["guardIds"])

    def test_full_fallback_derived_adapter_retains_the_complete_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            critical = fixture.root / "packages/core/critical.txt"
            critical.write_text("critical\n", encoding="utf-8")
            plan = fixture.plan()
            self.assertEqual("full", plan["impact"]["mode"])
            output = fixture.DERIVED + "/local-full.json"
            derived = fixture.json_cli(
                "render-adapter",
                "--tier",
                "full",
                "--impact-plan",
                fixture.IMPACT,
                "--output",
                output,
                "--campaign-root",
                fixture.CAMPAIGNS + "/local-full",
            )

            self.assertEqual("full", derived["verification"]["tier"])
            self.assertIsNone(derived["verification"]["ciPlan"])
            self.assertEqual(
                [case["id"] for case in fixture.adapter["cases"]],
                [case["id"] for case in derived["cases"]],
            )
            self.assertEqual(
                plan["impact"]["fullCaseIds"],
                [case["id"] for case in derived["cases"]],
            )

    def test_duplicate_json_keys_and_unknown_fields_are_strict_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            raw = fixture.profile_path.read_text(encoding="utf-8")
            needle = f'  "projectId": "{fixture.PROJECT_ID}",\n'
            self.assertIn(needle, raw)
            fixture.profile_path.write_text(
                raw.replace(needle, needle + needle, 1), encoding="utf-8"
            )
            duplicate = fixture.cli("validate-profile", expected=2)
            self.assertIn("duplicate key", duplicate.stderr)
            self.assertNotIn("Traceback", duplicate.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary) / "project")
            profile = _read_json(fixture.profile_path)
            profile["unexpected"] = True
            _write_json(fixture.profile_path, profile)
            unknown = fixture.cli("validate-profile", expected=2)
            self.assertIn("unknown fields", unknown.stderr)
            self.assertNotIn("Traceback", unknown.stderr)


if __name__ == "__main__":
    unittest.main()
