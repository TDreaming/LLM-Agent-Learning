"""L1 装配冒烟测试：导入 agent 并断言 Supervisor/SubAgent/App 装配正确。

不发起真实模型调用；导入前注入 dummy 凭据。
"""

import os
import unittest

os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from google.adk.apps.app import App

from devops_agent.agent import app, root_agent
from devops_agent.memory import LocalFileMemoryService, memory_service
from devops_agent.observability import DevOpsObservabilityPlugin
from devops_agent.subagents import remediation_agent


class TestAgentAssembly(unittest.TestCase):
    def test_root_agent_has_three_subagents(self) -> None:
        self.assertEqual(root_agent.name, "devops_supervisor")
        names = {a.name for a in root_agent.sub_agents}
        self.assertEqual(
            names, {"diagnostics_agent", "remediation_agent", "communicator_agent"}
        )

    def test_memory_service_is_persistent(self) -> None:
        self.assertIsInstance(memory_service, LocalFileMemoryService)

    def test_remediation_guardrail_callback_attached(self) -> None:
        self.assertIsNotNone(remediation_agent.before_tool_callback)

    def test_app_registers_observability_plugin(self) -> None:
        self.assertIsInstance(app, App)
        self.assertEqual(app.name, "devops_agent")
        self.assertTrue(
            any(isinstance(p, DevOpsObservabilityPlugin) for p in app.plugins)
        )
        self.assertIs(app.root_agent, root_agent)


if __name__ == "__main__":
    unittest.main()
