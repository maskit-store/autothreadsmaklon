"""Auto riset: gabungkan Google Trends + pencarian Threads, lalu Claude memilih topik terbaik."""
import xml.etree.ElementTree as ET

import requests

from .. import config, db, llm, threads_api


def google_trends(geo: str) -> list[str]:
    try:
        r = requests.get(f"https://trends.google.com/trending/rss?geo={geo}", timeout=20,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        return [i.findtext("title") for i in root.iter("item") if i.findtext("title")][:25]
    except Exception as e:
        db.log("warn", f"Google Trends gagal: {e}")
        return []


def threads_niche_posts() -> list[dict]:
    accounts = db.active_accounts()
    if not accounts:
        return []
    token = accounts[0]["access_token"]
    posts = []
    for kw in config.NICHE_KEYWORDS:
        for search_type in ("TOP", "RECENT"):
            try:
                for p in threads_api.keyword_search(token, kw, search_type, limit=10):
                    if p.get("text"):
                        posts.append({"keyword": kw, **p})
            except Exception as e:
                db.log("warn", f"keyword_search '{kw}' gagal: {e}")
                break
    # buang duplikat
    uniq = {p["id"]: p for p in posts}
    return list(uniq.values())[:60]


def run():
    gt = google_trends(config.TRENDS_GEO)
    tp = threads_niche_posts()
    if not gt and not tp:
        db.log("warn", "riset: tidak ada data tren")
        return
    topics = llm.pick_trends(gt, tp, config.NICHE_KEYWORDS)
    db.add_trends(topics)
    db.log("info", f"riset selesai: {len(topics)} topik ({len(gt)} Google Trends, {len(tp)} post Threads)")
