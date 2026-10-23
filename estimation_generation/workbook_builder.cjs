"use strict";

const fs = require("node:fs/promises");
const { SpreadsheetFile, Workbook } = require("@oai/artifact-tool");

function columnName(index) {
  let value = index + 1;
  let name = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    name = String.fromCharCode(65 + remainder) + name;
    value = Math.floor((value - 1) / 26);
  }
  return name;
}

async function main() {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) throw new Error("Usage: workbook_builder.cjs input.json output.xlsx");
  const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
  const qaSupport = Boolean(payload.qa_support);
  const headers = ["Module", "Submodule", "Analysis (PD)", "Development (PD)", "Unit Testing (PD)", "Functional Testing (PD)"];
  const keys = ["module", "submodule", "analysis_pd", "development_pd", "unit_testing_pd", "functional_testing_pd"];
  if (qaSupport) {
    headers.push("QA Deployment (PD)", "QA Testing (PD)");
    keys.push("qa_deployment_pd", "qa_testing_pd");
  }
  headers.push("QA Bugfixing (PD)", "Total PD", "Comments");
  keys.push("qa_bugfixing_pd");

  const totalColumnIndex = headers.indexOf("Total PD");
  const totalColumn = columnName(totalColumnIndex);
  const commentsColumn = columnName(headers.indexOf("Comments"));
  const moduleEffortHeaders = headers.slice(2, totalColumnIndex);
  const overall = payload.overall_effort || {};
  const overallHeaders = [
    ...moduleEffortHeaders,
    "PPE Deployment (PD)",
    "Production Deployment (PD)",
    "Post Production Support (PD)",
    "Contingency Effort (PD)",
    "Total PD",
  ];

  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("Estimation");
  sheet.showGridLines = false;
  sheet.tabColor = "#1F4E78";
  const lastColumn = columnName(headers.length - 1);
  const overallLastColumn = columnName(overallHeaders.length - 1);
  const reportLastColumn = columnName(Math.max(headers.length, overallHeaders.length) - 1);
  sheet.mergeCells(`A2:${reportLastColumn}2`);
  sheet.getRange("A2").values = [[`${payload.brs_name || "BRD"} Estimation Report`]];
  sheet.getRange("A3").values = [["QA support included", qaSupport ? "Yes" : "No"]];

  const overallTitleRow = 6;
  const overallHeaderRow = overallTitleRow + 1;
  const overallValueRow = overallTitleRow + 2;
  sheet.mergeCells(`A${overallTitleRow}:${reportLastColumn}${overallTitleRow}`);
  sheet.getRange(`A${overallTitleRow}`).values = [["Overall Effort"]];
  sheet.getRange(`A${overallHeaderRow}:${overallLastColumn}${overallHeaderRow}`).values = [overallHeaders];

  const detailedTitleRow = overallValueRow + 2;
  const detailedHeaderRow = detailedTitleRow + 1;
  sheet.mergeCells(`A${detailedTitleRow}:${lastColumn}${detailedTitleRow}`);
  sheet.getRange(`A${detailedTitleRow}`).values = [["Detailed Effort Module Wise"]];
  sheet.getRange(`A${detailedHeaderRow}:${lastColumn}${detailedHeaderRow}`).values = [headers];
  const dataStart = detailedHeaderRow + 1;
  const rows = payload.rows || [];
  const dataEnd = dataStart + rows.length - 1;
  const pdStartColumn = "C";
  const pdEndColumn = columnName(totalColumnIndex - 1);
  const matrix = rows.map((row, rowIndex) => {
    const values = keys.map((key) => row[key] == null ? "" : row[key]);
    values.push(null);
    values.push(row.comments || "");
    return values;
  });
  if (matrix.length) {
    sheet.getRange(`A${dataStart}:${lastColumn}${dataEnd}`).values = matrix;
    const formulas = rows.map((_row, index) => [`=SUM(${pdStartColumn}${dataStart + index}:${pdEndColumn}${dataStart + index})`]);
    sheet.getRange(`${totalColumn}${dataStart}:${totalColumn}${dataEnd}`).formulas = formulas;

    // Show one parent module cell spanning all of its contiguous submodule
    // rows. The remaining PD and comment cells deliberately stay row-level.
    let groupStart = 0;
    for (let index = 1; index <= rows.length; index += 1) {
      if (
        index !== rows.length
        && String(rows[index].module).toLocaleLowerCase() === String(rows[groupStart].module).toLocaleLowerCase()
      ) continue;
      if (index - groupStart > 1) {
        const startRow = dataStart + groupStart;
        const endRow = dataStart + index - 1;
        sheet.mergeCells(`A${startRow}:A${endRow}`);
        const moduleCell = sheet.getRange(`A${startRow}`);
        moduleCell.format.horizontalAlignment = "center";
        moduleCell.format.verticalAlignment = "center";
      }
      groupStart = index;
    }
  }
  const totalRow = dataEnd + 1;
  sheet.getRange(`A${totalRow}:B${totalRow}`).merge();
  sheet.getRange(`A${totalRow}`).values = [["Total PD"]];
  for (let col = 2; col <= totalColumnIndex; col += 1) {
    const column = columnName(col);
    sheet.getRange(`${column}${totalRow}`).formulas = [[`=SUM(${column}${dataStart}:${column}${dataEnd})`]];
  }

  const overallStaticEffort = {
    "PPE Deployment (PD)": overall.ppe_deployment_pd ?? 0,
    "Production Deployment (PD)": overall.production_deployment_pd ?? 0,
    "Post Production Support (PD)": overall.post_production_support_pd ?? 0,
    "Contingency Effort (PD)": overall.contingency_effort_pd ?? 0,
  };
  sheet.getRange(`A${overallValueRow}:${overallLastColumn}${overallValueRow}`).values = [[
    ...overallHeaders.map((header) => overallStaticEffort[header] ?? null),
  ]];
  moduleEffortHeaders.forEach((_, index) => {
    const sourceColumn = columnName(index + 2);
    const targetColumn = columnName(index);
    sheet.getRange(`${targetColumn}${overallValueRow}`).formulas = [[`=SUM(${sourceColumn}${dataStart}:${sourceColumn}${dataEnd})`]];
  });
  const fullTotalColumnIndex = overallHeaders.indexOf("Total PD");
  const fullTotalColumn = columnName(fullTotalColumnIndex);
  const fullTotalPreviousColumn = columnName(fullTotalColumnIndex - 1);
  sheet.getRange(`${fullTotalColumn}${overallValueRow}`).formulas = [[`=SUM(A${overallValueRow}:${fullTotalPreviousColumn}${overallValueRow})`]];

  const conditionTitleRow = totalRow + 3;
  sheet.mergeCells(`A${conditionTitleRow}:${reportLastColumn}${conditionTitleRow}`);
  sheet.getRange(`A${conditionTitleRow}`).values = [["Conditions"]];
  sheet.mergeCells(`A${conditionTitleRow + 1}:${reportLastColumn}${conditionTitleRow + 1}`);
  sheet.getRange(`A${conditionTitleRow + 1}`).values = [["The estimates below depend on these conditions. Estimates may vary if information changes or a condition is not met."]];
  (payload.conditions || []).forEach((condition, index) => {
    const row = conditionTitleRow + 2 + index;
    sheet.mergeCells(`A${row}:${reportLastColumn}${row}`);
    sheet.getRange(`A${row}`).values = [[`${index + 1}. ${condition}`]];
  });

  const title = sheet.getRange(`A2:${reportLastColumn}2`);
  title.format = { fill: "#FFFFFF", font: { name: "Aptos", size: 16, bold: true, color: "#000000" }, horizontalAlignment: "left", verticalAlignment: "center" };
  sheet.getRange("A3:B3").format = { font: { name: "Aptos", size: 10 }, verticalAlignment: "center" };
  sheet.getRange("A3").format.font = { name: "Aptos", size: 10, bold: true, color: "#000000" };
  sheet.getRange(`A${overallTitleRow}:${reportLastColumn}${overallTitleRow}`).format = { fill: "#1F4E78", font: { name: "Aptos", size: 11, bold: true, color: "#FFFFFF" }, verticalAlignment: "center" };
  sheet.getRange(`A${overallHeaderRow}:${overallLastColumn}${overallHeaderRow}`).format = { fill: "#D9EAF7", font: { name: "Aptos", size: 10, bold: true, color: "#000000" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: "#9ABAD0" } };
  sheet.getRange(`A${overallValueRow}:${overallLastColumn}${overallValueRow}`).format = { font: { name: "Aptos", size: 10, color: "#000000" }, horizontalAlignment: "right", verticalAlignment: "center", borders: { preset: "all", style: "thin", color: "#D9D9D9" } };
  sheet.getRange(`A${overallValueRow}:${overallLastColumn}${overallValueRow}`).format.numberFormat = "0.0";
  sheet.getRange(`${fullTotalColumn}${overallValueRow}`).format.font = { name: "Aptos", size: 10, bold: true, color: "#000000" };
  sheet.getRange(`A${detailedTitleRow}:${lastColumn}${detailedTitleRow}`).format = { fill: "#1F4E78", font: { name: "Aptos", size: 11, bold: true, color: "#FFFFFF" }, verticalAlignment: "center" };
  const header = sheet.getRange(`A${detailedHeaderRow}:${lastColumn}${detailedHeaderRow}`);
  header.format = { fill: "#1F4E78", font: { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "outside", style: "thin", color: "#FFFFFF" } };
  if (rows.length) {
    const body = sheet.getRange(`A${dataStart}:${lastColumn}${dataEnd}`);
    body.format.font = { name: "Aptos", size: 10, color: "#000000" };
    body.format.verticalAlignment = "center";
    body.format.borders = { preset: "inside", style: "thin", color: "#D9D9D9" };
    sheet.getRange(`C${dataStart}:${totalColumn}${dataEnd}`).format.numberFormat = "0.0";
  }
  const totals = sheet.getRange(`A${totalRow}:${lastColumn}${totalRow}`);
  totals.format = { fill: "#D9EAF7", font: { name: "Aptos", size: 10, bold: true, color: "#000000" }, verticalAlignment: "center", borders: { preset: "doubleBottom", style: "medium", color: "#1F4E78" } };
  sheet.getRange(`C${totalRow}:${totalColumn}${totalRow}`).format.numberFormat = "0.0";
  sheet.getRange(`A${conditionTitleRow}:${reportLastColumn}${conditionTitleRow}`).format = { fill: "#1F4E78", font: { name: "Aptos", size: 11, bold: true, color: "#FFFFFF" }, verticalAlignment: "center" };
  sheet.getRange(`A${conditionTitleRow + 1}:${reportLastColumn}${conditionTitleRow + 1 + (payload.conditions || []).length}`).format = { font: { name: "Aptos", size: 10, color: "#000000" }, wrapText: true, verticalAlignment: "top" };
  sheet.getRange(`A1:${reportLastColumn}${conditionTitleRow + 1 + (payload.conditions || []).length}`).format.wrapText = true;
  sheet.getRange(`A1:${reportLastColumn}${conditionTitleRow + 1 + (payload.conditions || []).length}`).format.autofitRows();
  sheet.getRange("A:A").format.columnWidth = 26;
  sheet.getRange("B:B").format.columnWidth = 28;
  for (let col = 2; col < headers.length; col += 1) sheet.getRange(`${columnName(col)}:${columnName(col)}`).format.columnWidth = 15;
  sheet.getRange(`${commentsColumn}:${commentsColumn}`).format.columnWidth = 48;
  for (let col = headers.length; col < overallHeaders.length; col += 1) sheet.getRange(`${columnName(col)}:${columnName(col)}`).format.columnWidth = 18;
  sheet.getRange(`A2:${reportLastColumn}2`).format.rowHeight = 26;
  sheet.getRange(`A${overallHeaderRow}:${overallLastColumn}${overallHeaderRow}`).format.rowHeight = 32;
  sheet.getRange(`A${detailedHeaderRow}:${lastColumn}${detailedHeaderRow}`).format.rowHeight = 32;
  sheet.freezePanes.freezeRows(detailedHeaderRow);
  sheet.freezePanes.freezeColumns(2);
  workbook.recalculate();
  await fs.mkdir(require("node:path").dirname(outputPath), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
}

main().catch((error) => { console.error(error); process.exit(1); });
