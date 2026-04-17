"""
Social Media Manager - API
FastAPI backend for managing social media accounts, videos, and publishing.
"""

import os
import sys
import json
import time
import uuid
import shutil
import logging
import secrets
import threading
from datetime import datetime
from typing import Optional

# Load .env file if present (for local dev; systemd uses EnvironmentFile)
from pathlib import Path
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import database as db
import publisher
import scheduler as sched
import ai_client

# ── Logging ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.log")),
    ],
)
logger = logging.getLogger("api")

# Suppress httpx request logging (leaks tokens in URLs)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ── Config ───────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
API_TOKEN = os.environ["SMM_API_TOKEN"]
DASHBOARD_PASSWORD = os.environ["SMM_PASSWORD"]
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB
CORS_ORIGINS = os.environ.get("SMM_CORS_ORIGINS", "http://localhost:3000").split(",")
TIMEZONE = os.environ.get("SMM_TIMEZONE", "Europe/Warsaw")

# Track background jobs in-memory
publish_jobs: dict = {}
background_jobs: dict = {}  # For comment fetching, AI generation

# ── Lifespan ─────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    db.init_db()
    seed_accounts()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    # Recover videos stuck in "publishing" after crash/restart
    with db.get_db() as conn:
        stuck = conn.execute("UPDATE videos SET status = 'queued' WHERE status = 'publishing'").rowcount
        if stuck:
            logger.warning(f"Recovered {stuck} videos stuck in 'publishing' status")
    sched.start()
    logger.info("Social Media Manager API started")
    yield
    sched.stop()
    logger.info("Social Media Manager API stopped")


def seed_accounts():
    """Create example accounts if database is empty. Tokens must be configured via dashboard."""
    existing = db.get_accounts()
    if existing:
        return

    logger.info("Seeding default accounts...")

    for acc_data in [
        {"name": "Account 1", "type": "instagram_facebook"},
        {"name": "Account 2", "type": "instagram_facebook"},
        {"name": "YouTube Channel", "type": "youtube"},
    ]:
        acc = db.create_account(acc_data)
        acc_dir = os.path.join(UPLOAD_DIR, str(acc["id"]))
        os.makedirs(os.path.join(acc_dir, "queue"), exist_ok=True)
        os.makedirs(os.path.join(acc_dir, "archive"), exist_ok=True)

    logger.info("Seeded default accounts. Configure tokens via dashboard settings.")
    sched.reload()

# ── App ──────────────────────────────────────────────────────────────

app = FastAPI(title="Social Media Manager", version="2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth ─────────────────────────────────────────────────────────────

async def verify_token(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not secrets.compare_digest(auth[7:], API_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Health & Login ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0", "time": datetime.now().isoformat()}


class LoginRequest(BaseModel):
    password: str


@app.post("/api/login")
async def login(data: LoginRequest):
    """Authenticate with dashboard password, receive API token."""
    if not secrets.compare_digest(data.password, DASHBOARD_PASSWORD):
        raise HTTPException(401, "Nieprawidłowe hasło")
    return {"token": API_TOKEN}


# ── Pydantic Models ─────────────────────────────────────────────────

class AccountCreate(BaseModel):
    name: str
    type: str = "instagram_facebook"
    fb_access_token: Optional[str] = None
    yt_client_id: Optional[str] = None
    yt_client_secret: Optional[str] = None
    yt_refresh_token: Optional[str] = None

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    fb_access_token: Optional[str] = None
    fb_page_id: Optional[str] = None
    ig_user_id: Optional[str] = None
    publish_to_ig: Optional[bool] = None
    publish_to_fb: Optional[bool] = None
    publish_to_stories: Optional[bool] = None
    yt_client_id: Optional[str] = None
    yt_client_secret: Optional[str] = None
    yt_refresh_token: Optional[str] = None
    active: Optional[bool] = None

class ScheduleUpdate(BaseModel):
    day_of_week: str = "*"
    publish_times: list[str] = ["09:00", "18:00"]
    max_per_day: int = 2
    enabled: bool = True

class VideoUpdate(BaseModel):
    title: Optional[str] = None
    caption: Optional[str] = None
    video_type: Optional[str] = None
    yt_title: Optional[str] = None
    yt_description: Optional[str] = None
    yt_tags: Optional[list[str]] = None
    yt_category: Optional[str] = None
    yt_privacy: Optional[str] = None
    target_ig: Optional[bool] = None
    target_fb: Optional[bool] = None
    fb_title: Optional[str] = None

class ReorderRequest(BaseModel):
    video_ids: list[int]

class VideoCopyRequest(BaseModel):
    target_account_id: int

class AISettingsUpdate(BaseModel):
    provider: str
    api_key: str
    model_name: str

class CommentToneUpdate(BaseModel):
    tone_preset: str = "friendly"
    custom_tone: str = ""

class CommentReplyUpdate(BaseModel):
    reply_text: str

class AIGenerateRequest(BaseModel):
    comment_ids: list[int] = []

class BulkSendRequest(BaseModel):
    comment_ids: list[int] = []

class CommentImportItem(BaseModel):
    platform_comment_id: str
    reply_text: str


# ── Account Endpoints ───────────────────────────────────────────────

@app.get("/api/accounts", dependencies=[Depends(verify_token)])
async def list_accounts(type: Optional[str] = None):
    accounts = db.get_accounts(account_type=type)
    for acc in accounts:
        acc["stats"] = db.get_account_stats(acc["id"])
        acc["schedule"] = db.get_schedule(acc["id"])
        # Don't send tokens to frontend
        for key in ["fb_access_token", "yt_client_secret", "yt_refresh_token"]:
            if key in acc and acc[key]:
                acc[key] = "***configured***"
    return accounts


@app.post("/api/accounts", dependencies=[Depends(verify_token)])
async def create_account(data: AccountCreate):
    account_data = data.model_dump()

    # Auto-fetch info from API
    if data.type == "instagram_facebook" and data.fb_access_token:
        info = publisher.fetch_ig_account_info(data.fb_access_token)
        account_data.update({k: v for k, v in info.items() if k != "error"})
        if "error" in info:
            logger.warning(f"Partial fetch for account '{data.name}': {info['error']}")

    elif data.type == "youtube" and data.yt_client_id and data.yt_client_secret and data.yt_refresh_token:
        info = publisher.fetch_yt_channel_info(data.yt_client_id, data.yt_client_secret, data.yt_refresh_token)
        account_data.update({k: v for k, v in info.items() if k != "error"})
        if "error" in info:
            logger.warning(f"Partial fetch for YT account '{data.name}': {info['error']}")

    account = db.create_account(account_data)

    # Create upload directories
    acc_dir = os.path.join(UPLOAD_DIR, str(account["id"]))
    os.makedirs(os.path.join(acc_dir, "queue"), exist_ok=True)
    os.makedirs(os.path.join(acc_dir, "archive"), exist_ok=True)

    sched.reload()
    return account


@app.get("/api/accounts/{account_id}", dependencies=[Depends(verify_token)])
async def get_account(account_id: int):
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    account["stats"] = db.get_account_stats(account_id)
    account["schedule"] = db.get_schedule(account_id)
    for key in ["fb_access_token", "yt_client_secret", "yt_refresh_token"]:
        if key in account and account[key]:
            account[key] = "***configured***"
    return account


@app.put("/api/accounts/{account_id}", dependencies=[Depends(verify_token)])
async def update_account(account_id: int, data: AccountUpdate):
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    result = db.update_account(account_id, update_data)
    sched.reload()
    return result


@app.delete("/api/accounts/{account_id}", dependencies=[Depends(verify_token)])
async def delete_account(account_id: int):
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    db.delete_account(account_id)
    # Remove upload directory
    acc_dir = os.path.join(UPLOAD_DIR, str(account_id))
    if os.path.exists(acc_dir):
        shutil.rmtree(acc_dir)
    sched.reload()
    return {"ok": True}


@app.get("/api/accounts/{account_id}/tokens", dependencies=[Depends(verify_token)])
async def get_account_tokens(account_id: int):
    """Return actual API tokens for this account (for settings page)."""
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    tokens = {}
    if account["type"] == "instagram_facebook":
        tokens["fb_access_token"] = account.get("fb_access_token") or ""
        tokens["fb_page_id"] = account.get("fb_page_id") or ""
        tokens["ig_user_id"] = account.get("ig_user_id") or ""
    elif account["type"] == "youtube":
        tokens["yt_client_id"] = account.get("yt_client_id") or ""
        tokens["yt_client_secret"] = account.get("yt_client_secret") or ""
        tokens["yt_refresh_token"] = account.get("yt_refresh_token") or ""
    return tokens


@app.post("/api/accounts/{account_id}/refresh", dependencies=[Depends(verify_token)])
async def refresh_account_info(account_id: int):
    """Re-fetch account info from platform APIs."""
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    info = {}
    if account["type"] == "instagram_facebook" and account.get("fb_access_token"):
        info = publisher.fetch_ig_account_info(account["fb_access_token"], account.get("ig_user_id"))
        fb_info = publisher.fetch_fb_page_info(account["fb_access_token"])
        info.update(fb_info)
    elif account["type"] == "youtube" and account.get("yt_client_id"):
        info = publisher.fetch_yt_channel_info(
            account["yt_client_id"], account["yt_client_secret"], account["yt_refresh_token"]
        )

    if "error" in info:
        raise HTTPException(400, info["error"])

    update_data = {k: v for k, v in info.items() if k != "error"}
    result = db.update_account(account_id, update_data)
    return result


# ── Schedule Endpoints ───────────────────────────────────────────────

@app.get("/api/accounts/{account_id}/schedule", dependencies=[Depends(verify_token)])
async def get_schedule(account_id: int):
    schedule = db.get_schedule(account_id)
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    return schedule


@app.put("/api/accounts/{account_id}/schedule", dependencies=[Depends(verify_token)])
async def update_schedule(account_id: int, data: ScheduleUpdate):
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    result = db.update_schedule(account_id, data.model_dump())
    sched.reload()
    return result


# ── Video Endpoints ──────────────────────────────────────────────────

def compute_estimated_dates(account_id: int) -> dict:
    """Calculate estimated publish dates for queued videos based on schedule."""
    schedule = db.get_schedule(account_id)
    videos = db.get_videos(account_id, status="queued")
    if not schedule or not schedule.get("enabled") or not videos:
        return {}

    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    publish_times = schedule.get("publish_times", [])
    if isinstance(publish_times, str):
        import json as _json
        publish_times = _json.loads(publish_times)
    publish_times = sorted(publish_times)

    dow = schedule.get("day_of_week", "*")
    all_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    allowed = set(all_days) if dow == "*" else set(d.strip().lower()[:3] for d in dow.split(","))
    max_per_day = schedule.get("max_per_day", 2)

    slots = []
    current_date = now.date()
    already_today = db.count_published_today(account_id)

    for _ in range(365):
        day_name = current_date.strftime("%a").lower()[:3]
        if day_name in allowed:
            used = already_today if current_date == now.date() else 0
            for t in publish_times:
                if used >= max_per_day:
                    break
                h, m = map(int, t.split(":"))
                slot = datetime(current_date.year, current_date.month, current_date.day, h, m, tzinfo=tz)
                if slot <= now:
                    continue
                slots.append(slot.isoformat())
                used += 1
                if len(slots) >= len(videos):
                    break
        if len(slots) >= len(videos):
            break
        current_date += timedelta(days=1)

    return {videos[i]["id"]: slots[i] for i in range(min(len(videos), len(slots)))}


@app.get("/api/accounts/{account_id}/videos", dependencies=[Depends(verify_token)])
async def list_videos(account_id: int, status: Optional[str] = None, video_type: Optional[str] = None):
    videos = db.get_videos(account_id, status=status, video_type=video_type)
    if status == "queued" or (not status and not video_type):
        est_dates = compute_estimated_dates(account_id)
        for v in videos:
            if v["id"] in est_dates:
                v["estimated_publish_at"] = est_dates[v["id"]]
    return videos


@app.get("/api/videos/{video_id}", dependencies=[Depends(verify_token)])
async def get_video(video_id: int):
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    return video


@app.put("/api/videos/{video_id}", dependencies=[Depends(verify_token)])
async def update_video(video_id: int, data: VideoUpdate):
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    return db.update_video(video_id, update_data)


@app.delete("/api/videos/{video_id}", dependencies=[Depends(verify_token)])
async def delete_video(video_id: int):
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    # Delete files from both queue and archive
    for subdir in ("queue", "archive"):
        video_path = os.path.join(UPLOAD_DIR, str(video["account_id"]), subdir, video["filename"])
        if os.path.exists(video_path):
            os.remove(video_path)
        for ext in (".txt", ".srt"):
            extra = video_path.rsplit(".", 1)[0] + ext
            if os.path.exists(extra):
                os.remove(extra)
    db.delete_video(video_id)
    return {"ok": True}


@app.post("/api/accounts/{account_id}/videos/reorder", dependencies=[Depends(verify_token)])
async def reorder_videos(account_id: int, data: ReorderRequest):
    db.reorder_videos(account_id, data.video_ids)
    return {"ok": True}


@app.post("/api/accounts/{account_id}/videos/upload", dependencies=[Depends(verify_token)])
async def upload_video(
    account_id: int,
    file: UploadFile = File(...),
    subtitle: Optional[UploadFile] = File(None),
    title: str = Form(""),
    caption: str = Form(""),
    video_type: str = Form("reel"),
    yt_title: str = Form(""),
    yt_description: str = Form(""),
    yt_tags: str = Form("[]"),
    yt_category: str = Form("22"),
    yt_privacy: str = Form("public"),
):
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    if not file.filename.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
        raise HTTPException(400, "Invalid video format. Supported: mp4, mov, avi, mkv, webm")

    # Sanitize filename
    safe_name = "".join(c for c in file.filename if c.isalnum() or c in "._-").strip()
    if not safe_name:
        safe_name = f"video_{uuid.uuid4().hex[:8]}.mp4"

    # Ensure unique filename
    queue_dir = os.path.join(UPLOAD_DIR, str(account_id), "queue")
    os.makedirs(queue_dir, exist_ok=True)
    dest_path = os.path.join(queue_dir, safe_name)
    counter = 1
    base, ext = os.path.splitext(safe_name)
    while os.path.exists(dest_path):
        safe_name = f"{base}_{counter}{ext}"
        dest_path = os.path.join(queue_dir, safe_name)
        counter += 1

    # Verify path is within upload dir
    real_dest = os.path.realpath(dest_path)
    if not real_dest.startswith(os.path.realpath(queue_dir)):
        raise HTTPException(400, "Invalid filename")

    # Write file
    file_size = 0
    with open(dest_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            file_size += len(chunk)
            if file_size > MAX_UPLOAD_SIZE:
                os.remove(dest_path)
                raise HTTPException(413, f"File too large. Max: {MAX_UPLOAD_SIZE // (1024*1024)}MB")
            f.write(chunk)

    # Save caption to .txt file
    if caption:
        caption_path = dest_path.rsplit(".", 1)[0] + ".txt"
        with open(caption_path, "w", encoding="utf-8") as f:
            f.write(caption)

    # Save subtitle .srt file
    subtitle_filename = None
    if subtitle and subtitle.filename and subtitle.filename.lower().endswith(".srt"):
        srt_name = os.path.splitext(safe_name)[0] + ".srt"
        srt_path = os.path.join(queue_dir, srt_name)
        with open(srt_path, "wb") as f:
            f.write(await subtitle.read())
        subtitle_filename = srt_name

    # Parse yt_tags
    try:
        tags = json.loads(yt_tags) if yt_tags else []
    except json.JSONDecodeError:
        tags = []

    # Add to database
    video = db.add_video({
        "account_id": account_id,
        "filename": safe_name,
        "original_filename": file.filename,
        "title": title,
        "caption": caption,
        "video_type": video_type,
        "file_size": file_size,
        "yt_title": yt_title,
        "yt_description": yt_description,
        "yt_tags": tags,
        "yt_category": yt_category,
        "yt_privacy": yt_privacy,
        "subtitle_file": subtitle_filename,
    })

    return video


@app.post("/api/accounts/{account_id}/videos/bulk-upload", dependencies=[Depends(verify_token)])
async def bulk_upload(
    account_id: int,
    files: list[UploadFile] = File(...),
    video_type: str = Form("reel"),
):
    """Upload multiple videos at once. Captions can be provided as .txt files with matching names."""
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    queue_dir = os.path.join(UPLOAD_DIR, str(account_id), "queue")
    os.makedirs(queue_dir, exist_ok=True)

    results = []
    video_files = []
    caption_files = {}
    subtitle_files = {}

    # Separate videos, captions, and subtitles
    for f in files:
        if f.filename.lower().endswith(".txt"):
            base = f.filename.rsplit(".", 1)[0]
            content = (await f.read()).decode("utf-8", errors="replace")
            caption_files[base] = content
        elif f.filename.lower().endswith(".srt"):
            base = f.filename.rsplit(".", 1)[0]
            subtitle_files[base] = await f.read()
        else:
            video_files.append(f)

    for file in video_files:
        if not file.filename.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
            results.append({"filename": file.filename, "error": "Invalid format"})
            continue

        safe_name = "".join(c for c in file.filename if c.isalnum() or c in "._-").strip()
        if not safe_name:
            safe_name = f"video_{uuid.uuid4().hex[:8]}.mp4"

        dest_path = os.path.join(queue_dir, safe_name)
        counter = 1
        base, ext = os.path.splitext(safe_name)
        while os.path.exists(dest_path):
            safe_name = f"{base}_{counter}{ext}"
            dest_path = os.path.join(queue_dir, safe_name)
            counter += 1

        real_dest = os.path.realpath(dest_path)
        if not real_dest.startswith(os.path.realpath(queue_dir)):
            results.append({"filename": file.filename, "error": "Invalid filename"})
            continue

        file_size = 0
        await file.seek(0)
        with open(dest_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > MAX_UPLOAD_SIZE:
                    break
                f.write(chunk)
        if file_size > MAX_UPLOAD_SIZE:
            os.remove(dest_path)
            results.append({"filename": file.filename, "error": "Too large"})
            continue
        if file_size == 0:
            os.remove(dest_path)
            results.append({"filename": file.filename, "error": "Empty file"})
            continue

        # Look for matching caption
        file_base = file.filename.rsplit(".", 1)[0]
        caption = caption_files.get(file_base, "")

        if caption:
            caption_path = dest_path.rsplit(".", 1)[0] + ".txt"
            with open(caption_path, "w") as cf:
                cf.write(caption)

        # Look for matching subtitle (.srt)
        subtitle_filename = None
        srt_data = subtitle_files.get(file_base)
        if srt_data:
            srt_name = os.path.splitext(safe_name)[0] + ".srt"
            srt_path = os.path.join(queue_dir, srt_name)
            with open(srt_path, "wb") as sf:
                sf.write(srt_data)
            subtitle_filename = srt_name

        video = db.add_video({
            "account_id": account_id,
            "filename": safe_name,
            "original_filename": file.filename,
            "title": file_base.replace("_", " ").replace("-", " "),
            "caption": caption,
            "video_type": video_type,
            "file_size": file_size,
            "subtitle_file": subtitle_filename,
        })
        results.append({"filename": safe_name, "id": video["id"], "ok": True})

    return {"uploaded": len([r for r in results if r.get("ok")]), "results": results}


# ── Publish Endpoints ────────────────────────────────────────────────

@app.post("/api/videos/{video_id}/publish", dependencies=[Depends(verify_token)])
async def publish_now(video_id: int):
    """Trigger immediate publishing of a specific video."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    if video["status"] != "queued":
        raise HTTPException(400, f"Video is {video['status']}, not queued")

    account = db.get_account(video["account_id"])
    if not account:
        raise HTTPException(404, "Account not found")

    # Clean old publish jobs to prevent memory leak
    if len(publish_jobs) > 50:
        for old_key in list(publish_jobs.keys())[:-20]:
            del publish_jobs[old_key]

    # Mark video as publishing atomically
    db.update_video(video_id, {"status": "publishing"})

    job_id = str(uuid.uuid4())
    publish_jobs[job_id] = {"status": "started", "video_id": video_id, "messages": []}

    def run_publish():
        try:
            publish_jobs[job_id]["status"] = "publishing"
            publish_jobs[job_id]["messages"].append("Starting publish...")
            sched.do_publish(account, video)
            updated = db.get_video(video_id)
            publish_jobs[job_id]["status"] = "done" if updated["status"] == "published" else "failed"
            publish_jobs[job_id]["messages"].append(
                f"Done: {updated['status']}" + (f" - {updated.get('error_message', '')}" if updated["status"] == "failed" else "")
            )
        except Exception as e:
            publish_jobs[job_id]["status"] = "failed"
            publish_jobs[job_id]["messages"].append(f"Error: {e}")

    thread = threading.Thread(target=run_publish, daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "started"}


@app.get("/api/publish/status/{job_id}", dependencies=[Depends(verify_token)])
async def publish_status(job_id: str):
    if job_id not in publish_jobs:
        raise HTTPException(404, "Job not found")
    return publish_jobs[job_id]


@app.post("/api/videos/{video_id}/archive", dependencies=[Depends(verify_token)])
async def archive_video(video_id: int):
    """Move a video to archive without publishing."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    video_path = os.path.join(UPLOAD_DIR, str(video["account_id"]), "queue", video["filename"])
    archive_dir = os.path.join(UPLOAD_DIR, str(video["account_id"]), "archive")
    os.makedirs(archive_dir, exist_ok=True)

    if os.path.exists(video_path):
        shutil.move(video_path, os.path.join(archive_dir, video["filename"]))
        caption_path = video_path.rsplit(".", 1)[0] + ".txt"
        if os.path.exists(caption_path):
            shutil.move(caption_path, os.path.join(archive_dir, os.path.basename(caption_path)))
        srt_path = video_path.rsplit(".", 1)[0] + ".srt"
        if os.path.exists(srt_path):
            shutil.move(srt_path, os.path.join(archive_dir, os.path.basename(srt_path)))

    db.update_video(video_id, {"status": "archived"})
    return {"ok": True}


@app.post("/api/videos/{video_id}/copy", dependencies=[Depends(verify_token)])
async def copy_video(video_id: int, req: VideoCopyRequest):
    """Copy a queued video to another account's queue."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    if video["status"] != "queued":
        raise HTTPException(400, "Only queued videos can be copied")

    src_account = db.get_account(video["account_id"])
    dst_account = db.get_account(req.target_account_id)
    if not dst_account:
        raise HTTPException(404, "Target account not found")
    if video["account_id"] == req.target_account_id:
        raise HTTPException(400, "Cannot copy to the same account")

    # Auto-convert video type based on account types
    vtype = video["video_type"]
    if src_account["type"] != dst_account["type"]:
        if dst_account["type"] == "youtube":
            vtype = "short" if vtype in ("reel", "story") else vtype
        else:
            vtype = "reel" if vtype in ("short", "video") else vtype

    # Handle filename deduplication in target queue dir
    src_dir = os.path.join(UPLOAD_DIR, str(video["account_id"]), "queue")
    dst_dir = os.path.join(UPLOAD_DIR, str(req.target_account_id), "queue")
    os.makedirs(dst_dir, exist_ok=True)

    base_name, ext = os.path.splitext(video["filename"])
    dst_filename = video["filename"]
    counter = 1
    while os.path.exists(os.path.join(dst_dir, dst_filename)):
        dst_filename = f"{base_name}_{counter}{ext}"
        counter += 1

    # Hard-link video file (saves disk space), fallback to copy
    src_path = os.path.join(src_dir, video["filename"])
    dst_path = os.path.join(dst_dir, dst_filename)
    if not os.path.exists(src_path):
        raise HTTPException(400, "Source video file not found on disk")
    try:
        os.link(src_path, dst_path)
    except OSError:
        shutil.copy2(src_path, dst_path)

    # Copy caption and subtitle files (regular copy — users may edit independently)
    dst_base = os.path.join(dst_dir, os.path.splitext(dst_filename)[0])
    src_base = os.path.join(src_dir, os.path.splitext(video["filename"])[0])
    subtitle_file = None
    for file_ext in (".txt", ".srt"):
        if os.path.exists(src_base + file_ext):
            shutil.copy2(src_base + file_ext, dst_base + file_ext)
            if file_ext == ".srt":
                subtitle_file = os.path.splitext(dst_filename)[0] + ".srt"

    new_video = db.add_video({
        "account_id": req.target_account_id,
        "filename": dst_filename,
        "original_filename": video.get("original_filename", video["filename"]),
        "title": video.get("title", ""),
        "caption": video.get("caption", ""),
        "video_type": vtype,
        "file_size": video.get("file_size"),
        "yt_title": video.get("yt_title"),
        "yt_description": video.get("yt_description"),
        "yt_tags": video.get("yt_tags"),
        "yt_category": video.get("yt_category", "22"),
        "yt_privacy": video.get("yt_privacy", "public"),
        "subtitle_file": subtitle_file or video.get("subtitle_file"),
        "target_ig": video.get("target_ig", 1),
        "target_fb": video.get("target_fb", 1),
        "fb_title": video.get("fb_title"),
    })
    return {"ok": True, "video": new_video}


@app.post("/api/videos/{video_id}/retry", dependencies=[Depends(verify_token)])
async def retry_video(video_id: int):
    """Retry a failed video - move it back to queue."""
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    if video["status"] != "failed":
        raise HTTPException(400, "Video is not in failed status")

    db.update_video(video_id, {"status": "queued", "error_message": None, "published_at": None})
    return {"ok": True}


# ── Scheduler Endpoints ─────────────────────────────────────────────

@app.get("/api/scheduler/jobs", dependencies=[Depends(verify_token)])
async def scheduler_jobs():
    return sched.get_active_jobs()


@app.post("/api/scheduler/reload", dependencies=[Depends(verify_token)])
async def scheduler_reload():
    sched.reload()
    return {"ok": True, "jobs": sched.get_active_jobs()}


# ── YouTube OAuth Flow ──────────────────────────────────────────────

YT_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
]
YT_REDIRECT_URI = os.environ.get("SMM_YT_REDIRECT_URI", "http://localhost:8902/api/youtube/oauth/callback")

# In-memory state for OAuth CSRF protection (state -> (account_id, created_at))
_oauth_states: dict = {}
_OAUTH_STATE_TTL = 600  # 10 minutes


def _cleanup_oauth_states():
    """Remove expired OAuth states."""
    now = time.time()
    expired = [k for k, v in _oauth_states.items() if now - v[1] > _OAUTH_STATE_TTL]
    for k in expired:
        del _oauth_states[k]


@app.get("/api/youtube/oauth/start", dependencies=[Depends(verify_token)])
async def youtube_oauth_start(account_id: int):
    """Generate Google OAuth consent URL for YouTube account."""
    account = db.get_account(account_id)
    if not account or account["type"] != "youtube":
        raise HTTPException(400, "Not a YouTube account")
    if not account.get("yt_client_id") or not account.get("yt_client_secret"):
        raise HTTPException(400, "Set Client ID and Client Secret first in account settings")

    _cleanup_oauth_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (account_id, time.time())

    params = urlencode({
        "client_id": account["yt_client_id"],
        "redirect_uri": YT_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(YT_OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{params}"}


@app.get("/api/youtube/oauth/callback")
async def youtube_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """Receive OAuth callback from Google, exchange code for tokens."""
    if error:
        return JSONResponse({"error": error}, status_code=400)
    _cleanup_oauth_states()
    if state not in _oauth_states:
        return JSONResponse({"error": "Invalid or expired state parameter. Please start OAuth again."}, status_code=400)

    account_id, _ = _oauth_states.pop(state)
    account = db.get_account(account_id)
    if not account:
        return JSONResponse({"error": "Account not found"}, status_code=404)

    # Exchange code for tokens
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            token_resp = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": account["yt_client_id"],
                "client_secret": account["yt_client_secret"],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": YT_REDIRECT_URI,
            })
        token_data = token_resp.json()

        if "error" in token_data:
            return JSONResponse({
                "error": f"Token exchange failed: {token_data.get('error_description', token_data['error'])}"
            }, status_code=400)

        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            return JSONResponse({
                "error": "No refresh token received. Make sure 'access_type=offline' and 'prompt=consent' are set."
            }, status_code=400)

        # Save refresh token
        db.update_account(account_id, {"yt_refresh_token": refresh_token})

        # Fetch channel info with the new access token
        access_token = token_data.get("access_token")
        if access_token:
            info = publisher.fetch_yt_channel_info(
                account["yt_client_id"], account["yt_client_secret"], refresh_token
            )
            update_data = {k: v for k, v in info.items() if k != "error"}
            if update_data:
                db.update_account(account_id, update_data)

        sched.reload()
        logger.info(f"YouTube OAuth completed for account {account_id}")

        # Redirect back to dashboard
        return RedirectResponse("/social-admin-v2/#oauth-success", status_code=302)

    except Exception as e:
        logger.error(f"YouTube OAuth error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Sync Published Videos from APIs ────────────────────────────────

@app.post("/api/accounts/{account_id}/sync-published", dependencies=[Depends(verify_token)])
async def sync_published_videos(account_id: int):
    """Fetch published videos from platform API and store them in the database."""
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    if account["type"] == "youtube":
        return await _sync_youtube_published(account)
    elif account["type"] == "instagram_facebook":
        return await _sync_ig_published(account)
    else:
        raise HTTPException(400, "Unsupported account type")


async def _sync_youtube_published(account: dict) -> dict:
    """Fetch published videos from YouTube API."""
    import httpx

    access_token = publisher._get_yt_access_token(
        account["yt_client_id"], account["yt_client_secret"], account["yt_refresh_token"]
    )
    if not access_token:
        raise HTTPException(400, "YouTube token refresh failed. Re-authorize via OAuth.")

    synced = 0
    errors = []

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Get channel's uploads playlist
            ch_resp = await client.get("https://www.googleapis.com/youtube/v3/channels", params={
                "part": "contentDetails,statistics,snippet",
                "mine": "true",
            }, headers={"Authorization": f"Bearer {access_token}"})
            ch_data = ch_resp.json()

            if not ch_data.get("items"):
                raise HTTPException(400, "Could not fetch channel info")

            channel = ch_data["items"][0]
            uploads_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]

            # Update channel stats
            snippet = channel.get("snippet", {})
            stats = channel.get("statistics", {})
            db.update_account(account["id"], {
                "yt_channel_id": channel["id"],
                "yt_channel_name": snippet.get("title", ""),
                "yt_channel_pic": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                "yt_subscribers": int(stats.get("subscriberCount", 0)),
                "yt_video_count": int(stats.get("videoCount", 0)),
            })

            # Fetch videos from uploads playlist (max 50 per page, up to 200 total)
            all_videos = []
            page_token = None
            for _ in range(4):  # max 4 pages = 200 videos
                params = {
                    "part": "snippet,contentDetails",
                    "playlistId": uploads_id,
                    "maxResults": 50,
                }
                if page_token:
                    params["pageToken"] = page_token

                pl_resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/playlistItems",
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                pl_data = pl_resp.json()
                all_videos.extend(pl_data.get("items", []))
                page_token = pl_data.get("nextPageToken")
                if not page_token:
                    break

            # Get video stats in batches of 50
            video_ids = [v["snippet"]["resourceId"]["videoId"] for v in all_videos]
            video_stats = {}
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i:i+50]
                vs_resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={
                        "part": "statistics,status",
                        "id": ",".join(batch),
                    },
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                for item in vs_resp.json().get("items", []):
                    video_stats[item["id"]] = item

            # Check which videos we already have
            existing = db.get_videos(account["id"])
            existing_yt_ids = {v.get("yt_video_id") for v in existing if v.get("yt_video_id")}

            for item in all_videos:
                snippet = item["snippet"]
                vid_id = snippet["resourceId"]["videoId"]

                if vid_id in existing_yt_ids:
                    continue  # Already in DB

                stats_item = video_stats.get(vid_id, {})
                video_status = stats_item.get("status", {})

                video_data = {
                    "account_id": account["id"],
                    "filename": f"yt_{vid_id}.mp4",
                    "original_filename": snippet.get("title", vid_id),
                    "title": snippet.get("title", ""),
                    "caption": "",
                    "video_type": "video",
                    "yt_title": snippet.get("title", ""),
                    "yt_description": snippet.get("description", ""),
                    "yt_tags": [],
                    "yt_category": "22",
                    "yt_privacy": video_status.get("privacyStatus", "public"),
                    "status": "published",
                    "yt_video_id": vid_id,
                    "yt_url": f"https://www.youtube.com/watch?v={vid_id}",
                }

                # Parse published date
                pub_date = snippet.get("publishedAt", "")
                if pub_date:
                    video_data["published_at"] = pub_date

                db.add_video(video_data)
                synced += 1

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"YouTube sync error: {e}")
        errors.append(str(e))

    return {"synced": synced, "total_on_platform": len(all_videos) if 'all_videos' in dir() else 0, "errors": errors}


async def _sync_ig_published(account: dict) -> dict:
    """Fetch published posts from Instagram and Facebook APIs."""
    import httpx

    token = account.get("fb_access_token")
    ig_user_id = account.get("ig_user_id")
    fb_page_id = account.get("fb_page_id")

    synced = 0
    total = 0
    errors = []

    async with httpx.AsyncClient(timeout=30) as client:
        # ── Sync Instagram posts ────────────────────────────────
        if token and ig_user_id:
            try:
                all_media = []
                url = f"{publisher.GRAPH_API_BASE}/{ig_user_id}/media"
                params = {
                    "access_token": token,
                    "fields": "id,caption,media_type,media_url,permalink,timestamp,thumbnail_url",
                    "limit": 50,
                }

                for _ in range(4):  # max 200 posts
                    resp = await client.get(url, params=params)
                    data = resp.json()
                    if "error" in data:
                        errors.append(f"IG: {data['error'].get('message', '')}")
                        break
                    all_media.extend(data.get("data", []))
                    # Use cursor-based pagination (not next URL which may change API version)
                    after = data.get("paging", {}).get("cursors", {}).get("after")
                    if not after:
                        break
                    params["after"] = after

                total += len(all_media)

                existing = db.get_videos(account["id"])
                existing_ig_ids = {v.get("ig_media_id") for v in existing if v.get("ig_media_id")}

                for media in all_media:
                    if media["id"] in existing_ig_ids:
                        continue
                    if media.get("media_type") not in ("VIDEO", "REELS"):
                        continue
                    db.add_video({
                        "account_id": account["id"],
                        "filename": f"ig_{media['id']}.mp4",
                        "original_filename": (media.get("caption") or "")[:60],
                        "title": (media.get("caption") or "")[:100],
                        "caption": media.get("caption") or "",
                        "video_type": "reel",
                        "status": "published",
                        "ig_media_id": media["id"],
                        "ig_permalink": media.get("permalink", ""),
                        "published_at": media.get("timestamp", ""),
                    })
                    synced += 1
            except Exception as e:
                logger.error(f"IG sync error: {e}")
                errors.append(f"IG: {e}")

        # ── Sync Facebook Page videos ───────────────────────────
        if token and fb_page_id:
            try:
                all_fb = []
                url = f"{publisher.GRAPH_API_BASE}/{fb_page_id}/videos"
                params = {
                    "access_token": token,
                    "fields": "id,title,description,permalink_url,created_time,length,views,source",
                    "limit": 50,
                }

                for _ in range(4):
                    resp = await client.get(url, params=params)
                    data = resp.json()
                    if "error" in data:
                        errors.append(f"FB: {data['error'].get('message', '')}")
                        break
                    all_fb.extend(data.get("data", []))
                    after = data.get("paging", {}).get("cursors", {}).get("after")
                    if not after:
                        break
                    params["after"] = after

                total += len(all_fb)

                existing = db.get_videos(account["id"])
                existing_fb_ids = {v.get("fb_video_id") for v in existing if v.get("fb_video_id")}

                for vid in all_fb:
                    if vid["id"] in existing_fb_ids:
                        continue
                    db.add_video({
                        "account_id": account["id"],
                        "filename": f"fb_{vid['id']}.mp4",
                        "original_filename": (vid.get("title") or vid.get("description") or "")[:60],
                        "title": vid.get("title") or "",
                        "caption": vid.get("description") or "",
                        "video_type": "reel",
                        "status": "published",
                        "fb_video_id": vid["id"],
                        "fb_permalink": vid.get("permalink_url", ""),
                        "published_at": vid.get("created_time", ""),
                    })
                    synced += 1
            except Exception as e:
                logger.error(f"FB sync error: {e}")
                errors.append(f"FB: {e}")

    if not token:
        raise HTTPException(400, "Account missing API token")

    return {"synced": synced, "total_on_platform": total, "errors": errors}


# ── Dashboard Stats ─────────────────────────────────────────────────

@app.get("/api/stats", dependencies=[Depends(verify_token)])
async def global_stats():
    stats = db.get_global_stats()
    stats["scheduler_jobs"] = len(sched.get_active_jobs())
    return stats


@app.get("/api/logs", dependencies=[Depends(verify_token)])
async def get_logs(account_id: Optional[int] = None, limit: int = 50):
    return db.get_publish_logs(account_id=account_id, limit=limit)


# ── Video Streaming ──────────────────────────────────────────────────

@app.get("/api/video-file/{account_id}/{subdir}/{filename}")
async def serve_video(account_id: int, subdir: str, filename: str, request: Request):
    """Serve video files. Accepts token in query param or Authorization header."""
    token = request.query_params.get("token", "")
    auth = request.headers.get("Authorization", "")
    auth_token = auth[7:] if auth.startswith("Bearer ") else ""
    if not (secrets.compare_digest(token, API_TOKEN) if token else False) and \
       not (secrets.compare_digest(auth_token, API_TOKEN) if auth_token else False):
        raise HTTPException(401, "Unauthorized")

    if subdir not in ("queue", "archive"):
        raise HTTPException(400, "Invalid directory")

    safe_filename = os.path.basename(filename)
    file_path = os.path.join(UPLOAD_DIR, str(account_id), subdir, safe_filename)
    real_path = os.path.realpath(file_path)

    if not real_path.startswith(os.path.realpath(UPLOAD_DIR)):
        raise HTTPException(400, "Invalid path")
    if not os.path.exists(real_path):
        raise HTTPException(404, "File not found")

    return FileResponse(real_path, media_type="video/mp4")


# ── Comments Endpoints ──────────────────────────────────────────────

@app.get("/api/accounts/{account_id}/comments", dependencies=[Depends(verify_token)])
async def list_comments(account_id: int, filter: str = "all", platform: str = None,
                        video_id: str = None, sort: str = "newest",
                        limit: int = 200, offset: int = 0):
    from datetime import datetime as _dt
    since = None
    reply_status = None
    if filter == "unsent":
        reply_status = "unsent"
    elif filter == "no_reply":
        reply_status = "no_reply"
    elif filter == "week_no_reply":
        reply_status = "no_reply"
        since = (_dt.now() - timedelta(days=7)).isoformat()
    elif filter == "oldest_no_reply":
        reply_status = "no_reply"
        sort = "oldest"
    elif filter == "draft":
        reply_status = "draft"
    elif filter == "sent":
        reply_status = "sent"
    elif filter == "failed":
        reply_status = "failed"
    return db.get_comments(account_id, reply_status=reply_status, platform=platform,
                           video_id=video_id, since_date=since, sort=sort,
                           limit=limit, offset=offset)


@app.get("/api/accounts/{account_id}/comments/stats", dependencies=[Depends(verify_token)])
async def comment_stats(account_id: int):
    return db.get_comment_stats(account_id)


@app.get("/api/comments/{comment_id}", dependencies=[Depends(verify_token)])
async def get_comment(comment_id: int):
    c = db.get_comment(comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    return c


@app.put("/api/comments/{comment_id}", dependencies=[Depends(verify_token)])
async def update_comment_reply(comment_id: int, req: CommentReplyUpdate):
    c = db.get_comment(comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    status = "edited" if c["reply_status"] in ("draft", "edited", "failed") else "draft"
    return db.update_comment(comment_id, {"reply_text": req.reply_text, "reply_status": status})


@app.post("/api/accounts/{account_id}/comments/fetch", dependencies=[Depends(verify_token)])
async def fetch_comments(account_id: int):
    """Fetch comments from platform API (runs in background)."""
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    job_id = str(uuid.uuid4())
    background_jobs[job_id] = {"type": "fetch", "status": "started", "progress": "", "result": None}

    def run_fetch():
        try:
            background_jobs[job_id]["status"] = "running"
            comments = []
            if account["type"] == "youtube":
                if not account.get("yt_refresh_token") or not account.get("yt_channel_id"):
                    background_jobs[job_id] = {"type": "fetch", "status": "failed",
                                                "progress": "YouTube not configured", "result": None}
                    return
                background_jobs[job_id]["progress"] = "Pobieranie komentarzy z YouTube..."
                comments = publisher.fetch_yt_comments(
                    account["yt_client_id"], account["yt_client_secret"],
                    account["yt_refresh_token"], account["yt_channel_id"])
            elif account["type"] == "instagram_facebook":
                if account.get("ig_user_id") and account.get("fb_access_token"):
                    background_jobs[job_id]["progress"] = "Pobieranie komentarzy z Instagram..."
                    comments.extend(publisher.fetch_ig_comments(
                        account["fb_access_token"], account["ig_user_id"]))
                if account.get("fb_page_id") and account.get("fb_access_token"):
                    background_jobs[job_id]["progress"] = "Pobieranie komentarzy z Facebook..."
                    comments.extend(publisher.fetch_fb_comments(
                        account["fb_access_token"], account["fb_page_id"]))

            # Store in DB (dedup via upsert)
            new_count = 0
            for c in comments:
                c["account_id"] = account_id
                result = db.upsert_comment(c)
                if result.get("fetched_at") and result["fetched_at"] >= datetime.now().strftime("%Y-%m-%d"):
                    new_count += 1

            background_jobs[job_id] = {
                "type": "fetch", "status": "done",
                "progress": f"Gotowe: {len(comments)} komentarzy ({new_count} nowych)",
                "result": {"total": len(comments), "new": new_count},
            }
        except Exception as e:
            logger.error(f"Comment fetch error: {e}")
            background_jobs[job_id] = {"type": "fetch", "status": "failed",
                                        "progress": f"Błąd: {e}", "result": None}

    threading.Thread(target=run_fetch, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}", dependencies=[Depends(verify_token)])
async def job_status(job_id: str):
    if job_id not in background_jobs:
        raise HTTPException(404, "Job not found")
    return background_jobs[job_id]


# ── Comment Reply Sending ──────────────────────────────────────────

@app.post("/api/comments/{comment_id}/send", dependencies=[Depends(verify_token)])
async def send_comment_reply(comment_id: int):
    c = db.get_comment(comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    if not c.get("reply_text"):
        raise HTTPException(400, "No reply text")
    if c["reply_status"] == "sent":
        raise HTTPException(400, "Already sent")

    account = db.get_account(c["account_id"])
    if not account:
        raise HTTPException(404, "Account not found")

    db.update_comment(comment_id, {"reply_status": "sending"})

    try:
        if c["platform"] == "youtube":
            result = publisher.send_yt_reply(
                account["yt_client_id"], account["yt_client_secret"],
                account["yt_refresh_token"], c["platform_comment_id"], c["reply_text"])
        elif c["platform"] == "instagram":
            result = publisher.send_ig_reply(
                account["fb_access_token"], c["platform_video_id"],
                c["platform_comment_id"], c["reply_text"])
        elif c["platform"] == "facebook":
            result = publisher.send_fb_reply(
                account["fb_access_token"], account["fb_page_id"],
                c["platform_comment_id"], c["reply_text"])
        else:
            result = {"success": False, "error": "Unknown platform"}

        if result.get("success"):
            db.update_comment(comment_id, {
                "reply_status": "sent",
                "reply_sent_at": datetime.now().isoformat(),
                "reply_platform_id": result.get("reply_id"),
                "has_owner_reply": 1,
            })
            return {"ok": True, "reply_id": result.get("reply_id")}
        else:
            db.update_comment(comment_id, {
                "reply_status": "failed",
                "reply_error": result.get("error", "Unknown error"),
            })
            raise HTTPException(500, result.get("error", "Send failed"))
    except HTTPException:
        raise
    except Exception as e:
        db.update_comment(comment_id, {"reply_status": "failed", "reply_error": str(e)})
        raise HTTPException(500, str(e))


@app.post("/api/accounts/{account_id}/comments/send-all", dependencies=[Depends(verify_token)])
async def send_all_replies(account_id: int, req: BulkSendRequest):
    """Send all pending replies (draft/edited) in background."""
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    if req.comment_ids:
        pending = [db.get_comment(cid) for cid in req.comment_ids]
        pending = [c for c in pending if c and c["reply_text"]]
    else:
        pending = db.get_comments(account_id, reply_status="draft")

    job_id = str(uuid.uuid4())
    background_jobs[job_id] = {"type": "send", "status": "running", "progress": "0/0", "result": None}

    def run_send():
        sent = 0
        failed = 0
        for i, c in enumerate(pending):
            background_jobs[job_id]["progress"] = f"{i+1}/{len(pending)}"
            try:
                db.update_comment(c["id"], {"reply_status": "sending"})
                if c["platform"] == "youtube":
                    result = publisher.send_yt_reply(
                        account["yt_client_id"], account["yt_client_secret"],
                        account["yt_refresh_token"], c["platform_comment_id"], c["reply_text"])
                elif c["platform"] == "instagram":
                    result = publisher.send_ig_reply(
                        account["fb_access_token"], c["platform_video_id"],
                        c["platform_comment_id"], c["reply_text"])
                elif c["platform"] == "facebook":
                    result = publisher.send_fb_reply(
                        account["fb_access_token"], account["fb_page_id"],
                        c["platform_comment_id"], c["reply_text"])
                else:
                    result = {"success": False, "error": "Unknown platform"}

                if result.get("success"):
                    db.update_comment(c["id"], {
                        "reply_status": "sent", "reply_sent_at": datetime.now().isoformat(),
                        "reply_platform_id": result.get("reply_id"), "has_owner_reply": 1,
                    })
                    sent += 1
                else:
                    db.update_comment(c["id"], {"reply_status": "failed", "reply_error": result.get("error")})
                    failed += 1
            except Exception as e:
                db.update_comment(c["id"], {"reply_status": "failed", "reply_error": str(e)})
                failed += 1
            time.sleep(1)  # Rate limit protection

        background_jobs[job_id] = {
            "type": "send", "status": "done",
            "progress": f"Wysłano {sent}, błędów {failed}",
            "result": {"sent": sent, "failed": failed},
        }

    threading.Thread(target=run_send, daemon=True).start()
    return {"job_id": job_id, "pending": len(pending)}


# ── AI Settings & Generation ──────────────────────────────────────

@app.get("/api/ai-settings", dependencies=[Depends(verify_token)])
async def get_ai_settings():
    settings = db.get_ai_settings()
    if settings:
        settings["api_key"] = "***configured***"
    return settings or {}


@app.put("/api/ai-settings", dependencies=[Depends(verify_token)])
async def update_ai_settings(req: AISettingsUpdate):
    if req.provider not in ("anthropic", "openai", "google"):
        raise HTTPException(400, "Invalid provider")
    result = db.upsert_ai_settings({
        "provider": req.provider, "api_key": req.api_key, "model_name": req.model_name,
    })
    result["api_key"] = "***configured***"
    return result


@app.get("/api/ai-models")
async def list_ai_models():
    return ai_client.MODELS


@app.get("/api/ai-tones")
async def list_ai_tones():
    return {k: v for k, v in ai_client.TONE_PRESETS.items()}


@app.get("/api/accounts/{account_id}/comment-tone", dependencies=[Depends(verify_token)])
async def get_tone(account_id: int):
    return db.get_comment_tone(account_id)


@app.put("/api/accounts/{account_id}/comment-tone", dependencies=[Depends(verify_token)])
async def update_tone(account_id: int, req: CommentToneUpdate):
    return db.upsert_comment_tone(account_id, {"tone_preset": req.tone_preset, "custom_tone": req.custom_tone})


@app.post("/api/accounts/{account_id}/comments/generate-replies", dependencies=[Depends(verify_token)])
async def generate_replies(account_id: int, req: AIGenerateRequest):
    """Generate AI replies for comments (runs in background)."""
    settings = db.get_ai_settings()
    if not settings:
        raise HTTPException(400, "AI not configured - set API key first")

    tone_data = db.get_comment_tone(account_id)
    tone = ai_client.get_tone_instructions(tone_data["tone_preset"], tone_data.get("custom_tone", ""))

    if req.comment_ids:
        targets = [db.get_comment(cid) for cid in req.comment_ids]
        targets = [c for c in targets if c and c["account_id"] == account_id]
    else:
        targets = db.get_comments(account_id, reply_status="no_reply", limit=50)

    if not targets:
        raise HTTPException(400, "No comments to process")

    job_id = str(uuid.uuid4())
    background_jobs[job_id] = {"type": "generate", "status": "running",
                                "progress": f"0/{len(targets)}", "result": None}

    def run_generate():
        generated = 0
        errors = 0
        for i, c in enumerate(targets):
            background_jobs[job_id]["progress"] = f"{i+1}/{len(targets)}"
            try:
                reply = ai_client.generate_reply(
                    settings["provider"], settings["api_key"], settings["model_name"],
                    c.get("video_title", ""), c.get("video_description", ""),
                    c["comment_text"], c.get("commenter_name", ""), tone)
                db.update_comment(c["id"], {
                    "reply_text": reply, "reply_status": "draft", "ai_generated": 1,
                })
                generated += 1
            except Exception as e:
                logger.error(f"AI generation error for comment {c['id']}: {e}")
                errors += 1
            time.sleep(0.5)  # Rate limit

        background_jobs[job_id] = {
            "type": "generate", "status": "done",
            "progress": f"Wygenerowano {generated}, błędów {errors}",
            "result": {"generated": generated, "errors": errors},
        }

    threading.Thread(target=run_generate, daemon=True).start()
    return {"job_id": job_id, "target_count": len(targets)}


# ── Comment Export/Import ──────────────────────────────────────────

@app.get("/api/accounts/{account_id}/comments/export", dependencies=[Depends(verify_token)])
async def export_comments(account_id: int, filter: str = "all"):
    from datetime import datetime as _dt
    comments = db.get_comments(account_id, reply_status="no_reply" if filter == "no_reply" else None, limit=10000)
    export = {
        "account_id": account_id,
        "exported_at": _dt.now().isoformat(),
        "count": len(comments),
        "comments": [{
            "platform_comment_id": c["platform_comment_id"],
            "platform": c["platform"],
            "video_title": c["video_title"],
            "video_url": c["video_url"],
            "commenter_name": c["commenter_name"],
            "comment_text": c["comment_text"],
            "comment_date": c["comment_date"],
            "reply_text": c.get("reply_text") or "",
        } for c in comments],
    }
    return JSONResponse(content=export, headers={
        "Content-Disposition": f"attachment; filename=comments_{account_id}_{_dt.now().strftime('%Y%m%d')}.json"
    })


@app.post("/api/accounts/{account_id}/comments/import", dependencies=[Depends(verify_token)])
async def import_comments(account_id: int, request: Request):
    """Import replies from JSON file."""
    body = await request.json()
    items = body.get("comments", [])
    updated = 0
    skipped = 0
    for item in items:
        reply = item.get("reply_text", "").strip()
        if not reply:
            skipped += 1
            continue
        cid = item.get("platform_comment_id")
        if not cid:
            skipped += 1
            continue
        # Find comment in DB
        comments = db.get_comments(account_id, limit=1)
        from database import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT id FROM comments WHERE account_id = ? AND platform_comment_id = ?",
                (account_id, cid)
            ).fetchone()
            if row:
                db.update_comment(row[0], {"reply_text": reply, "reply_status": "edited"})
                updated += 1
            else:
                skipped += 1
    return {"ok": True, "updated": updated, "skipped": skipped}


# ── Static Files (Dashboard) ────────────────────────────────────────

@app.get("/")
async def dashboard():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


# ── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8902, log_level="info")
