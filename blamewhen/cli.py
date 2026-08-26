"""blamewhen CLI 入口。

退出码约定：
- 0：成功
- 1：数据/运行错误（路径不存在、非 git 仓库、无 lockfile、坏 JSON、
     包不存在、版本未出现）
- 2：用法错误（未知命令、参数缺失/非法）

确定性：所有输出行顺序固定（事件按提交日期+sha 排序），日期一律
ISO 8601（来自 git 的 author date），不依赖环境。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, TextIO

from . import __version__
from .blame import TimelineBuilder
from .gitrepo import GitError, files_in_commit, find_lockfile, head_sha, show_file
from .lockfile import LockfileError, parse_lockfile_text


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blamewhen",
        description="npm 依赖漏洞时间轴归因：给定依赖包名，回答“是谁、哪次提交把它引进来的”。",
    )
    parser.add_argument(
        "--version", action="version", version="blamewhen %s" % __version__
    )
    sub = parser.add_subparsers(dest="command", metavar="命令", required=True)

    p_timeline = sub.add_parser("timeline", help="输出某包版本变化时间轴")
    p_timeline.add_argument("package", help="npm 依赖包名")
    p_timeline.add_argument(
        "--path", default=".", metavar="仓库路径", help="仓库路径（默认当前目录）"
    )
    p_timeline.set_defaults(handler=_cmd_timeline)

    p_when = sub.add_parser("when", help="定位某版本首次出现的提交")
    p_when.add_argument("package", help="npm 依赖包名")
    p_when.add_argument("version", help="要定位的版本号")
    p_when.add_argument(
        "--path", default=".", metavar="仓库路径", help="仓库路径（默认当前目录）"
    )
    p_when.set_defaults(handler=_cmd_when)

    p_diff = sub.add_parser("diff", help="比较两个版本切换的间隔与跳过版本")
    p_diff.add_argument("package", help="npm 依赖包名")
    p_diff.add_argument("old_version", metavar="旧版本", help="旧的版本号")
    p_diff.add_argument("new_version", metavar="新版本", help="新的版本号")
    p_diff.add_argument(
        "--path", default=".", metavar="仓库路径", help="仓库路径（默认当前目录）"
    )
    p_diff.set_defaults(handler=_cmd_diff)

    return parser


def _prepare(repo: Path, package: str, err: TextIO):
    """公共准备：定位 lockfile 并构建时间轴。

    失败时向 err 输出中文提示并返回 None；成功返回
    ``(lockfile_path, builder, events)``。
    """
    try:
        lockfile = find_lockfile(str(repo))
    except GitError as exc:
        err.write("错误：%s\n" % exc)
        return None
    if lockfile is None:
        err.write(
            "错误：未找到 package-lock.json（或 npm-shrinkwrap.json）——"
            "该仓库的 git 历史中没有提交过 lockfile。\n"
        )
        return None
    # 当前 HEAD 的 lockfile 若为坏 JSON，先给出友好提示
    head = head_sha(str(repo))
    if head:
        content = show_file(str(repo), head, lockfile)
        if content is not None:
            try:
                parse_lockfile_text(content)
            except LockfileError as exc:
                err.write("错误：%s\n" % exc)
                return None
    builder = TimelineBuilder(str(repo), lockfile, package)
    try:
        events = builder.events()
    except (GitError, LockfileError) as exc:
        err.write("错误：%s\n" % exc)
        return None
    if not events:
        err.write(
            "错误：依赖包 “%s” 未出现在 %s 的历史时间轴中（从未被锁定）。\n"
            % (package, lockfile)
        )
        return None
    return lockfile, builder, events


def _cmd_timeline(args, repo: Path, out: TextIO, err: TextIO) -> int:
    prepared = _prepare(repo, args.package, err)
    if prepared is None:
        return 1
    lockfile, _builder, events = prepared
    out.write("依赖包：%s\n时间轴文件：%s\n" % (args.package, lockfile))
    out.write("日期|提交|版本变化|作者\n")
    for ev in events:
        frm = ev.from_version if ev.from_version is not None else "-"
        to = ev.to_version if ev.to_version is not None else "-"
        out.write(
            "%s|%s|%s→%s|%s\n" % (ev.date.isoformat(), ev.short, frm, to, ev.author)
        )
    return 0


def _cmd_when(args, repo: Path, out: TextIO, err: TextIO) -> int:
    prepared = _prepare(repo, args.package, err)
    if prepared is None:
        return 1
    lockfile, builder, _events = prepared
    ev = builder.first_intro(args.version)
    if ev is None:
        err.write(
            "错误：版本 %s 未出现在 %s 的时间轴中（该版本从未被锁定）。\n"
            % (args.version, lockfile)
        )
        return 1
    others = [
        f
        for f in files_in_commit(str(repo), ev.sha)
        if os.path.basename(f) != os.path.basename(lockfile)
    ]
    out.write("依赖：%s\n版本：%s\n" % (args.package, args.version))
    out.write(
        "首次出现提交：%s（%s）\n作者：%s\n提交信息：%s\n"
        % (ev.short, ev.date.isoformat(), ev.author, ev.message)
    )
    if others:
        out.write("同提交改动的其他文件：\n")
        for f in others:
            out.write("  - %s\n" % f)
    else:
        out.write("同提交改动的其他文件：（无）\n")
    return 0


def _cmd_diff(args, repo: Path, out: TextIO, err: TextIO) -> int:
    prepared = _prepare(repo, args.package, err)
    if prepared is None:
        return 1
    lockfile, builder, events = prepared
    if args.old_version == args.new_version:
        err.write("错误：旧版本与新版本相同：%s\n" % args.old_version)
        return 1
    result = builder.diff(args.old_version, args.new_version)
    if result is None:
        if builder.first_intro(args.new_version) is None:
            err.write(
                "错误：新版本 %s 未出现在 %s 的时间轴中。\n"
                % (args.new_version, lockfile)
            )
        else:
            err.write(
                "错误：无法定位 %s → %s 的切换"
                "（请确认旧版本在时间轴中出现过且早于新版本）。\n"
                % (args.old_version, args.new_version)
            )
        return 1
    out.write("依赖：%s\n版本：%s → %s\n" % (args.package, result.old, result.new))
    out.write("间隔时长：%s\n" % _fmt_duration(result.duration))
    out.write(
        "切换提交：%s（%s）→ %s（%s）\n"
        % (
            result.start.short,
            result.start.date.isoformat(),
            result.end.short,
            result.end.date.isoformat(),
        )
    )
    if result.skipped:
        parts = [v if v is not None else "（移除）" for v in result.skipped]
        out.write("中间跳过的版本：%s\n" % ", ".join(parts))
    else:
        out.write("中间跳过的版本：（无）\n")
    return 0


def _fmt_duration(td) -> str:
    """timedelta 的可读中文表述（确定性）。"""
    seconds = max(0, int(td.total_seconds()))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days > 0:
        return "%d 天 %d 小时" % (days, hours)
    if hours > 0:
        return "%d 小时 %d 分" % (hours, minutes)
    if minutes > 0:
        return "%d 分钟" % minutes
    return "%d 秒" % seconds


def main(argv: Optional[list] = None, out: Optional[TextIO] = None,
         err: Optional[TextIO] = None) -> int:
    """CLI 入口。

    返回值：``0`` 成功；``1`` 数据/运行错误。
    用法错误（未知命令、参数缺失/非法）由 argparse 抛 ``SystemExit(2)``
    ——在子进程/console script 下表现为退出码 ``2``；in-process 直接调用
    时调用方收到该异常而非返回值。开头强制 stdout/stderr 以 UTF-8 输出
    （errors=replace），保证在 GBK/其它代码页终端下不崩溃、不产生编码异常。
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # 非流对象或环境不支持时忽略
    stdout: TextIO = out if out is not None else sys.stdout
    stderr: TextIO = err if err is not None else sys.stderr

    parser = _build_parser()
    args = parser.parse_args(argv)

    repo = Path(args.path).expanduser().resolve()
    if not repo.is_dir():
        stderr.write("错误：路径不存在：%s\n" % repo)
        return 1
    return args.handler(args, repo, stdout, stderr)


if __name__ == "__main__":
    sys.exit(main())