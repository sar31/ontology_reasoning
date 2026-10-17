"""Generate 50 evaluation questions from CMNEE selected articles and their annotations.

Question types:
  - 基础事实 (20): Direct queries from event arguments
  - 多跳推理 (20): Cross-event/entity reasoning
  - 全局理解 (10): Cross-document trend analysis

Ground truth is extracted directly from CMNEE annotations.
"""
import json
import logging
import os
import random
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SELECTED_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cmnee_selected_100.json")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cmnee_questions.json")

random.seed(42)

# CMNEE argument roles → question template mapping
BASIC_FACT_TEMPLATES = {
    "Location": {
        "pattern": "「{event_desc}」发生在哪里？",
        "type": "基础事实",
        "extract_gt": lambda arg, entry: arg["text"],
    },
    "Subject": {
        "pattern": "「{event_desc}」的参与方/主体是谁？",
        "type": "基础事实",
        "extract_gt": lambda arg, entry: arg["text"],
    },
    "Equipment": {
        "pattern": "「{event_desc}」涉及/使用了什么装备？",
        "type": "基础事实",
        "extract_gt": lambda arg, entry: arg["text"],
    },
    "Date": {
        "pattern": "「{event_desc}」发生在什么时间？",
        "type": "基础事实",
        "extract_gt": lambda arg, entry: arg["text"],
    },
    "Militaryforce": {
        "pattern": "「{event_desc}」涉及哪些军事力量？",
        "type": "基础事实",
        "extract_gt": lambda arg, entry: arg["text"],
    },
    "Result": {
        "pattern": "「{event_desc}」导致了什么结果？",
        "type": "基础事实",
        "extract_gt": lambda arg, entry: arg["text"],
    },
    "Quantity": {
        "pattern": "「{event_desc}」造成了多少人员伤亡？",
        "type": "基础事实",
        "extract_gt": lambda arg, entry: arg["text"],
    },
    "Object": {
        "pattern": "「{event_desc}」的针对对象是谁？",
        "type": "基础事实",
        "extract_gt": lambda arg, entry: arg["text"],
    },
    "Materials": {
        "pattern": "「{event_desc}」提供了什么物资？",
        "type": "基础事实",
        "extract_gt": lambda arg, entry: arg["text"],
    },
}


def get_event_desc(event, text):
    """Create a short keyword-based event description from annotation arguments.
    Returns 15-40 chars: 'Subject+Trigger+Location/Equipment' for reliable CONTAINS matching."""
    trigger = event.get("trigger", {}).get("text", "")
    subject = ""
    location = ""
    equipment = ""

    for arg in event.get("arguments", []):
        role = arg.get("role", "")
        val = arg.get("text", "").strip()
        if role == "Subject" and not subject:
            subject = val[:20]
        elif role == "Location" and not location:
            location = val[:15]
        elif role == "Equipment" and not equipment:
            equipment = val[:15]

    # Build short description
    parts = []
    if subject:
        parts.append(subject)
    if trigger and len(trigger) <= 8:
        parts.append(trigger)
    if equipment:
        parts.append(equipment)
    if location:
        parts.append(location)

    desc = "".join(parts[:4])  # max 4 parts
    if len(desc) >= 5:
        return desc[:40]

    # Fallback: use the first 30 chars of the article text
    return text[:30].replace("\n", " ").strip()


def generate_basic_fact_questions(articles, count=20):
    """Generate basic fact questions from individual event arguments."""
    candidates = []

    for article in articles:
        text = article.get("text", "")
        for event in article.get("event_list", []):
            etype = event.get("event_type", "")
            for arg in event.get("arguments", []):
                role = arg.get("role", "")
                if role in BASIC_FACT_TEMPLATES:
                    tmpl = BASIC_FACT_TEMPLATES[role]
                    event_desc = get_event_desc(event, text)
                    question = tmpl["pattern"].format(event_desc=event_desc)
                    gt = tmpl["extract_gt"](arg, article)
                    if question and gt and len(gt) >= 2:
                        candidates.append({
                            "question": question,
                            "type": "基础事实",
                            "ground_truth": gt,
                            "source_article_id": article.get("id"),
                            "event_type": etype,
                            "argument_role": role,
                            "difficulty": 1,
                        })

    log.info("Generated %d basic fact candidates", len(candidates))
    # Select diverse set (different roles, event types)
    selected = []
    role_counts = Counter()
    for c in sorted(candidates, key=lambda x: len(x["question"])):
        role = c["argument_role"]
        if role_counts[role] < 3 and len(selected) < count:
            selected.append(c)
            role_counts[role] += 1

    # Fill remaining
    for c in candidates:
        if len(selected) >= count:
            break
        if c not in selected:
            selected.append(c)

    log.info("Selected %d basic fact questions", len(selected))
    return selected[:count]


def generate_multihop_questions(articles, count=20):
    """Generate multi-hop questions by linking entities across events."""
    # Build entity → events index
    entity_events = defaultdict(list)  # entity text → [(article_id, event_idx, role)]
    for article in articles:
        aid = article.get("id")
        for ei, event in enumerate(article.get("event_list", [])):
            for arg in event.get("arguments", []):
                entity_text = arg.get("text", "").strip()
                if len(entity_text) >= 3:
                    entity_events[entity_text].append({
                        "article_id": aid,
                        "event_idx": ei,
                        "event_type": event.get("event_type", ""),
                        "role": arg.get("role", ""),
                        "event_desc": get_event_desc(event, article.get("text", "")),
                    })

    # Also use coref groups to link entity mentions
    candidates = []

    # Type A: Same entity participating in multiple events (within or across articles)
    for entity, events in entity_events.items():
        if len(events) >= 2 and len(entity) >= 4:
            # Get unique event descriptions
            unique_events = []
            seen_descs = set()
            for ev in events:
                desc = ev["event_desc"]
                if desc not in seen_descs:
                    unique_events.append(ev)
                    seen_descs.add(desc)
            if len(unique_events) >= 2:
                e1 = unique_events[0]
                e2 = unique_events[1]
                question = f"「{entity}」除了参与「{e1['event_desc']}」，还参与过什么事件？"
                # GT: the other event description
                gt = e2["event_desc"]
                candidates.append({
                    "question": question,
                    "type": "多跳推理",
                    "ground_truth": gt,
                    "source_article_id": e2["article_id"],
                    "entity": entity,
                    "difficulty": 2,
                })

    # Type B: Location → multiple event types
    location_events = defaultdict(list)
    for article in articles:
        for event in article.get("event_list", []):
            for arg in event.get("arguments", []):
                if arg.get("role") == "Location":
                    loc = arg.get("text", "").strip()
                    if len(loc) >= 3:
                        location_events[loc].append(event.get("event_type", ""))

    for loc, etypes in location_events.items():
        unique_types = set(etypes)
        if len(unique_types) >= 2 and len(loc) >= 3:
            type_names = [{"Experiment": "试验", "Conflict": "冲突", "Deploy": "部署",
                          "Manoeuvre": "演习", "Support": "援助", "Accident": "事故",
                          "Exhibit": "展示", "Injure": "伤亡"}.get(t, t) for t in unique_types]
            question = f"在「{loc}」发生过哪些类型的军事事件？"
            gt = "、".join(sorted(type_names))
            candidates.append({
                "question": question,
                "type": "多跳推理",
                "ground_truth": gt,
                "source_article_id": None,
                "location": loc,
                "difficulty": 2,
            })

    log.info("Generated %d multi-hop candidates", len(candidates))

    # Select diverse set
    random.shuffle(candidates)
    selected = candidates[:count]
    log.info("Selected %d multi-hop questions", len(selected))
    return selected


def generate_global_understanding_questions(articles, count=10):
    """Generate cross-document global understanding questions."""
    questions = []

    # Count event types across all articles
    event_type_counts = Counter()
    for article in articles:
        for event in article.get("event_list", []):
            event_type_counts[event.get("event_type", "?")] += 1

    # Count locations
    location_counts = Counter()
    for article in articles:
        for event in article.get("event_list", []):
            for arg in event.get("arguments", []):
                if arg.get("role") == "Location":
                    location_counts[arg.get("text", "").strip()] += 1

    # Count subjects (active participants)
    subject_counts = Counter()
    for article in articles:
        for event in article.get("event_list", []):
            for arg in event.get("arguments", []):
                if arg.get("role") == "Subject":
                    subject_counts[arg.get("text", "").strip()] += 1

    # Q1: Most frequent event types
    top_types = event_type_counts.most_common(3)
    type_names = {t: {"Experiment": "试验", "Conflict": "冲突", "Deploy": "部署",
                      "Manoeuvre": "演习", "Support": "援助", "Accident": "事故",
                      "Exhibit": "展示", "Injure": "伤亡"}.get(t, t) for t, c in top_types}
    gt_types = "、".join(f"{type_names[t]}（{c}次）" for t, c in top_types)
    questions.append({
        "question": "在这100篇军事新闻中，最常见的军事事件类型有哪些？各出现多少次？",
        "type": "全局理解",
        "ground_truth": gt_types,
        "difficulty": 3,
    })

    # Q2: Most active participants
    top_subjects = subject_counts.most_common(5)
    gt_subjects = "、".join(f"{s}（{c}次）" for s, c in top_subjects if len(s) >= 3)
    questions.append({
        "question": "在这些军事新闻中，最活跃的参与方/主体有哪些？",
        "type": "全局理解",
        "ground_truth": gt_subjects,
        "difficulty": 3,
    })

    # Q3: Most mentioned locations
    top_locs = location_counts.most_common(5)
    gt_locs = "、".join(f"{l}（{c}次）" for l, c in top_locs if len(l) >= 3)
    questions.append({
        "question": "这些军事新闻中最常出现的地点/区域有哪些？",
        "type": "全局理解",
        "ground_truth": gt_locs,
        "difficulty": 3,
    })

    # Q4: Event type ratio analysis
    total_events = sum(event_type_counts.values())
    conflict_count = event_type_counts.get("Conflict", 0)
    deploy_count = event_type_counts.get("Deploy", 0)
    experiment_count = event_type_counts.get("Experiment", 0)
    questions.append({
        "question": "分析这组军事新闻中事件类型的整体分布特点。",
        "type": "全局理解",
        "ground_truth": f"冲突类{conflict_count}次、部署类{deploy_count}次、试验类{experiment_count}次，共{total_events}个事件",
        "difficulty": 3,
    })

    # Q5-10: Statistical comparisons
    # Compare two specific locations
    top2_locs = [l for l, c in location_counts.most_common(2) if c >= 3]
    if len(top2_locs) >= 2:
        loc1_events = set()
        loc2_events = set()
        for article in articles:
            for event in article.get("event_list", []):
                for arg in event.get("arguments", []):
                    if arg.get("role") == "Location":
                        if arg.get("text", "").strip() == top2_locs[0]:
                            loc1_events.add(event.get("event_type", ""))
                        elif arg.get("text", "").strip() == top2_locs[1]:
                            loc2_events.add(event.get("event_type", ""))
        questions.append({
            "question": f"比较「{top2_locs[0]}」和「{top2_locs[1]}」两个区域的军事活动类型差异。",
            "type": "全局理解",
            "ground_truth": f"{top2_locs[0]}以{', '.join(loc1_events)}为主；{top2_locs[1]}以{', '.join(loc2_events)}为主",
            "difficulty": 3,
        })

    # Fill remaining with event-type-focused trend questions
    for evt_type, cn_name in [("Deploy", "部署行动"), ("Experiment", "试验活动"), ("Conflict", "冲突事件")]:
        type_articles = []
        for article in articles:
            if any(e.get("event_type") == evt_type for e in article.get("event_list", [])):
                type_articles.append(article.get("id"))
        if len(type_articles) >= 5:
            questions.append({
                "question": f"分析这组军事新闻中{cn_name}的分布情况和特点。",
                "type": "全局理解",
                "ground_truth": f"共{len(type_articles)}篇涉及{cn_name}，占{len(type_articles)/len(articles)*100:.0f}%",
                "difficulty": 3,
            })

    questions = questions[:count]
    log.info("Generated %d global understanding questions", len(questions))
    return questions


def assign_question_ids(questions):
    """Assign unique question IDs."""
    for i, q in enumerate(questions):
        q["question_id"] = f"l2_q_{i+1:03d}"
    return questions


def main():
    log.info("=" * 50)
    log.info("CMNEE Question Generation")
    log.info("=" * 50)

    # Load selected articles
    with open(SELECTED_PATH, "r", encoding="utf-8") as f:
        articles = json.load(f)
    log.info("Loaded %d articles", len(articles))

    # Generate questions
    basic = generate_basic_fact_questions(articles, count=20)
    multihop = generate_multihop_questions(articles, count=20)
    global_q = generate_global_understanding_questions(articles, count=10)

    all_questions = basic + multihop + global_q
    all_questions = assign_question_ids(all_questions)

    # Show summary
    type_counts = Counter(q["type"] for q in all_questions)
    log.info("\nQuestion distribution:")
    for t, c in type_counts.items():
        log.info("  %s: %d", t, c)

    avg_gt_len = sum(len(q["ground_truth"]) for q in all_questions) / len(all_questions)
    log.info("Avg GT length: %.0f chars", avg_gt_len)

    # Save
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_questions, f, ensure_ascii=False, indent=2)
    log.info("Saved %d questions to %s", len(all_questions), OUTPUT_PATH)

    # Show samples
    log.info("\n=== Sample Questions ===")
    for q in all_questions[:5]:
        log.info("  [%s] %s", q["question_id"], q["question"][:100])
        log.info("    GT: %s", q["ground_truth"][:100])
    log.info("  ...")


if __name__ == "__main__":
    main()
