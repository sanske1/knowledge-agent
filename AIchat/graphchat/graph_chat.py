import sys
import os
from typing import Union
from langchain_core.messages import HumanMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from AIchat.graphchat.graph_agent import build_graph_agent
from config import MCP_URL
import asyncio


async def chat_agent(mcp_url: Union[str, list[str]] = None):
    if mcp_url is None:
        mcp_url = MCP_URL
    app, config = await build_graph_agent(mcp_url, thread_id="2")

    while True:
        user_input = input("聊天 (输入 exit 退出): ")
        if user_input.lower() == "exit":
            break

        # 用户新消息进入图，自动经过 memory_compress → call_llm → 工具循环
        result = await app.ainvoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
        )

        last_msg = result["messages"][-1]
        ai_response = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        print(f"\n🤖 {ai_response}\n")


if __name__ == "__main__":
    asyncio.run(chat_agent())
