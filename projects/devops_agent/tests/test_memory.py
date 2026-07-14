"""memory（本地持久化记忆）单元测试。"""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from google.adk.events.event import Event
from google.adk.sessions.session import Session
from google.genai import types

from devops_agent.memory import MEMORY_TOOLS, LocalFileMemoryService


def _make_session(app: str, user: str, sid: str, text: str) -> Session:
    event = Event(
        author="user",
        invocation_id="inv-1",
        content=types.Content(role="user", parts=[types.Part(text=text)]),
    )
    return Session(id=sid, app_name=app, user_id=user, events=[event])


class TestMemory(unittest.TestCase):
    def test_persist_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = Path(d) / "mem.json"

            svc = LocalFileMemoryService(store_path=store)
            session = _make_session(
                "devops_agent", "u1", "s1", "order-service health check passed"
            )
            asyncio.run(svc.add_session_to_memory(session))

            # 落盘文件应已生成。
            self.assertTrue(store.exists())

            # 重建服务（模拟重启）后应能恢复并检索到记忆（关键词匹配，仅 ASCII 词）。
            svc2 = LocalFileMemoryService(store_path=store)
            resp = asyncio.run(
                svc2.search_memory(app_name="devops_agent", user_id="u1", query="health")
            )
            self.assertGreaterEqual(len(resp.memories), 1)

    def test_memory_tools_exposed(self) -> None:
        # 至少包含 preload + load 两个记忆工具（prefetch/load 语义）。
        self.assertGreaterEqual(len(MEMORY_TOOLS), 2)


if __name__ == "__main__":
    unittest.main()
