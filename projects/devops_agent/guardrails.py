"""安全护栏与人审批门（Guardrails & HITL Approval Gate）。

基于 ADK 的 ``before_tool_callback`` 实现生产级护栏（对齐 kagent requireApproval /
ADK Safety 最佳实践）：

1. 预算保护：限制单次会话的工具调用次数上限，防止失控循环烧 token。
2. 审批门：危险/写操作（``skills.DANGEROUS_TOOLS``）默认拦截：
   - 首次调用 -> 发放审批令牌并返回「待审批」结果，不执行真实动作；
   - 用户批准后，模型携带相同 ``approval_token`` 再次调用 -> 放行执行；
   - 用户拒绝（带理由）-> 把拒绝理由作为上下文回传 LLM，且不执行。
3. 审计：每次工具调用（放行/拦截/拒绝）都写结构化日志与审计文件。

返回非 None 的 dict 会让 ADK 跳过真实工具执行并把该 dict 作为工具结果。
"""

from __future__ import annotations

import hashlib
from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from .config import settings
from .observability import log_tool_call
from .skills import DANGEROUS_TOOLS

# session.state 中用于护栏的键。
_STATE_TOOL_CALLS = "guardrail.tool_calls"
_STATE_APPROVALS = "guardrail.approved_tokens"  # 已批准的令牌列表
_STATE_REJECTIONS = "guardrail.rejections"  # 已拒绝的 (token -> reason)


def _approval_token(tool_name: str, args: dict[str, Any]) -> str:
    """根据工具名 + 关键参数生成稳定的审批令牌。"""
    seed = tool_name + "|" + "|".join(
        f"{k}={args[k]}" for k in sorted(args) if k != "approval_token"
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def before_tool_guardrail(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> dict[str, Any] | None:
    """工具执行前护栏回调。返回 dict 表示拦截，返回 None 表示放行。"""
    state = tool_context.state
    invocation_id = getattr(tool_context, "invocation_id", "") or ""
    agent_name = getattr(tool_context, "agent_name", "") or ""
    tool_name = tool.name

    # ---------- 1) 预算保护 ----------
    calls = int(state.get(_STATE_TOOL_CALLS, 0)) + 1
    state[_STATE_TOOL_CALLS] = calls
    if calls > settings.max_tool_calls:
        log_tool_call(
            invocation_id=invocation_id,
            agent=agent_name,
            tool=tool_name,
            args=args,
            status="blocked_budget",
        )
        return {
            "status": "blocked",
            "reason": "budget_exceeded",
            "message": (
                f"已达到单次会话工具调用上限（{settings.max_tool_calls}），"
                "为防止失控已停止后续工具调用。请缩小范围或重新开始会话。"
            ),
        }

    # ---------- 2) 审批门（仅对危险/写操作）----------
    if settings.require_approval and tool_name in DANGEROUS_TOOLS:
        token = _approval_token(tool_name, args)
        provided = args.get("approval_token")

        # 已被拒绝：把拒绝理由作为上下文回传给 LLM，不执行。
        rejections = dict(state.get(_STATE_REJECTIONS, {}))
        if token in rejections:
            reason = rejections[token]
            log_tool_call(
                invocation_id=invocation_id,
                agent=agent_name,
                tool=tool_name,
                args=args,
                status="rejected",
                detail=reason,
            )
            return {
                "status": "rejected",
                "reason": reason,
                "message": (
                    f"用户已拒绝该操作，理由：{reason}。"
                    "请勿再次尝试执行，请据此调整你的建议。"
                ),
            }

        approved = list(state.get(_STATE_APPROVALS, []))
        if provided and provided == token and token in approved:
            # 已批准且令牌匹配：放行执行。
            log_tool_call(
                invocation_id=invocation_id,
                agent=agent_name,
                tool=tool_name,
                args=args,
                status="approved_exec",
            )
            return None

        # 首次命中：登记待审批，返回审批令牌，不执行。
        log_tool_call(
            invocation_id=invocation_id,
            agent=agent_name,
            tool=tool_name,
            args=args,
            status="pending_approval",
            detail=token,
        )
        return {
            "status": "pending_approval",
            "approval_token": token,
            "tool": tool_name,
            "args": {k: v for k, v in args.items() if k != "approval_token"},
            "message": (
                f"危险操作 `{tool_name}` 需要人工审批。请向用户清晰说明影响范围，"
                f"并请用户回复「批准 {token}」以放行，或「拒绝：<理由>」以取消。"
                "未获批准前严禁声称已执行。"
            ),
        }

    # ---------- 3) 普通只读工具：放行并审计 ----------
    log_tool_call(
        invocation_id=invocation_id,
        agent=agent_name,
        tool=tool_name,
        args=args,
        status="allowed",
    )
    return None


# =========================== 审批状态操作（供 CLI/上层调用）===========================


def grant_approval(state: Any, token: str) -> None:
    """把某审批令牌标记为已批准（写入 session.state）。"""
    approved = list(state.get(_STATE_APPROVALS, []))
    if token not in approved:
        approved.append(token)
    state[_STATE_APPROVALS] = approved


def reject_approval(state: Any, token: str, reason: str) -> None:
    """把某审批令牌标记为已拒绝，并记录理由。"""
    rejections = dict(state.get(_STATE_REJECTIONS, {}))
    rejections[token] = reason or "未提供理由"
    state[_STATE_REJECTIONS] = rejections
