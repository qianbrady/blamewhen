"""CLI 端到端测试：在 .build-tmp 的临时 git 仓库上回放 lockfile 历史。

覆盖：时间轴/定位/差异三大命令、包不存在/无 lockfile/坏 JSON/非 git 仓
分支、确定性双跑、GBK 代码页子进程冒烟、用法错误退出码。
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime
from pathlib import Path

from common import (
    BUILD_TMP,
    PROJECT_ROOT,
    GitRepoFixture,
    LOCK_V1,
    LOCK_V2,
    LOCK_V3,
    git_available,
)

from blamewhen.cli import main

DATE_1 = "2024-01-01T10:00:00+08:00"
DATE_2 = "2024-01-10T10:00:00+08:00"
DATE_3 = "2024-02-15T10:00:00+08:00"


def run_cli(*argv):
    """直接调用 main(argv)，返回 (exit_code, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def build_replay_repo():
    """回放历史：commit1 引入 lodash 1.0.0（v1），commit2 升 1.1.0（v2），
    commit3 升 1.2.0（v3）。固定时间戳与作者。"""
    repo = GitRepoFixture()
    lock1 = LOCK_V1.replace('"version": "4.17.21"', '"version": "1.0.0"')
    lock1 = lock1.replace("sha512-abc", "sha512-one")
    repo.write("package-lock.json", lock1)
    repo.write("package.json", '{"name": "demo", "dependencies": {"lodash": "^1.0.0"}}')
    repo.commit("feat: init demo app", DATE_1)

    lock2 = LOCK_V2.replace('"version": "4.17.21"', '"version": "1.1.0"')
    lock2 = lock2.replace("sha512-abc", "sha512-one").replace(
        '"version": "5.4.1"', '"version": "5.0.0"'
    )
    repo.write("package-lock.json", lock2)
    repo.write(
        "package.json",
        '{"name": "demo", "dependencies": {"lodash": "^1.1.0", "chalk": "^5.0.0"}}',
    )
    repo.commit("feat: upgrade lodash and add chalk", DATE_2)

    lock3 = LOCK_V3.replace('"version": "1.3.0"', '"version": "1.2.0"')
    lock3 = lock3.replace("left-pad", "lodash").replace(
        "sha512-abc", "sha512-one"
    )
    repo.write("package-lock.json", lock3)
    repo.write("package.json", '{"name": "demo", "dependencies": {"lodash": "^1.2.0"}}')
    repo.commit("fix: bump lodash to 1.2.0", DATE_3)
    return repo


@unittest.skipUnless(git_available(), "需要 git 可执行文件")
class TimelineTests(unittest.TestCase):
    def test_timeline_basic_replay(self):
        with build_replay_repo() as repo:
            code, out, err = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        lines = [ln for ln in out.splitlines() if "|" in ln]
        self.assertEqual(len(lines), 4)  # 表头 + 3 次版本变化
        self.assertTrue(lines[0].startswith("日期|提交|版本变化|作者"))
        self.assertTrue(lines[1].endswith("|-→1.0.0|ox-alpha"))
        self.assertTrue(lines[2].endswith("|1.0.0→1.1.0|ox-alpha"))
        self.assertTrue(lines[3].endswith("|1.1.0→1.2.0|ox-alpha"))

    def test_timeline_fields_deterministic_format(self):
        with build_replay_repo() as repo:
            code, out, _ = run_cli("timeline", "lodash", "--path", str(repo.root))
        rows = [ln for ln in out.splitlines() if "|" in ln and "日期|" not in ln]
        for row in rows:
            parts = row.split("|")
            self.assertEqual(len(parts), 4, row)
            # 日期可解析为 ISO 时间
            datetime.fromisoformat(parts[0])
            self.assertEqual(len(parts[1]), 7)  # 提交前 7 位

    def test_timeline_subcommand_offset_by_git_author_is_used(self):
        # 作者直接取自 commit author；日期为 author date
        with build_replay_repo() as repo:
            code, out, err = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        self.assertIn("2024-01-01T10:00:00+08:00", out)

    def test_timeline_no_version_change_yields_single_intro_event(self):
        with GitRepoFixture() as repo:
            repo.write("package-lock.json", LOCK_V1)
            repo.commit("feat: init", DATE_1)
            lock2 = LOCK_V1.replace("left-pad", "left-pad2")  # 别的包变化
            repo.write("package-lock.json", lock2)
            repo.commit("chore: unrelated change", DATE_2)
            code, out, err = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        rows = [ln for ln in out.splitlines() if "|" in ln and "日期|" not in ln]
        self.assertEqual(len(rows), 1)
        self.assertIn("-→4.17.21", rows[0])

    def test_timeline_bad_json_in_history_is_skipped(self):
        with GitRepoFixture() as repo:
            repo.write("package-lock.json", LOCK_V1)
            repo.commit("feat: init", DATE_1)
            repo.write("package-lock.json", '{"name": "broken",')
            repo.commit("bad json commit", DATE_2)
            lock3 = LOCK_V2.replace("4.17.21", "4.17.22").replace(
                '"version": "5.4.1"', '"version": "5.0.0"'
            )
            repo.write("package-lock.json", lock3)
            repo.commit("fix: restore lockfile", DATE_3)
            code, out, err = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        rows = [ln for ln in out.splitlines() if "|" in ln and "日期|" not in ln]
        # 坏 JSON 的提交被跳过：事件只有引入 4.17.21 与 4.17.21→4.17.22
        self.assertEqual(len(rows), 2)
        self.assertIn("-→4.17.21", rows[0])
        self.assertIn("4.17.21→4.17.22", rows[1])

    def test_timeline_package_removed_shows_dash(self):
        with GitRepoFixture() as repo:
            repo.write("package-lock.json", LOCK_V1)
            repo.commit("feat: init", DATE_1)
            repo.write("package-lock.json", LOCK_V3)  # lodash 不在 v3 样例中
            repo.commit("fix: drop lodash", DATE_2)
            code, out, err = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        rows = [ln for ln in out.splitlines() if "|" in ln and "日期|" not in ln]
        self.assertEqual(len(rows), 2)
        self.assertIn("-→4.17.21", rows[0])
        self.assertIn("4.17.21→-", rows[1])

    def test_timeline_unknown_package_friendly_exit1(self):
        with build_replay_repo() as repo:
            code, out, err = run_cli(
                "timeline", "never-installed", "--path", str(repo.root)
            )
        self.assertEqual(code, 1)
        self.assertIn("never-installed", err)
        self.assertIn("未出现", err)

    def test_timeline_missing_path_exit1(self):
        with build_replay_repo() as repo:
            code, _, err = run_cli(
                "timeline", "lodash", "--path", str(repo.root / "nope")
            )
        self.assertEqual(code, 1)
        self.assertIn("路径不存在", err)


@unittest.skipUnless(git_available(), "需要 git 可执行文件")
class WhenTests(unittest.TestCase):
    def test_when_first_intro_with_other_files(self):
        with build_replay_repo() as repo:
            code, out, err = run_cli(
                "when", "lodash", "1.1.0", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        self.assertIn("版本：1.1.0", out)
        self.assertIn("首次出现提交：", out)
        self.assertIn("作者：ox-alpha", out)
        self.assertIn("提交信息：feat: upgrade lodash and add chalk", out)
        self.assertIn("- package.json", out)  # 同提交改动的其他文件
        self.assertIn("2024-01-10T10:00:00+08:00", out)

    def test_when_intro_version(self):
        with build_replay_repo() as repo:
            code, out, _ = run_cli(
                "when", "lodash", "1.0.0", "--path", str(repo.root)
            )
        self.assertEqual(code, 0)
        self.assertIn("feat: init demo app", out)

    def test_when_version_missing_exit1(self):
        with build_replay_repo() as repo:
            code, _, err = run_cli(
                "when", "lodash", "9.9.9", "--path", str(repo.root)
            )
        self.assertEqual(code, 1)
        self.assertIn("9.9.9", err)
        self.assertIn("未出现", err)


@unittest.skipUnless(git_available(), "需要 git 可执行文件")
class DiffTests(unittest.TestCase):
    def test_diff_interval_and_skipped_versions(self):
        with build_replay_repo() as repo:
            code, out, err = run_cli(
                "diff", "lodash", "1.0.0", "1.2.0", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        self.assertIn("版本：1.0.0 → 1.2.0", out)
        self.assertIn("间隔时长：45 天 0 小时", out)
        self.assertIn("中间跳过的版本：1.1.0", out)

    def test_diff_adjacent_versions_no_skipped(self):
        with build_replay_repo() as repo:
            code, out, _ = run_cli(
                "diff", "lodash", "1.1.0", "1.2.0", "--path", str(repo.root)
            )
        self.assertEqual(code, 0)
        self.assertIn("中间跳过的版本：（无）", out)

    def test_diff_old_new_same_exit1(self):
        with build_replay_repo() as repo:
            code, _, err = run_cli(
                "diff", "lodash", "1.1.0", "1.1.0", "--path", str(repo.root)
            )
        self.assertEqual(code, 1)
        self.assertIn("相同", err)

    def test_diff_new_version_missing_exit1(self):
        with build_replay_repo() as repo:
            code, _, err = run_cli(
                "diff", "lodash", "1.0.0", "9.9.9", "--path", str(repo.root)
            )
        self.assertEqual(code, 1)
        self.assertIn("9.9.9", err)

    def test_diff_old_version_missing_exit1(self):
        with build_replay_repo() as repo:
            code, _, err = run_cli(
                "diff", "lodash", "0.0.1", "1.2.0", "--path", str(repo.root)
            )
        self.assertEqual(code, 1)
        self.assertIn("无法定位", err)


@unittest.skipUnless(git_available(), "需要 git 可执行文件")
class ErrorBranchTests(unittest.TestCase):
    def test_no_lockfile_friendly_exit1(self):
        with GitRepoFixture() as repo:
            repo.write("README.md", "# demo\n")
            repo.commit("chore: init", DATE_1)
            code, _, err = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
        self.assertEqual(code, 1)
        self.assertIn("未找到 package-lock.json", err)

    def test_bad_json_current_lockfile_friendly_exit1(self):
        with GitRepoFixture() as repo:
            repo.write("package-lock.json", '{"name": "broken",')
            repo.commit("feat: init", DATE_1)
            code, _, err = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
        self.assertEqual(code, 1)
        self.assertIn("不是合法 JSON", err)

    def test_non_git_path_friendly_exit1(self):
        tmp = Path(tempfile.mkdtemp(prefix="blamewhen-nogit-", dir=str(BUILD_TMP)))
        try:
            # 本工作区根目录本身是 git 仓库：用 GIT_CEILING_DIRECTORIES
            # 阻止 git 向上搜索，使 .build-tmp 下的临时目录视为非仓库
            ceiling = str(BUILD_TMP).replace("\\", "/")
            with unittest.mock.patch.dict(
                os.environ, {"GIT_CEILING_DIRECTORIES": ceiling}
            ):
                code, _, err = run_cli("timeline", "lodash", "--path", str(tmp))
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(code, 1)
        self.assertIn("git 仓库", err)

    def test_determinism_double_run(self):
        with build_replay_repo() as repo:
            code1, out1, err1 = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
            code2, out2, err2 = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
        self.assertEqual(code1, 0)
        self.assertEqual(code2, 0)
        self.assertEqual(out1, out2)
        self.assertEqual(err1, err2)
        self.assertGreater(len(out1), 0)

    def test_gbk_subprocess_smoke(self):
        """在 GBK 代码页环境下以子进程运行 CLI：不崩溃、无 Traceback、
        UTF-8 输出正常。"""
        with build_replay_repo() as repo:
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "gbk"
            proc = subprocess.run(
                [sys.executable, "-m", "blamewhen", "timeline", "lodash",
                 "--path", str(repo.root)],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=120,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("依赖包：lodash", proc.stdout)

    def test_usage_error_exit2(self):
        proc = subprocess.run(
            [sys.executable, "-m", "blamewhen"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_version_flag_exit0(self):
        proc = subprocess.run(
            [sys.executable, "-m", "blamewhen", "--version"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("blamewhen 0.1.0", proc.stdout)

    def test_when_and_timeline_report_exit0(self):
        with build_replay_repo() as repo:
            code, out, err = run_cli(
                "when", "lodash", "1.2.0", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        self.assertIn("提交信息：fix: bump lodash to 1.2.0", out)


@unittest.skipUnless(git_available(), "需要 git 可执行文件")
class AdditionalCoverageTests(unittest.TestCase):
    def test_shrinkwrap_only_and_package_lock_priority(self):
        # 只有 npm-shrinkwrap.json 时使用它
        with GitRepoFixture() as repo:
            repo.write("npm-shrinkwrap.json", LOCK_V1)
            repo.commit("chore: init", DATE_1)
            code, out, err = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        self.assertIn("npm-shrinkwrap.json", out)
        # 二者并存时 package-lock.json 优先
        with GitRepoFixture() as repo:
            repo.write("package-lock.json", LOCK_V1)
            repo.write(
                "npm-shrinkwrap.json", LOCK_V1.replace("4.17.21", "9.9.9")
            )
            repo.commit("chore: init", DATE_1)
            code, out, err = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        self.assertIn("package-lock.json", out)
        self.assertNotIn("9.9.9", out)

    def test_subdirectory_lockfile_monorepo(self):
        with GitRepoFixture() as repo:
            repo.write("apps/web/package-lock.json", LOCK_V2)
            repo.commit("chore: init", DATE_1)
            code, out, err = run_cli(
                "timeline", "lodash", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        self.assertIn("apps/web/package-lock.json", out)
        self.assertIn("-→4.17.21", out)

    def test_diff_removed_between_versions_shows_removed(self):
        with GitRepoFixture() as repo:
            repo.write(
                "package-lock.json", LOCK_V1.replace("4.17.21", "1.0.0")
            )
            repo.commit("chore: init", DATE_1)
            repo.write("package-lock.json", LOCK_V3)  # 不含 lodash → 移除
            repo.commit("chore: drop lodash", DATE_2)
            repo.write(
                "package-lock.json", LOCK_V2.replace("4.17.21", "1.2.0")
            )
            repo.commit("chore: restore lodash 1.2.0", DATE_3)
            code, out, err = run_cli(
                "diff", "lodash", "1.0.0", "1.2.0", "--path", str(repo.root)
            )
        self.assertEqual(code, 0, err)
        self.assertIn("中间跳过的版本：（移除）", out)

    def test_same_date_commits_sorted_by_sha(self):
        import blamewhen.gitrepo as G

        with GitRepoFixture() as repo:
            repo.write("package-lock.json", LOCK_V1)
            repo.commit("feat: a", "2024-03-01T10:00:00+08:00")
            repo.write("package-lock.json", LOCK_V2)
            repo.commit("feat: b", "2024-03-01T10:00:00+08:00")
            commits = G.log_history(str(repo.root), "package-lock.json")
        shas = [c.sha for c in commits]
        self.assertEqual(len(shas), 2)
        self.assertEqual(shas, sorted(shas))  # 同日期按 sha 决胜，保证确定性

    def test_unknown_subcommand_exit2(self):
        proc = subprocess.run(
            [sys.executable, "-m", "blamewhen", "frobnicate"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()