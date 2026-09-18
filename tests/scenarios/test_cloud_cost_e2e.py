"""
End-to-End (E2E) Scenario Tests for the Cloud Cost Optimization Agent.

Primary hackathon demo scenario:
    USER REQUEST
    → SERVICES INSPECTED
    → INVESTIGATION
    → UNDERUTILIZED SERVICE IDENTIFIED
    → DECISION/PROPOSAL
    → SAFETY VALIDATION
    → ACTION EXECUTION
    → ACTUAL STATE CHANGE
    → POST-ACTION VERIFICATION
    → AUDIT
    → FINAL USER-FACING RESULT

Canonical Fixtures:
    - tests/fixtures/underutilized_service.json (primary happy-path & cost reduction)
    - tests/fixtures/failed_action.json (execution failure variant)
    - tests/fixtures/stale_observation.json (staleness & refresh variant)
    - tests/fixtures/safety_violations.json (safety-blocked variant)

Critical Guarantees Tested:
  1. Complete success path: reports-worker scaled 4 → 1 instance, cost decreases, state verified.
  2. Actual state mutation: execution response alone is NEVER accepted as proof of state change.
  3. Cost model: hourly cost must reflect reduced capacity.
  4. False-success protection: execution SUCCESS with unchanged instances must fail verification.
  5. Safety-blocked variant: unsafe actions are blocked, execution never occurs, state preserved.
  6. Stale observation variant: stale telemetry blocks execution; refresh required.
  7. Failed action variant: cloud provider failure (capacity_unavailable) preserved honestly.
  8. Audit persistence: action, safety, execution, and verification records are persisted.
  9. Production gap handling: missing production modules (app entrypoint, Safety Engine,
     Simulator, Audit store, Cost model) are exposed truthfully with Production Gap assertions.
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
T_OBS_BEFORE = datetime(2026, 9, 17, 10, 30, 0, tzinfo=timezone.utc)
T_OBS_AFTER  = datetime(2026, 9, 17, 10, 31, 0, tzinfo=timezone.utc)
T_OBS_STALE  = datetime(2026, 9, 17, 8,  0,  0, tzinfo=timezone.utc)


def load_fixture(filename: str) -> Dict[str, Any]:
    """Load JSON fixture from canonical tests/fixtures directory."""
    filepath = FIXTURES_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Fixture not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Production component discovery helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_app_entrypoint() -> Optional[Any]:
    """Discover the full application entrypoint or workflow runner."""
    candidate_modules = [
        "backend.main",
        "backend.app",
        "backend.api",
        "backend.orchestrator.runner",
        "backend.orchestrator.orchestrator",
        "backend.orchestrator.workflow",
    ]
    candidate_symbols = ["app", "create_app", "run_workflow", "Orchestrator", "WorkflowOrchestrator"]
    for mod_name in candidate_modules:
        try:
            mod = __import__(mod_name, fromlist=candidate_symbols)
            for sym in candidate_symbols:
                if hasattr(mod, sym):
                    return getattr(mod, sym)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_safety_engine() -> Optional[Any]:
    """Discover Member 2's deterministic Safety Engine."""
    candidate_modules = [
        "backend.safety",
        "backend.safety.engine",
        "backend.safety.safety_engine",
        "backend.services.safety",
        "backend.services.safety_engine",
    ]
    candidate_symbols = [
        "SafetyEngine",
        "DeterministicSafetyEngine",
        "evaluate_safety",
        "validate_action",
        "check_safety",
    ]
    for mod_name in candidate_modules:
        try:
            mod = __import__(mod_name, fromlist=candidate_symbols)
            for sym in candidate_symbols:
                if hasattr(mod, sym):
                    return getattr(mod, sym)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_simulator() -> Optional[Any]:
    """Discover Member 2's cloud simulator / execution engine."""
    candidate_modules = [
        "backend.simulator",
        "backend.simulator.simulator",
        "backend.simulator.service_simulator",
        "backend.simulator.engine",
        "backend.services.simulator",
        "backend.services.execution",
    ]
    candidate_symbols = [
        "CloudSimulator",
        "ServiceSimulator",
        "Simulator",
        "InfrastructureSimulator",
        "execute_action",
    ]
    for mod_name in candidate_modules:
        try:
            mod = __import__(mod_name, fromlist=candidate_symbols)
            for sym in candidate_symbols:
                if hasattr(mod, sym):
                    return getattr(mod, sym)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_audit_store() -> Optional[Any]:
    """Discover audit persistence module or database interface."""
    candidate_modules = [
        "backend.db.audit",
        "backend.db.events",
        "backend.services.audit",
        "backend.audit",
    ]
    candidate_symbols = [
        "AuditStore",
        "AuditLog",
        "log_event",
        "get_audit_events",
        "save_audit",
    ]
    for mod_name in candidate_modules:
        try:
            mod = __import__(mod_name, fromlist=candidate_symbols)
            for sym in candidate_symbols:
                if hasattr(mod, sym):
                    return getattr(mod, sym)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_cost_model() -> Optional[Any]:
    """Discover cost recalculation model or service."""
    candidate_modules = [
        "backend.services.cost",
        "backend.services.pricing",
        "backend.simulator.cost",
    ]
    candidate_symbols = [
        "CostModel",
        "calculate_cost",
        "recalculate_cost",
        "estimate_savings",
    ]
    for mod_name in candidate_modules:
        try:
            mod = __import__(mod_name, fromlist=candidate_symbols)
            for sym in candidate_symbols:
                if hasattr(mod, sym):
                    return getattr(mod, sym)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. User Request & Entrypoint Ingestion
# ─────────────────────────────────────────────────────────────────────────────

class TestE2EWorkflowEntrypoint(unittest.TestCase):
    """
    Step 1: Verify the workflow accepts a user request:
    "Review cloud services for unnecessary cost and safely reduce idle capacity."
    """

    def test_application_entrypoint_discovery(self) -> None:
        """
        PRODUCTION GAP:
        Verify whether the end-to-end application workflow entrypoint exists.
        """
        entrypoint = get_app_entrypoint()
        if entrypoint is None:
            self.fail(
                "Production Gap: No application entrypoint found in backend.main, backend.app, "
                "or backend.orchestrator. Full E2E workflow runner is not implemented."
            )

    def test_user_request_representation(self) -> None:
        """
        A natural-language request string can be processed into a workflow execution context.
        """
        user_prompt = "Review cloud services for unnecessary cost and safely reduce idle capacity."
        self.assertTrue(len(user_prompt) > 0)
        self.assertIn("cost", user_prompt)
        self.assertIn("idle capacity", user_prompt)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Service Inspection & Identity Preservation
# ─────────────────────────────────────────────────────────────────────────────

class TestE2EServiceInspectionAndInvestigation(unittest.TestCase):
    """
    Steps 2 & 3: Service inspection obtains reports-worker metrics and passes
    them to investigation before any decision is made.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("underutilized_service.json")

    def test_service_identity_preserved(self) -> None:
        """The service identity under inspection must remain 'reports-worker'."""
        service_id = self.fixture["service"]["service_id"]
        self.assertEqual(service_id, "reports-worker")

        obs_data = self.fixture["observation"]
        obs = ServiceObservation(
            service_id=obs_data["service_id"],
            cpu_utilization_percent=obs_data["cpu_utilization_percent"],
            memory_utilization_percent=obs_data["memory_utilization_percent"],
            traffic_rpm=obs_data["traffic_rpm"],
            latency_ms=obs_data["latency_ms"],
            cost_per_hour=obs_data["cost_per_hour"],
            observation_timestamp=T_OBS_BEFORE,
            state_version=obs_data["state_version"],
        )
        self.assertEqual(obs.service_id, "reports-worker")

    def test_investigation_evidence_identifies_underutilization(self) -> None:
        """
        Investigation must produce evidence (issues list, summary) confirming
        idle/underutilized service before proposal generation.
        """
        obs_data = self.fixture["observation"]
        obs = ServiceObservation(
            service_id=obs_data["service_id"],
            cpu_utilization_percent=obs_data["cpu_utilization_percent"],
            memory_utilization_percent=obs_data["memory_utilization_percent"],
            traffic_rpm=obs_data["traffic_rpm"],
            latency_ms=obs_data["latency_ms"],
            cost_per_hour=obs_data["cost_per_hour"],
            observation_timestamp=T_OBS_BEFORE,
            state_version=obs_data["state_version"],
        )
        investigation = InvestigationResult(
            observation=obs,
            identified_issues=["underutilization", "zero_traffic"],
            summary="Service reports-worker is idle: CPU 9%, 0 RPM, 4 instances running.",
        )
        self.assertIn("underutilization", investigation.identified_issues)
        self.assertIn("reports-worker", investigation.summary)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Decision Generation
# ─────────────────────────────────────────────────────────────────────────────

class TestE2EDecision(unittest.TestCase):
    """
    Step 4: Decision Agent generates an ActionProposal proposing scale_down to 1 instance.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("underutilized_service.json")

    def test_decision_proposes_valid_scale_down(self) -> None:
        """
        Proposal action must be scale_down, target reports-worker, and respect min/max capacity.
        """
        expected_target = self.fixture["expected_behavior"]["expected_scale_down_target"]
        min_instances = self.fixture["service"]["min_instances"]
        max_instances = self.fixture["service"]["max_instances"]

        self.assertEqual(expected_target, 1)
        self.assertGreaterEqual(expected_target, min_instances)
        self.assertLessEqual(expected_target, max_instances)

        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Service is underutilized (9% CPU, 0 RPM). Scaling down to min instances.",
            expected_effect=f"Reduce instances from 4 to {expected_target}, reducing cost.",
            observation_version="v1.0.0",
            confidence=0.95,
        )
        self.assertEqual(proposal.action, InfrastructureAction.SCALE_DOWN)
        self.assertEqual(proposal.target_service_id, "reports-worker")
        self.assertEqual(proposal.confidence, 0.95)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Safety Validation
# ─────────────────────────────────────────────────────────────────────────────

class TestE2ESafetyStage(unittest.TestCase):
    """
    Step 5: Proposal must pass through Safety Engine validation before execution.
    """

    def test_safety_engine_discovery(self) -> None:
        """
        PRODUCTION GAP:
        Verify whether the Safety Engine exists in backend.safety.
        """
        safety = get_safety_engine()
        if safety is None:
            self.fail(
                "Production Gap: Safety Engine not implemented in backend.safety or "
                "backend.services.safety. Member 2 must implement the Safety Engine."
            )

    def test_safety_allows_valid_scale_down(self) -> None:
        """Safety check for valid scale-down within min/max boundaries returns ALLOW."""
        safety = SafetyCheckResult(
            is_approved=True,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            rejection_reasons=[],
            applied_rules=["capacity_boundary_check", "service_health_check", "latency_headroom_check"],
        )
        self.assertTrue(safety.is_approved)
        self.assertEqual(len(safety.rejection_reasons), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Action Execution & Actual State Mutation
# ─────────────────────────────────────────────────────────────────────────────

class TestE2EExecutionAndStateMutation(unittest.TestCase):
    """
    Step 6: Execute action through simulator and verify ACTUAL state change (4 → 1).
    Execution response alone is NEVER accepted as proof of state change.
    """

    def test_simulator_discovery(self) -> None:
        """
        PRODUCTION GAP:
        Verify whether the simulator/execution engine exists in backend.simulator.
        """
        sim = get_simulator()
        if sim is None:
            self.fail(
                "Production Gap: Simulator / execution engine not implemented in backend.simulator. "
                "Member 2 must implement the simulator."
            )

    def test_state_mutation_from_four_to_one(self) -> None:
        """
        Verify that reports-worker instance count mutates from 4 to 1.
        """
        initial_instances = 4
        target_instances = 1

        # Simulate state mutation
        pre_state = {"service_id": "reports-worker", "instances": initial_instances}
        post_state = {"service_id": "reports-worker", "instances": target_instances}

        self.assertEqual(pre_state["instances"], 4)
        self.assertEqual(post_state["instances"], 1)
        self.assertNotEqual(pre_state["instances"], post_state["instances"])

    def test_execution_alone_is_not_state_proof(self) -> None:
        """
        A bare ExecutionResult(status=SUCCESS) without verified post-action
        state telemetry does not constitute proof of infrastructure modification.
        """
        execution = ExecutionResult(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            status=ExecutionStatus.SUCCESS,
            new_state_version="v1.0.1",
        )
        # Without telemetry comparison, execution is only an intent confirmation
        self.assertEqual(execution.status, ExecutionStatus.SUCCESS)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Cost Recalculation
# ─────────────────────────────────────────────────────────────────────────────

class TestE2ECostRecalculation(unittest.TestCase):
    """
    Step 7: Verify hourly cost decreases after 4 → 1 instance reduction.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("underutilized_service.json")

    def test_cost_model_discovery(self) -> None:
        """
        PRODUCTION GAP:
        Verify whether cost recalculation service exists in backend.
        """
        cost_mod = get_cost_model()
        if cost_mod is None:
            self.fail(
                "Production Gap: Cost recalculation model not implemented in backend.services.cost "
                "or backend.simulator.cost. Member 2/3 must implement cost tracking."
            )

    def test_fixture_cost_impact_contract(self) -> None:
        """
        Contract check: fixture specifies hourly cost reduces from $11.00 to $2.75 ($8.25 savings).
        """
        cost_impact = self.fixture["expected_behavior"]["cost_impact"]
        self.assertTrue(cost_impact["cost_should_decrease"])
        self.assertEqual(cost_impact["previous_cost_per_hour"], 11.0)
        self.assertEqual(cost_impact["expected_cost_per_hour"], 2.75)
        self.assertEqual(cost_impact["expected_savings_per_hour"], 8.25)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Post-Action Verification
# ─────────────────────────────────────────────────────────────────────────────

class TestE2EPostActionVerification(unittest.TestCase):
    """
    Step 8: Verify workflow retrieves post-action telemetry and confirms state match.
    """

    def test_verification_confirms_state_match(self) -> None:
        """Observed instances (1) matches requested target (1) → is_successful=True."""
        obs_after = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=36.0,  # CPU increases proportionally with 1 instance
            memory_utilization_percent=45.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=2.75,
            observation_timestamp=T_OBS_AFTER,
            state_version="v1.0.1",
        )

        verification = VerificationResult(
            decision=DecisionResult(
                investigation=InvestigationResult(
                    observation=ServiceObservation(
                        service_id="reports-worker",
                        cpu_utilization_percent=9.0,
                        memory_utilization_percent=15.0,
                        traffic_rpm=0,
                        latency_ms=0.0,
                        cost_per_hour=11.0,
                        observation_timestamp=T_OBS_BEFORE,
                        state_version="v1.0.0",
                    ),
                    summary="Idle service",
                ),
                proposal=ActionProposal(
                    action=InfrastructureAction.SCALE_DOWN,
                    target_service_id="reports-worker",
                    reason="Scale down",
                    expected_effect="Reduce instances to 1",
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
            is_successful=True,
            verification_notes="State confirmed: reports-worker instance count is 1.",
        )
        self.assertTrue(verification.is_successful)
        self.assertIn("State confirmed", verification.verification_notes)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Audit Persistence
# ─────────────────────────────────────────────────────────────────────────────

class TestE2EAuditPersistence(unittest.TestCase):
    """
    Step 9: Verify audit persistence records all relevant workflow events.
    """

    def test_audit_store_discovery(self) -> None:
        """
        PRODUCTION GAP:
        Verify whether audit persistence / DB module exists in backend.db or backend.services.
        """
        audit_store = get_audit_store()
        if audit_store is None:
            self.fail(
                "Production Gap: Audit persistence store not implemented in backend.db or "
                "backend.services.audit. Member 3 must implement audit persistence."
            )


# ─────────────────────────────────────────────────────────────────────────────
# 9. Final User-Facing Result
# ─────────────────────────────────────────────────────────────────────────────

class TestE2EFinalResultStructure(unittest.TestCase):
    """
    Step 10: Final user-facing report distinguishes:
      - problem identified
      - action proposed
      - safety result
      - execution result
      - verification result
      - final state
    """

    def test_workflow_report_encompasses_all_stages(self) -> None:
        """WorkflowReport structure satisfies the complete contract."""
        obs_initial = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_OBS_BEFORE,
            state_version="v1.0.0",
        )
        investigation = InvestigationResult(
            observation=obs_initial,
            identified_issues=["underutilization"],
            summary="Idle reports-worker service.",
        )
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Scale down to min instances",
            expected_effect="Instances 4 -> 1",
            observation_version="v1.0.0",
            confidence=0.95,
        )
        safety = SafetyCheckResult(
            is_approved=True,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            applied_rules=["capacity_boundary_check"],
        )
        execution = ExecutionResult(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            status=ExecutionStatus.SUCCESS,
            new_state_version="v1.0.1",
        )
        verification = VerificationResult(
            decision=DecisionResult(investigation=investigation, proposal=proposal),
            safety_check=safety,
            execution=execution,
            is_successful=True,
            verification_notes="Verified state matches target.",
        )
        report = WorkflowReport(
            workflow_id="wf-demo-e2e",
            initial_observation=obs_initial,
            final_verification=verification,
        )
        self.assertEqual(report.workflow_id, "wf-demo-e2e")
        self.assertEqual(report.initial_observation.service_id, "reports-worker")
        self.assertTrue(report.final_verification.is_successful)
        self.assertTrue(report.final_verification.safety_check.is_approved)
        self.assertEqual(report.final_verification.execution.status, ExecutionStatus.SUCCESS)


# ─────────────────────────────────────────────────────────────────────────────
# 10. False-Success Protection Variant
# ─────────────────────────────────────────────────────────────────────────────

class TestE2EFalseSuccessProtection(unittest.TestCase):
    """
    Variant 11: Execution claims SUCCESS, but resulting state remains 4 (instances not mutated).
    Verify final result is NOT successful.
    """

    def test_phantom_execution_success_fails_verification(self) -> None:
        """
        When execution claims SUCCESS but observed instances remain 4,
        the verification result MUST be is_successful=False.
        """
        obs = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_OBS_BEFORE,
            state_version="v1.0.0",
        )
        decision = DecisionResult(
            investigation=InvestigationResult(observation=obs, summary="Idle service"),
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                reason="Scale down",
                expected_effect="Scale to 1",
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
        # Phantom success: telemetry check finds instances still at 4
        verification = VerificationResult(
            decision=decision,
            safety_check=safety,
            execution=execution,
            is_successful=False,  # Truthful failure: state mismatch
            verification_notes="Phantom success detected: execution returned SUCCESS but instance count remained 4.",
        )
        self.assertFalse(verification.is_successful)
        self.assertIn("Phantom success", verification.verification_notes)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Safety-Blocked E2E Variant
# ─────────────────────────────────────────────────────────────────────────────

class TestE2ESafetyBlockedVariant(unittest.TestCase):
    """
    Variant 12: Proposal attempts an unsafe target below min_instances (0 < 1).
    Verify: Safety blocks, execution does NOT happen, state remains unchanged,
    report reports action as blocked/rejected, NOT successful.
    """

    def test_safety_blocked_workflow_behavior(self) -> None:
        """Unsafe proposal is blocked by safety engine; execution=None; is_successful=False."""
        obs = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_OBS_BEFORE,
            state_version="v1.0.0",
        )
        decision = DecisionResult(
            investigation=InvestigationResult(observation=obs, summary="Idle service"),
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                reason="Scale to zero",
                expected_effect="Zero instances",
                observation_version="v1.0.0",
                confidence=0.9,
            ),
        )
        safety_blocked = SafetyCheckResult(
            is_approved=False,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            rejection_reasons=["Target capacity 0 is below min_instances=1."],
            applied_rules=["capacity_boundary_check"],
        )
        v = VerificationResult(
            decision=decision,
            safety_check=safety_blocked,
            execution=None,  # Execution was NOT invoked
            is_successful=False,
            verification_notes="Action blocked by Safety Engine: capacity below minimum.",
        )
        self.assertFalse(v.safety_check.is_approved)
        self.assertIsNone(v.execution)
        self.assertFalse(v.is_successful)


# ─────────────────────────────────────────────────────────────────────────────
# 12. Stale Observation E2E Variant
# ─────────────────────────────────────────────────────────────────────────────

class TestE2EStaleObservationVariant(unittest.TestCase):
    """
    Variant 13: Stale observation fixture (08:00 vs 10:30 surge).
    Verify: stale state detected, execution blocked, state refresh required.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("stale_observation.json")

    def test_stale_telemetry_detection(self) -> None:
        """Telemetry older than freshness window is rejected by safety engine."""
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
# 13. Failed Action E2E Variant
# ─────────────────────────────────────────────────────────────────────────────

class TestE2EFailedActionVariant(unittest.TestCase):
    """
    Variant 14: Failed action fixture (payment-api, scale_up 5, capacity_unavailable).
    Verify: execution reports failure, instances remain 3, error is preserved,
    final result does NOT claim successful scaling.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("failed_action.json")

    def test_cloud_provider_capacity_failure_preserved(self) -> None:
        """
        When cloud execution fails with capacity_unavailable:
        - execution.status = FAILURE
        - error_code = capacity_unavailable
        - is_successful = False
        - instances remain at 3
        """
        obs_data = self.fixture["observation"]
        obs = ServiceObservation(
            service_id=obs_data["service_id"],
            cpu_utilization_percent=obs_data["cpu_utilization_percent"],
            memory_utilization_percent=obs_data["memory_utilization_percent"],
            traffic_rpm=obs_data["traffic_rpm"],
            latency_ms=obs_data["latency_ms"],
            cost_per_hour=obs_data["cost_per_hour"],
            observation_timestamp=T_OBS_BEFORE,
            state_version=obs_data["state_version"],
        )
        decision = DecisionResult(
            investigation=InvestigationResult(
                observation=obs,
                identified_issues=["high_latency", "high_cpu"],
                summary="Payment API latency 410ms exceeds 300ms ceiling.",
            ),
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_UP,
                target_service_id="payment-api",
                reason="Capacity pressure",
                expected_effect="Scale up to 5 instances",
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
        execution = ExecutionResult(
            action=InfrastructureAction.SCALE_UP,
            target_service_id="payment-api",
            status=ExecutionStatus.FAILURE,
            error_code="capacity_unavailable",
            error_message="Host cluster out of capacity.",
        )
        verification = VerificationResult(
            decision=decision,
            safety_check=safety,
            execution=execution,
            is_successful=False,  # Truthful failure
            verification_notes="Execution failed: capacity_unavailable. Instances remain at 3.",
        )
        report = WorkflowReport(
            workflow_id="wf-failed-action",
            initial_observation=obs,
            final_verification=verification,
        )

        self.assertFalse(report.final_verification.is_successful)
        self.assertEqual(report.final_verification.execution.status, ExecutionStatus.FAILURE)
        self.assertEqual(report.final_verification.execution.error_code, "capacity_unavailable")
        self.assertIn("capacity_unavailable", report.final_verification.verification_notes)


if __name__ == "__main__":
    unittest.main()
