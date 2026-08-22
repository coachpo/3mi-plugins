"""Strict cross-platform bundle and aggregation contracts."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .helpers import json_output, make_case, read_json, run_cli, write_json
except ImportError:
    from helpers import (  # type: ignore
        json_output,
        make_case,
        read_json,
        run_cli,
        write_json,
    )


SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = PLUGIN_ROOT / "references" / "project-verification"

import platform_evidence
from model import CampaignError


def digest(character: str) -> str:
    return "sha256:" + character * 64


BINDINGS = {
    "profileFingerprint": digest("1"),
    "verificationCatalogFingerprint": digest("2"),
    "ciPlanFingerprint": digest("3"),
}


def entry(
    entry_id: str,
    platform: str,
    case_id: str,
    *,
    kind: str = "platform",
    shard_index: int = 1,
    shard_count: int = 1,
) -> dict[str, object]:
    return {
        "id": entry_id,
        "kind": kind,
        "platform": platform,
        "shardIndex": shard_index,
        "shardCount": shard_count,
        "caseIds": [case_id],
    }


def plan(*entries: dict[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "projectId": "fixture",
        "profileSha256": BINDINGS["profileFingerprint"],
        "verificationCatalogFingerprint": BINDINGS[
            "verificationCatalogFingerprint"
        ],
        "requiredPlatforms": ["linux", "windows"],
        "entries": list(entries),
        "contentDigest": digest("4"),
    }


def bundle(value: dict[str, object]) -> dict[str, object]:
    case_id = value["caseIds"][0]  # type: ignore[index]
    execution_source = digest("8")
    result: dict[str, object] = {
        "schemaVersion": 1,
        "kind": platform_evidence.BUNDLE_KIND,
        "binding": {
            "commit": "a" * 40,
            "sourceFingerprint": digest("5"),
            **BINDINGS,
            "campaignCatalogFingerprint": digest("7"),
            "executionSourceFingerprint": execution_source,
        },
        "entry": copy.deepcopy(value),
        "campaign": {
            "id": "campaign-fixture",
            "runtimePlatform": value["platform"],
            "finalRegressionAttemptId": "attempt-0002-regression",
        },
        "cases": [
            {
                "id": case_id,
                "round": "regression",
                "status": "PASS",
                "runId": "run-" + str(case_id),
                "sourceFingerprintBefore": execution_source,
                "sourceFingerprintAfter": execution_source,
                "artifactDir": "attempts/final/cases/" + str(case_id),
                "artifactManifest": {
                    "relativePath": "attempts/final/cases/"
                    + str(case_id)
                    + "/artifact-manifest.json",
                    "size": 10,
                    "sha256": digest("9"),
                },
                "evidence": {
                    "requiredFiles": ["proof.json"],
                    "nonEmptyFiles": ["proof.json"],
                    "missingFiles": [],
                    "emptyFiles": [],
                    "files": [
                        {"path": "proof.json", "size": 2, "sha256": digest("b")}
                    ],
                    "secretLikeContent": False,
                },
            }
        ],
    }
    result["bundleFingerprint"] = platform_evidence._bundle_fingerprint(result)
    return result


def rebind(value: dict[str, object]) -> None:
    value["bundleFingerprint"] = platform_evidence._bundle_fingerprint(value)


class PlatformEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.linux_entry = entry("linux-01-of-01", "linux", "linux-case")
        self.windows_entry = entry(
            "windows-01-of-01", "windows", "windows-case"
        )
        self.plan = plan(self.linux_entry, self.windows_entry)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_bundle(self, name: str, value: dict[str, object]) -> Path:
        return write_json(self.root / name, value)

    def aggregate(
        self,
        *paths: Path,
        output_path: Path = Path("aggregation.json"),
    ) -> dict[str, object]:
        with (
            mock.patch.object(
                platform_evidence,
                "_load_contracts",
                return_value=(
                    {"outputs": {"aggregation": "aggregation.json"}},
                    self.plan,
                    BINDINGS,
                ),
            ),
            mock.patch.object(
                platform_evidence,
                "_portable_source",
                return_value={
                    "commit": "a" * 40,
                    "sourceFingerprint": digest("5"),
                },
            ),
        ):
            return platform_evidence.aggregate_platform_evidence(
                profile_path=Path("profile.json"),
                ci_plan_path=Path("ci-plan.json"),
                bundle_paths=paths,
                output_path=output_path,
                project_root=self.root,
            )

    def test_complete_distinct_platform_bundles_aggregate(self) -> None:
        linux = self.write_bundle("linux.json", bundle(self.linux_entry))
        windows = self.write_bundle("windows.json", bundle(self.windows_entry))
        report = self.aggregate(linux, windows)

        self.assertTrue(report["ok"])
        self.assertEqual([], report["rejectionCodes"])
        self.assertEqual(
            ["linux", "windows"], report["coveredPlatforms"]
        )
        self.assertEqual(
            report, read_json(self.root / "aggregation.json")
        )
        reversed_report = self.aggregate(windows, linux)
        self.assertEqual(report, reversed_report)

    def test_output_must_match_declared_aggregation_without_writing(self) -> None:
        linux = self.write_bundle("linux.json", bundle(self.linux_entry))
        windows = self.write_bundle("windows.json", bundle(self.windows_entry))
        declared = self.root / "aggregation.json"
        declared.write_text("preserve\n", encoding="utf-8")
        undeclared = self.root / "source-output.json"

        with self.assertRaisesRegex(
            CampaignError,
            r"must match verification profile outputs\.aggregation",
        ):
            self.aggregate(
                linux,
                windows,
                output_path=Path("source-output.json"),
            )

        self.assertEqual("preserve\n", declared.read_text(encoding="utf-8"))
        self.assertFalse(undeclared.exists())

    def test_identity_mismatch_codes_are_stable(self) -> None:
        cases = (
            ("commit", "b" * 40, "COMMIT_MISMATCH"),
            ("sourceFingerprint", digest("c"), "SOURCE_FINGERPRINT_MISMATCH"),
            (
                "verificationCatalogFingerprint",
                digest("d"),
                "VERIFICATION_CATALOG_FINGERPRINT_MISMATCH",
            ),
            ("profileFingerprint", digest("e"), "PROFILE_FINGERPRINT_MISMATCH"),
            ("ciPlanFingerprint", digest("f"), "CI_PLAN_FINGERPRINT_MISMATCH"),
        )
        for field, replacement, expected_code in cases:
            with self.subTest(field=field):
                linux_value = bundle(self.linux_entry)
                windows_value = bundle(self.windows_entry)
                windows_value["binding"][field] = replacement  # type: ignore[index]
                rebind(windows_value)
                linux = self.write_bundle("linux-" + field + ".json", linux_value)
                windows = self.write_bundle(
                    "windows-" + field + ".json", windows_value
                )
                report = self.aggregate(linux, windows)
                self.assertFalse(report["ok"])
                self.assertIn(expected_code, report["rejectionCodes"])

    def test_missing_entry_platform_and_case_are_rejected(self) -> None:
        linux = self.write_bundle("linux-only.json", bundle(self.linux_entry))
        report = self.aggregate(linux)
        self.assertFalse(report["ok"])
        self.assertIn("ENTRY_MISSING", report["rejectionCodes"])
        self.assertIn("REQUIRED_PLATFORM_MISSING", report["rejectionCodes"])
        self.assertIn("CASE_MISSING", report["rejectionCodes"])

    def test_cross_platform_multishard_partition_must_close_globally(self) -> None:
        selector = entry(
            "selector-linux",
            "linux",
            "smoke-case",
            kind="selector",
        )
        linux_one = entry(
            "linux-01-of-02",
            "linux",
            "functional-case",
            shard_index=1,
            shard_count=2,
        )
        linux_two = entry(
            "linux-02-of-02",
            "linux",
            "integration-case",
            shard_index=2,
            shard_count=2,
        )
        windows = entry(
            "windows-01-of-01",
            "windows",
            "workflow-case",
        )
        self.plan = plan(selector, linux_one, linux_two, windows)
        paths = {
            item["id"]: self.write_bundle(
                str(item["id"]) + ".json",
                bundle(item),
            )
            for item in (selector, linux_one, linux_two, windows)
        }

        incomplete = self.aggregate(
            paths["selector-linux"],
            paths["linux-01-of-02"],
            paths["windows-01-of-01"],
        )
        self.assertFalse(incomplete["ok"])
        self.assertNotIn(
            "REQUIRED_PLATFORM_MISSING",
            incomplete["rejectionCodes"],
        )
        self.assertIn("ENTRY_MISSING", incomplete["rejectionCodes"])
        self.assertIn("CASE_MISSING", incomplete["rejectionCodes"])

        complete = self.aggregate(*paths.values())
        self.assertTrue(complete["ok"])
        self.assertEqual(
            sorted(item["id"] for item in self.plan["entries"]),
            complete["coveredEntries"],
        )
        self.assertEqual(
            sorted(
                case_id
                for item in self.plan["entries"]
                for case_id in item["caseIds"]
            ),
            complete["coveredCaseIds"],
        )
        self.assertEqual(
            BINDINGS["verificationCatalogFingerprint"],
            complete["binding"]["verificationCatalogFingerprint"],
        )

    def test_duplicate_entry_is_rejected(self) -> None:
        first = self.write_bundle("linux-a.json", bundle(self.linux_entry))
        second = self.write_bundle("linux-b.json", bundle(self.linux_entry))
        windows = self.write_bundle("windows.json", bundle(self.windows_entry))
        report = self.aggregate(first, second, windows)
        self.assertFalse(report["ok"])
        self.assertIn("ENTRY_DUPLICATE", report["rejectionCodes"])
        self.assertIn("CASE_DUPLICATE", report["rejectionCodes"])

    def test_unknown_entry_and_case_are_rejected(self) -> None:
        linux = self.write_bundle("linux.json", bundle(self.linux_entry))
        windows = self.write_bundle("windows.json", bundle(self.windows_entry))
        unknown_entry = entry("foreign-01-of-01", "linux", "foreign-case")
        unknown = self.write_bundle("unknown.json", bundle(unknown_entry))
        report = self.aggregate(linux, windows, unknown)
        self.assertFalse(report["ok"])
        self.assertIn("ENTRY_UNKNOWN", report["rejectionCodes"])
        self.assertIn("CASE_UNEXPECTED", report["rejectionCodes"])

    def test_posix_alias_is_not_platform_evidence(self) -> None:
        posix_entry = entry("posix-01-of-01", "posix", "portable-case")
        with self.assertRaisesRegex(CampaignError, "platform is unsupported"):
            platform_evidence._plan_entries({"entries": [posix_entry]})

        candidate = bundle(posix_entry)
        with self.assertRaisesRegex(CampaignError, "platform is unsupported"):
            platform_evidence.validate_platform_bundle(candidate)

        with self.assertRaisesRegex(CampaignError, "platform is unsupported"):
            platform_evidence._required_platforms(
                {}, {"requiredPlatforms": ["posix"]}
            )

    def test_entry_and_case_ids_must_begin_alphanumeric(self) -> None:
        for invalid_id in (".hidden", "-leading", "_leading"):
            with self.subTest(entry_id=invalid_id):
                invalid_entry = entry(invalid_id, "linux", "valid-case")
                with self.assertRaisesRegex(CampaignError, "unsupported characters"):
                    platform_evidence._plan_entries(
                        {"entries": [invalid_entry]}
                    )
                candidate = bundle(invalid_entry)
                with self.assertRaisesRegex(CampaignError, "unsupported characters"):
                    platform_evidence.validate_platform_bundle(candidate)

            with self.subTest(case_id=invalid_id):
                invalid_case = entry("linux-01-of-01", "linux", invalid_id)
                with self.assertRaisesRegex(CampaignError, "caseIds"):
                    platform_evidence._plan_entries({"entries": [invalid_case]})
                candidate = bundle(invalid_case)
                with self.assertRaisesRegex(CampaignError, "caseIds"):
                    platform_evidence.validate_platform_bundle(candidate)

    def test_schema_examples_match_runtime_platform_and_id_contract(self) -> None:
        bundle_schema = read_json(
            CONTRACT_ROOT / "platform-evidence-v1.schema.json"
        )
        aggregation_schema = read_json(
            CONTRACT_ROOT / "platform-evidence-aggregation-v1.schema.json"
        )
        for schema in (bundle_schema, aggregation_schema):
            with self.subTest(schema=schema["$id"]):
                self.assertEqual(
                    sorted(platform_evidence.PLATFORMS),
                    sorted(schema["$defs"]["platform"]["enum"]),
                )
                self.assertNotIn("posix", schema["$defs"]["platform"]["enum"])
                self.assertEqual(
                    platform_evidence.ENTRY_ID_PATTERN.pattern,
                    schema["$defs"]["id"]["pattern"],
                )

        bundle_example = read_json(
            CONTRACT_ROOT / "platform-evidence.example.json"
        )
        self.assertEqual(
            bundle_example,
            platform_evidence.validate_platform_bundle(bundle_example),
        )

        aggregation_example = read_json(CONTRACT_ROOT / "aggregation.example.json")
        self.assertEqual(
            aggregation_example["aggregationFingerprint"],
            platform_evidence._aggregation_digest(aggregation_example),
        )
        for platform in (
            aggregation_example["requiredPlatforms"]
            + aggregation_example["coveredPlatforms"]
        ):
            self.assertIn(platform, platform_evidence.PLATFORMS)
        for id_value in (
            aggregation_example["expectedEntries"]
            + aggregation_example["coveredEntries"]
            + aggregation_example["expectedCaseIds"]
            + aggregation_example["coveredCaseIds"]
        ):
            self.assertIsNotNone(
                platform_evidence.ENTRY_ID_PATTERN.fullmatch(id_value)
            )

    def test_quick_or_retest_bundle_cannot_be_rebound_as_final(self) -> None:
        for field, value in (("round", "quick"), ("status", "RETEST_PASSED")):
            with self.subTest(field=field):
                candidate = bundle(self.linux_entry)
                candidate["cases"][0][field] = value  # type: ignore[index]
                rebind(candidate)
                with self.assertRaisesRegex(CampaignError, "non-final-PASS"):
                    platform_evidence.validate_platform_bundle(candidate)

    def test_bundle_fingerprint_tampering_is_rejected(self) -> None:
        candidate = bundle(self.linux_entry)
        candidate["cases"][0]["runId"] = "forged"  # type: ignore[index]
        with self.assertRaisesRegex(CampaignError, "fingerprint mismatch"):
            platform_evidence.validate_platform_bundle(candidate)

    def test_rebound_bundle_cannot_hide_incomplete_evidence(self) -> None:
        mutations = (
            (
                "missing required binding",
                lambda value: value["cases"][0]["evidence"]["files"].clear(),
                "required-file bindings are incomplete",
            ),
            (
                "empty non-empty binding",
                lambda value: value["cases"][0]["evidence"]["files"][0].update(
                    {"size": 0}
                ),
                "non-empty-file binding has zero size",
            ),
            (
                "manifest path mismatch",
                lambda value: value["cases"][0]["artifactManifest"].update(
                    {"relativePath": "unrelated/artifact-manifest.json"}
                ),
                "artifact manifest path is inconsistent",
            ),
            (
                "drive-qualified evidence path",
                lambda value: value["cases"][0]["evidence"][
                    "requiredFiles"
                ].__setitem__(0, "C:/proof.json"),
                "must be a canonical relative path",
            ),
            (
                "control-character evidence path",
                lambda value: value["cases"][0]["evidence"][
                    "requiredFiles"
                ].__setitem__(0, "proof\x0b.json"),
                "must be a canonical relative path",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                candidate = bundle(self.linux_entry)
                mutate(candidate)
                rebind(candidate)
                with self.assertRaisesRegex(CampaignError, message):
                    platform_evidence.validate_platform_bundle(candidate)

    def test_export_refuses_campaign_without_successful_audit(self) -> None:
        campaign = mock.Mock()
        with (
            mock.patch.object(
                platform_evidence,
                "audit_report",
                return_value={
                    "ok": False,
                    "rejectionCodes": ["FULL_REGRESSION_REQUIRED"],
                },
            ),
            self.assertRaisesRegex(CampaignError, "audit is incomplete"),
        ):
            platform_evidence.export_platform_evidence(
                campaign,
                profile_path=Path("profile.json"),
                ci_plan_path=Path("ci-plan.json"),
                entry_id="linux-01-of-01",
                output_path=Path("bundle.json"),
            )

    def test_export_inputs_must_match_full_ci_adapter_binding(self) -> None:
        write_json(self.root / "profile.json", {})
        write_json(self.root / "ci-plan.json", {})
        write_json(self.root / "other-profile.json", {})
        write_json(self.root / "other-ci-plan.json", {})

        def campaign_with(verification: dict[str, object]) -> mock.Mock:
            campaign = mock.Mock()
            campaign.adapter.project_root = self.root
            campaign.adapter.verification = verification
            return campaign

        def valid_binding() -> dict[str, object]:
            return {
                "contractVersion": 1,
                "profile": {
                    "path": "profile.json",
                    "sha256": BINDINGS["profileFingerprint"],
                },
                "verificationCatalogFingerprint": BINDINGS[
                    "verificationCatalogFingerprint"
                ],
                "tier": "full",
                "impactPlan": None,
                "ciPlan": {
                    "path": "ci-plan.json",
                    "sha256": BINDINGS["ciPlanFingerprint"],
                    "entryId": "linux-01-of-01",
                },
            }

        platform_evidence._validate_campaign_verification_binding(
            campaign_with(valid_binding()),
            profile_path=Path("profile.json"),
            ci_plan_path=Path("ci-plan.json"),
            entry_id="linux-01-of-01",
            contract_bindings=BINDINGS,
        )

        mutations = (
            (
                "quick tier",
                lambda value: value.update({"tier": "quick"}),
                Path("profile.json"),
                Path("ci-plan.json"),
                "linux-01-of-01",
                "full CI verification binding",
            ),
            (
                "impact plan",
                lambda value: value.update(
                    {"impactPlan": {"path": "impact.json", "sha256": digest("a")}}
                ),
                Path("profile.json"),
                Path("ci-plan.json"),
                "linux-01-of-01",
                "full CI verification binding",
            ),
            (
                "profile path",
                lambda value: None,
                Path("other-profile.json"),
                Path("ci-plan.json"),
                "linux-01-of-01",
                "profile does not match",
            ),
            (
                "profile fingerprint",
                lambda value: value["profile"].update(  # type: ignore[union-attr]
                    {"sha256": digest("a")}
                ),
                Path("profile.json"),
                Path("ci-plan.json"),
                "linux-01-of-01",
                "profile fingerprint does not match",
            ),
            (
                "catalog fingerprint",
                lambda value: value.update(
                    {"verificationCatalogFingerprint": digest("a")}
                ),
                Path("profile.json"),
                Path("ci-plan.json"),
                "linux-01-of-01",
                "catalog fingerprint does not match",
            ),
            (
                "CI plan path",
                lambda value: None,
                Path("profile.json"),
                Path("other-ci-plan.json"),
                "linux-01-of-01",
                "CI plan does not match",
            ),
            (
                "CI plan fingerprint",
                lambda value: value["ciPlan"].update(  # type: ignore[union-attr]
                    {"sha256": digest("a")}
                ),
                Path("profile.json"),
                Path("ci-plan.json"),
                "linux-01-of-01",
                "CI plan fingerprint does not match",
            ),
            (
                "entry id",
                lambda value: None,
                Path("profile.json"),
                Path("ci-plan.json"),
                "windows-01-of-01",
                "entry does not match",
            ),
        )
        for label, mutate, profile_path, ci_plan_path, entry_id, message in mutations:
            with self.subTest(label=label):
                verification = valid_binding()
                mutate(verification)
                with self.assertRaisesRegex(CampaignError, message):
                    platform_evidence._validate_campaign_verification_binding(
                        campaign_with(verification),
                        profile_path=profile_path,
                        ci_plan_path=ci_plan_path,
                        entry_id=entry_id,
                        contract_bindings=BINDINGS,
                    )

    @unittest.skipUnless(shutil.which("git"), "Git is required for portable evidence")
    def test_public_cli_exports_and_aggregates_real_final_regressions(self) -> None:
        from adapter_paths import current_platform, validate_adapter
        from verification_pipeline import (
            VerificationPipelineError,
            build_ci_plan,
            load_profile,
            render_derived_adapter,
        )
        from verification_pipeline import write_json as write_contract_json

        host_platform = current_platform()
        if host_platform not in {"darwin", "linux", "windows"}:
            self.skipTest("the host has no concrete CI platform mapping")
        project = Path(os.path.realpath(str(self.root / "project")))
        contracts = project / ".steward"
        runtime = contracts / "runtime"
        contracts.mkdir(parents=True)
        runtime.mkdir()

        def git(*args: str) -> None:
            completed = subprocess.run(
                ["git", *args],
                cwd=project,
                capture_output=True,
                check=False,
                text=True,
            )
            if completed.returncode != 0:
                self.fail(
                    "git command failed\n"
                    + completed.stdout
                    + "\n"
                    + completed.stderr
                )

        git("init", "-q")
        git("config", "user.email", "fixture@example.invalid")
        git("config", "user.name", "Fixture")
        (project / "source.txt").write_text("stable\n", encoding="utf-8")

        command = (
            "import os\n"
            "from pathlib import Path\n"
            "evidence = Path(os.environ['CLOSED_LOOP_EVIDENCE_DIR'])\n"
            "(evidence / 'proof.json').write_text('{\"ok\":true}', encoding='utf-8')\n"
        )
        selector_case = make_case(
            "selector-self-test",
            "smoke",
            argv=(sys.executable, "-c", command),
            platform="any",
        )
        selector_case["quick"] = True
        full_case = make_case(
            "full-case",
            "functional",
            argv=(sys.executable, "-c", command),
            platform="any",
        )
        full_case["quick"] = True
        base_adapter = write_json(
            contracts / "base-adapter.json",
            {
                "schemaVersion": 1,
                "projectId": "platform-fixture",
                "projectRoot": "..",
                "campaignRoot": ".steward/runtime/base-campaign",
                "source": {
                    "provider": "git",
                    "excludes": [".steward/runtime/**"],
                },
                "localOnly": {
                    "enabled": True,
                    "allowedExternalCapabilities": [],
                },
                "cases": [selector_case, full_case],
            },
        )
        profile_path = contracts / "verification-profile.json"
        write_json(
            profile_path,
            {
                "schemaId": "steward.verification-profile",
                "schemaVersion": 1,
                "projectId": "platform-fixture",
                "projectRoot": "..",
                "adapter": {"path": ".steward/base-adapter.json"},
                "runtime": {
                    "pluginRoot": None,
                    "pythonExecutables": {
                        "posix": "python3",
                        "windows": "py",
                    },
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
                    "highImpactPaths": [],
                    "unknownPath": "full",
                },
                "packages": [],
                "guards": [],
                "tiers": {
                    "quick": {"selection": "impact-plan"},
                    "full": {"selection": "all", "ignoreSelector": True},
                },
                "ci": {
                    "platforms": [
                        {"id": host_platform, "required": True, "shards": 1}
                    ],
                    "portablePlatform": host_platform,
                    "posixPlatform": host_platform
                    if host_platform in {"darwin", "linux"}
                    else "linux",
                    "selectorPlatform": host_platform,
                    "selectorCaseIds": ["selector-self-test"],
                },
                "outputs": {
                    "profile": ".steward/verification-profile.json",
                    "impactPlan": ".steward/runtime/impact-plan.json",
                    "ciPlan": ".steward/runtime/ci-plan.json",
                    "localEntry": ".steward/run-quick",
                    "workflow": ".github/workflows/project-verification.yml",
                    "derivedAdapters": ".steward/runtime/adapters",
                    "campaigns": ".steward/runtime/campaigns",
                    "evidenceBundles": ".steward/runtime/evidence",
                    "aggregation": ".steward/runtime/aggregation.json",
                },
            },
        )
        # Windows profiles still need a configured POSIX target.  This fixture
        # has only portable cases, so add Linux without assigning it a required
        # platform obligation.
        if host_platform == "windows":
            profile_value = read_json(profile_path)
            profile_value["ci"]["platforms"].append(
                {"id": "linux", "required": False, "shards": 1}
            )
            write_json(profile_path, profile_value)

        # This alternate profile deliberately preserves the same case IDs and
        # CI entry IDs while changing one runner contract.  An audited campaign
        # from the primary profile must never be exportable under this catalog.
        rebound_adapter_path = contracts / "rebound-adapter.json"
        rebound_full_case = copy.deepcopy(full_case)
        rebound_full_case["argv"] = [
            sys.executable,
            "-c",
            command + "\nprint('different runner contract')\n",
        ]
        rebound_adapter_value = read_json(base_adapter)
        rebound_adapter_value["campaignRoot"] = (
            ".steward/runtime/rebound-base-campaign"
        )
        rebound_adapter_value["cases"] = [selector_case, rebound_full_case]
        write_json(rebound_adapter_path, rebound_adapter_value)

        rebound_profile_path = contracts / "rebound-profile.json"
        rebound_profile_value = read_json(profile_path)
        rebound_profile_value["adapter"]["path"] = (
            ".steward/rebound-adapter.json"
        )
        rebound_profile_value["outputs"] = {
            "profile": ".steward/rebound-profile.json",
            "impactPlan": ".steward/runtime/rebound-impact-plan.json",
            "ciPlan": ".steward/runtime/rebound-ci-plan.json",
            "localEntry": ".steward/rebound-run-quick",
            "workflow": ".github/workflows/rebound-project-verification.yml",
            "derivedAdapters": ".steward/runtime/rebound-adapters",
            "campaigns": ".steward/runtime/rebound-campaigns",
            "evidenceBundles": ".steward/runtime/rebound-evidence",
            "aggregation": ".steward/runtime/rebound-aggregation.json",
        }
        write_json(rebound_profile_path, rebound_profile_value)

        git("add", "source.txt", ".steward/base-adapter.json")
        git(
            "add",
            ".steward/verification-profile.json",
            ".steward/rebound-adapter.json",
            ".steward/rebound-profile.json",
        )
        git("commit", "-q", "-m", "fixture")

        invalid_profile_path = runtime / "invalid-profile.json"
        invalid_profile = read_json(profile_path)
        invalid_profile["projectRoot"] = "../.."
        invalid_profile["outputs"]["profile"] = (
            ".steward/runtime/invalid-profile.json"
        )
        invalid_profile["outputs"]["aggregation"] = (
            ".steward/runtime/evidence/aggregation.json"
        )
        write_json(invalid_profile_path, invalid_profile)
        with self.assertRaisesRegex(
            VerificationPipelineError,
            "output files and dynamic output directories cannot overlap",
        ):
            load_profile(invalid_profile_path, project)

        profile = load_profile(profile_path, project)
        ci_plan = build_ci_plan(profile)
        ci_plan_path = runtime / "ci-plan.json"
        write_contract_json(ci_plan_path, ci_plan)
        rebound_profile = load_profile(rebound_profile_path, project)
        rebound_ci_plan = build_ci_plan(rebound_profile)
        rebound_ci_plan_path = runtime / "rebound-ci-plan.json"
        write_contract_json(rebound_ci_plan_path, rebound_ci_plan)
        self.assertNotEqual(
            profile.adapter_catalog_fingerprint,
            rebound_profile.adapter_catalog_fingerprint,
        )
        self.assertNotEqual(
            ci_plan["contentDigest"], rebound_ci_plan["contentDigest"]
        )

        # A plan inside its derived campaign would be mutable campaign state,
        # not an independent pinned configuration input.  The adapter boundary
        # rejects it even when its digest and entry otherwise validate.
        unsafe_campaign = runtime / "campaigns" / "unsafe-campaign"
        unsafe_plan_path = unsafe_campaign / "ci-plan.json"
        write_contract_json(unsafe_plan_path, ci_plan)
        unsafe_adapter = runtime / "adapters" / "unsafe-adapter.json"
        render_derived_adapter(
            profile,
            tier="full",
            output=unsafe_adapter,
            campaign_root=unsafe_campaign,
            ci_plan=(unsafe_plan_path, ci_plan),
            entry_id=ci_plan["entries"][0]["id"],
        )
        with self.assertRaisesRegex(
            CampaignError, "CI plan cannot be inside campaignRoot"
        ):
            validate_adapter(unsafe_adapter)

        bundles: list[Path] = []
        for plan_entry in ci_plan["entries"]:
            entry_id = plan_entry["id"]
            derived_adapter = runtime / "adapters" / (entry_id + "-adapter.json")
            render_derived_adapter(
                profile,
                tier="full",
                output=derived_adapter,
                campaign_root=runtime / "campaigns" / entry_id,
                ci_plan=(ci_plan_path, ci_plan),
                entry_id=entry_id,
            )
            derived_value = read_json(derived_adapter)
            self.assertTrue(
                (derived_adapter.parent / derived_value["projectRoot"])
                .resolve()
                .is_dir(),
                derived_value["projectRoot"],
            )
            run_cli(derived_adapter, "init", expected=0)
            run_cli(derived_adapter, "run", expected=0)
            run_cli(
                derived_adapter,
                "run",
                "--mode",
                "regression",
                expected=0,
            )
            if not bundles:
                self.assertEqual(
                    plan_entry["caseIds"],
                    next(
                        item["caseIds"]
                        for item in rebound_ci_plan["entries"]
                        if item["id"] == entry_id
                    ),
                )
                rebound_output = runtime / (entry_id + "-rebound-bundle.json")
                rebound_export = run_cli(
                    derived_adapter,
                    "export-platform-evidence",
                    "--profile",
                    str(rebound_profile_path),
                    "--ci-plan",
                    str(rebound_ci_plan_path),
                    "--entry",
                    entry_id,
                    "--output",
                    str(rebound_output),
                    expected=2,
                )
                self.assertIn(
                    "profile does not match the campaign adapter binding",
                    rebound_export.stderr,
                )
                self.assertFalse(rebound_output.exists())
            bundle_path = runtime / "evidence" / (entry_id + ".json")
            exported = json_output(
                run_cli(
                    derived_adapter,
                    "export-platform-evidence",
                    "--profile",
                    str(profile_path),
                    "--ci-plan",
                    str(ci_plan_path),
                    "--entry",
                    entry_id,
                    "--output",
                    str(bundle_path),
                    expected=0,
                )
            )
            self.assertEqual("steward.platform-evidence", exported["kind"])
            bundles.append(bundle_path)
            if len(bundles) == 1:
                protected = run_cli(
                    derived_adapter,
                    "export-platform-evidence",
                    "--profile",
                    str(profile_path),
                    "--ci-plan",
                    str(ci_plan_path),
                    "--entry",
                    entry_id,
                    "--output",
                    str(derived_adapter),
                    expected=2,
                )
                self.assertIn(
                    "must match verification profile "
                    "outputs.evidenceBundles/<entryId>.json",
                    protected.stderr,
                )
                self.assertEqual(
                    entry_id,
                    read_json(derived_adapter)["verification"]["ciPlan"][
                        "entryId"
                    ],
                )

        aggregation_path = runtime / "aggregation.json"
        argv = [
            sys.executable,
            str(SCRIPT_ROOT / "campaign.py"),
            "aggregate-platform-evidence",
            "--profile",
            str(profile_path),
            "--ci-plan",
            str(ci_plan_path),
        ]
        for bundle_path in reversed(bundles):
            argv.extend(["--bundle", str(bundle_path)])
        argv.extend(["--output", str(aggregation_path)])
        completed = subprocess.run(
            argv,
            cwd=project,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            self.fail(completed.stdout + "\n" + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual([], report["rejectionCodes"])
        self.assertEqual(report, read_json(aggregation_path))
        self.assertTrue(base_adapter.is_file())

        repeated = subprocess.run(
            argv,
            cwd=project,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, repeated.returncode, repeated.stdout + repeated.stderr)
        self.assertEqual(report, json.loads(repeated.stdout))

        protected_output_argv = argv[:-1] + [str(bundles[0])]
        protected_output = subprocess.run(
            protected_output_argv,
            cwd=project,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            2,
            protected_output.returncode,
            protected_output.stdout + protected_output.stderr,
        )
        self.assertIn(
            "must match verification profile outputs.aggregation",
            protected_output.stderr,
        )
        self.assertEqual(
            "steward.platform-evidence",
            read_json(bundles[0])["kind"],
        )

        (project / "source.txt").write_text("dirty\n", encoding="utf-8")
        previous_aggregation = aggregation_path.read_bytes()
        dirty = subprocess.run(
            argv,
            cwd=project,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        self.assertEqual(2, dirty.returncode, dirty.stdout + dirty.stderr)
        self.assertIn("portable source identity is unavailable", dirty.stderr)
        self.assertEqual(previous_aggregation, aggregation_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
