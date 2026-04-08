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


def get_video_url_for_api(account_id: int, filename: str) -> str | None:
    """Upload video to tmpfiles.org and return URL for API consumption."""
    path = get_video_path(account_id, filename)
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


def publish_to_instagram(access_token: str, ig_user_id: str, video_url: str, caption: str) -> dict:
    """Publish a Reel to Instagram using the Content Publishing API."""
    try:
        with httpx.Client(timeout=300) as client:
            # Step 1: Create media container
            create_resp = client.post(f"{GRAPH_API_BASE}/{ig_user_id}/media", data={
                "access_token": access_token,
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
            })
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


# ── Facebook Publishing ─────────────────────────────────────────────

def publish_to_facebook(access_token: str, page_id: str, video_path: str, description: str) -> dict:
    """Publish a video to Facebook Page via curl with config file (no token in ps)."""
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

        # Write curl config to temp file (keeps token and description out of ps aux)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".curl", delete=False) as cf:
            cf.write(f'-F "access_token={page_token}"\n')
            cf.write(f'-F "description={description}"\n')
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

        logger.info(f"FB curl response: {result.stdout[:500]}")
        if result.stderr:
            logger.error(f"FB curl stderr: {result.stderr[:500]}")

        data = json.loads(result.stdout) if result.stdout.strip() else {}
        if not data and result.returncode != 0:
            return {"success": False, "error": f"curl failed (rc={result.returncode}): {result.stderr[:200]}"}

        if "id" in data:
            return {
                "success": True,
                "video_id": data["id"],
                "permalink": f"https://www.facebook.com/{page_id}/videos/{data['id']}",
            }

        # FB sometimes returns error code 1 (rate limit) but still processes the upload
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
                    ig_result = publish_to_instagram(
                        account["fb_access_token"], account["ig_user_id"], video_url, caption
                    )
                results["instagram"] = ig_result
            else:
                results["instagram"] = {"success": False, "error": "Failed to upload video for API"}

        # Publish to Facebook (direct file upload via curl)
        if do_fb:
            fb_caption = video.get("fb_title") or caption
            fb_result = publish_to_facebook(
                account["fb_access_token"], account["fb_page_id"], video_path, fb_caption
            )
            results["facebook"] = fb_result

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

    return results
