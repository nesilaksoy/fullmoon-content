#!/usr/bin/env python3
"""Drafts a blog article for the app's "Burçlar" feed and adds it to content/articles.json.

  pip install astronomy-engine anthropic
  export ANTHROPIC_API_KEY=...

  # next New/Full Moon within N days, computed automatically
  python3 tools/generate_article.py --auto --days 10
  # any topic
  python3 tools/generate_article.py --topic "Venüs Oğlak'ta" --date 2026-12-05 --sign 9 --header "Gökyüzü"
  # only check the feed
  python3 tools/generate_article.py --validate

The article goes in with "date" = publish date; the app shows it (and sends the
"Yeni blog yazısı" notification) from that day on. Review the text before merging.
"""
import argparse, json, os, re, sys, datetime as dt

ROOT = os.path.join(os.path.dirname(__file__), "..")
FEED = os.path.join(ROOT, "content", "articles.json")
SIGNS = ["Koç", "Boğa", "İkizler", "Yengeç", "Aslan", "Başak", "Terazi", "Akrep", "Yay", "Oğlak", "Kova", "Balık"]
BLOCK_TYPES = {"lead", "paragraph", "heading", "subheading", "bullets", "ritual", "note"}
MODEL = os.environ.get("MODEL", "claude-sonnet-5-5")


def validate(feed):
    errs, ids = [], set()
    for a in feed.get("articles", []):
        aid = a.get("id", "?")
        for k in ("id", "headerTitle", "title", "subtitle", "date", "blocks"):
            if not a.get(k): errs.append(f"{aid}: missing {k}")
        if aid in ids: errs.append(f"{aid}: duplicate id")
        ids.add(aid)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.get("date", "")): errs.append(f"{aid}: date must be yyyy-MM-dd")
        if a.get("sign") is not None and a["sign"] not in range(12): errs.append(f"{aid}: sign must be 0…11")
        for i, b in enumerate(a.get("blocks", [])):
            t = b.get("type")
            if t not in BLOCK_TYPES: errs.append(f"{aid} block {i}: unknown type {t}")
            elif t == "bullets" and not b.get("items"): errs.append(f"{aid} block {i}: bullets need items")
            elif t == "ritual" and not (b.get("title") and b.get("text")): errs.append(f"{aid} block {i}: ritual needs title+text")
            elif t not in ("bullets", "ritual") and not b.get("text"): errs.append(f"{aid} block {i}: text missing")
    return errs


def next_lunation(days):
    import astronomy
    now = astronomy.Time.Now()
    best = None
    for angle, name, key in ((0, "Yeni Ay", "new-moon"), (180, "Dolunay", "full-moon")):
        t = astronomy.SearchMoonPhase(angle, now, days)
        if t and (best is None or t.ut < best[0].ut):
            best = (t, name, key)
    if not best:
        sys.exit(f"No New/Full Moon in the next {days} days")
    t, name, key = best
    lon = astronomy.Ecliptic(astronomy.GeoVector(astronomy.Body.Moon, t, True)).elon
    sign = int(lon // 30) % 12
    date = (t.Utc() + dt.timedelta(hours=3)).date()  # Türkiye time
    return {
        "topic": f"{SIGNS[sign]} burcunda {name} ({date.strftime('%d.%m.%Y')}, {int(lon % 30)}°)",
        "date": date.isoformat(), "sign": sign, "header": name, "slug": f"{date:%Y-%m}-{key}-{sign}",
    }


PROMPT = """Sen "Full Moon Calendar" uygulamasının astroloji yazarısın. Sıcak, samimi, hafif esprili ve "siz" diliyle yazıyorsun.
Kesin kehanet, sağlık/para/hukuk tavsiyesi yok. Konu: {topic}

Uygulamadaki blog formatına uygun, yaklaşık 600-800 kelimelik bir yazı yaz. SADECE şu JSON'u döndür:
{{"title": "başlık (en fazla 70 karakter)",
 "subtitle": "kısa alt başlık, tarih aralığıyla",
 "blocks": [
  {{"type":"lead","text":"giriş cümlesi"}},
  {{"type":"paragraph","text":"..."}},
  {{"type":"heading","text":"Bu Dönem Neler Hissettirebilir?"}},
  {{"type":"subheading","text":"Aklınızdan şunlar geçebilir:"}},
  {{"type":"bullets","items":["...","..."]}},
  {{"type":"heading","text":"Ritüeller"}},
  {{"type":"ritual","title":"1. ...","text":"..."}},
  {{"type":"note","text":"Genel yorum olduğuna dair kısa kapanış notu"}}
 ]}}
Blok tipleri yalnızca: lead, paragraph, heading, subheading, bullets, ritual, note. 3-4 ritüel yaz."""


def draft(topic):
    import anthropic
    msg = anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=4000, temperature=0.8,
        messages=[{"role": "user", "content": PROMPT.format(topic=topic)}])
    text = "".join(c.text for c in msg.content if c.type == "text")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true", help="next New/Full Moon")
    ap.add_argument("--days", type=float, default=10)
    ap.add_argument("--topic"); ap.add_argument("--date"); ap.add_argument("--sign", type=int)
    ap.add_argument("--header", default="Gökyüzü"); ap.add_argument("--id")
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()

    feed = json.load(open(FEED, encoding="utf-8"))
    if a.validate:
        errs = validate(feed)
        print("\n".join(errs) or f"OK — {len(feed['articles'])} articles")
        sys.exit(1 if errs else 0)

    if a.auto:
        info = next_lunation(a.days)
    elif a.topic and a.date:
        info = {"topic": a.topic, "date": a.date, "sign": a.sign, "header": a.header,
                "slug": a.id or f"{a.date[:7]}-" + re.sub(r"[^a-z0-9]+", "-", a.topic.lower()).strip("-")[:40]}
    else:
        ap.error("use --auto, or --topic and --date")

    if any(x["id"] == info["slug"] for x in feed["articles"]):
        print("Already in the feed:", info["slug"]); return
    body = draft(info["topic"])
    art = {"id": info["slug"], "headerTitle": info["header"], "title": body["title"], "subtitle": body["subtitle"],
           "date": info["date"], "sign": info["sign"], "image": None, "lang": "tr", "blocks": body["blocks"]}
    feed["articles"].insert(0, art)
    errs = validate(feed)
    if errs: sys.exit("Draft failed validation:\n" + "\n".join(errs))
    json.dump(feed, open(FEED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Added", art["id"], "—", art["title"])


if __name__ == "__main__":
    main()
