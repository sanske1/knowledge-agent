import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import json
import redis
from config import REDIS_URL

redis_url = REDIS_URL
# MCP连接配置存在redis普通hash，不是向量库
REDIS_MCP_CONFIG_DB = 0

def get_redis_client():
    return redis.Redis.from_url(redis_url, db=REDIS_MCP_CONFIG_DB, decode_responses=True)

def MCPsave(mcp_name:str, mcp_url:str, transport:str="http", enabled:bool=True):
    """
    MCPsave：保存MCP服务连接信息到Redis（普通key-value，非向量）
    :param mcp_name: MCP服务名称，唯一标识
    :param mcp_url: MCP服务地址
    :param transport: http / sse
    :param enabled: 是否启用（默认 True）
    """
    r = get_redis_client()
    key = f"mcp:config:{mcp_name}"
    cfg = {
        "url": mcp_url,
        "transport": transport,
        "enabled": "1" if enabled else "0",
    }
    r.hset(key, mapping=cfg)
    return f"✅ MCP连接配置保存成功，name={mcp_name}, url={mcp_url}, enabled={enabled}"


def MCPsetEnabled(mcp_name:str, enabled:bool):
    """
    MCPsetEnabled：切换 MCP 服务的启用/停用状态。
    :param mcp_name: MCP服务名称
    :param enabled: True=启用，False=停用
    :return: 操作结果提示
    """
    r = get_redis_client()
    key = f"mcp:config:{mcp_name}"
    if not r.exists(key):
        return f"❌ 未找到 MCP 连接: {mcp_name}"
    r.hset(key, "enabled", "1" if enabled else "0")
    state = "启用" if enabled else "停用"
    return f"✅ MCP 服务「{mcp_name}」已{state}"


def MCPview(mcp_name:str=None):
    """
    MCPview：查看已保存的MCP连接信息
    - mcp_name=None：列出全部MCP服务
    - 传入名称：查看单个MCP详情
    返回的配置中包含 enabled 字段（布尔值）。
    """
    r = get_redis_client()
    def _normalize(cfg):
        """将 redis hash 中的字符串字段转为合适的类型。"""
        if not cfg:
            return cfg
        enabled = cfg.get("enabled", "1")
        cfg["enabled"] = enabled not in ("0", "false", "False", "")
        return cfg

    if mcp_name is None:
        keys = r.keys("mcp:config:*")
        res = {}
        for k in keys:
            name = k.split(":")[-1]
            res[name] = _normalize(r.hgetall(k))
        return res
    else:
        key = f"mcp:config:{mcp_name}"
        return _normalize(r.hgetall(key))
