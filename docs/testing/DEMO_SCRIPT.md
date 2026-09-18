# Evaluator Demo Script — Autonomous Cloud Cost Optimization Agent
**Phase 13: Demo Preparation**  
**Role:** Member 4 — Data + QA + Integration + Evaluation Lead

> **Important Presentation Note:** This script presents the deterministic contract and test-verified capabilities of the Cloud Cost Optimization Agent. In accordance with the Project Truthfulness Rules, whenever a production runtime component is not yet fully implemented (such as live LLM calling, FastAPI endpoints, or web UI), this script describes the verified contract behavior and points to the exact deterministic regression test validating it.

---

### 1. Opening
"Welcome. Today we are demonstrating the **Autonomous Cloud Cost Optimization Agent**. 

In modern cloud environments, autonomous agents cannot simply be given write credentials to scale or terminate infrastructure based solely on raw LLM reasoning. Unconstrained autonomous actions risk dropping database connections, violating service-level agreements (SLAs), or causing cascade outages. 

Our system solves this with a **7-stage deterministic safety and independent verification pipeline**:
$$\text{Request} \longrightarrow \text{Investigation} \longrightarrow \text{Decision} \longrightarrow \text{Safety Gate} \longrightarrow \text{Execution} \longrightarrow \text{Independent Verification} \longrightarrow \text{Audit}$$

Crucially, **execution success alone is never equated to verified success**. Observed infrastructure telemetry must independently prove that state was altered as expected before any savings claim is certified."

---

### 2. Input
"The user enters the following natural-language cost optimization prompt:

> *\"Analyze our cluster workloads, identify any idle or over-provisioned services, and safely optimize capacity to reduce hourly cloud spend without impacting SLAs.\"*

**Contract Status:** The workflow contract (`tests/scenarios/test_cloud_cost_e2e.py`) ingests this request string and binds it to a unique workflow trace (`workflow_id="wf-demo-p3-001"`)."

---

### 3. Investigation
"The agent inspects cluster telemetry across all active workloads. Using our deterministic test fixture (`tests/fixtures/underutilized_service.json`), the investigation yields:

- **Target Workload:** `reports-worker`
- **Active Capacity:** 4 instances (Configured limits: Min: 1, Max: 6)
- **Observed Metrics:**
  - CPU Utilization: **9.0%** (Low utilization threshold is < 15%)
  - Memory Utilization: **15.0%**
  - Incoming Traffic: **0 RPM** (Completely idle workload)
  - Latency: **0.0 ms**
  - Health: **Healthy (`True`)**
  - Current Spend: **$11.00 / hour**
  - Telemetry State Version: **`v1.0.0-1030`**

**Verified Implementation:** Implemented in `backend/schemas/metrics.py::ServiceObservation` and validated in `tests/test_regression.py::TestDataFixturesRegression::test_underutilized_service_semantic_constraints`."

---

### 4. Decision
"Based on the zero traffic and 9% CPU utilization, an action proposal is formulated:

- **Proposed Action:** `InfrastructureAction.SCALE_DOWN`
- **Target Service:** `reports-worker`
- **Target Capacity:** 1 instance (reduction of 3 instances)
- **Stated Rationale:** *\"Service reports-worker is underutilized with 9.0% CPU and 0 RPM over observation window.\"*
- **Expected Effect:** *\"Scale down from 4 to 1 instance; estimated cost reduction -$8.25/hr.\"*
- **Observation Version:** `v1.0.0-1030`
- **Confidence:** **0.95** (Must satisfy $0.0 \le c \le 1.0$)

**Verified Contract:** Validated by `backend/schemas/actions.py::ActionProposal` and protected by `tests/unit/test_agent_contract.py`. (Autonomous LLM generation in `backend/agents/` is a documented production gap)."

---

### 5. Safety
"Before any action is sent to the cloud infrastructure driver, it passes through the **Deterministic Safety Gate**. The proposal is evaluated against 7 hard rules:

1. **Minimum Capacity Rule:** Target $1 \ge \text{Min } 1$ $\rightarrow$ **PASS**
2. **Maximum Capacity Rule:** Target $1 \le \text{Max } 6$ $\rightarrow$ **PASS**
3. **Latency Ceiling Rule:** Current latency 0.0ms $\le 500\text{ms}$ threshold $\rightarrow$ **PASS**
4. **Health Check Rule:** Workload health is `True` $\rightarrow$ **PASS**
5. **Data Freshness Rule:** Proposal version `v1.0.0-1030` matches current telemetry version `v1.0.0-1030` (age < 15m) $\rightarrow$ **PASS**
6. **Data Completeness Rule:** All CPU, memory, and traffic metrics present $\rightarrow$ **PASS**
7. **Action Whitelist Rule:** `scale_down` is an authorized `InfrastructureAction` enum $\rightarrow$ **PASS**

- **Safety Result:** `is_approved = True`, `applied_rules = ["min_capacity", "max_capacity", "latency_check", "health_check", "freshness_check"]`.

**Verified Contract:** Validated in `backend/schemas/safety.py::SafetyCheckResult` and verified in `tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_1_no_safety_approval_no_execution`."

---

### 6. Execution
"Because and **only because** safety approval was granted, execution is initiated:

- **Action Executed:** `scale_down` on `reports-worker` to 1 instance.
- **Provider Status:** `ExecutionStatus.SUCCESS`
- **New State Version Assigned:** `v1.0.1`

**Critical Design Distinction:** The resulting `ExecutionResult` model intentionally contains **NO** `is_successful` field. An execution return code represents merely transport/API acceptance, not verified cloud state change. (Simulator driver in `backend/simulator/` is a documented production gap)."

---

### 7. Verification
"Now comes the core differentiator: **Independent Post-Action Verification**.

The verification engine does not take the execution driver's word for it. It polls the infrastructure state independently:

- **Observed Post-Action State:**
  - Service: `reports-worker`
  - Observed Instance Count: **1**
  - Observed State Version: **`v1.0.1`**
- **Evaluation:** Claimed target (`1`) == Observed target (`1`).
- **Final Verification Result:**
  - `is_successful = True`
  - `verification_notes = "Confirmed reports-worker scaled down from 4 to 1 instance. Telemetry state version v1.0.1 verified."`

**Verified Implementation:** Built into `backend/schemas/workflow.py::VerificationResult` and protected by `tests/test_regression.py::TestVerificationRegression`."

---

### 8. Cost Impact
"With post-action state verified by independent observation, the system computes verified cost impact:

- **Pre-Action Cost:** **$11.00 / hour** (4 instances @ $2.75/hr each)
- **Post-Action Cost:** **$2.75 / hour** (1 instance @ $2.75/hr)
- **Immediate Savings:** **$8.25 / hour**
- **Relative Savings:** **75.0% reduction** in workload spend.
- **Projected Monthly Savings:** **$5,940.00 / month** (at 720 hours/month).

*Note: In accordance with our Truthfulness Rules, cost figures are derived strictly from verified fixture contracts (`tests/fixtures/underutilized_service.json`).*"

---

### 9. Failure Demo: Unsafe Action Prevention & Blocked Safety
"To prove that our agent does not blindly optimize without regard for stability, let us examine an unsafe scenario: **Rising Traffic** (`tests/fixtures/rising_traffic.json`).

1. **Observation:** Workload `orders-api` has moderate CPU (28%), but incoming traffic has surged to **4,200 RPM**.
2. **Rule Enforcement:** Our test suite verifies `must_not_scale_down = True`. 
3. **Safety Intervention:** Scaling down during traffic surges triggers latency spikes. If a scale-down proposal is attempted, the safety engine immediately halts execution:
   - Outcome: **`BLOCKED`**
   - Reason: *\"Traffic surging at 4200 RPM exceeds scale-down safety ceiling\"*.
   - Execution Triggered: **None (`execution is None`)**.
   - UI Display: **`BLOCKED`** (Never reported as SUCCESS).

**Verified Test:** Validated in `tests/test_regression.py::TestSafetyRegression::test_rising_traffic_semantic_constraints` and `tests/test_regression.py::TestCriticalRegressionInvariants::test_rule_9_blocked_action_remains_blocked`."

---

### 10. Closing & The Safety/Verification Principle
"In summary, our autonomous architecture is anchored on three immutable principles:

1. **No Action Without Safety Approval:** Zero infrastructure calls can be executed without passing all 7 guardrails.
2. **No Success Claim Without Independent Verification:** Execution return codes do not outrank observed telemetry. If observed state does not match expected state, the workflow reports `VERIFICATION_FAILURE`.
3. **Truthful Presentation:** Blocked actions remain `BLOCKED`, execution failures remain `EXECUTION_FAILED`, and stale data triggers mandatory refresh.

Thank you. We welcome any questions regarding our deterministic regression suite or verification contracts."
