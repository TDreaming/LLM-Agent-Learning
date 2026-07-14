"""config（配置加载）单元测试。"""

import os
import unittest

os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from devops_agent.config import Settings, require_model_credentials


class TestConfig(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            k: os.environ.get(k)
            for k in (
                "MODEL_NAME",
                "ARK_API_KEY",
                "DEVOPS_ENABLE_MCP",
                "DEVOPS_REQUIRE_APPROVAL",
                "DEVOPS_MAX_TOOL_CALLS",
                "DEVOPS_COMPACTION_INTERVAL",
            )
        }

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_require_credentials_raises_when_missing(self) -> None:
        os.environ.pop("MODEL_NAME", None)
        os.environ.pop("ARK_API_KEY", None)
        with self.assertRaises(RuntimeError):
            require_model_credentials()

    def test_require_credentials_ok_when_present(self) -> None:
        os.environ["MODEL_NAME"] = "test/model"
        os.environ["ARK_API_KEY"] = "key"
        require_model_credentials()  # 不应抛出

    def test_switch_parsing(self) -> None:
        os.environ["DEVOPS_ENABLE_MCP"] = "true"
        os.environ["DEVOPS_REQUIRE_APPROVAL"] = "false"
        os.environ["DEVOPS_MAX_TOOL_CALLS"] = "7"
        os.environ["DEVOPS_COMPACTION_INTERVAL"] = "5"
        s = Settings()
        self.assertTrue(s.enable_mcp)
        self.assertFalse(s.require_approval)
        self.assertEqual(s.max_tool_calls, 7)
        self.assertEqual(s.compaction_interval, 5)

    def test_defaults(self) -> None:
        for k in (
            "DEVOPS_ENABLE_MCP",
            "DEVOPS_REQUIRE_APPROVAL",
            "DEVOPS_MAX_TOOL_CALLS",
            "DEVOPS_COMPACTION_INTERVAL",
        ):
            os.environ.pop(k, None)
        s = Settings()
        self.assertFalse(s.enable_mcp)
        self.assertTrue(s.require_approval)  # 默认要求审批
        self.assertEqual(s.max_tool_calls, 50)
        self.assertEqual(s.compaction_interval, 0)  # 默认关闭压缩

    def test_invalid_int_falls_back_to_default(self) -> None:
        os.environ["DEVOPS_MAX_TOOL_CALLS"] = "not-a-number"
        self.assertEqual(Settings().max_tool_calls, 50)


if __name__ == "__main__":
    unittest.main()
