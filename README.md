# LLM-Agent-Learning

记录 LLM、Agent 等 AI 相关知识的学习路径与方法，并配套两个可运行的 Agent 框架对照示例。

## 仓库架构

![仓库架构](assets/architecture.png)

## 目录结构

- `learn/`：学习笔记与精选资料
  - `learn/LLMs/`：大语言模型相关笔记（如 Anthropic Claude 101）
  - `learn/resources.md`：学习路线图与资料汇总（持续更新）
- `projects/`：两个可运行的 Agent 框架对照示例
  - `base_chart_langgraph/`：基于 LangGraph 的 ReAct chatbot 示例
  - `base_workflow_agent/`：基于 google-adk 的多阶段 HITL 工作流示例
  - `requirements.txt`：项目依赖声明
- `AGENTS.md`：面向协作者 / Agent 的仓库约定
- `pyrightconfig.json`：Pyright/Pylance 类型检查与虚拟环境配置

## 示例项目

### 1. base\_chart\_langgraph

基于 **LangGraph** 的 ReAct chatbot 最小示例：

- `StateGraph` 构建 `chatbot ⇄ tools` 循环，由 `tools_condition` 做条件路由
- `MemorySaver` 提供内存检查点（按 `thread_id` 维持多轮上下文）
- 内置工具：`sum_numbers`、`get_current_time`
- 通过 `ChatLiteLLM` 接入豆包（火山方舟）模型
- 入口：`projects/base_chart_langgraph/agent.py`

### 2. base\_workflow\_agent

基于 **google-adk** 的多阶段 Human-in-the-Loop 开发工作流示例：

- 自定义 `WorkflowAgent` 串联 `spec → design → code → test` 四个阶段
- 统一聊天输入确认：用户回复 `OK` 推进下一阶段，给出反馈则带「原始需求 + 上一版产出 + 反馈」重做当前阶段
- 通过 `session.state`（`EventActions.state_delta`）持久化流程状态
- `LocalFileMemoryService` 将记忆落地为本地 JSON 文件，重启不丢失
- 通过 `LiteLlm` 接入豆包（火山方舟）模型
- 入口：`projects/base_workflow_agent/agent.py`

## 环境与运行

要求 **Python >=3.12,<3.13**。依赖与虚拟环境均位于 `projects/` 目录下。

```bash
cd projects
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

在 `projects/` 下创建 `.env` 配置模型与密钥：

```bash
MODEL_NAME=your-model-name
ARK_API_KEY= your-API-Key
```

运行示例：

```bash
# LangGraph 示例
python base_chart_langgraph/agent.py

# google-adk 工作流示例（通过 ADK CLI）
adk run base_workflow_agent
```

