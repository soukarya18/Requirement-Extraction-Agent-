from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


QUERY_GROUPS = {
    "Epic": [f"JQ{i:03d}" for i in range(1, 19)],
    "Story": [f"JQ{i:03d}" for i in range(19, 40)],
    "Bug": ["JQ040"],
    "Traceability": ["JQ041"],
}


def load_results(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load merged or per-query Jira results."""

    if not path.exists():
        raise FileNotFoundError(
            f"Results file not found: {path}"
        )

    if path.is_file():
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            payload = json.load(file)

        if not isinstance(payload, dict):
            raise ValueError(
                "Results JSON must be an object."
            )

        # Merged format:
        # {
        #   "JQ001": {...},
        #   "JQ002": {...}
        # }
        if any(
            key.startswith("JQ")
            for key in payload
        ):
            return {
                str(key): value
                for key, value in payload.items()
                if isinstance(value, dict)
            }

        # Single query-result file.
        query_id = str(
            payload.get(
                "query_id",
                path.stem,
            )
        )

        return {
            query_id: payload
        }

    raise ValueError(
        f"Expected a JSON file, got directory: {path}"
    )


def answer_type(answer: Any) -> str:
    """Return a readable JSON type name."""

    if answer is None:
        return "null"

    if isinstance(answer, list):
        return "array"

    if isinstance(answer, dict):
        return "object"

    if isinstance(answer, str):
        return "string"

    if isinstance(answer, bool):
        return "boolean"

    if isinstance(answer, (int, float)):
        return "number"

    return type(answer).__name__


def item_count(answer: Any) -> int:
    """Return count of logical answer items."""

    if answer is None:
        return 0

    if isinstance(answer, list):
        return len(answer)

    if isinstance(answer, dict):
        return 1

    return 1


def summarize_answer(
    query_id: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a diagnostic summary for one query."""

    answer = result.get("answer")

    summary: Dict[str, Any] = {
        "query_id": query_id,
        "status": result.get(
            "status",
            "missing",
        ),
        "answer_type": answer_type(answer),
        "item_count": item_count(answer),
        "error": result.get("error"),
        "has_raw_llm_response": bool(
            result.get(
                "raw_llm_response"
            )
        ),
    }

    if isinstance(answer, list):
        summary["sample_keys"] = [
            sorted(
                item.keys()
            )
            for item in answer[:3]
            if isinstance(item, dict)
        ]

    elif isinstance(answer, dict):
        summary["sample_keys"] = [
            sorted(answer.keys())
        ]

    else:
        summary["sample_keys"] = []

    return summary


def print_query_report(
    query_id: str,
    summary: Dict[str, Any],
) -> None:
    """Print one compact query diagnostic."""

    status = summary["status"]
    answer_kind = summary["answer_type"]
    count = summary["item_count"]

    print(
        f"{query_id} | "
        f"status={status:<8} | "
        f"type={answer_kind:<7} | "
        f"items={count:<3}"
    )

    if summary.get("error"):
        print(
            f"    ERROR: {summary['error']}"
        )

    keys = summary.get(
        "sample_keys",
        [],
    )

    if keys:
        print(
            f"    KEYS: {keys}"
        )


def inspect(
    results: Dict[str, Dict[str, Any]],
) -> None:
    """Print grouped query diagnostics and identify likely layer failures."""

    summaries = {
        query_id: summarize_answer(
            query_id,
            result,
        )
        for query_id, result in sorted(
            results.items()
        )
    }

    print("=" * 90)
    print("JIRA QUERY RESULT DIAGNOSTIC")
    print("=" * 90)

    success_count = sum(
        1
        for summary in summaries.values()
        if summary["status"] == "success"
    )
    failed_count = sum(
        1
        for summary in summaries.values()
        if summary["status"] != "success"
    )

    print(
        f"Queries found: {len(summaries)} | "
        f"success: {success_count} | "
        f"failed/non-success: {failed_count}"
    )
    print()

    for group_name, query_ids in QUERY_GROUPS.items():
        print("-" * 90)
        print(group_name)
        print("-" * 90)

        for query_id in query_ids:
            if query_id not in summaries:
                print(
                    f"{query_id} | "
                    "MISSING FROM RESULTS"
                )
                continue

            print_query_report(
                query_id,
                summaries[query_id],
            )

        print()

    # Story-specific diagnostics.
    print("=" * 90)
    print("STORY PIPELINE DIAGNOSTIC")
    print("=" * 90)

    story_core = summaries.get(
        "JQ019"
    )

    if not story_core:
        print(
            "JQ019 is missing. "
            "The assembler cannot create any stories."
        )
    else:
        print(
            f"JQ019 status: {story_core['status']}"
        )
        print(
            f"JQ019 story count: {story_core['item_count']}"
        )

        if (
            story_core["status"] == "success"
            and story_core["item_count"] == 0
        ):
            print(
                "DIAGNOSIS: JQ019 succeeded but returned no stories."
            )
        elif (
            story_core["status"] != "success"
        ):
            print(
                "DIAGNOSIS: Story generation failed upstream "
                "(retrieval/LLM/validation), so an empty Story section "
                "in the DOCX is expected."
            )
        else:
            print(
                "DIAGNOSIS: JQ019 returned Story objects. "
                "If the DOCX has no stories, inspect the assembler."
            )

    # Acceptance criteria diagnostics.
    ac = summaries.get("JQ039")

    if ac:
        print(
            f"JQ039 status: {ac['status']} | "
            f"acceptance-criteria records: {ac['item_count']}"
        )

        if (
            ac["status"] == "success"
            and ac["item_count"] == 0
        ):
            print(
                "WARNING: No Story acceptance criteria were produced."
            )

    # Bug diagnostics.
    bug = summaries.get("JQ040")

    if bug:
        print(
            f"JQ040 status: {bug['status']} | "
            f"bug candidates: {bug['item_count']}"
        )

        if (
            bug["status"] == "success"
            and bug["item_count"] == 0
        ):
            print(
                "OK: No source-supported bug candidate was found."
            )

    # Traceability diagnostics.
    trace = summaries.get(
        "JQ041"
    )

    if trace:
        print(
            f"JQ041 status: {trace['status']} | "
            f"traceability rows: {trace['item_count']}"
        )

        if trace["status"] != "success":
            print(
                "NOTE: Traceability failed upstream; this should be treated "
                "separately from Story/Epic extraction quality."
            )

    # Contract-level checks.
    print()
    print("=" * 90)
    print("RESULT-SHAPE CHECKS")
    print("=" * 90)

    expected_array_queries = {
        "JQ003",
        "JQ006",
        "JQ007",
        "JQ009",
        "JQ010",
        "JQ011",
        "JQ012",
        "JQ013",
        "JQ017",
        "JQ018",
        "JQ019",
        "JQ020",
        "JQ021",
        "JQ022",
        "JQ023",
        "JQ024",
        "JQ025",
        "JQ026",
        "JQ027",
        "JQ028",
        "JQ029",
        "JQ030",
        "JQ031",
        "JQ032",
        "JQ033",
        "JQ034",
        "JQ035",
        "JQ036",
        "JQ037",
        "JQ038",
        "JQ039",
        "JQ040",
        "JQ041",
    }

    expected_object_queries = {
        "JQ001",
        "JQ002",
        "JQ004",
        "JQ005",
        "JQ008",
        "JQ014",
        "JQ015",
        "JQ016",
    }

    shape_errors = 0

    for query_id, expected in sorted(
        [
            *[
                (
                    query_id,
                    "array",
                )
                for query_id in expected_array_queries
            ],
            *[
                (
                    query_id,
                    "object",
                )
                for query_id in expected_object_queries
            ],
        ]
    ):
        summary = summaries.get(
            query_id
        )

        if not summary:
            continue

        if summary["status"] != "success":
            continue

        actual = summary["answer_type"]

        if (
            actual != expected
            and not (
                expected == "array"
                and actual == "null"
            )
        ):
            shape_errors += 1
            print(
                f"SHAPE MISMATCH: {query_id} "
                f"expected={expected}, actual={actual}"
            )

    if shape_errors == 0:
        print(
            "No successful-query response-shape mismatches detected."
        )
    else:
        print(
            f"Found {shape_errors} successful-query shape mismatches."
        )

    print()
    print("=" * 90)
    print("INTERPRETATION")
    print("=" * 90)
    print(
        "Use this output to separate failures by layer:"
    )
    print(
        "1. Query status failed -> inspect retrieval/LLM/validation."
    )
    print(
        "2. Query succeeded with good item count -> inspect answer quality/schema."
    )
    print(
        "3. Query succeeded with correct data but DOCX is blank -> inspect assembler."
    )
    print(
        "4. JQ019 has stories but DOCX has no stories -> assembler bug."
    )
    print(
        "5. JQ039 has criteria but DOCX has empty AC tables -> assembler mapping bug."
    )


def main() -> None:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Inspect existing Jira query results without calling the LLM."
        )
    )

    parser.add_argument(
        "results_path",
        nargs="?",
        default=(
            "jira_query_results/all_jira_query_results.json"
        ),
        help=(
            "Path to all_jira_query_results.json"
        ),
    )

    args = parser.parse_args()

    results_path = Path(
        args.results_path
    )

    results = load_results(
        results_path
    )

    inspect(
        results
    )


if __name__ == "__main__":
    main()
