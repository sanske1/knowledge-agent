"""
数据结构定义：FileRaw（loadfile 输出）、分片、索引等
"""
from dataclasses import dataclass, field
from typing import Optional
import time
import hashlib


@dataclass
class Paragraph:
    """段落结构：带起始位置"""
    text: str
    start_pos: int = 0
    end_pos: int = 0
    page: Optional[int] = None        # 页码（如有）
    heading_level: Optional[int] = None  # 标题层级（如有）


@dataclass
class FileRaw:
    """
    loadfile 标准化输出对象，作为与 AIsavefile 的交互协议。
    只做纯 IO 与解析后的结果承载，不包含任何 AI 加工字段。
    """
    file_id: str                    # 文件唯一 ID（基于路径+修改时间的哈希）
    abs_path: str                   # 绝对路径
    filename: str                   # 文件名
    ext: str                        # 后缀（小写，含点）
    size: int                       # 文件大小（字节）
    mtime: float                    # 修改时间戳
    content: str = ""               # 全文纯文本
    paragraphs: list = field(default_factory=list)  # 段落结构列表
    page_map: dict = field(default_factory=dict)     # 页码映射（如有）
    success: bool = True            # 解析成功/失败
    error: str = ""                 # 失败原因

    @property
    def fingerprint(self) -> str:
        """幂等指纹：文件名 + 文件大小 + 修改时间戳"""
        raw = f"{self.filename}|{self.size}|{self.mtime}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()


@dataclass
class FileChunk:
    """文本分片：用于语义向量库"""
    chunk_id: str
    file_id: str
    project_id: str
    text: str
    start_pos: int
    end_pos: int
    page: Optional[int] = None
    paragraph_idx: Optional[int] = None


@dataclass
class ProjectIndex:
    """项目索引"""
    project_id: str
    name: str
    summary: str = ""
    themes: list = field(default_factory=list)
    file_ids: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class FileIndex:
    """文件索引"""
    file_id: str
    project_id: str
    filename: str
    abs_path: str
    summary: str = ""
    keywords: list = field(default_factory=list)
    content_type: str = ""
    chunk_ids: list = field(default_factory=list)
    fingerprint: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class FileMeta:
    """
    .meta.json 侧录文件内容：归档真相源的结构化元数据。
    重建索引时直接读取此文件，无需重新解析/重新调用 AI。
    """
    file_id: str
    filename: str
    ext: str
    size: int
    mtime: float
    fingerprint: str
    project_id: str
    project_name: str
    summary: str = ""
    keywords: list = field(default_factory=list)
    content_type: str = ""
    chunks: list = field(default_factory=list)   # [{chunk_id, text, start_pos, end_pos, page}]
    index_version: str = "1.0"
    index_pending: bool = False                  # 索引待同步标记
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "ext": self.ext,
            "size": self.size,
            "mtime": self.mtime,
            "fingerprint": self.fingerprint,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "summary": self.summary,
            "keywords": self.keywords,
            "content_type": self.content_type,
            "chunks": self.chunks,
            "index_version": self.index_version,
            "index_pending": self.index_pending,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FileMeta":
        return cls(
            file_id=d.get("file_id", ""),
            filename=d.get("filename", ""),
            ext=d.get("ext", ""),
            size=d.get("size", 0),
            mtime=d.get("mtime", 0),
            fingerprint=d.get("fingerprint", ""),
            project_id=d.get("project_id", ""),
            project_name=d.get("project_name", ""),
            summary=d.get("summary", ""),
            keywords=d.get("keywords", []),
            content_type=d.get("content_type", ""),
            chunks=d.get("chunks", []),
            index_version=d.get("index_version", "1.0"),
            index_pending=d.get("index_pending", False),
            created_at=d.get("created_at", time.time()),
        )
