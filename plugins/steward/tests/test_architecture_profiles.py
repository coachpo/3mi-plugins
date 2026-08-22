from __future__ import annotations

import copy
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PROFILES_ROOT = PLUGIN_ROOT / "references" / "architecture-profiles"
SCRIPT_PATH = PLUGIN_ROOT / "scripts" / "architecture_profiles.py"
SPEC = importlib.util.spec_from_file_location("architecture_profiles", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
architecture_profiles = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(architecture_profiles)


EXPECTED_IDS = [
    "android",
    "cloudflare-workers",
    "django",
    "fastapi",
    "golang",
    "python",
    "tauri-2",
]

EXPECTED_SPECS = {
    "android": ("standalone", []),
    "cloudflare-workers": ("standalone", []),
    "django": ("overlay", ["python"]),
    "fastapi": ("overlay", ["python"]),
    "golang": ("standalone", []),
    "python": ("base", []),
    "tauri-2": ("standalone", []),
}

DIRECT_SELECTIONS = {
    "android": (["manifest:android", "source:android"], ["android"]),
    "cloudflare-workers": (["config:wrangler"], ["cloudflare-workers"]),
    "django": (["dependency:django", "entry:django"], ["python", "django"]),
    "fastapi": (["dependency:fastapi", "entry:asgi"], ["python", "fastapi"]),
    "golang": (["manifest:go", "source:go"], ["golang"]),
    "python": (["manifest:python", "source:python"], ["python"]),
    "tauri-2": (["dependency:tauri2", "manifest:cargo"], ["tauri-2"]),
}


def evidence(signals, capabilities=None, scope="."):
    return {
        "schemaVersion": 1,
        "components": [
            {
                "scope": scope,
                "signals": sorted(signals),
                "capabilities": dict(sorted((capabilities or {}).items())),
            }
        ],
    }


def resign(artifact):
    unsigned = dict(artifact)
    unsigned.pop("contentDigest", None)
    artifact["contentDigest"] = architecture_profiles.content_digest(unsigned)


class ArchitectureProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = architecture_profiles.load_package(PROFILES_ROOT)

    def copied_package(self, temporary):
        target = Path(temporary) / "architecture-profiles"
        shutil.copytree(PROFILES_ROOT, target)
        return target

    def test_catalog_has_exact_seven_plugin_owned_profiles(self):
        package = self.package
        self.assertEqual(EXPECTED_IDS, list(package.profiles))
        self.assertEqual(EXPECTED_IDS, [item["id"] for item in package.catalog["profiles"]])
        self.assertEqual(architecture_profiles.CATALOG_SCHEMA_VERSION, package.catalog["schemaVersion"])
        self.assertFalse((PROFILES_ROOT / "sources.lock.json").exists())
        for profile_id, profile in package.profiles.items():
            expected_kind, expected_extends = EXPECTED_SPECS[profile_id]
            self.assertEqual(expected_kind, profile["kind"])
            self.assertEqual(expected_extends, profile["extends"])
            self.assertEqual(architecture_profiles.PROFILE_SCHEMA_VERSION, profile["schemaVersion"])
            self.assertEqual("1.0.0", profile["profileVersion"])
            self.assertNotIn("source", profile)
            for collection in ("invariants", "checks", "scenarios"):
                for item in profile[collection]:
                    self.assertNotIn("sourceRefs", item)
            catalog_entry = next(
                item for item in package.catalog["profiles"] if item["id"] == profile_id
            )
            self.assertEqual(package.profile_digest(profile_id), catalog_entry["digest"])
        cloudflare = package.profiles["cloudflare-workers"]
        self.assertEqual("CFWORKERS", cloudflare["invariantPrefix"])
        self.assertTrue(
            all(
                item["id"].startswith("INV-CFWORKERS-")
                for item in cloudflare["invariants"]
            )
        )
        for collection in ("checks", "scenarios"):
            self.assertTrue(
                all(
                    item["id"].startswith("cloudflare-workers.")
                    for item in cloudflare[collection]
                )
            )

    def test_selection_evidence_schema_and_activation_document_match_runtime(self):
        schema = architecture_profiles.read_json(
            PROFILES_ROOT / "selection-evidence-v1.schema.json",
            "selection evidence schema",
        )
        documentation = (PROFILES_ROOT / "selection-evidence.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            "https://json-schema.org/draft/2020-12/schema", schema["$schema"]
        )
        self.assertEqual(
            "steward.architecture-profile-selection-evidence.v1",
            schema["$id"],
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(["schemaVersion", "components"], schema["required"])
        self.assertEqual(
            {"schemaVersion", "components"}, set(schema["properties"])
        )
        self.assertEqual(
            architecture_profiles.EVIDENCE_SCHEMA_VERSION,
            schema["properties"]["schemaVersion"]["const"],
        )
        components = schema["properties"]["components"]
        self.assertEqual(1, components["minItems"])
        self.assertEqual(architecture_profiles.MAX_COMPONENTS, components["maxItems"])
        component = schema["$defs"]["component"]
        self.assertFalse(component["additionalProperties"])
        self.assertEqual(
            ["scope", "signals", "capabilities"], component["required"]
        )
        self.assertEqual(
            {"scope", "signals", "capabilities"}, set(component["properties"])
        )
        self.assertEqual(
            architecture_profiles.MAX_SIGNALS_PER_COMPONENT,
            component["properties"]["signals"]["maxItems"],
        )
        self.assertEqual(
            architecture_profiles.MAX_CAPABILITIES_PER_COMPONENT,
            component["properties"]["capabilities"]["maxProperties"],
        )
        self.assertEqual(
            architecture_profiles.TOKEN_RE.pattern,
            schema["$defs"]["token"]["pattern"],
        )
        self.assertEqual(
            list(architecture_profiles.CAPABILITY_STATES),
            component["properties"]["capabilities"]["additionalProperties"][
                "enum"
            ],
        )
        for profile in self.package.profiles.values():
            for clause in profile["selection"]["activation"]:
                for signal in clause["allOf"] + clause["anyOf"] + clause["noneOf"]:
                    self.assertIn("`" + signal + "`", documentation)

    def test_exact_profile_relationships_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copied_package(temporary)
            profile_path = root / "profiles" / "django.json"
            profile = architecture_profiles.read_json(profile_path, "django profile")
            profile["extends"] = ["fastapi"]
            architecture_profiles.write_json(profile_path, profile)
            catalog_path = root / "catalog.json"
            catalog = architecture_profiles.read_json(catalog_path, "catalog")
            entry = next(item for item in catalog["profiles"] if item["id"] == "django")
            entry["extends"] = ["fastapi"]
            entry["digest"] = architecture_profiles.content_digest(profile)
            architecture_profiles.write_json(catalog_path, catalog)
            with self.assertRaisesRegex(
                architecture_profiles.ProfileError, "relationship drift"
            ):
                architecture_profiles.load_package(root)

    def test_all_hard_ids_are_unique_and_content_derived(self):
        seen = set()
        prefixes = set()
        for profile in self.package.profiles.values():
            self.assertNotIn(profile["invariantPrefix"], prefixes)
            prefixes.add(profile["invariantPrefix"])
            for invariant in profile["invariants"]:
                self.assertEqual(
                    architecture_profiles.expected_invariant_id(profile, invariant),
                    invariant["id"],
                )
                self.assertNotIn(invariant["id"], seen)
                seen.add(invariant["id"])
        self.assertEqual(38, len(seen))

    def test_invariant_check_and_scenario_references_are_exactly_reciprocal(self):
        for collection, reference_field, target_collection in (
            ("checks", "checkRefs", "checks"),
            ("scenarios", "scenarioRefs", "scenarios"),
        ):
            with self.subTest(collection=collection):
                profile = copy.deepcopy(self.package.profiles["android"])
                invariant = profile["invariants"][0]
                target_id = next(
                    item["id"]
                    for item in profile[target_collection]
                    if item["id"] not in invariant[reference_field]
                )
                invariant[reference_field].append(target_id)
                invariant[reference_field].sort()
                with self.assertRaisesRegex(
                    architecture_profiles.ProfileError, "must reference each other"
                ):
                    architecture_profiles.validate_profile(profile, "android")

    def test_every_shipped_profile_selects_directly_and_deterministically(self):
        for profile_id, (signals, expected_refs) in DIRECT_SELECTIONS.items():
            with self.subTest(profile_id=profile_id):
                first = architecture_profiles.select_profiles(
                    self.package, evidence(signals, scope="components/" + profile_id)
                )
                second = architecture_profiles.select_profiles(
                    self.package,
                    evidence(list(reversed(signals)), scope="components/" + profile_id),
                )
                self.assertEqual(first, second)
                self.assertEqual(expected_refs, first["components"][0]["profileRefs"])
                self.assertEqual(expected_refs, [item["id"] for item in first["profiles"]])
                target = next(item for item in first["profiles"] if item["id"] == profile_id)
                self.assertEqual("matched", target["selection"])
                self.assertEqual(
                    self.package.profiles[profile_id]["selection"]["scope"],
                    target["selectionScope"],
                )
                self.assertEqual(["components/" + profile_id], target["scopes"])

    def test_overlay_composition_unions_base_scopes_without_rule_duplication(self):
        value = {
            "schemaVersion": 1,
            "components": [
                {
                    "scope": "services/api",
                    "signals": ["dependency:fastapi", "entry:asgi"],
                    "capabilities": {
                        "fastapi.cache": "present",
                        "python.multiprocessing": "unknown",
                    },
                },
                {
                    "scope": "services/admin",
                    "signals": ["dependency:django", "entry:django"],
                    "capabilities": {
                        "django.database": "present",
                        "python.multiprocessing": "absent",
                    },
                },
            ],
        }
        selected = architecture_profiles.select_profiles(self.package, value)
        self.assertEqual(
            ["services/admin", "services/api"],
            [item["scope"] for item in selected["components"]],
        )
        self.assertEqual(
            [["python", "django"], ["python", "fastapi"]],
            [item["profileRefs"] for item in selected["components"]],
        )
        self.assertEqual(
            ["python", "django", "fastapi"],
            [item["id"] for item in selected["profiles"]],
        )
        by_profile = {item["id"]: item for item in selected["profiles"]}
        self.assertEqual("extended", by_profile["python"]["selection"])
        self.assertEqual("component", by_profile["python"]["selectionScope"])
        self.assertEqual(
            ["services/admin", "services/api"], by_profile["python"]["scopes"]
        )
        self.assertEqual(["services/admin"], by_profile["django"]["scopes"])
        self.assertEqual(["services/api"], by_profile["fastapi"]["scopes"])

        first = architecture_profiles.compile_selection(self.package, selected)
        second = architecture_profiles.compile_selection(
            self.package, copy.deepcopy(selected)
        )
        self.assertEqual(first, second)
        self.assertEqual(
            architecture_profiles.canonical_bytes(first),
            architecture_profiles.canonical_bytes(second),
        )
        unsigned = dict(first)
        digest = unsigned.pop("contentDigest")
        self.assertEqual(architecture_profiles.content_digest(unsigned), digest)
        serialized = architecture_profiles.canonical_bytes(first).decode("utf-8")
        self.assertNotIn(str(PROFILES_ROOT), serialized)
        self.assertNotIn("generatedAt", serialized)
        self.assertNotIn("timestamp", serialized)

        invariant_ids = [item["id"] for item in first["invariants"]]
        self.assertEqual(len(invariant_ids), len(set(invariant_ids)))
        self.assertEqual(
            sum(
                len(self.package.profiles[item]["invariants"])
                for item in ["python", "django", "fastapi"]
            ),
            len(invariant_ids),
        )
        self.assertEqual(
            len(self.package.profiles["python"]["invariants"]),
            sum(item["profileId"] == "python" for item in first["invariants"]),
        )
        expected_scopes = {
            "python": ["services/admin", "services/api"],
            "django": ["services/admin"],
            "fastapi": ["services/api"],
        }
        for collection in ("invariants", "checks", "scenarios"):
            for rule in first[collection]:
                self.assertEqual(expected_scopes[rule["profileId"]], rule["scopes"])
                applicability_scopes = [
                    item["scope"] for item in rule["applicabilityByScope"]
                ]
                self.assertEqual(rule["scopes"], applicability_scopes)
                self.assertEqual(sorted(applicability_scopes), applicability_scopes)

    def test_selector_requires_the_complete_activation_clause(self):
        partial = architecture_profiles.select_profiles(
            self.package, evidence(["dependency:django"])
        )
        self.assertEqual([], partial["components"][0]["profileRefs"])
        self.assertEqual([], partial["profiles"])
        complete = architecture_profiles.select_profiles(
            self.package, evidence(["dependency:django", "entry:django"])
        )
        self.assertEqual(
            ["python", "django"], complete["components"][0]["profileRefs"]
        )

    def test_selection_is_sorted_digest_bound_and_deterministic(self):
        value = {
            "schemaVersion": 1,
            "components": [
                evidence(["manifest:go", "source:go"], scope="services/z")["components"][0],
                evidence(["manifest:android", "source:android"], scope="apps/a")["components"][0],
            ],
        }
        first = architecture_profiles.select_profiles(self.package, value)
        second = architecture_profiles.select_profiles(self.package, copy.deepcopy(value))
        self.assertEqual(first, second)
        self.assertEqual(
            ["apps/a", "services/z"],
            [item["scope"] for item in first["components"]],
        )
        unsigned = dict(first)
        digest = unsigned.pop("contentDigest")
        self.assertEqual(architecture_profiles.content_digest(unsigned), digest)
        serialized = architecture_profiles.canonical_bytes(first).decode("utf-8")
        self.assertNotIn(str(PROFILES_ROOT), serialized)
        self.assertNotIn("generatedAt", serialized)
        self.assertNotIn("timestamp", serialized)

    def test_ambiguous_inherited_overlay_scope_is_rejected(self):
        profiles = copy.deepcopy(self.package.profiles)
        child = copy.deepcopy(profiles["django"])
        child["id"] = "child-overlay"
        child["invariantPrefix"] = "CHILD"
        child["extends"] = ["django"]
        child["selection"]["activation"] = [
            {"allOf": ["dependency:child-overlay"], "anyOf": [], "noneOf": []}
        ]
        profiles["child-overlay"] = child
        package = architecture_profiles.ProfilePackage(
            self.package.root,
            self.package.catalog,
            profiles,
        )
        components = [
            {
                "scope": "services/child",
                "signals": ["dependency:child-overlay"],
                "capabilities": {},
            }
        ]
        with self.assertRaisesRegex(
            architecture_profiles.ProfileError, "overlay selection has no matched.*scope"
        ):
            architecture_profiles.aggregate_profile_bindings(package, components)

    def test_tri_state_condition_semantics_fail_safe(self):
        evaluate = architecture_profiles.evaluate_condition
        empty = {"allOf": [], "anyOf": [], "noneOf": []}
        self.assertEqual("applicable", evaluate(empty, {}))
        required = {"allOf": ["x"], "anyOf": [], "noneOf": []}
        self.assertEqual("applicable", evaluate(required, {"x": "present"}))
        self.assertEqual("not_applicable", evaluate(required, {"x": "absent"}))
        self.assertEqual("unverified", evaluate(required, {"x": "unknown"}))
        self.assertEqual("unverified", evaluate(required, {}))
        either = {"allOf": [], "anyOf": ["x", "y"], "noneOf": []}
        self.assertEqual("applicable", evaluate(either, {"x": "present", "y": "unknown"}))
        self.assertEqual("not_applicable", evaluate(either, {"x": "absent", "y": "absent"}))
        self.assertEqual("unverified", evaluate(either, {"x": "absent", "y": "unknown"}))
        excluded = {"allOf": [], "anyOf": [], "noneOf": ["x"]}
        self.assertEqual("not_applicable", evaluate(excluded, {"x": "present"}))
        self.assertEqual("applicable", evaluate(excluded, {"x": "absent"}))
        self.assertEqual("unverified", evaluate(excluded, {}))
        with self.assertRaisesRegex(
            architecture_profiles.ProfileError, "requires and excludes"
        ):
            architecture_profiles.validate_condition(
                {"allOf": ["x"], "anyOf": [], "noneOf": ["x"]},
                "condition",
            )

    def test_single_line_strings_reject_all_unicode_line_separators(self):
        for separator in ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
            with self.subTest(codepoint=ord(separator)), self.assertRaisesRegex(
                architecture_profiles.ProfileError, "single line"
            ):
                architecture_profiles.require_string(
                    "before" + separator + "after", "value"
                )

    def test_android_target_projects_to_actual_campaign_host_and_platform_tag(self):
        self.assertIn("android", architecture_profiles.PLATFORMS)
        self.assertNotIn("android", architecture_profiles.CAMPAIGN_HOST_PLATFORMS)
        for host in sorted(architecture_profiles.CAMPAIGN_HOST_PLATFORMS):
            with self.subTest(host=host):
                self.assertEqual(
                    (host, ("platform",)),
                    architecture_profiles.campaign_platform_projection(
                        "android", host
                    ),
                )
        self.assertEqual(
            ("linux", ()),
            architecture_profiles.campaign_platform_projection("linux", "linux"),
        )
        with self.assertRaisesRegex(
            architecture_profiles.ProfileError, "campaign host platform is unsupported"
        ):
            architecture_profiles.campaign_platform_projection("android", "android")

    def test_compile_carries_scoped_tri_state_applicability(self):
        selected = architecture_profiles.select_profiles(
            self.package,
            evidence(
                ["dependency:fastapi", "entry:asgi"],
                {
                    "fastapi.async": "present",
                    "fastapi.cache": "absent",
                    "fastapi.database": "absent",
                    "fastapi.durable-jobs": "absent",
                    "fastapi.openapi": "absent",
                    "fastapi.remote-io": "absent",
                    "fastapi.streaming": "unknown",
                    "python.multiprocessing": "unknown",
                },
                "services/api",
            ),
        )
        compiled = architecture_profiles.compile_selection(self.package, selected)
        by_outcome = {item["outcome"]: item for item in compiled["invariants"]}
        lifecycle = next(
            item
            for outcome, item in by_outcome.items()
            if outcome.startswith("Actual lifespan hooks")
        )
        consistency = next(
            item
            for outcome, item in by_outcome.items()
            if outcome.startswith("Every adopted transaction")
        )
        process = next(
            item
            for outcome, item in by_outcome.items()
            if outcome.startswith("Process creation and worker sizing")
        )
        self.assertEqual("applicable", lifecycle["applicabilityByScope"][0]["state"])
        self.assertEqual("applicable", consistency["applicabilityByScope"][0]["state"])
        self.assertEqual("unverified", process["applicabilityByScope"][0]["state"])
        retry = next(item for item in compiled["scenarios"] if item["id"] == "fastapi.retry-boundary")
        openapi = next(item for item in compiled["checks"] if item["id"] == "fastapi.openapi")
        self.assertEqual("not_applicable", retry["applicabilityByScope"][0]["state"])
        self.assertEqual("not_applicable", openapi["applicabilityByScope"][0]["state"])
        for item in compiled["invariants"]:
            self.assertEqual(
                self.package.profile_digest(item["profileId"]), item["profileDigest"]
            )
            self.assertEqual(
                self.package.profiles[item["profileId"]]["profileVersion"],
                item["profileVersion"],
            )

    def test_compilation_never_executes_check_templates(self):
        selected = architecture_profiles.select_profiles(
            self.package, evidence(["manifest:go", "source:go"])
        )
        self.assertFalse(hasattr(architecture_profiles, "subprocess"))
        compiled = architecture_profiles.compile_selection(self.package, selected)
        self.assertTrue(compiled["checks"])

    def test_tampered_selection_scope_bindings_are_rejected(self):
        mutations = {
            "selection": lambda value: value["profiles"][0].__setitem__(
                "selection", "matched"
            ),
            "selectionScope": lambda value: value["profiles"][0].__setitem__(
                "selectionScope", "repository"
            ),
            "scopes": lambda value: value["profiles"][0].__setitem__(
                "scopes", ["services/other"]
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                selected = architecture_profiles.select_profiles(
                    self.package,
                    evidence(
                        ["dependency:django", "entry:django"],
                        scope="services/admin",
                    ),
                )
                mutate(selected)
                resign(selected)
                with self.assertRaisesRegex(
                    architecture_profiles.ProfileError,
                    "selectionScope differs|deterministic scoped bindings",
                ):
                    architecture_profiles.validate_selection(self.package, selected)

    def test_component_signal_and_capability_limits_bound_amplification(self):
        two_components = {
            "schemaVersion": 1,
            "components": [
                evidence(["a"], scope="a")["components"][0],
                evidence(["b"], scope="b")["components"][0],
            ],
        }
        with mock.patch.object(
            architecture_profiles, "MAX_COMPONENTS", 1
        ), self.assertRaisesRegex(
            architecture_profiles.ProfileError, "component limit"
        ):
            architecture_profiles.validate_evidence(two_components)
        with mock.patch.object(
            architecture_profiles, "MAX_SIGNALS_PER_COMPONENT", 1
        ), self.assertRaisesRegex(
            architecture_profiles.ProfileError, "signals exceeds"
        ):
            architecture_profiles.validate_evidence(evidence(["a", "b"]))
        with mock.patch.object(
            architecture_profiles, "MAX_CAPABILITIES_PER_COMPONENT", 1
        ), self.assertRaisesRegex(
            architecture_profiles.ProfileError, "capabilities exceeds"
        ):
            architecture_profiles.validate_evidence(
                evidence([], {"a": "present", "b": "unknown"})
            )

    def test_check_and_scenario_references_and_proof_limits_are_closed(self):
        for profile in self.package.profiles.values():
            invariants = {item["id"]: item for item in profile["invariants"]}
            checks = {item["id"]: item for item in profile["checks"]}
            scenarios = {item["id"]: item for item in profile["scenarios"]}
            for invariant in invariants.values():
                self.assertTrue(invariant["equivalenceCriteria"])
                self.assertTrue(invariant["checkRefs"] or invariant["scenarioRefs"])
                self.assertLessEqual(set(invariant["checkRefs"]), set(checks))
                self.assertLessEqual(set(invariant["scenarioRefs"]), set(scenarios))
            for check in checks.values():
                self.assertTrue(check["proves"])
                self.assertTrue(check["doesNotProve"])
                self.assertFalse(set(check["proves"]) & set(check["doesNotProve"]))
                self.assertLessEqual(set(check["invariantRefs"]), set(invariants))
                for invariant_id in check["invariantRefs"]:
                    self.assertIn(check["id"], invariants[invariant_id]["checkRefs"])
            for scenario in scenarios.values():
                self.assertLessEqual(set(scenario["invariantRefs"]), set(invariants))
                for invariant_id in scenario["invariantRefs"]:
                    self.assertIn(
                        scenario["id"], invariants[invariant_id]["scenarioRefs"]
                    )

    def test_v1_profiles_reject_removed_upstream_fields(self):
        profile = copy.deepcopy(self.package.profiles["android"])
        profile["source"] = {"repository": "https://example.invalid/source.git"}
        with self.assertRaisesRegex(
            architecture_profiles.ProfileError, "unknown fields: source"
        ):
            architecture_profiles.validate_profile(profile, "android")

        profile = copy.deepcopy(self.package.profiles["android"])
        profile["invariants"][0]["sourceRefs"] = [{"section": "legacy"}]
        with self.assertRaisesRegex(
            architecture_profiles.ProfileError, "unknown fields: sourceRefs"
        ):
            architecture_profiles.validate_profile(profile, "android")

        self.assertFalse(hasattr(architecture_profiles, "verify_upstream"))
        self.assertFalse(hasattr(architecture_profiles, "run_git"))

    def test_v2_selection_is_rejected_by_v1_compiler(self):
        selection = architecture_profiles.select_profiles(
            self.package,
            evidence(["manifest:python", "source:python"]),
        )
        self.assertEqual(
            architecture_profiles.SELECTION_SCHEMA_VERSION,
            selection["schemaVersion"],
        )
        selection["schemaVersion"] = 2
        with self.assertRaisesRegex(
            architecture_profiles.ProfileError, "selection schemaVersion must be 1"
        ):
            architecture_profiles.validate_selection(self.package, selection)

    def test_profile_content_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copied_package(temporary)
            path = root / "profiles" / "android.json"
            profile = architecture_profiles.read_json(path, "android profile")
            profile["baseline"]["versionPolicy"] += " Changed."
            architecture_profiles.write_json(path, profile)
            with self.assertRaisesRegex(
                architecture_profiles.ProfileError, "catalog digest drift"
            ):
                architecture_profiles.load_package(root)

    def test_unknown_fields_duplicate_keys_and_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copied_package(temporary)
            path = root / "catalog.json"
            catalog = architecture_profiles.read_json(path, "catalog")
            catalog["unexpected"] = True
            architecture_profiles.write_json(path, catalog)
            with self.assertRaisesRegex(architecture_profiles.ProfileError, "unknown fields"):
                architecture_profiles.load_package(root)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"schemaVersion":1,"schemaVersion":1}\n', encoding="utf-8")
            with self.assertRaisesRegex(architecture_profiles.ProfileError, "duplicate key"):
                architecture_profiles.read_json(path, "duplicate")

        with tempfile.TemporaryDirectory() as temporary:
            root = self.copied_package(temporary)
            path = root / "catalog.json"
            catalog = architecture_profiles.read_json(path, "catalog")
            catalog["profiles"][0]["path"] = "profiles/../profiles/android.json"
            architecture_profiles.write_json(path, catalog)
            with self.assertRaisesRegex(architecture_profiles.ProfileError, "traversal"):
                architecture_profiles.load_package(root)

    def test_symlinked_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copied_package(temporary)
            catalog_path = root / "catalog.json"
            catalog = architecture_profiles.read_json(catalog_path, "catalog")
            catalog["profiles"][0]["path"] = "profiles/android-link.json"
            architecture_profiles.write_json(catalog_path, catalog)
            os.symlink(
                PROFILES_ROOT / "profiles" / "android.json",
                root / "profiles" / "android-link.json",
            )
            with self.assertRaisesRegex(
                architecture_profiles.ProfileError, "symlink|escapes"
            ):
                architecture_profiles.load_package(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = self.copied_package(temporary)
            catalog_path = root / "catalog.json"
            catalog = architecture_profiles.read_json(catalog_path, "catalog")
            catalog["profiles"][0]["path"] = "profile-link/android.json"
            architecture_profiles.write_json(catalog_path, catalog)
            os.symlink(root / "profiles", root / "profile-link")
            with self.assertRaisesRegex(architecture_profiles.ProfileError, "symlink"):
                architecture_profiles.load_package(root)

    def test_cli_json_input_requires_lf_size_bound_and_one_trailing_newline(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_bytes(b"{}\r\n")
            with self.assertRaisesRegex(
                architecture_profiles.ProfileError, "exactly one trailing newline"
            ):
                architecture_profiles.read_json(path, "bad input")

    def test_json_reader_rejects_symlink_fifo_and_open_race(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "input.json"
            real_path = root / "real.json"
            real_path.write_bytes(b"{}\n")
            path.symlink_to(real_path)
            with self.assertRaisesRegex(
                architecture_profiles.ProfileError, "regular, non-symlink"
            ):
                architecture_profiles.read_json(path, "input")
            path.unlink()

            device = Path(os.devnull)
            if device.exists():
                with self.assertRaisesRegex(
                    architecture_profiles.ProfileError, "regular, non-symlink"
                ):
                    architecture_profiles.read_json(device, "input")

            if hasattr(os, "mkfifo"):
                os.mkfifo(path)
                with self.assertRaisesRegex(
                    architecture_profiles.ProfileError, "regular, non-symlink"
                ):
                    architecture_profiles.read_json(path, "input")
                path.unlink()

            path.write_bytes(b"{}\n")
            replacement = root / "replacement.json"
            real_open = os.open
            observed_flags = []

            def replace_before_open(target, flags):
                observed_flags.append(flags)
                replacement.write_bytes(b"{}\n")
                os.replace(replacement, path)
                return real_open(target, flags)

            with mock.patch.object(
                architecture_profiles.os,
                "open",
                side_effect=replace_before_open,
            ), self.assertRaisesRegex(
                architecture_profiles.ProfileError, "changed between"
            ):
                architecture_profiles.read_json(path, "input")
            if hasattr(os, "O_NONBLOCK"):
                self.assertTrue(observed_flags[0] & os.O_NONBLOCK)
            if hasattr(os, "O_NOFOLLOW"):
                self.assertTrue(observed_flags[0] & os.O_NOFOLLOW)

            with mock.patch.object(architecture_profiles, "MAX_JSON_BYTES", 4):
                path.write_bytes(b'{"x":1}\n')
                with self.assertRaisesRegex(
                    architecture_profiles.ProfileError, "JSON size limit"
                ):
                    architecture_profiles.read_json(path, "bad input")
            path.write_bytes(b"{}\n\n")
            with self.assertRaisesRegex(
                architecture_profiles.ProfileError, "exactly one trailing newline"
            ):
                architecture_profiles.read_json(path, "bad input")
            path.write_bytes(b"{} \n")
            with self.assertRaisesRegex(
                architecture_profiles.ProfileError, "exactly one trailing newline"
            ):
                architecture_profiles.read_json(path, "bad input")

    def test_cli_select_and_compile_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_path = root / "evidence.json"
            selection_path = root / "selection.json"
            compiled_path = root / "compiled.json"
            architecture_profiles.write_json(
                evidence_path,
                evidence(["dependency:fastapi", "entry:asgi"], scope="services/api"),
            )
            self.assertEqual(
                0,
                architecture_profiles.main(
                    [
                        "--profiles-root",
                        str(PROFILES_ROOT),
                        "select",
                        "--evidence",
                        str(evidence_path),
                        "--output",
                        str(selection_path),
                    ]
                ),
            )
            self.assertEqual(
                0,
                architecture_profiles.main(
                    [
                        "--profiles-root",
                        str(PROFILES_ROOT),
                        "compile",
                        "--selection",
                        str(selection_path),
                        "--output",
                        str(compiled_path),
                    ]
                ),
            )
            compiled = architecture_profiles.read_json(compiled_path, "compiled output")
            self.assertEqual(
                architecture_profiles.COMPILED_SCHEMA_VERSION,
                compiled["schemaVersion"],
            )
            self.assertEqual("1.0.0", compiled["compilerVersion"])
            self.assertEqual("services/api", compiled["components"][0]["scope"])
            self.assertEqual(
                ["python", "fastapi"], [item["id"] for item in compiled["profiles"]]
            )
            self.assertEqual(
                ["python", "fastapi"], compiled["components"][0]["profileRefs"]
            )


if __name__ == "__main__":
    unittest.main()
