from __future__ import annotations

import json
import os
from typing import Any, Dict


RESULTS_DIR = os.path.join(
    "query_results",
)

OUTPUT_FILE = os.path.join(
    RESULTS_DIR,
    "all_query_results.json",
)


def merge_query_results() -> None:
    """Merge all Qxxx.json files into one JSON file."""

    if not os.path.isdir(RESULTS_DIR):
        raise FileNotFoundError(
            f"Query results directory not found: {RESULTS_DIR}"
        )

    merged_results: Dict[str, Any] = {}

    result_files = sorted(
        file_name
        for file_name in os.listdir(RESULTS_DIR)
        if file_name.startswith("Q")
        and file_name.endswith(".json")
        and file_name != "all_query_results.json"
    )

    if not result_files:
        raise FileNotFoundError(
            f"No query result files found in: {RESULTS_DIR}"
        )

    for file_name in result_files:
        file_path = os.path.join(
            RESULTS_DIR,
            file_name,
        )

        with open(
            file_path,
            "r",
            encoding="utf-8",
        ) as file:
            result = json.load(file)

        query_id = result.get(
            "query_id",
            os.path.splitext(file_name)[0],
        )

        merged_results[query_id] = result

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            merged_results,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"Merged {len(result_files)} query results."
    )
    print(
        f"Output: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    merge_query_results()