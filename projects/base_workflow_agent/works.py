"""多阶段开发工作流（spec → design → code → test），每阶段后用户确认。

设计原则：
1. **统一聊天输入**：不使用 RequestInput，确认通过主聊天输入完成（用户回复 OK / 反馈）。
2. **驳回回退**：用户给出反馈时，把 "原始要求 + 上一版产出 + 用户反馈" 一起送回当前阶段重做。
3. **OK 自动推进**：用户回复 OK 后，下一轮 invocation 会自动进入下一个阶段，直到全部完成。

状态约定（写入 session.state）：
- `pipeline.stage`            : 当前阶段名 spec/design/code/test/done
- `pipeline.phase`            : "running" | "awaiting_confirm"
- `pipeline.original_request` : 用户最初的需求原文
- `pipeline.<stage>.output`   : 各阶段最近一次产出
- `pipeline.<stage>.feedback` : 上次用户给出的修改反馈（可空）
"""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk import Agent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.load_memory_tool import load_memory_tool
from google.adk.tools.preload_memory_tool import preload_memory_tool
from google.genai import types

from .base import get_model_name

_MEMORY_TOOLS = [preload_memory_tool, load_memory_tool]

STAGES = ["spec", "design", "code", "test"]
STAGE_TITLES = {"spec": "需求", "design": "设计", "code": "开发", "test": "测试"}

_APPROVE_KEYWORDS = {"ok", "yes", "y", "通过", "确认", "好", "approve", "同意"}


# ---------------- 各阶段 LLM Agent ----------------

def _build_stage_agent(name: str, description: str, instruction: str) -> Agent:
    return Agent(
        model=LiteLlm(model=get_model_name()),
        name=name,
        description=description,
        instruction=(
            instruction
            + "\n\n你将在 user message 中收到结构化输入：原始需求、上一版产出（若有）、用户反馈（若有）。"
            + "\n如果存在用户反馈，请认真采纳后重新生成本阶段产出；否则按原始需求生成。"
            + "\n直接输出本阶段的最终成果，不要解释。"
        ),
        tools=_MEMORY_TOOLS,
    )


spec_agent = _build_stage_agent(
    "spec_agent",
    "根据用户输入制定详细的需求文档（功能、性能、成本等）",
    "你是需求分析师。请基于用户输入产出一份完整的需求文档。",
)
design_agent = _build_stage_agent(
    "design_agent",
    "根据需求产出系统架构、模块、数据库设计等",
    "你是系统设计师。请基于需求文档产出系统架构、功能模块、数据库设计等设计文档。",
)
code_agent = _build_stage_agent(
    "code_agent",
    "根据设计文档产出代码",
    "你是开发工程师。请基于设计文档输出可运行的代码（合理使用伪代码可），按文件分块呈现。",
)
test_agent = _build_stage_agent(
    "test_agent",
    "根据代码产出测试用例与结论",
    "你是测试工程师。请基于代码产出测试用例并给出测试结论。",
)

_STAGE_AGENTS: dict[str, Agent] = {
    "spec": spec_agent,
    "design": design_agent,
    "code": code_agent,
    "test": test_agent,
}


# ---------------- 工具：构造给阶段 agent 的输入 ----------------

def _build_stage_user_message(state: dict, stage: str) -> str:
    original = state.get("pipeline.original_request", "")
    last_output = state.get(f"pipeline.{stage}.output", "")
    feedback = state.get(f"pipeline.{stage}.feedback", "")

    parts = [f"【原始需求】\n{original}"]
    # 把上一阶段的产出也带上，便于当前阶段衔接
    idx = STAGES.index(stage)
    if idx > 0:
        prev = STAGES[idx - 1]
        prev_out = state.get(f"pipeline.{prev}.output", "")
        if prev_out:
            parts.append(f"【上一阶段（{STAGE_TITLES[prev]}）产出】\n{prev_out}")
    if last_output:
        parts.append(f"【本阶段上一版产出】\n{last_output}")
    if feedback:
        parts.append(f"【用户反馈（请采纳并改进）】\n{feedback}")
    return "\n\n".join(parts)


def _latest_user_text(ctx: InvocationContext) -> str:
    """从 session 中取最近一条 user 消息的纯文本。"""
    for ev in reversed(ctx.session.events):
        if ev.author == "user" and ev.content and ev.content.parts:
            for p in ev.content.parts:
                if getattr(p, "text", None):
                    return p.text.strip()
    return ""


def _is_approval(text: str) -> bool:
    return text.strip().lower() in _APPROVE_KEYWORDS


def _make_text_event(author: str, text: str, state_delta: dict | None = None) -> Event:
    return Event(
        author=author,
        content=types.Content(role="model", parts=[types.Part(text=text)]),
        actions=EventActions(state_delta=state_delta or {}),
    )


# ---------------- 根 Agent：驱动整个 pipeline ----------------

class WorkflowAgent(BaseAgent):
    """统一聊天输入的多阶段 pipeline 控制器。"""

    async def _run_async_impl(  # type: ignore[override]
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = dict(ctx.session.state)  # 只读快照，写回通过 EventActions.state_delta
        user_text = _latest_user_text(ctx)
        phase = state.get("pipeline.phase")
        stage = state.get("pipeline.stage")

        # ===== 1) 首次进入：记录原始需求，从 spec 阶段开始 =====
        if not phase or stage == "done":
            if not user_text:
                yield _make_text_event(self.name, "请先输入你的需求。")
                return

            state_delta = {
                "pipeline.original_request": user_text,
                "pipeline.stage": "spec",
                "pipeline.phase": "running",
                # 清空旧记录
                **{f"pipeline.{s}.output": "" for s in STAGES},
                **{f"pipeline.{s}.feedback": "" for s in STAGES},
            }
            yield _make_text_event(
                self.name,
                f"已记录需求，开始执行【{STAGE_TITLES['spec']}】阶段……",
                state_delta=state_delta,
            )
            # 立即跑 spec
            async for ev in self._run_stage(ctx, "spec"):
                yield ev
            return

        # ===== 2) 等待用户确认中：解析用户回复 =====
        if phase == "awaiting_confirm" and stage in STAGES:
            if not user_text:
                yield _make_text_event(
                    self.name,
                    f"等待你对【{STAGE_TITLES[stage]}】阶段的反馈：回复 OK 继续，或给出修改意见。",
                )
                return

            if _is_approval(user_text):
                # 通过：清空反馈，进入下一阶段
                idx = STAGES.index(stage)
                if idx + 1 >= len(STAGES):
                    # 全部完成
                    delta = {
                        "pipeline.stage": "done",
                        "pipeline.phase": "completed",
                    }
                    yield _make_text_event(
                        self.name,
                        "✅ 全部阶段已完成，工作流结束。\n\n"
                        + self._summarize(state),
                        state_delta=delta,
                    )
                    return

                next_stage = STAGES[idx + 1]
                delta = {
                    f"pipeline.{stage}.feedback": "",
                    "pipeline.stage": next_stage,
                    "pipeline.phase": "running",
                }
                yield _make_text_event(
                    self.name,
                    f"✅【{STAGE_TITLES[stage]}】通过，进入【{STAGE_TITLES[next_stage]}】阶段……",
                    state_delta=delta,
                )
                async for ev in self._run_stage(ctx, next_stage):
                    yield ev
                return

            # 驳回：把反馈写入当前阶段，重新执行
            delta = {
                f"pipeline.{stage}.feedback": user_text,
                "pipeline.phase": "running",
            }
            yield _make_text_event(
                self.name,
                f"已收到反馈，将基于反馈重新生成【{STAGE_TITLES[stage]}】阶段……",
                state_delta=delta,
            )
            async for ev in self._run_stage(ctx, stage):
                yield ev
            return

        # ===== 3) 异常状态兜底 =====
        yield _make_text_event(
            self.name,
            f"内部状态异常：phase={phase}, stage={stage}，已重置。请重新输入需求开始。",
            state_delta={"pipeline.stage": "done", "pipeline.phase": "completed"},
        )

    # ---------------- 单阶段执行 ----------------

    async def _run_stage(
        self, ctx: InvocationContext, stage: str
    ) -> AsyncGenerator[Event, None]:
        """执行一个阶段的 LLM agent，把产出落到 state，并进入 awaiting_confirm。"""
        agent = _STAGE_AGENTS[stage]
        # 从最新 state（含本轮已经 yield 的 delta）拉取上下文
        state = dict(ctx.session.state)
        user_msg = _build_stage_user_message(state, stage)

        # 直接调用子 agent 的 run_async；它会读取 ctx.user_content / 历史
        # 我们这里需要把 user_msg 注入为 user content：通过临时改 ctx.user_content。
        original_user_content = ctx.user_content
        ctx.user_content = types.Content(
            role="user", parts=[types.Part(text=user_msg)]
        )
        try:
            stage_output_chunks: list[str] = []
            async for ev in agent.run_async(parent_context=ctx):
                # 收集 agent 的最终文本输出，便于落 state
                if ev.content and ev.content.parts:
                    for p in ev.content.parts:
                        if getattr(p, "text", None) and not getattr(p, "thought", False):
                            stage_output_chunks.append(p.text)
                yield ev
        finally:
            ctx.user_content = original_user_content

        stage_output = "".join(stage_output_chunks).strip()

        # 阶段结束 → 写入 state，并提示用户确认
        delta = {
            f"pipeline.{stage}.output": stage_output,
            "pipeline.phase": "awaiting_confirm",
            "pipeline.stage": stage,
        }
        yield _make_text_event(
            self.name,
            (
                f"【{STAGE_TITLES[stage]}】阶段完成 ✅\n\n"
                f"请审核以上产出：\n"
                f"  • 回复 OK / 通过 → 进入下一阶段\n"
                f"  • 否则给出修改意见 → 我会根据反馈重做该阶段"
            ),
            state_delta=delta,
        )

    @staticmethod
    def _summarize(state: dict) -> str:
        lines = ["## 工作流产出汇总"]
        for s in STAGES:
            out = state.get(f"pipeline.{s}.output", "")
            lines.append(f"\n### {STAGE_TITLES[s]}\n{out or '(空)'}")
        return "\n".join(lines)


# ---------------- 对外入口 ----------------

def get_root_agent() -> BaseAgent:
    return WorkflowAgent(
        name="root_agent",
        description="多阶段开发工作流，每阶段后等待用户在主输入框确认或反馈。",
        sub_agents=[spec_agent, design_agent, code_agent, test_agent],
    )
