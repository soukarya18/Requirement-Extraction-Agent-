"""End-to-end BRD-only estimation generation pipeline."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from modules.embeddings import get_embeddings
from modules.knowledge_base import KnowledgeBase
from src.query_engine.query_executer import QueryExecutor

from estimation_generation.document_builder import write_estimation_report
from estimation_generation.scoring import calculate_weighted_score, score_requirements


BASE_DIR = Path(__file__).resolve().parent.parent
ACTIVE_KB_DIR = BASE_DIR / "data" / "knowledge_bases" / "active"
QUERIES_PATH = Path(__file__).resolve().parent / "estimation_queries.json"
RESULTS_DIR = Path(__file__).resolve().parent / "query_results"
MERGED_RESULTS_PATH = RESULTS_DIR / "all_estimation_query_results.json"

LOGS_DIR =BASE_DIR/"logs"
LOG_FILE = LOGS_DIR / "estimation_generation_pipeline.log"
TOP_K = 5


@dataclass
class EstimationGenerationResult:
    success: bool
    generated_document: str
    generated_markdown: str
    merged_results: str
    successful_queries: int
    failed_queries: int
    total_queries: int
    final_complexity_score: float
    message: str


def _get_logger() -> logging.Logger:
    # LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True , exist_ok=True)
    logger = logging.getLogger("estimation_generation")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(handler)
    return logger


logger = _get_logger()


def _prepare_results_directory() -> None:
    if RESULTS_DIR.exists():
        for child in RESULTS_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _merge_results() -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for path in sorted(RESULTS_DIR.glob("EQ*.json")):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Unable to load %s: %s", path, exc)
            continue
        if isinstance(result, dict):
            merged[str(result.get("query_id", path.stem))] = result
    MERGED_RESULTS_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def generate_estimation(brs_name: str) -> EstimationGenerationResult:
    """Generate a BRD-only estimation report for the active knowledge base."""
    if not ACTIVE_KB_DIR.is_dir():
        raise FileNotFoundError("No active knowledge base found. Upload and process a BRD first.")
    if not brs_name or not brs_name.strip():
        raise ValueError("BRS name is required for estimation generation.")
    _prepare_results_directory()
    embeddings = get_embeddings()
    knowledge_base = KnowledgeBase(index_dir=str(ACTIVE_KB_DIR), embeddings=embeddings)
    knowledge_base.load()
    if knowledge_base.vector_store is None:
        raise RuntimeError("Failed to load the active knowledge base.")
    executor = QueryExecutor(queries_path=str(QUERIES_PATH), knowledge_base=knowledge_base, run_dir=str(RESULTS_DIR), top_k=TOP_K)
    results = executor.execute_all()
    successful = sum(result.get("status") == "success" for result in results.values())
    if successful != len(results):
        raise RuntimeError("Estimation cannot be scored because one or more BRD evidence queries failed.")
    merged = _merge_results()
    extraction_answers = {query_id: result["answer"] for query_id, result in merged.items()}
    factors = score_requirements(executor.llm, extraction_answers)
    final_score = calculate_weighted_score(factors)
    output_dir = BASE_DIR / "output" / Path(brs_name).stem
    docx_path, markdown_path = write_estimation_report(output_dir, Path(brs_name).stem, factors, final_score)
    return EstimationGenerationResult(True, str(docx_path), str(markdown_path), str(MERGED_RESULTS_PATH), successful, len(results) - successful, len(results), final_score, "BRD estimation generated successfully.")
