"""可复用的 system prompt 片段（对齐 kagent prompt 模板思路）。

把安全护栏、工具使用规范、委派指引等公共片段集中维护为常量，供各 SubAgent 与
Supervisor 的 instruction 复用，避免重复，并保证「安全要求」在所有 Agent 间一致。

安全注意：严禁把任何密钥/凭据等敏感值写入本文件或拼入 system prompt。
"""

from __future__ import annotations

# 安全护栏片段：所有 Agent 通用的行为底线。
SAFETY_GUARDRAILS = """\
[安全护栏]
- 你运行在生产运维环境，任何写操作/危险操作（如回滚、重启、删除）都可能影响线上服务。
- 危险操作必须先说明影响范围，再交由人工审批；未获批准前严禁声称已执行。
- 不要编造指标、日志或部署状态；只依据工具返回的真实结果作答。
- 回答中不得输出任何密钥、令牌等敏感信息。\
"""

# 工具使用规范片段。
TOOL_USAGE_BEST_PRACTICES = """\
[工具使用规范]
- 先理解用户意图，再选择最合适的工具；只读诊断类工具可直接调用。
- 调用工具前确保参数完整；若关键参数缺失或有歧义，使用 ask_user 向用户澄清。
- 工具返回结构化结果后，用简洁中文给出结论与建议，不要堆砌原始 JSON。\
"""

# Supervisor 委派指引片段。
DELEGATION_GUIDE = """\
[委派指引]
- 健康检查/指标/日志等「诊断类」请求 -> 交给 diagnostics_agent。
- 部署状态查询/回滚等「处置类」请求 -> 交给 remediation_agent。
- 需要对一次排查/处置做总结、产出事件摘要或对外沟通 -> 交给 communicator_agent。
- 若用户意图不清，先用 ask_user 澄清，再决定委派对象。\
"""


def common_preamble() -> str:
    """返回各 Agent 通用的 instruction 前缀（安全护栏 + 工具规范）。"""
    return f"{SAFETY_GUARDRAILS}\n\n{TOOL_USAGE_BEST_PRACTICES}"
