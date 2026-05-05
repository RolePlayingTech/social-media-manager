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
    published_today = db.count_published_today(account_id, TIMEZONE)
    max_per_day = schedule.get("max_per_day", 2)
    if published_today >= max_per_day:
        logger.info(f"Account {account_id}: daily limit reached ({published_today}/{max_per_day})")
        return

    # Atomically claim next video (prevents double-publish race condition)
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

    # Status already set to 'publishing' by atomic claim in get_next_queued_video()

    try:
        results = publisher.publish_video(account, video, video_path)

        update_data = {"published_at": datetime.now().isoformat()}

        if not results:
            update_data["status"] = "failed"
            update_data["error_message"] = "No platforms configured for publishing"
            logger.error(f"Video {video['id']}: no platforms configured")
            db.update_video(video["id"], update_data)
            return

        # *_comment results are best-effort follow-ups — don't fail the whole publish if they error
        success_results = {k: v for k, v in results.items()
                           if k not in ("facebook_comment", "youtube_comment")}
        all_success = all(r.get("success") for r in success_results.values())

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
            if "facebook_comment" in results:
                cr = results["facebook_comment"]
                if cr.get("success"):
                    update_data["fb_comment_posted"] = 1
                    update_data["fb_comment_id"] = cr.get("comment_id")
                    update_data["fb_comment_error"] = None
                else:
                    update_data["fb_comment_posted"] = 0
                    update_data["fb_comment_error"] = cr.get("error", "")
            if "youtube_comment" in results:
                cr = results["youtube_comment"]
                if cr.get("success"):
                    update_data["yt_comment_posted"] = 1
                    update_data["yt_comment_id"] = cr.get("comment_id")
                    update_data["yt_comment_error"] = None
                else:
                    update_data["yt_comment_posted"] = 0
                    update_data["yt_comment_error"] = cr.get("error", "")

            # Move to archive (avoid overwriting existing files)
            archive_dir = os.path.join(UPLOAD_DIR, str(account["id"]), "archive")
            os.makedirs(archive_dir, exist_ok=True)
            archive_path = os.path.join(archive_dir, video["filename"])
            if os.path.exists(archive_path):
                base, ext = os.path.splitext(video["filename"])
                counter = 1
                while os.path.exists(archive_path):
                    archive_path = os.path.join(archive_dir, f"{base}_{counter}{ext}")
                    counter += 1
            shutil.move(video_path, archive_path)

            # Move caption and subtitle files too if they exist
            for ext in (".txt", ".srt"):
                extra_path = video_path.rsplit(".", 1)[0] + ext
                if os.path.exists(extra_path):
                    shutil.move(extra_path, os.path.join(archive_dir, os.path.basename(extra_path)))

            # Speed up for IG Stories if needed (instagram_facebook accounts only)
            if account.get("type") == "instagram_facebook":
                _speedup_video_to_60s(archive_path)

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


import subprocess as _subprocess


def _video_duration(path: str) -> float:
    """Return video duration in seconds using ffprobe, or 0 on error."""
    try:
        result = _subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _has_audio_stream(path: str) -> bool:
    try:
        r = _subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=10,
        )
        return bool(r.stdout.strip())
    except Exception:
        return False


IG_STORY_MAX_SECONDS = 59.0


def _speedup_video_to_60s(video_path: str) -> bool:
    """Speed up video in-place so duration ≤ 60s. Returns True on success."""
    duration = _video_duration(video_path)
    if duration <= IG_STORY_MAX_SECONDS:
        return True

    speed = duration / IG_STORY_MAX_SECONDS
    tmp_path = video_path + ".speedup_tmp.mp4"

    # Build atempo chain (each filter instance supports 0.5–2.0x)
    atempo_parts = []
    remaining = speed
    while remaining > 2.0:
        atempo_parts.append("atempo=2.0")
        remaining /= 2.0
    atempo_parts.append(f"atempo={remaining:.6f}")
    atempo_str = ",".join(atempo_parts)

    cmd = ["ffmpeg", "-y", "-i", video_path,
           "-vf", f"setpts=PTS/{speed:.6f}",
           "-c:v", "libx264", "-preset", "fast", "-crf", "23"]

    if _has_audio_stream(video_path):
        cmd += ["-af", atempo_str, "-c:a", "aac"]
    else:
        cmd += ["-an"]

    cmd.append(tmp_path)

    try:
        result = _subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"[speedup] ffmpeg failed for {os.path.basename(video_path)}: "
                         f"{result.stderr[-300:].decode(errors='replace')}")
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return False
        os.replace(tmp_path, video_path)
        new_dur = _video_duration(video_path)
        logger.info(f"[speedup] {os.path.basename(video_path)}: {duration:.1f}s → {new_dur:.1f}s ({speed:.2f}x)")
        return True
    except Exception as e:
        logger.error(f"[speedup] error for {video_path}: {e}")
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return False


def speedup_archive(account_id: int):
    """Speed up all archive videos > 60s for this account (runs in background thread)."""
    archive_dir = os.path.join(UPLOAD_DIR, str(account_id), "archive")
    if not os.path.isdir(archive_dir):
        return
    files = [f for f in os.listdir(archive_dir) if f.lower().endswith((".mp4", ".mov"))]
    for fn in files:
        path = os.path.join(archive_dir, fn)
        dur = _video_duration(path)
        if dur > IG_STORY_MAX_SECONDS:
            logger.info(f"[speedup] batch: {fn} {dur:.1f}s — processing…")
            _speedup_video_to_60s(path)


def pick_story_video(account_id: int, schedule: dict) -> tuple:
    """Return (video_path, filename) for a story, or (None, None) if nothing available."""
    import random
    source = schedule.get("story_source", "archive")

    if source == "queue_skip":
        skip = schedule.get("story_queue_skip", 5)
        candidates = db.get_story_candidates_queue(account_id, skip)
        if not candidates:
            logger.info(f"[story] account {account_id}: no queue candidates (skip={skip})")
            return None, None
        # Speedup any oversized candidates on the fly
        valid = []
        for c in candidates:
            p = os.path.join(UPLOAD_DIR, str(account_id), "queue", c["filename"])
            if not os.path.exists(p):
                continue
            if _video_duration(p) > IG_STORY_MAX_SECONDS:
                _speedup_video_to_60s(p)
            valid.append(c)
        if not valid:
            return None, None
        chosen = random.choice(valid)
        return os.path.join(UPLOAD_DIR, str(account_id), "queue", chosen["filename"]), chosen["filename"]

    # Default: archive — all files should be pre-processed, speedup as fallback
    filenames = db.get_story_candidate_archive(account_id)
    if not filenames:
        logger.info(f"[story] account {account_id}: archive empty")
        return None, None
    for fn in filenames:
        p = os.path.join(UPLOAD_DIR, str(account_id), "archive", fn)
        if _video_duration(p) > IG_STORY_MAX_SECONDS:
            _speedup_video_to_60s(p)
    filename = random.choice(filenames)
    video_path = os.path.join(UPLOAD_DIR, str(account_id), "archive", filename)
    return video_path, filename


def _delete_story_file(video_path: str):
    """Delete a story video and its .txt sidecar after publishing."""
    for path in (video_path, video_path.rsplit(".", 1)[0] + ".txt"):
        if os.path.exists(path):
            try:
                os.unlink(path)
                logger.info(f"[story] deleted: {path}")
            except OSError as e:
                logger.warning(f"[story] could not delete {path}: {e}")


def process_account_story(account_id: int):
    """Post one story for this account (called per story_times slot)."""
    account = db.get_account(account_id)
    if not account or not account["active"]:
        return

    schedule = db.get_schedule(account_id)
    if not schedule or not schedule.get("story_enabled"):
        return

    stories_today = db.count_stories_today(account_id, TIMEZONE)
    max_stories = len(schedule.get("story_times") or [])
    if stories_today >= max_stories:
        logger.info(f"[story] account {account_id}: daily story limit reached ({stories_today}/{max_stories})")
        return

    video_path, filename = pick_story_video(account_id, schedule)
    if not video_path:
        return

    logger.info(f"[story] account {account_id} '{account.get('name')}': posting IG story from {filename}")

    if not account.get("ig_user_id") or not account.get("fb_access_token"):
        logger.warning(f"[story] account {account_id}: no IG user_id configured")
        return

    subdir = "queue" if schedule.get("story_source") == "queue_skip" else "archive"
    video_url = publisher.get_video_url_for_api(account_id, filename, subdir=subdir)
    if not video_url:
        logger.error(f"[story] account {account_id}: tmpfiles upload failed for IG story")
        return

    result = publisher.publish_story_to_instagram(
        account["fb_access_token"], account["ig_user_id"], video_url
    )
    ig_ok = result.get("success", False)
    db.add_publish_log({
        "video_id": None, "account_id": account_id,
        "platform": "ig_story",
        "status": "success" if ig_ok else "failed",
        "response_data": result,
        "error_message": result.get("error"),
    })
    logger.info(f"[story] IG {'OK' if ig_ok else 'FAIL'}: {result.get('error', '')}")

    if ig_ok:
        _delete_story_file(video_path)


def check_film_publishes():
    """Check for films due for publishing (runs every minute)."""
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M")

    for platform in ("fb", "yt"):
        due_films = db.get_films_due_for_publish(platform, now)
        if due_films:
            logger.info(f"[films:{platform}] {len(due_films)} due at {now}: "
                        f"{[(f['id'], f.get('title','')[:40]) for f in due_films]}")
        for film in due_films:
            # Completeness check before publishing
            ready = db.film_is_ready_fb(film) if platform == "fb" else db.film_is_ready_yt(film)
            if not ready:
                missing = []
                if not (film.get("title") or "").strip(): missing.append("tytuł")
                if platform == "fb" and not (film.get("fb_description") or "").strip(): missing.append("opis FB")
                if platform == "yt" and not (film.get("yt_description") or "").strip(): missing.append("opis YT")
                if not film.get("subtitle_filename"): missing.append("plik SRT")
                if not film.get("thumbnail_filename"): missing.append("miniaturka")
                err = "Brak wymaganych pól: " + ", ".join(missing)
                logger.error(f"[films:{platform}] film {film['id']} niekompletny — {err}")
                db.update_film(film["id"], {f"{platform}_status": "draft", f"{platform}_error": err})
                continue

            account_key = f"{platform}_account_id"
            account = db.get_account(film[account_key])
            if not account:
                logger.error(f"[films:{platform}] film {film['id']}: account_id={film[account_key]} not found")
                db.update_film(film["id"], {f"{platform}_status": "failed", f"{platform}_error": "Account not found"})
                continue

            video_filename = film.get("video_filename") or ""
            if not video_filename:
                logger.error(f"[films:{platform}] film {film['id']}: empty video_filename in DB")
                db.update_film(film["id"], {f"{platform}_status": "failed",
                                            f"{platform}_error": "Empty video_filename in DB (upload was incomplete)"})
                continue

            db.update_film(film["id"], {f"{platform}_status": "publishing"})
            film_dir = os.path.join(UPLOAD_DIR, "films", str(film["id"]))
            video_path = os.path.join(film_dir, video_filename)
            thumb_path = os.path.join(film_dir, film["thumbnail_filename"]) if film.get("thumbnail_filename") else None
            srt_path = os.path.join(film_dir, film["subtitle_filename"]) if film.get("subtitle_filename") else None

            if not os.path.exists(video_path):
                logger.error(f"[films:{platform}] film {film['id']}: video file not found at {video_path}")
                db.update_film(film["id"], {f"{platform}_status": "failed",
                                            f"{platform}_error": f"Video file not found: {video_path}"})
                continue

            logger.info(f"[films:{platform}] film {film['id']} '{film.get('title','')[:60]}': "
                        f"publishing on '{account.get('name')}' (acc {account['id']}) — file={video_filename}")

            try:
                if platform == "fb":
                    result = publisher.publish_film_to_facebook(
                        account["fb_access_token"], account["fb_page_id"],
                        video_path, film.get("fb_description", ""),
                        subtitle_path=srt_path,
                        thumbnail_path=thumb_path
                    )
                else:
                    import json as _json
                    tags = _json.loads(film.get("yt_tags", "[]")) if isinstance(film.get("yt_tags"), str) else film.get("yt_tags", [])
                    result = publisher.publish_film_to_youtube(
                        account["yt_client_id"], account["yt_client_secret"], account["yt_refresh_token"],
                        video_path, film.get("title", ""), film.get("yt_description", ""),
                        tags=tags, category=film.get("yt_category", "22"),
                        privacy=film.get("yt_privacy", "public"),
                        thumbnail_path=thumb_path, subtitle_path=srt_path
                    )

                if result.get("success"):
                    update = {f"{platform}_status": "published",
                              f"{platform}_published_at": datetime.now().isoformat(),
                              f"{platform}_error": None}
                    if platform == "fb":
                        update["fb_video_id"] = result.get("video_id")
                        update["fb_permalink"] = result.get("permalink")
                        link = result.get("permalink")
                    else:
                        update["yt_video_id"] = result.get("video_id")
                        update["yt_url"] = result.get("url")
                        link = result.get("url")
                    db.update_film(film["id"], update)
                    logger.info(f"[films:{platform}] film {film['id']} PUBLISHED on '{account.get('name')}' → {link}")
                else:
                    err = result.get("error", "Unknown error")
                    logger.error(f"[films:{platform}] film {film['id']} FAILED on '{account.get('name')}': {err}")
                    db.update_film(film["id"], {f"{platform}_status": "failed", f"{platform}_error": err})

                db.add_publish_log({
                    "video_id": None,
                    "account_id": account["id"],
                    "platform": "youtube" if platform == "yt" else "facebook",
                    "status": "success" if result.get("success") else "failed",
                    "response_data": result,
                    "error_message": result.get("error"),
                })

            except Exception as e:
                logger.error(f"Film {film['id']} publish error ({platform}): {e}")
                db.update_film(film["id"], {f"{platform}_status": "failed", f"{platform}_error": str(e)})

            logger.info(f"Film {film['id']} {platform} publish: {'ok' if result.get('success') else result.get('error', 'failed')}")


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

    # Film publisher - check every minute for films due to publish
    scheduler.add_job(
        check_film_publishes,
        CronTrigger(minute="*", timezone=TIMEZONE),
        id="film_publisher",
        replace_existing=True,
        misfire_grace_time=120,
    )
    _active_jobs["film_publisher"] = {
        "account_id": None,
        "account_name": "Filmy",
        "time": "co 1 min",
    }

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

        # Story jobs (only for instagram_facebook accounts with story_enabled)
        if account.get("type") == "instagram_facebook" and schedule.get("story_enabled"):
            story_times = schedule.get("story_times", [])
            if isinstance(story_times, str):
                story_times = json.loads(story_times)
            for time_str in story_times:
                try:
                    hour, minute = time_str.split(":")
                    job_id = f"story_{account['id']}_{time_str.replace(':', '')}"
                    scheduler.add_job(
                        process_account_story,
                        CronTrigger(hour=int(hour), minute=int(minute), timezone=TIMEZONE),
                        args=[account["id"]],
                        id=job_id,
                        replace_existing=True,
                        misfire_grace_time=300,
                    )
                    _active_jobs[job_id] = {
                        "account_id": account["id"],
                        "account_name": account["name"],
                        "time": f"relacja {time_str}",
                    }
                    logger.info(f"Scheduled story job {job_id}: account '{account['name']}' at {time_str}")
                except Exception as e:
                    logger.error(f"Failed to schedule story job for account {account['id']} at {time_str}: {e}")


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


def _run_batch_speedup():
    """Background thread: speed up all long archive videos for ig_fb accounts."""
    import threading
    def _worker():
        accounts = db.get_accounts()
        for acc in accounts:
            if acc.get("type") == "instagram_facebook" and acc.get("active"):
                speedup_archive(acc["id"])
    t = threading.Thread(target=_worker, daemon=True, name="archive-speedup")
    t.start()


def start():
    """Start the scheduler."""
    build_jobs()
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")
    _run_batch_speedup()


def stop():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def reload():
    """Reload jobs from database."""
    build_jobs()
    logger.info("Scheduler reloaded")
