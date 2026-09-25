from __future__ import annotations

import logging
import os

from modules.embeddings import get_embeddings
from modules.knowledge_base import KnowledgeBase
from src.query_engine.query_executer import QueryExecutor


BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

KB_DIR = os.path.join(
    BASE_DIR,
    "data",
    "knowledge_bases",
    "test_project" ,
)

QUERIES_PATH = os.path.join(
    BASE_DIR,
    "drs_queries",
    "extraction_queries.json",
)

RESULTS_DIR = os.path.join(
    BASE_DIR,
    "query_results",
)

LOG_DIR = os.path.join(
    BASE_DIR,
    "logs",
)

LOG_FILE = os.path.join(
    LOG_DIR,
    "query_execution.log",
)


def configure_logging() -> logging.Logger:
    """Configure centralized query execution logging."""

    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger()

    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers if this function is called again.
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(
        LOG_FILE,
        mode="w",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logging.getLogger("pipeline")


def main() -> None:
    """Execute all DRS extraction queries sequentially."""

    logger = configure_logging()

    logger.info("=" * 80)
    logger.info("QUERY EXECUTION STARTED")
    logger.info("=" * 80)

    # ------------------------------------------------------------------
    # Validate existing knowledge base
    # ------------------------------------------------------------------

    if not os.path.isdir(KB_DIR):
        raise FileNotFoundError(
            f"Knowledge base directory not found: {KB_DIR}"
        )

    index_path = os.path.join(
        KB_DIR,
        "index.faiss",
    )

    pickle_path = os.path.join(
        KB_DIR,
        "index.pkl",
    )

    if not os.path.isfile(index_path):
        raise FileNotFoundError(
            f"FAISS index not found: {index_path}"
        )

    if not os.path.isfile(pickle_path):
        raise FileNotFoundError(
            f"FAISS metadata not found: {pickle_path}"
        )

    # ------------------------------------------------------------------
    # Validate extraction queries
    # ------------------------------------------------------------------

    if not os.path.isfile(QUERIES_PATH):
        raise FileNotFoundError(
            f"Extraction queries file not found: {QUERIES_PATH}"
        )

    os.makedirs(
        RESULTS_DIR,
        exist_ok=True,
    )

    logger.info(
        "Knowledge base: %s",
        KB_DIR,
    )

    logger.info(
        "Queries: %s",
        QUERIES_PATH,
    )

    logger.info(
        "Results: %s",
        RESULTS_DIR,
    )

    logger.info(
        "Log: %s",
        LOG_FILE,
    )

    # ------------------------------------------------------------------
    # Load embeddings
    # ------------------------------------------------------------------

    logger.info(
        "Loading embedding model..."
    )

    embeddings = get_embeddings()

    logger.info(
        "Embedding model loaded."
    )

    # ------------------------------------------------------------------
    # Load existing knowledge base
    # ------------------------------------------------------------------

    logger.info(
        "Loading knowledge base..."
    )

    knowledge_base = KnowledgeBase(
        index_dir=KB_DIR,
        embeddings=embeddings,
    )

    knowledge_base.load()

    if knowledge_base.vector_store is None:
        raise RuntimeError(
            f"Failed to load knowledge base: {KB_DIR}"
        )

    logger.info(
        "Knowledge base loaded."
    )

    # ------------------------------------------------------------------
    # Execute queries
    # ------------------------------------------------------------------

    executor = QueryExecutor(
        queries_path=QUERIES_PATH,
        knowledge_base=knowledge_base,
        run_dir=RESULTS_DIR,
        top_k=3,
    )

    logger.info(
        "Query executor initialized with top_k=3."
    )

    results = executor.execute_all()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    total = len(results)

    successful = sum(
        1
        for result in results.values()
        if result.get("status") == "success"
    )

    failed = total - successful

    logger.info("=" * 80)
    logger.info("QUERY EXECUTION COMPLETED")
    logger.info(
        "Total: %d | Successful: %d | Failed: %d",
        total,
        successful,
        failed,
    )
    logger.info("=" * 80)

    print(
        f"\nCompleted: {successful}/{total} queries"
    )

    print(
        f"Results: {RESULTS_DIR}"
    )

    print(
        f"Log: {LOG_FILE}"
    )


if __name__ == "__main__":
    main()