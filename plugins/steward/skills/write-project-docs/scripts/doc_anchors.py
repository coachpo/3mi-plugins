#!/usr/bin/env python3
"""Per-language structural anchors and asset names for every managed block.

This module is the only definition site for the development-rules H1, the MVP
status line and heading, the shared and iteration-strategy CONTRIBUTING headings,
the root AGENTS.md H2s and the size-rules block heading. Add a language or reword
an anchor here; never hard-code these literals in the scripts.
"""

from __future__ import annotations

from dataclasses import dataclass

from canonical_paths import DocumentLanguage


@dataclass(frozen=True)
class LanguageProfile:
    """Every heading, status line and asset name that varies by document language."""

    language: DocumentLanguage
    assets_directory: str
    development_rules_title: str
    development_block_titles: tuple[str, ...]
    mvp_status_key: str
    mvp_status_separator: str
    mvp_enabled_value: str
    mvp_disabled_value: str
    mvp_title: str
    contributing_section_titles: tuple[str, ...]
    completion_title: str
    iteration_strategy_title: str
    iteration_strategy_section_titles: tuple[str, ...]
    agents_section_titles: tuple[str, ...]
    agents_asset_name: str
    contributing_base_asset_name: str
    contributing_mvp_asset_name: str
    development_asset_name: str
    source_size_asset_name: str

    @property
    def mvp_status_enabled_line(self) -> str:
        return (
            self.mvp_status_key
            + self.mvp_status_separator
            + self.mvp_enabled_value
        )

    @property
    def mvp_status_disabled_line(self) -> str:
        return (
            self.mvp_status_key
            + self.mvp_status_separator
            + self.mvp_disabled_value
        )

    @property
    def mvp_heading(self) -> str:
        return "### " + self.mvp_title

    @property
    def completion_heading(self) -> str:
        return "## " + self.completion_title + "\n"

    def asset_path(self, skill_root, name: str):
        """Resolve one asset inside this language's assets subdirectory."""

        return skill_root / "assets" / self.assets_directory / name

    def asset_display(self, name: str) -> str:
        return f"assets/{self.assets_directory}/{name}"


CHINESE_PROFILE = LanguageProfile(
    language=DocumentLanguage.CHINESE,
    assets_directory="zh",
    development_rules_title="# 开发规范",
    development_block_titles=("通用规模与职责规则",),
    mvp_status_key="MVP 快速验证模式",
    mvp_status_separator="：",
    mvp_enabled_value="启用",
    mvp_disabled_value="未启用",
    mvp_title="MVP 快速验证",
    contributing_section_titles=("通用设计原则", "通用实现原则", "完成定义"),
    completion_title="完成定义",
    iteration_strategy_title="当前迭代策略",
    iteration_strategy_section_titles=(
        "本轮必须完成",
        "本轮不主动投入",
        "不可降低的边界",
        "重新推导条件",
    ),
    agents_section_titles=("项目文档导航", "项目文档内容边界"),
    agents_asset_name="AGENTS-文档导航区块.md",
    contributing_base_asset_name="CONTRIBUTING-通用区块.md",
    contributing_mvp_asset_name="CONTRIBUTING-MVP-快速验证区块.md",
    development_asset_name="开发规范-规模规则区块.md",
    source_size_asset_name="源代码规模与职责规则.md",
)

ENGLISH_PROFILE = LanguageProfile(
    language=DocumentLanguage.ENGLISH,
    assets_directory="en",
    development_rules_title="# Development Rules",
    development_block_titles=("General Size and Responsibility Rules",),
    mvp_status_key="MVP Fast Validation Mode",
    mvp_status_separator=": ",
    mvp_enabled_value="Enabled",
    mvp_disabled_value="Disabled",
    mvp_title="MVP Fast Validation",
    contributing_section_titles=(
        "General Design Principles",
        "General Implementation Principles",
        "Definition of Done",
    ),
    completion_title="Definition of Done",
    iteration_strategy_title="Current Iteration Strategy",
    iteration_strategy_section_titles=(
        "Must Complete Now",
        "Not Pursued This Iteration",
        "Non-negotiable Boundaries",
        "Re-derivation Triggers",
    ),
    agents_section_titles=(
        "Project Documentation Navigation",
        "Project Documentation Content Boundaries",
    ),
    agents_asset_name="AGENTS-document-navigation.md",
    contributing_base_asset_name="CONTRIBUTING-general.md",
    contributing_mvp_asset_name="CONTRIBUTING-mvp-fast-validation.md",
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


def foreign_mvp_status_keys(language: DocumentLanguage) -> tuple[str, ...]:
    """Return MVP status keys belonging to the other language, for diagnostics."""

    return tuple(
        candidate.mvp_status_key
        for candidate in LANGUAGE_PROFILES.values()
        if candidate.language is not language
    )
