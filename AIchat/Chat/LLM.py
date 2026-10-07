import sys
import os
from operator import add as list_add
from typing import Union, Annotated, TypedDict

# 将项目根目录加入 sys.path，兼容直接运行脚本（python LLM.py）和模块导入两种方式
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    AIMessage, ToolMessage, HumanMessage, SystemMessage, RemoveMessage,
)
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages, REMOVE_ALL_MESSAGES
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import StrictStr

from AIchat.MCPcall.mcpcall import get_langchain_tools
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL


ds = ChatOpenAI(
    api_key=StrictStr(LLM_API_KEY),
    base_url=LLM_BASE_URL,
    model=LLM_MODEL,
    temperature=0.3,
    timeout=300,
)


def count_tokens_approximately(text) -> int:
    """
    修正版token估算：支持消息列表/消息对象/字符串
    包含工具调用、工具返回结果的附加token估算，更贴近真实值
    """
    if isinstance(text, list):
        total = 0
        for msg in text:
            total += count_tokens_approximately(msg)
        return total

    # 提取正文内容：兼容纯字符串 / 消息对象 / 其他对象
    if isinstance(text, str):
        content = text
    elif hasattr(text, "content"):
        content = text.content if text.content else ""
    else:
        content = str(text) if text else ""

    # 工具调用结构附加token
    tool_extra = 0
    if isinstance(text, AIMessage) and text.tool_calls:
        tool_extra = len(text.tool_calls) * 80

    # 工具返回消息附加token
    if isinstance(text, ToolMessage):
        tool_extra = 40

    # 正文token计算：兼容 content 为列表（多模态）的情况
    if isinstance(content, list):
        base = 0
        for part in content:
            if isinstance(part, dict):
                text_part = part.get("text", "")
                if isinstance(text_part, str) and text_part.strip():
                    chinese_chars = sum(1 for c in text_part if '\u4e00' <= c <= '\u9fff')
                    other_chars = len(text_part) - chinese_chars
                    base += chinese_chars * 2 + other_chars / 4
            elif isinstance(part, str) and part.strip():
                chinese_chars = sum(1 for c in part if '\u4e00' <= c <= '\u9fff')
                other_chars = len(part) - chinese_chars
                base += chinese_chars * 2 + other_chars / 4
    elif not isinstance(content, str) or len(content.strip()) == 0:
        base = 0
    else:
        chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
        other_chars = len(content) - chinese_chars
        base = chinese_chars * 2 + other_chars / 4

    return round(base + tool_extra)


# 滑动窗口大小：保留最近 N 轮完整对话（一轮 = 用户消息 + 工具调用 + 助手回答）
WINDOW_ROUNDS = 10

BASE_SYSTEM_PROMPT = (
    "数据助手，帮助用户提取数据库里边的数据，根据返还的数据进行回答。"
    "如果没有数据则输出：数据库中没有相关数据。"
    "说明你查询了哪个库，说明查询到的结果。"
)


# ==================== State 定义 ====================
class GraphState(TypedDict):
    # 工作记忆：窗口内完整对话消息，使用 add_messages reducer 追加
    messages: Annotated[list, add_messages]
    # 情节记忆：历史摘要列表，使用 list_add reducer 追加新摘要
    summary_list: Annotated[list, list_add]


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
            # 摘要 SystemMessage 不参与轮次计数
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
    将消息对象列表转为纯自然语言文本（去除工具调用结构）。
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
    - 旧轮次转纯文本 → LLM 生成摘要 → append 到 summary_list
    - 重构 messages = [摘要 SystemMessage] + 最近 WINDOW_ROUNDS 轮原始消息
    """
    messages = state.get("messages", [])
    summary_list = state.get("summary_list", []) or []

    rounds = group_into_rounds(messages)
    if len(rounds) <= WINDOW_ROUNDS:
        # 未超过窗口，不压缩
        return {}

    print(f"[memory_compress] 轮次 {len(rounds)} > {WINDOW_ROUNDS}，开始压缩")

    old_rounds = rounds[:-WINDOW_ROUNDS]
    recent_rounds = rounds[-WINDOW_ROUNDS:]
    old_messages = flatten_rounds(old_rounds)
    if not old_messages:
        return {}

    conversation_text = messages_to_text(old_messages)
    prompt = (
        "请阅读以下对话历史，生成一份简洁的摘要。"
        "摘要只需包含：用户问题、AI执行的动作（调用了什么工具、查询了什么）、AI的回答。\n\n"
        f"对话历史：\n{conversation_text}\n\n"
        "用简洁的自然语言输出摘要："
    )

    try:
        summary_resp = await ds.ainvoke([HumanMessage(content=prompt)])
        new_summary = summary_resp.content if summary_resp.content else None
    except Exception as e:
        print(f"[memory_compress] 摘要失败: {e}")
        return {}

    if not new_summary:
        return {}

    updated_summary_list = summary_list + [new_summary]
    summary_text = format_summary_list(updated_summary_list)
    recent_messages = flatten_rounds(recent_rounds)

    new_messages = []
    if summary_text:
        new_messages.append(SystemMessage(content=summary_text))
    new_messages.extend(recent_messages)

    # messages 用 RemoveMessage 清空后重建；summary_list 只返回新增摘要（list_add 追加）
    return {
        "messages": [RemoveMessage(REMOVE_ALL_MESSAGES)] + new_messages,
        "summary_list": [new_summary],
    }


# ==================== 节点 2: call_llm（LLM 推理节点）====================
def call_llm(state: GraphState, model, tools: list):
    """
    LLM 推理节点：
    - 注入基础系统提示（头部）
    - state.messages 已包含摘要 SystemMessage + 窗口内原始对话
    - 绑定 MCP 工具，调用模型
    """
    messages = state.get("messages", [])
    full_messages = [SystemMessage(content=BASE_SYSTEM_PROMPT)] + list(messages)
    model_with_tools = model.bind_tools(tools)
    response = model_with_tools.invoke(full_messages)
    return {"messages": [response]}


# ==================== 节点 3: call_mcp_tool（MCP 工具执行节点）====================
async def call_mcp_tool(state: GraphState, tools: list):
    """
    MCP 工具执行节点：
    - 执行最后一条 AIMessage 的 tool_calls
    - 返回 ToolMessage
    异常时生成错误 ToolMessage，保证消息结构配对与链路闭环。
    """
    tool_node = ToolNode(tools)
    try:
        return await tool_node.ainvoke(state)
    except Exception as e:
        print(f"[call_mcp_tool] 工具执行异常: {e}")
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


# ==================== 图构建入口 ====================
async def call_agent_with_MCPtools_summerization(mcp_input: Union[str, list[str]], thread_id: str):
    """基于 LangGraph StateGraph 构建带记忆压缩 + MCP 工具调用的对话 Agent。

    返回 (app, config, invoke_with_compression)，其中 invoke_with_compression
    保持原有调用方式，内部将用户输入交给图执行。
    """
    # 单/多MCP统一处理
    if isinstance(mcp_input, str):
        mcp_url_list = [mcp_input]
    else:
        mcp_url_list = mcp_input

    all_tools = []
    for url in mcp_url_list:
        # 自动补全http协议防护
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        tools = await get_langchain_tools(url)
        all_tools.extend(tools)
        print(f"MCP[{url}] 加载 {len(tools)} 个工具")
    print(f"合并后总工具数量：{len(all_tools)}")

    # 构建 StateGraph
    graph = StateGraph(GraphState)

    # 节点闭包：捕获 model/tools，避免 lambda 包装 async 函数的问题
    async def node_call_llm(state: GraphState):
        return call_llm(state, ds, all_tools)

    async def node_call_mcp_tool(state: GraphState):
        return await call_mcp_tool(state, all_tools)

    graph.add_node("memory_compress", memory_compress)
    graph.add_node("call_llm", node_call_llm)
    graph.add_node("call_mcp_tool", node_call_mcp_tool)

    # 固定边：入口先压缩，再进入 LLM
    graph.add_edge(START, "memory_compress")
    graph.add_edge("memory_compress", "call_llm")

    # 条件边：LLM 输出若需调用工具则进入工具节点，否则结束
    graph.add_conditional_edges(
        "call_llm",
        tools_condition,
        {
            "tools": "call_mcp_tool",
            END: END,
        },
    )

    # 工具执行完回到 LLM（工具循环闭环，不再经过 memory_compress）
    graph.add_edge("call_mcp_tool", "call_llm")

    checkpointer = InMemorySaver()
    config = {"configurable": {"thread_id": thread_id}}
    app = graph.compile(checkpointer=checkpointer)

    async def invoke_with_compression(user_input: str):
        """压缩逻辑已内置于 memory_compress 节点，每次调用自动执行。"""
        return await app.ainvoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
        )

    return app, config, invoke_with_compression
