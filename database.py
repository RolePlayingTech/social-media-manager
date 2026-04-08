"""
Social Media Manager - Database Layer
SQLite database with schema for accounts, videos, schedules, and publish logs.
"""

import sqlite3
import os
import json
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.sqlite3")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('instagram_facebook', 'youtube')),
                -- Instagram/Facebook fields
                fb_page_id TEXT,
                fb_page_name TEXT,
                fb_access_token TEXT,
                ig_user_id TEXT,
                ig_username TEXT,
                ig_profile_pic TEXT,
                ig_followers INTEGER DEFAULT 0,
                ig_media_count INTEGER DEFAULT 0,
                fb_followers INTEGER DEFAULT 0,
                -- YouTube fields
                yt_channel_id TEXT,
                yt_channel_name TEXT,
                yt_channel_pic TEXT,
                yt_subscribers INTEGER DEFAULT 0,
                yt_video_count INTEGER DEFAULT 0,
                yt_client_id TEXT,
                yt_client_secret TEXT,
                yt_refresh_token TEXT,
                -- Publishing settings
                publish_to_ig BOOLEAN DEFAULT 1,
                publish_to_fb BOOLEAN DEFAULT 1,
                publish_to_stories BOOLEAN DEFAULT 0,
                -- Metadata
                active BOOLEAN DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                day_of_week TEXT NOT NULL DEFAULT '*',
                publish_times TEXT NOT NULL DEFAULT '[]',
                max_per_day INTEGER DEFAULT 2,
                enabled BOOLEAN DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                original_filename TEXT,
                title TEXT DEFAULT '',
                caption TEXT DEFAULT '',
                -- Video metadata
                video_type TEXT DEFAULT 'reel' CHECK(video_type IN ('reel', 'story', 'short', 'video')),
                duration REAL,
                file_size INTEGER,
                thumbnail_time REAL DEFAULT 0.5,
                -- YouTube-specific fields
                yt_title TEXT,
                yt_description TEXT,
                yt_tags TEXT DEFAULT '[]',
                yt_category TEXT DEFAULT '22',
                yt_privacy TEXT DEFAULT 'public',
                -- Subtitle file
                subtitle_file TEXT,
                -- Per-video platform targeting (IG+FB accounts)
                target_ig BOOLEAN DEFAULT 1,
                target_fb BOOLEAN DEFAULT 1,
                fb_title TEXT,
                -- Queue & status
                status TEXT DEFAULT 'queued' CHECK(status IN ('queued', 'publishing', 'published', 'failed', 'archived')),
                queue_position INTEGER DEFAULT 0,
                -- Publishing results
                published_at TEXT,
                ig_media_id TEXT,
                ig_permalink TEXT,
                fb_video_id TEXT,
                fb_permalink TEXT,
                yt_video_id TEXT,
                yt_url TEXT,
                error_message TEXT,
                -- Metadata
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS publish_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER REFERENCES videos(id) ON DELETE SET NULL,
                account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                platform TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('success', 'failed', 'skipped')),
                response_data TEXT,
                error_message TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_videos_account_status ON videos(account_id, status);
            CREATE INDEX IF NOT EXISTS idx_videos_queue ON videos(account_id, status, queue_position);
            CREATE INDEX IF NOT EXISTS idx_publish_log_video ON publish_log(video_id);
            CREATE INDEX IF NOT EXISTS idx_schedules_account ON schedules(account_id);
        """)


# ── Account Operations ──────────────────────────────────────────────

def create_account(data: dict) -> dict:
    with get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM accounts").fetchone()[0]
        cur = conn.execute("""
            INSERT INTO accounts (name, type, fb_page_id, fb_page_name, fb_access_token,
                ig_user_id, ig_username, ig_profile_pic, ig_followers, ig_media_count,
                fb_followers, yt_channel_id, yt_channel_name, yt_channel_pic,
                yt_subscribers, yt_video_count, yt_client_id, yt_client_secret,
                yt_refresh_token, publish_to_ig, publish_to_fb, publish_to_stories,
                active, sort_order)
            VALUES (:name, :type, :fb_page_id, :fb_page_name, :fb_access_token,
                :ig_user_id, :ig_username, :ig_profile_pic, :ig_followers, :ig_media_count,
                :fb_followers, :yt_channel_id, :yt_channel_name, :yt_channel_pic,
                :yt_subscribers, :yt_video_count, :yt_client_id, :yt_client_secret,
                :yt_refresh_token, :publish_to_ig, :publish_to_fb, :publish_to_stories,
                :active, :sort_order)
        """, {
            "name": data.get("name", ""),
            "type": data.get("type", "instagram_facebook"),
            "fb_page_id": data.get("fb_page_id"),
            "fb_page_name": data.get("fb_page_name"),
            "fb_access_token": data.get("fb_access_token"),
            "ig_user_id": data.get("ig_user_id"),
            "ig_username": data.get("ig_username"),
            "ig_profile_pic": data.get("ig_profile_pic"),
            "ig_followers": data.get("ig_followers", 0),
            "ig_media_count": data.get("ig_media_count", 0),
            "fb_followers": data.get("fb_followers", 0),
            "yt_channel_id": data.get("yt_channel_id"),
            "yt_channel_name": data.get("yt_channel_name"),
            "yt_channel_pic": data.get("yt_channel_pic"),
            "yt_subscribers": data.get("yt_subscribers", 0),
            "yt_video_count": data.get("yt_video_count", 0),
            "yt_client_id": data.get("yt_client_id"),
            "yt_client_secret": data.get("yt_client_secret"),
            "yt_refresh_token": data.get("yt_refresh_token"),
            "publish_to_ig": data.get("publish_to_ig", 1),
            "publish_to_fb": data.get("publish_to_fb", 1),
            "publish_to_stories": data.get("publish_to_stories", 0),
            "active": data.get("active", 1),
            "sort_order": max_order,
        })
        account_id = cur.lastrowid
        # Create default schedule
        conn.execute("""
            INSERT INTO schedules (account_id, day_of_week, publish_times, max_per_day, enabled)
            VALUES (?, '*', '["09:00","18:00"]', 2, 1)
        """, (account_id,))
        return dict(conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())


def get_accounts(account_type=None):
    with get_db() as conn:
        if account_type:
            rows = conn.execute("SELECT * FROM accounts WHERE type = ? ORDER BY sort_order", (account_type,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM accounts ORDER BY sort_order").fetchall()
        return [dict(r) for r in rows]


def get_account(account_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return dict(row) if row else None


def update_account(account_id: int, data: dict):
    with get_db() as conn:
        fields = []
        values = {}
        allowed = [
            "name", "fb_page_id", "fb_page_name", "fb_access_token",
            "ig_user_id", "ig_username", "ig_profile_pic", "ig_followers",
            "ig_media_count", "fb_followers", "yt_channel_id", "yt_channel_name",
            "yt_channel_pic", "yt_subscribers", "yt_video_count", "yt_client_id",
            "yt_client_secret", "yt_refresh_token", "publish_to_ig", "publish_to_fb",
            "publish_to_stories", "active", "sort_order",
        ]
        for key in allowed:
            if key in data:
                fields.append(f"{key} = :{key}")
                values[key] = data[key]
        if not fields:
            return get_account(account_id)
        fields.append("updated_at = datetime('now')")
        values["id"] = account_id
        conn.execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id = :id", values)
        return get_account(account_id)


def delete_account(account_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


# ── Schedule Operations ─────────────────────────────────────────────

def get_schedule(account_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM schedules WHERE account_id = ?", (account_id,)).fetchone()
        if row:
            result = dict(row)
            result["publish_times"] = json.loads(result["publish_times"])
            return result
        return None


def update_schedule(account_id: int, data: dict):
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM schedules WHERE account_id = ?", (account_id,)).fetchone()
        times = json.dumps(data.get("publish_times", ["09:00", "18:00"]))
        if existing:
            conn.execute("""
                UPDATE schedules SET
                    day_of_week = ?, publish_times = ?, max_per_day = ?,
                    enabled = ?, updated_at = datetime('now')
                WHERE account_id = ?
            """, (
                data.get("day_of_week", "*"),
                times,
                data.get("max_per_day", 2),
                data.get("enabled", 1),
                account_id,
            ))
        else:
            conn.execute("""
                INSERT INTO schedules (account_id, day_of_week, publish_times, max_per_day, enabled)
                VALUES (?, ?, ?, ?, ?)
            """, (
                account_id,
                data.get("day_of_week", "*"),
                times,
                data.get("max_per_day", 2),
                data.get("enabled", 1),
            ))
    # Read after commit so we get the updated data
    return get_schedule(account_id)


# ── Video Operations ────────────────────────────────────────────────

def add_video(data: dict) -> dict:
    with get_db() as conn:
        max_pos = conn.execute(
            "SELECT COALESCE(MAX(queue_position), -1) + 1 FROM videos WHERE account_id = ? AND status = 'queued'",
            (data["account_id"],)
        ).fetchone()[0]
        cur = conn.execute("""
            INSERT INTO videos (account_id, filename, original_filename, title, caption,
                video_type, duration, file_size, yt_title, yt_description, yt_tags,
                yt_category, yt_privacy, status, queue_position, subtitle_file,
                published_at, ig_media_id, ig_permalink, fb_video_id, fb_permalink,
                yt_video_id, yt_url, target_ig, target_fb, fb_title)
            VALUES (:account_id, :filename, :original_filename, :title, :caption,
                :video_type, :duration, :file_size, :yt_title, :yt_description, :yt_tags,
                :yt_category, :yt_privacy, :status, :queue_position, :subtitle_file,
                :published_at, :ig_media_id, :ig_permalink, :fb_video_id, :fb_permalink,
                :yt_video_id, :yt_url, :target_ig, :target_fb, :fb_title)
        """, {
            "account_id": data["account_id"],
            "filename": data["filename"],
            "original_filename": data.get("original_filename", data["filename"]),
            "title": data.get("title", ""),
            "caption": data.get("caption", ""),
            "video_type": data.get("video_type", "reel"),
            "duration": data.get("duration"),
            "file_size": data.get("file_size"),
            "yt_title": data.get("yt_title"),
            "yt_description": data.get("yt_description"),
            "yt_tags": json.dumps(data.get("yt_tags", [])),
            "yt_category": data.get("yt_category", "22"),
            "yt_privacy": data.get("yt_privacy", "public"),
            "status": data.get("status", "queued"),
            "queue_position": max_pos,
            "subtitle_file": data.get("subtitle_file"),
            "published_at": data.get("published_at"),
            "ig_media_id": data.get("ig_media_id"),
            "ig_permalink": data.get("ig_permalink"),
            "fb_video_id": data.get("fb_video_id"),
            "fb_permalink": data.get("fb_permalink"),
            "yt_video_id": data.get("yt_video_id"),
            "yt_url": data.get("yt_url"),
            "target_ig": data.get("target_ig", 1),
            "target_fb": data.get("target_fb", 1),
            "fb_title": data.get("fb_title"),
        })
        return dict(conn.execute("SELECT * FROM videos WHERE id = ?", (cur.lastrowid,)).fetchone())


def get_videos(account_id: int, status: str = None, video_type: str = None):
    with get_db() as conn:
        query = "SELECT * FROM videos WHERE account_id = ?"
        params = [account_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        if video_type:
            query += " AND video_type = ?"
            params.append(video_type)
        if status == "queued":
            query += " ORDER BY queue_position ASC"
        else:
            query += " ORDER BY created_at DESC"
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_video(video_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return dict(row) if row else None


def update_video(video_id: int, data: dict):
    with get_db() as conn:
        fields = []
        values = {}
        allowed = [
            "title", "caption", "video_type", "status", "queue_position",
            "published_at", "ig_media_id", "ig_permalink", "fb_video_id",
            "fb_permalink", "yt_video_id", "yt_url", "error_message",
            "yt_title", "yt_description", "yt_tags", "yt_category", "yt_privacy",
            "thumbnail_time", "subtitle_file", "target_ig", "target_fb", "fb_title",
        ]
        for key in allowed:
            if key in data:
                fields.append(f"{key} = :{key}")
                val = data[key]
                if key == "yt_tags" and isinstance(val, list):
                    val = json.dumps(val)
                values[key] = val
        if not fields:
            return get_video(video_id)
        fields.append("updated_at = datetime('now')")
        values["id"] = video_id
        conn.execute(f"UPDATE videos SET {', '.join(fields)} WHERE id = :id", values)
        return get_video(video_id)


def delete_video(video_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))


def reorder_videos(account_id: int, video_ids: list):
    with get_db() as conn:
        for pos, vid in enumerate(video_ids):
            conn.execute(
                "UPDATE videos SET queue_position = ?, updated_at = datetime('now') WHERE id = ? AND account_id = ?",
                (pos, vid, account_id)
            )


def get_next_queued_video(account_id: int):
    """Atomically claim the next queued video by setting status to 'publishing'."""
    with get_db() as conn:
        row = conn.execute(
            "UPDATE videos SET status = 'publishing', updated_at = datetime('now') "
            "WHERE id = (SELECT id FROM videos WHERE account_id = ? AND status = 'queued' "
            "ORDER BY queue_position ASC LIMIT 1) RETURNING *",
            (account_id,)
        ).fetchone()
        return dict(row) if row else None


def count_published_today(account_id: int, timezone: str = "Europe/Warsaw") -> int:
    """Count videos published today in the configured timezone."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    today_str = _dt.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE account_id = ? AND status = 'published' AND date(published_at) = ?",
            (account_id, today_str)
        ).fetchone()
        return row[0]


# ── Publish Log ──────────────────────────────────────────────────────

def add_publish_log(data: dict):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO publish_log (video_id, account_id, platform, status, response_data, error_message)
            VALUES (:video_id, :account_id, :platform, :status, :response_data, :error_message)
        """, {
            "video_id": data.get("video_id"),
            "account_id": data.get("account_id"),
            "platform": data["platform"],
            "status": data["status"],
            "response_data": json.dumps(data.get("response_data")) if data.get("response_data") else None,
            "error_message": data.get("error_message"),
        })


def get_publish_logs(account_id: int = None, video_id: int = None, limit: int = 50):
    with get_db() as conn:
        query = "SELECT * FROM publish_log WHERE 1=1"
        params = []
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        if video_id:
            query += " AND video_id = ?"
            params.append(video_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(query, params).fetchall()]


# ── Stats ────────────────────────────────────────────────────────────

def get_account_stats(account_id: int):
    with get_db() as conn:
        queued = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE account_id = ? AND status = 'queued'", (account_id,)
        ).fetchone()[0]
        published = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE account_id = ? AND status = 'published'", (account_id,)
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE account_id = ? AND status = 'failed'", (account_id,)
        ).fetchone()[0]
        today = count_published_today(account_id)
        last_published = conn.execute(
            "SELECT published_at FROM videos WHERE account_id = ? AND status = 'published' ORDER BY published_at DESC LIMIT 1",
            (account_id,)
        ).fetchone()
        return {
            "queued": queued,
            "published": published,
            "failed": failed,
            "published_today": today,
            "last_published_at": last_published[0] if last_published else None,
        }


def get_global_stats():
    with get_db() as conn:
        total_queued = conn.execute("SELECT COUNT(*) FROM videos WHERE status = 'queued'").fetchone()[0]
        total_published = conn.execute("SELECT COUNT(*) FROM videos WHERE status = 'published'").fetchone()[0]
        total_accounts = conn.execute("SELECT COUNT(*) FROM accounts WHERE active = 1").fetchone()[0]
        return {
            "total_queued": total_queued,
            "total_published": total_published,
            "total_accounts": total_accounts,
        }
