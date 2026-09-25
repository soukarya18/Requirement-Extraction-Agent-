from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

# ---------------------------------------------------------------------------
# Make the project root importable.
# Place this script in the project root and run:
#     python test_chatbot_console.py
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from modules.embeddings import get_embeddings
from modules.knowledge_base import KnowledgeBase
from modules.llm import get_llm


# Existing active knowledge base created during BRD ingestion.
ACTIVE_KB_DIR = BASE_DIR / "data" / "knowledge_bases" / "active"

TOP_K = 5


def load_knowledge_base() -> KnowledgeBase:
    """Load the existing active FAISS knowledge base."""
    print("\n[1] Loading embedding model...")
    embeddings = get_embeddings()

    print(f"[2] Loading knowledge base: {ACTIVE_KB_DIR}")

    knowledge_base = KnowledgeBase(
        index_dir=str(ACTIVE_KB_DIR),
        embeddings=embeddings,
    )
    knowledge_base.load()

    if knowledge_base.vector_store is None:
        raise RuntimeError(
            f"Knowledge base is not available at: {ACTIVE_KB_DIR}\n"
            "Process a BRD first and make sure the active KB exists."
        )

    print("[OK] Knowledge base loaded.")
    return knowledge_base


def retrieve_chunks(
    knowledge_base: KnowledgeBase,
    question: str,
    top_k: int = TOP_K,
) -> List[Tuple[Document, float]]:
    """Retrieve and display the top-k chunks with FAISS scores."""
    print("\n" + "=" * 100)
    print("RETRIEVAL")
    print("=" * 100)
    print(f"Question : {question}")
    print(f"Top K    : {top_k}")

    results = knowledge_base.similarity_search_with_score(
        query=question,
        k=top_k,
    )

    print(f"\nRetrieved {len(results)} chunk(s).\n")

    for rank, (document, score) in enumerate(results, start=1):
        metadata = document.metadata or {}

        print("-" * 100)
        print(f"CHUNK {rank}")
        print(f"FAISS score : {float(score):.6f}")
        print(f"Source      : {metadata.get('source')}")
        print(f"Source type : {metadata.get('source_type')}")
        print(f"Chunk index : {metadata.get('chunk_index')}")
        print(f"Metadata    : {metadata}")
        print("\nCONTENT:")
        print(document.page_content)
        print("-" * 100)

    return results


def build_context(documents: List[Tuple[Document, float]]) -> str:
    """Build the exact evidence string sent to the LLM."""
    if not documents:
        return "No relevant evidence was retrieved from the knowledge base."

    parts: List[str] = []

    for rank, (document, score) in enumerate(documents, start=1):
        metadata = document.metadata or {}

        parts.append(
            f"--- Retrieved Source {rank} ---\n"
            f"FAISS score: {float(score):.6f}\n"
            f"Metadata: {metadata}\n"
            f"Content:\n{document.page_content}"
        )

    return "\n\n".join(parts)


def generate_answer(
    llm,
    question: str,
    context: str,
) -> str:
    """Send retrieved evidence and the question to the LLM."""
    prompt = ChatPromptTemplate.from_template(
        """
You are an evidence-grounded SDLC Assistant.

Answer the user's question using ONLY the supplied knowledge-base evidence.

Rules:
1. Do not use outside knowledge.
2. Do not make assumptions.
3. Preserve requirement IDs, names, numbers, and terminology exactly when supported.
4. Read all retrieved sources before answering.
5. If the supplied evidence does not support the answer, explicitly say so.
6. Do not claim information exists if it is not present in the supplied evidence.

USER QUESTION:
{question}

RETRIEVED KNOWLEDGE-BASE EVIDENCE:
{context}

Return a clear and concise answer.
"""
    ).partial(
        question=question,
        context=context,
    )

    response = (prompt | llm).invoke({})
    return str(response.content)


def main() -> None:
    """Run an interactive console chatbot test."""
    print("=" * 100)
    print("SDLC CHATBOT - CONSOLE RETRIEVAL TEST")
    print("=" * 100)
    print("This test uses the existing active BRD knowledge base.")
    print("For every question it will:")
    print("  1. Embed the query")
    print("  2. Retrieve top 3 chunks from FAISS")
    print("  3. Print the retrieved chunks")
    print("  4. Send those chunks + question to the LLM")
    print("  5. Print the generated answer")
    print("\nType 'exit' or 'quit' to stop.\n")

    knowledge_base = load_knowledge_base()

    print("[3] Loading LLM...")
    llm = get_llm()
    print("[OK] LLM loaded.")

    while True:
        try:
            question = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nExiting...")
            break

        if not question:
            continue

        if question.lower() in {"exit", "quit"}:
            print("Exiting...")
            break

        try:
            retrieved = retrieve_chunks(
                knowledge_base=knowledge_base,
                question=question,
                top_k=TOP_K,
            )

            context = build_context(retrieved)

            print("\n" + "=" * 100)
            print("LLM")
            print("=" * 100)
            print("Sending retrieved evidence to the LLM...")

            answer = generate_answer(
                llm=llm,
                question=question,
                context=context,
            )

            print("\nAssistant:")
            print(answer)

        except Exception as exc:
            print("\nERROR:")
            print(exc)


if __name__ == "__main__":
    main()
