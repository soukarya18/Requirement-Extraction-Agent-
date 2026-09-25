from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml.ns import qn


BASE_DIR = Path(__file__).resolve().parent.parent.parent

TEMPLATE_PATH = (
    BASE_DIR
    / "data"
    / "uploads"
    / "Jira_template.docx"
)

RESULTS_PATH = (
    BASE_DIR
    / "jira_query_results"
    / "all_jira_query_results.json"
)

OUTPUT_PATH = (
    BASE_DIR
    / "output"
    / "generated_jira_user_stories.docx"
)

logger = logging.getLogger("jira_assembler")


def _load_results() -> Dict[str, Dict[str, Any]]:
    """Load merged Jira query results."""

    if not RESULTS_PATH.is_file():
        raise FileNotFoundError(
            f"Jira query results not found: {RESULTS_PATH}"
        )

    with RESULTS_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        results = json.load(file)

    if not isinstance(results, dict):
        raise ValueError(
            "Merged Jira query results must be a JSON object."
        )

    return results


def _answer(
    results: Dict[str, Dict[str, Any]],
    query_id: str,
) -> Any:
    """Return a successful query answer or a safe empty value."""

    result = results.get(query_id)

    if not isinstance(result, dict):
        return []

    if result.get("status") != "success":
        return []

    return result.get("answer")


def _as_text(
    value: Any,
    default: str = "",
) -> str:
    """Render scalar/list values as compact text."""

    if value is None:
        return default

    if isinstance(value, list):
        return "; ".join(
            str(item)
            for item in value
            if item is not None
        )

    if isinstance(value, dict):
        return json.dumps(
            value,
            ensure_ascii=False,
        )

    return str(value)


def _join_field(
    items: Any,
    *candidate_keys: str,
) -> str:
    """
    Render a list of query-answer objects as readable text.

    Each JQ answer item is a dict such as
    {"business_objective": "...", "source_reference": [...]}. Passing that
    dict straight into `_as_text` dumps the *entire* object (including
    ids/source_reference) as raw JSON/repr text. This instead pulls out the
    first matching human-readable field per item and joins them, which is
    what the template actually wants to display.
    """

    if not isinstance(items, list):
        return ""

    rendered: List[str] = []

    for item in items:
        if isinstance(item, dict):
            value = None
            for key in candidate_keys:
                candidate = item.get(key)
                if candidate not in (None, "", []):
                    value = candidate
                    break
            if value is not None:
                rendered.append(_as_text(value))
        elif item is not None:
            rendered.append(str(item))

    return "; ".join(part for part in rendered if part)


def _first_non_empty(
    *values: Any,
) -> str:
    """Return the first non-empty rendered value."""

    for value in values:
        rendered = _as_text(value).strip()
        if rendered:
            return rendered

    return ""


def _set_paragraph_text(
    paragraph: Any,
    text: str,
) -> None:
    """Replace paragraph content while preserving the first run's formatting."""

    if not paragraph.runs:
        paragraph.add_run(text)
        return

    paragraph.runs[0].text = text

    for run in paragraph.runs[1:]:
        run.text = ""


def _set_cell_text(
    cell: Any,
    text: str,
) -> None:
    """Replace table-cell text safely."""

    paragraphs = cell.paragraphs

    if not paragraphs:
        cell.text = text
        return

    _set_paragraph_text(
        paragraphs[0],
        text,
    )

    for paragraph in paragraphs[1:]:
        _set_paragraph_text(
            paragraph,
            "",
        )


def _replace_labeled_paragraph(
    document: Document,
    label: str,
    value: Any,
    default: str = "",
) -> bool:
    """Replace the value portion of 'Label: value' paragraphs."""

    rendered = _as_text(
        value,
        default=default,
    )

    prefix = f"{label}:"

    for paragraph in document.paragraphs:
        stripped = paragraph.text.strip()

        if stripped.startswith(prefix):
            _set_paragraph_text(
                paragraph,
                f"{label}: {rendered}",
            )
            return True

    return False


def _find_paragraph_index(
    document: Document,
    text: str,
) -> Optional[int]:
    """Find an exact paragraph text index."""

    for index, paragraph in enumerate(
        document.paragraphs
    ):
        if paragraph.text.strip() == text:
            return index

    return None


def _clone_element(
    element: Any,
) -> Any:
    """Deep-clone a DOCX XML body element."""

    return copy.deepcopy(element)


def _body_children(
    document: Document,
) -> List[Any]:
    """Return top-level body children."""

    return list(
        document._body._element.iterchildren()
    )


def _body_paragraph_text(
    document: Document,
) -> List[str]:
    """Return paragraph text from direct body children only."""

    values: List[str] = []

    for child in _body_children(document):
        if child.tag == qn("w:p"):
            text = "".join(
                node.text or ""
                for node in child.iter(qn("w:t"))
            )
            values.append(text.strip())

    return values


def _find_body_heading_index(
    document: Document,
    exact_text: str,
) -> Optional[int]:
    """Find a direct body child index for a paragraph with exact text."""

    for index, child in enumerate(
        _body_children(document)
    ):
        if child.tag != qn("w:p"):
            continue

        text = "".join(
            node.text or ""
            for node in child.iter(qn("w:t"))
        ).strip()

        if text == exact_text:
            return index

    return None


def _insert_body_element_after(
    document: Document,
    reference_element: Any,
    element: Any,
) -> Any:
    """Insert a cloned element after a reference element."""

    reference_element.addnext(element)
    return element


def _remove_body_range(
    document: Document,
    start_index: int,
    end_index: int,
) -> None:
    """Remove body children in [start_index, end_index)."""

    children = _body_children(document)

    for element in children[
        start_index:end_index
    ]:
        document._body._element.remove(
            element
        )


def _build_epic_values(
    epic: Dict[str, Any],
) -> Dict[str, str]:
    """Map a generated epic object to template fields."""

    return {
        "Issue Type": "Epic",
        "Project": "To be configured",
        "Epic Key": "To be created by Jira",
        "Epic Name": _first_non_empty(
            epic.get("epic_name"),
            "Untitled Epic",
        ),
        "Summary": _first_non_empty(
            epic.get("summary"),
            epic.get("epic_name"),
            "Not explicitly provided",
        ),
        "Business Objective": _first_non_empty(
            epic.get("business_objectives"),
            "Not explicitly provided",
        ),
        "Business Problem / Opportunity": _first_non_empty(
            epic.get(
                "business_problem_or_opportunity"
            ),
            "Not explicitly provided",
        ),
        "Epic Hypothesis / Benefit": _first_non_empty(
            epic.get("hypothesis_or_benefit"),
            "Not explicitly provided",
        ),
        "In Scope": _first_non_empty(
            epic.get("in_scope"),
            "Not explicitly provided",
        ),
        "Out of Scope": _first_non_empty(
            epic.get("out_of_scope"),
            "Not explicitly provided",
        ),
        "Description": _first_non_empty(
            epic.get("description"),
            "Not explicitly provided",
        ),
        "Personas / Stakeholders": _first_non_empty(
            epic.get("personas_or_stakeholders"),
            "Not explicitly provided",
        ),
        "Success Measures": _first_non_empty(
            epic.get("success_measures"),
            "Not explicitly provided",
        ),
        "Dependencies": _first_non_empty(
            epic.get("dependencies"),
            "Not explicitly provided",
        ),
        "Risks / Assumptions": _first_non_empty(
            epic.get("risks_or_assumptions"),
            "Not explicitly provided",
        ),
        "Priority": _first_non_empty(
            epic.get("priority"),
            "To be planned",
        ),
        "Target Release / Fix Version": _first_non_empty(
            epic.get("target_release"),
            "To be planned",
        ),
        "Labels / Components": _first_non_empty(
            epic.get("labels_or_components"),
            "To be configured",
        ),
        "Source References": _first_non_empty(
            epic.get("source_references"),
            "Not explicitly provided",
        ),
        "Definition of Done": (
            "Epic capabilities delivered, acceptance criteria satisfied, "
            "traceability maintained, testing completed, and authorized "
            "reviewers accept the release."
        ),
    }


def _populate_epic_table(
    table: Any,
    epic: Dict[str, Any],
) -> None:
    """Populate the epic acceptance criteria table."""

    criteria = epic.get(
        "acceptance_criteria",
        [],
    )

    # Header exists in the template.
    if len(table.rows) > 1:
        for row in table.rows[
            1:
        ]:
            _set_cell_text(
                row.cells[0],
                "",
            )

    for row in list(
        table.rows[
            1:
        ]
    ):
        table._tbl.remove(
            row._tr
        )

    if not isinstance(
        criteria,
        list,
    ):
        criteria = []

    for item in criteria:
        if not isinstance(
            item,
            dict,
        ):
            continue

        cells = table.add_row().cells

        values = [
            item.get("ac_id"),
            item.get("given"),
            item.get("when"),
            item.get("then"),
            item.get("evidence"),
        ]

        for cell, value in zip(
            cells,
            values,
        ):
            _set_cell_text(
                cell,
                _as_text(
                    value,
                    default="Not explicitly provided",
                ),
            )


def _populate_epic_block(
    table: Any,
    epic: Dict[str, Any],
) -> None:
    """Populate the first epic template table when fields are tabular."""

    # Current Epic template uses paragraphs for fields, so this function
    # intentionally remains a no-op for future template variants.
    _ = table
    _ = epic


def _replace_epic_paragraphs(
    document: Document,
    values: Dict[str, str],
) -> None:
    """Replace the epic field paragraphs in-place."""

    for label, value in values.items():
        _replace_labeled_paragraph(
            document,
            label,
            value,
        )


def _populate_story_table(
    table: Any,
    story: Dict[str, Any],
    epic_name: str,
) -> None:
    """Populate the two-column Jira story field table."""

    values = {
        "Issue Type": "Story",
        "Summary": _first_non_empty(
            story.get("story_title"),
            story.get("story_title"),
            "Untitled Story",
        ),
        "Epic Link / Parent": _first_non_empty(
            story.get("epic_name"),
            epic_name,
            "Not explicitly provided",
        ),
        "Story ID": _first_non_empty(
            story.get("story_id"),
            "Not explicitly provided",
        ),
        "Persona": _first_non_empty(
            story.get("persona"),
            story.get("role"),
            "Not explicitly provided",
        ),
        "User Story": _first_non_empty(
            story.get("user_story"),
            "Not explicitly provided",
        ),
        "Description": _first_non_empty(
            story.get("description"),
            "Not explicitly provided",
        ),
        "Business Objective": _first_non_empty(
            story.get("business_objective"),
            "Not explicitly provided",
        ),
        "Source Requirement": _first_non_empty(
            story.get("source_requirement"),
            story.get("linked_fr_ids"),
            "Not explicitly provided",
        ),
        "Source Reference": _first_non_empty(
            story.get("source_reference"),
            "Not explicitly provided",
        ),
        "Priority": _first_non_empty(
            story.get("priority"),
            "To be planned",
        ),
        "Story Points": _first_non_empty(
            story.get("story_points"),
            "To be estimated",
        ),
        "Sprint / Fix Version": _first_non_empty(
            story.get("sprint_or_fix_version"),
            "To be planned",
        ),
        "Component / Labels": _first_non_empty(
            story.get("component_or_labels"),
            "To be configured",
        ),
        "Assignee": _first_non_empty(
            story.get("assignee"),
            "To be assigned",
        ),
        "Dependencies": _first_non_empty(
            story.get("dependencies"),
            "Not explicitly provided",
        ),
        "Attachments / UX Reference": _first_non_empty(
            story.get("attachments_or_ux_reference"),
            "Not provided",
        ),
        "Clarification Status": _first_non_empty(
            story.get("clarification_status"),
            "Human review required",
        ),
        "Status": _first_non_empty(
            story.get("status"),
            "Draft",
        ),
    }

    # Map rows using the first column label.
    for row in table.rows:
        if len(row.cells) < 2:
            continue

        field = row.cells[0].text.strip()

        if field in values:
            _set_cell_text(
                row.cells[1],
                values[field],
            )


def _append_story_detail_paragraphs(
    document: Document,
    details: Dict[str, Any],
) -> None:
    """Populate story-detail paragraphs in the existing template."""

    mappings = {
        "Preconditions": details.get(
            "preconditions"
        ),
        "Primary flow": details.get(
            "primary_flow"
        ),
        "Alternate flow": details.get(
            "alternate_flow"
        ),
        "Exception scenarios": details.get(
            "exception_scenarios"
        ),
        "Business rules": details.get(
            "business_rules"
        ),
        "Data requirements": details.get(
            "data_requirements"
        ),
        "Security / compliance considerations": details.get(
            "security_or_compliance_considerations"
        ),
        "Non-functional considerations": details.get(
            "non_functional_considerations"
        ),
        "Open questions": details.get(
            "open_questions"
        ),
    }

    for label, value in mappings.items():
        fallback = "Not explicitly provided"
        _replace_labeled_paragraph(
            document,
            label,
            value,
            default=fallback,
        )


def _populate_story_acceptance_table(
    table: Any,
    criteria: List[Dict[str, Any]],
    story_id: str,
) -> None:
    """Populate the six-column story acceptance criteria table."""

    # Remove example rows.
    for row in list(
        table.rows[
            1:
        ]
    ):
        table._tbl.remove(
            row._tr
        )

    for criterion in criteria:
        if not isinstance(
            criterion,
            dict,
        ):
            continue

        if (
            criterion.get("story_id")
            and str(
                criterion.get("story_id")
            )
            != str(story_id)
        ):
            continue

        row = table.add_row()

        values = [
            criterion.get("ac_id"),
            criterion.get("scenario"),
            criterion.get("given"),
            criterion.get("when"),
            criterion.get("then"),
            criterion.get("priority"),
        ]

        for cell, value in zip(
            row.cells,
            values,
        ):
            _set_cell_text(
                cell,
                _as_text(
                    value,
                    default="Not explicitly provided",
                ),
            )


def _find_tables(
    document: Document,
) -> List[Any]:
    """Return all document tables."""

    return list(
        document.tables
    )


def _remove_section_by_heading(
    document: Document,
    heading: str,
) -> None:
    """Remove a section starting at an exact heading through the next H-style heading."""

    body = document._body._element
    children = _body_children(document)

    start = None

    for index, child in enumerate(
        children
    ):
        if child.tag != qn("w:p"):
            continue

        text = "".join(
            node.text or ""
            for node in child.iter(qn("w:t"))
        ).strip()

        if text == heading:
            start = index
            break

    if start is None:
        return

    end = len(children)

    for index in range(
        start + 1,
        len(children),
    ):
        child = children[index]

        if child.tag != qn("w:p"):
            continue

        paragraph_text = "".join(
            node.text or ""
            for node in child.iter(qn("w:t"))
        ).strip()

        if re.match(
            r"^[A-Z]\.\s",
            paragraph_text,
        ):
            end = index
            break

    for child in children[
        start:end
    ]:
        body.remove(child)


def _clean_template_examples(
    document: Document,
) -> None:
    """
    Remove example-only sections that should not become project facts.

    The generated artefact is intended to contain actual Jira Epics and User
    Stories, not the example Bug template or example traceability row.
    """

    _remove_section_by_heading(
        document,
        "C. Jira Bug Template",
    )

    _remove_section_by_heading(
        document,
        "D. Example Traceability Mapping",
    )


def _insert_generated_story_block(
    document: Document,
    story: Dict[str, Any],
    details: Dict[str, Any],
    criteria: List[Dict[str, Any]],
    epic_name: str,
) -> None:
    """
    Reuse the existing story table and detail/criteria structure.

    The first story is populated in the template's existing location.
    Additional stories are appended as repeated, structured story blocks.
    """

    tables = _find_tables(document)

    story_tables = [
        table
        for table in tables
        if len(table.columns) == 2
        and any(
            cell.text.strip() == "Story ID"
            for cell in table.columns[0].cells
        )
    ]

    if not story_tables:
        raise RuntimeError(
            "Jira User Story table not found in template."
        )

    story_table = story_tables[0]

    _populate_story_table(
        story_table,
        story,
        epic_name,
    )

    _append_story_detail_paragraphs(
        document,
        details,
    )

    criteria_tables = [
        table
        for table in _find_tables(document)
        if len(table.columns) == 6
        and table.rows
        and table.rows[0].cells[0].text.strip()
        == "AC ID"
    ]

    if criteria_tables:
        _populate_story_acceptance_table(
            criteria_tables[-1],
            criteria,
            str(
                story.get(
                    "story_id",
                    "",
                )
            ),
        )


def generate_jira_document(
    output_dir: Optional[Path | str] = None,
) -> str:
    """
    Generate the Jira Epic and User Story document from the current
    JQ001-JQ041 query-result schema.

    Epic data is assembled from JQ001-JQ018. User-story data from JQ019-JQ032
    is merged by source_requirement_id so each functional requirement becomes
    one coherent story. Queries that failed or returned no answer are rendered
    as missing information rather than preventing the rest of the document
    from being generated.
    """

    output_directory = (
        Path(output_dir)
        if output_dir is not None
        else OUTPUT_PATH.parent
    )
    output_path = output_directory / "generated_jira_user_stories.docx"

    logger.info("Jira assembly started")
    logger.info("Template: %s", TEMPLATE_PATH)
    logger.info("Results: %s", RESULTS_PATH)
    logger.info("Output: %s", output_path)

    if not TEMPLATE_PATH.is_file():
        raise FileNotFoundError(
            f"Jira template not found: {TEMPLATE_PATH}"
        )

    results = _load_results()

    # ------------------------------------------------------------------
    # Epic data: JQ001-JQ018
    # ------------------------------------------------------------------
    epic_name_answer = _answer(results, "JQ001")
    epic_summary_answer = _answer(results, "JQ002")
    business_objectives_answer = _answer(results, "JQ003")
    business_problem_answer = _answer(results, "JQ004")
    epic_benefit_answer = _answer(results, "JQ005")
    in_scope_answer = _answer(results, "JQ006")
    out_of_scope_answer = _answer(results, "JQ007")
    epic_description_answer = _answer(results, "JQ008")
    stakeholders_answer = _answer(results, "JQ009")
    success_measures_answer = _answer(results, "JQ010")
    dependencies_answer = _answer(results, "JQ011")
    risks_answer = _answer(results, "JQ012")
    assumptions_answer = _answer(results, "JQ013")
    epic_priority_answer = _answer(results, "JQ014")
    epic_release_answer = _answer(results, "JQ015")
    epic_labels_answer = _answer(results, "JQ016")
    source_references_answer = _answer(results, "JQ017")
    epic_acceptance_answer = _answer(results, "JQ018")

    epic_name = (
        epic_name_answer.get("epic_name", "")
        if isinstance(epic_name_answer, dict)
        else ""
    )

    epic_summary = (
        epic_summary_answer.get("summary", "")
        if isinstance(epic_summary_answer, dict)
        else ""
    )

    business_problem = (
        business_problem_answer.get(
            "business_problem_or_opportunity",
            "",
        )
        if isinstance(business_problem_answer, dict)
        else ""
    )

    epic_benefit = (
        epic_benefit_answer.get(
            "hypothesis_or_benefit",
            "",
        )
        if isinstance(epic_benefit_answer, dict)
        else ""
    )

    in_scope = (
        in_scope_answer.get("in_scope", [])
        if isinstance(in_scope_answer, dict)
        else []
    )

    out_of_scope = (
        out_of_scope_answer.get("out_of_scope", [])
        if isinstance(out_of_scope_answer, dict)
        else []
    )

    epic_description = (
        epic_description_answer.get("description", "")
        if isinstance(epic_description_answer, dict)
        else ""
    )

    epic_priority = (
        epic_priority_answer.get("priority", "")
        if isinstance(epic_priority_answer, dict)
        else ""
    )

    epic_release = (
        epic_release_answer.get("target_release", "")
        if isinstance(epic_release_answer, dict)
        else ""
    )

    epic_labels = (
        epic_labels_answer.get("labels_or_components", "")
        if isinstance(epic_labels_answer, dict)
        else ""
    )

    epic_source_references: Any = source_references_answer
    if isinstance(epic_name_answer, dict) and not epic_source_references:
        epic_source_references = epic_name_answer.get(
            "source_reference",
            [],
        )

    # These JQ answers arrive as lists of objects, e.g.
    # [{"business_objective": "...", "source_reference": [...]}, ...].
    # Pull out just the human-readable field per item rather than
    # rendering the whole object (which used to dump raw JSON/dict repr
    # text straight into the document).
    business_objectives_text = _join_field(
        business_objectives_answer,
        "business_objective",
    )
    stakeholders_text = "; ".join(
        part
        for part in (
            " - ".join(
                piece
                for piece in (
                    _as_text(item.get("persona_or_stakeholder")),
                    _as_text(item.get("role_or_interest")),
                )
                if piece
            )
            for item in stakeholders_answer
            if isinstance(item, dict)
        )
        if part
    ) if isinstance(stakeholders_answer, list) else ""
    success_measures_text = _join_field(
        success_measures_answer,
        "measure",
    )
    dependencies_text = _join_field(
        dependencies_answer,
        "dependency",
    )
    risks_text = _join_field(
        risks_answer,
        "risk",
    )
    assumptions_text = _join_field(
        assumptions_answer,
        "assumption",
    )

    risks_or_assumptions_parts = []
    if risks_text:
        risks_or_assumptions_parts.append(f"Risks: {risks_text}")
    if assumptions_text:
        risks_or_assumptions_parts.append(
            f"Assumptions: {assumptions_text}"
        )
    risks_or_assumptions_text = " | ".join(risks_or_assumptions_parts)

    epic: Dict[str, Any] = {
        "epic_id": "EPIC-001",
        "epic_name": epic_name,
        "summary": epic_summary,
        "business_objectives": business_objectives_text,
        "business_problem_or_opportunity": business_problem,
        "hypothesis_or_benefit": epic_benefit,
        "in_scope": in_scope,
        "out_of_scope": out_of_scope,
        "description": epic_description,
        "personas_or_stakeholders": stakeholders_text,
        "success_measures": success_measures_text,
        "dependencies": dependencies_text,
        "risks_or_assumptions": risks_or_assumptions_text,
        "priority": epic_priority,
        "target_release": epic_release,
        "labels_or_components": epic_labels,
        "source_references": epic_source_references,
        "acceptance_criteria": (
            epic_acceptance_answer
            if isinstance(epic_acceptance_answer, list)
            else []
        ),
    }

    # ------------------------------------------------------------------
    # User stories: merge JQ019-JQ032 by source_requirement_id.
    # ------------------------------------------------------------------
    story_queries = {
        "story_core": "JQ019",
        "story_persona": "JQ020",
        "story_description": "JQ021",
        "story_priority": "JQ022",
        "story_points": "JQ023",
        "story_release": "JQ024",
        "story_labels_components": "JQ025",
        "story_assignee": "JQ026",
        "story_dependencies": "JQ027",
        "story_ux_references": "JQ028",
        "story_clarification_status": "JQ029",
        "story_preconditions": "JQ030",
        "story_primary_flow": "JQ031",
        "story_alternate_flow": "JQ032",
        "story_exceptions": "JQ033",
        "story_business_rules": "JQ034",
        "story_data_requirements": "JQ035",
        "story_security_compliance": "JQ036",
        "story_nfr": "JQ037",
        "story_open_questions": "JQ038",
        "story_acceptance_criteria": "JQ039",
    }

    story_data: Dict[str, Dict[str, Any]] = {}

    def merge_story_items(items: Any, field_name: str) -> None:
        if not isinstance(items, list):
            return

        for item in items:
            if not isinstance(item, dict):
                continue

            requirement_id = item.get("source_requirement_id")
            if not requirement_id:
                continue

            requirement_key = str(requirement_id)
            story = story_data.setdefault(
                requirement_key,
                {
                    "story_id": requirement_key,
                    "epic_id": "EPIC-001",
                },
            )

            for key, value in item.items():
                if key == "source_requirement_id":
                    continue

                if value is not None and (
                    key not in story
                    or story.get(key) in (None, "", [])
                ):
                    story[key] = value

            story["_last_source_query"] = field_name

    for field_name, query_id in story_queries.items():
        merge_story_items(
            _answer(results, query_id),
            field_name,
        )

    ordered_stories: List[Dict[str, Any]] = []
    core_items = _answer(results, "JQ019")

    if isinstance(core_items, list):
        for item in core_items:
            if not isinstance(item, dict):
                continue

            requirement_id = item.get("source_requirement_id")
            if not requirement_id:
                continue

            key = str(requirement_id)
            story = story_data.get(key)
            if story is not None:
                ordered_stories.append(story)

    known_ids = {
        str(story.get("story_id"))
        for story in ordered_stories
    }
    for key, story in story_data.items():
        if key not in known_ids:
            ordered_stories.append(story)

    # ------------------------------------------------------------------
    # Normalize story fields expected by the existing template helpers.
    # ------------------------------------------------------------------
    stories: List[Dict[str, Any]] = []
    details: List[Dict[str, Any]] = []

    for story in ordered_stories:
        story_id = str(
            story.get(
                "story_id",
                "",
            )
        )

        capability = story.get("capability", "")
        persona = story.get("persona")
        priority = story.get("priority")
        source_reference = story.get("source_reference")

        normalized_story = dict(story)
        normalized_story["story_id"] = story_id
        normalized_story["story_title"] = _first_non_empty(
            story.get("story_title"),
            capability,
            "Untitled Story",
        )
        normalized_story["epic_id"] = "EPIC-001"
        normalized_story["epic_name"] = epic_name
        normalized_story["persona"] = _first_non_empty(
            persona,
            "Not explicitly provided",
        )
        normalized_story["description"] = _first_non_empty(
            story.get("description"),
            "Not explicitly provided",
        )
        normalized_story["business_objective"] = _first_non_empty(
            story.get("business_objective"),
            "Not explicitly provided",
        )
        normalized_story["source_requirement"] = _first_non_empty(
            story.get("source_requirement"),
            story.get("source_requirement_id"),
            "Not explicitly provided",
        )
        normalized_story["source_reference"] = _first_non_empty(
            source_reference,
            "Not explicitly provided",
        )
        normalized_story["priority"] = _first_non_empty(
            priority,
            "To be planned",
        )
        normalized_story["story_points"] = _first_non_empty(
            story.get("story_points"),
            "To be estimated",
        )
        normalized_story["sprint_or_fix_version"] = _first_non_empty(
            story.get("sprint_or_fix_version"),
            "To be planned",
        )
        normalized_story["component_or_labels"] = _first_non_empty(
            story.get("component_or_labels"),
            "To be configured",
        )
        normalized_story["assignee"] = _first_non_empty(
            story.get("assignee"),
            "To be assigned",
        )
        normalized_story["dependencies"] = _first_non_empty(
            story.get("dependencies"),
            "Not explicitly provided",
        )
        normalized_story["attachments_or_ux_reference"] = _first_non_empty(
            story.get("attachments_or_ux_reference"),
            "Not provided",
        )
        normalized_story["clarification_status"] = _first_non_empty(
            story.get("clarification_status"),
            "Human review required",
        )
        normalized_story["status"] = _first_non_empty(
            story.get("status"),
            "Draft",
        )
        normalized_story["user_story"] = _first_non_empty(
            story.get("user_story"),
            capability,
            "Not explicitly provided",
        )

        details.append(
            {
                "story_id": story_id,
                "preconditions": story.get("precondition"),
                "primary_flow": story.get("primary_flow"),
                "alternate_flow": story.get("alternate_flow"),
                "exception_scenarios": story.get("exception"),
                "business_rules": story.get("business_rule"),
                "data_requirements": story.get("data_requirement"),
                "security_or_compliance_considerations": story.get(
                    "security_requirement"
                ),
                "non_functional_considerations": story.get(
                    "nfr_requirement"
                ),
                "open_questions": story.get("open_question"),
            }
        )

        stories.append(normalized_story)

    # ------------------------------------------------------------------
    # Reuse the existing template and rendering helpers.
    # ------------------------------------------------------------------
    document = Document(
        str(TEMPLATE_PATH)
    )

    _clean_template_examples(document)

    _replace_epic_paragraphs(
        document,
        _build_epic_values(epic),
    )

    epic_tables = [
        table
        for table in document.tables
        if len(table.columns) == 5
        and table.rows
        and table.rows[0].cells[0].text.strip() == "AC ID"
    ]

    if epic_tables:
        _populate_epic_table(
            epic_tables[0],
            epic,
        )

    detail_by_story = {
        str(item.get("story_id")): item
        for item in details
        if isinstance(item, dict)
    }

    story_criteria_answer = _answer(
        results,
        "JQ039",
    )
    story_criteria = (
        story_criteria_answer
        if isinstance(story_criteria_answer, list)
        else []
    )

    first_epic_name = _first_non_empty(
        epic.get("epic_name"),
        "Not explicitly provided",
    )

    for index, story in enumerate(stories):
        story_id = str(
            story.get(
                "story_id",
                f"STORY-{index + 1:03d}",
            )
        )

        story_details = detail_by_story.get(
            story_id,
            {},
        )

        if index == 0:
            _insert_generated_story_block(
                document,
                story,
                story_details,
                story_criteria,
                first_epic_name,
            )
            continue

        document.add_page_break()

        heading = document.add_paragraph(
            "B. Jira User Story"
        )
        heading.style = "Heading 1"

        table = document.add_table(
            rows=1,
            cols=2,
        )
        table.style = (
            document.tables[0].style.name
            if document.tables
            else "Table Grid"
        )

        headers = table.rows[0].cells
        _set_cell_text(
            headers[0],
            "Field",
        )
        _set_cell_text(
            headers[1],
            "Template / Guidance",
        )

        for field in [
            "Issue Type",
            "Summary",
            "Epic Link / Parent",
            "Story ID",
            "Persona",
            "User Story",
            "Description",
            "Business Objective",
            "Source Requirement",
            "Source Reference",
            "Priority",
            "Story Points",
            "Sprint / Fix Version",
            "Component / Labels",
            "Assignee",
            "Dependencies",
            "Attachments / UX Reference",
            "Clarification Status",
            "Status",
        ]:
            row = table.add_row().cells
            _set_cell_text(
                row[0],
                field,
            )

        _populate_story_table(
            table,
            story,
            first_epic_name,
        )

        document.add_paragraph(
            "Story Detail"
        ).style = "Heading 2"

        for label, key in [
            ("Preconditions", "preconditions"),
            ("Primary flow", "primary_flow"),
            ("Alternate flow", "alternate_flow"),
            ("Exception scenarios", "exception_scenarios"),
            ("Business rules", "business_rules"),
            ("Data requirements", "data_requirements"),
            (
                "Security / compliance considerations",
                "security_or_compliance_considerations",
            ),
            (
                "Non-functional considerations",
                "non_functional_considerations",
            ),
            ("Open questions", "open_questions"),
        ]:
            document.add_paragraph(
                f"{label}: "
                f"{_first_non_empty(
                    story_details.get(key),
                    "Not explicitly provided",
                )}"
            )

        document.add_paragraph(
            "Acceptance Criteria"
        ).style = "Heading 2"

        criteria_table = document.add_table(
            rows=1,
            cols=6,
        )
        criteria_table.style = table.style.name

        for cell, heading_text in zip(
            criteria_table.rows[0].cells,
            [
                "AC ID",
                "Scenario",
                "Given",
                "When",
                "Then",
                "Priority",
            ],
        ):
            _set_cell_text(
                cell,
                heading_text,
            )

        _populate_story_acceptance_table(
            criteria_table,
            story_criteria,
            story_id,
        )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    document.save(
        str(output_path)
    )

    logger.info(
        "Jira document generated: %s",
        output_path,
    )

    return str(output_path)


if __name__ == "__main__":
    print(
        generate_jira_document()
    )