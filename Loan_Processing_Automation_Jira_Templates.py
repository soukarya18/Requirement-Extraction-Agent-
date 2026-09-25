
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from docx import Document
from docx.oxml.ns import qn


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent

TEMPLATE_PATH = (
    BASE_DIR
    / "data"
    / "uploads"
    / "Loan_Processing_Automation_Jira_Templates.docx"
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


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------


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
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(
            "Merged Jira query results must be a JSON object."
        )

    return data


def _answer(
    results: Dict[str, Dict[str, Any]],
    query_id: str,
) -> Any:
    """Return a successful query answer or a safe empty value."""

    result = results.get(query_id)

    if not isinstance(result, dict):
        return []

    if result.get("status") != "success":
        logger.warning(
            "%s did not succeed; using an empty answer.",
            query_id,
        )
        return []

    return result.get("answer")


def _as_list(
    value: Any,
) -> List[Any]:
    """Normalize an arbitrary JSON value to a list."""

    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def _text(
    value: Any,
    default: str = "",
) -> str:
    """Render JSON values to readable text."""

    if value is None:
        return default

    if isinstance(value, list):
        values = [
            _text(item)
            for item in value
            if item is not None
        ]
        return "; ".join(
            item
            for item in values
            if item
        )

    if isinstance(value, dict):
        return json.dumps(
            value,
            ensure_ascii=False,
        )

    return str(value)


def _value(
    *values: Any,
    default: str = "",
) -> str:
    """Return the first non-empty rendered value."""

    for candidate in values:
        rendered = _text(candidate).strip()

        if rendered:
            return rendered

    return default


def _index_by(
    items: Any,
    key: str,
) -> Dict[str, Dict[str, Any]]:
    """Index object-list results by a stable key."""

    result: Dict[str, Dict[str, Any]] = {}

    for item in _as_list(items):
        if not isinstance(item, dict):
            continue

        raw_key = item.get(key)

        if raw_key is None:
            continue

        normalized = str(raw_key).strip()

        if normalized:
            result[normalized] = item

    return result


def _merge_optional(
    target: Dict[str, Any],
    source: Dict[str, Any],
) -> None:
    """
    Merge source fields without replacing meaningful values with null/empty
    values.
    """

    for key, incoming in source.items():
        if key == "story_id":
            continue

        if incoming is None:
            continue

        if isinstance(incoming, list) and not incoming:
            continue

        if isinstance(incoming, str) and not incoming.strip():
            continue

        existing = target.get(key)

        if existing is None:
            target[key] = incoming
            continue

        if isinstance(existing, list) and isinstance(incoming, list):
            merged = list(existing)

            for item in incoming:
                if item not in merged:
                    merged.append(item)

            target[key] = merged


# ---------------------------------------------------------------------------
# Consolidation: Epic
# ---------------------------------------------------------------------------


def _build_epics(
    results: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Merge JQ001-JQ008 into Epic objects.

    JQ001 is the Epic identity anchor. JQ003 is global scope information
    because its schema is not keyed by epic_name.
    """

    core = _index_by(
        _answer(results, "JQ001"),
        "epic_name",
    )
    context = _index_by(
        _answer(results, "JQ002"),
        "epic_name",
    )
    dependency_data = _index_by(
        _answer(results, "JQ006"),
        "epic_name",
    )
    planning = _index_by(
        _answer(results, "JQ007"),
        "epic_name",
    )

    scope_answer = _answer(
        results,
        "JQ003",
    )
    scope = (
        scope_answer
        if isinstance(scope_answer, dict)
        else {}
    )

    stakeholder_map: Dict[str, List[str]] = {}
    for item in _as_list(
        _answer(results, "JQ004")
    ):
        if not isinstance(item, dict):
            continue

        epic_name = str(
            item.get("epic_name", "")
        ).strip()

        person = _value(
            item.get("persona_or_stakeholder"),
            item.get("responsibility"),
        )

        if epic_name and person:
            stakeholder_map.setdefault(
                epic_name,
                [],
            ).append(person)

    measure_map: Dict[str, List[str]] = {}
    for item in _as_list(
        _answer(results, "JQ005")
    ):
        if not isinstance(item, dict):
            continue

        epic_name = str(
            item.get("epic_name", "")
        ).strip()

        measure = _value(
            item.get("success_measure")
        )

        if epic_name and measure:
            measure_map.setdefault(
                epic_name,
                [],
            ).append(measure)

    epic_criteria = _as_list(
        _answer(results, "JQ008")
    )

    epics: List[Dict[str, Any]] = []

    for epic_name, base in core.items():
        epic = dict(base)

        _merge_optional(
            epic,
            context.get(
                epic_name,
                {},
            ),
        )
        _merge_optional(
            epic,
            dependency_data.get(
                epic_name,
                {},
            ),
        )
        _merge_optional(
            epic,
            planning.get(
                epic_name,
                {},
            ),
        )

        epic["in_scope"] = list(
            scope.get(
                "in_scope",
                [],
            )
            or []
        )
        epic["out_of_scope"] = list(
            scope.get(
                "out_of_scope",
                [],
            )
            or []
        )

        epic["personas_or_stakeholders"] = (
            stakeholder_map.get(
                epic_name,
                [],
            )
        )

        epic["success_measures"] = (
            measure_map.get(
                epic_name,
                [],
            )
        )

        epic["acceptance_criteria"] = [
            item
            for item in epic_criteria
            if isinstance(item, dict)
            and str(
                item.get(
                    "epic_name",
                    "",
                )
            ).strip()
            == epic_name
        ]

        epics.append(epic)

    return epics


# ---------------------------------------------------------------------------
# Consolidation: Stories
# ---------------------------------------------------------------------------


def _build_stories(
    results: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Merge JQ009-JQ018 into Story objects keyed by story_id.

    JQ009 is the identity anchor. Secondary queries only enrich existing
    stories and never create new story records.
    """

    stories = [
        dict(item)
        for item in _as_list(
            _answer(
                results,
                "JQ009",
            )
        )
        if isinstance(item, dict)
        and str(
            item.get("story_id", "")
        ).strip()
    ]

    story_map = {
        str(
            story["story_id"]
        ).strip(): story
        for story in stories
    }

    for query_id in [
        "JQ010",
        "JQ011",
        "JQ012",
        "JQ013",
        "JQ014",
        "JQ015",
        "JQ016",
        "JQ017",
        "JQ018",
    ]:
        for item in _as_list(
            _answer(
                results,
                query_id,
            )
        ):
            if not isinstance(item, dict):
                continue

            story_id = str(
                item.get("story_id", "")
            ).strip()

            if not story_id:
                continue

            story = story_map.get(
                story_id
            )

            if story is None:
                continue

            _merge_optional(
                story,
                item,
            )

    # Construct the textual User Story only from supported values.
    #
    # The query schema intentionally allows role/persona to be null and does
    # not require a benefit. Therefore:
    #   role + capability + benefit -> full standard sentence
    #   role + capability           -> no invented benefit
    #   capability only             -> capability text
    for story in stories:
        role = _value(
            story.get("role"),
            story.get("persona"),
        )
        capability = _value(
            story.get("capability")
        )
        benefit = _value(
            story.get("benefit")
        )

        if role and capability and benefit:
            story["user_story"] = (
                f"As a {role}, I want {capability}, "
                f"so that {benefit}."
            )
        elif role and capability:
            story["user_story"] = (
                f"As a {role}, I want {capability}."
            )
        elif capability:
            story["user_story"] = capability

    return stories


# ---------------------------------------------------------------------------
# DOCX helpers
# ---------------------------------------------------------------------------


def _set_paragraph(
    paragraph: Any,
    text: Any,
) -> None:
    """Replace paragraph text while preserving the first run formatting."""

    rendered = _text(text)

    if not paragraph.runs:
        paragraph.add_run(
            rendered
        )
        return

    paragraph.runs[0].text = rendered

    for run in paragraph.runs[1:]:
        run.text = ""


def _set_cell(
    cell: Any,
    value: Any,
) -> None:
    """Replace table-cell text safely."""

    rendered = _text(
        value,
        default="Not explicitly provided",
    )

    paragraphs = cell.paragraphs

    if not paragraphs:
        cell.text = rendered
        return

    _set_paragraph(
        paragraphs[0],
        rendered,
    )

    for paragraph in paragraphs[1:]:
        _set_paragraph(
            paragraph,
            "",
        )


def _replace_labeled_paragraph(
    document: Document,
    label: str,
    value: Any,
    default: str = "Not explicitly provided",
) -> bool:
    """Replace a paragraph in the form 'Label: value'."""

    rendered = _text(
        value,
        default=default,
    )

    prefix = f"{label}:"

    for paragraph in document.paragraphs:
        if paragraph.text.strip().startswith(prefix):
            _set_paragraph(
                paragraph,
                f"{label}: {rendered}",
            )
            return True

    return False


def _replace_all_occurrences(
    document: Document,
    label: str,
    value: Any,
    default: str = "Not explicitly provided",
) -> int:
    """Replace every paragraph beginning with a given label."""

    rendered = _text(
        value,
        default=default,
    )
    prefix = f"{label}:"
    count = 0

    for paragraph in document.paragraphs:
        if paragraph.text.strip().startswith(prefix):
            _set_paragraph(
                paragraph,
                f"{label}: {rendered}",
            )
            count += 1

    return count


def _remove_rows_after_header(
    table: Any,
) -> None:
    """Remove all template/example rows after the header row."""

    for row in list(
        table.rows[1:]
    ):
        table._tbl.remove(
            row._tr
        )


def _add_table_row(
    table: Any,
    values: List[Any],
) -> None:
    """Append a row to a table."""

    row = table.add_row()

    for cell, value in zip(
        row.cells,
        values,
    ):
        _set_cell(
            cell,
            value,
        )


def _find_table_by_headers(
    document: Document,
    expected_headers: List[str],
) -> Optional[Any]:
    """Find a table whose first row starts with the requested headers."""

    for table in document.tables:
        if not table.rows:
            continue

        headers = [
            cell.text.strip()
            for cell in table.rows[0].cells
        ]

        if headers[: len(expected_headers)] == expected_headers:
            return table

    return None


def _find_story_field_table(
    document: Document,
) -> Optional[Any]:
    """Find the two-column Story field table."""

    for table in document.tables:
        if len(table.columns) != 2:
            continue

        first_column = {
            cell.text.strip()
            for cell in table.columns[0].cells
        }

        if "Story ID" in first_column:
            return table

    return None


def _duplicate_table_after(
    source_table: Any,
) -> Any:
    """Return a deep copy of a table XML element."""

    from copy import deepcopy

    return deepcopy(
        source_table._element
    )


def _insert_after(
    reference_element: Any,
    new_element: Any,
) -> None:
    """Insert a cloned XML element immediately after another element."""

    reference_element.addnext(
        new_element
    )


def _remove_table_from_document(
    table: Any,
) -> None:
    """Remove a table element from the document."""

    parent = table._element.getparent()

    if parent is not None:
        parent.remove(
            table._element
        )


# ---------------------------------------------------------------------------
# Epic rendering
# ---------------------------------------------------------------------------


def _populate_epic(
    document: Document,
    epic: Dict[str, Any],
) -> None:
    """Populate the existing Epic template block."""

    fields = {
        "Issue Type": "Epic",
        "Project": "To be configured",
        "Epic Key": "To be created by Jira",
        "Epic Name": _value(
            epic.get("epic_name"),
            default="Untitled Epic",
        ),
        "Summary": _value(
            epic.get("summary"),
            epic.get("epic_name"),
            default="Not explicitly provided",
        ),
        "Business Objective": _value(
            epic.get("business_objective"),
            epic.get("business_objectives"),
        ),
        "Business Problem / Opportunity": _value(
            epic.get(
                "business_problem_or_opportunity"
            )
        ),
        "Epic Hypothesis / Benefit": _value(
            epic.get(
                "hypothesis_or_benefit"
            )
        ),
        "In Scope": _value(
            epic.get("in_scope")
        ),
        "Out of Scope": _value(
            epic.get("out_of_scope")
        ),
        "Description": _value(
            epic.get("description")
        ),
        "Personas / Stakeholders": _value(
            epic.get(
                "personas_or_stakeholders"
            )
        ),
        "Success Measures": _value(
            epic.get(
                "success_measures"
            )
        ),
        "Dependencies": _value(
            epic.get("dependencies")
        ),
        "Risks / Assumptions": _value(
            epic.get(
                "risks_or_assumptions"
            )
        ),
        "Priority": _value(
            epic.get("priority"),
            default="To be planned",
        ),
        "Target Release / Fix Version": _value(
            epic.get("target_release"),
            default="To be planned",
        ),
        "Labels / Components": _value(
            epic.get("labels_or_components"),
            default="To be configured",
        ),
        "Source References": _value(
            epic.get("source_references"),
        ),
        "Definition of Done": (
            "Epic capabilities delivered, acceptance criteria satisfied, "
            "traceability maintained, testing completed, and authorized "
            "reviewers accept the release."
        ),
    }

    for label, value in fields.items():
        _replace_labeled_paragraph(
            document,
            label,
            value,
        )

    table = _find_table_by_headers(
        document,
        [
            "AC ID",
            "Given",
            "When",
            "Then",
            "Evidence",
        ],
    )

    if table is None:
        logger.warning(
            "Epic acceptance criteria table not found."
        )
        return

    _remove_rows_after_header(
        table
    )

    for criterion in epic.get(
        "acceptance_criteria",
        [],
    ):
        if not isinstance(criterion, dict):
            continue

        _add_table_row(
            table,
            [
                criterion.get("ac_id"),
                criterion.get("given"),
                criterion.get("when"),
                criterion.get("then"),
                criterion.get("evidence"),
            ],
        )


# ---------------------------------------------------------------------------
# Story rendering
# ---------------------------------------------------------------------------


def _populate_story(
    document: Document,
    story: Dict[str, Any],
    epic_name: str,
    criteria: List[Dict[str, Any]],
) -> None:
    """Populate the first Story block in the template."""

    table = _find_story_field_table(
        document
    )

    if table is None:
        raise RuntimeError(
            "Jira User Story field table not found in template."
        )

    values = {
        "Issue Type": "Story",
        "Summary": _value(
            story.get("story_title"),
            story.get("capability"),
            default="Untitled Story",
        ),
        "Epic Link / Parent": _value(
            story.get("epic_name"),
            epic_name,
        ),
        "Story ID": _value(
            story.get("story_id"),
            default="Not explicitly provided",
        ),
        "Persona": _value(
            story.get("persona"),
            story.get("role"),
        ),
        "User Story": _value(
            story.get("user_story"),
            story.get("capability"),
        ),
        "Description": _value(
            story.get("description")
        ),
        "Business Objective": _value(
            story.get("business_objective")
        ),
        "Source Requirement": _value(
            story.get("source_requirement"),
            story.get("linked_fr_ids"),
        ),
        "Source Reference": _value(
            story.get("source_reference")
        ),
        "Priority": _value(
            story.get("priority"),
            default="To be planned",
        ),
        "Story Points": _value(
            story.get("story_points"),
            default="To be estimated",
        ),
        "Sprint / Fix Version": _value(
            story.get("sprint_or_fix_version"),
            default="To be planned",
        ),
        "Component / Labels": _value(
            story.get("component_or_labels"),
            default="To be configured",
        ),
        "Assignee": _value(
            story.get("assignee"),
            default="To be assigned",
        ),
        "Dependencies": _value(
            story.get("dependencies")
        ),
        "Attachments / UX Reference": _value(
            story.get(
                "attachments_or_ux_reference"
            )
        ),
        "Clarification Status": _value(
            story.get("clarification_status"),
            default="Human review required",
        ),
        "Status": _value(
            story.get("status"),
            default="Draft",
        ),
    }

    for row in table.rows:
        if len(row.cells) < 2:
            continue

        field = row.cells[0].text.strip()

        if field in values:
            _set_cell(
                row.cells[1],
                values[field],
            )

    _populate_story_detail_paragraphs(
        document,
        story,
    )

    criteria_table = _find_table_by_headers(
        document,
        [
            "AC ID",
            "Scenario",
            "Given",
            "When",
            "Then",
            "Priority",
        ],
    )

    if criteria_table is None:
        logger.warning(
            "Story acceptance criteria table not found."
        )
        return

    _remove_rows_after_header(
        criteria_table
    )

    _append_story_criteria(
        criteria_table,
        str(
            story.get(
                "story_id",
                "",
            )
        ),
        criteria,
    )


def _populate_story_detail_paragraphs(
    document: Document,
    story: Dict[str, Any],
) -> None:
    """Populate the Story Detail section."""

    mappings = [
        (
            "Preconditions",
            "preconditions",
        ),
        (
            "Primary flow",
            "primary_flow",
        ),
        (
            "Alternate flow",
            "alternate_flow",
        ),
        (
            "Exception scenarios",
            "exception_scenarios",
        ),
        (
            "Business rules",
            "business_rules",
        ),
        (
            "Data requirements",
            "data_requirements",
        ),
        (
            "Security / compliance considerations",
            "security_or_compliance_considerations",
        ),
        (
            "Non-functional considerations",
            "non_functional_considerations",
        ),
        (
            "Open questions",
            "open_questions",
        ),
    ]

    for label, key in mappings:
        _replace_labeled_paragraph(
            document,
            label,
            story.get(key),
            default="Not explicitly provided",
        )


def _append_story_criteria(
    table: Any,
    story_id: str,
    criteria: Iterable[Dict[str, Any]],
) -> None:
    """Append only criteria belonging to the given story."""

    for criterion in criteria:
        if not isinstance(criterion, dict):
            continue

        criterion_story_id = criterion.get(
            "story_id"
        )

        if (
            criterion_story_id is not None
            and str(
                criterion_story_id
            ).strip()
            != story_id.strip()
        ):
            continue

        _add_table_row(
            table,
            [
                criterion.get("ac_id"),
                criterion.get("scenario"),
                criterion.get("given"),
                criterion.get("when"),
                criterion.get("then"),
                criterion.get("priority"),
            ],
        )


# ---------------------------------------------------------------------------
# Additional Story blocks
# ---------------------------------------------------------------------------


def _append_story_block(
    document: Document,
    story: Dict[str, Any],
    epic_name: str,
    criteria: List[Dict[str, Any]],
) -> None:
    """
    Append an additional story using the same structure as the static
    template. This deliberately creates a clean repeated block rather than
    copying the template's example content.
    """

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

    _set_cell(
        table.rows[0].cells[0],
        "Field",
    )
    _set_cell(
        table.rows[0].cells[1],
        "Template / Guidance",
    )

    fields = [
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
    ]

    for field in fields:
        cells = table.add_row().cells

        _set_cell(
            cells[0],
            field,
        )
        _set_cell(
            cells[1],
            "",
        )

    values = {
        "Issue Type": "Story",
        "Summary": _value(
            story.get("story_title"),
            story.get("capability"),
            default="Untitled Story",
        ),
        "Epic Link / Parent": _value(
            story.get("epic_name"),
            epic_name,
        ),
        "Story ID": _value(
            story.get("story_id"),
        ),
        "Persona": _value(
            story.get("persona"),
            story.get("role"),
        ),
        "User Story": _value(
            story.get("user_story"),
            story.get("capability"),
        ),
        "Description": _value(
            story.get("description")
        ),
        "Business Objective": _value(
            story.get("business_objective")
        ),
        "Source Requirement": _value(
            story.get("source_requirement"),
            story.get("linked_fr_ids"),
        ),
        "Source Reference": _value(
            story.get("source_reference")
        ),
        "Priority": _value(
            story.get("priority"),
            default="To be planned",
        ),
        "Story Points": _value(
            story.get("story_points"),
            default="To be estimated",
        ),
        "Sprint / Fix Version": _value(
            story.get("sprint_or_fix_version"),
            default="To be planned",
        ),
        "Component / Labels": _value(
            story.get("component_or_labels"),
            default="To be configured",
        ),
        "Assignee": _value(
            story.get("assignee"),
            default="To be assigned",
        ),
        "Dependencies": _value(
            story.get("dependencies")
        ),
        "Attachments / UX Reference": _value(
            story.get(
                "attachments_or_ux_reference"
            )
        ),
        "Clarification Status": _value(
            story.get("clarification_status"),
            default="Human review required",
        ),
        "Status": _value(
            story.get("status"),
            default="Draft",
        ),
    }

    for row in table.rows[1:]:
        field = row.cells[0].text.strip()

        if field in values:
            _set_cell(
                row.cells[1],
                values[field],
            )

    document.add_paragraph(
        "Story Detail"
    ).style = "Heading 2"

    details = [
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
    ]

    for label, key in details:
        document.add_paragraph(
            f"{label}: "
            f"{_value(
                story.get(key),
                default="Not explicitly provided",
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
        _set_cell(
            cell,
            heading_text,
        )

    _append_story_criteria(
        criteria_table,
        str(
            story.get(
                "story_id",
                "",
            )
        ),
        criteria,
    )


# ---------------------------------------------------------------------------
# Main assembly
# ---------------------------------------------------------------------------


def generate_jira_document() -> str:
    """Generate a Jira user-story document from the static template."""

    logger.info("=" * 80)
    logger.info("JIRA ASSEMBLY STARTED")
    logger.info("=" * 80)

    logger.info(
        "Template: %s",
        TEMPLATE_PATH,
    )
    logger.info(
        "Results: %s",
        RESULTS_PATH,
    )
    logger.info(
        "Output: %s",
        OUTPUT_PATH,
    )

    if not TEMPLATE_PATH.is_file():
        raise FileNotFoundError(
            f"Jira template not found: {TEMPLATE_PATH}"
        )

    results = _load_results()

    epics = _build_epics(
        results
    )
    stories = _build_stories(
        results
    )

    story_criteria = [
        item
        for item in _as_list(
            _answer(
                results,
                "JQ018",
            )
        )
        if isinstance(item, dict)
    ]

    document = Document(
        str(TEMPLATE_PATH)
    )

    # We do not delete the instructional pages. They describe how the
    # reusable template is intended to be used and are not source facts.
    #
    # The Bug and Example Traceability sections are template examples,
    # however, so they should not appear as generated project artefacts.
    _remove_example_bug_and_traceability(
        document
    )

    # ------------------------------------------------------------------
    # Epic
    # ------------------------------------------------------------------

    if epics:
        _populate_epic(
            document,
            epics[0],
        )

        if len(epics) > 1:
            logger.warning(
                "The template contains one Epic block. "
                "Only the first generated Epic is rendered. "
                "Additional Epic blocks are not yet duplicated."
            )

    # ------------------------------------------------------------------
    # Stories
    # ------------------------------------------------------------------

    story_table = _find_story_field_table(
        document
    )

    if stories and story_table is not None:
        _populate_story(
            document,
            stories[0],
            _value(
                stories[0].get("epic_name"),
                epics[0].get("epic_name")
                if epics
                else "",
            ),
            story_criteria,
        )

        for story in stories[1:]:
            _append_story_block(
                document,
                story,
                _value(
                    story.get("epic_name"),
                    epics[0].get("epic_name")
                    if epics
                    else "",
                ),
                story_criteria,
            )
    elif stories:
        raise RuntimeError(
            "Stories were generated but the Story template table was not found."
        )

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    document.save(
        str(OUTPUT_PATH)
    )

    logger.info(
        "Jira document generated: %s",
        OUTPUT_PATH,
    )
    logger.info(
        "Epic count: %d | Story count: %d",
        len(epics),
        len(stories),
    )
    logger.info("=" * 80)
    logger.info("JIRA ASSEMBLY COMPLETED")
    logger.info("=" * 80)

    return str(
        OUTPUT_PATH
    )


def _remove_example_traceability(
    document: Document,
) -> None:
    """Remove only the example Traceability Mapping section."""

    body = document._body._element
    children = list(
        body.iterchildren()
    )

    start_index: Optional[int] = None
    end_index: Optional[int] = None

    for index, child in enumerate(children):
        if child.tag != qn("w:p"):
            continue

        text = "".join(
            node.text or ""
            for node in child.iter(qn("w:t"))
        ).strip()

        if text == "D. Example Traceability Mapping":
            start_index = index

        if (
            start_index is not None
            and index > start_index
            and text == "E. Template Quality Checklist"
        ):
            end_index = index
            break

    if start_index is None:
        return

    final_index = (
        end_index
        if end_index is not None
        else len(children)
    )

    # Remove the heading/table/content range but leave the Quality Checklist.
    for child in children[
        start_index:final_index
    ]:
        body.remove(child)


def _find_bug_field_table(
    document: Document,
) -> Optional[Any]:
    """Find the two-column Jira Bug template table."""

    expected = {
        "Issue Type",
        "Summary",
        "Environment",
        "Preconditions",
        "Steps to Reproduce",
        "Expected Result",
        "Actual Result",
        "Severity",
        "Priority",
        "Frequency",
        "Affected Requirement / Story",
        "Evidence",
        "Workaround",
        "Acceptance / Retest Criteria",
    }

    for table in document.tables:
        if len(table.columns) != 2:
            continue

        labels = {
            row.cells[0].text.strip()
            for row in table.rows
            if row.cells
        }

        if expected.issubset(labels):
            return table

    return None


def _remove_bug_example_fields(
    table: Any,
) -> None:
    """Reset the Bug template values so example data cannot leak through."""

    for row in table.rows:
        if len(row.cells) < 2:
            continue

        field = row.cells[0].text.strip()

        if field == "Issue Type":
            _set_cell(row.cells[1], "Bug Candidate")
        else:
            _set_cell(row.cells[1], "")


def _populate_bug_candidate(
    document: Document,
    bug: Dict[str, Any],
) -> None:
    """Populate the first Bug Candidate template block."""

    table = _find_bug_field_table(
        document
    )

    if table is None:
        logger.warning(
            "Jira Bug template table not found."
        )
        return

    values = {
        "Issue Type": "Bug Candidate",
        "Summary": _value(
            bug.get("summary"),
            default="Not explicitly provided",
        ),
        "Environment": _value(
            bug.get("environment")
        ),
        "Preconditions": _value(
            bug.get("preconditions")
        ),
        "Steps to Reproduce": _value(
            bug.get("steps_to_reproduce")
        ),
        "Expected Result": _value(
            bug.get("expected_result")
        ),
        "Actual Result": _value(
            bug.get("actual_result")
        ),
        "Severity": _value(
            bug.get("severity")
        ),
        "Priority": _value(
            bug.get("priority")
        ),
        "Frequency": _value(
            bug.get("frequency")
        ),
        "Affected Requirement / Story": _value(
            bug.get("affected_requirement_or_story")
        ),
        "Evidence": _value(
            bug.get("evidence")
        ),
        "Workaround": _value(
            bug.get("workaround")
        ),
        "Acceptance / Retest Criteria": _value(
            bug.get("acceptance_or_retest_criteria")
        ),
    }

    for row in table.rows:
        if len(row.cells) < 2:
            continue

        field = row.cells[0].text.strip()

        if field not in values:
            continue

        value = values[field]

        if not value:
            value = "Not provided in source"

        _set_cell(
            row.cells[1],
            value,
        )


def _populate_no_bug_candidate(
    document: Document,
) -> None:
    """
    Remove the template's fake defect values when the source contains no
    explicit defect/current-vs-expected discrepancy.
    """

    table = _find_bug_field_table(
        document
    )

    if table is None:
        logger.warning(
            "Jira Bug template table not found."
        )
        return

    values = {
        "Issue Type": "Bug Candidate",
        "Summary": (
            "No source-supported bug candidate identified"
        ),
        "Environment": "Not provided in source",
        "Preconditions": "Not provided in source",
        "Steps to Reproduce": "Not provided in source",
        "Expected Result": "Not provided in source",
        "Actual Result": "Not provided in source",
        "Severity": "Not provided in source",
        "Priority": "Not provided in source",
        "Frequency": "Not provided in source",
        "Affected Requirement / Story": "Not provided in source",
        "Evidence": (
            "The source does not document a confirmed defect "
            "or an actual-versus-expected discrepancy."
        ),
        "Workaround": "Not provided in source",
        "Acceptance / Retest Criteria": "Not provided in source",
    }

    for row in table.rows:
        if len(row.cells) < 2:
            continue

        field = row.cells[0].text.strip()

        if field in values:
            _set_cell(
                row.cells[1],
                values[field],
            )


def _append_bug_candidate_block(
    document: Document,
    bug: Dict[str, Any],
) -> None:
    """Append an additional Bug Candidate block."""

    document.add_page_break()

    heading = document.add_paragraph(
        "C. Jira Bug Candidate"
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

    _set_cell(
        table.rows[0].cells[0],
        "Field",
    )
    _set_cell(
        table.rows[0].cells[1],
        "Value",
    )

    fields = [
        "Issue Type",
        "Summary",
        "Environment",
        "Preconditions",
        "Steps to Reproduce",
        "Expected Result",
        "Actual Result",
        "Severity",
        "Priority",
        "Frequency",
        "Affected Requirement / Story",
        "Evidence",
        "Workaround",
        "Acceptance / Retest Criteria",
    ]

    values = {
        "Issue Type": "Bug Candidate",
        "Summary": _value(
            bug.get("summary"),
            default="Not explicitly provided",
        ),
        "Environment": _value(
            bug.get("environment")
        ),
        "Preconditions": _value(
            bug.get("preconditions")
        ),
        "Steps to Reproduce": _value(
            bug.get("steps_to_reproduce")
        ),
        "Expected Result": _value(
            bug.get("expected_result")
        ),
        "Actual Result": _value(
            bug.get("actual_result")
        ),
        "Severity": _value(
            bug.get("severity")
        ),
        "Priority": _value(
            bug.get("priority")
        ),
        "Frequency": _value(
            bug.get("frequency")
        ),
        "Affected Requirement / Story": _value(
            bug.get("affected_requirement_or_story")
        ),
        "Evidence": _value(
            bug.get("evidence")
        ),
        "Workaround": _value(
            bug.get("workaround")
        ),
        "Acceptance / Retest Criteria": _value(
            bug.get("acceptance_or_retest_criteria")
        ),
    }

    for field in fields:
        cells = table.add_row().cells

        _set_cell(
            cells[0],
            field,
        )
        _set_cell(
            cells[1],
            values.get(
                field,
                "",
            ) or "Not provided in source",
        )


# ---------------------------------------------------------------------------
# Main assembly
# ---------------------------------------------------------------------------


def generate_jira_document() -> str:
    """Generate the filled Jira document from the static template."""

    logger.info("=" * 80)
    logger.info("JIRA ASSEMBLY STARTED")
    logger.info("=" * 80)

    logger.info(
        "Template: %s",
        TEMPLATE_PATH,
    )
    logger.info(
        "Results: %s",
        RESULTS_PATH,
    )
    logger.info(
        "Output: %s",
        OUTPUT_PATH,
    )

    if not TEMPLATE_PATH.is_file():
        raise FileNotFoundError(
            f"Jira template not found: {TEMPLATE_PATH}"
        )

    results = _load_results()

    epics = _build_epics(
        results
    )
    stories = _build_stories(
        results
    )

    story_criteria = [
        item
        for item in _as_list(
            _answer(
                results,
                "JQ018",
            )
        )
        if isinstance(item, dict)
    ]

    bug_candidates = [
        item
        for item in _as_list(
            _answer(
                results,
                "JQ020",
            )
        )
        if isinstance(item, dict)
    ]

    document = Document(
        str(TEMPLATE_PATH)
    )

    # Keep the Bug template structure, but remove its example Traceability
    # section. Example Bug values are overwritten below.
    _remove_example_traceability(
        document
    )

    # ------------------------------------------------------------------
    # Epic
    # ------------------------------------------------------------------

    if epics:
        _populate_epic(
            document,
            epics[0],
        )

        if len(epics) > 1:
            logger.warning(
                "The static template contains one Epic block. "
                "Only the first generated Epic is rendered."
            )

    # ------------------------------------------------------------------
    # Stories
    # ------------------------------------------------------------------

    story_table = _find_story_field_table(
        document
    )

    if stories and story_table is not None:
        first_story = stories[0]

        _populate_story(
            document,
            first_story,
            _value(
                first_story.get("epic_name"),
                epics[0].get("epic_name")
                if epics
                else "",
            ),
            story_criteria,
        )

        for story in stories[1:]:
            _append_story_block(
                document,
                story,
                _value(
                    story.get("epic_name"),
                    epics[0].get("epic_name")
                    if epics
                    else "",
                ),
                story_criteria,
            )

    elif stories:
        raise RuntimeError(
            "Stories were generated but the Story template table was not found."
        )

    # ------------------------------------------------------------------
    # Bug candidates
    # ------------------------------------------------------------------

    if bug_candidates:
        _populate_bug_candidate(
            document,
            bug_candidates[0],
        )

        for bug in bug_candidates[1:]:
            _append_bug_candidate_block(
                document,
                bug,
            )
    else:
        # Crucial: never leave the template's illustrative Bug example
        # in the project-specific output.
        _populate_no_bug_candidate(
            document
        )

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    document.save(
        str(OUTPUT_PATH)
    )

    logger.info(
        "Generated Jira document: %s",
        OUTPUT_PATH,
    )
    logger.info(
        "Epic count: %d | Story count: %d | Bug candidates: %d",
        len(epics),
        len(stories),
        len(bug_candidates),
    )
    logger.info("=" * 80)
    logger.info("JIRA ASSEMBLY COMPLETED")
    logger.info("=" * 80)

    return str(
        OUTPUT_PATH
    )



if __name__ == "__main__":
    print(
        generate_jira_document()
    )
