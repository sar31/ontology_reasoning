"""Text source management: save original text to MySQL and query."""
import logging

from db import get_mysql_conn

log = logging.getLogger(__name__)


def create_text_source(title, content, source_type="paste", filename=None):
    """Save text to MySQL and return the new text_source_id."""
    if not content or len(content.strip()) == 0:
        raise ValueError("content is empty")
    title = (title or "").strip() or content.strip()[:50]
    word_count = len(content.strip())
    mc = get_mysql_conn()
    try:
        with mc.cursor() as cur:
            cur.execute(
                """
                INSERT INTO text_sources (title, content, source_type, filename, word_count)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (title, content, source_type, filename, word_count),
            )
            mc.commit()
            return cur.lastrowid
    finally:
        mc.close()


def list_text_sources(limit=50, offset=0):
    """Return list of text sources (without content field)."""
    mc = get_mysql_conn()
    try:
        with mc.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, source_type, filename, word_count, created_at
                FROM text_sources
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        mc.close()


def get_text_source(source_id):
    """Return single text source detail including content."""
    mc = get_mysql_conn()
    try:
        with mc.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, content, source_type, filename, word_count, created_at
                FROM text_sources
                WHERE id = %s
                """,
                (source_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        mc.close()


def init_text_sources_table():
    """Create text_sources table if not exists."""
    mc = get_mysql_conn()
    try:
        with mc.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS text_sources (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title VARCHAR(255) DEFAULT '',
                    content TEXT NOT NULL,
                    source_type ENUM('paste', 'upload') DEFAULT 'paste',
                    filename VARCHAR(255) DEFAULT NULL,
                    word_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            mc.commit()
    finally:
        mc.close()
