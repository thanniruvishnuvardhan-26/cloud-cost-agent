# Evaluator Guide — Autonomous Cloud Cost Optimization Agent
**Phase 14: Evaluator Preparation**  
**Role:** Member 4 — Data + QA + Integration + Evaluation Lead

---

## 1. Problem Statement

In modern cloud computing, infrastructure costs escalate when services are over-provisioned, idle, or unmonitored. While autonomous AI agents promise hands-free cloud cost optimization, granting an agent write access to production cloud infrastructure creates severe operational risks:
- Uncontrolled downscaling can breach latency SLAs or starve sudden traffic surges.
- Premature termination or scaling below minimum cluster capacity can disrupt critical batch or worker pipelines.
- Optimistic HTTP return codes or transport-level success from cloud provider APIs frequently mask asynchronous backend provisioning failures, creating **phantom successes**.

The **Autonomous Cloud Cost Optimization Agent** addresses this challenge with a **deterministic safety and independent post-action verification architecture**. The agent identifies optimization opportunities, but no mutation is executed without passing strict deterministic guardrails, and no optimization is claimed as successful until independent post-action telemetry confirms the infrastructure state.

---

## 2. Intended 7-Stage Workflow

The autonomous cloud cost optimization pipeline executes in seven strictly ordered stages:

```
[1. User Request]
        │
        ▼
[2. Investigation] ── (Collects cluster telemetry, metrics, instance counts)
        │
        ▼
[3. Decision] ──────── (Synthesizes observation; formulates ActionProposal with confidence)
        │
        ▼
[4. Safety Gate] ───── (Evaluates proposal against 7 deterministic guardrails; BLOCKS if unsafe)
        │
        ▼
[5. Execution] ─────── (Executes mutation ONLY if approved; captures ExecutionResult)
        │
        ▼
[6. Verification] ──── (Independently inspects observed post-action state; confirms match)
        │
        ▼
[7. Final Result] ──── (Generates immutable WorkflowReport audit trail; displays distinct status)
```

### Stage Purposes:
1. **User Request**: Ingests high-level cost optimization intent (e.g. *"Analyze cluster workloads and safely reduce idle capacity"*).
2. **Investigation**: Queries telemetry across all active services (`reports-worker`, `orders-api`, `checkout-api`, `payment-api`), producing structured `ServiceObservation` snapshots.
3. **Decision**: Synthesizes telemetry to propose structured `InfrastructureAction` proposals (`scale_down`, `scale_up`, `resize`, `stop_idle_service`, `delay_batch`, `no_action`) with explicit confidence scores ($0.0 \le c \le 1.0$).
4. **Safety Gate**: Deterministically evaluates proposals against hard capacity limits, latency ceilings, health checks, freshness thresholds, and action whitelists before infrastructure drivers are invoked.
5. **Execution**: Dispatches approved actions to infrastructure drivers or cloud simulators, recording provider return codes in `ExecutionResult`.
6. **Independent Verification**: Independently re-queries cluster infrastructure state to verify that the observed state actually matches the proposal's expected state.
7. **Final Result & Audit**: Persists the full 7-stage trace in a tamper-evident `WorkflowReport` and displays one of four distinct outcome states.

---

## 3. The Safety Principle: "No Action Without Safety Approval"

The primary invariant of the system is: **Zero infrastructure actions may execute without passing the deterministic safety gate.**

The repository defines and tests seven hard safety rules:
1. **Minimum Capacity Rule**: Prohibits scaling below the service's configured minimum instances (e.g., attempting to scale `cart-service` to 0 when min is 1).
2. **Maximum Capacity Rule**: Prohibits scaling above configured maximum instances (e.g., attempting to scale `analytics-aggregator` to 10 when max is 6).
3. **Latency Ceiling Rule**: Prohibits capacity reduction if service latency exceeds maximum allowable thresholds (e.g., latency at 1250ms when ceiling is 500ms).
4. **Health Check Rule**: Prohibits any infrastructure modifications on degraded or unhealthy workloads (`healthy == False`).
5. **Data Freshness Rule**: Prohibits actions if observation telemetry is stale (e.g., telemetry older than 15-minute threshold; requires telemetry refresh).
6. **Data Completeness Rule**: Fails closed if critical metrics (such as CPU utilization or memory) are missing (`None`).
7. **Action Whitelist Rule**: Rejects unapproved or dangerous actions (e.g., `terminate_cluster` or `drop_db`) outside the defined `InfrastructureAction` enum.

*Tested in:* `tests/unit/test_safety.py`, `tests/fixtures/safety_violations.json`, and `tests/test_regression.py::TestSafetyRegression`.

---

## 4. The Verification Principle: "No Success Claim Without Post-Action Verification"

A critical insight of this project is that **Execution Success $\neq$ Verified Success**. Infrastructure providers frequently return HTTP 200 / `ExecutionStatus.SUCCESS` synchronously, even while instances fail to provision or remain unchanged.

The system enforces four distinct states:
- **Proposed**: An unverified recommendation generated by an agent or user request.
- **Safety-Approved (`is_approved = True`)**: The proposed action satisfies all 7 safety guardrails; permission is granted to attempt execution.
- **Execution-Reported Success (`status = ExecutionStatus.SUCCESS`)**: The cloud driver or simulator accepted the command without transport error. This does **not** prove infrastructure changed.
- **Verified Success (`is_successful = True`)**: An independent post-action observation confirms the infrastructure state matches the proposed target state.

```
Proposal ──(Safety Passed)──> Execution Call ──(Driver 200 OK)──> Independent Telemetry ──(State Matches)──> VERIFIED SUCCESS
                                                                          │
                                                                   (State Mismatched)
                                                                          │
                                                                          ▼
                                                                VERIFICATION FAILURE
```

*Tested in:* `tests/unit/test_verification.py`, `backend/schemas/workflow.py::VerificationResult`, and `tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_8_observed_state_outranks_execution_claim`.

---

## 5. Failure Handling

The repository tests fail-closed, truthful handling across all failure modes:

| Failure Mode | Pipeline Behavior | Final Status | Current Status |
|---|---|---|---|
| **Safety Block** | Guardrail violation halts pipeline before execution. | `BLOCKED` | Contract-Tested (`tests/unit/test_safety.py`) |
| **Execution Failure** | Cloud provider rejects request (e.g. `capacity_unavailable`). | `EXECUTION_FAILED` | Implemented & Verified (`backend/schemas/execution.py`, `tests/fixtures/failed_action.json`) |
| **Verification Mismatch** | Execution returns success, but instance count remains unchanged. | `VERIFICATION_FAILURE` | Implemented & Verified (`tests/unit/test_verification.py`) |
| **Stale Telemetry** | Observation age exceeds threshold (e.g. 150m > 15m). | `BLOCKED` (requires refresh) | Implemented & Verified (`tests/fixtures/stale_observation.json`) |
| **Missing Critical Data** | Null CPU, memory, or service identifier. | `BLOCKED` (fails closed) | Implemented & Verified (`backend/schemas/metrics.py` Pydantic validation) |
| **Malformed LLM Output** | LLM outputs unknown action or invalid confidence. | `REJECTED` | Implemented & Verified (`tests/unit/test_agent_contract.py`) |
| **Driver Timeout** | Execution driver exceeds timeout before confirmation. | `EXECUTION_FAILED` | Contract-Tested (`tests/scenarios/test_failure_cases.py`) |
| **No-Action Decision** | Traffic surge warrants preserving capacity. | `NO_ACTION` (Zero mutation) | Implemented & Verified (`tests/fixtures/rising_traffic.json`) |

---

## 6. Main Demo Scenario (Underutilized Service)

### Initial Cluster State (`tests/fixtures/underutilized_service.json`):
- **Target Workload**: `reports-worker`
- **Current Instances**: 4 (Configured bounds: Min: 1, Max: 6)
- **Observed Metrics**: CPU: **9.0%**, Traffic: **0 RPM**, Latency: **0.0 ms**, Health: **Healthy (`True`)**
- **Current Hourly Cost**: **$11.00 / hour** ($2.75 / instance-hour)
- **Telemetry State Version**: `v1.0.0-1030`

### Expected Workflow Contract:
1. Investigation flags `reports-worker` as completely idle (0 RPM, 9% CPU).
2. Decision agent proposes `InfrastructureAction.SCALE_DOWN` to 1 instance (confidence 0.95).
3. Safety gate verifies target $1 \ge \text{min } 1$, health is true, latency is 0, and data is fresh $\rightarrow$ **APPROVED**.
4. Execution requests scale-down from 4 to 1 on `reports-worker`.
5. Independent observation confirms `instances == 1` and new state version `v1.0.1`.
6. Verification confirms state match $\rightarrow$ **`VERIFIED_SUCCESS`**.
7. Cost recalculation records verified spend reduction: **$11.00/hr $\rightarrow$ $2.75/hr** (75% reduction; $8.25/hr savings).

*Runtime Note:* The data contracts, schema validations, and verification assertions are fully implemented and passing. The autonomous orchestrator and live simulator are documented production gaps.

---

## 7. Failure Demonstrations

### 1. Rising Traffic (`tests/fixtures/rising_traffic.json`)
- `orders-api` exhibits moderate CPU (28%), but incoming traffic has surged to **4,200 RPM**.
- Scaling down would violate latency SLAs.
- Contract test verifies `must_not_scale_down = True`. The system issues `no_action`, preserving cluster stability.

### 2. Safety Block (`tests/fixtures/safety_violations.json`)
- Demonstrates 7 distinct guardrail interventions (below minimum, above maximum, latency breach, unhealthy service, stale telemetry, missing metrics, invalid action).
- In each case, execution is halted, no cloud mutation is triggered, and the outcome is recorded truthfully as `BLOCKED`.

### 3. Execution Failure (`tests/fixtures/failed_action.json`)
- `payment-api` attempts scale-up during peak load, but the provider returns `error: "capacity_unavailable"`.
- Instances remain at 3; outcome is truthfully recorded as `EXECUTION_FAILED`.

### 4. Verification Mismatch ("Phantom Success")
- Execution returns HTTP 200, but infrastructure polling reveals instances remain at 4.
- Verification logic overrides the execution claim and flags `VERIFICATION_FAILURE`.

### 5. Stale Observation (`tests/fixtures/stale_observation.json`)
- Telemetry is 150 minutes old; current cluster version has moved ahead.
- Action is blocked until a fresh observation is captured.

---

## 8. Exact Evidence Pointers

| Requirement Area | Test File | Test Class / Method | Evidence Fixture |
|---|---|---|---|
| **Data Fixtures** | `tests/test_regression.py` | `TestDataFixturesRegression` | All 5 fixtures in `tests/fixtures/` |
| **Schema Validation** | `tests/test_regression.py` | `TestSchemaContractRegression` | `backend/schemas/` |
| **Safety Guardrails** | `tests/unit/test_safety.py` | `TestSafetyEngine` | `safety_violations.json` |
| **Verification Logic** | `tests/unit/test_verification.py` | `TestVerification` | `underutilized_service.json` |
| **Orchestration Order** | `tests/integration/test_orchestration.py` | `TestOrchestration` | `underutilized_service.json` |
| **Failure Cases** | `tests/scenarios/test_failure_cases.py` | `TestFailureCases` | `failed_action.json`, `stale_observation.json` |
| **UI Truthfulness** | `tests/browser/test_cloud_cost_ui.py` | `TestCloudCostUI` | Synthetic presentation states |
| **Regression & Invariants**| `tests/test_regression.py` | `TestCriticalRegressionInvariants` | All 10 invariant rules |
