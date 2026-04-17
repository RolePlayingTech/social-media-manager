#!/bin/bash
#
# Social Media Manager - Bulk Upload Script
#
# USAGE:
#   bulk_upload.sh <ACCOUNT_NAME> <VIDEO_DIR> [TYPE]
#   bulk_upload.sh --list
#
# EXAMPLES:
#   bulk_upload.sh "MyAccount" /tmp/upload/ reel
#   bulk_upload.sh "MyChannel" /tmp/upload/ short
#
# SSH one-liner from local machine:
#   scp -r ./videos/ user@yourserver:/tmp/upload/ && \
#   ssh user@yourserver '/path/to/bulk_upload.sh "MyAccount" /tmp/upload/ reel'
#

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
API_BASE="http://127.0.0.1:8902"
SUPPORTED_FORMATS="mp4 mov avi mkv webm"

# Load token from .env automatically
if [ -z "${SMM_API_TOKEN:-}" ] && [ -f "${APP_DIR}/.env" ]; then
    SMM_API_TOKEN=$(grep -E '^SMM_API_TOKEN=' "${APP_DIR}/.env" | cut -d'=' -f2-)
fi
API_TOKEN="${SMM_API_TOKEN:?Could not find SMM_API_TOKEN (set it or check .env)}"

# ── Colors ───────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

# ── --list mode ──────────────────────────────────────────────────────

if [ "${1:-}" = "--list" ]; then
    echo -e "${BLUE}Available accounts:${NC}"
    curl -sf -H "Authorization: Bearer ${API_TOKEN}" "${API_BASE}/api/accounts" | \
        python3 -c "
import sys, json
for a in json.load(sys.stdin):
    q = a.get('stats', {}).get('queued', 0)
    t = 'IG+FB' if a['type'] == 'instagram_facebook' else 'YT'
    types = 'reel/story' if t == 'IG+FB' else 'short/video'
    print(f\"  [{a['id']}] {a['name']}  ({t})  — {q} queued  [{types}]\")
"
    echo ""
    echo -e "${BLUE}ASCII aliases (use these from SSH/PowerShell):${NC}"
    echo "  swiadek-dziejow  → Świadek Dziejów"
    echo "  swiadek-jutra    → Świadek Jutra"
    echo "  roleplayinglife  → RolePlayingLife"
    echo "  rpl              → RolePlayingLife"
    exit 0
fi

# ── Validate arguments ──────────────────────────────────────────────

if [ $# -lt 2 ]; then
    echo -e "Usage: $0 <ACCOUNT_NAME> <VIDEO_DIR> [TYPE]"
    echo -e "       $0 --list"
    echo ""
    echo "  ACCOUNT_NAME  - account name or substring (e.g. \"Świadek\")"
    echo "  VIDEO_DIR     - directory with video files"
    echo "  TYPE          - reel|story|short|video (default: reel)"
    exit 1
fi

# ── ASCII aliases for accounts with special characters ──────────────
# Avoids encoding issues when calling via SSH from Windows/PowerShell
declare -A ALIASES=(
    ["swiadek-dziejow"]="Świadek Dziejów"
    ["swiadek-jutra"]="Świadek Jutra"
    ["roleplayinglife"]="RolePlayingLife"
    ["rpl"]="RolePlayingLife"
)

INPUT_QUERY="$1"
ALIAS_KEY=$(echo "$INPUT_QUERY" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
ACCOUNT_QUERY="${ALIASES[$ALIAS_KEY]:-$INPUT_QUERY}"
SOURCE_DIR="$2"
VIDEO_TYPE="${3:-reel}"

if [[ ! "$VIDEO_TYPE" =~ ^(reel|story|short|video)$ ]]; then
    echo -e "${RED}Unknown type '$VIDEO_TYPE'. Allowed: reel, story, short, video${NC}"
    exit 1
fi

if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}Directory '$SOURCE_DIR' does not exist${NC}"
    exit 1
fi

if ! curl -sf "${API_BASE}/health" > /dev/null 2>&1; then
    echo -e "${RED}API not responding at ${API_BASE}${NC}"
    exit 1
fi

# ── Resolve account name → ID ───────────────────────────────────────

ACCOUNTS_JSON=$(curl -sf -H "Authorization: Bearer ${API_TOKEN}" "${API_BASE}/api/accounts")

MATCH=$(echo "$ACCOUNTS_JSON" | python3 -c "
import sys, json, re

query = re.sub(r'\s+', '', sys.argv[1].lower())
video_type = sys.argv[2]
accounts = json.load(sys.stdin)

# Match ignoring spaces
matches = [a for a in accounts if query in re.sub(r'\s+', '', a['name'].lower())]

# If multiple matches with same name, pick by video_type
if len(matches) > 1:
    if video_type in ('reel', 'story'):
        filtered = [a for a in matches if a['type'] == 'instagram_facebook']
    elif video_type in ('short', 'video'):
        filtered = [a for a in matches if a['type'] == 'youtube']
    else:
        filtered = matches
    if len(filtered) == 1:
        matches = filtered

if len(matches) == 0:
    names = ', '.join(f\"{a['name']} ({a['type']})\" for a in accounts)
    print(f'ERROR:No account matching \"{sys.argv[1]}\". Available: {names}')
elif len(matches) > 1:
    hits = ', '.join(f\"{a['name']} ({a['type']}, ID:{a['id']})\" for a in matches)
    print(f'ERROR:Multiple matches: {hits}. Hint: use reel/story for IG+FB or short/video for YouTube.')
else:
    a = matches[0]
    print(f\"{a['id']}|{a['name']}|{a['type']}\")
" "$ACCOUNT_QUERY" "$VIDEO_TYPE" 2>/dev/null)

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
    echo -e "${YELLOW}No video files in ${SOURCE_DIR}${NC}"
    exit 0
fi

# ── Header ───────────────────────────────────────────────────────────

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Social Media Manager - Bulk Upload${NC}"
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
        -sf -X POST
        -H "Authorization: Bearer ${API_TOKEN}"
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

    RESPONSE=$(curl "${CURL_ARGS[@]}" "${API_BASE}/api/accounts/${ACCOUNT_ID}/videos/bulk-upload" 2>&1 || true)

    if echo "$RESPONSE" | grep -q '"ok": true\|"ok":true'; then
        echo -e "${GREEN}OK${NC}"
        SUCCESS=$((SUCCESS + 1))
    else
        ERROR=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail','') or d.get('results',[{}])[0].get('error','unknown'))" 2>/dev/null || echo "unknown error")
        echo -e "${RED}FAIL: ${ERROR}${NC}"
        FAILED=$((FAILED + 1))
    fi
done

# ── Summary ──────────────────────────────────────────────────────────

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "  Result: ${GREEN}${SUCCESS} OK${NC} / ${RED}${FAILED} failed${NC} / ${TOTAL} total"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"

# Clean up source directory after successful upload
if [ $FAILED -eq 0 ] && [ "$SOURCE_DIR" = "/tmp/upload" ] || [ "$SOURCE_DIR" = "/tmp/upload/" ]; then
    rm -f "${SOURCE_DIR}"/*.mp4 "${SOURCE_DIR}"/*.mov "${SOURCE_DIR}"/*.avi "${SOURCE_DIR}"/*.mkv "${SOURCE_DIR}"/*.webm
    rm -f "${SOURCE_DIR}"/*.txt "${SOURCE_DIR}"/*.srt
    echo -e "  ${CYAN}Cleaned up ${SOURCE_DIR}${NC}"
fi

[ $FAILED -gt 0 ] && exit 1
exit 0
