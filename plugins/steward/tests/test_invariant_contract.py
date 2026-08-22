from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import architecture_profiles
import invariant_contract
from architecture_profiles import compile_selection, load_package, select_profiles
from invariant_contract import (
    InvariantContractError,
    aggregate_applicability,
    invariant_map_canonical_bytes,
    invariant_map_sha256,
    invariant_map_view,
    load_invariant_map,
    router_rows,
    validate_project_references,
)

INV_ID = "INV-PROJECT-0123456789AB"


class FakeProfilePackage:
    def __init__(self, version: str, digest: str) -> None:
        self.profiles = {
            "python": {
                "profileVersion": version,
                "invariants": [{"id": "INV-PYTHON-0123456789AB", "level": "must"}],
            }
        }
        self._digest = digest

    def profile_digest(self, profile_id: str) -> str:
        self.assert_profile(profile_id)
        return self._digest

    def assert_profile(self, profile_id: str) -> None:
        if profile_id not in self.profiles:
            raise AssertionError(profile_id)


class InvariantContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / ".steward").mkdir()
        (self.root / "docs").mkdir()
        self.authority = self.root / "docs" / "architecture.md"
        self.evidence = self.root / "tests" / "test_architecture.py"
        self.evidence.parent.mkdir()
        self.evidence.write_text("# evidence\n", encoding="utf-8")
        self.write_authority("# Architecture\n\n<a id=\"inv-project-0123456789ab\"></a>\nRule.\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_authority(self, text: str) -> str:
        self.authority.write_text(text, encoding="utf-8")
        return "sha256:" + hashlib.sha256(self.authority.read_bytes()).hexdigest()

    def binding(self, **changes):
        value = {
            "invariantId": INV_ID,
            "source": {
                "kind": "project",
                "version": "1",
                "digest": "sha256:" + hashlib.sha256(self.authority.read_bytes()).hexdigest(),
            },
            "scopes": ["."],
            "trigger": "changing module boundaries",
            "authority": {
                "path": "docs/architecture.md",
                "anchor": "inv-project-0123456789ab",
            },
            "applicability": "applicable",
            "status": "direct",
            "evidence": ["tests/test_architecture.py"],
            "enforcement": {
                "kind": "mechanical",
                "evidence": ["tests/test_architecture.py"],
                "validationEntry": "`python3 -m unittest`",
            },
        }
        value.update(changes)
        return value

    def write_map(self, bindings=None) -> Path:
        path = self.root / ".steward" / "invariants.json"
        value = {
            "schemaVersion": 1,
            "bindings": [self.binding()] if bindings is None else bindings,
        }
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def write_map_document(self, value) -> Path:
        path = self.root / ".steward" / "invariants.json"
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def test_loads_project_binding_and_derives_router_contract(self) -> None:
        invariant_map = load_invariant_map(self.write_map())
        self.assertEqual(invariant_map.hard_invariant_ids, (INV_ID,))
        self.assertEqual(invariant_map.triggered_hard_invariant_ids, (INV_ID,))
        self.assertEqual(
            tuple(
                (instance.invariant_id, instance.scope, instance.applicability)
                for instance in invariant_map.triggered_hard_invariant_instances
            ),
            ((INV_ID, ".", "applicable"),),
        )
        self.assertRegex(invariant_map.invariant_map_sha256, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            invariant_map.invariant_map_sha256,
            "sha256:32389872f34327561e58fb413b8cc5010ba4d3b71c25335a85e089af1782f5fc",
        )
        self.assertEqual(
            validate_project_references(
                self.root,
                invariant_map,
                allowed_authorities={"docs/architecture.md"},
            ),
            [],
        )
        row = router_rows(invariant_map)[0]
        self.assertIn("changing module boundaries", row)
        self.assertIn(INV_ID, row)
        self.assertIn("python3 -m unittest", row)
        self.assertEqual(
            invariant_map.invariant_map_sha256,
            invariant_map_sha256(invariant_map),
        )
        self.assertEqual(invariant_map_view(invariant_map)["schemaVersion"], 1)
        self.assertNotIn(b"\n", invariant_map_canonical_bytes(invariant_map))

    def test_digest_is_independent_of_path_and_json_layout(self) -> None:
        first_path = self.write_map()
        first = load_invariant_map(first_path)
        second_path = self.root / "other.json"
        second_path.write_text(
            json.dumps(
                {"bindings": [self.binding()], "schemaVersion": 1},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        second = load_invariant_map(second_path)
        self.assertEqual(first.invariant_map_sha256, second.invariant_map_sha256)
        self.assertEqual(
            invariant_map_canonical_bytes(first),
            invariant_map_canonical_bytes(second),
        )

    def test_not_applicable_binding_is_not_triggered(self) -> None:
        binding = self.binding(
            applicability="not_applicable",
            status="not_applicable",
            notApplicableReason="scope has no runtime code",
            enforcement={"kind": "manual", "evidence": []},
        )
        invariant_map = load_invariant_map(self.write_map([binding]))
        self.assertEqual(invariant_map.hard_invariant_ids, (INV_ID,))
        self.assertEqual(invariant_map.triggered_hard_invariant_ids, ())
        self.assertEqual(router_rows(invariant_map), ())

        binding["evidence"] = []
        with self.assertRaisesRegex(InvariantContractError, "capability or scope"):
            load_invariant_map(self.write_map([binding]))

    def test_applicability_aggregation_is_conservative(self) -> None:
        self.assertEqual(
            aggregate_applicability(["applicable", "not_applicable"]),
            "applicable",
        )
        self.assertEqual(
            aggregate_applicability(["unverified", "not_applicable"]),
            "unverified",
        )
        self.assertEqual(
            aggregate_applicability(["not_applicable", "not_applicable"]),
            "not_applicable",
        )
        with self.assertRaisesRegex(InvariantContractError, "requires scopes"):
            aggregate_applicability([])

    def test_rejects_duplicate_json_keys_and_duplicate_ids(self) -> None:
        path = self.write_map()
        path.write_text(
            '{"schemaVersion":1,"schemaVersion":1,"bindings":[]}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(InvariantContractError, "duplicate key"):
            load_invariant_map(path)
        with self.assertRaisesRegex(InvariantContractError, "duplicate invariant"):
            load_invariant_map(self.write_map([self.binding(), self.binding()]))

    def test_rejects_empty_index_instead_of_rendering_an_empty_router(self) -> None:
        with self.assertRaisesRegex(InvariantContractError, "non-empty"):
            load_invariant_map(self.write_map([]))

    def test_map_reader_is_bounded(self) -> None:
        path = self.write_map()
        with mock.patch(
            "invariant_contract.MAX_INVARIANT_MAP_BYTES", 64
        ), self.assertRaisesRegex(InvariantContractError, "size limit"):
            load_invariant_map(path)

    def test_map_reader_rejects_symlink_fifo_and_open_race(self) -> None:
        map_path = self.write_map()
        real_map = self.root / "real-invariants.json"
        map_path.replace(real_map)
        map_path.symlink_to(real_map)
        with self.assertRaisesRegex(InvariantContractError, "regular, non-symlink"):
            load_invariant_map(map_path)
        map_path.unlink()

        device = Path(os.devnull)
        if device.exists():
            with self.assertRaisesRegex(
                InvariantContractError, "regular, non-symlink"
            ):
                load_invariant_map(device)

        if hasattr(os, "mkfifo"):
            os.mkfifo(map_path)
            with self.assertRaisesRegex(
                InvariantContractError, "regular, non-symlink"
            ):
                load_invariant_map(map_path)
            map_path.unlink()

        map_path = self.write_map()
        original = map_path.read_bytes()
        replacement = map_path.with_name("replacement.json")
        real_open = os.open
        observed_flags = []

        def replace_before_open(path, flags):
            observed_flags.append(flags)
            replacement.write_bytes(original)
            os.replace(replacement, map_path)
            return real_open(path, flags)

        with mock.patch(
            "invariant_contract.os.open", side_effect=replace_before_open
        ), self.assertRaisesRegex(InvariantContractError, "changed between"):
            load_invariant_map(map_path)
        if hasattr(os, "O_NONBLOCK"):
            self.assertTrue(observed_flags[0] & os.O_NONBLOCK)
        if hasattr(os, "O_NOFOLLOW"):
            self.assertTrue(observed_flags[0] & os.O_NOFOLLOW)

    def test_profile_selection_reader_is_bounded_and_nofollow(self) -> None:
        path = self.root / ".steward" / "selection.json"
        value = {"schemaVersion": 1, "components": []}
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")
        self.assertEqual(
            value,
            invariant_contract._read_profile_selection_json(
                architecture_profiles, path
            ),
        )
        with mock.patch.object(
            architecture_profiles, "MAX_JSON_BYTES", 8
        ), self.assertRaisesRegex(InvariantContractError, "size limit"):
            invariant_contract._read_profile_selection_json(
                architecture_profiles, path
            )

        real_path = path.with_name("real-selection.json")
        path.replace(real_path)
        path.symlink_to(real_path)
        with self.assertRaisesRegex(InvariantContractError, "regular, non-symlink"):
            invariant_contract._read_profile_selection_json(
                architecture_profiles, path
            )

    def test_rejects_mechanical_claim_without_validation(self) -> None:
        binding = self.binding(
            enforcement={
                "kind": "mechanical",
                "evidence": ["tests/test_architecture.py"],
            }
        )
        with self.assertRaisesRegex(InvariantContractError, "mechanical"):
            load_invariant_map(self.write_map([binding]))

    def test_rejects_invalid_equivalent_and_not_applicable_states(self) -> None:
        with self.assertRaisesRegex(InvariantContractError, "equivalentControl"):
            load_invariant_map(self.write_map([self.binding(status="equivalent")]))
        with self.assertRaisesRegex(InvariantContractError, "not_applicable"):
            load_invariant_map(
                self.write_map([self.binding(applicability="not_applicable")])
            )

    def test_reports_missing_anchor_evidence_and_project_digest_drift(self) -> None:
        invariant_map = load_invariant_map(self.write_map())
        self.write_authority("# Architecture\n")
        self.evidence.unlink()
        errors = validate_project_references(self.root, invariant_map)
        self.assertTrue(any("anchor" in error for error in errors))
        self.assertTrue(any("digest" in error for error in errors))
        self.assertTrue(any("evidence target" in error for error in errors))

    def test_project_reference_reads_reject_symlink_fifo_and_oversize(self) -> None:
        invariant_map = load_invariant_map(self.write_map())
        real_authority = self.authority.with_name("real-architecture.md")
        self.authority.replace(real_authority)
        self.authority.symlink_to(real_authority)
        errors = validate_project_references(self.root, invariant_map)
        self.assertTrue(any("canonical authority is missing" in error for error in errors))
        self.authority.unlink()
        real_authority.replace(self.authority)

        if hasattr(os, "mkfifo"):
            self.evidence.unlink()
            os.mkfifo(self.evidence)
            errors = validate_project_references(self.root, invariant_map)
            self.assertTrue(any("evidence target is missing" in error for error in errors))
            self.evidence.unlink()

        self.evidence.write_text(
            '<a id="proof"></a>\n' + "x" * 1024,
            encoding="utf-8",
        )
        binding = self.binding(
            evidence=["tests/test_architecture.py#proof"],
            enforcement={
                "kind": "manual",
                "evidence": ["tests/test_architecture.py#proof"],
            },
        )
        anchored_map = load_invariant_map(self.write_map([binding]))
        with mock.patch(
            "invariant_contract.MAX_PROJECT_REFERENCE_BYTES", 128
        ):
            errors = validate_project_references(self.root, anchored_map)
        self.assertTrue(
            any("evidence target" in error and "size limit" in error for error in errors)
        )

        self.authority.write_text("x" * 1024, encoding="utf-8")
        with mock.patch(
            "invariant_contract.MAX_PROJECT_REFERENCE_BYTES", 128
        ):
            errors = validate_project_references(self.root, anchored_map)
        self.assertTrue(
            any(
                "canonical authority" in error and "size limit" in error
                for error in errors
            )
        )

    def test_ignores_authority_anchors_hidden_in_code_fences(self) -> None:
        self.write_authority(
            '# Architecture\n\n```html\n<a id="inv-project-0123456789ab"></a>\n```\n'
        )
        invariant_map = load_invariant_map(self.write_map())
        errors = validate_project_references(self.root, invariant_map)
        self.assertTrue(any("authority anchor" in error for error in errors))

    def test_evidence_fragment_must_resolve_to_one_explicit_anchor(self) -> None:
        binding = self.binding(
            evidence=["tests/test_architecture.py#proof"],
            enforcement={
                "kind": "manual",
                "evidence": ["tests/test_architecture.py#proof"],
            },
        )
        invariant_map = load_invariant_map(self.write_map([binding]))
        errors = validate_project_references(self.root, invariant_map)
        self.assertTrue(any("evidence anchor" in error for error in errors))
        self.evidence.write_text(
            '<a id="proof"></a>\n# evidence\n', encoding="utf-8"
        )
        self.assertEqual(validate_project_references(self.root, invariant_map), [])

    def test_validates_profile_pin_and_invariant_membership(self) -> None:
        digest = "sha256:" + "a" * 64
        version = "1.0.0"
        binding = self.binding(
            invariantId="INV-PYTHON-0123456789AB",
            source={
                "kind": "profile",
                "profileId": "python",
                "profileVersion": version,
                "profileDigest": digest,
            },
            authority={
                "path": "docs/architecture.md",
                "anchor": "inv-python-0123456789ab",
            },
        )
        package = FakeProfilePackage(version, digest)
        with mock.patch("architecture_profiles.load_package", return_value=package):
            invariant_map = load_invariant_map(self.write_map([binding]), self.root)
        self.assertEqual(
            invariant_map.triggered_hard_invariant_ids,
            ("INV-PYTHON-0123456789AB",),
        )

    def test_rejects_legacy_profile_version_format(self) -> None:
        binding = self.binding(
            source={
                "kind": "profile",
                "profileId": "python",
                "profileVersion": "2026.8.0+0123456789ab",
                "profileDigest": "sha256:" + "a" * 64,
            }
        )
        with self.assertRaisesRegex(
            InvariantContractError, "profileVersion is invalid"
        ):
            load_invariant_map(self.write_map([binding]))

    def test_loads_a_real_bundled_profile_reference(self) -> None:
        profiles_root = PLUGIN_ROOT / "references" / "architecture-profiles"
        package = load_package(profiles_root)
        profile = package.profiles["python"]
        invariant_id = profile["invariants"][0]["id"]
        self.authority.write_text(
            f'# Architecture\n\n<a id="{invariant_id.lower()}"></a>\nRule.\n',
            encoding="utf-8",
        )
        binding = self.binding(
            invariantId=invariant_id,
            source={
                "kind": "profile",
                "profileId": "python",
                "profileVersion": profile["profileVersion"],
                "profileDigest": package.profile_digest("python"),
            },
            authority={
                "path": "docs/architecture.md",
                "anchor": invariant_id.lower(),
            },
        )
        invariant_map = load_invariant_map(self.write_map([binding]), profiles_root)
        self.assertEqual(invariant_map.triggered_hard_invariant_ids, (invariant_id,))

    def test_profile_selection_preserves_django_and_fastapi_scope_states(self) -> None:
        profiles_root = PLUGIN_ROOT / "references" / "architecture-profiles"
        package = load_package(profiles_root)
        evidence = {
            "schemaVersion": 1,
            "components": [
                {
                    "scope": "services/django-a",
                    "signals": [
                        "dependency:django",
                        "entry:django",
                        "manifest:python",
                        "source:python",
                    ],
                    "capabilities": {"django.database": "present"},
                },
                {
                    "scope": "services/django-b",
                    "signals": [
                        "dependency:django",
                        "entry:django",
                        "manifest:python",
                        "source:python",
                    ],
                    "capabilities": {"django.database": "absent"},
                },
                {
                    "scope": "services/fastapi",
                    "signals": [
                        "dependency:fastapi",
                        "entry:asgi",
                        "manifest:python",
                        "source:python",
                    ],
                    "capabilities": {},
                },
            ],
        }
        selection = select_profiles(package, evidence)
        selection_path = self.root / ".steward" / "profile-selection.json"
        selection_path.write_text(
            json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        compiled = compile_selection(package, selection)
        bindings = []
        for invariant in compiled["invariants"]:
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
                "trigger": "changing selected architecture",
                "authority": {
                    "path": "docs/architecture.md",
                    "anchor": invariant["id"].lower(),
                },
                "applicability": applicability,
                "applicabilityByScope": scope_states,
                "status": (
                    "not_applicable"
                    if applicability == "not_applicable"
                    else "unverified"
                ),
                "evidence": [".steward/profile-selection.json"],
                "enforcement": {
                    "kind": "manual",
                    "evidence": [".steward/profile-selection.json"],
                },
            }
            if applicability == "not_applicable":
                binding["notApplicableReason"] = (
                    "Every compiled scope is technically not applicable"
                )
            bindings.append(binding)
        bindings.sort(key=lambda item: item["invariantId"])
        document = {
            "schemaVersion": 1,
            "profileSelection": {
                "path": ".steward/profile-selection.json",
                "digest": selection["contentDigest"],
            },
            "bindings": bindings,
        }
        map_path = self.write_map_document(document)
        invariant_map = load_invariant_map(map_path, profiles_root)
        self.assertEqual(
            invariant_map.profile_selection.digest,
            selection["contentDigest"],
        )
        profile_ids = {
            binding.source.profile_id
            for binding in invariant_map.bindings
            if hasattr(binding.source, "profile_id")
        }
        self.assertTrue({"django", "fastapi", "python"} <= profile_ids)

        future_selection = json.loads(json.dumps(selection))
        future_selection["schemaVersion"] = 2
        future_unsigned = dict(future_selection)
        future_unsigned.pop("contentDigest")
        future_selection["contentDigest"] = architecture_profiles.content_digest(
            future_unsigned
        )
        architecture_profiles.write_json(selection_path, future_selection)
        future_document = json.loads(json.dumps(document))
        future_document["profileSelection"]["digest"] = future_selection[
            "contentDigest"
        ]
        with self.assertRaisesRegex(
            InvariantContractError, "selection schemaVersion must be 1"
        ):
            load_invariant_map(
                self.write_map_document(future_document), profiles_root
            )
        architecture_profiles.write_json(selection_path, selection)
        map_path = self.write_map_document(document)

        alternate_path = self.root / "alternate-invariants.json"
        alternate_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(InvariantContractError, "explicit project_root"):
            load_invariant_map(alternate_path, profiles_root)
        alternate_map = load_invariant_map(
            alternate_path,
            profiles_root,
            project_root=self.root,
        )
        self.assertEqual(
            alternate_map.invariant_map_sha256,
            invariant_map.invariant_map_sha256,
        )

        mixed = next(
            binding
            for binding in invariant_map.bindings
            if binding.source.profile_id == "django"
            and {item.state for item in binding.applicability_by_scope}
            == {"applicable", "not_applicable"}
        )
        self.assertEqual(mixed.applicability, "applicable")
        self.assertEqual(mixed.triggered_scopes, ("services/django-a",))
        instances = {
            (instance.invariant_id, instance.scope)
            for instance in invariant_map.triggered_hard_invariant_instances
        }
        self.assertIn((mixed.invariant_id, "services/django-a"), instances)
        self.assertNotIn((mixed.invariant_id, "services/django-b"), instances)
        mixed_row = next(
            row for row in router_rows(invariant_map) if mixed.invariant_id in row
        )
        self.assertIn("services/django-a", mixed_row)
        self.assertNotIn("services/django-b", mixed_row)

        stale_digest = json.loads(json.dumps(document))
        stale_digest["profileSelection"]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(InvariantContractError, "contentDigest"):
            load_invariant_map(self.write_map_document(stale_digest), profiles_root)

        missing_binding = json.loads(json.dumps(document))
        missing_binding["bindings"].pop()
        with self.assertRaisesRegex(InvariantContractError, "missing"):
            load_invariant_map(self.write_map_document(missing_binding), profiles_root)

        tampered = json.loads(json.dumps(document))
        mixed_json = next(
            binding
            for binding in tampered["bindings"]
            if binding["invariantId"] == mixed.invariant_id
        )
        mixed_json["applicabilityByScope"][1]["state"] = "unverified"
        with self.assertRaisesRegex(InvariantContractError, "compiled selection"):
            load_invariant_map(self.write_map_document(tampered), profiles_root)

    def test_rejects_unsafe_paths_and_table_injection(self) -> None:
        with self.assertRaisesRegex(InvariantContractError, "relative path"):
            load_invariant_map(
                self.write_map([self.binding(scopes=["/absolute"])])
            )
        with self.assertRaisesRegex(InvariantContractError, "table"):
            load_invariant_map(
                self.write_map([self.binding(trigger="change | inject")])
            )
        with self.assertRaisesRegex(InvariantContractError, "one trimmed line"):
            load_invariant_map(
                self.write_map([self.binding(trigger="first\u2028second")])
            )


if __name__ == "__main__":
    unittest.main()
