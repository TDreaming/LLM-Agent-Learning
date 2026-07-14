"""Supervisor 根 Agent 入口。

定义 ``root_agent``：协调三个专家 SubAgent（诊断/处置/沟通），并装配记忆工具、
可选 MCP 工具与全局护栏回调。组件装配由**统一 YAML 配置 + 注册表**驱动（仅初始化
开启项），并在运行期通过热加载监听器在 1 秒内感知配置变更、就地更新到运行中的
``root_agent``（保持对象引用不变）。同时暴露：
- ``root_agent``：被 ``adk run / adk web`` 加载（兼容既有方式）；
- ``app``：``App`` 实例，注册全局可观测 Plugin 与（可选）上下文压缩；ADK 加载时会
  **优先识别模块级 ``app``**，从而对所有 Agent/工具统一可观测；
- ``memory_service``：被 ADK 通过同名模块级变量约定注入到 Runner。
"""

from __future__ import annotations

import logging
import os

from google.adk import Agent
from google.adk.apps.app import App
from google.adk.models.lite_llm import LiteLlm

from . import registry
from .component_config import ConfigError, load_config
from .config import get_model_name, require_model_credentials, settings
from .custom_skills import skills_catalog
from .guardrails import before_tool_guardrail
from .memory import MEMORY_TOOLS, memory_service
from .observability import observability_plugin
from .prompts import DELEGATION_GUIDE, common_preamble
from .subagents import SUB_AGENTS

logger = logging.getLogger("devops_agent.agent")

# 启动期校验必要凭据，缺失时给出清晰报错。
require_model_credentials()


def _initial_snapshot():
    """加载初始配置快照；非法时回退到「全部内置组件开启」的安全缺省。"""
    try:
        return load_config()
    except ConfigError as e:
        logger.warning("initial config load failed (%s); using built-in defaults.", e)
        from .component_config import AgentConfigSnapshot, ComponentSpec

        return AgentConfigSnapshot(
            agents=tuple(ComponentSpec(a.name, True) for a in SUB_AGENTS),
            tools=(ComponentSpec("load_skill", True),),
            mcp=(),
        )


def _build_root_agent(snapshot, mcp_map: dict) -> Agent:
    # 工具 = 记忆工具（核心，始终挂载）+ 配置开启的内置工具 + 配置开启的 MCP toolset。
    tools = [
        *MEMORY_TOOLS,
        *registry.build_tools(snapshot),
        *mcp_map.values(),
    ]
    sub_agents = registry.build_sub_agents(snapshot)

    # 把用户自定义 Skill 的「能力目录」（仅 name+description）注入 instruction。
    catalog = skills_catalog()
    catalog_block = f"\n\n{catalog}" if catalog else ""

    return Agent(
        model=LiteLlm(model=get_model_name()),
        name="devops_supervisor",
        description=(
            "DevOps 智能运维 Supervisor：理解用户运维意图，路由/委派给诊断、处置、"
            "沟通三个专家 SubAgent，并保障安全护栏与记忆。"
        ),
        instruction=(
            common_preamble()
            + "\n\n你是 DevOps 智能运维总协调（Supervisor）。"
            + "\n你不直接执行运维动作，而是理解用户意图并委派给合适的专家子代理。"
            + "\n\n" + DELEGATION_GUIDE
            + "\n\n善用记忆：必要时回忆历史排查/处置结论，保持跨会话上下文一致。"
            + "\n对涉及生产变更的请求，提醒用户相关写操作需经人工审批。"
            + catalog_block
        ),
        sub_agents=sub_agents,
        tools=tools,
        before_tool_callback=before_tool_guardrail,
    )


def _build_app(agent: Agent) -> App:
    """构造 App：注册全局可观测 Plugin，并按配置开启上下文压缩（防爆 token）。"""
    compaction_config = None
    if settings.compaction_interval > 0:
        # ADK 原生上下文压缩（kagent context compaction 的等价物）。
        from google.adk.apps._configs import EventsCompactionConfig

        compaction_config = EventsCompactionConfig(
            compaction_interval=settings.compaction_interval,
            overlap_size=2,
        )
    return App(
        name="devops_agent",
        root_agent=agent,
        plugins=[observability_plugin],
        events_compaction_config=compaction_config,
    )


def _hot_reload_enabled() -> bool:
    raw = os.environ.get("DEVOPS_CONFIG_HOT_RELOAD")
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


_snapshot = _initial_snapshot()
_mcp_map = registry.build_mcp_map(_snapshot)
root_agent = _build_root_agent(_snapshot, _mcp_map)
app = _build_app(root_agent)

# 启动配置热加载监听器：运行期修改 YAML 后 <1s 就地更新 root_agent。
if _hot_reload_enabled():
    from .hot_reload import start_config_watcher

    config_watcher = start_config_watcher(
        root_agent, current=_snapshot, mcp_active=_mcp_map
    )

# 暴露给 ADK CLI / Runner：
# - `app`：携带全局可观测 Plugin 与上下文压缩，ADK 加载时优先识别；
# - `root_agent`：兼容仅按 root_agent 加载的方式；
# - `memory_service`：通过模块级同名变量约定自动注入。
__all__ = ["app", "root_agent", "memory_service"]
