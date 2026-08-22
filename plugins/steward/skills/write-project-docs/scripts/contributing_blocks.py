#!/usr/bin/env python3
"""Parse the MVP mode and compose the managed CONTRIBUTING block."""

from __future__ import annotations

from enum import Enum

from canonical_paths import DocumentLanguage, render_template
from doc_anchors import LanguageProfile, foreign_mvp_status_keys, profile_for
from managed_blocks import (
    ManagedBlockError,
    has_visible_h1_or_h2,
    locate_managed_block,
    visible_atx_heading_positions,
    visible_atx_headings,
    visible_markdown_lines,
)


class MvpMode(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ABSENT = "absent"

    @property
    def enabled(self) -> bool:
        return self is MvpMode.ENABLED

    @property
    def display(self) -> str:
        if self is MvpMode.ENABLED:
            return "启用"
        if self is MvpMode.DISABLED:
            return "未启用"
        return "未声明，按未启用处理"


def parse_mvp_mode(status_text: str, language: DocumentLanguage) -> MvpMode:
    """Return whether STATUS enables MVP mode; reject ambiguous visible states."""

    profile = profile_for(language)
    visible = visible_markdown_lines(status_text)
    states = [
        line for line in visible if line.startswith(profile.mvp_status_key)
    ]
    foreign_keys = foreign_mvp_status_keys(language)
    foreign_states = [
        line
        for line in visible
        if any(line.startswith(key) for key in foreign_keys)
    ]

    if foreign_states:
        raise ValueError(
            f"STATUS.md 的 MVP 状态行与项目文档语言（{profile.language.label}）"
            f"不一致；只能使用“{profile.mvp_status_enabled_line}”或"
            f"“{profile.mvp_status_disabled_line}”"
        )
    if not states:
        return MvpMode.ABSENT
    if len(states) > 1:
        raise ValueError(
            f"STATUS.md 的“{profile.mvp_status_key}”状态行重复或冲突"
        )
    state = states[0]
    if state == profile.mvp_status_enabled_line:
        return MvpMode.ENABLED
    if state == profile.mvp_status_disabled_line:
        return MvpMode.DISABLED
    raise ValueError(
        f"STATUS.md 的“{profile.mvp_status_key}”状态行无效；"
        f"必须精确写为“{profile.mvp_status_enabled_line}”或"
        f"“{profile.mvp_status_disabled_line}”"
    )


START_MARKER = "<!-- write-project-docs:shared-contributing:start -->"
END_MARKER = "<!-- write-project-docs:shared-contributing:end -->"


def validate_base_asset(base_asset: str, profile: LanguageProfile) -> None:
    """Require one complete base block without an embedded MVP section."""

    if (
        "\r" in base_asset
        or not base_asset.endswith("\n")
        or base_asset.rstrip(" \t\r\n") + "\n" != base_asset
    ):
        raise ValueError(
            "CONTRIBUTING 基础 asset 必须使用 LF，并仅保留一个尾随换行"
        )
    try:
        span = locate_managed_block(
            base_asset, START_MARKER, END_MARKER, "CONTRIBUTING 基础 asset"
        )
    except ManagedBlockError as error:
        raise ValueError(str(error)) from error
    if span is None or span.start != 0 or span.end != len(base_asset):
        raise ValueError("CONTRIBUTING 基础 asset 的 marker 必须包围整个 asset")
    if base_asset.count(profile.completion_heading) != 1:
        raise ValueError(
            "CONTRIBUTING 基础 asset 必须且只能包含一个"
            f"“## {profile.completion_title}”标题"
        )
    if mvp_heading_positions(base_asset, profile):
        raise ValueError(
            f"CONTRIBUTING 基础 asset 不得包含“{profile.mvp_heading}”区块"
        )


def validate_mvp_asset(mvp_asset: str, profile: LanguageProfile) -> None:
    """Validate the optional MVP asset before either mode is composed."""

    if (
        "\r" in mvp_asset
        or not mvp_asset.endswith("\n")
        or mvp_asset.rstrip(" \t\r\n") + "\n" != mvp_asset
    ):
        raise ValueError("CONTRIBUTING MVP asset 必须使用 LF，并仅保留一个尾随换行")
    if not mvp_asset.startswith(profile.mvp_heading + "\n\n"):
        raise ValueError(
            f"CONTRIBUTING MVP asset 必须以“{profile.mvp_heading}”及一个空行开头"
        )
    headings = visible_atx_headings(mvp_asset)
    h3_headings = [heading for heading in headings if heading[0] == 3]
    if h3_headings != [(3, profile.mvp_title, 0)]:
        raise ValueError(
            "CONTRIBUTING MVP asset 必须且只能包含一个可见"
            f"“{profile.mvp_heading}”标题"
        )
    if has_visible_h1_or_h2(mvp_asset):
        raise ValueError("CONTRIBUTING MVP asset 不得包含 H1 或 H2 标题")


def mvp_heading_positions(
    text: str, profile: LanguageProfile
) -> tuple[int, ...]:
    """Return visible managed-MVP heading offsets in a Markdown document."""

    return visible_atx_heading_positions(text, 3, profile.mvp_title)


def compose_contributing_block(
    base_asset: str,
    mvp_asset: str,
    *,
    mvp_mode: MvpMode,
    language: DocumentLanguage,
) -> str:
    """Insert the optional MVP H3 immediately before the completion section."""

    profile = profile_for(language)
    validate_base_asset(base_asset, profile)
    validate_mvp_asset(mvp_asset, profile)
    if not isinstance(mvp_mode, MvpMode):
        raise TypeError("mvp_mode 必须是 MvpMode")
    if not mvp_mode.enabled:
        return base_asset

    insertion = base_asset.index(profile.completion_heading)
    return base_asset[:insertion] + mvp_asset + "\n" + base_asset[insertion:]


def render_contributing_assets(
    base_data: bytes,
    mvp_data: bytes,
    selected: dict[str, str],
    language: DocumentLanguage,
) -> tuple[str, str]:
    """Render and validate both CONTRIBUTING assets through one shared path."""

    profile = profile_for(language)
    base_asset = render_template(
        base_data, selected, "CONTRIBUTING 基础 asset"
    ).decode("utf-8")
    mvp_asset = render_template(
        mvp_data, selected, "CONTRIBUTING MVP asset"
    ).decode("utf-8")
    validate_base_asset(base_asset, profile)
    validate_mvp_asset(mvp_asset, profile)
    return base_asset, mvp_asset
