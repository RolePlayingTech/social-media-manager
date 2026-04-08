#!/bin/bash
#
# Social Media Manager - Local Upload Script
# Upload videos from your local machine to the server queue.
#
# USAGE:
#   ./upload_local.sh <ACCOUNT_NAME> <VIDEO_DIR> [TYPE]
#
# PARAMETERS:
#   ACCOUNT_NAME  - account name (or unique substring), e.g. "Świadek" or "Bractwo"
#   VIDEO_DIR     - directory with .mp4 files (and optional .txt/.srt)
#   TYPE          - reel, story, short, video (default: reel)
#
# ENVIRONMENT:
#   SMM_API_TOKEN - required, your API bearer token
#   SMM_SERVER    - optional, default: https://yourserver.com/social-admin-v2/api
#
# FILE STRUCTURE:
#   videos/
#   ├── episode_01.mp4       # video (required)
#   ├── episode_01.txt       # caption (optional, matched by name)
#   ├── episode_01.srt       # YouTube subtitles (optional)
#   └── episode_02.mp4
#
# EXAMPLES:
#   ./upload_local.sh "Świadek" ./videos/ reel
#   ./upload_local.sh "Bractwo" ./videos/ reel
#   ./upload_local.sh "YouTube" ./videos/ short
#
#   # List available accounts:
#   ./upload_local.sh --list
#

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────

SERVER="${SMM_SERVER:-https://yourserver.com/social-admin-v2/api}"
TOKEN="${SMM_API_TOKEN:?Set SMM_API_TOKEN environment variable}"
SUPPORTED_FORMATS="mp4 mov avi mkv webm"

# ── Colors ───────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Helper: fetch accounts ──────────────────────────────────────────

fetch_accounts() {
    curl -sf -H "Authorization: Bearer ${TOKEN}" "${SERVER}/accounts" 2>/dev/null
}

# ── --list mode ──────────────────────────────────────────────────────

if [ "${1:-}" = "--list" ]; then
    echo -e "${BLUE}Available accounts:${NC}"
    echo ""
    ACCOUNTS=$(fetch_accounts)
    if [ -z "$ACCOUNTS" ]; then
        echo -e "${RED}Could not fetch accounts from ${SERVER}${NC}"
        exit 1
    fi
    echo "$ACCOUNTS" | python3 -c "
import sys, json
accounts = json.load(sys.stdin)
for a in accounts:
    q = a.get('stats', {}).get('queued', 0)
    print(f\"  [{a['id']}] {a['name']}  ({a['type']})  — {q} queued\")
"
    exit 0
fi

# ── Validate arguments ──────────────────────────────────────────────

if [ $# -lt 2 ]; then
    echo -e "${RED}ERROR: Not enough arguments${NC}"
    echo ""
    echo "Usage: $0 <ACCOUNT_NAME> <VIDEO_DIR> [TYPE]"
    echo "       $0 --list"
    echo ""
    echo "  ACCOUNT_NAME  - account name or substring (e.g. \"Świadek\")"
    echo "  VIDEO_DIR     - directory with video files"
    echo "  TYPE          - reel|story|short|video (default: reel)"
    exit 1
fi

ACCOUNT_QUERY="$1"
SOURCE_DIR="$2"
VIDEO_TYPE="${3:-reel}"

# Validate type
if [[ ! "$VIDEO_TYPE" =~ ^(reel|story|short|video)$ ]]; then
    echo -e "${RED}ERROR: Unknown type '$VIDEO_TYPE'. Allowed: reel, story, short, video${NC}"
    exit 1
fi

# Validate directory
if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}ERROR: Directory '$SOURCE_DIR' does not exist${NC}"
    exit 1
fi

# ── Resolve account name → ID ───────────────────────────────────────

ACCOUNTS=$(fetch_accounts)
if [ -z "$ACCOUNTS" ]; then
    echo -e "${RED}ERROR: Could not fetch accounts from ${SERVER}${NC}"
    echo "Check your SMM_API_TOKEN and server availability."
    exit 1
fi

MATCH=$(echo "$ACCOUNTS" | python3 -c "
import sys, json

query = '''${ACCOUNT_QUERY}'''.lower()
accounts = json.load(sys.stdin)
matches = [a for a in accounts if query in a['name'].lower()]

if len(matches) == 0:
    print('ERROR:No account matching \"${ACCOUNT_QUERY}\"')
    print('Available:', ', '.join(a['name'] for a in accounts))
elif len(matches) > 1:
    print('ERROR:Multiple matches: ' + ', '.join(f\"{a['name']} (ID:{a['id']})\" for a in matches))
else:
    a = matches[0]
    print(f\"{a['id']}|{a['name']}|{a['type']}\")
" 2>/dev/null)

if [[ "$MATCH" == ERROR:* ]]; then
    echo -e "${RED}${MATCH#ERROR:}${NC}"
    exit 1
fi

ACCOUNT_ID=$(echo "$MATCH" | cut -d'|' -f1)
ACCOUNT_NAME=$(echo "$MATCH" | cut -d'|' -f2)
ACCOUNT_TYPE=$(echo "$MATCH" | cut -d'|' -f3)

# ── Find video files ────────────────────────────────────────────────

VIDEO_FILES=()
for ext in $SUPPORTED_FORMATS; do
    while IFS= read -r -d '' file; do
        VIDEO_FILES+=("$file")
    done < <(find "$SOURCE_DIR" -maxdepth 1 -iname "*.${ext}" -print0 2>/dev/null | sort -z)
done

if [ ${#VIDEO_FILES[@]} -eq 0 ]; then
    echo -e "${YELLOW}No video files found in ${SOURCE_DIR}${NC}"
    exit 0
fi

# ── Header ───────────────────────────────────────────────────────────

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Social Media Manager - Upload${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "  Account:  ${GREEN}${ACCOUNT_NAME}${NC} (${ACCOUNT_TYPE}, ID: ${ACCOUNT_ID})"
echo -e "  Source:   ${SOURCE_DIR}"
echo -e "  Type:     ${VIDEO_TYPE}"
echo -e "  Videos:   ${#VIDEO_FILES[@]}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""

# ── Upload ───────────────────────────────────────────────────────────

SUCCESS=0
FAILED=0
TOTAL=${#VIDEO_FILES[@]}

for i in "${!VIDEO_FILES[@]}"; do
    VIDEO_FILE="${VIDEO_FILES[$i]}"
    FILENAME=$(basename "$VIDEO_FILE")
    BASENAME="${FILENAME%.*}"
    NUM=$((i + 1))

    echo -ne "  [${NUM}/${TOTAL}] ${FILENAME} "

    CURL_ARGS=(
        -sf
        -X POST
        -H "Authorization: Bearer ${TOKEN}"
        -F "files=@${VIDEO_FILE}"
        -F "video_type=${VIDEO_TYPE}"
    )

    EXTRAS=""
    if [ -f "${SOURCE_DIR}/${BASENAME}.txt" ]; then
        CURL_ARGS+=(-F "files=@${SOURCE_DIR}/${BASENAME}.txt")
        EXTRAS="+caption "
    fi
    if [ -f "${SOURCE_DIR}/${BASENAME}.srt" ]; then
        CURL_ARGS+=(-F "files=@${SOURCE_DIR}/${BASENAME}.srt")
        EXTRAS="${EXTRAS}+srt "
    fi

    [ -n "$EXTRAS" ] && echo -ne "${CYAN}${EXTRAS}${NC}"
    echo -n "... "

    RESPONSE=$(curl "${CURL_ARGS[@]}" "${SERVER}/accounts/${ACCOUNT_ID}/videos/bulk-upload" 2>&1 || true)

    if echo "$RESPONSE" | grep -q '"ok": true\|"ok":true'; then
        echo -e "${GREEN}OK${NC}"
        SUCCESS=$((SUCCESS + 1))
    else
        ERROR=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail','') or d.get('results',[{}])[0].get('error','unknown'))" 2>/dev/null || echo "$RESPONSE")
        echo -e "${RED}FAIL: ${ERROR}${NC}"
        FAILED=$((FAILED + 1))
    fi
done

# ── Summary ──────────────────────────────────────────────────────────

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "  Result: ${GREEN}${SUCCESS} OK${NC} / ${RED}${FAILED} failed${NC} / ${TOTAL} total"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"

[ $FAILED -gt 0 ] && exit 1
exit 0
