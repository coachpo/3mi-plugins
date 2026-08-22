"""Black-box path, adapter-schema, and conflicted-index boundary tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence
import unittest
from unittest import mock

from helpers import (
    campaign_path,
    make_adapter,
    make_case,
    read_json,
    run_cli,
    write_json,
)


GIT = shutil.which("git")
SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import adapter_paths as adapter_runtime  # noqa: E402


def _stderr(completed: subprocess.CompletedProcess[str]) -> str:
    return completed.stderr.encode("utf-8", "backslashreplace").decode("utf-8")


def _replace_source(adapter_path: Path, source: Mapping[str, Any]) -> None:
    adapter = read_json(adapter_path)
    adapter["source"] = dict(source)
    write_json(adapter_path, adapter)


def _symlink_directory(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        raise unittest.SkipTest(f"cannot create directory symlink: {exc}") from exc


class ConfigurationErrorAssertions(unittest.TestCase):
    def assert_configuration_error(
        self, completed: subprocess.CompletedProcess[str]
    ) -> None:
        diagnostic = _stderr(completed)
        self.assertEqual(completed.returncode, 2, diagnostic or completed.stdout)
        self.assertNotIn("Traceback", diagnostic + completed.stdout)
        self.assertTrue(diagnostic.startswith("ERROR:"), diagnostic)


@unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
class SymlinkBoundaryTests(ConfigurationErrorAssertions):
    def test_event_journal_symlink_is_rejected_without_writing_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            initialized = run_cli(adapter, "init")
            self.assertEqual(initialized.returncode, 0, _stderr(initialized))

            journal = campaign_path(adapter) / "events.jsonl"
            original = journal.read_bytes()
            outside = base / "outside-events.jsonl"
            outside.write_bytes(original)
            journal.unlink()
            journal.symlink_to(outside)

            completed = run_cli(adapter, "run")

            self.assert_configuration_error(completed)
            self.assertTrue(journal.is_symlink())
            self.assertEqual(original, outside.read_bytes())

    def test_attempts_symlink_is_rejected_before_external_directory_creation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            initialized = run_cli(adapter, "init")
            self.assertEqual(initialized.returncode, 0, _stderr(initialized))

            root = campaign_path(adapter)
            journal = root / "events.jsonl"
            original = journal.read_bytes()
            attempts = root / "attempts"
            attempts.rmdir()
            outside = base / "outside-attempts"
            outside.mkdir()
            _symlink_directory(attempts, outside)

            completed = run_cli(adapter, "run")

            self.assert_configuration_error(completed)
            self.assertEqual([], list(outside.iterdir()))
            self.assertEqual(original, journal.read_bytes())

    def test_campaign_lock_symlink_is_rejected_by_read_only_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            initialized = run_cli(adapter, "init")
            self.assertEqual(initialized.returncode, 0, _stderr(initialized))

            root = campaign_path(adapter)
            lock = root / "campaign.lock"
            original = lock.read_bytes()
            outside = base / "outside-campaign.lock"
            outside.write_bytes(original)
            lock.unlink()
            lock.symlink_to(outside)

            for command in ("status", "audit"):
                with self.subTest(command=command):
                    completed = run_cli(adapter, command)
                    self.assert_configuration_error(completed)
                    self.assertEqual(original, outside.read_bytes())

    def test_adapter_path_rejects_a_symlinked_parent_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            alias = base / "adapter-alias"
            _symlink_directory(alias, project)

            self.assert_configuration_error(run_cli(alias / adapter.name, "init"))

    def test_project_root_rejects_a_symlinked_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "real-project"
            original = make_adapter(project, [make_case("smoke", "smoke")])
            alias = base / "project-alias"
            _symlink_directory(alias, project)
            config = base / "config"
            config.mkdir()
            adapter_data = read_json(original)
            adapter_data["projectRoot"] = "../project-alias"
            adapter = write_json(config / "adapter.json", adapter_data)

            self.assert_configuration_error(run_cli(adapter, "init"))

    def test_campaign_root_rejects_a_symlinked_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / "campaign-target"
            target.mkdir()
            alias = project / "campaign-alias"
            _symlink_directory(alias, target)
            adapter = make_adapter(
                project,
                [make_case("smoke", "smoke")],
                campaign_root="campaign-alias/state",
            )
            data = read_json(adapter)
            data["source"]["excludes"] = [
                "campaign-alias/state",
                "campaign-target/state",
            ]
            write_json(adapter, data)

            self.assert_configuration_error(run_cli(adapter, "init"))

    def test_case_cwd_rejects_a_symlinked_component_at_init(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / "work-target"
            target.mkdir()
            alias = project / "work-alias"
            _symlink_directory(alias, target)
            case = make_case("smoke", "smoke")
            case["cwd"] = "work-alias"
            adapter = make_adapter(project, [case])

            self.assert_configuration_error(run_cli(adapter, "init"))

    def test_case_cwd_retarget_after_init_is_rejected_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            work = project / "work"
            work.mkdir()
            attacker = project / "retargeted-work"
            attacker.mkdir()
            case = make_case(
                "smoke",
                "smoke",
                argv=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('ran.txt').write_text('ran', encoding='utf-8')",
                ),
                required_files=(),
                non_empty_files=(),
            )
            case["cwd"] = "work"
            adapter = make_adapter(project, [case])
            initialized = run_cli(adapter, "init")
            self.assertEqual(initialized.returncode, 0, _stderr(initialized))

            work.rename(project / "original-work")
            _symlink_directory(work, attacker)
            completed = run_cli(adapter, "run")

            self.assertFalse(
                (attacker / "ran.txt").exists(),
                _stderr(completed) or completed.stdout,
            )
            self.assert_configuration_error(completed)

    def test_fixture_rejects_a_symlinked_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / "fixture-target"
            target.mkdir()
            (target / "fixture.json").write_text("{}\n", encoding="utf-8")
            alias = project / "fixture-alias"
            _symlink_directory(alias, target)
            case = make_case("smoke", "smoke")
            case["fixture"] = "fixture-alias/fixture.json"
            adapter = make_adapter(project, [case])

            self.assert_configuration_error(run_cli(adapter, "init"))

    def test_source_manifest_rejects_a_symlinked_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            target = project / "manifest-target"
            target.mkdir()
            (project / "source-manifest.json").replace(
                target / "source-manifest.json"
            )
            alias = project / "manifest-alias"
            _symlink_directory(alias, target)
            data = read_json(adapter)
            data["source"]["manifest"] = "manifest-alias/source-manifest.json"
            write_json(adapter, data)

            self.assert_configuration_error(run_cli(adapter, "init"))

    def test_source_file_rejects_a_symlinked_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            target = project / "source-target"
            target.mkdir()
            (target / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            alias = project / "source-alias"
            _symlink_directory(alias, target)
            _replace_source(
                adapter,
                {
                    "provider": "files",
                    "files": ["source-alias/module.py"],
                    "excludes": [".campaign"],
                },
            )

            self.assert_configuration_error(run_cli(adapter, "init"))


class AdapterSchemaTests(ConfigurationErrorAssertions):
    def test_every_provider_rejects_an_empty_effective_source_inventory(self) -> None:
        providers = ("files", "manifest", "git") if GIT is not None else (
            "files",
            "manifest",
        )
        for provider in providers:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary)
                adapter = make_adapter(project, [make_case("smoke", "smoke")])
                if provider == "files":
                    source = {
                        "provider": "files",
                        "files": ["source.txt"],
                        "excludes": [".campaign", "source.txt"],
                    }
                elif provider == "manifest":
                    source = {
                        "provider": "manifest",
                        "manifest": "source-manifest.json",
                        "excludes": [".campaign", "source.txt"],
                    }
                else:
                    subprocess.run(
                        [str(GIT), "-C", str(project), "init", "-q"],
                        check=True,
                    )
                    source = {
                        "provider": "git",
                        "excludes": [
                            ".campaign",
                            "adapter.json",
                            "source.txt",
                            "source-manifest.json",
                        ],
                    }
                _replace_source(adapter, source)
                rejected = run_cli(adapter, "init")
                self.assert_configuration_error(rejected)
                self.assertIn("source inventory is empty", rejected.stderr)

    def test_manifest_control_file_cannot_be_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            _replace_source(
                adapter,
                {
                    "provider": "manifest",
                    "manifest": "source-manifest.json",
                    "excludes": [".campaign", "source-manifest.json"],
                },
            )
            rejected = run_cli(adapter, "init")
            self.assert_configuration_error(rejected)
            self.assertIn("cannot be excluded", rejected.stderr)

    def test_schema_version_rejects_boolean_and_float_aliases_for_one(self) -> None:
        for invalid in (True, 1.0):
            with self.subTest(value=invalid), tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary)
                adapter = make_adapter(project, [make_case("smoke", "smoke")])
                data = read_json(adapter)
                data["schemaVersion"] = invalid
                write_json(adapter, data)

                self.assert_configuration_error(run_cli(adapter, "init"))

    def test_unhashable_provider_and_category_are_structured_errors(self) -> None:
        for field in ("provider", "category"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary)
                adapter = make_adapter(project, [make_case("smoke", "smoke")])
                data = read_json(adapter)
                if field == "provider":
                    data["source"]["provider"] = ["manifest"]
                else:
                    data["cases"][0]["category"] = ["smoke"]
                write_json(adapter, data)

                self.assert_configuration_error(run_cli(adapter, "init"))

    def test_provider_specific_irrelevant_keys_are_rejected(self) -> None:
        mutations: Sequence[tuple[str, Mapping[str, Any]]] = (
            (
                "git-manifest",
                {
                    "provider": "git",
                    "manifest": "source-manifest.json",
                    "excludes": [".campaign"],
                },
            ),
            (
                "git-files",
                {
                    "provider": "git",
                    "files": ["source.txt"],
                    "excludes": [".campaign"],
                },
            ),
            (
                "files-manifest",
                {
                    "provider": "files",
                    "files": ["source.txt"],
                    "manifest": "source-manifest.json",
                    "excludes": [".campaign"],
                },
            ),
            (
                "manifest-files",
                {
                    "provider": "manifest",
                    "manifest": "source-manifest.json",
                    "files": ["source.txt"],
                    "excludes": [".campaign"],
                },
            ),
        )
        for label, source in mutations:
            with self.subTest(source=label), tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary)
                adapter = make_adapter(project, [make_case("smoke", "smoke")])
                _replace_source(adapter, source)

                self.assert_configuration_error(run_cli(adapter, "init"))

    def test_existing_regular_file_campaign_root_is_a_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            (project / ".campaign").write_text("not a directory\n", encoding="utf-8")

            self.assert_configuration_error(run_cli(adapter, "init"))

    def test_git_provider_without_git_executable_is_a_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            _replace_source(adapter, {"provider": "git", "excludes": [".campaign"]})

            self.assert_configuration_error(
                run_cli(adapter, "init", env={"PATH": ""})
            )

    @unittest.skipUnless(os.name == "posix", "POSIX executable modes are required")
    def test_git_provider_with_unusable_git_path_is_a_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            _replace_source(adapter, {"provider": "git", "excludes": [".campaign"]})
            binaries = base / "bin"
            binaries.mkdir()
            unusable_git = binaries / "git"
            unusable_git.write_text("not executable\n", encoding="utf-8")
            unusable_git.chmod(0o600)

            self.assert_configuration_error(
                run_cli(adapter, "init", env={"PATH": str(binaries)})
            )

    @unittest.skipUnless(GIT is not None, "git is unavailable")
    def test_git_provider_outside_a_worktree_is_a_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            _replace_source(adapter, {"provider": "git", "excludes": [".campaign"]})

            self.assert_configuration_error(run_cli(adapter, "init"))


@unittest.skipUnless(os.name == "posix" and hasattr(os, "mkfifo"), "special files require POSIX")
class SpecialFileReadSafetyTests(ConfigurationErrorAssertions):
    def assert_fails_quickly(
        self,
        adapter: Path,
        command: str,
        *args: str,
    ) -> subprocess.CompletedProcess[str]:
        started = time.monotonic()
        completed = run_cli(adapter, command, *args, timeout=3)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.5, f"special-file read blocked for {elapsed:.2f}s")
        self.assert_configuration_error(completed)
        return completed

    def test_fifo_source_and_fix_document_fail_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            fifo = project / "input.fifo"
            os.mkfifo(fifo)
            _replace_source(
                adapter,
                {
                    "provider": "files",
                    "files": [fifo.name],
                    "excludes": [".campaign"],
                },
            )
            source_failure = self.assert_fails_quickly(adapter, "init")
            self.assertIn("regular", source_failure.stderr.lower())

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            run_cli(adapter, "init", expected=0)
            fifo = project / "fix.fifo"
            os.mkfifo(fifo)
            fix_failure = self.assert_fails_quickly(
                adapter, "record-fix", "--fix", str(fifo)
            )
            self.assertIn("regular", fix_failure.stderr.lower())

    @unittest.skipUnless(
        Path("/dev/null").exists(), "the platform has no standard character device"
    )
    def test_device_fix_document_fails_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            run_cli(adapter, "init", expected=0)
            failure = self.assert_fails_quickly(
                adapter, "record-fix", "--fix", "/dev/null"
            )
            self.assertRegex(failure.stderr.lower(), r"regular|symlink|reparse")

    def test_oversized_sparse_adapter_and_fix_are_rejected_quickly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            oversized_adapter = root / "oversized-adapter.json"
            oversized_adapter.touch()
            with oversized_adapter.open("r+b") as handle:
                handle.truncate(17 * 1024 * 1024)
            adapter_failure = self.assert_fails_quickly(
                oversized_adapter, "init"
            )
            self.assertIn("safe size limit", adapter_failure.stderr.lower())

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = make_adapter(root, [make_case("smoke", "smoke")])
            run_cli(adapter, "init", expected=0)
            oversized_fix = root / "oversized-fix.json"
            oversized_fix.touch()
            with oversized_fix.open("r+b") as handle:
                handle.truncate(17 * 1024 * 1024)
            fix_failure = self.assert_fails_quickly(
                adapter, "record-fix", "--fix", str(oversized_fix)
            )
            self.assertIn("safe size limit", fix_failure.stderr.lower())


class BoundedInventoryTests(unittest.TestCase):
    def test_internal_command_output_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                adapter_runtime.AdapterError, "exceeds the safe size limit"
            ):
                adapter_runtime.run_internal(
                    [
                        sys.executable,
                        "-c",
                        "import sys; sys.stdout.buffer.write(b'x' * 4096)",
                    ],
                    Path(temporary),
                    stdout_limit=1024,
                )

    @unittest.skipUnless(GIT is not None, "git is unavailable")
    def test_git_inventory_entry_count_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            subprocess.run(
                [str(GIT), "-C", str(project), "init", "-q"], check=True
            )
            _replace_source(
                adapter, {"provider": "git", "excludes": [".campaign"]}
            )
            with mock.patch.object(adapter_runtime, "MAX_SOURCE_ENTRIES", 1):
                with self.assertRaisesRegex(
                    adapter_runtime.AdapterError, "entry limit"
                ):
                    adapter_runtime.validate_adapter(adapter)


@unittest.skipUnless(GIT is not None, "git is unavailable")
class GitUnmergedIndexTests(ConfigurationErrorAssertions):
    def git(
        self,
        project: Path,
        *args: str,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        completed = subprocess.run(
            [str(GIT), "-C", str(project), *args],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr.decode("utf-8", "backslashreplace"),
        )
        return completed

    def hash_blob(self, project: Path, content: bytes) -> str:
        completed = self.git(
            project, "hash-object", "-w", "--stdin", input_bytes=content
        )
        return completed.stdout.decode("ascii").strip()

    def write_unmerged_entries(
        self, project: Path, path: str, stage_oids: Sequence[str]
    ) -> None:
        records = b"".join(
            f"100644 {oid} {stage}\t{path}".encode("utf-8") + b"\0"
            for stage, oid in enumerate(stage_oids, 1)
        )
        self.git(project, "update-index", "-z", "--index-info", input_bytes=records)

    def test_git_observation_uses_one_index_and_path_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter_path = make_adapter(project, [make_case("smoke", "smoke")])
            self.git(project, "init", "-q")
            old_oid = self.hash_blob(project, b"old gitlink target\n")
            new_oid = self.hash_blob(project, b"new gitlink target\n")
            self.git(
                project,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{old_oid},deps/old",
            )
            tabbed_path = "untracked\tname.txt"
            (project / tabbed_path).write_text("tabbed path\n", encoding="utf-8")
            _replace_source(
                adapter_path, {"provider": "git", "excludes": [".campaign"]}
            )
            adapter = adapter_runtime.validate_adapter(adapter_path)

            original_run_internal = adapter_runtime.run_internal
            listing_calls = 0

            def mutate_after_listing(
                args: Sequence[str],
                cwd: Path,
                **kwargs: Any,
            ) -> subprocess.CompletedProcess[bytes]:
                nonlocal listing_calls
                completed = original_run_internal(args, cwd, **kwargs)
                if "ls-files" in args:
                    listing_calls += 1
                    if listing_calls == 1:
                        self.git(
                            project,
                            "update-index",
                            "--force-remove",
                            "deps/old",
                        )
                        self.git(
                            project,
                            "update-index",
                            "--add",
                            "--cacheinfo",
                            f"160000,{new_oid},deps/new",
                        )
                return completed

            with mock.patch.object(
                adapter_runtime,
                "run_internal",
                side_effect=mutate_after_listing,
            ):
                observation = adapter_runtime.observe_source(adapter)

            self.assertEqual(1, listing_calls)
            self.assertIn(tabbed_path, observation["projectPaths"])
            gitlinks = {
                entry["path"]: entry["oid"]
                for entry in observation["files"]
                if entry.get("status") == "gitlink"
            }
            self.assertEqual({"deps/old": old_oid}, gitlinks)
            self.assertNotIn("deps/new", observation["projectPaths"])

    def test_unmerged_stage_oids_are_all_bound_or_init_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = make_adapter(project, [make_case("smoke", "smoke")])
            self.git(project, "init", "-q")
            conflict = project / "conflict.txt"
            conflict.write_text("stable working tree\n", encoding="utf-8")
            baseline = tuple(
                self.hash_blob(project, f"baseline-stage-{stage}\n".encode("ascii"))
                for stage in range(1, 4)
            )
            replacements = tuple(
                self.hash_blob(project, f"changed-stage-{stage}\n".encode("ascii"))
                for stage in range(1, 4)
            )
            self.write_unmerged_entries(project, conflict.name, baseline)
            _replace_source(adapter, {"provider": "git", "excludes": [".campaign"]})

            initialized = run_cli(adapter, "init")
            if initialized.returncode == 2:
                self.assert_configuration_error(initialized)
                self.assertRegex(_stderr(initialized).lower(), r"unmerged|unresolved|stage|index")
                return
            self.assertEqual(initialized.returncode, 0, _stderr(initialized))
            initial_summary = json.loads(initialized.stdout)
            initial_fingerprint = initial_summary["currentSourceFingerprint"]

            for changed_stage in range(3):
                with self.subTest(stage=changed_stage + 1):
                    changed = list(baseline)
                    changed[changed_stage] = replacements[changed_stage]
                    self.write_unmerged_entries(project, conflict.name, changed)
                    completed = run_cli(adapter, "status")
                    self.assertEqual(completed.returncode, 0, _stderr(completed))
                    status = json.loads(completed.stdout)
                    self.assertTrue(status["sourceDriftFromRecorded"], status)
                    self.assertNotEqual(
                        initial_fingerprint,
                        status["currentObservedSourceFingerprint"],
                    )


if __name__ == "__main__":
    unittest.main()
