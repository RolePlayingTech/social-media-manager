"""
Social Media Manager - Scheduler
Automated publishing based on per-account schedules using APScheduler.
"""

import logging
import json
import os
import shutil
from datetime import datetime, date
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import database as db
import publisher

logger = logging.getLogger("scheduler")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")

TIMEZONE = os.environ.get("SMM_TIMEZONE", "Europe/Warsaw")
scheduler = BackgroundScheduler(timezone=TIMEZONE)
_active_jobs = {}


def process_account_publish(account_id: int):
    """Check if account has videos to publish and hasn't exceeded daily limit."""
    account = db.get_account(account_id)
    if not account or not account["active"]:
        return

    schedule = db.get_schedule(account_id)
    if not schedule or not schedule["enabled"]:
        return

    # Check day of week
    today_dow = date.today().strftime("%a").lower()[:3]
    allowed_days = schedule.get("day_of_week", "*")
    if allowed_days != "*":
        days = [d.strip().lower()[:3] for d in allowed_days.split(",")]
        if today_dow not in days:
            logger.info(f"Account {account_id}: skipping, {today_dow} not in {days}")
            return

    # Check daily limit
    published_today = db.count_published_today(account_id)
    max_per_day = schedule.get("max_per_day", 2)
    if published_today >= max_per_day:
        logger.info(f"Account {account_id}: daily limit reached ({published_today}/{max_per_day})")
        return

    # Get next video
    video = db.get_next_queued_video(account_id)
    if not video:
        logger.info(f"Account {account_id}: no queued videos")
        return

    logger.info(f"Account {account_id}: publishing video {video['id']} ({video['filename']})")
    do_publish(account, video)


def do_publish(account: dict, video: dict):
    """Execute the publishing process for a video."""
    video_path = os.path.join(UPLOAD_DIR, str(account["id"]), "queue", video["filename"])
    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        db.update_video(video["id"], {"status": "failed", "error_message": "File not found"})
        return

    # Mark as publishing
    db.update_video(video["id"], {"status": "publishing"})

    try:
        results = publisher.publish_video(account, video, video_path)
        all_success = all(r.get("success") for r in results.values()) if results else False

        update_data = {"published_at": datetime.now().isoformat()}

        if all_success:
            update_data["status"] = "published"
            # Extract platform-specific IDs
            if "instagram" in results:
                update_data["ig_media_id"] = results["instagram"].get("media_id")
                update_data["ig_permalink"] = results["instagram"].get("permalink")
            if "facebook" in results:
                update_data["fb_video_id"] = results["facebook"].get("video_id")
                update_data["fb_permalink"] = results["facebook"].get("permalink")
            if "youtube" in results:
                update_data["yt_video_id"] = results["youtube"].get("video_id")
                update_data["yt_url"] = results["youtube"].get("url")

            # Move to archive
            archive_dir = os.path.join(UPLOAD_DIR, str(account["id"]), "archive")
            os.makedirs(archive_dir, exist_ok=True)
            archive_path = os.path.join(archive_dir, video["filename"])
            shutil.move(video_path, archive_path)

            # Move caption and subtitle files too if they exist
            for ext in (".txt", ".srt"):
                extra_path = video_path.rsplit(".", 1)[0] + ext
                if os.path.exists(extra_path):
                    shutil.move(extra_path, os.path.join(archive_dir, os.path.basename(extra_path)))

            logger.info(f"Video {video['id']} published successfully")
        else:
            errors = "; ".join(
                f"{p}: {r.get('error', 'unknown')}" for p, r in results.items() if not r.get("success")
            )
            update_data["status"] = "failed"
            update_data["error_message"] = errors
            logger.error(f"Video {video['id']} publish failed: {errors}")

        db.update_video(video["id"], update_data)

        # Log results per platform
        for platform, result in results.items():
            db.add_publish_log({
                "video_id": video["id"],
                "account_id": account["id"],
                "platform": platform,
                "status": "success" if result.get("success") else "failed",
                "response_data": result,
                "error_message": result.get("error"),
            })

    except Exception as e:
        logger.error(f"Publishing error for video {video['id']}: {e}")
        db.update_video(video["id"], {
            "status": "failed",
            "error_message": str(e),
        })


def build_jobs():
    """Build scheduler jobs from database schedules."""
    global _active_jobs

    # Remove old jobs
    for job_id in list(_active_jobs.keys()):
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
    _active_jobs.clear()

    accounts = db.get_accounts()
    for account in accounts:
        if not account["active"]:
            continue
        schedule = db.get_schedule(account["id"])
        if not schedule or not schedule["enabled"]:
            continue

        publish_times = schedule.get("publish_times", [])
        if isinstance(publish_times, str):
            publish_times = json.loads(publish_times)

        for time_str in publish_times:
            try:
                hour, minute = time_str.split(":")
                job_id = f"publish_{account['id']}_{time_str.replace(':', '')}"
                scheduler.add_job(
                    process_account_publish,
                    CronTrigger(hour=int(hour), minute=int(minute), timezone=TIMEZONE),
                    args=[account["id"]],
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=300,
                )
                _active_jobs[job_id] = {
                    "account_id": account["id"],
                    "account_name": account["name"],
                    "time": time_str,
                }
                logger.info(f"Scheduled job {job_id}: account '{account['name']}' at {time_str}")
            except Exception as e:
                logger.error(f"Failed to schedule job for account {account['id']} at {time_str}: {e}")


def get_active_jobs():
    """Return list of currently scheduled jobs."""
    jobs = []
    for job_id, info in _active_jobs.items():
        job = scheduler.get_job(job_id)
        jobs.append({
            "job_id": job_id,
            "account_id": info["account_id"],
            "account_name": info["account_name"],
            "time": info["time"],
            "next_run": str(job.next_run_time) if job else None,
        })
    return jobs


def start():
    """Start the scheduler."""
    build_jobs()
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def stop():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def reload():
    """Reload jobs from database."""
    build_jobs()
    logger.info("Scheduler reloaded")
