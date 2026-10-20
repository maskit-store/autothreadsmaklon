# Auto Threads Maklon

Bot otomatis untuk akun Threads, dikendalikan lewat **Telegram** dan ditulis oleh **Claude AI**:

| Fitur | Cara kerja |
|---|---|
| **Auto riset tren** | Tiap 6 jam: ambil Google Trends Indonesia + post Threads tentang kata kunci niche → Claude memilih 5 topik paling relevan |
| **Auto post** | Di jam yang ditentukan (default 08:00, 12:30, 19:30 WIB) Claude menulis post dari topik tren teratas |
| **Auto reply** | Tiap 10 menit cek komentar baru di post Anda → Claude membalas berdasarkan `knowledge.md`. Komplain/negosiasi/legal **dieskalasi** ke Anda |
| **Auto comment** | Cari post orang lain di niche Anda → Claude menulis komentar bernilai (tanpa promosi) |
| **Ruang kontrol Telegram** | Setiap draf dikirim ke Telegram dengan tombol ✅ Posting / ✏️ Revisi / ❌ Buang |

DM Threads **tidak** didukung karena Threads API resmi belum menyediakan endpoint DM.

---

## Yang perlu ANDA lakukan (tidak bisa dikerjakan Claude)

### 1. Lengkapi izin di Meta Developer
Buka **developers.facebook.com → App Anda → Use cases → Access the Threads API → Customize → Permissions**, lalu pastikan izin berikut sudah ditambahkan:
- `threads_basic`, `threads_content_publish`, `threads_read_replies`, `threads_manage_replies` (sudah Anda tambahkan)
- **tambahkan juga:** `threads_keyword_search` (untuk riset & auto comment) dan `threads_manage_insights` (untuk cek kuota)

> ⚠️ **Batasan selama app masih mode tester:** menurut dokumentasi Meta, sebelum `threads_keyword_search` disetujui lewat App Review, pencarian hanya menghasilkan **post milik akun Anda sendiri**. Jadi:
> - Riset tren tetap jalan (Google Trends tetap dipakai), hanya data dari Threads yang terbatas.
> - **Auto comment ke post orang lain baru efektif setelah App Review.** Karena itu default-nya `AUTO_COMMENT_ENABLED=false`.

### 2. Generate access token Threads
Masih di halaman **Customize → Settings → User Token Generator**, klik **Generate Access Token** di akun Threads Anda. Salin tokennya. **Generate ulang token setelah menambah izin baru** supaya izin barunya ikut masuk.

Catat juga **Threads App ID** dan **Threads App Secret** dari halaman Settings yang sama.

### 3. Buat bot Telegram
1. Chat **@BotFather** di Telegram → `/newbot` → ikuti instruksi.
2. Simpan **token bot**-nya.

### 4. API key Claude
1. Daftar/login di **console.anthropic.com**, isi saldo (misalnya $5–10).
2. Buat **API key** di menu API Keys.

### 5. Akses VPS
Anda perlu login SSH ke VPS (yang dulu dipakai chatbot), misalnya `ssh root@IP-VPS`. Bot ini berjalan sebagai service terpisah (`autothreads`) di `/opt/autothreads`, jadi **tidak mengganggu chatbot lama**. Bot ini juga tidak butuh domain, port terbuka, atau Nginx karena Telegram dibaca dengan polling.

---

## Instalasi di VPS (sekitar 10 menit)

Jalankan di terminal VPS:

```bash
# 1) Ambil kode (repo privat: GitHub akan meminta username + Personal Access Token sebagai password)
cd ~
git clone https://github.com/maskit-store/autothreadsmaklon.git
cd autothreadsmaklon

# 2) Pasang (membuat user sistem, virtualenv, dan service systemd)
sudo bash deploy/install.sh

# 3) Isi konfigurasi
sudo nano /opt/autothreads/.env
```

Isi minimal di `.env`:
```
TELEGRAM_BOT_TOKEN=token dari BotFather
THREADS_APP_ID=...
THREADS_APP_SECRET=...
THREADS_ACCESS_TOKEN=token dari User Token Generator
ANTHROPIC_API_KEY=sk-ant-...
```
Biarkan `TELEGRAM_ADMIN_IDS` kosong dulu. Simpan (Ctrl+O, Enter, Ctrl+X), lalu:

```bash
sudo systemctl restart autothreads
```

4) Buka bot Anda di Telegram dan kirim `/start`. Bot akan membalas dengan **ID Telegram** Anda. Masukkan angka itu ke `TELEGRAM_ADMIN_IDS` di `.env`, lalu `sudo systemctl restart autothreads` lagi.

5) Kirim `/status` ke bot. Pastikan akun Threads Anda muncul.

### Isi persona & knowledge base (penting!)
```bash
sudo nano /opt/autothreads/persona.md     # gaya bahasa, aturan klaim, contoh post
sudo nano /opt/autothreads/knowledge.md   # layanan, MOQ, kontak, FAQ, aturan eskalasi
sudo systemctl restart autothreads
```
AI hanya menjawab berdasarkan `knowledge.md`. Kalau infonya tidak ada di sana, AI akan mengarahkan ke kontak admin.

---

## Uji coba → live

1. **Mode uji (default):** `DRY_RUN=true`. Bot membuat draf dan semua alur Telegram berjalan, tapi **tidak benar-benar memposting** ke Threads. Coba:
   - `/post tips memilih nama brand skincare` → draf muncul dengan tombol
   - `/riset` lalu `/tren`
   - `/balas` (cek komentar di post Anda)
2. Kalau hasil tulisan sudah sesuai, ubah `DRY_RUN=false` di `.env` lalu restart. Sekarang draf yang Anda ✅ benar-benar terbit.
3. Setelah 1–2 minggu dan balasan AI konsisten bagus, Anda bisa set `REQUIRE_APPROVAL_REPLIES=false` supaya balasan komentar umum langsung terkirim. Komentar yang dieskalasi (🚨) **tetap** menunggu persetujuan Anda.

## Perintah Telegram

| Perintah | Fungsi |
|---|---|
| `/post <ide>` | Buat draf post dari ide Anda |
| `/riset` · `/tren` | Riset topik trending sekarang · lihat hasilnya |
| `/autopost` | Buat draf post dari topik tren teratas |
| `/balas` | Cek & balas komentar sekarang |
| `/komentar` | Cari post orang & buat draf komentar |
| `/antrian` | Tampilkan draf yang menunggu persetujuan |
| `/status` | Mode, akun, kuota API, statistik 24 jam |
| `/pause` · `/resume` | Hentikan / jalankan lagi semua otomatisasi |
| `/token <token>` | Hubungkan / perbarui token Threads (lalu hapus pesan berisi token) |
| `/log` | 15 log terakhir |

Tombol **✏️ Revisi**: kirim instruksi (misalnya "lebih singkat, tambah ajakan DM"), atau kirim teks pengganti lengkap yang diawali `=`.

## Pengaturan penting (`.env`)

| Variabel | Default | Keterangan |
|---|---|---|
| `DRY_RUN` | `true` | `false` = benar-benar posting |
| `REQUIRE_APPROVAL_POSTS / _REPLIES / _COMMENTS` | `true` | Draf harus disetujui di Telegram |
| `POST_TIMES` | `08:00,12:30,19:30` | Jam auto post (WIB) |
| `MAX_POSTS_PER_DAY` / `MAX_REPLIES_PER_HOUR` / `MAX_COMMENTS_PER_DAY` | 3 / 20 / 10 | Batas aman supaya akun tidak dianggap spam |
| `NICHE_KEYWORDS` | maklon skincare, … | Kata kunci riset & pencarian post |
| `CLAUDE_MODEL_WRITER` | `claude-sonnet-5-5` | Untuk post & riset |
| `CLAUDE_MODEL_REPLY` | `claude-haiku-5-5` | Untuk balasan & komentar (murah) |
| `AUTO_COMMENT_ENABLED` | `false` | Aktifkan setelah `threads_keyword_search` lolos App Review |

Setiap mengubah `.env`, `persona.md`, atau `knowledge.md`, jalankan `sudo systemctl restart autothreads`.

## Perawatan

```bash
sudo journalctl -u autothreads -f          # lihat log langsung
sudo systemctl status autothreads          # cek bot jalan atau tidak
sudo systemctl restart autothreads         # restart

# Update kode ke versi terbaru
cd ~/autothreadsmaklon && git pull && sudo bash deploy/install.sh
```

- **Token Threads** berlaku 60 hari dan diperpanjang otomatis setiap hari jam 03:17. Kalau gagal, bot mengirim peringatan ke Telegram. Generate token baru lalu kirim `/token <token>`.
- Database ada di `/opt/autothreads/data/autothreads.db` (SQLite). Untuk backup, salin file itu.
- Komentar lama yang sudah ada sebelum bot dipasang **tidak** akan dibalas massal.

## Perkiraan biaya
- Threads API & Telegram: gratis
- Claude API: sekitar $2–5/bulan untuk pemakaian normal (Haiku untuk balasan, Sonnet untuk post & riset)
- VPS: memakai VPS yang sudah ada

## Struktur kode
```
app/
  __main__.py      # entry point: python -m app
  bot.py           # bot Telegram (perintah, tombol approval, revisi)
  scheduler.py     # jadwal otomatis
  threads_api.py   # Threads API resmi
  llm.py           # prompt & pemanggilan Claude
  notify.py        # kirim pesan ke admin Telegram
  db.py            # SQLite
  jobs/            # research, autopost, autoreply, autocomment, tokens
persona.md         # gaya bahasa brand (edit!)
knowledge.md       # FAQ, MOQ, kontak, aturan eskalasi (edit!)
deploy/            # install.sh + service systemd
```
