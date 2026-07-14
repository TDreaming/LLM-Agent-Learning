"""运维领域 Skill（FunctionTool）。

每个 Skill 都是带规范 docstring 的纯函数，供 LLM function-calling 调用；动作统一经由
``providers.get_ops_backend()`` 的 Provider 接口执行（默认 Mock 只读后端）。

约定：
- 只读/诊断类工具（健康/指标/日志/部署状态）可直接调用；
- 写/危险操作（``rollback_deploy``）登记在 ``DANGEROUS_TOOLS``，由 guardrails 审批门拦截；
- ``ask_user`` 为澄清工具（对齐 kagent 内置 ask_user），用于参数缺失/意图不清时主动发问。
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

from google.adk.tools.long_running_tool import LongRunningFunctionTool
from google.adk.tools.tool_context import ToolContext

from .providers import get_ops_backend

# 需要人审批门拦截的危险/写操作工具名单（供 guardrails 使用）。
DANGEROUS_TOOLS: set[str] = {"rollback_deploy"}


# =========================== 诊断类（只读） ===========================


def check_service_health(service: str) -> dict[str, Any]:
    """检查指定服务的健康状态。

    Args:
        service: 服务名，例如 ``order-service``。

    Returns:
        结构化健康状态，包含 status、cpu_percent、memory_percent、replicas 等字段。
    """
    return get_ops_backend().health.check_health(service)


def query_metrics(service: str, metric: str = "latency", window: str = "5m") -> dict[str, Any]:
    """查询指定服务的监控指标。

    Args:
        service: 服务名。
        metric: 指标名，如 ``latency``、``qps``、``error_rate``。默认 ``latency``。
        window: 时间窗口，如 ``5m``、``1h``。默认 ``5m``。

    Returns:
        结构化指标结果，包含 value、unit、p99 等字段。
    """
    return get_ops_backend().metrics.query(service, metric, window)


def search_logs(service: str, keyword: str, limit: int = 5) -> dict[str, Any]:
    """检索指定服务的日志。

    Args:
        service: 服务名。
        keyword: 检索关键词，如 ``error``、``timeout``。
        limit: 返回条数上限，默认 5。

    Returns:
        结构化日志结果，包含 count 与 entries（每条含 ts、level、message）。
    """
    return get_ops_backend().logs.search(service, keyword, limit)


def get_deploy_status(service: str) -> dict[str, Any]:
    """查询指定服务的部署状态（只读）。

    Args:
        service: 服务名。

    Returns:
        结构化部署信息，包含 current_version、previous_version、strategy、status 等。
    """
    return get_ops_backend().deploy.get_status(service)


# =========================== 处置类（写/危险操作） ===========================


def rollback_deploy(
    service: str,
    target_version: Optional[str] = None,
    approval_token: Optional[str] = None,
) -> dict[str, Any]:
    """回滚指定服务的部署到目标版本（危险/写操作，需经人审批门确认）。

    安全契约：该工具属于写操作，会被安全护栏拦截进入审批门。首次调用（不带
    ``approval_token``）会被拦截并返回审批令牌；待用户明确批准后，须携带相同的
    ``approval_token`` 再次调用，才会真正执行。

    Args:
        service: 服务名。
        target_version: 目标版本号；省略时回滚到上一个版本。
        approval_token: 人审批令牌；首次调用留空，获批后由护栏发放并回填。

    Returns:
        结构化回滚结果，包含 from_version、to_version、result 等。
    """
    return get_ops_backend().deploy.rollback(service, target_version)


# =========================== 通用工具 ===========================


def get_current_time() -> dict[str, Any]:
    """获取当前服务器时间。

    Returns:
        包含 ISO 格式时间字符串的字典。
    """
    return {"now": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def ask_user(question: str, tool_context: ToolContext, options: Optional[list[str]] = None) -> None:
    """当请求有歧义或缺少必要参数时，向用户主动提出澄清问题。

    这是一个长运行工具：调用后会暂停并等待用户在 CLI/Web 中回答，
    用户的回答会作为后续上下文继续推进任务。

    Args:
        question: 要向用户提出的澄清问题。
        tool_context: ADK 注入的工具上下文（自动传入，无需模型提供）。
        options: 可选的候选项列表，便于用户快速选择。
    """
    # 暂停并把控制权交还给用户；不对本次空返回做总结。
    tool_context.actions.skip_summarization = True
    return None


# ask_user 需要作为长运行工具，使会话挂起等待用户输入。
ask_user_tool = LongRunningFunctionTool(func=ask_user)


# 各能力域的工具集合，供 subagents 装配。
DIAGNOSTIC_TOOLS = [check_service_health, query_metrics, search_logs, get_current_time, ask_user_tool]
REMEDIATION_TOOLS = [get_deploy_status, rollback_deploy, ask_user_tool]
COMMUNICATION_TOOLS = [get_current_time, ask_user_tool]
