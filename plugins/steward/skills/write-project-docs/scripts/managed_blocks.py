#!/usr/bin/env python3
"""Shared parsers for managed Markdown sections and legacy marker blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeVar

TextData = TypeVar("TextData", str, bytes)
RAW_HTML_TAG_RE = re.compile(
    r"<(script|pre|style|textarea)(?=[\s>/])", re.IGNORECASE
)
BLOCK_HTML_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|"
    "colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|"
    "footer|form|frame|frameset|h1|h2|h3|h4|h5|h6|head|header|hr|html|"
    "iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|"
    "option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|"
    "title|tr|track|ul"
)
BLOCK_HTML_TAG_RE = re.compile(
    rf"</?(?:{BLOCK_HTML_TAGS})(?=[\s>/])", re.IGNORECASE
)
HTML_ATTRIBUTE = (
    r"[ \t]+[A-Za-z_:][A-Za-z0-9_.:-]*"
    r"(?:[ \t]*=[ \t]*(?:[^\"'=<>`\x00-\x20]+|'[^']*'|\"[^\"]*\"))?"
)
COMPLETE_OPEN_TAG_RE = re.compile(
    rf"<[A-Za-z][A-Za-z0-9-]*(?:{HTML_ATTRIBUTE})*[ \t]*/?>[ \t]*$"
)
COMPLETE_CLOSING_TAG_RE = re.compile(
    r"</[A-Za-z][A-Za-z0-9-]*[ \t]*>[ \t]*$"
)
MANAGED_MARKER_RE = re.compile(
    r"<!-- (?P<name>[^<>\s:]+(?::[^<>\s:]+)+):"
    r"(?P<boundary>start|end) -->"
)


class ManagedBlockError(ValueError):
    """Raised when a managed block state is unsafe to edit or validate."""


@dataclass(frozen=True)
class BlockSpan:
    """Span for a managed block, including its final line ending when present."""

    start: int
    end: int


@dataclass(frozen=True)
class _MarkdownLine:
    """One Markdown source line and whether block parsing exposes its text."""

    start: int
    end: int
    text: str
    visible: bool


@dataclass(frozen=True)
class _HtmlBlockState:
    """A conservative CommonMark raw HTML block state."""

    kind: str
    closing: str = ""


def _is_standalone_marker(data: TextData, position: int, marker: TextData) -> bool:
    newline = b"\n" if isinstance(data, bytes) else "\n"
    carriage_return = b"\r" if isinstance(data, bytes) else "\r"
    marker_end = position + len(marker)

    starts_line = position == 0 or data[position - 1 : position] == newline
    if marker_end == len(data):
        ends_line = True
    elif data[marker_end : marker_end + 1] == newline:
        ends_line = True
    else:
        ends_line = (
            data[marker_end : marker_end + 1] == carriage_return
            and data[marker_end + 1 : marker_end + 2] == newline
        )
    return starts_line and ends_line


def _next_fence_state(
    active_fence: tuple[str, int] | None, line: str
) -> tuple[str, int] | None:
    indentation = len(line) - len(line.lstrip(" "))
    if indentation > 3:
        return active_fence
    candidate = line[indentation:]

    if active_fence is not None:
        fence_character, opening_length = active_fence
        run_length = len(candidate) - len(candidate.lstrip(fence_character))
        remainder = candidate[run_length:]
        if run_length >= opening_length and not remainder.strip(" \t"):
            return None
        return active_fence

    if not candidate or candidate[0] not in {"`", "~"}:
        return None
    fence_character = candidate[0]
    run_length = len(candidate) - len(candidate.lstrip(fence_character))
    if run_length < 3:
        return None
    remainder = candidate[run_length:]
    if fence_character == "`" and "`" in remainder:
        return None
    return fence_character, run_length


def opens_markdown_fence(line: str) -> bool:
    """Return whether one standalone line opens a CommonMark fenced block."""

    return _next_fence_state(None, line) is not None


def _starts_html_block(
    line: str, *, allow_type7: bool
) -> _HtmlBlockState | None:
    indentation = len(line) - len(line.lstrip(" "))
    if indentation > 3:
        return None
    candidate = line[indentation:]

    raw_tag = RAW_HTML_TAG_RE.match(candidate)
    if raw_tag is not None:
        tag = raw_tag.group(1).lower()
        return _HtmlBlockState("token", f"</{tag}>")
    if candidate.startswith("<!--"):
        return _HtmlBlockState("token", "-->")
    if candidate.startswith("<?"):
        return _HtmlBlockState("token", "?>")
    if candidate.startswith("<![CDATA["):
        return _HtmlBlockState("token", "]]>")
    if re.match(r"<![A-Z]", candidate):
        return _HtmlBlockState("token", ">")
    if BLOCK_HTML_TAG_RE.match(candidate):
        return _HtmlBlockState("blank")
    if allow_type7 and (
        COMPLETE_OPEN_TAG_RE.fullmatch(candidate)
        or COMPLETE_CLOSING_TAG_RE.fullmatch(candidate)
    ):
        return _HtmlBlockState("blank")
    return None


def _html_block_ends(state: _HtmlBlockState, line: str) -> bool:
    if state.kind == "blank":
        return not line.strip(" \t")
    return state.closing.lower() in line.lower()


def _is_inside_markdown_fence(data: TextData, position: int) -> bool:
    prefix = data[:position]
    if isinstance(prefix, bytes):
        text = prefix.decode("utf-8", errors="replace")
    else:
        text = prefix

    active_fence: tuple[str, int] | None = None
    for line in text.splitlines():
        active_fence = _next_fence_state(active_fence, line)
    return active_fence is not None


def markdown_h1_lines(text: str) -> list[str]:
    """Return visible ATX and conservative Setext H1 representations."""

    headings: list[str] = []
    lines = _markdown_lines(text)
    for index, line in enumerate(lines):
        if not line.visible:
            continue
        indentation = len(line.text) - len(line.text.lstrip(" "))
        candidate = line.text[indentation:].rstrip(" \t")
        if indentation <= 3 and re.match(r"^#(?:[ \t]+|$)", candidate):
            headings.append(candidate)
        if index == 0 or indentation > 3 or not re.fullmatch(
            r"=+[ \t]*", candidate
        ):
            continue
        previous = lines[index - 1]
        if previous.visible and previous.text.strip(" \t"):
            headings.append(previous.text.strip(" \t") + "\n" + candidate)
    return headings


def _atx_heading(line: str) -> tuple[int, str] | None:
    indentation = len(line) - len(line.lstrip(" "))
    if indentation > 3:
        return None
    candidate = line[indentation:].rstrip(" \t")
    match = re.match(r"^(#{1,6})(?:[ \t]+(.*)|[ \t]*)$", candidate)
    if match is None:
        return None

    title = match.group(2) or ""
    title = re.sub(r"[ \t]+#+[ \t]*$", "", title).strip()
    return len(match.group(1)), title


def _markdown_lines(text: str) -> list[_MarkdownLine]:
    lines: list[_MarkdownLine] = []
    active_fence: tuple[str, int] | None = None
    active_html_block: _HtmlBlockState | None = None
    paragraph_open = False
    offset = 0
    for line_with_ending in text.splitlines(keepends=True):
        line = line_with_ending.rstrip("\r\n")
        if active_fence is not None:
            active_fence = _next_fence_state(active_fence, line)
            visible = False
            paragraph_open = False
        elif active_html_block is not None:
            if _html_block_ends(active_html_block, line):
                active_html_block = None
            visible = False
            paragraph_open = False
        else:
            html_block = _starts_html_block(
                line, allow_type7=not paragraph_open
            )
            if html_block is not None:
                if not _html_block_ends(html_block, line):
                    active_html_block = html_block
                visible = False
                paragraph_open = False
            else:
                active_fence = _next_fence_state(None, line)
                visible = active_fence is None
                if not visible or not line.strip(" \t"):
                    paragraph_open = False
                else:
                    indentation = len(line) - len(line.lstrip(" "))
                    candidate = line[indentation:]
                    is_heading_or_underline = (
                        _atx_heading(line) is not None
                        or (
                            indentation <= 3
                            and re.fullmatch(
                                r"(?:=+|-+)[ \t]*", candidate
                            )
                            is not None
                        )
                    )
                    paragraph_open = not is_heading_or_underline
        line_end = offset + len(line_with_ending)
        lines.append(
            _MarkdownLine(
                start=offset,
                end=line_end,
                text=line,
                visible=visible,
            )
        )
        offset = line_end
    return lines


def _asset_boundary_lines(asset: str, label: str) -> tuple[str, str]:
    content_lines = [
        line.rstrip("\r\n")
        for line in asset.splitlines(keepends=True)
        if line.rstrip("\r\n").strip()
    ]
    if not content_lines:
        raise ManagedBlockError(f"{label} 不得为空")
    return content_lines[0], content_lines[-1]


def _visible_h2_title_positions(
    lines: list[_MarkdownLine], title: str
) -> list[tuple[int, str]]:
    positions: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if not line.visible:
            continue
        if _atx_heading(line.text) == (2, title):
            positions.append((line.start, "atx"))
        if line.text.strip(" \t") != title or index + 1 >= len(lines):
            continue
        underline = lines[index + 1]
        indentation = len(underline.text) - len(underline.text.lstrip(" "))
        if (
            underline.visible
            and indentation <= 3
            and re.fullmatch(r"-+[ \t]*", underline.text[indentation:])
        ):
            positions.append((line.start, "setext"))
    return positions


def visible_section_titles(text: str, section_titles: tuple[str, ...]) -> set[str]:
    """Return managed section titles that are visible as ATX or Setext H2s."""

    lines = _markdown_lines(text)
    return {
        title
        for title in section_titles
        if _visible_h2_title_positions(lines, title)
    }


def visible_markdown_lines(text: str) -> tuple[str, ...]:
    """Return source lines exposed by conservative Markdown block parsing."""

    return tuple(line.text for line in _markdown_lines(text) if line.visible)


def visible_markdown_line_spans(text: str) -> tuple[BlockSpan, ...]:
    """Return complete source-line spans exposed as ordinary Markdown text."""

    return tuple(
        BlockSpan(line.start, line.end)
        for line in _markdown_lines(text)
        if line.visible
    )


def markdown_line_spans(text: str) -> list[tuple[int, int, bool]]:
    """Return every physical Markdown line with its visibility state."""

    return [(line.start, line.end, line.visible) for line in _markdown_lines(text)]


def visible_exact_line_spans(
    text: str, candidates: frozenset[str]
) -> tuple[BlockSpan, ...]:
    """Return spans of visible source lines exactly matching ``candidates``."""

    return tuple(
        BlockSpan(line.start, line.end)
        for line in _markdown_lines(text)
        if line.visible and line.text in candidates
    )


def visible_atx_heading_positions(
    text: str, level: int, title: str
) -> tuple[int, ...]:
    """Return source offsets for one visible ATX heading."""

    return tuple(
        line.start
        for line in _markdown_lines(text)
        if line.visible and _atx_heading(line.text) == (level, title)
    )


def visible_atx_headings(text: str) -> tuple[tuple[int, str, int], ...]:
    """Return visible ATX headings as ``(level, title, offset)`` tuples."""

    headings: list[tuple[int, str, int]] = []
    for line in _markdown_lines(text):
        if not line.visible:
            continue
        heading = _atx_heading(line.text)
        if heading is not None:
            headings.append((heading[0], heading[1], line.start))
    return tuple(headings)


def has_visible_h1_or_h2(text: str) -> bool:
    """Return whether Markdown exposes an ATX or Setext H1/H2 heading."""

    lines = _markdown_lines(text)
    for index, line in enumerate(lines):
        if not line.visible:
            continue
        heading = _atx_heading(line.text)
        if heading is not None and heading[0] <= 2:
            return True
        indentation = len(line.text) - len(line.text.lstrip(" "))
        candidate = line.text[indentation:]
        if (
            index > 0
            and indentation <= 3
            and re.fullmatch(r"(?:=+|-+)[ \t]*", candidate)
        ):
            previous = lines[index - 1]
            if previous.visible and previous.text.strip(" \t"):
                return True
    return False


def locate_visible_asset_block(
    text: str,
    asset: str,
    section_titles: tuple[str, ...],
    label: str,
) -> BlockSpan | None:
    """Locate one visible asset by stable first/last lines and ATX H2 titles."""

    if not section_titles:
        raise ValueError("section_titles 不得为空")
    if len(set(section_titles)) != len(section_titles):
        raise ValueError("section_titles 不得重复")
    first_line, last_line = _asset_boundary_lines(asset, label)
    lines = _markdown_lines(text)
    all_first_matches = [line for line in lines if line.text == first_line]
    all_last_matches = [line for line in lines if line.text == last_line]
    first_matches = [line for line in all_first_matches if line.visible]
    last_matches = [line for line in all_last_matches if line.visible]
    hidden_first_matches = [line for line in all_first_matches if not line.visible]
    hidden_last_matches = [line for line in all_last_matches if not line.visible]

    if hidden_first_matches and hidden_last_matches:
        raise ManagedBlockError(
            f"{label} 的首尾边界同时出现在代码围栏或 HTML block 内"
        )

    raw_position_set: set[int] = set()
    for asset_variant in {asset, asset.replace("\n", "\r\n")}:
        cursor = 0
        while True:
            position = text.find(asset_variant, cursor)
            if position < 0:
                break
            raw_position_set.add(position)
            cursor = position + 1
    raw_positions = sorted(raw_position_set)

    if not first_matches and not last_matches:
        if raw_positions:
            raise ManagedBlockError(f"{label} 只出现在代码围栏或 HTML block 内")
        return None
    if len(first_matches) != 1 or len(last_matches) != 1:
        raise ManagedBlockError(f"{label} 的可见首尾边界行必须各出现一次")

    start_line = first_matches[0]
    end_line = last_matches[0]
    if end_line.start < start_line.start:
        raise ManagedBlockError(f"{label} 的可见首尾边界行顺序错误")

    title_positions: list[int] = []
    for title in section_titles:
        matching_positions = _visible_h2_title_positions(lines, title)
        if len(matching_positions) != 1:
            raise ManagedBlockError(
                f"{label} 必须且只能包含一个“## {title}”标题"
            )
        title_position, title_style = matching_positions[0]
        if not (
            title_style == "atx"
            and start_line.start <= title_position <= end_line.start
        ):
            raise ManagedBlockError(
                f"{label} 的“## {title}”标题必须位于可见首尾边界内"
            )
        title_positions.append(title_position)

    if title_positions != sorted(title_positions):
        raise ManagedBlockError(f"{label} 的标题顺序错误")

    allowed_title_positions = set(title_positions)
    for line in lines:
        if not (
            line.visible and start_line.start <= line.start <= end_line.start
        ):
            continue
        heading = _atx_heading(line.text)
        indentation = len(line.text) - len(line.text.lstrip(" "))
        if indentation <= 3 and re.fullmatch(
            r"(?:=+|-+)[ \t]*", line.text[indentation:]
        ):
            raise ManagedBlockError(
                f"{label} 的可见首尾边界之间不得出现 Setext 标题或歧义分隔线"
            )
        if (
            heading is not None
            and heading[0] <= 2
            and line.start not in allowed_title_positions
        ):
            raise ManagedBlockError(
                f"{label} 的可见首尾边界之间不得出现其他 H1/H2 标题"
            )

    if len(raw_positions) > 1 or (
        raw_positions and raw_positions[0] != start_line.start
    ):
        raise ManagedBlockError(f"{label} 在不可见位置重复或边界冲突")
    return BlockSpan(start=start_line.start, end=end_line.end)


def _is_inside_hidden_markdown_block(data: TextData, position: int) -> bool:
    prefix = data[:position]
    if isinstance(prefix, bytes):
        text = prefix.decode("utf-8", errors="replace")
    else:
        text = prefix
    probe = _markdown_lines(text + "write-project-docs-probe\n")[-1]
    return not probe.visible


def locate_managed_block(
    data: TextData,
    start_marker: TextData,
    end_marker: TextData,
    label: str,
) -> BlockSpan | None:
    """Locate one ordered whole-line block, or reject any malformed marker state."""

    start_count = data.count(start_marker)
    end_count = data.count(end_marker)
    if start_count == 0 and end_count == 0:
        return None
    if start_count != 1 or end_count != 1:
        raise ManagedBlockError(
            f"{label} marker 必须各出现一次，且不得缺失或重复"
        )

    start = data.index(start_marker)
    end_start = data.index(end_marker)
    if not _is_standalone_marker(data, start, start_marker) or not _is_standalone_marker(
        data, end_start, end_marker
    ):
        raise ManagedBlockError(f"{label} marker 必须独占整行")
    if _is_inside_markdown_fence(data, start) or _is_inside_markdown_fence(
        data, end_start
    ):
        raise ManagedBlockError(f"{label} marker 不得位于 Markdown 代码围栏内")
    if _is_inside_hidden_markdown_block(
        data, start
    ) or _is_inside_hidden_markdown_block(data, end_start):
        raise ManagedBlockError(f"{label} marker 不得位于 HTML block 内")
    if end_start < start:
        raise ManagedBlockError(f"{label} marker 顺序错误")

    end = end_start + len(end_marker)
    crlf = b"\r\n" if isinstance(data, bytes) else "\r\n"
    newline = b"\n" if isinstance(data, bytes) else "\n"
    if data[end : end + 2] == crlf:
        end += 2
    elif data[end : end + 1] == newline:
        end += 1
    return BlockSpan(start=start, end=end)


def locate_all_managed_blocks(text: str) -> tuple[tuple[str, BlockSpan], ...]:
    """Locate every visible ``owner:name:(start|end)`` marker pair.

    Marker-looking text inside fenced code or an existing raw HTML block is
    ordinary protected source text, not a managed boundary. Every exposed
    boundary must form one unique, ordered, non-overlapping pair so a writer
    never guesses how much foreign content it owns.
    """

    boundaries: dict[str, dict[str, list[tuple[int, int]]]] = {}
    offset = 0
    for line_with_ending in text.splitlines(keepends=True):
        line = line_with_ending.rstrip("\r\n")
        matches = tuple(MANAGED_MARKER_RE.finditer(line))
        if not matches:
            offset += len(line_with_ending)
            continue
        hidden_before_line = _is_inside_markdown_fence(
            text, offset
        ) or _is_inside_hidden_markdown_block(text, offset)
        exact_marker = len(matches) == 1 and matches[0].span() == (0, len(line))
        hidden_by_current_line = (
            _next_fence_state(None, line) is not None
            or _starts_html_block(line, allow_type7=True) is not None
        )
        if hidden_before_line or (not exact_marker and hidden_by_current_line):
            offset += len(line_with_ending)
            continue
        if not exact_marker:
            raise ManagedBlockError("托管区块 marker 必须独占整行")
        match = matches[0]
        name = match.group("name")
        boundary = match.group("boundary")
        boundaries.setdefault(name, {"start": [], "end": []})[boundary].append(
            (offset, offset + len(line_with_ending))
        )
        offset += len(line_with_ending)

    located: list[tuple[str, BlockSpan]] = []
    for name, positions in boundaries.items():
        starts = positions["start"]
        ends = positions["end"]
        if len(starts) != 1 or len(ends) != 1:
            raise ManagedBlockError(
                f"托管区块 {name} 的 marker 必须各出现一次，且不得缺失或重复"
            )
        start, _start_end = starts[0]
        end_start, end = ends[0]
        if end_start < start:
            raise ManagedBlockError(f"托管区块 {name} 的 marker 顺序错误")
        located.append((name, BlockSpan(start, end)))

    located.sort(key=lambda item: (item[1].start, item[1].end, item[0]))
    for previous, current in zip(located, located[1:]):
        if current[1].start < previous[1].end:
            raise ManagedBlockError(
                f"托管区块 {previous[0]} 与 {current[0]} 不得嵌套或重叠"
            )
    return tuple(located)
