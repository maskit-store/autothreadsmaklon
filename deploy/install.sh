#!/usr/bin/env bash
# Pasang bot di VPS (Ubuntu/Debian). Jalankan dari folder project: sudo bash deploy/install.sh
set -euo pipefail

APP_DIR=/opt/autothreads
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then echo "Jalankan dengan sudo"; exit 1; fi

echo "==> Install paket sistem"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip rsync

PYV=$(python3 -c 'import sys; print(sys.version_info[:2] >= (3, 10))')
if [[ "$PYV" != "True" ]]; then echo "Butuh Python 3.10+. Versi sekarang: $(python3 --version)"; exit 1; fi

echo "==> User sistem 'autothreads'"
id autothreads &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin autothreads

echo "==> Salin kode ke $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete \
  --exclude .git --exclude .venv --exclude data --exclude .env \
  --exclude persona.md --exclude knowledge.md \
  "$SRC_DIR/" "$APP_DIR/"
# persona & knowledge hanya disalin pertama kali supaya hasil edit Anda di VPS tidak tertimpa
for f in persona.md knowledge.md; do
  [[ -f "$APP_DIR/$f" ]] || cp "$SRC_DIR/$f" "$APP_DIR/$f"
done
[[ -f "$APP_DIR/.env" ]] || cp "$SRC_DIR/.env.example" "$APP_DIR/.env"
mkdir -p "$APP_DIR/data"

echo "==> Virtualenv & dependency"
[[ -d "$APP_DIR/.venv" ]] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

chown -R autothreads:autothreads "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo "==> Service systemd"
cp "$APP_DIR/deploy/autothreads.service" /etc/systemd/system/autothreads.service
systemctl daemon-reload
systemctl enable autothreads >/dev/null

if grep -qE '^(TELEGRAM_BOT_TOKEN|ANTHROPIC_API_KEY)=$' "$APP_DIR/.env"; then
  echo
  echo "!! .env belum lengkap. Edit dulu:  sudo nano $APP_DIR/.env"
  echo "   lalu jalankan:                 sudo systemctl restart autothreads"
else
  systemctl restart autothreads
  echo "==> Bot berjalan. Cek log:  sudo journalctl -u autothreads -f"
fi
