#!/bin/bash
#
# Social Media Manager - Film Upload Script
# Prześlij długie filmy poziome na serwer z poziomu lokalnego komputera.
# Film zostanie zakolejkowany do automatycznej publikacji na YouTube i/lub Facebooku.
#
# ╔═══════════════════════════════════════════════════════════════════════╗
# ║  CO TO ROBI                                                         ║
# ║                                                                     ║
# ║  1. Przesyła film (+ miniaturkę + napisy) na serwer przez SCP      ║
# ║  2. Rejestruje film w systemie przez API                            ║
# ║  3. Scheduler automatycznie opublikuje film w zaplanowanym terminie ║
# ╚═══════════════════════════════════════════════════════════════════════╝
#
# WYMAGANE PLIKI:
#   film.mp4                — film wideo (wymagany)
#                             formaty: mp4, mov, avi, mkv, webm
#                             max rozmiar: 5 GB
#
# OPCJONALNE PLIKI (wykrywane automatycznie po nazwie):
#   film.jpg/.png/.webp     — miniaturka (YouTube)
#                             zalecany rozmiar: 1280x720, max 2 MB
#   film.srt/.vtt           — napisy (przesyłane na YT i FB, język: polski)
#   film_fb.txt             — opis na Facebooka (pełny tekst)
#   film_yt.txt             — opis na YouTube (max 5000 znaków)
#   film_title.txt          — tytuł filmu (pierwsza linia pliku)
#   film_tags.txt           — tagi YouTube (po jednym w linii lub po przecinku)
#
#   Jeśli zamiast osobnych _fb.txt i _yt.txt jest jeden film.txt,
#   zostanie użyty jako opis na obie platformy.
#
# PARAMETRY:
#   --fb <KONTO>            — konto Facebook (nazwa lub ID)
#   --fb-date <DATA>        — data publikacji na FB (YYYY-MM-DD HH:MM)
#   --yt <KONTO>            — konto YouTube (nazwa lub ID)
#   --yt-date <DATA>        — data publikacji na YT (YYYY-MM-DD HH:MM)
#   --title <TYTUŁ>         — tytuł filmu (nadpisuje _title.txt)
#   --category <ID>         — kategoria YouTube (domyślnie: 22 = People & Blogs)
#   --privacy <TYP>         — prywatność YT: public/unlisted/private (domyślnie: public)
#   --tags <TAGI>           — tagi YouTube rozdzielone przecinkami (nadpisuje _tags.txt)
#
# UŻYCIE:
#   film_upload.sh <PLIK_WIDEO> [OPCJE]
#   film_upload.sh --list                    — pokaż dostępne konta
#   film_upload.sh --help                    — ta instrukcja
#
# PRZYKŁADY:
#   # Film z automatycznym harmonogramem (konta i daty z ustawień)
#   film_upload.sh film.mp4
#
#   # Film na YouTube i Facebooka z datami publikacji (override)
#   film_upload.sh film.mp4 \
#       --yt roleplayinglife --yt-date "2026-05-01 18:00" \
#       --fb "Świadek Dziejów" --fb-date "2026-05-01 12:00"
#
#   # Tylko YouTube, natychmiastowa publikacja
#   film_upload.sh film.mp4 --yt rpl --yt-date "now"
#
#   # Tylko Facebook
#   film_upload.sh film.mp4 --fb crewly --fb-date "2026-05-10 15:00"
#
#   # Z tytułem i tagami z linii poleceń
#   film_upload.sh film.mp4 --yt rpl --yt-date "2026-05-01 18:00" \
#       --title "Mój film" --tags "historia,dokument,polska"
#
# ZMIENNE ŚRODOWISKOWE:
#   SMM_API_TOKEN           — token API (wymagany, lub w .env na serwerze)
#   SMM_SSH_HOST            — host SSH (np. user@server.com)
#   SMM_REMOTE_PATH         — ścieżka do aplikacji na serwerze
#                             (domyślnie: /var/www/roleplayingtech.com/html/social-admin-v2)
#
# STRUKTURA PLIKÓW — PRZYKŁAD:
#   moj_film/
#   ├── historia_polski.mp4           # film (wymagany)
#   ├── historia_polski.jpg           # miniaturka YouTube (opcjonalnie)
#   ├── historia_polski.srt           # napisy PL (opcjonalnie)
#   ├── historia_polski_fb.txt        # opis Facebook (opcjonalnie)
#   ├── historia_polski_yt.txt        # opis YouTube (opcjonalnie)
#   ├── historia_polski_title.txt     # tytuł (opcjonalnie)
#   └── historia_polski_tags.txt      # tagi YT (opcjonalnie)
#

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
API_BASE="http://127.0.0.1:8902"

# Load token
if [ -z "${SMM_API_TOKEN:-}" ] && [ -f "${APP_DIR}/.env" ]; then
    SMM_API_TOKEN=$(grep -E '^SMM_API_TOKEN=' "${APP_DIR}/.env" | cut -d'=' -f2-)
fi
API_TOKEN="${SMM_API_TOKEN:?Set SMM_API_TOKEN (or add to .env)}"

# ── Colors ───────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# ── Help ─────────────────────────────────────────────────────────────

show_help() {
    sed -n '2,/^$/{ s/^# \?//; p }' "$0"
    exit 0
}

# ── --list mode ──────────────────────────────────────────────────────

if [ "${1:-}" = "--list" ]; then
    echo -e "${BLUE}Dostępne konta do publikacji filmów:${NC}"
    echo ""
    curl -sf -H "Authorization: Bearer ${API_TOKEN}" "${API_BASE}/api/accounts" | \
        python3 -c "
import sys, json
accounts = json.load(sys.stdin)
fb = [a for a in accounts if a.get('fb_page_id')]
yt = [a for a in accounts if a.get('yt_client_id')]
print('  Facebook:')
for a in fb:
    print(f'    [{a[\"id\"]}] {a[\"name\"]}')
if not fb:
    print('    (brak)')
print()
print('  YouTube:')
for a in yt:
    print(f'    [{a[\"id\"]}] {a[\"name\"]}')
if not yt:
    print('    (brak)')
"
    echo ""
    echo -e "${BLUE}Aliasy:${NC}"
    echo "  swiadek-dziejow, swiadek-jutra, roleplayinglife/rpl, crewly"
    exit 0
fi

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    show_help
fi

# ── Parse arguments ─────────────────────────────────────────────────

VIDEO_FILE=""
FB_ACCOUNT=""
FB_DATE=""
YT_ACCOUNT=""
YT_DATE=""
TITLE=""
CATEGORY="22"
PRIVACY="public"
TAGS=""

while [ $# -gt 0 ]; do
    case "$1" in
        --fb)       FB_ACCOUNT="$2"; shift 2 ;;
        --fb-date)  FB_DATE="$2"; shift 2 ;;
        --yt)       YT_ACCOUNT="$2"; shift 2 ;;
        --yt-date)  YT_DATE="$2"; shift 2 ;;
        --title)    TITLE="$2"; shift 2 ;;
        --category) CATEGORY="$2"; shift 2 ;;
        --privacy)  PRIVACY="$2"; shift 2 ;;
        --tags)     TAGS="$2"; shift 2 ;;
        --list)     exec "$0" --list ;;
        --help|-h)  show_help ;;
        -*)         echo -e "${RED}Nieznana opcja: $1${NC}"; exit 1 ;;
        *)
            if [ -z "$VIDEO_FILE" ]; then
                VIDEO_FILE="$1"
            else
                echo -e "${RED}Za dużo argumentów pozycyjnych${NC}"
                exit 1
            fi
            shift ;;
    esac
done

# ── Validate ─────────────────────────────────────────────────────────

if [ -z "$VIDEO_FILE" ]; then
    echo -e "${RED}Brak pliku wideo${NC}"
    echo ""
    echo "Użycie: $0 <PLIK_WIDEO> [OPCJE]"
    echo "        $0 --list"
    echo "        $0 --help"
    exit 1
fi

if [ ! -f "$VIDEO_FILE" ]; then
    echo -e "${RED}Plik nie istnieje: $VIDEO_FILE${NC}"
    exit 1
fi

if [ -z "$FB_ACCOUNT" ] && [ -z "$YT_ACCOUNT" ]; then
    echo -e "${YELLOW}Brak --fb/--yt — konta i daty zostaną przypisane z domyślnego harmonogramu filmów${NC}"
fi

EXT="${VIDEO_FILE##*.}"
EXT_LOWER=$(echo "$EXT" | tr '[:upper:]' '[:lower:]')
if [[ ! "$EXT_LOWER" =~ ^(mp4|mov|avi|mkv|webm)$ ]]; then
    echo -e "${RED}Nieobsługiwany format wideo: .$EXT_LOWER${NC}"
    echo "Obsługiwane: mp4, mov, avi, mkv, webm"
    exit 1
fi

if [[ ! "$PRIVACY" =~ ^(public|unlisted|private)$ ]]; then
    echo -e "${RED}Nieznana prywatność: $PRIVACY (dozwolone: public, unlisted, private)${NC}"
    exit 1
fi

# ── API check ────────────────────────────────────────────────────────

if ! curl -sf "${API_BASE}/health" > /dev/null 2>&1; then
    echo -e "${RED}API nie odpowiada: ${API_BASE}${NC}"
    exit 1
fi

# ── Resolve accounts ─────────────────────────────────────────────────

# Account name aliases
declare -A ALIASES=(
    ["swiadek-dziejow"]="Świadek Dziejów"
    ["swiadek-jutra"]="Świadek Jutra"
    ["roleplayinglife"]="RolePlayingLife"
    ["rpl"]="RolePlayingLife"
    ["crewly"]="crewly"
)

resolve_account() {
    local query="$1"
    local platform="$2"  # fb or yt

    local alias_key
    alias_key=$(echo "$query" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
    query="${ALIASES[$alias_key]:-$query}"

    ACCOUNTS_JSON=$(curl -sf -H "Authorization: Bearer ${API_TOKEN}" "${API_BASE}/api/accounts")

    echo "$ACCOUNTS_JSON" | python3 -c "
import sys, json, re
query = sys.argv[1]
platform = sys.argv[2]
accounts = json.load(sys.stdin)

# Filter by platform capability
if platform == 'fb':
    accounts = [a for a in accounts if a.get('fb_page_id')]
else:
    accounts = [a for a in accounts if a.get('yt_client_id')]

# Try numeric ID first
try:
    aid = int(query)
    hits = [a for a in accounts if a['id'] == aid]
except ValueError:
    qlow = re.sub(r'\s+', '', query.lower())
    hits = [a for a in accounts if qlow in re.sub(r'\s+', '', a['name'].lower())]

if len(hits) == 1:
    print(f\"{hits[0]['id']}|{hits[0]['name']}\")
elif len(hits) == 0:
    names = ', '.join(a['name'] for a in accounts) or '(brak)'
    print(f'ERROR:Nie znaleziono konta {platform.upper()} \"{query}\". Dostępne: {names}')
else:
    names = ', '.join(f\"{a['name']} (ID:{a['id']})\" for a in hits)
    print(f'ERROR:Wiele pasujących kont: {names}')
" "$query" "$platform" 2>/dev/null
}

FB_ACCOUNT_ID=""
FB_ACCOUNT_NAME=""
if [ -n "$FB_ACCOUNT" ]; then
    MATCH=$(resolve_account "$FB_ACCOUNT" "fb")
    if [[ "$MATCH" == ERROR:* ]]; then
        echo -e "${RED}${MATCH#ERROR:}${NC}"
        exit 1
    fi
    FB_ACCOUNT_ID=$(echo "$MATCH" | cut -d'|' -f1)
    FB_ACCOUNT_NAME=$(echo "$MATCH" | cut -d'|' -f2)
fi

YT_ACCOUNT_ID=""
YT_ACCOUNT_NAME=""
if [ -n "$YT_ACCOUNT" ]; then
    MATCH=$(resolve_account "$YT_ACCOUNT" "yt")
    if [[ "$MATCH" == ERROR:* ]]; then
        echo -e "${RED}${MATCH#ERROR:}${NC}"
        exit 1
    fi
    YT_ACCOUNT_ID=$(echo "$MATCH" | cut -d'|' -f1)
    YT_ACCOUNT_NAME=$(echo "$MATCH" | cut -d'|' -f2)
fi

# ── Handle "now" date ────────────────────────────────────────────────

if [ "$FB_DATE" = "now" ]; then
    FB_DATE=$(date '+%Y-%m-%d %H:%M')
fi
if [ "$YT_DATE" = "now" ]; then
    YT_DATE=$(date '+%Y-%m-%d %H:%M')
fi

# ── Detect companion files ──────────────────────────────────────────

VIDEO_DIR=$(dirname "$VIDEO_FILE")
BASENAME=$(basename "$VIDEO_FILE")
STEM="${BASENAME%.*}"

THUMBNAIL=""
for ext in jpg jpeg png webp; do
    if [ -f "${VIDEO_DIR}/${STEM}.${ext}" ]; then
        THUMBNAIL="${VIDEO_DIR}/${STEM}.${ext}"
        break
    fi
done

SUBTITLE=""
for ext in srt vtt; do
    if [ -f "${VIDEO_DIR}/${STEM}.${ext}" ]; then
        SUBTITLE="${VIDEO_DIR}/${STEM}.${ext}"
        break
    fi
done

# Descriptions: prefer _fb.txt/_yt.txt, fallback to .txt for both
FB_DESC_FILE=""
YT_DESC_FILE=""
if [ -f "${VIDEO_DIR}/${STEM}_fb.txt" ]; then
    FB_DESC_FILE="${VIDEO_DIR}/${STEM}_fb.txt"
fi
if [ -f "${VIDEO_DIR}/${STEM}_yt.txt" ]; then
    YT_DESC_FILE="${VIDEO_DIR}/${STEM}_yt.txt"
fi
# Fallback: single .txt for both
if [ -z "$FB_DESC_FILE" ] && [ -z "$YT_DESC_FILE" ] && [ -f "${VIDEO_DIR}/${STEM}.txt" ]; then
    FB_DESC_FILE="${VIDEO_DIR}/${STEM}.txt"
    YT_DESC_FILE="${VIDEO_DIR}/${STEM}.txt"
fi

# Title from file or filename
TITLE_FILE="${VIDEO_DIR}/${STEM}_title.txt"
if [ -z "$TITLE" ] && [ -f "$TITLE_FILE" ]; then
    TITLE=$(awk 'NF{print; exit}' "$TITLE_FILE" | sed 's/[[:space:]]*$//')
fi
if [ -z "$TITLE" ]; then
    TITLE=$(echo "$STEM" | tr '_-' '  ')
fi

# Tags from file or --tags
TAGS_FILE="${VIDEO_DIR}/${STEM}_tags.txt"
if [ -z "$TAGS" ] && [ -f "$TAGS_FILE" ]; then
    TAGS=$(tr '\n' ',' < "$TAGS_FILE" | sed 's/,$//')
fi

# ── Header ───────────────────────────────────────────────────────────

FILE_SIZE=$(stat -c%s "$VIDEO_FILE" 2>/dev/null || stat -f%z "$VIDEO_FILE" 2>/dev/null || echo "?")
FILE_SIZE_MB=$(python3 -c "print(f'{${FILE_SIZE}/1024/1024:.1f}')" 2>/dev/null || echo "?")

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Social Media Manager - Film Upload${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "  Film:       ${BOLD}${BASENAME}${NC} (${FILE_SIZE_MB} MB)"
echo -e "  Tytuł:      ${CYAN}${TITLE}${NC}"

if [ -n "$FB_ACCOUNT_ID" ]; then
    echo -e "  Facebook:   ${GREEN}${FB_ACCOUNT_NAME}${NC} → ${FB_DATE}"
elif [ -z "$FB_ACCOUNT" ]; then
    echo -e "  Facebook:   ${CYAN}z harmonogramu${NC}"
fi
if [ -n "$YT_ACCOUNT_ID" ]; then
    echo -e "  YouTube:    ${GREEN}${YT_ACCOUNT_NAME}${NC} → ${YT_DATE}"
    echo -e "  Prywatność: ${PRIVACY}"
    echo -e "  Kategoria:  ${CATEGORY}"
    [ -n "$TAGS" ] && echo -e "  Tagi:       ${TAGS}"
elif [ -z "$YT_ACCOUNT" ]; then
    echo -e "  YouTube:    ${CYAN}z harmonogramu${NC}"
fi

echo -e "  ─────────────────────────────────────────────────────"
[ -n "$THUMBNAIL" ] && echo -e "  Miniaturka: ${GREEN}$(basename "$THUMBNAIL")${NC}" || echo -e "  Miniaturka: ${YELLOW}brak${NC}"
[ -n "$SUBTITLE" ]  && echo -e "  Napisy:     ${GREEN}$(basename "$SUBTITLE")${NC}"  || echo -e "  Napisy:     ${YELLOW}brak${NC}"
[ -n "$FB_DESC_FILE" ] && echo -e "  Opis FB:    ${GREEN}$(basename "$FB_DESC_FILE")${NC} ($(wc -c < "$FB_DESC_FILE" | tr -d ' ') znaków)"
[ -n "$YT_DESC_FILE" ] && echo -e "  Opis YT:    ${GREEN}$(basename "$YT_DESC_FILE")${NC} ($(wc -c < "$YT_DESC_FILE" | tr -d ' ') znaków)"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# ── Upload ───────────────────────────────────────────────────────────

echo -ne "  Przesyłanie filmu... "

CURL_ARGS=(
    -s --show-error
    -X POST
    -H "Authorization: Bearer ${API_TOKEN}"
    -F "video=@${VIDEO_FILE}"
    -F "title=${TITLE}"
    -F "yt_category=${CATEGORY}"
    -F "yt_privacy=${PRIVACY}"
)

if [ -n "$THUMBNAIL" ]; then
    CURL_ARGS+=(-F "thumbnail=@${THUMBNAIL}")
fi

if [ -n "$SUBTITLE" ]; then
    CURL_ARGS+=(-F "subtitle=@${SUBTITLE}")
fi

if [ -n "$FB_DESC_FILE" ]; then
    CURL_ARGS+=(-F "fb_description=<${FB_DESC_FILE}")
fi

if [ -n "$YT_DESC_FILE" ]; then
    CURL_ARGS+=(-F "yt_description=<${YT_DESC_FILE}")
fi

if [ -n "$TAGS" ]; then
    CURL_ARGS+=(-F "yt_tags=${TAGS}")
fi

if [ -n "$FB_ACCOUNT_ID" ]; then
    CURL_ARGS+=(-F "fb_account_id=${FB_ACCOUNT_ID}")
    [ -n "$FB_DATE" ] && CURL_ARGS+=(-F "fb_publish_date=${FB_DATE}")
fi

if [ -n "$YT_ACCOUNT_ID" ]; then
    CURL_ARGS+=(-F "yt_account_id=${YT_ACCOUNT_ID}")
    [ -n "$YT_DATE" ] && CURL_ARGS+=(-F "yt_publish_date=${YT_DATE}")
fi

RESPONSE=$(curl "${CURL_ARGS[@]}" "${API_BASE}/api/films/upload" 2>&1)

# ── Result ───────────────────────────────────────────────────────────

FILM_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

if [ -n "$FILM_ID" ] && [ "$FILM_ID" != "None" ]; then
    echo -e "${GREEN}OK${NC}"
    echo ""
    echo -e "  Film ID:    ${BOLD}${FILM_ID}${NC}"

    # Show scheduled publish info from API response (covers both explicit and auto-assigned)
    ASSIGNED=$(echo "$RESPONSE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
fb_date = d.get('fb_publish_date') or ''
fb_status = d.get('fb_status') or ''
fb_acc = d.get('fb_account_id') or ''
yt_date = d.get('yt_publish_date') or ''
yt_status = d.get('yt_status') or ''
yt_acc = d.get('yt_account_id') or ''
print(f'{fb_acc}|{fb_date}|{fb_status}|{yt_acc}|{yt_date}|{yt_status}')
" 2>/dev/null || echo "||||")

    IFS='|' read -r R_FB_ACC R_FB_DATE R_FB_STATUS R_YT_ACC R_YT_DATE R_YT_STATUS <<< "$ASSIGNED"

    if [ -n "$R_FB_DATE" ] && [ "$R_FB_STATUS" = "scheduled" ]; then
        echo -e "  FB:         ${GREEN}zaplanowany${NC} → konto #${R_FB_ACC} @ ${R_FB_DATE}"
    fi
    if [ -n "$R_YT_DATE" ] && [ "$R_YT_STATUS" = "scheduled" ]; then
        echo -e "  YT:         ${GREEN}zaplanowany${NC} → konto #${R_YT_ACC} @ ${R_YT_DATE}"
    fi
    echo ""
    echo -e "${GREEN}Film został przesłany i zakolejkowany do publikacji.${NC}"
else
    echo -e "${RED}BŁĄD${NC}"
    ERROR=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail','') or d.get('error','unknown'))" 2>/dev/null || echo "$RESPONSE")
    echo -e "  ${RED}${ERROR}${NC}"
    exit 1
fi
