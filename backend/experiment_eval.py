"""Experiment evaluator: compute accuracy, recall, and generate comparison reports."""
import json
import logging
import statistics

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM-based scoring
# ---------------------------------------------------------------------------

ACCURACY_PROMPT = """你是知识问答评测专家。请评估以下答案与标准答案的语义匹配度。

标准答案（Ground Truth）：{ground_truth}

待评答案：{answer}

请给出0-1之间的准确率分数：
- 1.0：答案完全正确，与标准答案语义一致
- 0.7-0.9：答案基本正确，有少量细节偏差
- 0.4-0.6：答案部分正确，遗漏关键信息
- 0.1-0.3：答案有一些相关性但基本不正确
- 0.0：答案完全错误或无关

请严格按JSON输出：{{"score": 0.85, "reason": "简要说明评分理由"}}
只输出JSON。"""

RECALL_PROMPT = """你是知识问答评测专家。请评估待评答案覆盖标准答案要点的程度。

标准答案（Ground Truth）要点：{ground_truth}

待评答案：{answer}

请给出0-1之间的召回率分数（覆盖要点的比例）：
- 1.0：覆盖了所有要点
- 0.7-0.9：覆盖了大部分要点
- 0.4-0.6：覆盖了部分要点
- 0.1-0.3：只覆盖了极少要点
- 0.0：没有覆盖任何要点

请严格按JSON输出：{{"score": 0.8, "reason": "简要说明评分理由"}}
只输出JSON。"""


def _llm_score(prompt_template, ground_truth, answer, call_llm_fn):
    """Use LLM to evaluate answer quality."""
    if not answer or "无法" in answer[:20] or "无法回答" in answer[:50]:
        return 0.0, "答案表明无法回答"

    prompt = prompt_template.format(ground_truth=ground_truth, answer=answer[:2000])
    try:
        raw = call_llm_fn(
            "你是知识问答评测专家。请严格按照JSON格式输出评分结果。",
            prompt,
            temperature=0.0,
        )
        if isinstance(raw, dict):
            return float(raw.get("score", 0)), raw.get("reason", "")
    except Exception as e:
        log.warning("LLM scoring failed: %s", e)
    return 0.0, "评分失败"


# ---------------------------------------------------------------------------
# Experiment evaluator
# ---------------------------------------------------------------------------

class ExperimentEvaluator:
    """Compute accuracy, recall and generate reports."""

    def __init__(self, llm_fn=None):
        from llm_client import call_qwen
        self.llm_fn = llm_fn or call_qwen

    def score_answer(self, question_entry, method_result):
        """Score a single answer against ground truth."""
        ground_truth = question_entry.get("ground_truth", "")
        answer = method_result.get("answer", "")

        accuracy, acc_reason = _llm_score(
            ACCURACY_PROMPT, ground_truth, answer, self.llm_fn
        )
        recall, rec_reason = _llm_score(
            RECALL_PROMPT, ground_truth, answer, self.llm_fn
        )

        return {
            "accuracy_score": accuracy,
            "accuracy_reason": acc_reason,
            "recall_score": recall,
            "recall_reason": rec_reason,
        }

    def evaluate_experiment(self, experiment_output):
        """Evaluate all results in an experiment output file."""
        questions = experiment_output["experiment_output"]["questions"]
        methods = experiment_output["experiment_output"]["methods"]

        evaluations = {}
        for method_code, method_data in methods.items():
            method_scores = []
            for result in method_data["results"]:
                qid = result["question_id"]
                # Find matching question
                question_entry = next(
                    (q for q in questions if q["question_id"] == qid), None
                )
                if not question_entry:
                    continue

                scores = self.score_answer(question_entry, result)
                result.update(scores)
                method_scores.append(scores)

            # Aggregate
            acc_scores = [s["accuracy_score"] for s in method_scores]
            rec_scores = [s["recall_score"] for s in method_scores]
            latencies = [r.get("latency_ms", 0) for r in method_data["results"]]

            evaluations[method_code] = {
                "method_name": method_data["method_name"],
                "count": len(method_scores),
                "accuracy": {
                    "mean": round(statistics.mean(acc_scores), 3) if acc_scores else 0,
                    "median": round(statistics.median(acc_scores), 3) if acc_scores else 0,
                    "stdev": round(statistics.stdev(acc_scores), 3) if len(acc_scores) > 1 else 0,
                },
                "recall": {
                    "mean": round(statistics.mean(rec_scores), 3) if rec_scores else 0,
                    "median": round(statistics.median(rec_scores), 3) if rec_scores else 0,
                    "stdev": round(statistics.stdev(rec_scores), 3) if len(rec_scores) > 1 else 0,
                },
                "latency_ms": {
                    "mean": round(statistics.mean(latencies), 0) if latencies else 0,
                    "median": round(statistics.median(latencies), 0) if latencies else 0,
                    "min": round(min(latencies), 0) if latencies else 0,
                    "max": round(max(latencies), 0) if latencies else 0,
                },
            }

        return evaluations

    def compare_methods(self, evaluations):
        """Generate a ranked comparison table across methods."""
        rows = []
        for code, eval_data in evaluations.items():
            rows.append({
                "method_code": code,
                "method_name": eval_data["method_name"],
                "count": eval_data["count"],
                "accuracy_mean": eval_data["accuracy"]["mean"],
                "recall_mean": eval_data["recall"]["mean"],
                "latency_mean_ms": eval_data["latency_ms"]["mean"],
                "score_combined": round(
                    eval_data["accuracy"]["mean"] * 0.6
                    + eval_data["recall"]["mean"] * 0.4,
                    3,
                ),
            })

        # Sort by combined score descending
        rows.sort(key=lambda x: x["score_combined"], reverse=True)
        return rows

    def by_question_type(self, experiment_output, evaluations):
        """Break down results by question type (基础事实/多跳推理/全局理解)."""
        questions = experiment_output["experiment_output"]["questions"]
        methods = experiment_output["experiment_output"]["methods"]

        breakdown = {}
        for qtype in ["基础事实", "多跳推理", "全局理解"]:
            type_questions = [q for q in questions if q.get("type") == qtype]
            qids = {q["question_id"] for q in type_questions}

            type_eval = {}
            for method_code, method_data in methods.items():
                type_results = [
                    r for r in method_data["results"]
                    if r["question_id"] in qids
                ]
                acc_values = [r.get("accuracy_score", 0) for r in type_results]
                rec_values = [r.get("recall_score", 0) for r in type_results]
                lat_values = [r.get("latency_ms", 0) for r in type_results]

                type_eval[method_code] = {
                    "method_name": method_data["method_name"],
                    "count": len(type_results),
                    "accuracy_mean": round(statistics.mean(acc_values), 3) if acc_values else 0,
                    "recall_mean": round(statistics.mean(rec_values), 3) if rec_values else 0,
                    "latency_mean_ms": round(statistics.mean(lat_values), 0) if lat_values else 0,
                }

            breakdown[qtype] = type_eval

        return breakdown


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_summary_report(experiment_output, evaluations, comparison, breakdown):
    """Generate a human-readable summary report in Markdown."""
    lines = []
    lines.append("# 知识图谱问答系统对比实验报告")
    lines.append("")
    lines.append(f"实验ID: {experiment_output['experiment_output']['experiment_id']}")
    lines.append(f"问题总数: {experiment_output['experiment_output']['total_questions']}")
    lines.append("")

    # Overall comparison table
    lines.append("## 1. 整体对比")
    lines.append("")
    lines.append("| 方式 | 准确率均值 | 召回率均值 | 综合得分 | 平均延迟(ms) |")
    lines.append("|------|-----------|-----------|---------|-------------|")
    for row in comparison:
        lines.append(
            f"| {row['method_name']} "
            f"| {row['accuracy_mean']:.3f} "
            f"| {row['recall_mean']:.3f} "
            f"| {row['score_combined']:.3f} "
            f"| {row['latency_mean_ms']:.0f} |"
        )
    lines.append("")

    # By question type
    lines.append("## 2. 按问题类型拆分")
    lines.append("")
    for qtype, type_data in breakdown.items():
        lines.append(f"### {qtype}")
        lines.append("")
        lines.append("| 方式 | 准确率 | 召回率 | 延迟(ms) |")
        lines.append("|------|--------|--------|---------|")
        for method_code, mdata in type_data.items():
            lines.append(
                f"| {mdata['method_name']} "
                f"| {mdata['accuracy_mean']:.3f} "
                f"| {mdata['recall_mean']:.3f} "
                f"| {mdata['latency_mean_ms']:.0f} |"
            )
        lines.append("")

    # Detailed per-method stats
    lines.append("## 3. 详细指标")
    lines.append("")
    for code, eval_data in evaluations.items():
        lines.append(f"### {eval_data['method_name']} ({code})")
        lines.append(f"- 评测数量: {eval_data['count']}")
        lines.append(f"- 准确率: mean={eval_data['accuracy']['mean']:.3f}, "
                    f"median={eval_data['accuracy']['median']:.3f}, "
                    f"stdev={eval_data['accuracy']['stdev']:.3f}")
        lines.append(f"- 召回率: mean={eval_data['recall']['mean']:.3f}, "
                    f"median={eval_data['recall']['median']:.3f}, "
                    f"stdev={eval_data['recall']['stdev']:.3f}")
        lines.append(f"- 延迟: mean={eval_data['latency_ms']['mean']:.0f}ms, "
                    f"median={eval_data['latency_ms']['median']:.0f}ms, "
                    f"min={eval_data['latency_ms']['min']:.0f}ms, "
                    f"max={eval_data['latency_ms']['max']:.0f}ms")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python experiment_eval.py <experiment_output.json>")
    else:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            data = json.load(f)

        evaluator = ExperimentEvaluator()
        print("Computing evaluations...")
        evals = evaluator.evaluate_experiment(data)
        comp = evaluator.compare_methods(evals)
        bd = evaluator.by_question_type(data, evals)
        report = generate_summary_report(data, evals, comp, bd)

        report_path = sys.argv[1].replace(".json", "_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)

        evals_path = sys.argv[1].replace(".json", "_evaluation.json")
        with open(evals_path, "w", encoding="utf-8") as f:
            json.dump({
                "evaluations": evals,
                "comparison": comp,
                "by_type": bd,
            }, f, ensure_ascii=False, indent=2)

        print(f"Report saved to: {report_path}")
        print(f"Evaluation data saved to: {evals_path}")
