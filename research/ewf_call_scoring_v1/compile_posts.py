"""Phase 2: compile raw API pages into data/ewf_posts.parquet + print an inventory report.

Inventory: posts/year, category mix (incl. bluebox-wins share), top instrument tags,
edit-lag distribution (modified_gmt - date_gmt), and body-text length stats.

Run:  ./run_research.sh python research/ewf_call_scoring_v1/compile_posts.py
"""

import html
import json
import re
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"
RAW = DATA / "raw_pages"


def strip_html(s: str) -> str:
    s = re.sub(r"<script[^>]*>.*?</script>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def main() -> None:
    cats = {c["id"]: c["name"] for c in json.loads((RAW / "categories.json").read_text())}
    tags = {t["id"]: t["name"] for t in json.loads((RAW / "tags.json").read_text())}

    rows = []
    for page in sorted(RAW.glob("posts_p*.json")):
        for p in json.loads(page.read_text()):
            rows.append(
                {
                    "id": p["id"],
                    "date_gmt": p["date_gmt"],
                    "modified_gmt": p["modified_gmt"],
                    "slug": p["slug"],
                    "link": p["link"],
                    "title": strip_html(p["title"]["rendered"]),
                    "categories": [cats.get(c, f"?{c}") for c in p["categories"]],
                    "tags": [tags.get(t, f"?{t}") for t in p["tags"]],
                    "content_html": p["content"]["rendered"],
                    "content_text": strip_html(p["content"]["rendered"]),
                }
            )

    df = pd.DataFrame(rows).drop_duplicates(subset="id").sort_values("date_gmt")
    df["date_gmt"] = pd.to_datetime(df["date_gmt"])
    df["modified_gmt"] = pd.to_datetime(df["modified_gmt"])
    df["edit_lag_days"] = (df["modified_gmt"] - df["date_gmt"]).dt.total_seconds() / 86400
    df["text_len"] = df["content_text"].str.len()

    out = DATA / "ewf_posts.parquet"
    df.to_parquet(out, index=False)
    print(f"saved {len(df)} posts -> {out}  ({out.stat().st_size / 1e6:.1f} MB)\n")

    print("== posts per year ==")
    print(df.groupby(df["date_gmt"].dt.year).size().to_string())

    print("\n== category mix (a post can hold several) ==")
    print(df.explode("categories")["categories"].value_counts().head(20).to_string())

    print("\n== top 40 tags (instrument candidates) ==")
    print(df.explode("tags")["tags"].value_counts().head(40).to_string())

    print("\n== edit lag (days, modified - published) ==")
    q = df["edit_lag_days"].quantile([0.5, 0.75, 0.9, 0.95, 0.99])
    print(q.to_string())
    print(f"share edited > 7 days after publication: {(df['edit_lag_days'] > 7).mean():.1%}")

    print("\n== body length (chars) ==")
    print(df["text_len"].describe(percentiles=[0.1, 0.5, 0.9]).to_string())


if __name__ == "__main__":
    main()
