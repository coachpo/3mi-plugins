#!/usr/bin/env python3
"""Strict project invariant bindings shared by steward skills.

The project-local ``.steward/invariants.json`` file is a machine index.
It never replaces the canonical project documents named by each binding.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Union

SCHEMA_VERSION = 1
INVARIANT_MAP_RELATIVE_PATH = ".steward/invariants.json"
ROUTER_START_MARKER = "<!-- write-agent-guides:engineering-router:start -->"
ROUTER_END_MARKER = "<!-- write-agent-guides:engineering-router:end -->"

INVARIANT_ID_RE = re.compile(r"^INV-[A-Z][A-Z0-9]*-[0-9A-F]{12}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
PROFILE_VERSION_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
ANCHOR_RE = re.compile(r"^[a-z][a-z0-9-]*$")

APPLICABILITY_STATES = {"applicable", "not_applicable", "unverified"}
AUDIT_STATES = {
    "direct",
    "equivalent",
    "not_applicable",
    "unverified",
    "noncompliant",
    "accepted_deviation",
    "migrating",
}
ENFORCEMENT_KINDS = {"manual", "mechanical"}
MAX_INVARIANT_MAP_BYTES = 8 * 1024 * 1024
MAX_PROJECT_REFERENCE_BYTES = 8 * 1024 * 1024


class InvariantContractError(ValueError):
    """A deterministic, actionable invariant-contract error."""


@dataclass(frozen=True)
class ProfileSource:
    kind: str
    profile_id: str
    profile_version: str
    profile_digest: str


@dataclass(frozen=True)
class ProjectSource:
    kind: str
    version: str
    digest: str


InvariantSource = Union[ProfileSource, ProjectSource]  # noqa: UP007 -- Python 3.9


@dataclass(frozen=True)
class ProfileSelection:
    path: str
    digest: str


@dataclass(frozen=True)
class Authority:
    path: str
    anchor: str

    @property
    def target(self) -> str:
        return f"{self.path}#{self.anchor}"


@dataclass(frozen=True)
class Enforcement:
    kind: str
    evidence: tuple[str, ...]
    validation_entry: str | None


@dataclass(frozen=True)
class ScopeApplicability:
    scope: str
    state: str


@dataclass(frozen=True)
class InvariantInstance:
    invariant_id: str
    scope: str
    applicability: str

    @property
    def is_triggered(self) -> bool:
        return self.applicability != "not_applicable"


@dataclass(frozen=True)
class InvariantBinding:
    invariant_id: str
    source: InvariantSource
    scopes: tuple[str, ...]
    trigger: str
    authority: Authority
    applicability: str
    status: str
    evidence: tuple[str, ...]
    equivalent_control: str | None
    not_applicable_reason: str | None
    enforcement: Enforcement
    applicability_by_scope: tuple[ScopeApplicability, ...] | None = None

    @property
    def is_hard(self) -> bool:
        # Architecture profiles expose only outcome-level ``must`` invariants;
        # project-local invariant bindings use the same hard-invariant contract.
        return True

    @property
    def is_triggered(self) -> bool:
        return self.applicability != "not_applicable"

    @property
    def scoped_instances(self) -> tuple[InvariantInstance, ...]:
        states = self.applicability_by_scope or tuple(
            ScopeApplicability(scope, self.applicability) for scope in self.scopes
        )
        return tuple(
            InvariantInstance(self.invariant_id, item.scope, item.state)
            for item in states
        )

    @property
    def triggered_scopes(self) -> tuple[str, ...]:
        return tuple(
            instance.scope
            for instance in self.scoped_instances
            if instance.is_triggered
        )


@dataclass(frozen=True)
class InvariantMap:
    schema_version: int
    bindings: tuple[InvariantBinding, ...]
    invariant_map_sha256: str
    profile_selection: ProfileSelection | None = None

    @property
    def hard_invariant_ids(self) -> tuple[str, ...]:
        return tuple(
            binding.invariant_id for binding in self.bindings if binding.is_hard
        )

    @property
    def triggered_hard_invariant_ids(self) -> tuple[str, ...]:
        return tuple(
            binding.invariant_id
            for binding in self.bindings
            if binding.is_hard and binding.is_triggered
        )

    @property
    def hard_invariant_instances(self) -> tuple[InvariantInstance, ...]:
        return tuple(
            instance
            for binding in self.bindings
            if binding.is_hard
            for instance in binding.scoped_instances
        )

    @property
    def triggered_hard_invariant_instances(self) -> tuple[InvariantInstance, ...]:
        return tuple(
            instance
            for instance in self.hard_invariant_instances
            if instance.is_triggered
        )

    def binding_by_id(self) -> dict[str, InvariantBinding]:
        return {binding.invariant_id: binding for binding in self.bindings}


def _reject_duplicate_pairs(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvariantContractError(f"JSON object has a duplicate key: {key}")
        result[key] = value
    return result


def _read_bounded_regular_file(
    path: Path,
    *,
    label: str,
    max_bytes: int,
) -> bytes:
    try:
        inspected = path.lstat()
    except OSError as error:
        raise InvariantContractError(
            f"{label} must be a regular, non-symlink file"
        ) from error
    if not stat.S_ISREG(inspected.st_mode):
        raise InvariantContractError(
            f"{label} must be a regular, non-symlink file"
        )
    if inspected.st_size > max_bytes:
        raise InvariantContractError(f"{label} exceeds the size limit")

    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise InvariantContractError(
                f"{label} must be a regular, non-symlink file"
            )
        if (opened.st_dev, opened.st_ino) != (inspected.st_dev, inspected.st_ino):
            raise InvariantContractError(
                f"{label} changed between inspection and open"
            )
        if opened.st_size > max_bytes:
            raise InvariantContractError(f"{label} exceeds the size limit")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            raw = handle.read(max_bytes + 1)
    except InvariantContractError:
        raise
    except OSError as error:
        raise InvariantContractError(f"cannot read {label}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > max_bytes:
        raise InvariantContractError(f"{label} exceeds the size limit")
    return raw


def _read_invariant_map(path: Path) -> bytes:
    return _read_bounded_regular_file(
        path,
        label="invariant map",
        max_bytes=MAX_INVARIANT_MAP_BYTES,
    )


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise InvariantContractError("invariant map is not canonical JSON") from error


def invariant_map_view(invariant_map: InvariantMap) -> dict[str, Any]:
    """Return the path-independent canonical JSON view of a validated map."""

    bindings: list[dict[str, Any]] = []
    for binding in invariant_map.bindings:
        if isinstance(binding.source, ProfileSource):
            source: dict[str, Any] = {
                "kind": "profile",
                "profileId": binding.source.profile_id,
                "profileVersion": binding.source.profile_version,
                "profileDigest": binding.source.profile_digest,
            }
        else:
            source = {
                "kind": "project",
                "version": binding.source.version,
                "digest": binding.source.digest,
            }
        enforcement: dict[str, Any] = {
            "kind": binding.enforcement.kind,
            "evidence": list(binding.enforcement.evidence),
        }
        if binding.enforcement.validation_entry is not None:
            enforcement["validationEntry"] = binding.enforcement.validation_entry
        item: dict[str, Any] = {
            "invariantId": binding.invariant_id,
            "source": source,
            "scopes": list(binding.scopes),
            "trigger": binding.trigger,
            "authority": {
                "path": binding.authority.path,
                "anchor": binding.authority.anchor,
            },
            "applicability": binding.applicability,
            "status": binding.status,
            "evidence": list(binding.evidence),
            "enforcement": enforcement,
        }
        if binding.equivalent_control is not None:
            item["equivalentControl"] = binding.equivalent_control
        if binding.not_applicable_reason is not None:
            item["notApplicableReason"] = binding.not_applicable_reason
        if binding.applicability_by_scope is not None:
            item["applicabilityByScope"] = [
                {"scope": scoped.scope, "state": scoped.state}
                for scoped in binding.applicability_by_scope
            ]
        bindings.append(item)
    view: dict[str, Any] = {
        "schemaVersion": invariant_map.schema_version,
        "bindings": bindings,
    }
    if invariant_map.profile_selection is not None:
        view["profileSelection"] = {
            "path": invariant_map.profile_selection.path,
            "digest": invariant_map.profile_selection.digest,
        }
    return view


def invariant_map_canonical_bytes(invariant_map: InvariantMap) -> bytes:
    """Return deterministic canonical JSON bytes without a trailing newline."""

    return _canonical_bytes(invariant_map_view(invariant_map))


def invariant_map_sha256(invariant_map: InvariantMap) -> str:
    """Hash the canonical invariant-map content, independent of its path/layout."""

    return "sha256:" + hashlib.sha256(
        invariant_map_canonical_bytes(invariant_map)
    ).hexdigest()


def aggregate_applicability(states: Iterable[str]) -> str:
    """Aggregate compiled scope states without making false N/A claims."""

    values = tuple(states)
    if not values:
        raise InvariantContractError("applicability aggregation requires scopes")
    unknown = sorted(set(values) - APPLICABILITY_STATES)
    if unknown:
        raise InvariantContractError(
            "applicability aggregation has unsupported states: "
            + ", ".join(unknown)
        )
    if "applicable" in values:
        return "applicable"
    if "unverified" in values:
        return "unverified"
    return "not_applicable"


def _expect_object(
    value: Any,
    label: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvariantContractError(f"{label} must be an object")
    allowed = required | (optional or set())
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise InvariantContractError(
            f"{label} has unknown fields: {', '.join(unknown)}"
        )
    missing = sorted(required - set(value))
    if missing:
        raise InvariantContractError(
            f"{label} is missing fields: {', '.join(missing)}"
        )
    return value


def _expect_text(value: Any, label: str, *, table_safe: bool = False) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise InvariantContractError(f"{label} must be a non-empty string")
    line_separators = "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"
    if value != value.strip() or any(
        character in value for character in line_separators
    ):
        raise InvariantContractError(f"{label} must be one trimmed line")
    if table_safe and any(character in value for character in "|<>"):
        raise InvariantContractError(
            f"{label} must not contain Markdown table or raw-HTML metacharacters"
        )
    return value


def _relative_path(value: Any, label: str, *, allow_root: bool = False) -> str:
    text = _expect_text(value, label, table_safe=True)
    if (
        "\\" in text
        or "`" in text
        or text.startswith("/")
        or re.match(r"^[A-Za-z]:", text)
    ):
        raise InvariantContractError(f"{label} must be a POSIX relative path")
    parts = PurePosixPath(text).parts
    if ".." in parts or any(part == "" for part in parts):
        raise InvariantContractError(f"{label} contains path traversal")
    normalized = PurePosixPath(text).as_posix()
    if normalized != text or (normalized == "." and not allow_root):
        raise InvariantContractError(f"{label} is not a normalized relative path")
    return text


def _reference(value: Any, label: str) -> str:
    text = _expect_text(value, label, table_safe=True)
    path_text, separator, anchor = text.partition("#")
    _relative_path(path_text, label)
    if separator and (not anchor or not ANCHOR_RE.fullmatch(anchor)):
        raise InvariantContractError(f"{label} has an invalid anchor")
    return text


def _string_array(
    value: Any,
    label: str,
    *,
    allow_empty: bool = True,
    references: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise InvariantContractError(f"{label} must be a string array")
    if not allow_empty and not value:
        raise InvariantContractError(f"{label} must not be empty")
    parsed = tuple(
        _reference(item, f"{label} item")
        if references
        else _expect_text(item, f"{label} item", table_safe=True)
        for item in value
    )
    if len(set(parsed)) != len(parsed):
        raise InvariantContractError(f"{label} contains duplicate values")
    if parsed != tuple(sorted(parsed)):
        raise InvariantContractError(f"{label} must be sorted")
    return parsed


def _parse_source(value: Any, label: str) -> InvariantSource:
    if not isinstance(value, dict):
        raise InvariantContractError(f"{label} must be an object")
    kind = value.get("kind")
    if kind == "profile":
        source = _expect_object(
            value,
            label,
            required={"kind", "profileId", "profileVersion", "profileDigest"},
        )
        profile_id = _expect_text(source["profileId"], f"{label}.profileId")
        if not PROFILE_ID_RE.fullmatch(profile_id):
            raise InvariantContractError(f"{label}.profileId is invalid")
        profile_version = _expect_text(
            source["profileVersion"], f"{label}.profileVersion"
        )
        if not PROFILE_VERSION_RE.fullmatch(profile_version):
            raise InvariantContractError(f"{label}.profileVersion is invalid")
        profile_digest = _expect_text(
            source["profileDigest"], f"{label}.profileDigest"
        )
        if not DIGEST_RE.fullmatch(profile_digest):
            raise InvariantContractError(f"{label}.profileDigest is invalid")
        return ProfileSource("profile", profile_id, profile_version, profile_digest)
    if kind == "project":
        source = _expect_object(
            value,
            label,
            required={"kind", "version", "digest"},
        )
        version = _expect_text(source["version"], f"{label}.version")
        digest = _expect_text(source["digest"], f"{label}.digest")
        if not DIGEST_RE.fullmatch(digest):
            raise InvariantContractError(f"{label}.digest is invalid")
        return ProjectSource("project", version, digest)
    raise InvariantContractError(f"{label}.kind must be profile or project")


def _parse_profile_selection(value: Any) -> ProfileSelection:
    selection = _expect_object(
        value,
        "profileSelection",
        required={"path", "digest"},
    )
    path = _relative_path(selection["path"], "profileSelection.path")
    digest = _expect_text(selection["digest"], "profileSelection.digest")
    if not DIGEST_RE.fullmatch(digest):
        raise InvariantContractError("profileSelection.digest is invalid")
    return ProfileSelection(path, digest)


def _parse_authority(value: Any, label: str, invariant_id: str) -> Authority:
    authority = _expect_object(
        value, label, required={"path", "anchor"}
    )
    path = _relative_path(authority["path"], f"{label}.path")
    if not path.endswith(".md"):
        raise InvariantContractError(f"{label}.path must name a Markdown document")
    anchor = _expect_text(authority["anchor"], f"{label}.anchor")
    if not ANCHOR_RE.fullmatch(anchor):
        raise InvariantContractError(f"{label}.anchor is invalid")
    if anchor != invariant_id.lower():
        raise InvariantContractError(
            f"{label}.anchor must equal the lower-case invariant ID"
        )
    return Authority(path, anchor)


def _parse_enforcement(value: Any, label: str) -> Enforcement:
    enforcement = _expect_object(
        value,
        label,
        required={"kind", "evidence"},
        optional={"validationEntry"},
    )
    kind = _expect_text(enforcement["kind"], f"{label}.kind")
    if kind not in ENFORCEMENT_KINDS:
        raise InvariantContractError(f"{label}.kind is unsupported")
    evidence = _string_array(
        enforcement["evidence"], f"{label}.evidence", references=True
    )
    validation_entry = None
    if "validationEntry" in enforcement:
        validation_entry = _expect_text(
            enforcement["validationEntry"],
            f"{label}.validationEntry",
            table_safe=True,
        )
    if kind == "mechanical" and (not evidence or validation_entry is None):
        raise InvariantContractError(
            f"{label} claims mechanical enforcement without evidence and validationEntry"
        )
    return Enforcement(kind, evidence, validation_entry)


def _parse_applicability_by_scope(
    value: Any,
    label: str,
    scopes: tuple[str, ...],
) -> tuple[ScopeApplicability, ...]:
    if not isinstance(value, list) or not value:
        raise InvariantContractError(f"{label} must be a non-empty array")
    parsed: list[ScopeApplicability] = []
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        scoped = _expect_object(
            item,
            item_label,
            required={"scope", "state"},
        )
        scope = _relative_path(
            scoped["scope"], f"{item_label}.scope", allow_root=True
        )
        state = _expect_text(scoped["state"], f"{item_label}.state")
        if state not in APPLICABILITY_STATES:
            raise InvariantContractError(f"{item_label}.state is unsupported")
        parsed.append(ScopeApplicability(scope, state))
    scoped_values = tuple(parsed)
    parsed_scopes = tuple(item.scope for item in scoped_values)
    if parsed_scopes != tuple(sorted(set(parsed_scopes))):
        raise InvariantContractError(f"{label} scopes must be unique and sorted")
    if parsed_scopes != scopes:
        raise InvariantContractError(f"{label} scopes must exactly match binding scopes")
    return scoped_values


def _parse_binding(value: Any, index: int) -> InvariantBinding:
    label = f"bindings[{index}]"
    binding = _expect_object(
        value,
        label,
        required={
            "invariantId",
            "source",
            "scopes",
            "trigger",
            "authority",
            "applicability",
            "status",
            "evidence",
            "enforcement",
        },
        optional={
            "applicabilityByScope",
            "equivalentControl",
            "notApplicableReason",
        },
    )
    invariant_id = _expect_text(binding["invariantId"], f"{label}.invariantId")
    if not INVARIANT_ID_RE.fullmatch(invariant_id):
        raise InvariantContractError(f"{label}.invariantId is invalid")
    source = _parse_source(binding["source"], f"{label}.source")
    scopes = _string_array(binding["scopes"], f"{label}.scopes", allow_empty=False)
    scopes = tuple(
        _relative_path(scope, f"{label}.scopes item", allow_root=True)
        for scope in scopes
    )
    trigger = _expect_text(binding["trigger"], f"{label}.trigger", table_safe=True)
    authority = _parse_authority(
        binding["authority"], f"{label}.authority", invariant_id
    )
    applicability = _expect_text(
        binding["applicability"], f"{label}.applicability"
    )
    if applicability not in APPLICABILITY_STATES:
        raise InvariantContractError(f"{label}.applicability is unsupported")
    applicability_by_scope = None
    if "applicabilityByScope" in binding:
        applicability_by_scope = _parse_applicability_by_scope(
            binding["applicabilityByScope"],
            f"{label}.applicabilityByScope",
            scopes,
        )
        aggregated = aggregate_applicability(
            item.state for item in applicability_by_scope
        )
        if aggregated != applicability:
            raise InvariantContractError(
                f"{label}.applicability does not match applicabilityByScope"
            )
        if not isinstance(source, ProfileSource):
            raise InvariantContractError(
                f"{label}.applicabilityByScope is only valid for a profile source"
            )
    status = _expect_text(binding["status"], f"{label}.status")
    if status not in AUDIT_STATES:
        raise InvariantContractError(f"{label}.status is unsupported")
    evidence = _string_array(
        binding["evidence"], f"{label}.evidence", references=True
    )
    equivalent_control = None
    if "equivalentControl" in binding:
        equivalent_control = _expect_text(
            binding["equivalentControl"],
            f"{label}.equivalentControl",
            table_safe=True,
        )
    not_applicable_reason = None
    if "notApplicableReason" in binding:
        not_applicable_reason = _expect_text(
            binding["notApplicableReason"],
            f"{label}.notApplicableReason",
            table_safe=True,
        )
    if (status == "equivalent") != (equivalent_control is not None):
        raise InvariantContractError(
            f"{label}.equivalentControl is required iff status is equivalent"
        )
    not_applicable = status == "not_applicable" or applicability == "not_applicable"
    if (status == "not_applicable") != (applicability == "not_applicable"):
        raise InvariantContractError(
            f"{label} must align not_applicable status and applicability"
        )
    if not_applicable != (not_applicable_reason is not None):
        raise InvariantContractError(
            f"{label}.notApplicableReason is required iff not applicable"
        )
    if not_applicable and not evidence:
        raise InvariantContractError(
            f"{label}.evidence must record capability or scope evidence when "
            "not applicable"
        )
    enforcement = _parse_enforcement(
        binding["enforcement"], f"{label}.enforcement"
    )
    return InvariantBinding(
        invariant_id,
        source,
        scopes,
        trigger,
        authority,
        applicability,
        status,
        evidence,
        equivalent_control,
        not_applicable_reason,
        enforcement,
        applicability_by_scope,
    )


def _default_profiles_root() -> Path:
    return Path(__file__).resolve().parent.parent / "references" / "architecture-profiles"


def _load_profile_package(profiles_root: Path | None) -> tuple[Any, Any]:
    try:
        import architecture_profiles

        package = architecture_profiles.load_package(
            profiles_root or _default_profiles_root()
        )
    except (ImportError, OSError, ValueError) as error:
        raise InvariantContractError(
            f"cannot load architecture profile catalog: {error}"
        ) from error
    return architecture_profiles, package


def _validate_profile_sources(
    bindings: Sequence[InvariantBinding], profiles_root: Path | None
) -> tuple[Any, Any] | None:
    profile_bindings = [
        binding for binding in bindings if isinstance(binding.source, ProfileSource)
    ]
    if not profile_bindings:
        return None
    architecture_profiles, package = _load_profile_package(profiles_root)

    for binding in profile_bindings:
        source = binding.source
        assert isinstance(source, ProfileSource)
        profile = package.profiles.get(source.profile_id)
        if profile is None:
            raise InvariantContractError(
                f"{binding.invariant_id} references unknown profile {source.profile_id}"
            )
        if profile["profileVersion"] != source.profile_version:
            raise InvariantContractError(
                f"{binding.invariant_id} profileVersion does not match catalog"
            )
        if package.profile_digest(source.profile_id) != source.profile_digest:
            raise InvariantContractError(
                f"{binding.invariant_id} profileDigest does not match catalog"
            )
        invariants = {item["id"]: item for item in profile["invariants"]}
        invariant = invariants.get(binding.invariant_id)
        if invariant is None:
            raise InvariantContractError(
                f"{binding.invariant_id} is not defined by profile {source.profile_id}"
            )
        if invariant.get("level") != "must":
            raise InvariantContractError(
                f"{binding.invariant_id} is not a hard profile invariant"
            )
    return architecture_profiles, package


def _map_project_root(map_path: Path, project_root: Path | None) -> Path:
    if project_root is not None:
        root = project_root.resolve()
        try:
            map_path.resolve().relative_to(root)
        except (OSError, ValueError) as error:
            raise InvariantContractError(
                "invariant map must stay inside the explicit project root"
            ) from error
        return root
    if map_path.name == "invariants.json" and map_path.parent.name == ".steward":
        return map_path.parent.parent.resolve()
    raise InvariantContractError(
        "profileSelection requires the canonical .steward/invariants.json "
        "path or an explicit project_root"
    )


def _read_profile_selection_json(
    architecture_profiles: Any, selection_path: Path
) -> Any:
    raw = _read_bounded_regular_file(
        selection_path,
        label="profile selection",
        max_bytes=architecture_profiles.MAX_JSON_BYTES,
    )
    if (
        b"\r" in raw
        or not raw.endswith(b"\n")
        or raw != raw.rstrip(b" \t\n") + b"\n"
    ):
        raise InvariantContractError(
            "profile selection must use LF and exactly one trailing newline"
        )
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=architecture_profiles.reject_duplicate_pairs,
        )
    except InvariantContractError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise InvariantContractError(
            "profile selection is not valid UTF-8 JSON"
        ) from error


def _validate_profile_selection(
    map_path: Path,
    profile_selection: ProfileSelection | None,
    bindings: Sequence[InvariantBinding],
    profiles_root: Path | None,
    loaded_profile_package: tuple[Any, Any] | None,
    project_root: Path | None,
) -> None:
    scoped_bindings = [
        binding for binding in bindings if binding.applicability_by_scope is not None
    ]
    if profile_selection is None:
        if scoped_bindings:
            raise InvariantContractError(
                "applicabilityByScope requires a map-level profileSelection"
            )
        return

    if loaded_profile_package is None:
        architecture_profiles, package = _load_profile_package(profiles_root)
    else:
        architecture_profiles, package = loaded_profile_package

    root = _map_project_root(map_path, project_root)
    selection_path = _safe_project_file(root, profile_selection.path)
    if selection_path is None:
        raise InvariantContractError(
            "profileSelection.path must resolve to a regular project file"
        )
    try:
        selection = _read_profile_selection_json(
            architecture_profiles, selection_path
        )
        architecture_profiles.validate_selection(package, selection)
        if selection.get("contentDigest") != profile_selection.digest:
            raise InvariantContractError(
                "profileSelection.digest does not match selection contentDigest"
            )
        compiled = architecture_profiles.compile_selection(package, selection)
    except InvariantContractError:
        raise
    except (OSError, ValueError) as error:
        raise InvariantContractError(
            f"profileSelection is invalid: {error}"
        ) from error

    expected_invariants: dict[str, dict[str, Any]] = {}
    for invariant in compiled["invariants"]:
        invariant_id = invariant["id"]
        if invariant_id in expected_invariants:
            raise InvariantContractError(
                f"compiled profile selection duplicates {invariant_id}"
            )
        expected_invariants[invariant_id] = invariant

    profile_bindings = {
        binding.invariant_id: binding
        for binding in bindings
        if isinstance(binding.source, ProfileSource)
    }
    expected_ids = set(expected_invariants)
    actual_ids = set(profile_bindings)
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise InvariantContractError(
            "profile bindings do not match compiled selection: " + "; ".join(details)
        )

    for invariant_id in sorted(expected_ids):
        expected = expected_invariants[invariant_id]
        binding = profile_bindings[invariant_id]
        source = binding.source
        assert isinstance(source, ProfileSource)
        if (
            source.profile_id != expected["profileId"]
            or source.profile_version != expected["profileVersion"]
            or source.profile_digest != expected["profileDigest"]
        ):
            raise InvariantContractError(
                f"{invariant_id} source does not match compiled profile selection"
            )
        expected_scopes = tuple(expected["scopes"])
        if binding.scopes != expected_scopes:
            raise InvariantContractError(
                f"{invariant_id} scopes do not match compiled profile selection"
            )
        if binding.applicability_by_scope is None:
            raise InvariantContractError(
                f"{invariant_id} requires applicabilityByScope"
            )
        expected_applicability = tuple(
            ScopeApplicability(item["scope"], item["state"])
            for item in expected["applicabilityByScope"]
        )
        if binding.applicability_by_scope != expected_applicability:
            raise InvariantContractError(
                f"{invariant_id} applicabilityByScope does not match compiled selection"
            )


def load_invariant_map(
    path: Path | str,
    profiles_root: Path | str | None = None,
    *,
    project_root: Path | str | None = None,
) -> InvariantMap:
    """Load and validate one project-local invariant map.

    ``profiles_root`` is injectable for tests and alternate packaged profile
    roots. It defaults to the plugin's bundled architecture-profile package.
    ``project_root`` is needed only when a map with ``profileSelection`` is
    loaded from a non-canonical path; canonical project maps infer it.
    """

    map_path = Path(path)
    if map_path.parent.is_symlink():
        raise InvariantContractError(
            "invariant map must be a regular, non-symlink file"
        )
    raw = _read_invariant_map(map_path)
    if b"\r" in raw or not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise InvariantContractError(
            "invariant map must use LF and exactly one trailing newline"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs
        )
    except InvariantContractError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise InvariantContractError("invariant map is not valid UTF-8 JSON") from error
    document = _expect_object(
        value,
        "invariant map",
        required={"schemaVersion", "bindings"},
        optional={"profileSelection"},
    )
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        raise InvariantContractError("invariant map schemaVersion must be 1")
    values = document["bindings"]
    if not isinstance(values, list) or not values:
        raise InvariantContractError(
            "invariant map bindings must be a non-empty array"
        )
    bindings = tuple(_parse_binding(item, index) for index, item in enumerate(values))
    ids = [binding.invariant_id for binding in bindings]
    if len(set(ids)) != len(ids):
        raise InvariantContractError("invariant map contains duplicate invariant IDs")
    if ids != sorted(ids):
        raise InvariantContractError("invariant map bindings must be sorted by invariantId")
    profile_selection = None
    if "profileSelection" in document:
        profile_selection = _parse_profile_selection(document["profileSelection"])
    loaded_profile_package = _validate_profile_sources(
        bindings, Path(profiles_root) if profiles_root is not None else None
    )
    _validate_profile_selection(
        map_path,
        profile_selection,
        bindings,
        Path(profiles_root) if profiles_root is not None else None,
        loaded_profile_package,
        Path(project_root) if project_root is not None else None,
    )
    provisional = InvariantMap(
        SCHEMA_VERSION,
        bindings,
        "",
        profile_selection,
    )
    return InvariantMap(
        SCHEMA_VERSION,
        bindings,
        invariant_map_sha256(provisional),
        profile_selection,
    )


def find_invariant_map(project_root: Path | str) -> Path | None:
    path = Path(project_root) / INVARIANT_MAP_RELATIVE_PATH
    return path if path.exists() or path.is_symlink() else None


def _reference_path(reference: str) -> str:
    return reference.split("#", 1)[0]


def _visible_anchor_count(text: str, anchor: str) -> int:
    """Count exact standalone HTML anchors outside fences and comments."""

    count = 0
    fence: tuple[str, int] | None = None
    in_comment = False
    anchor_re = re.compile(
        rf"^[ \t]{{0,3}}<a[ \t]+id=[\"']{re.escape(anchor)}[\"']"
        rf"[ \t]*></a>[ \t]*$"
    )
    for line in text.splitlines():
        candidate = line.lstrip(" ")
        indentation = len(line) - len(candidate)
        if fence is not None:
            character, length = fence
            if indentation <= 3:
                run = len(candidate) - len(candidate.lstrip(character))
                if run >= length and not candidate[run:].strip(" \t"):
                    fence = None
            continue
        if indentation <= 3 and candidate[:1] in {"`", "~"}:
            character = candidate[0]
            run = len(candidate) - len(candidate.lstrip(character))
            if run >= 3 and not (character == "`" and "`" in candidate[run:]):
                fence = (character, run)
                continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if "<!--" in line:
            if "-->" not in line.split("<!--", 1)[1]:
                in_comment = True
            continue
        if anchor_re.fullmatch(line):
            count += 1
    return count


def _safe_project_file(root: Path, relative: str) -> Path | None:
    candidate = root / relative
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            return None
    try:
        candidate.resolve().relative_to(root)
        inspected = candidate.lstat()
    except (OSError, ValueError):
        return None
    return candidate if stat.S_ISREG(inspected.st_mode) else None


def validate_project_references(
    project_root: Path | str,
    invariant_map: InvariantMap,
    *,
    allowed_authorities: set[str] | None = None,
) -> list[str]:
    """Validate canonical authority anchors and repository evidence paths."""

    root = Path(project_root).resolve()
    errors: list[str] = []
    seen_authority_targets: set[str] = set()
    for binding in invariant_map.bindings:
        authority = binding.authority
        if allowed_authorities is not None and authority.path not in allowed_authorities:
            errors.append(
                f"{binding.invariant_id}: authority is not a canonical document: "
                f"{authority.path}"
            )
            continue
        target = _safe_project_file(root, authority.path)
        if target is None:
            errors.append(
                f"{binding.invariant_id}: canonical authority is missing: {authority.path}"
            )
        else:
            try:
                authority_bytes = _read_bounded_regular_file(
                    target,
                    label=f"canonical authority {authority.path}",
                    max_bytes=MAX_PROJECT_REFERENCE_BYTES,
                )
                text = authority_bytes.decode("utf-8")
            except InvariantContractError as error:
                errors.append(f"{binding.invariant_id}: {error}")
            except UnicodeError:
                errors.append(
                    f"{binding.invariant_id}: canonical authority is not readable UTF-8: "
                    f"{authority.path}"
                )
            else:
                count = _visible_anchor_count(text, authority.anchor)
                if count != 1:
                    errors.append(
                        f"{binding.invariant_id}: authority anchor must appear exactly once: "
                        f"{authority.target}"
                    )
                if isinstance(binding.source, ProjectSource):
                    actual_digest = (
                        "sha256:" + hashlib.sha256(authority_bytes).hexdigest()
                    )
                    if actual_digest != binding.source.digest:
                        errors.append(
                            f"{binding.invariant_id}: project source digest does not "
                            f"match canonical authority {authority.path}"
                        )
        if authority.target in seen_authority_targets:
            errors.append(f"duplicate authority target: {authority.target}")
        seen_authority_targets.add(authority.target)

        references = binding.evidence + binding.enforcement.evidence
        for reference in references:
            relative = _reference_path(reference)
            evidence_path = _safe_project_file(root, relative)
            if evidence_path is None:
                errors.append(
                    f"{binding.invariant_id}: evidence target is missing: {reference}"
                )
                continue
            try:
                evidence_bytes = _read_bounded_regular_file(
                    evidence_path,
                    label=f"evidence target {_reference_path(reference)}",
                    max_bytes=MAX_PROJECT_REFERENCE_BYTES,
                )
            except InvariantContractError as error:
                errors.append(f"{binding.invariant_id}: {error}")
                continue
            if "#" in reference:
                anchor = reference.split("#", 1)[1]
                try:
                    evidence_text = evidence_bytes.decode("utf-8")
                except UnicodeError:
                    errors.append(
                        f"{binding.invariant_id}: evidence target is not readable "
                        f"UTF-8: {reference}"
                    )
                else:
                    if _visible_anchor_count(evidence_text, anchor) != 1:
                        errors.append(
                            f"{binding.invariant_id}: evidence anchor must appear "
                            f"exactly once: {reference}"
                        )
    return errors


def router_rows(invariant_map: InvariantMap, *, language: str = "en") -> tuple[str, ...]:
    """Render deterministic four-column Markdown rows for triggered bindings."""

    if language not in {"en", "zh"}:
        raise InvariantContractError("router language must be en or zh")
    manual = "人工审查" if language == "zh" else "Manual review"
    rows: list[str] = []
    for binding in invariant_map.bindings:
        if not binding.is_triggered:
            continue
        scopes = ", ".join(f"`{scope}`" for scope in binding.triggered_scopes)
        trigger = f"{scopes}: {binding.trigger}"
        authority = f"[{binding.authority.path}]({binding.authority.target})"
        invariant = f"[{binding.invariant_id}]({binding.authority.target})"
        validation = binding.enforcement.validation_entry or manual
        rows.append(
            f"| {trigger} | {authority} | {invariant} | {validation} |"
        )
    return tuple(rows)


__all__ = [
    "APPLICABILITY_STATES",
    "AUDIT_STATES",
    "INVARIANT_MAP_RELATIVE_PATH",
    "ROUTER_END_MARKER",
    "ROUTER_START_MARKER",
    "Authority",
    "Enforcement",
    "InvariantBinding",
    "InvariantContractError",
    "InvariantInstance",
    "InvariantMap",
    "ProfileSelection",
    "ProfileSource",
    "ProjectSource",
    "ScopeApplicability",
    "aggregate_applicability",
    "find_invariant_map",
    "invariant_map_canonical_bytes",
    "invariant_map_sha256",
    "invariant_map_view",
    "load_invariant_map",
    "router_rows",
    "validate_project_references",
]
