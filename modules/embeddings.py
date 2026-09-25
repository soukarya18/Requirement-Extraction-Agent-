from __future__ import annotations

from langchain_huggingface import HuggingFaceEmbeddings

from modules.config import EMBEDDING_MODEL


def get_embeddings() -> HuggingFaceEmbeddings:
    """Create the local embedding model."""
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={
            "device": "cpu",
        },
        encode_kwargs={
            "normalize_embeddings": True,
        },
    )