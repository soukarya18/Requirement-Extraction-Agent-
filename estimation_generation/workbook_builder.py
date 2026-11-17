"""Build the estimation workbook with openpyxl.

The command-line contract intentionally matches the former Node builder:

    python workbook_builder.py input.json output.xlsx

The input payload is produced by ``estimation_generation.pipeline``.  Totals
are written as Excel formulas and the workbook is configured to recalculate
when opened in Excel.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet


BLUE = "1F4E78"
LIGHT_BLUE = "D9EAF7"
MID_BLUE = "9ABAD0"
LIGHT_GREY = "D9D9D9"
WHITE = "FFFFFF"
BLACK = "000000"


def _column_name(index: int) -> str:
    """Return the Excel column name for a zero-based column index."""

    return get_column_letter(index + 1)


def _font(*, size: float = 10, bold: bool = False, color: str = BLACK) -> Font:
    return Font(name="Aptos", size=size, bold=bold, color=color)


def _fill(color: str) -> PatternFill:
    return PatternFill(fill_type="solid", fgColor=color)


def _side(style: str = "thin", color: str = LIGHT_GREY) -> Side:
    return Side(style=style, color=color)


def _all_borders(style: str = "thin", color: str = LIGHT_GREY) -> Border:
    edge = _side(style, color)
    return Border(left=edge, right=edge, top=edge, bottom=edge)


def _outside_borders(style: str = "thin", color: str = WHITE) -> Border:
    edge = _side(style, color)
    return Border(left=edge, right=edge, top=edge, bottom=edge)


def _bottom_border(style: str = "medium", color: str = BLUE) -> Border:
    return Border(bottom=_side(style, color))


def _iter_cells(sheet: Worksheet, min_row: int, max_row: int, min_col: int, max_col: int):
    for row in sheet.iter_rows(
        min_row=min_row,
        max_row=max_row,
        min_col=min_col,
        max_col=max_col,
    ):
        yield from row


def _style_range(
    sheet: Worksheet,
    cell_range: str,
    *,
    fill: PatternFill | None = None,
    font: Font | None = None,
    alignment: Alignment | None = None,
    border: Border | None = None,
    number_format: str | None = None,
) -> None:
    for row in sheet[cell_range]:
        for cell in row:
            if fill is not None:
                cell.fill = fill
            if font is not None:
                cell.font = font
            if alignment is not None:
                cell.alignment = alignment
            if border is not None:
                cell.border = border
            if number_format is not None:
                cell.number_format = number_format


def _merge_and_write(sheet: Worksheet, cell_range: str, value: Any) -> None:
    sheet.merge_cells(cell_range)
    sheet[cell_range.split(":", 1)[0]] = value


def _as_number(value: Any) -> Any:
    """Keep numeric PD values numeric while preserving blank optional cells."""

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return value


def build_workbook(payload: dict[str, Any], output_path: Path) -> None:
    qa_support = bool(payload.get("qa_support"))
    rows = payload.get("rows") or []
    conditions = payload.get("conditions") or []

    headers = [
        "Module",
        "Submodule",
        "Analysis (PD)",
        "Development (PD)",
        "Unit Testing (PD)",
        "Functional Testing (PD)",
    ]
    keys = [
        "module",
        "submodule",
        "analysis_pd",
        "development_pd",
        "unit_testing_pd",
        "functional_testing_pd",
    ]
    if qa_support:
        headers.extend(["QA Deployment (PD)", "QA Testing (PD)"])
        keys.extend(["qa_deployment_pd", "qa_testing_pd"])
    headers.extend(["QA Bugfixing (PD)", "Total PD", "Comments"])
    keys.append("qa_bugfixing_pd")

    total_column_index = headers.index("Total PD")
    total_column = _column_name(total_column_index)
    comments_column = _column_name(headers.index("Comments"))
    module_effort_headers = headers[2:total_column_index]
    overall = payload.get("overall_effort") or {}
    overall_headers = [
        *module_effort_headers,
        "PPE Deployment (PD)",
        "Production Deployment (PD)",
        "Post Production Support (PD)",
        "Contingency Effort (PD)",
        "Total PD",
    ]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Estimation"
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.tabColor = BLUE

    last_column = _column_name(len(headers) - 1)
    overall_last_column = _column_name(len(overall_headers) - 1)
    report_last_column = _column_name(max(len(headers), len(overall_headers)) - 1)

    _merge_and_write(sheet, f"A2:{report_last_column}2", f"{payload.get('brs_name') or 'BRD'} Estimation Report")
    sheet["A3"] = "QA support included"
    sheet["B3"] = "Yes" if qa_support else "No"

    overall_title_row = 6
    overall_header_row = overall_title_row + 1
    overall_value_row = overall_title_row + 2
    _merge_and_write(sheet, f"A{overall_title_row}:{report_last_column}{overall_title_row}", "Overall Effort")
    for col, header in enumerate(overall_headers, 1):
        sheet.cell(overall_header_row, col, header)

    detailed_title_row = overall_value_row + 2
    detailed_header_row = detailed_title_row + 1
    _merge_and_write(sheet, f"A{detailed_title_row}:{last_column}{detailed_title_row}", "Detailed Effort Module Wise")
    for col, header in enumerate(headers, 1):
        sheet.cell(detailed_header_row, col, header)

    data_start = detailed_header_row + 1
    data_end = data_start + len(rows) - 1

    for row_index, estimate_row in enumerate(rows, data_start):
        for col_index, key in enumerate(keys, 1):
            sheet.cell(row_index, col_index, _as_number(estimate_row.get(key)))
        sheet.cell(row_index, total_column_index + 1, f"=SUM(C{row_index}:{_column_name(total_column_index - 1)}{row_index})")
        sheet.cell(row_index, len(headers), estimate_row.get("comments") or "")

    if rows:
        # Merge only contiguous parent-module cells; effort and comments remain
        # row-level so each submodule keeps its own estimate and rationale.
        group_start = 0
        for index in range(1, len(rows) + 1):
            same_module = (
                index < len(rows)
                and str(rows[index].get("module", "")).casefold()
                == str(rows[group_start].get("module", "")).casefold()
            )
            if same_module:
                continue
            if index - group_start > 1:
                start_row = data_start + group_start
                end_row = data_start + index - 1
                _merge_and_write(sheet, f"A{start_row}:A{end_row}", rows[group_start].get("module") or "")
                sheet[f"A{start_row}"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            group_start = index

    total_row = (data_end + 1) if rows else data_start
    _merge_and_write(sheet, f"A{total_row}:B{total_row}", "Total PD")
    for col_index in range(2, total_column_index + 1):
        column = _column_name(col_index)
        formula = f"=SUM({column}{data_start}:{column}{data_end})" if rows else "=0"
        sheet[f"{column}{total_row}"] = formula

    static_effort = {
        "PPE Deployment (PD)": overall.get("ppe_deployment_pd", 0),
        "Production Deployment (PD)": overall.get("production_deployment_pd", 0),
        "Post Production Support (PD)": overall.get("post_production_support_pd", 0),
        "Contingency Effort (PD)": overall.get("contingency_effort_pd", 0),
    }
    for col_index, header in enumerate(overall_headers, 1):
        sheet.cell(overall_value_row, col_index, static_effort.get(header))

    for index, _header in enumerate(module_effort_headers):
        source_column = _column_name(index + 2)
        target_column = _column_name(index)
        formula = f"=SUM({source_column}{data_start}:{source_column}{data_end})" if rows else "=0"
        sheet[f"{target_column}{overall_value_row}"] = formula

    full_total_column_index = overall_headers.index("Total PD")
    full_total_column = _column_name(full_total_column_index)
    full_total_previous_column = _column_name(full_total_column_index - 1)
    sheet[f"{full_total_column}{overall_value_row}"] = (
        f"=SUM(A{overall_value_row}:{full_total_previous_column}{overall_value_row})"
    )

    condition_title_row = total_row + 3
    _merge_and_write(sheet, f"A{condition_title_row}:{report_last_column}{condition_title_row}", "Conditions")
    _merge_and_write(
        sheet,
        f"A{condition_title_row + 1}:{report_last_column}{condition_title_row + 1}",
        "The estimates below depend on these conditions. Estimates may vary if information changes or a condition is not met.",
    )
    for index, condition in enumerate(conditions):
        row = condition_title_row + 2 + index
        _merge_and_write(sheet, f"A{row}:{report_last_column}{row}", f"{index + 1}. {condition}")

    # Title and metadata.
    _style_range(
        sheet,
        f"A2:{report_last_column}2",
        fill=_fill(WHITE),
        font=_font(size=16, bold=True),
        alignment=Alignment(horizontal="left", vertical="center"),
    )
    _style_range(sheet, "A3:B3", font=_font(), alignment=Alignment(vertical="center"))
    sheet["A3"].font = _font(bold=True)

    # Section bars and headers.
    section_style = {
        "fill": _fill(BLUE),
        "font": _font(size=11, bold=True, color=WHITE),
        "alignment": Alignment(vertical="center"),
    }
    _style_range(sheet, f"A{overall_title_row}:{report_last_column}{overall_title_row}", **section_style)
    _style_range(sheet, f"A{detailed_title_row}:{last_column}{detailed_title_row}", **section_style)
    _style_range(sheet, f"A{condition_title_row}:{report_last_column}{condition_title_row}", **section_style)
    _style_range(
        sheet,
        f"A{overall_header_row}:{overall_last_column}{overall_header_row}",
        fill=_fill(LIGHT_BLUE),
        font=_font(bold=True),
        alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
        border=_all_borders("thin", MID_BLUE),
    )
    _style_range(
        sheet,
        f"A{detailed_header_row}:{last_column}{detailed_header_row}",
        fill=_fill(BLUE),
        font=_font(bold=True, color=WHITE),
        alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
        border=_outside_borders(),
    )

    # Overall values and detailed body.
    _style_range(
        sheet,
        f"A{overall_value_row}:{overall_last_column}{overall_value_row}",
        font=_font(),
        alignment=Alignment(horizontal="right", vertical="center"),
        border=_all_borders(),
        number_format="0.0",
    )
    sheet[f"{full_total_column}{overall_value_row}"].font = _font(bold=True)
    if rows:
        _style_range(
            sheet,
            f"A{data_start}:{last_column}{data_end}",
            font=_font(),
            alignment=Alignment(vertical="center", wrap_text=True),
            border=_all_borders(),
        )
        _style_range(
            sheet,
            f"C{data_start}:{total_column}{data_end}",
            number_format="0.0",
            alignment=Alignment(horizontal="right", vertical="center"),
        )
    _style_range(
        sheet,
        f"A{total_row}:{last_column}{total_row}",
        fill=_fill(LIGHT_BLUE),
        font=_font(bold=True),
        alignment=Alignment(vertical="center"),
        border=_bottom_border(),
    )
    _style_range(sheet, f"C{total_row}:{total_column}{total_row}", number_format="0.0")
    _style_range(
        sheet,
        f"A{condition_title_row + 1}:{report_last_column}{condition_title_row + 1 + len(conditions)}",
        font=_font(),
        alignment=Alignment(vertical="top", wrap_text=True),
    )

    # Column widths and row heights match the existing workbook layout.
    sheet.column_dimensions["A"].width = 26
    sheet.column_dimensions["B"].width = 28
    for col_index in range(3, len(headers) + 1):
        sheet.column_dimensions[_column_name(col_index - 1)].width = 15
    sheet.column_dimensions[comments_column].width = 48
    for col_index in range(len(headers) + 1, len(overall_headers) + 1):
        sheet.column_dimensions[_column_name(col_index - 1)].width = 18
    sheet.row_dimensions[2].height = 26
    sheet.row_dimensions[overall_header_row].height = 32
    sheet.row_dimensions[detailed_header_row].height = 32
    sheet.freeze_panes = f"C{data_start}"

    # Excel will calculate all formulas when the workbook is opened.
    workbook.calculation.calcMode = "auto"
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: workbook_builder.py input.json output.xlsx")
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Workbook payload must be a JSON object")
    build_workbook(payload, output_path)


if __name__ == "__main__":
    main()
