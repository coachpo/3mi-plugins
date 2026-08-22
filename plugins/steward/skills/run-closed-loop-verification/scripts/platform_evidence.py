"""Strict export and aggregation of cross-platform final-regression evidence.

The campaign journal and artifacts remain the execution authority.  This
module only emits a bounded canonical projection after the ordinary campaign
audit succeeds, then checks a complete set of projections against the shared
provider-neutral CI plan.
"""

from __future__ import annotations

import copy
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from adapter_paths import (
    covers_exclude,
    is_within,
    normalize_relative,
    path_has_symlink_component,
    relative_to_root,
    resolve_project_path,
)
from audit import audit_report
from journal_state import Campaign, get_attempt
from model import (
    MAX_JSON_BYTES,
    CampaignError,
    assert_persistable,
    atomic_write_json,
    canonical_bytes,
    read_json,
    sha256_bytes,
)


PLUGIN_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))

try:
    from verification_pipeline import (
        ci_plan_sha256,
        load_ci_plan,
        load_profile,
        portable_git_source_identity,
        profile_catalog_fingerprint,
        profile_sha256,
    )
except ImportError:  # pragma: no cover - packaging validation covers this
    ci_plan_sha256 = None  # type: ignore[assignment]
    load_ci_plan = None  # type: ignore[assignment]
    load_profile = None  # type: ignore[assignment]
    portable_git_source_identity = None  # type: ignore[assignment]
    profile_catalog_fingerprint = None  # type: ignore[assignment]
    profile_sha256 = None  # type: ignore[assignment]


BUNDLE_SCHEMA_VERSION = 1
AGGREGATION_SCHEMA_VERSION = 1
BUNDLE_KIND = "steward.platform-evidence"
AGGREGATION_KIND = "steward.platform-evidence-aggregation"
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
ENTRY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PLATFORMS = {"darwin", "linux", "windows"}


def _view(value: Any, label: str) -> dict[str, Any]:
    """Return a detached canonical contract view from a loader result."""

    if isinstance(value, dict):
        result = value
    else:
        result = getattr(value, "view", None)
        if callable(result):
            result = result()
        if result is None:
            result = getattr(value, "data", None)
    if not isinstance(result, dict):
        raise CampaignError(label + " loader did not return an object view")
    try:
        detached = copy.deepcopy(result)
        canonical_bytes(detached)
        assert_persistable(detached)
    except (CampaignError, TypeError, ValueError) as exc:
        raise CampaignError(label + " view is not safe canonical JSON") from exc
    return detached


def _require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_PATTERN.fullmatch(value) is None:
        raise CampaignError(label + " must be a sha256-prefixed lowercase digest")
    return value


def _require_nonempty_string(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character in value for character in "\r\n\x00")
    ):
        raise CampaignError(label + " must be a non-empty single-line string")
    return value


def _require_relative_path(value: Any, label: str) -> str:
    result = _require_nonempty_string(value, label)
    if (
        result.startswith("/")
        or re.match(r"^[A-Za-z]:", result)
        or "\\" in result
        or any(ord(character) < 32 for character in result)
        or any(part in {"", ".", ".."} for part in result.split("/"))
    ):
        raise CampaignError(label + " must be a canonical relative path")
    return result


def _entry_id(value: dict[str, Any]) -> str:
    result = value.get("id", value.get("entryId"))
    result = _require_nonempty_string(result, "CI plan entry id")
    if ENTRY_ID_PATTERN.fullmatch(result) is None:
        raise CampaignError("CI plan entry id contains unsupported characters")
    return result


def _entry_cases(value: dict[str, Any]) -> list[str]:
    result = value.get("caseIds")
    if (
        not isinstance(result, list)
        or not result
        or any(
            not isinstance(item, str)
            or ENTRY_ID_PATTERN.fullmatch(item) is None
            for item in result
        )
        or len(result) != len(set(result))
    ):
        raise CampaignError("CI plan entry caseIds must be a non-empty unique ID array")
    return list(result)


def _entry_kind(value: dict[str, Any]) -> str:
    result = value.get("kind")
    if result not in {"selector", "platform"}:
        raise CampaignError("CI plan entry kind is unsupported")
    return result


def _entry_platform(value: dict[str, Any]) -> str:
    result = value.get("platform")
    if result not in PLATFORMS:
        raise CampaignError("CI plan entry platform is unsupported")
    return result


def _entry_shard(value: dict[str, Any]) -> tuple[int, int]:
    index = value.get("shardIndex")
    count = value.get("shardCount")
    if (
        type(index) is not int
        or type(count) is not int
        or index < 1
        or count < 1
        or index > count
    ):
        raise CampaignError("CI plan entry shard coordinates are invalid")
    return index, count


def _plan_entries(plan: Any) -> list[dict[str, Any]]:
    view = _view(plan, "CI plan")
    entries: Any = view.get("entries")
    if entries is None and isinstance(view.get("matrix"), dict):
        entries = view["matrix"].get("entries")
    if not isinstance(entries, list) or not entries:
        raise CampaignError("CI plan must contain a non-empty entries array")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_shards: set[tuple[str, str, int, int]] = set()
    seen_cases: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            raise CampaignError("CI plan entry must be an object")
        entry_id = _entry_id(raw)
        kind = _entry_kind(raw)
        platform = _entry_platform(raw)
        shard_index, shard_count = _entry_shard(raw)
        case_ids = _entry_cases(raw)
        shard_key = (kind, platform, shard_index, shard_count)
        if entry_id in seen_ids:
            raise CampaignError("CI plan contains a duplicate entry id")
        if shard_key in seen_shards:
            raise CampaignError("CI plan contains duplicate shard coordinates")
        overlap = seen_cases.intersection(case_ids)
        if overlap:
            raise CampaignError(
                "CI plan assigns a case more than once: " + min(overlap)
            )
        seen_ids.add(entry_id)
        seen_shards.add(shard_key)
        seen_cases.update(case_ids)
        result.append(
            {
                "id": entry_id,
                "kind": kind,
                "platform": platform,
                "shardIndex": shard_index,
                "shardCount": shard_count,
                "caseIds": case_ids,
            }
        )
    return result


def _required_platforms(profile: Any, plan: Any) -> list[str]:
    plan_view = _view(plan, "CI plan")
    raw: Any = plan_view.get("requiredPlatforms")
    if raw is None:
        profile_view = _view(profile, "verification profile")
        ci = profile_view.get("ci")
        if isinstance(ci, dict):
            raw = ci.get("requiredPlatforms", ci.get("platforms"))
    if not isinstance(raw, list) or not raw:
        raise CampaignError("verification profile must declare required platforms")
    values: list[str] = []
    for item in raw:
        if isinstance(item, str):
            platform = item
            required = True
        elif isinstance(item, dict):
            platform = item.get("id", item.get("platform"))
            required = item.get("required", True)
        else:
            raise CampaignError("required platform entry is invalid")
        if not isinstance(required, bool):
            raise CampaignError("required platform flag must be a boolean")
        if required:
            if platform not in PLATFORMS:
                raise CampaignError("required platform is unsupported")
            values.append(platform)
    if not values or len(values) != len(set(values)):
        raise CampaignError("required platforms must be a non-empty unique array")
    return sorted(values)


def _load_contracts(
    profile_path: Path,
    ci_plan_path: Path,
    project_root: Path,
) -> tuple[Any, Any, dict[str, str]]:
    if any(
        function is None
        for function in (
            load_profile,
            load_ci_plan,
            profile_sha256,
            profile_catalog_fingerprint,
            ci_plan_sha256,
        )
    ):
        raise CampaignError("shared verification pipeline contracts are unavailable")
    resolved_profile = (
        profile_path if profile_path.is_absolute() else project_root / profile_path
    )
    resolved_plan = (
        ci_plan_path if ci_plan_path.is_absolute() else project_root / ci_plan_path
    )
    try:
        profile = load_profile(resolved_profile, project_root)
        plan = load_ci_plan(resolved_plan, profile)
        bindings = {
            "profileFingerprint": _require_hash(
                profile_sha256(profile), "profile fingerprint"
            ),
            "verificationCatalogFingerprint": _require_hash(
                profile_catalog_fingerprint(profile),
                "verification catalog fingerprint",
            ),
            "ciPlanFingerprint": _require_hash(
                ci_plan_sha256(plan), "CI plan fingerprint"
            ),
        }
    except CampaignError:
        raise
    except Exception as exc:
        raise CampaignError("verification pipeline contracts are invalid") from exc
    return profile, plan, bindings


def _canonical_contract_path(
    value: Path | str,
    project_root: Path,
    label: str,
) -> Path:
    """Resolve one contract path without permitting link or traversal aliases."""

    path = Path(value)
    candidate = path if path.is_absolute() else project_root / path
    if path_has_symlink_component(candidate):
        raise CampaignError(label + " uses a symlink/reparse path")
    try:
        resolved = resolve_project_path(project_root, str(candidate), label)
    except CampaignError:
        raise
    except Exception as exc:
        raise CampaignError(label + " is invalid") from exc
    if not resolved.is_file():
        raise CampaignError(label + " must name an existing file")
    return resolved


def _validate_campaign_verification_binding(
    campaign: Campaign,
    *,
    profile_path: Path,
    ci_plan_path: Path,
    entry_id: str,
    contract_bindings: dict[str, str],
) -> None:
    """Bind export inputs to the exact full-CI contract audited by the campaign."""

    verification = getattr(campaign.adapter, "verification", None)
    verification_fields = {
        "contractVersion",
        "profile",
        "verificationCatalogFingerprint",
        "tier",
        "impactPlan",
        "ciPlan",
    }
    if (
        not isinstance(verification, dict)
        or set(verification) != verification_fields
        or type(verification.get("contractVersion")) is not int
        or verification.get("contractVersion") != 1
        or verification.get("tier") != "full"
        or verification.get("impactPlan") is not None
    ):
        raise CampaignError(
            "platform evidence requires the campaign's full CI verification binding"
        )

    profile_ref = verification.get("profile")
    if not isinstance(profile_ref, dict) or set(profile_ref) != {"path", "sha256"}:
        raise CampaignError("campaign verification profile binding is invalid")
    bound_profile_path = _canonical_contract_path(
        _require_relative_path(
            profile_ref.get("path"), "campaign verification profile path"
        ),
        campaign.adapter.project_root,
        "campaign verification profile path",
    )
    supplied_profile_path = _canonical_contract_path(
        profile_path,
        campaign.adapter.project_root,
        "supplied verification profile path",
    )
    if supplied_profile_path != bound_profile_path:
        raise CampaignError(
            "supplied verification profile does not match the campaign adapter binding"
        )
    if _require_hash(
        profile_ref.get("sha256"), "campaign verification profile fingerprint"
    ) != contract_bindings["profileFingerprint"]:
        raise CampaignError(
            "verification profile fingerprint does not match the campaign adapter binding"
        )
    if _require_hash(
        verification.get("verificationCatalogFingerprint"),
        "campaign verification catalog fingerprint",
    ) != contract_bindings["verificationCatalogFingerprint"]:
        raise CampaignError(
            "verification catalog fingerprint does not match the campaign adapter binding"
        )

    ci_ref = verification.get("ciPlan")
    if not isinstance(ci_ref, dict) or set(ci_ref) != {
        "path",
        "sha256",
        "entryId",
    }:
        raise CampaignError("campaign verification CI plan binding is invalid")
    bound_ci_plan_path = _canonical_contract_path(
        _require_relative_path(ci_ref.get("path"), "campaign verification CI plan path"),
        campaign.adapter.project_root,
        "campaign verification CI plan path",
    )
    supplied_ci_plan_path = _canonical_contract_path(
        ci_plan_path,
        campaign.adapter.project_root,
        "supplied verification CI plan path",
    )
    if supplied_ci_plan_path != bound_ci_plan_path:
        raise CampaignError(
            "supplied CI plan does not match the campaign adapter binding"
        )
    if _require_hash(
        ci_ref.get("sha256"), "campaign verification CI plan fingerprint"
    ) != contract_bindings["ciPlanFingerprint"]:
        raise CampaignError(
            "CI plan fingerprint does not match the campaign adapter binding"
        )
    if _require_nonempty_string(
        ci_ref.get("entryId"), "campaign verification CI plan entry id"
    ) != entry_id:
        raise CampaignError(
            "CI plan entry does not match the campaign adapter binding"
        )


def _portable_source(project_root: Path, profile: Any | None = None) -> dict[str, str]:
    if portable_git_source_identity is None:
        raise CampaignError("shared verification pipeline contracts are unavailable")
    try:
        excludes: list[str] = []
        if profile is not None:
            adapter_data = getattr(profile, "adapter_data", None)
            if isinstance(adapter_data, dict):
                source = adapter_data.get("source")
                if isinstance(source, dict) and isinstance(
                    source.get("excludes"), list
                ):
                    for item in source["excludes"]:
                        normalized = (
                            item.replace("\\", "/") if os.name == "nt" else item
                        )
                        recursive = normalized.endswith("/**")
                        base = (
                            normalized[:-3].rstrip("/")
                            if recursive
                            else normalized.rstrip("/")
                        )
                        excludes.append(
                            normalize_relative(base, "adapter source exclude")
                            + ("/**" if recursive else "")
                        )
        value = portable_git_source_identity(
            project_root,
            require_clean=True,
            excludes=excludes,
        )
    except CampaignError:
        raise
    except Exception as exc:
        raise CampaignError("portable source identity is unavailable") from exc
    if (
        not isinstance(value, dict)
        or not {"commit", "sourceFingerprint"}.issubset(value)
        or set(value)
        - {"sourceProvider", "commit", "tree", "fingerprint", "sourceFingerprint"}
    ):
        raise CampaignError("portable source identity has an invalid shape")
    if "sourceProvider" in value and value["sourceProvider"] != "git":
        raise CampaignError("portable source provider is invalid")
    if "tree" in value and (
        not isinstance(value["tree"], str)
        or COMMIT_PATTERN.fullmatch(value["tree"]) is None
    ):
        raise CampaignError("portable source tree is invalid")
    if "fingerprint" in value and value["fingerprint"] != value["sourceFingerprint"]:
        raise CampaignError("portable source fingerprint aliases disagree")
    commit = value.get("commit")
    if not isinstance(commit, str) or COMMIT_PATTERN.fullmatch(commit) is None:
        raise CampaignError("portable source commit must be a full lowercase object id")
    return {
        "commit": commit,
        "sourceFingerprint": _require_hash(
            value.get("sourceFingerprint"), "portable source fingerprint"
        ),
    }


def _safe_output_path(
    output: Path,
    project_root: Path,
    *,
    campaign: Campaign | None = None,
) -> Path:
    if "\x00" in str(output):
        raise CampaignError("output path contains a NUL character")
    candidate = output if output.is_absolute() else project_root / output
    if path_has_symlink_component(candidate):
        raise CampaignError("output path uses a symlink/reparse path")
    resolved = resolve_project_path(project_root, str(candidate), "output path")
    if resolved == project_root or resolved.exists() and not resolved.is_file():
        raise CampaignError("output path must name a file within projectRoot")
    if campaign is not None:
        if is_within(resolved, campaign.adapter.campaign_root):
            raise CampaignError("platform evidence cannot be written inside campaignRoot")
        relative = relative_to_root(project_root, resolved)
        if not any(
            covers_exclude(exclude, relative)
            for exclude in campaign.adapter.excludes
        ):
            raise CampaignError(
                "platform evidence output must be covered by source.excludes"
            )
    return resolved


def _bundle_payload_without_fingerprint(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result.pop("bundleFingerprint", None)
    return result


def _bundle_fingerprint(value: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(_bundle_payload_without_fingerprint(value)))


def _find_entry(plan: Any, entry_id: str) -> dict[str, Any]:
    matches = [entry for entry in _plan_entries(plan) if entry["id"] == entry_id]
    if len(matches) != 1:
        raise CampaignError("CI plan entry does not exist: " + entry_id)
    return matches[0]


def export_platform_evidence(
    campaign: Campaign,
    *,
    profile_path: Path,
    ci_plan_path: Path,
    entry_id: str,
    output_path: Path,
) -> dict[str, Any]:
    """Export one audited shard; quick, initial, and retest history is excluded."""

    report = audit_report(campaign)
    if not report.get("ok"):
        codes = report.get("rejectionCodes") or []
        suffix = ": " + ", ".join(codes) if codes else ""
        raise CampaignError("campaign audit is incomplete" + suffix)
    final_id = campaign.state.get("finalRegressionAttemptId")
    if not isinstance(final_id, str):
        raise CampaignError("campaign lacks a final regression attempt")
    final_attempt = get_attempt(campaign.state, final_id)
    if final_attempt.get("mode") != "regression" or final_attempt.get("status") != "PASS":
        raise CampaignError("platform evidence requires regression/PASS")

    project_root = campaign.adapter.project_root
    profile, plan, contract_bindings = _load_contracts(
        profile_path, ci_plan_path, project_root
    )
    _validate_campaign_verification_binding(
        campaign,
        profile_path=profile_path,
        ci_plan_path=ci_plan_path,
        entry_id=entry_id,
        contract_bindings=contract_bindings,
    )
    profile_view = _view(profile, "verification profile")
    plan_view = _view(plan, "CI plan")
    entry = _find_entry(plan, entry_id)
    outputs = profile_view.get("outputs")
    if not isinstance(outputs, dict):
        raise CampaignError(
            "verification profile does not declare an evidence bundle output"
        )
    bundle_directory = _require_relative_path(
        outputs.get("evidenceBundles"),
        "verification profile evidence bundle output",
    )
    declared_output = _safe_output_path(
        Path(bundle_directory) / (entry["id"] + ".json"),
        project_root,
        campaign=campaign,
    )
    output = _safe_output_path(output_path, project_root, campaign=campaign)
    if output != declared_output:
        raise CampaignError(
            "platform evidence output must match "
            "verification profile outputs.evidenceBundles/<entryId>.json"
        )
    portable_before = _portable_source(project_root, profile)
    runtime_platform = campaign.state.get("runtimePlatform")
    if runtime_platform != entry["platform"]:
        raise CampaignError("campaign runtime platform does not match CI plan entry")
    adapter_case_ids = [case["id"] for case in campaign.adapter.cases]
    if adapter_case_ids != entry["caseIds"]:
        raise CampaignError("campaign adapter cases do not match the CI plan entry")

    final_runs = final_attempt.get("caseRuns")
    if not isinstance(final_runs, list):
        raise CampaignError("final regression case runs are unavailable")
    run_by_case: dict[str, dict[str, Any]] = {}
    for run in final_runs:
        if not isinstance(run, dict) or not isinstance(run.get("caseId"), str):
            raise CampaignError("final regression contains an invalid case run")
        case_id = run["caseId"]
        if case_id in run_by_case:
            raise CampaignError("final regression contains a duplicate case run")
        run_by_case[case_id] = run
    if list(run_by_case) != entry["caseIds"]:
        raise CampaignError("final regression does not exactly cover the CI plan entry")

    cases: list[dict[str, Any]] = []
    baseline = final_attempt.get("sourceFingerprint")
    _require_hash(baseline, "final regression source fingerprint")
    for case_id in entry["caseIds"]:
        run = run_by_case[case_id]
        if (
            run.get("status") != "PASS"
            or run.get("sourceFingerprint") != baseline
            or run.get("sourceAfterFingerprint") != baseline
        ):
            raise CampaignError("platform evidence accepts only same-source final PASS runs")
        artifact_manifest = run.get("artifactManifest")
        evidence = run.get("evidence")
        if not isinstance(artifact_manifest, dict) or not isinstance(evidence, dict):
            raise CampaignError("final regression evidence binding is unavailable")
        cases.append(
            {
                "id": case_id,
                "round": "regression",
                "status": "PASS",
                "runId": _require_nonempty_string(run.get("runId"), "case run id"),
                "sourceFingerprintBefore": baseline,
                "sourceFingerprintAfter": baseline,
                "artifactDir": _require_relative_path(
                    run.get("artifactDir"), "case artifact directory"
                ),
                "artifactManifest": copy.deepcopy(artifact_manifest),
                "evidence": copy.deepcopy(evidence),
            }
        )

    observed_profile, observed_plan, observed_bindings = _load_contracts(
        profile_path, ci_plan_path, project_root
    )
    portable = _portable_source(project_root, observed_profile)
    if (
        observed_bindings != contract_bindings
        or _view(observed_profile, "verification profile") != profile_view
        or _view(observed_plan, "CI plan") != plan_view
    ):
        raise CampaignError(
            "verification profile or CI plan changed during evidence export"
        )
    if portable != portable_before:
        raise CampaignError("portable source identity changed during evidence export")
    if campaign.current_source() != baseline:
        raise CampaignError("campaign source changed during evidence export")
    bundle: dict[str, Any] = {
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "kind": BUNDLE_KIND,
        "binding": {
            **portable,
            **contract_bindings,
            "campaignCatalogFingerprint": _require_hash(
                campaign.state.get("catalogFingerprint"),
                "campaign catalog fingerprint",
            ),
            "executionSourceFingerprint": baseline,
        },
        "entry": copy.deepcopy(entry),
        "campaign": {
            "id": _require_nonempty_string(
                campaign.state.get("campaignId"), "campaign id"
            ),
            "runtimePlatform": runtime_platform,
            "finalRegressionAttemptId": final_id,
        },
        "cases": cases,
    }
    bundle["bundleFingerprint"] = _bundle_fingerprint(bundle)
    assert_persistable(bundle)
    protected_inputs = {
        campaign.adapter.path.resolve(),
        (profile_path if profile_path.is_absolute() else project_root / profile_path).resolve(),
        (ci_plan_path if ci_plan_path.is_absolute() else project_root / ci_plan_path).resolve(),
    }
    if output in protected_inputs:
        raise CampaignError("platform evidence output cannot overwrite a contract input")
    atomic_write_json(output, bundle)
    return bundle


def validate_platform_bundle(value: Any) -> dict[str, Any]:
    """Validate an untrusted bundle without consulting local campaign state."""

    if not isinstance(value, dict):
        raise CampaignError("platform evidence bundle root must be an object")
    expected = {
        "schemaVersion",
        "kind",
        "binding",
        "entry",
        "campaign",
        "cases",
        "bundleFingerprint",
    }
    if set(value) != expected:
        raise CampaignError("platform evidence bundle has invalid fields")
    if value.get("schemaVersion") != BUNDLE_SCHEMA_VERSION or value.get("kind") != BUNDLE_KIND:
        raise CampaignError("platform evidence bundle version is unsupported")
    if value.get("bundleFingerprint") != _bundle_fingerprint(value):
        raise CampaignError("platform evidence bundle fingerprint mismatch")

    binding = value.get("binding")
    binding_fields = {
        "commit",
        "sourceFingerprint",
        "verificationCatalogFingerprint",
        "profileFingerprint",
        "ciPlanFingerprint",
        "campaignCatalogFingerprint",
        "executionSourceFingerprint",
    }
    if not isinstance(binding, dict) or set(binding) != binding_fields:
        raise CampaignError("platform evidence binding has invalid fields")
    if not isinstance(binding.get("commit"), str) or COMMIT_PATTERN.fullmatch(binding["commit"]) is None:
        raise CampaignError("platform evidence commit is invalid")
    for field in binding_fields - {"commit"}:
        _require_hash(binding.get(field), "platform evidence " + field)

    raw_entry = value.get("entry")
    if not isinstance(raw_entry, dict):
        raise CampaignError("platform evidence entry is invalid")
    entry = {
        "id": _entry_id(raw_entry),
        "kind": _entry_kind(raw_entry),
        "platform": _entry_platform(raw_entry),
        "shardIndex": _entry_shard(raw_entry)[0],
        "shardCount": _entry_shard(raw_entry)[1],
        "caseIds": _entry_cases(raw_entry),
    }
    if raw_entry != entry:
        raise CampaignError("platform evidence entry is not canonical")

    campaign = value.get("campaign")
    if not isinstance(campaign, dict) or set(campaign) != {
        "id",
        "runtimePlatform",
        "finalRegressionAttemptId",
    }:
        raise CampaignError("platform evidence campaign binding is invalid")
    _require_nonempty_string(campaign.get("id"), "campaign id")
    _require_nonempty_string(
        campaign.get("finalRegressionAttemptId"), "final regression attempt id"
    )
    if campaign.get("runtimePlatform") != entry["platform"]:
        raise CampaignError("platform evidence runtime does not match its entry")

    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != len(entry["caseIds"]):
        raise CampaignError("platform evidence cases are incomplete")
    observed_ids: list[str] = []
    for item in cases:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "round",
            "status",
            "runId",
            "sourceFingerprintBefore",
            "sourceFingerprintAfter",
            "artifactDir",
            "artifactManifest",
            "evidence",
        }:
            raise CampaignError("platform evidence case has invalid fields")
        case_id = item.get("id")
        if not isinstance(case_id, str) or ENTRY_ID_PATTERN.fullmatch(case_id) is None:
            raise CampaignError("platform evidence case id is invalid")
        if item.get("round") != "regression" or item.get("status") != "PASS":
            raise CampaignError("platform evidence contains a non-final-PASS case")
        if (
            item.get("sourceFingerprintBefore")
            != binding["executionSourceFingerprint"]
            or item.get("sourceFingerprintAfter")
            != binding["executionSourceFingerprint"]
        ):
            raise CampaignError("platform evidence case source binding is inconsistent")
        _require_nonempty_string(item.get("runId"), "case run id")
        _require_relative_path(item.get("artifactDir"), "case artifact directory")
        manifest = item.get("artifactManifest")
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"relativePath", "size", "sha256"}
            or type(manifest.get("size")) is not int
            or manifest["size"] < 0
        ):
            raise CampaignError("platform evidence artifact manifest binding is invalid")
        _require_relative_path(
            manifest.get("relativePath"), "artifact manifest relativePath"
        )
        if manifest["relativePath"] != (
            item["artifactDir"] + "/artifact-manifest.json"
        ):
            raise CampaignError(
                "platform evidence artifact manifest path is inconsistent"
            )
        _require_hash(manifest.get("sha256"), "artifact manifest hash")
        evidence = item.get("evidence")
        evidence_fields = {
            "requiredFiles",
            "nonEmptyFiles",
            "missingFiles",
            "emptyFiles",
            "files",
            "secretLikeContent",
        }
        if (
            not isinstance(evidence, dict)
            or set(evidence) != evidence_fields
            or evidence.get("missingFiles")
            or evidence.get("emptyFiles")
            or evidence.get("secretLikeContent") is not False
            or not isinstance(evidence.get("files"), list)
        ):
            raise CampaignError("platform evidence case evidence is incomplete")
        for field in (
            "requiredFiles",
            "nonEmptyFiles",
            "missingFiles",
            "emptyFiles",
        ):
            values = evidence[field]
            if (
                not isinstance(values, list)
                or any(not isinstance(value, str) or not value for value in values)
                or len(values) != len(set(values))
            ):
                raise CampaignError(
                    "platform evidence case evidence paths are invalid"
                )
            for path in values:
                _require_relative_path(
                    path, "platform evidence case evidence path"
                )
        required_files = evidence["requiredFiles"]
        non_empty_files = evidence["nonEmptyFiles"]
        if not set(non_empty_files).issubset(required_files):
            raise CampaignError(
                "platform evidence non-empty files are not required files"
            )
        evidence_paths: set[str] = set()
        evidence_sizes: dict[str, int] = {}
        for evidence_file in evidence["files"]:
            if (
                not isinstance(evidence_file, dict)
                or set(evidence_file) != {"path", "size", "sha256"}
                or not isinstance(evidence_file.get("path"), str)
                or not evidence_file["path"]
                or evidence_file["path"] in evidence_paths
                or type(evidence_file.get("size")) is not int
                or evidence_file["size"] < 0
            ):
                raise CampaignError("platform evidence file binding is invalid")
            _require_relative_path(
                evidence_file.get("path"), "platform evidence file path"
            )
            _require_hash(evidence_file.get("sha256"), "evidence file hash")
            evidence_paths.add(evidence_file["path"])
            evidence_sizes[evidence_file["path"]] = evidence_file["size"]
        if evidence_paths != set(required_files):
            raise CampaignError(
                "platform evidence required-file bindings are incomplete"
            )
        if any(evidence_sizes[path] == 0 for path in non_empty_files):
            raise CampaignError(
                "platform evidence non-empty-file binding has zero size"
            )
        observed_ids.append(case_id)
    if observed_ids != entry["caseIds"] or len(observed_ids) != len(set(observed_ids)):
        raise CampaignError("platform evidence case order or coverage is invalid")
    assert_persistable(value)
    return copy.deepcopy(value)


def _discover_project_root(profile_path: Path) -> Path:
    """Use the aggregate command's working directory as explicit project context."""

    candidate = Path.cwd()
    if path_has_symlink_component(candidate):
        raise CampaignError("aggregate projectRoot uses a symlink/reparse path")
    root = Path(os.path.realpath(str(candidate)))
    supplied_profile = (
        profile_path if profile_path.is_absolute() else candidate / profile_path
    )
    if path_has_symlink_component(supplied_profile):
        raise CampaignError("verification profile uses a symlink/reparse path")
    resolved_profile = Path(os.path.realpath(str(supplied_profile)))
    if not is_within(resolved_profile, root):
        raise CampaignError("verification profile escapes aggregate projectRoot")
    return root


def _read_bundle(path: Path, project_root: Path) -> dict[str, Any]:
    candidate = path if path.is_absolute() else project_root / path
    if path_has_symlink_component(candidate):
        raise CampaignError("platform evidence path uses a symlink/reparse path")
    resolved = resolve_project_path(
        project_root, str(candidate), "platform evidence path"
    )
    try:
        if resolved.stat().st_size > MAX_JSON_BYTES:
            raise CampaignError("platform evidence bundle exceeds the safe size limit")
    except OSError as exc:
        raise CampaignError("platform evidence bundle cannot be inspected") from exc
    return validate_platform_bundle(read_json(resolved))


def _aggregation_digest(value: dict[str, Any]) -> str:
    payload = copy.deepcopy(value)
    payload.pop("aggregationFingerprint", None)
    return sha256_bytes(canonical_bytes(payload))


def _stable_error(error: BaseException, project_root: Path) -> str:
    message = str(error).replace(str(project_root), "<projectRoot>")
    return message.replace("\\", "/")[:2000]


def aggregate_platform_evidence(
    *,
    profile_path: Path,
    ci_plan_path: Path,
    bundle_paths: Iterable[Path],
    output_path: Path,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Aggregate exact plan coverage and return stable fail-closed diagnostics."""

    root = project_root or _discover_project_root(profile_path)
    profile, plan, expected_bindings = _load_contracts(
        profile_path, ci_plan_path, root
    )
    initial_profile_view = _view(profile, "verification profile")
    outputs = initial_profile_view.get("outputs")
    if not isinstance(outputs, dict):
        raise CampaignError(
            "verification profile does not declare an aggregation output"
        )
    declared_output = _safe_output_path(
        Path(
            _require_relative_path(
                outputs.get("aggregation"),
                "verification profile aggregation output",
            )
        ),
        root,
    )
    output = _safe_output_path(output_path, root)
    if output != declared_output:
        raise CampaignError(
            "aggregation output must match verification profile outputs.aggregation"
        )
    expected_source = _portable_source(root, profile)
    initial_plan_view = _view(plan, "CI plan")
    entries = _plan_entries(plan)
    required_platforms = _required_platforms(profile, plan)
    expected_by_id = {entry["id"]: entry for entry in entries}
    expected_case_ids = [case_id for entry in entries for case_id in entry["caseIds"]]
    paths = sorted(
        (Path(path) for path in bundle_paths),
        key=lambda path: path.as_posix(),
    )
    codes: list[str] = []
    errors: list[str] = []
    bundles: list[dict[str, Any]] = []
    for path in paths:
        try:
            bundles.append(_read_bundle(path, root))
        except CampaignError as exc:
            codes.append("BUNDLE_INVALID")
            errors.append(_stable_error(exc, root))
    bundles.sort(
        key=lambda bundle: (
            bundle["entry"]["id"],
            bundle["bundleFingerprint"],
        )
    )

    identity_fields = {
        "commit": "COMMIT_MISMATCH",
        "sourceFingerprint": "SOURCE_FINGERPRINT_MISMATCH",
        "verificationCatalogFingerprint": "VERIFICATION_CATALOG_FINGERPRINT_MISMATCH",
        "profileFingerprint": "PROFILE_FINGERPRINT_MISMATCH",
        "ciPlanFingerprint": "CI_PLAN_FINGERPRINT_MISMATCH",
    }
    expected_values = {
        "commit": expected_source["commit"],
        "sourceFingerprint": expected_source["sourceFingerprint"],
        "verificationCatalogFingerprint": expected_bindings[
            "verificationCatalogFingerprint"
        ],
        "profileFingerprint": expected_bindings["profileFingerprint"],
        "ciPlanFingerprint": expected_bindings["ciPlanFingerprint"],
    }
    first_binding = bundles[0]["binding"] if bundles else None
    for field, code in identity_fields.items():
        values = {
            bundle["binding"].get(field)
            for bundle in bundles
        }
        if len(values) > 1:
            codes.append(code)
            errors.append("platform evidence bundles disagree on " + field)
        expected = expected_values.get(field)
        if expected is not None and any(value != expected for value in values):
            codes.append(code)
            errors.append("platform evidence does not match current " + field)

    seen_entry_ids: set[str] = set()
    covered_entries: dict[str, dict[str, Any]] = {}
    observed_case_ids: list[str] = []
    observed_platforms: set[str] = set()
    for bundle in bundles:
        entry = bundle["entry"]
        entry_id = entry["id"]
        observed_case_ids.extend(item["id"] for item in bundle["cases"])
        if entry_id in seen_entry_ids:
            codes.append("ENTRY_DUPLICATE")
            errors.append("duplicate platform evidence entry: " + entry_id)
            continue
        seen_entry_ids.add(entry_id)
        expected_entry = expected_by_id.get(entry_id)
        if expected_entry is None or entry != expected_entry:
            codes.append("ENTRY_UNKNOWN")
            errors.append("platform evidence entry does not match the CI plan: " + entry_id)
            continue
        covered_entries[entry_id] = bundle
        observed_platforms.add(entry["platform"])

    missing_entries = sorted(set(expected_by_id) - set(covered_entries))
    if missing_entries:
        codes.append("ENTRY_MISSING")
        errors.append("missing platform evidence entries: " + ", ".join(missing_entries))
    missing_platforms = sorted(set(required_platforms) - observed_platforms)
    if missing_platforms:
        codes.append("REQUIRED_PLATFORM_MISSING")
        errors.append("missing required platforms: " + ", ".join(missing_platforms))

    observed_counts = {
        case_id: observed_case_ids.count(case_id) for case_id in set(observed_case_ids)
    }
    duplicate_cases = sorted(
        case_id for case_id, count in observed_counts.items() if count > 1
    )
    missing_cases = sorted(set(expected_case_ids) - set(observed_case_ids))
    unexpected_cases = sorted(set(observed_case_ids) - set(expected_case_ids))
    if duplicate_cases:
        codes.append("CASE_DUPLICATE")
        errors.append("duplicate final case evidence: " + ", ".join(duplicate_cases))
    if missing_cases:
        codes.append("CASE_MISSING")
        errors.append("missing final case evidence: " + ", ".join(missing_cases))
    if unexpected_cases:
        codes.append("CASE_UNEXPECTED")
        errors.append("unexpected final case evidence: " + ", ".join(unexpected_cases))

    try:
        observed_profile, observed_plan, observed_bindings = _load_contracts(
            profile_path, ci_plan_path, root
        )
        observed_source = _portable_source(root, observed_profile)
        contracts_stable = (
            observed_bindings == expected_bindings
            and observed_source == expected_source
            and _view(observed_profile, "verification profile")
            == initial_profile_view
            and _view(observed_plan, "CI plan") == initial_plan_view
        )
    except CampaignError as exc:
        contracts_stable = False
        errors.append(
            "verification contracts could not be rechecked: "
            + _stable_error(exc, root)
        )
    if not contracts_stable:
        codes.append("CONTRACT_DRIFT_DURING_AGGREGATION")
        if not any(
            message.startswith("verification contracts could not be rechecked")
            for message in errors
        ):
            errors.append("verification profile or CI plan changed during aggregation")

    rejection_codes = sorted(set(codes))
    result: dict[str, Any] = {
        "schemaVersion": AGGREGATION_SCHEMA_VERSION,
        "kind": AGGREGATION_KIND,
        "ok": not rejection_codes,
        "binding": {
            "commit": first_binding.get("commit") if first_binding else None,
            "sourceFingerprint": first_binding.get("sourceFingerprint")
            if first_binding
            else None,
            **expected_bindings,
        },
        "requiredPlatforms": required_platforms,
        "coveredPlatforms": sorted(observed_platforms),
        "expectedEntries": sorted(expected_by_id),
        "coveredEntries": sorted(covered_entries),
        "expectedCaseIds": expected_case_ids,
        "coveredCaseIds": observed_case_ids,
        "bundleFingerprints": sorted(
            bundle["bundleFingerprint"] for bundle in bundles
        ),
        "rejectionCodes": rejection_codes,
        "errors": errors,
    }
    result["aggregationFingerprint"] = _aggregation_digest(result)
    assert_persistable(result)
    protected_inputs = {
        (profile_path if profile_path.is_absolute() else root / profile_path).resolve(),
        (ci_plan_path if ci_plan_path.is_absolute() else root / ci_plan_path).resolve(),
    }
    protected_inputs.update(
        (path if path.is_absolute() else root / path).resolve() for path in paths
    )
    if output in protected_inputs:
        raise CampaignError("aggregation output cannot overwrite a contract or bundle input")
    atomic_write_json(output, result)
    return result


__all__ = [
    "aggregate_platform_evidence",
    "export_platform_evidence",
    "validate_platform_bundle",
]
