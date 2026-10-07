"""
storage: 双文件夹归档 + 三级索引

MySQL  = 主存：项目索引 + 文件索引 + 分片文本（真相源）
磁盘   = 已处理文件夹：原始文件 + .meta.json 侧录（备份/可移植）
Redis  = 语义分片向量库（可从 MySQL 重建）
"""
import os
import sys
import json
import shutil
import time
import uuid
from typing import List, Optional, Dict

import pymysql
from pymysql.cursors import DictCursor

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from .config import (
    ARCHIVED_DIR, REDIS_URL, VECTOR_INDEX_PREFIX,
    META_EXT, INDEX_VERSION, ARCHIVE_RETRY_TIMES,
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD,
    MYSQL_DATABASE, MYSQL_CHARSET,
)
from .models import FileRaw, FileChunk, FileMeta, ProjectIndex, FileIndex


# ==================== MySQL 主存层（索引 + 分片文本）====================
class MySQLIndex:
    """
    MySQL 主存：项目索引 + 文件索引 + 分片文本。
    真相源，磁盘 .meta.json 仅作侧录备份。
    """

    def __init__(self):
        self._conn = None
        self._connect()
        self._init_tables()

    def _connect(self):
        self._conn = pymysql.connect(
            host=MYSQL_HOST, port=MYSQL_PORT,
            user=MYSQL_USER, password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE, charset=MYSQL_CHARSET,
            cursorclass=DictCursor, autocommit=False,
        )

    def _ensure_conn(self):
        """连接保活：断开则重连。"""
        try:
            self._conn.ping(reconnect=True)
        except Exception:
            self._connect()

    def _cursor(self):
        self._ensure_conn()
        return self._conn.cursor()

    def _init_tables(self):
        cur = self._cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                summary TEXT,
                themes TEXT,
                file_ids TEXT,
                created_at DOUBLE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS files (
                file_id VARCHAR(64) PRIMARY KEY,
                project_id VARCHAR(64) NOT NULL,
                filename VARCHAR(512) NOT NULL,
                abs_path TEXT NOT NULL,
                summary TEXT,
                keywords TEXT,
                content_type VARCHAR(128),
                chunk_ids TEXT,
                fingerprint VARCHAR(64) NOT NULL,
                created_at DOUBLE,
                INDEX idx_files_project (project_id),
                INDEX idx_files_fingerprint (fingerprint)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id VARCHAR(128) PRIMARY KEY,
                file_id VARCHAR(64) NOT NULL,
                project_id VARCHAR(64) NOT NULL,
                text LONGTEXT NOT NULL,
                start_pos INT DEFAULT 0,
                end_pos INT DEFAULT 0,
                page INT DEFAULT 0,
                INDEX idx_chunks_file (file_id),
                INDEX idx_chunks_project (project_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        self._conn.commit()

    # ---------- 项目 ----------
    def upsert_project(self, project: ProjectIndex):
        cur = self._cursor()
        cur.execute("""
            INSERT INTO projects (project_id, name, summary, themes, file_ids, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                name=VALUES(name), summary=VALUES(summary),
                themes=VALUES(themes), file_ids=VALUES(file_ids)
        """, (
            project.project_id, project.name, project.summary,
            json.dumps(project.themes, ensure_ascii=False),
            json.dumps(project.file_ids, ensure_ascii=False),
            project.created_at,
        ))
        self._conn.commit()

    def get_project(self, project_id: str) -> Optional[ProjectIndex]:
        cur = self._cursor()
        cur.execute("SELECT * FROM projects WHERE project_id=%s", (project_id,))
        row = cur.fetchone()
        if not row:
            return None
        return ProjectIndex(
            project_id=row["project_id"], name=row["name"],
            summary=row["summary"], themes=json.loads(row["themes"]),
            file_ids=json.loads(row["file_ids"]), created_at=row["created_at"],
        )

    def list_projects(self) -> List[ProjectIndex]:
        cur = self._cursor()
        cur.execute("SELECT * FROM projects ORDER BY created_at DESC")
        return [ProjectIndex(
            project_id=r["project_id"], name=r["name"],
            summary=r["summary"], themes=json.loads(r["themes"]),
            file_ids=json.loads(r["file_ids"]), created_at=r["created_at"],
        ) for r in cur.fetchall()]

    # ---------- 文件 ----------
    def upsert_file(self, file: FileIndex):
        cur = self._cursor()
        cur.execute("""
            INSERT INTO files (file_id, project_id, filename, abs_path, summary,
                               keywords, content_type, chunk_ids, fingerprint, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                project_id=VALUES(project_id), filename=VALUES(filename),
                abs_path=VALUES(abs_path), summary=VALUES(summary),
                keywords=VALUES(keywords), content_type=VALUES(content_type),
                chunk_ids=VALUES(chunk_ids), fingerprint=VALUES(fingerprint)
        """, (
            file.file_id, file.project_id, file.filename, file.abs_path,
            file.summary, json.dumps(file.keywords, ensure_ascii=False),
            file.content_type, json.dumps(file.chunk_ids, ensure_ascii=False),
            file.fingerprint, file.created_at,
        ))
        self._conn.commit()

    def get_file_by_fingerprint(self, fingerprint: str) -> Optional[FileIndex]:
        cur = self._cursor()
        cur.execute("SELECT * FROM files WHERE fingerprint=%s", (fingerprint,))
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_file(row)

    def get_files_by_project(self, project_id: str) -> List[FileIndex]:
        cur = self._cursor()
        cur.execute("SELECT * FROM files WHERE project_id=%s", (project_id,))
        return [self._row_to_file(r) for r in cur.fetchall()]

    def list_files(self) -> List[FileIndex]:
        cur = self._cursor()
        cur.execute("SELECT * FROM files")
        return [self._row_to_file(r) for r in cur.fetchall()]

    def _row_to_file(self, r) -> FileIndex:
        return FileIndex(
            file_id=r["file_id"], project_id=r["project_id"],
            filename=r["filename"], abs_path=r["abs_path"],
            summary=r["summary"], keywords=json.loads(r["keywords"]),
            content_type=r["content_type"], chunk_ids=json.loads(r["chunk_ids"]),
            fingerprint=r["fingerprint"], created_at=r["created_at"],
        )

    # ---------- 分片文本（新增）----------
    def upsert_chunks(self, chunks: List[FileChunk]):
        """批量写入分片文本。"""
        if not chunks:
            return
        cur = self._cursor()
        cur.executemany("""
            INSERT INTO chunks (chunk_id, file_id, project_id, text, start_pos, end_pos, page)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                file_id=VALUES(file_id), project_id=VALUES(project_id),
                text=VALUES(text), start_pos=VALUES(start_pos),
                end_pos=VALUES(end_pos), page=VALUES(page)
        """, [
            (c.chunk_id, c.file_id, c.project_id, c.text,
             c.start_pos, c.end_pos, c.page or 0)
            for c in chunks
        ])
        self._conn.commit()

    def get_chunks_by_file(self, file_id: str) -> List[dict]:
        cur = self._cursor()
        cur.execute("SELECT * FROM chunks WHERE file_id=%s ORDER BY start_pos", (file_id,))
        return list(cur.fetchall())

    def get_chunks_by_project(self, project_id: str) -> List[dict]:
        cur = self._cursor()
        cur.execute("SELECT * FROM chunks WHERE project_id=%s ORDER BY start_pos", (project_id,))
        return list(cur.fetchall())

    def list_all_chunks(self) -> List[dict]:
        cur = self._cursor()
        cur.execute("SELECT * FROM chunks")
        return list(cur.fetchall())

    # ---------- 删除 / 清空 ----------
    def delete_file(self, file_id: str):
        cur = self._cursor()
        cur.execute("DELETE FROM chunks WHERE file_id=%s", (file_id,))
        cur.execute("DELETE FROM files WHERE file_id=%s", (file_id,))
        self._conn.commit()

    def delete_project(self, project_id: str):
        cur = self._cursor()
        cur.execute("DELETE FROM chunks WHERE project_id=%s", (project_id,))
        cur.execute("DELETE FROM files WHERE project_id=%s", (project_id,))
        cur.execute("DELETE FROM projects WHERE project_id=%s", (project_id,))
        self._conn.commit()

    def clear_all(self):
        """全量重建时清空所有索引 + 分片。"""
        cur = self._cursor()
        cur.execute("DELETE FROM chunks")
        cur.execute("DELETE FROM files")
        cur.execute("DELETE FROM projects")
        self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


# ==================== 归档层（已处理文件夹）====================
class Archiver:
    """
    已处理文件夹归档：原始文件 + .meta.json 侧录。
    索引的唯一真相源。
    """

    def __init__(self, archived_dir: str = ARCHIVED_DIR):
        self.archived_dir = archived_dir
        os.makedirs(self.archived_dir, exist_ok=True)

    def project_dir(self, project_name: str) -> str:
        return os.path.join(self.archived_dir, project_name)

    def archive_file(self, file_raw: FileRaw, meta: FileMeta) -> tuple:
        """
        归档：复制原始文件到已处理区 + 写入同名 .meta.json。
        返回 (archived_file_path, meta_path)。
        失败重试 ARCHIVE_RETRY_TIMES 次。
        """
        proj_dir = self.project_dir(meta.project_name)
        os.makedirs(proj_dir, exist_ok=True)

        dest_file = os.path.join(proj_dir, file_raw.filename)
        dest_meta = os.path.join(proj_dir, f"{file_raw.filename}{META_EXT}")

        last_error = None
        for attempt in range(1, ARCHIVE_RETRY_TIMES + 1):
            try:
                # 复制原始文件（保持格式不变）
                shutil.copy2(file_raw.abs_path, dest_file)
                # 写入 .meta.json
                with open(dest_meta, "w", encoding="utf-8") as f:
                    json.dump(meta.to_dict(), f, ensure_ascii=False, indent=2)
                return dest_file, dest_meta
            except Exception as e:
                last_error = e
                print(f"[归档] 第{attempt}次失败 {file_raw.filename}: {e}")
                time.sleep(0.5 * attempt)

        raise RuntimeError(f"归档失败（重试{ARCHIVE_RETRY_TIMES}次）: {last_error}")

    def read_meta(self, project_name: str, filename: str) -> Optional[FileMeta]:
        """读取已归档文件的 .meta.json。"""
        meta_path = os.path.join(self.project_dir(project_name), f"{filename}{META_EXT}")
        if not os.path.exists(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return FileMeta.from_dict(json.load(f))
        except Exception:
            return None

    def list_all_metas(self) -> List[FileMeta]:
        """遍历已处理文件夹，读取所有 .meta.json（全量重建用）。"""
        metas = []
        for project_name in os.listdir(self.archived_dir):
            proj_dir = os.path.join(self.archived_dir, project_name)
            if not os.path.isdir(proj_dir) or project_name.startswith("."):
                continue
            for fname in os.listdir(proj_dir):
                if fname.endswith(META_EXT):
                    meta_path = os.path.join(proj_dir, fname)
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            metas.append(FileMeta.from_dict(json.load(f)))
                    except Exception as e:
                        print(f"[归档] 读取 meta 失败 {meta_path}: {e}")
        return metas

    def list_archived_files(self) -> List[tuple]:
        """列出所有已归档文件 (project_name, filename, file_id, fingerprint)。"""
        result = []
        for project_name in os.listdir(self.archived_dir):
            proj_dir = os.path.join(self.archived_dir, project_name)
            if not os.path.isdir(proj_dir) or project_name.startswith("."):
                continue
            for fname in os.listdir(proj_dir):
                if fname.endswith(META_EXT):
                    meta = self.read_meta(project_name, fname[:-len(META_EXT)])
                    if meta:
                        result.append((project_name, meta.filename, meta.file_id, meta.fingerprint))
        return result

    def mark_index_pending(self, project_name: str, filename: str, pending: bool):
        """更新 .meta.json 的 index_pending 标记。"""
        meta = self.read_meta(project_name, filename)
        if meta:
            meta.index_pending = pending
            meta_path = os.path.join(self.project_dir(project_name), f"{filename}{META_EXT}")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta.to_dict(), f, ensure_ascii=False, indent=2)

    def delete_file(self, project_name: str, filename: str):
        """删除归档文件及其 meta。"""
        proj_dir = self.project_dir(project_name)
        for name in (filename, f"{filename}{META_EXT}"):
            p = os.path.join(proj_dir, name)
            if os.path.exists(p):
                os.remove(p)


# ==================== Redis 向量库层 ====================
class VectorStore:
    """语义分片库。"""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.index_name = f"{VECTOR_INDEX_PREFIX}_{project_id}"
        self._embeddings = None
        self._vector_db = None

    @property
    def embeddings(self):
        if self._embeddings is None:
            from langchain_ollama import OllamaEmbeddings
            from .config import EMBEDDING_MODEL, EMBEDDING_BASE_URL
            self._embeddings = OllamaEmbeddings(
                model=EMBEDDING_MODEL, base_url=EMBEDDING_BASE_URL,
            )
        return self._embeddings

    @property
    def vector_db(self):
        if self._vector_db is None:
            from langchain_redis import RedisVectorStore
            self._vector_db = RedisVectorStore(
                embeddings=self.embeddings,
                redis_url=REDIS_URL,
                index_name=self.index_name,
            )
        return self._vector_db

    def add_chunks(self, chunks: List[FileChunk]):
        if not chunks:
            return
        texts = [c.text for c in chunks]
        metadatas = [
            {
                "chunk_id": c.chunk_id,
                "file_id": c.file_id,
                "project_id": c.project_id,
                "start_pos": c.start_pos,
                "end_pos": c.end_pos,
                "page": c.page or 0,
            }
            for c in chunks
        ]
        self.vector_db.add_texts(texts=texts, metadatas=metadatas)

    def add_chunk_dicts(self, chunks: List[dict], project_id: str, file_id: str):
        """从 .meta.json 的 chunks 列表直接写入向量库（重建索引用）。"""
        if not chunks:
            return
        texts = [c["text"] for c in chunks]
        metadatas = [
            {
                "chunk_id": c["chunk_id"],
                "file_id": file_id,
                "project_id": project_id,
                "start_pos": c.get("start_pos", 0),
                "end_pos": c.get("end_pos", 0),
                "page": c.get("page", 0),
            }
            for c in chunks
        ]
        self.vector_db.add_texts(texts=texts, metadatas=metadatas)

    def search(self, query: str, k: int = 5) -> List[tuple]:
        results = self.vector_db.similarity_search_with_score(query, k=k)
        return [(doc.page_content, doc.metadata, score) for doc, score in results]


# ==================== 统一存储门面 ====================
class Storage:
    """统一门面：MySQL 主存（索引+分片文本） + 磁盘归档 + Redis 向量库。"""

    def __init__(self):
        self.index = MySQLIndex()
        self.archiver = Archiver()

    def get_vector_store(self, project_id: str) -> VectorStore:
        return VectorStore(project_id)

    def fix_stale_abs_paths(self) -> Dict:
        """
        修复 MySQL 中过期的 abs_path。
        当项目目录移动后，存储的绝对路径会失效。
        策略：先用存储的 abs_path，若磁盘不存在，则用
        ARCHIVED_DIR + project_name + filename 重建路径，
        若新路径存在则更新 MySQL。
        """
        files = self.index.list_files()
        fixed = 0
        still_missing = 0
        for f in files:
            if f.abs_path and os.path.exists(f.abs_path):
                continue
            # 尝试用归档目录重建路径
            proj = self.index.get_project(f.project_id)
            if not proj:
                still_missing += 1
                continue
            new_path = os.path.join(
                self.archiver.project_dir(proj.name), f.filename
            )
            if os.path.exists(new_path):
                # 更新 MySQL 中的 abs_path
                cur = self.index._cursor()
                try:
                    cur.execute(
                        "UPDATE files SET abs_path=%s WHERE file_id=%s",
                        (new_path, f.file_id),
                    )
                    self.index._conn.commit()
                    fixed += 1
                finally:
                    cur.close()
            else:
                still_missing += 1
        return {"total": len(files), "fixed": fixed, "still_missing": still_missing}

    def rebuild_index(self) -> Dict:
        """
        全量重建向量库：以 MySQL 分片文本为真相源，重新写入 Redis 向量。
        （MySQL 索引本身已是真相源，无需重建；仅重建可丢失的 Redis 向量。）
        """
        print("[重建索引] 开始从 MySQL 重建向量库...")
        all_chunks = self.index.list_all_chunks()
        print(f"[重建索引] MySQL 中共 {len(all_chunks)} 个分片")

        # 按项目分组重建向量
        by_project: Dict[str, list] = {}
        for c in all_chunks:
            by_project.setdefault(c["project_id"], []).append(c)

        rebuilt_chunks = 0
        for project_id, chunks in by_project.items():
            vs = self.get_vector_store(project_id)
            try:
                vs.add_chunk_dicts(
                    [{"chunk_id": c["chunk_id"], "text": c["text"],
                      "start_pos": c["start_pos"], "end_pos": c["end_pos"],
                      "page": c["page"]} for c in chunks],
                    project_id, chunks[0]["file_id"],
                )
                rebuilt_chunks += len(chunks)
            except Exception as e:
                print(f"[重建索引] 项目 {project_id} 向量写入失败: {e}")

        projects = len(self.index.list_projects())
        files = len(self.index.list_files())
        print(f"[重建索引] 完成: 项目{projects}个, 文件{files}个, 分片{rebuilt_chunks}个")
        return {"projects": projects, "files": files, "chunks": rebuilt_chunks}

    def import_from_disk(self) -> Dict:
        """
        灾备导入：从磁盘 .meta.json 导入到 MySQL（MySQL 数据丢失时使用）。
        1. 清空 MySQL
        2. 遍历所有 .meta.json
        3. 写入 MySQL（项目/文件/分片）+ Redis 向量
        """
        print("[灾备导入] 从磁盘 .meta.json 导入到 MySQL...")
        metas = self.archiver.list_all_metas()
        print(f"[灾备导入] 发现 {len(metas)} 个归档文件")

        self.index.clear_all()

        project_map: Dict[str, List[FileMeta]] = {}
        for meta in metas:
            project_map.setdefault(meta.project_id, []).append(meta)

        cnt_projects = cnt_files = cnt_chunks = 0
        for project_id, proj_metas in project_map.items():
            project_name = proj_metas[0].project_name
            file_ids = [m.file_id for m in proj_metas]
            self.index.upsert_project(ProjectIndex(
                project_id=project_id, name=project_name,
                summary="", themes=[], file_ids=file_ids,
            ))
            cnt_projects += 1

            vs = self.get_vector_store(project_id)
            for meta in proj_metas:
                self.index.upsert_file(FileIndex(
                    file_id=meta.file_id, project_id=project_id,
                    filename=meta.filename,
                    abs_path=os.path.join(self.archiver.project_dir(project_name), meta.filename),
                    summary=meta.summary, keywords=meta.keywords,
                    content_type=meta.content_type,
                    chunk_ids=[c["chunk_id"] for c in meta.chunks],
                    fingerprint=meta.fingerprint,
                ))
                cnt_files += 1

                if meta.chunks:
                    chunk_objs = [FileChunk(
                        chunk_id=c["chunk_id"], file_id=meta.file_id,
                        project_id=project_id, text=c["text"],
                        start_pos=c.get("start_pos", 0),
                        end_pos=c.get("end_pos", 0),
                        page=c.get("page"),
                    ) for c in meta.chunks]
                    self.index.upsert_chunks(chunk_objs)
                    try:
                        vs.add_chunk_dicts(meta.chunks, project_id, meta.file_id)
                    except Exception as e:
                        print(f"[灾备导入] 向量写入失败 {meta.filename}: {e}")
                    cnt_chunks += len(meta.chunks)

        print(f"[灾备导入] 完成: 项目{cnt_projects}个, 文件{cnt_files}个, 分片{cnt_chunks}个")
        return {"projects": cnt_projects, "files": cnt_files, "chunks": cnt_chunks}

    def validate_index(self) -> Dict:
        """
        索引校验：对比已处理文件清单 ↔ MySQL 索引条目。
        返回异常统计。
        """
        archived = {fid: (proj, fname) for proj, fname, fid, _ in self.archiver.list_archived_files()}
        indexed = {f.file_id: f for f in self.index.list_files()}

        missing_index = []
        orphan_index = []

        for fid, (proj, fname) in archived.items():
            if fid not in indexed:
                missing_index.append(f"{proj}/{fname}")

        for fid, f in indexed.items():
            if fid not in archived:
                orphan_index.append(f"{f.project_id}/{f.filename}")

        return {
            "archived_count": len(archived),
            "indexed_count": len(indexed),
            "missing_index": missing_index,
            "orphan_index": orphan_index,
            "consistent": len(missing_index) == 0 and len(orphan_index) == 0,
        }

    def close(self):
        self.index.close()
