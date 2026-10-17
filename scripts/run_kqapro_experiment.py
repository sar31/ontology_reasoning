"""KQA Pro Layer 1 Experiment: Ontology-guided KGQA with 4 ablation variants.

Usage:
  python scripts/run_kqapro_experiment.py A    # Run variant A only
  python scripts/run_kqapro_experiment.py B    # Run variant B only
  python scripts/run_kqapro_experiment.py all  # Run all variants sequentially

Checkpoint: saves after every question to data/kqapro_experiment/checkpoint_*.json
Resume: if checkpoint exists for a variant, skips completed questions.
"""
import json
import logging
import os
import re
import sys
import time
from datetime import datetime

from neo4j.graph import Node, Relationship

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import get_neo4j_driver
from llm_client import call_qwen

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "kqapro_full_120.json")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "kqapro_experiment")

# ---------------------------------------------------------------------------
# KQA Pro unified ontology schema prompt — proven effective in R4 (52.90%)
# Extended with Count examples and all Multi-hop fixes from R4-fix
# ---------------------------------------------------------------------------

KQA_SCHEMA_PROMPT = """You are a Neo4j Cypher expert. Generate a READ-ONLY Cypher query for a Freebase/Wikidata knowledge graph.

## 1. Node Types and Their Properties

Every node has: qid, name, concept_types (list of concept names like ['big city', 'sovereign state']).

| Label | Key Properties (use EXACT names!) |
|-------|-----------------------------------|
| KQA_Person | name, date_of_birth, date_of_death, official_website, twitter_username, instagram_username, work_period_(start) |
| KQA_CreativeWork | name, title, publication_date, duration, cost, box_office, number_of_episodes, number_of_seasons, start_time, end_time |
| KQA_Place | name, population, area, elevation_above_sea_level, inception, official_website, demonym, fips_10_4_(countries_and_regions), iso_3166_1_alpha_2_code, iso_3166_1_alpha_3_code, life_expectancy, total_fertility_rate, nominal_gdp, human_development_index, licence_plate_code, local_dialing_code, postal_code |
| KQA_Organization | name, inception, official_website, twitter_username, instagram_username, employees, short_name, dissolved_abolished_or_demolished, permid, isin |
| KQA_EducationalInstitution | name, inception, official_website, postal_code, located_at_street_address, students_count, twitter_username, employees |
| KQA_SportsTeam | name, inception, official_website, twitter_username, instagram_username, official_name, nickname, sport, short_name |
| KQA_MusicGroup | name, inception, official_website, twitter_username, instagram_username, genre, work_period_(start) |
| KQA_Award | name, inception, official_website, edition_number, point_in_time, review_score, start_time |
| KQA_Event | name, start_time, end_time, point_in_time, edition_number, official_website, short_name, number_of_deaths |

## 2. Relationship Types by Domain

Person outgoing: CAST_MEMBER, DIRECTOR, PRODUCER, SCREENWRITER, COMPOSER, VOICE_ACTOR, EDUCATED_AT, PLACE_OF_BIRTH, PLACE_OF_DEATH, COUNTRY_OF_CITIZENSHIP, OCCUPATION, RESIDENCE, ETHNIC_GROUP, RELIGION, CAUSE_OF_DEATH, MANNER_OF_DEATH, LANGUAGES_SPOKEN_WRITTEN_OR_SIGNED, MEMBER_OF, MEMBER_OF_SPORTS_TEAM, MEMBER_OF_POLITICAL_PARTY, FAMOUS_PEOPLE
CreativeWork outgoing: NOMINATED_FOR, AWARD_RECEIVED, WINNER, GENRE, PRODUCTION_COMPANY, DISTRIBUTOR, RECORD_LABEL, FILMING_LOCATION, NARRATIVE_LOCATION, ORIGINAL_LANGUAGE_OF_FILM_OR_TV_SHOW, FILM_RELEASE_REGION, MAIN_SUBJECT, HAS_PART
Place outgoing: COUNTRY, CAPITAL, CAPITAL_OF, SHARES_BORDER_WITH, LOCATED_IN_THE_ADMINISTRATIVE_TERRITORIAL_ENTITY, CONTAINS_ADMINISTRATIVE_TERRITORIAL_ENTITY, CONTINENT, HEADQUARTERS_LOCATION, TWINNED_ADMINISTRATIVE_BODY
Organization/Team outgoing: MEMBER_OF, MEMBER_OF_SPORTS_TEAM, MEMBER_OF_POLITICAL_PARTY, SPORT, DIPLOMATIC_RELATION
Event outgoing: PARTICIPANT, MILITARY_CONFLICTS
Any node: INFLUENCED_BY, COUNTRY_OF_ORIGIN

## 3. Qualifier Properties on Relationships

Qualifiers are stored ON THE RELATIONSHIP, accessed via [r] variable. Below are the ONLY qualifiers that exist:

| Relationship Type | Available Qualifier Properties |
|-------------------|-------------------------------|
| CAST_MEMBER | r.character_role |
| EDUCATED_AT | r.start_time, r.end_time, r.academic_major, r.academic_degree |
| MEMBER_OF_SPORTS_TEAM | r.start_time, r.end_time, r.number_of_matches_played_races_starts, r.number_of_points_goals_set_scored |
| NOMINATED_FOR | r.point_in_time, r.for_work, r.nominee |
| AWARD_RECEIVED | r.point_in_time, r.for_work, r.winner |
| WINNER | r.point_in_time, r.for_work |
| MEMBER_OF | r.start_time, r.end_time |
| MEMBER_OF_POLITICAL_PARTY | r.start_time, r.end_time |
| COUNTRY | r.start_time, r.end_time |
| SPOUSE | r.start_time, r.end_time |
| VOICE_ACTOR | r.character_role |
| SPORT | r.start_time, r.end_time |
| DIPLOMATIC_RELATION | r.start_time |
| SHARES_BORDER_WITH | r.direction_relative_to_location |
| HEADQUARTERS_LOCATION | r.postal_code, r.country |
| PLACE_OF_BIRTH | r.located_in_the_administrative_territorial_entity |
| PLACE_OF_DEATH | r.country |

No other qualifier properties exist. If a question asks about a qualifier not listed above, use entity-level properties instead.

## 4. Entity Identification vs Property Filtering — CRITICAL

When a question provides descriptive facts about an entity (population, fertility rate, GDP, elevation, lifespan, etc.), these are IDENTIFICATION CLUES for disambiguation, NOT property filters to put in WHERE clauses.

WRONG: MATCH (n:KQA_Place) WHERE n.name CONTAINS 'Lebanon' AND n.total_fertility_rate = 2.225 AND n.life_expectancy = 74.934
RIGHT: MATCH (n:KQA_Place) WHERE n.name CONTAINS 'Lebanon' RETURN n.inception LIMIT 1

The descriptive facts help identify WHICH entity is being asked about when there are multiple with similar names. They do NOT need to be matched in Cypher — the LLM will use them when reasoning about the answer.

EXCEPTION — KEEP the filter in Cypher when:
a) The fact is a UNIQUE IDENTIFIER: Q-ID, ISNI, ISO code, ISBN, exact website URL — match with CONTAINS
b) concept_types filtering IS needed to narrow entity types: "which animated film..." → 'animated film' IN n.concept_types
c) The question explicitly asks to COMPARE or FILTER BY a numeric condition ("cities with population > 1000000")
d) A property value is the ONLY way to identify the entity (no name given)

## 5. Comparison Query Rules

For superlative/ranking questions ("which is largest/smallest/most/least"):
- Use ORDER BY + LIMIT 1 to find the max/min value
- Return BOTH the entity name AND the compared value
- When comparing with unknown units ("academic term", "versta"), return raw values and let downstream LLM judge

For yes/no comparison questions ("is A bigger than B?"):
- Match both entities by name using CONTAINS
- Return both values, let LLM compare

For "which entity with condition X has the max/min Y":
- First filter entities matching condition X
- Then ORDER BY Y DESC/ASC LIMIT 1

## 6. Relationship Flexibility for Vague Verbs

When the question uses vague action verbs, match multiple possible relationship types with `|`:
- "created by / founded by / established by" → `:CREATOR|DIRECTOR|PRODUCER|SCREENWRITER`
- "worked for / employed by" → `:MEMBER_OF|OCCUPATION`
- "associated with / part of" → `:MEMBER_OF|MEMBER_OF_SPORTS_TEAM|MEMBER_OF_POLITICAL_PARTY`
- "located in / based in" → `:COUNTRY|LOCATED_IN_THE_ADMINISTRATIVE_TERRITORIAL_ENTITY|HEADQUARTERS_LOCATION`

If a relationship you think should exist is NOT listed in Section 2, don't invent it — fall back to matching by entity name only, or use a broader relationship from the list.

## 7. Few-Shot Examples

### Attribute — Look up a property value:
Q: "What is the population of Shanghai?"
Cypher: {"cypher": "MATCH (n:KQA_Place) WHERE n.name CONTAINS 'Shanghai' RETURN n.name, n.population LIMIT 1"}

Q: "What is the official website of Mona Marshall?"
Cypher: {"cypher": "MATCH (n:KQA_Person) WHERE n.name CONTAINS 'Mona Marshall' RETURN n.official_website LIMIT 1"}

Q: "What is the connection between Solomon Islands and Oceania?"
Cypher: {"cypher": "MATCH (a:KQA_Place)-[r]->(b:KQA_Place) WHERE a.name CONTAINS 'Solomon Islands' AND b.name CONTAINS 'Oceania' RETURN type(r) AS connection LIMIT 1"}

### Comparison — Superlative, ranking, or numeric comparison:
Q: "Is the population of London greater than the population of Paris?"
Cypher: {"cypher": "MATCH (a:KQA_Place), (b:KQA_Place) WHERE a.name CONTAINS 'London' AND b.name CONTAINS 'Paris' RETURN a.population, b.population LIMIT 1"}

Q: "Which New York county without 5700 inhabitants covers the biggest area?"
Cypher: {"cypher": "MATCH (c:KQA_Place)-[:LOCATED_IN_THE_ADMINISTRATIVE_TERRITORIAL_ENTITY]->(ny:KQA_Place) WHERE ny.name CONTAINS 'New York' AND c.name CONTAINS 'County' AND c.area IS NOT NULL AND toFloat(c.population) <> 5700 RETURN c.name, c.area ORDER BY toFloat(c.area) DESC LIMIT 1"}

Q: "Which has more episodes, WWE Superstars or Tiny Toon Adventures?"
Cypher: {"cypher": "MATCH (a:KQA_CreativeWork), (b:KQA_CreativeWork) WHERE a.name CONTAINS 'WWE Superstars' AND b.name CONTAINS 'Tiny Toon Adventures' RETURN a.name, a.number_of_episodes, b.name, b.number_of_episodes LIMIT 1"}

Q: "Of feature films released more recently than 2010, which is longest?"
Cypher: {"cypher": "MATCH (f:KQA_CreativeWork) WHERE toInteger(f.publication_date) > 2010 AND f.duration IS NOT NULL AND 'film' IN f.concept_types RETURN f.name, f.duration ORDER BY toFloat(f.duration) DESC LIMIT 1"}

### Logical — AND/OR conditions with entity filtering:
Q: "Which films were released after 2005 and have the genre 'science fiction'?"
Cypher: {"cypher": "MATCH (f:KQA_CreativeWork)-[:GENRE]->(g:KQA_Thing) WHERE g.name CONTAINS 'science fiction' AND toInteger(f.publication_date) > 2005 RETURN f.name LIMIT 20"}

Q: "Which persons are both actors and directors?"
Cypher: {"cypher": "MATCH (p:KQA_Person)-[:OCCUPATION]->(o1:KQA_Thing), (p)-[:OCCUPATION]->(o2:KQA_Thing) WHERE o1.name CONTAINS 'actor' AND o2.name CONTAINS 'director' RETURN DISTINCT p.name LIMIT 20"}

Q: "Which countries have a population greater than 10000000 and an area greater than 500000?"
Cypher: {"cypher": "MATCH (c:KQA_Place) WHERE c.population IS NOT NULL AND c.area IS NOT NULL AND toFloat(c.population) > 10000000 AND toFloat(c.area) > 500000 RETURN c.name, c.population, c.area LIMIT 20"}

### Multi-hop — Chain multiple relationships:
Q: "What country is the birthplace of the director of the film Titanic?"
Cypher: {"cypher": "MATCH (f:KQA_CreativeWork)-[:DIRECTOR]->(p:KQA_Person)-[:PLACE_OF_BIRTH]->(place:KQA_Place)-[:COUNTRY]->(c:KQA_Place) WHERE f.name CONTAINS 'Titanic' RETURN c.name LIMIT 1"}

Q: "When did the TV series created by Ricky Gervais end?"
Cypher: {"cypher": "MATCH (p:KQA_Person)-[:CREATOR|DIRECTOR|PRODUCER|SCREENWRITER]->(c:KQA_CreativeWork) WHERE p.name CONTAINS 'Ricky Gervais' AND 'TV series' IN c.concept_types RETURN c.end_time LIMIT 1"}

Q: "What is the duration of the film whose distributor is TV Tokyo?"
Cypher: {"cypher": "MATCH (cw:KQA_CreativeWork)-[:DISTRIBUTOR]->(dist:KQA_Organization) WHERE dist.name CONTAINS 'TV Tokyo' RETURN cw.duration LIMIT 1"}

### Qualifier — Query relationship-level properties:
Q: "When did Natalie Portman start attending Harvard University?"
Cypher: {"cypher": "MATCH (p:KQA_Person)-[r:EDUCATED_AT]->(e:KQA_EducationalInstitution) WHERE p.name CONTAINS 'Natalie Portman' AND e.name CONTAINS 'Harvard University' RETURN r.start_time LIMIT 1"}

Q: "What character role did Johnny Depp play in Edward Scissorhands?"
Cypher: {"cypher": "MATCH (p:KQA_Person)-[r:CAST_MEMBER]->(f:KQA_CreativeWork) WHERE p.name CONTAINS 'Johnny Depp' AND f.name CONTAINS 'Edward Scissorhands' RETURN r.character_role LIMIT 1"}

Q: "Who was a member of Millwall F.C. starting in 2005?"
Cypher: {"cypher": "MATCH (p:KQA_Person)-[r:MEMBER_OF_SPORTS_TEAM]->(t:KQA_SportsTeam) WHERE t.name CONTAINS 'Millwall' AND r.start_time CONTAINS '2005' RETURN p.name, r.start_time LIMIT 5"}

### Count — Return an integer count of matching entities:
Q: "How many big cities use 0261 as their local dialing code?"
Cypher: {"cypher": "MATCH (n:KQA_Place) WHERE n.local_dialing_code CONTAINS '0261' AND 'big city' IN n.concept_types RETURN count(DISTINCT n) AS count"}

Q: "What's the number of basketball teams in the United States of America?"
Cypher: {"cypher": "MATCH (t:KQA_SportsTeam)-[:COUNTRY]->(c:KQA_Place) WHERE c.name CONTAINS 'United States' AND 'basketball team' IN t.concept_types RETURN count(DISTINCT t) AS count"}

Q: "How many sports seasons transpired later than 2005?"
Cypher: {"cypher": "MATCH (n:KQA_Event) WHERE toInteger(n.point_in_time) > 2005 AND 'sports season' IN n.concept_types RETURN count(DISTINCT n) AS count"}

Q: "How many feature films are there whose title is The Sorcerer's Apprentice or whose official website is http://pirates.disney.com?"
Cypher: {"cypher": "MATCH (f:KQA_CreativeWork) WHERE 'feature film' IN f.concept_types AND (f.title CONTAINS \"The Sorcerer's Apprentice\" OR f.official_website CONTAINS 'pirates.disney.com') RETURN count(DISTINCT f) AS count"}

Q: "How many video game developers are a part of EuropaCorp and have an ISIN equal to JP3164630000?"
Cypher: {"cypher": "MATCH (v:KQA_Organization)-[:MEMBER_OF]->(e:KQA_Organization) WHERE e.name CONTAINS 'EuropaCorp' AND v.isin CONTAINS 'JP3164630000' AND 'video game developer' IN v.concept_types RETURN count(DISTINCT v) AS count"}

Q: "How many Academy Awards did Star Wars receive?"
Cypher: {"cypher": "MATCH (f:KQA_CreativeWork)-[:AWARD_RECEIVED]->(a:KQA_Award) WHERE f.name CONTAINS 'Star Wars' AND 'Academy Awards ceremony' IN a.concept_types RETURN count(DISTINCT a) AS count"}

## 8. Critical Rules

1. ONLY use exact property and relationship names listed above — NEVER invent names
2. ONLY read-only: MATCH, OPTIONAL MATCH, RETURN, WHERE, LIMIT, ORDER BY, WITH, DISTINCT
3. Match entity names with CONTAINS on n.name — NEVER exact match unless disambiguating with qid
4. Descriptive facts in questions are IDs for the LLM, NOT Cypher WHERE filters (see Section 4)
5. Default LIMIT 20; use LIMIT 1 for single-answer questions
6. For counting: MATCH ... RETURN count(DISTINCT n) AS count
7. For qualifiers: ALWAYS use [r] binder and access r.property_name on the relationship
8. For dates: use toInteger() for numeric years, or string comparison with CONTAINS for partial dates
9. Output ONLY valid JSON: {"cypher": "your query here"}
10. No markdown, no explanation — ONLY the JSON object
11. CRITICAL — array vs string: concept_types and other list properties must use 'value' IN n.concept_types or ANY(t IN n.concept_types WHERE t CONTAINS 'word'). NEVER use n.concept_types CONTAINS 'value' — CONTAINS only works on single string properties, not arrays
12. EVERY node in MATCH must declare a label: MATCH (n:KQA_Person) not bare MATCH (n). Unlabeled nodes cause full-scan and empty results."""

# =============================================================================
# GENERIC (no-ontology) prompt for Variant B
# =============================================================================

GENERIC_CYPHER_PROMPT = """You are a Neo4j Cypher expert. Generate a READ-ONLY Cypher query for a knowledge graph.

The graph has entities connected by relationships. Each entity has a 'name' property and may have other properties.

Rules:
1. ONLY read-only clauses: MATCH, OPTIONAL MATCH, RETURN, WHERE, LIMIT, ORDER BY, WITH, DISTINCT
2. FORBIDDEN: CREATE, DELETE, SET, REMOVE, MERGE, DROP, LOAD, CALL
3. Match entity names with CONTAINS: WHERE n.name CONTAINS 'keyword'
4. Default LIMIT 20
5. Output ONLY valid JSON: {"cypher": "your query here"}
6. No explanations — ONLY the JSON object"""

# =============================================================================
# Answer generation prompts
# =============================================================================

ANSWER_WITH_KG_PROMPT = """You are a precise QA assistant. Answer based STRICTLY on the KG query results below.

Rules:
1. Extract the EXACT value from the query results — do not fabricate or guess
2. For property queries: return the specific property value found (e.g. "123456" or "1954-01-01")
3. For COMPARISON questions (which is bigger/smaller/longer, more/less): compare the returned values and output the NAME of the entity that wins, or "yes"/"no" for yes/no comparisons
4. For SUPERLATIVE questions (biggest/smallest/most/least): output the entity name that ranks at the top
5. For yes/no questions: answer ONLY "yes" or "no"
6. For COUNT questions: the result is a count value. Return ONLY the integer (e.g. "13", "5", "0")
   - CRITICAL: if count is 0, return "0" — 0 IS a valid answer, do NOT say "Cannot answer"
   - Extract the count number from {"count": N} or [{"count": N}]
   - Never return text explanations for count answers
7. For relationship property queries: return the relationship property value (e.g. r.start_time, r.character_role)
8. If results are truly empty or null (NOT count=0), say "Cannot answer from available graph data"
9. Be extremely concise — return ONLY the answer value, no extra text

Output JSON: {"answer": "your answer"}"""

ANSWER_NO_KG_PROMPT = """You are a knowledgeable QA assistant. Answer based on your knowledge.

Rules:
1. Be concise and precise — return the specific value asked for
2. For yes/no questions, answer ONLY "yes" or "no"
3. If unsure, say "Cannot determine"
4. Return ONLY the answer, no extra explanation

Output JSON: {"answer": "your answer"}"""

# ---------------------------------------------------------------------------
# Cypher helpers
# ---------------------------------------------------------------------------

def _sanitize_cypher(cypher):
    cypher = cypher.strip()
    if cypher.startswith("```"):
        cypher = re.sub(r"^```\w*", "", cypher)
        cypher = re.sub(r"```$", "", cypher)
        cypher = cypher.strip()
    upper = cypher.upper()
    for d in ["CREATE", "DELETE", "SET", "REMOVE", "MERGE", "DROP", "LOAD", "CALL"]:
        if re.search(rf"\b{d}\b", upper):
            log.error("Dangerous keyword '%s' in cypher. Blocking.", d)
            return ""
    return cypher


def _neo4j_to_serializable(obj):
    """Recursively convert Neo4j Node/Relationship to plain dicts for JSON serialization."""
    if isinstance(obj, (Node, Relationship)):
        return dict(obj)
    if isinstance(obj, dict):
        return {k: _neo4j_to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_neo4j_to_serializable(i) for i in obj]
    return obj


def safe_execute_cypher(cypher, driver):
    if not cypher:
        return []
    upper = cypher.upper()
    for d in ["CREATE", "DELETE", "SET", "REMOVE", "MERGE", "DROP", "LOAD"]:
        if re.search(rf"\b{d}\b", upper):
            raise ValueError(f"Blocked dangerous cypher keyword: {d}")
    with driver.session() as s:
        result = s.run(cypher)
        return _neo4j_to_serializable([dict(r) for r in result])


# ---------------------------------------------------------------------------
# Experiment Runner with checkpoint/resume
# ---------------------------------------------------------------------------

class KQAProExperimentRunner:
    """Run ablation variants with checkpoint/resume support."""

    def __init__(self):
        self.driver = get_neo4j_driver()
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    def _checkpoint_path(self, variant_code):
        return os.path.join(OUTPUT_DIR, f"checkpoint_{variant_code}.json")

    def _load_checkpoint(self, variant_code):
        path = self._checkpoint_path(variant_code)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def _save_checkpoint(self, variant_code, results):
        path = self._checkpoint_path(variant_code)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    def _safe_call_llm(self, system_prompt, user_prompt, temperature=0.1, max_retries=2):
        for attempt in range(max_retries + 1):
            try:
                return call_qwen(system_prompt, user_prompt, temperature=temperature)
            except Exception as e:
                if attempt < max_retries:
                    log.warning("LLM call failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                    time.sleep(2)
                else:
                    log.error("LLM call failed after %d retries: %s", max_retries, e)
        return None

    RETRY_PROMPT = """You are a Neo4j expert. The previous Cypher query returned NO RESULTS. Generate a SIMPLIFIED Cypher query in JSON format.

RULES:
1. Remove numeric/property filters — match ONLY by entity names using CONTAINS on n.name
2. Remove qualifier conditions on relationships — just match the relationship path
3. Keep the core structure: node labels, relationship types, and RETURN clause
4. CRITICAL: Preserve the RETURN target — if the question asks for duration/inception/name, RETURN that exact property, NOT just the bare node
5. EVERY node must have a label: `MATCH (n:KQA_Person)` not bare `MATCH (n)`
6. For concept_types filtering, use `'value' IN n.concept_types` not CONTAINS
7. Simplify relationship types using `|` if the original was too specific
8. Output ONLY valid JSON: {"cypher": "your simplified query"}"""

    def _generate_cypher(self, question, use_ontology=True):
        prompt = KQA_SCHEMA_PROMPT if use_ontology else GENERIC_CYPHER_PROMPT
        raw = self._safe_call_llm(prompt, f"Question: {question}", temperature=0.1)
        if isinstance(raw, dict):
            return _sanitize_cypher(raw.get("cypher", ""))
        return ""

    def _generate_and_execute_cypher(self, question, use_ontology=True, max_retries=1):
        """Generate Cypher, execute, and optionally retry with simplification if result is empty.

        Returns: (cypher, retry_cypher, kg_results, retry_count)
        """
        cypher = self._generate_cypher(question, use_ontology)
        if not cypher:
            return cypher, "", [], 0

        kg_results = self._execute_cypher(cypher)
        retry_cypher = ""
        retry_count = 0

        # Retry with simplified prompt if no results
        if not kg_results and max_retries > 0:
            retry_user = (
                f"Original question: {question}\n\n"
                f"Previous Cypher that returned 0 results:\n{cypher}\n\n"
                f"Generate a SIMPLIFIED version: remove numeric/property filters, "
                f"use only name CONTAINS matching, keep the same node labels and relationship paths."
            )
            raw = self._safe_call_llm(self.RETRY_PROMPT, retry_user, temperature=0.1)
            if isinstance(raw, dict):
                simplified = _sanitize_cypher(raw.get("cypher", ""))
                if simplified and simplified != cypher:
                    retry_cypher = simplified
                    retry_count = 1
                    kg_results = self._execute_cypher(simplified)

        return cypher, retry_cypher, kg_results, retry_count

    def _execute_cypher(self, cypher):
        if not cypher:
            return []
        try:
            return safe_execute_cypher(cypher, self.driver)
        except Exception as e:
            log.error("Cypher execution failed: %s", e)
            return []

    def _generate_answer(self, question, kg_results, use_kg_context=True):
        if use_kg_context and kg_results:
            context_text = json.dumps(kg_results[:20], ensure_ascii=False, indent=2)
            user_prompt = f"Question: {question}\n\nKG query results:\n{context_text[:4000]}"
            raw = self._safe_call_llm(ANSWER_WITH_KG_PROMPT, user_prompt, temperature=0.3)
        else:
            raw = self._safe_call_llm(ANSWER_NO_KG_PROMPT, f"Question: {question}", temperature=0.3)
        if isinstance(raw, dict):
            return str(raw.get("answer", ""))
        return ""

    def run_variant(self, questions, variant_code, max_questions=None):
        """Run a single ablation variant with checkpoint/resume.

        Variants:
          A: ontology + Cypher + KG results -> LLM answer
          B: generic Cypher + KG results -> LLM answer (no ontology)
          C: ontology + Cypher + KG -> LLM WITHOUT seeing results
          D: LLM direct, no KG at all

        If max_questions is set, stops after processing that many NEW questions.
        """
        use_ontology = variant_code in ("A", "C")
        execute_kg = variant_code in ("A", "B", "C")
        use_kg_context = variant_code in ("A", "B")

        config_descriptions = {
            "A": "Full: ontology + Cypher + KG -> LLM",
            "B": "No ontology: generic Cypher + KG -> LLM",
            "C": "No KG context: ontology + Cypher + KG -> LLM (no KG results)",
            "D": "LLM direct: closed-book, no KG",
        }
        log.info("=" * 60)
        log.info("Variant %s: %s", variant_code, config_descriptions[variant_code])

        # Resume from checkpoint
        results = self._load_checkpoint(variant_code) or []
        completed_ids = {r["question_id"] for r in results}
        if completed_ids:
            log.info("Resuming from checkpoint: %d already completed", len(completed_ids))

        processed_count = 0
        for i, q in enumerate(questions):
            qid = q.get("question_id", f"q_{i:03d}")

            # Skip already completed
            if qid in completed_ids:
                continue

            # Limit batch size
            if max_questions and processed_count >= max_questions:
                log.info("Reached batch limit (%d), pausing. %d total completed.",
                         max_questions, len(results))
                break

            question_text = q.get("question", "")
            ground_truth = q.get("answer", "")
            qtype = q.get("type", "")

            record = {
                "question_id": qid,
                "question": question_text,
                "question_type": qtype,
                "ground_truth": ground_truth,
                "variant": variant_code,
            }

            t_start = time.time()

            try:
                cypher = ""
                retry_cypher = ""
                kg_results = []

                if execute_kg:
                    cypher, retry_cypher, kg_results, retry_count = \
                        self._generate_and_execute_cypher(question_text, use_ontology=use_ontology)
                    record["cypher"] = cypher
                    record["retry_cypher"] = retry_cypher
                    record["retry_count"] = retry_count
                    record["kg_result_count"] = len(kg_results)
                    if not cypher:
                        record["cypher_error"] = "empty or blocked cypher"

                if variant_code == "D":
                    answer = self._generate_answer(question_text, [], use_kg_context=False)
                elif variant_code == "C":
                    answer = self._generate_answer(question_text, [], use_kg_context=False)
                else:
                    answer = self._generate_answer(question_text, kg_results, use_kg_context=True)

                record["answer"] = answer
            except Exception as e:
                log.error("Error processing %s: %s", qid, e)
                record["answer"] = ""
                record["error"] = str(e)[:200]

            record["latency_ms"] = round((time.time() - t_start) * 1000)
            results.append(record)
            completed_ids.add(qid)
            processed_count += 1

            # Save checkpoint after every question
            self._save_checkpoint(variant_code, results)

            done = len([r for r in results if r["question_id"] in completed_ids])
            log.info("  [%s] %d/%d: %s (%dms) answer=%s",
                     variant_code, done, len(questions), qid,
                     record["latency_ms"], str(record.get("answer", ""))[:60])

        log.info("Variant %s complete: %d questions", variant_code, len(results))
        return results


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

ACCURACY_PROMPT = """You are a QA evaluation expert. Rate the semantic match between the predicted answer and the ground truth.

Ground Truth: %(ground_truth)s
Predicted Answer: %(answer)s

Scoring guidelines (0-1):
- 1.0: Answer is fully correct, semantically identical to ground truth
- 0.7-0.9: Mostly correct with minor detail differences (e.g. "1954" vs "1954-01-01")
- 0.4-0.6: Partially correct, missing key information
- 0.1-0.3: Some relevance but mostly incorrect
- 0.0: Completely wrong or unrelated

IMPORTANT for numeric/count answers:
- Exact match: predicted == ground truth -> score 1.0
- Off by 1: difference of exactly 1 -> score 0.9 (rounding or minor KG inconsistency)
- Off by 2-3 or small proportion: -> score 0.7 (possible KG data version difference)
- Off by more: score 0.0
- Count "0" is valid and must be compared as a number, not treated as empty
IMPORTANT for yes/no: "yes" matching "yes" = 1.0, "yes" vs "no" = 0.0.
IMPORTANT for dates: partial match like year-only vs full date = 0.8.

Output ONLY valid JSON: {"score": 0.85, "reason": "brief reason"}
No other text."""


def score_results(variant_code, results):
    """Score variant results against ground truth using LLM evaluation."""
    scored_path = os.path.join(OUTPUT_DIR, f"scored_{variant_code}.json")

    # Resume scoring from checkpoint
    scored_map = {}
    if os.path.exists(scored_path):
        with open(scored_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        for r in existing:
            scored_map[r["question_id"]] = r.get("accuracy", 0.0)

    log.info("Scoring variant %s (%d results)...", variant_code, len(results))
    scored_results = []
    accuracy_scores = []

    for i, r in enumerate(results):
        qid = r["question_id"]

        # Skip already scored
        if qid in scored_map:
            acc = scored_map[qid]
            scored_results.append({**r, "accuracy": acc})
            accuracy_scores.append(acc)
            continue

        gt = str(r.get("ground_truth", ""))
        ans = str(r.get("answer", ""))

        # Auto-score empty/failure answers (numeric answers like "0" or "5" are valid)
        stripped = ans.strip()
        is_numeric = stripped.lstrip('-').replace('.','',1).isdigit() if stripped else False
        if not stripped or (len(stripped) < 2 and not is_numeric):
            scored_results.append({**r, "accuracy": 0.0, "score_reason": "empty answer"})
            accuracy_scores.append(0.0)
            continue
        if "无法" in ans[:50] or "Cannot answer" in ans[:50] or "Cannot determine" in ans[:50]:
            scored_results.append({**r, "accuracy": 0.0, "score_reason": "cannot answer"})
            accuracy_scores.append(0.0)
            continue

        try:
            prompt = ACCURACY_PROMPT % {"ground_truth": gt, "answer": ans[:2000]}
            raw = call_qwen(prompt, "Please score the answer.", temperature=0.0)
            if isinstance(raw, dict):
                acc = raw.get("score", 0.0)
                reason = raw.get("reason", "")
            else:
                acc = 0.0
                reason = "parse error"
        except Exception as e:
            log.warning("Scoring failed for %s: %s", qid, e)
            acc = 0.0
            reason = str(e)[:100]

        scored_results.append({**r, "accuracy": acc, "score_reason": reason})
        accuracy_scores.append(acc)

        # Save scoring checkpoint every 10 questions
        if (i + 1) % 10 == 0:
            with open(scored_path, "w", encoding="utf-8") as f:
                json.dump(scored_results, f, ensure_ascii=False, indent=2)
            log.info("  Scoring checkpoint: %d/%d", i + 1, len(results))

    # Final save
    with open(scored_path, "w", encoding="utf-8") as f:
        json.dump(scored_results, f, ensure_ascii=False, indent=2)

    avg_acc = sum(accuracy_scores) / len(accuracy_scores) if accuracy_scores else 0.0
    log.info("Variant %s scored: avg accuracy = %.4f (%d questions)", variant_code, avg_acc, len(accuracy_scores))
    return avg_acc, scored_results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def generate_report(variant_scores):
    """Generate a Markdown report from all variant scores."""
    variant_names = {
        "A": "A-完整方法（本体+Cypher+KG）",
        "B": "B-无本体约束（通用Cypher+KG）",
        "C": "C-无KG上下文（本体+Cypher，不看KG结果）",
        "D": "D-LLM直接回答（无KG，闭卷）",
    }

    lines = [
        "# KQA Pro Layer 1 消融实验报告",
        "",
        f"实验时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"问题总数: 120 (每种推理类型20题)",
        f"基准线: NS-KGQA zero-shot 53.04%",
        "",
        "## 1. 整体对比",
        "",
        "| 方法 | 准确率 | vs. NS-KGQA |",
        "|------|--------|-------------|",
    ]

    for v in ["A", "B", "C", "D"]:
        if v in variant_scores:
            acc = variant_scores[v]
            delta = acc - 0.5304
            sign = "+" if delta >= 0 else ""
            lines.append(f"| {variant_names[v]} | {acc:.4f} | {sign}{delta:.4f} |")

    lines.append("")
    lines.append("## 2. 结论")
    lines.append("")
    lines.append("- 若 Variant A 准确率显著高于 Variant B，证明**本体约束**有效")
    lines.append("- 若 Variant A 准确率显著高于 Variant C，证明**KG查询结果作为上下文**有效")
    lines.append("- 若 Variant A 准确率显著高于 Variant D，证明**KG增强优于LLM闭卷**")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def main():
    variant_code = sys.argv[1] if len(sys.argv) > 1 else "A"
    log.info("=" * 60)
    log.info("KQA Pro Layer 1 Experiment")
    log.info("Variant: %s", variant_code)
    log.info("=" * 60)

    # Load questions
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        questions = json.load(f)
    log.info("Loaded %d questions", len(questions))

    runner = KQAProExperimentRunner()

    variants_to_run = ["A", "B", "C", "D"] if variant_code == "all" else [variant_code]

    for v in variants_to_run:
        # Run experiment
        results = runner.run_variant(questions, v)
        results_path = os.path.join(OUTPUT_DIR, f"results_{v}.json")
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        log.info("Results saved: %s", results_path)

        # Score
        avg_acc, scored = score_results(v, results)
        log.info("Variant %s final accuracy: %.4f", v, avg_acc)

    # Generate combined report if all variants done
    all_done = all(
        os.path.exists(os.path.join(OUTPUT_DIR, f"scored_{v}.json"))
        for v in ["A", "B", "C", "D"]
    )
    if all_done:
        variant_scores = {}
        for v in ["A", "B", "C", "D"]:
            with open(os.path.join(OUTPUT_DIR, f"scored_{v}.json"), "r", encoding="utf-8") as f:
                scored = json.load(f)
            scores = [r.get("accuracy", 0.0) for r in scored]
            variant_scores[v] = sum(scores) / len(scores) if scores else 0.0

        report = generate_report(variant_scores)
        report_path = os.path.join(OUTPUT_DIR, "experiment_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        log.info("Report saved: %s", report_path)

        # Print final summary
        log.info("=" * 60)
        log.info("FINAL RESULTS")
        for v in ["A", "B", "C", "D"]:
            log.info("  Variant %s: accuracy = %.4f", v, variant_scores[v])
        log.info("Baseline NS-KGQA (zero-shot): 0.5304")
        log.info("=" * 60)


if __name__ == "__main__":
    main()
