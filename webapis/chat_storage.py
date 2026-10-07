"""
聊天会话持久化：MySQL 存储会话元数据与消息记录。
- chat_sessions: 会话元数据（session_id, title, created_at）
- chat_messages: 消息记录（role, content, tool_calls）
"""
import json
import time
from typing import List, Dict, Any, Optional

import pymysql
from pymysql.cursors import DictCursor

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD,
    MYSQL_DATABASE, MYSQL_CHARSET,
)


class ChatStorage:
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
        try:
            self._conn.ping(reconnect=True)
        except Exception:
            self._connect()

    def _cursor(self):
        self._ensure_conn()
        return self._conn.cursor()

    def _init_tables(self):
        cur = self._cursor()
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id VARCHAR(64) PRIMARY KEY,
                    title VARCHAR(255) NOT NULL DEFAULT '新对话',
                    created_at DOUBLE NOT NULL,
                    updated_at DOUBLE NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content LONGTEXT,
                    tool_calls JSON,
                    created_at DOUBLE NOT NULL,
                    INDEX idx_session (session_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            self._conn.commit()
        finally:
            cur.close()

    def save_session(self, session_id: str, title: str, created_at: float):
        cur = self._cursor()
        try:
            cur.execute("""
                INSERT INTO chat_sessions (session_id, title, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE title=%s, updated_at=%s
            """, (session_id, title, created_at, created_at, title, created_at))
            self._conn.commit()
        finally:
            cur.close()

    def update_session_title(self, session_id: str, title: str):
        cur = self._cursor()
        try:
            cur.execute(
                "UPDATE chat_sessions SET title=%s, updated_at=%s WHERE session_id=%s",
                (title, time.time(), session_id)
            )
            self._conn.commit()
        finally:
            cur.close()

    def delete_session(self, session_id: str):
        cur = self._cursor()
        try:
            cur.execute("DELETE FROM chat_messages WHERE session_id=%s", (session_id,))
            cur.execute("DELETE FROM chat_sessions WHERE session_id=%s", (session_id,))
            self._conn.commit()
        finally:
            cur.close()

    def save_message(self, session_id: str, role: str, content: str,
                     tool_calls: Optional[List[Dict]] = None, created_at: float = None):
        if created_at is None:
            created_at = time.time()
        cur = self._cursor()
        try:
            cur.execute("""
                INSERT INTO chat_messages (session_id, role, content, tool_calls, created_at)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                session_id, role, content,
                json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                created_at,
            ))
            self._conn.commit()
        finally:
            cur.close()

    def load_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        """加载所有会话及其消息，返回 {session_id: {title, created_at, messages}}"""
        cur = self._cursor()
        try:
            cur.execute("SELECT session_id, title, created_at FROM chat_sessions ORDER BY created_at DESC")
            sessions = {row["session_id"]: {
                "title": row["title"],
                "created_at": row["created_at"],
                "messages": [],
            } for row in cur.fetchall()}

            cur.execute("""
                SELECT session_id, role, content, tool_calls, created_at
                FROM chat_messages ORDER BY id ASC
            """)
            for row in cur.fetchall():
                sid = row["session_id"]
                if sid in sessions:
                    msg = {"role": row["role"], "content": row["content"] or ""}
                    if row["tool_calls"]:
                        try:
                            msg["tool_calls"] = json.loads(row["tool_calls"])
                        except Exception:
                            msg["tool_calls"] = []
                    sessions[sid]["messages"].append(msg)
            return sessions
        finally:
            cur.close()
