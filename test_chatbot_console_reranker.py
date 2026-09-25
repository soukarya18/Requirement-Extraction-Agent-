from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Tuple

import torch
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from transformers import AutoModelForSequenceClassification, AutoTokenizer

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

# First-stage vector retrieval.
RETRIEVAL_TOP_K = 10

# Final number of chunks sent to the LLM after reranking.
RERANK_TOP_K = 3

# BAAI cross-encoder reranker.
# This is separate from the BGE embedding model used by FAISS.
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


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


def load_reranker() -> Tuple[Any, Any]:
    """Load the BGE cross-encoder reranker."""
    print(f"[3] Loading reranker: {RERANKER_MODEL}")
    print(f"    Device: {DEVICE}")

    tokenizer = AutoTokenizer.from_pretrained(RERANKER_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        RERANKER_MODEL
    )
    model.to(DEVICE)
    model.eval()

    print("[OK] Reranker loaded.")
    return tokenizer, model


def retrieve_candidates(
    knowledge_base: KnowledgeBase,
    question: str,
    top_k: int = RETRIEVAL_TOP_K,
) -> List[Tuple[Document, float]]:
    """Retrieve initial candidates from FAISS."""
    return knowledge_base.similarity_search_with_score(
        query=question,
        k=top_k,
    )


def rerank_chunks(
    question: str,
    candidates: List[Tuple[Document, float]],
    tokenizer: Any,
    model: Any,
    top_k: int = RERANK_TOP_K,
) -> List[Tuple[Document, float]]:
    """Rerank FAISS candidates using BGE cross-encoder relevance scores."""
    if not candidates:
        return []

    documents = [document for document, _ in candidates]
    passages = [document.page_content for document in documents]

    pairs = [[question, passage] for passage in passages]

    inputs = tokenizer(
        pairs,
        padding=True,
        truncation=True,
        max_length=8192,
        return_tensors="pt",
    )

    inputs = {
        key: value.to(DEVICE)
        for key, value in inputs.items()
    }

    with torch.inference_mode():
        logits = model(**inputs).logits.view(-1)

    reranked = [
        (document, float(score))
        for document, score in zip(documents, logits.tolist())
    ]

    reranked.sort(key=lambda item: item[1], reverse=True)

    return reranked[:top_k]


def print_initial_retrieval(
    question: str,
    candidates: List[Tuple[Document, float]],
) -> None:
    """Print the first-stage FAISS retrieval results."""
    print("\n" + "=" * 100)
    print("FAISS INITIAL RETRIEVAL")
    print("=" * 100)
    print(f"Question : {question}")
    print(f"Top K    : {len(candidates)}")

    for rank, (document, score) in enumerate(candidates, start=1):
        metadata = document.metadata or {}

        print("-" * 100)
        print(f"FAISS RANK {rank}")
        print(f"FAISS distance: {float(score):.6f}")
        print(f"Source        : {metadata.get('source')}")
        print(f"Source type   : {metadata.get('source_type')}")
        print(f"Section       : {metadata.get('section')}")
        print(f"Chunk index   : {metadata.get('chunk_index')}")
        print(f"Metadata      : {metadata}")
        print("\nCONTENT:")
        print(document.page_content)
        print("-" * 100)


def print_reranked_results(
    question: str,
    reranked: List[Tuple[Document, float]],
) -> None:
    """Print the final reranked results."""
    print("\n" + "=" * 100)
    print("BGE RERANKED RESULTS")
    print("=" * 100)
    print(f"Question : {question}")
    print(f"Top K    : {len(reranked)}")

    for rank, (document, score) in enumerate(reranked, start=1):
        metadata = document.metadata or {}

        print("-" * 100)
        print(f"RERANKED RANK {rank}")
        print(f"BGE score     : {float(score):.6f}")
        print(f"Source        : {metadata.get('source')}")
        print(f"Source type   : {metadata.get('source_type')}")
        print(f"Section       : {metadata.get('section')}")
        print(f"Chunk index   : {metadata.get('chunk_index')}")
        print(f"Metadata      : {metadata}")
        print("\nCONTENT:")
        print(document.page_content)
        print("-" * 100)


def build_context(
    documents: List[Tuple[Document, float]],
) -> str:
    """Build the exact evidence string sent to the LLM."""
    if not documents:
        return "No relevant evidence was retrieved from the knowledge base."

    parts: List[str] = []

    for rank, (document, score) in enumerate(documents, start=1):
        metadata = document.metadata or {}

        parts.append(
            f"--- Retrieved Source {rank} ---\n"
            f"BGE reranker score: {float(score):.6f}\n"
            f"Metadata: {metadata}\n"
            f"Content:\n{document.page_content}"
        )

    return "\n\n".join(parts)


def generate_answer(
    llm: Any,
    question: str,
    context: str,
) -> str:
    """Send reranked evidence and the question to the LLM."""
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

RERANKED KNOWLEDGE-BASE EVIDENCE:
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
    """Run an interactive console chatbot retrieval + reranking test."""
    print("=" * 100)
    print("SDLC CHATBOT - FAISS + BGE RERANKER CONSOLE TEST")
    print("=" * 100)
    print("Pipeline:")
    print("  1. Embed the query with the existing BGE embedding model")
    print(f"  2. Retrieve top {RETRIEVAL_TOP_K} candidates from FAISS")
    print(f"  3. Rerank those candidates with {RERANKER_MODEL}")
    print(f"  4. Keep the top {RERANK_TOP_K} reranked chunks")
    print("  5. Send ONLY those final chunks to the LLM")
    print("  6. Print the answer")
    print("\nType 'exit' or 'quit' to stop.\n")

    knowledge_base = load_knowledge_base()
    tokenizer, reranker = load_reranker()

    print("[4] Loading LLM...")
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
            candidates = retrieve_candidates(
                knowledge_base=knowledge_base,
                question=question,
                top_k=RETRIEVAL_TOP_K,
            )

            print_initial_retrieval(
                question=question,
                candidates=candidates,
            )

            reranked = rerank_chunks(
                question=question,
                candidates=candidates,
                tokenizer=tokenizer,
                model=reranker,
                top_k=RERANK_TOP_K,
            )

            print_reranked_results(
                question=question,
                reranked=reranked,
            )

            context = build_context(reranked)

            print("\n" + "=" * 100)
            print("LLM")
            print("=" * 100)
            print("Sending reranked evidence to the LLM...")

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
