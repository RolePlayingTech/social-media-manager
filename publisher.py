"""
Social Media Manager - Publisher
Handles publishing videos to Instagram, Facebook, and YouTube.
"""

import httpx
import os
import json
import time
import logging
from datetime import datetime

logger = logging.getLogger("publisher")

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
TMPFILES_UPLOAD_URL = "https://tmpfiles.org/api/v1/upload"


def get_video_path(account_id: int, filename: str, subdir: str = "queue") -> str:
    return os.path.join(UPLOAD_DIR, str(account_id), subdir, filename)


def get_video_url_for_api(account_id: int, filename: str, subdir: str = "queue") -> str | None:
    """Upload video to tmpfiles.org and return URL for API consumption."""
    path = get_video_path(account_id, filename, subdir)
    if not os.path.exists(path):
        logger.error(f"Video file not found: {path}")
        return None
    try:
        with open(path, "rb") as f:
            resp = httpx.post(
                TMPFILES_UPLOAD_URL,
                files={"file": (filename, f, "video/mp4")},
                timeout=300,
            )
        if resp.status_code == 200:
            data = resp.json()
            url = data.get("data", {}).get("url", "")
            # Convert tmpfiles.org page URL to direct download URL
            if "tmpfiles.org/" in url:
                url = url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
            logger.info(f"Uploaded to tmpfiles: {url}")
            return url
        logger.error(f"tmpfiles upload failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"tmpfiles upload error: {e}")
    return None


# ── Instagram Publishing ────────────────────────────────────────────

def fetch_ig_account_info(access_token: str, ig_user_id: str = None) -> dict:
    """Fetch Instagram account info from Graph API. If ig_user_id is not provided, discover it."""
    result = {}
    try:
        with httpx.Client(timeout=30) as client:
            if not ig_user_id:
                # Get pages linked to the token
                pages_resp = client.get(f"{GRAPH_API_BASE}/me/accounts", params={
                    "access_token": access_token,
                    "fields": "id,name,instagram_business_account,followers_count",
                })
                pages_data = pages_resp.json()
                if "data" in pages_data and len(pages_data["data"]) > 0:
                    page = pages_data["data"][0]
                    result["fb_page_id"] = page["id"]
                    result["fb_page_name"] = page.get("name", "")
                    result["fb_followers"] = page.get("followers_count", 0)
                    ig_biz = page.get("instagram_business_account", {})
                    ig_user_id = ig_biz.get("id")

            if ig_user_id:
                ig_resp = client.get(f"{GRAPH_API_BASE}/{ig_user_id}", params={
                    "access_token": access_token,
                    "fields": "id,username,name,profile_picture_url,followers_count,media_count",
                })
                ig_data = ig_resp.json()
                result["ig_user_id"] = ig_data.get("id", ig_user_id)
                result["ig_username"] = ig_data.get("username", "")
                result["ig_profile_pic"] = ig_data.get("profile_picture_url", "")
                result["ig_followers"] = ig_data.get("followers_count", 0)
                result["ig_media_count"] = ig_data.get("media_count", 0)

            # Also get FB page info if we have it
            if result.get("fb_page_id") and not result.get("fb_page_name"):
                fb_resp = client.get(f"{GRAPH_API_BASE}/{result['fb_page_id']}", params={
                    "access_token": access_token,
                    "fields": "name,followers_count",
                })
                fb_data = fb_resp.json()
                result["fb_page_name"] = fb_data.get("name", "")
                result["fb_followers"] = fb_data.get("followers_count", 0)

    except Exception as e:
        logger.error(f"Error fetching IG account info: {e}")
        result["error"] = str(e)
    return result


def publish_to_instagram(access_token: str, ig_user_id: str, video_url: str, caption: str, is_trial: bool = False) -> dict:
    """Publish a Reel to Instagram using the Content Publishing API."""
    IG_CAPTION_LIMIT = 2200
    if caption and len(caption) > IG_CAPTION_LIMIT:
        truncated = caption[:IG_CAPTION_LIMIT]
        # Try to cut at the last sentence boundary
        last_dot = truncated.rfind('. ')
        if last_dot > IG_CAPTION_LIMIT // 2:
            truncated = truncated[:last_dot + 1]
        caption = truncated
        logger.info(f"IG caption truncated from {len(caption)} to {len(truncated)} chars")
    try:
        with httpx.Client(timeout=300) as client:
            # Step 1: Create media container
            container_data = {
                "access_token": access_token,
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
            }
            if is_trial:
                container_data["trial_params"] = json.dumps({"graduation_strategy": "SS_PERFORMANCE"})
                logger.info("Publishing as trial reel (SS_PERFORMANCE)")
            create_resp = client.post(f"{GRAPH_API_BASE}/{ig_user_id}/media", data=container_data)
            create_data = create_resp.json()
            if "id" not in create_data:
                return {"success": False, "error": f"Container creation failed: {json.dumps(create_data)}"}

            container_id = create_data["id"]
            logger.info(f"IG container created: {container_id}")

            # Step 2: Wait for processing
            for attempt in range(60):  # max 5 minutes
                status_resp = client.get(f"{GRAPH_API_BASE}/{container_id}", params={
                    "access_token": access_token,
                    "fields": "status_code,status",
                })
                status_data = status_resp.json()
                status_code = status_data.get("status_code", "")

                if status_code == "FINISHED":
                    break
                elif status_code == "ERROR":
                    return {"success": False, "error": f"Processing failed: {status_data.get('status', '')}"}
                time.sleep(5)
            else:
                return {"success": False, "error": "Processing timeout"}

            # Step 3: Publish
            publish_resp = client.post(f"{GRAPH_API_BASE}/{ig_user_id}/media_publish", data={
                "access_token": access_token,
                "creation_id": container_id,
            })
            publish_data = publish_resp.json()
            if "id" not in publish_data:
                return {"success": False, "error": f"Publish failed: {json.dumps(publish_data)}"}

            media_id = publish_data["id"]

            # Get permalink
            media_resp = client.get(f"{GRAPH_API_BASE}/{media_id}", params={
                "access_token": access_token,
                "fields": "permalink",
            })
            permalink = media_resp.json().get("permalink", "")

            return {
                "success": True,
                "media_id": media_id,
                "permalink": permalink,
            }

    except Exception as e:
        logger.error(f"Instagram publish error: {e}")
        return {"success": False, "error": str(e)}


def publish_story_to_instagram(access_token: str, ig_user_id: str, video_url: str) -> dict:
    """Publish a Story to Instagram."""
    try:
        with httpx.Client(timeout=300) as client:
            create_resp = client.post(f"{GRAPH_API_BASE}/{ig_user_id}/media", data={
                "access_token": access_token,
                "media_type": "STORIES",
                "video_url": video_url,
            })
            create_data = create_resp.json()
            if "id" not in create_data:
                return {"success": False, "error": f"Story container failed: {json.dumps(create_data)}"}

            container_id = create_data["id"]

            for attempt in range(60):
                status_resp = client.get(f"{GRAPH_API_BASE}/{container_id}", params={
                    "access_token": access_token,
                    "fields": "status_code",
                })
                if status_resp.json().get("status_code") == "FINISHED":
                    break
                elif status_resp.json().get("status_code") == "ERROR":
                    return {"success": False, "error": "Story processing failed"}
                time.sleep(5)
            else:
                return {"success": False, "error": "Story processing timeout"}

            publish_resp = client.post(f"{GRAPH_API_BASE}/{ig_user_id}/media_publish", data={
                "access_token": access_token,
                "creation_id": container_id,
            })
            publish_data = publish_resp.json()
            if "id" not in publish_data:
                return {"success": False, "error": f"Story publish failed: {json.dumps(publish_data)}"}

            return {"success": True, "media_id": publish_data["id"]}

    except Exception as e:
        return {"success": False, "error": str(e)}


def publish_story_to_facebook(access_token: str, page_id: str, video_path: str) -> dict:
    """Publish a photo story to a Facebook Page (extracted frame from video).
    Note: FB video story upload (rupload.facebook.com) requires special app access
    not available here; we use a photo story extracted from the video frame instead."""
    import tempfile, subprocess as _sp
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.get(f"{GRAPH_API_BASE}/{page_id}", params={
                "access_token": access_token,
                "fields": "access_token",
            })
            page_token = resp.json().get("access_token", access_token)

        # Extract a frame at 5 seconds (or start of video)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            thumb_path = tf.name
        _sp.run(
            ["ffmpeg", "-y", "-ss", "5", "-i", video_path,
             "-vframes", "1", "-q:v", "2", thumb_path],
            capture_output=True, timeout=30,
        )
        if not os.path.exists(thumb_path) or os.path.getsize(thumb_path) == 0:
            return {"success": False, "error": "Could not extract frame from video for FB photo story"}

        try:
            with httpx.Client(timeout=60) as client:
                # Upload photo (unpublished)
                with open(thumb_path, "rb") as f:
                    r = client.post(f"{GRAPH_API_BASE}/{page_id}/photos", data={
                        "access_token": page_token,
                        "published": "false",
                    }, files={"source": ("frame.jpg", f, "image/jpeg")})
                photo_data = r.json()
                photo_id = photo_data.get("id")
                if not photo_id:
                    return {"success": False, "error": f"FB photo upload failed: {json.dumps(photo_data)}"}

                # Create photo story
                r2 = client.post(f"{GRAPH_API_BASE}/{page_id}/photo_stories", data={
                    "access_token": page_token,
                    "photo_id": photo_id,
                })
                result = r2.json()
                if not result.get("success"):
                    return {"success": False, "error": f"FB photo story failed: {json.dumps(result)}"}

                logger.info(f"FB photo story published: post_id={result.get('post_id')}")
                return {"success": True, "post_id": result.get("post_id")}
        finally:
            try:
                os.unlink(thumb_path)
            except OSError:
                pass

    except Exception as e:
        logger.error(f"FB photo story error: {e}")
        return {"success": False, "error": str(e)}


# ── Facebook Publishing ─────────────────────────────────────────────

def _publish_to_facebook_resumable(page_token: str, page_id: str, video_path: str, description: str) -> dict:
    """Resumable upload for large FB videos (>~50MB). Uses upload_phase=start/transfer/finish."""
    file_size = os.path.getsize(video_path)
    endpoint = f"{GRAPH_API_BASE}/{page_id}/videos"

    with httpx.Client(timeout=600) as client:
        # 1. start
        r = client.post(endpoint, data={
            "access_token": page_token,
            "upload_phase": "start",
            "file_size": str(file_size),
        })
        start = r.json()
        if "upload_session_id" not in start:
            return {"success": False, "error": f"FB resumable start failed: {json.dumps(start)}"}
        session_id = start["upload_session_id"]
        video_id = start.get("video_id")
        start_off = int(start["start_offset"])
        end_off = int(start["end_offset"])
        logger.info(f"FB resumable start: session={session_id} video_id={video_id} chunks=~{file_size}B")

        # 2. transfer chunks
        with open(video_path, "rb") as f:
            while start_off < end_off:
                f.seek(start_off)
                chunk = f.read(end_off - start_off)
                files = {"video_file_chunk": ("chunk", chunk, "application/octet-stream")}
                r = client.post(endpoint, data={
                    "access_token": page_token,
                    "upload_phase": "transfer",
                    "upload_session_id": session_id,
                    "start_offset": str(start_off),
                }, files=files)
                t = r.json()
                if "start_offset" not in t or "end_offset" not in t:
                    return {"success": False, "error": f"FB resumable transfer failed at {start_off}: {json.dumps(t)}"}
                new_start = int(t["start_offset"])
                new_end = int(t["end_offset"])
                logger.debug(f"FB resumable chunk: {start_off}..{end_off} → next {new_start}..{new_end}")
                if new_start == new_end:
                    break
                start_off, end_off = new_start, new_end
        logger.info(f"FB resumable: all chunks uploaded ({file_size} bytes), finalizing…")

        # 3. finish
        r = client.post(endpoint, data={
            "access_token": page_token,
            "upload_phase": "finish",
            "upload_session_id": session_id,
            "description": description or "",
        })
        fin = r.json()
        if not fin.get("success"):
            return {"success": False, "error": f"FB resumable finish failed: {json.dumps(fin)}"}

        return {
            "success": True,
            "video_id": video_id,
            "permalink": f"https://www.facebook.com/{page_id}/videos/{video_id}",
        }


# Use resumable for any video > 40 MB to be safe (FB rejects ~100MB+ via simple POST)
RESUMABLE_THRESHOLD = 40 * 1024 * 1024


def publish_to_facebook(access_token: str, page_id: str, video_path: str, description: str) -> dict:
    """Publish a video to Facebook Page. Uses resumable upload for large files."""
    import subprocess
    import tempfile
    try:
        # Get Page Access Token
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{GRAPH_API_BASE}/{page_id}", params={
                "access_token": access_token,
                "fields": "access_token",
            })
            page_token = resp.json().get("access_token", access_token)

        # Large videos must go through the resumable upload protocol — FB returns 413 otherwise.
        if os.path.getsize(video_path) >= RESUMABLE_THRESHOLD:
            logger.info(f"FB upload: using resumable protocol (size={os.path.getsize(video_path)})")
            return _publish_to_facebook_resumable(page_token, page_id, video_path, description)

        # Small videos: simple non-resumable POST via curl
        safe_desc = (description or "").replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".curl", delete=False) as cf:
            cf.write(f'-F "access_token={page_token}"\n')
            cf.write(f'-F "description={safe_desc}"\n')
            cf.write(f'-F "source=@{video_path};type=video/mp4"\n')
            config_path = cf.name

        try:
            result = subprocess.run([
                "curl", "-s", "--show-error",
                "-K", config_path,
                f"{GRAPH_API_BASE}/{page_id}/videos",
            ], capture_output=True, text=True, timeout=300)
        finally:
            os.remove(config_path)

        logger.info(f"FB curl rc={result.returncode} stdout={result.stdout[:600]!r} stderr={result.stderr[:600]!r}")

        data = json.loads(result.stdout) if result.stdout.strip() else {}
        if not data:
            return {"success": False,
                    "error": f"FB upload returned no body (curl rc={result.returncode}, stderr={result.stderr[:200] or 'empty'})"}

        if "id" in data:
            return {
                "success": True,
                "video_id": data["id"],
                "permalink": f"https://www.facebook.com/{page_id}/videos/{data['id']}",
            }

        error = data.get("error", {})
        if error.get("code") == 1:
            logger.warning(f"FB returned rate-limit error — upload may have succeeded")
            return {
                "success": True,
                "video_id": "pending",
                "permalink": f"https://www.facebook.com/{page_id}/videos/",
            }

        return {"success": False, "error": f"FB publish failed: {json.dumps(data)}"}

    except Exception as e:
        logger.error(f"Facebook publish error: {e}")
        return {"success": False, "error": str(e)}


def post_fb_video_comment(access_token: str, page_id: str, video_id: str, message: str) -> dict:
    """Post a comment under a freshly-published Facebook video, using a Page token."""
    try:
        with httpx.Client(timeout=30) as client:
            pt_resp = client.get(f"{GRAPH_API_BASE}/{page_id}", params={
                "access_token": access_token, "fields": "access_token",
            })
            page_token = pt_resp.json().get("access_token", access_token)

            # Wait briefly for the video object to become available for comments
            for attempt in range(6):
                resp = client.post(f"{GRAPH_API_BASE}/{video_id}/comments", data={
                    "access_token": page_token,
                    "message": message,
                })
                data = resp.json()
                if "id" in data:
                    return {"success": True, "comment_id": data["id"]}
                err = data.get("error", {}) or {}
                # 100 / not-yet-published — back off and retry
                if err.get("code") in (100, 1, 2) and attempt < 5:
                    time.sleep(5 * (attempt + 1))
                    continue
                return {"success": False, "error": err.get("message") or json.dumps(data)}
        return {"success": False, "error": "Comment post: out of retries"}
    except Exception as e:
        logger.error(f"FB comment post error: {e}")
        return {"success": False, "error": str(e)}


def fetch_fb_page_info(access_token: str) -> dict:
    """Fetch Facebook page info."""
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{GRAPH_API_BASE}/me/accounts", params={
                "access_token": access_token,
                "fields": "id,name,followers_count,fan_count,picture",
            })
            data = resp.json()
            if "data" in data and len(data["data"]) > 0:
                page = data["data"][0]
                return {
                    "fb_page_id": page["id"],
                    "fb_page_name": page.get("name", ""),
                    "fb_followers": page.get("followers_count", page.get("fan_count", 0)),
                }
    except Exception as e:
        logger.error(f"Error fetching FB page info: {e}")
    return {}


# ── YouTube Publishing ──────────────────────────────────────────────

def fetch_yt_channel_info(client_id: str, client_secret: str, refresh_token: str) -> dict:
    """Fetch YouTube channel info using OAuth2 credentials."""
    try:
        # Get access token from refresh token
        with httpx.Client(timeout=30) as client:
            token_resp = client.post("https://oauth2.googleapis.com/token", data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            })
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                return {"error": f"Token refresh failed: {json.dumps(token_data)}"}

            # Get channel info
            ch_resp = client.get("https://www.googleapis.com/youtube/v3/channels", params={
                "part": "snippet,statistics",
                "mine": "true",
            }, headers={"Authorization": f"Bearer {access_token}"})
            ch_data = ch_resp.json()
            if "items" in ch_data and len(ch_data["items"]) > 0:
                channel = ch_data["items"][0]
                snippet = channel.get("snippet", {})
                stats = channel.get("statistics", {})
                return {
                    "yt_channel_id": channel["id"],
                    "yt_channel_name": snippet.get("title", ""),
                    "yt_channel_pic": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                    "yt_subscribers": int(stats.get("subscriberCount", 0)),
                    "yt_video_count": int(stats.get("videoCount", 0)),
                }
    except Exception as e:
        logger.error(f"Error fetching YT channel info: {e}")
    return {"error": "Failed to fetch channel info"}


def _get_yt_access_token(client_id: str, client_secret: str, refresh_token: str) -> str | None:
    """Get a fresh YouTube access token from refresh token."""
    with httpx.Client(timeout=30) as client:
        resp = client.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        data = resp.json()
        if "error" in data:
            logger.error(f"YouTube token refresh failed: {data.get('error')} - {data.get('error_description', '')}")
            return None
        return data.get("access_token")


def publish_to_youtube(client_id: str, client_secret: str, refresh_token: str,
                       video_path: str, title: str, description: str,
                       tags: list = None, category: str = "22",
                       privacy: str = "public", is_short: bool = False,
                       subtitle_path: str = None) -> dict:
    """Upload a video to YouTube using resumable upload, optionally with SRT subtitles."""
    try:
        access_token = _get_yt_access_token(client_id, client_secret, refresh_token)
        if not access_token:
            return {"success": False, "error": "Token refresh failed"}

        if is_short and "#Shorts" not in title:
            title = f"{title} #Shorts"

        # YouTube limits: title 100 chars, description 5000 chars
        if len(title) > 100:
            title = title[:97] + "..."
        if description and len(description) > 5000:
            description = description[:4990] + "\n..."

        metadata = {
            "snippet": {
                "title": title,
                "description": description or "",
                "tags": tags or [],
                "categoryId": category,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        file_size = os.path.getsize(video_path)

        with httpx.Client(timeout=600) as client:
            # Step 1: Initialize resumable upload
            init_resp = client.post(
                "https://www.googleapis.com/upload/youtube/v3/videos",
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(file_size),
                },
                content=json.dumps(metadata),
            )
            upload_url = init_resp.headers.get("Location")
            if not upload_url:
                return {"success": False, "error": f"Init failed: {init_resp.text}"}

            # Step 2: Upload video file
            with open(video_path, "rb") as f:
                upload_resp = client.put(
                    upload_url,
                    content=f.read(),
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "video/mp4",
                        "Content-Length": str(file_size),
                    },
                )
            upload_data = upload_resp.json()
            if "id" not in upload_data:
                return {"success": False, "error": f"Upload failed: {json.dumps(upload_data)}"}

            video_id = upload_data["id"]

            # Step 3: Upload subtitles if provided
            subtitle_uploaded = False
            if subtitle_path and os.path.exists(subtitle_path):
                try:
                    subtitle_uploaded = upload_youtube_subtitles(
                        access_token, video_id, subtitle_path
                    )
                except Exception as e:
                    logger.warning(f"Subtitle upload failed for {video_id}: {e}")

            return {
                "success": True,
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "subtitles": subtitle_uploaded,
            }

    except Exception as e:
        logger.error(f"YouTube publish error: {e}")
        return {"success": False, "error": str(e)}


def post_yt_video_comment(client_id: str, client_secret: str, refresh_token: str,
                           video_id: str, message: str) -> dict:
    """Post a top-level comment under a YouTube video as the channel owner."""
    try:
        access_token = _get_yt_access_token(client_id, client_secret, refresh_token)
        if not access_token:
            return {"success": False, "error": "Token refresh failed"}
        # YouTube needs a brief delay after upload before commenting works
        for attempt in range(6):
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    "https://www.googleapis.com/youtube/v3/commentThreads",
                    params={"part": "snippet"},
                    headers={"Authorization": f"Bearer {access_token}",
                             "Content-Type": "application/json"},
                    json={"snippet": {
                        "videoId": video_id,
                        "topLevelComment": {"snippet": {"textOriginal": message}},
                    }},
                )
                data = resp.json()
                if "id" in data:
                    return {"success": True, "comment_id": data["id"]}
                err = data.get("error", {}) or {}
                # videoNotFound is transient right after upload
                code = err.get("code")
                msg = err.get("message", "")
                if (code == 404 or "video" in msg.lower()) and attempt < 5:
                    time.sleep(10 * (attempt + 1))
                    continue
                return {"success": False, "error": msg or json.dumps(data)}
        return {"success": False, "error": "YouTube comment: out of retries"}
    except Exception as e:
        logger.error(f"YouTube comment post error: {e}")
        return {"success": False, "error": str(e)}


def upload_youtube_subtitles(access_token: str, video_id: str, srt_path: str,
                              language: str = "en", name: str = "English") -> bool:
    """Upload SRT subtitles to a YouTube video via Captions API."""
    with open(srt_path, "rb") as f:
        srt_content = f.read()

    with httpx.Client(timeout=60) as client:
        metadata = json.dumps({
            "snippet": {
                "videoId": video_id,
                "language": language,
                "name": name,
                "isDraft": False,
            }
        })
        # Multipart upload: metadata + SRT file
        body = (b"--boundary\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                + metadata.encode()
                + b"\r\n--boundary\r\nContent-Type: application/x-subrip\r\n\r\n"
                + srt_content
                + b"\r\n--boundary--")
        resp = client.post(
            "https://www.googleapis.com/upload/youtube/v3/captions",
            params={"uploadType": "multipart", "part": "snippet"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "multipart/related; boundary=boundary",
            },
            content=body,
        )
        if resp.status_code == 200:
            logger.info(f"Subtitles uploaded for video {video_id}")
            return True
        else:
            logger.warning(f"Subtitle upload returned {resp.status_code}: {resp.text[:200]}")
            return False


# ── YouTube Thumbnail ──────────────────────────────────────────────

def upload_youtube_thumbnail(access_token: str, video_id: str, thumbnail_path: str) -> bool:
    """Upload a custom thumbnail for a YouTube video."""
    try:
        with open(thumbnail_path, "rb") as f:
            thumb_data = f.read()
        content_type = "image/png" if thumbnail_path.lower().endswith(".png") else "image/jpeg"
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
                params={"videoId": video_id, "uploadType": "media"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": content_type,
                },
                content=thumb_data,
            )
            if resp.status_code == 200:
                logger.info(f"Thumbnail uploaded for video {video_id}")
                return True
            else:
                logger.warning(f"Thumbnail upload returned {resp.status_code}: {resp.text[:200]}")
                return False
    except Exception as e:
        logger.warning(f"Thumbnail upload error for {video_id}: {e}")
        return False


# ── Facebook Captions ──────────────────────────────────────────────

def upload_facebook_captions(access_token: str, video_id: str, srt_path: str, locale: str = "pl_PL") -> bool:
    """Upload SRT captions to a Facebook video."""
    try:
        with open(srt_path, "rb") as f:
            srt_data = f.read()
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{GRAPH_API_BASE}/{video_id}/captions",
                data={"access_token": access_token, "locale": locale, "default": "true"},
                files={"captions_file": (f"captions.{locale}.srt", srt_data, "text/plain")},
            )
            if resp.status_code == 200:
                logger.info(f"FB captions uploaded for video {video_id}")
                return True
            else:
                logger.warning(f"FB caption upload returned {resp.status_code}: {resp.text[:200]}")
                return False
    except Exception as e:
        logger.warning(f"FB caption upload error for {video_id}: {e}")
        return False


def upload_facebook_thumbnail(access_token: str, video_id: str, thumbnail_path: str) -> bool:
    """Upload a custom thumbnail for a Facebook video."""
    try:
        content_type = "image/png" if thumbnail_path.lower().endswith(".png") else "image/jpeg"
        with open(thumbnail_path, "rb") as f:
            thumb_data = f.read()
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{GRAPH_API_BASE}/{video_id}",
                data={"access_token": access_token},
                files={"thumb": ("thumbnail", thumb_data, content_type)},
            )
            if resp.status_code == 200 and resp.json().get("success"):
                logger.info(f"FB thumbnail uploaded for video {video_id}")
                return True
            else:
                logger.warning(f"FB thumbnail upload returned {resp.status_code}: {resp.text[:200]}")
                return False
    except Exception as e:
        logger.warning(f"FB thumbnail upload error for {video_id}: {e}")
        return False


# ── Film Publishing ────────────────────────────────────────────────

def publish_film_to_facebook(access_token: str, page_id: str, video_path: str,
                              description: str, subtitle_path: str = None,
                              thumbnail_path: str = None) -> dict:
    """Publish a long video to Facebook Page, optionally with thumbnail and SRT subtitles."""
    result = publish_to_facebook(access_token, page_id, video_path, description)
    if not result.get("success"):
        return result

    video_id = result.get("video_id")
    if not video_id or video_id == "pending":
        return result

    # Get page token once for post-upload operations
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{GRAPH_API_BASE}/{page_id}", params={
                "access_token": access_token, "fields": "access_token",
            })
            page_token = resp.json().get("access_token", access_token)
    except Exception as e:
        logger.warning(f"FB page token fetch failed: {e}")
        page_token = access_token

    if thumbnail_path and os.path.exists(thumbnail_path):
        upload_facebook_thumbnail(page_token, video_id, thumbnail_path)

    if subtitle_path and os.path.exists(subtitle_path):
        upload_facebook_captions(page_token, video_id, subtitle_path)

    return result


def publish_film_to_youtube(client_id: str, client_secret: str, refresh_token: str,
                             video_path: str, title: str, description: str,
                             tags: list = None, category: str = "22",
                             privacy: str = "public",
                             thumbnail_path: str = None,
                             subtitle_path: str = None) -> dict:
    """Publish a long video to YouTube with optional thumbnail and Polish SRT subtitles."""
    # Upload video without subtitles first (we'll upload Polish subtitles separately)
    result = publish_to_youtube(
        client_id, client_secret, refresh_token,
        video_path, title, description,
        tags=tags, category=category, privacy=privacy,
        is_short=False, subtitle_path=None
    )
    if not result.get("success"):
        return result

    video_id = result["video_id"]
    access_token = _get_yt_access_token(client_id, client_secret, refresh_token)

    # Upload thumbnail
    if access_token and thumbnail_path and os.path.exists(thumbnail_path):
        upload_youtube_thumbnail(access_token, video_id, thumbnail_path)

    # Upload Polish subtitles
    if access_token and subtitle_path and os.path.exists(subtitle_path):
        try:
            result["subtitles"] = upload_youtube_subtitles(
                access_token, video_id, subtitle_path, language="pl", name="Polski"
            )
        except Exception as e:
            logger.warning(f"Polish subtitle upload failed: {e}")

    return result


# ── Orchestrator ─────────────────────────────────────────────────────

def publish_video(account: dict, video: dict, video_path: str) -> dict:
    """
    Orchestrate publishing a video to all enabled platforms for the account.
    Returns a dict with results per platform.
    """
    results = {}
    caption = video.get("caption", "") or video.get("title", "")

    if account["type"] == "instagram_facebook":
        # Per-video targeting (defaults to account-level settings)
        do_ig = video.get("target_ig", 1) and account.get("publish_to_ig") and account.get("ig_user_id")
        do_fb = video.get("target_fb", 1) and account.get("publish_to_fb") and account.get("fb_page_id")

        # Publish to Instagram (needs tmpfiles URL)
        if do_ig:
            video_url = get_video_url_for_api(account["id"], video["filename"])
            if video_url:
                if video.get("video_type") == "story":
                    ig_result = publish_story_to_instagram(
                        account["fb_access_token"], account["ig_user_id"], video_url
                    )
                else:
                    # Determine trial reel: per-video override (is_trial) > account default (ig_trial_reels)
                    use_trial = video.get("is_trial") if video.get("is_trial") is not None else bool(account.get("ig_trial_reels"))
                    ig_result = publish_to_instagram(
                        account["fb_access_token"], account["ig_user_id"], video_url, caption, is_trial=use_trial
                    )
                results["instagram"] = ig_result
            else:
                results["instagram"] = {"success": False, "error": "Failed to upload video for API"}

        # Publish to Facebook (direct file upload via curl)
        if do_fb:
            fb_caption = video.get("fb_title") or caption

            # Optional SRT: explicit subtitle_file field, or any .srt in the same directory
            fb_srt_path = None
            if video.get("subtitle_file"):
                candidate = os.path.join(os.path.dirname(video_path), video["subtitle_file"])
                if os.path.exists(candidate):
                    fb_srt_path = candidate
            else:
                video_dir = os.path.dirname(video_path)
                srts = [f for f in os.listdir(video_dir) if f.lower().endswith(".srt")]
                if srts:
                    fb_srt_path = os.path.join(video_dir, srts[0])

            # Optional thumbnail: auto-detect same-basename .jpg/.png
            fb_thumb_path = None
            for ext in (".jpg", ".jpeg", ".png"):
                candidate = video_path.rsplit(".", 1)[0] + ext
                if os.path.exists(candidate):
                    fb_thumb_path = candidate
                    break

            fb_result = publish_film_to_facebook(
                account["fb_access_token"], account["fb_page_id"], video_path, fb_caption,
                subtitle_path=fb_srt_path, thumbnail_path=fb_thumb_path,
            )
            results["facebook"] = fb_result

            # Post follow-up comment linking to the source long film, if configured
            comment_text = (video.get("fb_comment_text") or "").strip()
            fb_video_id = fb_result.get("video_id")
            if (fb_result.get("success") and comment_text
                    and fb_video_id and fb_video_id != "pending"):
                comment_res = post_fb_video_comment(
                    account["fb_access_token"], account["fb_page_id"],
                    fb_video_id, comment_text,
                )
                results["facebook_comment"] = comment_res

    elif account["type"] == "youtube":
        is_short = video.get("video_type") == "short"
        # Check for subtitle file
        subtitle_path = None
        if video.get("subtitle_file"):
            sub_path = os.path.join(os.path.dirname(video_path), video["subtitle_file"])
            if os.path.exists(sub_path):
                subtitle_path = sub_path
        else:
            # Auto-detect: look for .srt with same base name
            srt_path = video_path.rsplit(".", 1)[0] + ".srt"
            if os.path.exists(srt_path):
                subtitle_path = srt_path

        yt_result = publish_to_youtube(
            account["yt_client_id"], account["yt_client_secret"], account["yt_refresh_token"],
            video_path,
            title=video.get("yt_title") or video.get("title", ""),
            description=video.get("yt_description") or caption,
            tags=json.loads(video["yt_tags"]) if isinstance(video.get("yt_tags"), str) else video.get("yt_tags", []),
            category=video.get("yt_category", "22"),
            privacy=video.get("yt_privacy", "public"),
            is_short=is_short,
            subtitle_path=subtitle_path,
        )
        results["youtube"] = yt_result

        # Post follow-up comment linking to the source long film, if configured
        yt_comment = (video.get("yt_comment_text") or "").strip()
        yt_video_id = yt_result.get("video_id")
        if yt_result.get("success") and yt_comment and yt_video_id:
            comment_res = post_yt_video_comment(
                account["yt_client_id"], account["yt_client_secret"],
                account["yt_refresh_token"], yt_video_id, yt_comment,
            )
            results["youtube_comment"] = comment_res

    return results


# ── Comment Fetching ────────────────────────────────────────────────

def fetch_yt_comments(client_id: str, client_secret: str, refresh_token: str,
                      channel_id: str) -> list[dict]:
    """Fetch all comment threads for a YouTube channel's videos."""
    access_token = _get_yt_access_token(client_id, client_secret, refresh_token)
    if not access_token:
        raise RuntimeError("YouTube token refresh failed")

    comments = []
    # Cache video metadata to avoid redundant API calls
    video_cache = {}

    with httpx.Client(timeout=60) as client:
        page_token = None
        while True:
            params = {
                "part": "snippet",
                "allThreadsRelatedToChannelId": channel_id,
                "maxResults": 100,
                "order": "time",
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token

            resp = client.get("https://www.googleapis.com/youtube/v3/commentThreads",
                              params=params, headers={"Authorization": f"Bearer {access_token}"})
            data = resp.json()

            if "error" in data:
                logger.error(f"YT commentThreads error: {data['error']}")
                break

            for item in data.get("items", []):
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                vid_id = snippet.get("videoId", "")

                # Fetch video metadata (cached)
                if vid_id and vid_id not in video_cache:
                    vresp = client.get("https://www.googleapis.com/youtube/v3/videos",
                                       params={"part": "snippet", "id": vid_id},
                                       headers={"Authorization": f"Bearer {access_token}"})
                    vdata = vresp.json()
                    if vdata.get("items"):
                        vs = vdata["items"][0]["snippet"]
                        video_cache[vid_id] = {
                            "title": vs.get("title", ""),
                            "description": vs.get("description", ""),
                        }
                    else:
                        video_cache[vid_id] = {"title": "", "description": ""}

                vmeta = video_cache.get(vid_id, {"title": "", "description": ""})
                has_reply = item["snippet"].get("totalReplyCount", 0) > 0

                comments.append({
                    "platform": "youtube",
                    "platform_comment_id": item["snippet"]["topLevelComment"]["id"],
                    "platform_video_id": vid_id,
                    "platform_parent_id": item["id"],
                    "video_title": vmeta["title"],
                    "video_description": vmeta["description"],
                    "video_url": f"https://www.youtube.com/watch?v={vid_id}" if vid_id else "",
                    "commenter_name": snippet.get("authorDisplayName", ""),
                    "commenter_profile_url": snippet.get("authorChannelUrl", ""),
                    "comment_text": snippet.get("textDisplay", ""),
                    "comment_date": snippet.get("publishedAt", ""),
                    "like_count": snippet.get("likeCount", 0),
                    "has_owner_reply": has_reply,
                })

            page_token = data.get("nextPageToken")
            if not page_token:
                break

    logger.info(f"Fetched {len(comments)} YouTube comments")
    return comments


def fetch_ig_comments(access_token: str, ig_user_id: str) -> list[dict]:
    """Fetch comments on all Instagram media for the user."""
    comments = []
    with httpx.Client(timeout=60) as client:
        # Get user's media
        media_resp = client.get(f"{GRAPH_API_BASE}/{ig_user_id}/media", params={
            "access_token": access_token,
            "fields": "id,caption,permalink,media_url,media_type,timestamp",
            "limit": 50,
        })
        media_data = media_resp.json()

        for media in media_data.get("data", []):
            media_id = media["id"]
            # Fetch comments for this media
            c_resp = client.get(f"{GRAPH_API_BASE}/{media_id}/comments", params={
                "access_token": access_token,
                "fields": "id,text,timestamp,username,like_count,replies{id,text,timestamp,username}",
                "limit": 100,
            })
            c_data = c_resp.json()

            for c in c_data.get("data", []):
                # Check if any reply is from the account owner
                has_reply = False
                if "replies" in c:
                    for r in c["replies"].get("data", []):
                        pass  # IG API doesn't easily tell which is owner reply
                    has_reply = len(c["replies"].get("data", [])) > 0

                comments.append({
                    "platform": "instagram",
                    "platform_comment_id": c["id"],
                    "platform_video_id": media_id,
                    "platform_parent_id": media_id,
                    "video_title": (media.get("caption") or "")[:100],
                    "video_description": media.get("caption") or "",
                    "video_url": media.get("permalink") or "",
                    "commenter_name": c.get("username", ""),
                    "commenter_profile_url": f"https://instagram.com/{c.get('username', '')}",
                    "comment_text": c.get("text", ""),
                    "comment_date": c.get("timestamp", ""),
                    "like_count": c.get("like_count", 0),
                    "has_owner_reply": has_reply,
                })

    logger.info(f"Fetched {len(comments)} Instagram comments")
    return comments


def fetch_fb_comments(access_token: str, page_id: str) -> list[dict]:
    """Fetch comments on all Facebook Page videos."""
    comments = []
    with httpx.Client(timeout=60) as client:
        # Get page access token
        pt_resp = client.get(f"{GRAPH_API_BASE}/{page_id}", params={
            "access_token": access_token, "fields": "access_token",
        })
        page_token = pt_resp.json().get("access_token", access_token)

        # Get page videos
        v_resp = client.get(f"{GRAPH_API_BASE}/{page_id}/videos", params={
            "access_token": page_token, "fields": "id,title,description,permalink_url", "limit": 50,
        })

        for video in v_resp.json().get("data", []):
            vid_id = video["id"]
            c_resp = client.get(f"{GRAPH_API_BASE}/{vid_id}/comments", params={
                "access_token": page_token,
                "fields": "id,message,created_time,from,like_count,comment_count",
                "limit": 100,
            })

            for c in c_resp.json().get("data", []):
                commenter = c.get("from", {})
                comments.append({
                    "platform": "facebook",
                    "platform_comment_id": c["id"],
                    "platform_video_id": vid_id,
                    "platform_parent_id": vid_id,
                    "video_title": video.get("title") or video.get("description", "")[:100],
                    "video_description": video.get("description") or "",
                    "video_url": video.get("permalink_url") or f"https://www.facebook.com/{vid_id}",
                    "commenter_name": commenter.get("name", ""),
                    "commenter_profile_url": "",
                    "comment_text": c.get("message", ""),
                    "comment_date": c.get("created_time", ""),
                    "like_count": c.get("like_count", 0),
                    "has_owner_reply": (c.get("comment_count", 0) > 0),
                })

    logger.info(f"Fetched {len(comments)} Facebook comments")
    return comments


# ── Comment Reply Sending ──────────────────────────────────────────

def send_yt_reply(client_id: str, client_secret: str, refresh_token: str,
                  parent_comment_id: str, text: str) -> dict:
    """Post a reply to a YouTube comment."""
    access_token = _get_yt_access_token(client_id, client_secret, refresh_token)
    if not access_token:
        return {"success": False, "error": "Token refresh failed"}

    with httpx.Client(timeout=30) as client:
        resp = client.post("https://www.googleapis.com/youtube/v3/comments",
                           params={"part": "snippet"},
                           headers={"Authorization": f"Bearer {access_token}",
                                    "Content-Type": "application/json"},
                           json={"snippet": {"parentId": parent_comment_id, "textOriginal": text}})
        data = resp.json()
        if "error" in data:
            return {"success": False, "error": data["error"].get("message", str(data["error"]))}
        return {"success": True, "reply_id": data.get("id")}


def send_ig_reply(access_token: str, media_id: str, comment_id: str, text: str) -> dict:
    """Reply to an Instagram comment."""
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{GRAPH_API_BASE}/{comment_id}/replies", params={
            "access_token": access_token,
            "message": text,
        })
        data = resp.json()
        if "error" in data:
            return {"success": False, "error": data["error"].get("message", str(data["error"]))}
        return {"success": True, "reply_id": data.get("id")}


def send_fb_reply(access_token: str, page_id: str, comment_id: str, text: str) -> dict:
    """Reply to a Facebook comment."""
    with httpx.Client(timeout=30) as client:
        # Get page token
        pt_resp = client.get(f"{GRAPH_API_BASE}/{page_id}", params={
            "access_token": access_token, "fields": "access_token",
        })
        page_token = pt_resp.json().get("access_token", access_token)

        resp = client.post(f"{GRAPH_API_BASE}/{comment_id}/comments", params={
            "access_token": page_token,
            "message": text,
        })
        data = resp.json()
        if "error" in data:
            return {"success": False, "error": data["error"].get("message", str(data["error"]))}
        return {"success": True, "reply_id": data.get("id")}
