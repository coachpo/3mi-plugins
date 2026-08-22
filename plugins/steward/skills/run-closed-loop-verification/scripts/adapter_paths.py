"""Strict schema-version-one adapters and source fingerprints."""

from __future__ import annotations

import copy
import hashlib
import os
import re
import stat
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from model import (
    ADAPTER_SCHEMA_VERSION,
    SUPPORTED_CATEGORIES,
    SUPPORTED_PROVIDERS,
    AdapterError,
    CampaignError,
    assert_persistable,
    canonical_bytes,
    has_secret_like,
    parse_json_text,
    read_json,
    review_case_candidate_sha256,
    sha256_bytes,
)

SOURCE_READ_BYTES = 1024 * 1024
MAX_SOURCE_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_INTERNAL_STDOUT_BYTES = 64 * 1024 * 1024
MAX_INTERNAL_STDERR_BYTES = 1024 * 1024
MAX_SOURCE_ENTRIES = 500_000
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_INDEX_RECORD_PATTERN = re.compile(
    rb"([0-7]{6}) ([0-9a-f]{40}|[0-9a-f]{64}) ([0-3])\t(.*)",
    re.DOTALL,
)
CRITERION_ID_PATTERN = re.compile(r"^C[1-9][0-9]*$")
INVARIANT_ID_PATTERN = re.compile(r"^INV-[A-Z][A-Z0-9]*-[0-9A-F]{12}$")
REVIEW_FINDING_ID_PATTERN = re.compile(r"^RF-[A-Z0-9][A-Z0-9-]*$")
SCENARIO_TAGS = {"failure", "compatibility", "platform"}
RISK_TIER_CATEGORIES = (
    "smoke",
    "functional",
    "integration",
    "workflow",
    "role-play",
)
SOURCE_TEST_SUFFIXES = {
    ".c",
    ".cc",
    ".clj",
    ".cljs",
    ".cpp",
    ".cs",
    ".cxx",
    ".ex",
    ".exs",
    ".go",
    ".h",
    ".hh",
    ".hpp",
    ".hs",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".lua",
    ".mjs",
    ".php",
    ".pl",
    ".py",
    ".r",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".swift",
    ".test",
    ".ts",
    ".tsx",
    ".vue",
}
PLUGIN_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))

from goal_contract import (
    goal_contract_sha256,
    goal_contract_view,
    load_goal_contract,
)
from invariant_contract import (
    invariant_map_sha256,
    load_invariant_map,
    validate_project_references,
)
from semantic_review import (
    load_review_manifest,
    required_finding_ids,
    review_manifest_sha256,
    runner_inline_code_argv_indexes,
)

# Load the optional profile contract only when an adapter actually declares it.
# This keeps legacy adapters independent of the configuration layer and avoids
# an import cycle when that layer validates its base adapter through this module.
validate_adapter_verification = None


def _verification_validator():
    if validate_adapter_verification is not None:
        return validate_adapter_verification
    try:
        from verification_pipeline import (
            validate_adapter_verification as shared_validator,
        )
    except Exception as exc:
        raise AdapterError(
            "shared verification pipeline contracts are unavailable"
        ) from exc
    return shared_validator


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def path_has_traversal(value: str) -> bool:
    normalized = value.replace("\\", "/") if os.name == "nt" else value
    if "\x00" in normalized or normalized.startswith("/"):
        return True
    if re.match(r"^[A-Za-z]:/", normalized):
        return True
    return ".." in PurePosixPath(normalized).parts


def normalize_relative(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AdapterError(label + " must be a non-empty relative path")
    normalized = value.replace("\\", "/") if os.name == "nt" else value
    if path_has_traversal(normalized):
        raise AdapterError(label + " contains traversal or an absolute path")
    parts = [part for part in PurePosixPath(normalized).parts if part not in ("", ".")]
    return "." if not parts else "/".join(parts)


def validate_pinned_review_request(value: Any, label: str) -> dict[str, Any]:
    """Validate and return one canonical semantic Review request binding."""

    if not isinstance(value, dict) or set(value) != {
        "target",
        "requestedPaths",
        "requestSha256",
    }:
        raise AdapterError(label + " has invalid fields")
    target = value.get("target")
    if not isinstance(target, dict):
        raise AdapterError(label + ".target must be an object")
    kind = target.get("kind")
    target_fields = {
        "source": {"kind", "sourceFingerprint"},
        "diff": {
            "kind",
            "sourceFingerprint",
            "baseIdentity",
            "headIdentity",
        },
    }
    if kind not in target_fields or set(target) != target_fields[kind]:
        raise AdapterError(label + ".target has invalid fields")
    source_fingerprint = target.get("sourceFingerprint")
    if (
        not isinstance(source_fingerprint, str)
        or HASH_PATTERN.fullmatch(source_fingerprint) is None
    ):
        raise AdapterError(label + ".target.sourceFingerprint must be a sha256 digest")
    target_view: dict[str, Any] = {
        "kind": kind,
        "sourceFingerprint": source_fingerprint,
    }
    if kind == "diff":
        for field in ("baseIdentity", "headIdentity"):
            identity = target.get(field)
            if not isinstance(identity, str) or not identity:
                raise AdapterError(label + ".target." + field + " must be non-empty")
            target_view[field] = identity
    requested_paths = value.get("requestedPaths")
    if (
        not isinstance(requested_paths, list)
        or not requested_paths
        or any(not isinstance(path, str) for path in requested_paths)
    ):
        raise AdapterError(label + ".requestedPaths must be a non-empty string array")
    normalized_paths: list[str] = []
    for index, path in enumerate(requested_paths):
        if "\\" in path:
            raise AdapterError(
                label + f".requestedPaths[{index}] must be a POSIX relative path"
            )
        normalized = normalize_relative(
            path,
            label + f".requestedPaths[{index}]",
        )
        if normalized == "." or normalized != path:
            raise AdapterError(
                label + f".requestedPaths[{index}] is not a normalized project file"
            )
        normalized_paths.append(normalized)
    if normalized_paths != sorted(normalized_paths) or len(normalized_paths) != len(
        set(normalized_paths)
    ):
        raise AdapterError(label + ".requestedPaths must be sorted and unique")
    core = {
        "target": target_view,
        "requestedPaths": normalized_paths,
    }
    request_sha256 = value.get("requestSha256")
    if request_sha256 != sha256_bytes(canonical_bytes(core)):
        raise AdapterError(
            label + ".requestSha256 does not match the canonical request binding"
        )
    return {**core, "requestSha256": request_sha256}


def rebind_review_request_source(
    value: Any,
    source_fingerprint: str,
    label: str = "review request binding",
) -> dict[str, Any]:
    """Rebind only the source identity of an already validated request."""

    request = validate_pinned_review_request(value, label)
    if (
        not isinstance(source_fingerprint, str)
        or HASH_PATTERN.fullmatch(source_fingerprint) is None
    ):
        raise AdapterError(label + " source fingerprint must be a sha256 digest")
    target = copy.deepcopy(request["target"])
    target["sourceFingerprint"] = source_fingerprint
    core = {
        "target": target,
        "requestedPaths": list(request["requestedPaths"]),
    }
    rebound = {
        **core,
        "requestSha256": sha256_bytes(canonical_bytes(core)),
    }
    return validate_pinned_review_request(rebound, label)


def resolve_project_path(root: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise AdapterError(label + " must be a path string")
    if "\x00" in value:
        raise AdapterError(label + " contains a NUL character")
    if not Path(value).is_absolute() and path_has_traversal(value):
        raise AdapterError(label + " contains traversal")
    candidate = Path(value) if Path(value).is_absolute() else root / value
    resolved = Path(os.path.realpath(str(candidate)))
    root_real = Path(os.path.realpath(str(root)))
    if not is_within(resolved, root_real):
        raise AdapterError(label + " escapes projectRoot")
    return resolved


def relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise CampaignError("path escapes projectRoot") from exc


def path_uses_symlink(path: Path, root: Path) -> bool:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return True
    current = root.absolute()
    root_is_system_anchor = current == Path(current.anchor or os.sep)
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
            is_link = stat.S_ISLNK(metadata.st_mode)
            is_reparse = bool(
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            )
            if is_link or is_reparse:
                trusted_darwin_aliases = {
                    "/var": "/private/var",
                    "/tmp": "/private/tmp",
                    "/etc": "/private/etc",
                }
                if (
                    root_is_system_anchor
                    and sys.platform == "darwin"
                    and str(current) in trusted_darwin_aliases
                    and os.path.realpath(str(current))
                    == trusted_darwin_aliases[str(current)]
                ):
                    continue
                return True
        except FileNotFoundError:
            continue
        except OSError:
            return True
    return False


def path_has_symlink_component(path: Path) -> bool:
    """Inspect every existing component from the filesystem anchor."""

    try:
        absolute = path.absolute()
        anchor = Path(absolute.anchor or os.sep)
        return path_uses_symlink(absolute, anchor)
    except (OSError, ValueError) as exc:
        raise AdapterError("path cannot be inspected safely") from exc


def reject_nul_strings(value: Any, label: str = "adapter") -> None:
    if isinstance(value, str):
        if "\x00" in value:
            raise AdapterError(label + " contains a NUL character")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            reject_nul_strings(key, label)
            reject_nul_strings(item, label)
    elif isinstance(value, list):
        for item in value:
            reject_nul_strings(item, label)


def covers_exclude(exclude: str, relative: str) -> bool:
    ex = (exclude.replace("\\", "/") if os.name == "nt" else exclude).rstrip("/")
    rel = (relative.replace("\\", "/") if os.name == "nt" else relative).rstrip("/")
    if ex.endswith("/**"):
        ex = ex[:-3].rstrip("/")
    return rel == ex or rel.startswith(ex + "/")


def current_platform() -> str:
    if sys.platform.startswith("darwin"):
        return "darwin"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    if os.name == "posix":
        return "posix"
    return "windows" if os.name == "nt" else "posix"


def platform_supported_on(value: str, pinned_runtime: str) -> bool:
    """Evaluate a case platform against a journal-pinned runtime."""

    if value == "any":
        return True
    if not isinstance(pinned_runtime, str):
        return False
    if value == pinned_runtime:
        return True
    return value == "posix" and pinned_runtime in {"darwin", "linux", "posix"}


def platform_supported(value: str) -> bool:
    if value == "posix":
        return os.name == "posix"
    return platform_supported_on(value, current_platform())


class Adapter:
    def __init__(
        self,
        path: Path,
        data: dict[str, Any],
        project_root: Path,
        campaign_root: Path,
        excludes: list[str],
        catalog_fingerprint: str,
        traceability: dict[str, Any] | None = None,
        trace_input_errors: list[str] | None = None,
        goal_criteria_ids: set[str] | None = None,
        hard_invariant_ids: set[str] | None = None,
        review_finding_ids: set[str] | None = None,
        required_finding_ids: set[str] | None = None,
        finding_resolution_states: dict[str, str] | None = None,
        finding_criteria_ids: dict[str, set[str]] | None = None,
        finding_invariant_ids: dict[str, set[str]] | None = None,
        finding_required_flags: dict[str, bool] | None = None,
        finding_case_candidate_sha256s: dict[str, str] | None = None,
        finding_case_candidates: dict[str, dict[str, Any]] | None = None,
        finding_source_references: dict[str, list[dict[str, str]]] | None = None,
        review_attestation: dict[str, Any] | None = None,
        review_request: dict[str, Any] | None = None,
        review_bindings_verified: bool = False,
        trace_snapshot: dict[str, Any] | None = None,
        verification: dict[str, Any] | None = None,
    ) -> None:
        self.path = path
        self.data = data
        self.project_root = project_root
        self.campaign_root = campaign_root
        self.excludes = excludes
        self.catalog_fingerprint = catalog_fingerprint
        self.cases: list[dict[str, Any]] = data["cases"]
        self.case_by_id = {case["id"]: case for case in self.cases}
        self.traceability = traceability
        self.trace_input_errors = list(trace_input_errors or [])
        self.goal_criteria_ids = set(goal_criteria_ids or set())
        self.hard_invariant_ids = set(hard_invariant_ids or set())
        self.review_finding_ids = set(review_finding_ids or set())
        self.required_finding_ids = set(required_finding_ids or set())
        self.finding_resolution_states = dict(finding_resolution_states or {})
        self.finding_criteria_ids = {
            finding_id: set(criteria_ids)
            for finding_id, criteria_ids in (finding_criteria_ids or {}).items()
        }
        self.finding_invariant_ids = {
            finding_id: set(invariant_ids)
            for finding_id, invariant_ids in (finding_invariant_ids or {}).items()
        }
        self.finding_required_flags = dict(finding_required_flags or {})
        self.finding_case_candidate_sha256s = dict(
            finding_case_candidate_sha256s or {}
        )
        self.finding_case_candidates = copy.deepcopy(finding_case_candidates or {})
        self.finding_source_references = {
            finding_id: [dict(reference) for reference in references]
            for finding_id, references in (finding_source_references or {}).items()
        }
        self.review_attestation = copy.deepcopy(review_attestation)
        self.review_request = copy.deepcopy(review_request)
        self.review_bindings_verified = review_bindings_verified is True
        self.trace_snapshot = trace_snapshot
        self.verification = copy.deepcopy(verification)

    @property
    def coverage_mode(self) -> str:
        return self.data.get("coverageMode", "narrow")

    def coverage_summary(self) -> dict[str, Any]:
        present = sorted(
            {
                case["category"]
                for case in self.cases
                if case.get("required", True)
            }
        )
        missing = sorted(set(RISK_TIER_CATEGORIES) - set(present))
        return {
            "mode": self.coverage_mode,
            "presentTiers": present,
            "missingTiers": missing,
            "outOfScopeTiers": missing if self.coverage_mode == "narrow" else [],
        }

    def case_metadata(self) -> list[dict[str, Any]]:
        metadata = []
        for case in self.cases:
            evidence = case.get("evidence") or {}
            metadata.append(
                {
                    "id": case["id"],
                    "category": case["category"],
                    "required": bool(case.get("required", True)),
                    "platform": case.get("platform", "any"),
                    "dependsOn": list(case.get("dependsOn", [])),
                    "evidence": {
                        "requiredFiles": list(evidence.get("requiredFiles", [])),
                        "nonEmptyFiles": list(evidence.get("nonEmptyFiles", [])),
                    },
                }
            )
        return metadata


def validate_evidence_contract(case_id: str, evidence: Any) -> dict[str, list[str]]:
    if evidence is None:
        evidence = {}
    if not isinstance(evidence, dict):
        raise AdapterError("case " + case_id + " evidence must be an object")
    unknown = sorted(set(evidence) - {"requiredFiles", "nonEmptyFiles"})
    if unknown:
        raise AdapterError(
            "case " + case_id + " evidence has unknown fields: " + ", ".join(unknown)
        )
    result: dict[str, list[str]] = {}
    for key in ("requiredFiles", "nonEmptyFiles"):
        values = evidence.get(key, [])
        if not isinstance(values, list) or any(
            not isinstance(item, str) for item in values
        ):
            raise AdapterError(
                "case " + case_id + " evidence." + key + " must be a string array"
            )
        normalized = []
        for item in values:
            rel = normalize_relative(item, "case " + case_id + " evidence file")
            if rel == ".":
                raise AdapterError(
                    "case " + case_id + " evidence cannot name its directory"
                )
            normalized.append(rel)
        result[key] = sorted(set(normalized))
    non_empty = set(result["nonEmptyFiles"])
    result["requiredFiles"] = sorted(set(result["requiredFiles"]) | non_empty)
    return result


def validate_unique_id_array(
    value: Any,
    label: str,
    pattern: re.Pattern[str],
) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AdapterError(label + " must be a string array")
    if any(pattern.fullmatch(item) is None for item in value):
        raise AdapterError(label + " contains an invalid ID")
    if len(value) != len(set(value)):
        raise AdapterError(label + " contains duplicate IDs")
    return list(value)


def _trace_reference_path(
    project_root: Path,
    campaign_root: Path,
    reference: dict[str, Any],
    label: str,
) -> Path:
    relative = normalize_relative(reference["path"], label + ".path")
    if relative == ".":
        raise AdapterError(label + ".path cannot name projectRoot")
    unresolved = project_root / relative
    if path_uses_symlink(unresolved, project_root):
        raise AdapterError(label + ".path uses a symlink/reparse path")
    resolved = resolve_project_path(project_root, relative, label + ".path")
    if is_within(resolved, campaign_root):
        raise AdapterError(label + ".path cannot be inside campaignRoot")
    if not resolved.is_file():
        raise AdapterError(label + ".path must be an existing file")
    return resolved


def _validate_trace_reference(
    value: Any,
    label: str,
    *,
    goal: bool = False,
    review: bool = False,
) -> dict[str, Any]:
    expected = {"path", "sha256"} | ({"contractVersion"} if goal else set())
    if review and isinstance(value, dict) and "reviewRequestSha256" in value:
        expected.add("reviewRequestSha256")
    if not isinstance(value, dict) or set(value) != expected:
        raise AdapterError(label + " has invalid fields")
    if not isinstance(value.get("path"), str) or not value["path"]:
        raise AdapterError(label + ".path must be a non-empty relative path")
    if not isinstance(value.get("sha256"), str) or HASH_PATTERN.fullmatch(
        value["sha256"]
    ) is None:
        raise AdapterError(label + ".sha256 must be a sha256 digest")
    if goal and (
        type(value.get("contractVersion")) is not int
        or value["contractVersion"] != 1
    ):
        raise AdapterError(label + ".contractVersion must be 1")
    if review and "reviewRequestSha256" in value and (
        not isinstance(value["reviewRequestSha256"], str)
        or HASH_PATTERN.fullmatch(value["reviewRequestSha256"]) is None
    ):
        raise AdapterError(label + ".reviewRequestSha256 must be a sha256 digest")
    return value


def review_manifest_observation(manifest: Any) -> dict[str, Any]:
    """Project a validated semantic Review into closed-loop consumer fields."""

    finding_case_candidates = {
        item.id: item.case_candidate for item in manifest.findings
    }
    manifest_attestation = getattr(manifest, "attestation", None)
    manifest_request = getattr(manifest, "review_request", None)
    request_view = copy.deepcopy(
        getattr(manifest_request, "view", manifest_request)
    )
    return {
        "reviewFindingIds": {item.id for item in manifest.findings},
        "requiredFindingIds": set(required_finding_ids(manifest)),
        "findingResolutionStates": {
            item.id: item.resolution_state for item in manifest.findings
        },
        "findingCriteriaIds": {
            item.id: set(item.view["criteriaIds"]) for item in manifest.findings
        },
        "findingInvariantIds": {
            item.id: set(item.view["invariantIds"]) for item in manifest.findings
        },
        "findingRequiredFlags": {
            item.id: bool(item.view["required"]) for item in manifest.findings
        },
        "findingCaseCandidates": finding_case_candidates,
        "findingCaseCandidateSha256s": {
            finding_id: review_case_candidate_sha256(candidate)
            for finding_id, candidate in finding_case_candidates.items()
        },
        "findingSourceReferences": {
            item.id: [
                *[
                    {
                        "field": "primary evidence",
                        "path": evidence["location"]["path"],
                    }
                    for evidence in item.view["evidence"]
                ],
                *[
                    {
                        "field": "triggerPath",
                        "path": step["location"]["path"],
                    }
                    for step in item.view["triggerPath"]
                ],
                *[
                    {
                        "field": "runner source evidence",
                        "path": evidence["location"]["path"],
                    }
                    for evidence in (
                        (item.case_candidate.get("runner") or {}).get(
                            "sourceEvidence", []
                        )
                    )
                ],
            ]
            for item in manifest.findings
        },
        "reviewAttestation": copy.deepcopy(
            getattr(manifest_attestation, "view", manifest_attestation)
        ),
        "reviewRequest": request_view,
        "reviewRequestSha256": (
            request_view.get("requestSha256")
            if isinstance(request_view, dict)
            else None
        ),
        "reviewBindingsVerified": bool(
            getattr(manifest, "bindings_verified", False)
        ),
    }


def observe_traceability(
    project_root: Path,
    campaign_root: Path,
    traceability: dict[str, Any],
    *,
    observe_trace_drift: bool = False,
) -> dict[str, Any]:
    """Load versioned trace inputs and return IDs plus stable drift diagnostics."""

    result: dict[str, Any] = {
        "errors": [],
        "goalCriteriaIds": set(),
        "hardInvariantIds": set(),
        "reviewFindingIds": set(),
        "requiredFindingIds": set(),
        "findingResolutionStates": {},
        "findingCriteriaIds": {},
        "findingInvariantIds": {},
        "findingRequiredFlags": {},
        "findingCaseCandidateSha256s": {},
        "findingCaseCandidates": {},
        "findingSourceReferences": {},
        "reviewAttestation": None,
        "reviewRequest": None,
        "reviewRequestSha256": None,
        "reviewBindingsVerified": False,
    }

    def record(label: str, expected: str, observed: str) -> None:
        if observed != expected:
            result["errors"].append(
                label + " digest mismatch: expected " + expected + ", observed " + observed
            )

    try:
        reference = traceability["goalContract"]
        path = _trace_reference_path(
            project_root, campaign_root, reference, "traceability.goalContract"
        )
        contract = load_goal_contract(path)
        view = goal_contract_view(contract)
        if view.get("schemaVersion") != reference["contractVersion"]:
            result["errors"].append("goal contract version mismatch")
        observed = goal_contract_sha256(contract)
        record("goal contract", reference["sha256"], observed)
        result["goalCriteriaIds"] = {
            item.id for item in contract.completion_criteria
        }
    except Exception as exc:
        result["errors"].append("goal contract could not be observed: " + str(exc))

    try:
        reference = traceability["invariants"]
        path = _trace_reference_path(
            project_root, campaign_root, reference, "traceability.invariants"
        )
        profiles_root = PLUGIN_SCRIPTS.parent / "references" / "architecture-profiles"
        invariant_map = load_invariant_map(
            path,
            profiles_root=profiles_root,
            project_root=project_root,
        )
        observed = invariant_map_sha256(invariant_map)
        record("invariant map", reference["sha256"], observed)
        for error in validate_project_references(project_root, invariant_map):
            result["errors"].append(
                "invariant project reference is invalid: " + error
            )
        required_ids = getattr(invariant_map, "triggered_hard_invariant_ids", None)
        if required_ids is None:
            required_ids = getattr(invariant_map, "hard_invariant_ids")
        result["hardInvariantIds"] = set(required_ids)
    except Exception as exc:
        result["errors"].append("invariant map could not be observed: " + str(exc))

    try:
        reference = traceability["reviewFindings"]
        path = _trace_reference_path(
            project_root, campaign_root, reference, "traceability.reviewFindings"
        )
        manifest = load_review_manifest(
            path,
            project_root=project_root,
            verify_baseline=not observe_trace_drift,
        )
        observed = review_manifest_sha256(manifest)
        record("review findings", reference["sha256"], observed)
        observation = review_manifest_observation(manifest)
        pinned_request_sha256 = reference.get("reviewRequestSha256")
        request = observation["reviewRequest"]
        if pinned_request_sha256 is not None and not isinstance(request, dict):
            result["errors"].append(
                "REVIEW_REQUEST_REQUIRED: traceability pins a Review request but "
                "the manifest does not contain reviewRequest"
            )
        elif isinstance(request, dict) and pinned_request_sha256 is None:
            result["errors"].append(
                "REVIEW_REQUEST_REQUIRED: manifest.reviewRequest requires "
                "traceability.reviewFindings.reviewRequestSha256"
            )
        elif isinstance(request, dict):
            canonical_request = validate_pinned_review_request(
                request,
                "review manifest.reviewRequest",
            )
            if canonical_request["requestSha256"] != pinned_request_sha256:
                result["errors"].append(
                    "REVIEW_REQUEST_MISMATCH: manifest.reviewRequest does not match "
                    "the pinned traceability request digest"
                )
            else:
                manifest = load_review_manifest(
                    path,
                    project_root=project_root,
                    verify_baseline=not observe_trace_drift,
                    expected_review_request=canonical_request,
                )
                stable_observed = review_manifest_sha256(manifest)
                if stable_observed != observed:
                    result["errors"].append(
                        "REVIEW_REQUEST_MISMATCH: review manifest changed while its "
                        "request binding was validated"
                    )
                else:
                    observation = review_manifest_observation(manifest)
        result.update(observation)
    except Exception as exc:
        result["errors"].append("review findings could not be observed: " + str(exc))
    attestation = result["reviewAttestation"]
    if isinstance(attestation, dict):
        if attestation.get("outcome") == "incomplete":
            result["errors"].append(
                "REVIEW_ATTESTATION_INCOMPLETE: closed-loop verification cannot "
                "consume an incomplete semantic Review"
            )
        if attestation.get("goalContractSha256") != traceability["goalContract"][
            "sha256"
        ]:
            result["errors"].append(
                "review attestation goalContractSha256 does not match the pinned goal contract"
            )
        if attestation.get("invariantsSha256") != traceability["invariants"][
            "sha256"
        ]:
            result["errors"].append(
                "review attestation invariantsSha256 does not match the pinned invariant map"
            )
    return result


def validate_adapter(
    adapter_path: Path,
    *,
    observe_trace_drift: bool = False,
) -> Adapter:
    if "\x00" in str(adapter_path):
        raise AdapterError("adapter path contains a NUL character")
    try:
        supplied_adapter_path = adapter_path.absolute()
    except (OSError, ValueError) as exc:
        raise AdapterError("adapter path cannot be resolved") from exc
    if path_has_symlink_component(supplied_adapter_path):
        raise AdapterError("adapter file uses a symlink/reparse path")
    adapter_path = Path(os.path.realpath(str(supplied_adapter_path)))
    if not adapter_path.is_file():
        raise AdapterError("adapter file does not exist: " + str(adapter_path))
    data = read_json(adapter_path)
    if not isinstance(data, dict):
        raise AdapterError("adapter root must be a JSON object")
    reject_nul_strings(data)
    if (
        type(data.get("schemaVersion")) is not int
        or data["schemaVersion"] != ADAPTER_SCHEMA_VERSION
    ):
        raise AdapterError("adapter schemaVersion must be 1")
    allowed_top = {
        "schemaVersion",
        "projectId",
        "projectRoot",
        "campaignRoot",
        "source",
        "localOnly",
        "cases",
        "traceability",
        "verification",
        "coverageMode",
    }
    unknown_top = sorted(set(data) - allowed_top)
    if unknown_top:
        raise AdapterError("adapter has unknown fields: " + ", ".join(unknown_top))
    for key in (
        "projectId",
        "projectRoot",
        "campaignRoot",
        "source",
        "localOnly",
        "cases",
    ):
        if key not in data:
            raise AdapterError("adapter missing " + key)
    if not isinstance(data["projectId"], str) or not data["projectId"].strip():
        raise AdapterError("projectId must be a non-empty string")
    coverage_mode = data.get("coverageMode", "narrow")
    if not isinstance(coverage_mode, str) or coverage_mode not in {
        "narrow",
        "full",
    }:
        raise AdapterError("coverageMode must be narrow or full")

    project_value = data["projectRoot"]
    if not isinstance(project_value, str) or not project_value:
        raise AdapterError("projectRoot must be a path string")
    project_candidate = (
        Path(project_value)
        if Path(project_value).is_absolute()
        else adapter_path.parent / project_value
    )
    if path_has_symlink_component(project_candidate):
        raise AdapterError("projectRoot uses a symlink/reparse path")
    project_root = Path(os.path.realpath(str(project_candidate)))
    if not project_root.is_dir():
        raise AdapterError("projectRoot must be an existing directory")

    campaign_root = resolve_project_path(
        project_root, data["campaignRoot"], "campaignRoot"
    )
    if path_uses_symlink(project_root / data["campaignRoot"], project_root):
        raise AdapterError("campaignRoot uses a symlink/reparse path")
    if campaign_root == project_root:
        raise AdapterError("campaignRoot cannot be projectRoot")

    source = data["source"]
    if not isinstance(source, dict):
        raise AdapterError("source must be an object")
    unknown_source = sorted(set(source) - {"provider", "manifest", "files", "excludes"})
    if unknown_source:
        raise AdapterError("source has unknown fields: " + ", ".join(unknown_source))
    provider = source.get("provider")
    if not isinstance(provider, str):
        raise AdapterError("source.provider must be git, manifest, or files")
    if provider not in SUPPORTED_PROVIDERS:
        raise AdapterError("source.provider must be git, manifest, or files")
    if provider != "manifest" and "manifest" in source:
        raise AdapterError("source.manifest is only valid for the manifest provider")
    if provider != "files" and "files" in source:
        raise AdapterError("source.files is only valid for the files provider")
    excludes_raw = source.get("excludes", [])
    if not isinstance(excludes_raw, list) or any(
        not isinstance(item, str) for item in excludes_raw
    ):
        raise AdapterError("source.excludes must be a string array")
    excludes: list[str] = []
    for item in excludes_raw:
        if not item:
            raise AdapterError("source.excludes cannot contain an empty path")
        normalized = item.replace("\\", "/") if os.name == "nt" else item
        if normalized.endswith("/**"):
            base = normalized[:-3].rstrip("/")
        else:
            base = normalized.rstrip("/")
        normalized_base = normalize_relative(base, "source exclude")
        if normalized_base == ".":
            raise AdapterError("source.excludes cannot exclude the whole project root")
        excludes.append(normalized_base + ("/**" if normalized.endswith("/**") else ""))
    campaign_relative = relative_to_root(project_root, campaign_root)
    if not any(covers_exclude(item, campaign_relative) for item in excludes):
        raise AdapterError("campaignRoot must be explicitly covered by source.excludes")

    local_only = data["localOnly"]
    if not isinstance(local_only, dict):
        raise AdapterError("localOnly must be an object")
    unknown_local = sorted(set(local_only) - {"enabled", "allowedExternalCapabilities"})
    if unknown_local:
        raise AdapterError("localOnly has unknown fields: " + ", ".join(unknown_local))
    if local_only.get("enabled") is not True:
        raise AdapterError("localOnly.enabled must be true")
    allowed = local_only.get("allowedExternalCapabilities", [])
    if not isinstance(allowed, list) or any(
        not isinstance(item, str) or not item for item in allowed
    ):
        raise AdapterError(
            "localOnly.allowedExternalCapabilities must be a string array"
        )

    cases = data["cases"]
    if not isinstance(cases, list) or not cases:
        raise AdapterError("cases must be a non-empty array")
    ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise AdapterError("case " + str(index) + " must be an object")
        allowed_case = {
            "id",
            "category",
            "required",
            "platform",
            "dependsOn",
            "argv",
            "cwd",
            "timeoutSeconds",
            "fixture",
            "externalCapabilities",
            "evidence",
            "coversCriteria",
            "coversInvariants",
            "reviewFindingIds",
            "quick",
            "scenarioTags",
        }
        unknown_case = sorted(set(case) - allowed_case)
        if unknown_case:
            raise AdapterError("case has unknown fields: " + ", ".join(unknown_case))
        case_id = case.get("id")
        if not isinstance(case_id, str) or not re.match(r"^[A-Za-z0-9._-]+$", case_id):
            raise AdapterError(
                "case IDs must use letters, digits, dot, underscore, or hyphen"
            )
        if case_id in ids:
            raise AdapterError("duplicate case id: " + case_id)
        ids.add(case_id)
        category = case.get("category")
        if not isinstance(category, str) or category not in SUPPORTED_CATEGORIES:
            raise AdapterError("case " + case_id + " has an unsupported category")
        if not isinstance(case.get("required", True), bool):
            raise AdapterError("case " + case_id + " required must be a boolean")
        if not isinstance(case.get("quick", False), bool):
            raise AdapterError("case " + case_id + " quick must be a boolean")
        validate_unique_id_array(
            case.get("coversCriteria", []),
            "case " + case_id + " coversCriteria",
            CRITERION_ID_PATTERN,
        )
        validate_unique_id_array(
            case.get("coversInvariants", []),
            "case " + case_id + " coversInvariants",
            INVARIANT_ID_PATTERN,
        )
        validate_unique_id_array(
            case.get("reviewFindingIds", []),
            "case " + case_id + " reviewFindingIds",
            REVIEW_FINDING_ID_PATTERN,
        )
        scenario_tags = case.get("scenarioTags", [])
        if (
            not isinstance(scenario_tags, list)
            or any(not isinstance(item, str) for item in scenario_tags)
            or len(scenario_tags) != len(set(scenario_tags))
            or not set(scenario_tags).issubset(SCENARIO_TAGS)
        ):
            raise AdapterError(
                "case " + case_id + " scenarioTags must be unique supported values"
            )
        platform = case.get("platform", "any")
        if not isinstance(platform, str) or platform not in {
            "any",
            "darwin",
            "windows",
            "linux",
            "posix",
        }:
            raise AdapterError("case " + case_id + " platform is unsupported")
        argv = case.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(item, str) for item in argv)
        ):
            raise AdapterError(
                "case " + case_id + " argv must be a non-empty string array"
            )
        if not argv[0]:
            raise AdapterError("case " + case_id + " argv executable must be non-empty")
        if any(has_secret_like(item) for item in argv):
            raise AdapterError("case " + case_id + " contains secret-like argv")
        secret_options = re.compile(
            r"^--?(?:api[-_]?key|access[-_]?token|auth[-_]?token|token|password|passwd|secret|credential|private[-_]?key)$",
            re.IGNORECASE,
        )
        if any(secret_options.match(argv[index]) for index in range(len(argv) - 1)):
            raise AdapterError(
                "case " + case_id + " contains a secret-bearing argv option"
            )
        forbidden = {key for key in ("shell", "command", "env") if key in case}
        if forbidden:
            raise AdapterError("case " + case_id + " uses forbidden command fields")
        timeout = case.get("timeoutSeconds", 60)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not __import__("math").isfinite(timeout)
            or timeout <= 0
        ):
            raise AdapterError("case " + case_id + " timeoutSeconds must be positive")
        if timeout > 7 * 24 * 60 * 60:
            raise AdapterError(
                "case " + case_id + " timeoutSeconds is unreasonably large"
            )
        cwd = case.get("cwd", ".")
        if not isinstance(cwd, str):
            raise AdapterError("case " + case_id + " cwd must be a path string")
        if path_uses_symlink(project_root / cwd, project_root):
            raise AdapterError("case " + case_id + " cwd uses a symlink/reparse path")
        cwd_path = resolve_project_path(project_root, cwd, "case " + case_id + " cwd")
        if not cwd_path.is_dir():
            raise AdapterError("case " + case_id + " cwd must be an existing directory")
        depends = case.get("dependsOn", [])
        if not isinstance(depends, list) or any(
            not isinstance(item, str) for item in depends
        ):
            raise AdapterError("case " + case_id + " dependsOn must be a string array")
        case["evidence"] = validate_evidence_contract(case_id, case.get("evidence"))
        capabilities = case.get("externalCapabilities", [])
        if not isinstance(capabilities, list) or any(
            not isinstance(item, str) or not item for item in capabilities
        ):
            raise AdapterError(
                "case " + case_id + " externalCapabilities must be a string array"
            )
        if not set(capabilities).issubset(set(allowed)):
            raise AdapterError(
                "case "
                + case_id
                + " requests an external capability not allowed by localOnly"
            )
        fixture = case.get("fixture")
        if isinstance(fixture, str) and fixture:
            if path_uses_symlink(project_root / fixture, project_root):
                raise AdapterError(
                    "case " + case_id + " fixture uses a symlink/reparse path"
                )
            fixture_path = resolve_project_path(
                project_root, fixture, "case " + case_id + " fixture"
            )
            if not fixture_path.exists():
                raise AdapterError("case " + case_id + " fixture path does not exist")
        elif fixture is not None and not isinstance(fixture, dict):
            raise AdapterError(
                "case " + case_id + " fixture must be null, a path, or an object"
            )

    for case in cases:
        for dependency in case.get("dependsOn", []):
            if dependency not in ids:
                raise AdapterError(
                    "case " + case["id"] + " depends on unknown case " + dependency
                )
            if [item["id"] for item in cases].index(dependency) >= [
                item["id"] for item in cases
            ].index(case["id"]):
                raise AdapterError("case dependencies must point to an earlier case")
            if case.get("quick", False) and not next(
                item for item in cases if item["id"] == dependency
            ).get("quick", False):
                raise AdapterError("quick case dependencies must also be quick")

    present_tiers = {
        case["category"] for case in cases if case.get("required", True)
    }
    missing_tiers = sorted(set(RISK_TIER_CATEGORIES) - present_tiers)
    if coverage_mode == "full" and missing_tiers:
        raise AdapterError(
            "coverageMode full requires all risk tiers to have a required case; missing: "
            + ", ".join(missing_tiers)
        )

    traceability = data.get("traceability")
    trace_observation = {
        "errors": [],
        "goalCriteriaIds": set(),
        "hardInvariantIds": set(),
        "reviewFindingIds": set(),
        "requiredFindingIds": set(),
        "findingResolutionStates": {},
        "findingCriteriaIds": {},
        "findingInvariantIds": {},
        "findingRequiredFlags": {},
        "findingCaseCandidateSha256s": {},
        "findingCaseCandidates": {},
        "findingSourceReferences": {},
        "reviewAttestation": None,
        "reviewRequest": None,
        "reviewRequestSha256": None,
        "reviewBindingsVerified": False,
    }
    trace_snapshot: dict[str, Any] | None = None
    if traceability is not None:
        if not isinstance(traceability, dict):
            raise AdapterError("traceability must be an object")
        allowed_trace = {
            "goalContract",
            "invariants",
            "reviewFindings",
            "requiredScenarios",
        }
        if set(traceability) - allowed_trace:
            raise AdapterError("traceability has unknown fields")
        for field in ("goalContract", "invariants", "reviewFindings"):
            if field not in traceability:
                raise AdapterError("traceability missing " + field)
        _validate_trace_reference(
            traceability["goalContract"],
            "traceability.goalContract",
            goal=True,
        )
        _validate_trace_reference(
            traceability["invariants"], "traceability.invariants"
        )
        _validate_trace_reference(
            traceability["reviewFindings"],
            "traceability.reviewFindings",
            review=True,
        )
        scenarios = traceability.get("requiredScenarios", [])
        if (
            not isinstance(scenarios, list)
            or any(not isinstance(item, str) for item in scenarios)
            or len(scenarios) != len(set(scenarios))
            or not set(scenarios).issubset(SCENARIO_TAGS)
        ):
            raise AdapterError(
                "traceability.requiredScenarios must be unique supported values"
            )
        trace_observation = observe_traceability(
            project_root,
            campaign_root,
            traceability,
            observe_trace_drift=observe_trace_drift,
        )
        if trace_observation["errors"] and not observe_trace_drift:
            raise AdapterError(trace_observation["errors"][0])
        if not trace_observation["errors"]:
            criteria_ids = trace_observation["goalCriteriaIds"]
            invariant_ids = trace_observation["hardInvariantIds"]
            finding_ids = trace_observation["reviewFindingIds"]
            for finding_id in sorted(finding_ids):
                if not trace_observation["findingCriteriaIds"][finding_id].issubset(
                    criteria_ids
                ):
                    raise AdapterError(
                        "review finding "
                        + finding_id
                        + " references an unknown goal criterion"
                    )
                if not trace_observation["findingInvariantIds"][
                    finding_id
                ].issubset(invariant_ids):
                    raise AdapterError(
                        "review finding "
                        + finding_id
                        + " references an unknown triggered hard invariant"
                    )
            for case in cases:
                if not set(case.get("coversCriteria", [])).issubset(criteria_ids):
                    raise AdapterError(
                        "case " + case["id"] + " references an unknown goal criterion"
                    )
                if not set(case.get("coversInvariants", [])).issubset(
                    invariant_ids
                ):
                    raise AdapterError(
                        "case " + case["id"] + " references an unknown hard invariant"
                    )
                if not set(case.get("reviewFindingIds", [])).issubset(finding_ids):
                    raise AdapterError(
                        "case " + case["id"] + " references an unknown review finding"
                    )
                for finding_id in case.get("reviewFindingIds", []):
                    candidate = trace_observation["findingCaseCandidates"][
                        finding_id
                    ]
                    if candidate["id"] != case["id"]:
                        raise AdapterError(
                            "case "
                            + case["id"]
                            + " does not match review finding candidate "
                            + finding_id
                        )
                    if (
                        candidate["category"] != case["category"]
                        or candidate["required"] != case.get("required", True)
                        or candidate["platform"] != case.get("platform", "any")
                        or candidate["dependsOn"]
                        != sorted(case.get("dependsOn", []))
                        or candidate["coversCriteria"]
                        != sorted(case.get("coversCriteria", []))
                        or candidate["coversInvariants"]
                        != sorted(case.get("coversInvariants", []))
                        or candidate["reviewFindingIds"]
                        != sorted(case.get("reviewFindingIds", []))
                        or candidate["scenarioTags"]
                        != sorted(case.get("scenarioTags", []))
                        or candidate["quick"] != case.get("quick", False)
                    ):
                        raise AdapterError(
                            "case "
                            + case["id"]
                            + " trace mappings differ from review finding candidate"
                        )
                    runner = candidate["runner"]
                    if runner is None or candidate["conversionBlockers"]:
                        raise AdapterError(
                            "case "
                            + case["id"]
                            + " review finding candidate lacks an executable runner"
                        )
                    case_fixture = case.get("fixture")
                    normalized_fixture = (
                        normalize_relative(
                            case_fixture,
                            "case " + case["id"] + " fixture",
                        )
                        if isinstance(case_fixture, str)
                        else case_fixture
                    )
                    if (
                        runner["argv"] != case["argv"]
                        or runner["cwd"]
                        != normalize_relative(
                            case.get("cwd", "."),
                            "case " + case["id"] + " cwd",
                        )
                        or runner["timeoutSeconds"]
                        != case.get("timeoutSeconds", 60)
                        or runner["fixture"] != normalized_fixture
                        or runner["externalCapabilities"]
                        != sorted(case.get("externalCapabilities", []))
                        or runner["evidence"] != case["evidence"]
                    ):
                        raise AdapterError(
                            "case "
                            + case["id"]
                            + " execution contract differs from review finding runner"
                        )
            trace_snapshot = {
                "goalContract": {
                    "contractVersion": traceability["goalContract"][
                        "contractVersion"
                    ],
                    "sha256": traceability["goalContract"]["sha256"],
                    "criteriaIds": sorted(criteria_ids),
                },
                "invariants": {
                    "sha256": traceability["invariants"]["sha256"],
                    "hardInvariantIds": sorted(invariant_ids),
                },
                "reviewFindings": {
                    "sha256": traceability["reviewFindings"]["sha256"],
                    "findingIds": sorted(finding_ids),
                    "requiredFindingIds": sorted(
                        trace_observation["requiredFindingIds"]
                    ),
                    "resolutionStates": dict(
                        sorted(trace_observation["findingResolutionStates"].items())
                    ),
                },
                "requiredScenarios": sorted(
                    traceability.get("requiredScenarios", [])
                ),
            }
            if trace_observation["reviewAttestation"] is not None:
                trace_snapshot["reviewFindings"].update(
                    {
                        "requiredFlags": dict(
                            sorted(
                                trace_observation[
                                    "findingRequiredFlags"
                                ].items()
                            )
                        ),
                        "caseCandidateSha256s": dict(
                            sorted(
                                trace_observation[
                                    "findingCaseCandidateSha256s"
                                ].items()
                            )
                        ),
                        "attestation": copy.deepcopy(
                            trace_observation["reviewAttestation"]
                        ),
                    }
                )
            if trace_observation["reviewRequest"] is not None:
                if trace_observation["reviewBindingsVerified"] is not True:
                    raise AdapterError(
                        "REVIEW_REQUEST_MISMATCH: semantic Review request binding "
                        "was not verified"
                    )
                trace_snapshot["reviewFindings"].update(
                    {
                        "reviewRequest": copy.deepcopy(
                            trace_observation["reviewRequest"]
                        ),
                        "reviewRequestSha256": trace_observation[
                            "reviewRequestSha256"
                        ],
                        "bindingsVerified": True,
                    }
                )
    else:
        for case in cases:
            if any(
                case.get(field, [])
                for field in (
                    "coversCriteria",
                    "coversInvariants",
                    "reviewFindingIds",
                    "scenarioTags",
                )
            ):
                raise AdapterError(
                    "case trace mappings require top-level traceability"
                )

    verification: dict[str, Any] | None = None
    if "verification" in data:
        try:
            observed_verification = _verification_validator()(
                data["verification"],
                data,
                project_root,
                campaign_root,
                adapter_path,
            )
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(
                "adapter verification contract is invalid: " + str(exc)
            ) from exc
        if not isinstance(observed_verification, dict):
            raise AdapterError(
                "adapter verification validator did not return an object"
            )
        verification = copy.deepcopy(observed_verification)

    if provider == "manifest":
        manifest = source.get("manifest")
        if not isinstance(manifest, str) or not manifest:
            raise AdapterError("source.manifest must be a path string")
        manifest_relative = normalize_relative(manifest, "source.manifest")
        if any(covers_exclude(item, manifest_relative) for item in excludes):
            raise AdapterError("source.manifest cannot be excluded from the fingerprint")
        if path_uses_symlink(project_root / manifest, project_root):
            raise AdapterError("source.manifest uses a symlink/reparse path")
        manifest_path = resolve_project_path(project_root, manifest, "source.manifest")
        if not manifest_path.is_file():
            raise AdapterError("source.manifest must be an existing file")
    if provider == "files":
        files = source.get("files")
        if (
            not isinstance(files, list)
            or not files
            or any(not isinstance(item, str) for item in files)
        ):
            raise AdapterError("source.files must be a string array")
        for item in files:
            normalize_relative(item, "source file")
    inventory_adapter = Adapter(
        adapter_path,
        data,
        project_root,
        campaign_root,
        sorted(set(excludes)),
        "",
        traceability=traceability,
        finding_criteria_ids=trace_observation["findingCriteriaIds"],
        finding_invariant_ids=trace_observation["findingInvariantIds"],
        finding_required_flags=trace_observation["findingRequiredFlags"],
        finding_case_candidate_sha256s=trace_observation[
            "findingCaseCandidateSha256s"
        ],
        finding_case_candidates=trace_observation["findingCaseCandidates"],
        finding_source_references=trace_observation["findingSourceReferences"],
        review_attestation=trace_observation["reviewAttestation"],
        review_request=trace_observation["reviewRequest"],
        review_bindings_verified=trace_observation["reviewBindingsVerified"],
    )
    source_observation = observe_source(inventory_adapter)
    binding_errors = trace_source_binding_errors(
        inventory_adapter, source_observation
    )
    if binding_errors and not observe_trace_drift:
        raise AdapterError(binding_errors[0])
    try:
        assert_persistable(data)
        catalog_fingerprint = sha256_bytes(canonical_bytes(data))
    except CampaignError as exc:
        raise AdapterError("adapter contains a value unsafe to persist") from exc
    return Adapter(
        adapter_path,
        data,
        project_root,
        campaign_root,
        sorted(set(excludes)),
        catalog_fingerprint,
        traceability=traceability,
        trace_input_errors=trace_observation["errors"],
        goal_criteria_ids=trace_observation["goalCriteriaIds"],
        hard_invariant_ids=trace_observation["hardInvariantIds"],
        review_finding_ids=trace_observation["reviewFindingIds"],
        required_finding_ids=trace_observation["requiredFindingIds"],
        finding_resolution_states=trace_observation["findingResolutionStates"],
        finding_criteria_ids=trace_observation["findingCriteriaIds"],
        finding_invariant_ids=trace_observation["findingInvariantIds"],
        finding_required_flags=trace_observation["findingRequiredFlags"],
        finding_case_candidate_sha256s=trace_observation[
            "findingCaseCandidateSha256s"
        ],
        finding_case_candidates=trace_observation["findingCaseCandidates"],
        finding_source_references=trace_observation["findingSourceReferences"],
        review_attestation=trace_observation["reviewAttestation"],
        review_request=trace_observation["reviewRequest"],
        review_bindings_verified=trace_observation["reviewBindingsVerified"],
        trace_snapshot=trace_snapshot,
        verification=verification,
    )


def run_internal(
    argv: Sequence[str],
    cwd: Path,
    *,
    stdout_limit: int = MAX_INTERNAL_STDOUT_BYTES,
    stderr_limit: int = MAX_INTERNAL_STDERR_BYTES,
) -> subprocess.CompletedProcess[bytes]:
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        if process.stdout is None or process.stderr is None:  # pragma: no cover
            process.kill()
            process.wait()
            raise AdapterError("required command output pipes are unavailable")
        stdout = bytearray()
        stderr = bytearray()
        overflow: list[str] = []
        reader_errors: list[str] = []
        overflow_lock = threading.Lock()

        def collect(handle: Any, target: bytearray, limit: int, label: str) -> None:
            try:
                while True:
                    chunk = handle.read(SOURCE_READ_BYTES)
                    if not chunk:
                        return
                    with overflow_lock:
                        if len(target) + len(chunk) > limit:
                            overflow.append(label)
                            try:
                                process.kill()
                            except OSError:
                                pass
                            return
                        target.extend(chunk)
            except OSError:
                with overflow_lock:
                    reader_errors.append(label)
                    try:
                        process.kill()
                    except OSError:
                        pass
            finally:
                handle.close()

        threads = (
            threading.Thread(
                target=collect,
                args=(process.stdout, stdout, stdout_limit, "stdout"),
                daemon=True,
            ),
            threading.Thread(
                target=collect,
                args=(process.stderr, stderr, stderr_limit, "stderr"),
                daemon=True,
            ),
        )
        for thread in threads:
            thread.start()
        return_code = process.wait()
        for thread in threads:
            thread.join()
        if overflow:
            raise AdapterError(
                "required command " + overflow[0] + " exceeds the safe size limit"
            )
        if reader_errors:
            raise AdapterError(
                "cannot capture required command " + reader_errors[0] + " safely"
            )
        return subprocess.CompletedProcess(
            list(argv), return_code, bytes(stdout), bytes(stderr)
        )
    except FileNotFoundError as exc:
        raise AdapterError("required executable was not found: " + argv[0]) from exc
    except PermissionError as exc:
        raise AdapterError("required executable is not permitted: " + argv[0]) from exc
    except OSError as exc:
        raise AdapterError("cannot execute required command: " + argv[0]) from exc
    except BaseException:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        raise


def _is_reparse_point(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _assert_open_path_identity(
    path: Path,
    opened_metadata: os.stat_result,
    label: str,
) -> os.stat_result:
    """Ensure the pathname still names the regular file held by the descriptor."""

    try:
        path_metadata = path.lstat()
    except OSError as exc:
        raise AdapterError("cannot inspect " + label + " safely") from exc
    if stat.S_ISLNK(path_metadata.st_mode) or _is_reparse_point(path_metadata):
        raise AdapterError(label + " uses a symlink/reparse path")
    if not stat.S_ISREG(path_metadata.st_mode):
        raise AdapterError(label + " is not a regular file")
    if (path_metadata.st_dev, path_metadata.st_ino) != (
        opened_metadata.st_dev,
        opened_metadata.st_ino,
    ):
        raise AdapterError(label + " changed while it was being inspected")
    return path_metadata


def _resolve_source_path(root: Path, relative: str, label: str) -> tuple[Path, Path]:
    unresolved = root / relative
    if path_uses_symlink(unresolved, root):
        raise AdapterError(label + " uses a symlink/reparse path")
    resolved = resolve_project_path(root, relative, label)
    # Repeat the component inspection after realpath resolution.  This closes
    # the ordinary rename/retarget window; descriptor checks below protect the
    # final component during the actual read.
    if path_uses_symlink(unresolved, root) or path_uses_symlink(resolved, root):
        raise AdapterError(label + " uses a symlink/reparse path")
    return unresolved, resolved


def _stream_regular_source(
    unresolved: Path,
    resolved: Path,
    root: Path,
    label: str,
    capture_limit: int | None = None,
) -> tuple[dict[str, Any], bytes | None]:
    """Hash a source file in bounded chunks and optionally retain capped bytes."""

    if path_uses_symlink(unresolved, root) or path_uses_symlink(resolved, root):
        raise AdapterError(label + " uses a symlink/reparse path")
    try:
        before = resolved.lstat()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise AdapterError("cannot inspect " + label + " safely") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_reparse_point(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise AdapterError(label + " is not a regular non-link file")
    if capture_limit is not None and before.st_size > capture_limit:
        raise AdapterError(label + " exceeds the safe size limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: int | None = None
    try:
        descriptor = os.open(str(resolved), flags)
        opened_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (before.st_dev, before.st_ino)
        ):
            raise AdapterError(label + " changed while it was opened")
        _assert_open_path_identity(resolved, opened_metadata, label)
        if path_uses_symlink(unresolved, root) or path_uses_symlink(resolved, root):
            raise AdapterError(label + " uses a symlink/reparse path")

        digest = hashlib.sha256()
        total = 0
        captured = bytearray() if capture_limit is not None else None
        while True:
            chunk = os.read(descriptor, SOURCE_READ_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if capture_limit is not None and total > capture_limit:
                raise AdapterError(label + " exceeds the safe size limit")
            digest.update(chunk)
            if captured is not None:
                captured.extend(chunk)

        final_metadata = os.fstat(descriptor)
        if (
            opened_metadata.st_size != final_metadata.st_size
            or total != final_metadata.st_size
            or getattr(opened_metadata, "st_mtime_ns", None)
            != getattr(final_metadata, "st_mtime_ns", None)
            or getattr(opened_metadata, "st_ctime_ns", None)
            != getattr(final_metadata, "st_ctime_ns", None)
        ):
            raise AdapterError(label + " changed while it was being inspected")
        final_path_metadata = _assert_open_path_identity(
            resolved, final_metadata, label
        )
        if (
            final_path_metadata.st_size != final_metadata.st_size
            or getattr(final_path_metadata, "st_mtime_ns", None)
            != getattr(final_metadata, "st_mtime_ns", None)
            or getattr(final_path_metadata, "st_ctime_ns", None)
            != getattr(final_metadata, "st_ctime_ns", None)
        ):
            raise AdapterError(label + " changed while it was being inspected")
        if path_uses_symlink(unresolved, root) or path_uses_symlink(resolved, root):
            raise AdapterError(label + " uses a symlink/reparse path")
        metadata: dict[str, Any] = {
            "status": "present",
            "size": total,
            "mode": final_metadata.st_mode & 0o777,
            "sha256": "sha256:" + digest.hexdigest(),
        }
        return metadata, bytes(captured) if captured is not None else None
    except FileNotFoundError:
        raise
    except AdapterError:
        raise
    except OSError as exc:
        raise AdapterError("cannot read " + label) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_source_manifest(
    adapter: Adapter,
    manifest_value: str,
) -> tuple[Any, str, dict[str, Any]]:
    unresolved, manifest_path = _resolve_source_path(
        adapter.project_root,
        manifest_value,
        "source.manifest",
    )
    try:
        metadata, content = _stream_regular_source(
            unresolved,
            manifest_path,
            adapter.project_root,
            "source.manifest",
            MAX_SOURCE_MANIFEST_BYTES,
        )
    except FileNotFoundError as exc:
        raise AdapterError("source.manifest must be an existing file") from exc
    if content is None:
        raise AdapterError("source.manifest could not be read safely")
    try:
        manifest_text = content.decode("utf-8")
        manifest_data = parse_json_text(manifest_text, "source.manifest")
    except (CampaignError, UnicodeError) as exc:
        raise AdapterError("source.manifest is not valid JSON") from exc
    return (
        manifest_data,
        relative_to_root(adapter.project_root, manifest_path),
        metadata,
    )


def _source_file_entries(
    adapter: Adapter,
) -> tuple[
    list[str],
    list[str],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    source = adapter.data["source"]
    provider = source["provider"]
    paths: set[str] = set()
    precomputed: dict[str, dict[str, Any]] = {}
    gitlinks: dict[str, str] = {}
    manifest_control: str | None = None
    if provider == "git":
        root_check = run_internal(
            ["git", "-C", str(adapter.project_root), "rev-parse", "--show-toplevel"],
            adapter.project_root,
            stdout_limit=4096,
        )
        if root_check.returncode != 0:
            raise AdapterError("source provider git requires a Git worktree")
        git_root = Path(
            os.path.realpath(root_check.stdout.decode("utf-8", "replace").strip())
        )
        if git_root != adapter.project_root:
            raise AdapterError("Git root differs from projectRoot")
        # Ask one Git process for both cached stage metadata and untracked
        # paths.  Separate `ls-files --stage` and inventory calls can observe
        # different index generations and pair a gitlink OID with the wrong
        # path set.
        listing = run_internal(
            [
                "git",
                "-C",
                str(adapter.project_root),
                "ls-files",
                "-z",
                "-t",
                "--stage",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            adapter.project_root,
        )
        if listing.returncode != 0:
            raise AdapterError("cannot list Git worktree files")
        raw_entries = listing.stdout.split(b"\0")
        if sum(bool(raw) for raw in raw_entries) > MAX_SOURCE_ENTRIES:
            raise AdapterError("Git source inventory exceeds the entry limit")
        for raw in raw_entries:
            if not raw:
                continue
            if raw.startswith(b"? "):
                paths.add(raw[2:].decode("utf-8", "surrogateescape"))
                continue
            if len(raw) < 3 or raw[1:2] != b" ":
                raise AdapterError("cannot parse Git index entries")
            parsed = GIT_INDEX_RECORD_PATTERN.fullmatch(raw[2:])
            if parsed is None:
                raise AdapterError("cannot parse Git index entries")
            mode, oid, stage, raw_path = parsed.groups()
            relative = raw_path.decode("utf-8", "surrogateescape")
            if stage != b"0":
                raise AdapterError("Git index has unresolved entries: " + relative)
            paths.add(relative)
            if mode == b"160000" and not any(
                covers_exclude(exclude, relative) for exclude in adapter.excludes
            ):
                try:
                    gitlinks[relative] = oid.decode("ascii")
                except UnicodeDecodeError as exc:
                    raise AdapterError("cannot parse Git index entries") from exc
    elif provider == "manifest":
        manifest_value = source["manifest"]
        manifest_data, manifest_relative, manifest_metadata = _read_source_manifest(
            adapter,
            manifest_value,
        )
        manifest_control = manifest_relative
        if isinstance(manifest_data, list):
            manifest_files = manifest_data
        elif isinstance(manifest_data, dict):
            manifest_files = manifest_data.get("files")
        else:
            manifest_files = None
        if not isinstance(manifest_files, list) or any(
            not isinstance(item, str) for item in manifest_files
        ):
            raise AdapterError(
                "source.manifest must contain a string array or {files: []}"
            )
        paths.add(manifest_relative)
        precomputed[manifest_relative] = manifest_metadata
        paths.update(
            normalize_relative(item, "source manifest file") for item in manifest_files
        )
    else:
        paths.update(
            normalize_relative(item, "source file") for item in source.get("files", [])
        )
    filtered = sorted(
        path
        for path in paths
        if not any(covers_exclude(ex, path) for ex in adapter.excludes)
    )
    effective = [path for path in filtered if path != manifest_control]
    if not effective:
        raise AdapterError("effective source inventory is empty after excludes")
    return filtered, effective, precomputed, gitlinks


def source_file_entries(adapter: Adapter) -> list[str]:
    _, project_entries, _, _ = _source_file_entries(adapter)
    return project_entries


def observe_source(adapter: Adapter) -> dict[str, Any]:
    """Return one fingerprint capture plus its full and effective inventories."""

    entries: list[dict[str, Any]] = []
    source_paths, project_paths, precomputed, gitlinks = _source_file_entries(adapter)
    for relative in source_paths:
        if relative in gitlinks:
            entries.append(
                {
                    "path": relative,
                    "status": "gitlink",
                    "mode": 0o160000,
                    "oid": gitlinks[relative],
                }
            )
            continue
        if relative in precomputed:
            entries.append({"path": relative, **precomputed[relative]})
            continue
        unresolved, path = _resolve_source_path(
            adapter.project_root,
            relative,
            "source file " + relative,
        )
        try:
            metadata, _ = _stream_regular_source(
                unresolved,
                path,
                adapter.project_root,
                "source file " + relative,
            )
        except FileNotFoundError:
            entries.append({"path": relative, "status": "missing"})
            continue
        entries.append({"path": relative, **metadata})
    fingerprint = {
        "provider": adapter.data["source"]["provider"],
        "excludes": adapter.excludes,
        "files": entries,
    }
    return {
        "fingerprint": sha256_bytes(canonical_bytes(fingerprint)),
        "paths": list(source_paths),
        "projectPaths": list(project_paths),
        "files": entries,
    }


def source_snapshot(
    adapter: Adapter,
    observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the canonical, replayable preimage for one source observation."""

    observed = copy.deepcopy(observation or observe_source(adapter))
    return {
        "provider": adapter.data["source"]["provider"],
        "excludes": list(adapter.excludes),
        "fingerprint": observed["fingerprint"],
        "paths": observed["paths"],
        "projectPaths": observed["projectPaths"],
        "files": observed["files"],
    }


def source_snapshot_changed_paths(
    before: dict[str, Any], after: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Return exact project and control-path changes between two snapshots."""

    before_entries = {item["path"]: item for item in before["files"]}
    after_entries = {item["path"]: item for item in after["files"]}
    before_project = set(before["projectPaths"])
    after_project = set(after["projectPaths"])
    project_paths = before_project | after_project
    control_paths = (set(before["paths"]) | set(after["paths"])) - project_paths
    changed_project = sorted(
        path
        for path in project_paths
        if before_entries.get(path) != after_entries.get(path)
    )
    changed_control = sorted(
        path
        for path in control_paths
        if before_entries.get(path) != after_entries.get(path)
    )
    return changed_project, changed_control


def _argv_path_values(token: str) -> list[str]:
    """Return path-shaped values encoded as one argv token.

    The kernel does not guess whether a missing value is an input or an output.
    It binds only values that resolve to an existing project-owned path.
    """

    if token.startswith("-"):
        if "=" not in token:
            return []
        _, value = token.split("=", 1)
        values = [value] if value else []
    elif token.startswith("@") and len(token) > 1:
        values = [token[1:]]
    else:
        values = [token]
    expanded: list[str] = []
    for value in values:
        expanded.append(value)
        if "::" in value:
            path_part, _ = value.split("::", 1)
            if path_part:
                expanded.append(path_part)
    return list(dict.fromkeys(expanded))


def _looks_like_source_test_path(value: str) -> bool:
    if not value or "://" in value or re.match(r"^[A-Za-z]:", value):
        return False
    return (
        "/" in value
        or "\\" in value
        or PurePosixPath(value).suffix.lower() in SOURCE_TEST_SUFFIXES
    )


def _existing_project_file(
    adapter: Adapter,
    candidate: Path,
    label: str,
) -> tuple[str | None, str | None]:
    try:
        lexical = candidate if candidate.is_absolute() else candidate.absolute()
        lexical = Path(os.path.abspath(str(lexical)))
    except (OSError, ValueError):
        return None, None
    root = adapter.project_root
    if not is_within(lexical, root):
        return None, None
    try:
        exists = lexical.exists()
        is_link = lexical.is_symlink()
    except OSError:
        return None, None
    if not exists and not is_link:
        return None, None
    relative = lexical.relative_to(root).as_posix()
    if path_uses_symlink(lexical, root):
        return None, label + " uses a symlink/reparse path: " + relative
    resolved = Path(os.path.realpath(str(lexical)))
    if not is_within(resolved, root):
        return None, label + " escapes projectRoot: " + relative
    if resolved.is_dir():
        return None, None
    if not resolved.is_file():
        return None, label + " must be a regular file: " + relative
    return resolved.relative_to(root).as_posix(), None


def case_project_execution_inputs(
    adapter: Adapter,
    case: dict[str, Any],
) -> tuple[set[str], set[str], list[str]]:
    """Resolve explicit case argv/fixture file inputs owned by projectRoot."""

    case_id = str(case.get("id", "<unknown>"))
    paths: set[str] = set()
    argv_paths: set[str] = set()
    errors: list[str] = []
    cwd_value = case.get("cwd", ".")
    try:
        cwd = resolve_project_path(
            adapter.project_root,
            cwd_value,
            "case " + case_id + " cwd",
        )
    except AdapterError as exc:
        return set(), set(), [str(exc)]
    argv = case.get("argv", [])
    inline_options, inline_arguments = runner_inline_code_argv_indexes(argv)
    for index, token in enumerate(argv):
        if not isinstance(token, str) or "\x00" in token:
            continue
        if index in inline_options or index in inline_arguments:
            continue
        for value in _argv_path_values(token):
            if not value or any(character in value for character in "\r\n"):
                continue
            raw = Path(value)
            candidate = raw if raw.is_absolute() else cwd / raw
            try:
                lexical = Path(os.path.abspath(str(candidate)))
            except (OSError, ValueError):
                continue
            if not raw.is_absolute() and not is_within(
                lexical, adapter.project_root
            ):
                if _looks_like_source_test_path(value):
                    errors.append(
                        "case "
                        + case_id
                        + " argv project path escapes projectRoot: "
                        + value
                    )
                continue
            relative, error = _existing_project_file(
                adapter,
                candidate,
                "case " + case_id + " argv project file",
            )
            if error:
                errors.append(error)
            elif relative is not None:
                paths.add(relative)
                argv_paths.add(relative)
            elif is_within(lexical, adapter.project_root) and _looks_like_source_test_path(
                value
            ):
                errors.append(
                    "case "
                    + case_id
                    + " argv project file must be an existing regular file: "
                    + value
                )
    fixture = case.get("fixture")
    if isinstance(fixture, str):
        try:
            relative = normalize_relative(
                fixture,
                "case " + case_id + " fixture",
            )
        except AdapterError as exc:
            errors.append(str(exc))
        else:
            if relative == ".":
                errors.append("case " + case_id + " fixture must name a regular file")
            else:
                fixture_path, error = _existing_project_file(
                    adapter,
                    adapter.project_root / relative,
                    "case " + case_id + " fixture",
                )
                if error:
                    errors.append(error)
                elif fixture_path is None:
                    errors.append(
                        "case " + case_id + " fixture must be a regular file: " + relative
                    )
                else:
                    paths.add(fixture_path)
    return paths, argv_paths, errors


def trace_source_binding_errors(
    adapter: Adapter,
    source_observation: dict[str, Any],
) -> list[str]:
    """Validate execution and Review inputs against one exact source observation."""

    inventory = set(source_observation.get("projectPaths", []))
    observed_files = {
        entry.get("path"): entry
        for entry in source_observation.get("files", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    errors: list[str] = []
    case_inputs: dict[str, set[str]] = {}
    case_argv_inputs: dict[str, set[str]] = {}
    for case in adapter.cases:
        inputs, argv_inputs, input_errors = case_project_execution_inputs(
            adapter, case
        )
        case_inputs[case["id"]] = inputs
        case_argv_inputs[case["id"]] = argv_inputs
        errors.extend(input_errors)
        for source_path in sorted(inputs):
            if (
                source_path not in inventory
                or observed_files.get(source_path, {}).get("status") != "present"
            ):
                errors.append(
                    "case "
                    + case["id"]
                    + " execution input is not source-fingerprint bound: "
                    + source_path
                )

    if adapter.traceability is None:
        return list(dict.fromkeys(errors))

    attestation = adapter.review_attestation
    request = adapter.review_request
    attestation_scope: dict[str, str] = {}
    if isinstance(attestation, dict):
        attestation_scope = {
            item["path"]: item["sha256"]
            for item in attestation.get("scope", [])
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and isinstance(item.get("sha256"), str)
        }
        if attestation.get("sourceFingerprint") != source_observation.get(
            "fingerprint"
        ):
            errors.append(
                "REVIEW_BASELINE_DRIFT: review attestation sourceFingerprint "
                "does not match the observed source fingerprint"
            )
        for source_path, expected_digest in sorted(attestation_scope.items()):
            observed = observed_files.get(source_path, {})
            if source_path not in inventory or observed.get("status") != "present":
                errors.append(
                    "REVIEW_BASELINE_DRIFT: review attestation scope is not "
                    "source-fingerprint bound: "
                    + source_path
                )
            elif observed.get("sha256") != expected_digest:
                errors.append(
                    "REVIEW_BASELINE_DRIFT: review attestation scope digest "
                    "changed: "
                    + source_path
                )

    if isinstance(request, dict):
        try:
            canonical_request = validate_pinned_review_request(
                request,
                "review request binding",
            )
        except AdapterError as exc:
            errors.append("REVIEW_REQUEST_MISMATCH: " + str(exc))
        else:
            target_source = canonical_request["target"]["sourceFingerprint"]
            if target_source != source_observation.get("fingerprint"):
                errors.append(
                    "REVIEW_BASELINE_DRIFT: review request sourceFingerprint "
                    "does not match the observed source fingerprint"
                )
            if not isinstance(attestation, dict):
                errors.append(
                    "REVIEW_REQUEST_REQUIRED: review request binding requires "
                    "a semantic Review attestation"
                )
            else:
                requested_paths = set(canonical_request["requestedPaths"])
                missing_scope = sorted(requested_paths - set(attestation_scope))
                if missing_scope:
                    errors.append(
                        "REVIEW_REQUEST_SCOPE: completed semantic Review scope "
                        "does not cover requested paths: "
                        + ", ".join(missing_scope)
                    )
                unbound_requested = sorted(
                    path
                    for path in requested_paths
                    if path not in inventory
                    or observed_files.get(path, {}).get("status") != "present"
                )
                if unbound_requested:
                    errors.append(
                        "REVIEW_BASELINE_DRIFT: requested Review paths are not "
                        "source-fingerprint bound: "
                        + ", ".join(unbound_requested)
                    )

    for finding_id in sorted(adapter.finding_source_references):
        seen_references: set[tuple[str, str]] = set()
        for reference in adapter.finding_source_references.get(finding_id, []):
            field = reference.get("field")
            source_path = reference.get("path")
            identity = (str(field), str(source_path))
            if identity in seen_references:
                continue
            seen_references.add(identity)
            if (
                source_path not in inventory
                or observed_files.get(source_path, {}).get("status") != "present"
            ):
                errors.append(
                    "REVIEW_BASELINE_DRIFT: review finding "
                    + finding_id
                    + " "
                    + str(field)
                    + " is not source-fingerprint bound: "
                    + str(source_path)
                )
            if isinstance(attestation, dict) and source_path not in attestation_scope:
                errors.append(
                    "REVIEW_BASELINE_DRIFT: review finding "
                    + finding_id
                    + " "
                    + str(field)
                    + " is not bound by review attestation scope: "
                    + str(source_path)
                )

    for finding_id, candidate in sorted(adapter.finding_case_candidates.items()):
        runner = candidate.get("runner")
        if not isinstance(runner, dict):
            continue
        candidate_case = {**candidate, **runner}
        candidate_case["id"] = candidate.get("id", finding_id)
        inputs, argv_inputs, input_errors = case_project_execution_inputs(
            adapter,
            candidate_case,
        )
        errors.extend(
            "REVIEW_BASELINE_DRIFT: " + error for error in input_errors
        )
        runner_sources = {
            str(reference.get("path"))
            for reference in adapter.finding_source_references.get(finding_id, [])
            if reference.get("field") == "runner source evidence"
        }
        for source_path in sorted(inputs):
            if (
                source_path not in inventory
                or observed_files.get(source_path, {}).get("status") != "present"
            ):
                errors.append(
                    "REVIEW_BASELINE_DRIFT: review finding "
                    + finding_id
                    + " runner execution input is not source-fingerprint bound: "
                    + source_path
                )
            if source_path in argv_inputs and source_path not in runner_sources:
                errors.append(
                    "REVIEW_BASELINE_DRIFT: review finding "
                    + finding_id
                    + " runner sourceEvidence does not cover execution input: "
                    + source_path
                )
            if isinstance(attestation, dict) and source_path not in attestation_scope:
                errors.append(
                    "REVIEW_BASELINE_DRIFT: review finding "
                    + finding_id
                    + " runner execution input is not bound by review attestation scope: "
                    + source_path
                )

    for case in adapter.cases:
        inputs = case_inputs[case["id"]]
        argv_inputs = case_argv_inputs[case["id"]]
        for finding_id in case.get("reviewFindingIds", []):
            runner_sources = {
                str(reference.get("path"))
                for reference in adapter.finding_source_references.get(finding_id, [])
                if reference.get("field") == "runner source evidence"
            }
            for source_path in sorted(argv_inputs - runner_sources):
                errors.append(
                    "REVIEW_BASELINE_DRIFT: review finding "
                    + finding_id
                    + " runner sourceEvidence does not cover adapter execution input: "
                    + source_path
                )
            if isinstance(attestation, dict):
                for source_path in sorted(inputs - set(attestation_scope)):
                    errors.append(
                        "REVIEW_BASELINE_DRIFT: review finding "
                        + finding_id
                        + " adapter execution input is not bound by review attestation scope: "
                        + source_path
                    )
    return list(dict.fromkeys(errors))


def review_manifest_source_binding_errors(
    adapter: Adapter,
    source_observation: dict[str, Any],
    manifest: Any,
    *,
    require_attestation: bool = True,
) -> list[str]:
    """Validate a freshly parsed Review against an exact campaign source view."""

    observation = review_manifest_observation(manifest)
    errors: list[str] = []
    attestation = observation["reviewAttestation"]
    request = observation["reviewRequest"]
    if require_attestation and not isinstance(attestation, dict):
        errors.append(
            "REVIEW_ATTESTATION_REQUIRED: a fresh semantic Review attestation is required"
        )
    if isinstance(attestation, dict):
        if attestation.get("outcome") == "incomplete":
            errors.append(
                "REVIEW_ATTESTATION_INCOMPLETE: closed-loop verification cannot "
                "consume an incomplete semantic Review"
            )
        if adapter.traceability is None:
            errors.append(
                "review attestation requires adapter traceability"
            )
        else:
            if attestation.get("goalContractSha256") != adapter.traceability[
                "goalContract"
            ]["sha256"]:
                errors.append(
                    "review attestation goalContractSha256 does not match the pinned goal contract"
                )
            if attestation.get("invariantsSha256") != adapter.traceability[
                "invariants"
            ]["sha256"]:
                errors.append(
                    "review attestation invariantsSha256 does not match the pinned invariant map"
                )
    if require_attestation and not isinstance(request, dict):
        errors.append(
            "REVIEW_REQUEST_REQUIRED: a fresh semantic Review request binding is required"
        )
    elif require_attestation and observation["reviewBindingsVerified"] is not True:
        errors.append(
            "REVIEW_REQUEST_MISMATCH: fresh semantic Review request was not "
            "validated against the trusted expected binding"
        )
    for finding_id in sorted(observation["reviewFindingIds"]):
        if not observation["findingCriteriaIds"][finding_id].issubset(
            adapter.goal_criteria_ids
        ):
            errors.append(
                "review finding "
                + finding_id
                + " references an unknown goal criterion"
            )
        if not observation["findingInvariantIds"][finding_id].issubset(
            adapter.hard_invariant_ids
        ):
            errors.append(
                "review finding "
                + finding_id
                + " references an unknown triggered hard invariant"
            )
    review_adapter = Adapter(
        adapter.path,
        adapter.data,
        adapter.project_root,
        adapter.campaign_root,
        adapter.excludes,
        adapter.catalog_fingerprint,
        traceability=adapter.traceability or {},
        goal_criteria_ids=adapter.goal_criteria_ids,
        hard_invariant_ids=adapter.hard_invariant_ids,
        review_finding_ids=observation["reviewFindingIds"],
        required_finding_ids=observation["requiredFindingIds"],
        finding_resolution_states=observation["findingResolutionStates"],
        finding_criteria_ids=observation["findingCriteriaIds"],
        finding_invariant_ids=observation["findingInvariantIds"],
        finding_required_flags=observation["findingRequiredFlags"],
        finding_case_candidate_sha256s=observation[
            "findingCaseCandidateSha256s"
        ],
        finding_case_candidates=observation["findingCaseCandidates"],
        finding_source_references=observation["findingSourceReferences"],
        review_attestation=attestation,
        review_request=request,
        review_bindings_verified=observation["reviewBindingsVerified"],
        trace_snapshot=adapter.trace_snapshot,
        verification=adapter.verification,
    )
    errors.extend(trace_source_binding_errors(review_adapter, source_observation))
    return list(dict.fromkeys(errors))


def source_file_metadata(adapter: Adapter, relative: str) -> dict[str, Any]:
    """Observe one regular inventory file for a same-observation recheck."""

    unresolved, path = _resolve_source_path(
        adapter.project_root,
        relative,
        "source file " + relative,
    )
    try:
        metadata, _ = _stream_regular_source(
            unresolved,
            path,
            adapter.project_root,
            "source file " + relative,
        )
    except FileNotFoundError as exc:
        raise AdapterError("source file is missing: " + relative) from exc
    return metadata


def fingerprint_source(adapter: Adapter) -> str:
    return str(observe_source(adapter)["fingerprint"])


__all__ = [
    "Adapter",
    "AdapterError",
    "current_platform",
    "fingerprint_source",
    "observe_source",
    "platform_supported",
    "platform_supported_on",
    "source_file_metadata",
    "review_manifest_source_binding_errors",
    "trace_source_binding_errors",
    "validate_adapter",
]
