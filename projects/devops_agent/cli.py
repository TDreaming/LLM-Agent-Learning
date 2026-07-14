"""DevOps Agent 命令行入口（交互式控制台）。

两种用法：
- 进入对话界面（默认）：``python -m devops_agent.cli``
  进入后可随时与 Agent 多轮对话，**实时流式**接收输出，并能看到工具调用过程。
  支持内置斜杠命令：/help、/new（新会话）、/clear（清屏）、/exit。
- 单次提问：``python -m devops_agent.cli --prompt "查看 order-service 健康状态"``

底层用 ADK ``Runner`` + ``InMemorySessionService`` 驱动 ``root_agent``，注入持久化
``memory_service`` 与可观测 ``observability_plugin``；开启 SSE 流式以实现实时输出。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from .agent import root_agent
from .memory import memory_service
from .observability import observability_plugin

_APP_NAME = "devops_agent"
_USER_ID = "cli-user"
_EXIT_CMDS = {"/exit", "/quit", "/q", "exit", "quit", "q"}

# 终端配色（不支持时自动降级为空串）。
_C = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "magenta": "\033[35m",
}
if not sys.stdout.isatty():
    _C = {k: "" for k in _C}


def _c(text: str, color: str) -> str:
    return f"{_C.get(color, '')}{text}{_C['reset']}"


_BANNER = f"""{_C['cyan']}{_C['bold']}
╔══════════════════════════════════════════════════════════╗
║            DevOps 智能运维 Agent · 交互式控制台            ║
╚══════════════════════════════════════════════════════════╝{_C['reset']}
{_C['dim']}默认 Mock 数据（只读、不触达真实系统）。危险操作需人工审批。{_C['reset']}

命令：{_C['green']}/help{_C['reset']} 帮助   {_C['green']}/new{_C['reset']} 新会话   {_C['green']}/clear{_C['reset']} 清屏   {_C['green']}/exit{_C['reset']} 退出
示例：查看 order-service 健康状态 / payment-service 最近5分钟延迟 / 回滚 order-service
"""

_HELP = f"""{_C['bold']}可用命令{_C['reset']}
  {_C['green']}/help{_C['reset']}         显示本帮助
  {_C['green']}/new{_C['reset']}          开启新会话（清空当前上下文）
  {_C['green']}/clear{_C['reset']}        清屏
  {_C['green']}/exit{_C['reset']}         退出（也可用 exit/quit/q）

{_C['bold']}使用提示{_C['reset']}
  · 直接输入自然语言即可，例如「gateway 有没有 timeout 报错」
  · 危险操作（如回滚）会先返回审批令牌，回复「批准 <令牌>」才执行，或「拒绝：原因」
"""


async def _stream_turn(runner: Runner, session_id: str, text: str) -> None:
    """运行一轮对话，实时流式打印 Assistant 输出与工具调用提示。"""
    message = types.Content(role="user", parts=[types.Part(text=text)])
    run_config = RunConfig(streaming_mode=StreamingMode.SSE)

    printed_prefix = False
    try:
        async for event in runner.run_async(
            user_id=_USER_ID,
            session_id=session_id,
            new_message=message,
            run_config=run_config,
        ):
            # 工具调用提示（让用户看到 Agent 在做什么）。
            for call in event.get_function_calls():
                print(_c(f"\n  ⚙ 调用工具 {call.name}…", "magenta"))
                printed_prefix = False

            # 文本输出（SSE 下 partial=True 为增量片段，逐片打印实现"实时")。
            if event.content and event.content.parts:
                for part in event.content.parts:
                    txt = getattr(part, "text", None)
                    if txt and not getattr(part, "thought", False):
                        if not printed_prefix:
                            print(_c("Assistant: ", "cyan"), end="")
                            printed_prefix = True
                        print(txt, end="", flush=True)
    except Exception as e:  # noqa: BLE001 - 单轮失败不应退出整个控制台
        print(_c(f"\n[出错] {type(e).__name__}: {e}", "yellow"))
    if printed_prefix:
        print()  # 收尾换行


async def _new_session(session_service: InMemorySessionService) -> str:
    session = await session_service.create_session(app_name=_APP_NAME, user_id=_USER_ID)
    return session.id


async def _interactive() -> None:
    session_service = InMemorySessionService()
    runner = Runner(
        app_name=_APP_NAME,
        agent=root_agent,
        session_service=session_service,
        memory_service=memory_service,
        plugins=[observability_plugin],
    )
    session_id = await _new_session(session_service)

    print(_BANNER)
    while True:
        try:
            user_input = input(_c("You ▸ ", "green")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n" + _c("再见！", "dim"))
            break

        if not user_input:
            continue

        low = user_input.lower()
        if low in _EXIT_CMDS:
            print(_c("再见！", "dim"))
            break
        if low == "/help":
            print(_HELP)
            continue
        if low == "/clear":
            print("\033[2J\033[H", end="")
            print(_BANNER)
            continue
        if low == "/new":
            session_id = await _new_session(session_service)
            print(_c("已开启新会话（上下文已清空）。", "dim"))
            continue

        await _stream_turn(runner, session_id, user_input)


async def _single(prompt: str) -> None:
    session_service = InMemorySessionService()
    runner = Runner(
        app_name=_APP_NAME,
        agent=root_agent,
        session_service=session_service,
        memory_service=memory_service,
        plugins=[observability_plugin],
    )
    session_id = await _new_session(session_service)
    await _stream_turn(runner, session_id, prompt)


def main() -> None:
    parser = argparse.ArgumentParser(description="DevOps 智能运维 Agent CLI")
    parser.add_argument(
        "--prompt",
        "-p",
        default=None,
        help="单次提问内容；不提供则进入交互式对话界面。",
    )
    args = parser.parse_args()
    if args.prompt:
        asyncio.run(_single(args.prompt))
    else:
        asyncio.run(_interactive())


if __name__ == "__main__":
    main()
