"""blamewhen — npm 依赖漏洞时间轴归因工具。

给定一个 npm 依赖包名，回答「是谁、哪次提交把它引进来的」，
并输出该包在 package-lock.json 历史中的完整版本时间轴。

纯标准库实现，要求 Python >= 3.10。
"""

__version__ = "0.1.0"