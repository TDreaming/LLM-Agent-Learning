"""registry（组件注册表与按配置装配）单元测试。"""

import os
import unittest

os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from devops_agent import registry
from devops_agent.component_config import AgentConfigSnapshot, ComponentSpec


class TestRegistry(unittest.TestCase):
    def test_build_sub_agents_only_enabled(self) -> None:
        snap = AgentConfigSnapshot(
            agents=(
                ComponentSpec("diagnostics_agent", True),
                ComponentSpec("remediation_agent", False),
                ComponentSpec("communicator_agent", True),
            )
        )
        names = [a.name for a in registry.build_sub_agents(snap)]
        self.assertEqual(names, ["diagnostics_agent", "communicator_agent"])

    def test_build_sub_agents_unknown_skipped(self) -> None:
        snap = AgentConfigSnapshot(
            agents=(
                ComponentSpec("does_not_exist", True),
                ComponentSpec("diagnostics_agent", True),
            )
        )
        names = [a.name for a in registry.build_sub_agents(snap)]
        self.assertEqual(names, ["diagnostics_agent"])

    def test_build_tools_only_enabled_and_known(self) -> None:
        snap = AgentConfigSnapshot(
            tools=(
                ComponentSpec("get_current_time", True),
                ComponentSpec("unknown_tool", True),
                ComponentSpec("get_current_time_disabled", False),
            )
        )
        tools = registry.build_tools(snap)
        # 只有已登记且 enabled 的 get_current_time 会被装配。
        self.assertEqual(len(tools), 1)

    def test_build_mcp_map_unknown_skipped(self) -> None:
        snap = AgentConfigSnapshot(mcp=(ComponentSpec("unknown_mcp", True),))
        self.assertEqual(registry.build_mcp_map(snap), {})

    def test_build_mcp_map_uses_factory(self) -> None:
        # 用 stub 工厂避免依赖 npx；仅验证 enabled 项被构造、name 作为键。
        orig = registry.MCP_FACTORIES.copy()
        registry.MCP_FACTORIES["fake"] = lambda args: f"toolset::{args.get('x')}"
        try:
            snap = AgentConfigSnapshot(
                mcp=(
                    ComponentSpec("fake", True, {"x": 1}),
                    ComponentSpec("filesystem", False),
                )
            )
            m = registry.build_mcp_map(snap)
            self.assertEqual(m, {"fake": "toolset::1"})
        finally:
            registry.MCP_FACTORIES.clear()
            registry.MCP_FACTORIES.update(orig)

    def test_build_mcp_map_skips_none_from_factory(self) -> None:
        orig = registry.MCP_FACTORIES.copy()
        registry.MCP_FACTORIES["fail"] = lambda args: None  # 模拟优雅降级
        try:
            snap = AgentConfigSnapshot(mcp=(ComponentSpec("fail", True),))
            self.assertEqual(registry.build_mcp_map(snap), {})
        finally:
            registry.MCP_FACTORIES.clear()
            registry.MCP_FACTORIES.update(orig)


if __name__ == "__main__":
    unittest.main()
