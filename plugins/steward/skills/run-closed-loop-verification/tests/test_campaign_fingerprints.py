"""Boundary tests for adapters, paths, and source fingerprints.

The tests prefer the public CLI so implementation refactors do not weaken the
contract.  The lock test imports the small lock implementation only because a
foreign-platform branch cannot be reached through the CLI on a POSIX host.
"""

from __future__ import annotations

import copy
import importlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
from typing import Optional
import unittest
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_CLI = SKILL_ROOT / "scripts" / "campaign.py"
TIMEOUT_SECONDS = 30
RISK_CATEGORIES = ("smoke", "functional", "integration", "workflow", "role-play")


def _case(category: str, ordinal: int) -> dict[str, object]:
    return {
        "id": f"{category}-{ordinal}",
        "category": category,
        "required": True,
        "platform": "any",
        "dependsOn": [],
        "argv": [sys.executable, "-c", "pass"],
        "cwd": ".",
        "timeoutSeconds": 10,
        "fixture": None,
        "externalCapabilities": [],
        "evidence": {"requiredFiles": [], "nonEmptyFiles": []},
    }


class ProjectFixture:
    """A disposable project with a safe, complete adapter."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.adapter_path = root / "adapter.json"
        (root / "source.txt").write_text("baseline\n", encoding="utf-8")
        self.adapter: dict[str, object] = {
            "schemaVersion": 1,
            "projectId": "fingerprint-test",
            "projectRoot": ".",
            "campaignRoot": ".campaign",
            "source": {
                "provider": "files",
                "files": ["source.txt"],
                "excludes": [".campaign"],
            },
            "localOnly": {"enabled": True, "allowedExternalCapabilities": []},
            "cases": [_case(category, index) for index, category in enumerate(RISK_CATEGORIES, 1)],
        }

    def write_adapter(self, adapter: Optional[dict[str, object]] = None) -> Path:
        value = self.adapter if adapter is None else adapter
        self.adapter_path.write_text(
            json.dumps(value, ensure_ascii=True, allow_nan=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return self.adapter_path

    def cli(self, command: str, *extra: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(CAMPAIGN_CLI), command, "--adapter", str(self.adapter_path), *extra],
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )


class FingerprintTestCase(unittest.TestCase):
    def assert_configuration_error(self, result: subprocess.CompletedProcess[bytes]) -> None:
        stderr = result.stderr.decode("utf-8", "backslashreplace")
        self.assertEqual(result.returncode, 2, stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertTrue(stderr.startswith("ERROR:"), stderr)

    def init_and_read(self, fixture: ProjectFixture) -> dict[str, object]:
        fixture.write_adapter()
        result = fixture.cli("init")
        stderr = result.stderr.decode("utf-8", "backslashreplace")
        self.assertEqual(result.returncode, 0, stderr)
        return json.loads(result.stdout)

    def test_unknown_kernel_owned_fields_are_rejected(self) -> None:
        mutations = {
            "root": lambda value: value.__setitem__("unexpected", True),
            "source": lambda value: value["source"].__setitem__("unexpected", True),
            "localOnly": lambda value: value["localOnly"].__setitem__("unexpected", True),
            "case": lambda value: value["cases"][0].__setitem__("unexpected", True),
            "evidence": lambda value: value["cases"][0]["evidence"].__setitem__("unexpected", True),
        }
        for label, mutate in mutations.items():
            with self.subTest(location=label), tempfile.TemporaryDirectory() as temporary:
                fixture = ProjectFixture(Path(temporary))
                adapter = copy.deepcopy(fixture.adapter)
                mutate(adapter)
                fixture.write_adapter(adapter)
                self.assert_configuration_error(fixture.cli("init"))

    def test_boolean_fields_require_json_booleans(self) -> None:
        for field, invalid in (
            ("localOnly.enabled", 1),
            ("localOnly.enabled", "true"),
            ("localOnly.enabled", None),
            ("case.required", 1),
            ("case.required", "false"),
            ("case.required", None),
        ):
            with self.subTest(field=field, value=invalid), tempfile.TemporaryDirectory() as temporary:
                fixture = ProjectFixture(Path(temporary))
                adapter = copy.deepcopy(fixture.adapter)
                if field == "localOnly.enabled":
                    adapter["localOnly"]["enabled"] = invalid
                else:
                    adapter["cases"][0]["required"] = invalid
                fixture.write_adapter(adapter)
                self.assert_configuration_error(fixture.cli("init"))

    def test_platform_is_strictly_typed_and_enumerated(self) -> None:
        for invalid in (
            None,
            1,
            "",
            "all",
            "mac",
            "macos",
            "osx",
            "win",
            "solaris",
            ["linux"],
        ):
            with self.subTest(value=invalid), tempfile.TemporaryDirectory() as temporary:
                fixture = ProjectFixture(Path(temporary))
                adapter = copy.deepcopy(fixture.adapter)
                adapter["cases"][0]["platform"] = invalid
                fixture.write_adapter(adapter)
                self.assert_configuration_error(fixture.cli("init"))

    def test_timeout_must_be_finite_positive_and_bounded(self) -> None:
        for invalid in (math.nan, math.inf, -math.inf, 0, -1, True, "10", 604801):
            with self.subTest(value=invalid), tempfile.TemporaryDirectory() as temporary:
                fixture = ProjectFixture(Path(temporary))
                adapter = copy.deepcopy(fixture.adapter)
                adapter["cases"][0]["timeoutSeconds"] = invalid
                fixture.write_adapter(adapter)
                self.assert_configuration_error(fixture.cli("init"))

    def test_secret_like_values_and_fields_are_rejected(self) -> None:
        def secret_argv(value: dict[str, object]) -> None:
            value["cases"][0]["argv"].append("password=hunter2")

        def secret_fixture_field(value: dict[str, object]) -> None:
            value["cases"][0]["fixture"] = {"password": "hunter2"}

        def secret_fixture_value(value: dict[str, object]) -> None:
            value["cases"][0]["fixture"] = {"description": "auth_token=abcdefghijklmnop"}

        for label, mutate in (
            ("argv", secret_argv),
            ("fixture field", secret_fixture_field),
            ("fixture value", secret_fixture_value),
        ):
            with self.subTest(location=label), tempfile.TemporaryDirectory() as temporary:
                fixture = ProjectFixture(Path(temporary))
                adapter = copy.deepcopy(fixture.adapter)
                mutate(adapter)
                fixture.write_adapter(adapter)
                self.assert_configuration_error(fixture.cli("init"))

    def test_unicode_is_supported_but_lone_surrogates_fail_structurally(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary))
            fixture.adapter["projectId"] = "验证-🧪"
            summary = self.init_and_read(fixture)
            self.assertEqual(summary["projectId"], "验证-🧪")

        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary))
            fixture.adapter["cases"][0]["argv"].append("\ud800")
            fixture.write_adapter()
            self.assert_configuration_error(fixture.cli("init"))

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_source_path_rejects_a_symlinked_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary))
            real_dir = fixture.root / "real-source"
            real_dir.mkdir()
            (real_dir / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            try:
                (fixture.root / "source-alias").symlink_to(real_dir, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"cannot create a directory symlink: {exc}")
            fixture.adapter["source"]["files"] = ["source-alias/module.py"]
            fixture.write_adapter()
            self.assert_configuration_error(fixture.cli("init"))

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_campaign_root_rejects_a_symlinked_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary))
            target = fixture.root / "campaign-parent-target"
            target.mkdir()
            try:
                (fixture.root / "campaign-parent-alias").symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"cannot create a directory symlink: {exc}")
            fixture.adapter["campaignRoot"] = "campaign-parent-alias/.campaign"
            fixture.adapter["source"]["excludes"] = [
                "campaign-parent-alias/.campaign",
                "campaign-parent-target/.campaign",
            ]
            fixture.write_adapter()
            self.assert_configuration_error(fixture.cli("init"))

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_evidence_path_rejects_a_symlinked_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary))
            script = (
                "import os; from pathlib import Path; "
                "root=Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR']); "
                "(root/'real').mkdir(); "
                "(root/'real'/'proof.txt').write_text('ok', encoding='utf-8'); "
                "(root/'alias').symlink_to('real', target_is_directory=True)"
            )
            first = fixture.adapter["cases"][0]
            first["argv"] = [sys.executable, "-c", script]
            first["evidence"] = {
                "requiredFiles": ["alias/proof.txt"],
                "nonEmptyFiles": ["alias/proof.txt"],
            }
            self.init_and_read(fixture)
            result = fixture.cli("run")
            stderr = result.stderr.decode("utf-8", "backslashreplace")
            self.assertEqual(result.returncode, 1, stderr)
            summary = json.loads(result.stdout)
            self.assertIn(summary["cases"][first["id"]]["status"], {"FAILED", "BLOCKED"})

    @unittest.skipUnless(os.name == "posix", "backslash filename identity is POSIX-specific")
    def test_git_backslash_filename_content_changes_fingerprint(self) -> None:
        git = shutil.which("git")
        if git is None:
            self.skipTest("git is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary))
            filename = "name\\with-backslash.txt"
            path = fixture.root / filename
            path.write_text("one\n", encoding="utf-8")
            subprocess.run([git, "init", "-q", str(fixture.root)], check=True)
            subprocess.run([git, "-C", str(fixture.root), "add", "--", filename], check=True)
            fixture.adapter["source"] = {"provider": "git", "excludes": [".campaign"]}
            initial = self.init_and_read(fixture)
            path.write_text("two\n", encoding="utf-8")
            status_result = fixture.cli("status")
            self.assertEqual(status_result.returncode, 0, status_result.stderr.decode("utf-8", "replace"))
            status = json.loads(status_result.stdout)
            self.assertNotEqual(
                initial["currentSourceFingerprint"],
                status["currentObservedSourceFingerprint"],
            )

    def test_gitlink_object_id_changes_fingerprint(self) -> None:
        git = shutil.which("git")
        if git is None:
            self.skipTest("git is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary))
            subprocess.run([git, "init", "-q", str(fixture.root)], check=True)
            first_oid = subprocess.run(
                [git, "-C", str(fixture.root), "hash-object", "-w", "--stdin"],
                input=b"first gitlink target\n",
                stdout=subprocess.PIPE,
                check=True,
            ).stdout.decode("ascii").strip()
            second_oid = subprocess.run(
                [git, "-C", str(fixture.root), "hash-object", "-w", "--stdin"],
                input=b"second gitlink target\n",
                stdout=subprocess.PIPE,
                check=True,
            ).stdout.decode("ascii").strip()
            subprocess.run(
                [git, "-C", str(fixture.root), "update-index", "--add", "--cacheinfo", f"160000,{first_oid},vendor/lib"],
                check=True,
            )
            fixture.adapter["source"] = {"provider": "git", "excludes": [".campaign"]}
            initial = self.init_and_read(fixture)
            subprocess.run(
                [git, "-C", str(fixture.root), "update-index", "--cacheinfo", f"160000,{second_oid},vendor/lib"],
                check=True,
            )
            status_result = fixture.cli("status")
            self.assertEqual(status_result.returncode, 0, status_result.stderr.decode("utf-8", "replace"))
            status = json.loads(status_result.stdout)
            self.assertNotEqual(
                initial["currentSourceFingerprint"],
                status["currentObservedSourceFingerprint"],
            )

    def test_catalog_drift_is_reported_and_execution_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProjectFixture(Path(temporary))
            initial = self.init_and_read(fixture)
            fixture.adapter["cases"][0]["timeoutSeconds"] = 11
            fixture.write_adapter()

            status_result = fixture.cli("status")
            self.assertEqual(status_result.returncode, 0, status_result.stderr.decode("utf-8", "replace"))
            status = json.loads(status_result.stdout)
            self.assertTrue(status["catalogDrift"])
            self.assertEqual(status["catalogFingerprint"], initial["catalogFingerprint"])

            run_result = fixture.cli("run")
            self.assert_configuration_error(run_result)

    def test_windows_lock_branch_locks_and_unlocks_one_byte(self) -> None:
        scripts_dir = SKILL_ROOT / "scripts"
        module_name = "journal_state" if (scripts_dir / "journal_state.py").exists() else "campaign"
        sys.path.insert(0, str(scripts_dir))
        try:
            facade = importlib.import_module(module_name)
        finally:
            sys.path.remove(str(scripts_dir))
        lock_class = facade.CampaignLock
        module = sys.modules[lock_class.__module__]

        calls: list[tuple[int, int]] = []
        fake_msvcrt = types.SimpleNamespace(
            LK_NBLCK=101,
            LK_UNLCK=202,
            locking=lambda _fd, mode, size: calls.append((mode, size)),
        )
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(module, "fcntl", None), mock.patch.dict(
                sys.modules, {"msvcrt": fake_msvcrt}
            ):
                with lock_class(Path(temporary)):
                    self.assertEqual(calls, [(fake_msvcrt.LK_NBLCK, 1)])
        self.assertEqual(
            calls,
            [(fake_msvcrt.LK_NBLCK, 1), (fake_msvcrt.LK_UNLCK, 1)],
        )


if __name__ == "__main__":
    unittest.main()
