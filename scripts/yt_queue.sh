#!/bin/bash
#
# yt_queue.sh — Queue videos to a YouTube account via social-admin-v2 API,
# using per-file yt_title (from <slug>_title.txt) and yt_description (from <slug>_reel.txt).
#
# Expected file convention in SOURCE_DIR, for each video BASE.mp4:
#   BASE.mp4         — video (required), where BASE typically ends with "_reel"
#   BASE.txt         — full description/caption (optional)
#   <SLUG>_title.txt — title, where SLUG = BASE with trailing "_reel" stripped
#
# Example:
#   kolaps_trzy_zdania_reel.mp4
#   kolaps_trzy_zdania_reel.txt       (→ yt_description + caption)
#   kolaps_trzy_zdania_title.txt      (→ yt_title, first line)
#
# Usage:
#   yt_queue.sh <ACCOUNT> <SOURCE_DIR>
#
# Examples:
#   yt_queue.sh roleplayinglife /tmp/upload/
#   yt_queue.sh 3 /tmp/upload/
#   yt_queue.sh "RolePlayingLife" /tmp/upload/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
API_BASE="http://127.0.0.1:8902"

if [ -z "${SMM_API_TOKEN:-}" ] && [ -f "${APP_DIR}/.env" ]; then
    SMM_API_TOKEN=$(grep -E '^SMM_API_TOKEN=' "${APP_DIR}/.env" | cut -d'=' -f2-)
fi
API_TOKEN="${SMM_API_TOKEN:?Could not find SMM_API_TOKEN (set it or check .env)}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

if [ $# -lt 2 ]; then
    echo -e "Usage: $0 <ACCOUNT> <SOURCE_DIR>"
    echo "  ACCOUNT     - YouTube account name, substring, or numeric ID"
    echo "  SOURCE_DIR  - directory with .mp4 + matching .txt and _title.txt files"
    exit 1
fi

INPUT_QUERY="$1"
SOURCE_DIR="$2"

# Optional flag to skip cleanup (used when chaining upload scripts)
NO_CLEANUP=false
for _arg in "$@"; do
    [ "$_arg" = "--no-cleanup" ] && NO_CLEANUP=true
done

declare -A ALIASES=(
    ["roleplayinglife"]="RolePlayingLife"
    ["rpl"]="RolePlayingLife"
)
ALIAS_KEY=$(echo "$INPUT_QUERY" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
ACCOUNT_QUERY="${ALIASES[$ALIAS_KEY]:-$INPUT_QUERY}"

if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}Directory '$SOURCE_DIR' does not exist${NC}"
    exit 1
fi

if ! curl -sf "${API_BASE}/health" > /dev/null 2>&1; then
    echo -e "${RED}API not responding at ${API_BASE}${NC}"
    exit 1
fi

# Resolve YouTube account
ACCOUNTS_JSON=$(curl -sf -H "Authorization: Bearer ${API_TOKEN}" "${API_BASE}/api/accounts")

MATCH=$(echo "$ACCOUNTS_JSON" | python3 -c "
import sys, json, re
q = sys.argv[1]
accounts = [a for a in json.load(sys.stdin) if a['type'] == 'youtube']
try:
    aid = int(q)
    hits = [a for a in accounts if a['id'] == aid]
except ValueError:
    qlow = re.sub(r'\s+', '', q.lower())
    hits = [a for a in accounts if qlow in re.sub(r'\s+', '', a['name'].lower())]
if len(hits) == 1:
    a = hits[0]
    print(f\"{a['id']}|{a['name']}\")
elif len(hits) == 0:
    names = ', '.join(a['name'] for a in accounts) or '(none configured)'
    print(f'ERROR:No YouTube account matching \"{q}\". Available: {names}')
else:
    names = ', '.join(f\"{a['name']} (ID:{a['id']})\" for a in hits)
    print(f'ERROR:Multiple matches: {names}')
" "$ACCOUNT_QUERY" 2>/dev/null)

if [[ "$MATCH" == ERROR:* ]]; then
    echo -e "${RED}${MATCH#ERROR:}${NC}"
    exit 1
fi

ACCOUNT_ID=$(echo "$MATCH" | cut -d'|' -f1)
ACCOUNT_NAME=$(echo "$MATCH" | cut -d'|' -f2)

# Discover videos
VIDEOS=()
while IFS= read -r -d '' f; do
    VIDEOS+=("$f")
done < <(find "$SOURCE_DIR" -maxdepth 1 -iname "*.mp4" -print0 2>/dev/null | sort -z)

if [ ${#VIDEOS[@]} -eq 0 ]; then
    echo -e "${YELLOW}No .mp4 files in ${SOURCE_DIR}${NC}"
    exit 0
fi

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  YouTube Bulk Queue (social-admin-v2)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "  Account: ${GREEN}${ACCOUNT_NAME}${NC} (ID: ${ACCOUNT_ID})"
echo -e "  Source:  ${SOURCE_DIR}"
echo -e "  Videos:  ${#VIDEOS[@]}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""

OK=0
FAIL=0

for video in "${VIDEOS[@]}"; do
    filename=$(basename "$video")
    base="${filename%.*}"
    slug="${base%_reel}"

    title_file="${SOURCE_DIR%/}/${slug}_title.txt"
    caption_file="${SOURCE_DIR%/}/${base}.txt"

    title=""
    if [ -f "$title_file" ]; then
        title=$(awk 'NF{print; exit}' "$title_file" | sed 's/[[:space:]]*$//')
    fi
    if [ -z "$title" ]; then
        title=$(echo "$slug" | tr '_-' '  ')
    fi

    title_preview="${title:0:60}"
    [ "${#title}" -gt 60 ] && title_preview="${title_preview}..."
    echo -ne "  ${filename}\n     → ${CYAN}${title_preview}${NC} ... "

    CURL_ARGS=(
        -s -X POST
        -H "Authorization: Bearer ${API_TOKEN}"
        -F "file=@${video}"
        -F "video_type=short"
        -F "yt_title=${title}"
        -F "title=${title}"
    )
    if [ -f "$caption_file" ]; then
        CURL_ARGS+=(-F "yt_description=<${caption_file}" -F "caption=<${caption_file}")
    fi

    RESPONSE=$(curl "${CURL_ARGS[@]}" "${API_BASE}/api/accounts/${ACCOUNT_ID}/videos/upload" 2>&1 || true)

    if echo "$RESPONSE" | python3 -c "import sys,json;d=json.loads(sys.stdin.read());sys.exit(0 if d.get('id') else 1)" 2>/dev/null; then
        vid_id=$(echo "$RESPONSE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "?")
        echo -e "${GREEN}OK${NC} (id=${vid_id})"
        OK=$((OK+1))
    else
        ERROR=$(echo "$RESPONSE" | python3 -c "import sys,json;d=json.loads(sys.stdin.read());print(d.get('detail') or d.get('error') or 'unknown')" 2>/dev/null || echo "invalid response")
        echo -e "${RED}FAIL: ${ERROR}${NC}"
        FAIL=$((FAIL+1))
    fi
done

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "  Result: ${GREEN}${OK} OK${NC} / ${RED}${FAIL} failed${NC} / ${#VIDEOS[@]} total"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"

# Cleanup only if all OK and in /tmp/upload (match helper convention)
if [ "$NO_CLEANUP" != "true" ] && [ $FAIL -eq 0 ] && [[ "$SOURCE_DIR" =~ ^/tmp/upload/?$ ]]; then
    rm -f "${SOURCE_DIR%/}"/*.mp4 "${SOURCE_DIR%/}"/*.txt "${SOURCE_DIR%/}"/*.srt
    echo -e "  ${CYAN}Cleaned up ${SOURCE_DIR}${NC}"
fi

[ $FAIL -gt 0 ] && exit 1
exit 0
