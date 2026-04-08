#!/bin/bash
#
# Social Media Manager - Remote Upload Script
# Wgraj filmy ze swojego komputera na serwer jednym poleceniem.
#
# UŻYCIE:
#   ./remote_upload.sh <ACCOUNT_ID> <KATALOG_LUB_PLIKI> [TYP]
#
# PRZYKŁADY:
#   # Wgraj cały katalog z filmami
#   ./remote_upload.sh 1 ./filmy/
#
#   # Wgraj pojedynczy plik
#   ./remote_upload.sh 1 ./film.mp4
#
#   # Wgraj kilka plików
#   ./remote_upload.sh 1 ./film1.mp4 ./film2.mp4
#
#   # Wgraj jako YouTube Shorts
#   ./remote_upload.sh 4 ./shorty/ short
#
# CO ROBI:
#   1. Kopiuje pliki na serwer przez SCP
#   2. Uruchamia bulk_upload.sh na serwerze
#   3. Czyści pliki tymczasowe
#

set -euo pipefail

# ── Konfiguracja (dostosuj do siebie) ────────────────────────────────

SERVER="admin@roleplayingtech.com"
REMOTE_BASE="/var/www/roleplayingtech.com/html/social-admin-v2"
REMOTE_TMP="/tmp/smm_upload_$$"

# ── Kolory ───────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# ── Walidacja ────────────────────────────────────────────────────────

if [ $# -lt 2 ]; then
    echo -e "${RED}Użycie: $0 <ACCOUNT_ID> <KATALOG_LUB_PLIKI...> [reel|story|short|video]${NC}"
    exit 1
fi

ACCOUNT_ID="$1"
shift

# Sprawdź czy ostatni argument to typ
LAST_ARG="${!#}"
VIDEO_TYPE="reel"
ARGS=("$@")

if [[ "$LAST_ARG" =~ ^(reel|story|short|video)$ ]]; then
    VIDEO_TYPE="$LAST_ARG"
    unset 'ARGS[${#ARGS[@]}-1]'
fi

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Remote Upload → Konto #${ACCOUNT_ID} (typ: ${VIDEO_TYPE})${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"

# ── Krok 1: Kopiuj pliki na serwer ──────────────────────────────────

echo -e "\n${GREEN}[1/3]${NC} Tworzenie katalogu tymczasowego na serwerze..."
ssh "$SERVER" "mkdir -p ${REMOTE_TMP}"

echo -e "${GREEN}[2/3]${NC} Kopiowanie plików..."
for src in "${ARGS[@]}"; do
    if [ -d "$src" ]; then
        echo "  Katalog: $src"
        scp -r "$src"/* "${SERVER}:${REMOTE_TMP}/" 2>/dev/null || \
        scp -r "$src"/*.* "${SERVER}:${REMOTE_TMP}/" 2>/dev/null || true
    elif [ -f "$src" ]; then
        echo "  Plik: $(basename "$src")"
        scp "$src" "${SERVER}:${REMOTE_TMP}/"
    else
        echo -e "  ${RED}Pominięto: $src (nie istnieje)${NC}"
    fi
done

# ── Krok 2: Uruchom upload na serwerze ──────────────────────────────

echo -e "${GREEN}[3/3]${NC} Uruchamianie uploadu na serwerze..."
echo ""
ssh "$SERVER" "${REMOTE_BASE}/scripts/bulk_upload.sh ${ACCOUNT_ID} ${REMOTE_TMP} ${VIDEO_TYPE}"

# ── Krok 3: Cleanup ─────────────────────────────────────────────────

echo ""
echo -e "Czyszczenie plików tymczasowych..."
ssh "$SERVER" "rm -rf ${REMOTE_TMP}"

echo -e "${GREEN}Gotowe!${NC}"
