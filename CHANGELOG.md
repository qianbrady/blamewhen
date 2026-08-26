# Changelog

本项目版本变动记录，格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2025-02-10

### 新增

- 三个子命令，全部只读、纯标准库（Python ≥ 3.10）：
  - `timeline <包名> [--path 仓库路径]`：重放 lockfile 的 git 历史，
    输出该包版本变化时间轴（日期|提交前7位|版本从→到|提交作者）；
  - `when <包名> <版本>`：定位某版本首次出现的提交
    （日期/作者/提交信息 + 同提交改动的其他文件）；
  - `diff <包名> <旧版本> <新版本>`：两个版本切换的间隔时长与中间跳过的版本。
- 支持 npm `package-lock.json` v1 / v2 / v3 三种格式（另识别 `npm-shrinkwrap.json`，
  二者并存时 `package-lock.json` 优先；支持子目录/monorepo 中的 lockfile）：
  - v1 读顶层 `dependencies`（含无 `lockfileVersion` 字段的老式 v1 探测）；
  - v2 / v3 读 `packages`，兼容 v2 同时携带 `dependencies` 键；
  - 多层 `node_modules` 嵌套时以最外层版本为解析结果。
- 健壮性：
  - `main()` 入口强制 stdout/stderr 以 UTF-8 输出（`errors="replace"`）；
  - 所有 git 子进程调用显式 `encoding="utf-8"` / `errors="replace"`；
  - 容忍 UTF-8 BOM 与 CRLF；历史坏 JSON 提交跳过、当前坏 JSON 明确报错；
  - 包不存在 / 无 lockfile / 坏 JSON / 非 git 仓库均给出友好中文提示。
- 确定性：输出顺序固定（按提交日期+sha 排序），日期一律 ISO 8601。
- 退出码约定：`0` 成功；`1` 数据/运行错误；`2` 用法错误。
- 测试（40 例）：v1/v2/v3 解析、嵌套多版本、BOM/CRLF、坏 JSON 与不存在分支、
  临时 git 仓端到端回放（含 npm-shrinkwrap.json 与子目录 lockfile、同日期按 sha
  决胜、diff 跳过「（移除）」、未知命令退出码）、确定性双跑、GBK 代码页子进程
  冒烟、用法错误；临时 git 仓库一律构建在 `.build-tmp/` 下，测试结束自动清理。
- CI：`.github/workflows/ci.yml`，ubuntu + windows × Python 3.10 / 3.12。