"""Experiment Runner: batch run QA methods and record metrics."""
import json
import logging
import time
import os
from datetime import datetime

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

METHODS = {
    "kg_full": {
        "code": "kg_full",
        "name": "方式1-全图谱问答",
        "description": "MySQL + 文本 → 知识图谱 → 问答",
        "endpoint": "/api/qa/ask",
        "payload": lambda q: {"question": q, "mode": "auto"},
    },
    "kg_text_only": {
        "code": "kg_text_only",
        "name": "方式3-纯文本图谱问答",
        "description": "仅文本 → 知识图谱 → 问答",
        "endpoint": "/api/qa/ask",
        "payload": lambda q: {"question": q, "mode": "auto"},
        "requires_clear_first": True,
    },
    "kg_mysql_only": {
        "code": "kg_mysql_only",
        "name": "方式5-纯MySQL图谱问答",
        "description": "仅MySQL → 知识图谱 → 问答",
        "endpoint": "/api/qa/ask",
        "payload": lambda q: {"question": q, "mode": "auto"},
        "requires_clear_first": True,
        "requires_build_mysql": True,
    },
    "sql_direct": {
        "code": "sql_direct",
        "name": "方式6-原始MySQL直接问答",
        "description": "NL2SQL → MySQL查询 → 问答",
        "endpoint": "/api/qa/ask-sql",
        "payload": lambda q: {"question": q},
    },
    "vector_mysql": {
        "code": "vector_mysql",
        "name": "方式2-向量+MySQL混合问答",
        "description": "文本向量化 + MySQL Schema → 问答",
        "endpoint": "/api/qa/ask-vector",
        "payload": lambda q: {"question": q},
    },
    "vector_only": {
        "code": "vector_only",
        "name": "方式4-纯向量问答",
        "description": "仅文本 → 向量数据库 → 问答",
        "endpoint": "/api/qa/ask-vector-only",
        "payload": lambda q: {"question": q},
    },
}


class ExperimentRunner:
    """Run experiments across multiple QA methods."""

    def __init__(self, base_url="http://localhost:5000"):
        self.base_url = base_url
        import requests
        self.requests = requests

    def _call_endpoint(self, endpoint, payload, timeout=180):
        """Call an API endpoint and return response data with timing."""
        url = f"{self.base_url}{endpoint}"
        start = time.time()
        try:
            resp = self.requests.post(url, json=payload, timeout=timeout)
            elapsed_ms = (time.time() - start) * 1000
            data = resp.json()
            data["_latency_ms"] = round(elapsed_ms)
            data["_status_code"] = resp.status_code
            return data
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            return {
                "_latency_ms": round(elapsed_ms),
                "_status_code": 0,
                "_error": str(e),
            }

    def _clear_neo4j(self):
        """Clear Neo4j graph."""
        try:
            resp = self.requests.post(f"{self.base_url}/api/clear", timeout=60)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def _build_all(self):
        """Rebuild MySQL → Neo4j."""
        try:
            resp = self.requests.post(f"{self.base_url}/api/build/all", timeout=300)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def _get_stats(self):
        """Get current data stats."""
        try:
            resp = self.requests.get(f"{self.base_url}/api/stats", timeout=30)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def run_method(self, method_code, questions):
        """Run a single method against all questions."""
        method = METHODS[method_code]
        log.info("Running method: %s (%s)", method["name"], len(questions))

        # Pre-run setup
        if method.get("requires_clear_first"):
            log.info("Clearing Neo4j for %s...", method["name"])
            self._clear_neo4j()
            if method.get("requires_build_mysql"):
                log.info("Building MySQL instances for %s...", method["name"])
                self._build_all()

        stats_before = self._get_stats()

        results = []
        for i, q in enumerate(questions):
            question_text = q.get("question", "")
            qid = q.get("question_id", f"q_{i:03d}")

            payload = method["payload"](question_text)
            resp = self._call_endpoint(method["endpoint"], payload)

            record = {
                "question_id": qid,
                "question": question_text,
                "question_type": q.get("type", ""),
                "difficulty": q.get("difficulty", 0),
                "method": method["name"],
                "method_code": method_code,
                "answer": resp.get("answer", resp.get("_error", "")),
                "latency_ms": resp.get("_latency_ms", 0),
                "status_code": resp.get("_status_code", 0),
                "mode": resp.get("mode", resp.get("method", "")),
                "cypher": resp.get("cypher"),
                "sql": resp.get("sql"),
                "sources": resp.get("sources", []),
                "result_count": resp.get("result_count", resp.get("results", None)),
                "error": resp.get("_error"),
            }
            results.append(record)
            log.info("  [%d/%d] %s: %dms", i + 1, len(questions), qid, resp.get("_latency_ms", 0))

        stats_after = self._get_stats()

        return {
            "method_code": method_code,
            "method_name": method["name"],
            "total_questions": len(questions),
            "results": results,
            "stats_before": stats_before,
            "stats_after": stats_after,
        }

    def run_all(self, questions, method_codes=None):
        """Run all (or selected) methods against all questions."""
        if method_codes is None:
            method_codes = list(METHODS.keys())

        experiment_id = datetime.now().strftime("exp_%Y%m%d_%H%M%S")
        all_results = {
            "experiment_id": experiment_id,
            "total_questions": len(questions),
            "questions": questions,
            "methods": {},
        }

        for code in method_codes:
            log.info("=" * 60)
            log.info("Starting method: %s", METHODS[code]["name"])
            method_results = self.run_method(code, questions)
            all_results["methods"][code] = method_results

        return all_results


# ---------------------------------------------------------------------------
# Standalone runner entry
# ---------------------------------------------------------------------------

def run_from_files(questions_path, output_path, methods=None):
    """Run experiment from questions JSON file and save results."""
    with open(questions_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    runner = ExperimentRunner()
    results = runner.run_all(questions, method_codes=methods)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    log.info("Results saved to: %s", output_path)
    return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python experiment_runner.py <questions.json> [output.json] [method1,method2,...]")
        methods_list = "\n".join(f"  {k}: {v['name']}" for k, v in METHODS.items())
        print(f"Available methods:\n{methods_list}")
    else:
        q_path = sys.argv[1]
        out_path = sys.argv[2] if len(sys.argv) > 2 else "results/experiment_output.json"
        method_list = sys.argv[3].split(",") if len(sys.argv) > 3 else None
        run_from_files(q_path, out_path, method_list)
