#!/usr/bin/env python3
"""Shared Markdown link parsing, so path rewrites never touch prose."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote

import re

from managed_blocks import markdown_line_spans


INLINE_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^)\s]+)(?:\s+['\"][^)]*)?\)"
)
REFERENCE_LINK_RE = re.compile(
    r"^\s*\[[^\]]+\]:\s*(?P<target><[^>]+>|\S+)", re.MULTILINE
)
ATX_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)")
BLOCKQUOTE_RE = re.compile(r"^ {0,3}>")
LIST_MARKER_RE = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])[ \t]+")
SETEXT_OR_THEMATIC_RE = re.compile(
    r"^ {0,3}(?:=+[ \t]*|-+[ \t]*|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$"
)


def _is_escaped(text: str, position: int) -> bool:
    backslashes = 0
    cursor = position - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _inline_code_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Return CommonMark-style backtick code spans, including multiline spans."""

    spans: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(text):
        start = text.find("`", cursor)
        if start < 0:
            break
        if _is_escaped(text, start):
            cursor = start + 1
            continue
        run_end = start
        while run_end < len(text) and text[run_end] == "`":
            run_end += 1
        delimiter = text[start:run_end]
        close = text.find(delimiter, run_end)
        while close >= 0:
            exact_start = close == 0 or text[close - 1] != "`"
            exact_end = (
                close + len(delimiter) == len(text)
                or text[close + len(delimiter)] != "`"
            )
            # Backslashes have no escaping semantics inside an open code span.
            if exact_start and exact_end:
                break
            close = text.find(delimiter, close + 1)
        if close < 0:
            cursor = run_end
            continue
        span_end = close + len(delimiter)
        spans.append((start, span_end))
        cursor = span_end
    return tuple(spans)


def _block_kind(line: str) -> str | None:
    """Classify boundaries that cannot share one inline parsing container."""

    if line.startswith("    ") or line.startswith("\t"):
        return "indented"
    if ATX_HEADING_RE.match(line) or SETEXT_OR_THEMATIC_RE.match(line):
        return "standalone"
    if REFERENCE_LINK_RE.match(line):
        return "standalone"
    if BLOCKQUOTE_RE.match(line):
        return "quote"
    if LIST_MARKER_RE.match(line):
        return "list"
    return None


def _visible_inline_containers(text: str) -> tuple[tuple[int, int], ...]:
    """Return CommonMark-like inline containers without crossing block boundaries."""

    containers: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end = 0
    current_kind: str | None = None

    def flush() -> None:
        nonlocal current_start, current_end, current_kind
        if current_start is not None:
            containers.append((current_start, current_end))
        current_start = None
        current_end = 0
        current_kind = None

    for start, end, visible in markdown_line_spans(text):
        line = text[start:end].rstrip("\r\n")
        if not visible or not line.strip():
            flush()
            continue

        kind = _block_kind(line)
        if kind == "indented" and current_start is not None:
            kind = None  # An indented continuation remains part of its paragraph.
        if kind == "indented":
            flush()
            continue  # Indented code is not an inline container.

        if current_start is None:
            current_start, current_end, current_kind = start, end, kind
        elif kind is None or (kind == "quote" and current_kind == "quote"):
            current_end = end
        else:
            flush()
            current_start, current_end, current_kind = start, end, kind

        if kind == "standalone":
            flush()

    flush()
    return tuple(containers)


def _visible_inline_code_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Parse code spans within visible CommonMark inline containers."""

    spans: list[tuple[int, int]] = []
    for segment_start, segment_end in _visible_inline_containers(text):
        spans.extend(
            (segment_start + begin, segment_start + finish)
            for begin, finish in _inline_code_spans(text[segment_start:segment_end])
        )
    return tuple(spans)


def _relative_spans(
    spans: tuple[tuple[int, int], ...], start: int, end: int
) -> tuple[tuple[int, int], ...]:
    return tuple(
        (max(begin, start) - start, min(finish, end) - start)
        for begin, finish in spans
        if begin < end and start < finish
    )


def _link_matches(
    line: str, code_spans: tuple[tuple[int, int], ...] | None = None
) -> list[re.Match[str]]:
    """Return ordered real-link matches outside inline code spans."""

    if code_spans is None:
        code_spans = _inline_code_spans(line)
    matches = [
        match
        for pattern in (INLINE_LINK_RE, REFERENCE_LINK_RE)
        for match in pattern.finditer(line)
        if not any(
            begin <= match.start() < finish
            or (
                begin < match.end("target")
                and match.start("target") < finish
            )
            for begin, finish in code_spans
        )
    ]
    matches.sort(key=lambda match: (match.start(), match.end()))
    return matches


@dataclass(frozen=True)
class _TargetParts:
    """One link target split into the path and whatever trails it."""

    prefix: str
    path: str
    suffix: str


def _split_target(target: str) -> _TargetParts:
    prefix = ""
    suffix = ""
    body = target
    if body.startswith("<") and body.endswith(">"):
        prefix, body, suffix = "<", body[1:-1], ">"
    positions = [
        position
        for marker in ("#", "?")
        if (position := body.find(marker)) >= 0
    ]
    if positions:
        position = min(positions)
        suffix = body[position:] + suffix
        body = body[:position]
    return _TargetParts(prefix=prefix, path=body, suffix=suffix)


def _matches(path: str, old_path: str) -> bool:
    """Match one whole relative path, never a substring of a longer one."""

    if not path:
        return False
    candidates = {path}
    decoded = unquote(path)
    candidates.add(decoded)
    for candidate in tuple(candidates):
        if candidate.startswith("./"):
            candidates.add(candidate[2:])
    return old_path in candidates


def _rewrite_target(
    target: str, mappings: tuple[tuple[str, str], ...]
) -> str | None:
    parts = _split_target(target)
    for old_path, new_path in mappings:
        if not _matches(parts.path, old_path):
            continue
        replacement = new_path
        if parts.path != unquote(parts.path):
            replacement = quote(new_path)
        if parts.path.startswith("./"):
            replacement = "./" + replacement
        return parts.prefix + replacement + parts.suffix
    return None


def _rewrite_line(
    line: str,
    mappings: tuple[tuple[str, str], ...],
    code_spans: tuple[tuple[int, int], ...] | None = None,
) -> tuple[str, list[str]]:
    replacements: list[str] = []
    pieces: list[str] = []
    cursor = 0
    for match in _link_matches(line, code_spans):
        if match.start("target") < cursor:
            continue
        rewritten = _rewrite_target(match.group("target"), mappings)
        if rewritten is None:
            continue
        pieces.append(line[cursor : match.start("target")])
        pieces.append(rewritten)
        replacements.append(f"{match.group('target')} → {rewritten}")
        cursor = match.end("target")
    if not replacements:
        return line, []
    pieces.append(line[cursor:])
    return "".join(pieces), replacements


def replace_visible_link_targets(
    text: str, mappings: tuple[tuple[str, str], ...]
) -> tuple[str, list[str]]:
    """Rewrite whole link paths on visible lines, leaving prose untouched."""

    if not mappings:
        return text, []

    pieces: list[str] = []
    replacements: list[str] = []
    code_spans = _visible_inline_code_spans(text)
    for start, end, visible in markdown_line_spans(text):
        raw = text[start:end]
        if not visible:
            pieces.append(raw)
            continue
        body = raw.rstrip("\r\n")
        ending = raw[len(body) :]
        rewritten, line_replacements = _rewrite_line(
            body,
            mappings,
            _relative_spans(code_spans, start, start + len(body)),
        )
        pieces.append(rewritten + ending)
        replacements.extend(line_replacements)
    return "".join(pieces), replacements


def visible_path_mentions(
    text: str, paths: tuple[str, ...]
) -> list[tuple[int, str]]:
    """Report visible non-link mentions of a path, which are never rewritten."""

    mentions: list[tuple[int, str]] = []
    line_number = 0
    code_spans = _visible_inline_code_spans(text)
    for start, end, visible in markdown_line_spans(text):
        line_number += 1
        if not visible:
            continue
        body = text[start:end].rstrip("\r\n")
        line_code_spans = _relative_spans(code_spans, start, start + len(body))
        excluded_spans = [
            (match.start("target"), match.end("target"))
            for match in _link_matches(body, line_code_spans)
        ]
        excluded_spans.extend(line_code_spans)
        for path in paths:
            position = body.find(path)
            while position >= 0:
                excluded = any(
                    begin <= position < finish for begin, finish in excluded_spans
                )
                if not excluded:
                    mentions.append((line_number, path))
                    break
                position = body.find(path, position + 1)
    return mentions
