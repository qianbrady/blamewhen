"""blamewhen 测试共享工具。

所有临时 git 仓库一律建在 ``D:\\earn money\\001\\.build-tmp\\`` 下
（铁律：临时文件只准放 .build-tmp），用完即删。
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # .../projects/blamewhen
BUILD_TMP = PROJECT_ROOT.parent.parent / ".build-tmp"  # D:\earn money\001\.build-tmp

BUILD_TMP.mkdir(parents=True, exist_ok=True)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_GIT_ENCODING = dict(encoding="utf-8", errors="replace")


def run_git(*args, cwd=None, env=None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=full_env,
        **_GIT_ENCODING,
    )


def _force_remove(func, path, _exc_info):
    """rmtree onerror 回调：先清只读位再重试（Windows git 对象文件是只读的）。"""
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    func(path)


class GitRepoFixture:
    """在 .build-tmp 下建临时 git 仓库并回放 lockfile 历史。

    用法：``with GitRepoFixture() as repo: ...``，退出时自动清理。
    """

    def __init__(self) -> None:
        # 路径不预创建：git init 以显式目标路径创建目录与仓库
        # （本环境沙箱不接受 mkdtemp 预留目录 + cwd 式 init）
        self.root = BUILD_TMP / ("blamewhen-test-" + uuid.uuid4().hex)
        self._git("init", "-b", "main", str(self.root), cwd=str(BUILD_TMP))
        self._git("config", "user.name", "ox-alpha")
        self._git("config", "user.email", "ox-alpha@example.com")
        self._git("config", "commit.gpgsign", "false")
        # 无条件关闭 autocrlf，防御 Linux/Windows 全局配置干扰内容断言
        self._git("config", "core.autocrlf", "false")

    def _git(self, *args, env=None, cwd=None) -> subprocess.CompletedProcess:
        proc = run_git(*args, cwd=cwd or str(self.root), env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                "git %s 失败: %s" % (" ".join(args), proc.stderr.strip())
            )
        return proc

    def write(self, rel: str, content: str) -> Path:
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
        return target

    def commit(self, message: str, when: str) -> None:
        self._git("add", "-A")
        env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        self._git("commit", "-m", message, env=env)

    def destroy(self) -> None:
        # git 在 Windows 上会把 .git/objects 内文件设为只读，
        # 直接 rmtree 会因 PermissionError 失败；先清只读位再删。
        shutil.rmtree(self.root, onerror=_force_remove)

    def __enter__(self) -> "GitRepoFixture":
        return self

    def __exit__(self, *exc) -> None:
        self.destroy()


def git_available() -> bool:
    return shutil.which("git") is not None


def _cleanup_stale_fixture_dirs() -> None:
    """启动时清扫历史遗留的 blamewhen-test-* 目录（最佳努力）。

    正常环境每次跑测试前清掉陈旧目录；个别目录访问被拒时静默跳过。
    """
    try:
        for d in BUILD_TMP.iterdir():
            if d.is_dir() and d.name.startswith("blamewhen-test-"):
                try:
                    shutil.rmtree(d, onerror=_force_remove)
                except Exception:
                    pass
    except Exception:
        pass


_cleanup_stale_fixture_dirs()


# ---- 标准 lockfile 样例（v1 / v2 / v3）----

LOCK_V1 = """{
  "name": "demo",
  "version": "1.0.0",
  "lockfileVersion": 1,
  "requires": true,
  "dependencies": {
    "lodash": {
      "version": "4.17.21",
      "resolved": "https://registry.npmjs.org/lodash/-/lodash-4.17.21.tgz",
      "integrity": "sha512-abc"
    },
    "left-pad": { "version": "1.3.0" }
  }
}
"""

LOCK_V1_LEGACY = """{
  "name": "demo",
  "version": "1.0.0",
  "requires": true,
  "dependencies": {
    "lodash": { "version": "4.17.20" }
  }
}
"""

LOCK_V2 = """{
  "name": "demo",
  "version": "1.0.0",
  "lockfileVersion": 2,
  "requires": true,
  "packages": {
    "": {
      "name": "demo",
      "version": "1.0.0",
      "dependencies": { "lodash": "^4.0.0", "chalk": "^5.0.0" }
    },
    "node_modules/lodash": {
      "version": "4.17.21",
      "resolved": "https://registry.npmjs.org/lodash/-/lodash-4.17.21.tgz",
      "integrity": "sha512-abc"
    },
    "node_modules/chalk": { "version": "5.4.1" }
  },
  "dependencies": {
    "lodash": { "version": "4.17.21" },
    "chalk": { "version": "5.4.1" }
  }
}
"""

LOCK_V2_NESTED = """{
  "name": "demo",
  "version": "1.0.0",
  "lockfileVersion": 2,
  "requires": true,
  "packages": {
    "": { "name": "demo", "version": "1.0.0" },
    "node_modules/lodash": { "version": "4.17.20" },
    "node_modules/foo": { "version": "1.0.0" },
    "node_modules/foo/node_modules/lodash": { "version": "4.17.19" }
  }
}
"""

LOCK_V3 = """{
  "name": "demo",
  "version": "1.0.0",
  "lockfileVersion": 3,
  "requires": true,
  "packages": {
    "": {
      "name": "demo",
      "version": "1.0.0",
      "dependencies": { "left-pad": "^1.3.0" }
    },
    "node_modules/left-pad": { "version": "1.3.0" }
  }
}
"""