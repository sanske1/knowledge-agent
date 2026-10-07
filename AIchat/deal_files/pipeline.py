"""
pipeline: 双文件夹归档 + 索引对齐 的端到端流转入口

未处理/  →  loadfile  →  AIsavefile（AI加工+归档+索引）  →  已处理/
                                                          ↘ 失败 → 未处理/.failed/
"""
import os
import sys
import json
from typing import Dict, List, Optional
from dataclasses import dataclass, field

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from .config import INBOX_DIR, ARCHIVED_DIR, FAILED_DIR, META_EXT
from .loadfile import loadfile
from .AIsavefile import AIsavefile, IngestReport
from .storage import Storage


@dataclass
class PipelineReport:
    """未处理区全流程处理报告"""
    scanned: int = 0
    archived: int = 0
    projects: int = 0
    chunks: int = 0
    skipped: int = 0
    failed: int = 0
    failed_details: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "archived": self.archived,
            "projects": self.projects,
            "chunks": self.chunks,
            "skipped": self.skipped,
            "failed": self.failed,
            "failed_details": self.failed_details,
        }


def _ensure_dirs():
    """确保未处理/已处理/.failed 目录存在"""
    os.makedirs(INBOX_DIR, exist_ok=True)
    os.makedirs(ARCHIVED_DIR, exist_ok=True)
    os.makedirs(FAILED_DIR, exist_ok=True)


def _scan_inbox(inbox_dir: str) -> tuple:
    """
    扫描未处理区：
    - 一级子目录 → 文件夹模式（目录名=项目名）
    - 根目录零散文件 → AI 自动聚类模式
    - 跳过 .failed 系统目录
    Returns: (folder_mode_files: List[str], loose_files: List[str])
    """
    folder_files = []  # (project_name, [file_path, ...])
    loose_files = []

    for entry in os.listdir(inbox_dir):
        full = os.path.join(inbox_dir, entry)
        # 跳过系统目录
        if entry.startswith("."):
            continue
        if os.path.isdir(full):
            # 一级子目录 = 项目，递归收集内部文件
            files = []
            for root, _, fs in os.walk(full):
                for f in fs:
                    if not f.endswith(META_EXT):
                        files.append(os.path.join(root, f))
            if files:
                folder_files.append((entry, files))
        elif os.path.isfile(full):
            if not full.endswith(META_EXT):
                loose_files.append(full)

    return folder_files, loose_files


def process_inbox(inbox_dir: Optional[str] = None) -> PipelineReport:
    """
    扫描未处理文件夹并执行完整流转：
    扫描 → loadfile → AIsavefile（归档+索引+清理）→ 输出报告

    Args:
        inbox_dir: 未处理文件夹路径，默认 config.INBOX_DIR

    Returns:
        PipelineReport
    """
    if inbox_dir is None:
        inbox_dir = INBOX_DIR

    _ensure_dirs()
    report = PipelineReport()

    folder_groups, loose_files = _scan_inbox(inbox_dir)
    total = sum(len(fs) for _, fs in folder_groups) + len(loose_files)
    report.scanned = total
    print(f"[pipeline] 扫描未处理区: 文件夹项目 {len(folder_groups)} 个, "
          f"零散文件 {len(loose_files)} 个, 共 {total} 个文件")

    if total == 0:
        print("[pipeline] 未处理区为空，无需处理")
        return report

    # ===== 处理文件夹模式项目（一级子目录 = 项目）=====
    # 收集所有子目录中的文件，一次性交给 AIsavefile，
    # 以 inbox_dir 为 root_dir，使一级子目录名成为项目名
    all_folder_files = []
    for proj_name, files in folder_groups:
        print(f"[pipeline] 文件夹项目: {proj_name} ({len(files)} 个文件)")
        all_folder_files.extend(files)

    if all_folder_files:
        print(f"\n[pipeline] 处理文件夹模式共 {len(all_folder_files)} 个文件")
        raws = loadfile(all_folder_files, recursive=False)
        sub = AIsavefile(raws, mode="folder", root_dir=inbox_dir)
        _merge_report(report, sub)

    # ===== 处理零散文件（AI 自动聚类）=====
    if loose_files:
        print(f"\n[pipeline] 处理零散文件 {len(loose_files)} 个（AI 自动聚类）")
        raws = loadfile(loose_files, recursive=False)
        sub = AIsavefile(raws, mode="auto")
        _merge_report(report, sub)

    print(f"\n[pipeline] 处理完成: 扫描{report.scanned}个, 归档{report.archived}个, "
          f"项目{report.projects}个, 分片{report.chunks}个, "
          f"跳过{report.skipped}个, 失败{report.failed}个")
    return report


def _merge_report(report: PipelineReport, sub: IngestReport):
    report.archived += sub.file_count
    report.projects += sub.project_count
    report.chunks += sub.chunk_count
    report.skipped += len(sub.skipped)
    report.failed += len(sub.failed)
    report.failed_details.extend(sub.failed)


# ==================== 索引管理 ====================
def rebuild_index() -> Dict:
    """
    全量重建向量库：以 MySQL 分片文本为真相源，重新写入 Redis 向量。
    """
    print("[pipeline] 开始全量重建索引...")
    storage = Storage()
    try:
        result = storage.rebuild_index()
    finally:
        storage.close()
    print(f"[pipeline] 索引重建完成: {result}")
    return result


def import_from_disk() -> Dict:
    """
    灾备导入：从磁盘 .meta.json 导入到 MySQL（MySQL 数据丢失时使用）。
    """
    print("[pipeline] 开始从磁盘导入到 MySQL...")
    storage = Storage()
    try:
        result = storage.import_from_disk()
    finally:
        storage.close()
    print(f"[pipeline] 导入完成: {result}")
    return result


def validate_index() -> Dict:
    """
    索引校验：对比已处理文件清单与索引条目，识别异常。
    """
    print("[pipeline] 开始索引校验...")
    storage = Storage()
    try:
        result = storage.validate_index()
    finally:
        storage.close()
    print(f"[pipeline] 索引校验完成: {result}")
    return result


# ==================== 失败管理 ====================
def list_failed(failed_dir: Optional[str] = None) -> List[Dict]:
    """
    列出 .failed 目录中的失败文件。
    Returns: [{filename, size, error_log}]
    """
    if failed_dir is None:
        failed_dir = FAILED_DIR
    result = []
    if not os.path.exists(failed_dir):
        return result
    for f in os.listdir(failed_dir):
        fp = os.path.join(failed_dir, f)
        if os.path.isfile(fp):
            error_log = ""
            log_path = fp + ".error.log"
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as lf:
                        error_log = lf.read()
                except Exception:
                    pass
            stat = os.stat(fp)
            result.append({
                "filename": f,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "error_log": error_log,
            })
    return result


def retry_failed(failed_dir: Optional[str] = None) -> PipelineReport:
    """
    重试 .failed 目录中的所有文件：
    将失败文件移回未处理区根目录，然后执行 process_inbox。
    """
    import shutil
    if failed_dir is None:
        failed_dir = FAILED_DIR
    if not os.path.exists(failed_dir):
        return PipelineReport()

    retried = 0
    for f in os.listdir(failed_dir):
        fp = os.path.join(failed_dir, f)
        if os.path.isfile(fp) and not f.endswith(".error.log"):
            try:
                shutil.move(fp, os.path.join(INBOX_DIR, f))
                retried += 1
            except Exception as e:
                print(f"[pipeline] 重试移动失败 {f}: {e}")
    print(f"[pipeline] 已将 {retried} 个失败文件移回未处理区")
    return process_inbox()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="deal_files 双文件夹归档流水线")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("process", help="扫描并处理未处理区全部文件")
    sub.add_parser("rebuild", help="从 MySQL 重建 Redis 向量库")
    sub.add_parser("import", help="灾备：从磁盘 .meta.json 导入到 MySQL")
    sub.add_parser("validate", help="校验索引与已处理区一致性")
    sub.add_parser("failed", help="列出失败文件")
    sub.add_parser("retry", help="重试失败文件")

    args = parser.parse_args()
    if args.cmd == "process":
        print(json.dumps(process_inbox().to_dict(), ensure_ascii=False, indent=2))
    elif args.cmd == "rebuild":
        print(json.dumps(rebuild_index(), ensure_ascii=False, indent=2))
    elif args.cmd == "import":
        print(json.dumps(import_from_disk(), ensure_ascii=False, indent=2))
    elif args.cmd == "validate":
        print(json.dumps(validate_index(), ensure_ascii=False, indent=2))
    elif args.cmd == "failed":
        print(json.dumps(list_failed(), ensure_ascii=False, indent=2))
    elif args.cmd == "retry":
        print(json.dumps(retry_failed().to_dict(), ensure_ascii=False, indent=2))
    else:
        parser.print_help()
