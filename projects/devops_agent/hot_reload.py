"""配置动态热加载（运行期 <1s 感知 YAML 变更并就地更新 root_agent）。

实现要点：
- **轮询而非文件监听库**：daemon 线程每 ``poll_interval`` 秒（默认 0.5s，保证 <1s 感知）
  检查配置文件的 ``mtime + size``，变化时才重新解析，零额外第三方依赖；
- **就地更新**：通过对 ``root_agent.tools`` / ``root_agent.sub_agents`` 列表做
  **切片赋值**（``lst[:] = ...``）实现原地替换，``root_agent`` 仍是同一对象实例，
  ADK 运行期持有者无感；
- **MCP 按 name 差量启停**：仅对新增/移除的 MCP server 创建/关闭 toolset，避免无谓重启；
- **容错**：解析失败（``ConfigError``）保留上一份有效快照并告警，绝不破坏运行中的 Agent；
- **线程安全**：apply 过程加锁，避免与下一次轮询并发修改列表。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Optional

from google.adk import Agent

from . import registry
from .component_config import (
    AgentConfigSnapshot,
    ConfigError,
    default_config_path,
    load_config,
)
from .memory import MEMORY_TOOLS

logger = logging.getLogger("devops_agent.hot_reload")


def _file_signature(path: Path) -> Optional[tuple[float, int]]:
    """返回 (mtime, size) 作为变更指纹；文件不存在返回 None。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime, st.st_size)


class ConfigWatcher:
    """监听统一 YAML 配置文件并把变更就地应用到 ``root_agent``。"""

    def __init__(
        self,
        root_agent: Agent,
        *,
        path: Optional[Path] = None,
        poll_interval: float = 0.5,
        current: Optional[AgentConfigSnapshot] = None,
        mcp_active: Optional[dict[str, Any]] = None,
    ) -> None:
        self._root_agent = root_agent
        self._path = path or default_config_path()
        self._poll_interval = poll_interval
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # 已激活的 MCP toolset（name -> toolset），用于差量启停。
        # 初始装配已构造的 toolset 由 agent.py 透传进来，避免重复构造。
        self._mcp_active: dict[str, Any] = dict(mcp_active or {})
        # 上一份有效快照与文件指纹。
        self._snapshot = current or AgentConfigSnapshot()
        self._signature = _file_signature(self._path)

    # ---------------- 生命周期 ----------------

    def start(self) -> "ConfigWatcher":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._run, name="devops-config-watcher", daemon=True
        )
        self._thread.start()
        logger.info(
            "config watcher started (path=%s interval=%.2fs)",
            self._path, self._poll_interval,
        )
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ---------------- 轮询主循环 ----------------

    def _run(self) -> None:
        while not self._stop.wait(self._poll_interval):
            try:
                self.check_once()
            except Exception as e:  # noqa: BLE001 - 守护线程绝不因异常退出
                logger.warning("config watch iteration failed: %s", e)

    def check_once(self) -> bool:
        """检查一次文件指纹；有变更则重新加载并应用。返回是否发生了应用。"""
        sig = _file_signature(self._path)
        if sig == self._signature:
            return False
        self._signature = sig
        try:
            snapshot = load_config(self._path)
        except ConfigError as e:
            logger.warning("config reload skipped (invalid): %s; keeping last good.", e)
            return False
        self.apply(snapshot)
        return True

    # ---------------- 就地应用 ----------------

    def apply(self, snapshot: AgentConfigSnapshot) -> None:
        """把快照差量就地应用到 ``root_agent``（线程安全）。"""
        with self._lock:
            self._apply_mcp(snapshot)
            self._apply_tools(snapshot)
            self._apply_sub_agents(snapshot)
            self._snapshot = snapshot
        logger.info(
            "applied config: tools=%d sub_agents=%d mcp=%d",
            len(self._root_agent.tools),
            len(self._root_agent.sub_agents),
            len(self._mcp_active),
        )

    def _apply_mcp(self, snapshot: AgentConfigSnapshot) -> None:
        desired = {s.name: s for s in snapshot.mcp if s.enabled}

        # 移除：不再开启的 MCP。
        for name in list(self._mcp_active):
            if name not in desired:
                toolset = self._mcp_active.pop(name)
                _close_toolset(toolset)
                logger.info("MCP '%s' disabled; toolset removed.", name)

        # 新增：开启但尚未激活的 MCP。
        for name, spec in desired.items():
            if name in self._mcp_active:
                continue
            factory = registry.MCP_FACTORIES.get(name)
            if factory is None:
                logger.warning("unknown MCP server '%s' in config; skipped.", name)
                continue
            toolset = factory(spec.args)
            if toolset is None:
                logger.warning("MCP '%s' enable failed (graceful degrade); skipped.", name)
                continue
            self._mcp_active[name] = toolset
            logger.info("MCP '%s' enabled; toolset added.", name)

    def _apply_tools(self, snapshot: AgentConfigSnapshot) -> None:
        # 重新组装工具列表：记忆工具（核心）+ 配置工具 + 已激活 MCP toolset。
        managed = registry.build_tools(snapshot)
        active_mcp = list(self._mcp_active.values())
        new_tools = [*MEMORY_TOOLS, *managed, *active_mcp]
        # 切片赋值：保持 root_agent.tools 列表对象不变，仅替换内容。
        self._root_agent.tools[:] = new_tools

    def _apply_sub_agents(self, snapshot: AgentConfigSnapshot) -> None:
        desired = registry.build_sub_agents(snapshot)
        for agent in desired:
            # 首次纳入时确保 parent 指向 root（ADK 构造期只对初始 sub_agents 设置过）。
            if agent.parent_agent is None:
                agent.parent_agent = self._root_agent
        self._root_agent.sub_agents[:] = desired


def _close_toolset(toolset: Any) -> None:
    """尽力关闭 MCP toolset（若提供了关闭接口）；失败仅告警。"""
    for attr in ("close", "aclose"):
        fn = getattr(toolset, attr, None)
        if fn is None:
            continue
        try:
            result = fn()
            # 异步关闭接口无法在同步线程优雅 await，忽略其协程（守护线程退出即随进程回收）。
            if hasattr(result, "__await__"):
                logger.debug("toolset.%s is async; skipped awaiting in watcher.", attr)
            return
        except Exception as e:  # noqa: BLE001
            logger.warning("failed to close MCP toolset (%s): %s", attr, e)
            return


def start_config_watcher(
    root_agent: Agent,
    *,
    path: Optional[Path] = None,
    poll_interval: float = 0.5,
    current: Optional[AgentConfigSnapshot] = None,
    mcp_active: Optional[dict[str, Any]] = None,
) -> ConfigWatcher:
    """便捷入口：创建并启动配置监听器。"""
    return ConfigWatcher(
        root_agent,
        path=path,
        poll_interval=poll_interval,
        current=current,
        mcp_active=mcp_active,
    ).start()
