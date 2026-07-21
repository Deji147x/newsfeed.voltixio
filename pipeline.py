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
MIN_BODY_CHARS = 2000
MAX_BODY_CHARS = 3000

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

_PLACEHOLDER_SNIPPETS = (
    "compelling headline",
    "2 sentence summary",
    "paragraph 1</p>",
    "specific keywords describing",
)

_FILLER_PARAS = (
    "<p>This story continues to develop across the {v} sector, with additional reporting "
    "and reaction expected in the hours ahead.</p>",
    "<p>VoltixIO NewsFeed will keep tracking verified updates on this {v} story as they "
    "surface, so check back for the latest developments and analysis.</p>",
    "<p>Readers following {v} news are encouraged to watch for official statements and "
    "follow-up coverage as more details become available.</p>",
)


def _looks_like_placeholder(result):
    blob = (str(result.get("title", "")) + " " + str(result.get("summary", "")) + " " + str(result.get("body", ""))).lower()
    return any(snip in blob for snip in _PLACEHOLDER_SNIPPETS)


def _plain_len(body):
    return len(re.sub(r'<[^>]+>', '', body))


def _fit_body_length(body, vertical):
    if _plain_len(body) > MAX_BODY_CHARS:
        paras = re.findall(r'<p>.*?</p>', body, flags=re.S) or [body]
        out, total = [], 0
        for p in paras:
            p_len = len(re.sub(r'<[^>]+>', '', p))
            if out and total + p_len > MAX_BODY_CHARS:
                break
            out.append(p)
            total += p_len
        return "".join(out)
    i = 0
    while _plain_len(body) < MIN_BODY_CHARS:
        body += _FILLER_PARAS[i % len(_FILLER_PARAS)].format(v=vertical)
        i += 1
    return body


def ai_rewrite(title, summary, vertical, dry_run=False):
    clean = lambda s: re.sub(r'[^\w\s\.\,\-\!\?]', ' ', str(s)).strip()
    safe_title   = clean(title)[:80]
    safe_summary = clean(summary)[:300]
    # Build a decent fallback article even without an AI provider
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
        "body":         _fit_body_length(fallback_body, vertical),
        "image_query":  vertical + " news " + safe_title.split()[0] if safe_title else "news",
        "ai_ok":        False,
    }
    if dry_run:
        return fallback

    prompt = (
        "You are a senior journalist writing for VoltixIO NewsFeed. Write a full news article.\n"
        "Headline: " + safe_title + "\n"
        "Summary: " + safe_summary + "\n\n"
        "Write a detailed, insightful article of 2000-3000 characters (roughly 5-7 paragraphs) covering:\n"
        "- What happened and why it matters\n"
        "- Key details, numbers, names, context\n"
        "- Background and implications\n"
        "- What happens next or what readers should watch\n\n"
        "Respond with ONLY this JSON, no markdown, no explanation:\n"
        '{"title":"compelling headline under 90 chars","summary":"2 sentence summary","body":"<p>paragraph 1</p><p>paragraph 2</p><p>paragraph 3</p><p>paragraph 4</p><p>paragraph 5</p>","image_query":"3 specific keywords describing the visual scene of this story"}'
    )

    def _parse(raw):
        s = raw.find("{")
        e = raw.rfind("}") + 1
        if s >= 0 and e > s:
            raw = raw[s:e]
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw).strip()
        raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw)
        raw = raw.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"').replace('–', '-').replace('—', '-')
        result = json.loads(raw, strict=False)
        for k in ("title", "summary", "body"):
            if k not in result:
                result[k] = fallback[k]
        return result

    # Primary: OpenRouter API (fast, free models, no CPU)
    or_key = os.environ.get("OPENROUTER_KEY", "")
    if or_key:
        try:
            r_or = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": "Bearer " + or_key,
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://newsfeed.voltixio.com",
                    "X-Title": "VoltixIO NewsFeed"
                },
                json={
                    "model": "google/gemma-4-31b-it:free",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1200
                },
                timeout=20
            )
            r_or.raise_for_status()
            result_or = _parse(r_or.json()["choices"][0]["message"]["content"].strip())
            if _looks_like_placeholder(result_or):
                raise ValueError("placeholder leak from OpenRouter")
            result_or["body"] = _fit_body_length(result_or["body"], vertical)
            result_or["ai_ok"] = True
            log.info("OpenRouter rewrite OK: " + result_or["title"][:50])
            return result_or
        except Exception as e_or:
            log.warning("OpenRouter failed (" + str(e_or)[:80] + ") - trying Groq")

    # Fallback: Groq API
    groq_key = os.environ.get("GROQ_KEY", "")
    if groq_key:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": "Bearer " + groq_key, "Content-Type": "application/json"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1200
                },
                timeout=20
            )
            r.raise_for_status()
            result = _parse(r.json()["choices"][0]["message"]["content"].strip())
            if _looks_like_placeholder(result):
                raise ValueError("placeholder leak from Groq")
            result["body"] = _fit_body_length(result["body"], vertical)
            result["ai_ok"] = True
            log.info("Groq rewrite OK: " + result["title"][:50])
            return result
        except Exception as e:
            log.warning("Groq failed (" + str(e)[:80] + ") - trying Ollama")
    else:
        log.warning("GROQ_KEY not set - trying Ollama")

    # Fallback: deterministic template (guaranteed valid, no external API dependency)
    log.info("All AI providers exhausted - using deterministic template")
    return fallback


def fetch_og_image_url(article_url):
    """Scrape og:image meta tag from the original article URL, following redirects (Google News etc)."""
    if not article_url:
        return ""
    try:
        import re as _re2
        # Use requests with redirect following (handles Google News redirect links)
        resp = requests.get(article_url, timeout=6, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"})
        chunk = resp.text[:60000]
        m = (_re2.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\'>\s]+)', chunk) or
             _re2.search(r'<meta[^>]+content=["\'](https?://[^"\'>\s]+)[^>]+property=["\']og:image["\']', chunk) or
             _re2.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\'](https?://[^"\'>\s]+)', chunk))
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def generate_image(prompt, slug, dry_run=False, article_url=None, vertical=None):
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    img_path = IMAGES_DIR / (slug + ".jpg")
    if img_path.exists():
        import time as _t
        age_days = (_t.time() - img_path.stat().st_mtime) / 86400
        if age_days < 7:
            return BASE_URL + "/images/" + slug + ".jpg"
        # Stale image - delete and regenerate
        img_path.unlink()
    if dry_run:
        return BASE_URL + "/images/placeholder.jpg"

    # Priority 1: real photo scraped from the source article's og:image
    if article_url:
        try:
            og_url = fetch_og_image_url(article_url)
            if og_url:
                r_og = requests.get(og_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                r_og.raise_for_status()
                if len(r_og.content) > 8000:
                    img_path.write_bytes(r_og.content)
                    log.info("Image saved (og:image): " + slug + ".jpg")
                    return BASE_URL + "/images/" + slug + ".jpg"
        except Exception as e_og:
            log.warning("og:image failed (" + str(e_og)[:60] + ") - trying Picsum")

    # Fallback: Picsum, seeded deterministically per-slug so each article gets a
    # distinct (if generic) photo instead of a repeated stock image. LoremFlickr was
    # dropped here: when its keyword-tag search finds no match it silently serves its
    # own generic default photo instead of erroring, which the old code accepted as
    # valid - that's why thousands of unrelated articles ended up sharing one image.
    try:
        seed_val = hashlib.md5(slug.encode("utf-8")).hexdigest()[:8]
        r2 = requests.get("https://picsum.photos/seed/" + seed_val + "/1200/630", timeout=15, allow_redirects=True)
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
            "\n      <source_url><![CDATA[" + item.get("source_url", "") + "]]></source_url>"
            "\n      <content:encoded><![CDATA[<img src='" + item["image_url"] + "' style='width:100%;border-radius:8px;margin-bottom:16px'>" + item["body"] + "<p style='margin-top:20px;padding-top:16px;border-top:1px solid #222'><a href='" + item.get("source_url", "#") + "' target='_blank' rel='noopener' style='color:#378ADD;font-weight:600'>Read original article &#8599;</a></p>]]></content:encoded>"
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


def build_sitemaps(items):
    """Write sitemap.xml (all current articles) and sitemap-news.xml (Google News:
    articles under 48h old, AI-written only - boilerplate fallbacks excluded)."""
    pub_dir = BASE_DIR / "public"
    pub_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    urls = [
        "  <url>\n    <loc>" + BASE_URL + "/</loc>\n    <changefreq>always</changefreq>"
        "\n    <priority>1.0</priority>\n    <lastmod>" + now.strftime("%Y-%m-%d") + "</lastmod>\n  </url>"
    ]
    news_urls = []
    for item in items:
        loc = BASE_URL + "/article/" + item["slug"]
        urls.append(
            "  <url>\n    <loc>" + loc + "</loc>\n    <changefreq>never</changefreq>"
            "\n    <priority>0.8</priority>\n    <lastmod>" + item["pub_date"].strftime("%Y-%m-%d") + "</lastmod>\n  </url>"
        )
        age_hours = (now - item["pub_date"]).total_seconds() / 3600
        if age_hours <= 48 and item.get("ai_ok", True):
            news_urls.append(
                "  <url>\n    <loc>" + loc + "</loc>\n    <news:news>\n      <news:publication>"
                "\n        <news:name>VoltixIO NewsFeed</news:name>\n        <news:language>en</news:language>"
                "\n      </news:publication>\n      <news:publication_date>" + item["pub_date"].strftime("%Y-%m-%dT%H:%M:%SZ") + "</news:publication_date>"
                "\n      <news:title><![CDATA[" + item["title"] + "]]></news:title>\n    </news:news>\n  </url>"
            )
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">\n'
    )
    (pub_dir / "sitemap.xml").write_text(header + "\n".join(urls) + "\n</urlset>\n", encoding="utf-8")
    (pub_dir / "sitemap-news.xml").write_text(header + "\n".join(news_urls) + "\n</urlset>\n", encoding="utf-8")
    log.info("Sitemaps written: " + str(len(urls)) + " urls, " + str(len(news_urls)) + " news urls")


def process_vertical(vertical, dry_run=False, seen=None):
    items = []
    if seen is None:
        seen = set()
    for src in RSS_SOURCES.get(vertical, []):
        try:
            feed = feedparser.parse(src)
            log.info("Fetched " + str(len(feed.entries)) + " from " + src)
        except Exception as e:
            log.warning("Failed " + src + ": " + str(e))
            continue
        for entry in feed.entries[:15]:
            raw_title   = str(entry.get("title", "")).strip()
            raw_summary = re.sub(r'<[^>]+>', '', str(entry.get("summary", entry.get("description", "")))).strip()
            import html as _html
            raw_summary = _html.unescape(raw_summary)
            raw_title = _html.unescape(raw_title)
            raw_link    = str(entry.get("link", "")).strip()
            if not raw_title or len(raw_title) < 10:
                continue
            slug = slugify(raw_title)[:80]
            if slug in seen:
                continue
            seen.add(slug)
            try:
                parsed = getattr(entry, 'published_parsed', None) or getattr(entry, 'updated_parsed', None)
                pub = datetime(*parsed[:6], tzinfo=timezone.utc) if parsed else datetime.now(timezone.utc)
            except Exception:
                pub = datetime.now(timezone.utc)
            log.info("Processing: " + raw_title[:60])
            time.sleep(1.5)
            ai  = ai_rewrite(raw_title, raw_summary, vertical, dry_run)
            img_query = ai.get("image_query", ai.get("image_prompt", raw_title))
            img = generate_image(img_query, slug, dry_run, article_url=raw_link, vertical=vertical)
            items.append({
                "slug":       slug,
                "title":      ai["title"],
                "summary":    ai["summary"],
                "body":       ai["body"],
                "image_url":  img,
                "source_url": str(entry.get("link", "")),
                "vertical":   vertical,
                "pub_date":   pub,
                "ai_ok":      ai.get("ai_ok", True),
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
    global_seen = set()
    for v in verticals:
        log.info("--- " + v + " ---")
        items = process_vertical(v, dry_run, seen=global_seen)
        if items:
            build_rss(v, items, v + ".xml")
            all_items.extend(items)
            # Progressive update: refresh uglyfeed after each vertical
            _sorted = sorted(all_items, key=lambda x: x["pub_date"], reverse=True)[:120]
            build_rss("all", _sorted, "uglyfeed.xml")
            log.info("uglyfeed updated: " + str(len(_sorted)) + " articles so far")
    # Balance: take up to 8 articles per vertical, then fill remainder by recency
    from collections import defaultdict
    per_vert = defaultdict(list)
    for item in sorted(all_items, key=lambda x: x["pub_date"], reverse=True):
        per_vert[item["vertical"]].append(item)
    balanced = []
    # First pass: up to 8 per vertical (floor, so low-volume verticals aren't crowded out)
    for v_items in per_vert.values():
        balanced.extend(v_items[:8])
    # Second pass: fill to 120 by recency from remaining
    used = set(id(i) for i in balanced)
    remainder = [i for i in sorted(all_items, key=lambda x: x["pub_date"], reverse=True) if id(i) not in used]
    balanced.extend(remainder[:120 - len(balanced)])
    balanced = sorted(balanced, key=lambda x: x["pub_date"], reverse=True)[:120]
    build_rss("all", balanced, "uglyfeed.xml")
    build_sitemaps(balanced)
    log.info("=== Done: " + str(len(all_items)) + " articles in " + str(round(time.time() - t0, 1)) + "s ===")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--vertical")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    run(a.vertical, a.dry_run)
