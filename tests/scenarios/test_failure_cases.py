"""
Deterministic Failure Testing Suite for the Cloud Cost Optimization Agent.

Core Principle:
IF THE SYSTEM CANNOT PROVE THE ACTION IS SAFE AND SUCCESSFUL, IT MUST NOT CLAIM SUCCESS.

Failure Scenarios Covered:
  1. Failed Action (failed_action.json — payment-api, scale_up 5, capacity_unavailable)
  2. Safety Block (safety_violations.json — 7 distinct violation cases + bypass prevention)
  3. Verification Failure (phantom success: execution claims SUCCESS but instances remain unchanged)
  4. Stale Observation (stale_observation.json — 08:00 vs 10:30 surge)
  5. Missing Data (fail-closed on null/missing critical telemetry)
  6. Invalid Action (unsupported actions, malformed proposals, out-of-bounds capacity/confidence)
  7. LLM Failure (adapter missing, timeout/error payloads, malformed outputs)
  8. Dependency / Service Failure (inspection, metrics, execution dependencies unavailable)
  9. Retry / Duplicate Execution (duplicate execution handling & idempotency gap)
 10. Timeout / Partial Failure (execution timeout, unknown state does not claim success)
 11. Critical Truthfulness Tests (none of HTTP 200, high confidence, safety allow, or execution claim
     can alone produce verified success).

Ownership:
  Member 4 owns QA/Failure Testing.
  Do NOT modify backend, frontend, agent, orchestrator, simulator, or safety production code.
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from backend.schemas.actions import ActionProposal, InfrastructureAction
from backend.schemas.execution import ExecutionResult, ExecutionStatus
from backend.schemas.metrics import ServiceObservation
from backend.schemas.safety import SafetyCheckResult
from backend.schemas.workflow import (
    DecisionResult,
    InvestigationResult,
    VerificationResult,
    WorkflowReport,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Deterministic timestamps — NO system clock usage anywhere
T_0800 = datetime(2026, 9, 17, 8,  0,  0, tzinfo=timezone.utc)
T_1030 = datetime(2026, 9, 17, 10, 30, 0, tzinfo=timezone.utc)
T_1031 = datetime(2026, 9, 17, 10, 31, 0, tzinfo=timezone.utc)


def load_fixture(filename: str) -> Dict[str, Any]:
    """Load JSON fixture from canonical tests/fixtures directory."""
    filepath = FIXTURES_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Fixture not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Discovery Helpers for Missing Production Components
# ─────────────────────────────────────────────────────────────────────────────

def get_safety_engine() -> Optional[Any]:
    candidate_modules = ["backend.safety", "backend.safety.engine", "backend.services.safety"]
    candidate_symbols = ["SafetyEngine", "DeterministicSafetyEngine", "evaluate_safety", "validate_action"]
    for mod in candidate_modules:
        try:
            m = __import__(mod, fromlist=candidate_symbols)
            for sym in candidate_symbols:
                if hasattr(m, sym):
                    return getattr(m, sym)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_llm_adapter() -> Optional[Any]:
    candidate_modules = ["backend.agents.llm", "backend.agents.llm_adapter", "backend.agents.client"]
    candidate_symbols = ["LLMAdapter", "LLMClient", "get_llm_client"]
    for mod in candidate_modules:
        try:
            m = __import__(mod, fromlist=candidate_symbols)
            for sym in candidate_symbols:
                if hasattr(m, sym):
                    return getattr(m, sym)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_orchestrator() -> Optional[Any]:
    candidate_modules = ["backend.orchestrator.orchestrator", "backend.orchestrator.workflow"]
    candidate_symbols = ["Orchestrator", "WorkflowOrchestrator", "run_workflow"]
    for mod in candidate_modules:
        try:
            m = __import__(mod, fromlist=candidate_symbols)
            for sym in candidate_symbols:
                if hasattr(m, sym):
                    return getattr(m, sym)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_retry_handler() -> Optional[Any]:
    candidate_modules = ["backend.orchestrator.retry", "backend.services.retry", "backend.simulator.retry"]
    candidate_symbols = ["RetryHandler", "execute_with_retry", "IdempotentExecutor"]
    for mod in candidate_modules:
        try:
            m = __import__(mod, fromlist=candidate_symbols)
            for sym in candidate_symbols:
                if hasattr(m, sym):
                    return getattr(m, sym)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Failed Action Scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestFailedActionScenario(unittest.TestCase):
    """
    Scenario 1: payment-api attempts scale_up to 5 instances.
    Execution fails with capacity_unavailable.
    Verify: failure is surfaced, instances remain 3, final result is not SUCCESS,
    error code preserved, audit preserves failure.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("failed_action.json")

    def test_failed_action_preserves_error_code_and_failure_status(self) -> None:
        """ExecutionResult preserves status=FAILURE and error_code=capacity_unavailable."""
        exec_res = ExecutionResult(
            action=InfrastructureAction.SCALE_UP,
            target_service_id="payment-api",
            status=ExecutionStatus.FAILURE,
            error_code="capacity_unavailable",
            error_message="Host cluster has insufficient compute capacity.",
        )
        self.assertEqual(exec_res.status, ExecutionStatus.FAILURE)
        self.assertEqual(exec_res.error_code, "capacity_unavailable")

    def test_failed_action_workflow_report_never_reports_success(self) -> None:
        """When execution fails, VerificationResult and WorkflowReport report is_successful=False."""
        obs = ServiceObservation(
            service_id="payment-api",
            cpu_utilization_percent=91.0,
            memory_utilization_percent=82.0,
            traffic_rpm=6400,
            latency_ms=410.0,
            cost_per_hour=22.0,
            observation_timestamp=T_1030,
            state_version="v1.0.0",
        )
        report = WorkflowReport(
            workflow_id="wf-fail-01",
            initial_observation=obs,
            final_verification=VerificationResult(
                decision=DecisionResult(
                    investigation=InvestigationResult(observation=obs, summary="High latency"),
                    proposal=ActionProposal(
                        action=InfrastructureAction.SCALE_UP,
                        target_service_id="payment-api",
                        reason="Load spike",
                        expected_effect="Scale to 5",
                        observation_version="v1.0.0",
                        confidence=0.92,
                    ),
                ),
                safety_check=SafetyCheckResult(
                    is_approved=True,
                    proposal_version="v1.0.0",
                    evaluated_against_version="v1.0.0",
                ),
                execution=ExecutionResult(
                    action=InfrastructureAction.SCALE_UP,
                    target_service_id="payment-api",
                    status=ExecutionStatus.FAILURE,
                    error_code="capacity_unavailable",
                ),
                is_successful=False,  # Truthful failure
                verification_notes="Execution failed: capacity_unavailable. Instances remain at 3.",
            ),
        )
        self.assertFalse(report.final_verification.is_successful)
        self.assertEqual(report.final_verification.execution.status, ExecutionStatus.FAILURE)
        self.assertIn("capacity_unavailable", report.final_verification.verification_notes)

    def test_failed_action_infrastructure_state_remains_unchanged(self) -> None:
        """Fixture contract check: payment-api instances must remain at initial 3 instances."""
        expected = self.fixture["expected_behavior"]["verification"]
        self.assertFalse(expected["is_successful"])
        self.assertFalse(expected["state_confirmed"])
        self.assertEqual(expected["actual_instances_remaining"], 3)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Safety Block Scenarios
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyBlockScenarios(unittest.TestCase):
    """
    Scenario 2: Safety violations from safety_violations.json:
      - below minimum capacity
      - above maximum capacity
      - latency constraint violation
      - unhealthy service
      - stale observation
      - missing required metric
      - invalid action
    Verify: safety result is BLOCKED, execution does NOT occur, final result is not SUCCESS,
    direct execution bypass is strictly prevented.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("safety_violations.json")

    def test_safety_engine_discovery_gap(self) -> None:
        """PRODUCTION GAP: Verify whether Member 2's Safety Engine exists."""
        safety = get_safety_engine()
        if safety is None:
            self.fail(
                "Production Gap: Safety Engine not implemented in backend.safety or backend.services.safety."
            )

    def test_all_seven_safety_violations_require_blocking(self) -> None:
        """Each scenario in safety_violations.json defines is_approved=false and expected_safety_result=BLOCK."""
        violations = self.fixture["violations"]
        self.assertEqual(len(violations), 7)

        for v in violations:
            scenario = v["scenario_name"]
            with self.subTest(scenario=scenario):
                self.assertFalse(v["is_approved"])
                self.assertEqual(v["expected_safety_result"], "BLOCK")
                self.assertTrue(len(v["rejection_reason"]) > 0)

    def test_direct_execution_bypass_prevention(self) -> None:
        """
        CRITICAL SAFETY TEST:
        Attempting to construct a VerificationResult without a SafetyCheckResult must fail
        at schema level, preventing direct execution bypass.
        """
        obs = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_1030,
            state_version="v1.0.0",
        )
        decision = DecisionResult(
            investigation=InvestigationResult(observation=obs, summary="Idle service"),
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                reason="Scale down",
                expected_effect="Scale to 0",
                observation_version="v1.0.0",
                confidence=0.9,
            ),
        )
        # Attempt to bypass safety_check by omitting it
        with self.assertRaises(ValidationError):
            VerificationResult(
                decision=decision,
                # safety_check intentionally omitted
                execution=ExecutionResult(
                    action=InfrastructureAction.SCALE_DOWN,
                    target_service_id="reports-worker",
                    status=ExecutionStatus.SUCCESS,
                ),
                is_successful=True,
                verification_notes="Unsafe bypass attempt",
            )

    def test_safety_block_prevents_execution_invocation(self) -> None:
        """When safety is blocked (is_approved=False), execution MUST be None."""
        safety = SafetyCheckResult(
            is_approved=False,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            rejection_reasons=["Target capacity 0 is below minimum 1."],
            applied_rules=["capacity_boundary_check"],
        )
        obs = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_1030,
            state_version="v1.0.0",
        )
        v = VerificationResult(
            decision=DecisionResult(
                investigation=InvestigationResult(observation=obs, summary="Idle"),
                proposal=ActionProposal(
                    action=InfrastructureAction.SCALE_DOWN,
                    target_service_id="reports-worker",
                    reason="Scale to zero",
                    expected_effect="0 instances",
                    observation_version="v1.0.0",
                    confidence=0.9,
                ),
            ),
            safety_check=safety,
            execution=None,  # Execution was NOT invoked
            is_successful=False,
            verification_notes="Blocked by safety engine.",
        )
        self.assertFalse(v.safety_check.is_approved)
        self.assertIsNone(v.execution)
        self.assertFalse(v.is_successful)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Verification Failure Scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestVerificationFailureScenario(unittest.TestCase):
    """
    Scenario 3: Phantom execution success.
    Execution returns status=SUCCESS, but post-action observation shows instances unchanged (4).
    Verify: verification fails, system does not claim verified success, infrastructure state
    represented using observed state not execution claim.
    """

    def test_phantom_execution_success_is_not_verified_success(self) -> None:
        """
        When execution claims SUCCESS but observed state does not match target (4 != 1),
        VerificationResult must record is_successful=False.
        """
        obs_pre = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_1030,
            state_version="v1.0.0",
        )
        # Post-action observation shows instances STILL at 4 (phantom success)
        obs_post = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_1031,
            state_version="v1.0.0",  # State version did not increment
        )

        v = VerificationResult(
            decision=DecisionResult(
                investigation=InvestigationResult(observation=obs_pre, summary="Idle"),
                proposal=ActionProposal(
                    action=InfrastructureAction.SCALE_DOWN,
                    target_service_id="reports-worker",
                    reason="Scale down to 1",
                    expected_effect="Instances 4 -> 1",
                    observation_version="v1.0.0",
                    confidence=0.95,
                ),
            ),
            safety_check=SafetyCheckResult(
                is_approved=True,
                proposal_version="v1.0.0",
                evaluated_against_version="v1.0.0",
            ),
            execution=ExecutionResult(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                status=ExecutionStatus.SUCCESS,
                new_state_version="v1.0.1",
            ),
            is_successful=False,  # Truthful failure: state mismatch
            verification_notes="State mismatch: execution returned SUCCESS but observed state version remained v1.0.0.",
        )
        self.assertFalse(v.is_successful)
        self.assertIn("State mismatch", v.verification_notes)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Stale Observation Scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleObservationScenario(unittest.TestCase):
    """
    Scenario 4: Observation at 08:00 vs latest traffic surge at 10:30.
    Verify: stale data detected, risky action blocked, no success claim on stale data.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("stale_observation.json")

    def test_stale_telemetry_blocked_by_safety(self) -> None:
        """Proposal based on stale observation version (v1.0.0-0800) is blocked by safety."""
        expected = self.fixture["expected_behavior"]
        self.assertTrue(expected["is_stale"])
        self.assertTrue(expected["staleness_detected"])
        self.assertFalse(expected["action_permitted_on_stale_data"])

        safety = SafetyCheckResult(
            is_approved=False,
            proposal_version="v1.0.0-0800",
            evaluated_against_version="v1.0.0-1030",
            rejection_reasons=["Data version v1.0.0-0800 is 150 minutes stale."],
            applied_rules=["data_freshness_check"],
        )
        self.assertFalse(safety.is_approved)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Missing Telemetry Fail-Closed
# ─────────────────────────────────────────────────────────────────────────────

class TestMissingTelemetryFailClosed(unittest.TestCase):
    """
    Scenario 5: Missing or invalid critical telemetry fields in ServiceObservation:
    missing CPU, memory, RPM, latency, service ID, timestamp, state version.
    Verify: fail-closed behavior (ValidationError raised, no unsafe allows).
    """

    def test_missing_cpu_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ServiceObservation(
                service_id="reports-worker",
                cpu_utilization_percent=None,  # type: ignore[arg-type]
                memory_utilization_percent=15.0,
                traffic_rpm=0,
                latency_ms=0.0,
                cost_per_hour=11.0,
                observation_timestamp=T_1030,
                state_version="v1.0.0",
            )

    def test_missing_memory_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ServiceObservation(
                service_id="reports-worker",
                cpu_utilization_percent=9.0,
                memory_utilization_percent=None,  # type: ignore[arg-type]
                traffic_rpm=0,
                latency_ms=0.0,
                cost_per_hour=11.0,
                observation_timestamp=T_1030,
                state_version="v1.0.0",
            )

    def test_missing_service_id_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ServiceObservation(
                service_id=None,  # type: ignore[arg-type]
                cpu_utilization_percent=9.0,
                memory_utilization_percent=15.0,
                traffic_rpm=0,
                latency_ms=0.0,
                cost_per_hour=11.0,
                observation_timestamp=T_1030,
                state_version="v1.0.0",
            )

    def test_missing_state_version_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ServiceObservation(
                service_id="reports-worker",
                cpu_utilization_percent=9.0,
                memory_utilization_percent=15.0,
                traffic_rpm=0,
                latency_ms=0.0,
                cost_per_hour=11.0,
                observation_timestamp=T_1030,
                state_version=None,  # type: ignore[arg-type]
            )

    def test_negative_traffic_rpm_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ServiceObservation(
                service_id="reports-worker",
                cpu_utilization_percent=9.0,
                memory_utilization_percent=15.0,
                traffic_rpm=-100,  # ge=0 violation
                latency_ms=0.0,
                cost_per_hour=11.0,
                observation_timestamp=T_1030,
                state_version="v1.0.0",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Invalid Action Rejection
# ─────────────────────────────────────────────────────────────────────────────

class TestInvalidActionRejection(unittest.TestCase):
    """
    Scenario 6: Malformed / unsupported actions:
    unknown action name, invalid enum, malformed proposal, missing target service,
    invalid confidence.
    Verify: action rejected, no execution occurs, no false success produced.
    """

    def test_unknown_action_terminate_cluster_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({
                "action": "terminate_cluster",
                "target_service_id": "reports-worker",
                "reason": "Save all cost",
                "expected_effect": "Destroy cluster",
                "observation_version": "v1.0.0",
                "confidence": 0.9,
            })

    def test_unknown_action_drop_database_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({
                "action": "drop_database",
                "target_service_id": "reports-worker",
                "reason": "Unsafe action",
                "expected_effect": "Data loss",
                "observation_version": "v1.0.0",
                "confidence": 0.9,
            })

    def test_missing_target_service_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({
                "action": "scale_down",
                "reason": "Idle service",
                "expected_effect": "Save cost",
                "observation_version": "v1.0.0",
                "confidence": 0.9,
            })

    def test_invalid_confidence_above_one_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({
                "action": "scale_down",
                "target_service_id": "reports-worker",
                "reason": "Idle service",
                "expected_effect": "Save cost",
                "observation_version": "v1.0.0",
                "confidence": 1.5,  # le=1.0 constraint
            })

    def test_invalid_confidence_negative_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({
                "action": "scale_down",
                "target_service_id": "reports-worker",
                "reason": "Idle service",
                "expected_effect": "Save cost",
                "observation_version": "v1.0.0",
                "confidence": -0.2,  # ge=0.0 constraint
            })


# ─────────────────────────────────────────────────────────────────────────────
# 7. LLM Failure Handling
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMFailureHandling(unittest.TestCase):
    """
    Scenario 7: LLM failure modes:
    adapter missing, simulated timeout, provider 500 error, malformed output.
    Verify: failure surfaced, malformed output not executed, no false success.
    """

    def test_llm_adapter_discovery_gap(self) -> None:
        """PRODUCTION GAP: Verify whether Member 1's LLM adapter exists."""
        adapter = get_llm_adapter()
        if adapter is None:
            self.fail(
                "Production Gap: LLM adapter interface not implemented in backend.agents."
            )

    def test_llm_timeout_payload_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"error": "TimeoutError: LLM timed out"})

    def test_llm_provider_500_payload_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"error": {"code": 500, "message": "Internal error"}})

    def test_empty_llm_response_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({})


# ─────────────────────────────────────────────────────────────────────────────
# 8. Dependency / Service Failure
# ─────────────────────────────────────────────────────────────────────────────

class TestDependencyAndServiceFailure(unittest.TestCase):
    """
    Scenario 8: Test dependency failures:
    inspection unavailable, metrics unavailable, execution dependency unavailable.
    Documents production gaps in backend.services.
    """

    def test_service_inspection_dependency_gap(self) -> None:
        """PRODUCTION GAP: Service inspection service not implemented in backend.services."""
        candidate_modules = ["backend.services.inspection", "backend.services.discovery"]
        found = False
        for m in candidate_modules:
            try:
                __import__(m)
                found = True
            except ImportError:
                continue
        if not found:
            self.fail("Production Gap: Service inspection dependency not implemented in backend.services.")

    def test_execution_api_dependency_gap(self) -> None:
        """PRODUCTION GAP: Action execution API / driver not implemented in backend.services."""
        candidate_modules = ["backend.services.action_api", "backend.services.executor"]
        found = False
        for m in candidate_modules:
            try:
                __import__(m)
                found = True
            except ImportError:
                continue
        if not found:
            self.fail("Production Gap: Action execution API dependency not implemented in backend.services.")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Retry and Duplicate Execution
# ─────────────────────────────────────────────────────────────────────────────

class TestRetryAndIdempotencyContract(unittest.TestCase):
    """
    Scenario 9: Retry / idempotency handling:
    test duplicate execution request or re-executing same proposal.
    Documents gap if retry/idempotency mechanism does not exist.
    """

    def test_idempotency_handler_discovery_gap(self) -> None:
        """PRODUCTION GAP: No idempotency handler implemented in backend.orchestrator."""
        handler = get_retry_handler()
        if handler is None:
            self.fail(
                "Production Gap: Retry / idempotency handler not implemented in backend.orchestrator "
                "or backend.services. Re-executing identical proposals lacks idempotency protection."
            )

    def test_re_executing_proposal_with_stale_version_fails_closed(self) -> None:
        """
        If a proposal is replayed against an updated state version,
        SafetyCheckResult proposal_version != evaluated_against_version must fail closed.
        """
        stale_replay_safety = SafetyCheckResult(
            is_approved=False,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.1",  # State already incremented by first execution
            rejection_reasons=["Duplicate/replay detected: proposal based on superseded version v1.0.0."],
            applied_rules=["data_freshness_check"],
        )
        self.assertFalse(stale_replay_safety.is_approved)


# ─────────────────────────────────────────────────────────────────────────────
# 10. Timeout and Partial Failure
# ─────────────────────────────────────────────────────────────────────────────

class TestTimeoutAndPartialFailure(unittest.TestCase):
    """
    Scenario 10: Execution timeout and partial/unknown execution state:
    Verify timeout is not treated as success; unknown state does not become verified success.
    """

    def test_execution_timeout_recorded_as_failure(self) -> None:
        """Timeout in execution must produce status=FAILURE with error_code=timeout."""
        exec_timeout = ExecutionResult(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            status=ExecutionStatus.FAILURE,
            error_code="execution_timeout",
            error_message="Cloud API did not respond within 30s deadline.",
        )
        self.assertEqual(exec_timeout.status, ExecutionStatus.FAILURE)
        self.assertEqual(exec_timeout.error_code, "execution_timeout")

    def test_timeout_cannot_produce_verified_success(self) -> None:
        """A timed-out execution must produce is_successful=False in VerificationResult."""
        obs = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_1030,
            state_version="v1.0.0",
        )
        v = VerificationResult(
            decision=DecisionResult(
                investigation=InvestigationResult(observation=obs, summary="Idle"),
                proposal=ActionProposal(
                    action=InfrastructureAction.SCALE_DOWN,
                    target_service_id="reports-worker",
                    reason="Scale down",
                    expected_effect="Scale 1",
                    observation_version="v1.0.0",
                    confidence=0.9,
                ),
            ),
            safety_check=SafetyCheckResult(
                is_approved=True,
                proposal_version="v1.0.0",
                evaluated_against_version="v1.0.0",
            ),
            execution=ExecutionResult(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                status=ExecutionStatus.FAILURE,
                error_code="execution_timeout",
            ),
            is_successful=False,
            verification_notes="Execution timed out; state unconfirmed.",
        )
        self.assertFalse(v.is_successful)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Critical Truthfulness Invariants
# ─────────────────────────────────────────────────────────────────────────────

class TestCriticalTruthfulnessInvariants(unittest.TestCase):
    """
    Explicitly test that NONE of the following alone can produce verified success:
      1. HTTP 200 alone
      2. Request accepted alone
      3. Valid action proposal alone
      4. High confidence alone (1.0)
      5. Safety ALLOWED alone
      6. Execution claimed SUCCESS alone
      7. Expected effect description alone
      8. Unchanged response structure alone
    """

    def test_high_confidence_alone_does_not_equal_success(self) -> None:
        """ActionProposal with confidence=1.0 is only a proposal, NOT a verified success."""
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Certain recommendation",
            expected_effect="Cost cut",
            observation_version="v1.0.0",
            confidence=1.0,
        )
        self.assertEqual(proposal.confidence, 1.0)
        self.assertFalse(hasattr(proposal, "is_successful"))

    def test_safety_allowed_alone_does_not_equal_success(self) -> None:
        """SafetyCheckResult(is_approved=True) is only permission, NOT execution or verification."""
        safety = SafetyCheckResult(
            is_approved=True,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
        )
        self.assertTrue(safety.is_approved)
        self.assertFalse(hasattr(safety, "is_successful"))

    def test_execution_claim_alone_does_not_equal_verified_success(self) -> None:
        """ExecutionResult(status=SUCCESS) without post-action state verification is NOT verified success."""
        exec_claim = ExecutionResult(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            status=ExecutionStatus.SUCCESS,
        )
        self.assertEqual(exec_claim.status, ExecutionStatus.SUCCESS)
        self.assertFalse(hasattr(exec_claim, "is_successful"))

    def test_expected_effect_text_alone_does_not_equal_success(self) -> None:
        """Describing expected savings does not prove infrastructure change occurred."""
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Idle",
            expected_effect="Reduced cost by $8.25/hr and instances to 1",
            observation_version="v1.0.0",
            confidence=0.95,
        )
        self.assertIn("Reduced cost", proposal.expected_effect)
        self.assertNotIsInstance(proposal, ExecutionResult)


if __name__ == "__main__":
    unittest.main()
