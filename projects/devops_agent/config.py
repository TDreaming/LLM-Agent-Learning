"""配置加载模块。

集中管理模型配置、能力开关、安全预算与本地存储路径，统一从 `.env`/环境变量读取。
所有敏感值（如 API Key）仅用于运行时模型调用，严禁拼入 system prompt 或日志。

使用方式：
    from .config import get_model_name, settings
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 自动向上查找最近的 .env 文件并加载（不会覆盖已存在的同名变量）
load_dotenv()


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"环境变量 {key} 未设置，请在 projects/.env 中配置或导出到 shell")
    return value


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_model_name() -> str:
    """返回模型名称（如 ``volcengine/doubao-seed-1-6-251015``）。缺失时抛错。"""
    return _require_env("MODEL_NAME")


def require_model_credentials() -> None:
    """启动期校验：确保模型名与 API Key 均已配置，否则给出清晰报错。"""
    _require_env("MODEL_NAME")
    _require_env("ARK_API_KEY")


@dataclass(frozen=True)
class Settings:
    """运行期配置快照。"""

    # ---- 能力开关 ----
    enable_mcp: bool = field(default_factory=lambda: _env_bool("DEVOPS_ENABLE_MCP", False))
    require_approval: bool = field(
        default_factory=lambda: _env_bool("DEVOPS_REQUIRE_APPROVAL", True)
    )

    # ---- 安全预算 ----
    max_tool_calls: int = field(
        default_factory=lambda: _env_int("DEVOPS_MAX_TOOL_CALLS", 50)
    )
    # 上下文压缩：每 N 次用户输入触发一次（0 表示关闭，示例默认关闭）
    compaction_interval: int = field(
        default_factory=lambda: _env_int("DEVOPS_COMPACTION_INTERVAL", 0)
    )

    # ---- 后端适配器选择：mock（默认）/ 预留 prometheus/k8s ----
    provider_backend: str = field(
        default_factory=lambda: os.environ.get("DEVOPS_PROVIDER_BACKEND", "mock")
    )

    # ---- 本地存储路径 ----
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("DEVOPS_DATA_DIR", str(Path.cwd()))
        )
    )

    @property
    def memory_store_path(self) -> Path:
        return self.data_dir / ".devops_agent_memory.json"

    @property
    def audit_log_path(self) -> Path:
        return self.data_dir / ".devops_agent_audit.log"

    @property
    def runbooks_dir(self) -> Path:
        """预留：本地 runbook（markdown）知识目录，供 RAG 扩展使用。"""
        return self.data_dir / "runbooks"

    @property
    def skills_dir(self) -> Path:
        """用户自定义 Skill 目录：放入 `*.py` 即可被自动加载为工具。

        优先用 `DEVOPS_SKILLS_DIR` 覆盖；否则默认指向包内 `devops_agent/skills/`，
        保证示例自定义 Skill 开箱即可被发现（与运行 cwd 无关）。
        """
        custom = os.environ.get("DEVOPS_SKILLS_DIR")
        if custom:
            return Path(custom)
        return Path(__file__).resolve().parent / "skills"


# 全局配置单例
settings = Settings()
