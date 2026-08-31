from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import make_project, mutate_adapter
except ImportError:
    from helpers import make_project, mutate_adapter  # type: ignore

from adapter_paths import source_snapshot_changed_entries, validate_adapter
from model import AdapterError


class AdapterV2Tests(unittest.TestCase):
    def test_source_delta_classifies_every_supported_change_kind(self) -> None:
        before = {
            "files": [
                {
                    "path": "deleted.txt",
                    "status": "present",
                    "sha256": "old",
                    "executable": False,
                },
                {
                    "path": "mode.txt",
                    "status": "present",
                    "sha256": "same",
                    "executable": False,
                },
                {
                    "path": "modified.txt",
                    "status": "present",
                    "sha256": "old",
                    "executable": False,
                },
            ]
        }
        after = {
            "files": [
                {
                    "path": "added.txt",
                    "status": "present",
                    "sha256": "new",
                    "executable": False,
                },
                {
                    "path": "mode.txt",
                    "status": "present",
                    "sha256": "same",
                    "executable": True,
                },
                {
                    "path": "modified.txt",
                    "status": "present",
                    "sha256": "new",
                    "executable": False,
                },
            ]
        }

        self.assertEqual(
            [
                {"path": "added.txt", "change": "added"},
                {"path": "deleted.txt", "change": "deleted"},
                {"path": "mode.txt", "change": "mode-only"},
                {"path": "modified.txt", "change": "modified"},
            ],
            source_snapshot_changed_entries(before, after),
        )

    def test_goal_only_adapter_maps_every_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(
                Path(temporary) / "project",
                criteria="(C1) 第一项通过；(C2) 第二项由同一命令证明",
            )
            mutate_adapter(
                path,
                lambda value: value["cases"][0].update(
                    {"coversCriteria": ["C1", "C2"]}
                ),
            )
            adapter = validate_adapter(path)
            self.assertEqual(2, adapter.data["schemaVersion"])
            self.assertEqual({"C1", "C2"}, adapter.goal_criteria_ids)
            self.assertEqual(
                [
                    {"id": "C1", "requiredCaseIds": ["acceptance"]},
                    {"id": "C2", "requiredCaseIds": ["acceptance"]},
                ],
                adapter.criteria_configuration(),
            )

    def test_unsupported_shapes_are_rejected(self) -> None:
        cases = [
            (lambda value: value.update({"schemaVersion": 1}), "schemaVersion must be 2"),
            (lambda value: value.update({"projectRoot": "."}), "projectRoot must be .."),
            (lambda value: value["source"].update({"excludes": []}), "must contain .steward"),
            (lambda value: value["cases"][0].update({"required": False}), "required-case coverage"),
            (lambda value: value["cases"][0].update({"coversCriteria": ["C2"]}), "unknown GOAL criterion"),
            (lambda value: value["cases"][0].update({"coversCriteria": ["C1", "C1"]}), "duplicate values"),
            (lambda value: value.update({"extra": True}), "invalid fields"),
        ]
        for index, (mutator, message) in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                path = make_project(Path(temporary) / "project")
                mutate_adapter(path, mutator)
                with self.assertRaisesRegex(AdapterError, message):
                    validate_adapter(path)

    def test_adapter_path_and_control_paths_are_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            copied = path.parent / "other.json"
            copied.write_bytes(path.read_bytes())
            with self.assertRaisesRegex(AdapterError, "adapter path must"):
                validate_adapter(copied)

    def test_goal_digest_drift_can_only_be_observed_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = make_project(Path(temporary) / "project")
            goal = path.parent / "goal.txt"
            goal.write_text(
                goal.read_text(encoding="utf-8").replace("当前测试项目", "其他项目"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(AdapterError, "GOAL_CONTRACT_DRIFT"):
                validate_adapter(path)
            observed = validate_adapter(path, observe_goal_drift=True)
            self.assertEqual(["GOAL_CONTRACT_DRIFT"], observed.goal_errors)

    def test_symlink_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            path = make_project(root)
            target = root / "real.txt"
            target.write_text("content\n", encoding="utf-8")
            (root / "app.txt").unlink()
            (root / "app.txt").symlink_to(target)
            with self.assertRaisesRegex(AdapterError, "symlink"):
                validate_adapter(path)

    def test_source_inventory_requires_present_non_control_project_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "files-project"
            path = make_project(root)
            (root / "app.txt").unlink()
            with self.assertRaisesRegex(AdapterError, "non-control project source"):
                validate_adapter(path)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "manifest-project"
            path = make_project(root)
            manifest = root / "source-manifest.json"
            manifest.write_text("[]\n", encoding="utf-8")

            def use_empty_manifest(value: dict) -> None:
                value["source"] = {
                    "provider": "manifest",
                    "manifest": "source-manifest.json",
                    "excludes": [".steward"],
                }

            mutate_adapter(path, use_empty_manifest)
            with self.assertRaisesRegex(AdapterError, "must declare project source"):
                validate_adapter(path)


if __name__ == "__main__":
    unittest.main()
