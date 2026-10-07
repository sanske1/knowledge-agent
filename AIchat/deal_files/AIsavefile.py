"""
AIsavefile: 项目分级 + AI结构化加工 + 双层存储 + 三级索引

不直接读取磁盘文件，只接收 loadfile 输出的 FileRaw 对象。
职责边界：AI 加工 + 存储 + 索引，不做文件 IO。
"""
import os
import sys
import json
import uuid
import re
from typing import List, Dict, Optional
from dataclasses import dataclass, field

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from .config import (
    CHUNK_MAX_CHARS, CHUNK_OVERLAP_TOKENS, FILE_SUMMARY_MAX_CHARS,
    FILE_KEYWORDS_MIN, FILE_KEYWORDS_MAX, WARN_FILE_SIZE,
    INDEX_VERSION,
)
from .models import FileRaw, FileChunk, FileMeta, ProjectIndex, FileIndex
from .storage import Storage

# 复用 Chat 模块的 DeepSeek 模型做 AI 加工
from AIchat.Chat.LLM import ds as llm_model


# ==================== 入库报告 ====================
@dataclass
class IngestReport:
    project_count: int = 0
    file_count: int = 0
    chunk_count: int = 0
    skipped: List[str] = field(default_factory=list)   # 幂等跳过的文件
    failed: List[str] = field(default_factory=list)     # 失败的文件及原因

    def to_dict(self) -> dict:
        return {
            "project_count": self.project_count,
            "file_count": self.file_count,
            "chunk_count": self.chunk_count,
            "skipped": self.skipped,
            "failed": self.failed,
        }


# ==================== 文本分片 ====================
def chunk_text(file_raw: FileRaw) -> List[FileChunk]:
    """
    按字符长度切分，保留段落边界，相邻分片重叠，不切断完整语义。
    表格、代码块尽量整体保留。
    """
    if not file_raw.content.strip():
        return []

    chunks = []
    paragraphs = file_raw.paragraphs if file_raw.paragraphs else [file_raw.content]

    current = ""
    chunk_idx = 0
    for para in paragraphs:
        para_text = para.text if hasattr(para, "text") else str(para)
        # 段落过长则单独切分
        if len(para_text) > CHUNK_MAX_CHARS:
            # 先 flush 当前累积
            if current.strip():
                chunks.append(_make_chunk(file_raw, current, chunk_idx))
                chunk_idx += 1
                current = ""
            # 长段落按字符切分，带重叠
            for i in range(0, len(para_text), CHUNK_MAX_CHARS - 100):
                piece = para_text[i:i + CHUNK_MAX_CHARS]
                chunks.append(_make_chunk(file_raw, piece, chunk_idx))
                chunk_idx += 1
        else:
            if len(current) + len(para_text) > CHUNK_MAX_CHARS and current.strip():
                chunks.append(_make_chunk(file_raw, current, chunk_idx))
                chunk_idx += 1
                # 重叠：保留当前段落的尾部作为下一分片开头
                overlap_len = min(100, len(current))
                current = current[-overlap_len:] + "\n" + para_text
            else:
                current += ("\n" if current else "") + para_text

    if current.strip():
        chunks.append(_make_chunk(file_raw, current, chunk_idx))

    return chunks


def _make_chunk(file_raw: FileRaw, text: str, idx: int) -> FileChunk:
    return FileChunk(
        chunk_id=f"{file_raw.file_id}_c{idx}",
        file_id=file_raw.file_id,
        project_id="",  # 后续填充
        text=text.strip(),
        start_pos=file_raw.content.find(text[:20]) if text else 0,
        end_pos=file_raw.content.find(text[:20]) + len(text) if text else 0,
    )


# ==================== AI 加工 ====================
def ai_file_summary(file_raw: FileRaw) -> Dict:
    """
    文件级 AI 加工：生成 300 字以内摘要、3-8 个关键词、内容类型标签。
    大文件降级：超过告警阈值时仅取前 N 字符做摘要。
    """
    content = file_raw.content
    if file_raw.size > WARN_FILE_SIZE:
        # 大文件降级：仅取前 8000 字符
        content = content[:8000]

    prompt = (
        "请阅读以下文档内容，输出 JSON 格式结果，包含三个字段：\n"
        '{"summary": "300字以内的内容摘要", "keywords": ["关键词1","关键词2"], "content_type": "内容类型标签"}\n'
        "要求：\n"
        f"1. summary 不超过 {FILE_SUMMARY_MAX_CHARS} 字\n"
        f"2. keywords 为 {FILE_KEYWORDS_MIN}-{FILE_KEYWORDS_MAX} 个核心关键词\n"
        "3. content_type 用一个短语描述文档类型（如技术文档/会议纪要/需求文档等）\n"
        "4. 只输出 JSON，不要其他文字\n\n"
        f"文档内容：\n{content[:6000]}"
    )

    try:
        resp = llm_model.invoke([{"role": "user", "content": prompt}])
        text = resp.content if hasattr(resp, "content") else str(resp)
        # 提取 JSON（兼容模型输出多余文字）
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            data = {"summary": text[:FILE_SUMMARY_MAX_CHARS], "keywords": [], "content_type": ""}
        # 字段兜底
        data.setdefault("summary", "")
        data.setdefault("keywords", [])
        data.setdefault("content_type", "")
        if len(data["summary"]) > FILE_SUMMARY_MAX_CHARS:
            data["summary"] = data["summary"][:FILE_SUMMARY_MAX_CHARS]
        if not isinstance(data["keywords"], list):
            data["keywords"] = [str(data["keywords"])]
        return data
    except Exception as e:
        print(f"[AIsavefile] 文件摘要失败 {file_raw.filename}: {e}")
        return {"summary": "", "keywords": [], "content_type": ""}


def ai_project_summary(project_name: str, file_summaries: List[str]) -> Dict:
    """
    项目级 AI 加工：聚合文件摘要，生成项目总览摘要、核心主题、文档清单。
    """
    summaries_text = "\n".join(f"- {s}" for s in file_summaries if s)
    prompt = (
        f"以下是项目「{project_name}」中所有文档的摘要：\n{summaries_text}\n\n"
        "请输出 JSON 格式结果：\n"
        '{"summary": "项目总览摘要", "themes": ["核心主题1","核心主题2"], "doc_list": ["文档1","文档2"]}\n'
        "要求：\n"
        "1. summary 概括项目整体内容\n"
        "2. themes 为 3-6 个核心主题\n"
        "3. doc_list 为项目内文档清单\n"
        "4. 只输出 JSON"
    )

    try:
        resp = llm_model.invoke([{"role": "user", "content": prompt}])
        text = resp.content if hasattr(resp, "content") else str(resp)
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            data = {"summary": text, "themes": [], "doc_list": []}
        data.setdefault("summary", "")
        data.setdefault("themes", [])
        data.setdefault("doc_list", [])
        return data
    except Exception as e:
        print(f"[AIsavefile] 项目摘要失败 {project_name}: {e}")
        return {"summary": "", "themes": [], "doc_list": []}


def ai_auto_classify(file_raws: List[FileRaw]) -> Dict[str, List[FileRaw]]:
    """
    AI 自动聚合模式：基于内容主题/关键词/命名规则进行语义聚类，
    自动生成项目名称，将文件分配到项目。
    """
    if not file_raws:
        return {}

    # 取每个文件的文件名+前200字作为聚类依据
    file_briefs = []
    for fr in file_raws:
        brief = f"文件名:{fr.filename}\n内容片段:{fr.content[:200]}"
        file_briefs.append(brief)

    prompt = (
        "请将以下文件按主题语义聚类为若干项目，输出 JSON：\n"
        '{"项目名1": [0, 2], "项目名2": [1, 3]}\n'
        "数字为文件序号。项目名应简洁描述主题。\n\n"
        + "\n---\n".join(f"[{i}]\n{b}" for i, b in enumerate(file_briefs))
    )

    try:
        resp = llm_model.invoke([{"role": "user", "content": prompt}])
        text = resp.content if hasattr(resp, "content") else str(resp)
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            clusters = json.loads(json_match.group())
        else:
            clusters = {}
    except Exception as e:
        print(f"[AIsavefile] AI 聚类失败，降级为单文件单项目: {e}")
        clusters = {}

    # 校验并构建结果
    result = {}
    assigned = set()
    for proj_name, indices in clusters.items():
        if not isinstance(indices, list):
            continue
        valid_indices = [i for i in indices if isinstance(i, int) and 0 <= i < len(file_raws)]
        if valid_indices:
            result[proj_name] = [file_raws[i] for i in valid_indices]
            assigned.update(valid_indices)

    # 未分配的文件各自成项
    for i, fr in enumerate(file_raws):
        if i not in assigned:
            proj_name = os.path.splitext(fr.filename)[0]
            result.setdefault(proj_name, []).append(fr)

    return result


# ==================== 主入口 ====================
def AIsavefile(
    file_raws: List[FileRaw],
    mode: str = "folder",
    auto_classify: bool = False,
    root_dir: Optional[str] = None,
    cleanup: bool = True,
    failed_dir: Optional[str] = None,
) -> IngestReport:
    """
    文件入库第二步：项目分级 → AI加工 → 归档（原始文件+.meta.json）→ 索引 → 清理未处理区。

    Args:
        file_raws: loadfile 输出的 FileRaw 列表
        mode: "folder"（文件夹映射，默认）或 "auto"（AI自动聚合）
        auto_classify: 是否强制 AI 自动分类
        root_dir: 文件夹模式下的根目录，用于推断项目名
        cleanup: 归档+索引成功后是否删除未处理区原文件（默认 True）
        failed_dir: 失败文件移入目录（默认 未处理/.failed）

    Returns:
        IngestReport: 入库报告
    """
    import shutil
    from .config import FAILED_DIR

    if failed_dir is None:
        failed_dir = FAILED_DIR
    os.makedirs(failed_dir, exist_ok=True)

    storage = Storage()
    report = IngestReport()

    # 只处理解析成功的文件
    valid_raws = [fr for fr in file_raws if fr.success]
    failed_raws = [fr for fr in file_raws if not fr.success]
    for fr in failed_raws:
        report.failed.append(f"{fr.filename}: {fr.error}")
        # 解析失败的文件移入 .failed
        try:
            if os.path.exists(fr.abs_path):
                shutil.move(fr.abs_path, os.path.join(failed_dir, fr.filename))
        except Exception as e:
            print(f"[AIsavefile] 移动失败文件出错 {fr.filename}: {e}")

    if not valid_raws:
        print("[AIsavefile] 无有效文件可入库")
        storage.close()
        return report

    # ========== 项目分级 ==========
    if mode == "auto" or auto_classify:
        print("[AIsavefile] 模式 B: AI 自动聚合分类...")
        project_map = ai_auto_classify(valid_raws)
    else:
        print("[AIsavefile] 模式 A: 文件夹映射...")
        project_map = {}
        for fr in valid_raws:
            if root_dir:
                rel = os.path.relpath(fr.abs_path, root_dir)
                parts = rel.split(os.sep)
                proj_name = parts[0] if len(parts) > 1 else "_root"
            else:
                proj_name = os.path.basename(os.path.dirname(fr.abs_path)) or "_root"
            project_map.setdefault(proj_name, []).append(fr)

    print(f"[AIsavefile] 分为 {len(project_map)} 个项目")

    # ========== 逐项目处理 ==========
    for proj_name, proj_files in project_map.items():
        project_id = str(uuid.uuid4())
        print(f"\n[AIsavefile] 处理项目: {proj_name} (id={project_id[:8]})")

        file_ids = []
        file_summaries = []
        all_chunk_ids = []
        vector_store = storage.get_vector_store(project_id)

        for fr in proj_files:
            # 幂等检查：基于 fingerprint（已处理区是否已存在同指纹）
            existing = storage.index.get_file_by_fingerprint(fr.fingerprint)
            if existing:
                report.skipped.append(f"{fr.filename} (已存在，fingerprint 一致)")
                print(f"  ⏭️  {fr.filename} 已存在，跳过")
                file_ids.append(existing.file_id)
                file_summaries.append(existing.summary)
                # 幂等跳过也清理未处理区原文件
                if cleanup and os.path.exists(fr.abs_path):
                    try:
                        os.remove(fr.abs_path)
                    except Exception:
                        pass
                continue

            try:
                # 1. AI 文件级加工
                ai_result = ai_file_summary(fr)
                summary = ai_result["summary"]
                keywords = ai_result["keywords"]
                content_type = ai_result["content_type"]

                # 2. 分片
                chunks = chunk_text(fr)
                for c in chunks:
                    c.project_id = project_id
                chunk_ids = [c.chunk_id for c in chunks]

                # 3. 构建 FileMeta（.meta.json 内容）
                chunks_meta = [
                    {
                        "chunk_id": c.chunk_id,
                        "text": c.text,
                        "start_pos": c.start_pos,
                        "end_pos": c.end_pos,
                        "page": c.page,
                    }
                    for c in chunks
                ]
                meta = FileMeta(
                    file_id=fr.file_id,
                    filename=fr.filename,
                    ext=fr.ext,
                    size=fr.size,
                    mtime=fr.mtime,
                    fingerprint=fr.fingerprint,
                    project_id=project_id,
                    project_name=proj_name,
                    summary=summary,
                    keywords=keywords,
                    content_type=content_type,
                    chunks=chunks_meta,
                    index_version=INDEX_VERSION,
                    index_pending=False,
                )

                # 4. 归档：复制原始文件到已处理区 + 写入 .meta.json
                storage.archiver.archive_file(fr, meta)

                # 5. 分片文本写入 MySQL 主存
                storage.index.upsert_chunks(chunks)

                # 6. 索引更新（项目批次内统一处理，此处先写文件索引）
                index_ok = True
                try:
                    file_index = FileIndex(
                        file_id=fr.file_id,
                        project_id=project_id,
                        filename=fr.filename,
                        abs_path=os.path.join(storage.archiver.project_dir(proj_name), fr.filename),
                        summary=summary,
                        keywords=keywords,
                        content_type=content_type,
                        chunk_ids=chunk_ids,
                        fingerprint=fr.fingerprint,
                    )
                    storage.index.upsert_file(file_index)
                except Exception as e:
                    index_ok = False
                    print(f"  ⚠️  {fr.filename} 索引写入失败（已归档，标记待同步）: {e}")
                    storage.archiver.mark_index_pending(proj_name, fr.filename, True)

                # 6. 向量入库（失败不阻塞，已归档）
                if chunks:
                    try:
                        vector_store.add_chunks(chunks)
                    except Exception as e:
                        print(f"  ⚠️  {fr.filename} 向量入库失败（已归档+索引）: {e}")

                # 7. 双确认后清理未处理区原文件
                if cleanup and os.path.exists(fr.abs_path):
                    try:
                        os.remove(fr.abs_path)
                    except Exception as e:
                        print(f"  ⚠️  清理未处理区文件失败 {fr.filename}: {e}")

                file_ids.append(fr.file_id)
                file_summaries.append(summary)
                all_chunk_ids.extend(chunk_ids)
                report.file_count += 1
                report.chunk_count += len(chunks)
                print(f"  ✅ {fr.filename}: {len(chunks)} 分片, 摘要={summary[:30]}...")

            except Exception as e:
                # 归档或加工失败：移入 .failed
                report.failed.append(f"{fr.filename}: {str(e)}")
                print(f"  ❌ {fr.filename}: {e}")
                try:
                    if os.path.exists(fr.abs_path):
                        shutil.move(fr.abs_path, os.path.join(failed_dir, fr.filename))
                        print(f"  📁 已移入失败目录: {failed_dir}")
                except Exception as move_err:
                    print(f"  ⚠️  移入失败目录也失败: {move_err}")

        # 8. 项目级 AI 加工 + 项目索引
        proj_ai = ai_project_summary(proj_name, file_summaries)
        project_index = ProjectIndex(
            project_id=project_id,
            name=proj_name,
            summary=proj_ai.get("summary", ""),
            themes=proj_ai.get("themes", []),
            file_ids=file_ids,
        )
        storage.index.upsert_project(project_index)
        report.project_count += 1
        print(f"  项目摘要: {proj_ai.get('summary', '')[:50]}...")

    storage.close()
    print(f"\n[AIsavefile] 入库完成: 项目{report.project_count}个, "
          f"文件{report.file_count}个, 分片{report.chunk_count}个, "
          f"跳过{len(report.skipped)}个, 失败{len(report.failed)}个")
    return report


# ==================== 检索入口（溯源）====================
def search_chunks(project_id: str, query: str, k: int = 5) -> List[dict]:
    """
    语义检索：召回 TopN 分片，反向关联文件与项目元数据，组装上下文。
    返回带引用来源的结果列表。
    """
    storage = Storage()
    vector_store = storage.get_vector_store(project_id)
    results = vector_store.search(query, k=k)

    enriched = []
    for text, meta, score in results:
        file_id = meta.get("file_id", "")
        file_index = None
        # 反向关联文件
        for f in storage.index.get_files_by_project(project_id):
            if f.file_id == file_id:
                file_index = f
                break
        project = storage.index.get_project(project_id)
        enriched.append({
            "text": text,
            "score": score,
            "chunk_id": meta.get("chunk_id"),
            "file_id": file_id,
            "filename": file_index.filename if file_index else "",
            "file_summary": file_index.summary if file_index else "",
            "project_id": project_id,
            "project_name": project.name if project else "",
            "page": meta.get("page"),
            "start_pos": meta.get("start_pos"),
        })

    storage.close()
    return enriched


def format_citation(result: dict) -> str:
    """引用标注：《文件名》（项目名），第X页/段落"""
    page = result.get("page")
    page_info = f"，第{page}页" if page else ""
    return f"《{result['filename']}》（{result['project_name']}）{page_info}"


# ==================== 跨项目检索 + Graph 工具 ====================
def search_all(query: str, k: int = 5) -> List[dict]:
    """
    跨项目语义检索：遍历 MySQL 中所有项目，分别做向量检索，
    按 score 合并去重后返回 TopK，带完整溯源信息。
    """
    storage = Storage()
    try:
        projects = storage.index.list_projects()
        if not projects:
            return []

        all_results = []
        for proj in projects:
            try:
                vs = storage.get_vector_store(proj.project_id)
                hits = vs.search(query, k=k)
            except Exception as e:
                print(f"[search_all] 项目 {proj.name} 检索失败: {e}")
                continue
            for text, meta, score in hits:
                file_id = meta.get("file_id", "")
                file_index = next(
                    (f for f in storage.index.get_files_by_project(proj.project_id)
                     if f.file_id == file_id), None)
                all_results.append({
                    "text": text,
                    "score": float(score),
                    "chunk_id": meta.get("chunk_id"),
                    "file_id": file_id,
                    "filename": file_index.filename if file_index else "",
                    "file_summary": file_index.summary if file_index else "",
                    "project_id": proj.project_id,
                    "project_name": proj.name,
                    "page": meta.get("page"),
                    "start_pos": meta.get("start_pos"),
                })

        # langchain_redis 返回的是距离（score 越小越相似），升序排列取 TopK
        all_results.sort(key=lambda r: r["score"])
        return all_results[:k]
    finally:
        storage.close()


# LangChain 工具：供 graph 直接调用
from langchain_core.tools import tool as _lc_tool


@_lc_tool
def search_File_index(query: str, top_k: int = 5) -> str:
    """
    在已归档的文档库中进行语义检索，返回最相关的文档片段及来源信息。

    参数:
        query: 用户的查询问题或关键词
        top_k: 返回的最相关结果数量，默认5

    返回: 包含片段文本、文件名、项目名、相似度分数的结构化结果。
    """
    results = search_all(query, k=top_k)
    if not results:
        return "未检索到相关文档内容。"
    parts = []
    for i, r in enumerate(results, 1):
        cite = format_citation(r)
        parts.append(
            f"[{i}] 来源: {cite}\n"
            f"    相似度: {r['score']:.4f}\n"
            f"    内容: {r['text']}"
        )
    return "\n\n".join(parts)


if __name__ == "__main__":
    pass
