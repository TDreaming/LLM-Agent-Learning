"""本地文件持久化的 MemoryService。

继承 ADK 的 InMemoryMemoryService，把内存里的事件落到本地 JSON 文件，
启动时再读回来，避免 `adk run / adk web` 重启后记忆丢失。

适用于本地开发和原型；生产请换成 RAG / Vertex Memory Bank。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.genai import types

if TYPE_CHECKING:
    from google.adk.events.event import Event
    from google.adk.sessions.session import Session

logger = logging.getLogger(__name__)


def _default_store_path() -> Path:
    # 默认放在工程根目录下的 .adk_memory.json，已在 .gitignore 里忽略
    base = Path(os.environ.get("ADK_LOCAL_MEMORY_DIR", str(Path.cwd())))
    return base / ".adk_memory.json"


class LocalFileMemoryService(InMemoryMemoryService):
    """JSON 文件持久化的 MemoryService。"""

    def __init__(self, store_path: str | Path | None = None) -> None:
        super().__init__()
        self._store_path: Path = Path(store_path) if store_path else _default_store_path()
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
        from google.adk.events.event import Event  # 延迟导入避免循环

        with self._io_lock, self._lock:
            payload: dict[str, dict[str, list[dict]]] = {}
            for user_key, sessions in self._session_events.items():
                payload[user_key] = {
                    sid: [self._event_to_dict(ev) for ev in evs]
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

    # ---------- 事件序列化辅助 ----------

    @staticmethod
    def _event_to_dict(event: "Event") -> dict:
        # Event 是 pydantic BaseModel，直接 dump 即可
        return event.model_dump(mode="json", exclude_none=True)


# 全局单例，方便 ADK 通过 --memory_service_uri 之外的方式注入
local_memory_service = LocalFileMemoryService()
