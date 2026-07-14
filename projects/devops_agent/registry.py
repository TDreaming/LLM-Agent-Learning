"""组件注册表（Registry）。

把内置的 **tools / sub-agents / MCP 工厂** 按 name 集中登记，并提供「按配置快照装配」
的工厂函数。装配规则：

- 只实例化 ``enabled: true`` 且**已登记**的组件；
- 配置里出现未登记的 name → 告警跳过（优雅降级），不阻断装配。

供 ``agent.py`` 初次装配与 ``hot_reload.py`` 运行期增删共同复用，确保两者一致。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from google.adk import Agent

from . import skills, subagents
from .component_config import AgentConfigSnapshot
from .custom_skills import has_custom_skills, load_skill
from .mcp_tools import MCP_FACTORIES

logger = logging.getLogger("devops_agent.registry")


# ---------------- 工具注册表（Supervisor 自身可挂载的内置工具） ----------------
# name -> 返回该工具对象的构造器（惰性，便于按需生成/校验）。

def _build_load_skill() -> Any | None:
    # 仅当存在用户自定义 Skill 时，load_skill 才有意义。
    if not has_custom_skills():
        logger.info("no custom skills found; 'load_skill' tool skipped.")
        return None
    return load_skill


TOOL_REGISTRY: dict[str, Callable[[], Any | None]] = {
    "load_skill": _build_load_skill,
    "get_current_time": lambda: skills.get_current_time,
}


# ---------------- 子代理注册表 ----------------
# name -> 内置 Agent 单例。
SUB_AGENT_REGISTRY: dict[str, Agent] = {
    agent.name: agent for agent in subagents.SUB_AGENTS
}


# ---------------- MCP 工厂注册表 ----------------
# 复用 mcp_tools 的 name -> 工厂映射（工厂接收 args，返回 toolset 或 None）。


def build_tools(snapshot: AgentConfigSnapshot) -> list[Any]:
    """按快照装配 Supervisor 工具（仅 enabled 且已登记的项）。"""
    tools: list[Any] = []
    for spec in snapshot.tools:
        if not spec.enabled:
            continue
        builder = TOOL_REGISTRY.get(spec.name)
        if builder is None:
            logger.warning("unknown tool '%s' in config; skipped.", spec.name)
            continue
        obj = builder()
        if obj is not None:
            tools.append(obj)
    return tools


def build_sub_agents(snapshot: AgentConfigSnapshot) -> list[Agent]:
    """按快照装配子代理（仅 enabled 且已登记的项），返回内置单例实例。"""
    agents: list[Agent] = []
    for spec in snapshot.agents:
        if not spec.enabled:
            continue
        agent = SUB_AGENT_REGISTRY.get(spec.name)
        if agent is None:
            logger.warning("unknown sub-agent '%s' in config; skipped.", spec.name)
            continue
        agents.append(agent)
    return agents


def build_mcp_map(snapshot: AgentConfigSnapshot) -> dict[str, Any]:
    """按快照装配 MCP toolset，返回 ``{name: toolset}``（仅成功构造的 enabled 项）。"""
    result: dict[str, Any] = {}
    for spec in snapshot.mcp:
        if not spec.enabled:
            continue
        factory = MCP_FACTORIES.get(spec.name)
        if factory is None:
            logger.warning("unknown MCP server '%s' in config; skipped.", spec.name)
            continue
        toolset = factory(spec.args)
        if toolset is not None:
            result[spec.name] = toolset
    return result


def build_mcp_toolsets(snapshot: AgentConfigSnapshot) -> list[Any]:
    """按快照装配 MCP toolset 列表（仅 enabled 且已登记的项，含优雅降级）。"""
    return list(build_mcp_map(snapshot).values())
