"""
deal_files: 文件入库与语义记忆存储模块

核心流程（双文件夹归档 + 索引对齐）：
  未处理/  →  loadfile(解析)  →  AIsavefile(AI加工+归档+索引+清理)  →  已处理/
                                                              ↘ 失败 → 未处理/.failed/

入口：
- loadfile:        文件识别、格式适配、内容读取与标准化（纯IO）
- AIsavefile:      项目分级、AI结构化加工、归档（原始文件+.meta.json）、索引构建
- process_inbox:   扫描未处理区全流程
- rebuild_index:   以已处理区为真相源全量重建索引
- validate_index:  校验索引与已处理区一致性
- list_failed:     列出失败文件
- retry_failed:    重试失败文件
"""
from .loadfile import loadfile, FileRaw
from .AIsavefile import AIsavefile, IngestReport
from .pipeline import (
    process_inbox,
    rebuild_index,
    import_from_disk,
    validate_index,
    list_failed,
    retry_failed,
    PipelineReport,
)

__all__ = [
    "loadfile",
    "FileRaw",
    "AIsavefile",
    "IngestReport",
    "process_inbox",
    "rebuild_index",
    "import_from_disk",
    "validate_index",
    "list_failed",
    "retry_failed",
    "PipelineReport",
]
