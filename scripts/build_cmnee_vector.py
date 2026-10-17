"""Build TF-IDF vector index from CMNEE selected articles for Method E."""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from vector_store import index_texts, get_stats

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SELECTED_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cmnee_selected_100.json")


def main():
    log.info("=" * 50)
    log.info("Build CMNEE Vector Index")
    log.info("=" * 50)

    with open(SELECTED_PATH, "r", encoding="utf-8") as f:
        articles = json.load(f)
    log.info("Loaded %d articles", len(articles))

    # Prepare texts with metadata
    texts = []
    for article in articles:
        text = article.get("text", "")
        meta = {
            "article_id": article.get("id"),
            "event_count": len(article.get("event_list", [])),
            "event_types": list(set(e.get("event_type", "") for e in article.get("event_list", []))),
        }
        texts.append((text, meta))

    # Index
    index_texts(texts)
    stats = get_stats()
    log.info("Index stats: %s", stats)
    log.info("Done!")


if __name__ == "__main__":
    main()
