# Evaluator Quickstart — Cloud Cost Optimization Agent
**Phase 14: Evaluator Preparation**  
**Role:** Member 4 — Data + QA + Integration + Evaluation Lead

---

## 1. Repository Context
- **Active Git Branch:** `person-4-qa`
- **Ownership:** Member 4 owns QA, deterministic data fixtures, test harnesses, failure mode testing, and regression suites.
- **QA Objective:** Protect safety, verification, contract, and truthfulness invariants across Phases 1–14 without modifying or fabricating production code.

---

## 2. Test Fixtures (`tests/fixtures/`)
All test fixtures are static, deterministic JSON files located in `tests/fixtures/`:

1. `underutilized_service.json`: Demonstrates the primary golden path. Service `reports-worker` has 0 RPM, 9% CPU, 4 instances costing $11.00/hr, with valid scale-down target to 1 instance ($2.75/hr).
2. `rising_traffic.json`: Demonstrates unsafe action prevention. Service `orders-api` has surging 4,200 RPM traffic; explicitly enforces `must_not_scale_down = True`.
3. `stale_observation.json`: Demonstrates freshness guardrail. Telemetry is 150 minutes old (`v1.0.0-0800` vs current `v1.0.0-1030`); enforces action blocking and mandatory refresh.
4. `failed_action.json`: Demonstrates cloud infrastructure failure. Service `payment-api` scale-up fails with `capacity_unavailable`; confirms instances remain unchanged at 3.
5. `safety_violations.json`: Demonstrates all 7 safety violation regimes (below min, above max, latency ceiling, unhealthy workload, stale data, missing metrics, invalid action).

---

## 3. Key Test Suites

| Suite Path | Focus Area | Total Tests | Implemented / Gap |
|---|---|---|---|
| `tests/unit/test_simulator.py` | Cloud mutation, boundaries, cost model | 7 | 7 gaps (simulator missing) |
| `tests/unit/test_safety.py` | 7 safety guardrails | 10 | 10 gaps (safety engine missing) |
| `tests/unit/test_verification.py` | Post-action state verification | 11 | **11 passed** (100% verified) |
| `tests/integration/test_api.py` | REST API endpoints & contracts | 29 | 29 gaps (FastAPI app missing) |
| `tests/unit/test_agent_contract.py` | LLM proposals, enum whitelisting, confidence | 42 | **40 passed**, 2 gaps |
| `tests/integration/test_orchestration.py` | 7-stage pipeline order & safety gates | 27 | **20 passed**, 7 gaps |
| `tests/scenarios/test_cloud_cost_e2e.py` | End-to-end P3 demo scenario | 19 | **14 passed**, 5 gaps |
| `tests/browser/test_cloud_cost_ui.py` | UI presentation truthfulness & badges | 17 | **14 passed**, 3 gaps |
| `tests/scenarios/test_failure_cases.py` | Fail-closed, timeout, partial state | 33 | **28 passed**, 5 gaps |
| `tests/test_regression.py` | Consolidated regression & 10 invariants | 115 | **95 passed**, 20 gaps |

---

## 4. Test Commands

### 1. Pytest Probe (Checking Runner Availability)
```powershell
python -m pytest tests/test_regression.py -q
```
*Observed Output:* `No module named pytest` (pytest is not installed in this environment).

### 2. Primary Verified Regression Command (Fast & Deterministic)
Run the consolidated regression suite using Python's built-in `unittest` runner:
```powershell
python -m unittest tests.test_regression -v
```
*Expected Result:*
- **Total Tests Run:** 115
- **Passed:** 95
- **Failed:** 20 (100% documented production gaps in simulator, safety engine, API server, and orchestrator runner)
- **Execution Time:** ~0.10s

### 3. Critical Invariants Only (10 Rules in 0.001s)
```powershell
python -c "import unittest; suite = unittest.TestLoader().loadTestsFromName('tests.test_regression.TestCriticalRegressionInvariants'); runner = unittest.TextTestRunner(verbosity=2); runner.run(suite)"
```
*Expected Result:* **10 tests run, 10 passed, 0 failures, 0 errors.**

### 4. Full Discovery Across Entire Repository
```powershell
python -m unittest discover -s tests -p "test*.py" -v
```

---

## 5. Critical Invariants (Rules 1–10)

The regression suite protects 10 non-negotiable invariant rules:

| Rule | Statement | Invariant Meaning |
|---|---|---|
| **RULE 1** | **No safety approval $\rightarrow$ no execution** | If `is_approved = False`, `execution` is strictly `None`. |
| **RULE 2** | **Execution failure $\rightarrow$ never verified success** | If status is `FAILURE`, `is_successful` is strictly `False`. |
| **RULE 3** | **Execution SUCCESS alone $\rightarrow$ never verified success** | Provider return codes never bypass independent post-action observation. |
| **RULE 4** | **Expected effect text alone $\rightarrow$ never verified success** | An `ActionProposal` text claim is not an `ExecutionResult`. |
| **RULE 5** | **HTTP 200 alone $\rightarrow$ never verified success** | Web status 200 indicates transport health, not infrastructure mutation. |
| **RULE 6** | **Stale telemetry $\rightarrow$ no risky action claim** | Observations older than freshness ceiling strictly halt pipeline. |
| **RULE 7** | **Missing telemetry $\rightarrow$ fail closed** | Missing critical fields (`service_id`, `cpu_utilization_percent`) trigger rejection. |
| **RULE 8** | **Observed state outranks execution claim** | When post-action observation contradicts execution claim, observation wins. |
| **RULE 9** | **Blocked action remains BLOCKED** | Safety blocks are never sanitized or displayed as successes. |
| **RULE 10**| **No_action does not claim mutation** | A `no_action` decision leaves infrastructure untouched (`instances unchanged`). |
