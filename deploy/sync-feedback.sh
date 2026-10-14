#!/usr/bin/env bash
#
# sync-feedback.sh
#
# Copies the live feedback.json written by the running nc-analyser service
# into this cloned repo, so you can view / commit it from your dev checkout.
#
# Usage:
#   bash deploy/sync-feedback.sh             # pull live -> repo
#   bash deploy/sync-feedback.sh --dry-run   # show what would happen
#
# Live file (written by systemd service running as user 'ncanalyser'):
#   /opt/nc-code-analyser/feedback.json
#
# Repo destination (this clone):
#   <repo-root>/feedback.json
#
set -euo pipefail

LIVE_FILE="${LIVE_FILE:-/opt/nc-code-analyser/feedback.json}"

# Resolve the repo root as the parent of the directory containing this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEST_FILE="${REPO_ROOT}/feedback.json"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]]; then
    DRY_RUN=1
fi

log() { printf '[sync-feedback] %s\n' "$*"; }
die() { printf '[sync-feedback] ERROR: %s\n' "$*" >&2; exit 1; }

# 1. Live file must exist.
if [[ ! -e "${LIVE_FILE}" ]]; then
    die "live file not found: ${LIVE_FILE} (is nc-analyser deployed?)"
fi

# 2. Need sudo to read it (owned by 'ncanalyser', mode 644 usually, but be safe).
SUDO=""
if [[ ! -r "${LIVE_FILE}" ]]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        die "cannot read ${LIVE_FILE} and sudo is not available"
    fi
fi

LIVE_COUNT="$(${SUDO} python3 -c "import json,sys; print(len(json.load(open('${LIVE_FILE}'))))" 2>/dev/null || echo "?")"
LIVE_MTIME="$(${SUDO} stat -c '%y' "${LIVE_FILE}")"

log "live   : ${LIVE_FILE}"
log "         entries=${LIVE_COUNT}  modified=${LIVE_MTIME}"

if [[ -e "${DEST_FILE}" ]]; then
    DEST_COUNT="$(python3 -c "import json; print(len(json.load(open('${DEST_FILE}'))))" 2>/dev/null || echo "?")"
    DEST_MTIME="$(stat -c '%y' "${DEST_FILE}")"
    log "repo   : ${DEST_FILE}"
    log "         entries=${DEST_COUNT}  modified=${DEST_MTIME}"
else
    log "repo   : ${DEST_FILE} (does not exist yet)"
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "dry-run: would copy live -> repo (no changes made)"
    exit 0
fi

# 3. Back up the existing repo copy (single rolling backup).
if [[ -e "${DEST_FILE}" ]]; then
    cp -a "${DEST_FILE}" "${DEST_FILE}.bak"
    log "backup : ${DEST_FILE}.bak"
fi

# 4. Copy atomically: write to .tmp then mv.
TMP_FILE="${DEST_FILE}.tmp.$$"
${SUDO} cat "${LIVE_FILE}" > "${TMP_FILE}"
chmod 644 "${TMP_FILE}"
# Re-own to the current user so VS Code / git don't trip over root-owned files.
if [[ -n "${SUDO}" ]]; then
    chown "$(id -u):$(id -g)" "${TMP_FILE}" 2>/dev/null || true
fi
mv "${TMP_FILE}" "${DEST_FILE}"

NEW_COUNT="$(python3 -c "import json; print(len(json.load(open('${DEST_FILE}'))))" 2>/dev/null || echo "?")"
log "synced : ${DEST_FILE} now has ${NEW_COUNT} entries"
