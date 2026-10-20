#!/usr/bin/env bash
# Pasang / update bot di VPS (Ubuntu/Debian).
#   Pasang atau update : sudo bash deploy/install.sh
#   Ubah token/pengaturan: sudo bash deploy/install.sh --setup
set -euo pipefail

APP_DIR=/opt/autothreads
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FORCE_SETUP=${1:-}

if [[ $EUID -ne 0 ]]; then echo "Jalankan sebagai root (tambahkan sudo di depan perintah)"; exit 1; fi

echo "==> [1/6] Install paket sistem (bisa 1-3 menit)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip rsync >/dev/null

# Cari Python 3.10+; kalau tidak ada (mis. Ubuntu 20.04), pasang python3.11 dari PPA deadsnakes
PY=""
for cand in python3 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$cand" >/dev/null && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    PY=$(command -v "$cand"); break
  fi
done
if [[ -z "$PY" ]]; then
  if grep -qi ubuntu /etc/os-release; then
    echo "==> Python bawaan terlalu lama ($(python3 --version)), memasang Python 3.11"
    apt-get install -y -qq software-properties-common >/dev/null
    add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
    apt-get update -qq
    apt-get install -y -qq python3.11 python3.11-venv >/dev/null
    PY=$(command -v python3.11)
  else
    echo "!! Butuh Python 3.10+, versi sekarang: $(python3 --version). Kirim pesan ini ke Claude."; exit 1
  fi
fi
echo "    Python: $($PY --version)"

echo "==> [2/6] User sistem 'autothreads'"
id autothreads &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin autothreads

echo "==> [3/6] Salin kode ke $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete \
  --exclude .git --exclude .venv --exclude data --exclude .env \
  --exclude persona.md --exclude knowledge.md --exclude '*.bak' \
  "$SRC_DIR/" "$APP_DIR/"
# persona & knowledge hanya disalin pertama kali supaya hasil edit Anda di VPS tidak tertimpa
for f in persona.md knowledge.md; do
  [[ -f "$APP_DIR/$f" ]] || cp "$SRC_DIR/$f" "$APP_DIR/$f"
done
[[ -f "$APP_DIR/.env" ]] || cp "$SRC_DIR/.env.example" "$APP_DIR/.env"
mkdir -p "$APP_DIR/data"

echo "==> [4/6] Virtualenv & library (bisa 1-2 menit)"
if [[ -x "$APP_DIR/.venv/bin/python" ]] && ! "$APP_DIR/.venv/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  rm -rf "$APP_DIR/.venv"
fi
[[ -d "$APP_DIR/.venv" ]] || "$PY" -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> [5/6] Pengaturan token"
systemctl stop autothreads 2>/dev/null || true   # supaya wizard bisa membaca pesan /start di Telegram
if [[ "$FORCE_SETUP" == "--setup" ]] || grep -qE '^(TELEGRAM_BOT_TOKEN|TELEGRAM_ADMIN_IDS|THREADS_ACCESS_TOKEN|ANTHROPIC_API_KEY)=$' "$APP_DIR/.env"; then
  "$APP_DIR/.venv/bin/python" "$APP_DIR/deploy/setup_wizard.py" "$APP_DIR/.env" < /dev/tty
else
  echo "    Sudah terisi (ubah dengan: sudo bash deploy/install.sh --setup)"
fi
chown -R autothreads:autothreads "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo "==> [6/6] Menyalakan bot"
cp "$APP_DIR/deploy/autothreads.service" /etc/systemd/system/autothreads.service
systemctl daemon-reload
systemctl enable autothreads >/dev/null 2>&1
systemctl restart autothreads
sleep 8
if systemctl is-active --quiet autothreads; then
  echo
  echo "=================================================================="
  echo " ✔ SELESAI! Bot sudah berjalan 24 jam (mode uji / DRY_RUN)."
  echo "   Cek Telegram Anda: harusnya ada pesan 'Bot Threads aktif'."
  echo "   Kirim /status ke bot untuk memastikan akun Threads terhubung."
  echo "=================================================================="
else
  echo
  echo "!! Bot gagal menyala. Log terakhir (kirim ke Claude, tanpa token):"
  journalctl -u autothreads -n 30 --no-pager
  exit 1
fi
