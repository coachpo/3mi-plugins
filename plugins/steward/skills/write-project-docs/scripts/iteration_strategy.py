#!/usr/bin/env python3
"""Parse, render and validate the derived current-iteration strategy block."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from canonical_paths import DocumentLanguage
from contributing_blocks import parse_mvp_mode
from doc_anchors import LANGUAGE_PROFILES, LanguageProfile
from managed_blocks import (
    BlockSpan,
    ManagedBlockError,
    locate_managed_block,
    opens_markdown_fence,
    visible_atx_headings,
    visible_exact_line_spans,
    visible_section_titles,
)

START_MARKER = "<!-- write-project-docs:derived-iteration-strategy:start -->"
END_MARKER = "<!-- write-project-docs:derived-iteration-strategy:end -->"
SHARED_START_MARKER = "<!-- write-project-docs:shared-contributing:start -->"
SHARED_END_MARKER = "<!-- write-project-docs:shared-contributing:end -->"
METADATA_PREFIX = "<!-- write-project-docs:derived-iteration-strategy:metadata "
METADATA_SUFFIX = " -->"
MAX_HANDOFF_BYTES = 64 * 1024
MAX_ITEM_LENGTH = 2_000
MAX_LIST_ITEMS = 32
STATUS_NORMALIZATION = "without-visible-exact-mvp-control-line-terminal-lf-v2"
BIDI_CONTROL_CHARACTERS = frozenset(
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)
HANDOFF_FIELDS = frozenset(
    {
        "schemaVersion",
        "language",
        "strategy",
        "doNow",
        "defer",
        "guardrails",
        "rederiveWhen",
    }
)


@dataclass(frozen=True)
class IterationStrategy:
    """Validated semantic handoff; the updater never derives these statements."""

    language: DocumentLanguage
    strategy: str
    do_now: tuple[str, ...]
    defer: tuple[str, ...]
    guardrails: tuple[str, ...]
    rederive_when: tuple[str, ...]


COPY = {
    DocumentLanguage.CHINESE: {
        "sources": "派生依据（事实权威仍在原文档）",
        "boundary": (
            "本区块只约束当前迭代，不改变 MVP 快速验证开关，不扩大用户授权，"
            "不授权外部写入或破坏性操作、删除或重置现有数据、虚构验证结果，"
            "也不覆盖更高优先级的用户要求或明确禁止事项。"
        ),
    },
    DocumentLanguage.ENGLISH: {
        "sources": "Derived from (the source documents remain authoritative)",
        "boundary": (
            "This block scopes only the current iteration. It does not change the "
            "MVP fast-validation switch, expand user authorization, authorize "
            "external writes or destructive operations, delete or reset existing "
            "data, fabricate validation results, or override higher-priority user "
            "requirements or explicit prohibitions."
        ),
    },
}


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"JSON 字段重复：{key}")
        value[key] = item
    return value


def _reject_mvp_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if "mvp" in key.lower():
                raise ValueError(f"阶段策略 handoff 不得包含 MVP 字段：{key}")
            _reject_mvp_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_mvp_fields(item)


def _one_line(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} 必须是首尾无空白的非空字符串")
    if len(value) > MAX_ITEM_LENGTH:
        raise ValueError(f"{field} 过长")
    if value.splitlines() != [value]:
        raise ValueError(f"{field} 必须是安全的单行 Markdown 文本")
    if any(
        character in BIDI_CONTROL_CHARACTERS
        or (character != "\t" and unicodedata.category(character) in {"Cc", "Cs"})
        for character in value
    ):
        raise ValueError(f"{field} 必须是安全的单行 Markdown 文本")
    if visible_atx_headings(value + "\n"):
        raise ValueError(f"{field} 不得注入 Markdown 标题")
    if opens_markdown_fence(value):
        raise ValueError(f"{field} 不得开启 Markdown 围栏代码块")
    return value


def _string_list(
    value: Any, field: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
        raise ValueError(f"{field} 必须是最多 {MAX_LIST_ITEMS} 项的数组")
    if not value and not allow_empty:
        raise ValueError(f"{field} 不得为空")
    items = tuple(
        _one_line(item, f"{field}[{index}]") for index, item in enumerate(value)
    )
    if len(items) != len(set(items)):
        raise ValueError(f"{field} 不得包含重复项")
    return items


def parse_iteration_strategy_handoff(
    data: bytes, expected_language: DocumentLanguage
) -> IterationStrategy:
    """Parse one bounded, exact-schema semantic handoff from stdin bytes."""

    if not data or len(data) > MAX_HANDOFF_BYTES:
        raise ValueError("阶段策略 handoff 必须是非空且不超过 64 KiB 的 JSON")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("阶段策略 handoff 不是有效 UTF-8") from error
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"阶段策略 handoff 不是有效的唯一键 JSON：{error}") from error
    if not isinstance(value, dict):
        raise ValueError("阶段策略 handoff 顶层必须是 JSON object")
    _reject_mvp_fields(value)
    if set(value) != HANDOFF_FIELDS:
        missing = sorted(HANDOFF_FIELDS - set(value))
        unknown = sorted(set(value) - HANDOFF_FIELDS)
        details = []
        if missing:
            details.append("缺少 " + "、".join(missing))
        if unknown:
            details.append("未知 " + "、".join(unknown))
        raise ValueError("阶段策略 handoff 字段不匹配：" + "；".join(details))
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ValueError("schemaVersion 必须精确为整数 1")
    if value["language"] != expected_language.value:
        raise ValueError(
            "阶段策略 handoff 的 language 必须与项目文档语言一致："
            + expected_language.value
        )
    return IterationStrategy(
        language=expected_language,
        strategy=_one_line(value["strategy"], "strategy"),
        do_now=_string_list(value["doNow"], "doNow"),
        defer=_string_list(value["defer"], "defer", allow_empty=True),
        guardrails=_string_list(value["guardrails"], "guardrails"),
        rederive_when=_string_list(value["rederiveWhen"], "rederiveWhen"),
    )


def strategy_source_paths(selected: dict[str, str]) -> tuple[str, ...]:
    return (
        "STATUS.md",
        selected["product"],
        selected["architecture"],
        selected["development_rules"],
    )


def normalize_status_for_strategy(data: bytes, language: DocumentLanguage) -> bytes:
    """Remove only the visible exact MVP control line from a STATUS digest."""

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("STATUS.md 不是有效 UTF-8") from error
    parse_mvp_mode(text, language)
    profile = next(
        item for item in LANGUAGE_PROFILES.values() if item.language is language
    )
    candidates = frozenset(
        {profile.mvp_status_enabled_line, profile.mvp_status_disabled_line}
    )
    spans = visible_exact_line_spans(text, candidates)
    cursor = 0
    pieces: list[str] = []
    for span in spans:
        pieces.append(text[cursor : span.start])
        cursor = span.end
    pieces.append(text[cursor:])
    normalized = "".join(pieces).rstrip("\r\n") + "\n"
    return normalized.encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def strategy_source_bindings(
    root: Path,
    selected: dict[str, str],
    language: DocumentLanguage,
) -> list[dict[str, str]]:
    bindings: list[dict[str, str]] = []
    for relative in strategy_source_paths(selected):
        path = root / relative
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"阶段策略来源必须位于项目内：{relative}")
        current = root
        has_symlink_component = False
        for part in relative_path.parts:
            current = current / part
            if current.is_symlink():
                has_symlink_component = True
                break
        if has_symlink_component or not path.is_file():
            raise ValueError(f"阶段策略来源必须是普通非符号链接文件：{relative}")
        data = path.read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"阶段策略来源不是有效 UTF-8：{relative}") from error
        binding = {"path": relative}
        if relative == "STATUS.md":
            data = normalize_status_for_strategy(data, language)
            binding["normalization"] = STATUS_NORMALIZATION
        binding["sha256"] = _sha256(data)
        bindings.append(binding)
    return bindings


def _source_links(selected: dict[str, str], language: DocumentLanguage) -> str:
    separator = "、" if language is DocumentLanguage.CHINESE else ", "
    return separator.join(
        f"[`{relative}`]({relative})" for relative in strategy_source_paths(selected)
    )


def _source_attribution(selected: dict[str, str], language: DocumentLanguage) -> str:
    if language is DocumentLanguage.CHINESE:
        return f"{COPY[language]['sources']}：{_source_links(selected, language)}。"
    return f"{COPY[language]['sources']}: {_source_links(selected, language)}."


def _escape_markdown_text(value: str) -> str:
    """Escape raw HTML delimiters while preserving ordinary comparison text."""

    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rendered_one_line(value: str, field: str) -> str:
    if "<" in value or ">" in value:
        raise ValueError(f"{field} 含有未转义的 HTML 分隔符")
    decoded: list[str] = []
    cursor = 0
    while cursor < len(value):
        if value[cursor] != "&":
            decoded.append(value[cursor])
            cursor += 1
            continue
        for entity, character in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
            if value.startswith(entity, cursor):
                decoded.append(character)
                cursor += len(entity)
                break
        else:
            raise ValueError(f"{field} 含有未转义的 HTML 分隔符")
    raw_value = _one_line("".join(decoded), field)
    if _escape_markdown_text(raw_value) != value:
        raise ValueError(f"{field} 不是规范 Markdown 文本")
    return value


def render_iteration_strategy_body(
    handoff: IterationStrategy,
    profile: LanguageProfile,
    selected: dict[str, str],
) -> str:
    if handoff.language is not profile.language:
        raise ValueError("阶段策略 handoff 与语言 profile 不一致")
    sections = profile.iteration_strategy_section_titles
    lines = [
        f"## {profile.iteration_strategy_title}",
        "",
        _escape_markdown_text(handoff.strategy),
        "",
        _source_attribution(selected, profile.language),
        "",
        f"> {COPY[profile.language]['boundary']}",
        "",
        f"### {sections[0]}",
        "",
        *(f"- {_escape_markdown_text(item)}" for item in handoff.do_now),
    ]
    if handoff.defer:
        lines.extend(("", f"### {sections[1]}", ""))
        lines.extend(f"- {_escape_markdown_text(item)}" for item in handoff.defer)
    lines.extend(("", f"### {sections[2]}", ""))
    lines.extend(f"- {_escape_markdown_text(item)}" for item in handoff.guardrails)
    lines.extend(("", f"### {sections[3]}", ""))
    lines.extend(f"- {_escape_markdown_text(item)}" for item in handoff.rederive_when)
    return "\n".join(lines) + "\n"


def render_iteration_strategy_block(
    handoff: IterationStrategy,
    root: Path,
    selected: dict[str, str],
    profile: LanguageProfile,
) -> str:
    body = render_iteration_strategy_body(handoff, profile, selected)
    metadata = {
        "contentSha256": _sha256(body.encode("utf-8")),
        "schemaVersion": 1,
        "sources": strategy_source_bindings(root, selected, profile.language),
    }
    metadata_text = json.dumps(
        metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return (
        START_MARKER
        + "\n"
        + METADATA_PREFIX
        + metadata_text
        + METADATA_SUFFIX
        + "\n"
        + body
        + END_MARKER
        + "\n"
    )


def _parse_metadata(line: str) -> dict[str, Any]:
    if not line.startswith(METADATA_PREFIX) or not line.endswith(METADATA_SUFFIX):
        raise ValueError("当前迭代策略区块缺少规范 metadata 行")
    raw = line[len(METADATA_PREFIX) : -len(METADATA_SUFFIX)]
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"当前迭代策略 metadata 无效：{error}") from error
    if not isinstance(value, dict) or set(value) != {
        "contentSha256",
        "schemaVersion",
        "sources",
    }:
        raise ValueError("当前迭代策略 metadata 字段不匹配")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or not isinstance(value["sources"], list)
    ):
        raise ValueError("当前迭代策略 metadata schema 无效")
    if (
        not isinstance(value["contentSha256"], str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", value["contentSha256"]) is None
    ):
        raise ValueError("当前迭代策略 metadata 内容 digest 无效")
    return value


def _validate_rendered_body(
    body: str,
    profile: LanguageProfile,
    selected: dict[str, str],
) -> None:
    """Validate the exact renderer grammar, including required nonempty lists."""

    if "\r" in body or not body.endswith("\n") or body.endswith("\n\n"):
        raise ValueError("当前迭代策略正文结构无效：换行格式无效")
    lines = body[:-1].split("\n")
    cursor = 0

    def expect(expected: str, label: str) -> None:
        nonlocal cursor
        if cursor >= len(lines) or lines[cursor] != expected:
            raise ValueError(f"当前迭代策略正文结构无效：{label}")
        cursor += 1

    def consume_items(title: str, field: str) -> tuple[str, ...]:
        nonlocal cursor
        expect(f"### {title}", f"缺少“{title}”小节")
        expect("", f"“{title}”标题后缺少空行")
        items: list[str] = []
        while cursor < len(lines) and lines[cursor].startswith("- "):
            item = _rendered_one_line(lines[cursor][2:], f"{field}[{len(items)}]")
            items.append(item)
            cursor += 1
        if not items:
            raise ValueError(f"当前迭代策略正文结构无效：“{title}”不得为空")
        if len(items) > MAX_LIST_ITEMS or len(items) != len(set(items)):
            raise ValueError(f"当前迭代策略正文结构无效：“{title}”列表无效")
        return tuple(items)

    sections = profile.iteration_strategy_section_titles
    expect(f"## {profile.iteration_strategy_title}", "H2 标题无效")
    expect("", "H2 标题后缺少空行")
    if cursor >= len(lines):
        raise ValueError("当前迭代策略正文结构无效：缺少策略摘要")
    _rendered_one_line(lines[cursor], "strategy")
    cursor += 1
    expect("", "策略摘要后缺少空行")
    expect(
        _source_attribution(selected, profile.language),
        "派生来源声明无效",
    )
    expect("", "派生来源声明后缺少空行")
    expect(
        f"> {COPY[profile.language]['boundary']}",
        "固定范围与授权边界声明无效",
    )
    expect("", "固定范围与授权边界声明后缺少空行")
    consume_items(sections[0], "doNow")
    expect("", f"“{sections[0]}”后缺少空行")
    if cursor < len(lines) and lines[cursor] == f"### {sections[1]}":
        consume_items(sections[1], "defer")
        expect("", f"“{sections[1]}”后缺少空行")
    consume_items(sections[2], "guardrails")
    expect("", f"“{sections[2]}”后缺少空行")
    consume_items(sections[3], "rederiveWhen")
    if cursor != len(lines):
        raise ValueError("当前迭代策略正文结构无效：包含额外内容")


def validate_iteration_strategy_block(
    block: str,
    root: Path,
    selected: dict[str, str],
    profile: LanguageProfile,
) -> None:
    if "\r" in block or not block.endswith("\n") or block.endswith("\n\n"):
        raise ValueError("当前迭代策略区块必须使用 LF 且仅有一个尾随换行")
    try:
        span = locate_managed_block(block, START_MARKER, END_MARKER, "当前迭代策略区块")
    except ManagedBlockError as error:
        raise ValueError(str(error)) from error
    if span is None or span.start != 0 or span.end != len(block):
        raise ValueError("当前迭代策略 marker 必须包围整个区块")
    lines = block.splitlines(keepends=True)
    if len(lines) < 5:
        raise ValueError("当前迭代策略区块不完整")
    metadata = _parse_metadata(lines[1].rstrip("\n"))
    body = "".join(lines[2:-1])
    if metadata["contentSha256"] != _sha256(body.encode("utf-8")):
        raise ValueError("当前迭代策略内容已漂移")
    if metadata["sources"] != strategy_source_bindings(
        root, selected, profile.language
    ):
        raise ValueError("当前迭代策略来源已漂移，必须重新推导")

    _validate_rendered_body(body, profile, selected)

    headings = tuple((level, title) for level, title, _ in visible_atx_headings(body))
    sections = profile.iteration_strategy_section_titles
    without_defer = (
        (2, profile.iteration_strategy_title),
        (3, sections[0]),
        (3, sections[2]),
        (3, sections[3]),
    )
    with_defer = without_defer[:2] + ((3, sections[1]),) + without_defer[2:]
    if headings not in {without_defer, with_defer}:
        raise ValueError("当前迭代策略标题缺失、重复或顺序错误")


def _locate_document_blocks(
    text: str, profile: LanguageProfile
) -> tuple[BlockSpan | None, BlockSpan | None]:
    try:
        strategy = locate_managed_block(
            text, START_MARKER, END_MARKER, "CONTRIBUTING.md 的当前迭代策略区块"
        )
        shared = locate_managed_block(
            text, SHARED_START_MARKER, SHARED_END_MARKER, "CONTRIBUTING.md 的共享区块"
        )
    except ManagedBlockError as error:
        raise ValueError(str(error)) from error
    if strategy is not None and shared is not None:
        if strategy.start < shared.end and shared.start < strategy.end:
            raise ValueError("CONTRIBUTING.md 的当前迭代策略与共享区块不得重叠或嵌套")
        if strategy.start > shared.start:
            raise ValueError("CONTRIBUTING.md 的当前迭代策略区块必须位于共享区块之前")
    outside = (
        text if strategy is None else text[: strategy.start] + text[strategy.end :]
    )
    strategy_titles = tuple(
        item.iteration_strategy_title for item in LANGUAGE_PROFILES.values()
    )
    if visible_section_titles(outside, strategy_titles):
        raise ValueError("CONTRIBUTING.md 在托管区块外包含当前迭代策略标题")
    return strategy, shared


def validate_iteration_strategy_document(
    text: str,
    root: Path,
    selected: dict[str, str],
    profile: LanguageProfile,
) -> BlockSpan | None:
    """Validate the optional block and its independent relationship to MVP."""

    strategy, _shared = _locate_document_blocks(text, profile)
    if strategy is None:
        return None
    validate_iteration_strategy_block(
        text[strategy.start : strategy.end], root, selected, profile
    )
    return strategy


def insert_or_replace_iteration_strategy(
    text: str, block: str, profile: LanguageProfile
) -> tuple[str, str]:
    strategy, shared = _locate_document_blocks(text, profile)
    if shared is None:
        raise ValueError(
            "CONTRIBUTING.md 缺少共享区块；请先运行 update_contributing.py"
        )
    if strategy is not None:
        return text[: strategy.start] + block + text[strategy.end :], "replaced"
    prefix = text[: shared.start]
    return prefix + block + "\n" + text[shared.start :], "inserted"


def remove_iteration_strategy(text: str, profile: LanguageProfile) -> tuple[str, str]:
    strategy, shared = _locate_document_blocks(text, profile)
    if strategy is None:
        return text, "absent"
    suffix_start = strategy.end
    if shared is not None and strategy.end <= shared.start:
        between = text[strategy.end : shared.start]
        if between in {"\n", "\r\n"}:
            suffix_start = shared.start
    return text[: strategy.start] + text[suffix_start:], "removed"
