"""环境变量加载模块。

通过 python-dotenv 从项目根目录或当前工作目录的 .env 文件加载配置，
统一对外暴露已校验的环境变量常量。

使用方式：
    from env import MODEL_NAME, ARK_API_KEY
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# 自动向上查找最近的 .env 文件并加载（不会覆盖已存在的同名变量）
load_dotenv()


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"环境变量 {key} 未设置，请在 .env 中配置或导出到 shell")
    return value


# 模型名称，例如：volcengine/doubao-seed-1-6-251015
MODEL_NAME: str = _require_env("MODEL_NAME")

# 火山方舟（volcengine provider）的 API Key
ARK_API_KEY: str = _require_env("ARK_API_KEY")
