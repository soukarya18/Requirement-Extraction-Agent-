"""End-to-end BRD-only estimation generation pipeline."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from modules.embeddings import get_embeddings
from modules.knowledge_base import KnowledgeBase
from src.query_engine.query_executer import QueryExecutor

from estimation_generation.estimator import generate_estimate


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
    merged_results: str
    successful_queries: int
    failed_queries: int
    total_queries: int
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


def _build_workbook(
    *,
    brs_name: str,
    rows: list,
    conditions: list[str],
    overall_effort: object,
    qa_support: bool,
    output_path: Path,
) -> None:
    """Invoke the artifact-tool Excel builder with serializable estimate data."""
    runtime_root = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies"
    bundled_node = runtime_root / "node" / "bin" / "node.exe"
    node_executable = os.environ.get("NODE_EXECUTABLE") or (
        str(bundled_node) if bundled_node.is_file() else shutil.which("node")
    )
    if not node_executable:
        raise RuntimeError("Node.js is required to generate the Excel estimation report.")
    builder = Path(__file__).resolve().parent / "workbook_builder.cjs"
    payload = {
        "brs_name": brs_name,
        "qa_support": qa_support,
        "rows": [row.__dict__ for row in rows],
        "overall_effort": overall_effort.__dict__,
        "conditions": conditions,
    }
    with tempfile.TemporaryDirectory(prefix="brd_estimation_") as temp_dir:
        input_path = Path(temp_dir) / "estimate.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        environment = os.environ.copy()
        node_modules = environment.get("CODEX_NODE_MODULES") or str(
            runtime_root / "node" / "node_modules"
        )
        if node_modules:
            environment["NODE_PATH"] = node_modules
        try:
            subprocess.run(
                [node_executable, str(builder), str(input_path), str(output_path)],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Node.js is required to generate the Excel estimation report.") from exc
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(f"Excel estimation report generation failed: {details}") from exc


def generate_estimation(brs_name: str, qa_support: bool = False) -> EstimationGenerationResult:
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
    estimate = generate_estimate(
        executor.llm,
        extraction_answers,
        qa_support,
        diagnostics_dir=RESULTS_DIR,
    )
    output_dir = BASE_DIR / "output" / Path(brs_name).stem
    workbook_path = output_dir / "generated_estimation.xlsx"
    _build_workbook(
        brs_name=Path(brs_name).stem,
        rows=estimate.rows,
        conditions=estimate.conditions,
        overall_effort=estimate.overall_effort,
        qa_support=qa_support,
        output_path=workbook_path,
    )
    return EstimationGenerationResult(
        True,
        str(workbook_path),
        str(MERGED_RESULTS_PATH),
        successful,
        len(results) - successful,
        len(results),
        "BRD estimation generated successfully.",
    )
