"""guardrails（安全护栏与人审批门）单元测试（重点）。"""

import os
import types
import unittest

os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from devops_agent import guardrails
from devops_agent.guardrails import (
    before_tool_guardrail,
    grant_approval,
    reject_approval,
)


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCtx:
    def __init__(self) -> None:
        self.state: dict = {}
        self.actions = types.SimpleNamespace()
        self.invocation_id = "inv-test"
        self.agent_name = "remediation_agent"


def _fake_settings(require_approval: bool = True, max_tool_calls: int = 50):
    return types.SimpleNamespace(
        require_approval=require_approval, max_tool_calls=max_tool_calls
    )


class TestGuardrails(unittest.TestCase):
    def setUp(self) -> None:
        # 保存并替换模块级 settings，便于控制预算/审批开关。
        self._orig_settings = guardrails.settings
        guardrails.settings = _fake_settings()

    def tearDown(self) -> None:
        guardrails.settings = self._orig_settings

    def test_readonly_tool_allowed(self) -> None:
        ctx = _FakeCtx()
        ret = before_tool_guardrail(
            _FakeTool("check_service_health"), {"service": "order-service"}, ctx
        )
        self.assertIsNone(ret)  # 放行

    def test_dangerous_tool_first_call_pending(self) -> None:
        ctx = _FakeCtx()
        ret = before_tool_guardrail(
            _FakeTool("rollback_deploy"), {"service": "order-service"}, ctx
        )
        self.assertIsNotNone(ret)
        self.assertEqual(ret["status"], "pending_approval")
        self.assertIn("approval_token", ret)

    def test_approval_token_is_stable(self) -> None:
        ctx1, ctx2 = _FakeCtx(), _FakeCtx()
        r1 = before_tool_guardrail(_FakeTool("rollback_deploy"), {"service": "x"}, ctx1)
        r2 = before_tool_guardrail(_FakeTool("rollback_deploy"), {"service": "x"}, ctx2)
        self.assertEqual(r1["approval_token"], r2["approval_token"])

    def test_approved_retry_passes(self) -> None:
        ctx = _FakeCtx()
        args = {"service": "order-service"}
        first = before_tool_guardrail(_FakeTool("rollback_deploy"), args, ctx)
        token = first["approval_token"]

        grant_approval(ctx.state, token)
        retry = before_tool_guardrail(
            _FakeTool("rollback_deploy"),
            {"service": "order-service", "approval_token": token},
            ctx,
        )
        self.assertIsNone(retry)  # 已批准 -> 放行执行

    def test_rejected_feeds_reason_and_blocks(self) -> None:
        ctx = _FakeCtx()
        args = {"service": "order-service"}
        first = before_tool_guardrail(_FakeTool("rollback_deploy"), args, ctx)
        token = first["approval_token"]

        reject_approval(ctx.state, token, "影响范围过大")
        ret = before_tool_guardrail(_FakeTool("rollback_deploy"), args, ctx)
        self.assertEqual(ret["status"], "rejected")
        self.assertIn("影响范围过大", ret["reason"])

    def test_budget_exceeded(self) -> None:
        guardrails.settings = _fake_settings(max_tool_calls=2)
        ctx = _FakeCtx()
        tool = _FakeTool("check_service_health")
        self.assertIsNone(before_tool_guardrail(tool, {"service": "a"}, ctx))  # 1
        self.assertIsNone(before_tool_guardrail(tool, {"service": "a"}, ctx))  # 2
        ret = before_tool_guardrail(tool, {"service": "a"}, ctx)  # 3 -> 超限
        self.assertIsNotNone(ret)
        self.assertEqual(ret["status"], "blocked")
        self.assertEqual(ret["reason"], "budget_exceeded")

    def test_approval_disabled_passes_dangerous(self) -> None:
        guardrails.settings = _fake_settings(require_approval=False)
        ctx = _FakeCtx()
        ret = before_tool_guardrail(
            _FakeTool("rollback_deploy"), {"service": "x"}, ctx
        )
        self.assertIsNone(ret)  # 审批关闭 -> 直接放行


if __name__ == "__main__":
    unittest.main()
