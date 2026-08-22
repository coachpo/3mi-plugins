#!/usr/bin/env python3
"""Update the independent derived iteration-strategy block in CONTRIBUTING.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from canonical_paths import (
    add_language_argument,
    requested_language,
    resolve_project_docs,
)
from contributing_blocks import parse_mvp_mode
from doc_anchors import profile_for
from iteration_strategy import (
    MAX_HANDOFF_BYTES,
    insert_or_replace_iteration_strategy,
    parse_iteration_strategy_handoff,
    remove_iteration_strategy,
    render_iteration_strategy_block,
    strategy_source_bindings,
    strategy_source_paths,
    validate_iteration_strategy_block,
    validate_iteration_strategy_document,
)
from safe_write import AtomicWriteCommittedError, read_snapshot, write_atomically


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "从 stdin 的严格 JSON handoff 更新 CONTRIBUTING.md 当前迭代策略区块；"
            "语义策略由调用方推导，脚本只验证和投影。"
        )
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="项目根目录，默认为当前目录。",
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="移除当前迭代策略托管区块；此模式不读取 stdin。",
    )
    add_language_argument(parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).expanduser().resolve()
    if not root.is_dir():
        print(f"错误：项目根目录不存在或不是目录：{root}")
        return 2

    context = resolve_project_docs(root, language=requested_language(args.language))
    if context.errors:
        print("错误：")
        for error in context.errors:
            print(f"- {error}")
        print("未修改 CONTRIBUTING.md")
        return 1
    profile = profile_for(context.language)
    status_path = root / "STATUS.md"
    contributing_path = root / "CONTRIBUTING.md"
    try:
        source_file_snapshots = tuple(
            (root / relative, read_snapshot(root / relative))
            for relative in strategy_source_paths(context.selected)
        )
        status_snapshot = next(
            snapshot for path, snapshot in source_file_snapshots if path == status_path
        )
        status_text = status_snapshot.data.decode("utf-8")
        parse_mvp_mode(status_text, context.language)
        source_snapshot = strategy_source_bindings(
            root, context.selected, context.language
        )
        for path, snapshot in source_file_snapshots:
            if read_snapshot(path) != snapshot:
                raise ValueError(f"{path.name} 在来源绑定期间发生变化")
        contributing_snapshot = read_snapshot(contributing_path)
        original = contributing_snapshot.data.decode("utf-8")
    except UnicodeDecodeError:
        print("错误：STATUS.md 或 CONTRIBUTING.md 不是有效 UTF-8；未修改")
        return 1
    except (OSError, ValueError) as error:
        print(f"错误：{error}；未修改")
        return 1

    if args.remove:
        try:
            updated, action = remove_iteration_strategy(original, profile)
        except ValueError as error:
            print(f"错误：{error}；未修改")
            return 1
    else:
        handoff_data = sys.stdin.buffer.read(MAX_HANDOFF_BYTES + 1)
        try:
            handoff = parse_iteration_strategy_handoff(handoff_data, context.language)
        except ValueError as error:
            print(f"错误：{error}；未修改")
            return 2
        try:
            block = render_iteration_strategy_block(
                handoff, root, context.selected, profile
            )
            validate_iteration_strategy_block(block, root, context.selected, profile)
            updated, action = insert_or_replace_iteration_strategy(
                original, block, profile
            )
        except (OSError, ValueError) as error:
            print(f"错误：{error}；未修改")
            return 1

    try:
        validate_iteration_strategy_document(updated, root, context.selected, profile)
    except (OSError, ValueError) as error:
        print(f"错误：{error}；未修改")
        return 1

    def precommit_validate() -> None:
        current_context = resolve_project_docs(
            root, language=requested_language(args.language)
        )
        if current_context.errors:
            raise ValueError("写入前固定文档路径或语言发生变化")
        if (
            current_context.language is not context.language
            or current_context.selected != context.selected
        ):
            raise ValueError("写入前固定文档路径或语言发生变化")
        current_status = read_snapshot(status_path).data.decode("utf-8")
        parse_mvp_mode(current_status, current_context.language)
        current_sources = strategy_source_bindings(
            root, current_context.selected, current_context.language
        )
        if current_sources != source_snapshot:
            raise ValueError("当前迭代策略来源在写入期间发生变化")
        validate_iteration_strategy_document(
            updated,
            root,
            current_context.selected,
            profile_for(current_context.language),
        )

    if updated == original:
        try:
            precommit_validate()
            if read_snapshot(contributing_path) != contributing_snapshot:
                raise ValueError("CONTRIBUTING.md 在校验期间发生变化")
            for path, snapshot in source_file_snapshots:
                if read_snapshot(path) != snapshot:
                    raise ValueError(f"{path.name} 在校验期间发生变化")
        except (OSError, UnicodeDecodeError, ValueError) as error:
            print(f"错误：{error}；未修改")
            return 1
        if args.remove:
            print("CONTRIBUTING.md 不含当前迭代策略区块；未修改")
        else:
            print("CONTRIBUTING.md 当前迭代策略区块已是最新；未修改")
        return 0

    try:
        write_atomically(
            contributing_path,
            updated,
            contributing_snapshot,
            precommit_validate,
            input_snapshots=source_file_snapshots,
        )
    except AtomicWriteCommittedError as error:
        print(f"错误：{error}；文件已替换")
        return 1
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"错误：{error}；未修改")
        return 1
    if action == "removed":
        print("已移除 CONTRIBUTING.md 当前迭代策略区块。")
    else:
        action_text = "已插入" if action == "inserted" else "已更新"
        print(
            f"{action_text} CONTRIBUTING.md 当前迭代策略区块；"
            f"文档语言：{profile.language.label}。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
