# Demo QA Checklist — Cloud Cost Optimization Agent
**Phase 13: Demo Preparation**  
**Role:** Member 4 — Data + QA + Integration + Evaluation Lead

---

## 1. Complete Intended Demo Flow Checklist

This checklist defines the 11-step end-to-end autonomous cloud cost optimization workflow. For each step, it records expected behavior, required evidence, deterministic pass/fail criteria, and the factual implementation status as verified by the test suite.

| Step | Flow Stage | Expected Behavior | Evidence Required | Pass / Fail Criterion | Implementation Status |
|---|---|---|---|---|---|
| **1** | **User Natural-Language Request** | Accepts user prompt targeting cost reduction (e.g. *"Analyze our cluster services and safely reduce cloud spend on underutilized workloads"*). | Request string captured in workflow context or API request body. | **Pass:** Valid UTF-8 string received without truncation.<br>**Fail:** Request dropped, rejected, or unparsed. | **Contract-Tested** (`tests/scenarios/test_cloud_cost_e2e.py::test_full_workflow_happy_path_underutilized`)<br>*Production Gap:* No API endpoint or UI form currently deployed. |
| **2** | **Services / State Inspection** | Queries infrastructure telemetry and registry for all active workloads (`reports-worker`, `orders-api`, `checkout-api`, `payment-api`). | `ServiceObservation` objects generated with CPU, memory, traffic RPM, latency, and state version. | **Pass:** Validated Pydantic `ServiceObservation` records.<br>**Fail:** Missing fields, negative metrics, or unvalidated dictionaries. | **Verified / Implemented** (`backend/schemas/metrics.py`, `tests/fixtures/underutilized_service.json`, `tests/unit/test_verification.py`). |
| **3** | **Investigation & Evidence Identification** | Pinpoints `reports-worker` as an idle workload (CPU: 9.0%, Traffic: 0 RPM, 4 active instances, costing $11.00/hr). | `InvestigationResult` with identified issues list and non-empty summary. | **Pass:** Identifies 0 RPM and low CPU; confirms min capacity threshold (min: 1).<br>**Fail:** Misses idle service or flags high-traffic services. | **Verified / Implemented** (`backend/schemas/workflow.py`, `InvestigationResult` schema validation). |
| **4** | **Decision / Action Proposal** | Formulates structured `ActionProposal` proposing `InfrastructureAction.SCALE_DOWN` to 1 instance on `reports-worker` with confidence score. | Validated `ActionProposal` model instance with `action`, `target_service_id`, `observation_version`, and $0.0 \le \text{confidence} \le 1.0$. | **Pass:** Exact enum `scale_down`, valid target, confidence within $[0.0, 1.0]$.<br>**Fail:** Arbitrary string action, missing confidence, or malformed JSON. | **Verified / Implemented** (`backend/schemas/actions.py`, `tests/unit/test_agent_contract.py`).<br>*Production Gap:* Autonomous LLM prompt/decision agent in `backend/agents/` not implemented. |
| **5** | **Safety Check** | Deterministic guardrails evaluate proposed action against 7 safety rules (capacity boundary, latency ceiling, health, freshness, complete data, valid action). | `SafetyCheckResult` with `is_approved=True`, matching proposal/evaluation versions, applied rules logged. | **Pass:** `is_approved=True` for valid action; `is_approved=False` with clear rejection reasons if violated.<br>**Fail:** Execution proceeds without safety approval. | **Contract-Tested** (`tests/unit/test_safety.py`, `tests/fixtures/safety_violations.json`).<br>*Production Gap:* Safety engine in `backend/safety/` not implemented. |
| **6** | **Action Execution** | Cloud simulator invokes target mutation (`target_instances=1`) ONLY IF `is_approved=True`. | `ExecutionResult` containing `status=ExecutionStatus.SUCCESS`, `action`, `target_service_id`, and `new_state_version`. | **Pass:** Status is `ExecutionStatus.SUCCESS` or `ExecutionStatus.FAILURE`. `ExecutionResult` explicitly does NOT assert verified success.<br>**Fail:** Unapproved action executes, or failure is suppressed. | **Contract-Tested** (`tests/unit/test_simulator.py`, `backend/schemas/execution.py`).<br>*Production Gap:* Infrastructure simulator in `backend/simulator/` not implemented. |
| **7** | **Infrastructure State Change** | Cloud simulator mutates service state: `reports-worker` instances change from 4 to 1. | Post-action simulator state inspection showing `instances=1`, updated timestamp, incremented `state_version="v1.0.1"`. | **Pass:** State reflects requested target.<br>**Fail:** State remains 4 or mutates to out-of-bounds value. | **Contract-Tested** (`tests/fixtures/underutilized_service.json` expected state).<br>*Production Gap:* Simulator state engine not implemented. |
| **8** | **Post-Action Verification** | Independent observer re-queries infrastructure state and compares observed state against proposed effect. | `VerificationResult` with `is_successful=True` ONLY IF observed state confirms target instances. | **Pass:** `is_successful=True` if state confirmed; `is_successful=False` if unchanged or mismatched.<br>**Fail:** Execution SUCCESS alone equated to verification success. | **Verified / Implemented** (`backend/schemas/workflow.py`, `tests/unit/test_verification.py`, `tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_8_observed_state_outranks_execution_claim`). |
| **9** | **Cost Impact Calculation** | Re-computes hourly and projected monthly spend based on confirmed instance count ($11.00/hr $\rightarrow$ $2.75/hr; savings $8.25/hr or 75%). | Hourly cost delta recorded in summary/notes matching fixture contract ($11.00 \rightarrow $2.75). | **Pass:** Cost delta derived strictly from confirmed state.<br>**Fail:** Fabricated cost savings or unverified projection. | **Contract-Tested** (`tests/fixtures/underutilized_service.json` cost impact specification). |
| **10** | **Audit / Activity Record Creation** | Creates immutable audit record containing request, observation, proposal, safety evaluation, execution log, and verification result. | `WorkflowReport` instance serialized to storage with unique `workflow_id`. | **Pass:** Complete 7-stage audit payload persisted.<br>**Fail:** Missing safety check, dropped failure codes, or unpersisted record. | **Verified / Implemented** (`backend/schemas/workflow.py::WorkflowReport`, `tests/unit/test_verification.py`). |
| **11** | **Final Result Display** | UI/CLI surfaces unambiguous outcome: `VERIFIED_SUCCESS`, `BLOCKED`, `EXECUTION_FAILED`, or `VERIFICATION_FAILURE`. | Final UI card / CLI status displaying confirmed outcome state, metrics, and audit link. | **Pass:** Displays exact outcome; never displays SUCCESS for blocked/failed actions.<br>**Fail:** HTTP 200 or execution claim disguised as verified success. | **Contract-Tested** (`tests/browser/test_cloud_cost_ui.py`, `tests/test_regression.py::TestBrowserUITruthfulnessRegression`).<br>*Production Gap:* Web frontend in `frontend/` not implemented. |

---

## 2. Deterministic Demo Scenarios

### Scenario A: Underutilized Service (Primary Golden Path)
- **Fixture:** `tests/fixtures/underutilized_service.json`
- **Initial State:**
  - Service: `reports-worker`
  - Active Instances: `4` (Min: `1`, Max: `6`)
  - Health: `healthy = True`
  - Telemetry: CPU: `9.0%`, Memory: `15.0%`, Traffic: `0 RPM`, Latency: `0.0 ms`, Cost: `$11.00/hr`
  - State Version: `v1.0.0-1030`
- **Narrative & Steps:**
  1. Agent inspects cluster telemetry and identifies `reports-worker` has 0 traffic and under 10% CPU over observation window.
  2. Agent proposes: `InfrastructureAction.SCALE_DOWN` to `1` instance (confidence: `0.95`).
  3. Safety engine validates: Target $1 \ge \text{min\_instances } 1$, health is True, latency is within bounds, observation is fresh. $\rightarrow$ **ALLOWED (`is_approved=True`)**.
  4. Execution engine issues scale-down command to infrastructure simulator.
  5. Simulator mutates instances from 4 to 1, producing version `v1.0.1`.
  6. Independent verification queries infrastructure, confirms `instances == 1`, confirms new state version. $\rightarrow$ **VERIFIED_SUCCESS (`is_successful=True`)**.
  7. Cost impact calculated: $11.00/hr $\rightarrow$ $2.75/hr (savings: $8.25/hr / 75%).
- **Verification Rule:** Execution success alone is NOT enough; verified success requires confirmed observation of 1 instance.

### Scenario B: Rising Traffic (Unsafe Action Prevention)
- **Fixture:** `tests/fixtures/rising_traffic.json`
- **Initial State:**
  - Service: `orders-api`
  - Active Instances: `4` (Min: `2`, Max: `10`)
  - Telemetry: CPU: `28.0%`, Memory: `45.0%`, Traffic: `4200 RPM` (surging), Latency: `260.0 ms`, Cost: `$18.50/hr`
- **Narrative & Steps:**
  1. Agent evaluates cluster for cost-reduction opportunities.
  2. Even though CPU utilization is currently moderate (28%), traffic has surged to 4,200 RPM.
  3. Workload requires capacity to prevent tail-latency degradation.
  4. Agent / Safety explicitly prohibits `scale_down` (`must_not_scale_down = True`, `prohibited_actions: ["scale_down"]`).
  5. Output: Proposes `no_action` (or `scale_up` if threshold exceeded).
  6. Outcome: Zero mutations executed. Infrastructure remains stable at 4 instances. Cost remains $18.50/hr.

### Scenario C: Stale Observation (Freshness Guardrail)
- **Fixture:** `tests/fixtures/stale_observation.json`
- **Initial State:**
  - Service: `checkout-api`
  - Stale Observation: Timestamp: `2026-09-17T08:00:00Z` (`v1.0.0-0800`), CPU: `24.0%`, Traffic: `900 RPM`.
  - Actual Current Cluster Telemetry: Timestamp: `2026-09-17T10:30:00Z` (`v1.0.0-1030`), Traffic: `8500 RPM`.
  - Age: 150 minutes (Threshold: 15 minutes).
- **Narrative & Steps:**
  1. Decision proposal submitted referencing stale observation version `v1.0.0-0800`.
  2. Safety engine compares proposal version (`v1.0.0-0800`) against current cluster version (`v1.0.0-1030`).
  3. Safety detects 150-minute staleness ($150\text{m} > 15\text{m}$ max allowed).
  4. Safety **BLOCKS** action: `is_approved = False`, reason: *"Observation data is 150.0 minutes old (threshold 15m)"*.
  5. Workflow halts before execution. No infrastructure call is made.
  6. System triggers mandatory re-investigation / telemetry refresh.
  7. Evaluator takeaway: Stale telemetry never allows a risky state modification.

### Scenario D: Failed Action (Infrastructure Fault Handling)
- **Fixture:** `tests/fixtures/failed_action.json`
- **Initial State:**
  - Service: `payment-api`
  - Active Instances: `3`
  - Telemetry: CPU: `91.0%`, Traffic: `5800 RPM`.
- **Narrative & Steps:**
  1. Workload requires scale-up from 3 to 5 instances due to 91% CPU.
  2. Safety approves scale-up (`is_approved = True`).
  3. Execution engine calls infrastructure provider / cloud simulator.
  4. Provider rejects request with `error: "capacity_unavailable"`.
  5. `ExecutionResult` captures `status = ExecutionStatus.FAILURE`, `error_code = "capacity_unavailable"`, `new_state_version = None`.
  6. Verification observes actual infrastructure: instances remain at `3` (not 5).
  7. Verification evaluates: `is_successful = False`, `verification_notes = "Execution failed: capacity_unavailable. Instances remain at 3."`.
  8. UI displays: **`EXECUTION_FAILED`** (never SUCCESS).

### Scenario E: Safety Block (7 Violation Sub-Scenarios)
- **Fixture:** `tests/fixtures/safety_violations.json`
- **Core Principle:** Safety blocks are first-class safety achievements. A blocked action must be clearly displayed as **`BLOCKED`**, never as `SUCCESS`.
- **The 7 Sub-Scenarios:**
  1. `below_minimum_capacity`: Attempting to scale down `cart-service` to 0 (min: 1) $\rightarrow$ **BLOCKED**.
  2. `above_maximum_capacity`: Attempting to scale up `analytics-aggregator` to 10 (max: 6) $\rightarrow$ **BLOCKED**.
  3. `latency_violation`: Attempting to scale down `auth-service` when latency is 1250ms (ceiling: 500ms) $\rightarrow$ **BLOCKED**.
  4. `unhealthy_service`: Attempting any modification on `inventory-db` when `healthy = False` $\rightarrow$ **BLOCKED**.
  5. `stale_data`: Attempting modification when observation telemetry is 90 minutes old $\rightarrow$ **BLOCKED**.
  6. `missing_metric_data`: Attempting evaluation when CPU utilization is missing (`None`) $\rightarrow$ **FAIL CLOSED / BLOCKED**.
  7. `invalid_action`: Attempting unapproved action `"terminate_cluster"` not defined in `InfrastructureAction` enum $\rightarrow$ **REJECTED**.

### Scenario F: Verification Failure (Phantom Success Prevention)
- **Tested In:** `tests/unit/test_verification.py::TestVerification::test_execution_claims_success_but_state_not_updated_fails_verification`, `tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_8_observed_state_outranks_execution_claim`
- **Initial State:**
  - Service: `reports-worker`
  - Initial Instances: `4`
- **Narrative & Steps:**
  1. Proposal: scale down to 1. Safety: ALLOWED.
  2. Execution driver returns an optimistic return code or HTTP 200 indicating success.
  3. Independent observer queries infrastructure telemetry 30 seconds later.
  4. Observation reveals: instances are still `4` (cloud provider dropped or silently failed the call).
  5. Verification engine compares claimed target (`1`) vs observed reality (`4`).
  6. Verification declares **`is_successful = False`**, `verification_notes = "Instances unchanged at 4; expected 1"`.
  7. Result: The system surfaces **`VERIFICATION_FAILURE`**. Execution claim is subordinated to observed reality.

---

## 3. DEMO TRUTHFULNESS RULES

These 12 mandatory rules govern all presentations, test assertions, and evaluator demonstrations:

1. **Never claim SUCCESS merely because a request was accepted.** HTTP 202 / job acceptance only means the task was queued.
2. **Never claim SUCCESS merely because an action proposal exists.** An AI proposal is an unverified recommendation, not an action.
3. **Never claim SUCCESS merely because safety is ALLOWED.** Safety clearance is a prerequisite, not an execution result.
4. **Never claim SUCCESS merely because execution reports SUCCESS.** Infrastructure APIs frequently report synchronous 200/OK before backend provisioning fails.
5. **Never claim SUCCESS merely because HTTP returns 200.** API response codes indicate transport health, not cloud infrastructure reality.
6. **Verified success requires post-action observed state.** An action is only successful when independent post-execution telemetry confirms the expected state change.
7. **BLOCKED must remain BLOCKED.** A safety block is a successful guardrail intervention; it must never be renamed or softened into a success.
8. **EXECUTION_FAILED must remain failed.** Infrastructure failures must be presented honestly with exact error codes.
9. **VERIFICATION_FAILED must remain failed.** When execution claims success but observed state contradicts it, verification failure must be surfaced.
10. **STALE data must not support a risky success claim.** Telemetry beyond freshness thresholds must trigger mandatory refresh/re-investigation.
11. **Missing critical data must fail closed.** Incomplete telemetry (e.g. null CPU/memory) strictly prevents mutation.
12. **Never fabricate screenshots or live demo evidence.** Demonstrations must use real, reproducible terminal commands, test fixtures, and verified test assertions.
