# ELHG Finder

Mines public Q&A sites for **unmet demand** — the questions people ask when
they're about to spend money — and clusters them into things you could build
and sell from home.

The premise: people reveal what they'd buy by the *shape* of the sentence, not
by naming a product. "Does anyone know a tool that…", "I'd pay someone to…",
"where do I start with…" are demand. "Notion" is just a noun. So the crawler
searches for **intent patterns crossed with topic seeds**, scores what it finds
by how close the phrasing sits to a purchase, and lets Claude cluster the
survivors into named opportunities.

## What it searches

| Source | Access | API key |
|---|---|---|
| Reddit | Official OAuth API | free, required |
| Hacker News | Algolia search API | **none** |
| Stack Exchange | Public API (300 req/day) | **none** |
| Quora, JustAnswer, anywhere | Search API with `site:` filters | one of Brave / Serper / Google |

Quora and JustAnswer forbid scraping in their terms and sit behind bot
protection, so this tool never crawls them directly. It asks a search API for
`site:quora.com "I would pay for" bookkeeping` and works from indexed titles
and snippets — shallower than a crawl, and it won't get you blocked or sued.

**Hacker News and Stack Exchange need no credentials at all**, so you can run a
real crawl before signing up for anything.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml     # edit the topics list
cp .env.example .env                   # add keys as you get them
set -a && source .env && set +a

python -m elhg_finder.cli crawl --sources hackernews,stackexchange
python -m elhg_finder.cli top -n 20
python -m elhg_finder.cli serve        # dashboard at http://127.0.0.1:8000
```

Add `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` (free, 2 minutes at
<https://www.reddit.com/prefs/apps> — choose "script") and Reddit joins the
crawl. Add a search API key and Quora/JustAnswer join too.

## Commands

| Command | Does |
|---|---|
| `crawl` | One pass over every configured source |
| `top` | Highest-demand findings in the terminal |
| `analyze` | Cluster findings into market opportunities (needs `ANTHROPIC_API_KEY`) |
| `serve` | Web dashboard — browse, filter, star, trigger runs |
| `schedule` | Run crawls on the configured cron, in the foreground |
| `stats` | What's in the database, and recent run history |
| `export` | Everything to CSV |
| `init` | Write a starter `config.yaml` |

## How the demand score works

Four components, in `elhg_finder/scoring.py`. Argue with the weights — they're
one file and they're meant to be tuned.

- **Intent** — what the phrasing reveals. "I would pay for" (5.0) outranks
  "can someone explain" (2.0). Takes the *highest* signal rather than the sum,
  so a rambling post can't outscore a short one that says "I'll pay."
- **Engagement** — upvotes and replies, log-scaled so one viral thread doesn't
  flatten everything else.
- **Recency** — six-month half-life. Demand from 2019 is history, not a market.
- **Unanswered bonus** — a question nobody answered is a customer nobody
  served. The strongest single signal in the tool.

## Tuning it

Everything lives in two files:

- **`config.yaml`** — topics, subreddits, sites, schedule, quota caps.
  Fewer topics means deeper coverage of each and far fewer API calls.
- **`elhg_finder/signals.py`** — the demand patterns themselves. Add a phrasing
  you've noticed people use and it's searched everywhere immediately.

Watch `websearch_max_queries`: it's a hard per-run cap so a long topic list
can't burn a month of your free search tier in one crawl.

## Adding a source

Subclass `Source` in `elhg_finder/sources/`, implement `available()` and
`search()`, register it in `sources/__init__.py`. Scoring, dedup, storage, and
the dashboard pick it up automatically.

## Notes on failure

A crawl that connects to nothing is reported as a **failure**, not as an empty
market — `describe()` distinguishes "matched nothing, try broader topics" from
"every query failed, check your credentials." That distinction matters when
this runs unattended on a schedule.

## Tests

```bash
python -m pytest tests/ -q     # 59 tests, no network required
```
