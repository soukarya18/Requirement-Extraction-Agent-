from __future__ import annotations

import os
from typing import List

from faster_whisper import WhisperModel
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from modules.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    WHISPER_MODEL,
    get_logger,
)


logger = get_logger("video_processor")


class VideoProcessor:
    """Local MP4 transcription and chunking."""

    def __init__(
        self,
        model_size: str = WHISPER_MODEL,
    ) -> None:
        self.model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
        )

    def transcribe(
        self,
        path: str,
    ) -> List[dict]:
        """Transcribe an MP4 file into timestamped segments."""
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"Video not found: {path}"
            )

        segments, _ = self.model.transcribe(
            path,
            beam_size=5,
        )

        result: List[dict] = []

        for segment in segments:
            text = segment.text.strip()

            if not text:
                continue

            result.append(
                {
                    "text": text,
                    "start": float(segment.start),
                    "end": float(segment.end),
                }
            )

        logger.info(
            "Transcribed %s -> %d segments",
            os.path.basename(path),
            len(result),
        )

        return result

    def segments_to_documents(
        self,
        segments: List[dict],
        source_name: str,
    ) -> List[Document]:
        """Convert transcript segments into chunked Documents."""

        documents: List[Document] = []

        buffer: List[str] = []
        buffer_start: float | None = None
        buffer_end: float | None = None
        buffer_length = 0
        chunk_index = 0

        for segment in segments:
            text = segment["text"]

            if buffer_start is None:
                buffer_start = segment["start"]

            buffer.append(text)
            buffer_end = segment["end"]
            buffer_length += len(text)

            if buffer_length >= CHUNK_SIZE:
                documents.append(
                    Document(
                        page_content="\n".join(buffer),
                        metadata={
                            "source": source_name,
                            "source_type": "video",
                            "chunk_index": chunk_index,
                            "start_time": buffer_start,
                            "end_time": buffer_end,
                        },
                    )
                )

                chunk_index += 1

                # Keep the final segment as overlap
                last_segment = buffer[-1]

                buffer = [last_segment]
                buffer_length = len(last_segment)

                buffer_start = segment["start"]

        if buffer:
            documents.append(
                Document(
                    page_content="\n".join(buffer),
                    metadata={
                        "source": source_name,
                        "source_type": "video",
                        "chunk_index": chunk_index,
                        "start_time": (
                            buffer_start
                            if buffer_start is not None
                            else 0.0
                        ),
                        "end_time": (
                            buffer_end
                            if buffer_end is not None
                            else 0.0
                        ),
                    },
                )
            )

        return documents

    def process(
        self,
        path: str,
    ) -> List[Document]:
        """Transcribe an MP4 and return chunked Documents."""
        source_name = os.path.basename(path)

        segments = self.transcribe(path)

        return self.segments_to_documents(
            segments=segments,
            source_name=source_name,
        )