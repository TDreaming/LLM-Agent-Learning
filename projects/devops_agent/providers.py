"""端口-适配器层（Ports & Adapters / Hexagonal）。

Skill 工具只依赖这里定义的抽象 Provider 接口（Ports），不直接依赖任何具体后端。
默认提供只读 ``MockAdapter``（确定性 mock 数据，可离线演示，绝不触达真实系统）。

企业落地时，只需实现相同接口的真实适配器（如 PrometheusAdapter / KubernetesAdapter /
CIAdapter），并在 ``get_ops_backend`` 工厂中按 ``DEVOPS_PROVIDER_BACKEND`` 选择，
Skill 与 SubAgent 代码无需任何修改。
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Any

from .config import settings

# ---- 已知的演示用服务清单（mock 后端使用）----
_KNOWN_SERVICES = {"order-service", "payment-service", "user-service", "gateway"}


# =========================== Ports（抽象接口） ===========================


class HealthProvider(ABC):
    """健康检查端口。"""

    @abstractmethod
    def check_health(self, service: str) -> dict[str, Any]: ...


class MetricsProvider(ABC):
    """指标查询端口。"""

    @abstractmethod
    def query(self, service: str, metric: str, window: str) -> dict[str, Any]: ...


class LogsProvider(ABC):
    """日志检索端口。"""

    @abstractmethod
    def search(self, service: str, keyword: str, limit: int) -> dict[str, Any]: ...


class DeployProvider(ABC):
    """部署状态/回滚端口。"""

    @abstractmethod
    def get_status(self, service: str) -> dict[str, Any]: ...

    @abstractmethod
    def rollback(self, service: str, target_version: str | None) -> dict[str, Any]: ...


class OpsBackend(ABC):
    """聚合后端：把四类 Provider 组合为一个运维后端门面。"""

    health: HealthProvider
    metrics: MetricsProvider
    logs: LogsProvider
    deploy: DeployProvider


# =========================== Mock 适配器（默认） ===========================


def _stable_int(seed: str, lo: int, hi: int) -> int:
    """基于字符串生成稳定（确定性）的伪随机整数，便于演示可复现。"""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    span = hi - lo + 1
    return lo + (int(digest[:8], 16) % span)


class _MockHealth(HealthProvider):
    def check_health(self, service: str) -> dict[str, Any]:
        known = service in _KNOWN_SERVICES
        cpu = _stable_int(f"{service}:cpu", 5, 95)
        mem = _stable_int(f"{service}:mem", 10, 90)
        status = "healthy" if cpu < 85 and mem < 85 else "degraded"
        return {
            "service": service,
            "known": known,
            "status": status if known else "unknown",
            "cpu_percent": cpu,
            "memory_percent": mem,
            "replicas_ready": _stable_int(f"{service}:rep", 1, 6),
            "replicas_desired": _stable_int(f"{service}:rep", 1, 6),
        }


class _MockMetrics(MetricsProvider):
    def query(self, service: str, metric: str, window: str) -> dict[str, Any]:
        base = _stable_int(f"{service}:{metric}", 20, 800)
        return {
            "service": service,
            "metric": metric,
            "window": window,
            "value": base,
            "unit": "ms" if "latency" in metric else "count",
            "p99": base + _stable_int(f"{service}:{metric}:p99", 10, 300),
        }


class _MockLogs(LogsProvider):
    def search(self, service: str, keyword: str, limit: int) -> dict[str, Any]:
        n = max(1, min(limit, _stable_int(f"{service}:{keyword}", 1, 5)))
        samples = [
            {
                "ts": f"2026-06-12T1{i}:00:00",
                "level": "ERROR" if keyword.lower() in {"error", "exception"} else "INFO",
                "message": f"[{service}] sample log matching '{keyword}' #{i}",
            }
            for i in range(n)
        ]
        return {"service": service, "keyword": keyword, "count": n, "entries": samples}


class _MockDeploy(DeployProvider):
    def get_status(self, service: str) -> dict[str, Any]:
        cur = _stable_int(f"{service}:ver", 10, 40)
        return {
            "service": service,
            "current_version": f"v1.{cur}.0",
            "previous_version": f"v1.{cur - 1}.0",
            "strategy": "rolling",
            "status": "succeeded",
            "updated_at": "2026-06-12T08:30:00",
        }

    def rollback(self, service: str, target_version: str | None) -> dict[str, Any]:
        status = self.get_status(service)
        target = target_version or status["previous_version"]
        return {
            "service": service,
            "action": "rollback",
            "from_version": status["current_version"],
            "to_version": target,
            "result": "executed",
            "note": "mock 后端：未触达真实系统",
        }


class MockAdapter(OpsBackend):
    """只读/无副作用的 Mock 后端，用于离线演示与本地开发。"""

    def __init__(self) -> None:
        self.health = _MockHealth()
        self.metrics = _MockMetrics()
        self.logs = _MockLogs()
        self.deploy = _MockDeploy()


# =========================== 工厂 ===========================

_backend: OpsBackend | None = None


def get_ops_backend() -> OpsBackend:
    """按配置返回运维后端单例。

    目前内置 ``mock``；真实后端（prometheus/k8s/ci）为预留扩展点：实现对应
    Provider 接口后在此分支返回即可，Skill 层无需改动。
    """
    global _backend
    if _backend is not None:
        return _backend

    backend = settings.provider_backend.lower()
    if backend == "mock":
        _backend = MockAdapter()
    else:
        # 预留：真实后端尚未在示例中实现，回退到 Mock 并保持可运行。
        _backend = MockAdapter()
    return _backend
