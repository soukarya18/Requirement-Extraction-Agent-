from __future__ import annotations

import os
from typing import List

from langchain_core.documents import Document

from modules.document_loader import load_and_split_document
from modules.video_processor import VideoProcessor
from modules.knowledge_base import KnowledgeBase


class IngestionService:
    """Route uploaded files to the appropriate processor."""

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        video_processor: VideoProcessor,
    ) -> None:
        self.knowledge_base = knowledge_base
        self.video_processor = video_processor

    def process_upload(
        self,
        path: str,
    ) -> int:
        """
        Process a single uploaded file and add it to the KB.

        Returns:
            Number of chunks added.
        """
        extension = os.path.splitext(path)[1].lower()

        if extension in {
            ".pdf",
            ".docx",
            ".txt",
        }:
            documents = load_and_split_document(path)

        elif extension == ".mp4":
            documents = self.video_processor.process(path)

        else:
            raise ValueError(
                f"Unsupported upload type: {extension}"
            )

        if not documents:
            raise ValueError(
                f"No usable content extracted from {path}"
            )

        self.knowledge_base.add_documents(
            documents,
        )

        return len(documents)