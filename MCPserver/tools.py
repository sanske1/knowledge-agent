from fastmcp import FastMCP
from langchain_ollama import OllamaEmbeddings
from langchain_redis import RedisVectorStore
import json
import os
from datetime import datetime
import redis
import pymysql

# ==================== 初始化全局向量模型与Redis连接 ====================
# 向量模型
embedding_model = OllamaEmbeddings(
    model="bge-m3:latest",
    base_url="http://localhost:11434"
)
# redis url
REDIS_URL = "redis://127.0.0.1:6379"
# 连接Redis（失败只警告，不阻塞服务启动）
redis_client = redis.Redis.from_url(REDIS_URL)
try:
    redis_client.ping()
    print(f"✅ Redis 连接成功: {REDIS_URL}")
except Exception as e:
    print(f"❌ Redis 连接失败: {e}（Redis 相关工具将不可用）")

# ==================== deal_files 直连配置（不依赖 AIchat 包）====================
MYSQL_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": os.environ.get("KB_MYSQL_PASSWORD", ""),   # 口令走环境变量，不进仓库
    "database": "deal_files",
    "charset": "utf8mb4",
}
DEAL_FILES_INDEX_PREFIX = "deal_files_chunks"


def _df_list_projects():
    """直连 MySQL 获取 deal_files 所有项目及文件列表。"""
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT project_id, name, summary FROM projects")
            projects = cur.fetchall()
            # 取每个项目的文件（file_id -> filename 映射）
            cur.execute("SELECT file_id, project_id, filename FROM files")
            files = cur.fetchall()
        file_map = {}
        for f in files:
            file_map.setdefault(f["project_id"], {})[f["file_id"]] = f["filename"]
        return projects, file_map
    finally:
        conn.close()

mcp = FastMCP(name='toolsCenter')

# ---------- 原有工具 ----------
@mcp.tool
def get_date() -> str:
    """获取当前系统本地日期时间，返回 年/月/日 时:分:秒"""
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S")


# ==================== 新增 RAG MCP工具 ====================
@mcp.tool
def RAGsave(text: str, db: int) -> str:
    """
    保存文本内容到RAG向量知识库
    Args:
        text: 需要入库的文本内容
        db: 知识库编号，不同db代表独立向量索引，例如0,1,2
    """
    index_name = f"rag_index_db{db}"
    vector_db = RedisVectorStore(
        embeddings=embedding_model,
        redis_url=REDIS_URL,
        index_name=index_name
    )
    vector_db.add_texts([text])
    return f"✅ RAG保存成功，db={db}, index={index_name}"


@mcp.tool
def RAGsearch(query: str, db: int, k: int = 2) -> str:
    """
    在指定知识库执行向量检索，返回相关片段+相似度分数。
    同时检索：
      1. agent 自身 RAG 索引：rag_index_db{db}
      2. deal_files 文档库所有项目索引：deal_files_chunks_{project_id}
    合并后按相似度排序返回 top-k。
    Args:
        query: 用户检索问题
        db: 知识库编号
        k: 返回topk结果数量，默认2
    Return:
        json字符串，包含page_content、metadata（含source标记）、score
    """
    all_results = []

    # 1. 检索 agent 自身 RAG 索引
    try:
        index_name = f"rag_index_db{db}"
        vector_db = RedisVectorStore(
            embeddings=embedding_model,
            redis_url=REDIS_URL,
            index_name=index_name,
        )
        all_results.extend(vector_db.similarity_search_with_score(query, k=k))
    except Exception as e:
        print(f"[RAGsearch] 索引 rag_index_db{db} 检索失败: {e}")

    # 2. 检索 deal_files 文档库所有项目索引（打通 deal_files ↔ agent RAG）
    try:
        projects, file_map = _df_list_projects()
        for p in projects:
            pid = p["project_id"]
            df_index = f"{DEAL_FILES_INDEX_PREFIX}_{pid}"
            try:
                df_db = RedisVectorStore(
                    embeddings=embedding_model,
                    redis_url=REDIS_URL,
                    index_name=df_index,
                )
                hits = df_db.similarity_search_with_score(query, k=k)
                for doc, score in hits:
                    doc.metadata["source"] = "deal_files"
                    doc.metadata["project_name"] = p["name"]
                all_results.extend(hits)
            except Exception as e:
                print(f"[RAGsearch] deal_files 索引 {df_index} 检索失败: {e}")
    except Exception as e:
        print(f"[RAGsearch] 获取 deal_files 项目列表失败: {e}")

    # 合并排序：score 越小越相似
    all_results.sort(key=lambda x: x[1])
    top = all_results[:k]

    output = []
    for doc, score in top:
        output.append({
            "page_content": doc.page_content,
            "metadata": doc.metadata,
            "score": float(score),
        })
    return json.dumps(output, ensure_ascii=False, indent=2)


# ---------- Redis基础操作工具（保留你原来的）----------
REDIS_CONFIG = {
    'host': 'localhost',
    'port': 6379,
    'decode_responses': True
}

def get_redis_client():
    return redis.Redis(**REDIS_CONFIG)

@mcp.tool
def redis_set(key: str, value: str, ex: int = None) -> str:
    """设置 Redis 字符串键值。"""
    try:
        r = get_redis_client()
        r.set(key, value, ex=ex)
        return f"设置成功：{key} = {value}" + (f" (过期时间 {ex}s)" if ex else "")
    except Exception as e:
        return f"设置失败：{e}"

@mcp.tool
def redis_get(key: str) -> str:
    """获取 Redis 字符串值。"""
    try:
        r = get_redis_client()
        value = r.get(key)
        if value is None:
            return f"键 {key} 不存在"
        return f"{key} = {value}"
    except Exception as e:
        return f"获取失败：{e}"

@mcp.tool
def redis_delete(keys: str) -> str:
    """删除一个或多个 Redis 键。多个逗号分隔"""
    try:
        key_list = [k.strip() for k in keys.split(',') if k.strip()]
        r = get_redis_client()
        count = r.delete(*key_list)
        return f"成功删除 {count} 个键"
    except Exception as e:
        return f"删除失败：{e}"

@mcp.tool
def redis_hset(name: str, field: str, value: str) -> str:
    """设置 Redis 哈希字段。"""
    try:
        r = get_redis_client()
        r.hset(name, field, value)
        return f"哈希 {name} 字段 {field} 设置成功"
    except Exception as e:
        return f"设置失败：{e}"

@mcp.tool
def redis_hget(name: str, field: str) -> str:
    """获取 Redis 哈希字段值。"""
    try:
        r = get_redis_client()
        value = r.hget(name, field)
        if value is None:
            return f"哈希 {name} 中字段 {field} 不存在"
        return f"{name}.{field} = {value}"
    except Exception as e:
        return f"获取失败：{e}"

@mcp.tool
def redis_hgetall(name: str) -> str:
    """获取 Redis 哈希的所有字段和值。"""
    try:
        r = get_redis_client()
        data = r.hgetall(name)
        if not data:
            return f"哈希 {name} 为空或不存在"
        return json.dumps(data, ensure_ascii=False)
    except Exception as e:
        return f"获取失败：{e}"

@mcp.tool
def redis_hdel(name: str, field: str) -> str:
    """删除 Redis 哈希中的指定字段。"""
    try:
        r = get_redis_client()
        count = r.hdel(name, field)
        if count == 0:
            return f"字段 {field} 不存在或删除失败"
        return f"哈希 {name} 字段 {field} 删除成功"
    except Exception as e:
        return f"删除失败：{e}"

@mcp.tool
def redis_exists(keys: str) -> str:
    """检查一个或多个键是否存在，多个逗号分隔"""
    try:
        key_list = [k.strip() for k in keys.split(',') if k.strip()]
        r = get_redis_client()
        count = r.exists(*key_list)
        return f"存在 {count} 个键"
    except Exception as e:
        return f"检查失败：{e}"

@mcp.tool
def redis_keys(pattern: str = '*') -> str:
    """查找匹配模式的所有键。"""
    try:
        r = get_redis_client()
        keys = r.keys(pattern)
        return json.dumps(keys, ensure_ascii=False)
    except Exception as e:
        return f"查找失败：{e}"


# ==================== deal_files 文档库检索工具 ====================
@mcp.tool
def search_File_index(query: str, top_k: int = 5) -> str:
    """
    在已归档的文档库中进行语义检索，返回最相关的文档片段及来源信息。
    Args:
        query: 用户的查询问题或关键词
        top_k: 返回的最相关结果数量，默认5
    Return:
        包含片段文本、文件名、项目名、相似度分数的结构化文本。
    """
    try:
        projects, file_map = _df_list_projects()

        all_hits = []
        for p in projects:
            pid = p["project_id"]
            project_files = file_map.get(pid, {})
            index_name = f"{DEAL_FILES_INDEX_PREFIX}_{pid}"
            try:
                vs = RedisVectorStore(
                    embeddings=embedding_model,
                    redis_url=REDIS_URL,
                    index_name=index_name,
                )
                hits = vs.similarity_search_with_score(query, k=top_k)
                for doc, score in hits:
                    md = doc.metadata
                    file_id = md.get("file_id", "")
                    filename = project_files.get(file_id, md.get("filename", ""))
                    all_hits.append({
                        "text": doc.page_content,
                        "score": float(score),
                        "filename": filename,
                        "project_name": p["name"],
                        "file_id": file_id,
                        "chunk_id": md.get("chunk_id", ""),
                        "page": md.get("page"),
                    })
            except Exception as e:
                print(f"[search_File_index] 索引 {index_name} 检索失败: {e}")

        all_hits.sort(key=lambda x: x["score"])
        top = all_hits[:top_k]

        if not top:
            return "未检索到相关文档。"

        lines = []
        for i, r in enumerate(top, 1):
            src = r["filename"]
            if r["project_name"]:
                src = f"{r['filename']}（{r['project_name']}）"
            lines.append(f"[{i}] 来源: 《{src}》")
            lines.append(f"    相似度: {r['score']:.4f}")
            if r["page"] is not None:
                lines.append(f"    页码: {r['page']}")
            lines.append(f"    内容: {r['text']}")
            lines.append("")
        return "\n".join(lines)

    except Exception as e:
        return f"检索失败：{e}"


# ---------- 启动服务器 ----------
if __name__ == "__main__":
    import asyncio
    asyncio.run(mcp.run_http_async(port=8889))
