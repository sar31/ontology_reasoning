"""Generate military news text data based on database content.

Uses LLM to create semi-realistic military/geopolitical news articles,
then imports them as text_sources and indexes into the vector store.
"""
import json
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from db import get_mysql_conn
from llm_client import call_qwen
from text_source import create_text_source, list_text_sources
import requests

# ---------------------------------------------------------------------------
# News generation prompt
# ---------------------------------------------------------------------------

NEWS_PROMPT = """你是一位军事新闻记者。请基于以下事件信息，撰写一篇150-300字的中文军事新闻。

事件信息：
- 标题：{title}
- 类型：{event_type}
- 时间：{start_time}
- 地点：{location}
- 国家：{country}
- 严重程度：{severity}
- 摘要：{summary}

参与组织：{organizations}
参与人员：{persons}
涉及装备：{equipments}
涉及设施：{facilities}

要求：
1. 新闻风格，客观报道
2. 包含具体的时间、地点、参与方
3. 150-300字
4. 只输出新闻正文，不要标题
"""


def fetch_event_details():
    """Fetch events with related entities from MySQL."""
    conn = get_mysql_conn()
    with conn.cursor() as cur:
        # Get events
        cur.execute("""
            SELECT e.id, e.title, e.event_type, e.start_time, e.primary_location,
                   cr.name AS country_name, e.severity, e.summary
            FROM events e
            LEFT JOIN countries_regions cr ON e.country_id = cr.id
            ORDER BY e.id
        """)
        events = cur.fetchall()

        for evt in events:
            eid = evt["id"]

            # Related organizations
            cur.execute("""
                SELECT o.name, eo.role
                FROM event_organizations eo
                JOIN organizations o ON eo.organization_id = o.id
                WHERE eo.event_id = %s LIMIT 5
            """, (eid,))
            evt["organizations"] = cur.fetchall()

            # Related persons
            cur.execute("""
                SELECT p.full_name, ep.role
                FROM event_persons ep
                JOIN persons p ON ep.person_id = p.id
                WHERE ep.event_id = %s LIMIT 5
            """, (eid,))
            evt["persons"] = cur.fetchall()

            # Related equipments
            cur.execute("""
                SELECT e.name, ee.usage_type
                FROM event_equipments ee
                JOIN equipments e ON ee.equipment_id = e.id
                WHERE ee.event_id = %s LIMIT 5
            """, (eid,))
            evt["equipments"] = cur.fetchall()

            # Related facilities
            cur.execute("""
                SELECT f.name, ef.impact_type
                FROM event_facilities ef
                JOIN facilities f ON ef.facility_id = f.id
                WHERE ef.event_id = %s LIMIT 5
            """, (eid,))
            evt["facilities"] = cur.fetchall()

    conn.close()
    return events


def generate_news(events, limit=30):
    """Generate news articles from events using LLM."""
    articles = []
    for i, evt in enumerate(events[:limit]):
        print(f"Generating news [{i+1}/{limit}]: {evt.get('title', 'N/A')}")

        prompt = NEWS_PROMPT.format(
            title=evt.get("title", ""),
            event_type=evt.get("event_type", ""),
            start_time=str(evt.get("start_time", "")),
            location=evt.get("primary_location", "未指定"),
            country=evt.get("country_name", "未指定"),
            severity=evt.get("severity", ""),
            summary=(evt.get("summary") or evt.get("detailed_description") or "")[:200],
            organizations=json.dumps(evt.get("organizations", []), ensure_ascii=False),
            persons=json.dumps(evt.get("persons", []), ensure_ascii=False),
            equipments=json.dumps(evt.get("equipments", []), ensure_ascii=False),
            facilities=json.dumps(evt.get("facilities", []), ensure_ascii=False),
        )

        try:
            response = call_qwen(
                "你是一位军事新闻记者，请根据提供的信息撰写新闻稿。",
                prompt,
                temperature=0.7,
            )
            if isinstance(response, dict) and "answer" in response:
                text = response["answer"]
            elif isinstance(response, str):
                text = response
            else:
                # Call raw (non-JSON mode)
                from openai import OpenAI
                import os
                client = OpenAI(
                    api_key=os.getenv("QWEN_API_KEY", ""),
                    base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                )
                resp = client.chat.completions.create(
                    model="qwen3.6-plus",
                    messages=[
                        {"role": "system", "content": "你是一位军事新闻记者，请根据提供的信息撰写新闻稿。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                )
                text = resp.choices[0].message.content
        except Exception as e:
            print(f"  LLM call failed: {e}")
            text = f"（新闻生成失败）{evt.get('title', '')}: {evt.get('summary', '')}"

        articles.append({
            "title": evt.get("title", ""),
            "content": text.strip(),
            "event_id": evt["id"],
        })
        time.sleep(0.5)  # Rate limiting

    return articles


def import_and_index(articles, base_url="http://localhost:5000"):
    """Import articles as text_sources and index into vector store."""
    # First, import as text_sources via API
    imported = []
    for a in articles:
        try:
            resp = requests.post(
                f"{base_url}/api/extract/text",
                json={"title": a["title"], "text": a["content"]},
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                text_source_id = data.get("text_source_id")
                imported.append({"id": text_source_id, "title": a["title"]})
                print(f"  Imported text_source #{text_source_id}: {a['title'][:50]}")
            else:
                print(f"  Import failed: {resp.status_code}")
        except Exception as e:
            print(f"  Import error: {e}")
        time.sleep(0.5)

    # Then index into vector store
    print(f"\nIndexing {len(articles)} articles into vector store...")
    try:
        resp = requests.post(
            f"{base_url}/api/vector/index-texts",
            timeout=300,
        )
        print(f"  Index result: {resp.json()}")
    except Exception as e:
        print(f"  Index error: {e}")

    return imported


def main():
    print("=" * 50)
    print("Fetching events from database...")
    events = fetch_event_details()
    print(f"Found {len(events)} events")

    print(f"\nGenerating news articles for first 30 events...")
    articles = generate_news(events, limit=30)

    print(f"\nSaving articles to file...")
    save_path = os.path.join(os.path.dirname(__file__), "..", "data", "generated_news.json")
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(articles)} articles to {save_path}")

    print(f"\nImporting and indexing articles...")
    imported = import_and_index(articles)
    print(f"Imported {len(imported)} text sources")

    print("\nDone!")
    return articles


if __name__ == "__main__":
    main()
