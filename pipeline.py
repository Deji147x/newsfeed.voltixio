#!/usr/bin/env python3
import os, json, time, hashlib, logging, argparse, re
from datetime import datetime, timezone
from pathlib import Path
from email.utils import format_datetime
import feedparser, requests
from slugify import slugify

BASE_DIR   = Path("/var/www/newsfeed.voltixio.com")
FEEDS_DIR  = BASE_DIR / "public" / "feeds"
IMAGES_DIR = BASE_DIR / "public" / "images"
LOG_FILE   = BASE_DIR / "logs" / "pipeline.log"
BASE_URL   = "https://newsfeed.voltixio.com"
MAX_ITEMS  = 30
IMAGE_W    = 1200
IMAGE_H    = 630

RSS_SOURCES = {
    "technology":    ["https://feeds.feedburner.com/TechCrunch", "https://www.wired.com/feed/rss"],
    "ai":            ["https://venturebeat.com/category/ai/feed/", "https://www.technologyreview.com/feed/"],
    "cybersecurity": ["https://feeds.feedburner.com/TheHackersNews", "https://www.bleepingcomputer.com/feed/"],
    "business":      ["https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"],
    "fintech":       ["https://techcrunch.com/category/fintech/feed/"],
    "sports":        ["https://www.espn.com/espn/rss/news", "https://feeds.bbci.co.uk/sport/rss.xml"],
    "politics":      ["https://rss.politico.com/politics-news.xml", "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml"],
    "health":        ["https://rss.medicalnewstoday.com/featurednews.xml"],
    "science":       ["https://www.sciencedaily.com/rss/all.xml"],
    "entertainment": ["https://variety.com/feed/", "https://deadline.com/feed/"],
    "local":         ["https://feeds.feedburner.com/baltimoresun/news"],
    "world":         ["https://feeds.bbci.co.uk/news/world/rss.xml"],
    "us":            ["https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml"],
}

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger("voltixio")


def ai_rewrite(title, summary, vertical, dry_run=False):
    clean = lambda s: re.sub(r'[^\w\s\.\,\-\!\?]', ' ', str(s)).strip()
    safe_title   = clean(title)[:80]
    safe_summary = clean(summary)[:300]
    fallback = {
        "title":        safe_title,
        "summary":      safe_summary[:200],
        "body":         "<p>" + safe_summary + "</p>",
        "image_prompt": "editorial news photograph " + safe_title[:50] + " cinematic lighting"
    }
    if dry_run:
        return fallback
    groq_key = os.environ.get("GROQ_KEY", "")
    if not groq_key:
        log.warning("GROQ_KEY not set - using original text")
        return fallback
    prompt = (
        "You are a news journalist. Rewrite this article.\n"
        "Headline: " + safe_title + "\n"
        "Summary: " + safe_summary + "\n\n"
        "Respond with ONLY a JSON object, no explanation, no markdown:\n"
        '{"title":"improved headline under 90 chars",'
        '"summary":"two sentence summary",'
        '"body":"<p>article body 200 words</p>",'
        '"image_prompt":"photorealistic editorial photograph cinematic 16x9 no text"}'
    )
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": "Bearer " + groq_key,
                "Content-Type": "application/json"
            },
            json={
                "model":       "llama-3.1-8b-instant",
                "messages":    [{"role": "user", "content": prompt}],
                "temperature": 0.5,
                "max_tokens":  600
            },
            timeout=15
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw).strip()
        result = json.loads(raw)
        for k in ("title", "summary", "body", "image_prompt"):
            if k not in result:
                result[k] = fallback[k]
        log.info("Groq rewrite OK: " + result["title"][:50])
        return result
    except Exception as e:
        log.warning("Groq failed (" + str(e) + ") - using original")
        return fallback


def generate_image(prompt, slug, dry_run=False):
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    img_path = IMAGES_DIR / (slug + ".jpg")
    if img_path.exists():
        return BASE_URL + "/images/" + slug + ".jpg"
    if dry_run:
        return BASE_URL + "/images/placeholder.jpg"
    seed_val = abs(hash(slug)) % 1000
    url = "https://picsum.photos/seed/" + str(seed_val) + "/1200/630"
    try:
        r = requests.get(url, timeout=15, allow_redirects=True)
        r.raise_for_status()
        img_path.write_bytes(r.content)
        log.info("Image saved: " + slug + ".jpg (" + str(len(r.content)//1024) + "KB)")
        return BASE_URL + "/images/" + slug + ".jpg"
    except Exception as e:
        log.warning("Image failed " + slug + ": " + str(e))
        return BASE_URL + "/images/default.jpg"


def build_rss(vertical, items, filename):
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)
    now   = format_datetime(datetime.now(timezone.utc))
    label = vertical.replace("-", " ").title()
    entries = ""
    for item in items:
        pub = format_datetime(item.get("pub_date", datetime.now(timezone.utc)))
        entries += (
            "\n    <item>"
            "\n      <title><![CDATA[" + item["title"] + "]]></title>"
            "\n      <link>" + BASE_URL + "/article/" + item["slug"] + "</link>"
            "\n      <guid isPermaLink='true'>" + BASE_URL + "/article/" + item["slug"] + "</guid>"
            "\n      <pubDate>" + pub + "</pubDate>"
            "\n      <dc:creator>VoltixIO AI</dc:creator>"
            "\n      <category>" + item.get("vertical", vertical) + "</category>"
            "\n      <description><![CDATA[" + item["summary"] + "]]></description>"
            "\n      <content:encoded><![CDATA[<img src='" + item["image_url"] + "' style='width:100%;border-radius:8px;margin-bottom:16px'>" + item["body"] + "]]></content:encoded>"
            "\n      <media:content url='" + item["image_url"] + "' medium='image' width='" + str(IMAGE_W) + "' height='" + str(IMAGE_H) + "' type='image/jpeg'/>"
            "\n    </item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"\n'
        '  xmlns:media="http://search.yahoo.com/mrss/"\n'
        '  xmlns:content="http://purl.org/rss/1.0/modules/content/"\n'
        '  xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '  xmlns:atom="http://www.w3.org/2005/Atom">\n'
        '  <channel>\n'
        '    <title>VoltixIO NewsFeed - ' + label + '</title>\n'
        '    <link>' + BASE_URL + '</link>\n'
        '    <description>AI-curated ' + label + ' news by VoltixIO.</description>\n'
        '    <language>en-us</language>\n'
        '    <lastBuildDate>' + now + '</lastBuildDate>\n'
        '    <ttl>20</ttl>\n'
        '    <atom:link href="' + BASE_URL + '/feeds/' + filename + '" rel="self" type="application/rss+xml"/>\n'
        + entries +
        '\n  </channel>\n</rss>'
    )
    (FEEDS_DIR / filename).write_text(xml, encoding="utf-8")
    log.info("Feed written: " + filename + " (" + str(len(items)) + " items)")


def process_vertical(vertical, dry_run=False):
    items = []
    seen  = set()
    for src in RSS_SOURCES.get(vertical, []):
        try:
            feed = feedparser.parse(src)
            log.info("Fetched " + str(len(feed.entries)) + " from " + src)
        except Exception as e:
            log.warning("Failed " + src + ": " + str(e))
            continue
        for entry in feed.entries[:8]:
            raw_title   = str(entry.get("title", "")).strip()
            raw_summary = re.sub(r'<[^>]+>', '', str(entry.get("summary", entry.get("description", "")))).strip()
            if not raw_title or len(raw_title) < 10:
                continue
            slug = slugify(raw_title)[:80]
            if slug in seen:
                continue
            seen.add(slug)
            try:
                pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc) if hasattr(entry, 'published_parsed') and entry.published_parsed else datetime.now(timezone.utc)
            except Exception:
                pub = datetime.now(timezone.utc)
            log.info("Processing: " + raw_title[:60])
            ai  = ai_rewrite(raw_title, raw_summary, vertical, dry_run)
            img = generate_image(ai.get("image_prompt", raw_title), slug, dry_run)
            items.append({
                "slug":       slug,
                "title":      ai["title"],
                "summary":    ai["summary"],
                "body":       ai["body"],
                "image_url":  img,
                "source_url": str(entry.get("link", "")),
                "vertical":   vertical,
                "pub_date":   pub,
            })
            if len(items) >= MAX_ITEMS:
                break
            time.sleep(2.0)
        if len(items) >= MAX_ITEMS:
            break
    return items


def run(target=None, dry_run=False):
    log.info("=== VoltixIO pipeline starting" + (" (DRY RUN)" if dry_run else "") + " ===")
    t0 = time.time()
    verticals = [target] if target else list(RSS_SOURCES.keys())
    all_items = []
    for v in verticals:
        log.info("--- " + v + " ---")
        items = process_vertical(v, dry_run)
        if items:
            build_rss(v, items, v + ".xml")
            all_items.extend(items)
    sorted_items = sorted(all_items, key=lambda x: x["pub_date"], reverse=True)
    build_rss("all", sorted_items[:60], "uglyfeed.xml")
    log.info("=== Done: " + str(len(all_items)) + " articles in " + str(round(time.time()-t0, 1)) + "s ===")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--vertical")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    run(a.vertical, a.dry_run)
