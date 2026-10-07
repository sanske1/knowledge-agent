import sys
import os
from typing import Union
from langchain_core.messages import HumanMessage

# 将项目根目录加入 sys.path，兼容直接运行脚本和模块导入两种方式
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from AIchat.Chat.LLM import call_agent_with_MCPtools_summerization
from config import MCP_URL
import asyncio


async def chat_agent(mcp_url: Union[str, list[str]] = None):
    if mcp_url is None:
        mcp_url = MCP_URL
    agent, config, invoke_with_compression = await call_agent_with_MCPtools_summerization(mcp_url, thread_id="2")

    while True:
        user_input = input("聊天 (输入 exit 退出): ")
        if user_input.lower() == "exit":
            break

        result = await invoke_with_compression(user_input)
        print(result)

        last_msg = result["messages"][-1]
        ai_response = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        print(f"\n🤖 {ai_response}\n")


if __name__ == "__main__":
    asyncio.run(chat_agent())
