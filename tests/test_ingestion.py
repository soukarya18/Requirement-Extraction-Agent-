from __future__ import annotations

import logging
import os
from typing import List

from langchain_core.documents import Document

from modules.answer_generator import generate_answer
from modules.document_loader import load_and_split_document
from modules.embeddings import get_embeddings
from modules.knowledge_base import KnowledgeBase


BRD_PATH = os.path.join(
    "data",
    "uploads",
    "BRD_Inventory_Management_System.pdf",
)

KB_PATH = os.path.join(
    "data",
    "knowledge_bases",
    "test_project",
)

LOG_PATH = os.path.join(
    "tests",
    "test_log.txt",
)


# Only questions where the previous Gemma result
# was incomplete, incorrect, or questionable.
QUESTIONS: List[str] = [
    (
        "What are all the business objectives of the system, "
        "including their KPIs where available?"
    ),
    (
        "What business rules are explicitly defined in the BRD?"
    ),
    (
        "Based only on the functional requirements and role information "
        "in the BRD, what user stories can be directly supported by "
        "the document?"
    ),
    (
        "Summarize the requirements information from the BRD that "
        "would be needed to create a Detailed Requirement Specification."
    ),
]


def create_logger() -> logging.Logger:
    """Create a dedicated logger for the test run."""

    logger = logging.getLogger("drs_rag_test")

    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    file_handler = logging.FileHandler(
        LOG_PATH,
        mode="w",
        encoding="utf-8",
    )

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s"
    )

    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    return logger


def test_document_loading() -> List[Document]:
    """Load and chunk the BRD."""

    documents = load_and_split_document(BRD_PATH)

    if not documents:
        raise RuntimeError(
            "No chunks were created from the BRD."
        )

    return documents


def test_knowledge_base(
    documents: List[Document],
) -> KnowledgeBase:
    """Build the FAISS knowledge base."""

    embeddings = get_embeddings()

    kb = KnowledgeBase(
        index_dir=KB_PATH,
        embeddings=embeddings,
    )

    kb.add_documents(documents)

    return kb


def test_question(
    kb: KnowledgeBase,
    question: str,
    logger: logging.Logger,
    question_number: int,
) -> None:
    """Retrieve chunks and generate an answer."""

    # ------------------------------------------------------------------
    # Console
    # ------------------------------------------------------------------

    print("\n" + "=" * 70)
    print(f"QUESTION {question_number}")
    print("=" * 70)
    print(question)

    # ------------------------------------------------------------------
    # Log question
    # ------------------------------------------------------------------

    logger.info("=" * 80)
    logger.info(
        "QUESTION %d",
        question_number,
    )
    logger.info("-" * 80)
    logger.info(question)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    retrieved_documents = kb.similarity_search(
        query=question,
        k=10,
    )

    logger.info("")
    logger.info("RETRIEVED CHUNKS: %d", len(retrieved_documents))
    logger.info("=" * 80)

    for index, document in enumerate(
        retrieved_documents,
        start=1,
    ):
        logger.info(
            "--- RETRIEVED CHUNK %d ---",
            index,
        )

        logger.info(
            "Metadata: %s",
            document.metadata,
        )

        logger.info(
            "Content:\n%s",
            document.page_content,
        )

        logger.info("=" * 80)

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------

    answer = generate_answer(
        question=question,
        documents=retrieved_documents,
    )

    # ------------------------------------------------------------------
    # Console
    # ------------------------------------------------------------------

    print("\nLLM GENERATED ANSWER")
    print("-" * 70)
    print(answer)

    # ------------------------------------------------------------------
    # Log answer
    # ------------------------------------------------------------------

    logger.info("LLM GENERATED ANSWER")
    logger.info("-" * 80)
    logger.info(answer)
    logger.info("")
    logger.info("")


def main() -> None:
    """Run the focused debugging test."""

    if not os.path.isfile(BRD_PATH):
        raise FileNotFoundError(
            f"BRD file not found: {BRD_PATH}"
        )

    logger = create_logger()

    documents = test_document_loading()

    logger.info(
        "BRD LOADED: %s chunks",
        len(documents),
    )

    kb = test_knowledge_base(documents)

    logger.info(
        "KNOWLEDGE BASE CREATED: %s",
        KB_PATH,
    )

    print("\n" + "=" * 70)
    print("FOCUSED DRS QUESTION TEST")
    print("=" * 70)

    logger.info("=" * 80)
    logger.info("FOCUSED DRS QUESTION TEST STARTED")
    logger.info("=" * 80)

    for question_number, question in enumerate(
        QUESTIONS,
        start=1,
    ):
        test_question(
            kb=kb,
            question=question,
            logger=logger,
            question_number=question_number,
        )

    logger.info("=" * 80)
    logger.info("TEST COMPLETED")
    logger.info("=" * 80)

    print("\n" + "=" * 70)
    print(f"Detailed retrieval log written to: {LOG_PATH}")
    print("=" * 70)


if __name__ == "__main__":
    main()