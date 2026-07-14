"""可选的 MCP Tools 集成（filesystem MCP server）。

通过 ADK 的 ``McpToolset`` + ``StdioServerParameters`` 接入本地 filesystem MCP
server，使 Agent 具备读取本地文件/目录的能力（例如查阅本地 runbook、配置）。

设计为「可选 + 优雅降级」：
- 仅当配置开启时才尝试加载（统一 YAML 的 ``mcp[].enabled``，回退 ``DEVOPS_ENABLE_MCP``）；
- 若 ``mcp`` 依赖未安装或 ``npx`` 不可用，则记录告警并返回 ``None``，
  保证 Agent 在任何环境下都能正常启动（对齐 spec 的优雅降级要求）。

本模块以「按 name 的工厂」组织，供注册表装配与热加载启停复用。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from .config import settings

logger = logging.getLogger("devops_agent.mcp")


def build_filesystem_toolset(args: Optional[dict[str, Any]] = None) -> Optional[Any]:
    """构造单个 filesystem MCP toolset；不可用时返回 ``None``（优雅降级）。

    Args:
        args: 可选参数，支持 ``root_dir``（缺省取 ``settings.runbooks_dir``）。
    """
    args = args or {}

    # filesystem MCP server 需要 npx 运行。
    if shutil.which("npx") is None:
        logger.warning("`npx` not found; skipping MCP filesystem tools.")
        return None

    try:
        from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
        from mcp import StdioServerParameters
    except ImportError as e:  # noqa: BLE001
        logger.warning("MCP deps unavailable (%s); skipping MCP tools.", e)
        return None

    # 暴露给 MCP filesystem server 的根目录（默认 runbooks 目录，按需调整）。
    root_override = args.get("root_dir")
    root_dir = Path(root_override) if root_override else settings.runbooks_dir
    try:
        root_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:  # noqa: BLE001
        logger.warning("cannot prepare MCP root dir %s (%s); skipping.", root_dir, e)
        return None

    try:
        toolset = McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="npx",
                    args=[
                        "-y",
                        "@modelcontextprotocol/server-filesystem",
                        str(Path(root_dir).resolve()),
                    ],
                ),
                timeout=30,
            ),
        )
    except Exception as e:  # noqa: BLE001 - 加载失败不应阻断 Agent 启动
        logger.warning("failed to init MCP filesystem toolset (%s); skipping.", e)
        return None

    logger.info("MCP filesystem tools enabled (root=%s).", root_dir)
    return toolset


# name -> 工厂函数 的映射，供 registry / hot_reload 按 name 启停。
MCP_FACTORIES: dict[str, Any] = {
    "filesystem": build_filesystem_toolset,
}


def build_mcp_toolsets() -> list[Any]:
    """兼容入口：按当前配置快照构造已开启的 MCP toolset 列表。

    优先读取统一 YAML（``mcp[].enabled``）；当 YAML 未声明任何 MCP 条目时，
    回退到旧开关 ``settings.enable_mcp`` 以保持向后兼容。
    """
    from .component_config import ConfigError, load_config

    try:
        snapshot = load_config()
        mcp_specs = snapshot.mcp
    except ConfigError as e:  # noqa: BLE001
        logger.warning("config load failed (%s); fallback to env switch.", e)
        mcp_specs = ()

    toolsets: list[Any] = []
    if mcp_specs:
        for spec in mcp_specs:
            if not spec.enabled:
                continue
            factory = MCP_FACTORIES.get(spec.name)
            if factory is None:
                logger.warning("unknown MCP server '%s'; skipped.", spec.name)
                continue
            toolset = factory(spec.args)
            if toolset is not None:
                toolsets.append(toolset)
        return toolsets

    # 回退：无 YAML mcp 声明时沿用旧 env 开关。
    if not settings.enable_mcp:
        logger.info("MCP disabled (no YAML mcp config and DEVOPS_ENABLE_MCP unset).")
        return []
    toolset = build_filesystem_toolset()
    return [toolset] if toolset is not None else []
