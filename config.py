# -*- coding: utf-8 -*-
"""
知识库Agent系统 - 统一配置入口（单源真相）
所有模块统一从本文件读取配置，便于用户自定义与跨机器部署。

项目根目录 = 本文件所在目录
所有路径均基于 __file__ 解析，不依赖 CWD，复制到任意位置均可运行。

所有**连接信息与密钥**均可用环境变量覆盖，仓库里不存任何真实凭据。
可覆盖的变量见 README「配置」一节，或 .env.example。
"""
import os

# ==================== 路径配置 ====================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 数据目录（未处理/已处理归档）
DEAL_FILES_DATA_DIR = os.path.join(PROJECT_ROOT, "deal_files_data")
INBOX_DIR = os.path.join(DEAL_FILES_DATA_DIR, "未处理")
ARCHIVED_DIR = os.path.join(DEAL_FILES_DATA_DIR, "已处理")
FAILED_DIR = os.path.join(INBOX_DIR, ".failed")

# 前端静态目录
WEB_DIR = os.path.join(PROJECT_ROOT, "web")

# ==================== MySQL 主存配置 ====================
MYSQL_HOST = os.environ.get("KB_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("KB_MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("KB_MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("KB_MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("KB_MYSQL_DATABASE", "deal_files")
MYSQL_CHARSET = os.environ.get("KB_MYSQL_CHARSET", "utf8mb4")


def get_mysql_config() -> dict:
    return {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "database": MYSQL_DATABASE,
        "charset": MYSQL_CHARSET,
    }


# ==================== Redis 向量库配置 ====================
REDIS_URL = os.environ.get("KB_REDIS_URL", "redis://127.0.0.1:6379")
VECTOR_INDEX_PREFIX = os.environ.get("KB_VECTOR_INDEX_PREFIX", "deal_files_chunks")


# ==================== Ollama 嵌入模型配置 ====================
EMBEDDING_MODEL = os.environ.get("KB_EMBEDDING_MODEL", "bge-m3:latest")
EMBEDDING_BASE_URL = os.environ.get("KB_EMBEDDING_BASE_URL", "http://localhost:11434")


# ==================== LLM 大模型配置 ====================
# 密钥从环境变量读，仓库里不放明文；本地开发在 .env.example 的基础上建 .env
LLM_API_KEY = os.environ.get("KB_LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("KB_LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("KB_LLM_MODEL", "deepseek-chat")


# ==================== MCP 连接配置 ====================
# MCP 服务器由用户自行搭建，在此填写默认 MCP 服务地址（也可通过 /api/mcp/add 动态添加）
MCP_URL = os.environ.get("KB_MCP_URL", "http://127.0.0.1:8889/mcp")


# ==================== WebAPI 服务配置 ====================
WEBAPI_HOST = os.environ.get("KB_WEBAPI_HOST", "0.0.0.0")
WEBAPI_PORT = int(os.environ.get("KB_WEBAPI_PORT", "8000"))


# ==================== 文件处理配置 ====================
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".json", ".csv", ".log",
    ".js", ".ts", ".html", ".css", ".xml", ".yaml", ".yml",
    ".ini", ".conf", ".sh", ".bat", ".sql", ".java", ".c",
    ".cpp", ".h", ".go", ".rs", ".toml", ".rst",
}
OFFICE_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"}
ENCODING_TRIES = ["utf-8", "gbk", "gb2312", "utf-16", "latin-1"]
MAX_FILE_SIZE = 50 * 1024 * 1024
WARN_FILE_SIZE = 10 * 1024 * 1024

# 分片配置
CHUNK_MAX_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
CHUNK_MAX_CHARS = 1000

# AI 加工配置
FILE_SUMMARY_MAX_CHARS = 300
FILE_KEYWORDS_MIN = 3
FILE_KEYWORDS_MAX = 8
SUMMARY_LIST_MAX = 20

# 归档与一致性
INDEX_VERSION = "1.0"
ARCHIVE_RETRY_TIMES = 3
INDEX_PENDING_FLAG = "_index_pending"
META_EXT = ".meta.json"


def ensure_dirs():
    """确保数据目录存在。"""
    for d in (DEAL_FILES_DATA_DIR, INBOX_DIR, ARCHIVED_DIR, FAILED_DIR):
        os.makedirs(d, exist_ok=True)
