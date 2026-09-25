from __future__ import annotations

import logging
import os


from dotenv import load_dotenv


load_dotenv()


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is not configured. "
        "Please set it in the .env file."
    )
# ─── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
KB_DIR = os.path.join(DATA_DIR, "knowledge_bases")


# ─── Chunking ─────────────────────────────────────────────────────────────────

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150


# ─── Embedding model ──────────────────────────────────────────────────────────

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"


# ─── Video transcription ──────────────────────────────────────────────────────

WHISPER_MODEL = "small"


def get_logger(name: str) -> logging.Logger:
    """Create and configure a module logger."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger