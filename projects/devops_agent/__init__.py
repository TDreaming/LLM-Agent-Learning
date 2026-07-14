"""DevOps 智能运维 Agent 包。

基于 google-adk 实现的企业级智能运维（AIOps/SRE）参考 Agent：
- Supervisor 根 Agent + 诊断/处置/沟通 三个专家 SubAgent；
- 端口-适配器解耦的运维 Skill（默认 Mock 只读后端）；
- 生产级安全护栏（危险操作人审批门 + 审计 + 预算）；
- 跨会话持久化记忆；可选 MCP 工具集成；
- 同时支持 CLI（`adk run` / `cli.py`）与对话式 Web（`adk web`）。

遵循 ADK 约定：暴露模块级 `agent` 与 `memory_service`，供 CLI/Runner 自动加载与注入。
"""

from . import agent
