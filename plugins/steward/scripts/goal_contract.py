#!/usr/bin/env python3
"""Validate and export the shared seven-line consensus GOAL contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SCHEMA_ID = "steward.goal-contract"
SCHEMA_VERSION = 1
MAX_OBJECTIVE_CHARACTERS = 4_000
MAX_INPUT_BYTES = MAX_OBJECTIVE_CHARACTERS * 4 + 1

FIELD_SPECS = (
    ("result", "结果"),
    ("evidenceAndContext", "证据与上下文"),
    ("scope", "范围"),
    ("constraintsAndAuthorization", "约束与授权"),
    ("completionCriteria", "完成标准"),
    ("legitimateBlockers", "正当阻塞项"),
    ("finalDelivery", "最终交付"),
)

REQUIRED_SUBSTANTIVE_FIELD_KEYS = frozenset({"result", "scope", "finalDelivery"})

KNOWN_PLACEHOLDERS = (
    "[内容]",
    "[用户可见的最终结果]",
    "[相关文件、规范、错误、数据和必需来源]",
    "[必须完成的工作、需要保留的行为和明确排除项]",
    "[架构、兼容性、安全、隐私、性能、项目约定、允许的本地操作和需要确认的操作]",
    "[可执行的测试、构建、检查、测量或评审标准]",
    "[(C1) 第一项可执行完成标准；(C2) 第二项可执行完成标准；按需继续连续编号]",
    "[缺少哪些证据、访问权、授权或外部状态时可以停止]",
    "[需要报告的变更、验证证据、假设、风险和剩余缺口]",
)

PLACEHOLDER_ONLY_VALUES = {
    "fixme",
    "placeholder",
    "tbc",
    "tbd",
    "todo",
    "待定",
    "待确认",
    "待补充",
}

_FORBIDDEN_LINE_SEPARATORS = (
    "\v",
    "\f",
    "\r",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
)
_BIDI_CONTROL_CODEPOINTS = frozenset(
    {
        0x061C,  # ARABIC LETTER MARK
        0x200E,  # LEFT-TO-RIGHT MARK
        0x200F,  # RIGHT-TO-LEFT MARK
        *range(0x202A, 0x202F),  # embeddings, overrides, and pop formatting
        *range(0x2066, 0x206A),  # directional isolates and pop isolate
    }
)
_CRITERION_PART_RE = re.compile(r"\(C([1-9][0-9]*)\) (.+)", re.DOTALL)
_CRITERION_SPLIT_RE = re.compile(r"；(?=\(C[0-9]+\) )")
_EMBEDDED_CRITERION_RE = re.compile(r"\([Cc][0-9]+\)")
_CRITERION_LITERAL_DELIMITERS = (
    ("`", "`"),
    ('"', '"'),
    ("'", "'"),
    ("“", "”"),
    ("‘", "’"),
    ("「", "」"),
    ("『", "』"),
)
_PLACEHOLDER_SENTINEL = (
    r"(?:fixme|placeholder|tbc|tbd|todo|待定|待确认|待补充)"
)
_ANNOTATED_PLACEHOLDER_RE = re.compile(
    r"^" + _PLACEHOLDER_SENTINEL + r"\s*[:：]\s*.*",
    re.IGNORECASE,
)
_WRAPPED_PLACEHOLDER_RE = re.compile(
    r"(?:\[|<|\{|【|（)\s*"
    + _PLACEHOLDER_SENTINEL
    + r"(?:\s*[:：]\s*[^\]}>】）]*)?\s*(?:\]|>|\}|】|）)",
    re.IGNORECASE,
)


class GoalContractError(ValueError):
    """A stable, user-actionable GOAL contract validation error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.code + ": " + self.message


@dataclass(frozen=True)
class GoalField:
    key: str
    label: str
    value: str


@dataclass(frozen=True)
class CompletionCriterion:
    id: str
    text: str


@dataclass(frozen=True)
class GoalContract:
    objective: str
    fields: tuple[GoalField, ...]
    completion_criteria: tuple[CompletionCriterion, ...]


def _decode_input(value: str | bytes) -> str:
    if isinstance(value, str):
        if len(value) > MAX_OBJECTIVE_CHARACTERS + 1:
            raise GoalContractError(
                "GOAL_LENGTH", "GOAL 输入超过 4,000 字符合同的读取上限"
            )
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise GoalContractError(
                "GOAL_ENCODING", "GOAL 必须是有效 UTF-8"
            ) from exc
        return value
    if not isinstance(value, bytes):
        raise TypeError("GOAL input must be str or bytes")
    if len(value) > MAX_INPUT_BYTES:
        raise GoalContractError(
            "GOAL_LENGTH", "GOAL 输入超过 4,000 字符合同的读取上限"
        )
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GoalContractError("GOAL_ENCODING", "GOAL 必须是有效 UTF-8") from exc


def _canonical_objective(value: str | bytes) -> str:
    text = _decode_input(value)
    if text.startswith("\ufeff"):
        raise GoalContractError("GOAL_BOM", "GOAL 不得包含 UTF-8 BOM")
    if "\x00" in text:
        raise GoalContractError("GOAL_NUL", "GOAL 不得包含 NUL 字符")
    if any(separator in text for separator in _FORBIDDEN_LINE_SEPARATORS):
        raise GoalContractError("GOAL_NEWLINE", "GOAL 只能使用 LF 换行")
    if any(_is_forbidden_control(character) for character in text):
        raise GoalContractError(
            "GOAL_CONTROL",
            "GOAL 不得包含 C0/C1 控制字符或 Unicode 双向文本控制符",
        )

    # A single final LF is transport framing, not part of the canonical objective.
    objective = text[:-1] if text.endswith("\n") else text
    if len(objective) > MAX_OBJECTIVE_CHARACTERS:
        raise GoalContractError(
            "GOAL_LENGTH",
            "GOAL 规范化后不得超过 4,000 个 Unicode code point",
        )
    return objective


def _is_forbidden_control(character: str) -> bool:
    codepoint = ord(character)
    return (
        (codepoint < 0x20 and character != "\n")
        or 0x7F <= codepoint <= 0x9F
        or codepoint in _BIDI_CONTROL_CODEPOINTS
    )


def _parse_completion_criteria(value: str) -> tuple[CompletionCriterion, ...]:
    if value == "无":
        raise GoalContractError("GOAL_CRITERIA", "完成标准至少需要 (C1)")

    parts = _CRITERION_SPLIT_RE.split(value)
    criteria: list[CompletionCriterion] = []
    for expected_number, part in enumerate(parts, start=1):
        match = _CRITERION_PART_RE.fullmatch(part)
        if match is None:
            raise GoalContractError(
                "GOAL_CRITERIA",
                "完成标准必须使用 `(C1) 内容；(C2) 内容` 格式",
            )
        number = int(match.group(1))
        criterion_text = match.group(2)
        if number != expected_number:
            raise GoalContractError(
                "GOAL_CRITERIA_IDS",
                "完成标准 ID 必须从 C1 开始且唯一、连续、按序排列",
            )
        if criterion_text != criterion_text.strip() or not criterion_text:
            raise GoalContractError(
                "GOAL_CRITERIA_TEXT", "完成标准内容不得为空或包含首尾空白"
            )
        if criterion_text == "无" or _is_placeholder_value(criterion_text):
            raise GoalContractError(
                "GOAL_PLACEHOLDER", "完成标准不得使用“无”或待填充标记"
            )
        for embedded in _EMBEDDED_CRITERION_RE.finditer(criterion_text):
            if not _is_literal_criterion_reference(criterion_text, embedded):
                raise GoalContractError(
                    "GOAL_CRITERIA_IDS",
                    "疑似完成标准标记缺少 `；` 分隔；字面 C* 引用须置于引号、反引号或连续正文中",
                )
        criteria.append(
            CompletionCriterion(id="C" + str(number), text=criterion_text)
        )
    return tuple(criteria)


def _is_literal_criterion_reference(value: str, match: re.Match[str]) -> bool:
    start, end = match.span()
    if start > 0 and end < len(value):
        if value[start - 1].isalnum() and value[end].isalnum():
            return True

    for opener, closer in _CRITERION_LITERAL_DELIMITERS:
        opening = value.rfind(opener, 0, start)
        if opening < 0:
            continue
        if opener == closer:
            if value[:start].count(opener) % 2 == 1 and value.find(closer, end) >= 0:
                return True
            continue
        last_closing = value.rfind(closer, 0, start)
        if opening > last_closing and value.find(closer, end) >= 0:
            return True
    return False


def _is_placeholder_value(value: str) -> bool:
    return (
        value.casefold() in PLACEHOLDER_ONLY_VALUES
        or _ANNOTATED_PLACEHOLDER_RE.fullmatch(value) is not None
        or _WRAPPED_PLACEHOLDER_RE.fullmatch(value) is not None
    )


def validate_goal_text(value: str | bytes) -> GoalContract:
    """Parse a raw seven-line GOAL and return its canonical contract."""

    objective = _canonical_objective(value)
    lines = objective.split("\n")
    if len(lines) != len(FIELD_SPECS):
        raise GoalContractError(
            "GOAL_LINES", "GOAL 必须恰好包含七个字段和六个 LF 换行"
        )

    fields: list[GoalField] = []
    for line_number, ((key, label), line) in enumerate(
        zip(FIELD_SPECS, lines), start=1
    ):
        prefix = label + "："
        if not line.startswith(prefix):
            raise GoalContractError(
                "GOAL_FIELD",
                f"第 {line_number} 行必须以 `{prefix}` 开头并保持字段顺序",
            )
        field_value = line[len(prefix) :]
        if not field_value:
            raise GoalContractError(
                "GOAL_FIELD_VALUE", f"字段 `{label}` 不得为空；无适用内容时写“无”"
            )
        if field_value != field_value.strip():
            raise GoalContractError(
                "GOAL_FIELD_WHITESPACE", f"字段 `{label}` 不得包含首尾空白"
            )
        if field_value in KNOWN_PLACEHOLDERS or _is_placeholder_value(field_value):
            raise GoalContractError(
                "GOAL_PLACEHOLDER", f"字段 `{label}` 不得使用待填充标记"
            )
        if key in REQUIRED_SUBSTANTIVE_FIELD_KEYS and field_value == "无":
            raise GoalContractError(
                "GOAL_FIELD_VALUE", f"字段 `{label}` 必须包含实质内容，不得写“无”"
            )
        fields.append(GoalField(key=key, label=label, value=field_value))

    criteria = _parse_completion_criteria(fields[4].value)
    return GoalContract(
        objective=objective,
        fields=tuple(fields),
        completion_criteria=criteria,
    )


def load_goal_contract(path: str | Path) -> GoalContract:
    """Load a raw seven-line GOAL file and validate it without modifying it."""

    return validate_goal_text(_read_regular_goal_file(Path(path)))


def goal_contract_view(contract: GoalContract) -> dict[str, Any]:
    """Return the deterministic, versioned JSON-compatible contract view."""

    if not isinstance(contract, GoalContract):
        raise TypeError("contract must be a GoalContract")
    if validate_goal_text(contract.objective) != contract:
        raise GoalContractError(
            "GOAL_VIEW_MISMATCH", "GoalContract 与 objective 的规范解析结果不一致"
        )
    return {
        "schemaId": SCHEMA_ID,
        "schemaVersion": SCHEMA_VERSION,
        "objective": contract.objective,
        "fields": [
            {"key": item.key, "label": item.label, "value": item.value}
            for item in contract.fields
        ],
        "completionCriteria": [
            {"id": item.id, "text": item.text}
            for item in contract.completion_criteria
        ],
    }


def validate_goal_contract_view(value: Mapping[str, Any]) -> GoalContract:
    """Validate a parsed v1 view and prove it equals a fresh objective parse."""

    if not isinstance(value, Mapping):
        raise GoalContractError("GOAL_VIEW", "GOAL contract view 必须是对象")
    expected_keys = {
        "schemaId",
        "schemaVersion",
        "objective",
        "fields",
        "completionCriteria",
    }
    if set(value) != expected_keys:
        raise GoalContractError(
            "GOAL_VIEW", "GOAL contract view 字段不完整或包含未知字段"
        )
    if value.get("schemaId") != SCHEMA_ID:
        raise GoalContractError("GOAL_VIEW_SCHEMA", "不支持的 GOAL schemaId")
    if type(value.get("schemaVersion")) is not int or value.get(
        "schemaVersion"
    ) != SCHEMA_VERSION:
        raise GoalContractError("GOAL_VIEW_SCHEMA", "GOAL schemaVersion 必须为 1")
    objective = value.get("objective")
    if not isinstance(objective, str):
        raise GoalContractError("GOAL_VIEW", "GOAL objective 必须是字符串")
    parsed = validate_goal_text(objective)
    if dict(value) != goal_contract_view(parsed):
        raise GoalContractError(
            "GOAL_VIEW_MISMATCH",
            "GOAL contract view 与 objective 的规范解析结果不一致",
        )
    return parsed


def canonical_goal_contract_bytes(contract: GoalContract) -> bytes:
    """Serialize a contract view canonically; the digest excludes transport LF."""

    return json.dumps(
        goal_contract_view(contract),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def goal_contract_sha256(contract: GoalContract) -> str:
    """Return the canonical v1 view digest used by traceability.goalContract."""

    return "sha256:" + hashlib.sha256(canonical_goal_contract_bytes(contract)).hexdigest()


def _read_cli_input(path: str) -> bytes:
    if path == "-":
        return _read_bounded(sys.stdin.buffer)
    return _read_regular_goal_file(Path(path))


def _read_regular_goal_file(path: Path) -> bytes:
    """Read one bounded regular file without following a link or opening a FIFO."""

    descriptor: int | None = None
    try:
        initial = path.lstat()
        is_reparse = bool(
            getattr(initial, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
        if stat.S_ISLNK(initial.st_mode) or is_reparse or not stat.S_ISREG(
            initial.st_mode
        ):
            raise GoalContractError(
                "GOAL_IO", "GOAL 路径必须是普通非符号链接文件"
            )

        flags = os.O_RDONLY
        for optional_flag in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
            flags |= getattr(os, optional_flag, 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(initial, opened):
            raise GoalContractError(
                "GOAL_IO", "GOAL 路径在打开期间发生变化或不是普通文件"
            )
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            return _read_bounded(handle)
    except GoalContractError:
        raise
    except OSError as exc:
        raise GoalContractError(
            "GOAL_IO", "无法读取 GOAL 文件 " + str(path) + ": " + str(exc)
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_bounded(handle: Any) -> bytes:
    data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise GoalContractError(
            "GOAL_LENGTH", "GOAL 输入超过 4,000 字符合同的读取上限"
        )
    return data


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="只读校验并导出固定七行 consensus GOAL contract。"
    )
    parser.add_argument("command", choices=("check", "view", "digest"))
    parser.add_argument("path", nargs="?", default="-", help="GOAL 文本路径或 -")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        contract = validate_goal_text(_read_cli_input(args.path))
        digest = goal_contract_sha256(contract)
        if args.command == "view":
            sys.stdout.buffer.write(canonical_goal_contract_bytes(contract) + b"\n")
        elif args.command == "digest":
            print(digest)
        else:
            print("VALID " + digest)
        return 0
    except GoalContractError as exc:
        print("ERROR " + str(exc), file=sys.stderr)
        return 2 if exc.code == "GOAL_IO" else 1
    except OSError as exc:
        print("ERROR GOAL_IO: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
