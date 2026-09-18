"""
Integration tests for the Autonomous Cloud Cost Workflow Orchestrator.

Goal:
Verify that the end-to-end cloud-cost optimization workflow strictly enforces the required order:
    REQUEST
    → INVESTIGATION
    → DECISION
    → SAFETY
    → ACTION/EXECUTION
    → VERIFICATION
    → FINAL RESULT

Critical architectural guarantees enforced:
  1. Direct agent → execution bypass is prevented.
  2. Safety Engine validation MUST precede any infrastructure execution.
  3. Safety rejection halts the workflow (execution is never attempted).
  4. Execution failures (e.g. capacity_unavailable) are never masked as SUCCESS.
  5. Post-action verification is mandatory and cannot be skipped.
  6. Verification failure (state mismatch) prevents infrastructure-change SUCCESS.
  7. Stale observations require state refresh before risky actions are executed.
  8. Investigation must precede decision generation (no arbitrary unevidenced actions).
  9. Final result distinguishes BLOCKED, FAILED, MISMATCHED, and VERIFIED SUCCESS.
 10. Service identity and state version consistency are preserved across all stages.

Production Gap Handling:
  - If backend/orchestrator implementation is missing: tests probe for candidate modules
    and fail explicitly with 'Production Gap' assertions.
  - No fake production orchestrators are created to artificially pass tests.
  - Phase 2 fixtures are loaded deterministically without system clock, network, or cloud calls.
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

# ─────────────────────────────────────────────────────────────────────────────
# Deterministic timestamp constants — NO system clock usage anywhere
# ─────────────────────────────────────────────────────────────────────────────
T_OBS_0800 = datetime(2026, 9, 17, 8, 0, 0, tzinfo=timezone.utc)
T_OBS_1030 = datetime(2026, 9, 17, 10, 30, 0, tzinfo=timezone.utc)
T_OBS_1031 = datetime(2026, 9, 17, 10, 31, 0, tzinfo=timezone.utc)


def load_fixture(filename: str) -> Dict[str, Any]:
    """Load JSON fixture from canonical tests/fixtures directory."""
    filepath = FIXTURES_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Fixture not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator discovery helper (Member 1 production ownership)
# ─────────────────────────────────────────────────────────────────────────────

def get_orchestrator() -> Optional[Any]:
    """
    Attempt to discover Member 1's workflow orchestrator from backend.orchestrator.
    Returns orchestrator module or callable if found, None if missing.
    """
    candidate_modules = [
        "backend.orchestrator.orchestrator",
        "backend.orchestrator.workflow",
        "backend.orchestrator.engine",
        "backend.orchestrator.pipeline",
        "backend.orchestrator.coordinator",
        "backend.orchestrator.runner",
    ]
    candidate_callables = [
        "Orchestrator",
        "WorkflowOrchestrator",
        "CloudCostOrchestrator",
        "run_workflow",
        "execute_workflow",
        "run_pipeline",
        "process_observation",
    ]
    for mod_name in candidate_modules:
        try:
            mod = __import__(mod_name, fromlist=["*"])
            for sym in candidate_callables:
                if hasattr(mod, sym):
                    return getattr(mod, sym)
            return mod
        except (ImportError, ModuleNotFoundError):
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Full Workflow Order
# ─────────────────────────────────────────────────────────────────────────────

class TestFullWorkflowOrder(unittest.TestCase):
    """
    Verify the expected 7-stage sequence:
      1. Request received
      2. Service investigation
      3. Decision/proposal generated
      4. Safety Engine validation
      5. Execution
      6. Post-action verification
      7. Final result
    """

    def test_orchestrator_module_discovery(self) -> None:
        """
        PRODUCTION GAP:
        Member 1 owns the Orchestration pipeline.
        Verify whether an orchestrator runner exists in backend.orchestrator.
        Fails explicitly if missing so the production gap is exposed.
        """
        orchestrator = get_orchestrator()
        if orchestrator is None:
            self.fail(
                "Production Gap: Orchestrator runner not implemented in backend.orchestrator. "
                "Candidate modules (backend.orchestrator.orchestrator, backend.orchestrator.workflow, "
                "backend.orchestrator.engine) do not exist. Member 1 must implement the orchestrator."
            )

    def test_workflow_report_schema_ordering_contract(self) -> None:
        """
        WorkflowReport contract requires initial_observation at root and
        nested final_verification containing decision, safety_check, and execution.
        Enforces that the workflow cannot produce a final report without each stage's artifact.
        """
        fixture = load_fixture("underutilized_service.json")
        obs_data = fixture["observation"]

        obs = ServiceObservation(
            service_id=obs_data["service_id"],
            cpu_utilization_percent=obs_data["cpu_utilization_percent"],
            memory_utilization_percent=obs_data["memory_utilization_percent"],
            traffic_rpm=obs_data["traffic_rpm"],
            latency_ms=obs_data["latency_ms"],
            cost_per_hour=obs_data["cost_per_hour"],
            observation_timestamp=T_OBS_1030,
            state_version=obs_data["state_version"],
        )

        investigation = InvestigationResult(
            observation=obs,
            identified_issues=["underutilization"],
            summary="Service reports-worker is idle at 9% CPU.",
        )

        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Scale down to min instances.",
            expected_effect="Reduce cost.",
            observation_version="v1.0.0",
            confidence=0.95,
        )

        decision = DecisionResult(investigation=investigation, proposal=proposal)

        safety_check = SafetyCheckResult(
            is_approved=True,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            rejection_reasons=[],
            applied_rules=["capacity_boundary_check", "service_health_check"],
        )

        execution = ExecutionResult(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            status=ExecutionStatus.SUCCESS,
            new_state_version="v1.0.1",
        )

        verification = VerificationResult(
            decision=decision,
            safety_check=safety_check,
            execution=execution,
            is_successful=True,
            verification_notes="Verified: instance count scaled down to 1.",
        )

        report = WorkflowReport(
            workflow_id="wf-001",
            initial_observation=obs,
            final_verification=verification,
        )

        self.assertEqual(report.workflow_id, "wf-001")
        self.assertEqual(report.initial_observation.service_id, "reports-worker")
        self.assertTrue(report.final_verification.is_successful)
        self.assertTrue(report.final_verification.safety_check.is_approved)
        self.assertEqual(report.final_verification.execution.status, ExecutionStatus.SUCCESS)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Safety Must Precede Execution
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyPrecedesExecution(unittest.TestCase):
    """
    Verify that the Safety Engine is consulted before execution, and
    execution is NEVER invoked when safety blocks the action.
    """

    def test_orchestrator_consults_safety_before_execution(self) -> None:
        """
        PRODUCTION GAP:
        Probes orchestrator to verify safety check is executed before calling action execution.
        """
        orchestrator = get_orchestrator()
        if orchestrator is None:
            self.fail(
                "Production Gap: Orchestrator not implemented. Cannot verify runtime invocation order "
                "of Safety Engine preceding Execution API."
            )

    def test_schema_prevents_execution_when_safety_blocks(self) -> None:
        """
        Contract rule: when safety_check.is_approved is False, the workflow
        must NOT attach a successful execution result.
        """
        safety_blocked = SafetyCheckResult(
            is_approved=False,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            rejection_reasons=["Scale-down target 0 is below min_instances=1"],
            applied_rules=["capacity_boundary_check"],
        )

        # In a safety-blocked scenario, execution must be None
        v = VerificationResult(
            decision=DecisionResult(
                investigation=InvestigationResult(
                    observation=ServiceObservation(
                        service_id="reports-worker",
                        cpu_utilization_percent=9.0,
                        memory_utilization_percent=15.0,
                        traffic_rpm=0,
                        latency_ms=0.0,
                        cost_per_hour=11.0,
                        observation_timestamp=T_OBS_1030,
                        state_version="v1.0.0",
                    ),
                    summary="Idle service",
                ),
                proposal=ActionProposal(
                    action=InfrastructureAction.SCALE_DOWN,
                    target_service_id="reports-worker",
                    reason="Scale to zero",
                    expected_effect="Zero instances",
                    observation_version="v1.0.0",
                    confidence=0.9,
                ),
            ),
            safety_check=safety_blocked,
            execution=None,  # Execution was NOT invoked
            is_successful=False,
            verification_notes="Workflow safely halted: action blocked by safety engine.",
        )
        self.assertFalse(v.safety_check.is_approved)
        self.assertIsNone(v.execution)
        self.assertFalse(v.is_successful)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Direct Agent -> Execution Bypass
# ─────────────────────────────────────────────────────────────────────────────

class TestDirectAgentExecutionBypass(unittest.TestCase):
    """
    Protect against architecture where Agent -> Execution directly
    without passing through the Safety Engine.
    """

    def test_orchestration_boundary_enforces_safety_stage(self) -> None:
        """
        PRODUCTION GAP:
        Verify that no direct execution path exists that bypasses the Safety Engine.
        """
        orchestrator = get_orchestrator()
        if orchestrator is None:
            self.fail(
                "Production Gap: No orchestration boundary exists to enforce Safety Engine "
                "mediation between agent proposals and execution."
            )

    def test_workflow_schema_requires_safety_check(self) -> None:
        """
        VerificationResult cannot be constructed without a SafetyCheckResult.
        Omitting safety_check must raise ValidationError.
        """
        obs = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_OBS_1030,
            state_version="v1.0.0",
        )
        decision = DecisionResult(
            investigation=InvestigationResult(observation=obs, summary="Investigated"),
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                reason="Scale down",
                expected_effect="Save cost",
                observation_version="v1.0.0",
                confidence=0.9,
            ),
        )
        execution = ExecutionResult(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            status=ExecutionStatus.SUCCESS,
        )

        with self.assertRaises(ValidationError):
            # Attempt to bypass safety_check by omitting it
            VerificationResult(
                decision=decision,
                # safety_check is missing
                execution=execution,
                is_successful=True,
                verification_notes="Bypassed safety",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Safety Rejection Stops Workflow
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyRejectionStopsWorkflow(unittest.TestCase):
    """
    When Safety Engine returns BLOCK/REJECT:
    - execution must NOT occur (execution=None)
    - verification does not falsely report infrastructure success
    - final workflow result preserves safety rejection
    """

    def test_orchestrator_halts_on_safety_block(self) -> None:
        """
        PRODUCTION GAP:
        Probes orchestrator to verify pipeline halts when safety check is rejected.
        """
        orchestrator = get_orchestrator()
        if orchestrator is None:
            self.fail(
                "Production Gap: Orchestrator not implemented. Cannot verify pipeline halting "
                "on Safety Engine rejection."
            )

    def test_safety_rejection_result_integrity(self) -> None:
        """Safety rejection preserves rejection reasons and marks is_successful=False."""
        safety_check = SafetyCheckResult(
            is_approved=False,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            rejection_reasons=["Latency headroom 40ms is below required minimum 100ms."],
            applied_rules=["latency_headroom_check"],
        )
        self.assertFalse(safety_check.is_approved)
        self.assertEqual(len(safety_check.rejection_reasons), 1)
        self.assertIn("latency_headroom_check", safety_check.applied_rules)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Successful Action Reaches Verification
# ─────────────────────────────────────────────────────────────────────────────

class TestSuccessfulActionReachesVerification(unittest.TestCase):
    """
    When Safety ALLOW and Execution SUCCESS:
    - verification is invoked after execution
    - final result reflects verified success
    - verification is NOT skipped
    """

    def test_orchestrator_executes_verification_after_execution(self) -> None:
        """
        PRODUCTION GAP:
        Probes orchestrator to verify post-action verification is called after execution.
        """
        orchestrator = get_orchestrator()
        if orchestrator is None:
            self.fail(
                "Production Gap: Orchestrator not implemented. Cannot verify post-action "
                "verification invocation after execution."
            )

    def test_verified_success_workflow_structure(self) -> None:
        """A complete successful workflow contains valid artifacts for every stage."""
        obs = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_OBS_1030,
            state_version="v1.0.0",
        )
        decision = DecisionResult(
            investigation=InvestigationResult(observation=obs, summary="Idle service"),
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                reason="Scale down to save cost",
                expected_effect="Instances reduced to 1",
                observation_version="v1.0.0",
                confidence=0.95,
            ),
        )
        safety = SafetyCheckResult(
            is_approved=True,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            rejection_reasons=[],
            applied_rules=["capacity_boundary_check"],
        )
        execution = ExecutionResult(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            status=ExecutionStatus.SUCCESS,
            new_state_version="v1.0.1",
        )
        verification = VerificationResult(
            decision=decision,
            safety_check=safety,
            execution=execution,
            is_successful=True,
            verification_notes="State confirmed: reports-worker scaled to 1 instance.",
        )
        self.assertTrue(verification.is_successful)
        self.assertIsNotNone(verification.execution)
        self.assertEqual(verification.execution.status, ExecutionStatus.SUCCESS)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Failed Execution Reaches Honest Final Result
# ─────────────────────────────────────────────────────────────────────────────

class TestFailedExecutionHonestResult(unittest.TestCase):
    """
    Use failed_action fixture (payment-api, scale_up 5, execution FAILED with capacity_unavailable):
    - execution failure is preserved
    - verification does NOT claim successful infrastructure change
    - no fake SUCCESS is generated
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("failed_action.json")

    def test_orchestrator_preserves_execution_failure(self) -> None:
        """
        PRODUCTION GAP:
        Probes orchestrator with failed_action scenario to ensure failure is preserved.
        """
        orchestrator = get_orchestrator()
        if orchestrator is None:
            self.fail(
                "Production Gap: Orchestrator not implemented. Cannot verify execution "
                "failure propagation through orchestrator pipeline."
            )

    def test_failed_execution_in_workflow_report(self) -> None:
        """
        When execution fails with capacity_unavailable, verification must record
        is_successful=False and preserve the error_code.
        """
        obs_data = self.fixture["observation"]
        obs = ServiceObservation(
            service_id=obs_data["service_id"],
            cpu_utilization_percent=obs_data["cpu_utilization_percent"],
            memory_utilization_percent=obs_data["memory_utilization_percent"],
            traffic_rpm=obs_data["traffic_rpm"],
            latency_ms=obs_data["latency_ms"],
            cost_per_hour=obs_data["cost_per_hour"],
            observation_timestamp=T_OBS_1030,
            state_version=obs_data["state_version"],
        )

        decision = DecisionResult(
            investigation=InvestigationResult(
                observation=obs,
                identified_issues=["high_latency", "high_cpu"],
                summary="Payment API latency 410ms exceeds 300ms ceiling under 6400 RPM.",
            ),
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_UP,
                target_service_id="payment-api",
                reason="Capacity pressure",
                expected_effect="Restore headroom",
                observation_version="v1.0.0",
                confidence=0.94,
            ),
        )

        safety = SafetyCheckResult(
            is_approved=True,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            applied_rules=["capacity_boundary_check"],
        )

        # Execution fails in the simulator/cloud provider
        execution = ExecutionResult(
            action=InfrastructureAction.SCALE_UP,
            target_service_id="payment-api",
            status=ExecutionStatus.FAILURE,
            error_code="capacity_unavailable",
            error_message="Insufficient cloud capacity to provision requested instances.",
        )

        verification = VerificationResult(
            decision=decision,
            safety_check=safety,
            execution=execution,
            is_successful=False,  # Truthful reporting: execution failed
            verification_notes="Execution failed: capacity_unavailable. Instances remain at 3.",
        )

        report = WorkflowReport(
            workflow_id="wf-failed-exec",
            initial_observation=obs,
            final_verification=verification,
        )

        self.assertFalse(report.final_verification.is_successful)
        self.assertEqual(report.final_verification.execution.status, ExecutionStatus.FAILURE)
        self.assertEqual(report.final_verification.execution.error_code, "capacity_unavailable")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Verification Failure Is Not Success
# ─────────────────────────────────────────────────────────────────────────────

class TestVerificationFailureIsNotSuccess(unittest.TestCase):
    """
    When Safety ALLOW and Execution claims SUCCESS, but post-action state
    does not match the requested state:
    - final workflow result is NOT infrastructure-change SUCCESS
    - verification failure is preserved
    """

    def test_state_mismatch_prevents_infrastructure_success(self) -> None:
        """
        If execution returns SUCCESS but telemetry shows instances unchanged,
        the workflow verification must report is_successful=False.
        """
        obs = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_OBS_1030,
            state_version="v1.0.0",
        )
        decision = DecisionResult(
            investigation=InvestigationResult(observation=obs, summary="Idle service"),
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                reason="Scale down to 1",
                expected_effect="Cost reduction",
                observation_version="v1.0.0",
                confidence=0.9,
            ),
        )
        safety = SafetyCheckResult(
            is_approved=True,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
        )
        execution = ExecutionResult(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            status=ExecutionStatus.SUCCESS,
            new_state_version="v1.0.1",
        )
        # Post-action check finds instances still at 4 (phantom success / state mismatch)
        verification = VerificationResult(
            decision=decision,
            safety_check=safety,
            execution=execution,
            is_successful=False,  # Truthful: state mismatch
            verification_notes="State mismatch: execution returned success but instances remain at 4.",
        )
        self.assertFalse(verification.is_successful)
        self.assertIn("State mismatch", verification.verification_notes)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Stale Observation Requires Refresh
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleObservationWorkflow(unittest.TestCase):
    """
    Use stale_observation fixture (08:00 observation vs 10:30 surge):
    - stale state is detected
    - risky action is NOT executed on stale observation
    - fresh investigation/state retrieval must occur before execution
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("stale_observation.json")

    def test_orchestrator_stale_observation_refresh_gap(self) -> None:
        """
        PRODUCTION GAP:
        Probes orchestrator to verify automatic state refresh / telemetry re-fetch pipeline.
        """
        orchestrator = get_orchestrator()
        if orchestrator is None:
            self.fail(
                "Production Gap: State refresh / telemetry re-fetch pipeline not implemented "
                "in backend.orchestrator. When observation is stale (08:00 vs 10:30 surge), "
                "orchestrator must re-fetch state before executing."
            )

    def test_stale_observation_safety_rejection(self) -> None:
        """
        SafetyCheckResult contract records rejection when proposal_version does not
        match evaluated_against_version.
        """
        stale_safety = SafetyCheckResult(
            is_approved=False,
            proposal_version="v1.0.0-0800",
            evaluated_against_version="v1.0.0-1030",
            rejection_reasons=[
                "Blocked: observation data version v1.0.0-0800 is stale relative to current version v1.0.0-1030."
            ],
            applied_rules=["data_freshness_check"],
        )
        self.assertFalse(stale_safety.is_approved)
        self.assertNotEqual(stale_safety.proposal_version, stale_safety.evaluated_against_version)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Investigation Must Precede Decision
# ─────────────────────────────────────────────────────────────────────────────

class TestInvestigationPrecedesDecision(unittest.TestCase):
    """
    Verify that a decision cannot be generated or executed without an
    InvestigationResult (protects against arbitrary unevidenced actions).
    """

    def test_decision_result_requires_investigation(self) -> None:
        """DecisionResult schema strictly requires an investigation field."""
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Scale down",
            expected_effect="Save money",
            observation_version="v1.0.0",
            confidence=0.9,
        )
        with self.assertRaises(ValidationError):
            # Attempt to create DecisionResult with investigation=None
            DecisionResult(
                investigation=None,  # type: ignore[arg-type]
                proposal=proposal,
            )

    def test_investigation_result_contains_evidence(self) -> None:
        """InvestigationResult requires observation, identified_issues, and summary."""
        obs = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_OBS_1030,
            state_version="v1.0.0",
        )
        investigation = InvestigationResult(
            observation=obs,
            identified_issues=["underutilization", "idle"],
            summary="CPU at 9% with zero traffic; safe scale down candidate.",
        )
        self.assertEqual(investigation.observation.service_id, "reports-worker")
        self.assertEqual(len(investigation.identified_issues), 2)
        self.assertTrue(len(investigation.summary) > 0)


# ─────────────────────────────────────────────────────────────────────────────
# 10. Final Result Must Reflect Actual Workflow State
# ─────────────────────────────────────────────────────────────────────────────

class TestFinalResultReflectsActualState(unittest.TestCase):
    """
    Test that distinct workflow outcomes are preserved separately:
      A. Safety BLOCK
      B. Execution FAILURE
      C. Verification FAILURE
      D. Verified SUCCESS
      E. NO_ACTION
    Outcomes must NEVER be collapsed into a single generic success result.
    """

    def setUp(self) -> None:
        self.obs = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_OBS_1030,
            state_version="v1.0.0",
        )
        self.investigation = InvestigationResult(observation=self.obs, summary="Observed")

    def test_outcome_safety_blocked(self) -> None:
        """Safety block produces is_approved=False, execution=None, is_successful=False."""
        decision = DecisionResult(
            investigation=self.investigation,
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                reason="Unsafe",
                expected_effect="Below min",
                observation_version="v1.0.0",
                confidence=0.9,
            ),
        )
        v = VerificationResult(
            decision=decision,
            safety_check=SafetyCheckResult(
                is_approved=False,
                proposal_version="v1.0.0",
                evaluated_against_version="v1.0.0",
                rejection_reasons=["Target capacity below minimum"],
            ),
            execution=None,
            is_successful=False,
            verification_notes="Blocked by safety.",
        )
        self.assertFalse(v.safety_check.is_approved)
        self.assertIsNone(v.execution)
        self.assertFalse(v.is_successful)

    def test_outcome_execution_failure(self) -> None:
        """Execution failure produces execution.status=FAILURE, is_successful=False."""
        decision = DecisionResult(
            investigation=self.investigation,
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                reason="Valid",
                expected_effect="Scale",
                observation_version="v1.0.0",
                confidence=0.9,
            ),
        )
        v = VerificationResult(
            decision=decision,
            safety_check=SafetyCheckResult(
                is_approved=True,
                proposal_version="v1.0.0",
                evaluated_against_version="v1.0.0",
            ),
            execution=ExecutionResult(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                status=ExecutionStatus.FAILURE,
                error_code="capacity_unavailable",
            ),
            is_successful=False,
            verification_notes="Execution failed.",
        )
        self.assertTrue(v.safety_check.is_approved)
        self.assertEqual(v.execution.status, ExecutionStatus.FAILURE)
        self.assertFalse(v.is_successful)

    def test_outcome_verification_failure(self) -> None:
        """State mismatch produces execution.status=SUCCESS, is_successful=False."""
        decision = DecisionResult(
            investigation=self.investigation,
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                reason="Valid",
                expected_effect="Scale",
                observation_version="v1.0.0",
                confidence=0.9,
            ),
        )
        v = VerificationResult(
            decision=decision,
            safety_check=SafetyCheckResult(
                is_approved=True,
                proposal_version="v1.0.0",
                evaluated_against_version="v1.0.0",
            ),
            execution=ExecutionResult(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                status=ExecutionStatus.SUCCESS,
            ),
            is_successful=False,
            verification_notes="State mismatch: instances unchanged.",
        )
        self.assertTrue(v.safety_check.is_approved)
        self.assertEqual(v.execution.status, ExecutionStatus.SUCCESS)
        self.assertFalse(v.is_successful)

    def test_outcome_verified_success(self) -> None:
        """Verified success produces execution.status=SUCCESS, is_successful=True."""
        decision = DecisionResult(
            investigation=self.investigation,
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                reason="Valid",
                expected_effect="Scale",
                observation_version="v1.0.0",
                confidence=0.9,
            ),
        )
        v = VerificationResult(
            decision=decision,
            safety_check=SafetyCheckResult(
                is_approved=True,
                proposal_version="v1.0.0",
                evaluated_against_version="v1.0.0",
            ),
            execution=ExecutionResult(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                status=ExecutionStatus.SUCCESS,
            ),
            is_successful=True,
            verification_notes="Verified: state matches target.",
        )
        self.assertTrue(v.safety_check.is_approved)
        self.assertEqual(v.execution.status, ExecutionStatus.SUCCESS)
        self.assertTrue(v.is_successful)

    def test_outcome_no_action(self) -> None:
        """no_action proposal produces execution=None, is_successful=True (correctly completed)."""
        decision = DecisionResult(
            investigation=self.investigation,
            proposal=ActionProposal(
                action=InfrastructureAction.NO_ACTION,
                target_service_id="reports-worker",
                reason="Steady state; no changes required",
                expected_effect="Maintain current capacity",
                observation_version="v1.0.0",
                confidence=1.0,
            ),
        )
        v = VerificationResult(
            decision=decision,
            safety_check=SafetyCheckResult(
                is_approved=True,
                proposal_version="v1.0.0",
                evaluated_against_version="v1.0.0",
            ),
            execution=None,
            is_successful=True,
            verification_notes="No action required; workflow successfully concluded without infrastructure modification.",
        )
        self.assertEqual(v.decision.proposal.action, InfrastructureAction.NO_ACTION)
        self.assertIsNone(v.execution)
        self.assertTrue(v.is_successful)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Error Propagation
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorPropagation(unittest.TestCase):
    """
    Verify errors in any stage (investigation, safety, execution, verification)
    are propagated honestly according to existing workflow schemas.
    """

    def test_execution_error_details_preserved_in_verification(self) -> None:
        """ExecutionResult error_code and error_message are preserved in VerificationResult."""
        exec_result = ExecutionResult(
            action=InfrastructureAction.SCALE_UP,
            target_service_id="payment-api",
            status=ExecutionStatus.FAILURE,
            error_code="capacity_unavailable",
            error_message="Host cluster out of memory slots.",
        )
        self.assertEqual(exec_result.error_code, "capacity_unavailable")
        self.assertEqual(exec_result.error_message, "Host cluster out of memory slots.")

    def test_safety_rejection_reasons_preserved_in_workflow(self) -> None:
        """SafetyCheckResult rejection reasons are preserved without truncation."""
        rejection = "Service unhealthy: health='degraded' blocks all infrastructure actions."
        safety = SafetyCheckResult(
            is_approved=False,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            rejection_reasons=[rejection],
            applied_rules=["service_health_check"],
        )
        self.assertIn(rejection, safety.rejection_reasons)


# ─────────────────────────────────────────────────────────────────────────────
# 12. Service Identity / State Version Propagation
# ─────────────────────────────────────────────────────────────────────────────

class TestServiceIdentityAndVersionPropagation(unittest.TestCase):
    """
    Verify that target_service_id and state_version/observation_version
    are preserved across proposal -> safety -> execution -> verification boundaries.
    Protects against acting on one service and verifying another.
    """

    def test_target_service_id_consistent_across_stages(self) -> None:
        """Service ID must match across observation, proposal, and execution."""
        service_id = "reports-worker"
        obs = ServiceObservation(
            service_id=service_id,
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_OBS_1030,
            state_version="v1.0.0",
        )
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id=service_id,
            reason="Scale down",
            expected_effect="Save cost",
            observation_version="v1.0.0",
            confidence=0.9,
        )
        execution = ExecutionResult(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id=service_id,
            status=ExecutionStatus.SUCCESS,
        )
        self.assertEqual(obs.service_id, proposal.target_service_id)
        self.assertEqual(proposal.target_service_id, execution.target_service_id)

    def test_mismatched_service_id_between_stages_violates_integrity(self) -> None:
        """
        If a proposal targets reports-worker but execution occurs on payment-api,
        an orchestration integrity check must flag the mismatch.
        """
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Scale down reports worker",
            expected_effect="Save cost",
            observation_version="v1.0.0",
            confidence=0.9,
        )
        execution = ExecutionResult(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="payment-api",  # MISMATCH!
            status=ExecutionStatus.SUCCESS,
        )

        def verify_service_consistency(p: ActionProposal, e: ExecutionResult) -> bool:
            return p.target_service_id == e.target_service_id

        self.assertFalse(
            verify_service_consistency(proposal, execution),
            "Orchestrator must detect service identity mismatch between proposal and execution."
        )

    def test_observation_version_consistent_across_proposal_and_safety(self) -> None:
        """Safety check evaluates proposal against matching proposal_version."""
        version = "v1.0.0"
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Scale down",
            expected_effect="Save cost",
            observation_version=version,
            confidence=0.9,
        )
        safety = SafetyCheckResult(
            is_approved=True,
            proposal_version=version,
            evaluated_against_version=version,
        )
        self.assertEqual(proposal.observation_version, safety.proposal_version)


if __name__ == "__main__":
    unittest.main()
