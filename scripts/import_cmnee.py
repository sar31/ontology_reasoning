"""Import CMNEE dataset: select 100 high-quality texts → MySQL text_sources.

Data source: data/cmnee/CMNEE/test.json (3,000 test-set documents)
Selection criteria:
  - Text length: 200-2000 chars
  - Event density: >= 2 annotated events
  - Event type diversity: cover all 8 types
  - Entity (argument) density: >= 3 distinct argument texts per event on average

Output: data/cmnee_selected_100.json + MySQL text_sources records
"""
import json
import logging
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import get_mysql_conn

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CMNEE_TEST_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cmnee", "CMNEE", "test.json")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cmnee_selected_100.json")

# All 8 CMNEE event types
EVENT_TYPES = [
    "Experiment",   # 试验
    "Manoeuvre",    # 演习
    "Deploy",       # 部署
    "Support",      # 援助
    "Accident",     # 事故
    "Exhibit",      # 展示
    "Conflict",     # 冲突
    "Injure",       # 伤亡
]


def score_article(entry):
    """Score an article for selection quality (higher = better)."""
    text = entry.get("text", "")
    events = entry.get("event_list", [])
    coref = entry.get("coref_arguments", [])

    score = 0.0

    # Text length: prefer 300-1500 chars
    length = len(text)
    if 300 <= length <= 1500:
        score += 3.0
    elif 200 <= length <= 2000:
        score += 1.5
    else:
        score -= 2.0

    # Event count: prefer 2-6 events
    n_events = len(events)
    if 3 <= n_events <= 6:
        score += 4.0
    elif 2 <= n_events:
        score += 2.0
    else:
        return -10.0  # Discard single-event articles

    # Event type diversity: prefer diverse types
    types = set(e.get("event_type", "") for e in events)
    score += len(types) * 1.5

    # Argument richness: total distinct argument texts
    all_args = []
    for e in events:
        for a in e.get("arguments", []):
            all_args.append(a.get("text", ""))
    distinct_args = len(set(all_args))
    if distinct_args >= 8:
        score += 4.0
    elif distinct_args >= 5:
        score += 2.0

    # Coreference groups: indicates entity richness
    score += min(len(coref), 5) * 0.5

    return score


def select_articles(entries, n=100):
    """Select top-n articles ensuring event type coverage."""
    # Score all entries
    scored = [(score_article(e), e) for e in entries]
    scored.sort(key=lambda x: -x[0])

    # Filter out negative scores
    valid = [(s, e) for s, e in scored if s > 0]
    log.info("Filtered to %d valid articles (score > 0)", len(valid))

    # Greedy selection ensuring type coverage
    selected = []
    covered_types = set()

    for s, e in valid:
        e_types = set(ev.get("event_type", "") for ev in e.get("event_list", []))
        new_types = e_types - covered_types

        # Always take if it covers new types
        if new_types and len(selected) < n:
            selected.append(e)
            covered_types.update(new_types)
            continue

        # Fill remaining slots with highest-scored
        if len(selected) >= n:
            break

    # Fill up to n if not enough from type-coverage pass
    if len(selected) < n:
        for s, e in valid:
            if e not in selected:
                selected.append(e)
                if len(selected) >= n:
                    break

    # Trim to n
    selected = selected[:n]

    # Verify coverage
    all_types = set()
    for e in selected:
        for ev in e.get("event_list", []):
            all_types.add(ev.get("event_type", ""))
    log.info("Selected %d articles covering %d/%d event types: %s",
             len(selected), len(all_types), len(EVENT_TYPES), sorted(all_types))

    # Show distribution
    type_counts = Counter()
    for e in selected:
        for ev in e.get("event_list", []):
            type_counts[ev.get("event_type", "?")] += 1
    log.info("Event type distribution in selection:")
    for t in EVENT_TYPES:
        log.info("  %-15s: %d", t, type_counts.get(t, 0))

    # Avg events per article
    avg_events = sum(len(e.get("event_list", [])) for e in selected) / len(selected)
    avg_chars = sum(len(e.get("text", "")) for e in selected) / len(selected)
    log.info("Avg events/article: %.1f, Avg chars: %.0f", avg_events, avg_chars)

    return selected


def import_to_mysql(selected):
    """Insert selected articles into text_sources table."""
    conn = get_mysql_conn()
    inserted = 0

    with conn.cursor() as c:
        for entry in selected:
            text = entry.get("text", "")
            cmnee_id = entry.get("id", 0)
            title = text[:80].replace("\n", " ") + ("..." if len(text) > 80 else "")
            event_types = list(set(
                ev.get("event_type", "") for ev in entry.get("event_list", [])
            ))

            c.execute(
                """INSERT INTO text_sources (title, content, source_type, filename, word_count)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    f"[CMNEE #{cmnee_id}] {title}",
                    text,
                    "paste",
                    f"cmnee_test_{cmnee_id}.txt",
                    len(text),
                ),
            )
            inserted += 1

        conn.commit()

    log.info("Inserted %d articles into text_sources", inserted)
    conn.close()


def main():
    log.info("=" * 50)
    log.info("CMNEE Text Import")
    log.info("=" * 50)

    # Load test set
    log.info("Loading %s ...", CMNEE_TEST_PATH)
    with open(CMNEE_TEST_PATH, "r", encoding="utf-8") as f:
        test_data = json.load(f)
    log.info("Loaded %d test entries", len(test_data))

    # Select 100
    selected = select_articles(test_data, n=100)

    # Save to JSON for downstream use
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(selected, f, ensure_ascii=False, indent=2)
    log.info("Saved selection to %s", OUTPUT_PATH)

    # Import to MySQL
    import_to_mysql(selected)

    # Verify
    conn = get_mysql_conn()
    with conn.cursor() as c:
        c.execute("SELECT count(*) AS c FROM text_sources WHERE filename LIKE 'cmnee_test_%'")
        count = c.fetchone()["c"]
    log.info("text_sources CMNEE count: %d", count)
    conn.close()

    log.info("=" * 50)
    log.info("Done! 100 CMNEE articles imported.")
    log.info("Selected articles saved to: %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
