#!/usr/bin/env python3
"""Update the source-size-policy section in the development rules."""

from __future__ import annotations

import argparse
from pathlib import Path

from canonical_paths import (
    add_language_argument,
    render_template,
    requested_language,
    resolve_project_docs,
)
from doc_anchors import LanguageProfile, profile_for
from managed_blocks import (
    ManagedBlockError,
    locate_managed_block,
    markdown_h1_lines,
    visible_section_titles,
)
from safe_write import AtomicWriteCommittedError, read_snapshot, write_atomically

START_MARKER = "<!-- write-project-docs:development-source-size:start -->"
END_MARKER = "<!-- write-project-docs:development-source-size:end -->"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="更新开发规范中指向源代码规模与职责规则的托管区块。"
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="项目根目录，默认为当前目录。",
    )
    add_language_argument(parser)
    return parser.parse_args()


def insert_after_title(text: str, asset: str, profile: LanguageProfile) -> str:
    title = profile.development_rules_title
    if markdown_h1_lines(text) != [title]:
        raise ValueError(f"开发规范必须包含唯一的“{title}”标题")

    if text == title:
        return text + "\n\n" + asset
    if text.startswith(title + "\r\n"):
        title_end = len(title + "\r\n")
        newline = "\r\n"
    elif text.startswith(title + "\n"):
        title_end = len(title + "\n")
        newline = "\n"
    else:
        raise ValueError(f"开发规范必须以“{title}”标题开头")

    prefix = text[:title_end] + newline
    remainder = text[title_end:]
    if remainder and not remainder.startswith(("\n", "\r\n")):
        remainder = newline + remainder
    return prefix + asset + remainder


def insert_or_replace_block(
    text: str, asset: str, profile: LanguageProfile
) -> tuple[str, str]:
    title = profile.development_rules_title
    if markdown_h1_lines(text) != [title]:
        raise ValueError(f"开发规范必须包含唯一的“{title}”标题")

    try:
        span = locate_managed_block(
            text, START_MARKER, END_MARKER, "开发规范的规模规则引用区块"
        )
    except ManagedBlockError as error:
        raise ValueError(str(error)) from error

    if span is None:
        if visible_section_titles(text, profile.development_block_titles):
            raise ValueError("开发规范的规模规则引用区块已漂移")
        return insert_after_title(text, asset, profile), "inserted"

    prefix = text[: span.start]
    if prefix in {title + "\n\n", title + "\r\n\r\n"}:
        return prefix + asset + text[span.end :], "replaced"

    newline = "\r\n" if text.startswith(title + "\r\n") else "\n"
    before = text[: span.start].rstrip("\r\n")
    after = text[span.end :].lstrip("\r\n")
    without_block = before
    if after:
        without_block += newline * 2 + after
    return insert_after_title(without_block, asset, profile), "replaced"


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).expanduser().resolve()
    skill_root = Path(__file__).resolve().parent.parent

    if not root.is_dir():
        print(f"错误：项目根目录不存在或不是目录：{root}")
        return 2

    context = resolve_project_docs(root, language=requested_language(args.language))
    if context.errors:
        print("错误：")
        for error in context.errors:
            print(f"- {error}")
        return 1
    selected = context.selected
    profile = profile_for(context.language)

    asset_path = profile.asset_path(skill_root, profile.development_asset_name)
    if asset_path.is_symlink() or not asset_path.is_file():
        print(
            "错误：skill 缺少普通文件 "
            + profile.asset_display(profile.development_asset_name)
        )
        return 2

    development_path = root / selected["development_rules"]
    if development_path.is_symlink():
        print("错误：开发规范是符号链接；未修改")
        return 1
    if not development_path.is_file():
        print(f"错误：开发规范不存在或不是普通文件：{development_path}")
        return 1

    try:
        asset_snapshot = read_snapshot(asset_path)
        development_snapshot = read_snapshot(development_path)
        asset = render_template(
            asset_snapshot.data, selected, "开发规范规模规则 asset"
        ).decode("utf-8")
        original = development_snapshot.data.decode("utf-8")
    except UnicodeDecodeError:
        print("错误：开发规范或 asset 不是有效 UTF-8；未修改")
        return 1
    except ValueError as error:
        print(f"错误：{error}")
        return 2

    try:
        asset_span = locate_managed_block(
            asset, START_MARKER, END_MARKER, "开发规范规模规则 asset"
        )
    except ManagedBlockError as error:
        print(f"错误：{error}")
        return 2
    if (
        asset_span is None
        or asset_span.start != 0
        or asset_span.end != len(asset)
        or not asset.endswith("\n")
        or asset.endswith("\n\n")
        or "\r" in asset
    ):
        print("错误：开发规范规模规则 asset 格式无效")
        return 2

    try:
        updated, action = insert_or_replace_block(original, asset, profile)
    except ValueError as error:
        print(f"错误：{error}；未修改")
        return 1

    def precommit_validate() -> None:
        current_context = resolve_project_docs(
            root, language=requested_language(args.language)
        )
        if (
            current_context.errors
            or current_context.language is not context.language
            or current_context.selected != context.selected
        ):
            raise ValueError("写入前固定文档路径或语言发生变化")

    if updated == original:
        try:
            precommit_validate()
            if (
                read_snapshot(development_path) != development_snapshot
                or read_snapshot(asset_path) != asset_snapshot
            ):
                raise ValueError("开发规范或 asset 在校验期间发生变化")
        except (OSError, UnicodeDecodeError, ValueError) as error:
            print(f"错误：{error}；未修改")
            return 1
        print("开发规范已包含正确的规模规则引用区块；未修改")
        return 0

    try:
        write_atomically(
            development_path,
            updated,
            development_snapshot,
            precommit_validate,
            input_snapshots=((asset_path, asset_snapshot),),
        )
    except AtomicWriteCommittedError as error:
        print(f"错误：{error}；文件已替换")
        return 1
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"错误：{error}；未修改")
        return 1
    action_text = "已插入" if action == "inserted" else "已更新"
    print(
        f"{action_text}开发规范的规模规则引用区块；文档语言：{profile.language.label}。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
