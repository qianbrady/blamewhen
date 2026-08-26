"""package-lock.json 解析器，兼容 npm lockfile v1 / v2 / v3。

纯标准库实现：
- 容忍 BOM / CRLF / 末尾换行差异
- v1：数据在顶层 ``dependencies``（无 ``lockfileVersion`` 字段）
- v2/v3：数据在 ``packages``（键形如 ``node_modules/<name>``，
  嵌套依赖形如 ``node_modules/a/node_modules/b``），
  ``packages[""]`` 为工作区根（忽略）
- 解析失败抛 :class:`LockfileError`，携带友好中文消息
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple


class LockfileError(Exception):
    """lockfile 无法解析（坏 JSON / 顶层不是对象）。"""


def parse_lockfile_text(text: str) -> Dict[str, Any]:
    """解析 package-lock.json 文本，返回原始 dict。

    容忍 UTF-8 BOM；内部换行符不敏感（json 模块原生容忍 CRLF）。
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LockfileError(
            "package-lock.json 不是合法 JSON：第 %d 行第 %d 列：%s"
            % (exc.lineno, exc.colno, exc.msg)
        ) from exc
    if not isinstance(data, dict):
        raise LockfileError("package-lock.json 顶层必须是 JSON 对象")
    return data


def lockfile_version(data: Dict[str, Any]) -> Optional[int]:
    """探测 lockfile 格式版本：1 / 2 / 3；未知返回 None。"""
    raw = data.get("lockfileVersion")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        v = int(raw)
        if v in (1, 2, 3):
            return v
        return None
    # v1 文件没有 lockfileVersion 字段，但有顶层 dependencies
    if isinstance(data.get("dependencies"), dict):
        return 1
    return None


def _package_key_matches(key: str, name: str) -> bool:
    """键是否指向包 ``name``（路径段级别的 node_modules/<name> 结尾）。"""
    if not key.startswith("node_modules/"):
        return False
    parts = key.split("/")
    return len(parts) >= 2 and parts[-2:] == ["node_modules", name]


def package_hits(
    data: Dict[str, Any], name: str
) -> List[Tuple[int, str, str]]:
    """返回该包在 lockfile 中的所有出现位置：

    ``(深度, 键, 版本)``，按 (深度, 键) 升序——顶层的
    ``node_modules/<name>``（深度 1）永远排在最前，同深度按键字典序，
    结果确定。
    """
    hits: List[Tuple[int, str, str]] = []
    ver = lockfile_version(data)
    if ver == 1:
        deps = data.get("dependencies")
        if isinstance(deps, dict):
            entry = deps.get(name)
            if isinstance(entry, dict):
                v = entry.get("version")
                if isinstance(v, str) and v:
                    hits.append((1, "dependencies/" + name, v))
        return hits
    pkgs = data.get("packages")
    if isinstance(pkgs, dict):
        for key in sorted(pkgs.keys()):
            if not _package_key_matches(key, name):
                continue
            entry = pkgs[key]
            if not isinstance(entry, dict):
                continue
            v = entry.get("version")
            if isinstance(v, str) and v:
                depth = key.count("node_modules/")
                hits.append((depth, key, v))
    hits.sort(key=lambda h: (h[0], h[1]))
    return hits


def resolved_version(data: Dict[str, Any], name: str) -> Optional[str]:
    """该项目解析到的版本：顶层 ``node_modules/<name>`` 优先，其次是
    最外层出现位置；包不存在返回 None。"""
    hits = package_hits(data, name)
    return hits[0][2] if hits else None


def all_versions(data: Dict[str, Any], name: str) -> List[str]:
    """该包在 lockfile 中出现的全部版本（去重、按出现顺序）。"""
    seen: List[str] = []
    for _depth, _key, version in package_hits(data, name):
        if version not in seen:
            seen.append(version)
    return seen