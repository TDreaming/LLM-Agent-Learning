"""统一 YAML 组件配置解析。

把一份 YAML（声明 agents / tools / mcp 三类组件的启停与参数）解析为强类型的
**配置快照**（不可变 dataclass）。职责分离：

- 本模块只负责「**装配与开关**」——有哪些组件、各自开/关、可选参数；
- 密钥与运行期敏感项（``MODEL_NAME`` / ``ARK_API_KEY`` / 数据目录等）仍由
  ``config.py`` + ``.env`` 负责，绝不进入本 YAML。

容错原则（优雅降级）：
- 单个条目缺 ``name`` 或类型非法 → 告警跳过该条目，不影响其余组件；
- 整个文件 YAML 语法错误/结构非法 → 抛出 :class:`ConfigError`，由调用方决定回退
  （热加载会保留上一份有效快照）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("devops_agent.component_config")

_DEFAULT_CONFIG_NAME = "agent_config.yaml"


class ConfigError(Exception):
    """配置文件无法解析（语法/结构非法）时抛出，供调用方回退到上一份有效快照。"""


@dataclass(frozen=True)
class ComponentSpec:
    """单个组件（agent / tool / mcp）的声明。"""

    name: str
    enabled: bool = False
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentConfigSnapshot:
    """一次有效配置的不可变快照。"""

    agents: tuple[ComponentSpec, ...] = ()
    tools: tuple[ComponentSpec, ...] = ()
    mcp: tuple[ComponentSpec, ...] = ()
    source: Optional[Path] = None

    def enabled_names(self, kind: str) -> list[str]:
        specs = getattr(self, kind)
        return [s.name for s in specs if s.enabled]


def default_config_path() -> Path:
    """解析默认配置路径：优先 ``DEVOPS_AGENT_CONFIG``，否则包内 agent_config.yaml。"""
    override = os.environ.get("DEVOPS_AGENT_CONFIG")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / _DEFAULT_CONFIG_NAME


def _parse_section(raw: Any, kind: str) -> tuple[ComponentSpec, ...]:
    """解析某一类组件列表；逐条目容错（缺 name/类型错误 → 告警跳过）。"""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        logger.warning("config section '%s' must be a list; ignoring.", kind)
        return ()

    specs: list[ComponentSpec] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            logger.warning("config[%s] entry is not a mapping: %r; skipped.", kind, item)
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            logger.warning("config[%s] entry missing valid 'name': %r; skipped.", kind, item)
            continue
        name = name.strip()
        if name in seen:
            logger.warning("config[%s] duplicate name '%s'; keeping the first.", kind, name)
            continue

        enabled = item.get("enabled", False)
        if not isinstance(enabled, bool):
            logger.warning(
                "config[%s].'%s'.enabled must be bool; got %r, treated as False.",
                kind, name, enabled,
            )
            enabled = False

        args = item.get("args", {})
        if not isinstance(args, dict):
            logger.warning(
                "config[%s].'%s'.args must be a mapping; got %r, treated as {}.",
                kind, name, args,
            )
            args = {}

        seen.add(name)
        specs.append(ComponentSpec(name=name, enabled=enabled, args=dict(args)))
    return tuple(specs)


def load_config(path: Optional[Path | str] = None) -> AgentConfigSnapshot:
    """读取并解析 YAML，返回不可变配置快照。

    Args:
        path: 配置文件路径；缺省时用 :func:`default_config_path`。

    Raises:
        ConfigError: 文件不存在、YAML 语法错误或顶层结构非法（非 mapping）。
    """
    cfg_path = Path(path) if path is not None else default_config_path()
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"cannot read config file {cfg_path}: {e}") from e

    try:
        import yaml

        data = yaml.safe_load(text)
    except Exception as e:  # noqa: BLE001 - 任意解析错误统一转为 ConfigError
        raise ConfigError(f"invalid YAML in {cfg_path}: {e}") from e

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be a mapping in {cfg_path}, got {type(data)}")

    snapshot = AgentConfigSnapshot(
        agents=_parse_section(data.get("agents"), "agents"),
        tools=_parse_section(data.get("tools"), "tools"),
        mcp=_parse_section(data.get("mcp"), "mcp"),
        source=cfg_path,
    )
    logger.info(
        "loaded config %s (agents=%d/%d tools=%d/%d mcp=%d/%d enabled/total)",
        cfg_path,
        len(snapshot.enabled_names("agents")), len(snapshot.agents),
        len(snapshot.enabled_names("tools")), len(snapshot.tools),
        len(snapshot.enabled_names("mcp")), len(snapshot.mcp),
    )
    return snapshot
