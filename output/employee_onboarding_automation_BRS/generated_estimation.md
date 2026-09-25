# BRD Delivery Estimation

**BRD:** employee_onboarding_automation_BRS

## Scoring Summary

Scores increase with delivery effort or risk. For requirement clarity, a higher score means greater ambiguity or incompleteness.

| Factor | Weight | Score | Weighted contribution |
| --- | ---: | ---: | ---: |
| Functional complexity | 20% | 3 | 0.60 |
| Technical complexity | 25% | 4 | 1.00 |
| Integration impact | 15% | 3 | 0.45 |
| Testing effort | 15% | 4 | 0.60 |
| Requirement clarity | 10% | 2 | 0.20 |
| Risk and dependency | 15% | 4 | 0.60 |

## Final Complexity Score

**3.45 / 5.00**

## Functional complexity

**Assigned score:** 3 / 5

**Justification:** The evidence lists 8 explicit business rules (EQ001) and 12 functional capabilities (FR-001 to FR-012). These indicate multiple decision points, document handling, workflow routing, and reporting features. However, there is no explicit count of UI screens/pages or APIs/integrations, creating uncertainty about the total number of UI components and service interfaces, which keeps the overall complexity at a moderate level.

**Evidence observations:**
- EQ001 contains eight distinct business rules governing document presence, approvals, timestamps, and reminders.
- EQ003 enumerates twelve functional requirements covering request creation, document upload, validation, task assignment, notifications, search, reporting, and audit history.

## Technical complexity

**Assigned score:** 4 / 5

**Justification:** The requirements imply building a new end‑to‑end onboarding solution (no mention of existing code to modify). Required technical elements include document storage and preview, workflow engine, role‑based security, email notification service, audit logging, and reporting. The breadth of new components and the need to integrate with multiple internal domains (HR, Compliance, IT, Facilities) raise the technical effort.

**Evidence observations:**
- Functional requirements (FR‑001 to FR‑012) call for capabilities such as document upload, workflow routing, audit history, and report generation.
- Non‑functional requirements (NFR‑004, NFR‑006) require corporate authentication, role‑based authorization, and comprehensive logging.

## Integration impact

**Assigned score:** 3 / 5

**Justification:** The solution must interact with several internal groups (HR Operations, Compliance, IT Access, Facilities) and send email notifications. While these are named dependencies, no external third‑party APIs or detailed integration contracts are described, limiting the integration scope to moderate.

**Evidence observations:**
- BR‑004 specifies routing onboarding tasks to HR Operations, Compliance, IT Access and Facilities.
- FR‑008 and AC‑006 reference email notifications triggered by onboarding events.

## Testing effort

**Assigned score:** 4 / 5

**Justification:** A comprehensive set of acceptance criteria (10 AC items) covers happy‑path flows, validation errors, workflow routing, decision recording, notifications, and audit visibility. Additional testing dimensions such as exception handling, regression, UAT, and automation are implied by the breadth of functional and non‑functional requirements, indicating a high testing effort.

**Evidence observations:**
- AC‑001 to AC‑010 provide explicit acceptance tests for request submission, document handling, validation, task assignment, decision recording, notifications, UI visibility, audit history, search, and hold handling.
- NFRs address performance, security, availability, and accessibility, all of which add testing dimensions.

## Requirement clarity

**Assigned score:** 2 / 5

**Justification:** The documentation supplies detailed business rules, functional requirements, and acceptance criteria, but lacks explicit information on UI screen counts, API specifications, and some wording appears inconsistent (e.g., references to "loan application" in AC‑006, AC‑007, AC‑009, AC‑010). These gaps introduce ambiguity that could affect estimation accuracy.

**Evidence observations:**
- No explicit enumeration of UI pages or API endpoints is present in the evidence.
- Acceptance criteria AC‑006, AC‑007, AC‑009, and AC‑010 mention "loan application" which seems out of context for an employee onboarding solution.

## Risk and dependency

**Assigned score:** 4 / 5

**Justification:** The solution depends on multiple internal stakeholders (HR, Compliance, IT, Facilities) and must satisfy stringent security, privacy, and audit requirements. Ambiguities in integration details and UI specifications increase the risk of scope changes or rework, elevating overall dependency risk.

**Evidence observations:**
- BR‑004 and EQ001 define routing and approval rules that involve several internal groups.
- NFR‑004 (security) and NFR‑005 (privacy) impose strict compliance constraints.
- Missing details on integration mechanisms and UI design create uncertainty.
