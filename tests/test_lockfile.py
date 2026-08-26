"""lockfile 三格式解析测试（纯字符串解析，无需 git）。"""

import unittest

from blamewhen.lockfile import (
    LockfileError,
    all_versions,
    lockfile_version,
    package_hits,
    parse_lockfile_text,
    resolved_version,
)

from common import LOCK_V1, LOCK_V1_LEGACY, LOCK_V2, LOCK_V2_NESTED, LOCK_V3


class LockfileFormatTests(unittest.TestCase):
    def test_v1_parse_basic(self):
        data = parse_lockfile_text(LOCK_V1)
        self.assertEqual(lockfile_version(data), 1)
        self.assertEqual(resolved_version(data, "lodash"), "4.17.21")
        self.assertEqual(resolved_version(data, "left-pad"), "1.3.0")

    def test_v1_legacy_without_lockfileversion(self):
        # 老式 v1 没有 lockfileVersion 字段，靠顶层 dependencies 探测
        data = parse_lockfile_text(LOCK_V1_LEGACY)
        self.assertEqual(lockfile_version(data), 1)
        self.assertEqual(resolved_version(data, "lodash"), "4.17.20")

    def test_v2_parse_basic(self):
        data = parse_lockfile_text(LOCK_V2)
        self.assertEqual(lockfile_version(data), 2)
        self.assertEqual(resolved_version(data, "lodash"), "4.17.21")
        self.assertEqual(resolved_version(data, "chalk"), "5.4.1")

    def test_v3_parse_basic(self):
        data = parse_lockfile_text(LOCK_V3)
        self.assertEqual(lockfile_version(data), 3)
        self.assertEqual(resolved_version(data, "left-pad"), "1.3.0")

    def test_nested_package_prefers_top_level(self):
        data = parse_lockfile_text(LOCK_V2_NESTED)
        # 顶层 node_modules/lodash 优先于嵌套拓扑
        self.assertEqual(resolved_version(data, "lodash"), "4.17.20")
        versions = all_versions(data, "lodash")
        self.assertEqual(versions, ["4.17.20", "4.17.19"])

    def test_v2_with_legacy_dependencies_still_uses_packages(self):
        # v2 文件同时含 packages 与 dependencies 键，必须走 packages
        data = parse_lockfile_text(LOCK_V2)
        hits = package_hits(data, "lodash")
        self.assertEqual(hits[0][1], "node_modules/lodash")

    def test_crlf_and_bom_tolerated(self):
        text = "\ufeff" + LOCK_V2.replace("\n", "\r\n")
        data = parse_lockfile_text(text)
        self.assertEqual(lockfile_version(data), 2)
        self.assertEqual(resolved_version(data, "lodash"), "4.17.21")

    def test_bad_json_raises_friendly(self):
        with self.assertRaises(LockfileError) as ctx:
            parse_lockfile_text('{"name": "demo", "version":')
        self.assertIn("JSON", str(ctx.exception))

    def test_top_level_not_object_raises(self):
        with self.assertRaises(LockfileError):
            parse_lockfile_text("[1, 2, 3]")

    def test_unknown_package_returns_none(self):
        data = parse_lockfile_text(LOCK_V2)
        self.assertIsNone(resolved_version(data, "never-installed"))
        self.assertEqual(all_versions(data, "never-installed"), [])

    def test_workspace_root_entry_ignored(self):
        data = parse_lockfile_text(LOCK_V2)
        self.assertIsNone(resolved_version(data, "demo"))
        self.assertIsNone(resolved_version(data, ""))


if __name__ == "__main__":
    unittest.main()