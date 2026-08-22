#!/usr/bin/env python3
"""Parse the development tier and compose managed CONTRIBUTING content."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from canonical_paths import DocumentLanguage, render_template
from doc_anchors import (
    LANGUAGE_PROFILES,
    LanguageProfile,
    foreign_development_tier_keys,
    legacy_mvp_status_keys,
    profile_for,
)
from managed_blocks import (
    BlockSpan,
    ManagedBlockError,
    locate_managed_block,
    visible_atx_heading_positions,
    visible_atx_headings,
    visible_markdown_lines,
    visible_section_titles,
)


class ContributingBlockError(ValueError):
    """Raised when a tier or managed CONTRIBUTING asset is invalid."""


class DevelopmentTier(Enum):
    YOLO_LOCAL = "YOLO_LOCAL"
    EXPERIMENT = "EXPERIMENT"
    MVP = "MVP"
    PILOT = "PILOT"
    PRODUCTION = "PRODUCTION"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"

    @property
    def display(self) -> str:
        return self.value


START_MARKER = "<!-- write-project-docs:shared-contributing:start -->"
END_MARKER = "<!-- write-project-docs:shared-contributing:end -->"
LEGACY_STRATEGY_START_MARKER = (
    "<!-- write-project-docs:derived-iteration-strategy:start -->"
)
LEGACY_STRATEGY_END_MARKER = (
    "<!-- write-project-docs:derived-iteration-strategy:end -->"
)


def parse_development_tier(
    status_text: str, language: DocumentLanguage
) -> DevelopmentTier:
    """Parse one required exact development-tier line from visible Markdown."""

    profile = profile_for(language)
    visible = visible_markdown_lines(status_text)

    legacy_states = [
        line
        for line in visible
        if any(line.startswith(key) for key in legacy_mvp_status_keys())
    ]
    if legacy_states:
        if (
            len(legacy_states) == 1
            and legacy_states[0] == profile.legacy_mvp_enabled_line
        ):
            raise ContributingBlockError(
                "STATUS.md 使用已废弃的 MVP 启用状态；迁移时请精确改为"
                f"“{profile.development_tier_line(DevelopmentTier.MVP.value)}”"
            )
        if (
            len(legacy_states) == 1
            and legacy_states[0] == profile.legacy_mvp_disabled_line
        ):
            raise ContributingBlockError(
                "STATUS.md 使用已废弃的 MVP 未启用状态，无法推断开发档位；"
                "请显式选择一个开发档位"
            )
        raise ContributingBlockError(
            "STATUS.md 包含已废弃、重复、冲突或跨语言的 MVP 状态行；"
            "请删除旧状态并显式选择开发档位"
        )

    foreign_keys = foreign_development_tier_keys(language)
    foreign_states = [
        line
        for line in visible
        if any(line.startswith(key) for key in foreign_keys)
    ]
    if foreign_states:
        raise ContributingBlockError(
            f"STATUS.md 的开发档位行与项目文档语言（{profile.language.label}）"
            f"不一致；必须使用“{profile.development_tier_line('<TOKEN>')}”"
        )

    states = [
        line for line in visible if line.startswith(profile.development_tier_key)
    ]
    if not states:
        raise ContributingBlockError(
            "STATUS.md 缺少开发档位；必须精确声明一行"
            f"“{profile.development_tier_line('<TOKEN>')}”"
        )
    if len(states) > 1:
        raise ContributingBlockError(
            f"STATUS.md 的“{profile.development_tier_key}”状态行重复或冲突"
        )

    state = states[0]
    for tier in DevelopmentTier:
        if state == profile.development_tier_line(tier.value):
            return tier
    allowed = "、".join(tier.value for tier in DevelopmentTier)
    raise ContributingBlockError(
        f"STATUS.md 的“{profile.development_tier_key}”状态行无效；"
        f"允许值：{allowed}"
    )


def validate_base_asset(base_asset: str, profile: LanguageProfile) -> None:
    """Require one complete base block without a tier strategy section."""

    if (
        "\r" in base_asset
        or not base_asset.endswith("\n")
        or base_asset.rstrip(" \t\r\n") + "\n" != base_asset
    ):
        raise ContributingBlockError(
            "CONTRIBUTING 基础 asset 必须使用 LF，并仅保留一个尾随换行"
        )
    try:
        span = locate_managed_block(
            base_asset, START_MARKER, END_MARKER, "CONTRIBUTING 基础 asset"
        )
    except ManagedBlockError as error:
        raise ContributingBlockError(str(error)) from error
    if span is None or span.start != 0 or span.end != len(base_asset):
        raise ContributingBlockError(
            "CONTRIBUTING 基础 asset 的 marker 必须包围整个 asset"
        )
    headings = tuple(
        (level, title) for level, title, _position in visible_atx_headings(base_asset)
    )
    expected = tuple((2, title) for title in profile.contributing_section_titles)
    if headings != expected:
        raise ContributingBlockError(
            "CONTRIBUTING 基础 asset 的标题缺失、重复或顺序错误"
        )
    strategy_titles = tuple(
        candidate.development_strategy_title
        for candidate in LANGUAGE_PROFILES.values()
    )
    if visible_section_titles(base_asset, strategy_titles):
        raise ContributingBlockError("CONTRIBUTING 基础 asset 不得包含开发策略区块")


def validate_tier_asset(
    tier_asset: str,
    profile: LanguageProfile,
    development_tier: DevelopmentTier,
) -> None:
    """Validate one static tier strategy asset and its exact section grammar."""

    if not isinstance(development_tier, DevelopmentTier):
        raise TypeError("development_tier 必须是 DevelopmentTier")
    if (
        "\r" in tier_asset
        or not tier_asset.endswith("\n")
        or tier_asset.rstrip(" \t\r\n") + "\n" != tier_asset
    ):
        raise ContributingBlockError(
            "CONTRIBUTING 档位 asset 必须使用 LF，并仅保留一个尾随换行"
        )
    expected_prefix = (
        profile.development_strategy_heading
        + "\n\n"
        + profile.development_tier_label(development_tier.value)
        + "\n\n"
    )
    if not tier_asset.startswith(expected_prefix):
        raise ContributingBlockError(
            "CONTRIBUTING 档位 asset 必须以规范策略标题、档位标签和空行开头"
        )
    headings = visible_atx_headings(tier_asset)
    expected_headings = (
        (2, profile.development_strategy_title),
        *((3, title) for title in profile.development_strategy_section_titles),
    )
    actual_headings = tuple((level, title) for level, title, _ in headings)
    if actual_headings != expected_headings:
        raise ContributingBlockError(
            "CONTRIBUTING 档位 asset 的标题缺失、重复或顺序错误"
        )
    offsets = [position for _level, _title, position in headings]
    offsets.append(len(tier_asset))
    for index, title in enumerate(
        (
            profile.development_strategy_title,
            *profile.development_strategy_section_titles,
        )
    ):
        start = tier_asset.index("\n", offsets[index]) + 1
        body = tier_asset[start : offsets[index + 1]].strip()
        if not body:
            raise ContributingBlockError(
                f"CONTRIBUTING 档位 asset 的“{title}”内容不得为空"
            )
        if index > 0 and not any(
            line.startswith("- ") for line in body.splitlines()
        ):
            raise ContributingBlockError(
                f"CONTRIBUTING 档位 asset 的“{title}”必须包含列表项"
            )


def strategy_heading_positions(
    text: str, profile: LanguageProfile
) -> tuple[int, ...]:
    """Return visible managed development-strategy heading offsets."""

    return visible_atx_heading_positions(
        text, 2, profile.development_strategy_title
    )


def all_strategy_heading_positions(text: str) -> tuple[int, ...]:
    """Return strategy heading offsets for every supported language."""

    return tuple(
        sorted(
            position
            for candidate in LANGUAGE_PROFILES.values()
            for position in visible_atx_heading_positions(
                text, 2, candidate.development_strategy_title
            )
        )
    )


def all_legacy_mvp_heading_positions(text: str) -> tuple[int, ...]:
    """Return retired MVP heading offsets for every supported language."""

    return tuple(
        sorted(
            position
            for candidate in LANGUAGE_PROFILES.values()
            for position in visible_atx_heading_positions(
                text, 3, candidate.legacy_mvp_title
            )
        )
    )


def all_managed_contributing_titles() -> tuple[str, ...]:
    """Return every localized H2 title owned by the shared block."""

    return tuple(
        title
        for candidate in LANGUAGE_PROFILES.values()
        for title in candidate.managed_contributing_section_titles
    )


def compose_contributing_block(
    base_asset: str,
    tier_asset: str,
    *,
    development_tier: DevelopmentTier,
    language: DocumentLanguage,
) -> str:
    """Insert the selected static strategy immediately after the start marker."""

    profile = profile_for(language)
    validate_base_asset(base_asset, profile)
    validate_tier_asset(tier_asset, profile, development_tier)
    insertion = base_asset.index("\n") + 1
    return base_asset[:insertion] + tier_asset + "\n" + base_asset[insertion:]


def render_contributing_assets(
    base_data: bytes,
    tier_data: Mapping[DevelopmentTier, bytes],
    selected: dict[str, str],
    language: DocumentLanguage,
) -> tuple[str, dict[DevelopmentTier, str]]:
    """Render and validate the base asset and complete static tier catalog."""

    expected_tiers = set(DevelopmentTier)
    if set(tier_data) != expected_tiers:
        missing = sorted(tier.value for tier in expected_tiers - set(tier_data))
        extra = sorted(str(tier) for tier in set(tier_data) - expected_tiers)
        details = []
        if missing:
            details.append("缺少 " + "、".join(missing))
        if extra:
            details.append("未知 " + "、".join(extra))
        raise ContributingBlockError(
            "CONTRIBUTING 档位 catalog 不完整：" + "；".join(details)
        )

    profile = profile_for(language)
    base_asset = render_template(
        base_data, selected, "CONTRIBUTING 基础 asset"
    ).decode("utf-8")
    validate_base_asset(base_asset, profile)
    rendered: dict[DevelopmentTier, str] = {}
    for tier in DevelopmentTier:
        asset = render_template(
            tier_data[tier], selected, f"CONTRIBUTING {tier.value} 档位 asset"
        ).decode("utf-8")
        validate_tier_asset(asset, profile, tier)
        rendered[tier] = asset
    return base_asset, rendered


def locate_legacy_strategy_block(text: str) -> BlockSpan | None:
    """Locate one structurally valid retired dynamic-strategy block."""

    try:
        legacy = locate_managed_block(
            text,
            LEGACY_STRATEGY_START_MARKER,
            LEGACY_STRATEGY_END_MARKER,
            "CONTRIBUTING.md 的旧动态策略区块",
        )
        shared = locate_managed_block(
            text, START_MARKER, END_MARKER, "CONTRIBUTING.md 的共享区块"
        )
    except ManagedBlockError as error:
        raise ContributingBlockError(str(error)) from error

    legacy_titles = tuple(
        candidate.legacy_iteration_strategy_title
        for candidate in LANGUAGE_PROFILES.values()
    )
    outside = text if legacy is None else text[: legacy.start] + text[legacy.end :]
    if visible_section_titles(outside, legacy_titles):
        raise ContributingBlockError(
            "CONTRIBUTING.md 在旧托管区块外包含旧“当前迭代策略”标题"
        )
    if legacy is None:
        return None
    block_headings = [
        title
        for level, title, _ in visible_atx_headings(text[legacy.start : legacy.end])
        if level == 2 and title in legacy_titles
    ]
    if len(block_headings) != 1:
        raise ContributingBlockError(
            "CONTRIBUTING.md 的旧动态策略区块缺少唯一旧策略标题"
        )
    if shared is not None:
        if legacy.start < shared.end and shared.start < legacy.end:
            raise ContributingBlockError("旧动态策略区块不得与共享区块重叠或嵌套")
        if legacy.start > shared.start:
            raise ContributingBlockError("旧动态策略区块必须位于共享区块之前")
    return legacy


def remove_legacy_strategy_block(text: str) -> tuple[str, bool]:
    """Remove one valid retired strategy block and its separator newline."""

    legacy = locate_legacy_strategy_block(text)
    if legacy is None:
        return text, False
    try:
        shared = locate_managed_block(
            text, START_MARKER, END_MARKER, "CONTRIBUTING.md 的共享区块"
        )
    except ManagedBlockError as error:  # pragma: no cover - checked above
        raise ContributingBlockError(str(error)) from error
    suffix_start = legacy.end
    if shared is not None and legacy.end <= shared.start:
        between = text[legacy.end : shared.start]
        if between in {"\n", "\r\n"}:
            suffix_start = shared.start
    return text[: legacy.start] + text[suffix_start:], True
