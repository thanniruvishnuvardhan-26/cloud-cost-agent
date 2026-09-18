# Evaluator Evidence Map — Cloud Cost Optimization Agent
**Phase 13: Demo Preparation**  
**Role:** Member 4 — Data + QA + Integration + Evaluation Lead

This document maps all critical architectural, safety, verification, and truthfulness claims directly to deterministic repository evidence, including test files, test class/method names, schema definitions, and fixtures.

---

## 1. Evaluator Claims & Repository Evidence Matrix

| # | Evaluator Claim | Exact Repository Evidence | Current Implementation Status |
|---|---|---|---|
| **1** | **Deterministic Test Fixtures** | - `tests/fixtures/underutilized_service.json`<br>- `tests/fixtures/rising_traffic.json`<br>- `tests/fixtures/stale_observation.json`<br>- `tests/fixtures/failed_action.json`<br>- `tests/fixtures/safety_violations.json`<br>- `tests/test_regression.py::TestDataFixturesRegression` (8 tests) | **Implemented & Verified**<br>All 5 fixtures pass JSON parsing, schema conformance, and semantic validation deterministically. |
| **2** | **Safety Constraints (7 Rules)** | - `tests/fixtures/safety_violations.json`<br>- `backend/schemas/safety.py::SafetyCheckResult`<br>- `tests/unit/test_safety.py`<br>- `tests/test_regression.py::TestSafetyRegression` | **Contract-Tested**<br>All 7 safety scenarios (`below_minimum`, `above_maximum`, `latency`, `unhealthy`, `stale_data`, `missing_metric`, `invalid_action`) are formally specified.<br>*Production Gap:* `backend/safety/` engine missing. |
| **3** | **Safety Bypass Prevention** | - `backend/schemas/workflow.py::VerificationResult` (requires `safety_check: SafetyCheckResult`)<br>- `tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_1_no_safety_approval_no_execution`<br>- `tests/integration/test_orchestration.py::test_orchestrator_blocks_execution_on_safety_failure` | **Contract-Tested**<br>Workflow report rejects schema validation if safety check is omitted. An unapproved safety result forces `execution=None`.<br>*Production Gap:* Orchestrator pipeline missing. |
| **4** | **Execution Failure Handling** | - `tests/fixtures/failed_action.json`<br>- `backend/schemas/execution.py::ExecutionResult`<br>- `backend/schemas/execution.py::ExecutionStatus` (`SUCCESS`, `FAILURE`)<br>- `tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_2_execution_failure_never_verified_success`<br>- `tests/scenarios/test_failure_cases.py::test_execution_failure_handling` | **Implemented & Verified**<br>Execution failure captures `error_code="capacity_unavailable"`, sets `new_state_version=None`, and strictly prevents `is_successful=True`. |
| **5** | **Verification Failure Handling (Phantom Success Prevention)** | - `backend/schemas/workflow.py::VerificationResult`<br>- `tests/unit/test_verification.py::test_execution_claims_success_but_state_not_updated_fails_verification`<br>- `tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_8_observed_state_outranks_execution_claim`<br>- `tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_3_execution_success_alone_never_verified_success` | **Implemented & Verified**<br>When execution driver reports success but observed instances remain unchanged, verification declares `is_successful=False`. |
| **6** | **Stale-Data Protection** | - `tests/fixtures/stale_observation.json`<br>- `tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_6_stale_critical_telemetry_no_risky_action_claim`<br>- `tests/scenarios/test_failure_cases.py::test_stale_data_rejection` | **Implemented & Verified**<br>150-minute-old observation (`v1.0.0-0800`) is rejected against current cluster version (`v1.0.0-1030`). Action permitted is explicitly `False`. |
| **7** | **Missing-Data Fail-Closed Behavior** | - `backend/schemas/metrics.py::ServiceObservation`<br>- `tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_7_missing_critical_telemetry_fails_closed`<br>- `tests/unit/test_safety.py::test_missing_cpu_fails_closed` | **Implemented & Verified**<br>Missing or `None` values for critical fields (`service_id`, `cpu_utilization_percent`) trigger strict Pydantic `ValidationError` and fail closed. |
| **8** | **LLM Output & Proposal Validation** | - `backend/schemas/actions.py::ActionProposal`<br>- `backend/schemas/actions.py::InfrastructureAction`<br>- `tests/unit/test_agent_contract.py` (42 tests)<br>- `tests/test_regression.py::TestAgentContractRegression` (11 tests) | **Implemented & Verified**<br>Rejects unauthorized actions (`terminate_cluster`, `drop_db`), confidence $< 0$ or $> 1$, string confidence, missing version, and malformed JSON payloads. |
| **9** | **API Contracts** | - `tests/integration/test_api.py` (29 tests)<br>- `tests/test_regression.py::TestAPIRegression` (6 tests) | **Contract-Tested**<br>Defines expected contracts for `GET /health`, `GET /services`, `POST /actions/validate`, `POST /actions/execute`, `POST /actions/verify`, `GET /audit`.<br>*Production Gap:* FastAPI app in `backend/main.py` missing. |
| **10** | **Orchestration Ordering (7 Stages)** | - `backend/schemas/workflow.py::WorkflowReport`<br>- `tests/integration/test_orchestration.py` (27 tests)<br>- `tests/test_regression.py::TestOrchestrationRegression::test_7_stage_workflow_schema_assembly` | **Contract-Tested**<br>Assembly validates: Investigation $\rightarrow$ Decision $\rightarrow$ Safety $\rightarrow$ Execution $\rightarrow$ Verification $\rightarrow$ Audit $\rightarrow$ Final Report.<br>*Production Gap:* Workflow orchestrator runner missing. |
| **11** | **UI Truthfulness & Distinct Outcome States** | - `tests/browser/test_cloud_cost_ui.py` (17 tests)<br>- `tests/test_regression.py::TestBrowserUITruthfulnessRegression` (8 tests) | **Contract-Tested**<br>Enforces 4 distinct states: `VERIFIED_SUCCESS`, `BLOCKED`, `EXECUTION_FAILED`, `VERIFICATION_FAILURE`. Blocked or failed states can never display SUCCESS. HTTP 200 alone cannot trigger success banner.<br>*Production Gap:* Web frontend in `frontend/` missing. |
| **12** | **Deterministic Regression Suite** | - `tests/test_regression.py` (115 tests)<br>- `tests/test_regression.py::TestCriticalRegressionInvariants` (10 tests) | **Implemented & Verified**<br>Consolidates all 11 coverage areas; 95 passing tests, 20 documented production gap tests, 10/10 invariant passes. Zero flaky or clock-dependent assertions. |

---

## 2. Invariant Rules to Test Methods Mapping

| Invariant Rule | Summary | Test Class & Method | Status |
|---|---|---|---|
| **RULE 1** | No safety approval $\rightarrow$ no execution | `TestCriticalRegressionInvariants::test_rule_1_no_safety_approval_no_execution` | **PASS** |
| **RULE 2** | Execution failure $\rightarrow$ never verified success | `TestCriticalRegressionInvariants::test_rule_2_execution_failure_never_verified_success` | **PASS** |
| **RULE 3** | Execution SUCCESS alone $\rightarrow$ never verified success | `TestCriticalRegressionInvariants::test_rule_3_execution_success_alone_never_verified_success` | **PASS** |
| **RULE 4** | Expected effect text alone $\rightarrow$ never verified success | `TestCriticalRegressionInvariants::test_rule_4_expected_effect_text_alone_never_verified_success` | **PASS** |
| **RULE 5** | HTTP 200 alone $\rightarrow$ never verified success | `TestCriticalRegressionInvariants::test_rule_5_http_200_alone_never_verified_success` | **PASS** |
| **RULE 6** | Stale telemetry $\rightarrow$ no risky action claim | `TestCriticalRegressionInvariants::test_rule_6_stale_critical_telemetry_no_risky_action_claim` | **PASS** |
| **RULE 7** | Missing critical telemetry $\rightarrow$ fail closed | `TestCriticalRegressionInvariants::test_rule_7_missing_critical_telemetry_fails_closed` | **PASS** |
| **RULE 8** | Observed state outranks execution claim | `TestCriticalRegressionInvariants::test_rule_8_observed_state_outranks_execution_claim` | **PASS** |
| **RULE 9** | Blocked action remains BLOCKED | `TestCriticalRegressionInvariants::test_rule_9_blocked_action_remains_blocked_never_success` | **PASS** |
| **RULE 10**| No_action does not claim mutation | `TestCriticalRegressionInvariants::test_rule_10_no_action_does_not_claim_infrastructure_mutation` | **PASS** |
