from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from modules.embeddings import get_embeddings
from modules.knowledge_base import KnowledgeBase
from src.assembler.drs_assembler import generate_drs as assemble_drs
from src.query_engine.query_executer import QueryExecutor


BASE_DIR = Path(__file__).resolve().parent.parent

QUERIES_PATH = BASE_DIR / "drs_queries" / "extraction_queries.json"

KNOWLEDGE_BASES_DIR = BASE_DIR / "data" / "knowledge_bases"
ACTIVE_KB_DIR = KNOWLEDGE_BASES_DIR / "active"

QUERY_RESULTS_DIR = BASE_DIR / "query_results"
MERGED_RESULTS_PATH = QUERY_RESULTS_DIR / "all_query_results.json"

LOGS_DIR = BASE_DIR / "logs"
LOG_FILE = LOGS_DIR / "fetch_drs_pipeline.log"

TOP_K = 3


@dataclass
class DRSGenerationResult:
    """Result returned to the Streamlit layer after DRS generation."""

    success: bool
    generated_document: str
    merged_results: str
    successful_queries: int
    failed_queries: int
    total_queries: int
    message: str


def _get_logger() -> logging.Logger:
    """Create the dedicated DRS-generation pipeline logger."""

    LOGS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    logger = logging.getLogger("fetch_drs_pipeline")
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
    """Validate the active KB and static query configuration."""

    if not ACTIVE_KB_DIR.exists():
        raise FileNotFoundError(
            "No active knowledge base found. "
            "Upload and process a BRD first."
        )

    if not QUERIES_PATH.is_file():
        raise FileNotFoundError(
            f"Extraction queries not found: {QUERIES_PATH}"
        )


def _prepare_query_results_directory() -> None:
    """Clear stale query results before generating a new DRS."""

    if QUERY_RESULTS_DIR.exists():
        logger.info(
            "Clearing previous query results: %s",
            QUERY_RESULTS_DIR,
        )

        for child in QUERY_RESULTS_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    QUERY_RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


def _merge_query_results() -> Dict[str, Dict[str, Any]]:
    """
    Merge Qxxx.json results into all_query_results.json.

    This is the in-process equivalent of the current
    tests.merge_query_results step, so the Streamlit layer does not need to
    invoke a second Python process.
    """

    merged: Dict[str, Dict[str, Any]] = {}

    result_files = sorted(
        QUERY_RESULTS_DIR.glob("Q*.json"),
        key=lambda path: path.name,
    )

    for result_file in result_files:
        if result_file.name == MERGED_RESULTS_PATH.name:
            continue

        try:
            with result_file.open(
                "r",
                encoding="utf-8",
            ) as file:
                result = json.load(file)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(
                "Unable to read query result %s: %s",
                result_file,
                exc,
            )
            continue

        if not isinstance(result, dict):
            logger.warning(
                "Ignoring non-object query result: %s",
                result_file,
            )
            continue

        query_id = result.get(
            "query_id",
            result_file.stem,
        )

        merged[str(query_id)] = result

    with MERGED_RESULTS_PATH.open(
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
        "Merged %d query results into %s",
        len(merged),
        MERGED_RESULTS_PATH,
    )

    return merged


def _get_output_directory(brs_name: str) -> Path:
    """Return and create the BRS-specific generated-artifacts directory."""

    output_directory = BASE_DIR / "output" / brs_name
    output_directory.mkdir(parents=True, exist_ok=True)
    return output_directory


def generate_drs(brs_name: str) -> DRSGenerationResult:
    """
    Run the complete DRS generation flow used by the Streamlit UI.

    active KB
        -> sequential query execution
        -> per-query JSON results
        -> merged all_query_results.json
        -> BRS-specific output directory
        -> DRS assembler
        -> generated_drs.docx
    """

    logger.info("=" * 80)
    logger.info("DRS GENERATION PIPELINE STARTED")
    logger.info("=" * 80)

    _validate_prerequisites()
    _prepare_query_results_directory()

    logger.info(
        "Loading embedding model..."
    )

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
        "Initializing query executor | top_k=%d",
        TOP_K,
    )

    executor = QueryExecutor(
        queries_path=str(QUERIES_PATH),
        knowledge_base=knowledge_base,
        run_dir=str(QUERY_RESULTS_DIR),
        top_k=TOP_K,
    )

    logger.info(
        "Executing extraction queries sequentially..."
    )

    results = executor.execute_all()

    successful_queries = sum(
        1
        for result in results.values()
        if result.get("status") == "success"
    )

    failed_queries = len(results) - successful_queries

    logger.info(
        "Query execution complete | total=%d | success=%d | failed=%d",
        len(results),
        successful_queries,
        failed_queries,
    )

    logger.info(
        "Merging query results..."
    )

    merged = _merge_query_results()

    if not merged:
        raise RuntimeError(
            "No query results were produced; DRS cannot be assembled."
        )

    logger.info(
        "Assembling final DRS document..."
    )

    if not brs_name or not brs_name.strip():
        raise ValueError("BRS name is required for DRS generation.")

    safe_brs_name = Path(brs_name).stem
    output_directory = _get_output_directory(safe_brs_name)

    logger.info("BRS name: %s", safe_brs_name)
    logger.info("Output directory: %s", output_directory)

    generated_document = assemble_drs(output_dir=output_directory)

    logger.info(
        "DRS document generated: %s",
        generated_document,
    )

    logger.info("=" * 80)
    logger.info("DRS GENERATION PIPELINE COMPLETED")
    logger.info("=" * 80)

    return DRSGenerationResult(
        success=True,
        generated_document=str(generated_document),
        merged_results=str(MERGED_RESULTS_PATH),
        successful_queries=successful_queries,
        failed_queries=failed_queries,
        total_queries=len(results),
        message="DRS generated successfully.",
    )


if __name__ == "__main__":
    raise SystemExit(
        "Run generate_drs(brs_name=...) from the application layer."
    )

    print()
    print("=" * 70)
    print("DRS GENERATION COMPLETED")
    print("=" * 70)
    print(
        f"Queries  : {result.successful_queries}/"
        f"{result.total_queries} successful"
    )
    print(f"Failed   : {result.failed_queries}")
    print(f"Results  : {result.merged_results}")
    print(f"DRS      : {result.generated_document}")
    print(f"Message  : {result.message}")
