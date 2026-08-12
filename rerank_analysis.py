"""Exercise 3.5 (Bonus) — Retrieval Reranking analysis.

Loads the saved golden dataset + actual-answer traces, measures Context
Recall / Context Precision before and after `rerank_by_overlap()`, and
prints a Markdown table ready to paste into exercises.md.

Does NOT call the RAG system or any LLM again — it only re-scores the
already-retrieved chunks stored in artifacts/actual_answers.json, so it is
safe to re-run as many times as you like.

Usage:
    python rerank_analysis.py                 # 5 lowest-precision cases
    python rerank_analysis.py --n 8            # pick a different count
    python rerank_analysis.py --ids H03 A01 A02 A03 M06   # pick specific IDs
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from template import RAGASEvaluator, rerank_by_overlap


def load_traces(golden_path: Path, actual_path: Path) -> list[dict]:
    golden = {
        record["id"]: record
        for record in json.loads(golden_path.read_text(encoding="utf-8"))["qa_pairs"]
    }
    actual = json.loads(actual_path.read_text(encoding="utf-8"))["answers"]

    traces = []
    for record in actual:
        qid = record["id"]
        if record.get("error") is not None:
            continue
        gold = golden[qid]
        contexts = [c["text"] for c in record["retrieved_contexts"]]
        if len(contexts) < 2:
            continue  # reranking a single chunk is meaningless
        traces.append(
            {
                "id": qid,
                "question": gold["question"],
                "expected": gold["expected_answer"],
                "contexts": contexts,
            }
        )
    return traces


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=5, help="How many cases to report")
    parser.add_argument("--ids", nargs="*", default=None, help="Specific QA IDs to use")
    parser.add_argument("--golden", type=Path, default=Path("golden_dataset.json"))
    parser.add_argument("--actual", type=Path, default=Path("artifacts/actual_answers.json"))
    args = parser.parse_args()

    evaluator = RAGASEvaluator()
    traces = load_traces(args.golden, args.actual)
    if not traces:
        raise SystemExit("No usable traces found in artifacts/actual_answers.json")

    rows = []
    for trace in traces:
        contexts = trace["contexts"]
        expected = trace["expected"]
        # Rerank using the QUESTION (not the expected answer) — a real
        # reranker never sees the gold answer, only the query. Reranking by
        # expected would be gold leakage into the retriever step.
        query = trace["question"]

        recall_before = evaluator.evaluate_context_recall(contexts, expected)
        precision_before = evaluator.evaluate_context_precision(contexts, expected)

        reranked = rerank_by_overlap(contexts, query)
        recall_after = evaluator.evaluate_context_recall(reranked, expected)
        precision_after = evaluator.evaluate_context_precision(reranked, expected)

        rows.append(
            {
                "id": trace["id"],
                "recall_before": recall_before,
                "recall_after": recall_after,
                "precision_before": precision_before,
                "precision_after": precision_after,
                "delta_precision": precision_after - precision_before,
            }
        )

    if args.ids:
        wanted = set(args.ids)
        selected = [r for r in rows if r["id"] in wanted]
    else:
        # Default: the N cases with the most room to improve (lowest
        # precision_before) — this is where reranking has a visible effect.
        selected = sorted(rows, key=lambda r: r["precision_before"])[: args.n]

    print(
        "| ID | Recall before | Recall after | Precision before | "
        "Precision after | Delta Precision |"
    )
    print("|---|---:|---:|---:|---:|---:|")
    for r in selected:
        print(
            f"| {r['id']} | {r['recall_before']:.3f} | {r['recall_after']:.3f} | "
            f"{r['precision_before']:.3f} | {r['precision_after']:.3f} | "
            f"{r['delta_precision']:+.3f} |"
        )

    avg = lambda key: sum(r[key] for r in selected) / len(selected)
    print(
        f"| **Avg** | {avg('recall_before'):.3f} | {avg('recall_after'):.3f} | "
        f"{avg('precision_before'):.3f} | {avg('precision_after'):.3f} | "
        f"{avg('delta_precision'):+.3f} |"
    )

    unchanged_recall = all(
        abs(r["recall_before"] - r["recall_after"]) < 1e-9 for r in selected
    )
    print(
        f"\nRecall unchanged for all selected cases: {unchanged_recall} "
        "(expected — reordering never changes the union of retrieved chunks)."
    )


if __name__ == "__main__":
    main()
