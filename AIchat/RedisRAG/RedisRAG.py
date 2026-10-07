import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from langchain_ollama import OllamaEmbeddings
from langchain_redis import RedisVectorStore
from langchain_core.tools import tool
from ragconfig import get_redis_url, load_embedding
from config import REDIS_URL, EMBEDDING_MODEL, EMBEDDING_BASE_URL, VECTOR_INDEX_PREFIX
import json

# 初始化ollama向量模型
embedding_model = load_embedding(EMBEDDING_MODEL, EMBEDDING_BASE_URL)
redis_url = get_redis_url(REDIS_URL)

# deal_files 向量索引前缀
DEAL_FILES_INDEX_PREFIX = VECTOR_INDEX_PREFIX


def _get_deal_files_project_ids():
    """从 MySQL 获取 deal_files 所有项目 ID，用于遍历其向量索引。"""
    try:
        from AIchat.deal_files.storage import Storage
        storage = Storage()
        try:
            return [p.project_id for p in storage.index.list_projects()]
        finally:
            storage.close()
    except Exception as e:
        print(f"[RAGsearch] 获取 deal_files 项目列表失败: {e}")
        return []


@tool
def RAGsave(text, db, redis_url):
    "保存数据到数据库"
    # RedisVectorStore，index名称绑定db区分
    index_name = f"rag_index_db{db}"
    vector_db = RedisVectorStore(
        embeddings=embedding_model,
        redis_url=redis_url,
        index_name=index_name
    )
    # 存入向量库
    vector_db.add_texts([text])
    print(f"✅ 保存成功，存入redis db={db}, index={index_name}")


# 修复：增加 redis_url 参数
@tool
def RAGsearch(query, db, redis_url, k=2):
    """
    查找数据库中相关的数据。
    同时检索：
      1. agent 自身 RAG 索引：rag_index_db{db}
      2. deal_files 文档库所有项目索引：deal_files_chunks_{project_id}
    合并后按相似度排序返回 top-k。
    """
    all_results = []

    # 1. 检索 agent 自身 RAG 索引
    try:
        index_name = f"rag_index_db{db}"
        vector_db = RedisVectorStore(
            embeddings=embedding_model,
            redis_url=redis_url,
            index_name=index_name,
        )
        all_results.extend(vector_db.similarity_search_with_score(query, k=k))
    except Exception as e:
        print(f"[RAGsearch] 索引 {index_name} 检索失败: {e}")

    # 2. 检索 deal_files 文档库所有项目索引（打通 deal_files ↔ agent RAG）
    project_ids = _get_deal_files_project_ids()
    for pid in project_ids:
        df_index = f"{DEAL_FILES_INDEX_PREFIX}_{pid}"
        try:
            df_db = RedisVectorStore(
                embeddings=embedding_model,
                redis_url=redis_url,
                index_name=df_index,
            )
            hits = df_db.similarity_search_with_score(query, k=k)
            # 给 deal_files 结果打上来源标记，便于溯源
            for doc, score in hits:
                doc.metadata["source"] = "deal_files"
                doc.metadata["project_id"] = pid
            all_results.extend(hits)
        except Exception as e:
            print(f"[RAGsearch] deal_files 索引 {df_index} 检索失败: {e}")

    # 合并排序：score 越小越相似（langchain_redis 用距离），取 top-k
    all_results.sort(key=lambda x: x[1])
    return all_results[:k]


# 示例：也支持 as_retriever(k=2)
if __name__ == "__main__":
    # text = "爱若天有意，逐风不肯息"
    # RAGsave(text, db=0, redis_url=redis_url)

    res = RAGsearch("爱", db=0, redis_url=redis_url, k=1)
    for doc, score in res:
        content = doc.page_content
        meta = doc.metadata
        print(f"文本：{content}, \n相似度：{score}")

