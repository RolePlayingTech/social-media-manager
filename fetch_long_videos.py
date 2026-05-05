"""
Fetch all videos from configured FB pages + YT channels via API,
identify the LONG-form films (>= 5 min) and cache them to long_videos_cache.json.

Run:  python3 fetch_long_videos.py
"""

import httpx
import json
import logging
import sys
import time
from pathlib import Path

import database as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fetch_long")

CACHE_PATH = Path(__file__).parent / "long_videos_cache.json"

GRAPH = "https://graph.facebook.com/v21.0"
LONG_VIDEO_MIN_SECONDS = 300  # >= 5 minutes is "long"


def fetch_fb_page_videos(account: dict) -> list:
    """Return all videos from a FB page with full metadata."""
    out = []
    with httpx.Client(timeout=60) as client:
        pt_resp = client.get(f"{GRAPH}/{account['fb_page_id']}", params={
            "access_token": account["fb_access_token"], "fields": "access_token",
        })
        page_token = pt_resp.json().get("access_token", account["fb_access_token"])

        url = f"{GRAPH}/{account['fb_page_id']}/videos"
        params = {
            "access_token": page_token,
            "fields": "id,title,description,length,permalink_url,created_time",
            "limit": 100,
        }
        page = 0
        while url:
            page += 1
            resp = client.get(url, params=params if page == 1 else None)
            data = resp.json()
            if "error" in data:
                log.error(f"FB error: {data['error']}")
                break
            out.extend(data.get("data", []))
            paging = data.get("paging", {})
            next_url = paging.get("next")
            if next_url:
                url = next_url
                params = None
            else:
                url = None
            log.info(f"  page {page}: total so far {len(out)}")
            if page > 50:
                log.warning("Pagination cap reached at 50 pages")
                break
            time.sleep(0.2)
    return out


def fetch_yt_channel_videos(account: dict) -> list:
    """Return YouTube videos with id, title, description, duration via uploads playlist."""
    from publisher import _get_yt_access_token
    access_token = _get_yt_access_token(
        account["yt_client_id"], account["yt_client_secret"], account["yt_refresh_token"]
    )
    if not access_token:
        log.error(f"YT token refresh failed for account {account['id']}")
        return []

    out = []
    with httpx.Client(timeout=60) as client:
        # Get uploads playlist id
        ch_resp = client.get("https://www.googleapis.com/youtube/v3/channels", params={
            "part": "contentDetails", "mine": "true",
        }, headers={"Authorization": f"Bearer {access_token}"})
        items = ch_resp.json().get("items", [])
        if not items:
            return []
        uploads_pid = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # Page through playlistItems to get video IDs
        page_token = None
        video_ids = []
        for _ in range(50):
            params = {
                "part": "contentDetails", "playlistId": uploads_pid, "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            resp = client.get("https://www.googleapis.com/youtube/v3/playlistItems",
                              params=params,
                              headers={"Authorization": f"Bearer {access_token}"})
            data = resp.json()
            for it in data.get("items", []):
                video_ids.append(it["contentDetails"]["videoId"])
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        log.info(f"  YT video IDs collected: {len(video_ids)}")

        # Fetch metadata in batches of 50
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            resp = client.get("https://www.googleapis.com/youtube/v3/videos", params={
                "part": "snippet,contentDetails",
                "id": ",".join(batch),
            }, headers={"Authorization": f"Bearer {access_token}"})
            for it in resp.json().get("items", []):
                snippet = it.get("snippet", {})
                cd = it.get("contentDetails", {})
                out.append({
                    "id": it["id"],
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "duration_iso": cd.get("duration", ""),
                    "url": f"https://www.youtube.com/watch?v={it['id']}",
                    "published_at": snippet.get("publishedAt", ""),
                })
            time.sleep(0.1)
    return out


def parse_iso_duration(iso: str) -> int:
    """Convert ISO 8601 duration like 'PT15M30S' to seconds."""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mn, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mn * 60 + s


def is_long_fb(v: dict) -> bool:
    length = v.get("length") or 0
    try:
        return float(length) >= LONG_VIDEO_MIN_SECONDS
    except (TypeError, ValueError):
        return False


def is_long_yt(v: dict) -> bool:
    return parse_iso_duration(v.get("duration_iso", "")) >= LONG_VIDEO_MIN_SECONDS


def main():
    cache = {"fb_pages": {}, "yt_channels": {}, "fetched_at": ""}
    accounts = db.get_accounts()

    for acc in accounts:
        if acc.get("fb_page_id") and acc.get("fb_access_token"):
            log.info(f"Fetching FB videos for account {acc['id']} ({acc['name']})…")
            try:
                videos = fetch_fb_page_videos(acc)
                long_videos = [v for v in videos if is_long_fb(v)]
                log.info(f"  Total: {len(videos)}, long (>={LONG_VIDEO_MIN_SECONDS}s): {len(long_videos)}")
                cache["fb_pages"][str(acc["id"])] = {
                    "name": acc["name"], "page_id": acc["fb_page_id"],
                    "all": videos, "long": long_videos,
                }
            except Exception as e:
                log.error(f"  Error: {e}")

        if acc.get("yt_channel_id") and acc.get("yt_refresh_token"):
            log.info(f"Fetching YT videos for account {acc['id']} ({acc['name']})…")
            try:
                videos = fetch_yt_channel_videos(acc)
                long_videos = [v for v in videos if is_long_yt(v)]
                log.info(f"  Total: {len(videos)}, long (>={LONG_VIDEO_MIN_SECONDS}s): {len(long_videos)}")
                cache["yt_channels"][str(acc["id"])] = {
                    "name": acc["name"], "channel_id": acc["yt_channel_id"],
                    "all": videos, "long": long_videos,
                }
            except Exception as e:
                log.error(f"  Error: {e}")

    cache["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    log.info(f"Saved cache to {CACHE_PATH}")
    log.info(f"FB long films: {sum(len(v['long']) for v in cache['fb_pages'].values())}")
    log.info(f"YT long films: {sum(len(v['long']) for v in cache['yt_channels'].values())}")


if __name__ == "__main__":
    main()
