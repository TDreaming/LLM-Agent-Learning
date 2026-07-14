"""专家 SubAgent 定义（诊断 / 处置 / 沟通）。

每个 SubAgent：
- 通过 ``LiteLlm`` 接入豆包模型；
- instruction 复用 ``prompts.py`` 的公共片段（安全护栏 + 工具规范）并内嵌
  「Skill 能力目录」（描述/示例/安全要求/何时使用，对齐 kagent A2A skill 元数据）；
- 处置类 Agent 挂载 ``before_tool_guardrail`` 审批门回调。
"""

from __future__ import annotations

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm

from . import skills
from .config import get_model_name
from .guardrails import before_tool_guardrail
from .prompts import common_preamble


def _model() -> LiteLlm:
    return LiteLlm(model=get_model_name())


# ---------------- 诊断 Agent ----------------

diagnostics_agent = Agent(
    model=_model(),
    name="diagnostics_agent",
    description="负责服务健康检查、指标查询与日志检索的诊断专家。",
    instruction=(
        common_preamble()
        + "\n\n你是诊断专家（Diagnostician）。"
        + "\n\n[Skill 能力目录]"
        + "\n- check_service_health(service)：检查服务健康（status/cpu/memory/replicas）。"
        " 例：用户问『order-service 健康吗』→ 调用并解读结果。"
        + "\n- query_metrics(service, metric, window)：查询延迟/QPS/错误率等指标。"
        " 例：『payment-service 最近 5 分钟延迟』。"
        + "\n- search_logs(service, keyword, limit)：检索服务日志。"
        " 例：『gateway 有没有 timeout 报错』。安全要求：均为只读操作，可直接调用。"
        + "\n- ask_user(question, options)：服务名等关键参数缺失或有歧义时先澄清。"
        + "\n\n请综合多个信号给出明确诊断结论与可能根因，不要编造数据。"
    ),
    tools=skills.DIAGNOSTIC_TOOLS,
)


# ---------------- 处置 Agent ----------------

remediation_agent = Agent(
    model=_model(),
    name="remediation_agent",
    description="负责部署状态查询与回滚等处置动作的运维专家（写操作需人工审批）。",
    instruction=(
        common_preamble()
        + "\n\n你是处置专家（Remediator）。"
        + "\n\n[Skill 能力目录]"
        + "\n- get_deploy_status(service)：查询部署状态（当前/上一版本、策略）。只读，可直接调用。"
        + "\n- rollback_deploy(service, target_version, approval_token)：回滚部署。"
        " 安全要求：这是危险写操作，必须先说明影响范围；首次调用会被审批门拦截并返回"
        " approval_token；只有在用户明确回复『批准 <token>』后，才携带该 token 再次调用执行。"
        " 若用户拒绝，请据其理由调整建议，切勿重复尝试。"
        + "\n- ask_user(question, options)：参数缺失或需确认时先澄清。"
        + "\n\n未获批准前严禁声称已执行任何写操作。"
    ),
    tools=skills.REMEDIATION_TOOLS,
    before_tool_callback=before_tool_guardrail,
)


# ---------------- 沟通 Agent ----------------

communicator_agent = Agent(
    model=_model(),
    name="communicator_agent",
    description="负责把诊断/处置过程整理成结构化事件摘要与后续建议。",
    instruction=(
        common_preamble()
        + "\n\n你是沟通专家（Communicator）。"
        + "\n\n[Skill 能力目录]"
        + "\n- 基于上文的诊断与处置结果，产出结构化【事件摘要】：包含 现象 / 影响范围 /"
        " 根因（如有）/ 已采取动作 / 后续建议 五个部分。"
        + "\n- get_current_time()：需要时间戳时调用。"
        + "\n- ask_user(question, options)：信息不足时澄清。"
        + "\n\n输出要简洁专业，面向值班 SRE 与相关方，不要堆砌原始 JSON。"
    ),
    tools=skills.COMMUNICATION_TOOLS,
)


SUB_AGENTS = [diagnostics_agent, remediation_agent, communicator_agent]
