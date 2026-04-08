#!/bin/bash
#
# Social Media Manager - Bulk Upload Script
# Hurtowe wgrywanie filmów na serwer przez SSH
#
# UŻYCIE:
#   ./bulk_upload.sh <ACCOUNT_ID> <KATALOG_Z_FILMAMI> [TYP]
#
# PARAMETRY:
#   ACCOUNT_ID          - ID konta (widoczne w dashboardzie w zakładce Ustawienia)
#   KATALOG_Z_FILMAMI   - ścieżka do katalogu z plikami .mp4 (i opcjonalnie .txt)
#   TYP                 - typ wideo: reel, story, short, video (domyślnie: reel)
#
# STRUKTURA PLIKÓW:
#   Skrypt szuka plików .mp4 w podanym katalogu. Dla każdego pliku .mp4
#   może istnieć plik .txt o tej samej nazwie z opisem (caption)
#   oraz plik .srt z napisami (YouTube).
#
#   Przykład:
#     filmy/
#     ├── historia_01.mp4          <- film
#     ├── historia_01.txt          <- opis (caption) do posta
#     ├── historia_01.srt          <- napisy SRT (YouTube)
#     ├── historia_02.mp4          <- film (bez opisu)
#     └── historia_03.mp4          <- film
#
# PRZYKŁADY:
#   # Wgraj wszystkie filmy z katalogu jako Reels na konto #1
#   ./bulk_upload.sh 1 ./filmy/
#
#   # Wgraj jako YouTube Shorts na konto #4
#   ./bulk_upload.sh 4 ./filmy/ short
#
#   # Wgraj normalne filmy YouTube
#   ./bulk_upload.sh 4 ./filmy/ video
#
#   # Bezpośrednio na serwerze (po SSH)
#   ssh admin@roleplayingtech.com
#   cd /var/www/roleplayingtech.com/html/social-admin-v2/scripts
#   ./bulk_upload.sh 1 /tmp/filmy/ reel
#
# ZDALNY UPLOAD (ze swojego komputera):
#   # Krok 1: Skopiuj pliki na serwer
#   scp -r ./filmy/ admin@roleplayingtech.com:/tmp/upload/
#
#   # Krok 2: Uruchom skrypt na serwerze
#   ssh admin@roleplayingtech.com 'cd /var/www/roleplayingtech.com/html/social-admin-v2/scripts && ./bulk_upload.sh 1 /tmp/upload/ reel'
#
#   # Albo jednolinijkowo z przesyłaniem i kolejkowaniem:
#   scp -r ./filmy/ admin@roleplayingtech.com:/tmp/upload/ && \
#   ssh admin@roleplayingtech.com '/var/www/roleplayingtech.com/html/social-admin-v2/scripts/bulk_upload.sh 1 /tmp/upload/'
#

set -euo pipefail

# ── Konfiguracja ─────────────────────────────────────────────────────

API_BASE="http://127.0.0.1:8902"
API_TOKEN="${SMM_API_TOKEN:?Set SMM_API_TOKEN environment variable}"
SUPPORTED_FORMATS="mp4 mov avi mkv webm"

# ── Kolory ───────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ── Walidacja argumentów ─────────────────────────────────────────────

if [ $# -lt 2 ]; then
    echo -e "${RED}BŁĄD: Za mało argumentów${NC}"
    echo ""
    echo "Użycie: $0 <ACCOUNT_ID> <KATALOG> [TYP]"
    echo ""
    echo "  ACCOUNT_ID  - ID konta (np. 1, 2, 3)"
    echo "  KATALOG     - ścieżka do katalogu z filmami"
    echo "  TYP         - reel|story|short|video (domyślnie: reel)"
    echo ""
    echo "Przykład: $0 1 ./filmy/ reel"
    exit 1
fi

ACCOUNT_ID="$1"
SOURCE_DIR="$2"
VIDEO_TYPE="${3:-reel}"

# Walidacja typu
if [[ ! "$VIDEO_TYPE" =~ ^(reel|story|short|video)$ ]]; then
    echo -e "${RED}BŁĄD: Nieznany typ '$VIDEO_TYPE'. Dozwolone: reel, story, short, video${NC}"
    exit 1
fi

# Walidacja katalogu
if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}BŁĄD: Katalog '$SOURCE_DIR' nie istnieje${NC}"
    exit 1
fi

# Sprawdź API
if ! curl -sf "${API_BASE}/health" > /dev/null 2>&1; then
    echo -e "${RED}BŁĄD: API nie odpowiada na ${API_BASE}${NC}"
    echo "Upewnij się, że serwis social-media-manager jest uruchomiony."
    exit 1
fi

# Sprawdź konto
ACCOUNT_INFO=$(curl -sf -H "Authorization: Bearer ${API_TOKEN}" "${API_BASE}/api/accounts/${ACCOUNT_ID}" 2>/dev/null || true)
if [ -z "$ACCOUNT_INFO" ] || echo "$ACCOUNT_INFO" | grep -q '"detail"'; then
    echo -e "${RED}BŁĄD: Konto o ID ${ACCOUNT_ID} nie istnieje${NC}"
    exit 1
fi

ACCOUNT_NAME=$(echo "$ACCOUNT_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name','?'))" 2>/dev/null || echo "?")
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Social Media Manager - Bulk Upload${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "  Konto:    ${GREEN}${ACCOUNT_NAME}${NC} (ID: ${ACCOUNT_ID})"
echo -e "  Katalog:  ${SOURCE_DIR}"
echo -e "  Typ:      ${VIDEO_TYPE}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"

# ── Znajdź pliki wideo ───────────────────────────────────────────────

VIDEO_FILES=()
for ext in $SUPPORTED_FORMATS; do
    while IFS= read -r -d '' file; do
        VIDEO_FILES+=("$file")
    done < <(find "$SOURCE_DIR" -maxdepth 1 -iname "*.${ext}" -print0 2>/dev/null | sort -z)
done

if [ ${#VIDEO_FILES[@]} -eq 0 ]; then
    echo -e "${YELLOW}Brak plików wideo w katalogu ${SOURCE_DIR}${NC}"
    echo "Obsługiwane formaty: ${SUPPORTED_FORMATS}"
    exit 0
fi

echo -e "\nZnaleziono ${GREEN}${#VIDEO_FILES[@]}${NC} plików wideo."
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

    echo -ne "  [${NUM}/${TOTAL}] ${FILENAME} ... "

    # Przygotuj argumenty curl
    CURL_ARGS=(
        -sf
        -X POST
        -H "Authorization: Bearer ${API_TOKEN}"
        -F "files=@${VIDEO_FILE}"
        -F "video_type=${VIDEO_TYPE}"
    )

    # Sprawdź czy jest plik z opisem (.txt)
    CAPTION_FILE=""
    if [ -f "${SOURCE_DIR}/${BASENAME}.txt" ]; then
        CAPTION_FILE="${SOURCE_DIR}/${BASENAME}.txt"
        CURL_ARGS+=(-F "files=@${CAPTION_FILE}")
    fi

    # Sprawdź czy jest plik z napisami (.srt)
    SUBTITLE_FILE=""
    if [ -f "${SOURCE_DIR}/${BASENAME}.srt" ]; then
        SUBTITLE_FILE="${SOURCE_DIR}/${BASENAME}.srt"
        CURL_ARGS+=(-F "files=@${SUBTITLE_FILE}")
    fi

    # Upload
    RESPONSE=$(curl "${CURL_ARGS[@]}" "${API_BASE}/api/accounts/${ACCOUNT_ID}/videos/bulk-upload" 2>&1 || true)

    if echo "$RESPONSE" | grep -q '"ok": true\|"ok":true'; then
        EXTRAS=""
        [ -n "$CAPTION_FILE" ] && EXTRAS=" +caption"
        [ -n "$SUBTITLE_FILE" ] && EXTRAS="${EXTRAS} +srt"
        echo -e "${GREEN}OK${NC}${EXTRAS}"
        SUCCESS=$((SUCCESS + 1))
    else
        ERROR=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail','') or d.get('results',[{}])[0].get('error','unknown'))" 2>/dev/null || echo "unknown error")
        echo -e "${RED}BŁĄD: ${ERROR}${NC}"
        FAILED=$((FAILED + 1))
    fi
done

# ── Podsumowanie ─────────────────────────────────────────────────────

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "  Wynik: ${GREEN}${SUCCESS} OK${NC} / ${RED}${FAILED} błędów${NC} / ${TOTAL} total"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"

if [ $FAILED -gt 0 ]; then
    exit 1
fi
