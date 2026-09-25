from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from modules.embeddings import get_embeddings
from modules.knowledge_base import KnowledgeBase
from src.assembler.jira_assembler import generate_jira_document
from src.query_engine.query_executer import QueryExecutor


BASE_DIR = Path(__file__).resolve().parent.parent

JIRA_QUERIES_PATH = BASE_DIR / "jira_queries" / "jira_queries.json"
ACTIVE_KB_DIR = BASE_DIR / "data" / "knowledge_bases" / "active"

JIRA_QUERY_RESULTS_DIR = BASE_DIR / "jira_query_results"
MERGED_JIRA_RESULTS_PATH = JIRA_QUERY_RESULTS_DIR / "all_jira_query_results.json"

LOGS_DIR = BASE_DIR / "logs"
LOG_FILE = LOGS_DIR / "jira_generation_pipeline.log"

TOP_K = 5


@dataclass
class JiraGenerationResult:
    """Result returned to the Streamlit layer."""

    success: bool
    generated_document: str
    merged_results: str
    successful_queries: int
    failed_queries: int
    total_queries: int
    message: str


def _get_logger() -> logging.Logger:
    """Create the Jira-generation pipeline logger."""

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("jira_generation_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(
        LOG_FILE,
        mode="a",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


logger = _get_logger()


def _validate_prerequisites() -> None:
    """Validate the active KB and Jira query configuration."""

    if not ACTIVE_KB_DIR.exists():
        raise FileNotFoundError(
            "No active knowledge base found. Upload and process a BRD first."
        )

    if not JIRA_QUERIES_PATH.is_file():
        raise FileNotFoundError(
            f"Jira query file not found: {JIRA_QUERIES_PATH}"
        )


def _prepare_results_directory() -> None:
    """Clear stale Jira query results before a new run."""

    if JIRA_QUERY_RESULTS_DIR.exists():
        logger.info(
            "Clearing previous Jira query results: %s",
            JIRA_QUERY_RESULTS_DIR,
        )

        for child in JIRA_QUERY_RESULTS_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    JIRA_QUERY_RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


def _merge_query_results() -> Dict[str, Dict[str, Any]]:
    """Merge JQxxx result files into one JSON object."""

    merged: Dict[str, Dict[str, Any]] = {}

    result_files = sorted(
        JIRA_QUERY_RESULTS_DIR.glob("JQ*.json"),
        key=lambda path: path.name,
    )

    for result_file in result_files:
        try:
            with result_file.open("r", encoding="utf-8") as file:
                result = json.load(file)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(
                "Unable to read Jira query result %s: %s",
                result_file,
                exc,
            )
            continue

        if not isinstance(result, dict):
            continue

        query_id = str(
            result.get(
                "query_id",
                result_file.stem,
            )
        )
        merged[query_id] = result

    with MERGED_JIRA_RESULTS_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            merged,
            file,
            ensure_ascii=False,
            indent=2,
        )

    logger.info(
        "Merged %d Jira query results into %s",
        len(merged),
        MERGED_JIRA_RESULTS_PATH,
    )

    return merged


def _get_output_directory(brs_name: str) -> Path:
    """Return and create the BRS-specific generated-artifacts directory."""

    output_directory = BASE_DIR / "output" / brs_name
    output_directory.mkdir(parents=True, exist_ok=True)
    return output_directory


def generate_jira_document_pipeline(brs_name: str) -> JiraGenerationResult:
    """
    Generate the filled Jira artefact using the active DRS knowledge base.

    active KB
        -> Jira query execution
        -> per-query Jira JSON
        -> merged Jira results
        -> BRS-specific output directory
        -> Jira DOCX assembler
    """

    logger.info("=" * 80)
    logger.info("JIRA GENERATION PIPELINE STARTED")
    logger.info("=" * 80)

    _validate_prerequisites()
    _prepare_results_directory()

    logger.info("Loading embedding model...")
    embeddings = get_embeddings()

    logger.info(
        "Loading active knowledge base: %s",
        ACTIVE_KB_DIR,
    )

    knowledge_base = KnowledgeBase(
        index_dir=str(ACTIVE_KB_DIR),
        embeddings=embeddings,
    )
    knowledge_base.load()

    if knowledge_base.vector_store is None:
        raise RuntimeError(
            f"Failed to load knowledge base from {ACTIVE_KB_DIR}"
        )

    logger.info("Knowledge base loaded successfully.")

    logger.info(
        "Initializing Jira QueryExecutor | top_k=%d",
        TOP_K,
    )

    executor = QueryExecutor(
        queries_path=str(JIRA_QUERIES_PATH),
        knowledge_base=knowledge_base,
        run_dir=str(JIRA_QUERY_RESULTS_DIR),
        top_k=TOP_K,
    )

    logger.info("Executing Jira queries sequentially...")
    results = executor.execute_all()

    successful_queries = sum(
        1
        for result in results.values()
        if result.get("status") == "success"
    )
    failed_queries = len(results) - successful_queries

    logger.info(
        "Jira query execution complete | total=%d | success=%d | failed=%d",
        len(results),
        successful_queries,
        failed_queries,
    )

    merged = _merge_query_results()

    if not merged:
        raise RuntimeError(
            "No Jira query results were produced."
        )

    logger.info("Assembling Jira document...")
    if not brs_name or not brs_name.strip():
        raise ValueError("BRS name is required for Jira generation.")

    safe_brs_name = Path(brs_name).stem
    output_directory = _get_output_directory(safe_brs_name)

    logger.info("BRS name: %s", safe_brs_name)
    logger.info("Output directory: %s", output_directory)

    generated_document = generate_jira_document(output_dir=output_directory)

    logger.info(
        "Jira document generated: %s",
        generated_document,
    )

    logger.info("=" * 80)
    logger.info("JIRA GENERATION PIPELINE COMPLETED")
    logger.info("=" * 80)

    return JiraGenerationResult(
        success=True,
        generated_document=str(generated_document),
        merged_results=str(MERGED_JIRA_RESULTS_PATH),
        successful_queries=successful_queries,
        failed_queries=failed_queries,
        total_queries=len(results),
        message="Jira user-story document generated successfully.",
    )


if __name__ == "__main__":
    raise SystemExit(
        "Run generate_jira_document_pipeline(brs_name=...) from the application layer."
    )

    print()
    print("=" * 70)
    print("JIRA GENERATION COMPLETED")
    print("=" * 70)
    print(
        f"Queries  : {result.successful_queries}/"
        f"{result.total_queries} successful"
    )
    print(f"Failed   : {result.failed_queries}")
    print(f"Results  : {result.merged_results}")
    print(f"Jira DOC : {result.generated_document}")
    print(f"Message  : {result.message}")
