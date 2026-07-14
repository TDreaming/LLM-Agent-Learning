"""skills（运维 Skill）单元测试。"""

import os
import unittest

os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from google.adk.tools.long_running_tool import LongRunningFunctionTool

from devops_agent import skills


class _FakeActions:
    def __init__(self) -> None:
        self.skip_summarization = False


class _FakeToolContext:
    def __init__(self) -> None:
        self.actions = _FakeActions()


class TestSkills(unittest.TestCase):
    def test_dangerous_tools_contains_rollback(self) -> None:
        self.assertIn("rollback_deploy", skills.DANGEROUS_TOOLS)

    def test_readonly_skills_return_structured_dict(self) -> None:
        health = skills.check_service_health("order-service")
        self.assertIsInstance(health, dict)
        self.assertIn("status", health)

        metrics = skills.query_metrics("order-service")
        self.assertIn("value", metrics)

        logs = skills.search_logs("order-service", "error")
        self.assertIn("entries", logs)

        deploy = skills.get_deploy_status("order-service")
        self.assertIn("current_version", deploy)

        now = skills.get_current_time()
        self.assertIn("now", now)

    def test_rollback_returns_structured_dict(self) -> None:
        result = skills.rollback_deploy("order-service")
        self.assertEqual(result["action"], "rollback")
        self.assertIn("to_version", result)

    def test_ask_user_is_long_running_and_skips_summarization(self) -> None:
        self.assertIsInstance(skills.ask_user_tool, LongRunningFunctionTool)
        self.assertTrue(skills.ask_user_tool.is_long_running)

        ctx = _FakeToolContext()
        ret = skills.ask_user("哪个服务？", ctx, options=["order-service", "gateway"])
        self.assertIsNone(ret)
        self.assertTrue(ctx.actions.skip_summarization)

    def test_tool_bundles_assigned(self) -> None:
        self.assertIn(skills.check_service_health, skills.DIAGNOSTIC_TOOLS)
        self.assertIn(skills.rollback_deploy, skills.REMEDIATION_TOOLS)
        self.assertIn(skills.ask_user_tool, skills.COMMUNICATION_TOOLS)


if __name__ == "__main__":
    unittest.main()
