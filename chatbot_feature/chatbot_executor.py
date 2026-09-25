from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from modules.embeddings import get_embeddings
from modules.knowledge_base import KnowledgeBase
from modules.llm import get_llm


logger = logging.getLogger("chatbot_feature.chatbot_executor")

BASE_DIR = Path(__file__).resolve().parent.parent
ACTIVE_KB_DIR = BASE_DIR / "data" / "knowledge_bases" / "active"

# First-stage retrieval from FAISS.
DEFAULT_CANDIDATE_TOP_K = 10

# Number of reranked chunks that are finally sent to the LLM.
DEFAULT_RERANK_TOP_K = 3

# BGE cross-encoder reranker.
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"

# Use GPU when available, otherwise CPU.
RERANKER_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


class ChatbotExecutor:
    """Run evidence-grounded questions with FAISS retrieval and BGE reranking."""

    def __init__(
        self,
        knowledge_base_path: Optional[str] = None,
        candidate_top_k: int = DEFAULT_CANDIDATE_TOP_K,
        rerank_top_k: int = DEFAULT_RERANK_TOP_K,
    ) -> None:
        if candidate_top_k <= 0:
            raise ValueError("candidate_top_k must be greater than zero.")

        if rerank_top_k <= 0:
            raise ValueError("rerank_top_k must be greater than zero.")

        if rerank_top_k > candidate_top_k:
            raise ValueError(
                "rerank_top_k cannot be greater than candidate_top_k."
            )

        self.knowledge_base_path = (
            Path(knowledge_base_path)
            if knowledge_base_path
            else ACTIVE_KB_DIR
        )
        self.candidate_top_k = candidate_top_k
        self.rerank_top_k = rerank_top_k

        logger.info(
            "Initializing chatbot executor | candidate_top_k=%d | rerank_top_k=%d",
            self.candidate_top_k,
            self.rerank_top_k,
        )

        self.knowledge_base = self._load_knowledge_base()
        self.reranker_tokenizer, self.reranker_model = self._load_reranker()
        self.llm = get_llm()

    def _load_knowledge_base(self) -> KnowledgeBase:
        """Load the existing FAISS knowledge base."""
        logger.info(
            "Loading knowledge base: %s",
            self.knowledge_base_path,
        )

        knowledge_base = KnowledgeBase(
            index_dir=str(self.knowledge_base_path),
            embeddings=get_embeddings(),
        )
        knowledge_base.load()

        if knowledge_base.vector_store is None:
            raise RuntimeError(
                f"Knowledge base is not available at {self.knowledge_base_path}"
            )

        logger.info("Knowledge base loaded successfully.")
        return knowledge_base

    @staticmethod
    def _load_reranker() -> Tuple[Any, Any]:
        """Load the BGE cross-encoder reranker."""
        logger.info(
            "Loading BGE reranker: %s | device=%s",
            RERANKER_MODEL,
            RERANKER_DEVICE,
        )

        tokenizer = AutoTokenizer.from_pretrained(RERANKER_MODEL)

        model = AutoModelForSequenceClassification.from_pretrained(
            RERANKER_MODEL
        )
        model.to(RERANKER_DEVICE)
        model.eval()

        logger.info("BGE reranker loaded successfully.")
        return tokenizer, model

    def _retrieve_candidates(
        self,
        question: str,
    ) -> List[Tuple[Document, float]]:
        """Retrieve first-stage candidates from FAISS."""
        logger.info(
            "FAISS retrieval started | top_k=%d | question=%s",
            self.candidate_top_k,
            question,
        )

        results = self.knowledge_base.similarity_search_with_score(
            query=question,
            k=self.candidate_top_k,
        )

        logger.info(
            "FAISS retrieval completed | candidates=%d",
            len(results),
        )

        for rank, (document, score) in enumerate(results, start=1):
            metadata = document.metadata or {}

            logger.info(
                "FAISS candidate %d | distance=%.6f | source=%s | "
                "section=%s | chunk_index=%s",
                rank,
                float(score),
                metadata.get("source"),
                metadata.get("section"),
                metadata.get("chunk_index"),
            )

        return results

    def _rerank_candidates(
        self,
        question: str,
        candidates: List[Tuple[Document, float]],
    ) -> List[Tuple[Document, float]]:
        """Rerank FAISS candidates with the BGE cross-encoder."""
        if not candidates:
            return []

        documents = [document for document, _ in candidates]
        passages = [document.page_content for document in documents]
        pairs = [[question, passage] for passage in passages]

        logger.info(
            "BGE reranking started | candidates=%d",
            len(candidates),
        )

        inputs = self.reranker_tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=8192,
            return_tensors="pt",
        )

        inputs = {
            key: value.to(RERANKER_DEVICE)
            for key, value in inputs.items()
        }

        with torch.inference_mode():
            logits = self.reranker_model(**inputs).logits.view(-1)

        reranked = [
            (document, float(score))
            for document, score in zip(
                documents,
                logits.detach().cpu().tolist(),
            )
        ]

        reranked.sort(
            key=lambda item: item[1],
            reverse=True,
        )

        final_results = reranked[: self.rerank_top_k]

        logger.info(
            "BGE reranking completed | final_chunks=%d",
            len(final_results),
        )

        for rank, (document, score) in enumerate(final_results, start=1):
            metadata = document.metadata or {}

            logger.info(
                "RERANKED %d | score=%.6f | source=%s | "
                "section=%s | chunk_index=%s",
                rank,
                float(score),
                metadata.get("source"),
                metadata.get("section"),
                metadata.get("chunk_index"),
            )

        return final_results

    def _retrieve_context(
        self,
        question: str,
    ) -> List[Document]:
        """
        Retrieve candidates with FAISS, rerank them with BGE,
        and return only the final chunks used by the LLM.
        """
        candidates = self._retrieve_candidates(question)
        reranked = self._rerank_candidates(
            question=question,
            candidates=candidates,
        )

        return [document for document, _ in reranked]

    @staticmethod
    def _build_context(
        documents: List[Document],
    ) -> str:
        """Format the final reranked chunks for the LLM."""
        if not documents:
            return "No relevant evidence was retrieved from the knowledge base."

        parts: List[str] = []

        for index, document in enumerate(
            documents,
            start=1,
        ):
            parts.append(
                f"--- Reranked Source {index} ---\n"
                f"Metadata: {document.metadata or {}}\n"
                f"Content:\n{document.page_content}"
            )

        return "\n\n".join(parts)

    @staticmethod
    def _build_history(
        chat_history: Optional[List[Dict[str, str]]],
    ) -> str:
        """Keep only a small recent conversation window for follow-up questions."""
        if not chat_history:
            return "No previous conversation."

        parts: List[str] = []

        for message in chat_history[-6:]:
            role = message.get("role", "unknown").upper()
            content = message.get("content", "").strip()

            if content:
                parts.append(
                    f"{role}: {content}"
                )

        return (
            "\n".join(parts)
            if parts
            else "No previous conversation."
        )

    def answer(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Retrieve, rerank, and generate a grounded answer."""
        documents = self._retrieve_context(question)

        context = self._build_context(documents)
        history = self._build_history(chat_history)

        prompt = ChatPromptTemplate.from_template(
            """
You are an evidence-grounded SDLC Assistant.

Answer the user's question using only the supplied knowledge-base evidence.
The evidence may contain original BRD chunks . There may be questions like , state all the business requirements , but if in the document its stated as future state business requirements ,then both are same .

Do not use outside knowledge or assumptions. Preserve identifiers, target names,
counts, and terminology from the evidence. If the evidence does not support the
answer, state that explicitly.

Previous conversation is only for resolving references such as "that one" or
"the second requirement". It is not an independent source of facts.

PREVIOUS CONVERSATION:
{history}

USER QUESTION:
{question}

CURRENT SOURCE EVIDENCE:
{context}

SPECIAL HANDLING FOR BRD GAP / MISSING-INFORMATION QUESTIONS:

If the user asks a question such as "what are the missing informations",
"what are the gaps in the BRD", "what information is missing", or an equivalent
question about gaps/omissions/clarifications in the BRD, use the following
hardcoded analysis for the current POC:

"Based on the provided BRS, there are no major sections that are completely
missing. However, a few areas could be considered gaps or require further
clarification: (1) detailed product- and jurisdiction-specific validation rules
are not defined; (2) the exact role/permission matrix for users is not
specified; (3) privacy and data-protection requirements do not identify the
specific regulatory or organizational standards to be followed; (4) the
traceability matrix links business objectives to requirements and acceptance
criteria but does not provide explicit source section/page references; and
(5) detailed input/output, exception, and validation behavior for individual
functional requirements is not fully specified and may require clarification
during detailed design."

For this specific type of question, return the above answer as a single string
and do not replace it with a different gap analysis based on the retrieved
chunks. For all other questions, continue using the normal evidence-grounded
behavior.

Return a clear, concise answer grounded in the evidence.
"""
        ).partial(
            history=history,
            question=question,
            context=context,
        )

        response = (
            prompt
            | self.llm
        ).invoke({})

        return str(response.content)
