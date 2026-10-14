#!/usr/bin/env bash
#
# NC Code Analyser - one-shot Linux setup script.
# Tested on Ubuntu 22.04 / 24.04 and Debian 12. For RHEL/Fedora replace
# `apt-get` blocks with the equivalent `dnf` commands.
#
# Usage:  sudo bash deploy/setup.sh
#
set -euo pipefail

APP_USER="${APP_USER:-ncanalyser}"
APP_DIR="${APP_DIR:-/opt/nc-code-analyser}"
OLLAMA_MODEL="${OLLAMA_MODEL:-mistral}"

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-dev python3-pip \
    build-essential git curl ca-certificates \
    libmagic1 \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
    libffi-dev shared-mime-info fonts-dejavu

echo "==> Creating service user '${APP_USER}'"
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

echo "==> Copying source to ${APP_DIR}"
mkdir -p "${APP_DIR}"
# Sync everything from the directory this script lives in (../) into APP_DIR.
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${SRC_DIR}" != "${APP_DIR}" ]; then
    rsync -a --delete \
        --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
        --exclude 'data/uploads/*' --exclude 'data/reports/*' \
        "${SRC_DIR}/" "${APP_DIR}/"
fi
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

echo "==> Creating Python virtualenv"
sudo -u "${APP_USER}" python3 -m venv "${APP_DIR}/.venv"
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install --upgrade pip wheel
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements-linux.txt"

echo "==> Ensuring data directories exist"
sudo -u "${APP_USER}" mkdir -p \
    "${APP_DIR}/data/uploads" \
    "${APP_DIR}/data/baselines" \
    "${APP_DIR}/data/reports"

echo "==> Seeding .env if missing"
if [ ! -f "${APP_DIR}/.env" ]; then
    cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    sed -i 's/^DEBUG=.*/DEBUG=false/' "${APP_DIR}/.env"
    chown "${APP_USER}:${APP_USER}" "${APP_DIR}/.env"
    echo "    -> ${APP_DIR}/.env created. Edit it to set OLLAMA_MODEL etc."
fi

echo "==> Installing Ollama (if missing)"
if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
fi
systemctl enable --now ollama || true

echo "==> Pulling Ollama model: ${OLLAMA_MODEL}"
ollama pull "${OLLAMA_MODEL}" || echo "WARN: model pull failed - pull manually later."

echo "==> Installing systemd unit"
install -m 0644 "${APP_DIR}/deploy/nc-analyser.service" /etc/systemd/system/nc-analyser.service
systemctl daemon-reload
systemctl enable --now nc-analyser.service

echo
echo "==> Done."
echo "    Service status:  systemctl status nc-analyser"
echo "    Logs:            journalctl -u nc-analyser -f"
HOST_IP=$(hostname -I | awk '{print $1}')
echo "    Open in browser: http://${HOST_IP}:8000/"
