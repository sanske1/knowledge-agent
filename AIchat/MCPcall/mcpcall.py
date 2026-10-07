import asyncio
import json
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import create_model

# ---------- 工具转换（内部辅助）----------
from langchain_mcp_adapters.client import MultiServerMCPClient
from config import MCP_URL


async def get_langchain_tools(MCP_url=None, transport="http"):
    if MCP_url is None:
        MCP_url = MCP_URL
    # transport 兼容：langchain-mcp-adapters 支持 "http" / "sse" / "stdio"
    # 用户保存的 "streamable-http" 统一映射为 "http"
    if transport == "streamable-http":
        transport = "http"
    client = MultiServerMCPClient({
        "mcp_server": {
            "transport": transport,
            "url": MCP_url,
        }
    })
    tools = await client.get_tools()
    return tools

async def main():
    tools = await get_langchain_tools()
    print(tools)


if __name__ == '__main__':
    asyncio.run(main())


