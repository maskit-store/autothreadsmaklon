"""Wizard pengisian .env: tanya satu per satu, cek tiap token, deteksi ID Telegram otomatis.

Dipanggil oleh deploy/install.sh. Bisa diulang kapan saja: sudo bash deploy/install.sh --setup
"""
import getpass
import sys
from pathlib import Path

import anthropic
import requests

ENV = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/autothreads/.env")

GREEN, RED, YELLOW, BOLD, END = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"


def read_env() -> dict:
    values = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def write_env(updates: dict):
    lines = ENV.read_text(encoding="utf-8").splitlines()
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in updates and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={updates[key]}"
            done.add(key)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask(value: str) -> str:
    return value[:4] + "…" + value[-3:] if len(value) > 10 else "***"


def ask(label: str, current: str, check=None, secret_hint: str = "", secret: bool = True) -> str:
    """Tanya nilai sampai valid. Enter kosong = pakai nilai lama (kalau ada)."""
    while True:
        hint = f" {YELLOW}(sudah terisi, tekan Enter untuk memakai yang lama){END}" if current else ""
        print(f"\n{BOLD}{label}{END}{hint}")
        if secret_hint:
            print(f"  {secret_hint}")
        if secret:
            # input rahasia tidak ditampilkan supaya aman kalau layar di-screenshot
            raw = getpass.getpass("  > (tempel lalu Enter, isian tidak terlihat di layar) ")
        else:
            raw = input("  > ")
        value = raw.strip().strip('"').strip("'")
        if not value and current:
            value = current
        if value and secret:
            print(f"  diterima: {mask(value)} ({len(value)} karakter)")
        if not value:
            print(f"  {RED}Tidak boleh kosong.{END}")
            continue
        if check is None:
            return value
        try:
            info = check(value)
            print(f"  {GREEN}✔ {info}{END}")
            return value
        except Exception as e:
            print(f"  {RED}✘ Gagal: {e}{END}")
            print("  Periksa lagi lalu tempel ulang (pastikan tidak ada spasi/karakter yang terpotong).")


def check_telegram(token: str) -> str:
    r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
    if not r.get("ok"):
        raise ValueError(r.get("description", "token bot tidak valid"))
    return f"Bot ditemukan: @{r['result']['username']}"


def detect_admin(token: str, current: str) -> str:
    bot = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()["result"]["username"]
    if current:
        print(f"\n{BOLD}2/6  ID Telegram admin{END} {YELLOW}(sudah terisi: {current}){END}")
        if input("  Tekan Enter untuk memakai yang lama, atau ketik 'ganti': ").strip().lower() != "ganti":
            return current
    while True:
        print(f"\n{BOLD}2/6  Sekarang buka Telegram di HP, cari @{bot}, lalu kirim pesan: /start{END}")
        input("  Kalau sudah, tekan Enter di sini...")
        updates = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json().get("result", [])
        msgs = [u["message"] for u in updates if "message" in u]
        if not msgs:
            print(f"  {RED}Belum ada pesan masuk. Pastikan /start dikirim ke @{bot}, lalu coba lagi.{END}")
            continue
        sender = msgs[-1]["from"]
        name = " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")]))
        if input(f"  Pesan dari {BOLD}{name}{END} (ID {sender['id']}). Ini Anda? [Y/n] ").strip().lower() in ("", "y", "ya"):
            # tandai pesan sudah dibaca supaya tidak diproses ulang oleh bot
            requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                         params={"offset": updates[-1]["update_id"] + 1}, timeout=30)
            print(f"  {GREEN}✔ Admin: {name} ({sender['id']}){END}")
            return str(sender["id"])


def check_threads(token: str) -> str:
    r = requests.get("https://graph.threads.net/v1.0/me", params={"fields": "username", "access_token": token},
                     timeout=20).json()
    if "error" in r:
        raise ValueError(r["error"].get("message", r["error"]))
    return f"Akun Threads: @{r['username']}"


def check_anthropic(key: str) -> str:
    try:
        anthropic.Anthropic(api_key=key).models.list(limit=1)
    except anthropic.AuthenticationError:
        raise ValueError("API key ditolak (salah ketik / sudah dihapus)")
    except anthropic.PermissionDeniedError:
        raise ValueError("API key tidak punya akses, cek saldo/billing di console.anthropic.com")
    return "API key Claude valid"


def main():
    env = read_env()
    print(f"\n{BOLD}=== Pengaturan Bot Auto Threads ==={END}")
    print("Tempel (klik kanan) setiap nilai yang diminta, lalu tekan Enter.")

    tg = ask("1/6  Token bot Telegram (dari @BotFather)", env.get("TELEGRAM_BOT_TOKEN", ""), check_telegram,
             "Bentuknya seperti 7123456789:AAHxxxxxxxx")
    admin = detect_admin(tg, env.get("TELEGRAM_ADMIN_IDS", ""))
    app_id = ask("3/6  Threads App ID", env.get("THREADS_APP_ID", ""), None,
                 "Meta Developer > Use cases > Access the Threads API > Customize > Settings", secret=False)
    secret = ask("4/6  Threads App Secret", env.get("THREADS_APP_SECRET", ""), None,
                 "Di halaman yang sama, klik 'Show' di sebelah Threads app secret")
    th = ask("5/6  Threads access token (dari User Token Generator)", env.get("THREADS_ACCESS_TOKEN", ""),
             check_threads, "Panjang, biasanya diawali THAA...")
    key = ask("6/6  API key Claude (dari console.anthropic.com)", env.get("ANTHROPIC_API_KEY", ""),
              check_anthropic, "Diawali sk-ant-...")

    write_env({
        "TELEGRAM_BOT_TOKEN": tg,
        "TELEGRAM_ADMIN_IDS": admin,
        "THREADS_APP_ID": app_id,
        "THREADS_APP_SECRET": secret,
        "THREADS_ACCESS_TOKEN": th,
        "ANTHROPIC_API_KEY": key,
    })
    print(f"\n{GREEN}✔ Pengaturan disimpan.{END}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDibatalkan. Jalankan lagi: sudo bash deploy/install.sh --setup")
        sys.exit(1)
