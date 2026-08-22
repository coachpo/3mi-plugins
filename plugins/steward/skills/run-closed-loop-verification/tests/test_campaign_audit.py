"""Black-box audit coverage for the closed-loop campaign CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

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
        write_json,
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
        write_json,
    )


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import audit as audit_runtime  # noqa: E402
import runner_evidence as runner_runtime  # noqa: E402


_CATEGORIES = ("smoke", "functional", "integration", "workflow", "role-play")


def _passing_script() -> str:
    return (
        "import os, sys\n"
        "from pathlib import Path\n"
        "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
        "(evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n"
        "print('known stdout')\n"
        "print('known stderr', file=sys.stderr)\n"
    )


def _passing_cases() -> list[dict[str, object]]:
    return [
        make_case(
            f"{category}-case",
            category,
            argv=(sys.executable, "-c", _passing_script()),
        )
        for category in _CATEGORIES
    ]


class CampaignAuditTests(unittest.TestCase):
    maxDiff = None

    def _complete_campaign(self, root: Path) -> tuple[Path, Path]:
        adapter = make_adapter(root, _passing_cases())
        json_output(run_cli(adapter, "init", expected=0))
        initial = json_output(run_cli(adapter, "run", expected=0))
        self.assertEqual(initial["status"], "READY_FOR_REGRESSION")
        regression = json_output(
            run_cli(adapter, "run", "--mode", "regression", expected=0)
        )
        self.assertEqual(regression["status"], "COMPLETE")
        report = json_output(run_cli(adapter, "audit", expected=0))
        self.assertTrue(report["ok"], report)

        state = load_state(adapter)
        final_id = state["finalRegressionAttemptId"]
        final_attempt = next(
            attempt for attempt in state["attempts"] if attempt["id"] == final_id
        )
        case_run = final_attempt["caseRuns"][0]
        artifact = campaign_path(adapter) / case_run["artifactDir"]
        self.assertTrue((artifact / "result.json").is_file())
        self.assertTrue((artifact / "artifact-manifest.json").is_file())
        return adapter, artifact

    def _assert_audit_rejects(self, adapter: Path, expected_fragment: str = "") -> None:
        completed = run_cli(adapter, "audit", expected=1)
        self.assertNotIn("Traceback", completed.stderr)
        report = json_output(completed)
        self.assertFalse(report["ok"], report)
        errors = "\n".join(report.get("errors", [])).lower()
        if expected_fragment:
            self.assertIn(expected_fragment.lower(), errors, report)

    def _assert_audit_rejects_unexpected_object(self, adapter: Path) -> None:
        completed = run_cli(adapter, "audit", expected=1)
        self.assertNotIn("Traceback", completed.stderr)
        report = json_output(completed)
        self.assertFalse(report["ok"], report)
        errors = "\n".join(report.get("errors", [])).lower()
        self.assertRegex(errors, r"\b(?:unexpected|extra|untracked|undeclared|orphan)\b")

    def test_audit_rejects_tampered_bound_files(self) -> None:
        mutations = {
            "stdout": lambda artifact: (artifact / "stdout.txt").write_text(
                "tampered stdout\n", encoding="utf-8"
            ),
            "stderr": lambda artifact: (artifact / "stderr.txt").write_text(
                "tampered stderr\n", encoding="utf-8"
            ),
            "evidence": lambda artifact: (artifact / "proof.json").write_text(
                '{"ok":false}\n', encoding="utf-8"
            ),
            "result": self._tamper_result,
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                adapter, artifact = self._complete_campaign(Path(temporary))
                mutate(artifact)
                self._assert_audit_rejects(adapter, name)

    @staticmethod
    def _tamper_result(artifact: Path) -> None:
        result_path = artifact / "result.json"
        result = read_json(result_path)
        result["durationMs"] = int(result.get("durationMs", 0)) + 1
        write_json(result_path, result)

    def test_audit_rejects_missing_and_unexpected_artifacts(self) -> None:
        mutations = {
            "missing": lambda artifact: (artifact / "stderr.txt").unlink(),
            "unexpected": lambda artifact: (artifact / "unexpected.bin").write_bytes(
                b"not in the artifact manifest"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                adapter, artifact = self._complete_campaign(Path(temporary))
                mutate(artifact)
                self._assert_audit_rejects(adapter)

    def test_audit_rejects_unexpected_campaign_layout_objects(self) -> None:
        def campaign_root_file(adapter: Path, _artifact: Path) -> None:
            (campaign_path(adapter) / "unexpected.txt").write_text(
                "not owned by the campaign\n", encoding="utf-8"
            )

        def attempt_root_file(adapter: Path, artifact: Path) -> None:
            (artifact.parent.parent / "unexpected.txt").write_text(
                "not owned by the attempt\n", encoding="utf-8"
            )

        def orphan_attempt(adapter: Path, _artifact: Path) -> None:
            (campaign_path(adapter) / "attempts" / "orphan-attempt").mkdir()

        def orphan_case(_adapter: Path, artifact: Path) -> None:
            (artifact.parent / "orphan-case").mkdir()

        mutations = {
            "campaign root extra file": campaign_root_file,
            "attempt root extra file": attempt_root_file,
            "attempts orphan directory": orphan_attempt,
            "attempt cases orphan directory": orphan_case,
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                adapter, artifact = self._complete_campaign(Path(temporary))
                mutate(adapter, artifact)
                self._assert_audit_rejects_unexpected_object(adapter)

    def test_audit_rejects_missing_expected_case_artifact_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter, artifact = self._complete_campaign(Path(temporary))
            artifact.rename(adapter.parent / "removed-case-artifact")
            self._assert_audit_rejects(adapter, "missing")

    def test_audit_rejects_evidence_symlink(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symbolic links are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            adapter, artifact = self._complete_campaign(Path(temporary))
            evidence = artifact / "proof.json"
            evidence.unlink()
            try:
                evidence.symlink_to(adapter.parent / "source.txt")
            except OSError as exc:
                self.skipTest(f"symbolic links cannot be created: {exc}")
            self._assert_audit_rejects(adapter, "symlink")

    def test_audit_rejects_case_artifact_directory_symlink(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symbolic links are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            adapter, artifact = self._complete_campaign(Path(temporary))
            renamed = artifact.with_name(artifact.name + "-renamed")
            artifact.rename(renamed)
            try:
                artifact.symlink_to(renamed.name, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links cannot be created: {exc}")
            self._assert_audit_rejects(adapter, "symlink")

    def test_audit_rejects_added_directory_symlink_inside_artifact(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symbolic links are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            adapter, artifact = self._complete_campaign(Path(temporary))
            target = adapter.parent / "directory-link-target"
            target.mkdir()
            added_link = artifact / "added-directory-link"
            try:
                added_link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links cannot be created: {exc}")
            self._assert_audit_rejects(adapter, "symlink")

    def test_audit_rejects_malformed_result_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter, artifact = self._complete_campaign(Path(temporary))
            (artifact / "result.json").write_text("{not-json\n", encoding="utf-8")
            self._assert_audit_rejects(adapter, "result")

    def test_audit_rejects_malformed_journal_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter, _ = self._complete_campaign(Path(temporary))
            events = campaign_path(adapter) / "events.jsonl"
            with events.open("a", encoding="utf-8") as handle:
                handle.write("{not-json\n")
            completed = run_cli(adapter, "audit", expected=2)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertIn("journal", (completed.stdout + completed.stderr).lower())

    def test_audit_rejects_projection_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter, _ = self._complete_campaign(Path(temporary))
            state_path = campaign_path(adapter) / "state.json"
            state = read_json(state_path)
            state["status"] = "FAILED"
            write_json(state_path, state)
            self._assert_audit_rejects(adapter, "state")

    def test_historical_failed_missing_evidence_can_complete(self) -> None:
        conditional_script = (
            "import os, sys\n"
            "from pathlib import Path\n"
            "if Path('mode.txt').read_text(encoding='utf-8').strip() == 'pass':\n"
            "    evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            "    (evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n"
            "print('conditional case', file=sys.stdout)\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = _passing_cases()
            cases[0] = make_case(
                "smoke-case",
                "smoke",
                argv=(sys.executable, "-c", conditional_script),
            )
            adapter = make_adapter(root, cases)
            (root / "mode.txt").write_text("fail\n", encoding="utf-8")

            json_output(run_cli(adapter, "init", expected=0))
            failed = json_output(run_cli(adapter, "run", expected=1))
            self.assertEqual(failed["status"], "FAILED")
            failed_artifact = campaign_path(adapter) / failed["cases"]["smoke-case"][
                "artifactDir"
            ]
            self.assertFalse((failed_artifact / "proof.json").exists())

            (root / "mode.txt").write_text("pass\n", encoding="utf-8")
            fix = write_fix_for_latest_failure(adapter)
            json_output(
                run_cli(adapter, "record-fix", "--fix", str(fix), expected=0)
            )
            retested = json_output(run_cli(adapter, "retest", expected=0))
            self.assertEqual(retested["status"], "READY_FOR_REGRESSION")
            completed = json_output(
                run_cli(adapter, "run", "--mode", "regression", expected=0)
            )
            self.assertEqual(completed["status"], "COMPLETE")
            report = json_output(run_cli(adapter, "audit", expected=0))
            self.assertTrue(report["ok"], report)

    def test_schema_one_journal_has_clear_legacy_diagnostic(self) -> None:
        for command in ("status", "audit"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                adapter = make_adapter(root, _passing_cases())
                campaign = campaign_path(adapter)
                campaign.mkdir()
                (campaign / "events.jsonl").write_text(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "seq": 1,
                            "type": "campaign_initialized",
                            "payload": {},
                            "prevHash": "0" * 64,
                            "hash": "sha256:" + "0" * 64,
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                completed = run_cli(adapter, command, expected=2)
                diagnostic = (completed.stdout + completed.stderr).lower()
                self.assertNotIn("traceback", diagnostic)
                self.assertIn("legacy", diagnostic)
                self.assertIn("new campaign root", diagnostic)


class WindowsReparseAuditTests(unittest.TestCase):
    def test_regular_artifact_reader_rejects_windows_reparse_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact.json"
            path.write_text("{}", encoding="utf-8")
            metadata = path.lstat()
            reparse_flag = 0x400
            reparse_metadata = SimpleNamespace(
                st_mode=metadata.st_mode,
                st_size=metadata.st_size,
                st_dev=metadata.st_dev,
                st_ino=metadata.st_ino,
                st_file_attributes=reparse_flag,
            )
            with mock.patch.object(
                audit_runtime.stat,
                "FILE_ATTRIBUTE_REPARSE_POINT",
                reparse_flag,
                create=True,
            ), mock.patch.object(Path, "lstat", return_value=reparse_metadata):
                with self.assertRaisesRegex(
                    audit_runtime.CampaignError, "reparse"
                ):
                    audit_runtime.stream_regular_file(path)

    def test_artifact_scan_does_not_descend_into_windows_reparse_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "artifact"
            junction = artifact / "junction"
            junction.mkdir(parents=True)
            nested = junction / "outside.txt"
            nested.write_text("must not be traversed", encoding="utf-8")
            junction_inode = junction.lstat().st_ino

            def is_reparse(metadata: os.stat_result) -> bool:
                return metadata.st_ino == junction_inode

            with mock.patch.object(
                runner_runtime,
                "artifact_metadata_is_reparse",
                side_effect=is_reparse,
            ):
                entries = runner_runtime.artifact_tree_entries(artifact)
                observed = {
                    path.relative_to(artifact).as_posix() for path, _ in entries
                }
                self.assertIn("junction", observed)
                self.assertNotIn("junction/outside.txt", observed)
                with self.assertRaisesRegex(
                    runner_runtime.CampaignError, "reparse"
                ):
                    runner_runtime.scan_artifact_text_files(
                        artifact, redact_files=False
                    )


if __name__ == "__main__":
    unittest.main()
