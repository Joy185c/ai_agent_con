"""
SQLite storage for the API key pool.

Kept deliberately simple (raw sqlite3, no ORM) — this table is small
(dozens of rows, not millions), so there's no need for anything heavier
yet. Swap to Postgres later if it ever needs to move off a single file.
"""

import os
import pg8000.dbapi as pg8000
import urllib.parse
from contextlib import contextmanager
from datetime import datetime, timezone
import queue
from typing import Optional

import crypto

DB_POOL = None

class SimplePool:
    def __init__(self, url, size=5):
        self.url = url
        self.size = size
        # We use a LifoQueue so we reuse the most recently used connections first (less likely to time out)
        self.pool = queue.LifoQueue(maxsize=size)
        parsed = urllib.parse.urlparse(url)
        self.conn_kwargs = {
            'user': parsed.username,
            'password': urllib.parse.unquote(parsed.password or ""),
            'host': parsed.hostname,
            'port': parsed.port or 5432,
            'database': parsed.path.lstrip('/'),
            'timeout': 15.0
        }
        for _ in range(size):
            try:
                self.pool.put_nowait(self._create_conn())
            except Exception:
                pass

    def _create_conn(self):
        return pg8000.connect(**self.conn_kwargs)

    def getconn(self):
        for _ in range(self.size):
            try:
                conn = self.pool.get_nowait()
                # Check if the connection is alive
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT 1")
                    return conn
                except Exception:
                    # Connection is dead
                    pass
            except queue.Empty:
                break
        
        # If no valid connections were in the pool, make a new one
        return self._create_conn()

    def putconn(self, conn):
        try:
            self.pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass

def get_db_pool():
    global DB_POOL
    if DB_POOL is None:
        db_url = os.environ.get("SUPABASE_DB_URL")
        if not db_url:
            raise ValueError("SUPABASE_DB_URL not set in environment")
        DB_POOL = SimplePool(db_url, size=10)
    return DB_POOL

class MockCursor:
    def __init__(self, rows, lastrowid):
        self.rows = rows
        self.lastrowid = lastrowid
        self.idx = 0
        self.rowcount = len(rows)  # for rowcount tracking
    def fetchone(self):
        if self.idx < len(self.rows):
            r = self.rows[self.idx]
            self.idx += 1
            return r
        return None
    def fetchall(self):
        r = self.rows[self.idx:]
        self.idx = len(self.rows)
        return r

class DBConnWrapper:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        # Handle SQLite INSERT OR REPLACE
        if "INSERT OR REPLACE INTO system_settings" in sql:
            sql = "INSERT INTO system_settings (key, value, updated_at) VALUES (%s, %s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at"

        is_insert = sql.strip().upper().startswith("INSERT")
        needs_returning = False
        
        if is_insert and "ON CONFLICT" not in sql:
            lower_sql = sql.lower()
            if any(t in lower_sql for t in ["into api_keys", "into users", "into conversations", "into messages", "into user_keys", "into audit_log", "into request_stats", "into about_sections"]):
                needs_returning = True
                
        if needs_returning and "RETURNING id" not in sql:
            sql = sql.strip()
            if sql.endswith(";"):
                sql = sql[:-1]
            sql += " RETURNING id"
            
        cur = self.conn.cursor()
        if params is None:
            params = ()
        cur.execute(sql, params)
        
        lastrowid = None
        rows = []
        if cur.description:
            columns = [col[0] for col in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
            
        if needs_returning and rows:
            lastrowid = rows[0]["id"]
            
        mock = MockCursor(rows, lastrowid)
        mock.rowcount = cur.rowcount
        return mock

    def executemany(self, sql, params_list):
        sql = sql.replace("?", "%s")
        cur = self.conn.cursor()
        cur.executemany(sql, params_list)
        return MockCursor([], None)

    def commit(self):
        self.conn.commit()

@contextmanager
def get_conn():
    p = get_db_pool()
    conn = p.getconn()
    try:
        yield DBConnWrapper(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id SERIAL PRIMARY KEY,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                key_encrypted TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'text',   -- 'text' or 'vision'
                rpm_limit INTEGER NOT NULL,
                rpd_limit INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',   -- active | paused | invalid
                priority INTEGER NOT NULL DEFAULT 0,     -- higher = tried first on tie
                last_checked_at TEXT,
                last_check_result TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT 'New chat',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_keys (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                key_encrypted TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'text',
                status TEXT NOT NULL DEFAULT 'active',   -- active | invalid
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,               -- uuid, also used as the Chroma document_id
                user_id INTEGER NOT NULL,
                conversation_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                extraction_method TEXT NOT NULL,   -- pdf_text | ocr | vision_fallback
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id          SERIAL PRIMARY KEY,
                action      TEXT NOT NULL,
                target_type TEXT,
                target_id   TEXT,
                details     TEXT,
                created_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS request_stats (
                id       SERIAL PRIMARY KEY,
                date     TEXT NOT NULL,
                hour     INTEGER NOT NULL DEFAULT 0,
                provider TEXT NOT NULL DEFAULT 'unknown',
                category TEXT NOT NULL DEFAULT 'text',
                status   TEXT NOT NULL,
                count    INTEGER NOT NULL DEFAULT 0,
                UNIQUE(date, hour, provider, category, status)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_overrides (
                user_id     INTEGER PRIMARY KEY,
                daily_quota INTEGER,
                is_banned   INTEGER NOT NULL DEFAULT 0,
                ban_reason  TEXT,
                notes       TEXT,
                updated_at  TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS about_sections (
                id SERIAL PRIMARY KEY,
                section_type TEXT NOT NULL,
                title TEXT,
                subtitle TEXT,
                content TEXT,
                image_url TEXT,
                image_alt TEXT,
                metadata TEXT,
                display_order INTEGER NOT NULL,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        
        # Seed default About content if empty
        row = conn.execute("SELECT COUNT(*) as count FROM about_sections").fetchone()
        if row and row["count"] == 0:
            import json
            now = datetime.now(timezone.utc).isoformat()
            default_sections = [
                (1, "hero", "ABOUT CONTINUUM AI", "AI that keeps going.", "Built by\nJOY KUMAR YUV\nFounder & Creator", None, None, None, 1, 1, now, now),
                (2, "text", "Why I Built Continuum AI", "", "I built Continuum AI around a simple question:\n\n**Why should your AI assistant stop just because you reached a limit?**\n\nAI has become an incredibly powerful tool for learning, creating, researching, and solving problems. But one of the most frustrating parts of using AI today is that the experience can suddenly stop when you need it most.\n\nYou may be in the middle of an important conversation, studying from a document, working through a problem, or building something — and suddenly, the free limit is reached.\n\nYou wait.\n\nYou switch accounts.\n\nYou lose momentum.\n\nI didn't think the experience should have to work that way.\n\nSo I built Continuum AI.", None, None, None, 2, 1, now, now),
                (3, "text", "The Idea Behind Continuum", "", "The idea is simple: keep the user experience continuous, even when the underlying AI resources change.\n\nInstead of depending on a single AI provider, Continuum AI is designed to intelligently work across multiple available AI providers and resources.\n\nWhen one resource reaches its limit, another available resource can take over while keeping the conversation itself intact.\n\nAnd when shared capacity is no longer enough, users can bring their own free API key and continue from the same conversation — without starting over and without losing context.\n\nThe technology underneath may change.\n\nThe provider may change.\n\nThe API key may change.\n\n**But the user's journey should continue.**", None, None, None, 3, 1, now, now),
                (4, "feature_grid", "More Than Just a Chatbot", "", "Continuum AI is not meant to be another simple ChatGPT wrapper.\n\nI wanted to build an AI environment that is useful beyond ordinary conversations.\n\nUsers can chat, ask questions, work with files and images, and learn from their own materials through document understanding and retrieval-based AI.\n\nThe goal is to make AI feel less like a limited service and more like a continuous workspace for thinking, learning, and creating.", None, None, json.dumps({
                    "items": [
                        {"title": "Chat", "description": "Ask questions, explore ideas and solve problems."},
                        {"title": "Learn", "description": "Study from your own files and learning materials."},
                        {"title": "Understand", "description": "Work with documents and images."},
                        {"title": "Continue", "description": "Keep working even when one AI resource reaches its limit."}
                    ]
                }), 4, 1, now, now),
                (5, "belief_grid", "What We Believe", "", "", None, None, json.dumps({
                    "items": [
                        {"title": "Continuity", "description": "Your workflow shouldn't stop because one AI resource reaches its limit."},
                        {"title": "Accessibility", "description": "Powerful AI should be easier to access without unnecessary barriers."},
                        {"title": "Simplicity", "description": "Complex technology should feel simple to the people using it."},
                        {"title": "User First", "description": "The experience should be designed around the user's journey, not the limitations of the infrastructure."}
                    ]
                }), 5, 1, now, now),
                (6, "vision", "Our Vision", "", "**AI should help people move forward — not make them stop.**\n\nContinuum AI is an ongoing experiment in building an AI experience that is accessible, flexible, and resilient.\n\nIt is built around one simple idea:\n\n**When one resource ends, the journey doesn't.**", None, None, None, 6, 1, now, now),
                (7, "founder", "Meet the Creator", "", "Continuum AI was created by JOY KUMAR YUV as a personal project driven by curiosity, experimentation, and a desire to build a more continuous AI experience for learning, work, and everyday problem solving.", "/static/founder.jpg", "JOY KUMAR YUV", json.dumps({
                    "name": "JOY KUMAR YUV",
                    "role": "Founder & Creator\nContinuum AI",
                    "links": [
                        {"label": "GitHub", "url": "#"},
                        {"label": "LinkedIn", "url": "#"}
                    ]
                }), 7, 1, now, now),
                (8, "closing", "", "", "Keep learning.\nKeep building.\nKeep going.\n\nThat's Continuum.\n\n— JOY KUMAR YUV\nFounder & Creator", None, None, None, 8, 1, now, now)
            ]
            conn.executemany(
                """INSERT INTO about_sections (id, section_type, title, subtitle, content, image_url, image_alt, metadata, display_order, is_enabled, created_at, updated_at) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                default_sections
            )


def add_key(provider: str, model: str, api_key: str, rpm_limit: int,
            rpd_limit: int, category: str = "text", priority: int = 0) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO api_keys
                (provider, model, key_encrypted, category, rpm_limit, rpd_limit, priority, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (provider, model, crypto.encrypt(api_key), category, rpm_limit,
             rpd_limit, priority, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def list_keys(include_decrypted: bool = False) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM api_keys ORDER BY priority DESC, id ASC").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        if include_decrypted:
            item["api_key"] = crypto.decrypt(item["key_encrypted"])
        else:
            item["key_masked"] = crypto.mask(crypto.decrypt(item["key_encrypted"]))
        del item["key_encrypted"]
        result.append(item)
    return result


def get_key(key_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["api_key"] = crypto.decrypt(item["key_encrypted"])
    return item


def active_keys(category: str = "text") -> list[dict]:
    """Keys eligible for the pool right now (active status, matching category)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM api_keys WHERE status = 'active' AND category = ? "
            "ORDER BY priority DESC, id ASC",
            (category,),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["api_key"] = crypto.decrypt(item["key_encrypted"])
        item["orig_id"] = item["id"]
        item["id"] = f"p{item['id']}"  # namespaced so it never collides with user-key ids
        item["source"] = "pool"
        out.append(item)
    return out


def update_status(key_id: int, status: str):
    with get_conn() as conn:
        conn.execute("UPDATE api_keys SET status = ? WHERE id = ?", (status, key_id))


def update_priority(key_id: int, priority: int):
    with get_conn() as conn:
        conn.execute("UPDATE api_keys SET priority = ? WHERE id = ?", (priority, key_id))


def record_check_result(key_id: int, result: str):
    """result: 'valid' | 'invalid' | 'rate_limited'"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE api_keys SET last_checked_at = ?, last_check_result = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), result, key_id),
        )
        if result == "invalid":
            conn.execute("UPDATE api_keys SET status = 'invalid' WHERE id = ?", (key_id,))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(email: str, password_hash: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email.lower().strip(), password_hash, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def get_user_by_email(email: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def update_password(user_id: int, new_password_hash: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_password_hash, user_id))


def delete_user_data(user_id: int):
    """Permanently delete a user and all their associated data."""
    with get_conn() as conn:
        # 1. Delete messages (via conversation link)
        conn.execute(
            "DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)", 
            (user_id,)
        )
        # 2. Delete documents (RAG)
        conn.execute("DELETE FROM documents WHERE user_id = ?", (user_id,))
        # 3. Delete conversations
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        # 4. Delete user BYOK keys
        conn.execute("DELETE FROM user_keys WHERE user_id = ?", (user_id,))
        # 5. Delete admin overrides
        conn.execute("DELETE FROM user_overrides WHERE user_id = ?", (user_id,))
        # 6. Delete user
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


# ---------------------------------------------------------------------------
# Conversations & messages
# ---------------------------------------------------------------------------

def create_conversation(user_id: int, title: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (user_id, title, created_at) VALUES (?, ?, ?)",
            (user_id, title, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def list_conversations(user_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE user_id = ? ORDER BY id DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_conversation(conversation_id: int, user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id)
        ).fetchone()
    return dict(row) if row else None


def delete_conversation(conversation_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM documents WHERE conversation_id = ? AND user_id = ?", (conversation_id, user_id))
        conn.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id))


def delete_all_conversations(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)",
            (user_id,)
        )
        conn.execute("DELETE FROM documents WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))


def rename_conversation(conversation_id: int, user_id: int, title: str):
    """Update the title of a conversation. Silently does nothing if the row
    doesn't belong to the user."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ? AND user_id = ?",
            (title, conversation_id, user_id),
        )


def search_conversations(user_id: int, query: str) -> list[dict]:
    """Full-text search across conversation titles AND message content.
    Returns matching conversations (deduplicated, ordered newest first)."""
    q = f"%{query}%"
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT c.id, c.title, c.created_at
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE c.user_id = ?
              AND (c.title LIKE ? OR m.content LIKE ?)
            ORDER BY c.id DESC
            """,
            (user_id, q, q),
        ).fetchall()
    return [dict(r) for r in rows]


def add_message(conversation_id: int, role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, datetime.now(timezone.utc).isoformat()),
        )


def get_messages(conversation_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Per-user BYOK keys
# ---------------------------------------------------------------------------

def add_user_key(user_id: int, provider: str, model: str, api_key: str, category: str = "text") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO user_keys (user_id, provider, model, key_encrypted, category, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, provider, model, crypto.encrypt(api_key), category,
             datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def active_user_keys(user_id: int, category: str = "text") -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM user_keys WHERE user_id = ? AND status = 'active' AND category = ?",
            (user_id, category),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["api_key"] = crypto.decrypt(item["key_encrypted"])
        out.append(item)
    return out


# Generous defaults for a user's own key — we trust their own account's
# real limits and mainly track usage so multiple personal keys can still
# fall back to one another if the user adds more than one.
USER_KEY_DEFAULT_RPM = 30
USER_KEY_DEFAULT_RPD = 5000


def active_user_keys_as_candidates(user_id: int, category: str = "text") -> list[dict]:
    candidates = []
    for row in active_user_keys(user_id, category):
        candidates.append({
            **row,
            "orig_id": row["id"],
            "id": f"u{user_id}_{row['id']}",  # namespaced so it never collides with pool ids
            "source": "user",
            "rpm_limit": USER_KEY_DEFAULT_RPM,
            "rpd_limit": USER_KEY_DEFAULT_RPD,
        })
    return candidates


def list_user_keys(user_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM user_keys WHERE user_id = ?", (user_id,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["key_masked"] = crypto.mask(crypto.decrypt(item["key_encrypted"]))
        del item["key_encrypted"]
        out.append(item)
    return out


def mark_user_key_invalid(key_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE user_keys SET status = 'invalid' WHERE id = ?", (key_id,))


def delete_user_key(key_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM user_keys WHERE id = ? AND user_id = ?", (key_id, user_id))


# ---------------------------------------------------------------------------
# Documents (uploaded files, ingested for RAG)
# ---------------------------------------------------------------------------

def add_document(doc_id: str, user_id: int, conversation_id: int, filename: str,
                  extraction_method: str, chunk_count: int):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO documents (id, user_id, conversation_id, filename, extraction_method, chunk_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, user_id, conversation_id, filename, extraction_method, chunk_count,
             datetime.now(timezone.utc).isoformat()),
        )


def list_documents(conversation_id: int, user_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE conversation_id = ? AND user_id = ? ORDER BY id ASC",
            (conversation_id, user_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_document(doc_id: str, user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ? AND user_id = ?", (doc_id, user_id)
        ).fetchone()
    return dict(row) if row else None


def delete_document_row(doc_id: str, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM documents WHERE id = ? AND user_id = ?", (doc_id, user_id))


# ---------------------------------------------------------------------------
# System settings  (key/value store for runtime config)
# ---------------------------------------------------------------------------

def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, datetime.now(timezone.utc).isoformat()),
        )


def get_all_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM system_settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def add_audit_log(action: str, target_type: Optional[str] = None,
                  target_id: Optional[str] = None, details: Optional[str] = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (action, target_type, target_id, details, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (action, target_type, target_id, details, datetime.now(timezone.utc).isoformat()),
        )


def list_audit_logs(limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# User management — admin views and per-user overrides
# ---------------------------------------------------------------------------

def list_users_admin() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.email, u.created_at,
                   COALESCE(uo.daily_quota, -1)  AS daily_quota,
                   COALESCE(uo.is_banned,  0)    AS is_banned,
                   uo.ban_reason,
                   uo.notes,
                   (SELECT COUNT(*) FROM conversations WHERE user_id = u.id)  AS conversation_count,
                   (SELECT COUNT(*) FROM messages
                        WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = u.id)
                          AND role = 'user')                                   AS message_count
            FROM users u
            LEFT JOIN user_overrides uo ON uo.user_id = u.id
            ORDER BY u.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_user_override(user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_overrides WHERE user_id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def upsert_user_override(user_id: int, daily_quota: Optional[int] = None,
                         is_banned: Optional[bool] = None, ban_reason: Optional[str] = None,
                         notes: Optional[str] = None):
    existing = get_user_override(user_id)
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        if existing:
            fields, params = [], []
            if daily_quota is not None:
                fields.append("daily_quota = ?")
                params.append(daily_quota if daily_quota >= 0 else None)
            if is_banned is not None:
                fields.append("is_banned = ?")
                params.append(1 if is_banned else 0)
            if ban_reason is not None:
                fields.append("ban_reason = ?")
                params.append(ban_reason)
            if notes is not None:
                fields.append("notes = ?")
                params.append(notes)
            if not fields:
                return
            fields.append("updated_at = ?")
            params.append(now)
            params.append(user_id)
            conn.execute(
                f"UPDATE user_overrides SET {', '.join(fields)} WHERE user_id = ?", params
            )
        else:
            conn.execute(
                "INSERT INTO user_overrides "
                "(user_id, daily_quota, is_banned, ban_reason, notes, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, daily_quota, 1 if is_banned else 0, ban_reason, notes, now),
            )


def is_user_banned(user_id: int) -> bool:
    override = get_user_override(user_id)
    return bool(override and override.get("is_banned"))


def get_effective_quota(user_id: int, default: int) -> int:
    override = get_user_override(user_id)
    if override and override.get("daily_quota") is not None and override["daily_quota"] >= 0:
        return override["daily_quota"]
    return default


# ---------------------------------------------------------------------------
# Analytics — request tracking
# ---------------------------------------------------------------------------

def increment_request_stat(provider: Optional[str], category: str, status: str):
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hour = datetime.now(timezone.utc).hour
    prov = provider or "unknown"
    with get_conn() as conn:
        updated = conn.execute(
            "UPDATE request_stats SET count = count + 1 "
            "WHERE date = ? AND hour = ? AND provider = ? AND category = ? AND status = ?",
            (date, hour, prov, category, status),
        ).rowcount
        if not updated:
            try:
                conn.execute(
                    "INSERT INTO request_stats "
                    "(date, hour, provider, category, status, count) VALUES (?, ?, ?, ?, ?, 1)",
                    (date, hour, prov, category, status),
                )
            except psycopg2.IntegrityError:
                pass  # concurrent insert — ignore


def delete_key_from_db(key_id: int):
    """Hard-delete a pool key. Prefer pausing for audit trail when possible."""
    with get_conn() as conn:
        conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))


def get_analytics(days: int = 7) -> dict:
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with get_conn() as conn:
        totals = conn.execute(
            "SELECT status, SUM(count) AS total FROM request_stats WHERE date >= ? GROUP BY status",
            (cutoff,),
        ).fetchall()

        by_provider = conn.execute(
            "SELECT provider, SUM(count) AS total FROM request_stats "
            "WHERE date >= ? AND status = 'success' GROUP BY provider ORDER BY total DESC",
            (cutoff,),
        ).fetchall()

        daily = conn.execute(
            "SELECT date, status, SUM(count) AS total FROM request_stats "
            "WHERE date >= ? GROUP BY date, status ORDER BY date, status",
            (cutoff,),
        ).fetchall()

        dau = conn.execute(
            "SELECT DATE(created_at) AS date, COUNT(DISTINCT user_id) AS users "
            "FROM conversations WHERE DATE(created_at) >= ? "
            "GROUP BY DATE(created_at) ORDER BY date",
            (cutoff,),
        ).fetchall()

        total_users = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()["cnt"]

        new_users = conn.execute(
            "SELECT DATE(created_at) AS date, COUNT(*) AS cnt FROM users "
            "WHERE DATE(created_at) >= ? GROUP BY DATE(created_at) ORDER BY date",
            (cutoff,),
        ).fetchall()

        today_total = conn.execute(
            "SELECT COALESCE(SUM(count), 0) AS n FROM request_stats WHERE date = ?",
            (today,),
        ).fetchone()["n"]

        today_errors = conn.execute(
            "SELECT COALESCE(SUM(count), 0) AS n FROM request_stats "
            "WHERE date = ? AND status IN ('error', 'quota_exceeded')",
            (today,),
        ).fetchone()["n"]

    return {
        "period_days": days,
        "totals": [dict(r) for r in totals],
        "by_provider": [dict(r) for r in by_provider],
        "daily": [dict(r) for r in daily],
        "dau": [dict(r) for r in dau],
        "total_users": total_users,
        "new_users": [dict(r) for r in new_users],
        "today_total": today_total,
        "today_errors": today_errors,
    }


# ---------------------------------------------------------------------------
# About Page CMS
# ---------------------------------------------------------------------------

def list_about_sections(public_only: bool = False) -> list[dict]:
    with get_conn() as conn:
        if public_only:
            rows = conn.execute("SELECT * FROM about_sections WHERE is_enabled = 1 ORDER BY display_order ASC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM about_sections ORDER BY display_order ASC").fetchall()
    return [dict(r) for r in rows]


def get_about_section(section_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM about_sections WHERE id = ?", (section_id,)).fetchone()
    return dict(row) if row else None


def create_about_section(data: dict) -> int:
    with get_conn() as conn:
        # Get next display order
        row = conn.execute("SELECT MAX(display_order) as m FROM about_sections").fetchone()
        next_order = (row["m"] or 0) + 1
        
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            INSERT INTO about_sections (section_type, title, subtitle, content, image_url, image_alt, metadata, display_order, is_enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("section_type", "text"),
                data.get("title", ""),
                data.get("subtitle", ""),
                data.get("content", ""),
                data.get("image_url", ""),
                data.get("image_alt", ""),
                data.get("metadata", None),
                next_order,
                data.get("is_enabled", 1),
                now,
                now
            )
        )
        return cur.lastrowid


def update_about_section(section_id: int, data: dict):
    with get_conn() as conn:
        now = datetime.now(timezone.utc).isoformat()
        
        # Build dynamic update query
        fields = []
        values = []
        for key in ["section_type", "title", "subtitle", "content", "image_url", "image_alt", "metadata", "display_order", "is_enabled"]:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])
                
        if not fields:
            return
            
        fields.append("updated_at = ?")
        values.append(now)
        values.append(section_id)
        
        query = f"UPDATE about_sections SET {', '.join(fields)} WHERE id = ?"
        conn.execute(query, tuple(values))


def delete_about_section(section_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM about_sections WHERE id = ?", (section_id,))

