from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from modules.config import get_logger


logger = get_logger("knowledge_base")


DocStore = Dict[str, List[Dict[str, Any]]]


class KnowledgeBase:
    """Session-scoped FAISS knowledge base."""

    def __init__(
        self,
        index_dir: str,
        embeddings,
    ) -> None:
        self.index_dir = index_dir
        self.embeddings = embeddings

        self.vector_store: Optional[FAISS] = None
        self.doc_store: DocStore = {}

    @property
    def doc_store_path(self) -> str:
        """Return doc_store.json path."""
        return os.path.join(
            self.index_dir,
            "doc_store.json",
        )

    def _save_doc_store(self) -> None:
        """Persist the document metadata store."""
        os.makedirs(
            self.index_dir,
            exist_ok=True,
        )

        with open(
            self.doc_store_path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                self.doc_store,
                file,
                ensure_ascii=False,
                indent=2,
            )

    def _add_to_doc_store(
        self,
        documents: List[Document],
    ) -> None:
        """Add document chunks to the auxiliary document store."""
        for document in documents:
            metadata = document.metadata or {}

            source = metadata.get(
                "source",
                "unknown",
            )

            self.doc_store.setdefault(
                source,
                [],
            ).append(
                {
                    "content": document.page_content,
                    "metadata": metadata,
                }
            )

    def load(self) -> None:
        """Load an existing FAISS index if present."""
        index_faiss = os.path.join(
            self.index_dir,
            "index.faiss",
        )

        index_pkl = os.path.join(
            self.index_dir,
            "index.pkl",
        )

        if not (
            os.path.isfile(index_faiss)
            and os.path.isfile(index_pkl)
        ):
            return

        self.vector_store = FAISS.load_local(
            self.index_dir,
            self.embeddings,
            allow_dangerous_deserialization=True,
        )

        if os.path.isfile(self.doc_store_path):
            with open(
                self.doc_store_path,
                "r",
                encoding="utf-8",
            ) as file:
                self.doc_store = json.load(file)

        logger.info(
            "Loaded knowledge base from %s",
            self.index_dir,
        )

    def add_documents(
        self,
        documents: List[Document],
    ) -> None:
        """Embed and add new documents to the current KB."""
        if not documents:
            logger.warning(
                "No documents supplied to knowledge base."
            )
            return

        if self.vector_store is None:
            self.vector_store = FAISS.from_documents(
                documents,
                self.embeddings,
            )
        else:
            self.vector_store.add_documents(
                documents,
            )

        self._add_to_doc_store(documents)

        os.makedirs(
            self.index_dir,
            exist_ok=True,
        )

        self.vector_store.save_local(
            self.index_dir,
        )

        self._save_doc_store()

        logger.info(
            "Added %d chunks to knowledge base",
            len(documents),
        )

    def similarity_search(
        self,
        query: str,
        k: int = 5,
    ) -> List[Document]:
        """Retrieve semantically similar documents."""
        if self.vector_store is None:
            raise RuntimeError(
                "Knowledge base has not been initialized."
            )

        return self.vector_store.similarity_search(
            query,
            k=k,
        )

    def similarity_search_with_score(
    self,
    query: str,
    k: int = 3,
):
        """Retrieve documents with FAISS similarity scores."""

        if self.vector_store is None:
            raise RuntimeError(
                "Knowledge base has not been loaded."
            )

        return self.vector_store.similarity_search_with_score(
            query,
            k=k,
        )