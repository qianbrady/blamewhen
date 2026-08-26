# blamewhen

> **Dependency timeline attribution for npm lockfiles** — answer *who introduced a vulnerable dependency version, and in which commit*, by replaying the history of `package-lock.json` in your git repo.

`blamewhen` 是一个纯标准库（Python ≥ 3.10）的 CLI 工具：给定一个 npm 依赖包名，它沿 git 历史逐提交解析 `package-lock.json`（兼容 npm **v1 / v2 / v3** 三种格式），回答「是谁、哪次提交把它引进来的」，并给出该包的完整版本变化时间轴。

它是**只读归因分析**：不上网、不扫描漏洞库、不改你的代码。它回答的不是「这个版本有没有漏洞」，而是「这个版本是何时、被谁、在哪一次提交里进入你仓库的」——这正是漏洞通报落地排查时最常缺的一环。

---

## 为什么需要它（vs Dependabot / Snyk）

[Dependabot-Core](https://github.com/dependabot/dependabot-core)(dependabot-core) 是 Dependabot 安全/版本更新机制的核心库：它检查依赖的最新可解析版本、为升级生成新的 manifest 与 lockfile、生成包含 changelog / release notes / commits 的 PR 描述。Snyk 则基于漏洞库扫描依赖树并给出修复建议。它们的共同点是**报告「有漏洞 / 有新版本」，并推动升级**；而当我们想追责排查「这个坏版本当初是怎么进来的」时，它们都帮不上忙。

| 维度 | Dependabot / Dependabot-Core | Snyk | **blamewhen** |
|---|---|---|---|
| 回答的问题 | 有新版本/有漏洞，帮你升级 | 有漏洞，给你修补建议 | **谁、哪次提交把这个版本引进来的** |
| 核心动作 | 检查最新可解析版本、生成更新 PR | 依赖树扫描 + 脆弱版本清单 | 重放 git 历史，输出版本变化时间轴 |
| 数据来源 | 在线 registry + 漏洞公告 | 漏洞数据库 | **纯本地**：git 历史 + `package-lock.json` |
| 对代码的副作用 | 修改 manifest/lockfile、开 PR | 集成 CI/CD、提交修复 | **零副作用**（只读） |
| 输出 | PR 描述（changelog、commits） | 告警清单 | 时间轴 / 引入提交 / 间隔与跳过版本 |

一句话：**它们报「有漏洞」，我们答「谁何时引入」**。

---

## 安装与运行

无需任何第三方依赖（纯标准库）：

```bash
# 方式一：直接以模块运行
python -m blamewhen timeline lodash --path /path/to/repo

# 方式二：pip 安装后使用全局命令（可选）
pip install -e .
blamewhen timeline lodash --path /path/to/repo
```

## 命令

### 1. `timeline <包名> [--path 仓库路径]`

重放 lockfile 的 git 历史，输出该包的版本变化序列（从旧到新）：

```
依赖包：lodash
时间轴文件：package-lock.json
日期|提交|版本变化|作者
2024-01-01T10:00:00+08:00|6810094|-→1.0.0|ox-alpha
2024-01-10T10:00:00+08:00|b07ba04|1.0.0→1.1.0|ox-alpha
2024-02-15T10:00:00+08:00|49afef5|1.1.0→1.2.0|ox-alpha
```

- 首行 `-→1.0.0`：该包被**首次引入**的提交（最重要的归因点）；
- `→-`：该版本在本次提交中被移除；
- 提交为该 7 位短哈希，日期为提交作者日期（ISO 8601），作者取自 commit author。

### 2. `when <包名> <版本>`

定位该版本**首次出现**的提交：日期、作者、提交信息，以及同提交改动的其他文件（常能顺藤摸瓜找到它是在哪次功能/升级里被带进来的）。

### 3. `diff <包名> <旧版本> <新版本>`

输出两个版本切换的**间隔时长**、首尾切换提交，以及**中间被跳过的版本**。

### 退出码

每个命令都支持 `--path 仓库路径`（默认当前目录）与全局 `--version` 旗标。

| 退出码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 数据/运行错误（路径不存在、非 git 仓库、无 lockfile、坏 JSON、包不存在、版本未出现） |
| `2` | 用法错误（未知命令、参数缺失） |

所有错误均有友好中文提示（写入 stderr）。

---

## 解析与行为说明

- **三格式支持**：v1 读顶层 `dependencies`；v2/v3 读 `packages`（兼容 v2 文件同时携带 `dependencies` 键的情况）；老式 v1（无 `lockfileVersion` 字段）按顶层 `dependencies` 自动探测。
- **多版本并存**：同包在多个 `node_modules/<a>/node_modules/<b>` 层级出现时，以**最外层（顶层 `node_modules/<pkg>` 优先）**作为解析版本；`all_versions` 可列全。
- **健壮性**：容忍 UTF-8 BOM 与 CRLF；历史中被损坏的 JSON 提交会被跳过而不中断时间轴,但**当前** lockfile 是坏 JSON 时会明确报错。
- **确定性**：事件按提交日期 + sha 排序，输出顺序固定，日期一律 ISO 8601，不依赖环境与 locale。
- **临时 git 仓库回放测试**均构建在 `.build-tmp/` 下，测试结束自动清理（Windows 下 git 生成的只读对象文件也会一并处理；启动时还会最佳努力清扫陈旧目录）。

## 开发与测试

```bash
python -m unittest discover -s tests -q
```

测试覆盖：v1/v2/v3 三格式解析、嵌套多版本、BOM/CRLF、坏 JSON 与不存在分支、临时 git 仓端到端回放、确定性双跑、GBK 代码页子进程冒烟、用法错误退出码。

CI（`.github/workflows/ci.yml`）：ubuntu + windows × Python 3.10 / 3.12。

## License

MIT © 2025 ox-alpha（见 [LICENSE](LICENSE)）。