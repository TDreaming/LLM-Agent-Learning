"""hot_reload（配置动态热加载）单元测试。

全部离线：用 stub 组件注入注册表，避免依赖 LLM / 网络 / npx；用临时 YAML 文件
驱动 ConfigWatcher。
"""

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from devops_agent import hot_reload, registry
from devops_agent.component_config import AgentConfigSnapshot, ComponentSpec


def _fake_root() -> SimpleNamespace:
    # 仅需 tools / sub_agents 两个列表属性即可驱动 ConfigWatcher。
    return SimpleNamespace(tools=[], sub_agents=[], name="fake_root")


class TestHotReload(unittest.TestCase):
    def setUp(self) -> None:
        # 注入 stub 子代理 / 工具 / MCP 工厂到真实注册表，结束后恢复。
        self._sa_orig = registry.SUB_AGENT_REGISTRY.copy()
        self._tool_orig = registry.TOOL_REGISTRY.copy()
        self._mcp_orig = registry.MCP_FACTORIES.copy()

        registry.SUB_AGENT_REGISTRY.clear()
        registry.SUB_AGENT_REGISTRY.update(
            {
                "agent_a": SimpleNamespace(name="agent_a", parent_agent=None),
                "agent_b": SimpleNamespace(name="agent_b", parent_agent=None),
            }
        )
        registry.TOOL_REGISTRY.clear()
        registry.TOOL_REGISTRY.update(
            {
                "tool_x": lambda: "TOOL_X",
                "tool_y": lambda: "TOOL_Y",
            }
        )
        registry.MCP_FACTORIES.clear()
        registry.MCP_FACTORIES.update(
            {"fs": lambda args: f"MCP_FS::{args.get('root_dir', '')}"}
        )

        self._dir = TemporaryDirectory()
        self._path = Path(self._dir.name) / "agent_config.yaml"

    def tearDown(self) -> None:
        registry.SUB_AGENT_REGISTRY.clear()
        registry.SUB_AGENT_REGISTRY.update(self._sa_orig)
        registry.TOOL_REGISTRY.clear()
        registry.TOOL_REGISTRY.update(self._tool_orig)
        registry.MCP_FACTORIES.clear()
        registry.MCP_FACTORIES.update(self._mcp_orig)
        self._dir.cleanup()

    def _write(self, text: str) -> None:
        self._path.write_text(text, encoding="utf-8")

    # ---------------- apply（就地更新） ----------------

    def test_apply_in_place_keeps_object_identity(self) -> None:
        root = _fake_root()
        tools_list_id = id(root.tools)
        sub_list_id = id(root.sub_agents)
        watcher = hot_reload.ConfigWatcher(root, path=self._path)

        snap = AgentConfigSnapshot(
            agents=(ComponentSpec("agent_a", True),),
            tools=(ComponentSpec("tool_x", True),),
        )
        watcher.apply(snap)

        # root 与其 tools/sub_agents 列表对象保持同一实例（切片赋值）。
        self.assertEqual(id(root.tools), tools_list_id)
        self.assertEqual(id(root.sub_agents), sub_list_id)
        self.assertIn("TOOL_X", root.tools)
        self.assertEqual([a.name for a in root.sub_agents], ["agent_a"])

    def test_apply_enable_disable_sub_agents(self) -> None:
        root = _fake_root()
        watcher = hot_reload.ConfigWatcher(root, path=self._path)

        watcher.apply(
            AgentConfigSnapshot(
                agents=(ComponentSpec("agent_a", True), ComponentSpec("agent_b", True))
            )
        )
        self.assertEqual({a.name for a in root.sub_agents}, {"agent_a", "agent_b"})

        watcher.apply(AgentConfigSnapshot(agents=(ComponentSpec("agent_a", True),)))
        self.assertEqual([a.name for a in root.sub_agents], ["agent_a"])

    def test_apply_mcp_enable_then_disable(self) -> None:
        root = _fake_root()
        watcher = hot_reload.ConfigWatcher(root, path=self._path)

        watcher.apply(
            AgentConfigSnapshot(mcp=(ComponentSpec("fs", True, {"root_dir": "/rb"}),))
        )
        self.assertIn("MCP_FS::/rb", root.tools)

        watcher.apply(AgentConfigSnapshot(mcp=(ComponentSpec("fs", False),)))
        self.assertNotIn("MCP_FS::/rb", root.tools)

    # ---------------- check_once（文件变更检测） ----------------

    def test_check_once_detects_change(self) -> None:
        root = _fake_root()
        # 先构造 watcher（文件尚不存在，签名为 None），再写入 → 触发变更。
        watcher = hot_reload.ConfigWatcher(root, path=self._path)
        self._write("agents:\n  - name: agent_a\n    enabled: true\n")
        self.assertTrue(watcher.check_once())
        self.assertEqual([a.name for a in root.sub_agents], ["agent_a"])
        # 无变更时不再应用。
        self.assertFalse(watcher.check_once())

    def test_invalid_yaml_keeps_last_good(self) -> None:
        root = _fake_root()
        watcher = hot_reload.ConfigWatcher(root, path=self._path)
        self._write("agents:\n  - name: agent_a\n    enabled: true\n")
        watcher.check_once()
        self.assertEqual([a.name for a in root.sub_agents], ["agent_a"])

        # 写入非法 YAML：应保留上一份有效状态，不抛异常。
        time.sleep(0.01)
        self._write("agents: [broken\n")
        self.assertFalse(watcher.check_once())
        self.assertEqual([a.name for a in root.sub_agents], ["agent_a"])

    # ---------------- 线程化 <1s 感知 ----------------

    def test_watcher_thread_applies_within_one_second(self) -> None:
        self._write("agents:\n  - name: agent_a\n    enabled: true\n")
        root = _fake_root()
        watcher = hot_reload.ConfigWatcher(root, path=self._path, poll_interval=0.2)
        watcher.check_once()  # 建立初始状态
        watcher.start()
        try:
            time.sleep(0.05)
            # 运行期开启 agent_b。
            self._write(
                "agents:\n"
                "  - name: agent_a\n    enabled: true\n"
                "  - name: agent_b\n    enabled: true\n"
            )
            deadline = time.time() + 1.0
            ok = False
            while time.time() < deadline:
                if {a.name for a in root.sub_agents} == {"agent_a", "agent_b"}:
                    ok = True
                    break
                time.sleep(0.05)
            self.assertTrue(ok, "config change not applied within 1s")
        finally:
            watcher.stop()


if __name__ == "__main__":
    unittest.main()
