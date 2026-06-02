from typing import Annotated

from typing_extensions import TypedDict

from langgraph.graph import StateGraph,START,END
from langgraph.graph.message import add_messages
from langchain_litellm import ChatLiteLLM
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

from env import MODEL_NAME, ARK_API_KEY
from m_tool import sum_numbers, get_current_time



class State(TypedDict):
    # Messages have the type "list". The `add_messages` function
    # 在注释中定义了该状态键应如何更新。
    # （在这种情况下，它将消息附加到列表中，而不是覆盖它们）
    messages: Annotated[list, add_messages]

graph_builder = StateGraph(State)

tools = [sum_numbers, get_current_time]
llm = ChatLiteLLM(model=MODEL_NAME, api_key=ARK_API_KEY)
llm = llm.bind_tools(tools)

def chartbot(state: State) -> State:
    return {"messages": [llm.invoke(state["messages"])]}

# 第一个参数是唯一的节点名称。
# 第二个参数是将在每次调用时使用的函数或对象。
# 节点正在被使用。
graph_builder.add_node(chartbot)
graph_builder.add_edge(START, "chartbot")

tool_node = ToolNode(tools=tools)
graph_builder.add_node("tools", tool_node)

graph_builder.add_conditional_edges(
    "chartbot",
    tools_condition,
)
graph_builder.add_edge("tools", "chartbot")

memory = MemorySaver()
graph = graph_builder.compile(checkpointer=memory)


def stream_graph_updates(user_input: str):
    config: RunnableConfig = {"configurable": {"thread_id": "1"}}
    for event in graph.stream({"messages": [("user", user_input)]}, config):
        for value in event.values():
            print("Assistant:", value["messages"][-1].content)


while True:
    try:
        user_input = input("User: ")
        if user_input.lower() in ["quit", "exit", "q"]:
            print("Goodbye!")
            break

        stream_graph_updates(user_input)
    except:
        # 如果 input() 不可用，则备选方案。
        user_input = "What do you know about LangGraph?"
        print("User: " + user_input)
        stream_graph_updates(user_input)
        break