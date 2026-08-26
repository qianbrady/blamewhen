"""git 子进程封装。

所有 subprocess 调用一律显式 ``encoding="utf-8", errors="replace"``，
并容忍输出中的 CRLF。失败场景抛 :class:`GitError`（友好中文消息）。
"""

from __future__ import annotations

import datetime
import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional

_SUBPROCESS_ENCODING = dict(encoding="utf-8", errors="replace")
_LOCKFILE_CANDIDATES = ("package-lock.json", "npm-shrinkwrap.json")


class GitError(Exception):
    """git 不可用 / 非 git 仓库 / git 命令失败。"""


@dataclass(frozen=True)
class Commit:
    """一次历史提交的元信息。"""

    sha: str
    date: datetime.datetime
    author: str
    message: str

    @property
    def short(self) -> str:
        return self.sha[:7]


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            **_SUBPROCESS_ENCODING,
            timeout=120,
        )
    except FileNotFoundError:
        raise GitError("未找到 git 可执行文件，请先安装 git") from None
    except subprocess.TimeoutExpired:
        raise GitError("git 命令执行超时") from None
    return proc


def is_git_repo(repo: str) -> bool:
    return _git(repo, "rev-parse", "--is-inside-work-tree").returncode == 0


def head_sha(repo: str) -> Optional[str]:
    """当前 HEAD 的完整 sha；非 git 仓库返回 None。"""
    proc = _git(repo, "rev-parse", "HEAD")
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def find_lockfile(repo: str) -> Optional[str]:
    """在 git 追踪的文件中找 lockfile。

    优先级 package-lock.json > npm-shrinkwrap.json（均按 basename 匹配，
    取字典序第一个），支持放在子目录（monorepo）。未找到返回 None。
    """
    if not is_git_repo(repo):
        raise GitError("路径不是 git 仓库：%s" % repo)
    proc = _git(repo, "ls-files")
    if proc.returncode != 0:
        raise GitError("git ls-files 失败：%s" % proc.stderr.strip())
    tracked = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    for candidate in _LOCKFILE_CANDIDATES:
        for name in sorted(tracked):
            if os.path.basename(name) == candidate:
                return name
    return None


def log_history(repo: str, path: str) -> List[Commit]:
    """该文件的历史提交（含重命名，--follow），从旧到新排序（确定性）。"""
    proc = _git(
        repo,
        "log",
        "--follow",
        "--format=%H%x09%aI%x09%an%x09%s",
        "--",
        path,
    )
    if proc.returncode != 0:
        raise GitError("git log 失败：%s" % proc.stderr.strip())
    commits: List[Commit] = []
    for line in proc.stdout.splitlines():
        line = line.rstrip("\r")  # 容忍 CRLF
        if not line:
            continue
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        sha, iso_date, author, message = parts
        try:
            date = datetime.datetime.fromisoformat(iso_date)
        except ValueError:
            continue  # 无法解析的日期直接跳过，不影响其余历史
        commits.append(Commit(sha=sha, date=date, author=author, message=message))
    commits.sort(key=lambda c: (c.date, c.sha))
    return commits


def show_file(repo: str, commit_sha: str, path: str) -> Optional[str]:
    """取某提交中该文件的内容；该提交不含此文件返回 None。"""
    proc = _git(repo, "show", "%s:%s" % (commit_sha, path))
    if proc.returncode != 0:
        return None
    return proc.stdout


def files_in_commit(repo: str, commit_sha: str) -> List[str]:
    """某提交改动的所有文件（按 git 输出顺序，确定性）。"""
    proc = _git(repo, "show", "--name-only", "--format=", commit_sha)
    if proc.returncode != 0:
        return []
    return [line.rstrip("\r") for line in proc.stdout.splitlines() if line.strip()]