"""Append-only journal, deterministic projection, locking, and campaign storage."""

from __future__ import annotations

import copy
import errno
import json
import os
import re
import stat
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

from adapter_paths import (
    Adapter,
    current_platform,
    fingerprint_source,
    is_within,
    observe_source,
    path_has_symlink_component,
    path_uses_symlink,
    platform_supported_on,
    rebind_review_request_source,
    source_snapshot,
    source_snapshot_changed_paths,
    trace_source_binding_errors,
    validate_adapter,
    validate_pinned_review_request,
)
from model import (
    ARTIFACT_MANIFEST_VERSION,
    CASE_STATUSES,
    FINAL_RUN_STATUSES,
    INITIAL_PASS_STATUSES,
    JOURNAL_SCHEMA_VERSION,
    LEGACY_KERNEL_VERSIONS,
    READ_ONLY_JOURNAL_SCHEMA_VERSIONS,
    SCHEMA_VERSION,
    SCRIPT_VERSION,
    CampaignError,
    assert_persistable,
    atomic_write_json,
    canonical_bytes,
    parse_json_text,
    read_regular_bytes,
    sha256_bytes,
    slug,
    utc_now,
)

EVENT_FIELDS = {
    "schemaVersion",
    "seq",
    "timestamp",
    "type",
    "payload",
    "prevHash",
    "hash",
}

HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
INVARIANT_ID_PATTERN = re.compile(r"^INV-[A-Z][A-Z0-9]*-[0-9A-F]{12}$")
REVIEW_FINDING_ID_PATTERN = re.compile(r"^RF-[A-Z0-9][A-Z0-9-]*$")
ATTEMPT_ID_PATTERN = re.compile(
    r"^attempt-(?P<ordinal>[0-9]{4})-(?P<mode>quick|initial|retest|regression)-[0-9a-f]{8}$"
)
MAX_JOURNAL_BYTES = 256 * 1024 * 1024
# Projection size is an independent resource invariant. Kernel appends preflight
# the exact candidate state and summary, and replay enforces the same bound.
MAX_PROJECTION_BYTES = 512 * 1024 * 1024
MAX_ATTEMPT_ORDINAL = 9999
IS_WINDOWS = os.name == "nt"
_NO_PROJECTION_PREFLIGHT = object()


def require_hash(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or HASH_PATTERN.fullmatch(value) is None:
        raise CampaignError(label + " must be a sha256-prefixed lowercase digest")


def validate_artifact_binding(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"relativePath", "size", "sha256"}:
        raise CampaignError("case_finished artifactManifest binding is invalid")
    relative = value.get("relativePath")
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or "\\" in relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or type(value.get("size")) is not int
        or value["size"] < 0
    ):
        raise CampaignError("case_finished artifactManifest binding is invalid")
    require_hash(value.get("sha256"), "case_finished artifact manifest hash")


def validate_evidence_binding(value: Any) -> None:
    expected = {
        "requiredFiles",
        "nonEmptyFiles",
        "missingFiles",
        "emptyFiles",
        "files",
        "secretLikeContent",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise CampaignError("case_finished evidence binding is invalid")
    for field in {"requiredFiles", "nonEmptyFiles", "missingFiles", "emptyFiles"}:
        entries = value[field]
        if not isinstance(entries, list) or any(
            not isinstance(item, str) or not item for item in entries
        ):
            raise CampaignError("case_finished evidence field is invalid: " + field)
    files = value["files"]
    if not isinstance(files, list):
        raise CampaignError("case_finished evidence files must be an array")
    seen_paths: set[str] = set()
    for item in files:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "size", "sha256"}
            or not isinstance(item.get("path"), str)
            or not item["path"]
            or item["path"] in seen_paths
            or type(item.get("size")) is not int
            or item["size"] < 0
        ):
            raise CampaignError("case_finished evidence file binding is invalid")
        require_hash(item.get("sha256"), "case_finished evidence file hash")
        seen_paths.add(item["path"])
    if not isinstance(value["secretLikeContent"], bool):
        raise CampaignError(
            "case_finished evidence secretLikeContent must be a boolean"
        )


def validate_initialized_cases(value: Any) -> None:
    expected = {"id", "category", "required", "platform", "dependsOn", "evidence"}
    if not isinstance(value, list) or not value:
        raise CampaignError("campaign_initialized cases must be a non-empty array")
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != expected:
            raise CampaignError("campaign_initialized case metadata is invalid")
        case_id = item.get("id")
        if (
            not isinstance(case_id, str)
            or re.fullmatch(r"[A-Za-z0-9._-]+", case_id) is None
            or case_id in seen
            or not isinstance(item.get("category"), str)
            or not isinstance(item.get("required"), bool)
            or item.get("platform")
            not in {"any", "darwin", "linux", "windows", "posix"}
        ):
            raise CampaignError("campaign_initialized case metadata is invalid")
        seen.add(case_id)
        dependencies = item["dependsOn"]
        if not isinstance(dependencies, list) or any(
            not isinstance(dependency, str) or dependency not in seen - {case_id}
            for dependency in dependencies
        ):
            raise CampaignError("campaign_initialized case dependencies are invalid")
        evidence = item["evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {
            "requiredFiles",
            "nonEmptyFiles",
        }:
            raise CampaignError("campaign_initialized evidence metadata is invalid")
        for field in ("requiredFiles", "nonEmptyFiles"):
            entries = evidence[field]
            if not isinstance(entries, list) or any(
                not isinstance(entry, str) or not entry for entry in entries
            ):
                raise CampaignError("campaign_initialized evidence metadata is invalid")


EVENT_PAYLOAD_FIELDS = {
    "campaign_initialized": {
        "kernelVersion",
        "journalSchemaVersion",
        "artifactManifestVersion",
        "campaignId",
        "projectId",
        "projectRoot",
        "campaignRoot",
        "sourceProvider",
        "runtimePlatform",
        "catalogFingerprint",
        "catalog",
        "sourceFingerprint",
        "cases",
        "traceSnapshot",
    },
    "attempt_started": {
        "attemptId",
        "mode",
        "sourceFingerprint",
        "catalogFingerprint",
        "artifactDir",
        "resumedFrom",
        "targetCaseId",
    },
    "case_started": {
        "attemptId",
        "runId",
        "caseId",
        "ordinal",
        "artifactDir",
        "sourceFingerprint",
    },
    "case_finished": {
        "attemptId",
        "runId",
        "caseId",
        "ordinal",
        "artifactDir",
        "status",
        "reason",
        "exitCode",
        "timedOut",
        "evidence",
        "stdoutSha256",
        "stderrSha256",
        "sourceFingerprint",
        "sourceAfterFingerprint",
        "artifactManifest",
    },
    "case_skipped": {"attemptId", "caseId", "ordinal", "reason"},
    "attempt_finished": {
        "attemptId",
        "status",
        "campaignStatus",
        "currentSourceFingerprint",
        "reason",
        "clearPendingFix",
        "resumeMode",
    },
    "attempt_interrupted": {"attemptId", "interruptedRunIds", "reason"},
    "attempt_invalidated": {
        "attemptId",
        "reason",
        "sourceBeforeFingerprint",
        "sourceAfterFingerprint",
        "campaignStatus",
    },
    "fix_recorded": {
        "fixId",
        "failedCaseId",
        "failedRound",
        "failedAttemptId",
        "failedSourceFingerprint",
        "fixedSourceFingerprint",
        "rootCause",
        "changedFiles",
        "fixSummary",
        "externalCondition",
        "minimalRegressionEvidence",
        "violatedInvariant",
        "rootCauseSource",
        "resolvedFindingIds",
        "permanentGuardrail",
    },
    "review_handoff_recorded": {
        "fixId",
        "manifestPath",
        "manifestSha256",
        "sourceFingerprint",
        "goalContractSha256",
        "invariantsSha256",
        "outcome",
        "scope",
        "findingIds",
        "requiredFindingIds",
        "resolutionStates",
        "caseCandidateSha256s",
    },
    "pending_fix_superseded": {
        "fixId",
        "fixedSourceFingerprint",
        "reason",
        "reviewManifestSha256",
        "supersedingSourceFingerprint",
    },
}

SCHEMA3_EVENT_PAYLOAD_FIELDS = copy.deepcopy(EVENT_PAYLOAD_FIELDS)
EVENT_PAYLOAD_FIELDS["attempt_started"].add("sourceSnapshot")
EVENT_PAYLOAD_FIELDS["fix_recorded"] |= {
    "fixedSourceSnapshot",
    "changedFilesVerified",
}
EVENT_PAYLOAD_FIELDS["review_handoff_recorded"] |= {
    "reviewRequest",
    "reviewRequestSha256",
    "bindingsVerified",
}

LEGACY_EVENT_PAYLOAD_FIELDS = copy.deepcopy(SCHEMA3_EVENT_PAYLOAD_FIELDS)
LEGACY_EVENT_PAYLOAD_FIELDS.pop("review_handoff_recorded")
LEGACY_EVENT_PAYLOAD_FIELDS.pop("pending_fix_superseded")
LEGACY_EVENT_PAYLOAD_FIELDS["campaign_initialized"].remove("traceSnapshot")
LEGACY_EVENT_PAYLOAD_FIELDS["fix_recorded"] -= {
    "violatedInvariant",
    "rootCauseSource",
    "resolvedFindingIds",
    "permanentGuardrail",
}


def validate_source_snapshot(value: Any, label: str) -> None:
    expected = {
        "provider",
        "excludes",
        "fingerprint",
        "paths",
        "projectPaths",
        "files",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise CampaignError(label + " has invalid fields")
    provider = value.get("provider")
    excludes = value.get("excludes")
    paths = value.get("paths")
    project_paths = value.get("projectPaths")
    files = value.get("files")
    if (
        not isinstance(provider, str)
        or not provider
        or not isinstance(excludes, list)
        or any(not isinstance(item, str) or not item for item in excludes)
        or excludes != sorted(set(excludes))
        or not isinstance(paths, list)
        or not paths
        or any(not isinstance(item, str) or not item for item in paths)
        or paths != sorted(set(paths))
        or not isinstance(project_paths, list)
        or not project_paths
        or any(not isinstance(item, str) or not item for item in project_paths)
        or project_paths != sorted(set(project_paths))
        or not set(project_paths).issubset(paths)
        or not isinstance(files, list)
        or [entry.get("path") for entry in files if isinstance(entry, dict)] != paths
        or len(files) != len(paths)
    ):
        raise CampaignError(label + " inventory is invalid")
    for entry in files:
        if not isinstance(entry, dict):
            raise CampaignError(label + " file entry is invalid")
        status = entry.get("status")
        if status == "present":
            if (
                set(entry) != {"path", "status", "size", "mode", "sha256"}
                or type(entry.get("size")) is not int
                or entry["size"] < 0
                or type(entry.get("mode")) is not int
                or entry["mode"] < 0
            ):
                raise CampaignError(label + " present file entry is invalid")
            require_hash(entry.get("sha256"), label + " present file hash")
        elif status == "missing":
            if set(entry) != {"path", "status"}:
                raise CampaignError(label + " missing file entry is invalid")
        elif status == "gitlink":
            if (
                set(entry) != {"path", "status", "mode", "oid"}
                or entry.get("mode") != 0o160000
                or not isinstance(entry.get("oid"), str)
                or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", entry["oid"])
                is None
            ):
                raise CampaignError(label + " gitlink entry is invalid")
        else:
            raise CampaignError(label + " file status is invalid")
    require_hash(value.get("fingerprint"), label + " fingerprint")
    fingerprint_preimage = {
        "provider": provider,
        "excludes": excludes,
        "files": files,
    }
    if sha256_bytes(canonical_bytes(fingerprint_preimage)) != value["fingerprint"]:
        raise CampaignError(label + " fingerprint does not match its preimage")

OWNED_FILE_NAMES = {"events.jsonl", "state.json", "summary.json", "campaign.lock"}


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def require_safe_campaign_root(campaign_root: Path) -> None:
    """Reject replacement/aliasing of the initialized campaign directory."""

    try:
        if path_has_symlink_component(campaign_root):
            raise CampaignError("campaignRoot uses a symlink/reparse path")
        if not campaign_root.is_dir():
            raise CampaignError("campaignRoot identity is invalid")
    except CampaignError:
        raise
    except (OSError, ValueError) as exc:
        raise CampaignError("campaignRoot cannot be inspected safely") from exc


def require_safe_owned_path(
    campaign_root: Path,
    path: Path,
    *,
    kind: str,
    must_exist: bool = True,
) -> Optional[os.stat_result]:
    """Validate a campaign-owned path without following links/reparse points."""

    require_safe_campaign_root(campaign_root)
    try:
        absolute = path.absolute()
        if not is_within(absolute, campaign_root.absolute()):
            raise CampaignError(kind + " escapes campaignRoot")
        if path_uses_symlink(absolute, campaign_root):
            raise CampaignError(kind + " uses a symlink/reparse path")
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            if must_exist:
                raise CampaignError(kind + " is missing")
            return None
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            raise CampaignError(kind + " uses a symlink/reparse path")
        if kind.endswith("directory"):
            if not stat.S_ISDIR(metadata.st_mode):
                raise CampaignError(kind + " is not a directory")
        elif not stat.S_ISREG(metadata.st_mode):
            raise CampaignError(kind + " is not a regular file")
        return metadata
    except CampaignError:
        raise
    except (OSError, ValueError) as exc:
        raise CampaignError(kind + " cannot be inspected safely") from exc


def read_owned_json(campaign_root: Path, path: Path, label: str) -> Any:
    """Strictly parse an owned JSON projection through an O_NOFOLLOW handle."""

    before = require_safe_owned_path(campaign_root, path, kind=label)
    assert before is not None
    try:
        content = read_regular_bytes(
            path,
            label=label,
            max_bytes=MAX_PROJECTION_BYTES,
        )
        value = parse_json_text(content.decode("utf-8"), label)
        after = require_safe_owned_path(campaign_root, path, kind=label)
        assert after is not None
        if (
            (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or after.st_size != len(content)
        ):
            raise CampaignError(label + " changed while it was read")
        return value
    except CampaignError:
        raise
    except (OSError, UnicodeError) as exc:
        raise CampaignError("cannot read " + label) from exc


def validate_event_payload(
    event_type: Any,
    payload: Any,
    schema_version: int = JOURNAL_SCHEMA_VERSION,
) -> None:
    if schema_version == 2:
        payload_fields = LEGACY_EVENT_PAYLOAD_FIELDS
    elif schema_version == 3:
        payload_fields = SCHEMA3_EVENT_PAYLOAD_FIELDS
    else:
        payload_fields = EVENT_PAYLOAD_FIELDS
    if not isinstance(event_type, str) or event_type not in payload_fields:
        raise CampaignError("unknown event type: " + str(event_type))
    if not isinstance(payload, dict):
        raise CampaignError("event payload is not an object")
    expected = payload_fields[event_type]
    missing = sorted(expected - set(payload))
    unknown = sorted(set(payload) - expected)
    if missing:
        raise CampaignError(event_type + " payload missing: " + ", ".join(missing))
    if unknown:
        raise CampaignError(
            event_type + " payload has unknown fields: " + ", ".join(unknown)
        )
    if event_type == "case_finished" and not isinstance(payload["timedOut"], bool):
        raise CampaignError("case_finished timedOut must be a boolean")
    if event_type == "attempt_finished" and not isinstance(
        payload["clearPendingFix"], bool
    ):
        raise CampaignError("attempt_finished clearPendingFix must be a boolean")
    string_fields = {
        "campaign_initialized": {
            "kernelVersion",
            "campaignId",
            "projectId",
            "projectRoot",
            "campaignRoot",
            "sourceProvider",
            "runtimePlatform",
            "catalogFingerprint",
            "sourceFingerprint",
        },
        "attempt_started": {
            "attemptId",
            "mode",
            "sourceFingerprint",
            "catalogFingerprint",
            "artifactDir",
        },
        "case_started": {
            "attemptId",
            "runId",
            "caseId",
            "artifactDir",
            "sourceFingerprint",
        },
        "case_finished": {
            "attemptId",
            "runId",
            "caseId",
            "artifactDir",
            "status",
            "stdoutSha256",
            "stderrSha256",
            "sourceFingerprint",
        },
        "case_skipped": {"attemptId", "caseId", "reason"},
        "attempt_finished": {
            "attemptId",
            "status",
            "campaignStatus",
            "currentSourceFingerprint",
        },
        "attempt_interrupted": {"attemptId", "reason"},
        "attempt_invalidated": {
            "attemptId",
            "reason",
            "sourceBeforeFingerprint",
            "campaignStatus",
        },
        "fix_recorded": {
            "fixId",
            "failedCaseId",
            "failedRound",
            "failedAttemptId",
            "failedSourceFingerprint",
            "fixedSourceFingerprint",
            "rootCause",
            "fixSummary",
        },
        "review_handoff_recorded": {
            "fixId",
            "manifestPath",
            "manifestSha256",
            "sourceFingerprint",
            "goalContractSha256",
            "invariantsSha256",
            "outcome",
        },
        "pending_fix_superseded": {
            "fixId",
            "fixedSourceFingerprint",
            "reason",
            "supersedingSourceFingerprint",
        },
    }
    for field in string_fields[event_type]:
        if not isinstance(payload[field], str) or not payload[field]:
            raise CampaignError(
                event_type + " payload field must be a non-empty string: " + field
            )
    nullable_strings = {
        "attempt_started": {"resumedFrom", "targetCaseId"},
        "case_finished": {"reason", "sourceAfterFingerprint"},
        "attempt_finished": {"reason", "resumeMode"},
        "attempt_invalidated": {"sourceAfterFingerprint"},
        "pending_fix_superseded": {"reviewManifestSha256"},
    }
    for field in nullable_strings.get(event_type, set()):
        if payload[field] is not None and not isinstance(payload[field], str):
            raise CampaignError(
                event_type + " payload field must be null or a string: " + field
            )
    if event_type == "campaign_initialized":
        if (
            type(payload["journalSchemaVersion"]) is not int
            or type(payload["artifactManifestVersion"]) is not int
            or not isinstance(payload["catalog"], dict)
            or not isinstance(payload["cases"], list)
            or (
                schema_version >= 3
                and payload["traceSnapshot"] is not None
                and not isinstance(payload["traceSnapshot"], dict)
            )
        ):
            raise CampaignError("campaign_initialized payload scalar types are invalid")
        validate_initialized_cases(payload["cases"])
        if payload["runtimePlatform"] not in {"darwin", "linux", "windows", "posix"}:
            raise CampaignError("campaign_initialized runtimePlatform is invalid")
        require_hash(
            payload["catalogFingerprint"], "campaign_initialized catalogFingerprint"
        )
        require_hash(
            payload["sourceFingerprint"], "campaign_initialized sourceFingerprint"
        )
    if event_type == "attempt_started":
        allowed_modes = {"initial", "retest", "regression"}
        if schema_version >= 3:
            allowed_modes.add("quick")
        if payload["mode"] not in allowed_modes:
            raise CampaignError("attempt_started mode is invalid")
        require_hash(payload["sourceFingerprint"], "attempt_started sourceFingerprint")
        require_hash(
            payload["catalogFingerprint"], "attempt_started catalogFingerprint"
        )
        if schema_version >= 4:
            validate_source_snapshot(
                payload["sourceSnapshot"], "attempt_started sourceSnapshot"
            )
            if payload["sourceSnapshot"]["fingerprint"] != payload["sourceFingerprint"]:
                raise CampaignError(
                    "attempt_started sourceSnapshot fingerprint mismatch"
                )
    if event_type in {"case_started", "case_finished", "case_skipped"}:
        if type(payload["ordinal"]) is not int or payload["ordinal"] <= 0:
            raise CampaignError(event_type + " ordinal must be a positive integer")
    if event_type == "case_started":
        require_hash(payload["sourceFingerprint"], "case_started sourceFingerprint")
    if event_type == "case_finished":
        if (
            (payload["exitCode"] is not None and (type(payload["exitCode"]) is not int))
            or not isinstance(payload["evidence"], dict)
            or not isinstance(payload["artifactManifest"], dict)
        ):
            raise CampaignError("case_finished payload scalar types are invalid")
        if payload["status"] not in FINAL_RUN_STATUSES:
            raise CampaignError("case_finished status is invalid")
        require_hash(payload["stdoutSha256"], "case_finished stdoutSha256")
        require_hash(payload["stderrSha256"], "case_finished stderrSha256")
        require_hash(payload["sourceFingerprint"], "case_finished sourceFingerprint")
        require_hash(
            payload["sourceAfterFingerprint"],
            "case_finished sourceAfterFingerprint",
            nullable=True,
        )
        validate_evidence_binding(payload["evidence"])
        validate_artifact_binding(payload["artifactManifest"])
    if event_type == "attempt_finished":
        if payload["status"] not in {"PASS", "FAILED", "BLOCKED", "RETEST_PASSED"}:
            raise CampaignError("attempt_finished status is invalid")
        if payload["campaignStatus"] not in {
            "PENDING",
            "RUNNING",
            "READY_FOR_REGRESSION",
            "COMPLETE",
            "FAILED",
            "BLOCKED",
        }:
            raise CampaignError("attempt_finished campaignStatus is invalid")
        if payload["resumeMode"] not in {
            None,
            "quick",
            "initial",
            "retest",
            "regression",
        }:
            raise CampaignError("attempt_finished resumeMode is invalid")
        require_hash(
            payload["currentSourceFingerprint"],
            "attempt_finished currentSourceFingerprint",
        )
    if event_type == "attempt_interrupted" and (
        not isinstance(payload["interruptedRunIds"], list)
        or any(
            not isinstance(item, str) or not item
            for item in payload["interruptedRunIds"]
        )
    ):
        raise CampaignError("attempt_interrupted run IDs must be a string array")
    if event_type == "attempt_invalidated":
        if payload["campaignStatus"] not in {"REGRESSION_RUNNING", "BLOCKED"}:
            raise CampaignError("attempt_invalidated campaignStatus is invalid")
        require_hash(
            payload["sourceBeforeFingerprint"],
            "attempt_invalidated sourceBeforeFingerprint",
        )
        require_hash(
            payload["sourceAfterFingerprint"],
            "attempt_invalidated sourceAfterFingerprint",
            nullable=True,
        )
    if event_type == "fix_recorded" and (
        not isinstance(payload["changedFiles"], list)
        or not isinstance(payload["minimalRegressionEvidence"], list)
        or not isinstance(payload["externalCondition"], bool)
    ):
        raise CampaignError("fix_recorded payload scalar types are invalid")
    if event_type == "fix_recorded":
        if payload["failedRound"] not in {"quick", "initial", "regression"}:
            raise CampaignError("fix_recorded failedRound is invalid")
        if (
            any(
                not isinstance(item, str) or not item
                for item in payload["changedFiles"]
            )
            or any(
                not isinstance(item, str) or not item
                for item in payload["minimalRegressionEvidence"]
            )
            or not payload["minimalRegressionEvidence"]
            or (not payload["changedFiles"] and not payload["externalCondition"])
        ):
            raise CampaignError("fix_recorded evidence fields are invalid")
        require_hash(
            payload["failedSourceFingerprint"], "fix_recorded failedSourceFingerprint"
        )
        require_hash(
            payload["fixedSourceFingerprint"], "fix_recorded fixedSourceFingerprint"
        )
        if schema_version >= 3:
            enhanced = payload["violatedInvariant"] is not None
            if enhanced:
                violated_invariant = payload["violatedInvariant"]
                invariant_id = (
                    isinstance(violated_invariant, str)
                    and INVARIANT_ID_PATTERN.fullmatch(violated_invariant) is not None
                )
                invariant_fallback = (
                    isinstance(violated_invariant, dict)
                    and set(violated_invariant)
                    == {"notApplicable", "technicalReason"}
                    and violated_invariant.get("notApplicable") is True
                    and isinstance(violated_invariant.get("technicalReason"), str)
                    and bool(violated_invariant["technicalReason"].strip())
                )
                root_cause_source = payload["rootCauseSource"]
                if (
                    not (invariant_id or invariant_fallback)
                    or not isinstance(root_cause_source, dict)
                    or not {"path", "lineStart", "lineEnd"}.issubset(
                        root_cause_source
                    )
                    or set(root_cause_source)
                    - {"path", "lineStart", "lineEnd", "symbol"}
                    or not isinstance(root_cause_source.get("path"), str)
                    or not root_cause_source["path"]
                    or root_cause_source["path"].startswith("/")
                    or "\\" in root_cause_source["path"]
                    or any(
                        part in {"", ".", ".."}
                        for part in root_cause_source["path"].split("/")
                    )
                    or type(root_cause_source.get("lineStart")) is not int
                    or type(root_cause_source.get("lineEnd")) is not int
                    or root_cause_source["lineStart"] < 1
                    or root_cause_source["lineEnd"]
                    < root_cause_source["lineStart"]
                    or (
                        "symbol" in root_cause_source
                        and (
                            not isinstance(root_cause_source["symbol"], str)
                            or not root_cause_source["symbol"].strip()
                            or root_cause_source["symbol"]
                            != root_cause_source["symbol"].strip()
                            or any(
                                character in root_cause_source["symbol"]
                                for character in "\r\n\x00"
                            )
                        )
                    )
                    or not isinstance(payload["resolvedFindingIds"], list)
                    or any(
                        not isinstance(item, str)
                        or REVIEW_FINDING_ID_PATTERN.fullmatch(item) is None
                        for item in payload["resolvedFindingIds"]
                    )
                    or len(payload["resolvedFindingIds"])
                    != len(set(payload["resolvedFindingIds"]))
                    or not isinstance(payload["permanentGuardrail"], dict)
                ):
                    raise CampaignError("fix_recorded traceability fields are invalid")
                guardrail = payload["permanentGuardrail"]
                not_applicable = guardrail.get("notApplicable") is True
                if not_applicable:
                    if (
                        set(guardrail) != {"notApplicable", "technicalReason"}
                        or not isinstance(guardrail.get("technicalReason"), str)
                        or not guardrail["technicalReason"].strip()
                    ):
                        raise CampaignError("fix_recorded guardrail is invalid")
                elif (
                    set(guardrail)
                    != {"kind", "sourcePath", "caseId", "evidenceFile"}
                    or guardrail.get("kind")
                    not in {"test", "guard", "rule", "adversarial-case"}
                    or any(
                        not isinstance(guardrail.get(field), str)
                        or not guardrail[field]
                        for field in ("sourcePath", "caseId", "evidenceFile")
                    )
                ):
                    raise CampaignError("fix_recorded guardrail is invalid")
            elif any(
                payload[field] not in (None, [])
                for field in (
                    "rootCauseSource",
                    "resolvedFindingIds",
                    "permanentGuardrail",
                )
            ):
                raise CampaignError("legacy fix_recorded traceability fields are invalid")
        if schema_version >= 4:
            if payload["changedFilesVerified"] is not True:
                raise CampaignError(
                    "fix_recorded changedFilesVerified must be true"
                )
            validate_source_snapshot(
                payload["fixedSourceSnapshot"],
                "fix_recorded fixedSourceSnapshot",
            )
            if (
                payload["fixedSourceSnapshot"]["fingerprint"]
                != payload["fixedSourceFingerprint"]
            ):
                raise CampaignError(
                    "fix_recorded fixedSourceSnapshot fingerprint mismatch"
                )
    if event_type == "review_handoff_recorded":
        manifest_path = payload["manifestPath"]
        if (
            not isinstance(manifest_path, str)
            or not manifest_path
            or manifest_path.startswith("/")
            or re.match(r"^[A-Za-z]:", manifest_path) is not None
            or "\\" in manifest_path
            or any(part in {"", ".", ".."} for part in manifest_path.split("/"))
        ):
            raise CampaignError(
                "review_handoff_recorded manifestPath is invalid"
            )
        for field in (
            "manifestSha256",
            "sourceFingerprint",
            "goalContractSha256",
            "invariantsSha256",
        ):
            require_hash(
                payload[field], "review_handoff_recorded " + field
            )
        if schema_version >= 4:
            request = validate_pinned_review_request(
                payload["reviewRequest"],
                "review_handoff_recorded reviewRequest",
            )
            require_hash(
                payload["reviewRequestSha256"],
                "review_handoff_recorded reviewRequestSha256",
            )
            if (
                payload["bindingsVerified"] is not True
                or request["requestSha256"]
                != payload["reviewRequestSha256"]
            ):
                raise CampaignError(
                    "review_handoff_recorded Review request binding is invalid"
                )
        if (
            re.fullmatch(r"fix-[0-9a-f]{12}", payload["fixId"]) is None
            or payload["outcome"] not in {"findings", "no-findings"}
        ):
            raise CampaignError(
                "review_handoff_recorded identity or outcome is invalid"
            )
        scope = payload["scope"]
        if not isinstance(scope, list) or not scope:
            raise CampaignError("review_handoff_recorded scope is invalid")
        scope_paths: list[str] = []
        for item in scope:
            if (
                not isinstance(item, dict)
                or set(item) != {"path", "sha256"}
                or not isinstance(item.get("path"), str)
                or not item["path"]
                or item["path"].startswith("/")
                or re.match(r"^[A-Za-z]:", item["path"]) is not None
                or "\\" in item["path"]
                or any(
                    part in {"", ".", ".."}
                    for part in item["path"].split("/")
                )
            ):
                raise CampaignError("review_handoff_recorded scope is invalid")
            require_hash(item.get("sha256"), "review_handoff_recorded scope hash")
            scope_paths.append(item["path"])
        if scope_paths != sorted(scope_paths) or len(scope_paths) != len(
            set(scope_paths)
        ):
            raise CampaignError("review_handoff_recorded scope is invalid")
        finding_ids = payload["findingIds"]
        required_ids = payload["requiredFindingIds"]
        for entries in (finding_ids, required_ids):
            if (
                not isinstance(entries, list)
                or entries != sorted(entries)
                or len(entries) != len(set(entries))
                or any(
                    not isinstance(item, str)
                    or REVIEW_FINDING_ID_PATTERN.fullmatch(item) is None
                    for item in entries
                )
            ):
                raise CampaignError(
                    "review_handoff_recorded finding IDs are invalid"
                )
        if not set(required_ids).issubset(finding_ids):
            raise CampaignError(
                "review_handoff_recorded required finding IDs are unknown"
            )
        resolution_states = payload["resolutionStates"]
        candidate_digests = payload["caseCandidateSha256s"]
        if (
            not isinstance(resolution_states, dict)
            or set(resolution_states) != set(finding_ids)
            or any(
                state not in {"open", "resolved", "invalidated"}
                for state in resolution_states.values()
            )
            or not isinstance(candidate_digests, dict)
            or set(candidate_digests) != set(finding_ids)
        ):
            raise CampaignError(
                "review_handoff_recorded finding bindings are invalid"
            )
        for finding_id, digest in candidate_digests.items():
            require_hash(
                digest,
                "review_handoff_recorded case candidate " + finding_id,
            )
    if event_type == "pending_fix_superseded":
        if re.fullmatch(r"fix-[0-9a-f]{12}", payload["fixId"]) is None:
            raise CampaignError("pending_fix_superseded fixId is invalid")
        for field in ("fixedSourceFingerprint", "supersedingSourceFingerprint"):
            require_hash(payload[field], "pending_fix_superseded " + field)
        require_hash(
            payload["reviewManifestSha256"],
            "pending_fix_superseded reviewManifestSha256",
            nullable=True,
        )
        reason = payload["reason"]
        source_changed = (
            payload["fixedSourceFingerprint"]
            != payload["supersedingSourceFingerprint"]
        )
        if reason not in {"source-drift", "review-manifest-drift"}:
            raise CampaignError("pending_fix_superseded reason is invalid")
        if (
            (reason == "source-drift" and not source_changed)
            or (reason == "review-manifest-drift" and source_changed)
            or (
                reason == "review-manifest-drift"
                and payload["reviewManifestSha256"] is None
            )
        ):
            raise CampaignError(
                "pending_fix_superseded reason does not match its drift binding"
            )


class CampaignLock:
    def __init__(self, campaign_root: Path) -> None:
        self.campaign_root = campaign_root
        self.handle: Optional[Any] = None
        self._windows_lock = False

    def __enter__(self) -> "CampaignLock":
        if self.campaign_root.exists():
            require_safe_campaign_root(self.campaign_root)
        self.campaign_root.mkdir(parents=True, exist_ok=True)
        require_safe_campaign_root(self.campaign_root)
        lock_path = self.campaign_root / "campaign.lock"
        existing = require_safe_owned_path(
            self.campaign_root,
            lock_path,
            kind="campaign lock",
            must_exist=False,
        )
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            descriptor = os.open(str(lock_path), flags, 0o600)
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (
                existing is not None
                and (opened.st_dev, opened.st_ino) != (existing.st_dev, existing.st_ino)
            ):
                os.close(descriptor)
                raise CampaignError("campaign lock identity is invalid")
            self.handle = os.fdopen(descriptor, "a+")
            if fcntl is not None:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:  # pragma: no cover - Windows fallback
                import msvcrt  # type: ignore

                self.handle.seek(0)
                if not self.handle.read(1):
                    self.handle.seek(0)
                    self.handle.write("0")
                self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                self._windows_lock = True
        except (OSError, IOError) as exc:
            self.handle.close()
            self.handle = None
            raise CampaignError("campaign lock is held by another runner") from exc
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self.handle is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            elif self._windows_lock:  # pragma: no cover - exercised by mock on POSIX
                import msvcrt  # type: ignore

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.handle.close()
            self.handle = None


def event_hash(event_without_hash: Dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(event_without_hash))


def read_events(events_path: Path) -> List[Dict[str, Any]]:
    campaign_root = events_path.parent
    before = require_safe_owned_path(campaign_root, events_path, kind="event journal")
    assert before is not None
    if before.st_size > MAX_JOURNAL_BYTES:
        raise CampaignError("event journal exceeds the safe size limit")
    events: List[Dict[str, Any]] = []
    previous_hash = "0" * 64
    expected_seq = 1
    journal_schema: Optional[int] = None
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        descriptor = os.open(str(events_path), flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or opened.st_size != before.st_size
            or getattr(opened, "st_mtime_ns", None)
            != getattr(before, "st_mtime_ns", None)
            or getattr(opened, "st_ctime_ns", None)
            != getattr(before, "st_ctime_ns", None)
        ):
            os.close(descriptor)
            raise CampaignError("event journal changed while it was opened")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            raw = handle.read(MAX_JOURNAL_BYTES + 1)
            if len(raw) > MAX_JOURNAL_BYTES:
                raise CampaignError("event journal exceeds the safe size limit")
            raw_lines = raw.split(b"\n")
        after = require_safe_owned_path(
            campaign_root, events_path, kind="event journal"
        )
        assert after is not None
        if (
            len(raw) != opened.st_size
            or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or after.st_size != opened.st_size
            or getattr(after, "st_mtime_ns", None)
            != getattr(opened, "st_mtime_ns", None)
            or getattr(after, "st_ctime_ns", None)
            != getattr(opened, "st_ctime_ns", None)
        ):
            raise CampaignError("event journal changed while it was read")
    except OSError as exc:
        raise CampaignError("cannot read event journal") from exc
    if raw and not raw.endswith(b"\n"):
        raise CampaignError("event journal is not newline-terminated")
    for line_number, raw_line in enumerate(raw_lines, start=1):
        if not raw_line.strip():
            continue
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CampaignError(
                "event journal has invalid UTF-8 at line " + str(line_number)
            ) from exc
        try:

            def reject_duplicate_pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
                result: Dict[str, Any] = {}
                for key, value in pairs:
                    if key in result:
                        raise CampaignError(
                            "event journal JSON has a duplicate key: " + key
                        )
                    result[key] = value
                return result

            event = json.loads(line, object_pairs_hook=reject_duplicate_pairs)
        except json.JSONDecodeError as exc:
            raise CampaignError(
                "event journal has invalid JSON at line " + str(line_number)
            ) from exc
        if not isinstance(event, dict):
            raise CampaignError("event journal entry is not an object")
        observed_schema = event.get("schemaVersion")
        if observed_schema == 1:
            raise CampaignError(
                "legacy journal schema 1 is read-only and unsupported by kernel 0.2.0; "
                "preserve it and choose a new campaign root"
            )
        if observed_schema not in ({JOURNAL_SCHEMA_VERSION} | READ_ONLY_JOURNAL_SCHEMA_VERSIONS):
            raise CampaignError("event journal schema mismatch")
        if journal_schema is None:
            journal_schema = observed_schema
        elif observed_schema != journal_schema:
            raise CampaignError("event journal mixes schema versions")
        missing_fields = sorted(EVENT_FIELDS - set(event))
        unknown_fields = sorted(set(event) - EVENT_FIELDS)
        if missing_fields:
            raise CampaignError(
                "event journal entry is missing fields: " + ", ".join(missing_fields)
            )
        if unknown_fields:
            raise CampaignError(
                "event journal entry has unknown fields: " + ", ".join(unknown_fields)
            )
        if type(event.get("schemaVersion")) is not int:
            raise CampaignError("event journal schemaVersion must be an integer")
        if type(event.get("seq")) is not int or event["seq"] != expected_seq:
            raise CampaignError("event journal sequence is not contiguous")
        if (
            not isinstance(event.get("timestamp"), str)
            or re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z",
                event["timestamp"],
            )
            is None
        ):
            raise CampaignError("event journal timestamp must be a UTC RFC3339 string")
        try:
            # The regular expression fixes the wire representation to UTC/Z;
            # fromisoformat additionally rejects impossible calendar and clock
            # values that merely have the right textual shape.
            datetime.fromisoformat(event["timestamp"][:-1] + "+00:00")
        except ValueError as exc:
            raise CampaignError(
                "event journal timestamp must be a valid UTC RFC3339 instant"
            ) from exc
        if not isinstance(event.get("type"), str) or not event["type"]:
            raise CampaignError("event journal type must be a non-empty string")
        if not isinstance(event.get("prevHash"), str) or not isinstance(
            event.get("hash"), str
        ):
            raise CampaignError("event journal hashes must be strings")
        if HASH_PATTERN.fullmatch(event["hash"]) is None:
            raise CampaignError("event journal hash has an invalid format")
        if event.get("prevHash") != previous_hash:
            raise CampaignError("event journal hash chain is broken")
        supplied_hash = event.get("hash")
        without_hash = dict(event)
        without_hash.pop("hash", None)
        if (
            not isinstance(supplied_hash, str)
            or event_hash(without_hash) != supplied_hash
        ):
            raise CampaignError("event journal hash is invalid")
        validate_event_payload(
            event.get("type"), event.get("payload"), schema_version=observed_schema
        )
        if (
            event.get("type") == "campaign_initialized"
            and event["payload"].get("journalSchemaVersion") != observed_schema
        ):
            raise CampaignError(
                "campaign_initialized journal version does not match event schema"
            )
        assert_persistable(event.get("payload"))
        events.append(event)
        previous_hash = supplied_hash
        expected_seq += 1
    if not events:
        raise CampaignError("event journal is empty")
    return events


def append_event(
    campaign_root: Path,
    event_type: str,
    payload: Dict[str, Any],
    *,
    projection_state: Any = _NO_PROJECTION_PREFLIGHT,
) -> Dict[str, Any]:
    validate_event_payload(event_type, payload, schema_version=JOURNAL_SCHEMA_VERSION)
    assert_persistable(payload)
    events_path = campaign_root / "events.jsonl"
    before = require_safe_owned_path(campaign_root, events_path, kind="event journal")
    assert before is not None
    existing = read_events(events_path) if before.st_size else []
    previous_hash = existing[-1]["hash"] if existing else "0" * 64
    event_without_hash: Dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "seq": len(existing) + 1,
        "timestamp": utc_now(),
        "type": event_type,
        "payload": payload,
        "prevHash": previous_hash,
    }
    event = dict(event_without_hash)
    event["hash"] = event_hash(event_without_hash)
    line = canonical_bytes(event) + b"\n"
    if before.st_size + len(line) > MAX_JOURNAL_BYTES:
        raise CampaignError("event journal exceeds the safe size limit")
    if projection_state is not _NO_PROJECTION_PREFLIGHT:
        candidate_base = (
            copy.deepcopy(projection_state) if projection_state is not None else None
        )
        candidate = apply_event(candidate_base, event)
        candidate["lastEventSeq"] = event["seq"]
        candidate["lastEventHash"] = event["hash"]
        require_projection_within_limit(candidate)
    try:
        flags = os.O_WRONLY | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        descriptor = os.open(str(events_path), flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or opened.st_size != before.st_size
            or getattr(opened, "st_mtime_ns", None)
            != getattr(before, "st_mtime_ns", None)
            or getattr(opened, "st_ctime_ns", None)
            != getattr(before, "st_ctime_ns", None)
        ):
            os.close(descriptor)
            raise CampaignError("event journal changed before append")
        with os.fdopen(descriptor, "ab", closefd=True) as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        after = require_safe_owned_path(
            campaign_root, events_path, kind="event journal"
        )
        assert after is not None
        if (
            (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or after.st_size != before.st_size + len(line)
        ):
            raise CampaignError("event journal changed during append")
    except OSError as exc:
        raise CampaignError("cannot append event journal") from exc
    return event


def validate_trace_snapshot(value: Any, catalog: Dict[str, Any]) -> None:
    traceability = catalog.get("traceability")
    if traceability is None:
        if value is not None:
            raise CampaignError("legacy campaign cannot contain a trace snapshot")
        return
    if not isinstance(value, dict) or set(value) != {
        "goalContract",
        "invariants",
        "reviewFindings",
        "requiredScenarios",
    }:
        raise CampaignError("campaign trace snapshot shape is invalid")
    goal = value["goalContract"]
    invariants = value["invariants"]
    findings = value["reviewFindings"]
    if (
        not isinstance(goal, dict)
        or set(goal) != {"contractVersion", "sha256", "criteriaIds"}
        or not isinstance(invariants, dict)
        or set(invariants) != {"sha256", "hardInvariantIds"}
        or not isinstance(findings, dict)
    ):
        raise CampaignError("campaign trace snapshot contract shape is invalid")
    finding_base_fields = {
        "sha256",
        "findingIds",
        "requiredFindingIds",
        "resolutionStates",
    }
    finding_extended_fields = {
        "requiredFlags",
        "caseCandidateSha256s",
        "attestation",
        "reviewRequest",
        "reviewRequestSha256",
        "bindingsVerified",
    }
    if not finding_base_fields.issubset(findings) or set(findings) - (
        finding_base_fields | finding_extended_fields
    ):
        raise CampaignError("campaign trace snapshot contract shape is invalid")
    immutable_fields = {"requiredFlags", "caseCandidateSha256s"}
    if set(findings) & immutable_fields and not immutable_fields.issubset(findings):
        raise CampaignError("campaign trace snapshot extended binding is incomplete")
    request_fields = {
        "reviewRequest",
        "reviewRequestSha256",
        "bindingsVerified",
    }
    if set(findings) & request_fields and not request_fields.issubset(findings):
        raise CampaignError(
            "campaign trace snapshot Review request binding is incomplete"
        )
    if (
        goal.get("contractVersion")
        != traceability.get("goalContract", {}).get("contractVersion")
        or goal.get("sha256") != traceability.get("goalContract", {}).get("sha256")
        or invariants.get("sha256")
        != traceability.get("invariants", {}).get("sha256")
        or findings.get("sha256")
        != traceability.get("reviewFindings", {}).get("sha256")
    ):
        raise CampaignError("campaign trace snapshot digest binding is invalid")
    id_fields = (
        (goal.get("criteriaIds"), re.compile(r"^C[1-9][0-9]*$")),
        (invariants.get("hardInvariantIds"), INVARIANT_ID_PATTERN),
        (findings.get("findingIds"), REVIEW_FINDING_ID_PATTERN),
        (findings.get("requiredFindingIds"), REVIEW_FINDING_ID_PATTERN),
    )
    for entries, pattern in id_fields:
        if (
            not isinstance(entries, list)
            or entries != sorted(entries)
            or len(entries) != len(set(entries))
            or any(not isinstance(item, str) or pattern.fullmatch(item) is None for item in entries)
        ):
            raise CampaignError("campaign trace snapshot IDs are invalid")
    if not set(findings["requiredFindingIds"]).issubset(findings["findingIds"]):
        raise CampaignError("campaign required finding IDs are unknown")
    resolution_states = findings.get("resolutionStates")
    if (
        not isinstance(resolution_states, dict)
        or set(resolution_states) != set(findings["findingIds"])
        or any(value not in {"open", "resolved", "invalidated"} for value in resolution_states.values())
    ):
        raise CampaignError("campaign finding resolution states are invalid")
    if immutable_fields.issubset(findings):
        required_flags = findings["requiredFlags"]
        candidate_digests = findings["caseCandidateSha256s"]
        if (
            not isinstance(required_flags, dict)
            or set(required_flags) != set(findings["findingIds"])
            or any(type(flag) is not bool for flag in required_flags.values())
            or sorted(
                finding_id
                for finding_id, required in required_flags.items()
                if required
            )
            != findings["requiredFindingIds"]
            or not isinstance(candidate_digests, dict)
            or set(candidate_digests) != set(findings["findingIds"])
        ):
            raise CampaignError("campaign finding immutable bindings are invalid")
        for finding_id, digest in candidate_digests.items():
            require_hash(
                digest, "campaign case candidate digest for " + finding_id
            )
    if "attestation" in findings:
        attestation = findings["attestation"]
        if attestation is not None:
            if (
                not immutable_fields.issubset(findings)
                or not isinstance(attestation, dict)
                or set(attestation)
                != {
                    "sourceFingerprint",
                    "goalContractSha256",
                    "invariantsSha256",
                    "outcome",
                    "scope",
                    "gaps",
                }
                or attestation.get("outcome")
                not in {"findings", "no-findings", "incomplete"}
                or attestation.get("outcome") == "incomplete"
                or not isinstance(attestation.get("scope"), list)
                or not attestation.get("scope")
                or not isinstance(attestation.get("gaps"), list)
            ):
                raise CampaignError("campaign review attestation is invalid")
            for field in (
                "sourceFingerprint",
                "goalContractSha256",
                "invariantsSha256",
            ):
                require_hash(
                    attestation.get(field), "campaign review attestation " + field
                )
            if (
                attestation["goalContractSha256"] != goal["sha256"]
                or attestation["invariantsSha256"] != invariants["sha256"]
            ):
                raise CampaignError(
                    "campaign review attestation authority binding is invalid"
                )
            if (
                (attestation["outcome"] == "findings" and not findings["findingIds"])
                or (
                    attestation["outcome"] == "no-findings"
                    and findings["findingIds"]
                )
                or (
                    attestation["outcome"] == "incomplete"
                    and not attestation["gaps"]
                )
                or (
                    attestation["outcome"] != "incomplete"
                    and attestation["gaps"]
                )
            ):
                raise CampaignError("campaign review attestation outcome is invalid")
            scope_paths: list[str] = []
            for item in attestation["scope"]:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"path", "sha256"}
                    or not isinstance(item.get("path"), str)
                    or not item["path"]
                    or item["path"].startswith("/")
                    or re.match(r"^[A-Za-z]:", item["path"]) is not None
                    or "\\" in item["path"]
                    or any(
                        part in {"", ".", ".."}
                        for part in item["path"].split("/")
                    )
                ):
                    raise CampaignError("campaign review attestation scope is invalid")
                require_hash(
                    item.get("sha256"), "campaign review attestation scope hash"
                )
                scope_paths.append(item["path"])
            if scope_paths != sorted(scope_paths) or len(scope_paths) != len(
                set(scope_paths)
            ):
                raise CampaignError("campaign review attestation scope is invalid")
            gap_ids: list[str] = []
            for gap in attestation["gaps"]:
                if (
                    not isinstance(gap, dict)
                    or set(gap) != {"id", "kind", "detail", "neededEvidence"}
                    or not isinstance(gap.get("id"), str)
                    or re.fullmatch(r"RG-[A-Z0-9][A-Z0-9-]*", gap["id"])
                    is None
                    or gap.get("kind")
                    not in {
                        "insufficient-evidence",
                        "unreviewed-scope",
                        "unavailable-context",
                    }
                    or not isinstance(gap.get("detail"), str)
                    or not gap["detail"]
                    or not isinstance(gap.get("neededEvidence"), list)
                    or not gap["neededEvidence"]
                    or any(
                        not isinstance(entry, str) or not entry
                        for entry in gap["neededEvidence"]
                    )
                ):
                    raise CampaignError("campaign review attestation gaps are invalid")
                gap_ids.append(gap["id"])
            if gap_ids != sorted(gap_ids) or len(gap_ids) != len(set(gap_ids)):
                raise CampaignError("campaign review attestation gaps are invalid")
    pinned_request_sha256 = traceability.get("reviewFindings", {}).get(
        "reviewRequestSha256"
    )
    if pinned_request_sha256 is None:
        if request_fields & set(findings):
            raise CampaignError(
                "campaign Review request snapshot lacks a catalog pin"
            )
    else:
        require_hash(
            pinned_request_sha256,
            "campaign catalog Review request digest",
        )
        if not request_fields.issubset(findings):
            raise CampaignError(
                "campaign pinned Review request snapshot is incomplete"
            )
        request = validate_pinned_review_request(
            findings["reviewRequest"],
            "campaign Review request",
        )
        attestation = findings.get("attestation")
        if (
            findings["bindingsVerified"] is not True
            or findings["reviewRequestSha256"] != pinned_request_sha256
            or request["requestSha256"] != pinned_request_sha256
            or not isinstance(attestation, dict)
            or request["target"]["sourceFingerprint"]
            != attestation.get("sourceFingerprint")
            or not set(request["requestedPaths"]).issubset(
                {
                    item.get("path")
                    for item in attestation.get("scope", [])
                    if isinstance(item, dict)
                }
            )
        ):
            raise CampaignError(
                "campaign pinned Review request binding is invalid"
            )
    scenarios = value["requiredScenarios"]
    if (
        not isinstance(scenarios, list)
        or scenarios != sorted(scenarios)
        or len(scenarios) != len(set(scenarios))
        or not set(scenarios).issubset({"failure", "compatibility", "platform"})
        or scenarios != sorted(traceability.get("requiredScenarios", []))
    ):
        raise CampaignError("campaign required scenarios are invalid")


def initial_projection(payload: Dict[str, Any]) -> Dict[str, Any]:
    required = {
        "kernelVersion",
        "journalSchemaVersion",
        "artifactManifestVersion",
        "campaignId",
        "projectId",
        "projectRoot",
        "campaignRoot",
        "sourceProvider",
        "runtimePlatform",
        "catalogFingerprint",
        "catalog",
        "sourceFingerprint",
        "cases",
    }
    if payload.get("journalSchemaVersion", 0) >= 3:
        required.add("traceSnapshot")
    missing = sorted(required - set(payload))
    if missing:
        raise CampaignError(
            "campaign_initialized payload missing: " + ", ".join(missing)
        )
    if payload["journalSchemaVersion"] not in (
        {JOURNAL_SCHEMA_VERSION} | READ_ONLY_JOURNAL_SCHEMA_VERSIONS
    ):
        raise CampaignError("campaign journal schema version is unsupported")
    if payload["artifactManifestVersion"] != ARTIFACT_MANIFEST_VERSION:
        raise CampaignError("campaign artifact manifest version is unsupported")
    catalog = payload["catalog"]
    if not isinstance(catalog, dict):
        raise CampaignError("campaign catalog preimage is not an object")
    if sha256_bytes(canonical_bytes(catalog)) != payload["catalogFingerprint"]:
        raise CampaignError("campaign catalog fingerprint does not match its preimage")
    trace_snapshot = (
        payload.get("traceSnapshot")
        if payload["journalSchemaVersion"] >= 3
        else None
    )
    validate_trace_snapshot(trace_snapshot, catalog)
    if isinstance(trace_snapshot, dict):
        review_attestation = trace_snapshot.get("reviewFindings", {}).get(
            "attestation"
        )
        if (
            isinstance(review_attestation, dict)
            and review_attestation.get("sourceFingerprint")
            != payload["sourceFingerprint"]
        ):
            raise CampaignError(
                "campaign review attestation does not bind the initialized source"
            )
    catalog_source = catalog.get("source")
    if not isinstance(catalog_source, dict):
        raise CampaignError("campaign catalog source is invalid")
    if (
        catalog.get("projectId") != payload["projectId"]
        or catalog_source.get("provider") != payload["sourceProvider"]
    ):
        raise CampaignError("campaign catalog metadata is inconsistent")
    try:
        catalog_cases = Adapter(
            Path("."),
            catalog,
            Path(payload["projectRoot"]),
            Path(payload["campaignRoot"]),
            [],
            "",
        ).case_metadata()
    except (KeyError, TypeError) as exc:
        raise CampaignError("campaign catalog cases are invalid") from exc
    if catalog_cases != payload["cases"]:
        raise CampaignError("campaign catalog cases do not match initialized cases")
    cases: Dict[str, Any] = {}
    for item in payload["cases"]:
        case_projection = {
            "id": item["id"],
            "category": item["category"],
            "required": bool(item["required"]),
            "platform": item["platform"],
            "dependsOn": list(item["dependsOn"]),
            "evidence": copy.deepcopy(item["evidence"]),
            "status": "PENDING",
            "terminalSkip": False,
            "lastAttemptId": None,
            "lastCaseRunId": None,
            "artifactDir": None,
            "lastSourceFingerprint": None,
            "lastOutcome": None,
            "runs": [],
        }
        if payload["journalSchemaVersion"] >= 3:
            case_projection.update(
                {
                    "quickStatus": "PENDING",
                    "lastQuickAttemptId": None,
                    "lastQuickCaseRunId": None,
                    "lastQuickOutcome": None,
                }
            )
        cases[item["id"]] = case_projection
    projection = {
        "schemaVersion": payload["journalSchemaVersion"],
        "kernelVersion": payload["kernelVersion"],
        "journalSchemaVersion": payload["journalSchemaVersion"],
        "artifactManifestVersion": payload["artifactManifestVersion"],
        "campaignId": payload["campaignId"],
        "projectId": payload["projectId"],
        "projectRoot": payload["projectRoot"],
        "campaignRoot": payload["campaignRoot"],
        "sourceProvider": payload["sourceProvider"],
        "runtimePlatform": payload["runtimePlatform"],
        "catalogFingerprint": payload["catalogFingerprint"],
        "catalog": copy.deepcopy(catalog),
        "initialSourceFingerprint": payload["sourceFingerprint"],
        "currentSourceFingerprint": payload["sourceFingerprint"],
        "status": "PENDING",
        "currentMode": "initial",
        "resumeMode": None,
        "currentAttemptId": None,
        "currentCaseId": None,
        "regressionBaselineSourceFingerprint": None,
        "finalRegressionAttemptId": None,
        "pendingRegressionInvalidation": None,
        "cases": cases,
        "attempts": [],
        "fixes": [],
        "pendingFix": None,
        "lastEventSeq": 0,
        "lastEventHash": "",
    }
    if payload["journalSchemaVersion"] >= 3:
        projection["traceSnapshot"] = copy.deepcopy(trace_snapshot)
    return projection


def get_attempt(state: Dict[str, Any], attempt_id: str) -> Dict[str, Any]:
    for attempt in state["attempts"]:
        if attempt["id"] == attempt_id:
            return attempt
    raise CampaignError("unknown attempt in journal: " + attempt_id)


def get_case_run(attempt: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    for case_run in attempt["caseRuns"]:
        if case_run["runId"] == run_id:
            return case_run
    raise CampaignError("unknown case run in journal: " + run_id)


def attempt_recorded_ordinals(attempt: Dict[str, Any]) -> List[int]:
    return [item["ordinal"] for item in attempt["caseRuns"]] + [
        item["ordinal"] for item in attempt["skippedCases"]
    ]


def latest_failed_run(
    state: Dict[str, Any],
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    for attempt in reversed(state["attempts"]):
        for case_run in reversed(attempt["caseRuns"]):
            if case_run["status"] == "FAILED":
                return attempt, case_run
    return None


def expected_failure_round(
    state: Dict[str, Any], attempt: Dict[str, Any], case_run: Dict[str, Any]
) -> str:
    if attempt["mode"] != "retest":
        if attempt["mode"] in {"quick", "regression"}:
            return attempt["mode"]
        return "initial"
    origin = next(
        (
            item
            for item in reversed(state["fixes"])
            if item["failedCaseId"] == case_run["caseId"]
            and item["fixedSourceFingerprint"] == case_run["sourceFingerprint"]
        ),
        None,
    )
    if origin is None:
        raise CampaignError("failed retest lacks original failure provenance")
    return origin["failedRound"]


def review_attestation_campaign(state: Dict[str, Any]) -> bool:
    """Return whether history contains the legacy attestation extension."""

    snapshot = state.get("traceSnapshot")
    if not isinstance(snapshot, dict):
        return False
    findings = snapshot.get("reviewFindings")
    return isinstance(findings, dict) and isinstance(
        findings.get("attestation"), dict
    )


def strict_review_campaign(state: Dict[str, Any]) -> bool:
    """Return whether the campaign pinned a fully verified Review request."""

    if not review_attestation_campaign(state):
        return False
    snapshot = state["traceSnapshot"]
    findings = snapshot["reviewFindings"]
    catalog_reference = (
        state.get("catalog", {})
        .get("traceability", {})
        .get("reviewFindings", {})
    )
    pin = catalog_reference.get("reviewRequestSha256")
    return (
        isinstance(findings.get("reviewRequest"), dict)
        and findings.get("reviewRequestSha256") == pin
        and findings.get("bindingsVerified") is True
        and isinstance(pin, str)
        and HASH_PATTERN.fullmatch(pin) is not None
    )


def recent_regression_invalidation_count(state: Dict[str, Any]) -> int:
    count = 0
    for attempt in reversed(state["attempts"]):
        if attempt["mode"] != "regression":
            continue
        if (
            attempt["id"] == state.get("currentAttemptId")
            and attempt["status"] == "RUNNING"
        ):
            continue
        if attempt["status"] == "INVALIDATED":
            count += 1
            continue
        if attempt["status"] == "INTERRUPTED":
            continue
        break
    return count


def safe_run_identity(
    attempt: Dict[str, Any], case_id: str, ordinal: int, run_id: str, artifact_dir: str
) -> bool:
    expected_prefix = "%s-%03d-%s-" % (attempt["id"], ordinal, slug(case_id))
    return bool(
        run_id.startswith(expected_prefix)
        and re.fullmatch(re.escape(expected_prefix) + r"[0-9a-f]{8}", run_id)
        and artifact_dir == attempt["artifactDir"] + "/cases/" + run_id
    )


def _try_flush_windows_directory(path: Path) -> bool:
    """Try the WinAPI directory-handle flush; return false when unsupported."""

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, ImportError, OSError):  # pragma: no cover - non-Windows
        return False

    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    flush_file_buffers = kernel32.FlushFileBuffers
    flush_file_buffers.argtypes = (wintypes.HANDLE,)
    flush_file_buffers.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    generic_write = 0x40000000
    share_all = 0x00000001 | 0x00000002 | 0x00000004
    open_existing = 3
    directory_flags = 0x02000000 | 0x00200000
    handle = create_file(
        str(path),
        generic_write,
        share_all,
        None,
        open_existing,
        directory_flags,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    unsupported_errors = {1, 5, 6, 50, 87}
    if handle in (None, invalid_handle):
        error = ctypes.get_last_error()
        if error in unsupported_errors:
            return False
        raise ctypes.WinError(error)
    try:
        if flush_file_buffers(handle):
            return True
        error = ctypes.get_last_error()
        if error in unsupported_errors:
            return False
        raise ctypes.WinError(error)
    finally:
        close_handle(handle)


def _fsync_directory(
    path: Path,
    *,
    required: bool = False,
    label: str = "directory",
) -> None:
    """Persist a directory entry, failing closed for pre-event allocations."""

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    descriptor: Optional[int] = None
    try:
        before = path.lstat()
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or _is_reparse(before)
        ):
            raise OSError("path is not a safe directory")
        if IS_WINDOWS:
            try:
                _try_flush_windows_directory(path)
            except OSError as exc:
                if exc.errno not in {
                    errno.EACCES,
                    errno.EBADF,
                    errno.EINVAL,
                    errno.EISDIR,
                    errno.ENOTSUP,
                    errno.EPERM,
                }:
                    raise
            # Windows does not support POSIX directory fsync consistently. If
            # its directory-handle flush is unavailable, retain a stable,
            # no-reparse identity barrier and the journal file's strict fsync.
            after = path.lstat()
            if (
                not stat.S_ISDIR(after.st_mode)
                or stat.S_ISLNK(after.st_mode)
                or _is_reparse(after)
                or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise OSError("directory changed during the durability barrier")
            return
        descriptor = os.open(str(path), flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise OSError("directory changed while it was opened")
        os.fsync(descriptor)
        after = path.lstat()
        if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError("directory changed while it was synchronized")
    except OSError as exc:
        if required:
            raise CampaignError("cannot durably persist " + label) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _directory_names(path: Path, label: str) -> List[str]:
    """Enumerate a trusted directory without following any child entry."""

    try:
        with os.scandir(str(path)) as entries:
            return sorted(entry.name for entry in entries)
    except OSError as exc:
        raise CampaignError("cannot inspect " + label + " safely") from exc


def _remove_empty_allocation_directory(
    campaign_root: Path,
    path: Path,
    label: str,
) -> None:
    require_safe_owned_path(campaign_root, path, kind=label + " directory")
    if _directory_names(path, label):
        raise CampaignError(label + " contains unjournaled content")
    try:
        os.rmdir(path)
    except OSError as exc:
        raise CampaignError("cannot reconcile " + label) from exc
    _fsync_directory(
        path.parent,
        required=True,
        label=label + " parent directory",
    )


def apply_event(
    state: Optional[Dict[str, Any]], event: Dict[str, Any]
) -> Dict[str, Any]:
    event_type = event["type"]
    payload = event["payload"]
    if event_type == "campaign_initialized":
        if state is not None:
            raise CampaignError("duplicate campaign_initialized event")
        return initial_projection(payload)
    if state is None:
        raise CampaignError("journal starts without campaign_initialized")

    pending_invalidation = state.get("pendingRegressionInvalidation")
    if pending_invalidation is not None:
        if event_type != "attempt_invalidated":
            raise CampaignError(
                "regression source drift must be followed by attempt_invalidated"
            )
        if (
            payload.get("attemptId") != pending_invalidation["attemptId"]
            or payload.get("sourceBeforeFingerprint")
            != pending_invalidation["sourceBeforeFingerprint"]
            or payload.get("sourceAfterFingerprint")
            != pending_invalidation["sourceAfterFingerprint"]
        ):
            raise CampaignError(
                "attempt_invalidated does not bind the observed regression drift"
            )

    if event_type == "attempt_started":
        if state["currentAttemptId"] is not None:
            raise CampaignError("attempt_started while another attempt is active")
        attempt_id = payload["attemptId"]
        mode = payload["mode"]
        match = ATTEMPT_ID_PATTERN.fullmatch(attempt_id)
        if (
            match is None
            or int(match.group("ordinal")) != len(state["attempts"]) + 1
            or match.group("mode") != mode
        ):
            raise CampaignError("attempt_started attemptId is invalid")
        allowed_statuses = {
            "quick": {"PENDING", "INTERRUPTED", "BLOCKED"},
            "initial": {"PENDING", "RUNNING", "INTERRUPTED", "BLOCKED"},
            "retest": {"FAILED", "INTERRUPTED", "BLOCKED"},
            "regression": {
                "READY_FOR_REGRESSION",
                "REGRESSION_RUNNING",
                "INTERRUPTED",
                "BLOCKED",
            },
        }
        if state["status"] not in allowed_statuses[mode]:
            raise CampaignError("attempt_started is invalid for the campaign state")
        if payload["catalogFingerprint"] != state["catalogFingerprint"]:
            raise CampaignError("attempt_started catalog fingerprint mismatch")
        if payload["sourceFingerprint"] != state["currentSourceFingerprint"]:
            raise CampaignError("attempt_started source fingerprint mismatch")
        if state["journalSchemaVersion"] >= 4:
            snapshot = payload["sourceSnapshot"]
            if (
                snapshot["provider"] != state["sourceProvider"]
                or snapshot["fingerprint"] != payload["sourceFingerprint"]
            ):
                raise CampaignError("attempt_started source snapshot is invalid")
        if payload["artifactDir"] != "attempts/" + attempt_id:
            raise CampaignError("attempt_started artifact directory is invalid")
        if mode == "retest":
            if (
                payload["targetCaseId"] not in state["cases"]
                or state["pendingFix"] is None
                or payload["targetCaseId"] != state["pendingFix"]["failedCaseId"]
            ):
                raise CampaignError("retest attempt lacks a bound target/fix")
            if strict_review_campaign(state) and not isinstance(
                state["pendingFix"].get("reviewHandoff"), dict
            ):
                raise CampaignError(
                    "REVIEW_HANDOFF_REQUIRED: attested campaigns require a post-fix semantic Review handoff before retest"
                )
        elif payload["targetCaseId"] is not None:
            raise CampaignError("non-retest attempt cannot have a target case")
        if payload["resumedFrom"] is not None:
            previous = get_attempt(state, payload["resumedFrom"])
            if not state["attempts"] or previous is not state["attempts"][-1]:
                raise CampaignError(
                    "attempt resumedFrom must identify the latest attempt"
                )
            same_mode_resume = (
                previous["mode"] == mode
                and previous["status"] in {"BLOCKED", "INTERRUPTED", "INVALIDATED"}
                and not (previous["status"] == "INVALIDATED" and mode != "regression")
            )
            retest_checkpoint = (
                previous["mode"] == "retest"
                and previous["status"] == "RETEST_PASSED"
                and mode in {"quick", "initial", "regression"}
            )
            if not (same_mode_resume or retest_checkpoint):
                raise CampaignError("attempt resumedFrom binding is invalid")
            if previous["status"] == "BLOCKED" and previous.get("resumedFrom"):
                prior = get_attempt(state, previous["resumedFrom"])
                if (
                    prior["status"] == "BLOCKED"
                    and prior["mode"] == previous["mode"]
                    and prior.get("targetCaseId") == previous.get("targetCaseId")
                ):
                    raise CampaignError("blocked attempt retry was already consumed")
        elif state["status"] in {"INTERRUPTED", "BLOCKED"}:
            raise CampaignError("resumed attempt is missing resumedFrom")
        if state["status"] == "RUNNING" and not (
            mode == "initial"
            and payload["resumedFrom"] is not None
            and state["attempts"][-1]["status"] == "RETEST_PASSED"
        ):
            raise CampaignError(
                "initial continuation lacks a successful retest checkpoint"
            )
        if any(item["id"] == attempt_id for item in state["attempts"]):
            raise CampaignError("duplicate attempt id")
        attempt = {
            "id": attempt_id,
            "mode": payload["mode"],
            "status": "RUNNING",
            "sourceFingerprint": payload["sourceFingerprint"],
            "catalogFingerprint": payload["catalogFingerprint"],
            "artifactDir": payload["artifactDir"],
            "startedAt": event["timestamp"],
            "finishedAt": None,
            "resumedFrom": payload.get("resumedFrom"),
            "targetCaseId": payload.get("targetCaseId"),
            "caseRuns": [],
            "skippedCases": [],
            "lastOutcome": None,
        }
        if state["journalSchemaVersion"] >= 4:
            attempt["sourceSnapshot"] = copy.deepcopy(payload["sourceSnapshot"])
        state["attempts"].append(attempt)
        state["currentAttemptId"] = attempt_id
        state["currentMode"] = payload["mode"]
        state["resumeMode"] = payload["mode"]
        state["currentCaseId"] = None
        state["status"] = (
            "REGRESSION_RUNNING" if payload["mode"] == "regression" else "RUNNING"
        )
        state["currentSourceFingerprint"] = payload["sourceFingerprint"]
        if payload["mode"] == "regression":
            state["regressionBaselineSourceFingerprint"] = payload["sourceFingerprint"]
        return state

    if event_type == "case_started":
        attempt = get_attempt(state, payload["attemptId"])
        case_state = state["cases"][payload["caseId"]]
        if (
            state["currentAttemptId"] != payload["attemptId"]
            or attempt["status"] != "RUNNING"
        ):
            raise CampaignError("case started on a closed attempt")
        if state["currentCaseId"] is not None:
            raise CampaignError("case started while another case is running")
        expected_ordinal = (
            1
            if attempt["mode"] == "retest"
            else list(state["cases"]).index(payload["caseId"]) + 1
        )
        if payload["ordinal"] != expected_ordinal:
            raise CampaignError("case_started ordinal is not contiguous")
        if attempt["mode"] == "retest" and payload["caseId"] != attempt["targetCaseId"]:
            raise CampaignError("retest started the wrong target case")
        if payload["sourceFingerprint"] != attempt["sourceFingerprint"]:
            raise CampaignError("case_started source fingerprint mismatch")
        if not safe_run_identity(
            attempt,
            payload["caseId"],
            payload["ordinal"],
            payload["runId"],
            payload["artifactDir"],
        ):
            raise CampaignError("case_started run/artifact identity is invalid")
        if any(
            item["runId"] == payload["runId"]
            for prior_attempt in state["attempts"]
            for item in prior_attempt["caseRuns"]
        ):
            raise CampaignError("duplicate case run id")
        if any(
            item["caseId"] == payload["caseId"] for item in attempt["caseRuns"]
        ) or any(
            item["caseId"] == payload["caseId"] for item in attempt["skippedCases"]
        ):
            raise CampaignError("case already recorded in this attempt")
        previous_ordinals = attempt_recorded_ordinals(attempt)
        if previous_ordinals and payload["ordinal"] <= max(previous_ordinals):
            raise CampaignError("case_started ordinal is not strictly increasing")
        if (
            attempt["mode"] == "regression"
            and not previous_ordinals
            and payload["ordinal"] != 1
        ):
            raise CampaignError("regression must begin with catalog ordinal 1")
        case_run = {
            "runId": payload["runId"],
            "caseId": payload["caseId"],
            "ordinal": payload["ordinal"],
            "status": "RUNNING",
            "artifactDir": payload["artifactDir"],
            "sourceFingerprint": payload["sourceFingerprint"],
            "startedAt": event["timestamp"],
            "finishedAt": None,
            "reason": None,
            "exitCode": None,
            "timedOut": False,
            "evidence": None,
            "stdoutSha256": None,
            "stderrSha256": None,
            "artifactManifest": None,
        }
        attempt["caseRuns"].append(case_run)
        case_state["runs"].append(copy.deepcopy(case_run))
        feedback_only = attempt["mode"] == "quick" or (
            attempt["mode"] == "retest"
            and isinstance(state.get("pendingFix"), dict)
            and state["pendingFix"].get("failedRound") == "quick"
        )
        if feedback_only:
            case_state["quickStatus"] = "RUNNING"
            case_state["lastQuickAttemptId"] = payload["attemptId"]
            case_state["lastQuickCaseRunId"] = payload["runId"]
            case_state["lastQuickOutcome"] = None
        else:
            case_state["status"] = "RUNNING"
            case_state["terminalSkip"] = False
            case_state["lastAttemptId"] = payload["attemptId"]
            case_state["lastCaseRunId"] = payload["runId"]
            case_state["artifactDir"] = payload["artifactDir"]
            case_state["lastSourceFingerprint"] = payload["sourceFingerprint"]
            case_state["lastOutcome"] = None
        state["currentCaseId"] = payload["caseId"]
        return state

    if event_type == "case_finished":
        attempt = get_attempt(state, payload["attemptId"])
        case_state = state["cases"][payload["caseId"]]
        case_run = get_case_run(attempt, payload["runId"])
        if case_run["status"] != "RUNNING":
            raise CampaignError("case finished without a RUNNING case")
        if (
            state["currentAttemptId"] != payload["attemptId"]
            or state["currentCaseId"] != payload["caseId"]
        ):
            raise CampaignError("case_finished does not identify the active case")
        if (
            case_run["caseId"] != payload["caseId"]
            or case_run["ordinal"] != payload["ordinal"]
            or case_run["artifactDir"] != payload["artifactDir"]
            or case_run["sourceFingerprint"] != payload["sourceFingerprint"]
        ):
            raise CampaignError("case_finished identity does not match case_started")
        if payload["status"] not in FINAL_RUN_STATUSES:
            raise CampaignError("case_finished status is not terminal")
        valid_statuses = (
            {"RETEST_PASSED", "FAILED", "BLOCKED"}
            if attempt["mode"] == "retest"
            else {"PASS", "FAILED", "BLOCKED"}
        )
        if payload["status"] not in valid_statuses:
            raise CampaignError("case_finished status is invalid for the attempt mode")
        source_drift_for_regression = (
            attempt["mode"] == "regression"
            and payload["status"] == "PASS"
            and payload["sourceAfterFingerprint"] is not None
            and payload["sourceAfterFingerprint"] != payload["sourceFingerprint"]
        )
        if payload["status"] in {"PASS", "RETEST_PASSED"}:
            if (
                payload["exitCode"] != 0
                or payload["timedOut"]
                or payload["reason"] is not None
                or payload["sourceAfterFingerprint"] is None
                or (
                    payload["sourceAfterFingerprint"] != payload["sourceFingerprint"]
                    and not source_drift_for_regression
                )
                or payload["evidence"]["missingFiles"]
                or payload["evidence"]["emptyFiles"]
                or payload["evidence"]["secretLikeContent"]
            ):
                raise CampaignError(
                    "passing case_finished outcome is semantically invalid"
                )
        else:
            if not isinstance(payload["reason"], str) or not payload["reason"]:
                raise CampaignError("failed or blocked case_finished requires a reason")
        expected_manifest_path = payload["artifactDir"] + "/artifact-manifest.json"
        if payload["artifactManifest"]["relativePath"] != expected_manifest_path:
            raise CampaignError("case_finished artifact manifest path is invalid")
        case_run.update(
            {
                "status": payload["status"],
                "finishedAt": event["timestamp"],
                "reason": payload.get("reason"),
                "exitCode": payload.get("exitCode"),
                "timedOut": bool(payload.get("timedOut", False)),
                "evidence": copy.deepcopy(payload.get("evidence")),
                "stdoutSha256": payload.get("stdoutSha256"),
                "stderrSha256": payload.get("stderrSha256"),
                "sourceAfterFingerprint": payload.get("sourceAfterFingerprint"),
                "artifactManifest": copy.deepcopy(payload.get("artifactManifest")),
            }
        )
        for stored in case_state["runs"]:
            if stored["runId"] == payload["runId"]:
                stored.update(copy.deepcopy(case_run))
                break
        outcome_projection = {
            "status": payload["status"],
            "reason": payload.get("reason"),
            "evidence": copy.deepcopy(payload.get("evidence")),
        }
        feedback_only = attempt["mode"] == "quick" or (
            attempt["mode"] == "retest"
            and isinstance(state.get("pendingFix"), dict)
            and state["pendingFix"].get("failedRound") == "quick"
        )
        if feedback_only:
            case_state["quickStatus"] = payload["status"]
            case_state["lastQuickAttemptId"] = payload["attemptId"]
            case_state["lastQuickCaseRunId"] = payload["runId"]
            case_state["lastQuickOutcome"] = copy.deepcopy(outcome_projection)
        else:
            case_state["status"] = payload["status"]
            case_state["terminalSkip"] = False
            case_state["lastAttemptId"] = payload["attemptId"]
            case_state["lastCaseRunId"] = payload["runId"]
            case_state["artifactDir"] = payload["artifactDir"]
            case_state["lastSourceFingerprint"] = payload.get(
                "sourceAfterFingerprint"
            ) or payload.get("sourceFingerprint")
            case_state["lastOutcome"] = copy.deepcopy(outcome_projection)
        attempt["lastOutcome"] = copy.deepcopy(outcome_projection)
        attempt["lastCaseId"] = payload["caseId"]
        state["currentCaseId"] = None
        if payload.get("sourceAfterFingerprint"):
            state["currentSourceFingerprint"] = payload["sourceAfterFingerprint"]
        if source_drift_for_regression:
            state["pendingRegressionInvalidation"] = {
                "attemptId": payload["attemptId"],
                "sourceBeforeFingerprint": payload["sourceFingerprint"],
                "sourceAfterFingerprint": payload["sourceAfterFingerprint"],
            }
        return state

    if event_type == "case_skipped":
        attempt = get_attempt(state, payload["attemptId"])
        case_state = state["cases"][payload["caseId"]]
        if (
            state["currentAttemptId"] != payload["attemptId"]
            or attempt["status"] != "RUNNING"
        ):
            raise CampaignError("case_skipped requires the current RUNNING attempt")
        if state["currentCaseId"] is not None:
            raise CampaignError("case_skipped while another case is running")
        if attempt["mode"] == "retest":
            raise CampaignError("retest target cannot be represented as a skip")
        if case_state["required"]:
            raise CampaignError("required case cannot be skipped")
        expected_ordinal = list(state["cases"]).index(payload["caseId"]) + 1
        if payload["ordinal"] != expected_ordinal:
            raise CampaignError("case_skipped ordinal is not contiguous")
        if any(
            item["caseId"] == payload["caseId"] for item in attempt["skippedCases"]
        ) or any(item["caseId"] == payload["caseId"] for item in attempt["caseRuns"]):
            raise CampaignError("case already recorded in this attempt")
        previous_ordinals = attempt_recorded_ordinals(attempt)
        if previous_ordinals and payload["ordinal"] <= max(previous_ordinals):
            raise CampaignError("case_skipped ordinal is not strictly increasing")
        if (
            attempt["mode"] == "regression"
            and not previous_ordinals
            and payload["ordinal"] != 1
        ):
            raise CampaignError("regression must begin with catalog ordinal 1")
        if case_state["status"] == "RUNNING":
            raise CampaignError("cannot skip a running case")
        if attempt["mode"] == "quick":
            quick_outcomes = {
                item["caseId"]: item["status"] for item in attempt["caseRuns"]
            }
            dependency_unmet = any(
                quick_outcomes.get(dependency) != "PASS"
                for dependency in case_state["dependsOn"]
            )
        else:
            dependency_unmet = any(
                state["cases"][dependency]["status"] not in INITIAL_PASS_STATUSES
                for dependency in case_state["dependsOn"]
            )
        platform_unavailable = not platform_supported_on(
            case_state["platform"], state["runtimePlatform"]
        )
        if not dependency_unmet and not platform_unavailable:
            raise CampaignError("optional case is runnable and cannot be skipped")
        if attempt["mode"] == "quick":
            case_state["quickStatus"] = "NOT_RUN"
            case_state["lastQuickAttemptId"] = payload["attemptId"]
            case_state["lastQuickOutcome"] = {
                "status": "NOT_RUN",
                "reason": payload["reason"],
            }
        else:
            case_state["status"] = "NOT_RUN"
            case_state["terminalSkip"] = True
            case_state["lastAttemptId"] = payload["attemptId"]
            case_state["lastOutcome"] = {
                "status": "NOT_RUN",
                "reason": payload["reason"],
            }
        attempt["skippedCases"].append(
            {
                "caseId": payload["caseId"],
                "reason": payload["reason"],
                "ordinal": payload["ordinal"],
            }
        )
        return state

    if event_type == "attempt_finished":
        attempt = get_attempt(state, payload["attemptId"])
        if state["currentAttemptId"] != payload["attemptId"]:
            raise CampaignError(
                "attempt_finished does not identify the current attempt"
            )
        if attempt["status"] != "RUNNING":
            raise CampaignError("attempt_finished requires a RUNNING attempt")
        if any(run["status"] == "RUNNING" for run in attempt["caseRuns"]):
            raise CampaignError("attempt_finished cannot close a running case")
        if state["currentCaseId"] is not None:
            raise CampaignError("attempt_finished cannot close an active case")
        allowed_outcomes = {
            "quick": {"PASS", "FAILED", "BLOCKED"},
            "initial": {"PASS", "FAILED", "BLOCKED"},
            "regression": {"PASS", "FAILED", "BLOCKED"},
            "retest": {"RETEST_PASSED", "FAILED", "BLOCKED"},
        }
        if payload["status"] not in allowed_outcomes[attempt["mode"]]:
            raise CampaignError(
                "attempt_finished status is invalid for the attempt mode"
            )
        allowed_campaign_statuses = {
            ("quick", "PASS"): {"PENDING"},
            ("quick", "FAILED"): {"FAILED"},
            ("quick", "BLOCKED"): {"BLOCKED"},
            ("initial", "PASS"): {"READY_FOR_REGRESSION"},
            ("initial", "FAILED"): {"FAILED"},
            ("initial", "BLOCKED"): {"BLOCKED"},
            ("regression", "PASS"): {"COMPLETE"},
            ("regression", "FAILED"): {"FAILED"},
            ("regression", "BLOCKED"): {"BLOCKED"},
            ("retest", "RETEST_PASSED"): {
                "PENDING",
                "RUNNING",
                "READY_FOR_REGRESSION",
            },
            ("retest", "FAILED"): {"FAILED"},
            ("retest", "BLOCKED"): {"BLOCKED"},
        }
        if (
            payload["campaignStatus"]
            not in allowed_campaign_statuses[(attempt["mode"], payload["status"])]
        ):
            raise CampaignError("attempt_finished campaign status is inconsistent")
        if payload["currentSourceFingerprint"] != state["currentSourceFingerprint"]:
            raise CampaignError("attempt_finished source fingerprint is inconsistent")
        if (
            payload["status"] in {"PASS", "RETEST_PASSED"}
            and payload["reason"] is not None
        ):
            raise CampaignError("passing attempt cannot have a failure reason")
        if payload["status"] in {"FAILED", "BLOCKED"} and (
            not isinstance(payload["reason"], str) or not payload["reason"]
        ):
            raise CampaignError("failed or blocked attempt must have a reason")
        if attempt["mode"] == "retest":
            if len(attempt["caseRuns"]) != 1 or attempt["skippedCases"]:
                raise CampaignError("retest attempt must contain exactly one case run")
            if attempt["caseRuns"][0]["status"] != payload["status"]:
                raise CampaignError(
                    "retest attempt outcome disagrees with its case run"
                )
            should_clear = payload["status"] in {"RETEST_PASSED", "FAILED"}
            if payload["clearPendingFix"] is not should_clear:
                raise CampaignError("retest pending-fix transition is inconsistent")
            if payload["status"] == "RETEST_PASSED":
                expected_resume = {
                    "PENDING": "quick",
                    "RUNNING": "initial",
                    "READY_FOR_REGRESSION": "regression",
                }[payload["campaignStatus"]]
                if payload["resumeMode"] != expected_resume:
                    raise CampaignError("successful retest resumeMode is inconsistent")
        elif payload["clearPendingFix"]:
            raise CampaignError("non-retest attempt cannot clear a pending fix")
        if state["journalSchemaVersion"] >= 4:
            if payload["status"] in {"FAILED", "BLOCKED"}:
                expected_resume = attempt["mode"]
            elif attempt["mode"] == "quick":
                expected_resume = "initial"
            elif attempt["mode"] == "initial":
                expected_resume = (
                    "regression"
                    if payload["campaignStatus"] == "READY_FOR_REGRESSION"
                    else "initial"
                )
            elif attempt["mode"] == "regression":
                expected_resume = None
            else:
                expected_resume = {
                    "PENDING": "quick",
                    "RUNNING": "initial",
                    "READY_FOR_REGRESSION": "regression",
                }[payload["campaignStatus"]]
            if payload["resumeMode"] != expected_resume:
                raise CampaignError(
                    "attempt_finished resumeMode does not identify the next phase"
                )
        if payload["status"] in {"FAILED", "BLOCKED"} and attempt["caseRuns"]:
            last_status = attempt["caseRuns"][-1]["status"]
            if last_status not in {payload["status"], "PASS", "RETEST_PASSED"}:
                raise CampaignError("attempt outcome disagrees with its last case run")
        if attempt["mode"] == "regression" and payload["status"] == "PASS":
            if sorted(attempt_recorded_ordinals(attempt)) != list(
                range(1, len(state["cases"]) + 1)
            ):
                raise CampaignError(
                    "passing regression did not cover the complete catalog"
                )
        if attempt["mode"] == "quick" and payload["status"] == "PASS":
            selected_ordinals = [
                index
                for index, item in enumerate(state["catalog"]["cases"], start=1)
                if item.get("quick", False)
            ]
            if sorted(attempt_recorded_ordinals(attempt)) != selected_ordinals:
                raise CampaignError("passing quick attempt did not cover its selection")
        if attempt["mode"] == "initial" and payload["status"] == "PASS":
            if any(
                case["status"] not in INITIAL_PASS_STATUSES
                and not (
                    case["status"] == "NOT_RUN"
                    and case["terminalSkip"]
                    and not case["required"]
                )
                for case in state["cases"].values()
            ):
                raise CampaignError("passing initial attempt left incomplete cases")
        attempt["status"] = payload["status"]
        attempt["finishedAt"] = event["timestamp"]
        attempt["lastOutcome"] = {
            "status": payload["status"],
            "reason": payload.get("reason"),
        }
        state["currentAttemptId"] = None
        state["currentCaseId"] = None
        state["status"] = payload["campaignStatus"]
        state["currentMode"] = attempt["mode"]
        if state["journalSchemaVersion"] >= 4:
            state["resumeMode"] = payload["resumeMode"]
        else:
            state["resumeMode"] = payload["resumeMode"] or attempt["mode"]
        if payload.get("currentSourceFingerprint"):
            state["currentSourceFingerprint"] = payload["currentSourceFingerprint"]
        if payload.get("clearPendingFix"):
            state["pendingFix"] = None
        if attempt["mode"] == "regression" and payload["status"] == "PASS":
            state["finalRegressionAttemptId"] = attempt["id"]
        return state

    if event_type == "attempt_interrupted":
        attempt = get_attempt(state, payload["attemptId"])
        if (
            state["currentAttemptId"] != payload["attemptId"]
            or attempt["status"] != "RUNNING"
        ):
            raise CampaignError(
                "attempt_interrupted requires the current RUNNING attempt"
            )
        running_ids = [
            case_run["runId"]
            for case_run in attempt["caseRuns"]
            if case_run["status"] == "RUNNING"
        ]
        if len(payload["interruptedRunIds"]) != len(
            set(payload["interruptedRunIds"])
        ) or set(payload["interruptedRunIds"]) != set(running_ids):
            raise CampaignError("attempt_interrupted run IDs do not match active runs")
        if (state["currentCaseId"] is None) != (not running_ids):
            raise CampaignError(
                "attempt_interrupted active case binding is inconsistent"
            )
        if running_ids:
            active_run = get_case_run(attempt, running_ids[0])
            if active_run["caseId"] != state["currentCaseId"]:
                raise CampaignError(
                    "attempt_interrupted active case binding is inconsistent"
                )
        attempt["status"] = "INTERRUPTED"
        attempt["finishedAt"] = event["timestamp"]
        attempt["lastOutcome"] = {"status": "INTERRUPTED", "reason": payload["reason"]}
        for run_id in payload.get("interruptedRunIds", []):
            case_run = get_case_run(attempt, run_id)
            case_run["status"] = "INTERRUPTED"
            case_run["reason"] = payload["reason"]
            case_state = state["cases"][case_run["caseId"]]
            feedback_only = attempt["mode"] == "quick" or (
                attempt["mode"] == "retest"
                and isinstance(state.get("pendingFix"), dict)
                and state["pendingFix"].get("failedRound") == "quick"
            )
            if feedback_only:
                case_state["quickStatus"] = "INTERRUPTED"
                case_state["lastQuickAttemptId"] = payload["attemptId"]
                case_state["lastQuickCaseRunId"] = run_id
                case_state["lastQuickOutcome"] = {
                    "status": "INTERRUPTED",
                    "reason": payload["reason"],
                }
            else:
                case_state["status"] = "INTERRUPTED"
                case_state["lastOutcome"] = {
                    "status": "INTERRUPTED",
                    "reason": payload["reason"],
                }
            for stored in case_state["runs"]:
                if stored["runId"] == run_id:
                    stored.update(copy.deepcopy(case_run))
                    break
        state["currentAttemptId"] = None
        state["currentCaseId"] = None
        state["status"] = "INTERRUPTED"
        state["resumeMode"] = attempt["mode"]
        return state

    if event_type == "attempt_invalidated":
        attempt = get_attempt(state, payload["attemptId"])
        if (
            state["currentAttemptId"] != payload["attemptId"]
            or attempt["status"] != "RUNNING"
        ):
            raise CampaignError(
                "attempt_invalidated requires the current RUNNING attempt"
            )
        if attempt["mode"] != "regression":
            raise CampaignError("only a regression attempt can be invalidated")
        if state["currentCaseId"] is not None or any(
            run["status"] == "RUNNING" for run in attempt["caseRuns"]
        ):
            raise CampaignError("attempt_invalidated cannot close an active case")
        if payload["sourceBeforeFingerprint"] != attempt["sourceFingerprint"]:
            raise CampaignError("attempt_invalidated baseline fingerprint mismatch")
        catalog_invalidation = "catalog" in payload["reason"].lower()
        if (
            not catalog_invalidation
            and payload["sourceAfterFingerprint"] == payload["sourceBeforeFingerprint"]
        ):
            raise CampaignError("attempt_invalidated did not observe source drift")
        if state["journalSchemaVersion"] >= 4:
            if payload["campaignStatus"] != "BLOCKED":
                raise CampaignError(
                    "regression invalidation must fail-stop the campaign"
                )
        else:
            # Schema 3 permitted bounded automatic restarts. It is now
            # read-only, but replay must preserve its historical semantics.
            prior_invalidations = recent_regression_invalidation_count(state)
            if payload["campaignStatus"] == "BLOCKED" and not catalog_invalidation:
                if prior_invalidations + 1 < 8:
                    raise CampaignError("regression restart limit was not reached")
            if (
                payload["campaignStatus"] == "REGRESSION_RUNNING"
                and prior_invalidations + 1 >= 8
            ):
                raise CampaignError("regression restart limit was exceeded")
        attempt["status"] = "INVALIDATED"
        attempt["finishedAt"] = event["timestamp"]
        attempt["invalidationReason"] = payload["reason"]
        attempt["lastOutcome"] = {
            "status": "INVALIDATED",
            "reason": payload["reason"],
        }
        attempt["sourceAfterFingerprint"] = payload.get("sourceAfterFingerprint")
        state["currentAttemptId"] = None
        state["currentCaseId"] = None
        state["status"] = payload.get("campaignStatus", "REGRESSION_RUNNING")
        state["currentMode"] = attempt["mode"]
        state["resumeMode"] = attempt["mode"]
        if state["journalSchemaVersion"] < 4:
            state["currentSourceFingerprint"] = (
                payload.get("sourceAfterFingerprint")
                or state["currentSourceFingerprint"]
            )
        state["pendingRegressionInvalidation"] = None
        return state

    if event_type == "fix_recorded":
        if state["status"] != "FAILED" or state["currentAttemptId"] is not None:
            raise CampaignError("fix_recorded requires a closed FAILED campaign")
        if state["pendingFix"] is not None:
            raise CampaignError("fix_recorded cannot replace a pending fix")
        failed = latest_failed_run(state)
        if failed is None:
            raise CampaignError("fix_recorded has no failed case to bind")
        failed_attempt, failed_run = failed
        if (
            re.fullmatch(r"fix-[0-9a-f]{12}", payload["fixId"]) is None
            or payload["failedCaseId"] != failed_run["caseId"]
            or payload["failedAttemptId"] != failed_attempt["id"]
            or payload["failedSourceFingerprint"] != failed_run["sourceFingerprint"]
            or payload["failedRound"]
            != expected_failure_round(state, failed_attempt, failed_run)
        ):
            raise CampaignError("fix_recorded failure provenance is invalid")
        if (
            failed_attempt is not state["attempts"][-1]
            or failed_attempt["status"] != "FAILED"
        ):
            raise CampaignError("fix_recorded does not bind the latest failed attempt")
        if any(item["fixId"] == payload["fixId"] for item in state["fixes"]):
            raise CampaignError("duplicate fix id")
        if state["journalSchemaVersion"] >= 4:
            failed_snapshot = failed_attempt.get("sourceSnapshot")
            fixed_snapshot = payload["fixedSourceSnapshot"]
            if (
                not isinstance(failed_snapshot, dict)
                or failed_snapshot.get("fingerprint")
                != payload["failedSourceFingerprint"]
                or failed_snapshot.get("provider") != fixed_snapshot.get("provider")
                or failed_snapshot.get("excludes") != fixed_snapshot.get("excludes")
            ):
                raise CampaignError("fix_recorded source snapshot provenance is invalid")
            actual_changes, _control_changes = source_snapshot_changed_paths(
                failed_snapshot, fixed_snapshot
            )
            if payload["changedFiles"] != actual_changes:
                raise CampaignError(
                    "fix_recorded changedFiles do not match the snapshot delta"
                )
            if payload["changedFilesVerified"] is not True:
                raise CampaignError("fix_recorded lacks exact changed-file proof")
        traceable = isinstance(state.get("catalog", {}).get("traceability"), dict)
        if traceable and payload.get("violatedInvariant") is None:
            raise CampaignError("traceable fix_recorded lacks invariant provenance")
        if not traceable and payload.get("violatedInvariant") is not None:
            raise CampaignError("legacy campaign cannot record traceability fix fields")
        if traceable:
            failed_case_definition = next(
                item
                for item in state["catalog"]["cases"]
                if item["id"] == failed_run["caseId"]
            )
            violated_invariant = payload["violatedInvariant"]
            if isinstance(violated_invariant, str):
                if (
                    violated_invariant
                    not in failed_case_definition.get("coversInvariants", [])
                    or violated_invariant
                    not in state["traceSnapshot"]["invariants"]["hardInvariantIds"]
                ):
                    raise CampaignError(
                        "fix_recorded invariant is not covered by the failed case"
                    )
            elif failed_case_definition.get("coversInvariants", []):
                raise CampaignError(
                    "fix_recorded invariant fallback is invalid for a covered case"
                )
            failed_case_finding_ids = set(
                failed_case_definition.get("reviewFindingIds", [])
            )
            if not set(payload["resolvedFindingIds"]).issubset(
                failed_case_finding_ids
            ):
                raise CampaignError(
                    "fix_recorded resolves a finding not linked to the failed case"
                )
            guardrail = payload["permanentGuardrail"]
            if guardrail.get("notApplicable") is not True:
                guardrail_case = next(
                    (
                        item
                        for item in state["catalog"]["cases"]
                        if item["id"] == guardrail["caseId"]
                    ),
                    None,
                )
                if (
                    guardrail_case is None
                    or not guardrail_case.get("required", True)
                    or guardrail["evidenceFile"]
                    not in (guardrail_case.get("evidence") or {}).get(
                        "nonEmptyFiles", []
                    )
                ):
                    raise CampaignError("fix_recorded guardrail binding is invalid")
                if isinstance(violated_invariant, str) and violated_invariant not in (
                    guardrail_case.get("coversInvariants", [])
                ):
                    raise CampaignError(
                        "fix_recorded guardrail does not cover the violated invariant"
                    )
                if not set(payload["resolvedFindingIds"]).issubset(
                    set(guardrail_case.get("reviewFindingIds", []))
                ):
                    raise CampaignError(
                        "fix_recorded guardrail does not cover resolved findings"
                    )
        state["fixes"].append(copy.deepcopy(payload))
        state["pendingFix"] = copy.deepcopy(payload)
        state["currentSourceFingerprint"] = payload["fixedSourceFingerprint"]
        state["currentMode"] = payload["failedRound"]
        state["resumeMode"] = payload["failedRound"]
        state["status"] = "FAILED"
        return state

    if event_type == "review_handoff_recorded":
        if state["journalSchemaVersion"] >= 4 and not strict_review_campaign(state):
            raise CampaignError(
                "review_handoff_recorded requires a request-bound semantic Review campaign"
            )
        if state["journalSchemaVersion"] < 4 and not review_attestation_campaign(
            state
        ):
            raise CampaignError(
                "review_handoff_recorded requires an attested semantic Review campaign"
            )
        pending_fix = state.get("pendingFix")
        if (
            state.get("status") != "FAILED"
            or state.get("currentAttemptId") is not None
            or not isinstance(pending_fix, dict)
        ):
            raise CampaignError(
                "review_handoff_recorded requires a closed FAILED campaign with a pending fix"
            )
        if pending_fix.get("fixId") != payload["fixId"]:
            raise CampaignError(
                "review_handoff_recorded does not bind the pending fix"
            )
        if pending_fix.get("reviewHandoff") is not None:
            raise CampaignError(
                "review_handoff_recorded cannot replace an existing handoff"
            )
        matching_fix = next(
            (
                fix
                for fix in state["fixes"]
                if fix.get("fixId") == payload["fixId"]
            ),
            None,
        )
        if matching_fix is None or matching_fix is not pending_fix:
            # Projection construction intentionally installs the same object for
            # fixes[-1] and pendingFix only after this event; older projections
            # use independent copies, so compare by identity-independent fields.
            if matching_fix is None or matching_fix != pending_fix:
                raise CampaignError(
                    "review_handoff_recorded pending-fix projection is inconsistent"
                )
        if payload["sourceFingerprint"] != pending_fix.get(
            "fixedSourceFingerprint"
        ):
            raise CampaignError(
                "review_handoff_recorded source does not bind the pending fix"
            )
        snapshot = state["traceSnapshot"]
        snapshot_findings = snapshot["reviewFindings"]
        if (
            payload["goalContractSha256"] != snapshot["goalContract"]["sha256"]
            or payload["invariantsSha256"] != snapshot["invariants"]["sha256"]
        ):
            raise CampaignError(
                "review_handoff_recorded authority digest binding is invalid"
            )
        if state["journalSchemaVersion"] >= 4:
            initial_request = validate_pinned_review_request(
                snapshot_findings["reviewRequest"],
                "initialized Review request",
            )
            handoff_request = validate_pinned_review_request(
                payload["reviewRequest"],
                "review_handoff_recorded reviewRequest",
            )
            initial_target = initial_request["target"]
            handoff_target = handoff_request["target"]
            request_identity_matches = (
                handoff_target["kind"] == initial_target["kind"]
                and handoff_target["sourceFingerprint"]
                == payload["sourceFingerprint"]
                and handoff_request["requestedPaths"]
                == initial_request["requestedPaths"]
            )
            if initial_target["kind"] == "source":
                expected_request = rebind_review_request_source(
                    initial_request,
                    payload["sourceFingerprint"],
                    "post-fix Review request",
                )
                request_identity_matches = (
                    request_identity_matches
                    and handoff_request == expected_request
                )
            else:
                request_identity_matches = (
                    request_identity_matches
                    and handoff_target["baseIdentity"]
                    == initial_target["baseIdentity"]
                )
            if (
                not request_identity_matches
                or payload["reviewRequestSha256"]
                != handoff_request["requestSha256"]
                or payload["bindingsVerified"] is not True
            ):
                raise CampaignError(
                    "review_handoff_recorded Review request differs from the "
                    "initialized target or fixed source binding"
                )
        if (
            payload["findingIds"] != snapshot_findings["findingIds"]
            or payload["requiredFindingIds"]
            != snapshot_findings["requiredFindingIds"]
        ):
            raise CampaignError(
                "review_handoff_recorded finding set differs from the initialized Review"
            )
        expected_candidates = snapshot_findings.get("caseCandidateSha256s")
        if not isinstance(expected_candidates, dict) or (
            payload["caseCandidateSha256s"] != expected_candidates
        ):
            raise CampaignError(
                "review_handoff_recorded case candidates differ from the initialized Review"
            )
        unresolved = sorted(
            finding_id
            for finding_id in pending_fix.get("resolvedFindingIds", [])
            if payload["resolutionStates"].get(finding_id)
            not in {"resolved", "invalidated"}
        )
        if unresolved:
            raise CampaignError(
                "review_handoff_recorded leaves fix-resolved findings open: "
                + ", ".join(unresolved)
            )
        if any(
            fix.get("reviewHandoff", {}).get("manifestPath")
            == payload["manifestPath"]
            for fix in state["fixes"]
            if isinstance(fix.get("reviewHandoff"), dict)
        ):
            raise CampaignError(
                "review_handoff_recorded manifestPath must be unique per fix"
            )
        handoff = copy.deepcopy(payload)
        matching_fix["reviewHandoff"] = copy.deepcopy(handoff)
        pending_fix["reviewHandoff"] = copy.deepcopy(handoff)
        return state

    if event_type == "pending_fix_superseded":
        if state["journalSchemaVersion"] >= 4 and not strict_review_campaign(state):
            raise CampaignError(
                "pending_fix_superseded requires a request-bound semantic Review campaign"
            )
        if state["journalSchemaVersion"] < 4 and not review_attestation_campaign(
            state
        ):
            raise CampaignError(
                "pending_fix_superseded requires an attested semantic Review campaign"
            )
        pending_fix = state.get("pendingFix")
        if (
            state.get("status") != "FAILED"
            or state.get("currentAttemptId") is not None
            or not isinstance(pending_fix, dict)
        ):
            raise CampaignError(
                "pending_fix_superseded requires a closed FAILED campaign with a pending fix"
            )
        handoff = pending_fix.get("reviewHandoff")
        expected_manifest_sha256 = (
            handoff.get("manifestSha256") if isinstance(handoff, dict) else None
        )
        if (
            payload["fixId"] != pending_fix.get("fixId")
            or payload["fixedSourceFingerprint"]
            != pending_fix.get("fixedSourceFingerprint")
            or payload["reviewManifestSha256"]
            != expected_manifest_sha256
        ):
            raise CampaignError(
                "pending_fix_superseded does not bind the pending fix and stale Review"
            )
        source_changed = (
            payload["supersedingSourceFingerprint"]
            != pending_fix.get("fixedSourceFingerprint")
        )
        if (
            (payload["reason"] == "source-drift" and not source_changed)
            or (
                payload["reason"] == "review-manifest-drift"
                and (source_changed or not isinstance(handoff, dict))
            )
        ):
            raise CampaignError(
                "pending_fix_superseded reason does not match the pending binding"
            )
        matching_fix = next(
            (
                fix
                for fix in state["fixes"]
                if fix.get("fixId") == payload["fixId"]
            ),
            None,
        )
        if matching_fix is None or matching_fix != pending_fix:
            raise CampaignError(
                "pending_fix_superseded pending-fix projection is inconsistent"
            )
        if isinstance(matching_fix.get("supersession"), dict):
            raise CampaignError("pending_fix_superseded cannot be repeated")
        supersession = {
            "reason": payload["reason"],
            "reviewManifestSha256": payload["reviewManifestSha256"],
            "sourceFingerprint": payload["supersedingSourceFingerprint"],
        }
        matching_fix["supersession"] = copy.deepcopy(supersession)
        state["pendingFix"] = None
        state["currentSourceFingerprint"] = payload[
            "supersedingSourceFingerprint"
        ]
        state["status"] = "FAILED"
        return state

    raise CampaignError("unknown event type: " + event_type)


def replay_projection(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    state: Optional[Dict[str, Any]] = None
    for event in events:
        try:
            state = apply_event(state, event)
            if not isinstance(state, dict):
                raise CampaignError("event replay did not produce a projection")
            state["lastEventSeq"] = event["seq"]
            state["lastEventHash"] = event["hash"]
        except CampaignError:
            raise
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            sequence = event.get("seq", "?") if isinstance(event, dict) else "?"
            raise CampaignError(
                "invalid journal event payload at seq " + str(sequence)
            ) from exc
    if state is None:
        raise CampaignError("cannot replay an empty journal")
    require_projection_within_limit(state)
    return state


def count_statuses(state: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {status: 0 for status in sorted(CASE_STATUSES)}
    for case in state["cases"].values():
        status = case["status"]
        counts[status] = counts.get(status, 0) + 1
    return counts


def make_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    attempts = []
    for attempt in state["attempts"]:
        attempts.append(
            {
                "id": attempt["id"],
                "mode": attempt["mode"],
                "status": attempt["status"],
                "sourceFingerprint": attempt["sourceFingerprint"],
                "artifactDir": attempt["artifactDir"],
                "startedAt": attempt["startedAt"],
                "finishedAt": attempt["finishedAt"],
                "resumedFrom": attempt.get("resumedFrom"),
                "targetCaseId": attempt.get("targetCaseId"),
                "lastOutcome": attempt.get("lastOutcome"),
                "invalidationReason": attempt.get("invalidationReason"),
            }
        )
    cases = {}
    for case_id, case in state["cases"].items():
        case_summary = {
            "category": case["category"],
            "required": case["required"],
            "status": case["status"],
            "lastAttemptId": case["lastAttemptId"],
            "lastCaseRunId": case["lastCaseRunId"],
            "artifactDir": case["artifactDir"],
            "lastSourceFingerprint": case["lastSourceFingerprint"],
            "lastOutcome": case["lastOutcome"],
        }
        if state["journalSchemaVersion"] >= 3:
            case_summary.update(
                {
                    "quickStatus": case.get("quickStatus", "PENDING"),
                    "lastQuickAttemptId": case.get("lastQuickAttemptId"),
                    "lastQuickCaseRunId": case.get("lastQuickCaseRunId"),
                    "lastQuickOutcome": case.get("lastQuickOutcome"),
                }
            )
        cases[case_id] = case_summary
    fixes = copy.deepcopy(state["fixes"])
    pending_fix = copy.deepcopy(state["pendingFix"])
    if state["journalSchemaVersion"] >= 4:
        for fix in fixes + ([pending_fix] if isinstance(pending_fix, dict) else []):
            snapshot = fix.pop("fixedSourceSnapshot", None)
            if isinstance(snapshot, dict):
                fix["fixedSourceSnapshotFingerprint"] = snapshot.get("fingerprint")
    summary = {
        "schemaVersion": state["journalSchemaVersion"],
        "kernelVersion": state["kernelVersion"],
        "campaignId": state["campaignId"],
        "projectId": state["projectId"],
        "status": state["status"],
        "currentMode": state["currentMode"],
        "currentAttemptId": state["currentAttemptId"],
        "catalogFingerprint": state["catalogFingerprint"],
        "initialSourceFingerprint": state["initialSourceFingerprint"],
        "currentSourceFingerprint": state["currentSourceFingerprint"],
        "regressionBaselineSourceFingerprint": state[
            "regressionBaselineSourceFingerprint"
        ],
        "finalRegressionAttemptId": state["finalRegressionAttemptId"],
        "counts": count_statuses(state),
        "cases": cases,
        "attempts": attempts,
        "fixes": fixes,
        "pendingFix": pending_fix,
        "lastEventSeq": state["lastEventSeq"],
        "lastEventHash": state["lastEventHash"],
    }
    if state["journalSchemaVersion"] >= 3:
        summary["traceSnapshot"] = copy.deepcopy(state.get("traceSnapshot"))
    if state["journalSchemaVersion"] >= 4:
        summary["resumeMode"] = state.get("resumeMode")
    return summary


def require_projection_within_limit(state: Dict[str, Any]) -> None:
    """Reject a journal transition whose materialized caches cannot be read safely."""

    projections = (
        ("state projection", state),
        ("summary projection", make_summary(state)),
    )
    for label, projection in projections:
        if len(canonical_bytes(projection)) + 1 > MAX_PROJECTION_BYTES:
            raise CampaignError(label + " exceeds the safe size limit")


class Campaign:
    def __init__(
        self,
        adapter: Adapter,
        state: Dict[str, Any],
        snapshot_consistent: bool,
        summary_consistent: bool,
        read_only: bool = False,
    ) -> None:
        self.adapter = adapter
        self.state = state
        self.snapshot_consistent = snapshot_consistent
        self.summary_consistent = summary_consistent
        self.read_only = read_only

    @classmethod
    def initialize(cls, adapter: Adapter) -> "Campaign":
        if adapter.campaign_root.exists():
            if not adapter.campaign_root.is_dir():
                raise CampaignError("campaignRoot must be a directory")
        with CampaignLock(adapter.campaign_root):
            # The existence decision is authoritative only while holding the
            # campaign lock.  Concurrent initializers may both validate an
            # empty path before either enters here; exactly one may create the
            # journal.  campaign.lock is the sole permitted pre-existing entry.
            try:
                entries = [
                    item
                    for item in adapter.campaign_root.iterdir()
                    if item.name != "campaign.lock"
                ]
            except OSError as exc:
                raise CampaignError(
                    "cannot inspect campaignRoot for initialization"
                ) from exc
            if entries:
                raise CampaignError(
                    "campaignRoot is non-empty; refusing to overwrite existing content"
                )
            source_observation = observe_source(adapter)
            source_binding_errors = trace_source_binding_errors(
                adapter, source_observation
            )
            if source_binding_errors:
                raise CampaignError(source_binding_errors[0])
            source_fingerprint = source_observation["fingerprint"]
            attempts = adapter.campaign_root / "attempts"
            attempts.mkdir(mode=0o700)
            events_path = adapter.campaign_root / "events.jsonl"
            events_path.touch(mode=0o600)
            payload = {
                "kernelVersion": SCRIPT_VERSION,
                "journalSchemaVersion": JOURNAL_SCHEMA_VERSION,
                "artifactManifestVersion": ARTIFACT_MANIFEST_VERSION,
                "campaignId": "campaign-" + uuid.uuid4().hex[:16],
                "projectId": adapter.data["projectId"],
                "projectRoot": str(adapter.project_root),
                "campaignRoot": str(adapter.campaign_root),
                "sourceProvider": adapter.data["source"]["provider"],
                "runtimePlatform": current_platform(),
                "catalogFingerprint": adapter.catalog_fingerprint,
                "catalog": copy.deepcopy(adapter.data),
                "sourceFingerprint": source_fingerprint,
                "cases": adapter.case_metadata(),
                "traceSnapshot": copy.deepcopy(adapter.trace_snapshot),
            }
            event = append_event(
                adapter.campaign_root,
                "campaign_initialized",
                payload,
                projection_state=None,
            )
            state = apply_event(None, event)
            state["lastEventSeq"] = event["seq"]
            state["lastEventHash"] = event["hash"]
            atomic_write_json(adapter.campaign_root / "state.json", state)
            atomic_write_json(
                adapter.campaign_root / "summary.json", make_summary(state)
            )
        return cls(adapter, state, True, True)

    @classmethod
    def load(cls, adapter: Adapter) -> "Campaign":
        require_safe_campaign_root(adapter.campaign_root)
        events = read_events(adapter.campaign_root / "events.jsonl")
        require_safe_owned_path(
            adapter.campaign_root,
            adapter.campaign_root / "campaign.lock",
            kind="campaign lock",
        )
        require_safe_owned_path(
            adapter.campaign_root,
            adapter.campaign_root / "attempts",
            kind="attempts directory",
        )
        state = replay_projection(events)
        journal_version = state.get("journalSchemaVersion")
        read_only = journal_version in READ_ONLY_JOURNAL_SCHEMA_VERSIONS
        expected_kernel = (
            LEGACY_KERNEL_VERSIONS.get(journal_version)
            if read_only
            else SCRIPT_VERSION
        )
        if state["kernelVersion"] != expected_kernel:
            raise CampaignError(
                "campaign kernel version is unsupported; choose a new campaign root"
            )
        if (
            journal_version >= 3
            and state.get("catalog", {}).get("traceability") is not None
            and adapter.traceability is not None
            and not adapter.trace_input_errors
            and adapter.trace_snapshot != state.get("traceSnapshot")
        ):
            raise CampaignError(
                "campaign trace snapshot does not match the pinned contracts"
            )
        if state["projectRoot"] != str(adapter.project_root) or state[
            "campaignRoot"
        ] != str(adapter.campaign_root):
            raise CampaignError("adapter roots do not match the initialized campaign")
        state_path = adapter.campaign_root / "state.json"
        summary_path = adapter.campaign_root / "summary.json"
        saved_state: Optional[Any] = None
        saved_summary: Optional[Any] = None
        state_metadata = require_safe_owned_path(
            adapter.campaign_root,
            state_path,
            kind="state projection",
            must_exist=False,
        )
        summary_metadata = require_safe_owned_path(
            adapter.campaign_root,
            summary_path,
            kind="summary projection",
            must_exist=False,
        )
        try:
            if state_metadata is None:
                raise CampaignError("state projection is missing")
            saved_state = read_owned_json(
                adapter.campaign_root,
                state_path,
                "state projection",
            )
        except CampaignError:
            pass
        try:
            if summary_metadata is None:
                raise CampaignError("summary projection is missing")
            saved_summary = read_owned_json(
                adapter.campaign_root,
                summary_path,
                "summary projection",
            )
        except CampaignError:
            pass
        snapshot_consistent = saved_state == state
        summary_consistent = saved_summary == make_summary(state)
        return cls(
            adapter,
            state,
            snapshot_consistent,
            summary_consistent,
            read_only=read_only,
        )

    def ensure_mutable(self) -> None:
        if self.read_only:
            raise CampaignError(
                "journal schema "
                + str(self.state.get("journalSchemaVersion"))
                + " is read-only under kernel "
                + SCRIPT_VERSION
                + "; preserve it and choose a new campaign root"
            )

    def reconcile_unjournaled_allocations(self) -> None:
        """Remove only provably empty shells left before their journal event."""

        self.ensure_mutable()
        self.validate_layout()
        attempts_root = self.adapter.campaign_root / "attempts"
        require_safe_owned_path(
            self.adapter.campaign_root,
            attempts_root,
            kind="attempts directory",
        )
        expected_attempts = {
            Path(attempt["artifactDir"]).name: attempt
            for attempt in self.state["attempts"]
        }
        observed_attempts = _directory_names(attempts_root, "attempts directory")

        for name in observed_attempts:
            if name in expected_attempts:
                continue
            match = ATTEMPT_ID_PATTERN.fullmatch(name)
            if (
                match is None
                or self.state.get("currentAttemptId") is not None
                or int(match.group("ordinal")) != len(self.state["attempts"]) + 1
            ):
                raise CampaignError(
                    "unexpected attempts entry is not a recoverable allocation: "
                    + name
                )
            attempt_path = attempts_root / name
            require_safe_owned_path(
                self.adapter.campaign_root,
                attempt_path,
                kind="unjournaled attempt allocation directory",
            )
            children = _directory_names(
                attempt_path, "unjournaled attempt allocation"
            )
            if children == ["cases"]:
                cases_path = attempt_path / "cases"
                _remove_empty_allocation_directory(
                    self.adapter.campaign_root,
                    cases_path,
                    "unjournaled attempt cases allocation",
                )
            elif children:
                raise CampaignError(
                    "unjournaled attempt allocation contains unexpected content: "
                    + name
                )
            _remove_empty_allocation_directory(
                self.adapter.campaign_root,
                attempt_path,
                "unjournaled attempt allocation",
            )

        active_attempt_id = self.state.get("currentAttemptId")
        for name, attempt in expected_attempts.items():
            attempt_path = attempts_root / name
            cases_path = attempt_path / "cases"
            require_safe_owned_path(
                self.adapter.campaign_root,
                attempt_path,
                kind="attempt directory",
            )
            require_safe_owned_path(
                self.adapter.campaign_root,
                cases_path,
                kind="case artifacts directory",
            )
            expected_runs = {
                Path(run["artifactDir"]).name for run in attempt.get("caseRuns", [])
            }
            for run_name in _directory_names(
                cases_path, "case artifacts directory"
            ):
                if run_name in expected_runs:
                    continue
                if attempt["id"] != active_attempt_id or attempt["status"] != "RUNNING":
                    raise CampaignError(
                        "unexpected case artifact is not a recoverable allocation: "
                        + run_name
                    )
                valid_allocation = False
                for ordinal, case in enumerate(self.adapter.cases, start=1):
                    if attempt["mode"] == "retest":
                        if case["id"] != attempt.get("targetCaseId"):
                            continue
                        expected_ordinal = 1
                    else:
                        expected_ordinal = ordinal
                    prefix = "%s-%03d-%s-" % (
                        attempt["id"],
                        expected_ordinal,
                        slug(case["id"]),
                    )
                    if re.fullmatch(re.escape(prefix) + r"[0-9a-f]{8}", run_name):
                        valid_allocation = True
                        break
                if not valid_allocation:
                    raise CampaignError(
                        "unexpected case artifact is not a recoverable allocation: "
                        + run_name
                    )
                _remove_empty_allocation_directory(
                    self.adapter.campaign_root,
                    cases_path / run_name,
                    "unjournaled case allocation",
                )

    def ensure_catalog(self) -> None:
        if current_platform() != self.state["runtimePlatform"]:
            raise CampaignError(
                "runtime platform differs from the initialized campaign; choose a new campaign root"
            )
        if self.adapter.catalog_fingerprint != self.state["catalogFingerprint"]:
            raise CampaignError(
                "adapter catalog drift detected; reinitialize before executing"
            )
        try:
            observed = validate_adapter(
                self.adapter.path,
                observe_trace_drift=True,
            )
        except CampaignError as exc:
            raise CampaignError("adapter catalog is no longer valid") from exc
        if observed.catalog_fingerprint != self.state["catalogFingerprint"]:
            raise CampaignError(
                "adapter catalog drift detected; reinitialize before executing"
            )
        trace_errors = list(observed.trace_input_errors)
        try:
            observation = observe_source(observed)
            trace_errors.extend(
                trace_source_binding_errors(observed, observation)
            )
        except CampaignError as exc:
            raise CampaignError("adapter catalog is no longer valid") from exc
        if trace_errors:
            review_baseline_only = strict_review_campaign(self.state) and all(
                "REVIEW_BASELINE_DRIFT" in error for error in trace_errors
            )
            if not review_baseline_only:
                raise CampaignError(
                    "adapter trace inputs are no longer valid: " + trace_errors[0]
                )

    def catalog_drift_reason(self) -> Optional[str]:
        try:
            observed = validate_adapter(
                self.adapter.path,
                observe_trace_drift=True,
            )
        except CampaignError:
            return "adapter catalog became invalid during execution"
        if observed.catalog_fingerprint != self.state["catalogFingerprint"]:
            return "adapter catalog drifted during execution"
        trace_errors = list(observed.trace_input_errors)
        try:
            trace_errors.extend(
                trace_source_binding_errors(observed, observe_source(observed))
            )
        except CampaignError:
            return "adapter trace inputs became invalid during execution"
        if trace_errors and not (
            strict_review_campaign(self.state)
            and all("REVIEW_BASELINE_DRIFT" in error for error in trace_errors)
        ):
            return "adapter trace inputs drifted during execution"
        return None

    def current_source(self) -> str:
        return fingerprint_source(self.adapter)

    def current_source_observation(self) -> Dict[str, Any]:
        return observe_source(self.adapter)

    def commit(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.ensure_mutable()
        self.validate_layout()
        event = append_event(
            self.adapter.campaign_root,
            event_type,
            payload,
            projection_state=self.state,
        )
        self.state = apply_event(self.state, event)
        self.state["lastEventSeq"] = event["seq"]
        self.state["lastEventHash"] = event["hash"]
        atomic_write_json(self.adapter.campaign_root / "state.json", self.state)
        atomic_write_json(
            self.adapter.campaign_root / "summary.json", make_summary(self.state)
        )
        self.validate_layout()

    def summary(self) -> Dict[str, Any]:
        return make_summary(self.state)

    def rebuild_projections(self) -> None:
        """Materialize journal-derived projections without changing the journal."""

        self.ensure_mutable()
        self.validate_layout(allow_missing_projections=True)
        atomic_write_json(self.adapter.campaign_root / "state.json", self.state)
        atomic_write_json(
            self.adapter.campaign_root / "summary.json", make_summary(self.state)
        )
        self.snapshot_consistent = True
        self.summary_consistent = True
        self.validate_layout()

    def validate_layout(self, *, allow_missing_projections: bool = False) -> None:
        require_safe_campaign_root(self.adapter.campaign_root)
        require_safe_owned_path(
            self.adapter.campaign_root,
            self.adapter.campaign_root / "campaign.lock",
            kind="campaign lock",
        )
        require_safe_owned_path(
            self.adapter.campaign_root,
            self.adapter.campaign_root / "events.jsonl",
            kind="event journal",
        )
        require_safe_owned_path(
            self.adapter.campaign_root,
            self.adapter.campaign_root / "attempts",
            kind="attempts directory",
        )
        for name, label in (
            ("state.json", "state projection"),
            ("summary.json", "summary projection"),
        ):
            require_safe_owned_path(
                self.adapter.campaign_root,
                self.adapter.campaign_root / name,
                kind=label,
                must_exist=not allow_missing_projections,
            )

    def initial_complete(self) -> bool:
        for case in self.state["cases"].values():
            if case["status"] in INITIAL_PASS_STATUSES:
                continue
            if (
                case["status"] == "NOT_RUN"
                and case["terminalSkip"]
                and not case["required"]
            ):
                continue
            return False
        return all(
            case["status"] in INITIAL_PASS_STATUSES
            for case in self.state["cases"].values()
            if case["required"]
        )

    def required_initial_passed(self) -> bool:
        return all(
            case["status"] in INITIAL_PASS_STATUSES
            for case in self.state["cases"].values()
            if case["required"]
        )

    def pending_initial_cases(self) -> List[Dict[str, Any]]:
        result = []
        for case in self.adapter.cases:
            state_case = self.state["cases"][case["id"]]
            if state_case["status"] in INITIAL_PASS_STATUSES:
                continue
            if state_case["status"] == "NOT_RUN" and state_case["terminalSkip"]:
                continue
            result.append(case)
        return result

    def start_attempt(
        self,
        mode: str,
        source_fingerprint: str,
        resumed_from: Optional[str] = None,
        target_case_id: Optional[str] = None,
    ) -> str:
        self.ensure_mutable()
        source_observation = self.current_source_observation()
        if source_observation["fingerprint"] != source_fingerprint:
            raise CampaignError("source changed before the attempt could be started")
        attempt_source_snapshot = source_snapshot(
            self.adapter, source_observation
        )
        ordinal = len(self.state["attempts"]) + 1
        if ordinal > MAX_ATTEMPT_ORDINAL:
            raise CampaignError("campaign attempt limit reached")
        self.reconcile_unjournaled_allocations()
        attempt_id = "attempt-%04d-%s-%s" % (ordinal, mode, uuid.uuid4().hex[:8])
        artifact_relative = "attempts/" + attempt_id
        artifact_root = self.adapter.campaign_root / artifact_relative
        self.validate_layout()
        attempts_root = self.adapter.campaign_root / "attempts"
        require_safe_owned_path(
            self.adapter.campaign_root,
            attempts_root,
            kind="attempts directory",
        )
        artifact_root.mkdir(mode=0o700)
        require_safe_owned_path(
            self.adapter.campaign_root,
            artifact_root,
            kind="attempt directory",
        )
        cases_root = artifact_root / "cases"
        cases_root.mkdir(mode=0o700)
        require_safe_owned_path(
            self.adapter.campaign_root,
            cases_root,
            kind="case artifacts directory",
        )
        # Make every allocation ancestor durable before its journal event can
        # make the corresponding path authoritative.
        _fsync_directory(
            cases_root,
            required=True,
            label="case artifacts directory",
        )
        _fsync_directory(
            artifact_root,
            required=True,
            label="attempt directory",
        )
        _fsync_directory(
            attempts_root,
            required=True,
            label="attempts directory",
        )
        if self.current_source_observation() != source_observation:
            raise CampaignError("source changed while the attempt was being started")
        self.commit(
            "attempt_started",
            {
                "attemptId": attempt_id,
                "mode": mode,
                "sourceFingerprint": source_fingerprint,
                "catalogFingerprint": self.state["catalogFingerprint"],
                "artifactDir": artifact_relative,
                "resumedFrom": resumed_from,
                "targetCaseId": target_case_id,
                "sourceSnapshot": attempt_source_snapshot,
            },
        )
        return attempt_id

    def allocate_case_artifact(
        self, attempt_id: str, case_id: str, ordinal: int
    ) -> Tuple[str, Path]:
        self.ensure_mutable()
        self.reconcile_unjournaled_allocations()
        attempt = get_attempt(self.state, attempt_id)
        run_id = "%s-%03d-%s-%s" % (
            attempt_id,
            ordinal,
            slug(case_id),
            uuid.uuid4().hex[:8],
        )
        relative = attempt["artifactDir"] + "/cases/" + run_id
        path = self.adapter.campaign_root / relative
        self.validate_layout()
        attempt_root = self.adapter.campaign_root / attempt["artifactDir"]
        cases_root = attempt_root / "cases"
        require_safe_owned_path(
            self.adapter.campaign_root,
            attempt_root,
            kind="attempt directory",
        )
        require_safe_owned_path(
            self.adapter.campaign_root,
            cases_root,
            kind="case artifacts directory",
        )
        path.mkdir(mode=0o700)
        require_safe_owned_path(
            self.adapter.campaign_root,
            path,
            kind="case artifact directory",
        )
        _fsync_directory(
            path,
            required=True,
            label="case artifact directory",
        )
        _fsync_directory(
            cases_root,
            required=True,
            label="case artifacts directory",
        )
        return run_id, path

    def mark_interrupted(
        self, reason: str = "runner stopped before final case event"
    ) -> None:
        self.ensure_mutable()
        self.reconcile_unjournaled_allocations()
        attempt_id = self.state.get("currentAttemptId")
        if not attempt_id:
            return
        attempt = get_attempt(self.state, attempt_id)
        if attempt["status"] != "RUNNING":
            return
        interrupted = [
            run["runId"] for run in attempt["caseRuns"] if run["status"] == "RUNNING"
        ]
        self.commit(
            "attempt_interrupted",
            {
                "attemptId": attempt_id,
                "interruptedRunIds": interrupted,
                "reason": reason,
            },
        )


__all__ = [
    "Campaign",
    "CampaignError",
    "CampaignLock",
    "get_attempt",
    "read_events",
    "replay_projection",
]
