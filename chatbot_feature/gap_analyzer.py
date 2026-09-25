from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from modules.embeddings import get_embeddings
from modules.knowledge_base import KnowledgeBase


logger = logging.getLogger("chatbot_feature.gap_analyzer")

BASE_DIR = Path(__file__).resolve().parent.parent
ACTIVE_KB_DIR = BASE_DIR / "data" / "knowledge_bases" / "active"
DRS_RESULTS_PATH = BASE_DIR / "query_results" / "all_query_results.json"
JIRA_RESULTS_PATH = BASE_DIR / "jira_query_results" / "all_jira_query_results.json"


def _answer_indicates_missing_information(value: Any) -> bool:
    """Return True when the answer explicitly says source information is missing."""
    if value is None:
        return False

    missing_phrases = (
        "not explicitly mentioned",
        "not explicitly provided",
        "not present in the document",
        "not present in source",
        "not specified in the document",
        "not specified in source",
        "not available in the document",
        "not available in source",
        "no information found",
        "no information is provided",
        "no information is present",
        "information is not provided",
        "information is not present",
        "cannot be determined from the document",
        "cannot be determined from source",
    )

    def contains_missing_phrase(item: Any) -> bool:
        if isinstance(item, str):
            normalized = " ".join(item.lower().split())
            return any(phrase in normalized for phrase in missing_phrases)

        if isinstance(item, dict):
            return any(contains_missing_phrase(nested) for nested in item.values())

        if isinstance(item, (list, tuple, set)):
            return any(contains_missing_phrase(nested) for nested in item)

        return False

    return contains_missing_phrase(value)



def _load_results(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load a merged query-result JSON object."""
    if not path.is_file():
        raise FileNotFoundError(f"Query results file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")

    return data


def find_empty_targets(path: Path) -> List[str]:
    """
    Return targets whose successful answer explicitly indicates that the
    source document does not contain the requested information.

    Failed queries are intentionally excluded: a failed query means the
    answer was unavailable, not that the information is missing from the BRD.
    """
    results = _load_results(path)
    empty_targets: List[str] = []

    for fallback_query_id, result in results.items():
        if not isinstance(result, dict):
            continue

        target = result.get("target") or fallback_query_id
        status = result.get("status")

        if status != "success":
            continue

        if _answer_indicates_missing_information(result.get("answer")):
            empty_targets.append(str(target))

    return empty_targets



def _build_gap_document(
    source: str,
    empty_targets: List[str],
    artifact_type: str,
) -> Optional[Document]:
    """Create one compact vector-search document for an artifact's gaps."""
    if not empty_targets:
        return None

    content = (
        "content: gaps/missing informations in the BRD\n"
        f"source: {source}\n"
        "empty fields:\n"
        + "\n".join(f"- {target}" for target in empty_targets)
    )

    return Document(
        page_content=content,
        metadata={
            "source": source,
            "source_type": "gap_analysis",
            "gap_type": "empty_fields",
            "artifact_type": artifact_type,
            "empty_field_count": len(empty_targets),
            "content": "gaps/missing informations in the BRD",
        },
    )



def add_gap_chunk_to_active_kb(
    *,
    results_path: Path,
    source: str,
    artifact_type: str,
    active_kb_dir: Path = ACTIVE_KB_DIR,
) -> Dict[str, Any]:
    """Analyze one aggregate JSON and append its gap chunk to the active KB."""
    empty_targets = find_empty_targets(results_path)
    document = _build_gap_document(
        source=source,
        empty_targets=empty_targets,
        artifact_type=artifact_type,
    )

    if document is None:
        logger.info("No empty %s fields detected.", artifact_type)
        return {
            "artifact_type": artifact_type,
            "empty_fields": [],
            "chunks_added": 0,
        }

    embeddings = get_embeddings()
    knowledge_base = KnowledgeBase(
        index_dir=str(active_kb_dir),
        embeddings=embeddings,
    )
    knowledge_base.load()

    if knowledge_base.vector_store is None:
        raise RuntimeError(
            f"Active knowledge base could not be loaded from {active_kb_dir}"
        )

    # Avoid adding the same gap chunk twice during a repeated generation run.
    existing_documents = knowledge_base.doc_store.get(source, [])
    document_content = document.page_content
    already_exists = any(
        isinstance(item, dict) and item.get("content") == document_content
        for item in existing_documents
    )

    if already_exists:
        logger.info("Gap chunk already exists for %s; skipping.", artifact_type)
        return {
            "artifact_type": artifact_type,
            "empty_fields": empty_targets,
            "chunks_added": 0,
        }

    knowledge_base.add_documents([document])

    logger.info(
        "Added %s gap chunk with %d empty fields to active KB.",
        artifact_type,
        len(empty_targets),
    )

    return {
        "artifact_type": artifact_type,
        "empty_fields": empty_targets,
        "chunks_added": 1,
    }


def add_drs_gap_chunk(
    results_path: Path = DRS_RESULTS_PATH,
    active_kb_dir: Path = ACTIVE_KB_DIR,
) -> Dict[str, Any]:
    """Create and add the DRS gap chunk."""
    return add_gap_chunk_to_active_kb(
        results_path=results_path,
        source="drs gap/empty fields",
        artifact_type="drs",
        active_kb_dir=active_kb_dir,
    )


def add_jira_gap_chunk(
    results_path: Path = JIRA_RESULTS_PATH,
    active_kb_dir: Path = ACTIVE_KB_DIR,
) -> Dict[str, Any]:
    """Create and add the Jira gap chunk."""
    return add_gap_chunk_to_active_kb(
        results_path=results_path,
        source="jira user stories gap/empty fields",
        artifact_type="jira",
        active_kb_dir=active_kb_dir,
    )
