# -*- coding: utf-8 -*-
"""
deal_files 配置（向后兼容层）
所有实际配置统一维护在项目根目录的 config.py，本文件仅做重导出。
"""
import sys
import os

# 确保项目根目录在 sys.path 中，以便 import config
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import (  # noqa: E402,F401
    PROJECT_ROOT,
    WEB_DIR,
    DEAL_FILES_DATA_DIR,
    INBOX_DIR,
    ARCHIVED_DIR,
    FAILED_DIR,
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE, MYSQL_CHARSET,
    get_mysql_config,
    REDIS_URL, VECTOR_INDEX_PREFIX,
    EMBEDDING_MODEL, EMBEDDING_BASE_URL,
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
    MCP_URL,
    TEXT_EXTENSIONS, OFFICE_EXTENSIONS, ENCODING_TRIES,
    MAX_FILE_SIZE, WARN_FILE_SIZE,
    CHUNK_MAX_TOKENS, CHUNK_OVERLAP_TOKENS, CHUNK_MAX_CHARS,
    FILE_SUMMARY_MAX_CHARS, FILE_KEYWORDS_MIN, FILE_KEYWORDS_MAX, SUMMARY_LIST_MAX,
    INDEX_VERSION, ARCHIVE_RETRY_TIMES, INDEX_PENDING_FLAG, META_EXT,
    ensure_dirs,
)
