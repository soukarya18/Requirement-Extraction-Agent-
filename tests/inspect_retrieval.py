from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Dict, List

from modules.embeddings import get_embeddings
from modules.knowledge_base import KnowledgeBase


BASE_DIR = Path(__file__).resolve().parent.parent
QUERIES_PATH = BASE_DIR / "drs_queries" / "extraction_queries.json"
ACTIVE_KB_DIR = BASE_DIR / "data" / "knowledge_bases" / "active"
OUTPUT_DIR = BASE_DIR / "logs"
OUTPUT_TEXT = OUTPUT_DIR / "retrieval_inspection.txt"
OUTPUT_JSON = OUTPUT_DIR / "retrieval_inspection.json"
TOP_K = 5

# Inspect only these queries. Use [] to inspect every query.
INSPECT_QUERY_IDS: List[str] = [
    "Q004",  # Business Objectives
    "Q007",  # Stakeholders
    "Q015",  # Functional Requirements
    "Q016",  # Non-Functional Requirements
    "Q017",  # Business Rules
    "Q018",  # Epics
    "Q019",  # User Stories
    "Q020",  # Acceptance Criteria
    "Q024",  # Traceability Matrix
]


def load_queries() -> List[Dict[str, Any]]:
    """Load query definitions from extraction_queries.json."""
    if not QUERIES_PATH.is_file():
        raise FileNotFoundError(f"Extraction queries not found: {QUERIES_PATH}")

    with QUERIES_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    queries = data.get("queries")
    if not isinstance(queries, list):
        raise ValueError("'queries' must be a list in extraction_queries.json.")

    return queries


def build_query_map(queries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Build a query-id to query-definition mapping."""
    return {
        str(query["query_id"]): query
        for query in queries
        if "query_id" in query
    }


def inspect_retrieval() -> List[Dict[str, Any]]:
    """Retrieve and report the exact chunks used for selected queries."""
    if not ACTIVE_KB_DIR.is_dir():
        raise FileNotFoundError(f"Active knowledge base not found: {ACTIVE_KB_DIR}")

    query_map = build_query_map(load_queries())

    if INSPECT_QUERY_IDS:
        unknown_ids = [query_id for query_id in INSPECT_QUERY_IDS if query_id not in query_map]
        if unknown_ids:
            raise ValueError("Unknown query IDs: " + ", ".join(unknown_ids))
        query_ids = INSPECT_QUERY_IDS
    else:
        query_ids = list(query_map.keys())

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("RETRIEVAL INSPECTION")
    print("=" * 100)
    print(f"Knowledge Base : {ACTIVE_KB_DIR}")
    print(f"Queries File   : {QUERIES_PATH}")
    print(f"TOP_K          : {TOP_K}")
    print(f"Queries        : {len(query_ids)}")
    print("=" * 100)

    embeddings = get_embeddings()
    knowledge_base = KnowledgeBase(
        index_dir=str(ACTIVE_KB_DIR),
        embeddings=embeddings,
    )
    knowledge_base.load()

    if knowledge_base.vector_store is None:
        raise RuntimeError(f"Could not load FAISS index from {ACTIVE_KB_DIR}")

    inspections: List[Dict[str, Any]] = []
    text_blocks: List[str] = []

    for number, query_id in enumerate(query_ids, start=1):
        query = query_map[query_id]
        question = str(query.get("question", ""))
        target = str(query.get("target", ""))
        dependencies = query.get("depends_on", [])

        header = (
            "\n" + "#" * 100 +
            f"\n[{number}/{len(query_ids)}] {query_id} | {target}" +
            "\n" + "#" * 100
        )

        print(header)
        print(f"QUESTION: {question}")
        print(f"DEPENDENCIES: {dependencies}")
        print("-" * 100)

        results = knowledge_base.similarity_search_with_score(
            query=question,
            k=TOP_K,
        )

        query_inspection: Dict[str, Any] = {
            "query_id": query_id,
            "target": target,
            "question": question,
            "depends_on": dependencies,
            "retrieved_chunks": [],
        }

        text_blocks.extend([
            header,
            f"QUESTION: {question}",
            f"DEPENDENCIES: {dependencies}",
        ])

        for rank, (document, score) in enumerate(results, start=1):
            metadata = document.metadata or {}
            content = document.page_content

            chunk_data = {
                "rank": rank,
                "score": float(score),
                "metadata": metadata,
                "content": content,
            }
            query_inspection["retrieved_chunks"].append(chunk_data)

            block = (
                f"\n--- CHUNK {rank} ---\n"
                f"Score: {float(score):.6f}\n"
                f"Metadata: {json.dumps(metadata, ensure_ascii=False)}\n"
                f"CONTENT:\n{content}\n"
            )
            print(block)
            text_blocks.append(block)

        inspections.append(query_inspection)
        print(f"\nRETRIEVAL COMPLETE: {query_id}")

    OUTPUT_TEXT.write_text("\n".join(text_blocks), encoding="utf-8")
    OUTPUT_JSON.write_text(
        json.dumps(inspections, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 100)
    print("INSPECTION COMPLETE")
    print("=" * 100)
    print(f"Text report : {OUTPUT_TEXT}")
    print(f"JSON report : {OUTPUT_JSON}")
    print(
        "Important: with the current FAISS/L2 implementation, "
        "lower scores represent closer matches."
    )

    return inspections


if __name__ == "__main__":
    inspect_retrieval()
