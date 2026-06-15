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
    "technology":    [
        "https://techcrunch.com/feed/",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://www.theverge.com/rss/index.xml",
        "https://www.wired.com/feed/rss",
        "https://www.technologyreview.com/feed/",
    ],
    "ai":            [
        "https://venturebeat.com/category/ai/feed/",
        "https://blog.google/technology/ai/rss/",
        "https://openai.com/blog/rss.xml",
        "https://artificialintelligence-news.com/feed/",
        "https://news.google.com/rss/search?q=artificial+intelligence+AI+2026&hl=en-US&gl=US&ceid=US:en",
    ],
    "cybersecurity": [
        "https://feeds.feedburner.com/TheHackersNews",
        "https://krebsonsecurity.com/feed/",
        "https://www.darkreading.com/rss.xml",
        "https://www.bleepingcomputer.com/feed/",
        "https://www.schneier.com/feed/atom/",
    ],
    "business":      [
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://fortune.com/feed/",
        "https://www.fastcompany.com/latest/rss",
        "https://www.inc.com/rss",
        "https://news.google.com/rss/search?q=business+economy+markets&hl=en-US&gl=US&ceid=US:en",
    ],
    "fintech":       [
        "https://www.finextra.com/rss/headlines.aspx",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://www.pymnts.com/feed/",
        "https://decrypt.co/feed",
        "https://news.google.com/rss/search?q=fintech+cryptocurrency+banking+2026&hl=en-US&gl=US&ceid=US:en",
    ],
    "health":        [
        "https://www.who.int/rss-feeds/news-english.xml",
        "https://www.medpagetoday.com/rss/headlines.xml",
        "https://www.healthline.com/rss/health-news",
        "https://news.google.com/rss/search?q=health+medical+news+2026&hl=en-US&gl=US&ceid=US:en",
    ],
    "science":       [
        "https://www.sciencedaily.com/rss/all.xml",
        "https://www.nasa.gov/rss/dyn/breaking_news.rss",
        "https://www.newscientist.com/feed/home/",
        "https://www.nature.com/nature.rss",
        "https://phys.org/rss-feed/",
    ],
    "entertainment": [
        "https://variety.com/feed/",
        "https://www.hollywoodreporter.com/feed/",
        "https://deadline.com/feed/",
        "https://www.rollingstone.com/feed/",
        "https://news.google.com/rss/search?q=entertainment+celebrity+movies+music&hl=en-US&gl=US&ceid=US:en",
    ],
    "sports":        [
        "https://www.espn.com/espn/rss/news",
        "https://feeds.bbci.co.uk/sport/rss.xml",
        "https://www.skysports.com/rss/12040",
        "https://www.cbssports.com/rss/headlines/",
        "https://sports.yahoo.com/rss/",
        "https://feeds.bbci.co.uk/sport/tennis/rss.xml",
        "https://news.google.com/rss/search?q=tennis+WTA+ATP+tournament+2026&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Wimbledon+2026&hl=en-US&gl=US&ceid=US:en",
        "https://www.ubitennis.net/feed/",
        "https://tennishead.net/feed/",
    ],
    "politics":      [
        "https://thehill.com/feed/",
        "https://feeds.npr.org/1014/rss.xml",
        "https://api.axios.com/feed/",
        "https://www.realclearpolitics.com/index.xml",
        "https://news.google.com/rss/search?q=US+politics+congress+senate+2026&hl=en-US&gl=US&ceid=US:en",
    ],
    "local":         [
        "https://news.google.com/rss/search?q=Baltimore+Maryland+news&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Baltimore+crime+community&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Maryland+news+today&hl=en-US&gl=US&ceid=US:en",
    ],
    "world":         [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://news.google.com/rss/search?q=world+news+international&hl=en-US&gl=US&ceid=US:en",
    ],
    "us":            [
        "https://feeds.bbci.co.uk/news/rss.xml",
        "https://news.google.com/rss/search?q=United+States+news+today&hl=en-US&gl=US&ceid=US:en",
    ],
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
    # Build a decent fallback article even without Groq
    sentences = [s.strip() for s in safe_summary.replace('!','.').replace('?','.').split('.') if len(s.strip()) > 20]
    if len(sentences) >= 2:
        fallback_body = (
            "<p>" + safe_summary + "</p>"
            "<p>This development represents a notable shift in the " + vertical + " landscape. "
            "Analysts and industry watchers are paying close attention as new details continue "
            "to emerge. The broader implications for consumers, businesses, and policymakers "
            "remain to be seen, but early indicators suggest this story will have lasting "
            "relevance across multiple sectors.</p>"
            "<p>Context matters here. The " + vertical + " sector has seen significant activity "
            "in recent months, with organizations and individuals adapting to rapidly changing "
            "conditions. This latest development fits into a larger pattern of transformation "
            "that experts have been tracking carefully. Stakeholders from government, industry, "
            "and civil society are all expected to respond in the coming days.</p>"
            "<p>Looking ahead, observers will be watching closely for follow-up actions, "
            "official statements, and data that could shed more light on the full scope of "
            "this story. VoltixIO NewsFeed will continue tracking this developing situation "
            "and delivering updates as they become available from verified sources. "
            "Readers are encouraged to check back for the latest reporting.</p>"
        )
    else:
        fallback_body = "<p>" + safe_summary + "</p>"

    fallback = {
        "title":        safe_title,
        "summary":      safe_summary[:200],
        "body":         fallback_body,
        "image_query":  vertical + " news " + safe_title.split()[0] if safe_title else "news"
    }
    if dry_run:
        return fallback
    groq_key = os.environ.get("GROQ_KEY", "")
    if not groq_key:
        log.warning("GROQ_KEY not set - using original text")
        return fallback
    prompt = (
        "You are a senior journalist writing for VoltixIO NewsFeed. Write a full news article.\n"
        "Headline: " + safe_title + "\n"
        "Summary: " + safe_summary + "\n\n"
        "Write a detailed, insightful article with 4-5 paragraphs covering:\n"
        "- What happened and why it matters\n"
        "- Key details, numbers, names, context\n"
        "- Background and implications\n"
        "- What happens next or what readers should watch\n\n"
        "Respond with ONLY this JSON, no markdown, no explanation:\n"
        '{"title":"compelling headline under 90 chars","summary":"2 sentence summary","body":"<p>paragraph 1</p><p>paragraph 2</p><p>paragraph 3</p><p>paragraph 4</p><p>paragraph 5</p>","image_query":"3 specific keywords describing the visual scene of this story"}'
    )
    # Try Ollama first (local, no rate limits)
    try:
        r_ollama = requests.post(
            "http://localhost:11434/api/chat",
            headers={"Content-Type": "application/json"},
            json={
                "model":   "llama3.2",
                "messages": [{"role": "user", "content": prompt}],
                "stream":  False,
                "options": {"temperature": 0.3, "num_predict": 600}
            },
            timeout=90
        )
        r_ollama.raise_for_status()
        raw_ollama = r_ollama.json().get("message", {}).get("content", "").strip()
        raw_ollama = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw_ollama)
        raw_ollama = re.sub(r"^```[a-z]*\n?", "", raw_ollama)
        raw_ollama = re.sub(r"\n?```$", "", raw_ollama).strip()
        result_ollama = json.loads(raw_ollama)
        for k in ("title", "summary", "body"):
            if k not in result_ollama:
                result_ollama[k] = fallback[k]
        log.info("Ollama rewrite OK: " + result_ollama["title"][:50])
        return result_ollama
    except Exception as e_ollama:
        log.warning("Ollama failed (" + str(e_ollama) + ") - trying Groq")

    # Fallback: Groq API
    groq_key = os.environ.get("GROQ_KEY", "")
    if not groq_key:
        return fallback
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": "Bearer " + groq_key, "Content-Type": "application/json"},
            json={
                "model":   "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 800
            },
            timeout=20
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw).strip()
        # Strip control characters that break JSON parsing
        import re as _re2
        raw = _re2.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw)
        # Remove control characters that break JSON
        import re as _re
        raw = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
        # Fix common unicode chars that break JSON
        raw = raw.replace('\u2019',"'").replace('\u2018',"'").replace('\u201c','"').replace('\u201d','"').replace('\u2013','-').replace('\u2014','-')
        result = json.loads(raw)
        for k in ("title", "summary", "body"):
            if k not in result:
                result[k] = fallback[k]
        log.info("Groq rewrite OK: " + result["title"][:50])
        return result
    except Exception as e:
        log.warning("Ollama failed (" + str(e) + ") - using original")
        return fallback


# FLUX client singleton - initialized once, reused for all articles
_flux_client = None

def get_flux_client(token):
    global _flux_client
    if _flux_client is None and token:
        try:
            from gradio_client import Client
            _flux_client = Client("multimodalart/FLUX.1-merged", headers={"Authorization": "Bearer " + token})
            log.info("FLUX client initialized")
        except Exception as e:
            log.warning("FLUX client init failed: " + str(e)[:80])
    return _flux_client

# FLUX client singleton - initialized once, reused for all articles
_flux_client = None

def get_flux_client(token):
    global _flux_client
    if _flux_client is None and token:
        try:
            from gradio_client import Client
            _flux_client = Client("multimodalart/FLUX.1-merged", headers={"Authorization": "Bearer " + token})
            log.info("FLUX client initialized")
        except Exception as e:
            log.warning("FLUX client init failed: " + str(e)[:80])
    return _flux_client

def generate_image(prompt, slug, dry_run=False):
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    img_path = IMAGES_DIR / (slug + ".jpg")
    if img_path.exists():
        return BASE_URL + "/images/" + slug + ".jpg"
    if dry_run:
        return BASE_URL + "/images/placeholder.jpg"

    # LoremFlickr with topic-relevant keywords from article title
    import re as _re
    clean = _re.sub(r"[^a-zA-Z0-9\s]", " ", str(prompt)).strip()
    stopwords = {"the","and","for","that","with","this","from","have","will","been","they","what","when","your","after"}
    words = [w for w in clean.lower().split() if len(w) > 4 and w not in stopwords][:3]
    query = ",".join(words) if words else "news,world"
    try:
        url_lf = "https://loremflickr.com/1200/630/" + query
        r_lf = requests.get(url_lf, timeout=20, allow_redirects=True)
        r_lf.raise_for_status()
        if len(r_lf.content) > 10000:
            img_path.write_bytes(r_lf.content)
            log.info("Image saved (flickr/" + query + "): " + slug + ".jpg")
            return BASE_URL + "/images/" + slug + ".jpg"
    except Exception as e:
        log.warning("LoremFlickr failed: " + str(e))

    # Fallback: Picsum
    try:
        seed_val = abs(hash(slug)) % 1000
        r2 = requests.get("https://picsum.photos/seed/" + str(seed_val) + "/1200/630", timeout=15, allow_redirects=True)
        r2.raise_for_status()
        img_path.write_bytes(r2.content)
        log.info("Image saved (picsum): " + slug + ".jpg")
        return BASE_URL + "/images/" + slug + ".jpg"
    except Exception as e2:
        log.warning("Image failed: " + str(e2))
        return BASE_URL + "/images/placeholder.jpg" 


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
            "\n      <source_url><![CDATA[" + item.get("source_url","") + "]]></source_url>"
            "\n      <content:encoded><![CDATA[<img src='" + item["image_url"] + "' style='width:100%;border-radius:8px;margin-bottom:16px'>" + item["body"] + "<p style='margin-top:20px;padding-top:16px;border-top:1px solid #222'><a href='" + item.get("source_url","#") + "' target='_blank' rel='noopener' style='color:#378ADD;font-weight:600'>Read original article &#8599;</a></p>]]></content:encoded>"
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
            img_query = ai.get("image_query", ai.get("image_prompt", raw_title))
            img = generate_image(img_query, slug, dry_run)
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
            time.sleep(5.0)
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
            # Progressive update: refresh uglyfeed after each vertical
            _sorted = sorted(all_items, key=lambda x: x["pub_date"], reverse=True)[:120]
            build_rss("all", _sorted, "uglyfeed.xml")
            log.info("uglyfeed updated: " + str(len(_sorted)) + " articles so far")
    # Balance: take up to 5 articles per vertical, then fill remainder by recency
    from collections import defaultdict
    per_vert = defaultdict(list)
    for item in sorted(all_items, key=lambda x: x["pub_date"], reverse=True):
        per_vert[item["vertical"]].append(item)
    balanced = []
    # First pass: up to 5 per vertical
    for v_items in per_vert.values():
        balanced.extend(v_items[:8])
    # Second pass: fill to 120 by recency from remaining
    used = set(id(i) for i in balanced)
    remainder = [i for i in sorted(all_items, key=lambda x: x["pub_date"], reverse=True) if id(i) not in used]
    balanced.extend(remainder[:120-len(balanced)])
    balanced = sorted(balanced, key=lambda x: x["pub_date"], reverse=True)[:120]
    build_rss("all", balanced, "uglyfeed.xml")
    log.info("=== Done: " + str(len(all_items)) + " articles in " + str(round(time.time()-t0, 1)) + "s ===")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--vertical")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    run(a.vertical, a.dry_run)
