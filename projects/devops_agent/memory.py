"""记忆管理：本地 JSON 文件持久化的 MemoryService + 记忆工具。

继承 ADK 的 ``InMemoryMemoryService``，把内存事件落到本地 JSON 文件，启动时读回，
保证 ``adk run / adk web / cli`` 重启后跨会话记忆不丢失（对齐仓库已有的
``base_workflow_agent.local_memory`` 经验）。

对外提供：
- ``memory_service``：模块级单例，供 ADK Runner 注入；
- ``MEMORY_TOOLS``：``preload_memory_tool`` + ``load_memory_tool``（提供 prefetch/load 语义）；

扩展点（对齐 kagent）：
- 语义检索：可换成向量库（VikingDB 等）实现 ``search_memory``；
- runbook RAG：可从 ``settings.runbooks_dir`` 或 Git 加载 markdown 知识；
- 周期性记忆抽取：可在每 N 条用户消息后抽取关键信息后再 ``add_session_to_memory``。
本示例保持本地 JSON + 关键词检索，零外部依赖。
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.tools.load_memory_tool import load_memory_tool
from google.adk.tools.preload_memory_tool import preload_memory_tool

from .config import settings

if TYPE_CHECKING:
    from google.adk.events.event import Event
    from google.adk.sessions.session import Session

logger = logging.getLogger("devops_agent.memory")


class LocalFileMemoryService(InMemoryMemoryService):
    """JSON 文件持久化的 MemoryService（开发/原型用；生产可换 RAG/向量库）。"""

    def __init__(self, store_path: str | Path | None = None) -> None:
        super().__init__()
        self._store_path: Path = (
            Path(store_path) if store_path else settings.memory_store_path
        )
        self._io_lock = threading.Lock()
        self._load()

    # ---------- override：写操作后落盘 ----------

    async def add_session_to_memory(self, session: "Session") -> None:
        await super().add_session_to_memory(session)
        self._dump()

    async def add_events_to_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        events: Sequence["Event"],
        session_id: str | None = None,
        custom_metadata: Mapping[str, object] | None = None,
    ) -> None:
        await super().add_events_to_memory(
            app_name=app_name,
            user_id=user_id,
            events=events,
            session_id=session_id,
            custom_metadata=custom_metadata,
        )
        self._dump()

    # ---------- 持久化 ----------

    def _dump(self) -> None:
        with self._io_lock, self._lock:
            payload: dict[str, dict[str, list[dict]]] = {}
            for user_key, sessions in self._session_events.items():
                payload[user_key] = {
                    sid: [ev.model_dump(mode="json", exclude_none=True) for ev in evs]
                    for sid, evs in sessions.items()
                }
            tmp = self._store_path.with_suffix(self._store_path.suffix + ".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            tmp.replace(self._store_path)
            logger.debug("memory dumped to %s", self._store_path)

    def _load(self) -> None:
        from google.adk.events.event import Event  # 延迟导入避免循环

        if not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text() or "{}")
        except json.JSONDecodeError:
            logger.warning("local memory file %s is invalid JSON, ignored", self._store_path)
            return

        with self._lock:
            for user_key, sessions in data.items():
                self._session_events[user_key] = {}
                for sid, evs in sessions.items():
                    restored: list[Event] = []
                    for ev_dict in evs:
                        try:
                            restored.append(Event.model_validate(ev_dict))
                        except Exception as e:  # noqa: BLE001
                            logger.warning("skip invalid event in memory: %s", e)
                    self._session_events[user_key][sid] = restored
        logger.info("memory loaded from %s", self._store_path)


# 全局单例，供 agent.py 暴露给 ADK 注入。
memory_service = LocalFileMemoryService()

# 记忆工具：
# - preload_memory_tool：每次 LLM 请求前自动预载（prefetch）相关记忆；
# - load_memory_tool：模型可主动按查询加载（load/search）记忆。
MEMORY_TOOLS = [preload_memory_tool, load_memory_tool]
