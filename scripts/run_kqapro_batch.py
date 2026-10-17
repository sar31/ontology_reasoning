"""Batch runner for KQA Pro experiment - runs a limited number of questions per invocation.

Usage:
  python scripts/run_kqapro_batch.py A    # Process next batch of variant A (resumes from checkpoint)
  python scripts/run_kqapro_batch.py A 5  # Process exactly 5 questions for variant A
  python scripts/run_kqapro_batch.py all 5  # Process 5 questions for each variant

Each invocation processes up to --count questions (default 5), then exits.
Run repeatedly until all questions are done.
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# Share the module with run_kqapro_experiment
from run_kqapro_experiment import (
    KQAProExperimentRunner, score_results, generate_report,
    QUESTIONS_PATH, OUTPUT_DIR
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def process_batch(variant_code, max_count=5):
    """Process up to max_count pending questions for a variant."""
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        questions = json.load(f)

    runner = KQAProExperimentRunner()

    # Check existing progress
    checkpoint = runner._load_checkpoint(variant_code)
    completed = len(checkpoint) if checkpoint else 0
    pending = len(questions) - completed

    if pending == 0:
        log.info("Variant %s: ALL DONE (%d/%d questions)", variant_code, completed, len(questions))

        # Auto-score when all done
        if checkpoint:
            avg_acc, scored = score_results(variant_code, checkpoint)
            log.info("Variant %s final accuracy: %.4f", variant_code, avg_acc)
        return True

    log.info("Variant %s: %d done, %d pending, processing up to %d",
             variant_code, completed, pending, min(max_count, pending))

    # Run the variant - it will auto-resume from checkpoint, processing up to max_count
    runner.run_variant(questions, variant_code, max_questions=max_count)

    # Check progress after
    checkpoint2 = runner._load_checkpoint(variant_code)
    completed2 = len(checkpoint2) if checkpoint2 else 0
    pending2 = len(questions) - completed2
    log.info("Variant %s: now %d/%d done, %d remaining",
             variant_code, completed2, len(questions), pending2)

    if pending2 == 0:
        # All done - save final results and score
        results_path = os.path.join(OUTPUT_DIR, f"results_{variant_code}.json")
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint2, f, ensure_ascii=False, indent=2)
        log.info("Results saved: %s", results_path)

        avg_acc, scored = score_results(variant_code, checkpoint2)
        log.info("Variant %s final accuracy: %.4f", variant_code, avg_acc)

        # Check if all variants done
        all_done = all(
            os.path.exists(os.path.join(OUTPUT_DIR, f"scored_{v}.json"))
            for v in ["A", "B", "C", "D"]
        )
        if all_done:
            variant_scores = {}
            for v in ["A", "B", "C", "D"]:
                with open(os.path.join(OUTPUT_DIR, f"scored_{v}.json"), "r", encoding="utf-8") as f:
                    sc = json.load(f)
                scores = [r.get("accuracy", 0.0) for r in sc]
                variant_scores[v] = sum(scores) / len(scores) if scores else 0.0

            report = generate_report(variant_scores)
            report_path = os.path.join(OUTPUT_DIR, "experiment_report.md")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report)
            log.info("Report saved: %s", report_path)

            log.info("=" * 60)
            log.info("ALL EXPERIMENTS COMPLETE")
            for v in ["A", "B", "C", "D"]:
                log.info("  Variant %s: accuracy = %.4f", v, variant_scores[v])
            log.info("=" * 60)

        return True

    return False


def main():
    variant_arg = sys.argv[1] if len(sys.argv) > 1 else "A"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    variants = ["A", "B", "C", "D"] if variant_arg == "all" else [variant_arg]

    for v in variants:
        done = process_batch(v, count)
        if done:
            log.info("Variant %s complete!", v)
        else:
            log.info("Variant %s: more questions remain. Run again to continue.", v)


if __name__ == "__main__":
    main()
