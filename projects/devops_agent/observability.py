"""可观测性与审计模块。

提供：
- 统一的 stdout 结构化日志（含 invocation_id / agent / tool / 状态等字段，默认脱敏）；
- 工具调用审计落盘（追加写本地 JSONL 审计文件）；
- 基于 ADK 原生能力的可观测接入：
  · ``DevOpsObservabilityPlugin``：基于 ADK ``BasePlugin`` 的全局生命周期回调，
    统一观测「所有 Agent / 所有工具调用 / 模型 token 用量」（经模块级 ``app`` 或
    ``Runner(plugins=...)`` 注册即可，无需在每个 Agent 上重复挂回调）；
  · ``start_span``：基于 ADK ``telemetry.tracer`` 的真实 OpenTelemetry span，
    与 ADK 自动产生的 invocation/agent_run/call_llm/execute_tool span 同属一棵 trace；
    未配置 OTel 后端时为零开销 no-op，配置 ``OTEL_EXPORTER_OTLP_ENDPOINT`` 即可导出。

设计原则（对齐 kagent / ADK Observability）：让每次工具调用与关键事件可见、可审计，
但默认不打印敏感原文，避免凭据/隐私泄露。
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator, Optional

from google.adk.plugins.base_plugin import BasePlugin

from .config import settings

if TYPE_CHECKING:
    from google.adk.models.llm_response import LlmResponse
    from google.adk.tools.base_tool import BaseTool
    from google.adk.tools.tool_context import ToolContext

_LOGGER_NAME = "devops_agent"
_SENSITIVE_KEYS = {"api_key", "ark_api_key", "token", "password", "secret", "authorization"}
_MAX_VALUE_LEN = 120


def get_logger() -> logging.Logger:
    """返回输出到 stdout 的结构化日志器（幂等初始化）。"""
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


logger = get_logger()


def redact(value: Any) -> Any:
    """对单个值做脱敏与长度截断。"""
    if isinstance(value, str) and len(value) > _MAX_VALUE_LEN:
        return value[:_MAX_VALUE_LEN] + "…"
    return value


def redact_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """对工具参数做脱敏：敏感键打码，长字符串截断。"""
    if not args:
        return {}
    out: dict[str, Any] = {}
    for k, v in args.items():
        if k.lower() in _SENSITIVE_KEYS:
            out[k] = "***REDACTED***"
        else:
            out[k] = redact(v)
    return out


def log_tool_call(
    *,
    invocation_id: str,
    agent: str,
    tool: str,
    args: dict[str, Any] | None,
    status: str,
    detail: str | None = None,
) -> None:
    """记录一次工具调用：stdout 结构化日志 + 审计落盘。"""
    payload = {
        "invocation_id": invocation_id,
        "agent": agent,
        "tool": tool,
        "args": redact_args(args),
        "status": status,
    }
    if detail:
        payload["detail"] = redact(detail)
    logger.info("tool_call %s", json.dumps(payload, ensure_ascii=False))
    _append_audit(payload)


def _append_audit(payload: dict[str, Any]) -> None:
    """把审计记录追加写入本地 JSONL 文件（失败不影响主流程）。"""
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **payload}
    try:
        path = settings.audit_log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:  # noqa: BLE001 - 审计落盘失败不应中断 Agent
        logger.warning("audit write failed: %s", e)


@contextmanager
def start_span(name: str, **attributes: Any) -> Iterator[None]:
    """基于 ADK 原生 ``telemetry.tracer`` 创建真实 OpenTelemetry span。

    与 ADK 自动产生的 invocation/agent_run/call_llm/execute_tool span 同属一棵 trace。
    未配置 OTel 后端（无 ``OTEL_EXPORTER_OTLP_*`` 环境变量）时，OTel 全局为 no-op
    provider，几乎零开销；导入失败时回退为纯计时日志，保证 Agent 仍可运行。
    """
    try:
        from google.adk.telemetry import tracer
    except Exception:  # noqa: BLE001 - 追踪不可用不应中断 Agent
        start = time.perf_counter()
        try:
            yield
        finally:
            logger.debug(
                "span %s done in %.1fms",
                name,
                (time.perf_counter() - start) * 1000,
            )
        return

    with tracer.start_as_current_span(name) as span:
        for key, value in redact_args(attributes).items():
            try:
                span.set_attribute(f"devops.{key}", value)
            except Exception:  # noqa: BLE001
                pass
        yield


# 兼容旧名：保留 trace_span 作为 start_span 的别名。
trace_span = start_span


# =========================== ADK 全局可观测 Plugin ===========================


class DevOpsObservabilityPlugin(BasePlugin):
    """基于 ADK ``BasePlugin`` 的全局可观测插件。

    覆盖**所有 Agent、所有工具**的生命周期回调，统一记录结构化日志 + 审计落盘，
    并在模型响应后记录 token 用量。通过模块级 ``app=App(plugins=[...])`` 或
    ``Runner(plugins=[...])`` 注册即可全局生效（区别于仅挂在单个 Agent 上的回调）。
    """

    def __init__(self, name: str = "devops_observability_plugin") -> None:
        super().__init__(name)

    async def before_tool_callback(
        self, *, tool: "BaseTool", tool_args: dict[str, Any], tool_context: "ToolContext"
    ) -> Optional[dict]:
        log_tool_call(
            invocation_id=getattr(tool_context, "invocation_id", "") or "",
            agent=getattr(tool_context, "agent_name", "") or "",
            tool=tool.name,
            args=tool_args,
            status="before_tool",
        )
        return None

    async def after_tool_callback(
        self,
        *,
        tool: "BaseTool",
        tool_args: dict[str, Any],
        tool_context: "ToolContext",
        result: dict,
    ) -> Optional[dict]:
        status = "after_tool"
        if isinstance(result, dict) and "status" in result:
            status = f"after_tool:{result['status']}"
        log_tool_call(
            invocation_id=getattr(tool_context, "invocation_id", "") or "",
            agent=getattr(tool_context, "agent_name", "") or "",
            tool=tool.name,
            args=tool_args,
            status=status,
        )
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: "BaseTool",
        tool_args: dict[str, Any],
        tool_context: "ToolContext",
        error: Exception,
    ) -> Optional[dict]:
        log_tool_call(
            invocation_id=getattr(tool_context, "invocation_id", "") or "",
            agent=getattr(tool_context, "agent_name", "") or "",
            tool=tool.name,
            args=tool_args,
            status="tool_error",
            detail=f"{type(error).__name__}: {error}",
        )
        return None

    async def after_model_callback(
        self, *, callback_context: Any, llm_response: "LlmResponse"
    ) -> None:
        usage = getattr(llm_response, "usage_metadata", None)
        if usage is None:
            return None
        payload = {
            "agent": getattr(callback_context, "agent_name", "") or "",
            "invocation_id": getattr(callback_context, "invocation_id", "") or "",
            "prompt_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
            "total_tokens": getattr(usage, "total_token_count", None),
        }
        logger.info("model_usage %s", json.dumps(payload, ensure_ascii=False))
        return None


# 全局单例，供 agent.py（模块级 app）与 cli.py（Runner plugins）复用。
observability_plugin = DevOpsObservabilityPlugin()
