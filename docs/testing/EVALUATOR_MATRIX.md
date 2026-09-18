# Evaluator Matrix — Cloud Cost Optimization Agent
**Phase 14: Evaluator Preparation**  
**Role:** Member 4 — Data + QA + Integration + Evaluation Lead

---

## Factual Requirements & Evidence Matrix

This matrix provides an objective, evidence-backed evaluation of all system requirements. In compliance with project guidelines, no scores, rankings, grades, percentages, or subjective judgments are used. Statuses strictly reflect repository code, schema definitions, test suites, and test execution outcomes.

| # | Evaluation Requirement | Repository Evidence | Status | Notes |
|---|---|---|---|---|
| **1** | **Natural-Language Request** | `tests/scenarios/test_cloud_cost_e2e.py::test_full_workflow_happy_path_underutilized` | **Contract-tested** | Request string ingested and bound to workflow context. UI input form is missing. |
| **2** | **Service Inspection** | `backend/schemas/metrics.py::ServiceObservation`<br>`tests/fixtures/underutilized_service.json` | **Implemented** | Strictly validates CPU, memory, traffic, latency, and state version. |
| **3** | **Investigation** | `backend/schemas/workflow.py::InvestigationResult`<br>`tests/test_regression.py::TestOrchestrationRegression` | **Implemented** | Structures identified issues list and human-readable investigation summary. |
| **4** | **Action Proposal** | `backend/schemas/actions.py::ActionProposal`<br>`backend/schemas/actions.py::InfrastructureAction`<br>`tests/unit/test_agent_contract.py` | **Implemented** | Proposal models enforce action enums, target service IDs, and confidence ranges ($0.0 \le c \le 1.0$). |
| **5** | **Safety Enforcement** | `backend/schemas/safety.py::SafetyCheckResult`<br>`tests/fixtures/safety_violations.json`<br>`tests/unit/test_safety.py` | **Contract-tested** | All 7 safety rules defined in fixtures and test contracts. Safety engine in `backend/safety/` is missing. |
| **6** | **Safety Bypass Prevention** | `backend/schemas/workflow.py::VerificationResult`<br>`tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_1_no_safety_approval_no_execution` | **Contract-tested** | Schema strictly requires `safety_check`. If unapproved, execution remains `None`. |
| **7** | **Infrastructure Execution** | `backend/schemas/execution.py::ExecutionResult`<br>`tests/unit/test_simulator.py` | **Contract-tested** | `ExecutionResult` captures provider response. Simulator in `backend/simulator/` is missing. |
| **8** | **Post-Action Verification** | `backend/schemas/workflow.py::VerificationResult`<br>`tests/unit/test_verification.py`<br>`tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_8_observed_state_outranks_execution_claim` | **Implemented** | Operates independently of execution driver. Only confirms success when observed telemetry matches target state. |
| **9** | **Cost Impact** | `tests/fixtures/underutilized_service.json`<br>`tests/test_regression.py::TestDataFixturesRegression::test_underutilized_service_semantic_constraints` | **Contract-tested** | Hourly and monthly savings are derived strictly from verified fixture values ($11.00 $\rightarrow$ $2.75/hr). |
| **10** | **Audit / Activity Record** | `backend/schemas/workflow.py::WorkflowReport`<br>`tests/unit/test_verification.py` | **Implemented** | 7-stage trace serializes to immutable Pydantic `WorkflowReport` model. |
| **11** | **Stale Observation Handling** | `tests/fixtures/stale_observation.json`<br>`tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_6_stale_critical_telemetry_no_risky_action_claim` | **Implemented** | Observations older than threshold (150m > 15m) are blocked from execution; requires telemetry refresh. |
| **12** | **Failed Action Handling** | `tests/fixtures/failed_action.json`<br>`backend/schemas/execution.py::ExecutionResult`<br>`tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_2_execution_failure_never_verified_success` | **Implemented** | Captures provider error code (`capacity_unavailable`), sets `status=FAILURE`, and prevents verified success. |
| **13** | **Missing Data Handling** | `backend/schemas/metrics.py::ServiceObservation`<br>`tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_7_missing_critical_telemetry_fails_closed` | **Implemented** | Missing critical fields (`service_id`, `cpu_utilization_percent`) trigger immediate Pydantic validation error; fails closed. |
| **14** | **LLM Output Validation** | `backend/schemas/actions.py::ActionProposal`<br>`tests/unit/test_agent_contract.py` (42 tests) | **Implemented** | Rejects invalid actions, non-numeric confidence, out-of-range confidence, and malformed JSON output. |
| **15** | **API Contract** | `tests/integration/test_api.py` (29 tests)<br>`tests/test_regression.py::TestAPIRegression` | **Contract-tested** | Complete REST request/response contracts for 6 endpoints. FastAPI server in `backend/main.py` is missing. |
| **16** | **Orchestration Order** | `backend/schemas/workflow.py::WorkflowReport`<br>`tests/integration/test_orchestration.py` (27 tests) | **Contract-tested** | Strict 7-stage order enforced in report schemas. Workflow coordinator in `backend/orchestrator/` is missing. |
| **17** | **UI Truthfulness** | `tests/browser/test_cloud_cost_ui.py` (17 tests)<br>`tests/test_regression.py::TestBrowserUITruthfulnessRegression` | **Contract-tested** | 4 distinct outcome states enforced. Blocked and failed states can never display SUCCESS. React UI is missing. |
| **18** | **Regression Coverage** | `tests/test_regression.py` (115 tests)<br>`tests/test_regression.py::TestCriticalRegressionInvariants` | **Implemented** | Consolidates all 11 functional areas and 10 critical invariants; runs deterministically in < 0.1s. |
