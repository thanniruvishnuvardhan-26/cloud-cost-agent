# Evaluator Walkthrough — Cloud Cost Optimization Agent
**Phase 14: Evaluator Preparation**  
**Role:** Member 4 — Data + QA + Integration + Evaluation Lead

---

## Overview for Hackathon Evaluators

This walkthrough provides a structured, step-by-step sequence for evaluating the Cloud Cost Optimization Agent repository. In accordance with the Project Truthfulness Rules, this guide explains exactly what evidence to inspect, where contracts and schemas are enforced, and how to verify our deterministic test suite.

---

## Step-by-Step Evaluation Sequence

### Step 1: Read the Project Context & Overview
- **Action:** Open `README.md` and `docs/testing/EVALUATOR_GUIDE.md`.
- **What to Look For:**
  - The problem formulation: autonomous cloud cost reduction while safeguarding infrastructure against unconstrained LLM write mutations.
  - The 7-stage architectural workflow: Request $\rightarrow$ Investigation $\rightarrow$ Decision $\rightarrow$ Safety $\rightarrow$ Execution $\rightarrow$ Verification $\rightarrow$ Audit.
  - The core design distinction: **Execution SUCCESS $\ne$ Verified SUCCESS**.

### Step 2: Inspect the Primary Test Fixture
- **Action:** Open [tests/fixtures/underutilized_service.json](file:///d:/Branches/Pragyaan/cloud-cost-agent/tests/fixtures/underutilized_service.json).
- **What to Look For:**
  - `service.service_id`: `"reports-worker"`.
  - `service.instances`: `4` (Min: `1`, Max: `6`).
  - `observation`: `traffic_rpm = 0`, `cpu_utilization_percent = 9.0%`, `cost_per_hour = 11.0`.
  - `expected_behavior`: `expected_action = "scale_down"`, `expected_scale_down_target = 1`.
  - `expected_behavior.cost_impact`: previous cost $11.00/hr, expected cost $2.75/hr (75% savings).
  - This fixture anchors the primary P3 golden demo scenario.

### Step 3: Inspect Safety Tests & Guardrail Specifications
- **Action:** Open [tests/fixtures/safety_violations.json](file:///d:/Branches/Pragyaan/cloud-cost-agent/tests/fixtures/safety_violations.json) and [tests/unit/test_safety.py](file:///d:/Branches/Pragyaan/cloud-cost-agent/tests/unit/test_safety.py).
- **What to Look For:**
  - 7 explicit safety violation scenarios:
    1. `below_minimum_capacity` (target 0 < min 1)
    2. `above_maximum_capacity` (target 10 > max 6)
    3. `latency_violation` (latency 1250ms > 500ms threshold)
    4. `unhealthy_service` (`healthy = False`)
    5. `stale_data` (age 90m > 15m threshold)
    6. `missing_metric_data` (`cpu_percent` is null; fails closed)
    7. `invalid_action` (action `"terminate_cluster"` rejected)
  - Verify that tests assert `is_approved = False` and that blocked actions never mutate infrastructure.

### Step 4: Inspect Independent Verification Tests
- **Action:** Open [tests/unit/test_verification.py](file:///d:/Branches/Pragyaan/cloud-cost-agent/tests/unit/test_verification.py).
- **What to Look For:**
  - `test_execution_claims_success_but_state_not_updated_fails_verification`: Demonstrates that if execution returns success but instances remain at 4, verification declares `is_successful = False`.
  - `test_verification_result_has_no_mock_shortcuts`: Confirms verification does not accept synthetic bypasses.
  - `test_workflow_report_embeds_complete_audit_trail`: Confirms the 7-stage trace is serialized in `WorkflowReport`.

### Step 5: Inspect Failure Mode Tests
- **Action:** Open [tests/scenarios/test_failure_cases.py](file:///d:/Branches/Pragyaan/cloud-cost-agent/tests/scenarios/test_failure_cases.py).
- **What to Look For:**
  - Handling of provider errors (`capacity_unavailable` in `failed_action.json`).
  - Handling of stale data (150-minute age in `stale_observation.json`).
  - Handling of surging traffic (`rising_traffic.json` enforcing `must_not_scale_down`).
  - Fail-closed handling when observations lack critical fields.

### Step 6: Run and Inspect the Consolidated Regression Suite
- **Action:** Run the regression test command in the terminal:
  ```powershell
  python -m unittest tests.test_regression -v
  ```
- **What to Look For:**
  - Execution runs in ~0.1 seconds without requiring internet access or cloud credentials.
  - **95 tests pass**, protecting fixtures, schemas, verification logic, agent contracts, orchestration ordering, and UI truthfulness.
  - **20 tests fail as explicit, documented Production Gaps** (e.g. `AssertionError: Production Gap: Simulator not implemented in backend.simulator`).
  - Inspect `tests/test_regression.py::TestCriticalRegressionInvariants`: All 10 invariant rules pass deterministically in 0.001s.

### Step 7: Review the Demo Script and Checklist
- **Action:** Open [docs/testing/DEMO_SCRIPT.md](file:///d:/Branches/Pragyaan/cloud-cost-agent/docs/testing/DEMO_SCRIPT.md) and [docs/testing/DEMO_CHECKLIST.md](file:///d:/Branches/Pragyaan/cloud-cost-agent/docs/testing/DEMO_CHECKLIST.md).
- **What to Look For:**
  - Evaluator-friendly 10-step narrative covering Opening, Input, Investigation, Decision, Safety, Execution, Verification, Cost Impact, Failure Demo, and Closing.
  - The 12 Demo Truthfulness Rules enforcing that BLOCKED is never SUCCESS, HTTP 200 alone is never verified success, and missing components are documented honestly.

### Step 8: Review Current Implementation Status & Readiness
- **Action:** Open [docs/testing/CURRENT_STATUS.md](file:///d:/Branches/Pragyaan/cloud-cost-agent/docs/testing/CURRENT_STATUS.md) and [docs/testing/DEMO_READINESS.md](file:///d:/Branches/Pragyaan/cloud-cost-agent/docs/testing/DEMO_READINESS.md).
- **What to Look For:**
  - Transparent separation between **Implemented/Verified** (schemas, fixtures, verification logic, invariants), **Contract-Tested** (E2E workflows, orchestration ordering, UI presentation contracts), and **Production Gaps** (backend simulator, safety engine, API server, agent loop, frontend UI).
