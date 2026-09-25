from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

from langchain_core.documents import Document

from modules.document_loader import load_and_split_document
from modules.embeddings import get_embeddings
from modules.knowledge_base import KnowledgeBase


BASE_DIR = Path(__file__).resolve().parent.parent

UPLOADS_DIR = BASE_DIR / "data" / "uploads"
KNOWLEDGE_BASES_DIR = BASE_DIR / "data" / "knowledge_bases"
ACTIVE_KB_DIR = KNOWLEDGE_BASES_DIR / "active"

LOGS_DIR = BASE_DIR / "logs"
LOG_FILE = LOGS_DIR / "ingestion_pipeline.log"


@dataclass
class IngestionResult:
    """Result returned to the Streamlit layer after ingestion."""

    success: bool
    document_path: str
    chunks_created: int
    knowledge_base_path: str
    message: str


def _get_logger() -> logging.Logger:
    """Create the dedicated ingestion pipeline logger."""

    LOGS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    logger = logging.getLogger("ingestion_pipeline")
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


def _resolve_path(path: str | Path) -> Path:
    """Resolve a path relative to the project root when necessary."""

    resolved = Path(path)

    if not resolved.is_absolute():
        resolved = BASE_DIR / resolved

    return resolved.resolve()


def _prepare_active_knowledge_base() -> None:
    """Replace the previous active knowledge base with a clean directory."""

    if ACTIVE_KB_DIR.exists():
        logger.info(
            "Removing previous active knowledge base: %s",
            ACTIVE_KB_DIR,
        )
        shutil.rmtree(ACTIVE_KB_DIR)

    ACTIVE_KB_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


def ingest_brd(
    brd_path: str | Path,
) -> IngestionResult:
    """
    Ingest one BRD into the active knowledge base.

    Intended UI flow:
        uploaded BRD -> save file -> ingest_brd(path)

    This function does not execute any extraction queries or LLM calls.
    """

    logger.info("=" * 80)
    logger.info("INGESTION PIPELINE STARTED")
    logger.info("=" * 80)

    document_path = _resolve_path(brd_path)

    if not document_path.is_file():
        raise FileNotFoundError(
            f"BRD file not found: {document_path}"
        )

    if document_path.suffix.lower() not in {
        ".pdf",
        ".docx",
        ".doc",
        ".txt",
    }:
        raise ValueError(
            "Unsupported BRD format. "
            "Expected PDF, DOCX, DOC, or TXT."
        )

    logger.info(
        "BRD: %s",
        document_path,
    )

    logger.info(
        "Loading and splitting document..."
    )

    documents: List[Document] = load_and_split_document(
        str(document_path)
    )

    if not documents:
        raise RuntimeError(
            "No chunks were created from the uploaded BRD."
        )

    logger.info(
        "Document loaded successfully | chunks=%d",
        len(documents),
    )

    logger.info(
        "Loading embedding model..."
    )

    embeddings = get_embeddings()

    logger.info(
        "Embedding model loaded."
    )

    _prepare_active_knowledge_base()

    logger.info(
        "Creating active knowledge base..."
    )

    knowledge_base = KnowledgeBase(
        index_dir=str(ACTIVE_KB_DIR),
        embeddings=embeddings,
    )

    knowledge_base.add_documents(
        documents
    )

    logger.info(
        "Knowledge base created: %s",
        ACTIVE_KB_DIR,
    )

    logger.info("=" * 80)
    logger.info("INGESTION PIPELINE COMPLETED")
    logger.info("=" * 80)

    return IngestionResult(
        success=True,
        document_path=str(document_path),
        chunks_created=len(documents),
        knowledge_base_path=str(ACTIVE_KB_DIR),
        message="BRD ingested successfully and knowledge base is ready.",
    )


if __name__ == "__main__":
    default_brd = UPLOADS_DIR / "BRD_Inventory_Management_System.pdf"
    result = ingest_brd(default_brd)

    print()
    print("=" * 70)
    print("INGESTION COMPLETED")
    print("=" * 70)
    print(f"Document : {result.document_path}")
    print(f"Chunks   : {result.chunks_created}")
    print(f"KB       : {result.knowledge_base_path}")
    print(f"Message  : {result.message}")
