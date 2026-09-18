# Test Evidence Index — Cloud Cost Optimization Agent
**Phase 14: Evaluator Preparation**  
**Role:** Member 4 — Data + QA + Integration + Evaluation Lead

This index maps every key evaluator requirement and safety invariant to its exact test file, test class, test method name, data fixture, and verification assertion.

---

## 1. The 10 Critical Regression Invariants (`tests/test_regression.py`)

All 10 invariants are tested in `tests/test_regression.py::TestCriticalRegressionInvariants` and pass deterministically:

| Rule | Test Method Name | Fixture Used | What the Assertion Proves |
|---|---|---|---|
| **RULE 1** | `test_rule_1_no_safety_approval_no_execution` | Synthetic `SafetyCheckResult` | When `is_approved = False`, `execution` must be `None` and `is_successful` must be `False`. Execution cannot bypass safety. |
| **RULE 2** | `test_rule_2_execution_failure_never_verified_success` | Synthetic `ExecutionResult` | When execution status is `FAILURE`, verified success is strictly `False` regardless of any other parameter. |
| **RULE 3** | `test_rule_3_execution_success_alone_never_verified_success` | Synthetic `ExecutionResult` | `ExecutionResult` lacks `is_successful`. Execution SUCCESS alone cannot certify verified success without confirmed state change. |
| **RULE 4** | `test_rule_4_expected_effect_text_alone_never_verified_success` | Synthetic `ActionProposal` | An `ActionProposal` text claim is not an `ExecutionResult` and does not possess an `is_successful` or `status` attribute. |
| **RULE 5** | `test_rule_5_http_200_alone_never_verified_success` | Synthetic API status | HTTP status 200 without post-action confirmation evaluates to `False`. |
| **RULE 6** | `test_rule_6_stale_critical_telemetry_no_risky_action_claim` | `stale_observation.json` | 150-minute-old observation version mismatch with active version forces `is_approved = False`. |
| **RULE 7** | `test_rule_7_missing_critical_telemetry_fails_closed` | Synthetic null inputs | Missing `service_id` or `cpu_utilization_percent` triggers Pydantic `ValidationError`; pipeline fails closed. |
| **RULE 8** | `test_rule_8_observed_state_outranks_execution_claim` | Synthetic telemetry vs target | Claimed instance target (`1`) contradicted by observed telemetry (`4`) forces `is_successful = False`. Telemetry outranks execution claim. |
| **RULE 9** | `test_rule_9_blocked_action_remains_blocked_never_success` | Synthetic rejected reasons | Blocked safety evaluations across all reasons evaluate strictly to UI presentation label `"BLOCKED"`, never `"SUCCESS"`. |
| **RULE 10**| `test_rule_10_no_action_does_not_claim_infrastructure_mutation` | `rising_traffic.json` | `no_action` proposals yield `execution = None`, confirm 0 modifications, and preserve instance counts. |

---

## 2. Core Functional Requirements Mapping

### 1. Data Fixture Integrity
- **Test File:** `tests/test_regression.py`
- **Test Class:** `TestDataFixturesRegression`
- **Key Methods:**
  - `test_all_five_fixtures_load_valid_json`: Confirms all 5 fixtures parse as valid dictionaries.
  - `test_scenario_ids_are_stable`: Asserts deterministic scenario IDs.
  - `test_observations_validate_against_service_observation_schema`: Confirms fixtures validate against `ServiceObservation`.
  - `test_underutilized_service_semantic_constraints`: Validates `reports-worker` 0 RPM, 9% CPU, 4 instances, target 1.
  - `test_rising_traffic_semantic_constraints`: Validates `orders-api` 4,200 RPM and `must_not_scale_down = True`.
  - `test_stale_observation_semantic_constraints`: Validates 150m age and `action_permitted_on_stale_data = False`.
  - `test_failed_action_semantic_constraints`: Validates `capacity_unavailable` error and instances remaining at 3.
  - `test_safety_violations_collection_has_all_seven_scenarios`: Confirms all 7 violation scenarios are present.

### 2. Schema and Contract Validation
- **Test File:** `tests/test_regression.py`
- **Test Class:** `TestSchemaContractRegression`
- **Key Methods:**
  - `test_infrastructure_action_enum_exact_values`: Proves exact domain of 6 allowed actions.
  - `test_action_proposal_rejects_missing_confidence`: Rejects proposal lacking confidence.
  - `test_confidence_above_1_rejected` & `test_confidence_below_0_rejected`: Enforces $0.0 \le c \le 1.0$.
  - `test_observation_rejects_cpu_above_100`: Rejects CPU utilization > 100%.
  - `test_observation_rejects_negative_cost`: Rejects negative cost values.
  - `test_execution_result_no_is_successful_field`: Asserts architectural separation between execution and verification.

### 3. Safety Guardrails
- **Test File:** `tests/unit/test_safety.py` & `tests/test_regression.py`
- **Test Class:** `TestSafetyRegression`
- **Fixture:** `tests/fixtures/safety_violations.json`
- **Key Methods:**
  - `test_below_minimum_capacity_blocked`: Asserts scaling below minimum (0 < 1) is blocked.
  - `test_above_maximum_capacity_blocked`: Asserts scaling above maximum (10 > 6) is blocked.
  - `test_latency_violation_blocked`: Asserts scale-down on high latency (1250ms > 500ms) is blocked.
  - `test_unhealthy_service_blocked`: Asserts unhealthy workload (`healthy=False`) is blocked.
  - `test_stale_observation_blocked`: Asserts stale observation is blocked.
  - `test_missing_metric_data_fails_closed`: Asserts missing metric data fails closed.
  - `test_invalid_action_blocked`: Asserts action `"terminate_cluster"` is blocked.

### 4. Independent Verification
- **Test File:** `tests/unit/test_verification.py` & `tests/test_regression.py`
- **Test Class:** `TestVerificationRegression`
- **Key Methods:**
  - `test_state_match_yields_verified_success`: State confirmed matches target $\rightarrow$ `is_successful = True`.
  - `test_state_mismatch_not_verified_success`: State mismatch $\rightarrow$ `is_successful = False`.
  - `test_execution_failure_not_verified_success`: Provider error code $\rightarrow$ `is_successful = False`.
  - `test_blocked_safety_has_no_execution`: Blocked safety leaves `execution = None` and `is_successful = False`.
  - `test_workflow_report_embeds_verification`: Confirms `WorkflowReport` embeds full verification result.

### 5. Agent Decision Contracts
- **Test File:** `tests/unit/test_agent_contract.py` & `tests/test_regression.py`
- **Test Class:** `TestAgentContractRegression`
- **Key Methods:**
  - `test_valid_scale_down_proposal_structure`: Validates structured proposal generation.
  - `test_terminate_cluster_rejected` & `test_drop_db_rejected`: Rejects unauthorized actions.
  - `test_string_confidence_rejected`: Rejects string confidence (e.g. `"high"`).
  - `test_llm_timeout_payload_rejected`: Rejects empty or error payloads from LLM.

### 6. Orchestration Pipeline Ordering
- **Test File:** `tests/integration/test_orchestration.py` & `tests/test_regression.py`
- **Test Class:** `TestOrchestrationRegression`
- **Key Methods:**
  - `test_7_stage_workflow_schema_assembly`: Proves 7-stage workflow assembly.
  - `test_decision_embeds_investigation`: Proves investigation precedes decision.
  - `test_verification_requires_safety_check`: Proves safety cannot be bypassed.
  - `test_failed_execution_reaches_verification`: Proves execution failure flows to verification.

### 7. Browser and UI Truthfulness
- **Test File:** `tests/browser/test_cloud_cost_ui.py` & `tests/test_regression.py`
- **Test Class:** `TestBrowserUITruthfulnessRegression`
- **Key Methods:**
  - `test_four_outcome_states_are_distinct`: Enforces `VERIFIED_SUCCESS`, `BLOCKED`, `EXECUTION_FAILED`, `VERIFICATION_FAILURE`.
  - `test_blocked_safety_state_never_shows_success`: Prohibits success label on blocked action.
  - `test_execution_failure_never_shows_success`: Prohibits success label on execution failure.
  - `test_verification_failure_never_shows_verified_success`: Prohibits success label on state mismatch.
  - `test_http_200_alone_not_verified_success`: Proves HTTP 200 does not equal verified success.
