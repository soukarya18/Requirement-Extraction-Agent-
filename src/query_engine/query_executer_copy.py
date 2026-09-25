from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from modules.knowledge_base import KnowledgeBase
from modules.llm import get_llm
import time

from src.query_engine.response_validator import validate_answer


QueryDefinition = Dict[str, Any]
QueryResult = Dict[str, Any]


logger = logging.getLogger("query_executor")

REQUEST_DELAY_SECONDS = 1.0
MAX_LLM_ATTEMPTS = 3
INITIAL_RETRY_DELAY_SECONDS = 2.0

class QueryExecutor:
    """
    Sequentially execute DRS extraction queries against an
    already-created knowledge base.

    Responsibilities:
        - Load extraction_queries.json
        - Execute queries sequentially
        - Retrieve top-k relevant chunks
        - Pass context to the LLM
        - Make dependency results available to dependent queries
        - Parse LLM JSON response
        - Save each result as Qxxx.json
    """

    def __init__(
        self,
        queries_path: str,
        knowledge_base: KnowledgeBase,
        run_dir: str,
        top_k: int = 3,
    ) -> None:
        self.queries_path = queries_path
        self.knowledge_base = knowledge_base
        self.run_dir = run_dir
        self.top_k = top_k

        self.results_dir =   run_dir

        os.makedirs(
            self.results_dir,
            exist_ok=True,
        )

        self.llm = get_llm()

        self.config = self._load_queries()

        self.queries: List[QueryDefinition] = self.config.get(
            "queries",
            []
        )

        self.global_rules: List[str] = self.config.get(
            "global_rules",
            []
        )

        self.completed_results: Dict[str, QueryResult] = {}

        logger.info(
            "Loaded %d extraction queries from %s",
            len(self.queries),
            self.queries_path,
        )

    # ------------------------------------------------------------------
    # Query configuration
    # ------------------------------------------------------------------

    def _load_queries(self) -> Dict[str, Any]:
        """Load extraction_queries.json."""

        if not os.path.isfile(self.queries_path):
            raise FileNotFoundError(
                f"Extraction query file not found: "
                f"{self.queries_path}"
            )

        with open(
            self.queries_path,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError(
                "extraction_queries.json must contain a JSON object."
            )

        if not isinstance(
            data.get("queries"),
            list,
        ):
            raise ValueError(
                "'queries' must be a list."
            )

        return data

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def _retrieve_context(
        self,
        question: str,
        query_id: str,
    ) -> List[Document]:
        """Retrieve top-k chunks and log exactly what was retrieved."""

        logger.info(
            "%s | RETRIEVAL START",
            query_id,
        )

        results = self.knowledge_base.similarity_search_with_score(
            query=question,
            k=self.top_k,
        )

        logger.info(
            "%s | RETRIEVED %d CHUNKS",
            query_id,
            len(results),
        )

        documents: List[Document] = []

        for rank, (document, score) in enumerate(
            results,
            start=1,
        ):
            documents.append(document)

            metadata = document.metadata or {}

            logger.info(
                "%s | CHUNK %d | score=%.6f",
                query_id,
                rank,
                float(score),
            )

            logger.info(
                "%s | CHUNK %d | source=%s",
                query_id,
                rank,
                metadata.get("source"),
            )

            logger.info(
                "%s | CHUNK %d | source_type=%s",
                query_id,
                rank,
                metadata.get("source_type"),
            )

            logger.info(
                "%s | CHUNK %d | chunk_index=%s",
                query_id,
                rank,
                metadata.get("chunk_index"),
            )

            if "page" in metadata:
                logger.info(
                    "%s | CHUNK %d | page=%s",
                    query_id,
                    rank,
                    metadata.get("page"),
                )

            if "start_time" in metadata:
                logger.info(
                    "%s | CHUNK %d | start_time=%s",
                    query_id,
                    rank,
                    metadata.get("start_time"),
                )

            if "end_time" in metadata:
                logger.info(
                    "%s | CHUNK %d | end_time=%s",
                    query_id,
                    rank,
                    metadata.get("end_time"),
                )

            logger.info(
                "%s | CHUNK %d | CONTENT START\n%s\nCONTENT END",
                query_id,
                rank,
                document.page_content,
            )

        logger.info(
            "%s | RETRIEVAL COMPLETE",
            query_id,
        )

        return documents

    def _build_context(
        self,
        documents: List[Document],
    ) -> str:
        """Convert retrieved documents into LLM context."""

        if not documents:
            return (
                "No relevant information was retrieved "
                "from the knowledge base."
            )

        context_parts: List[str] = []

        for index, document in enumerate(
            documents,
            start=1,
        ):
            metadata = document.metadata or {}

            context_parts.append(
                (
                    f"--- Context {index} ---\n"
                    f"Metadata: "
                    f"{json.dumps(metadata, ensure_ascii=False)}\n"
                    f"Content:\n"
                    f"{document.page_content}"
                )
            )

        return "\n\n".join(context_parts)

    # ------------------------------------------------------------------
    # Dependencies
    # ------------------------------------------------------------------

    def _get_dependency_results(
        self,
        query: QueryDefinition,
    ) -> Dict[str, Dict[str, Any]]:
        """Return compact dependency context for the current query.

        Only the dependency query ID, target, and answer are forwarded to the
        current LLM call. Raw LLM responses, errors, and any previously
        retrieved source chunks are intentionally excluded to reduce prompt
        size and prevent dependency context from growing unnecessarily.

        Failed or otherwise unavailable dependencies do not block execution of
        the current query; they are represented explicitly as unavailable.
        """

        dependency_ids = query.get(
            "depends_on",
            [],
        )

        dependency_results: Dict[str, Dict[str, Any]] = {}

        for dependency_id in dependency_ids:
            result = self.completed_results.get(dependency_id)

            if result is None:
                logger.warning(
                    "%s | dependency %s unavailable: result not found",
                    query["query_id"],
                    dependency_id,
                )
                dependency_results[dependency_id] = {
                    "query_id": dependency_id,
                    "target": None,
                    "answer": "[Dependency result unavailable]",
                }
                continue

            status = result.get("status")
            dependency_results[dependency_id] = {
                "query_id": dependency_id,
                "target": result.get("target"),
                "answer": (
                    result.get("answer")
                    if status == "success"
                    else "[Dependency result unavailable]"
                ),
            }

            if status != "success":
                logger.warning(
                    "%s | dependency %s unavailable: status=%s",
                    query["query_id"],
                    dependency_id,
                    status,
                )

        return dependency_results

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        query: QueryDefinition,
        context: str,
        dependency_results: Dict[str, Dict[str, Any]],
    ) -> ChatPromptTemplate:
        """Build the LLM prompt for one extraction query."""

        global_rules_text = "\n".join(
            f"- {rule}"
            for rule in self.global_rules
        )

        query_rules_text = "\n".join(
            f"- {rule}"
            for rule in query.get("rules", [])
        )

        response_schema = json.dumps(
            query.get("response_schema"),
            ensure_ascii=False,
            indent=2,
        )

        dependency_text = json.dumps(
            dependency_results,
            ensure_ascii=False,
            indent=2,
        )

        if not dependency_results:
            dependency_text = "No previous query results were provided."

        return  ChatPromptTemplate.from_template(
    """
You are an evidence-grounded business requirements analyst.

Answer ONE query using only:
1. CURRENT SOURCE EVIDENCE
2. PREVIOUS QUERY RESULTS, when provided.

CURRENT SOURCE EVIDENCE is the primary authority for the current query.
PREVIOUS QUERY RESULTS are compact outputs from earlier queries and may be
used as derived context, but they must not override conflicting current
source evidence.

GLOBAL RULES:
{global_rules}

QUERY RULES:
{query_rules}

QUERY ID:
{query_id}

TARGET:
{target}

QUESTION:
{question}

RESPONSE TYPE:
{response_type}

RESPONSE SCHEMA:
{response_schema}

PREVIOUS QUERY RESULTS:
{dependency_results}

CURRENT SOURCE EVIDENCE:
{context}

Rules:

1. Use only information explicitly supported by the supplied evidence.
2. Do not use outside knowledge, business assumptions, or typical system behavior.
3. Read all supplied context before answering.
4. Keep different categories separate. Do not substitute one category for another.
5. Do not infer actors, permissions, relationships, workflows, inputs, outputs,
   benefits, metrics, or implementation details unless explicitly supported.
6. A feature or requirement title does not imply additional behavior.
   Example: "Purchase Orders" does not imply create, edit, approve, fulfill,
   or cancel unless stated.
7. A role or permission does not prove that the role performs a requirement.
8. For generated artifacts such as epics, user stories, acceptance criteria,
   traceability, or recommendations, derive only what is supported by the
   supplied evidence. Do not invent missing details.
9. If a value is not supported, use null or an empty array when allowed by
   the response schema. Do not fill gaps with guesses.
10. Treat previous query results as derived context, not as permission to
    invent additional relationships.
11. When current source evidence conflicts with a previous query result,
    prefer the current source evidence.
12. Preserve source terminology, IDs, numbers, and measurable values.
13. Every source_reference must support the specific value being returned.
14. The response schema defines structure, not facts.

Before returning, check every field:
"Is this specific value supported by the supplied evidence?"
If not, remove it or use null/empty array as permitted.

Return valid JSON only.
Do not use Markdown or code fences.
Do not add fields outside the response schema.

Return ONLY the JSON response.
"""


        ).partial(
            global_rules=global_rules_text,
            query_rules=query_rules_text,
            query_id=query["query_id"],
            target=query["target"],
            question=query["question"],
            response_type=query["response_type"],
            response_schema=response_schema,
            dependency_results=dependency_text,
            context=context,
        )

    # ------------------------------------------------------------------
    # JSON parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(
        response_text: str,
    ) -> Any:
        """Parse JSON from the LLM response."""

        cleaned = response_text.strip()

        cleaned = re.sub(
            r"^```(?:json)?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned,
        )

        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)

        except json.JSONDecodeError:
            object_start = cleaned.find("{")
            array_start = cleaned.find("[")

            starts = [
                index
                for index in (
                    object_start,
                    array_start,
                )
                if index >= 0
            ]

            if not starts:
                raise ValueError(
                    "LLM response does not contain valid JSON."
                )

            start = min(starts)

            object_end = cleaned.rfind("}")
            array_end = cleaned.rfind("]")

            end = max(
                object_end,
                array_end,
            )

            if end < start:
                raise ValueError(
                    "Unable to locate JSON response."
                )

            return json.loads(
                cleaned[start : end + 1]
            )

    # ------------------------------------------------------------------
    # Execute one query
    # ------------------------------------------------------------------

    def _execute_single_query(
    self,
    query: QueryDefinition,
) -> QueryResult:
        """Execute one query from retrieval through validated LLM output."""

        query_id = query["query_id"]

        # ------------------------------------------------------------------
        # Retrieval
        # ------------------------------------------------------------------

        logger.info(
            "%s | retrieval started",
            query_id,
        )

        documents = self._retrieve_context(
            question=query["question"],
            query_id=query_id,
        )

        context = self._build_context(
            documents,
        )

        # ------------------------------------------------------------------
        # Dependencies
        # ------------------------------------------------------------------

        dependency_results = (
            self._get_dependency_results(
                query
            )
        )

        if dependency_results:
            logger.info(
                "%s | dependencies: %s",
                query_id,
                list(
                    dependency_results.keys()
                ),
            )

        # ------------------------------------------------------------------
        # LLM + validation retry loop
        # ------------------------------------------------------------------

        validation_feedback = ""

        for attempt in range(
            1,
            MAX_LLM_ATTEMPTS + 1,
        ):

            logger.info(
                "%s | LLM attempt %d/%d",
                query_id,
                attempt,
                MAX_LLM_ATTEMPTS,
            )

            prompt = self._build_prompt(
                query=query,
                context=context,
                dependency_results=dependency_results,
                # validation_feedback=validation_feedback,
            )

            # --------------------------------------------------------------
            # Rate limiting
            # --------------------------------------------------------------

            if attempt > 1:
                retry_delay = (
                    INITIAL_RETRY_DELAY_SECONDS
                    * (2 ** (attempt - 2))
                )

                logger.info(
                    "%s | retry delay %.1f seconds",
                    query_id,
                    retry_delay,
                )

                time.sleep(
                    retry_delay
                )

            elif REQUEST_DELAY_SECONDS > 0:
                time.sleep(
                    REQUEST_DELAY_SECONDS
                )

            # --------------------------------------------------------------
            # LLM call
            # --------------------------------------------------------------

            logger.info(
                "%s | LLM call started | attempt=%d",
                query_id,
                attempt,
            )

            try:
                response = (
                    prompt
                    | self.llm
                ).invoke({})

                response_text = str(
                    response.content
                )

                logger.info(
                    "%s | LLM response received | attempt=%d",
                    query_id,
                    attempt,
                )

            except Exception as exc:

                error_text = str(
                    exc
                )

                logger.error(
                    "%s | LLM call failed | attempt=%d | error=%s",
                    query_id,
                    attempt,
                    error_text,
                )

                # Retry API failures as well.
                if attempt < MAX_LLM_ATTEMPTS:
                    validation_feedback = (
                        "The previous model/API attempt failed. "
                        "Retry the same extraction query."
                    )

                    continue

                return {
                    "query_id": query_id,
                    "target": query["target"],
                    "question": query["question"],
                    "response_type": query["response_type"],
                    "status": "failed",
                    "answer": None,
                    "error": error_text,
                }

            # --------------------------------------------------------------
            # JSON parsing
            # --------------------------------------------------------------

            try:

                answer = self._extract_json(
                    response_text
                )

                logger.info(
                    "%s | JSON parsing successful | attempt=%d",
                    query_id,
                    attempt,
                )

            except Exception as exc:

                validation_feedback = (
                    "The previous response was not valid JSON.\n"
                    f"Parser error: {exc}\n"
                    "Return ONLY valid JSON matching the expected schema."
                )

                logger.error(
                    "%s | JSON parsing failed | attempt=%d | error=%s",
                    query_id,
                    attempt,
                    exc,
                )

                if attempt < MAX_LLM_ATTEMPTS:
                    continue

                return {
                    "query_id": query_id,
                    "target": query["target"],
                    "question": query["question"],
                    "response_type": query["response_type"],
                    "status": "failed",
                    "answer": None,
                    "error": str(exc),
                    "raw_llm_response": response_text,
                }

            # --------------------------------------------------------------
            # Pydantic validation
            # --------------------------------------------------------------

            try:

                validated_answer = validate_answer(
                    answer=answer,
                    response_type=query[
                        "response_type"
                    ],
                    response_schema=query[
                        "response_schema"
                    ],
                    query_id=query_id,
                )

                logger.info(
                    "%s | Pydantic validation successful | attempt=%d",
                    query_id,
                    attempt,
                )

                return {
                    "query_id": query_id,
                    "target": query["target"],
                    "question": query["question"],
                    "response_type": query["response_type"],
                    "status": "success",
                    "answer": validated_answer,
                }

            except Exception as exc:

                validation_feedback = (
                    "The previous response failed schema validation.\n"
                    f"Validation error: {exc}\n"
                    "Return a corrected JSON response that exactly matches "
                    "the expected response schema. Do not add fields."
                )

                logger.error(
                    "%s | Pydantic validation failed | attempt=%d | error=%s",
                    query_id,
                    attempt,
                    exc,
                )

                if attempt < MAX_LLM_ATTEMPTS:
                    continue

                return {
                    "query_id": query_id,
                    "target": query["target"],
                    "question": query["question"],
                    "response_type": query["response_type"],
                    "status": "failed",
                    "answer": None,
                    "error": str(exc),
                    "raw_llm_response": response_text,
                }

        raise RuntimeError(
            f"{query_id}: unexpected execution state."
        )
        # ------------------------------------------------------------------
    # Save result
    # ------------------------------------------------------------------

    def _save_result(
        self,
        query_id: str,
        result: QueryResult,
    ) -> str:
        """Save one query result."""

        path = os.path.join(
            self.results_dir,
            f"{query_id}.json",
        )

        with open(
            path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                result,
                file,
                ensure_ascii=False,
                indent=2,
            )

        return path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_all(self) -> Dict[str, QueryResult]:
        """Execute all queries sequentially."""

        total = len(self.queries)

        logger.info(
            "Starting sequential execution of %d queries",
            total,
        )

        for index, query in enumerate(
            self.queries,
            start=1,
        ):
            query_id = query.get(
                "query_id",
                "UNKNOWN",
            )

            target = query.get(
                "target",
                "unknown",
            )

            logger.info(
                "[%d/%d] %s START | target=%s",
                index,
                total,
                query_id,
                target,
            )

            print(
                f"[{index}/{total}] "
                f"{query_id} | {target}"
            )

            try:
                result = self._execute_single_query(
                    query,
                )

            except Exception as exc:
                logger.exception(
                    "%s | execution failed",
                    query_id,
                )

                result = {
                    "query_id": query_id,
                    "target": target,
                    "question": query.get(
                        "question",
                    ),
                    "response_type": query.get(
                        "response_type",
                    ),
                    "status": "failed",
                    "answer": None,
                    "error": str(exc),
                }

            self.completed_results[
                query_id
            ] = result

            result_path = self._save_result(
                query_id=query_id,
                result=result,
            )
            time.sleep(REQUEST_DELAY_SECONDS)

            logger.info(
                "[%d/%d] %s COMPLETE | status=%s | file=%s",
                index,
                total,
                query_id,
                result.get("status"),
                result_path,
            )

            print(
                f"[{index}/{total}] "
                f"{query_id} | "
                f"{result.get('status')}"
            )

        logger.info(
            "Sequential query execution completed: %d/%d",
            total,
            total,
        )

        print(
            f"\nCompleted {total}/{total} queries."
        )

        return self.completed_results