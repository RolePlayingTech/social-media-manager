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
                ig_trial_reels BOOLEAN DEFAULT 0,
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
                is_trial BOOLEAN DEFAULT NULL,
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
                -- Source film (when reel is a fragment of a long film)
                source_film_id INTEGER REFERENCES films(id) ON DELETE SET NULL,
                fb_comment_text TEXT,
                fb_comment_posted INTEGER DEFAULT 0,
                fb_comment_id TEXT,
                fb_comment_error TEXT,
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

            -- AI settings (global, one row per provider)
            CREATE TABLE IF NOT EXISTS ai_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL CHECK(provider IN ('anthropic', 'openai', 'google')),
                api_key TEXT NOT NULL,
                model_name TEXT NOT NULL,
                active BOOLEAN DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(provider)
            );

            -- Per-account reply tone settings
            CREATE TABLE IF NOT EXISTS comment_tones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                tone_preset TEXT DEFAULT 'friendly',
                custom_tone TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(account_id)
            );

            -- Comments fetched from platforms
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                platform TEXT NOT NULL CHECK(platform IN ('youtube', 'instagram', 'facebook')),
                platform_comment_id TEXT NOT NULL,
                platform_video_id TEXT,
                platform_parent_id TEXT,
                video_title TEXT DEFAULT '',
                video_description TEXT DEFAULT '',
                video_url TEXT DEFAULT '',
                commenter_name TEXT DEFAULT '',
                commenter_profile_url TEXT DEFAULT '',
                comment_text TEXT NOT NULL,
                comment_date TEXT,
                like_count INTEGER DEFAULT 0,
                has_owner_reply BOOLEAN DEFAULT 0,
                reply_text TEXT,
                reply_status TEXT DEFAULT 'none' CHECK(reply_status IN ('none', 'draft', 'edited', 'sending', 'sent', 'failed')),
                reply_sent_at TEXT,
                reply_platform_id TEXT,
                reply_error TEXT,
                ai_generated BOOLEAN DEFAULT 0,
                fetched_at TEXT DEFAULT (datetime('now')),
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(account_id, platform_comment_id)
            );

            CREATE INDEX IF NOT EXISTS idx_comments_account ON comments(account_id, platform);
            CREATE INDEX IF NOT EXISTS idx_comments_reply_status ON comments(account_id, reply_status);
            CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(account_id, platform_video_id);

            -- Films (long horizontal videos, independent of accounts)
            CREATE TABLE IF NOT EXISTS films (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                -- File assets
                video_filename TEXT NOT NULL,
                original_filename TEXT,
                thumbnail_filename TEXT,
                subtitle_filename TEXT,
                file_size INTEGER,
                duration REAL,
                -- Metadata
                title TEXT NOT NULL DEFAULT '',
                fb_description TEXT DEFAULT '',
                yt_description TEXT DEFAULT '',
                yt_tags TEXT DEFAULT '[]',
                yt_category TEXT DEFAULT '22',
                yt_privacy TEXT DEFAULT 'public',
                -- Facebook targeting
                fb_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                fb_publish_date TEXT,
                fb_status TEXT DEFAULT 'draft' CHECK(fb_status IN ('draft','scheduled','publishing','published','failed')),
                fb_video_id TEXT,
                fb_permalink TEXT,
                fb_error TEXT,
                fb_published_at TEXT,
                -- YouTube targeting
                yt_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                yt_publish_date TEXT,
                yt_status TEXT DEFAULT 'draft' CHECK(yt_status IN ('draft','scheduled','publishing','published','failed')),
                yt_video_id TEXT,
                yt_url TEXT,
                yt_error TEXT,
                yt_published_at TEXT,
                -- Reel comment auto-link
                topic_prefixes TEXT DEFAULT '',
                fb_comment_template TEXT DEFAULT '',
                -- Metadata
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_films_fb_schedule ON films(fb_status, fb_publish_date);
            CREATE INDEX IF NOT EXISTS idx_films_yt_schedule ON films(yt_status, yt_publish_date);

            -- Film schedule (single-row global config, YT settings only now)
            CREATE TABLE IF NOT EXISTS film_schedule (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                fb_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                fb_publish_time TEXT DEFAULT '12:00',
                fb_day_of_week TEXT DEFAULT '*',
                fb_enabled BOOLEAN DEFAULT 0,
                yt_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                yt_publish_time TEXT DEFAULT '18:00',
                yt_day_of_week TEXT DEFAULT '*',
                yt_enabled BOOLEAN DEFAULT 0,
                fb_start_date TEXT,
                yt_start_date TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            -- Per-account FB film schedule (one row per FB account)
            CREATE TABLE IF NOT EXISTS film_schedule_fb (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER UNIQUE NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                publish_time TEXT DEFAULT '12:00',
                day_of_week TEXT DEFAULT '*',
                enabled BOOLEAN DEFAULT 0,
                start_date TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_film_schedule_fb_account ON film_schedule_fb(account_id);
        """)

        # Migrations for existing DBs (safe to run repeatedly — IF NOT EXISTS via try/except)
        for stmt in [
            "ALTER TABLE videos ADD COLUMN source_film_id INTEGER REFERENCES films(id) ON DELETE SET NULL",
            "ALTER TABLE videos ADD COLUMN fb_comment_text TEXT",
            "ALTER TABLE videos ADD COLUMN fb_comment_posted INTEGER DEFAULT 0",
            "ALTER TABLE videos ADD COLUMN fb_comment_id TEXT",
            "ALTER TABLE videos ADD COLUMN fb_comment_error TEXT",
            "ALTER TABLE videos ADD COLUMN yt_comment_text TEXT",
            "ALTER TABLE videos ADD COLUMN yt_comment_posted INTEGER DEFAULT 0",
            "ALTER TABLE videos ADD COLUMN yt_comment_id TEXT",
            "ALTER TABLE videos ADD COLUMN yt_comment_error TEXT",
            "ALTER TABLE films ADD COLUMN topic_prefixes TEXT DEFAULT ''",
            "ALTER TABLE films ADD COLUMN fb_comment_template TEXT DEFAULT ''",
            "ALTER TABLE schedules ADD COLUMN story_enabled INTEGER DEFAULT 0",
            "ALTER TABLE schedules ADD COLUMN story_times TEXT DEFAULT '[\"09:00\"]'",
            "ALTER TABLE schedules ADD COLUMN story_source TEXT DEFAULT 'archive'",
            "ALTER TABLE schedules ADD COLUMN story_queue_skip INTEGER DEFAULT 5",
        ]:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass

        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_source_film ON videos(source_film_id)")

        # One-time migration: copy FB settings from old global film_schedule → film_schedule_fb
        try:
            old = conn.execute("SELECT * FROM film_schedule WHERE id=1").fetchone()
            if old and old["fb_account_id"] and old["fb_enabled"]:
                exists = conn.execute(
                    "SELECT id FROM film_schedule_fb WHERE account_id=?", (old["fb_account_id"],)
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO film_schedule_fb (account_id, publish_time, day_of_week, enabled, start_date) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (old["fb_account_id"], old["fb_publish_time"], old["fb_day_of_week"],
                         old["fb_enabled"], old["fb_start_date"]),
                    )
        except sqlite3.OperationalError:
            pass


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
                ig_trial_reels, active, sort_order)
            VALUES (:name, :type, :fb_page_id, :fb_page_name, :fb_access_token,
                :ig_user_id, :ig_username, :ig_profile_pic, :ig_followers, :ig_media_count,
                :fb_followers, :yt_channel_id, :yt_channel_name, :yt_channel_pic,
                :yt_subscribers, :yt_video_count, :yt_client_id, :yt_client_secret,
                :yt_refresh_token, :publish_to_ig, :publish_to_fb, :publish_to_stories,
                :ig_trial_reels, :active, :sort_order)
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
            "ig_trial_reels": data.get("ig_trial_reels", 0),
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
            "publish_to_stories", "ig_trial_reels", "active", "sort_order",
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
            if isinstance(result.get("story_times"), str):
                result["story_times"] = json.loads(result["story_times"])
            return result
        return None


def update_schedule(account_id: int, data: dict):
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM schedules WHERE account_id = ?", (account_id,)).fetchone()
        times = json.dumps(data.get("publish_times", ["09:00", "18:00"]))
        story_times = json.dumps(data.get("story_times", ["09:00"]))
        if existing:
            conn.execute("""
                UPDATE schedules SET
                    day_of_week = ?, publish_times = ?, max_per_day = ?,
                    enabled = ?, story_enabled = ?, story_times = ?,
                    story_source = ?, story_queue_skip = ?,
                    updated_at = datetime('now')
                WHERE account_id = ?
            """, (
                data.get("day_of_week", "*"),
                times,
                data.get("max_per_day", 2),
                data.get("enabled", 1),
                int(data.get("story_enabled", 0)),
                story_times,
                data.get("story_source", "archive"),
                data.get("story_queue_skip", 5),
                account_id,
            ))
        else:
            conn.execute("""
                INSERT INTO schedules (account_id, day_of_week, publish_times, max_per_day, enabled,
                    story_enabled, story_times, story_source, story_queue_skip)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                account_id,
                data.get("day_of_week", "*"),
                times,
                data.get("max_per_day", 2),
                data.get("enabled", 1),
                int(data.get("story_enabled", 0)),
                story_times,
                data.get("story_source", "archive"),
                data.get("story_queue_skip", 5),
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
                yt_video_id, yt_url, target_ig, target_fb, fb_title, is_trial)
            VALUES (:account_id, :filename, :original_filename, :title, :caption,
                :video_type, :duration, :file_size, :yt_title, :yt_description, :yt_tags,
                :yt_category, :yt_privacy, :status, :queue_position, :subtitle_file,
                :published_at, :ig_media_id, :ig_permalink, :fb_video_id, :fb_permalink,
                :yt_video_id, :yt_url, :target_ig, :target_fb, :fb_title, :is_trial)
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
            "is_trial": data.get("is_trial"),
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


def find_queued_by_original_filename(account_id: int, original_filename: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, filename FROM videos WHERE account_id=? AND status='queued' AND original_filename=? LIMIT 1",
            (account_id, original_filename),
        ).fetchone()
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
            "is_trial",
            "source_film_id", "fb_comment_text", "fb_comment_posted",
            "fb_comment_id", "fb_comment_error",
            "yt_comment_text", "yt_comment_posted", "yt_comment_id", "yt_comment_error",
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


def count_stories_today(account_id: int, timezone: str = "Europe/Warsaw") -> int:
    """Count story posts made today (tracked via publish_log platform='ig_story'/'fb_story')."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    today_str = _dt.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM publish_log WHERE account_id = ? AND platform IN ('ig_story', 'fb_story')"
            " AND status = 'success' AND date(created_at) = ?",
            (account_id, today_str)
        ).fetchone()
    return row[0]


def get_story_candidate_archive(account_id: int) -> list[str]:
    """Return list of video filenames in the account archive folder."""
    upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    archive_dir = os.path.join(upload_dir, str(account_id), "archive")
    if not os.path.isdir(archive_dir):
        return []
    return [f for f in os.listdir(archive_dir) if f.lower().endswith((".mp4", ".mov"))]


def get_story_candidates_queue(account_id: int, skip: int) -> list[dict]:
    """Return queued video rows for account, skipping the first `skip` by queue_position."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, filename FROM videos WHERE account_id = ? AND status = 'queued'"
            " ORDER BY queue_position ASC",
            (account_id,)
        ).fetchall()
    return [dict(r) for r in rows[skip:]]


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


# ── Comments ───────────────────────────────────────────────────────

def upsert_comment(data: dict) -> dict:
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM comments WHERE account_id = ? AND platform_comment_id = ?",
            (data["account_id"], data["platform_comment_id"])
        ).fetchone()
        if existing:
            return dict(existing)
        conn.execute("""
            INSERT INTO comments (account_id, platform, platform_comment_id, platform_video_id,
                platform_parent_id, video_title, video_description, video_url,
                commenter_name, commenter_profile_url, comment_text, comment_date,
                like_count, has_owner_reply)
            VALUES (:account_id, :platform, :platform_comment_id, :platform_video_id,
                :platform_parent_id, :video_title, :video_description, :video_url,
                :commenter_name, :commenter_profile_url, :comment_text, :comment_date,
                :like_count, :has_owner_reply)
        """, {
            "account_id": data["account_id"],
            "platform": data["platform"],
            "platform_comment_id": data["platform_comment_id"],
            "platform_video_id": data.get("platform_video_id"),
            "platform_parent_id": data.get("platform_parent_id"),
            "video_title": data.get("video_title", ""),
            "video_description": data.get("video_description", ""),
            "video_url": data.get("video_url", ""),
            "commenter_name": data.get("commenter_name", ""),
            "commenter_profile_url": data.get("commenter_profile_url", ""),
            "comment_text": data["comment_text"],
            "comment_date": data.get("comment_date"),
            "like_count": data.get("like_count", 0),
            "has_owner_reply": data.get("has_owner_reply", 0),
        })
        row = conn.execute(
            "SELECT * FROM comments WHERE account_id = ? AND platform_comment_id = ?",
            (data["account_id"], data["platform_comment_id"])
        ).fetchone()
        return dict(row)


def get_comments(account_id: int, reply_status: str = None, platform: str = None,
                 video_id: str = None, since_date: str = None, sort: str = "newest",
                 limit: int = 200, offset: int = 0):
    with get_db() as conn:
        query = "SELECT * FROM comments WHERE account_id = ?"
        params = [account_id]
        if reply_status == "unsent":
            query += " AND reply_status != 'sent' AND has_owner_reply = 0"
        elif reply_status == "no_reply":
            query += " AND reply_status = 'none' AND has_owner_reply = 0"
        elif reply_status == "draft":
            query += " AND reply_status IN ('draft', 'edited')"
        elif reply_status == "sent":
            query += " AND reply_status = 'sent'"
        elif reply_status == "failed":
            query += " AND reply_status = 'failed'"
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        if video_id:
            query += " AND platform_video_id = ?"
            params.append(video_id)
        if since_date:
            query += " AND comment_date >= ?"
            params.append(since_date)
        if sort == "oldest":
            query += " ORDER BY comment_date ASC"
        else:
            query += " ORDER BY comment_date DESC"
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_comment(comment_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
        return dict(row) if row else None


def update_comment(comment_id: int, data: dict):
    allowed = {"reply_text", "reply_status", "reply_sent_at", "reply_platform_id",
               "reply_error", "ai_generated", "has_owner_reply"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return get_comment(comment_id)
    fields["updated_at"] = "datetime('now')"
    set_clauses = []
    params = []
    for k, v in fields.items():
        if v == "datetime('now')":
            set_clauses.append(f"{k} = datetime('now')")
        else:
            set_clauses.append(f"{k} = ?")
            params.append(v)
    params.append(comment_id)
    with get_db() as conn:
        conn.execute(f"UPDATE comments SET {', '.join(set_clauses)} WHERE id = ?", params)
        return get_comment(comment_id)


def get_comment_stats(account_id: int):
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM comments WHERE account_id = ?", (account_id,)).fetchone()[0]
        no_reply = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE account_id = ? AND reply_status = 'none' AND has_owner_reply = 0",
            (account_id,)
        ).fetchone()[0]
        drafts = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE account_id = ? AND reply_status IN ('draft', 'edited')",
            (account_id,)
        ).fetchone()[0]
        sent = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE account_id = ? AND reply_status = 'sent'",
            (account_id,)
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE account_id = ? AND reply_status = 'failed'",
            (account_id,)
        ).fetchone()[0]
        return {"total": total, "no_reply": no_reply, "drafts": drafts, "sent": sent, "failed": failed}


# ── Film Operations ────────────────────────────────────────────────

def _normalize_publish_date(val):
    """Convert HTML datetime-local 'YYYY-MM-DDTHH:MM' to 'YYYY-MM-DD HH:MM'."""
    if isinstance(val, str) and "T" in val:
        return val.replace("T", " ")[:16]
    return val


def add_film(data: dict) -> dict:
    data = {**data,
            "fb_publish_date": _normalize_publish_date(data.get("fb_publish_date")),
            "yt_publish_date": _normalize_publish_date(data.get("yt_publish_date"))}
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO films (video_filename, original_filename, thumbnail_filename,
                subtitle_filename, file_size, duration, title, fb_description, yt_description,
                yt_tags, yt_category, yt_privacy,
                fb_account_id, fb_publish_date, fb_status,
                yt_account_id, yt_publish_date, yt_status)
            VALUES (:video_filename, :original_filename, :thumbnail_filename,
                :subtitle_filename, :file_size, :duration, :title, :fb_description, :yt_description,
                :yt_tags, :yt_category, :yt_privacy,
                :fb_account_id, :fb_publish_date, :fb_status,
                :yt_account_id, :yt_publish_date, :yt_status)
        """, {
            "video_filename": data["video_filename"],
            "original_filename": data.get("original_filename"),
            "thumbnail_filename": data.get("thumbnail_filename"),
            "subtitle_filename": data.get("subtitle_filename"),
            "file_size": data.get("file_size"),
            "duration": data.get("duration"),
            "title": data.get("title", ""),
            "fb_description": data.get("fb_description", ""),
            "yt_description": data.get("yt_description", ""),
            "yt_tags": json.dumps(data.get("yt_tags", [])),
            "yt_category": data.get("yt_category", "22"),
            "yt_privacy": data.get("yt_privacy", "public"),
            "fb_account_id": data.get("fb_account_id"),
            "fb_publish_date": data.get("fb_publish_date"),
            "fb_status": "scheduled" if data.get("fb_publish_date") and data.get("fb_account_id") else "draft",
            "yt_account_id": data.get("yt_account_id"),
            "yt_publish_date": data.get("yt_publish_date"),
            "yt_status": "scheduled" if data.get("yt_publish_date") and data.get("yt_account_id") else "draft",
        })
        return dict(conn.execute("SELECT * FROM films WHERE id = ?", (cur.lastrowid,)).fetchone())


def get_film(film_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
        return dict(row) if row else None


def get_films(status: str = None, fb_account_id: int = None, limit: int = 200):
    with get_db() as conn:
        conditions = []
        params = []
        if status == "scheduled":
            conditions.append("(fb_status = 'scheduled' OR yt_status = 'scheduled')")
        elif status == "published":
            conditions.append("(fb_status = 'published' OR yt_status = 'published')")
        elif status == "draft":
            conditions.append("fb_status = 'draft' AND yt_status = 'draft'")
        elif status == "failed":
            conditions.append("(fb_status = 'failed' OR yt_status = 'failed')")
        if fb_account_id:
            conditions.append("fb_account_id = ?")
            params.append(fb_account_id)
        query = "SELECT * FROM films"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY COALESCE(fb_publish_date, yt_publish_date, created_at) ASC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def update_film(film_id: int, data: dict):
    with get_db() as conn:
        fields = []
        values = {}
        allowed = [
            "video_filename", "original_filename", "file_size",
            "title", "fb_description", "yt_description", "yt_tags", "yt_category", "yt_privacy",
            "thumbnail_filename", "subtitle_filename", "duration",
            "fb_account_id", "fb_publish_date", "fb_status", "fb_video_id", "fb_permalink",
            "fb_error", "fb_published_at",
            "yt_account_id", "yt_publish_date", "yt_status", "yt_video_id", "yt_url",
            "yt_error", "yt_published_at",
            "topic_prefixes", "fb_comment_template",
        ]
        for key in allowed:
            if key in data:
                fields.append(f"{key} = :{key}")
                val = data[key]
                if key == "yt_tags" and isinstance(val, list):
                    val = json.dumps(val)
                # Normalize ISO datetime-local strings ('YYYY-MM-DDTHH:MM') to
                # 'YYYY-MM-DD HH:MM' so string-comparison in scheduler works.
                if key in ("fb_publish_date", "yt_publish_date") and isinstance(val, str):
                    val = val.replace("T", " ")[:16] if "T" in val else val
                values[key] = val
        if not fields:
            return get_film(film_id)
        fields.append("updated_at = datetime('now')")
        values["id"] = film_id
        conn.execute(f"UPDATE films SET {', '.join(fields)} WHERE id = :id", values)
    return get_film(film_id)


def delete_film(film_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM films WHERE id = ?", (film_id,))


def get_films_due_for_publish(platform: str, now_iso: str):
    """Get films ready to publish on a platform (status=scheduled, date <= now)."""
    status_col = f"{platform}_status"
    date_col = f"{platform}_publish_date"
    account_col = f"{platform}_account_id"
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM films WHERE {status_col} = 'scheduled' AND {date_col} <= ? AND {account_col} IS NOT NULL",
            (now_iso,)
        ).fetchall()
        return [dict(r) for r in rows]


def _split_prefixes(raw: str) -> list:
    if not raw:
        return []
    parts = []
    for chunk in raw.replace(";", ",").replace("\n", ",").split(","):
        c = chunk.strip().lower()
        if c:
            parts.append(c)
    return parts


def _filename_matches_prefixes(filename: str, prefixes: list) -> bool:
    if not prefixes:
        return False
    base = (filename or "").lower()
    # Strip extension and common reel suffix
    for p in prefixes:
        if base.startswith(p + "_") or base.startswith(p + "-") or base == p or base.startswith(p + "."):
            return True
    return False


def find_matching_film_for_reel(filename: str):
    """Return film dict whose topic_prefixes match the reel filename, or None."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM films WHERE COALESCE(topic_prefixes, '') != ''"
        ).fetchall()
        for r in rows:
            if _filename_matches_prefixes(filename, _split_prefixes(r["topic_prefixes"])):
                return dict(r)
    return None


def link_queued_reels_to_film(film_id: int, only_unlinked: bool = True) -> int:
    """Auto-link queued reels matching the film's topic_prefixes. Returns count linked."""
    film = get_film(film_id)
    if not film:
        return 0
    prefixes = _split_prefixes(film.get("topic_prefixes", ""))
    if not prefixes:
        return 0
    with get_db() as conn:
        query = "SELECT id, filename FROM videos WHERE status = 'queued' AND video_type IN ('reel','story','short')"
        if only_unlinked:
            query += " AND (source_film_id IS NULL OR source_film_id = 0)"
        rows = conn.execute(query).fetchall()
        linked = 0
        for r in rows:
            if _filename_matches_prefixes(r["filename"], prefixes):
                conn.execute(
                    "UPDATE videos SET source_film_id = ?, updated_at = datetime('now') WHERE id = ?",
                    (film_id, r["id"])
                )
                linked += 1
        return linked


def get_videos_linked_to_film(film_id: int):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM videos WHERE source_film_id = ? ORDER BY queue_position",
            (film_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_film_stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM films").fetchone()[0]
        draft = conn.execute("SELECT COUNT(*) FROM films WHERE fb_status = 'draft' AND yt_status = 'draft'").fetchone()[0]
        scheduled = conn.execute("SELECT COUNT(*) FROM films WHERE fb_status = 'scheduled' OR yt_status = 'scheduled'").fetchone()[0]
        published = conn.execute("SELECT COUNT(*) FROM films WHERE fb_status = 'published' OR yt_status = 'published'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM films WHERE fb_status = 'failed' OR yt_status = 'failed'").fetchone()[0]
        return {"total": total, "draft": draft, "scheduled": scheduled, "published": published, "failed": failed}


# ── Film Schedule ─────────────────────────────────────────────────

def get_film_schedule():
    with get_db() as conn:
        row = conn.execute("SELECT * FROM film_schedule WHERE id = 1").fetchone()
        return dict(row) if row else None


def update_film_schedule(data: dict) -> dict:
    with get_db() as conn:
        allowed = [
            "fb_account_id", "fb_publish_time", "fb_day_of_week", "fb_enabled", "fb_start_date",
            "yt_account_id", "yt_publish_time", "yt_day_of_week", "yt_enabled", "yt_start_date",
        ]
        filtered = {k: v for k, v in data.items() if k in allowed}
        # Upsert: try update first, insert if not exists
        existing = conn.execute("SELECT id FROM film_schedule WHERE id = 1").fetchone()
        if existing:
            fields = [f"{k} = :{k}" for k in filtered]
            fields.append("updated_at = datetime('now')")
            filtered["id"] = 1
            conn.execute(f"UPDATE film_schedule SET {', '.join(fields)} WHERE id = :id", filtered)
        else:
            filtered["id"] = 1
            cols = ", ".join(filtered.keys())
            placeholders = ", ".join(f":{k}" for k in filtered.keys())
            conn.execute(f"INSERT INTO film_schedule ({cols}) VALUES ({placeholders})", filtered)
        return dict(conn.execute("SELECT * FROM film_schedule WHERE id = 1").fetchone())


def get_next_film_slot(platform: str) -> tuple:
    """Return (next_date_str, account_id) for the next available film slot on a platform."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    schedule = get_film_schedule()
    if not schedule or not schedule.get(f"{platform}_enabled"):
        return None, None

    account_id = schedule.get(f"{platform}_account_id")
    publish_time = schedule.get(f"{platform}_publish_time", "12:00")
    dow = schedule.get(f"{platform}_day_of_week", "*")

    if not account_id:
        return None, None

    all_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    if dow == "*":
        allowed = set(all_days)
    else:
        allowed = set(d.strip().lower()[:3] for d in dow.split(","))

    tz = ZoneInfo(os.environ.get("SMM_TIMEZONE", "Europe/Warsaw"))

    # Find the latest scheduled film date for this platform
    with get_db() as conn:
        row = conn.execute(
            f"SELECT MAX({platform}_publish_date) FROM films "
            f"WHERE {platform}_status = 'scheduled' AND {platform}_account_id = ?",
            (account_id,)
        ).fetchone()
        latest = row[0] if row else None

    # Determine earliest possible start date
    min_start = (datetime.now(tz) + timedelta(days=1)).date()

    # Respect configured start date (don't schedule before it)
    configured_start = schedule.get(f"{platform}_start_date")
    if configured_start:
        try:
            configured = datetime.fromisoformat(configured_start.replace(" ", "T")).date()
            if configured > min_start:
                min_start = configured
        except (ValueError, AttributeError):
            pass

    if latest:
        try:
            after_latest = datetime.fromisoformat(latest.replace(" ", "T")).date() + timedelta(days=1)
            start_date = max(after_latest, min_start)
        except (ValueError, AttributeError):
            start_date = min_start
    else:
        start_date = min_start

    h, m = map(int, publish_time.split(":"))

    for offset in range(365):
        candidate = start_date + timedelta(days=offset)
        day_name = candidate.strftime("%a").lower()[:3]
        if day_name in allowed:
            slot_dt = datetime(candidate.year, candidate.month, candidate.day, h, m, tzinfo=tz)
            # Skip past slots
            if slot_dt <= datetime.now(tz):
                continue
            return slot_dt.strftime("%Y-%m-%d %H:%M"), account_id

    return None, None


# ── Per-account FB Film Schedule ──────────────────────────────────

def get_film_schedules_fb() -> list:
    """Return all per-account FB film schedules."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM film_schedule_fb ORDER BY account_id").fetchall()
        return [dict(r) for r in rows]


def get_film_schedule_fb(account_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM film_schedule_fb WHERE account_id = ?", (account_id,)).fetchone()
        return dict(row) if row else None


def update_film_schedule_fb(account_id: int, data: dict) -> dict:
    allowed = ["publish_time", "day_of_week", "enabled", "start_date"]
    filtered = {k: v for k, v in data.items() if k in allowed}
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM film_schedule_fb WHERE account_id = ?", (account_id,)).fetchone()
        if existing:
            fields = [f"{k} = :{k}" for k in filtered] + ["updated_at = datetime('now')"]
            filtered["account_id"] = account_id
            conn.execute(f"UPDATE film_schedule_fb SET {', '.join(fields)} WHERE account_id = :account_id", filtered)
        else:
            filtered["account_id"] = account_id
            cols = ", ".join(filtered.keys())
            placeholders = ", ".join(f":{k}" for k in filtered.keys())
            conn.execute(f"INSERT INTO film_schedule_fb (account_id, {cols}) VALUES (:account_id, {placeholders})", filtered)
    return get_film_schedule_fb(account_id)


def get_next_film_slot_fb(account_id: int) -> tuple:
    """Return (next_date_str, account_id) for the next available film slot for a specific FB account."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    schedule = get_film_schedule_fb(account_id)
    if not schedule or not schedule.get("enabled"):
        return None, None

    publish_time = schedule.get("publish_time", "12:00")
    dow = schedule.get("day_of_week", "*")
    all_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    allowed = set(all_days) if dow == "*" else set(d.strip().lower()[:3] for d in dow.split(","))

    tz = ZoneInfo(os.environ.get("SMM_TIMEZONE", "Europe/Warsaw"))

    with get_db() as conn:
        row = conn.execute(
            "SELECT MAX(fb_publish_date) FROM films WHERE fb_status = 'scheduled' AND fb_account_id = ?",
            (account_id,)
        ).fetchone()
        latest = row[0] if row else None

    min_start = (datetime.now(tz) + timedelta(days=1)).date()
    configured_start = schedule.get("start_date")
    if configured_start:
        try:
            configured = datetime.fromisoformat(configured_start.replace(" ", "T")).date()
            if configured > min_start:
                min_start = configured
        except (ValueError, AttributeError):
            pass

    if latest:
        try:
            after_latest = datetime.fromisoformat(latest.replace(" ", "T")).date() + timedelta(days=1)
            start_date = max(after_latest, min_start)
        except (ValueError, AttributeError):
            start_date = min_start
    else:
        start_date = min_start

    h, m = map(int, publish_time.split(":"))
    for offset in range(365):
        candidate = start_date + timedelta(days=offset)
        if candidate.strftime("%a").lower()[:3] in allowed:
            slot_dt = datetime(candidate.year, candidate.month, candidate.day, h, m, tzinfo=tz)
            if slot_dt > datetime.now(tz):
                return slot_dt.strftime("%Y-%m-%d %H:%M"), account_id
    return None, None


def film_is_ready_fb(film: dict) -> bool:
    """True if film has all required fields for FB publication."""
    return bool(
        film.get("video_filename") and
        (film.get("title") or "").strip() and
        (film.get("fb_description") or "").strip() and
        film.get("subtitle_filename") and
        film.get("thumbnail_filename") and
        film.get("fb_account_id")
    )


def film_is_ready_yt(film: dict) -> bool:
    """True if film has all required fields for YT publication."""
    return bool(
        film.get("video_filename") and
        (film.get("title") or "").strip() and
        (film.get("yt_description") or "").strip() and
        film.get("subtitle_filename") and
        film.get("thumbnail_filename") and
        film.get("yt_account_id")
    )


def auto_assign_film_slots(film_id: int) -> dict:
    """Assign schedule dates to a film if it's complete and still in draft status."""
    film = get_film(film_id)
    if not film:
        return {}
    update = {}
    if film.get("fb_status") == "draft" and film_is_ready_fb(film):
        slot, _ = get_next_film_slot_fb(film["fb_account_id"])
        if slot:
            update["fb_publish_date"] = slot
            update["fb_status"] = "scheduled"
    if film.get("yt_status") == "draft" and film_is_ready_yt(film):
        slot, _ = get_next_film_slot("yt")
        if slot:
            update["yt_publish_date"] = slot
            update["yt_status"] = "scheduled"
    if update:
        return update_film(film_id, update)
    return film


# ── AI Settings ────────────────────────────────────────────────────

def get_ai_settings():
    with get_db() as conn:
        row = conn.execute("SELECT * FROM ai_settings WHERE active = 1 ORDER BY updated_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def upsert_ai_settings(data: dict):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO ai_settings (provider, api_key, model_name, active, updated_at)
            VALUES (:provider, :api_key, :model_name, 1, datetime('now'))
            ON CONFLICT(provider) DO UPDATE SET
                api_key = excluded.api_key,
                model_name = excluded.model_name,
                active = 1,
                updated_at = datetime('now')
        """, data)
        # Deactivate other providers
        conn.execute("UPDATE ai_settings SET active = 0 WHERE provider != ?", (data["provider"],))
        return get_ai_settings()


def get_comment_tone(account_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM comment_tones WHERE account_id = ?", (account_id,)).fetchone()
        return dict(row) if row else {"tone_preset": "friendly", "custom_tone": ""}


def upsert_comment_tone(account_id: int, data: dict):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO comment_tones (account_id, tone_preset, custom_tone, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(account_id) DO UPDATE SET
                tone_preset = excluded.tone_preset,
                custom_tone = excluded.custom_tone,
                updated_at = datetime('now')
        """, (account_id, data.get("tone_preset", "friendly"), data.get("custom_tone", "")))
        return get_comment_tone(account_id)
