"""providers（端口-适配器）单元测试。"""

import os
import unittest

# 为「导入即装配」的 devops_agent 提供 dummy 凭据（仅离线装配，不发起真实调用）。
os.environ.setdefault("MODEL_NAME", "test/dummy-model")
os.environ.setdefault("ARK_API_KEY", "dummy-key")

from devops_agent import providers
from devops_agent.providers import MockAdapter, OpsBackend, get_ops_backend


class TestProviders(unittest.TestCase):
    def setUp(self) -> None:
        # 重置工厂缓存，避免用例间相互影响。
        providers._backend = None

    def test_default_backend_is_mock(self) -> None:
        backend = get_ops_backend()
        self.assertIsInstance(backend, MockAdapter)
        self.assertIsInstance(backend, OpsBackend)

    def test_backend_is_singleton(self) -> None:
        self.assertIs(get_ops_backend(), get_ops_backend())

    def test_health_has_expected_fields(self) -> None:
        result = MockAdapter().health.check_health("order-service")
        for key in ("status", "cpu_percent", "memory_percent", "replicas_ready", "replicas_desired"):
            self.assertIn(key, result)
        self.assertEqual(result["service"], "order-service")

    def test_results_are_deterministic(self) -> None:
        a = MockAdapter().health.check_health("payment-service")
        b = MockAdapter().health.check_health("payment-service")
        self.assertEqual(a, b)

    def test_metrics_and_logs_structure(self) -> None:
        metrics = MockAdapter().metrics.query("gateway", "latency", "5m")
        self.assertIn("value", metrics)
        self.assertIn("p99", metrics)

        logs = MockAdapter().logs.search("gateway", "timeout", limit=3)
        self.assertIn("entries", logs)
        self.assertLessEqual(logs["count"], 3)
        self.assertEqual(logs["count"], len(logs["entries"]))

    def test_deploy_status_and_rollback(self) -> None:
        status = MockAdapter().deploy.get_status("order-service")
        self.assertIn("current_version", status)
        self.assertIn("previous_version", status)

        rollback = MockAdapter().deploy.rollback("order-service", None)
        self.assertEqual(rollback["action"], "rollback")
        # 未指定目标版本时回滚到上一个版本。
        self.assertEqual(rollback["to_version"], status["previous_version"])


if __name__ == "__main__":
    unittest.main()
