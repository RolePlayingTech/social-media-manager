# Social Media Manager

A self-hosted social media publishing queue manager for **Instagram**, **Facebook**, and **YouTube**. Built with FastAPI, SQLite, and a vanilla JS dashboard.

## Features

- **Multi-account support** — manage multiple Instagram+Facebook pairs and YouTube channels from one dashboard
- **Video queue** with drag-and-drop reordering and estimated publish dates
- **Automated scheduling** — per-account publish times, daily limits, day-of-week rules
- **Per-video platform targeting** — publish to Instagram only, Facebook only, or both
- **Separate captions** for Instagram and Facebook per video
- **YouTube OAuth2** — built-in authorization flow, no manual token management
- **SRT subtitle upload** for YouTube videos
- **Bulk upload** via SSH scripts for server-side batch operations
- **Sync published content** — import your existing posts from Instagram, Facebook, and YouTube APIs
- **Published video browser** with platform filtering and date sorting
- **Dark minimal UI** — responsive, fast, zero dependencies

## Requirements

- Python 3.11+
- nginx (reverse proxy)
- A Facebook App with Graph API access (for Instagram/Facebook publishing)
- A Google Cloud project with YouTube Data API v3 enabled (for YouTube publishing)

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/yourusername/social-media-manager.git /opt/social-media-manager
cd /opt/social-media-manager

# Install dependencies
pip install -r requirements.txt

# Create environment file with your secrets
cp .env.example .env
nano .env  # Set SMM_API_TOKEN and SMM_PASSWORD
chmod 600 .env
```

### 2. Set up systemd service

```bash
# Edit the service file paths
cp social-media-manager.service.example /etc/systemd/system/social-media-manager.service
nano /etc/systemd/system/social-media-manager.service  # Update paths and User

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable social-media-manager
sudo systemctl start social-media-manager

# Verify
sudo systemctl status social-media-manager
curl http://127.0.0.1:8902/health
```

### 3. Configure nginx

Add to your nginx site configuration:

```nginx
# Block sensitive files
location ~* /social-admin-v2/.*\.(py|service|md|sqlite3|log|env)$ { deny all; }

# Static files
location /social-admin-v2/static/ {
    alias /opt/social-media-manager/static/;
    expires 1h;
}

# Dashboard
location = /social-admin-v2/ {
    alias /opt/social-media-manager/static/;
    try_files /index.html =404;
}

# API proxy
location /social-admin-v2/api/ {
    proxy_pass http://127.0.0.1:8902/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    client_max_body_size 500M;
}
```

Reload nginx: `sudo nginx -t && sudo systemctl reload nginx`

### 4. Log in

Open `https://yourdomain.com/social-admin-v2/` and enter the password from your `.env` file.

## Account Setup

### Instagram + Facebook

1. Go to [Facebook for Developers](https://developers.facebook.com/) and create an app
2. Generate a **Page Access Token** with these permissions:
   - `instagram_basic`, `instagram_content_publish`
   - `pages_manage_posts`, `pages_read_engagement`
   - `publish_video`
3. In the dashboard, go to **Settings** → paste the token → **Save**
4. Click **Refresh** to auto-discover your Page ID, IG User ID, and profile info

### YouTube

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a project
2. Enable the **YouTube Data API v3**
3. Create **OAuth 2.0 credentials** (Web Application type)
4. Add this Authorized redirect URI:
   ```
   https://yourdomain.com/social-admin-v2/api/youtube/oauth/callback
   ```
5. In the OAuth consent screen, add scopes:
   - `youtube.upload`, `youtube.force-ssl`, `youtube.readonly`
6. In the dashboard, go to **Settings** → paste Client ID and Client Secret → **Save**
7. Click **Authorize with Google** → complete the consent flow
8. Done — channel info and profile picture will load automatically

## Publishing

### How the queue works

Each account has a **schedule** configurable in the **Schedule** tab:
- **Publish times** — e.g., 06:00 and 17:00
- **Days of week** — which days to publish
- **Max per day** — daily publish limit
- **Platform toggles** — Instagram, Facebook, or both (for IG+FB accounts)

Videos in the queue get published in order. The queue view shows **estimated publish dates** calculated from the schedule.

### Per-video platform targeting (Instagram + Facebook)

Each video can be published to Instagram, Facebook, or both:
- Toggle platforms in the **Edit** dialog
- Set a **separate Facebook description** if you want different text per platform
- If Facebook description is empty, the Instagram caption is used

### Manual publish

Click the **Publish** button on any queued video to publish it immediately.

## Bulk Upload

### From the dashboard

Go to the **Upload** tab. Drag and drop video files (MP4, MOV, AVI, MKV, WEBM). You can also drop `.txt` files with matching names for captions and `.srt` files for YouTube subtitles.

### Via SSH (server-side script)

For uploading many videos at once from your local machine:

```bash
# Step 1: Copy videos to the server
scp -r ./videos/ admin@yourserver.com:/tmp/upload/

# Step 2: Run the bulk upload script
ssh admin@yourserver.com 'cd /opt/social-media-manager/scripts && \
  SMM_API_TOKEN=your-token-here ./bulk_upload.sh ACCOUNT_ID /tmp/upload/ TYPE'
```

**Parameters:**
- `ACCOUNT_ID` — numeric account ID (visible in dashboard Settings tab)
- `/tmp/upload/` — directory containing your video files
- `TYPE` — `reel`, `story`, `short`, or `video` (default: `reel`)

**File structure:**

```
videos/
├── my_video.mp4          # Video file
├── my_video.txt          # Caption/description (optional, matched by name)
├── my_video.srt          # SRT subtitles for YouTube (optional)
├── another_video.mp4     # Video without caption
└── third_video.mp4
```

The script auto-matches `.txt` and `.srt` files to videos by filename.

**One-liner (upload + queue):**

```bash
scp -r ./videos/ admin@server:/tmp/upload/ && \
ssh admin@server 'SMM_API_TOKEN=token /opt/social-media-manager/scripts/bulk_upload.sh 1 /tmp/upload/ reel'
```

### Automating bulk uploads with cron

To automatically upload videos dropped into a directory:

```bash
# Add to crontab (crontab -e)
*/30 * * * * SMM_API_TOKEN=your-token /opt/social-media-manager/scripts/bulk_upload.sh 1 /data/auto-upload/ reel && rm -f /data/auto-upload/*.mp4 /data/auto-upload/*.txt
```

## Syncing Published Content

The dashboard can import your already-published videos from platform APIs:

1. Go to the account's **Settings** tab
2. Click **"Sync published videos"**
3. Videos from Instagram, Facebook, and YouTube will be imported with metadata, links, and dates

This is useful to see your full publishing history in one place.

## SRT Subtitles (YouTube)

YouTube videos can have SRT subtitle files attached:

- **Dashboard upload:** Include `.srt` files alongside video files
- **Bulk upload:** Place `.srt` files with matching filenames next to `.mp4` files
- **Automatic:** The publisher auto-detects `.srt` files by name and uploads them via the YouTube Captions API

Subtitles are only supported for YouTube. Instagram does not support subtitle files.

## API Reference

All endpoints require `Authorization: Bearer <token>` header (except `/health` and `/api/login`).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/login` | Login with password, get token |
| GET | `/api/accounts` | List all accounts |
| POST | `/api/accounts` | Create account |
| GET | `/api/accounts/:id` | Get account details |
| PUT | `/api/accounts/:id` | Update account |
| DELETE | `/api/accounts/:id` | Delete account |
| GET | `/api/accounts/:id/tokens` | Get unmasked API tokens |
| POST | `/api/accounts/:id/refresh` | Refresh account info from APIs |
| POST | `/api/accounts/:id/sync-published` | Sync published videos from platform |
| GET | `/api/accounts/:id/videos` | List videos (filter: `?status=queued`) |
| POST | `/api/accounts/:id/videos/upload` | Upload single video |
| POST | `/api/accounts/:id/videos/bulk-upload` | Upload multiple videos |
| POST | `/api/accounts/:id/videos/reorder` | Reorder queue |
| GET | `/api/videos/:id` | Get video details |
| PUT | `/api/videos/:id` | Update video metadata |
| DELETE | `/api/videos/:id` | Delete video |
| POST | `/api/videos/:id/publish` | Publish now |
| GET | `/api/publish/status/:job_id` | Poll publish job status |
| GET | `/api/accounts/:id/schedule` | Get schedule |
| PUT | `/api/accounts/:id/schedule` | Update schedule |
| GET | `/api/youtube/oauth/start` | Start YouTube OAuth flow |
| GET | `/api/youtube/oauth/callback` | OAuth callback (auto) |

## Architecture

```
social-admin-v2/
├── api.py              # FastAPI application & endpoints
├── database.py         # SQLite schema & CRUD operations
├── publisher.py        # Platform publishing (IG, FB, YouTube)
├── scheduler.py        # APScheduler automated publishing
├── static/
│   ├── index.html      # SPA entry point
│   ├── css/style.css   # Dark minimal theme
│   └── js/app.js       # Dashboard application
├── scripts/
│   ├── bulk_upload.sh  # Server-side bulk upload
│   └── remote_upload.sh # Remote upload helper
├── uploads/            # Video file storage (gitignored)
│   └── {account_id}/
│       ├── queue/      # Queued videos
│       └── archive/    # Published videos
├── .env                # Secrets (gitignored)
├── .env.example        # Template for .env
├── requirements.txt    # Python dependencies
└── db.sqlite3          # Database (gitignored)
```

## Security Notes

- All API tokens and credentials are stored in `.env` (never committed)
- Facebook/YouTube tokens are stored in the SQLite database
- The `.gitignore` excludes `.env`, `db.sqlite3`, `uploads/`, and `app.log`
- nginx is configured to deny access to `.py`, `.env`, `.sqlite3`, and `.log` files
- HTTPS is required (tokens are sent in Authorization headers)

## License

MIT
