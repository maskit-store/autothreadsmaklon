"""Semua pemanggilan Claude: tulis post, balas komentar, komentar, revisi, dan riset tren."""
import json

import anthropic

from . import config

client = anthropic.Anthropic()

SYSTEM_BASE = """Kamu adalah admin media sosial yang menulis untuk akun Threads sebuah brand.
Ikuti persona dan aturan brand dengan ketat. Untuk fakta tentang bisnis (layanan, MOQ, proses, kontak),
gunakan HANYA knowledge base. Kalau infonya tidak ada, arahkan ke kontak admin, jangan mengarang.

<persona>
{persona}
</persona>

<knowledge_base>
{knowledge}
</knowledge_base>

Aturan umum Threads:
- Maksimal 500 karakter per tulisan (usahakan jauh lebih pendek).
- Tulis seperti manusia asli, bukan seperti iklan atau AI. Tanpa hashtag berlebihan.
- Jangan mengaku sebagai AI/bot kecuali ditanya langsung secara serius.
- Jangan mengarang fakta, angka, atau berita."""


class LLMRefusal(Exception):
    pass


def _ask(model: str, task: str, schema: dict, max_tokens: int = 4000) -> dict:
    kwargs = {}
    # Fallback server-side saat model menolak (tidak tersedia untuk Haiku)
    if "haiku" not in model:
        kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    response = client.beta.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_BASE.format(persona=config.persona(), knowledge=config.knowledge()),
        messages=[{"role": "user", "content": task}],
        output_config={
            "effort": config.CLAUDE_EFFORT,
            "format": {"type": "json_schema", "schema": schema},
        },
        **kwargs,
    )
    if response.stop_reason == "refusal":
        raise LLMRefusal(str(response.stop_details))
    text = "".join(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


TEXT_ONLY = _obj({"text": {"type": "string"}})


def write_post(topic: str, angle: str, recent_posts: list[str]) -> str:
    recent = "\n---\n".join(recent_posts) or "(belum ada)"
    out = _ask(config.CLAUDE_MODEL_WRITER, f"""Buat SATU post Threads baru.

Topik/ide: {topic}
Sudut pandang yang disarankan: {angle or '-'}

Hubungkan topik ini secara natural dengan niche brand (jangan dipaksakan). Variasikan format:
tips singkat, opini, pertanyaan pemancing diskusi, cerita pendek, atau list.

Post terakhir kita (JANGAN mengulang ide/kalimat pembuka yang sama):
<recent>
{recent}
</recent>""", TEXT_ONLY)
    return out["text"].strip()


def write_reply(my_post: str, their_comment: str, username: str, thread_context: str = "") -> dict:
    """Return {"action": "reply"|"skip"|"escalate", "text": ..., "reason": ...}."""
    context = f"Percakapan sebelumnya:\n<context>{thread_context}</context>\n" if thread_context else ""
    out = _ask(config.CLAUDE_MODEL_REPLY, f"""Seseorang mengomentari post kita. Putuskan tindakannya.

Post kita:
<post>{my_post}</post>
{context}
Komentar dari @{username}:
<comment>{their_comment}</comment>

Pilihan action:
- "skip": spam, promosi orang lain, kasar/provokatif, hanya emoji yang tidak perlu dijawab, atau tidak jelas.
- "escalate": termasuk kategori eskalasi di knowledge base (komplain, efek samping, negosiasi harga, legal,
  calon klien serius). Tetap tulis draf balasan singkat yang sopan dan mengarahkan ke kontak admin.
- "reply": selain itu. Tulis balasan ramah, singkat (1-3 kalimat), menjawab poinnya berdasarkan knowledge base.
"reason" berisi alasan singkat pilihanmu.""", _obj({
        "action": {"type": "string", "enum": ["reply", "skip", "escalate"]},
        "text": {"type": "string"},
        "reason": {"type": "string"},
    }))
    out["text"] = out["text"].strip()
    if out["action"] != "skip" and not out["text"]:
        out["action"] = "skip"
    return out


def write_comment(their_post: str, username: str) -> str | None:
    """Komentar ke post orang lain. Return None kalau post tidak cocok dikomentari."""
    out = _ask(config.CLAUDE_MODEL_REPLY, f"""Ini post milik @{username} di Threads yang relevan dengan niche kita.

<post>{their_post}</post>

Tulis komentar yang menambah nilai (insight, pengalaman, pertanyaan cerdas, atau dukungan tulus).
JANGAN promosi, jangan menyebut brand kita, jangan menaruh link. Maksimal 2 kalimat.
Pilih "skip" jika post bersifat pribadi/sensitif (duka, musibah, konflik), politik/SARA, iklan kompetitor,
atau tidak ada hal bermanfaat yang bisa ditambahkan.""", _obj({
        "action": {"type": "string", "enum": ["comment", "skip"]},
        "text": {"type": "string"},
    }))
    return out["text"].strip() if out["action"] == "comment" and out["text"].strip() else None


def revise(kind: str, draft: str, instruction: str, context: str = "") -> str:
    ctx = f"Konteks (yang dibalas/topik):\n<context>{context}</context>\n" if context else ""
    out = _ask(config.CLAUDE_MODEL_WRITER, f"""Revisi draf {kind} Threads berikut sesuai instruksi admin.
{ctx}
<draft>{draft}</draft>

Instruksi admin: {instruction}

Kalau instruksi berisi teks pengganti lengkap, pakai teks itu apa adanya (rapikan seperlunya saja).""", TEXT_ONLY)
    return out["text"].strip()


def update_doc(doc_name: str, current: str, instruction: str) -> str:
    """Perbarui knowledge base / persona berdasarkan instruksi admin (bahasa bebas)."""
    out = _ask(config.CLAUDE_MODEL_WRITER, f"""Admin ingin memperbarui dokumen "{doc_name}" milik bot Threads.

Dokumen saat ini:
<document>
{current}
</document>

Instruksi / info baru dari admin:
<instruction>
{instruction}
</instruction>

Tulis ulang dokumen LENGKAP dengan perubahan tersebut. Aturan:
- Pertahankan struktur heading Markdown yang ada; masukkan info baru ke bagian yang paling cocok.
- Ganti placeholder seperti "(ISI)", "(ISI SESUAI)", "...", atau "08xx" kalau admin memberi datanya.
- Jangan menghapus info lama kecuali admin memintanya atau info itu bertentangan dengan yang baru.
- Jangan menambah fakta yang tidak diberikan admin.""", TEXT_ONLY, max_tokens=16000)
    return out["text"].strip() + "\n"


def pick_trends(google_trends: list[str], threads_posts: list[dict], keywords: list[str]) -> list[dict]:
    gt = "\n".join(f"- {t}" for t in google_trends) or "(tidak ada data)"
    tp = "\n".join(f"- [{p.get('keyword')}] {(p.get('text') or '')[:280]}" for p in threads_posts) or "(tidak ada data)"
    topic = _obj({
        "title": {"type": "string"},
        "angle": {"type": "string"},
        "reason": {"type": "string"},
        "score": {"type": "integer"},
    })
    out = _ask(config.CLAUDE_MODEL_WRITER, f"""Kamu riset konten. Dari data di bawah, temukan 5 topik yang paling
berpotensi ramai dan bisa dibahas akun kita secara relevan dengan niche ({', '.join(keywords)}).

Google Trends hari ini:
{gt}

Post Threads terbaru tentang niche kita:
{tp}

Untuk tiap topik beri: title (singkat), angle (sudut pandang konten untuk akun kita),
reason (kenapa relevan, berdasarkan data di atas), score 1-100 (potensi engagement x relevansi).
Kalau tren umum tidak ada yang nyambung, boleh pakai topik evergreen di niche kita (score lebih rendah).
Hindari topik politik, SARA, bencana, atau berita duka.""",
        _obj({"topics": {"type": "array", "items": topic}}), max_tokens=8000)
    return out["topics"]
