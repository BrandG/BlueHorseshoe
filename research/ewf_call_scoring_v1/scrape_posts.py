"""Phase 1: pull the full elliottwave-forecast.com blog archive via the WordPress REST API.

Pulls every post (id, date, modified, slug, link, title, categories, tags, content)
plus the category and tag taxonomies (id -> name), so instruments can be identified
from tags without parsing prose.

Resumable: each API page is saved to data/raw_pages/posts_pNNN.json and skipped if
present and valid. Polite: 1 request / 1.2s, honest UA, exponential backoff on errors.

Run:  ./run_research.sh python research/ewf_call_scoring_v1/scrape_posts.py
Then: ./run_research.sh python research/ewf_call_scoring_v1/compile_posts.py
"""

import json
import sys
import time
from pathlib import Path

import requests

BASE = "https://elliottwave-forecast.com/wp-json/wp/v2"
OUT = Path(__file__).parent / "data" / "raw_pages"
PER_PAGE = 100
DELAY_S = 1.2
FIELDS = "id,date,date_gmt,modified,modified_gmt,slug,link,title,categories,tags,content"
UA = "BlueHorseshoe-research/1.0 (archive study; contact: brandg@gmail.com)"

session = requests.Session()
session.headers["User-Agent"] = UA


def fetch(url: str, params: dict, tries: int = 5) -> requests.Response:
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=60)
            if r.status_code == 200:
                return r
            if r.status_code == 400:  # past the last page
                return r
            print(f"  HTTP {r.status_code}, attempt {attempt + 1}/{tries}", flush=True)
        except requests.RequestException as e:
            print(f"  {type(e).__name__}: {e}, attempt {attempt + 1}/{tries}", flush=True)
        time.sleep(DELAY_S * (2 ** attempt))
    raise RuntimeError(f"gave up on {url} params={params}")


def page_ok(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        json.loads(path.read_text())
        return True
    except (json.JSONDecodeError, OSError):
        return False


def pull_taxonomy(name: str) -> None:
    """Pull all pages of a taxonomy (categories or tags) into one file."""
    out = OUT / f"{name}.json"
    if page_ok(out):
        print(f"{name}: already pulled", flush=True)
        return
    items, page = [], 1
    while True:
        r = fetch(f"{BASE}/{name}", {"per_page": 100, "page": page, "_fields": "id,name,slug,count"})
        if r.status_code == 400:
            break
        batch = r.json()
        if not batch:
            break
        items.extend(batch)
        total_pages = int(r.headers.get("X-WP-TotalPages", page))
        print(f"{name}: page {page}/{total_pages} ({len(items)} items)", flush=True)
        if page >= total_pages:
            break
        page += 1
        time.sleep(DELAY_S)
    out.write_text(json.dumps(items))
    print(f"{name}: saved {len(items)} items", flush=True)


def pull_posts() -> None:
    r = fetch(f"{BASE}/posts", {"per_page": 1, "_fields": "id"})
    total = int(r.headers["X-WP-Total"])
    total_pages = -(-total // PER_PAGE)
    print(f"posts: {total} total, {total_pages} pages of {PER_PAGE}", flush=True)
    for page in range(1, total_pages + 1):
        out = OUT / f"posts_p{page:03d}.json"
        if page_ok(out):
            continue
        r = fetch(f"{BASE}/posts", {"per_page": PER_PAGE, "page": page, "_fields": FIELDS})
        if r.status_code == 400:
            print(f"posts: page {page} returned 400 (end of archive), stopping", flush=True)
            break
        out.write_text(json.dumps(r.json()))
        if page % 10 == 0 or page == total_pages:
            print(f"posts: page {page}/{total_pages}", flush=True)
        time.sleep(DELAY_S)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pull_taxonomy("categories")
    pull_taxonomy("tags")
    pull_posts()
    n_pages = len(list(OUT.glob("posts_p*.json")))
    print(f"done: {n_pages} post pages in {OUT}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
