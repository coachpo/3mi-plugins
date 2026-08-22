#!/usr/bin/env python3
"""Per-language structural anchors and asset names for managed documents.

Keep every localized exact status key, heading and asset name here.  Scripts
must consume these anchors rather than duplicating translated literals.
"""

from __future__ import annotations

from dataclasses import dataclass

from canonical_paths import DocumentLanguage


@dataclass(frozen=True)
class LanguageProfile:
    """Every heading, status line and asset name that varies by language."""

    language: DocumentLanguage
    assets_directory: str
    development_rules_title: str
    development_block_titles: tuple[str, ...]
    development_tier_key: str
    development_tier_separator: str
    development_tier_label_prefix: str
    development_strategy_title: str
    development_strategy_section_titles: tuple[str, ...]
    contributing_section_titles: tuple[str, ...]
    completion_title: str
    legacy_mvp_status_key: str
    legacy_mvp_enabled_line: str
    legacy_mvp_disabled_line: str
    legacy_mvp_title: str
    legacy_iteration_strategy_title: str
    agents_section_titles: tuple[str, ...]
    agents_asset_name: str
    contributing_base_asset_name: str
    development_asset_name: str
    source_size_asset_name: str

    def development_tier_line(self, token: str) -> str:
        return self.development_tier_key + self.development_tier_separator + token

    def development_tier_label(self, token: str) -> str:
        return self.development_tier_label_prefix + token + "`**"

    @property
    def development_strategy_heading(self) -> str:
        return "## " + self.development_strategy_title

    @property
    def managed_contributing_section_titles(self) -> tuple[str, ...]:
        return (self.development_strategy_title, *self.contributing_section_titles)

    @property
    def completion_heading(self) -> str:
        return "## " + self.completion_title + "\n"

    @staticmethod
    def contributing_tier_asset_name(token: str) -> str:
        slug = token.lower().replace("_", "-")
        return f"CONTRIBUTING-tier-{slug}.md"

    def asset_path(self, skill_root, name: str):
        """Resolve one asset inside this language's assets subdirectory."""

        return skill_root / "assets" / self.assets_directory / name

    def tier_asset_path(self, skill_root, token: str):
        return self.asset_path(skill_root, self.contributing_tier_asset_name(token))

    def asset_display(self, name: str) -> str:
        return f"assets/{self.assets_directory}/{name}"


CHINESE_PROFILE = LanguageProfile(
    language=DocumentLanguage.CHINESE,
    assets_directory="zh",
    development_rules_title="# 开发规范",
    development_block_titles=("通用规模与职责规则",),
    development_tier_key="开发档位",
    development_tier_separator="：",
    development_tier_label_prefix="**开发档位：`",
    development_strategy_title="当前开发策略",
    development_strategy_section_titles=(
        "本档位必须完成",
        "默认不投入",
        "不可越过的边界",
        "切换条件",
    ),
    contributing_section_titles=("通用设计原则", "通用实现原则", "完成定义"),
    completion_title="完成定义",
    legacy_mvp_status_key="MVP 快速验证模式",
    legacy_mvp_enabled_line="MVP 快速验证模式：启用",
    legacy_mvp_disabled_line="MVP 快速验证模式：未启用",
    legacy_mvp_title="MVP 快速验证",
    legacy_iteration_strategy_title="当前迭代策略",
    agents_section_titles=("项目文档导航", "项目文档内容边界"),
    agents_asset_name="AGENTS-文档导航区块.md",
    contributing_base_asset_name="CONTRIBUTING-通用区块.md",
    development_asset_name="开发规范-规模规则区块.md",
    source_size_asset_name="源代码规模与职责规则.md",
)

ENGLISH_PROFILE = LanguageProfile(
    language=DocumentLanguage.ENGLISH,
    assets_directory="en",
    development_rules_title="# Development Rules",
    development_block_titles=("General Size and Responsibility Rules",),
    development_tier_key="Development Tier",
    development_tier_separator=": ",
    development_tier_label_prefix="**Development tier: `",
    development_strategy_title="Current Development Strategy",
    development_strategy_section_titles=(
        "Must Complete at This Tier",
        "Not Pursued by Default",
        "Non-negotiable Boundaries",
        "Tier Transition Conditions",
    ),
    contributing_section_titles=(
        "General Design Principles",
        "General Implementation Principles",
        "Definition of Done",
    ),
    completion_title="Definition of Done",
    legacy_mvp_status_key="MVP Fast Validation Mode",
    legacy_mvp_enabled_line="MVP Fast Validation Mode: Enabled",
    legacy_mvp_disabled_line="MVP Fast Validation Mode: Disabled",
    legacy_mvp_title="MVP Fast Validation",
    legacy_iteration_strategy_title="Current Iteration Strategy",
    agents_section_titles=(
        "Project Documentation Navigation",
        "Project Documentation Content Boundaries",
    ),
    agents_asset_name="AGENTS-document-navigation.md",
    contributing_base_asset_name="CONTRIBUTING-general.md",
    development_asset_name="development-rules-size-block.md",
    source_size_asset_name="source-code-size-and-responsibility-rules.md",
)

LANGUAGE_PROFILES = {
    DocumentLanguage.CHINESE: CHINESE_PROFILE,
    DocumentLanguage.ENGLISH: ENGLISH_PROFILE,
}


def profile_for(language: DocumentLanguage) -> LanguageProfile:
    """Return the anchor set for one resolved document language."""

    try:
        return LANGUAGE_PROFILES[language]
    except KeyError as error:
        raise ValueError(f"未知的项目文档语言：{language}") from error


def foreign_development_tier_keys(language: DocumentLanguage) -> tuple[str, ...]:
    """Return tier keys belonging to the other document language."""

    return tuple(
        candidate.development_tier_key
        for candidate in LANGUAGE_PROFILES.values()
        if candidate.language is not language
    )


def legacy_mvp_status_keys() -> tuple[str, ...]:
    """Return every retired MVP control key for strict migration diagnostics."""

    return tuple(
        candidate.legacy_mvp_status_key
        for candidate in LANGUAGE_PROFILES.values()
    )
