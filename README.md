# VoltixIO NewsFeed

AI-curated news site at [newsfeed.voltixio.com](https://newsfeed.voltixio.com). A Python pipeline pulls ~60 RSS sources across 13 verticals, rewrites each story with an LLM, attaches an image, and publishes RSS feeds + sitemaps consumed by a static front-end.

## Architecture

```
RSS sources ──> pipeline.py ──> public/feeds/*.xml   (per-vertical RSS + uglyfeed.xml master feed)
                    │      └──> public/sitemap.xml, public/sitemap-news.xml
                    ├── LLM rewrite: OpenRouter (gemma-4-31b-it:free) → Groq (llama-3.1-8b-instant) → local Ollama (gemma2:9b) → original-text fallback
                    └── Images: source og:image → LoremFlickr keywords → Picsum (7-day cache in public/images/)

public/index.html    Front-end shell; renders articles client-side from /feeds/uglyfeed.xml
public/article.html  Article page, served for /article/<slug> via web-server rewrite
```

Fallback articles (all LLMs failed) are marked `ai_ok: false` and excluded from the Google News sitemap.

## Deployment

Runs on the VPS at `/var/www/newsfeed.voltixio.com` (path is hard-coded as `BASE_DIR` in `pipeline.py`). The `public/` directory is the web docroot.

```bash
# on the server
cd /var/www/newsfeed.voltixio.com
pip install -r requirements.txt
python3 pipeline.py                    # full run, all verticals
python3 pipeline.py --vertical ai      # single vertical
python3 pipeline.py --dry-run          # no LLM/image calls
```

Schedule with cron, e.g. hourly:

```cron
0 * * * * cd /var/www/newsfeed.voltixio.com && python3 pipeline.py >> logs/cron.log 2>&1
```

### Environment variables

| Variable | Purpose |
|---|---|
| `OPENROUTER_KEY` | Primary LLM rewrites (free tier) |
| `GROQ_KEY` | Secondary LLM fallback |

Both optional — the chain degrades to local Ollama (`gemma2:9b` at `localhost:11434`), then to lightly-formatted original text. Keys must be present in the cron environment, not just the login shell.

## Monitoring

`.github/workflows/feed-health.yml` checks the live feed every 2 hours and fails (GitHub emails the repo owner) if `uglyfeed.xml` is older than 3 hours — i.e. the server cron has stopped.

## Logs

`logs/pipeline.log` on the server.
