#!/bin/bash
#
# Social Media Manager - Remote Film Upload
# Prześlij długi film z lokalnego komputera na serwer przez SSH/SCP.
#
# Skrypt kopiuje pliki na serwer, a następnie uruchamia film_upload.sh po stronie serwera.
#
# UŻYCIE:
#   ./remote_film_upload.sh <PLIK_WIDEO> [OPCJE]
#   ./remote_film_upload.sh --list
#
# OPCJE — identyczne jak w film_upload.sh:
#   --fb <KONTO>            — konto Facebook
#   --fb-date <DATA>        — data publikacji FB (YYYY-MM-DD HH:MM lub "now")
#   --yt <KONTO>            — konto YouTube
#   --yt-date <DATA>        — data publikacji YT (YYYY-MM-DD HH:MM lub "now")
#   --title <TYTUŁ>         — tytuł filmu
#   --category <ID>         — kategoria YouTube (domyślnie: 22)
#   --privacy <TYP>         — prywatność YT: public/unlisted/private
#   --tags <TAGI>           — tagi YouTube (przecinkami)
#
# PLIKI TOWARZYSZĄCE (automatycznie wykrywane i przesyłane):
#   film.jpg/.png/.webp     — miniaturka
#   film.srt/.vtt           — napisy
#   film_fb.txt             — opis Facebook
#   film_yt.txt             — opis YouTube
#   film.txt                — opis wspólny (jeśli brak _fb/_yt)
#   film_title.txt          — tytuł
#   film_tags.txt           — tagi YouTube
#
# PRZYKŁADY:
#   ./remote_film_upload.sh film.mp4 \
#       --yt roleplayinglife --yt-date "2026-05-01 18:00" \
#       --fb "swiadek-dziejow" --fb-date "2026-05-01 12:00"
#
#   ./remote_film_upload.sh film.mp4 --fb crewly --fb-date "now"
#
# ZMIENNE ŚRODOWISKOWE:
#   SMM_SSH_HOST            — host SSH (wymagany, np. user@server.com)
#   SMM_REMOTE_PATH         — ścieżka na serwerze
#                             (domyślnie: /var/www/roleplayingtech.com/html/social-admin-v2)
#

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────

SERVER="${SMM_SSH_HOST:?Ustaw SMM_SSH_HOST (np. user@server.com)}"
REMOTE_BASE="${SMM_REMOTE_PATH:-/var/www/roleplayingtech.com/html/social-admin-v2}"
REMOTE_TMP="/tmp/smm_film_upload_$$"

# ── Colors ───────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

# ── --list mode (forward to remote) ─────────────────────────────────

if [ "${1:-}" = "--list" ]; then
    ssh "$SERVER" "${REMOTE_BASE}/scripts/film_upload.sh --list"
    exit 0
fi

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    sed -n '2,/^$/{ s/^# \?//; p }' "$0"
    exit 0
fi

# ── Parse arguments — separate VIDEO_FILE from options ──────────────

VIDEO_FILE=""
PASS_ARGS=()

# First pass: find the video file
for arg in "$@"; do
    if [ -z "$VIDEO_FILE" ] && [[ ! "$arg" == --* ]] && [ -f "$arg" ]; then
        VIDEO_FILE="$arg"
    fi
done

if [ -z "$VIDEO_FILE" ]; then
    echo -e "${RED}Brak pliku wideo${NC}"
    echo "Użycie: $0 <PLIK_WIDEO> [OPCJE]"
    echo "        $0 --list"
    exit 1
fi

if [ ! -f "$VIDEO_FILE" ]; then
    echo -e "${RED}Plik nie istnieje: $VIDEO_FILE${NC}"
    exit 1
fi

# Rebuild args, replacing local video path with remote path
VIDEO_DIR=$(cd "$(dirname "$VIDEO_FILE")" && pwd)
BASENAME=$(basename "$VIDEO_FILE")
STEM="${BASENAME%.*}"

# ── Discover companion files ────────────────────────────────────────

FILES_TO_COPY=("$VIDEO_FILE")

for ext in jpg jpeg png webp; do
    [ -f "${VIDEO_DIR}/${STEM}.${ext}" ] && FILES_TO_COPY+=("${VIDEO_DIR}/${STEM}.${ext}") && break
done

for ext in srt vtt; do
    [ -f "${VIDEO_DIR}/${STEM}.${ext}" ] && FILES_TO_COPY+=("${VIDEO_DIR}/${STEM}.${ext}") && break
done

for suffix in _fb.txt _yt.txt .txt _title.txt _tags.txt; do
    [ -f "${VIDEO_DIR}/${STEM}${suffix}" ] && FILES_TO_COPY+=("${VIDEO_DIR}/${STEM}${suffix}")
done

# ── Header ───────────────────────────────────────────────────────────

FILE_SIZE=$(stat -c%s "$VIDEO_FILE" 2>/dev/null || stat -f%z "$VIDEO_FILE" 2>/dev/null || echo "?")
FILE_SIZE_MB=$(python3 -c "print(f'{${FILE_SIZE}/1024/1024:.1f}')" 2>/dev/null || echo "?")

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Remote Film Upload → ${SERVER}${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "  Film:    ${BASENAME} (${FILE_SIZE_MB} MB)"
echo -e "  Pliki:   ${#FILES_TO_COPY[@]} (film + towarzyszące)"
for f in "${FILES_TO_COPY[@]}"; do
    echo -e "           ${CYAN}$(basename "$f")${NC}"
done
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# ── Step 1: Create temp dir on server ────────────────────────────────

echo -e "${GREEN}[1/3]${NC} Tworzenie katalogu tymczasowego na serwerze..."
ssh "$SERVER" "mkdir -p ${REMOTE_TMP}"

# ── Step 2: Copy files via SCP ───────────────────────────────────────

echo -e "${GREEN}[2/3]${NC} Kopiowanie plików (${FILE_SIZE_MB} MB)..."
for f in "${FILES_TO_COPY[@]}"; do
    echo -ne "  $(basename "$f") ... "
    scp -q "$f" "${SERVER}:${REMOTE_TMP}/"
    echo -e "${GREEN}OK${NC}"
done

# ── Step 3: Run film_upload.sh on server ─────────────────────────────

echo -e "${GREEN}[3/3]${NC} Uruchamianie uploadu na serwerze..."
echo ""

# Build remote command: forward all CLI options + point to remote video file
REMOTE_ARGS=("${REMOTE_BASE}/scripts/film_upload.sh" "${REMOTE_TMP}/${BASENAME}")

# Forward all original args except the video file
SKIP_NEXT=false
for arg in "$@"; do
    if $SKIP_NEXT; then
        SKIP_NEXT=false
        continue
    fi
    # Skip the video file argument
    if [ "$arg" = "$VIDEO_FILE" ]; then
        continue
    fi
    REMOTE_ARGS+=("$arg")
done

# Quote args for SSH
QUOTED_CMD=""
for arg in "${REMOTE_ARGS[@]}"; do
    QUOTED_CMD+="$(printf ' %q' "$arg")"
done

ssh "$SERVER" "$QUOTED_CMD"
EXIT_CODE=$?

# ── Cleanup ──────────────────────────────────────────────────────────

echo ""
echo -ne "Czyszczenie plików tymczasowych... "
ssh "$SERVER" "rm -rf ${REMOTE_TMP}"
echo -e "${GREEN}OK${NC}"

exit $EXIT_CODE
