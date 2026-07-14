"""observability（ADK 原生可观测接入）单元测试。

覆盖新增内容：基于 ADK ``BasePlugin`` 的全局可观测 Plugin、基于 ADK ``telemetry.tracer``
的真实 OTel span（无后端时 no-op）、以及脱敏逻辑。
"""

import asyncio
import os
import tempfile
import types
import unittest
from pathlib import Path

os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from google.adk.plugins.base_plugin import BasePlugin

from devops_agent import observability
from devops_agent.observability import (
    DevOpsObservabilityPlugin,
    observability_plugin,
    redact_args,
    start_span,
)


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class _Ctx:
    invocation_id = "inv-1"
    agent_name = "diagnostics_agent"


class TestObservability(unittest.TestCase):
    def test_plugin_is_base_plugin(self) -> None:
        self.assertIsInstance(observability_plugin, DevOpsObservabilityPlugin)
        self.assertIsInstance(observability_plugin, BasePlugin)

    def test_redact_sensitive_keys(self) -> None:
        out = redact_args({"service": "x", "api_key": "secret", "approval_token": "t"})
        self.assertEqual(out["api_key"], "***REDACTED***")
        self.assertEqual(out["service"], "x")

    def test_start_span_noop_does_not_raise(self) -> None:
        # 无 OTel 后端时应为 no-op，且不抛异常。
        with start_span("unit-test-span", tool="check_service_health"):
            pass

    def test_plugin_tool_callbacks_audit(self) -> None:
        # 把审计落盘指向临时目录，验证 before/after 回调写审计。
        with tempfile.TemporaryDirectory() as d:
            audit = Path(d) / "audit.log"
            orig = observability.settings
            observability.settings = types.SimpleNamespace(audit_log_path=audit)
            try:
                asyncio.run(
                    observability_plugin.before_tool_callback(
                        tool=_Tool("check_service_health"),
                        tool_args={"service": "order-service"},
                        tool_context=_Ctx(),
                    )
                )
                asyncio.run(
                    observability_plugin.after_tool_callback(
                        tool=_Tool("check_service_health"),
                        tool_args={"service": "order-service"},
                        tool_context=_Ctx(),
                        result={"status": "healthy"},
                    )
                )
            finally:
                observability.settings = orig

            self.assertTrue(audit.exists())
            content = audit.read_text(encoding="utf-8")
            self.assertIn("before_tool", content)
            self.assertIn("after_tool:healthy", content)

    def test_after_model_token_usage_no_raise(self) -> None:
        usage = types.SimpleNamespace(
            prompt_token_count=10, candidates_token_count=5, total_token_count=15
        )
        resp = types.SimpleNamespace(usage_metadata=usage)
        ctx = types.SimpleNamespace(agent_name="devops_supervisor", invocation_id="inv-2")
        # 不应抛异常；无 usage 时也应安全返回。
        asyncio.run(observability_plugin.after_model_callback(callback_context=ctx, llm_response=resp))
        asyncio.run(
            observability_plugin.after_model_callback(
                callback_context=ctx, llm_response=types.SimpleNamespace(usage_metadata=None)
            )
        )


if __name__ == "__main__":
    unittest.main()
