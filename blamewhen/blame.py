"""依赖漏洞时间轴归因核心逻辑。

思路：对 lockfile 的 git 历史逐提交解析，得到该包被锁定的版本
序列；版本发生变化的那次提交即为「归因点」——回答谁、何时、从
哪个版本改到哪个版本。首次引入（从无到有）是最重要的归因点。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import List, Optional

from .gitrepo import Commit, GitError, log_history, show_file
from .lockfile import LockfileError, parse_lockfile_text, resolved_version


@dataclass(frozen=True)
class Event:
    """一次版本变化：提交 c 让该包从 from_version 变成 to_version。"""

    date: datetime.datetime
    sha: str
    from_version: Optional[str]  # None 表示首次引入（此前不存在）
    to_version: Optional[str]    # None 表示本次提交中该包被移除
    author: str
    message: str

    @property
    def short(self) -> str:
        return self.sha[:7]


@dataclass(frozen=True)
class DiffResult:
    """diff 命令的结构化结果。"""

    old: str
    new: str
    duration: datetime.timedelta
    start: Event
    end: Event
    skipped: List[str]  # old 与 new 之间被跳过（未锁定）的版本


class TimelineBuilder:
    """把 lockfile 历史重放成版本变化事件序列。"""

    def __init__(self, repo: str, lockfile_path: str, package: str) -> None:
        self.repo = repo
        self.lockfile_path = lockfile_path
        self.package = package
        self._events: Optional[List[Event]] = None
        self.bad_json_commits: List[str] = []

    def events(self) -> List[Event]:
        """从旧到新的版本变化事件（确定性：按日期+sha 排序）。"""
        if self._events is not None:
            return self._events
        events: List[Event] = []
        prev: Optional[str] = None
        for commit in log_history(self.repo, self.lockfile_path):
            content = show_file(self.repo, commit.sha, self.lockfile_path)
            if content is None:
                continue  # 该提交没有 lockfile（例如引入前）
            try:
                data = parse_lockfile_text(content)
            except LockfileError:
                self.bad_json_commits.append(commit.short)
                continue  # 历史版本坏 JSON，跳过该提交
            cur = resolved_version(data, self.package)
            if cur != prev:
                events.append(
                    Event(
                        date=commit.date,
                        sha=commit.sha,
                        from_version=prev,
                        to_version=cur,
                        author=commit.author,
                        message=commit.message,
                    )
                )
                prev = cur
        self._events = events
        return events

    def first_intro(self, version: str) -> Optional[Event]:
        """版本首次出现的提交（第一次 to == version）。"""
        for ev in self.events():
            if ev.to_version == version:
                return ev
        return None

    def diff(self, old: str, new: str) -> Optional[DiffResult]:
        """old → new 的切换：间隔时长与中间跳过的版本。

        语义：new 首次出现的位置之前、old 最后一次出现的位置之后，
        时间轴上经过的所有中间版本即为「跳过的版本」。
        """
        if old == new:
            return None
        events = self.events()
        if not events:
            return None
        end_index = -1
        end_event: Optional[Event] = None
        for idx, ev in enumerate(events):
            if ev.to_version == new:
                end_index = idx
                end_event = ev
                break
        if end_event is None:
            return None
        start_event: Optional[Event] = None
        start_index = -1
        for idx in range(end_index, -1, -1):
            if events[idx].to_version == old:
                start_index = idx
                start_event = events[idx]
                break
        if start_event is None:
            # old 恰好是引入前的状态（from_version == old），从时间轴起点算
            for idx in range(0, end_index + 1):
                if events[idx].from_version == old:
                    start_index = idx
                    start_event = events[idx]
                    break
        if start_event is None:
            return None
        skipped = [ev.to_version for ev in events[start_index + 1 : end_index]]
        return DiffResult(
            old=old,
            new=new,
            duration=end_event.date - start_event.date,
            start=start_event,
            end=end_event,
            skipped=skipped,
        )


def build_timeline(repo: str, lockfile_path: str, package: str) -> List[Event]:
    """兼容便捷函数，等价于 TimelineBuilder(...).events()。

    会抛出 GitError（git 不可用 / 非 git 仓库 / git log 失败）。
    """
    return TimelineBuilder(repo, lockfile_path, package).events()