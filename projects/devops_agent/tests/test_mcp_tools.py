"""mcp_tools（可选 MCP 集成，优雅降级）单元测试。"""

import os
import types
import unittest

os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from devops_agent import mcp_tools


class TestMcpTools(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_settings = mcp_tools.settings

    def tearDown(self) -> None:
        mcp_tools.settings = self._orig_settings

    def test_disabled_returns_empty(self) -> None:
        mcp_tools.settings = types.SimpleNamespace(enable_mcp=False)
        self.assertEqual(mcp_tools.build_mcp_toolsets(), [])

    def test_enabled_without_npx_returns_empty(self) -> None:
        # 启用开关但环境无 npx -> 仍应优雅降级返回空列表。
        import shutil

        mcp_tools.settings = types.SimpleNamespace(enable_mcp=True)
        orig_which = shutil.which
        shutil.which = lambda _cmd: None  # 模拟 npx 不可用
        try:
            self.assertEqual(mcp_tools.build_mcp_toolsets(), [])
        finally:
            shutil.which = orig_which


if __name__ == "__main__":
    unittest.main()
