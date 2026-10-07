import sys
import os
from typing import Union, Annotated

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    AIMessage, ToolMessage, HumanMessage, SystemMessage, RemoveMessage,
)
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages, REMOVE_ALL_MESSAGES
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import StrictStr

from AIchat.MCPcall.mcpcall import get_langchain_tools
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL


# ==================== 模型配置 ====================
ds = ChatOpenAI(
    api_key=StrictStr(LLM_API_KEY),
    base_url=LLM_BASE_URL,
    model=LLM_MODEL,
    temperature=0.3,
    timeout=300,
)

# 摘要用模型（可与主模型相同）
summary_model = ds


# ==================== 常量配置 ====================
WINDOW_ROUNDS = 10  # 滑动窗口：保留最近 N 轮完整对话
SUMMARY_MERGE_THRESHOLD = 20  # 摘要列表超过此长度时合并最早几条
SUMMARY_MERGE_KEEP = 10  # 合并时保留最近 N 条

BASE_SYSTEM_PROMPT = (
    "数据助手，帮助用户提取数据库里边的数据，根据返还的数据进行回答。"
    "如果没有数据则输出：数据库中没有相关数据。"
    "说明你查询了哪个库，说明查询到的结果。"
)


# ==================== State 定义 ====================
def append_reducer(left: list, right: list) -> list:
    """列表追加 reducer：用于 summary_list，支持增量合并"""
    if left is None:
        left = []
    if right is None:
        right = []
    return left + right


from typing import TypedDict


class GraphState(TypedDict):
    # 工作记忆：窗口内完整原始对话消息（含 HumanMessage/AIMessage/ToolMessage）
    # 使用 add_messages reducer，节点返回的消息会被追加
    messages: Annotated[list, add_messages]
    # 情节记忆：历史摘要列表，使用 append_reducer 追加新摘要
    summary_list: Annotated[list, append_reducer]


# ==================== 轮次分组与摘要辅助函数 ====================
def group_into_rounds(messages):
    """
    将消息列表按用户轮次分组（跳过 SystemMessage）。
    一轮 = 一个 HumanMessage 及其后续所有非 HumanMessage 消息。
    """
    rounds = []
    current_round = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            # SystemMessage（如摘要）不参与轮次计数
            continue
        if isinstance(msg, HumanMessage):
            if current_round:
                rounds.append(current_round)
            current_round = [msg]
        else:
            if current_round:
                current_round.append(msg)
    if current_round:
        rounds.append(current_round)
    return rounds


def flatten_rounds(rounds):
    """将轮次列表展平为消息列表"""
    result = []
    for rnd in rounds:
        result.extend(rnd)
    return result


def format_summary_list(summary_list):
    """将摘要列表格式化为 SystemMessage 文本"""
    if not summary_list:
        return ""
    block = "【历史对话摘要汇总】\n"
    for i, s in enumerate(summary_list, 1):
        block += f"{i}. {s}\n"
    block += "\n【当前对话】"
    return block


def messages_to_text(messages):
    """
    将消息对象列表转为纯自然语言文本（移除所有消息结构与 tool_calls 字段）。
    摘要模型接收纯字符串，避免工具调用结构混入导致协议报错。
    """
    lines = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            lines.append(f"用户: {msg.content}")
        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    lines.append(f"AI动作: 调用工具「{tc['name']}」，参数: {tc.get('args', {})}")
            if msg.content:
                lines.append(f"AI回答: {msg.content}")
        elif isinstance(msg, ToolMessage):
            lines.append(f"工具返回: {msg.content}")
    return "\n".join(lines)


# ==================== 节点 1: memory_compress（记忆压缩节点）====================
async def memory_compress(state: GraphState):
    """
    图入口第一个节点，每轮用户输入仅执行一次。
    - 按轮次分组，超过 WINDOW_ROUNDS 时压缩旧轮次
    - 旧轮次转为纯文本 → LLM 生成摘要 → append 到 summary_list
    - 重构 messages = [摘要 SystemMessage] + 最近 WINDOW_ROUNDS 轮原始消息
    """
    messages = state.get("messages", [])
    summary_list = state.get("summary_list", []) or []

    # 跳过 SystemMessage 后按轮次分组
    rounds = group_into_rounds(messages)
    print(rounds)

    if len(rounds) <= WINDOW_ROUNDS:
        # 未超过窗口，不压缩
        return {}

    print(f"[memory_compress] 轮次 {len(rounds)} > {WINDOW_ROUNDS}，开始压缩")

    # 拆分：旧轮次（待摘要）+ 最近 WINDOW_ROUNDS 轮（保留）
    old_rounds = rounds[:-WINDOW_ROUNDS]
    recent_rounds = rounds[-WINDOW_ROUNDS:]

    old_messages = flatten_rounds(old_rounds)
    if not old_messages:
        return {}

    # 旧消息转纯文本，调用摘要模型
    conversation_text = messages_to_text(old_messages)
    prompt = (
        "请阅读以下对话历史，生成一份简洁的摘要。"
        "摘要只需包含：用户问题、AI执行的动作（调用了什么工具、查询了什么）、AI的回答。\n\n"
        f"对话历史：\n{conversation_text}\n\n"
        "用简洁的自然语言输出摘要："
    )

    try:
        summary_resp = await summary_model.ainvoke([HumanMessage(content=prompt)])
        new_summary = summary_resp.content if summary_resp.content else None
    except Exception as e:
        print(f"[memory_compress] 摘要失败: {e}")
        return {}

    if not new_summary:
        return {}

    # 摘要列表防膨胀：超过阈值时合并最早几条
    updated_summary_list = summary_list + [new_summary]
    if len(updated_summary_list) > SUMMARY_MERGE_THRESHOLD:
        merge_count = len(updated_summary_list) - SUMMARY_MERGE_KEEP
        to_merge = updated_summary_list[:merge_count]
        kept = updated_summary_list[merge_count:]
        merged_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(to_merge))
        merge_prompt = (
            "请将以下多条对话摘要合并为一条连贯的总摘要，保留关键信息：\n"
            f"{merged_text}\n\n合并后的摘要："
        )
        try:
            merge_resp = await summary_model.ainvoke([HumanMessage(content=merge_prompt)])
            merged_summary = merge_resp.content if merge_resp.content else to_merge[0]
        except Exception:
            merged_summary = to_merge[0]
        updated_summary_list = [merged_summary] + kept
        print(f"[memory_compress] 摘要合并: {len(summary_list)+1} -> {len(updated_summary_list)} 条")

    # 重构 messages：摘要 SystemMessage + 最近轮次原始消息
    summary_text = format_summary_list(updated_summary_list)
    recent_messages = flatten_rounds(recent_rounds)
    new_messages = []
    if summary_text:
        new_messages.append(SystemMessage(content=summary_text))
    new_messages.extend(recent_messages)

    # messages 用 RemoveMessage 清空后重建；summary_list 用 append_reducer 追加
    # 由于 summary_list 使用 append reducer，这里只返回新增的摘要
    new_summary_entries = [new_summary] if updated_summary_list == summary_list + [new_summary] else updated_summary_list

    return {
        "messages": [RemoveMessage(REMOVE_ALL_MESSAGES)] + new_messages,
        "summary_list": new_summary_entries,
    }


# ==================== 节点 2: call_llm（LLM 推理节点）====================
def call_llm(state: GraphState, model, tools: list):
    """
    LLM 推理节点：
    - 注入基础业务系统提示（头部）
    - state.messages 已包含摘要 SystemMessage + 窗口内原始对话
    - 绑定 MCP 工具，调用模型
    """
    messages = state.get("messages", [])

    # 固定顺序：[基础系统提示] + [摘要系统提示 + 窗口内对话]
    full_messages = [SystemMessage(content=BASE_SYSTEM_PROMPT)] + list(messages)

    model_with_tools = model.bind_tools(tools)
    response = model_with_tools.invoke(full_messages)
    return {"messages": [response]}


# ==================== 节点 3: call_mcp_tool（MCP 工具执行节点）====================
async def call_mcp_tool(state: GraphState, tools: list):
    """
    MCP 工具执行节点：
    - 解析最后一条 AIMessage 的 tool_calls
    - 执行对应工具
    - 返回 ToolMessage
    异常时生成错误 ToolMessage，保证消息结构配对。
    """
    tool_node = ToolNode(tools)
    try:
        result = await tool_node.ainvoke(state)
        return result
    except Exception as e:
        print(f"[call_mcp_tool] 工具执行异常: {e}")
        # 生成错误 ToolMessage，保证链路闭环
        last_msg = state["messages"][-1]
        error_tools = []
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                error_tools.append(ToolMessage(
                    content=f"工具执行失败: {str(e)}",
                    tool_call_id=tc["id"],
                    name=tc.get("name", ""),
                ))
        return {"messages": error_tools}


# ==================== 图构建 ====================
async def build_graph_agent(mcp_input: Union[str, list, dict], thread_id: str):
    """
    构建 LangGraph StateGraph Agent。
    mcp_input 支持：
      - str: 单个 MCP URL
      - list[str]: 多个 MCP URL
      - list[dict]: [{"url": ..., "transport": ...}, ...]
      - dict: {"url": ..., "transport": ...}
    """
    # 规范化为列表
    if isinstance(mcp_input, str):
        mcp_list = [{"url": mcp_input, "transport": "http"}]
    elif isinstance(mcp_input, dict):
        mcp_list = [mcp_input]
    else:
        mcp_list = []
        for item in mcp_input:
            if isinstance(item, str):
                mcp_list.append({"url": item, "transport": "http"})
            else:
                mcp_list.append(item)

    all_tools = []
    for cfg in mcp_list:
        url = cfg.get("url", "")
        transport = cfg.get("transport", "http")
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        try:
            tools = await get_langchain_tools(url, transport)
            all_tools.extend(tools)
            print(f"MCP[{url}] 加载 {len(tools)} 个工具")
        except Exception as e:
            print(f"MCP[{url}] 连接失败: {e}")
    print(f"合并后总工具数量：{len(all_tools)}")

    # 构建图
    graph = StateGraph(GraphState)

    # 节点函数闭包（捕获 tools/model，避免 lambda 包装 async 函数的问题）
    async def node_call_llm(state: GraphState):
        return call_llm(state, ds, all_tools)

    async def node_call_mcp_tool(state: GraphState):
        return await call_mcp_tool(state, all_tools)

    # 添加节点
    graph.add_node("memory_compress", memory_compress)
    graph.add_node("call_llm", node_call_llm)
    graph.add_node("call_mcp_tool", node_call_mcp_tool)

    # 固定边
    graph.add_edge(START, "memory_compress")
    graph.add_edge("memory_compress", "call_llm")

    # 条件边：call_llm 出口判断是否需要调用工具
    graph.add_conditional_edges(
        "call_llm",
        tools_condition,
        {
            "tools": "call_mcp_tool",
            END: END,
        },
    )

    # 工具执行完回到 LLM（工具循环闭环，不经过 memory_compress）
    graph.add_edge("call_mcp_tool", "call_llm")

    # Checkpoint 持久化
    checkpointer = InMemorySaver()
    config = {"configurable": {"thread_id": thread_id}}

    app = graph.compile(checkpointer=checkpointer)
    return app, config
