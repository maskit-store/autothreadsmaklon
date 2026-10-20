"""Bot Telegram sebagai ruang kontrol: approval draf, perintah manual, status."""
import threading
import time

from . import config, db, llm, notify, threads_api
from .jobs import autocomment, autopost, autoreply, common, research

HELP = """<b>Perintah</b>
/post &lt;ide&gt; – buat draf post dari ide kamu
/riset – riset topik trending sekarang
/tren – lihat topik hasil riset terakhir
/autopost – buat draf post dari topik tren teratas
/balas – cek &amp; balas komentar sekarang
/komentar – cari post orang &amp; buat draf komentar
/antrian – tampilkan draf yang menunggu persetujuan
/status – status akun, kuota, mode

<b>Data bisnis &amp; gaya bahasa</b>
/data – lihat data bisnis (layanan, MOQ, kontak, FAQ)
/ubahdata &lt;info&gt; – tambah/ubah data bisnis dengan bahasa biasa
/gaya – lihat panduan gaya bahasa
/ubahgaya &lt;info&gt; – ubah gaya bahasa / aturan tulisan

<b>Mode</b>
/live – mulai posting sungguhan ke Threads
/uji – kembali ke mode uji (tidak posting)
/pause – hentikan semua otomatisasi
/resume – jalankan lagi
/token &lt;access_token&gt; – hubungkan / perbarui akun Threads
/log – 15 log terakhir"""

# admin chat_id -> item_id yang sedang direvisi
_waiting_revision: dict[int, int] = {}
# admin chat_id -> (nama dokumen, path, isi baru) yang menunggu konfirmasi simpan
_pending_doc: dict[int, tuple] = {}

DOCS = {
    "data": ("Data bisnis (knowledge base)", config.KNOWLEDGE_FILE),
    "gaya": ("Gaya bahasa (persona)", config.PERSONA_FILE),
}


def _bg(chat_id: int, label: str, fn, *args, quiet: bool = False):
    def run():
        try:
            fn(*args)
            if not quiet:
                notify.call("sendMessage", chat_id=chat_id, text=f"✔️ {label} selesai.")
        except Exception as e:
            db.log("error", f"{label}: {e}")
            notify.call("sendMessage", chat_id=chat_id, text=f"⚠️ {label} gagal: {e}")
    threading.Thread(target=run, daemon=True).start()


def send_long(chat_id: int, text: str):
    """Kirim teks panjang (tanpa format HTML) dipotong per 3500 karakter."""
    chunk = ""
    for line in text.splitlines(keepends=True):
        if len(chunk) + len(line) > 3500:
            notify.call("sendMessage", chat_id=chat_id, text=chunk)
            chunk = ""
        chunk += line
    if chunk.strip():
        notify.call("sendMessage", chat_id=chat_id, text=chunk)


def update_doc(chat_id: int, key: str, instruction: str):
    name, path = DOCS[key]
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    new = llm.update_doc(name, current, instruction)
    _pending_doc[chat_id] = (key, new)
    send_long(chat_id, new)
    reply(chat_id, f"👆 Ini {name} versi baru. Simpan?", [[
        {"text": "💾 Simpan", "callback_data": "docok:0"},
        {"text": "❌ Batal", "callback_data": "docno:0"},
    ]])


def reply(chat_id: int, text: str, buttons=None):
    payload = {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    notify.call("sendMessage", **payload)


def connect_token(token: str) -> str:
    token = token.strip()
    expires_at = None
    if config.THREADS_APP_SECRET:
        try:  # kalau token masih short-lived, tukar jadi long-lived (60 hari)
            token, expires_at = threads_api.long_lived_token(token)
        except threads_api.ThreadsError:
            pass  # token dari User Token Generator biasanya sudah long-lived
    profile = threads_api.me(token)
    if not expires_at:
        try:
            token, expires_at = threads_api.refresh_token(token)
        except threads_api.ThreadsError:
            expires_at = db.ago(days=-50)  # perkiraan; refresh harian akan memperbaruinya
    db.upsert_account(str(profile["id"]), profile.get("username", ""), token, expires_at)
    db.log("info", f"akun @{profile.get('username')} terhubung")
    return profile.get("username", "")


def handle_command(chat_id: int, text: str):
    cmd, _, arg = text.strip().partition(" ")
    cmd = cmd.split("@")[0].lower()

    if cmd in ("/start", "/help"):
        reply(chat_id, HELP)
    elif cmd == "/post":
        if not arg:
            return reply(chat_id, "Contoh: /post tips memilih nama brand skincare")
        reply(chat_id, "⏳ Membuat draf...")
        _bg(chat_id, "Draf post", autopost.from_idea, arg)
    elif cmd == "/riset":
        reply(chat_id, "⏳ Riset tren berjalan (±1 menit)...")
        _bg(chat_id, "Riset", lambda: (research.run(), _send_trends(chat_id)))
    elif cmd == "/tren":
        _send_trends(chat_id)
    elif cmd == "/autopost":
        _bg(chat_id, "Auto post", autopost.run)
    elif cmd == "/balas":
        _bg(chat_id, "Cek komentar", autoreply.run)
    elif cmd == "/komentar":
        _bg(chat_id, "Cari post untuk dikomentari", autocomment.run)
    elif cmd == "/antrian":
        items = db.outbox_by_status("pending", 10)
        if not items:
            return reply(chat_id, "Tidak ada draf yang menunggu.")
        for it in reversed(items):
            reply(chat_id, notify.item_text(it), notify.approval_buttons(it["id"]))
    elif cmd == "/status":
        _send_status(chat_id)
    elif cmd == "/pause":
        db.set_setting("paused", "1")
        reply(chat_id, "⏸️ Otomatisasi dihentikan. Draf yang kamu setujui tetap bisa terbit. /resume untuk lanjut.")
    elif cmd == "/resume":
        db.set_setting("paused", "0")
        reply(chat_id, "▶️ Otomatisasi berjalan lagi.")
    elif cmd == "/token":
        if not arg:
            return reply(chat_id, "Kirim: /token &lt;access_token dari User Token Generator&gt;")
        try:
            username = connect_token(arg)
            reply(chat_id, f"✅ Akun @{notify.esc(username)} terhubung. Hapus pesan berisi token tadi dari chat ini.")
        except Exception as e:
            reply(chat_id, f"⚠️ Token gagal dipakai: {notify.esc(e)}")
    elif cmd in ("/data", "/gaya"):
        name, path = DOCS[cmd[1:]]
        send_long(chat_id, path.read_text(encoding="utf-8") if path.exists() else "(kosong)")
        reply(chat_id, f"Untuk mengubah {name}, kirim /ubah{cmd[1:]} diikuti info baru.\n"
                       f"Contoh: <i>/ubah{cmd[1:]} " + ("MOQ 100 pcs, WA admin 0812-3456-7890, bisa sampel dulu"
                       if cmd == "/data" else "pakai sapaan kak, jangan pakai emoji") + "</i>")
    elif cmd in ("/ubahdata", "/ubahgaya"):
        key = cmd[5:]
        if not arg:
            return reply(chat_id, f"Tulis infonya setelah perintah. Contoh: <i>{cmd} "
                         + ("layanan kami serum, toner, sunscreen. MOQ 100 pcs" if key == "data"
                            else "gaya bahasa lebih santai, sapa dengan kak") + "</i>")
        reply(chat_id, "⏳ Merapikan dokumen...")
        _bg(chat_id, "Penyusunan dokumen", update_doc, chat_id, key, arg, quiet=True)
    elif cmd == "/live":
        if not db.is_dry_run():
            return reply(chat_id, "Sudah dalam mode 🟢 LIVE.")
        reply(chat_id, "⚠️ Mode LIVE: draf yang kamu ✅ akan <b>benar-benar terbit</b> di Threads, dan balasan/"
                       "komentar yang tidak butuh persetujuan akan langsung terkirim. Lanjut?",
              [[{"text": "🟢 Ya, mulai live", "callback_data": "live:1"},
                {"text": "Batal", "callback_data": "live:0"}]])
    elif cmd == "/uji":
        db.set_setting("dry_run", "1")
        reply(chat_id, "🧪 Kembali ke mode uji. Tidak ada yang diposting ke Threads.")
    elif cmd == "/log":
        rows = db.recent_logs(15)
        reply(chat_id, "\n".join(f"{r['created_at'][11:16]} [{r['level']}] {notify.esc(r['message'][:200])}"
                                 for r in reversed(rows)) or "(kosong)")
    else:
        reply(chat_id, "Perintah tidak dikenal. /help")


def _send_trends(chat_id: int):
    rows = db.recent_trends(8)
    if not rows:
        return reply(chat_id, "Belum ada data tren. Jalankan /riset")
    lines = [f"{'✅' if r['used'] else '🔹'} <b>{notify.esc(r['title'])}</b> ({r['score']})\n   {notify.esc(r['angle'])}"
             for r in rows]
    reply(chat_id, "<b>Topik tren terbaru</b>\n" + "\n".join(lines))


def _send_status(chat_id: int):
    lines = [f"Mode: {'🧪 DRY_RUN (tidak benar-benar posting)' if db.is_dry_run() else '🟢 LIVE'}",
             f"Otomatisasi: {'⏸️ pause' if db.is_paused() else '▶️ jalan'}",
             f"Approval: post={config.REQUIRE_APPROVAL_POSTS}, balasan={config.REQUIRE_APPROVAL_REPLIES}, "
             f"komentar={config.REQUIRE_APPROVAL_COMMENTS}",
             f"Jadwal post: {', '.join(config.POST_TIMES)} ({config.TIMEZONE})"]
    accounts = db.all_accounts()
    if not accounts:
        lines.append("\n⚠️ Belum ada akun Threads. Kirim /token &lt;access_token&gt;")
    for acc in accounts:
        lines.append(f"\n<b>@{notify.esc(acc['username'])}</b> {'aktif' if acc['active'] else 'nonaktif'}, "
                     f"token s/d {(acc['token_expires_at'] or '?')[:10]}")
        st = db.stats_today(acc["id"])
        if st:
            lines.append("24 jam: " + ", ".join(f"{k}={v}" for k, v in sorted(st.items())))
        try:
            q = threads_api.publishing_limit(acc["threads_user_id"], acc["access_token"])
            lines.append(f"Kuota API: post {q.get('quota_usage', '?')}/{(q.get('config') or {}).get('quota_total', 250)}, "
                         f"reply {q.get('reply_quota_usage', '?')}/{(q.get('reply_config') or {}).get('quota_total', 1000)}")
        except Exception as e:
            lines.append(f"Kuota API: gagal cek ({notify.esc(e)})")
    reply(chat_id, "\n".join(lines))


def handle_callback(cb: dict):
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    action, _, raw_id = cb.get("data", "").partition(":")
    if action in ("docok", "docno", "live"):
        notify.call("answerCallbackQuery", callback_query_id=cb["id"])
        return handle_setting_callback(chat_id, message_id, action, raw_id)
    item = db.get_outbox(int(raw_id)) if raw_id.isdigit() else None
    if not item:
        return notify.call("answerCallbackQuery", callback_query_id=cb["id"], text="Item tidak ditemukan")

    def mark(status_line: str):
        notify.call("editMessageText", chat_id=chat_id, message_id=message_id, parse_mode="HTML",
                    text=(notify.item_text(db.get_outbox(item["id"])) + f"\n\n{status_line}")[:4000])

    if action == "ok":
        if item["status"] in ("pending", "failed"):
            db.update_outbox(item["id"], status="approved", error=None)
            mark("⏳ Disetujui, sedang diposting...")
            threading.Thread(target=common.publish_item, args=(item["id"],), daemon=True).start()
        else:
            mark(f"Status: {item['status']}")
    elif action == "no":
        if item["status"] in ("pending", "failed"):
            db.update_outbox(item["id"], status="rejected")
        mark("❌ Dibuang")
    elif action == "rev":
        _waiting_revision[chat_id] = item["id"]
        reply(chat_id, f"✏️ Kirim instruksi revisi untuk #{item['id']}.\n"
                       "Contoh: <i>lebih singkat, tambah ajakan DM</i>\n"
                       "Atau kirim teks pengganti lengkap diawali tanda = (contoh: <i>=Halo kak...</i>)")
    notify.call("answerCallbackQuery", callback_query_id=cb["id"])


def handle_setting_callback(chat_id: int, message_id: int, action: str, value: str):
    def done(text: str):
        notify.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text)

    if action == "live":
        if value == "1":
            db.set_setting("dry_run", "0")
            db.log("info", "mode LIVE diaktifkan dari Telegram")
            return done("🟢 Mode LIVE aktif. Kembali ke mode uji kapan saja dengan /uji")
        return done("Dibatalkan, tetap mode uji.")
    pending = _pending_doc.pop(chat_id, None)
    if not pending:
        return done("Tidak ada perubahan yang menunggu.")
    if action == "docno":
        return done("❌ Perubahan dibatalkan.")
    key, new = pending
    name, path = DOCS[key]
    if path.exists():
        path.with_suffix(".md.bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(new, encoding="utf-8")
    db.log("info", f"{name} diperbarui dari Telegram")
    done(f"💾 {name} disimpan dan langsung dipakai untuk tulisan berikutnya.")


def handle_revision(chat_id: int, text: str):
    item_id = _waiting_revision.pop(chat_id)
    item = db.get_outbox(item_id)
    if not item or item["status"] not in ("pending", "failed"):
        return reply(chat_id, "Draf ini sudah tidak bisa direvisi.")
    if text.startswith("="):
        new_text = text[1:].strip()
    else:
        reply(chat_id, "⏳ Merevisi...")
        new_text = llm.revise(item["kind"], item["text"], text, item["context"] or "")
    db.update_outbox(item_id, text=new_text[:500], status="pending")
    notify.ask_approval(item_id)


def handle_update(upd: dict):
    if "callback_query" in upd:
        cb = upd["callback_query"]
        if cb["from"]["id"] not in config.TELEGRAM_ADMIN_IDS:
            return notify.call("answerCallbackQuery", callback_query_id=cb["id"], text="Bukan admin")
        return handle_callback(cb)

    msg = upd.get("message")
    if not msg or "text" not in msg:
        return
    chat_id, user_id, text = msg["chat"]["id"], msg["from"]["id"], msg["text"]
    if user_id not in config.TELEGRAM_ADMIN_IDS:
        return reply(chat_id, f"Halo! ID Telegram kamu: <code>{user_id}</code>\n"
                              "Masukkan ID ini ke TELEGRAM_ADMIN_IDS di file .env lalu restart bot.")
    if text.startswith("/"):
        _waiting_revision.pop(chat_id, None)
        return handle_command(chat_id, text)
    if chat_id in _waiting_revision:
        return handle_revision(chat_id, text)
    reply(chat_id, "Ketik /help untuk daftar perintah. Untuk membuat post: /post &lt;ide&gt;")


def run_forever():
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN belum diisi di .env")
    notify.call("setMyCommands", commands=[
        {"command": c.split()[0][1:], "description": d}
        for c, d in [("/post", "Buat draf post dari ide"), ("/riset", "Riset topik trending"),
                     ("/tren", "Lihat topik tren"), ("/autopost", "Draf post dari tren teratas"),
                     ("/balas", "Cek & balas komentar"), ("/komentar", "Komentar ke post orang"),
                     ("/antrian", "Draf menunggu persetujuan"), ("/status", "Status bot"),
                     ("/data", "Lihat data bisnis"), ("/ubahdata", "Ubah data bisnis"),
                     ("/gaya", "Lihat gaya bahasa"), ("/ubahgaya", "Ubah gaya bahasa"),
                     ("/live", "Mulai posting sungguhan"), ("/uji", "Kembali ke mode uji"),
                     ("/pause", "Hentikan otomatisasi"), ("/resume", "Jalankan lagi"),
                     ("/log", "Log terakhir"), ("/help", "Bantuan")]
    ])
    notify.to_admins(f"🤖 Bot Threads aktif ({'DRY_RUN' if db.is_dry_run() else 'LIVE'}). /status untuk cek.")
    offset = None
    while True:
        try:
            data = notify.call("getUpdates", offset=offset, timeout=30,
                               allowed_updates=["message", "callback_query"])
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    handle_update(upd)
                except Exception as e:
                    db.log("error", f"telegram update error: {e}")
            if not data:
                time.sleep(5)
        except Exception as e:
            db.log("error", f"telegram polling error: {e}")
            time.sleep(5)
