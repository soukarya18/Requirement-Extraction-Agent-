# BRD Delivery Estimation

**BRD:** loan_processing_automation_BRS

## Scoring Summary

Scores increase with delivery effort or risk. For requirement clarity, a higher score means greater ambiguity or incompleteness.

| Factor | Weight | Score | Weighted contribution |
| --- | ---: | ---: | ---: |
| Functional complexity | 20% | 4 | 0.80 |
| Technical complexity | 25% | 4 | 1.00 |
| Integration impact | 15% | 2 | 0.30 |
| Testing effort | 15% | 4 | 0.60 |
| Requirement clarity | 10% | 3 | 0.30 |
| Risk and dependency | 15% | 4 | 0.60 |

## Final Complexity Score

**3.60 / 5.00**

## Functional complexity

**Assigned score:** 4 / 5

**Justification:** The evidence lists ten explicit business rules (BR-001 to BR-010) and twelve functional capabilities (FR-001 to FR-012), indicating many distinct workflows (e.g., creation, validation, routing, decision recording, notifications, search, reporting). No explicit count of UI pages or APIs is provided, creating uncertainty, but the breadth of rules and capabilities suggests a substantial functional scope.

**Evidence observations:**
- BR-001 to BR-010 enumerate ten distinct business rules covering notifications, view permissions, audit history, search, hold logic, etc.
- FR-001 to FR-012 describe twelve functional capabilities such as create/edit, document handling, validation, task assignment, decision recording, UI display, email notifications, search, reporting, export, and audit capture.

## Technical complexity

**Assigned score:** 4 / 5

**Justification:** The requirements imply a new web‑based solution with immutable audit storage, configurable routing, document management, and reporting. No existing codebase is referenced, so design and implementation must be built from scratch, increasing technical effort. The need to support concurrency (500 users) and strict performance (3‑second response) adds further technical depth.

**Evidence observations:**
- FR‑001 to FR‑012 require new capabilities such as draft handling, document upload/classify, validation, workflow task assignment, and audit history.
- NFR‑002 and NFR‑003 specify performance and capacity targets that affect architecture and scalability decisions.

## Integration impact

**Assigned score:** 2 / 5

**Justification:** Only email notifications are explicitly mentioned (FR‑008, AC‑006) as an integration point, and there is no detailed description of external systems, APIs, or data feeds. The lack of named internal or external dependencies suggests limited integration effort.

**Evidence observations:**
- FR‑008 and AC‑006 refer to sending email notifications based on workflow events.
- No explicit APIs, external services, or system‑to‑system interfaces are listed in the evidence.

## Testing effort

**Assigned score:** 4 / 5

**Justification:** Ten detailed acceptance criteria cover core functional paths, validation failures, routing, decision recording, notifications, UI visibility, audit history, search, and hold logic. Additionally, eight non‑functional requirements (availability, performance, capacity, security, privacy, auditability, retention, accessibility) introduce regression, performance, security, and accessibility testing dimensions, raising overall testing scope.

**Evidence observations:**
- AC‑001 to AC‑010 provide explicit acceptance tests for creation, document handling, validation, routing, decision capture, notifications, UI display, audit view, search, and hold handling.
- NFR‑001 to NFR‑008 introduce testing needs for availability, response time, concurrent users, role‑based security, data privacy, audit logging, data retention, and accessibility.

## Requirement clarity

**Assigned score:** 3 / 5

**Justification:** The BR, FR, AC, and NFR sections are largely complete, but there are gaps: no explicit screen/page count, no defined APIs, and a typo/reference to a non‑existent BR‑03 in AC‑003. These ambiguities reduce clarity and may lead to re‑work.

**Evidence observations:**
- Screen/page counts are not specified in any requirement.
- AC‑003 references "BR-03" which is not present in the BR list.
- Integration or API details are marked as null across FR entries.

## Risk and dependency

**Assigned score:** 4 / 5

**Justification:** Risks stem from undefined integration points (email service, document storage), missing UI specifications, and the typo in AC‑003 that could cause misinterpretation. The solution also depends on role‑based authentication and compliance with privacy regulations, adding dependency risk.

**Evidence observations:**
- Email notification dependency (FR‑008, AC‑006) without specifying the mail system.
- Document upload and classification (FR‑003) imply reliance on a storage subsystem not described.
- Reference error in AC‑003 (BR‑03) indicates potential ambiguity.
- NFR‑004 and NFR‑005 introduce security and privacy compliance dependencies.
