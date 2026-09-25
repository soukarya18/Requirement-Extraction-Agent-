"""Evidence-grounded estimation scoring and deterministic calculation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

FACTORS = (
    ("functional_complexity", "Functional complexity", 0.20),
    ("technical_complexity", "Technical complexity", 0.25),
    ("integration_impact", "Integration impact", 0.15),
    ("testing_effort", "Testing effort", 0.15),
    ("requirement_clarity", "Requirement clarity", 0.10),
    ("risk_dependency", "Risk and dependency", 0.15),
)


@dataclass(frozen=True)
class FactorScore:
    key: str
    label: str
    weight: float
    score: int
    justification: str
    evidence_observations: List[str]


def _extract_json(response_text: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*", "", response_text.strip(), flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Estimation scorer did not return a JSON object.")
        return json.loads(cleaned[start : end + 1])


def _normalise_scores(payload: Any) -> List[FactorScore]:
    if not isinstance(payload, dict) or not isinstance(payload.get("factors"), list):
        raise ValueError("Estimation scorer response must contain a 'factors' array.")
    expected = {key: (label, weight) for key, label, weight in FACTORS}
    values: Dict[str, FactorScore] = {}
    for item in payload["factors"]:
        if not isinstance(item, dict):
            raise ValueError("Each estimation factor must be an object.")
        key = item.get("factor")
        if key not in expected or key in values:
            raise ValueError("Estimation scorer returned an unexpected or duplicate factor.")
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            raise ValueError(f"{key} score must be an integer from 1 to 5.")
        justification, observations = item.get("justification"), item.get("evidence_observations")
        if not isinstance(justification, str) or not justification.strip():
            raise ValueError(f"{key} must include a justification.")
        if not isinstance(observations, list) or not all(isinstance(value, str) for value in observations):
            raise ValueError(f"{key} evidence_observations must be an array of strings.")
        label, weight = expected[key]
        values[key] = FactorScore(key, label, weight, score, justification.strip(), observations)
    if set(values) != set(expected):
        missing = ", ".join(sorted(set(expected) - set(values)))
        raise ValueError(f"Estimation scorer omitted required factors: {missing}.")
    return [values[key] for key, _, _ in FACTORS]


def calculate_weighted_score(factors: Iterable[FactorScore]) -> float:
    """Calculate the weighted score; this calculation is not delegated to the LLM."""
    return round(sum(factor.score * factor.weight for factor in factors), 2)


def score_requirements(llm: Any, extraction_answers: Dict[str, Any]) -> List[FactorScore]:
    from langchain_core.prompts import ChatPromptTemplate

    evidence = json.dumps(extraction_answers, ensure_ascii=False, indent=2)
    prompt = ChatPromptTemplate.from_template(
        """You are a software delivery estimation analyst. Use only the supplied BRD extraction evidence. Do not use outside knowledge or assume implementation details that the evidence does not state. Assign one integer score from 1 to 5 to each required factor, where 1 means minimal estimation effort or risk and 5 means substantial estimation effort or risk. For example requirement_clarity, score requirement clarity : 5 means the requirements and acceptance criteria are complete and clear, while 1 means they are incomplete or ambiguous and likely to cause rework. When evidence is incomplete, state that limitation and reflect the resulting uncertainty in requirement clarity or risk and dependency.

For functional_complexity, explicitly identify supported counts or absence of counts for business rules, workflows, screens/pages(screens means as per the requirements how many UI pages needs to be created), and APIs/integrations.
For technical_complexity, consider only explicit code(from the supported document try to understand if the requirements needs to be designed from scratch or to modify any existing codebase ), data, batch, API(backend API creation/modification), or integration changes.
For integration_impact, consider explicitly named internal or external dependencies. 
For testing_effort, consider explicit acceptance, validation, exception, regression, UAT, and automation impacts.
For requirement_clarity, assess completeness of the extracted requirements and acceptance criteria.
For risk_dependency, assess explicit dependencies, constraints, ambiguity, and missing information.

Return JSON only, containing exactly this field: {{"factors": [{{"factor": "functional_complexity", "score": 1, "justification": "Evidence-grounded explanation.", "evidence_observations": ["Concrete supporting observation."]}}]}}.
Return exactly these six factor values once each: functional_complexity, technical_complexity, integration_impact, testing_effort, requirement_clarity, risk_dependency.

BRD EXTRACTION EVIDENCE:
{evidence}"""
    ).partial(evidence=evidence)
    response = (prompt | llm).invoke({})
    return _normalise_scores(_extract_json(str(response.content)))
