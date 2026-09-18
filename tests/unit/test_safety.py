"""
Unit tests for the Deterministic Safety Engine and Safety Validation Workflow.

Validates that:
1. Boundary conditions (min/max capacity) are strictly enforced.
2. Latency ceilings and headrooms prevent risky scale-downs.
3. Unhealthy service states block infrastructure modifications.
4. Stale observations are detected and rejected.
5. Missing or null metrics fail closed (no unsafe allows).
6. Unsupported or invalid actions are rejected.
7. Valid actions meeting all constraints are permitted (positive control).
8. Safety bypass is prevented: execution cannot occur without Safety Engine approval.
9. No-action proposals are handled safely.
"""

import json
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.schemas.actions import ActionProposal, InfrastructureAction
from backend.schemas.execution import ExecutionResult, ExecutionStatus
from backend.schemas.metrics import ServiceObservation
from backend.schemas.safety import SafetyCheckResult

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_fixture(filename: str) -> Dict[str, Any]:
    """Load JSON fixture from canonical tests/fixtures directory."""
    filepath = FIXTURES_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Fixture not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def get_safety_engine() -> Optional[Any]:
    """
    Attempt to discover and instantiate the Safety Engine from backend.
    Inspects candidate modules and classes/callables owned by Member 2.
    Returns None if backend safety engine has not yet been implemented.
    """
    candidate_modules = [
        "backend.safety",
        "backend.safety.engine",
        "backend.safety.safety_engine",
        "backend.services.safety",
        "backend.services.safety_engine",
        "backend.orchestrator.safety",
    ]
    candidate_symbols = [
        "SafetyEngine",
        "DeterministicSafetyEngine",
        "evaluate_safety",
        "validate_action",
        "check_safety",
        "guardrail",
    ]
    for mod_name in candidate_modules:
        try:
            mod = __import__(mod_name, fromlist=candidate_symbols)
            for sym_name in candidate_symbols:
                if hasattr(mod, sym_name):
                    target = getattr(mod, sym_name)
                    if isinstance(target, type):
                        return target()
                    return target
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_workflow_orchestrator() -> Optional[Any]:
    """
    Attempt to discover the orchestrator or execution workflow runner.
    Returns None if backend orchestrator has not yet been implemented.
    """
    candidate_modules = [
        "backend.orchestrator",
        "backend.orchestrator.workflow",
        "backend.orchestrator.runner",
        "backend.services.workflow",
    ]
    candidate_symbols = [
        "WorkflowOrchestrator",
        "run_workflow",
        "execute_workflow",
        "Orchestrator",
    ]
    for mod_name in candidate_modules:
        try:
            mod = __import__(mod_name, fromlist=candidate_symbols)
            for sym_name in candidate_symbols:
                if hasattr(mod, sym_name):
                    target = getattr(mod, sym_name)
                    if isinstance(target, type):
                        return target()
                    return target
        except (ImportError, ModuleNotFoundError):
            continue
    return None


class TestSafetyEngine(unittest.TestCase):
    """
    Test suite verifying deterministic safety guardrails, boundary enforcement,
    and workflow integration gating.
    """

    def setUp(self) -> None:
        """Initialize Safety Engine reference and fixture cache before each test."""
        self.safety_engine = get_safety_engine()
        self.orchestrator = get_workflow_orchestrator()
        self.violations_fixture = load_fixture("safety_violations.json")

    def _require_safety_engine(self) -> Any:
        """Helper to enforce Safety Engine availability or fail with production gap report."""
        if self.safety_engine is None:
            self.fail(
                "Production Gap: Safety Engine implementation missing in backend. "
                "Member 2 has not yet implemented the Deterministic Safety Engine."
            )
        return self.safety_engine

    def _get_violation_case(self, scenario_name: str) -> Dict[str, Any]:
        """Extract a specific named violation case from the safety_violations fixture."""
        for case in self.violations_fixture["violations"]:
            if case["scenario_name"] == scenario_name:
                return case
        raise KeyError(f"Violation case '{scenario_name}' not found in fixture.")

    def _evaluate(self, engine: Any, service: Dict[str, Any], action: str, target: Optional[int] = None, **kwargs) -> Any:
        """
        Invoke the safety engine under various method conventions.
        Returns SafetyCheckResult or tuple (is_approved, reasons).
        """
        if hasattr(engine, "check_safety"):
            return engine.check_safety(service=service, action=action, target_instances=target, **kwargs)
        if hasattr(engine, "evaluate"):
            return engine.evaluate(service=service, action=action, target_instances=target, **kwargs)
        if hasattr(engine, "guardrail"):
            return engine.guardrail(service=service, desired=target, action=action)
        if callable(engine):
            return engine(service=service, action=action, target_instances=target, **kwargs)
        self.fail("Production Gap: Safety Engine has no recognizable check/evaluate method.")

    def _assert_blocked(self, result: Any, expected_keyword: Optional[str] = None) -> None:
        """Assert that a safety evaluation result is blocked/rejected and contains expected reason."""
        if isinstance(result, SafetyCheckResult):
            self.assertFalse(result.is_approved, "Safety Check must NOT approve an unsafe action.")
            if expected_keyword:
                reasons_str = " ".join(result.rejection_reasons).lower()
                self.assertIn(
                    expected_keyword.lower(),
                    reasons_str,
                    f"Rejection reasons must cite '{expected_keyword}'. Got: {result.rejection_reasons}",
                )
        elif isinstance(result, tuple):
            is_ok, reason = result
            self.assertFalse(is_ok, "Safety Check must return False for unsafe action.")
            if expected_keyword:
                self.assertIn(expected_keyword.lower(), str(reason).lower())
        elif isinstance(result, dict):
            self.assertFalse(result.get("is_approved", False))
        else:
            self.fail(f"Unexpected safety result type: {type(result)}")

    def _assert_approved(self, result: Any) -> None:
        """Assert that a safety evaluation result is approved."""
        if isinstance(result, SafetyCheckResult):
            self.assertTrue(result.is_approved, f"Valid action was rejected: {result.rejection_reasons}")
        elif isinstance(result, tuple):
            is_ok, reason = result
            self.assertTrue(is_ok, f"Valid action was rejected: {reason}")
        elif isinstance(result, dict):
            self.assertTrue(result.get("is_approved", False))
        else:
            self.fail(f"Unexpected safety result type: {type(result)}")

    def test_below_minimum_capacity(self) -> None:
        """
        1. BELOW MINIMUM CAPACITY
        Given: current instances = 2, min_instances = 2, attempted target = 1
        Verify Safety Engine rejects/blocks action and cites minimum-capacity violation.
        """
        case = self._get_violation_case("below_minimum_capacity")
        service = case["service"]
        action = case["attempted_action"]["action"]
        target = case["attempted_action"]["target_instances"]

        self.assertEqual(service["instances"], 2)
        self.assertEqual(service["min_instances"], 2)
        self.assertEqual(target, 1)

        engine = self._require_safety_engine()
        result = self._evaluate(engine, service=service, action=action, target=target)
        self._assert_blocked(result, expected_keyword="minimum")

    def test_above_maximum_capacity(self) -> None:
        """
        2. ABOVE MAXIMUM CAPACITY
        Given: current instances = 4 (or 8), max_instances = 8, attempted target = 9
        Verify action is blocked/rejected.
        """
        case = self._get_violation_case("above_maximum_capacity")
        service = case["service"]
        action = case["attempted_action"]["action"]
        target = case["attempted_action"]["target_instances"]

        self.assertEqual(service["max_instances"], 8)
        self.assertEqual(target, 9)

        engine = self._require_safety_engine()
        result = self._evaluate(engine, service=service, action=action, target=target)
        self._assert_blocked(result, expected_keyword="maximum")

    def test_latency_violation(self) -> None:
        """
        3. LATENCY VIOLATION
        Given: latency = 320 ms, max_latency = 300 ms, attempted scale-down
        Verify Safety Engine does not allow the unsafe action.
        """
        case = self._get_violation_case("latency_violation")
        service = case["service"]
        action = case["attempted_action"]["action"]
        target = case["attempted_action"]["target_instances"]

        self.assertEqual(service["latency_ms"], 320.0)
        self.assertEqual(service["max_latency_ms"], 300.0)
        self.assertEqual(action, "scale_down")

        engine = self._require_safety_engine()
        result = self._evaluate(engine, service=service, action=action, target=target)
        self._assert_blocked(result, expected_keyword="latency")

    def test_unhealthy_service(self) -> None:
        """
        4. UNHEALTHY SERVICE
        Given: healthy = false, otherwise actionable service state
        Verify infrastructure modification is blocked/rejected.
        """
        case = self._get_violation_case("unhealthy_service")
        service = case["service"]
        action = case["attempted_action"]["action"]
        target = case["attempted_action"]["target_instances"]

        self.assertFalse(service["healthy"])

        engine = self._require_safety_engine()
        result = self._evaluate(engine, service=service, action=action, target=target)
        self._assert_blocked(result, expected_keyword="health")

    def test_stale_observation(self) -> None:
        """
        5. STALE OBSERVATION
        Using tests/fixtures/stale_observation.json:
        Verify stale data is detected, risky action is not allowed based on stale info,
        and stale data is NOT treated as equivalent to fresh observation.
        """
        fixture = load_fixture("stale_observation.json")
        service = fixture["service"]
        obs = fixture["observation"]
        latest = fixture["latest_traffic"]

        self.assertEqual(obs["observation_timestamp"], "2026-09-17T08:00:00Z")
        self.assertEqual(latest["timestamp"], "2026-09-17T10:30:00Z")

        engine = self._require_safety_engine()
        result = self._evaluate(
            engine,
            service=service,
            action="scale_down",
            target=2,
            proposal_version=obs["state_version"],
            evaluated_against_version=latest["state_version"],
        )
        self._assert_blocked(result, expected_keyword="stale")

    def test_missing_metric_data(self) -> None:
        """
        6. MISSING METRIC/DATA
        Using fixture with null CPU and latency:
        Verify missing required information does not result in an unsafe ALLOW.
        Safety Engine must fail closed.
        """
        case = self._get_violation_case("missing_metric_data")
        service = case["service"]
        action = case["attempted_action"]["action"]
        target = case["attempted_action"]["target_instances"]

        self.assertIsNone(service["cpu_percent"])
        self.assertIsNone(service["latency_ms"])

        engine = self._require_safety_engine()
        result = self._evaluate(engine, service=service, action=action, target=target)
        self._assert_blocked(result)

    def test_invalid_action(self) -> None:
        """
        7. INVALID ACTION
        Using action 'terminate_cluster':
        Verify unsupported action is rejected/blocked and never treated as valid.
        """
        case = self._get_violation_case("invalid_action")
        service = case["service"]
        action = case["attempted_action"]["action"]
        target = case["attempted_action"]["target_instances"]

        self.assertEqual(action, "terminate_cluster")

        engine = self._require_safety_engine()
        result = self._evaluate(engine, service=service, action=action, target=target)
        self._assert_blocked(result)

    def test_valid_action_is_allowed(self) -> None:
        """
        8. VALID ACTION IS ALLOWED (POSITIVE CONTROL)
        Using underutilized_service fixture:
        - target (1) >= min_instances (1)
        - target (1) <= max_instances (6)
        - service is healthy (healthy = true)
        - observation is fresh
        - required metrics exist
        - latency (0 ms) is well within safe range (max 900 ms)
        Verify Safety Engine approves the valid action.
        """
        fixture = load_fixture("underutilized_service.json")
        service = fixture["service"]
        target = fixture["expected_behavior"]["expected_scale_down_target"]

        self.assertEqual(service["service_id"], "reports-worker")
        self.assertEqual(service["instances"], 4)
        self.assertEqual(target, 1)
        self.assertTrue(service["healthy"])
        self.assertLessEqual(service["latency_ms"], service["max_latency_ms"] * 0.75)

        engine = self._require_safety_engine()
        result = self._evaluate(
            engine,
            service=service,
            action="scale_down",
            target=target,
            proposal_version=fixture["observation"]["state_version"],
            evaluated_against_version=fixture["observation"]["state_version"],
        )
        self._assert_approved(result)

    def test_safety_bypass_prevented(self) -> None:
        """
        9. SAFETY BYPASS TEST — CRITICAL
        Verify that an unsafe action cannot execute through the normal action workflow
        without passing Safety Engine validation.
        Protects against: 'caller directly requests an unsafe infrastructure action
        and execution happens without Safety Engine approval.'
        """
        # 1. Check if orchestrator/workflow pipeline exists
        orchestrator = self.orchestrator
        if orchestrator is None:
            self.fail(
                "Critical Integration Gap: Production workflow orchestrator is missing in backend.orchestrator. "
                "There is no pipeline enforcing that Action Proposals are validated by the Safety Engine "
                "prior to execution."
            )

        # 2. If orchestrator exists, attempt to execute an unsafe proposal through it
        unsafe_proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Unsafe cost reduction attempt below min instances",
            expected_effect="Reduce instances to 0",
            observation_version="v1.0.0",
            confidence=0.9,
        )

        if hasattr(orchestrator, "execute_proposal"):
            report = orchestrator.execute_proposal(unsafe_proposal)
            # The execution must NOT be executed or succeed
            if hasattr(report, "final_verification"):
                self.assertFalse(
                    report.final_verification.is_successful and report.final_verification.execution is not None,
                    "CRITICAL SAFETY GAP: Unsafe action executed through workflow without Safety Engine approval!",
                )
        else:
            self.fail(
                "Critical Integration Gap: Orchestrator lacks execute_proposal method with mandatory safety check."
            )

    def test_no_action_allowed(self) -> None:
        """
        10. NO ACTION
        Verify that a no_action proposal is accepted as a safe/no-op decision
        where appropriate without generating false safety rejections.
        """
        fixture = load_fixture("rising_traffic.json")
        service = fixture["service"]

        engine = self._require_safety_engine()
        result = self._evaluate(
            engine,
            service=service,
            action="no_action",
            target=service["instances"],
            proposal_version=fixture["observation"]["state_version"],
            evaluated_against_version=fixture["observation"]["state_version"],
        )
        self._assert_approved(result)


if __name__ == "__main__":
    unittest.main()
