#!/usr/bin/env python3
"""Validate, select, and compile plugin-owned architecture profiles.

The runtime commands consume only the compact, bundled JSON profiles.  Profile
content, versions, and digests are maintained directly by this plugin.

Profile ``platforms`` are validation targets, not necessarily command hosts.
In particular, ``android`` stays an Android target: a downstream campaign uses
its actual supported host enum and the generic ``platform`` scenario tag.  It
must not add Android to the campaign host-platform enum.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


PROFILE_SCHEMA_VERSION = 1
CATALOG_SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 1
SELECTION_SCHEMA_VERSION = 1
COMPILED_SCHEMA_VERSION = 1
COMPILER_VERSION = "1.0.0"
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_COMPONENTS = 256
MAX_SIGNALS_PER_COMPONENT = 128
MAX_CAPABILITIES_PER_COMPONENT = 128
PROFILE_KINDS = {"base", "overlay", "standalone"}
EXPECTED_PROFILE_SPECS = {
    "android": ("standalone", ()),
    "cloudflare-workers": ("standalone", ()),
    "django": ("overlay", ("python",)),
    "fastapi": ("overlay", ("python",)),
    "golang": ("standalone", ()),
    "python": ("base", ()),
    "tauri-2": ("standalone", ()),
}
LEVELS = {"must"}
AUDIT_STATES = (
    "direct",
    "equivalent",
    "not_applicable",
    "unverified",
    "noncompliant",
    "accepted_deviation",
    "migrating",
)
CAPABILITY_STATES = ("present", "absent", "unknown")
APPLICABILITY_STATES = {"applicable", "not_applicable", "unverified"}
EVIDENCE_KINDS = {
    "code",
    "config",
    "test",
    "build",
    "runtime",
    "documentation",
}
PLATFORMS = {"any", "darwin", "linux", "windows", "posix", "android"}
CAMPAIGN_HOST_PLATFORMS = {"any", "darwin", "linux", "windows", "posix"}
SIDE_EFFECTS = {"read-only", "local-artifacts", "local-source-format"}
SELECTION_SCOPES = {"component", "deployment-unit", "repository"}
PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]*$")
TOKEN_RE = re.compile(r"^[a-z][a-z0-9._:-]*$")
ITEM_ID_RE = re.compile(r"^[a-z][a-z0-9.-]*$")
INVARIANT_ID_RE = re.compile(r"^INV-[A-Z][A-Z0-9]*-[0-9A-F]{12}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PROFILE_VERSION_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z][A-Za-z0-9]*)\}\}")


class ProfileError(ValueError):
    """A deterministic, user-actionable profile contract error."""


def reject_duplicate_pairs(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError("JSON object has a duplicate key: " + key)
        result[key] = value
    return result


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ProfileError("value is not canonical JSON") from error


def content_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _read_bounded_regular_file(path: Path, label: str) -> bytes:
    try:
        inspected = path.lstat()
    except OSError as error:
        raise ProfileError(label + " must be a regular, non-symlink file") from error
    if not stat.S_ISREG(inspected.st_mode):
        raise ProfileError(label + " must be a regular, non-symlink file")
    if inspected.st_size > MAX_JSON_BYTES:
        raise ProfileError(label + " exceeds the JSON size limit")

    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ProfileError(label + " must be a regular, non-symlink file")
        if (opened.st_dev, opened.st_ino) != (inspected.st_dev, inspected.st_ino):
            raise ProfileError(label + " changed between inspection and open")
        if opened.st_size > MAX_JSON_BYTES:
            raise ProfileError(label + " exceeds the JSON size limit")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            raw = handle.read(MAX_JSON_BYTES + 1)
    except ProfileError:
        raise
    except OSError as error:
        raise ProfileError("cannot read " + label) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > MAX_JSON_BYTES:
        raise ProfileError(label + " exceeds the JSON size limit")
    return raw


def read_json(path: Path, label: str) -> Any:
    raw = _read_bounded_regular_file(path, label)
    if (
        b"\r" in raw
        or not raw.endswith(b"\n")
        or raw != raw.rstrip(b" \t\n") + b"\n"
    ):
        raise ProfileError(label + " must use LF and exactly one trailing newline")
    try:
        text = raw.decode("utf-8")
        return json.loads(text, object_pairs_hook=reject_duplicate_pairs)
    except ProfileError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ProfileError(label + " is not valid UTF-8 JSON") from error


def write_json(path: Optional[Path], value: Any) -> None:
    data = canonical_bytes(value) + b"\n"
    if len(data) > MAX_JSON_BYTES:
        raise ProfileError("output exceeds the JSON size limit")
    if path is None:
        sys.stdout.buffer.write(data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(path.parent),
            prefix="." + path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            with suppress(OSError):
                os.unlink(temporary)


def require_object(
    value: Any,
    label: str,
    allowed: Set[str],
    required: Set[str],
) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileError(label + " must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProfileError(label + " has unknown fields: " + ", ".join(unknown))
    missing = sorted(required - set(value))
    if missing:
        raise ProfileError(label + " is missing fields: " + ", ".join(missing))
    return value


def require_string(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
        or any(character in value for character in ("\u0085", "\u2028", "\u2029"))
    ):
        raise ProfileError(label + " must be a non-empty, trimmed single line")
    return value


def require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProfileError(label + " must be a boolean")
    return value


def campaign_platform_projection(
    target_platform: str, host_platform: str
) -> Tuple[str, Tuple[str, ...]]:
    """Project a profile target onto campaign host and scenario vocabularies.

    Android is intentionally not a host value: keep the actual host and attach
    the campaign's generic ``platform`` scenario tag so target-specific proof
    remains required.  The Android target itself remains in the profile rule
    and its evidence rather than being written into the campaign host field.
    """

    target = require_string(target_platform, "target platform")
    host = require_string(host_platform, "campaign host platform")
    if target not in PLATFORMS:
        raise ProfileError("target platform is unsupported")
    if host not in CAMPAIGN_HOST_PLATFORMS:
        raise ProfileError("campaign host platform is unsupported")
    return host, (("platform",) if target == "android" else ())


def string_list(
    value: Any,
    label: str,
    *,
    allow_empty: bool = True,
    values: Optional[Set[str]] = None,
    pattern: Optional[re.Pattern[str]] = None,
    sorted_unique: bool = True,
) -> List[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProfileError(label + " must be a string array")
    if not allow_empty and not value:
        raise ProfileError(label + " must not be empty")
    for item in value:
        require_string(item, label + " item")
        if values is not None and item not in values:
            raise ProfileError(label + " contains unsupported value: " + item)
        if pattern is not None and not pattern.fullmatch(item):
            raise ProfileError(label + " contains invalid value: " + item)
    if len(set(value)) != len(value):
        raise ProfileError(label + " contains duplicate values")
    if sorted_unique and value != sorted(value):
        raise ProfileError(label + " must be sorted")
    return value


def relative_path(value: Any, label: str, *, allow_dot: bool = False) -> str:
    text = require_string(value, label)
    if "\\" in text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise ProfileError(label + " must be a POSIX relative path")
    parts = PurePosixPath(text).parts
    if ".." in parts or any(part == "" for part in parts):
        raise ProfileError(label + " contains traversal")
    normalized = PurePosixPath(text).as_posix()
    if normalized == "." and not allow_dot:
        raise ProfileError(label + " must not name the root")
    if normalized != text:
        raise ProfileError(label + " is not normalized")
    return text


def safe_child(root: Path, relative: str, label: str) -> Path:
    normalized = relative_path(relative, label)
    candidate = root / normalized
    current = root
    for part in PurePosixPath(normalized).parts:
        current = current / part
        if current.is_symlink():
            raise ProfileError(label + " uses a symlink")
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError) as error:
        raise ProfileError(label + " escapes the profile root") from error
    return candidate


def validate_schema_version(value: Any, label: str, expected: int) -> None:
    if type(value) is not int or value != expected:
        raise ProfileError(label + " schemaVersion must be " + str(expected))


def validate_condition(value: Any, label: str) -> Dict[str, List[str]]:
    condition = require_object(
        value,
        label,
        {"allOf", "anyOf", "noneOf"},
        {"allOf", "anyOf", "noneOf"},
    )
    for key in ("allOf", "anyOf", "noneOf"):
        string_list(condition[key], label + "." + key, pattern=TOKEN_RE)
    required = set(condition["allOf"])
    alternatives = set(condition["anyOf"])
    excluded = set(condition["noneOf"])
    if required & alternatives:
        raise ProfileError(label + " repeats a capability in allOf and anyOf")
    if (required | alternatives) & excluded:
        raise ProfileError(label + " requires and excludes the same capability")
    return condition


def normalized_condition(value: Mapping[str, Sequence[str]]) -> Dict[str, List[str]]:
    return {
        "allOf": sorted(value.get("allOf", [])),
        "anyOf": sorted(value.get("anyOf", [])),
        "noneOf": sorted(value.get("noneOf", [])),
    }


def expected_invariant_id(profile: Mapping[str, Any], invariant: Mapping[str, Any]) -> str:
    identity = {
        "profileId": profile["id"],
        "level": invariant["level"],
        "when": normalized_condition(invariant["when"]),
        "outcome": invariant["outcome"],
    }
    suffix = hashlib.sha256(canonical_bytes(identity)).hexdigest()[:12].upper()
    return "INV-%s-%s" % (profile["invariantPrefix"], suffix)


def validate_profile(profile: Any, label: str) -> Dict[str, Any]:
    required = {
        "schemaVersion",
        "id",
        "profileVersion",
        "kind",
        "invariantPrefix",
        "extends",
        "baseline",
        "selection",
        "capabilities",
        "layering",
        "invariants",
        "checks",
        "scenarios",
    }
    profile = require_object(profile, label, required, required)
    validate_schema_version(profile["schemaVersion"], label, PROFILE_SCHEMA_VERSION)
    profile_id = require_string(profile["id"], label + ".id")
    if not PROFILE_ID_RE.fullmatch(profile_id):
        raise ProfileError(label + ".id is invalid")
    prefix = require_string(profile["invariantPrefix"], label + ".invariantPrefix")
    if not PREFIX_RE.fullmatch(prefix):
        raise ProfileError(label + ".invariantPrefix is invalid")
    version = require_string(profile["profileVersion"], label + ".profileVersion")
    if not PROFILE_VERSION_RE.fullmatch(version):
        raise ProfileError(label + ".profileVersion is invalid")
    kind = require_string(profile["kind"], label + ".kind")
    if kind not in PROFILE_KINDS:
        raise ProfileError(label + ".kind is unsupported")
    extends = string_list(profile["extends"], label + ".extends", pattern=PROFILE_ID_RE)
    if kind == "overlay" and not extends:
        raise ProfileError(label + " overlay must extend at least one profile")
    if kind != "overlay" and extends:
        raise ProfileError(label + " non-overlay must not extend profiles")
    if profile_id in extends:
        raise ProfileError(label + " cannot extend itself")

    baseline = require_object(
        profile["baseline"],
        label + ".baseline",
        {"authored", "technologies", "versionPolicy"},
        {"authored", "technologies", "versionPolicy"},
    )
    authored = require_string(baseline["authored"], label + ".baseline.authored")
    authored_match = re.fullmatch(r"[0-9]{4}-([0-9]{2})", authored)
    if not authored_match or not 1 <= int(authored_match.group(1)) <= 12:
        raise ProfileError(label + ".baseline.authored must use YYYY-MM")
    string_list(baseline["technologies"], label + ".baseline.technologies", allow_empty=False)
    require_string(baseline["versionPolicy"], label + ".baseline.versionPolicy")
    selection = require_object(
        profile["selection"],
        label + ".selection",
        {"scope", "activation", "supportingSignals"},
        {"scope", "activation", "supportingSignals"},
    )
    selection_scope = require_string(selection["scope"], label + ".selection.scope")
    if selection_scope not in SELECTION_SCOPES:
        raise ProfileError(label + ".selection.scope is unsupported")
    activation = selection["activation"]
    if not isinstance(activation, list) or not activation:
        raise ProfileError(label + ".selection.activation must be a non-empty array")
    for index, clause in enumerate(activation):
        condition = validate_condition(clause, "%s.selection.activation[%d]" % (label, index))
        if not condition["allOf"] and not condition["anyOf"]:
            raise ProfileError(label + ".selection activation needs allOf or anyOf evidence")
    string_list(selection["supportingSignals"], label + ".selection.supportingSignals", pattern=TOKEN_RE)

    capabilities = string_list(profile["capabilities"], label + ".capabilities", pattern=TOKEN_RE)
    capability_set = set(capabilities)

    layering = require_object(
        profile["layering"],
        label + ".layering",
        {"referenceOnly", "nodes", "edges", "hardOutcomes"},
        {"referenceOnly", "nodes", "edges", "hardOutcomes"},
    )
    if require_bool(layering["referenceOnly"], label + ".layering.referenceOnly") is not True:
        raise ProfileError(label + ".layering.referenceOnly must be true")
    if not isinstance(layering["nodes"], list) or not layering["nodes"]:
        raise ProfileError(label + ".layering.nodes must be a non-empty array")
    node_ids: Set[str] = set()
    for index, node_value in enumerate(layering["nodes"]):
        node_label = "%s.layering.nodes[%d]" % (label, index)
        node = require_object(node_value, node_label, {"id", "owns"}, {"id", "owns"})
        node_id = require_string(node["id"], node_label + ".id")
        if not ITEM_ID_RE.fullmatch(node_id) or node_id in node_ids:
            raise ProfileError(node_label + ".id is invalid or duplicate")
        node_ids.add(node_id)
        string_list(node["owns"], node_label + ".owns", allow_empty=False)
    if not isinstance(layering["edges"], list):
        raise ProfileError(label + ".layering.edges must be an array")
    seen_edges: Set[Tuple[str, str]] = set()
    for index, edge_value in enumerate(layering["edges"]):
        edge_label = "%s.layering.edges[%d]" % (label, index)
        edge = require_object(edge_value, edge_label, {"from", "to"}, {"from", "to"})
        pair = (require_string(edge["from"], edge_label + ".from"), require_string(edge["to"], edge_label + ".to"))
        if pair[0] not in node_ids or pair[1] not in node_ids or pair in seen_edges:
            raise ProfileError(edge_label + " has an unknown node or duplicate edge")
        seen_edges.add(pair)
    reachable = set()
    remaining = set(node_ids)
    while remaining:
        ready = {
            node_id
            for node_id in remaining
            if not any(
                target == node_id and source in remaining
                for source, target in seen_edges
            )
        }
        if not ready:
            raise ProfileError(label + ".layering.edges must be acyclic")
        reachable.update(ready)
        remaining.difference_update(ready)
    if reachable != node_ids:
        raise ProfileError(label + ".layering.edges do not cover known nodes")
    string_list(layering["hardOutcomes"], label + ".layering.hardOutcomes", allow_empty=False)

    invariants = profile["invariants"]
    if not isinstance(invariants, list) or not invariants:
        raise ProfileError(label + ".invariants must be a non-empty array")
    invariant_ids: Set[str] = set()
    for index, invariant_value in enumerate(invariants):
        invariant_label = "%s.invariants[%d]" % (label, index)
        fields = {
            "id",
            "level",
            "when",
            "outcome",
            "equivalenceCriteria",
            "evidenceKinds",
            "checkRefs",
            "scenarioRefs",
        }
        invariant = require_object(invariant_value, invariant_label, fields, fields)
        invariant_id = require_string(invariant["id"], invariant_label + ".id")
        if not INVARIANT_ID_RE.fullmatch(invariant_id) or invariant_id in invariant_ids:
            raise ProfileError(invariant_label + ".id is invalid or duplicate")
        invariant_ids.add(invariant_id)
        level = require_string(invariant["level"], invariant_label + ".level")
        if level not in LEVELS:
            raise ProfileError(invariant_label + ".level must be must")
        validate_condition(invariant["when"], invariant_label + ".when")
        require_string(invariant["outcome"], invariant_label + ".outcome")
        require_string(invariant["equivalenceCriteria"], invariant_label + ".equivalenceCriteria")
        string_list(
            invariant["evidenceKinds"],
            invariant_label + ".evidenceKinds",
            allow_empty=False,
            values=EVIDENCE_KINDS,
        )
        string_list(invariant["checkRefs"], invariant_label + ".checkRefs", pattern=ITEM_ID_RE)
        string_list(invariant["scenarioRefs"], invariant_label + ".scenarioRefs", pattern=ITEM_ID_RE)
        if not invariant["checkRefs"] and not invariant["scenarioRefs"]:
            raise ProfileError(invariant_label + " needs a check or scenario reference")
        expected_id = expected_invariant_id(profile, invariant)
        if invariant_id != expected_id:
            raise ProfileError(invariant_label + ".id must be content-derived: " + expected_id)

    checks = profile["checks"]
    if not isinstance(checks, list) or not checks:
        raise ProfileError(label + ".checks must be a non-empty array")
    check_ids: Set[str] = set()
    for index, check_value in enumerate(checks):
        check_label = "%s.checks[%d]" % (label, index)
        fields = {
            "id",
            "when",
            "platforms",
            "argvTemplate",
            "parameters",
            "sideEffect",
            "proves",
            "doesNotProve",
            "invariantRefs",
        }
        check = require_object(check_value, check_label, fields, fields)
        check_id = require_string(check["id"], check_label + ".id")
        if not ITEM_ID_RE.fullmatch(check_id) or check_id in check_ids or not check_id.startswith(profile_id + "."):
            raise ProfileError(check_label + ".id is invalid, duplicate, or unnamespaced")
        check_ids.add(check_id)
        validate_condition(check["when"], check_label + ".when")
        string_list(check["platforms"], check_label + ".platforms", allow_empty=False, values=PLATFORMS)
        argv = string_list(check["argvTemplate"], check_label + ".argvTemplate", allow_empty=False, sorted_unique=False)
        parameters = string_list(check["parameters"], check_label + ".parameters", pattern=re.compile(r"^[A-Za-z][A-Za-z0-9]*$"))
        placeholders = sorted(set(PLACEHOLDER_RE.findall("\n".join(argv))))
        if placeholders != parameters:
            raise ProfileError(check_label + ".parameters must exactly match argvTemplate placeholders")
        side_effect = require_string(check["sideEffect"], check_label + ".sideEffect")
        if side_effect not in SIDE_EFFECTS:
            raise ProfileError(check_label + ".sideEffect is unsupported")
        proves = string_list(
            check["proves"], check_label + ".proves", allow_empty=False
        )
        does_not_prove = string_list(
            check["doesNotProve"],
            check_label + ".doesNotProve",
            allow_empty=False,
        )
        if set(proves) & set(does_not_prove):
            raise ProfileError(check_label + " cannot prove and disclaim the same claim")
        refs = string_list(check["invariantRefs"], check_label + ".invariantRefs", allow_empty=False, pattern=INVARIANT_ID_RE)
        if not set(refs).issubset(invariant_ids):
            raise ProfileError(check_label + ".invariantRefs contains an unknown invariant")

    scenarios = profile["scenarios"]
    if not isinstance(scenarios, list) or not scenarios:
        raise ProfileError(label + ".scenarios must be a non-empty array")
    scenario_ids: Set[str] = set()
    for index, scenario_value in enumerate(scenarios):
        scenario_label = "%s.scenarios[%d]" % (label, index)
        fields = {
            "id",
            "when",
            "platforms",
            "failure",
            "requiredOutcome",
            "invariantRefs",
        }
        scenario = require_object(scenario_value, scenario_label, fields, fields)
        scenario_id = require_string(scenario["id"], scenario_label + ".id")
        if not ITEM_ID_RE.fullmatch(scenario_id) or scenario_id in scenario_ids or not scenario_id.startswith(profile_id + "."):
            raise ProfileError(scenario_label + ".id is invalid, duplicate, or unnamespaced")
        scenario_ids.add(scenario_id)
        validate_condition(scenario["when"], scenario_label + ".when")
        string_list(scenario["platforms"], scenario_label + ".platforms", allow_empty=False, values=PLATFORMS)
        require_string(scenario["failure"], scenario_label + ".failure")
        require_string(scenario["requiredOutcome"], scenario_label + ".requiredOutcome")
        refs = string_list(scenario["invariantRefs"], scenario_label + ".invariantRefs", allow_empty=False, pattern=INVARIANT_ID_RE)
        if not set(refs).issubset(invariant_ids):
            raise ProfileError(scenario_label + ".invariantRefs contains an unknown invariant")

    for index, invariant in enumerate(invariants):
        if not set(invariant["checkRefs"]).issubset(check_ids):
            raise ProfileError("%s.invariants[%d].checkRefs contains an unknown check" % (label, index))
        if not set(invariant["scenarioRefs"]).issubset(scenario_ids):
            raise ProfileError("%s.invariants[%d].scenarioRefs contains an unknown scenario" % (label, index))
    invariant_by_id = {invariant["id"]: invariant for invariant in invariants}
    check_by_id = {check["id"]: check for check in checks}
    scenario_by_id = {scenario["id"]: scenario for scenario in scenarios}
    for invariant in invariants:
        for check_id in invariant["checkRefs"]:
            if invariant["id"] not in check_by_id[check_id]["invariantRefs"]:
                raise ProfileError(
                    "%s and %s must reference each other"
                    % (invariant["id"], check_id)
                )
        for scenario_id in invariant["scenarioRefs"]:
            if invariant["id"] not in scenario_by_id[scenario_id]["invariantRefs"]:
                raise ProfileError(
                    "%s and %s must reference each other"
                    % (invariant["id"], scenario_id)
                )
    for check in checks:
        for invariant_id in check["invariantRefs"]:
            if check["id"] not in invariant_by_id[invariant_id]["checkRefs"]:
                raise ProfileError(
                    "%s and %s must reference each other"
                    % (check["id"], invariant_id)
                )
    for scenario in scenarios:
        for invariant_id in scenario["invariantRefs"]:
            if scenario["id"] not in invariant_by_id[invariant_id]["scenarioRefs"]:
                raise ProfileError(
                    "%s and %s must reference each other"
                    % (scenario["id"], invariant_id)
                )
    for context_label, condition in _profile_conditions(profile, label):
        if context_label.startswith(label + ".selection.activation"):
            continue
        for token in condition["allOf"] + condition["anyOf"] + condition["noneOf"]:
            if token not in capability_set:
                raise ProfileError(context_label + " references unknown capability: " + token)
    return profile


def _profile_conditions(profile: Mapping[str, Any], label: str) -> Iterable[Tuple[str, Mapping[str, Sequence[str]]]]:
    selection = profile.get("selection", {})
    for index, value in enumerate(selection.get("activation", [])):
        yield "%s.selection.activation[%d]" % (label, index), value
    for collection in ("invariants", "checks", "scenarios"):
        for index, value in enumerate(profile.get(collection, [])):
            if isinstance(value, dict) and isinstance(value.get("when"), dict):
                yield "%s.%s[%d].when" % (label, collection, index), value["when"]


class ProfilePackage:
    def __init__(
        self,
        root: Path,
        catalog: Dict[str, Any],
        profiles: Dict[str, Dict[str, Any]],
    ) -> None:
        self.root = root
        self.catalog = catalog
        self.profiles = profiles
        self.catalog_digest = content_digest(catalog)

    def profile_digest(self, profile_id: str) -> str:
        return content_digest(self.profiles[profile_id])

    def ordered_profiles(self, selected: Iterable[str]) -> List[str]:
        requested = set(selected)
        expanded: Set[str] = set()

        def visit(profile_id: str, stack: List[str]) -> None:
            if profile_id in stack:
                raise ProfileError("profile inheritance cycle: " + " -> ".join(stack + [profile_id]))
            if profile_id not in self.profiles:
                raise ProfileError("unknown profile: " + profile_id)
            if profile_id in expanded:
                return
            for parent in self.profiles[profile_id]["extends"]:
                visit(parent, stack + [profile_id])
            expanded.add(profile_id)

        for profile_id in sorted(requested):
            visit(profile_id, [])

        ordered: List[str] = []
        pending = set(expanded)
        while pending:
            ready = sorted(
                profile_id
                for profile_id in pending
                if set(self.profiles[profile_id]["extends"]).issubset(set(ordered))
            )
            if not ready:
                raise ProfileError("profile inheritance graph cannot be ordered")
            ordered.extend(ready)
            pending.difference_update(ready)
        return ordered


def load_package(root: Path) -> ProfilePackage:
    if root.is_symlink() or not root.is_dir():
        raise ProfileError("profile root must be a regular directory")
    catalog = validate_catalog(read_json(root / "catalog.json", "catalog.json"))
    profiles: Dict[str, Dict[str, Any]] = {}
    for entry in catalog["profiles"]:
        profile_path = safe_child(root, entry["path"], "catalog profile path")
        profile = validate_profile(read_json(profile_path, entry["path"]), entry["path"])
        profile_id = profile["id"]
        if profile_id in profiles:
            raise ProfileError("duplicate profile id: " + profile_id)
        profiles[profile_id] = profile
        for key in ("id", "profileVersion", "kind", "invariantPrefix", "extends"):
            if entry[key] != profile[key]:
                raise ProfileError("catalog/profile mismatch for %s.%s" % (profile_id, key))
        actual_digest = content_digest(profile)
        if entry["digest"] != actual_digest:
            raise ProfileError("catalog digest drift for " + profile_id)

    catalog_ids = [entry["id"] for entry in catalog["profiles"]]
    if sorted(profiles) != catalog_ids:
        raise ProfileError("catalog profiles must be sorted and complete")
    if set(profiles) != set(EXPECTED_PROFILE_SPECS):
        raise ProfileError("catalog must contain the exact seven bundled profile IDs")
    for profile_id, (expected_kind, expected_parents) in EXPECTED_PROFILE_SPECS.items():
        profile = profiles[profile_id]
        if profile["kind"] != expected_kind or tuple(profile["extends"]) != expected_parents:
            raise ProfileError("bundled profile relationship drift: " + profile_id)
    prefix_owners: Dict[str, str] = {}
    invariant_owners: Dict[str, str] = {}
    for profile_id, profile in profiles.items():
        prefix = profile["invariantPrefix"]
        if prefix in prefix_owners:
            raise ProfileError(
                "invariant prefix is shared by %s and %s"
                % (prefix_owners[prefix], profile_id)
            )
        prefix_owners[prefix] = profile_id
        for invariant in profile["invariants"]:
            invariant_id = invariant["id"]
            if invariant_id in invariant_owners:
                raise ProfileError(
                    "invariant id is shared by %s and %s"
                    % (invariant_owners[invariant_id], profile_id)
                )
            invariant_owners[invariant_id] = profile_id
    package = ProfilePackage(root, catalog, profiles)
    package.ordered_profiles(profiles)
    return package


def validate_catalog(value: Any) -> Dict[str, Any]:
    catalog = require_object(
        value,
        "catalog",
        {"schemaVersion", "auditStates", "capabilityStates", "profiles"},
        {"schemaVersion", "auditStates", "capabilityStates", "profiles"},
    )
    validate_schema_version(
        catalog["schemaVersion"], "catalog", CATALOG_SCHEMA_VERSION
    )
    audit_states = string_list(
        catalog["auditStates"],
        "catalog.auditStates",
        allow_empty=False,
        sorted_unique=False,
    )
    if tuple(audit_states) != AUDIT_STATES:
        raise ProfileError("catalog.auditStates must match the v2 audit contract")
    capability_states = string_list(
        catalog["capabilityStates"],
        "catalog.capabilityStates",
        allow_empty=False,
        sorted_unique=False,
    )
    if tuple(capability_states) != CAPABILITY_STATES:
        raise ProfileError("catalog.capabilityStates must match the v2 tri-state contract")
    profiles = catalog["profiles"]
    if not isinstance(profiles, list) or not profiles:
        raise ProfileError("catalog.profiles must be a non-empty array")
    seen: Set[str] = set()
    ids: List[str] = []
    for index, item in enumerate(profiles):
        label = "catalog.profiles[%d]" % index
        fields = {"id", "profileVersion", "kind", "invariantPrefix", "extends", "path", "digest"}
        entry = require_object(item, label, fields, fields)
        profile_id = require_string(entry["id"], label + ".id")
        if not PROFILE_ID_RE.fullmatch(profile_id) or profile_id in seen:
            raise ProfileError(label + ".id is invalid or duplicate")
        seen.add(profile_id)
        ids.append(profile_id)
        if not PROFILE_VERSION_RE.fullmatch(require_string(entry["profileVersion"], label + ".profileVersion")):
            raise ProfileError(label + ".profileVersion is invalid")
        kind = require_string(entry["kind"], label + ".kind")
        if kind not in PROFILE_KINDS:
            raise ProfileError(label + ".kind is unsupported")
        if not PREFIX_RE.fullmatch(require_string(entry["invariantPrefix"], label + ".invariantPrefix")):
            raise ProfileError(label + ".invariantPrefix is invalid")
        string_list(entry["extends"], label + ".extends", pattern=PROFILE_ID_RE)
        relative_path(entry["path"], label + ".path")
        if not DIGEST_RE.fullmatch(require_string(entry["digest"], label + ".digest")):
            raise ProfileError(label + ".digest is invalid")
    if ids != sorted(ids):
        raise ProfileError("catalog.profiles must be sorted by id")
    return catalog


def activation_matches(clause: Mapping[str, Sequence[str]], signals: Set[str]) -> bool:
    all_of = set(clause["allOf"])
    any_of = set(clause["anyOf"])
    none_of = set(clause["noneOf"])
    return all_of.issubset(signals) and (not any_of or bool(any_of & signals)) and not bool(none_of & signals)


def evaluate_condition(
    condition: Mapping[str, Sequence[str]], capabilities: Mapping[str, str]
) -> str:
    def state(token: str) -> str:
        return capabilities.get(token, "unknown")

    all_states = [state(token) for token in condition["allOf"]]
    if "absent" in all_states:
        return "not_applicable"
    unknown = "unknown" in all_states

    any_states = [state(token) for token in condition["anyOf"]]
    if any_states and "present" not in any_states:
        if all(item == "absent" for item in any_states):
            return "not_applicable"
        unknown = True

    none_states = [state(token) for token in condition["noneOf"]]
    if "present" in none_states:
        return "not_applicable"
    if "unknown" in none_states:
        unknown = True
    return "unverified" if unknown else "applicable"


def validate_evidence(value: Any) -> Dict[str, Any]:
    evidence = require_object(value, "selection evidence", {"schemaVersion", "components"}, {"schemaVersion", "components"})
    validate_schema_version(
        evidence["schemaVersion"], "selection evidence", EVIDENCE_SCHEMA_VERSION
    )
    components = evidence["components"]
    if not isinstance(components, list) or not components:
        raise ProfileError("selection evidence.components must be a non-empty array")
    if len(components) > MAX_COMPONENTS:
        raise ProfileError("selection evidence exceeds the component limit")
    scopes: Set[str] = set()
    for index, value in enumerate(components):
        label = "selection evidence.components[%d]" % index
        component = require_object(value, label, {"scope", "signals", "capabilities"}, {"scope", "signals", "capabilities"})
        scope = relative_path(component["scope"], label + ".scope", allow_dot=True)
        if scope in scopes:
            raise ProfileError("selection evidence has duplicate scope: " + scope)
        scopes.add(scope)
        signals = string_list(
            component["signals"], label + ".signals", pattern=TOKEN_RE
        )
        if len(signals) > MAX_SIGNALS_PER_COMPONENT:
            raise ProfileError(label + ".signals exceeds the limit")
        capabilities = component["capabilities"]
        if not isinstance(capabilities, dict):
            raise ProfileError(label + ".capabilities must be an object")
        if len(capabilities) > MAX_CAPABILITIES_PER_COMPONENT:
            raise ProfileError(label + ".capabilities exceeds the limit")
        for key, state in capabilities.items():
            if not TOKEN_RE.fullmatch(require_string(key, label + ".capability key")):
                raise ProfileError(label + " has an invalid capability key")
            if state not in CAPABILITY_STATES:
                raise ProfileError(label + " has an invalid capability state for " + key)
        if list(capabilities) != sorted(capabilities):
            raise ProfileError(label + ".capabilities keys must be sorted")
    return evidence


def finalize_artifact(value: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(value)
    result["contentDigest"] = content_digest(value)
    return result


def directly_matched_profiles(
    package: ProfilePackage, signals: Iterable[str]
) -> Set[str]:
    signal_set = set(signals)
    return {
        profile_id
        for profile_id, profile in package.profiles.items()
        if any(
            activation_matches(clause, signal_set)
            for clause in profile["selection"]["activation"]
        )
    }


def profile_refs_for_signals(
    package: ProfilePackage, signals: Iterable[str]
) -> List[str]:
    return package.ordered_profiles(directly_matched_profiles(package, signals))


def aggregate_profile_bindings(
    package: ProfilePackage, components: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    direct_scopes: Dict[str, Set[str]] = {
        profile_id: set() for profile_id in package.profiles
    }
    effective_scopes: Dict[str, Set[str]] = {
        profile_id: set() for profile_id in package.profiles
    }
    selected: Set[str] = set()
    for component in components:
        scope = component["scope"]
        matched = directly_matched_profiles(package, component["signals"])
        for profile_id in matched:
            direct_scopes[profile_id].add(scope)
        for profile_id in package.ordered_profiles(matched):
            effective_scopes[profile_id].add(scope)
        selected.update(matched)

    bindings: List[Dict[str, Any]] = []
    for profile_id in package.ordered_profiles(selected):
        profile = package.profiles[profile_id]
        scopes = sorted(effective_scopes[profile_id])
        if not scopes:
            raise ProfileError("selected profile has no component scope: " + profile_id)
        if profile["kind"] == "overlay" and not direct_scopes[profile_id]:
            raise ProfileError("overlay selection has no matched component scope: " + profile_id)
        bindings.append(
            {
                "id": profile_id,
                "profileVersion": profile["profileVersion"],
                "profileDigest": package.profile_digest(profile_id),
                "selection": "matched" if direct_scopes[profile_id] else "extended",
                "selectionScope": profile["selection"]["scope"],
                "scopes": scopes,
            }
        )
    return bindings


def select_profiles(package: ProfilePackage, evidence: Mapping[str, Any]) -> Dict[str, Any]:
    validate_evidence(evidence)
    components: List[Dict[str, Any]] = []
    for component in evidence["components"]:
        components.append(
            {
                "scope": component["scope"],
                "signals": list(component["signals"]),
                "capabilities": dict(component["capabilities"]),
                "profileRefs": profile_refs_for_signals(
                    package, component["signals"]
                ),
            }
        )
    components.sort(key=lambda item: item["scope"])
    artifact = {
        "schemaVersion": SELECTION_SCHEMA_VERSION,
        "compilerVersion": COMPILER_VERSION,
        "catalogDigest": package.catalog_digest,
        "components": components,
        "profiles": aggregate_profile_bindings(package, components),
    }
    return finalize_artifact(artifact)


def validate_selection(package: ProfilePackage, value: Any) -> Dict[str, Any]:
    selection = require_object(
        value,
        "selection",
        {"schemaVersion", "compilerVersion", "catalogDigest", "components", "profiles", "contentDigest"},
        {"schemaVersion", "compilerVersion", "catalogDigest", "components", "profiles", "contentDigest"},
    )
    validate_schema_version(
        selection["schemaVersion"], "selection", SELECTION_SCHEMA_VERSION
    )
    compiler_version = require_string(selection["compilerVersion"], "selection.compilerVersion")
    if compiler_version != COMPILER_VERSION:
        raise ProfileError("selection compilerVersion is unsupported")
    catalog_digest = require_string(selection["catalogDigest"], "selection.catalogDigest")
    if not DIGEST_RE.fullmatch(catalog_digest) or catalog_digest != package.catalog_digest:
        raise ProfileError("selection catalog digest does not match the bundled catalog")
    unsigned = dict(selection)
    supplied_digest = unsigned.pop("contentDigest")
    if not DIGEST_RE.fullmatch(require_string(supplied_digest, "selection.contentDigest")) or supplied_digest != content_digest(unsigned):
        raise ProfileError("selection content digest is invalid")
    components = selection["components"]
    if not isinstance(components, list) or not components:
        raise ProfileError("selection.components must be a non-empty array")
    if len(components) > MAX_COMPONENTS:
        raise ProfileError("selection exceeds the component limit")
    scopes: List[str] = []
    for index, value in enumerate(components):
        label = "selection.components[%d]" % index
        component = require_object(value, label, {"scope", "signals", "capabilities", "profileRefs"}, {"scope", "signals", "capabilities", "profileRefs"})
        scopes.append(relative_path(component["scope"], label + ".scope", allow_dot=True))
        signals = string_list(
            component["signals"], label + ".signals", pattern=TOKEN_RE
        )
        if len(signals) > MAX_SIGNALS_PER_COMPONENT:
            raise ProfileError(label + ".signals exceeds the limit")
        capabilities = component["capabilities"]
        if not isinstance(capabilities, dict) or list(capabilities) != sorted(capabilities):
            raise ProfileError(label + ".capabilities must be an object with sorted keys")
        if len(capabilities) > MAX_CAPABILITIES_PER_COMPONENT:
            raise ProfileError(label + ".capabilities exceeds the limit")
        for key, state in capabilities.items():
            if not TOKEN_RE.fullmatch(key) or state not in CAPABILITY_STATES:
                raise ProfileError(label + ".capabilities contains an invalid entry")
        profile_refs = string_list(
            component["profileRefs"],
            label + ".profileRefs",
            pattern=PROFILE_ID_RE,
            sorted_unique=False,
        )
        expected_refs = profile_refs_for_signals(package, component["signals"])
        if profile_refs != expected_refs:
            raise ProfileError(label + ".profileRefs do not match the deterministic selector")
    if scopes != sorted(set(scopes)):
        raise ProfileError("selection components must be unique and sorted by scope")
    bindings = selection["profiles"]
    if not isinstance(bindings, list):
        raise ProfileError("selection.profiles must be an array")
    binding_fields = {
        "id",
        "profileVersion",
        "profileDigest",
        "selection",
        "selectionScope",
        "scopes",
    }
    for index, binding_value in enumerate(bindings):
        label = "selection.profiles[%d]" % index
        binding = require_object(binding_value, label, binding_fields, binding_fields)
        profile_id = require_string(binding["id"], label + ".id")
        if profile_id not in package.profiles:
            raise ProfileError(label + " names an unknown profile")
        profile = package.profiles[profile_id]
        if (
            binding["profileVersion"] != profile["profileVersion"]
            or binding["profileDigest"] != package.profile_digest(profile_id)
        ):
            raise ProfileError(label + " version or digest drift")
        binding_selection = require_string(
            binding["selection"], label + ".selection"
        )
        if binding_selection not in {"matched", "extended"}:
            raise ProfileError(label + ".selection is invalid")
        selection_scope = require_string(
            binding["selectionScope"], label + ".selectionScope"
        )
        if selection_scope != profile["selection"]["scope"]:
            raise ProfileError(label + ".selectionScope differs from the profile")
        binding_scopes = string_list(
            binding["scopes"], label + ".scopes", allow_empty=False
        )
        if len(binding_scopes) > MAX_COMPONENTS:
            raise ProfileError(label + ".scopes exceeds the component limit")
        for scope in binding_scopes:
            relative_path(scope, label + ".scopes item", allow_dot=True)
    expected_bindings = aggregate_profile_bindings(package, components)
    if bindings != expected_bindings:
        raise ProfileError("selection.profiles do not match deterministic scoped bindings")
    return selection


def compile_selection(package: ProfilePackage, selection: Mapping[str, Any]) -> Dict[str, Any]:
    validate_selection(package, selection)
    components_by_scope = {
        component["scope"]: component for component in selection["components"]
    }
    invariants: List[Dict[str, Any]] = []
    checks: List[Dict[str, Any]] = []
    scenarios: List[Dict[str, Any]] = []
    for binding in selection["profiles"]:
        profile_id = binding["id"]
        profile = package.profiles[profile_id]
        rule_scopes = list(binding["scopes"])

        def applicability_by_scope(
            rule: Mapping[str, Any], scopes: Tuple[str, ...] = tuple(rule_scopes)
        ) -> List[Dict[str, str]]:
            return [
                {
                    "scope": scope,
                    "state": evaluate_condition(
                        rule["when"], components_by_scope[scope]["capabilities"]
                    ),
                }
                for scope in scopes
            ]

        for invariant in profile["invariants"]:
            invariants.append(
                {
                    **invariant,
                    "profileId": profile_id,
                    "profileVersion": profile["profileVersion"],
                    "profileDigest": binding["profileDigest"],
                    "scopes": rule_scopes,
                    "applicabilityByScope": applicability_by_scope(invariant),
                }
            )
        for check in profile["checks"]:
            checks.append(
                {
                    **check,
                    "profileId": profile_id,
                    "scopes": rule_scopes,
                    "applicabilityByScope": applicability_by_scope(check),
                }
            )
        for scenario in profile["scenarios"]:
            scenarios.append(
                {
                    **scenario,
                    "profileId": profile_id,
                    "scopes": rule_scopes,
                    "applicabilityByScope": applicability_by_scope(scenario),
                }
            )

    compiled_components: List[Dict[str, Any]] = []
    for component in selection["components"]:
        profile_refs = component["profileRefs"]
        compiled_components.append(
            {
                "scope": component["scope"],
                "capabilities": dict(component["capabilities"]),
                "profileRefs": list(profile_refs),
                "invariantRefs": sorted(
                    invariant["id"]
                    for profile_id in profile_refs
                    for invariant in package.profiles[profile_id]["invariants"]
                ),
                "checkRefs": sorted(
                    check["id"]
                    for profile_id in profile_refs
                    for check in package.profiles[profile_id]["checks"]
                ),
                "scenarioRefs": sorted(
                    scenario["id"]
                    for profile_id in profile_refs
                    for scenario in package.profiles[profile_id]["scenarios"]
                ),
            }
        )
    artifact = {
        "schemaVersion": COMPILED_SCHEMA_VERSION,
        "compilerVersion": COMPILER_VERSION,
        "catalogDigest": package.catalog_digest,
        "auditStates": list(AUDIT_STATES),
        "capabilityStates": list(CAPABILITY_STATES),
        "components": compiled_components,
        "profiles": [dict(binding) for binding in selection["profiles"]],
        "invariants": sorted(invariants, key=lambda item: item["id"]),
        "checks": sorted(checks, key=lambda item: item["id"]),
        "scenarios": sorted(scenarios, key=lambda item: item["id"]),
    }
    return finalize_artifact(artifact)


def default_profiles_root() -> Path:
    return Path(__file__).resolve().parent.parent / "references" / "architecture-profiles"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and compile bundled architecture profiles.")
    parser.add_argument(
        "--profiles-root",
        default=str(default_profiles_root()),
        help="Architecture profile package root; defaults to the bundled references.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="Validate catalog and all seven profiles.")

    select_parser = subparsers.add_parser("select", help="Select profiles from normalized repository evidence.")
    select_parser.add_argument("--evidence", required=True, help="Tri-state selection evidence JSON.")
    select_parser.add_argument("--output", help="Output JSON path; stdout when omitted.")

    compile_parser = subparsers.add_parser("compile", help="Compile a selected, scoped profile set.")
    compile_parser.add_argument("--selection", required=True, help="Selection JSON produced by select.")
    compile_parser.add_argument("--output", help="Output JSON path; stdout when omitted.")

    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        package = load_package(Path(args.profiles_root))
        if args.command == "validate":
            print("architecture profiles valid: 7")
            return 0
        if args.command == "select":
            evidence = validate_evidence(read_json(Path(args.evidence), "selection evidence"))
            write_json(Path(args.output) if args.output else None, select_profiles(package, evidence))
            return 0
        if args.command == "compile":
            selection = validate_selection(package, read_json(Path(args.selection), "selection"))
            write_json(Path(args.output) if args.output else None, compile_selection(package, selection))
            return 0
        raise ProfileError("unknown command")
    except ProfileError as error:
        print("error: " + str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print("error: invalid invocation or resource: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
