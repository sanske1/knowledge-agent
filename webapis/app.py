# -*- coding: utf-8 -*-
"""
webapis FastAPI 应用
封装 deal_files 的入库、索引、检索能力，供 Web 前端调用。

启动（在项目根目录执行）：
    uvicorn webapis.app:app --host 0.0.0.0 --port 8000 --reload

接口文档：
    http://127.0.0.1:8000/docs
前端页面：
    http://127.0.0.1:8000/
"""
import os
import sys
import json
import shutil
import uuid
import time
from typing import List, Optional, Dict, Any

# 将项目根目录加入 sys.path，使 AIchat 包可导入
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# 复用 AIchat.deal_files（单一真相源）
from AIchat.deal_files.config import (
    INBOX_DIR, ARCHIVED_DIR, FAILED_DIR,
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE, MYSQL_CHARSET,
    REDIS_URL, VECTOR_INDEX_PREFIX,
    ARCHIVE_RETRY_TIMES, CHUNK_MAX_CHARS,
    MCP_URL, META_EXT,
)
from AIchat.deal_files import (
    process_inbox, rebuild_index, import_from_disk,
    validate_index, list_failed, retry_failed,
)
from AIchat.deal_files.AIsavefile import search_all, search_File_index
from AIchat.deal_files.loadfile import loadfile
from AIchat.deal_files.storage import Storage


# ==================== FastAPI 应用 ====================
app = FastAPI(
    title="知识库Agent系统 Web API",
    description="文档入库、索引、检索、智能对话的统一接口",
    version="1.0.0",
)

# CORS：允许前端跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 工具函数 ====================
def _to_dict(obj):
    if obj is None:
        return None
    if hasattr(obj, "__dataclass_fields__"):
        return {k: getattr(obj, k) for k in obj.__dataclass_fields__}
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return obj


# ==================== 请求 / 响应模型 ====================
class SearchRequest(BaseModel):
    q: str
    top_k: int = 5


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    project: Optional[str] = None


class ConfigSaveRequest(BaseModel):
    mysql_host: Optional[str] = None
    mysql_port: Optional[int] = None
    mysql_user: Optional[str] = None
    mysql_password: Optional[str] = None
    mysql_database: Optional[str] = None
    redis_url: Optional[str] = None
    inbox_dir: Optional[str] = None
    archived_dir: Optional[str] = None
    webapi_port: Optional[int] = None
    mcp_port: Optional[int] = None
    archive_retry: Optional[int] = None
    chunk_max_chars: Optional[int] = None
    default_topk: Optional[int] = None


class MySQLTestRequest(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    user: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None


class RedisTestRequest(BaseModel):
    url: Optional[str] = None


# ==================== 1. 入库相关接口 ====================
@app.post("/api/ingest/process", summary="处理未处理区全部文件")
def api_process_inbox():
    try:
        report = process_inbox()
        return {"success": True, "data": report.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ingest/upload", summary="上传文件到未处理区")
async def api_upload_files(files: List[UploadFile] = File(...), project: Optional[str] = Form(None)):
    saved = []
    try:
        for f in files:
            if project:
                target_dir = os.path.join(INBOX_DIR, project)
            else:
                target_dir = INBOX_DIR
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, f.filename)
            with open(target_path, "wb") as buf:
                shutil.copyfileobj(f.file, buf)
            saved.append(f.filename)
        return {"success": True, "saved_files": saved, "count": len(saved)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 2. 索引管理接口 ====================
@app.post("/api/index/rebuild", summary="从 MySQL 重建 Redis 向量库")
def api_rebuild_index():
    try:
        result = rebuild_index()
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/index/import", summary="灾备：从磁盘 .meta.json 导入到 MySQL")
def api_import_from_disk():
    try:
        result = import_from_disk()
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/index/validate", summary="校验索引与已处理区一致性")
def api_validate_index():
    try:
        result = validate_index()
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/index/stats", summary="索引统计：项目数 / 文件数 / 分片数")
def api_index_stats():
    storage = Storage()
    try:
        projects = storage.index.list_projects()
        files = storage.index.list_files()
        chunks = storage.index.list_all_chunks()
        # Redis 向量数
        redis_info = {"status": "unknown", "total_vectors": 0}
        try:
            import redis
            r = redis.from_url(REDIS_URL)
            r.ping()
            # langchain_redis 将向量存为 hash key，命名形如 {index_name}:{doc_id}
            # 统计所有以 deal_files_chunks_ 开头的 key（含索引元数据与向量文档）
            all_keys = r.keys(f"{VECTOR_INDEX_PREFIX}_*")
            # 排除 RediSearch 索引自身的元数据 key（通常是 index_name 本身）
            index_keys = set()
            for k in all_keys:
                # 尝试获取索引文档数
                try:
                    idx_name = k.decode() if isinstance(k, bytes) else k
                    # 索引 key 不包含 ":"，向量文档 key 形如 idx:docid
                    if ":" not in idx_name:
                        index_keys.add(idx_name)
                except Exception:
                    pass
            # 向量文档数 = 总 key 数 - 索引元数据 key 数
            total = len(all_keys) - len(index_keys)
            redis_info = {
                "status": "ok",
                "total_vectors": total,
                "index_count": len(index_keys),
                "indexes": [{"index": i} for i in index_keys],
            }
        except Exception as e:
            redis_info = {"status": "error", "error": str(e)}

        return {
            "success": True,
            "data": {
                "project_count": len(projects),
                "file_count": len(files),
                "chunk_count": len(chunks),
                "projects": [{"id": p.project_id, "name": p.name, "file_count": len(p.file_ids)} for p in projects],
                "redis": redis_info,
            },
        }
    finally:
        storage.close()


# ==================== 3. 检索接口 ====================
@app.get("/api/search", summary="语义检索（返回结构化 JSON）")
def api_search(q: str, top_k: int = 5, project: Optional[str] = None):
    try:
        results = search_all(q, k=top_k)
        # 可选按项目过滤
        if project:
            results = [r for r in results if r.get("project_name") == project or r.get("project_id") == project]
        return {"success": True, "query": q, "count": len(results), "data": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/search/tool", summary="语义检索（返回格式化文本）")
def api_search_tool(q: str, top_k: int = 5):
    try:
        result = search_File_index.invoke({"query": q, "top_k": top_k})
        return {"success": True, "query": q, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 4. 失败文件接口 ====================
@app.get("/api/failed", summary="列出未处理区失败文件")
def api_list_failed():
    try:
        failed = list_failed()
        return {"success": True, "count": len(failed), "data": failed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/failed/retry", summary="重试失败文件")
def api_retry_failed():
    try:
        report = retry_failed()
        return {"success": True, "data": report.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 5. 项目 / 文件浏览接口 ====================
@app.get("/api/projects", summary="列出所有项目")
def api_list_projects():
    storage = Storage()
    try:
        projects = storage.index.list_projects()
        return {
            "success": True,
            "data": [
                {
                    "project_id": p.project_id,
                    "name": p.name,
                    "summary": p.summary,
                    "themes": p.themes,
                    "file_count": len(p.file_ids),
                }
                for p in projects
            ],
        }
    finally:
        storage.close()


@app.get("/api/projects/{project_id}/files", summary="列出项目下的文件")
def api_project_files(project_id: str):
    storage = Storage()
    try:
        files = storage.index.get_files_by_project(project_id)
        return {
            "success": True,
            "data": [
                {
                    "file_id": f.file_id,
                    "filename": f.filename,
                    "summary": f.summary,
                    "keywords": f.keywords,
                    "content_type": f.content_type,
                    "chunk_count": len(f.chunk_ids),
                }
                for f in files
            ],
        }
    finally:
        storage.close()


@app.get("/api/files/{file_id}/chunks", summary="获取文件的分片文本")
def api_file_chunks(file_id: str):
    storage = Storage()
    try:
        chunks = storage.index.get_chunks_by_file(file_id)
        return {"success": True, "file_id": file_id, "count": len(chunks), "data": chunks}
    finally:
        storage.close()


@app.get("/api/files/{file_id}/meta", summary="获取文件的 .meta.json 元数据")
def api_file_meta(file_id: str):
    storage = Storage()
    try:
        files = storage.index.list_files()
        target = None
        for f in files:
            if f.file_id == file_id:
                target = f
                break
        if not target:
            raise HTTPException(status_code=404, detail="文件不存在")
        # 优先从归档目录读取 .meta.json（不依赖可能过期的 abs_path）
        proj = storage.index.get_project(target.project_id)
        project_name = proj.name if proj else ""
        meta = {}
        if project_name:
            file_meta = storage.archiver.read_meta(project_name, target.filename)
            if file_meta:
                meta = file_meta.to_dict()
        # 兜底：若归档目录未找到，尝试存储的 abs_path
        if not meta and target.abs_path:
            meta_path = target.abs_path + META_EXT
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as fp:
                    meta = json.load(fp)
        return {"success": True, "data": meta}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        storage.close()


# ==================== 6. 文件夹路径信息 ====================
@app.get("/api/folders", summary="获取未处理/已处理/失败文件夹路径")
def api_folders():
    return {
        "success": True,
        "data": {
            "inbox": INBOX_DIR,
            "archived": ARCHIVED_DIR,
            "failed": FAILED_DIR,
        },
    }


# ==================== 7. 智能对话接口 ====================
# 内存会话管理：session_id -> {graph_app, config, title, created_at, messages}
_chat_sessions: Dict[str, Dict[str, Any]] = {}

# 聊天持久化存储（MySQL）
_chat_storage = None


@app.on_event("startup")
def _load_chat_sessions():
    """启动时从 MySQL 加载历史会话到内存，并修复过期的归档路径。"""
    global _chat_storage, _chat_sessions
    # 修复归档文件路径（项目移动后 abs_path 可能过期）
    try:
        storage = Storage()
        try:
            result = storage.fix_stale_abs_paths()
            if result["fixed"] > 0:
                print(f"[storage] 修复 {result['fixed']} 个过期文件路径，"
                      f"仍缺失 {result['still_missing']} 个")
        finally:
            storage.close()
    except Exception as e:
        print(f"[storage] 路径修复失败: {e}")
    # 加载聊天历史
    try:
        from webapis.chat_storage import ChatStorage
        _chat_storage = ChatStorage()
        persisted = _chat_storage.load_all_sessions()
        for sid, data in persisted.items():
            _chat_sessions[sid] = {
                "app": None,          # graph_app 延迟到首次发消息时重建
                "config": None,
                "title": data["title"],
                "created_at": data["created_at"],
                "messages": data["messages"],
            }
        print(f"[chat] 已从 MySQL 加载 {len(_chat_sessions)} 个历史会话")
    except Exception as e:
        print(f"[chat] 加载历史会话失败: {e}")


@app.get("/api/chat/sessions", summary="列出所有对话会话")
def api_list_sessions():
    sessions = []
    for sid, s in _chat_sessions.items():
        sessions.append({
            "session_id": sid,
            "title": s.get("title", "新对话"),
            "created_at": s.get("created_at"),
            "message_count": len(s.get("messages", [])),
        })
    sessions.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return {"success": True, "data": sessions}


@app.delete("/api/chat/sessions/{session_id}", summary="删除对话会话")
def api_delete_session(session_id: str):
    if session_id in _chat_sessions:
        del _chat_sessions[session_id]
    if _chat_storage:
        _chat_storage.delete_session(session_id)
    return {"success": True}


@app.get("/api/chat/sessions/{session_id}/messages", summary="获取会话历史消息")
def api_session_messages(session_id: str):
    s = _chat_sessions.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"success": True, "data": s.get("messages", [])}


@app.post("/api/chat/send", summary="发送消息并获取 AI 回复")
async def api_chat_send(req: ChatRequest):
    """调用 LangGraph Agent 进行多轮对话。"""
    try:
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        from AIchat.graphchat.graph_agent import build_graph_agent

        session_id = req.session_id or str(uuid.uuid4())
        is_new = session_id not in _chat_sessions

        # 新建会话 或 重启后 app 为空：构建 graph_app
        if is_new or _chat_sessions[session_id].get("app") is None:
            from AIchat.MCPcall.MCPmanager import MCPview
            mcp_configs = MCPview()
            # 仅加载已启用的 MCP 服务
            mcp_list = [cfg for cfg in mcp_configs.values() if cfg.get("enabled", True)] if mcp_configs else []
            if not mcp_list:
                mcp_list = [{"url": MCP_URL, "transport": "http"}]
            graph_app, config = await build_graph_agent(
                mcp_list, thread_id=session_id
            )

            if is_new:
                _chat_sessions[session_id] = {
                    "app": graph_app,
                    "config": config,
                    "title": req.message[:20] if req.message else "新对话",
                    "created_at": time.time(),
                    "messages": [],
                }
                # 持久化会话元数据
                if _chat_storage:
                    _chat_storage.save_session(
                        session_id, _chat_sessions[session_id]["title"],
                        _chat_sessions[session_id]["created_at"],
                    )
            else:
                # 重启恢复：注入历史消息到图状态，恢复对话上下文
                session = _chat_sessions[session_id]
                session["app"] = graph_app
                session["config"] = config
                history = []
                for m in session.get("messages", []):
                    if m["role"] == "user":
                        history.append(HumanMessage(content=m["content"]))
                    elif m["role"] == "assistant":
                        history.append(AIMessage(content=m.get("content", "")))
                if history:
                    graph_app.update_state(config, {"messages": history})
                    print(f"[chat] 会话 {session_id} 已恢复 {len(history)} 条历史消息到图状态")

        session = _chat_sessions[session_id]
        graph_app = session["app"]
        config = session["config"]

        # 执行图
        result = await graph_app.ainvoke(
            {"messages": [HumanMessage(content=req.message)]},
            config=config,
        )

        # 提取 AI 最终回复与工具调用记录
        messages = result.get("messages", [])
        ai_content = ""
        tool_calls = []
        for msg in messages:
            if isinstance(msg, AIMessage):
                if msg.content:
                    ai_content = msg.content
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls.append({
                            "name": tc.get("name"),
                            "args": tc.get("args", {}),
                            "status": "success",
                        })
            elif isinstance(msg, ToolMessage):
                for tc in tool_calls:
                    if tc.get("name") == msg.name and not tc.get("result"):
                        tc["result"] = str(msg.content)[:500]
                        break

        # 保存消息记录到内存 + MySQL
        user_msg = {"role": "user", "content": req.message}
        ai_msg = {"role": "assistant", "content": ai_content, "tool_calls": tool_calls}
        session["messages"].append(user_msg)
        session["messages"].append(ai_msg)

        if _chat_storage:
            _chat_storage.save_message(session_id, "user", req.message)
            _chat_storage.save_message(session_id, "assistant", ai_content, tool_calls)

        return {
            "success": True,
            "session_id": session_id,
            "message": ai_content,
            "tool_calls": tool_calls,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 8. 配置接口 ====================
_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "runtime_config.json")


def _load_runtime_config() -> dict:
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_runtime_config(cfg: dict):
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


@app.get("/api/config", summary="获取当前系统配置")
def api_get_config():
    rc = _load_runtime_config()
    return {
        "success": True,
        "data": {
            "mysql": {
                "host": rc.get("mysql_host", MYSQL_HOST),
                "port": rc.get("mysql_port", MYSQL_PORT),
                "user": rc.get("mysql_user", MYSQL_USER),
                "password": "******",  # 脱敏
                "database": rc.get("mysql_database", MYSQL_DATABASE),
                "charset": MYSQL_CHARSET,
            },
            "redis": {
                "url": rc.get("redis_url", REDIS_URL),
                "index_prefix": VECTOR_INDEX_PREFIX,
            },
            "folders": {
                "inbox": rc.get("inbox_dir", INBOX_DIR),
                "archived": rc.get("archived_dir", ARCHIVED_DIR),
                "failed": FAILED_DIR,
            },
            "params": {
                "archive_retry": rc.get("archive_retry", ARCHIVE_RETRY_TIMES),
                "chunk_max_chars": rc.get("chunk_max_chars", CHUNK_MAX_CHARS),
                "default_topk": rc.get("default_topk", 5),
                "webapi_port": rc.get("webapi_port", 8000),
                "mcp_port": rc.get("mcp_port", 8889),
            },
        },
    }


@app.post("/api/config/save", summary="保存系统配置")
def api_save_config(req: ConfigSaveRequest):
    rc = _load_runtime_config()
    for k, v in req.model_dump().items():
        if v is not None:
            rc[k] = v
    _save_runtime_config(rc)
    return {"success": True, "data": rc}


@app.post("/api/config/test_mysql", summary="测试 MySQL 连接")
def api_test_mysql(req: MySQLTestRequest = None):
    import pymysql
    host = (req.host if req else None) or MYSQL_HOST
    port = (req.port if req else None) or MYSQL_PORT
    user = (req.user if req else None) or MYSQL_USER
    password = (req.password if req else None) or MYSQL_PASSWORD
    database = (req.database if req else None) or MYSQL_DATABASE
    try:
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database=database, charset=MYSQL_CHARSET, connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute("SELECT VERSION()")
        version = cur.fetchone()[0]
        cur.execute("SHOW TABLES")
        tables = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return {
            "success": True,
            "data": {
                "connected": True,
                "version": version,
                "table_count": len(tables),
                "tables": tables,
            },
        }
    except Exception as e:
        return {"success": False, "data": {"connected": False, "error": str(e)}}


@app.post("/api/config/test_redis", summary="测试 Redis 连接")
def api_test_redis(req: RedisTestRequest = None):
    import redis
    url = (req.url if req else None) or REDIS_URL
    try:
        r = redis.from_url(url)
        r.ping()
        info = r.info()
        keys = r.keys("*")
        return {
            "success": True,
            "data": {
                "connected": True,
                "used_memory_human": info.get("used_memory_human"),
                "total_keys": len(keys),
                "redis_version": info.get("redis_version"),
            },
        }
    except Exception as e:
        return {"success": False, "data": {"connected": False, "error": str(e)}}


# ==================== 9. 服务状态接口 ====================
@app.get("/api/status/services", summary="服务心跳：MySQL / Redis / MCP")
def api_status_services():
    result = {"mysql": {}, "redis": {}, "mcp": {}}
    # MySQL
    try:
        import pymysql
        conn = pymysql.connect(
            host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
            password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
            charset=MYSQL_CHARSET, connect_timeout=3,
        )
        conn.close()
        result["mysql"] = {"status": "ok"}
    except Exception as e:
        result["mysql"] = {"status": "error", "error": str(e)}
    # Redis
    try:
        import redis
        r = redis.from_url(REDIS_URL)
        r.ping()
        result["redis"] = {"status": "ok"}
    except Exception as e:
        result["redis"] = {"status": "error", "error": str(e)}
    # MCP
    try:
        import requests
        resp = requests.get(MCP_URL, timeout=3)
        result["mcp"] = {"status": "ok", "http_status": resp.status_code}
    except Exception as e:
        result["mcp"] = {"status": "error", "error": str(e)}
    return {"success": True, "data": result}


@app.get("/api/status/mcp_tools", summary="列出已配置 MCP 服务的工具")
async def api_status_mcp_tools():
    """通过 MCP 客户端库连接已保存的 MCP 服务并列出工具。"""
    try:
        from AIchat.MCPcall.MCPmanager import MCPview
        from AIchat.MCPcall.mcpcall import get_langchain_tools

        configs = MCPview()  # dict[name] = {url, transport, enabled}
        all_tools = []
        for name, cfg in configs.items():
            # 跳过已停用的 MCP 服务
            if not cfg.get("enabled", True):
                continue
            try:
                tools = await get_langchain_tools(cfg["url"], cfg.get("transport", "http"))
                for t in tools:
                    all_tools.append({
                        "name": t.name,
                        "description": (t.description or "")[:120],
                        "source": name,
                        "status": "ok",
                    })
            except Exception as e:
                all_tools.append({
                    "name": f"[{name} 连接失败]",
                    "description": str(e)[:120],
                    "source": name,
                    "status": "error",
                })
        return {"success": True, "data": {"count": len(all_tools), "tools": all_tools}}
    except Exception as e:
        return {"success": False, "data": {"count": 0, "tools": [], "error": str(e)}}


# ==================== MCP 连接管理（添加 / 查看 / 删除）====================
class MCPAddRequest(BaseModel):
    name: str
    url: str
    transport: str = "http"


@app.post("/api/mcp/add", summary="添加 MCP 服务连接")
def api_mcp_add(req: MCPAddRequest):
    from AIchat.MCPcall.MCPmanager import MCPsave
    msg = MCPsave(req.name, req.url, req.transport)
    return {"success": True, "message": msg}


@app.get("/api/mcp/list", summary="列出已添加的 MCP 服务")
def api_mcp_list():
    from AIchat.MCPcall.MCPmanager import MCPview
    data = MCPview()
    return {"success": True, "data": data}


@app.delete("/api/mcp/{name}", summary="删除 MCP 服务连接")
def api_mcp_delete(name: str):
    from AIchat.MCPcall.MCPmanager import get_redis_client
    r = get_redis_client()
    key = f"mcp:config:{name}"
    if r.exists(key):
        r.delete(key)
        return {"success": True, "message": f"已删除 MCP 连接: {name}"}
    return {"success": False, "message": f"未找到 MCP 连接: {name}"}


class MCPToggleRequest(BaseModel):
    enabled: bool


@app.post("/api/mcp/{name}/toggle", summary="启用/停用 MCP 服务")
def api_mcp_toggle(name: str, req: MCPToggleRequest):
    from AIchat.MCPcall.MCPmanager import MCPsetEnabled
    msg = MCPsetEnabled(name, req.enabled)
    success = "✅" in msg
    return {"success": success, "message": msg, "enabled": req.enabled}


# ==================== 10. 未处理区文件列表（供前端展示）====================
@app.get("/api/inbox/files", summary="列出未处理区文件")
def api_inbox_files():
    files = []
    try:
        for root, dirs, fnames in os.walk(INBOX_DIR):
            # 跳过 .failed 目录单独处理
            if ".failed" in root:
                continue
            for fn in fnames:
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, INBOX_DIR)
                stat = os.stat(fp)
                files.append({
                    "name": fn,
                    "path": rel,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "project": os.path.dirname(rel) or "(根目录/自动聚类)",
                })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"success": True, "count": len(files), "data": files}


# ==================== 静态文件：Web 前端 ====================
from AIchat.deal_files.config import WEB_DIR

if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))

    # 子路径也返回 index.html（SPA 前端路由）
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        # 优先返回真实文件，否则返回 index.html
        target = os.path.join(WEB_DIR, full_path)
        if os.path.isfile(target):
            return FileResponse(target)
        return FileResponse(os.path.join(WEB_DIR, "index.html"))


# ==================== 启动入口 ====================
if __name__ == "__main__":
    import uvicorn
    from config import WEBAPI_HOST, WEBAPI_PORT
    uvicorn.run("webapis.app:app", host=WEBAPI_HOST, port=WEBAPI_PORT, reload=True)
