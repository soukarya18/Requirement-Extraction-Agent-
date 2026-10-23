"""LLM-assisted, BRD-grounded person-day estimation."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


PD_FIELDS = (
    "analysis_pd",
    "development_pd",
    "unit_testing_pd",
    "functional_testing_pd",
    "qa_deployment_pd",
    "qa_testing_pd",
    "qa_bugfixing_pd",
)

MAX_ESTIMATION_LLM_ATTEMPTS = 5
# The default completion limit used by the shared LLM is too small for a
# module-by-module estimate. A truncated response looks like malformed JSON.
ESTIMATION_MAX_TOKENS = 10000
logger = logging.getLogger("estimation_generation")
REQUIREMENT_ID_PATTERN = re.compile(r"\b(?:BR|FR|NFR|AC|RULE)[-_]?\d+\b", re.IGNORECASE)
COMBINED_SUBMODULE_PATTERN = re.compile(r"/|\s&\s|,|\s+and\s+", re.IGNORECASE)


@dataclass(frozen=True)
class EstimationRow:
    module: str
    submodule: str
    analysis_pd: float
    development_pd: float
    unit_testing_pd: float
    functional_testing_pd: float
    qa_deployment_pd: float | None
    qa_testing_pd: float | None
    qa_bugfixing_pd: float
    comments: str
    # Retained as an empty compatibility field; it is no longer a module-row
    # estimate and is rendered only in the overall effort summary.
    post_production_support_pd: None = None


@dataclass(frozen=True)
class OverallEffort:
    ppe_deployment_pd: float
    production_deployment_pd: float
    post_production_support_pd: float
    contingency_percentage: float
    contingency_effort_pd: float


@dataclass(frozen=True)
class GeneratedEstimate:
    rows: List[EstimationRow]
    conditions: List[str]
    overall_effort: OverallEffort

    def __iter__(self):
        """Preserve the existing rows, conditions unpacking contract."""
        yield self.rows
        yield self.conditions


def _extract_json(response_text: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*", "", response_text.strip(), flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Estimation model did not return a JSON object.")
        return json.loads(cleaned[start : end + 1])


def _pd(value: Any, field: str, *, required: bool = True) -> float | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{field} must be a non-negative number.")
    return round(float(value) * 2) / 2


def _normalise_estimate(payload: Any, qa_support: bool) -> tuple[List[EstimationRow], List[str]]:
    if not isinstance(payload, dict):
        raise ValueError("Estimation model response must be an object.")
    raw_rows = payload.get("estimation_rows")
    raw_conditions = payload.get("conditions")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Estimation model response must contain at least one estimation row.")
    if not isinstance(raw_conditions, list) or not all(isinstance(item, str) and item.strip() for item in raw_conditions):
        raise ValueError("Estimation model response must contain conditions as non-empty strings.")

    rows: List[EstimationRow] = []
    for index, item in enumerate(raw_rows, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Estimation row {index} must be an object.")
        module = item.get("module")
        submodule = item.get("submodule")
        comments = item.get("comments")
        if not isinstance(module, str) or not module.strip():
            raise ValueError(f"Estimation row {index} needs a module.")
        if not isinstance(submodule, str):
            raise ValueError(f"Estimation row {index} needs a submodule string.")
        if not isinstance(comments, str) or not comments.strip():
            raise ValueError(f"Estimation row {index} needs comments.")
        if submodule.strip() and COMBINED_SUBMODULE_PATTERN.search(submodule):
            raise ValueError(
                f"Estimation row {index} combines multiple submodules. "
                "Create a separate row for each submodule."
            )
        if REQUIREMENT_ID_PATTERN.search(comments):
            raise ValueError(
                f"Estimation row {index} comments must be plain-language and must not contain requirement IDs."
            )
        rows.append(
            EstimationRow(
                module=module.strip(),
                submodule=submodule.strip(),
                analysis_pd=_pd(item.get("analysis_pd"), "analysis_pd"),
                development_pd=_pd(item.get("development_pd"), "development_pd"),
                unit_testing_pd=_pd(item.get("unit_testing_pd"), "unit_testing_pd"),
                functional_testing_pd=_pd(item.get("functional_testing_pd"), "functional_testing_pd"),
                qa_deployment_pd=_pd(item.get("qa_deployment_pd"), "qa_deployment_pd", required=qa_support),
                qa_testing_pd=_pd(item.get("qa_testing_pd"), "qa_testing_pd", required=qa_support),
                qa_bugfixing_pd=_pd(item.get("qa_bugfixing_pd"), "qa_bugfixing_pd"),
                comments=comments.strip(),
            )
        )
    # Keep all child rows of a module together. The workbook builder uses this
    # ordering to merge the module cell vertically across its submodules.
    grouped_rows: Dict[str, List[EstimationRow]] = {}
    for row in rows:
        grouped_rows.setdefault(row.module.casefold(), []).append(row)
    ordered_rows = [row for group in grouped_rows.values() for row in group]
    return ordered_rows, [condition.strip() for condition in raw_conditions]


def _normalise_overall_effort(payload: Any, rows: List[EstimationRow]) -> OverallEffort:
    """Validate one-time delivery effort and calculate its contingency PD."""
    raw_overall = payload.get("overall_effort") if isinstance(payload, dict) else None
    if raw_overall is None:
        # Maintains compatibility with older callers while the prompt requires
        # this object for all newly generated estimation reports.
        raw_overall = {
            "ppe_deployment_pd": 0.0,
            "production_deployment_pd": 0.0,
            "post_production_support_pd": 0.0,
            "contingency_percentage": 10.0,
        }
    if not isinstance(raw_overall, dict):
        raise ValueError("Estimation model response must contain overall_effort as an object.")

    contingency_percentage = raw_overall.get("contingency_percentage")
    if (
        isinstance(contingency_percentage, bool)
        or not isinstance(contingency_percentage, (int, float))
        or not 5 <= float(contingency_percentage) <= 50
    ):
        raise ValueError("contingency_percentage must be a number from 5 to 50.")

    module_total = sum(
        row.analysis_pd
        + row.development_pd
        + row.unit_testing_pd
        + row.functional_testing_pd
        + (row.qa_deployment_pd or 0)
        + (row.qa_testing_pd or 0)
        + row.qa_bugfixing_pd
        for row in rows
    )
    ppe_deployment_pd = _pd(raw_overall.get("ppe_deployment_pd"), "ppe_deployment_pd") or 0.0
    production_deployment_pd = _pd(
        raw_overall.get("production_deployment_pd"), "production_deployment_pd"
    ) or 0.0
    post_production_support_pd = _pd(
        raw_overall.get("post_production_support_pd"), "post_production_support_pd"
    ) or 0.0
    contingency_percentage = round(float(contingency_percentage), 1)
    contingency_effort_pd = round(
        (module_total + ppe_deployment_pd + production_deployment_pd + post_production_support_pd)
        * contingency_percentage
        / 100
        * 2
    ) / 2
    return OverallEffort(
        ppe_deployment_pd=ppe_deployment_pd,
        production_deployment_pd=production_deployment_pd,
        post_production_support_pd=post_production_support_pd,
        contingency_percentage=contingency_percentage,
        contingency_effort_pd=contingency_effort_pd,
    )


def _save_invalid_response(
    response_text: str,
    attempt: int,
    diagnostics_dir: Path | None,
) -> Path | None:
    """Persist invalid model output so malformed JSON can be diagnosed."""
    if diagnostics_dir is None:
        return None
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / f"estimation_llm_invalid_attempt_{attempt}.txt"
    path.write_text(response_text, encoding="utf-8")
    return path


def _llm_with_estimation_output_limit(llm: Any) -> Any:
    """Request enough output space for the complete estimation JSON only."""
    bind = getattr(llm, "bind", None)
    if callable(bind):
        return bind(max_tokens=ESTIMATION_MAX_TOKENS)
    return llm


def generate_estimate(
    llm: Any,
    extraction_answers: Dict[str, Any],
    qa_support: bool,
    diagnostics_dir: str | Path | None = None,
) -> GeneratedEstimate:
    """Convert extracted BRD evidence into module-level person-day estimates."""
    from langchain_core.prompts import ChatPromptTemplate

    evidence = json.dumps(extraction_answers, ensure_ascii=False, indent=2)
    qa_instruction = (
        "QA support is included. Estimate qa_deployment_pd and qa_testing_pd."
        if qa_support
        else "QA support is not included. Return null for qa_deployment_pd and qa_testing_pd."
    )
    diagnostics_path = Path(diagnostics_dir) if diagnostics_dir else None
    prompt = ChatPromptTemplate.from_template(
        """You are a delivery estimator. Build a module-level effort estimate from the supplied BRD extraction evidence. Use professional judgement for a competent but inexperienced developer working on a normal business application. All values are person-days (PD), where one PD is one person working for one day. Use increments of 0.5 PD.

Create modules and submodules from the extracted business requirements, functional requirements, business rules, non-functional requirements, and acceptance criteria. Do not add features that are unsupported by the evidence. Create one row for each separately estimable capability or action, repeating the module name for every child row. List every row for the same module consecutively before moving to the next module. Do not combine multiple actions in one submodule row. A submodule name must never contain a slash, ampersand, comma-separated list, or the word "and". For example, instead of "Create/Edit/Submit Request", emit separate rows such as "Create request", "Edit saved request", and "Submit request". Instead of "Upload/Preview/Replace/Download", emit four rows. Use an empty submodule only when the BRD genuinely identifies no subdivision.

For each module/submodule row provide only analysis, development, unit testing, functional testing, and QA bug fixing effort. Do not include PPE deployment, production deployment, or post-production support in any module row. {qa_instruction}

Estimate one-time project-wide delivery effort separately in overall_effort. PPE deployment, production deployment, and post-production support are overall activities, not module-level activities. Select contingency_percentage using these ranges: 5-10 for well-defined low-risk work, 10-15 for a normal enterprise project, 15-20 for moderate uncertainty, and 20-30 or higher for high-risk or unclear requirements. Do not make contingency_percentage lower than 5 or higher than 50.

For every row, comments must explain why its Total PD is needed by naming the supported scope and effort drivers in plain business language. Keep comments to one concise sentence of at most 40 words. Never include BR, FR, NFR, AC, RULE, or any other requirement ID in comments. Do not cite or list source identifiers. Provide at most 8 concise conditions. Complete the entire JSON object, including its closing brackets; never stop partway through a row or condition.

{retry_instruction}

Return JSON only with exactly this structure:
{{
  "estimation_rows": [
    {{
      "module": "Module name",
      "submodule": "Submodule name or empty string",
      "analysis_pd": 0.5,
      "development_pd": 1.0,
      "unit_testing_pd": 0.5,
      "functional_testing_pd": 0.5,
      "qa_deployment_pd": 0.5,
      "qa_testing_pd": 1.0,
      "qa_bugfixing_pd": 0.5,
      "comments": "Brief, evidence-grounded explanation of why this row's Total PD is required."
    }}
  ],
  "overall_effort": {{
    "ppe_deployment_pd": 1.0,
    "production_deployment_pd": 1.0,
    "post_production_support_pd": 1.0,
    "contingency_percentage": 15.0
  }},
  "conditions": ["Condition or assumption that this estimate depends on."]
}}

Conditions must explain the information, dependencies, environments, approvals, integrations, test data, or other assumptions required for the estimate. State that estimates may vary when a listed condition is unmet or information changes.

BRD EXTRACTION EVIDENCE:
{evidence}"""
    ).partial(evidence=evidence, qa_instruction=qa_instruction)
    estimation_llm = _llm_with_estimation_output_limit(llm)

    last_error: Exception | None = None
    last_response_path: Path | None = None
    for attempt in range(1, MAX_ESTIMATION_LLM_ATTEMPTS + 1):
        response_text: str | None = None
        retry_instruction = ""
        if last_error is not None:
            retry_instruction = (
                "IMPORTANT: Your previous response could not be parsed or validated. "
                f"Error: {last_error}. Return a newly generated response as valid JSON only. "
                "Do not use Markdown, code fences, comments, trailing commas, or unescaped quotes in strings."
            )

        try:
            response = (prompt.partial(retry_instruction=retry_instruction) | estimation_llm).invoke({})
            response_text = str(response.content)
            payload = _extract_json(response_text)
            rows, conditions = _normalise_estimate(payload, qa_support)
            estimate = GeneratedEstimate(
                rows=rows,
                conditions=conditions,
                overall_effort=_normalise_overall_effort(payload, rows),
            )
            logger.info("Estimation response validated on attempt %d/%d", attempt, MAX_ESTIMATION_LLM_ATTEMPTS)
            return estimate
        except Exception as exc:
            last_error = exc
            if response_text is not None:
                last_response_path = _save_invalid_response(response_text, attempt, diagnostics_path)
            logger.warning(
                "Estimation response failed validation on attempt %d/%d: %s%s",
                attempt,
                MAX_ESTIMATION_LLM_ATTEMPTS,
                exc,
                f"; saved at {last_response_path}" if last_response_path else "",
            )

    detail = f" Last invalid response saved at: {last_response_path}." if last_response_path else ""
    raise RuntimeError(
        "The estimation model returned an invalid response after "
        f"{MAX_ESTIMATION_LLM_ATTEMPTS} attempts. Please try again.{detail}"
    ) from last_error
