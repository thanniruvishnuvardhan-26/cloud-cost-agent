"""
Unit tests for the Cloud Infrastructure Simulator.

Validates that infrastructure actions cause deterministic state mutations,
preserve service identity, handle failure paths without state corruption,
and conform to the project's execution contract and capacity boundaries.
"""

import json
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

from backend.schemas.actions import InfrastructureAction
from backend.schemas.execution import ExecutionResult, ExecutionStatus

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_fixture(filename: str) -> Dict[str, Any]:
    """Load and parse a JSON test fixture from the canonical fixtures directory."""
    fixture_path = FIXTURES_DIR / filename
    if not fixture_path.exists():
        raise FileNotFoundError(f"Fixture file not found: {fixture_path}")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_simulator_class() -> Optional[Any]:
    """
    Dynamically discover the simulator class from backend.simulator if implemented.
    Looks for standard naming conventions: CloudSimulator, ServiceSimulator, Simulator, InfrastructureSimulator.
    Returns None if backend/simulator has not yet been implemented by the engineering team.
    """
    candidate_modules = [
        "backend.simulator",
        "backend.simulator.simulator",
        "backend.simulator.service_simulator",
        "backend.simulator.engine",
    ]
    candidate_classes = [
        "CloudSimulator",
        "ServiceSimulator",
        "Simulator",
        "InfrastructureSimulator",
    ]
    for mod_name in candidate_modules:
        try:
            mod = __import__(mod_name, fromlist=candidate_classes)
            for cls_name in candidate_classes:
                if hasattr(mod, cls_name):
                    return getattr(mod, cls_name)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


class TestSimulator(unittest.TestCase):
    """
    Test suite verifying simulator state mutation, cost representation,
    failure isolation, boundary transitions, and no-op safety.
    """

    def setUp(self) -> None:
        """Reset simulator state before each test execution."""
        self.simulator_cls = get_simulator_class()
        self.simulator = self.simulator_cls() if self.simulator_cls else None

    def _require_simulator(self) -> Any:
        """Helper to enforce simulator availability and report production gap."""
        if self.simulator is None:
            self.fail(
                "Production Gap: Simulator implementation missing in backend.simulator. "
                "The engineering team has not yet implemented CloudSimulator/ServiceSimulator."
            )
        return self.simulator

    def test_scale_down_mutates_state(self) -> None:
        """
        1. SCALE DOWN MUTATES STATE
        Using tests/fixtures/underutilized_service.json:
        Verify that a valid scale_down action:
        - starts with reports-worker at 4 instances
        - requests target 1
        - actually changes simulator state to 1
        - does not produce a negative or invalid instance count
        - preserves the service identity
        - produces a successful execution result if the simulator contract says so
        """
        fixture = load_fixture("underutilized_service.json")
        service_data = fixture["service"]
        service_id = service_data["service_id"]
        initial_instances = service_data["instances"]
        target_instances = fixture["expected_behavior"]["expected_scale_down_target"]

        self.assertEqual(service_id, "reports-worker")
        self.assertEqual(initial_instances, 4)
        self.assertEqual(target_instances, 1)

        sim = self._require_simulator()

        # Seed simulator state with fixture data
        if hasattr(sim, "set_service"):
            sim.set_service(service_data)
        elif hasattr(sim, "register_service"):
            sim.register_service(service_data)

        # Execute scale_down action
        if hasattr(sim, "execute_action"):
            result = sim.execute_action(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id=service_id,
                target_instances=target_instances,
            )
        elif hasattr(sim, "apply_action"):
            result = sim.apply_action(
                service_id=service_id,
                action="scale_down",
                desired_instances=target_instances,
            )
        else:
            self.fail("Production Gap: Simulator lacks execute_action/apply_action method.")

        # Verify state mutation
        state = sim.get_service(service_id) if hasattr(sim, "get_service") else getattr(sim, "services", {}).get(service_id)
        self.assertIsNotNone(state, "Service state must be retrievable from simulator after action.")

        current_instances = state.get("instances") if isinstance(state, dict) else getattr(state, "instances", None)
        self.assertEqual(current_instances, 1, "Simulator state must be mutated to target instances 1.")
        self.assertGreater(current_instances, 0, "Instance count must not be negative or zero.")
        self.assertGreaterEqual(current_instances, service_data["min_instances"], "Instance count must not violate min_instances.")

        # Verify service identity preservation
        retrieved_id = state.get("service_id") if isinstance(state, dict) else getattr(state, "service_id", None)
        self.assertEqual(retrieved_id, service_id, "Service identity must be preserved across action execution.")

        # Verify execution result contract
        if isinstance(result, ExecutionResult):
            self.assertEqual(result.status, ExecutionStatus.SUCCESS)
            self.assertEqual(result.target_service_id, service_id)
        elif isinstance(result, dict):
            self.assertEqual(result.get("status"), "success")

    def test_scale_up_mutates_state(self) -> None:
        """
        2. SCALE UP MUTATES STATE
        Using tests/fixtures/rising_traffic.json:
        If the simulator supports scale_up:
        - start orders-api at 4 instances
        - request a valid target within max capacity, preferably 5
        - verify actual state becomes 5
        - verify the execution result reflects the state mutation
        """
        fixture = load_fixture("rising_traffic.json")
        service_data = fixture["service"]
        service_id = service_data["service_id"]
        initial_instances = service_data["instances"]
        target_instances = 5  # within min 2, max 8

        self.assertEqual(service_id, "orders-api")
        self.assertEqual(initial_instances, 4)
        self.assertLessEqual(target_instances, service_data["max_instances"])

        sim = self._require_simulator()

        # Seed simulator state
        if hasattr(sim, "set_service"):
            sim.set_service(service_data)
        elif hasattr(sim, "register_service"):
            sim.register_service(service_data)

        # Execute scale_up action
        if hasattr(sim, "execute_action"):
            result = sim.execute_action(
                action=InfrastructureAction.SCALE_UP,
                target_service_id=service_id,
                target_instances=target_instances,
            )
        elif hasattr(sim, "apply_action"):
            result = sim.apply_action(
                service_id=service_id,
                action="scale_up",
                desired_instances=target_instances,
            )
        else:
            self.fail("Production Gap: Simulator lacks execute_action/apply_action method.")

        # Verify state mutation
        state = sim.get_service(service_id) if hasattr(sim, "get_service") else getattr(sim, "services", {}).get(service_id)
        self.assertIsNotNone(state, "Service state must be retrievable from simulator after scale_up.")

        current_instances = state.get("instances") if isinstance(state, dict) else getattr(state, "instances", None)
        self.assertEqual(current_instances, 5, "Simulator state must be mutated to target instances 5.")

        # Verify execution result reflects mutation
        if isinstance(result, ExecutionResult):
            self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        elif isinstance(result, dict):
            self.assertEqual(result.get("status"), "success")

    def test_cost_decrease_after_scale_down(self) -> None:
        """
        3. COST DECREASE AFTER SCALE DOWN
        Using underutilized_service fixture:
        - initial reports-worker cost_per_hour = 11
        - initial instance count = 4
        - scale down to 1
        Verify that the simulator's resulting cost representation changes consistently
        with the project's actual cost model.
        """
        fixture = load_fixture("underutilized_service.json")
        service_data = fixture["service"]
        service_id = service_data["service_id"]
        initial_cost = service_data["cost_per_hour"]

        self.assertEqual(initial_cost, 11.0)
        self.assertEqual(service_data["instances"], 4)

        sim = self._require_simulator()

        if hasattr(sim, "set_service"):
            sim.set_service(service_data)

        if hasattr(sim, "execute_action"):
            sim.execute_action(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id=service_id,
                target_instances=1,
            )

        state = sim.get_service(service_id) if hasattr(sim, "get_service") else getattr(sim, "services", {}).get(service_id)
        new_cost = state.get("cost_per_hour") if isinstance(state, dict) else getattr(state, "cost_per_hour", None)

        if new_cost is None:
            self.fail(
                "Production Gap: Simulator does not calculate or recalculate cost_per_hour "
                "following an action execution."
            )
        else:
            self.assertLess(new_cost, initial_cost, "Cost per hour must decrease following a valid scale-down.")

    def test_scale_up_cost_behavior(self) -> None:
        """
        4. SCALE-UP COST BEHAVIOR
        If the simulator calculates cost:
        - scale orders-api from 4 to 5
        - verify resulting cost increases according to the existing simulator cost model.
        If the simulator does not calculate cost:
        - report the limitation.
        """
        fixture = load_fixture("rising_traffic.json")
        service_data = fixture["service"]
        service_id = service_data["service_id"]
        initial_cost = service_data["cost_per_hour"]

        sim = self._require_simulator()

        if hasattr(sim, "set_service"):
            sim.set_service(service_data)

        if hasattr(sim, "execute_action"):
            sim.execute_action(
                action=InfrastructureAction.SCALE_UP,
                target_service_id=service_id,
                target_instances=5,
            )

        state = sim.get_service(service_id) if hasattr(sim, "get_service") else getattr(sim, "services", {}).get(service_id)
        new_cost = state.get("cost_per_hour") if isinstance(state, dict) else getattr(state, "cost_per_hour", None)

        if new_cost is None:
            self.fail(
                "Production Gap: Simulator does not track or update cost_per_hour following scale_up."
            )
        else:
            self.assertGreater(new_cost, initial_cost, "Cost per hour must increase following a scale-up.")

    def test_failed_action_does_not_mutate_state(self) -> None:
        """
        5. FAILED ACTION DOES NOT MUTATE STATE
        Using tests/fixtures/failed_action.json:
        - payment-api starts at 3 instances
        - requested scale_up target = 5
        - execution failure = capacity_unavailable
        Verify:
        - execution is represented as failed according to existing contract
        - instance count remains 3
        - failed execution does not silently mutate state to 5
        - failure information remains available in the result
        """
        fixture = load_fixture("failed_action.json")
        service_data = fixture["service"]
        service_id = service_data["service_id"]
        initial_instances = service_data["instances"]
        target_instances = fixture["attempted_action"]["requested_instances"]
        expected_error = fixture["action_result"]["error"]

        self.assertEqual(service_id, "payment-api")
        self.assertEqual(initial_instances, 3)
        self.assertEqual(target_instances, 5)
        self.assertEqual(expected_error, "capacity_unavailable")

        sim = self._require_simulator()

        if hasattr(sim, "set_service"):
            sim.set_service(service_data)

        # Configure or inject failure simulation if supported by simulator
        if hasattr(sim, "set_simulated_failure"):
            sim.set_simulated_failure(service_id, error_code=expected_error)

        if hasattr(sim, "execute_action"):
            result = sim.execute_action(
                action=InfrastructureAction.SCALE_UP,
                target_service_id=service_id,
                target_instances=target_instances,
            )
        else:
            self.fail("Production Gap: Simulator lacks execute_action method.")

        # Verify execution is represented as failed
        if isinstance(result, ExecutionResult):
            self.assertEqual(result.status, ExecutionStatus.FAILURE, "Execution status must indicate FAILURE.")
            self.assertEqual(result.error_code, expected_error, "Error code must indicate capacity_unavailable.")
        elif isinstance(result, dict):
            self.assertIn(result.get("status"), ("failed", "failure"))
            self.assertIn(expected_error, str(result.get("error") or result.get("error_code")))

        # Verify instance count remains untouched at initial value 3
        state = sim.get_service(service_id) if hasattr(sim, "get_service") else getattr(sim, "services", {}).get(service_id)
        current_instances = state.get("instances") if isinstance(state, dict) else getattr(state, "instances", None)

        self.assertEqual(current_instances, 3, "Instance count must remain 3 after failed execution.")
        self.assertNotEqual(current_instances, 5, "Failed execution must NOT mutate instance count to requested target.")

    def test_boundary_state_mutation(self) -> None:
        """
        6. BOUNDARY STATE MUTATION
        Using safety_violations fixture for boundary limits:
        - valid scale-down target equal to min_instances
        - valid scale-up target equal to max_instances
        Answers: If the simulator receives an already-valid boundary action, does it mutate state to the boundary?
        (Does not test safety blocking).
        """
        fixture = load_fixture("safety_violations.json")
        # Boundary case A: min_instances = 2 for orders-api
        boundary_service = {
            "service_id": "orders-api",
            "instances": 4,
            "min_instances": 2,
            "max_instances": 8,
            "latency_ms": 150.0,
            "max_latency_ms": 300.0,
            "health": "healthy",
            "healthy": True,
            "cost_per_hour": 18.5,
        }
        service_id = boundary_service["service_id"]
        min_capacity = boundary_service["min_instances"]
        max_capacity = boundary_service["max_instances"]

        sim = self._require_simulator()

        if hasattr(sim, "set_service"):
            sim.set_service(boundary_service)

        # Test boundary mutation to exact min_instances (2)
        if hasattr(sim, "execute_action"):
            sim.execute_action(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id=service_id,
                target_instances=min_capacity,
            )
        state_min = sim.get_service(service_id) if hasattr(sim, "get_service") else getattr(sim, "services", {}).get(service_id)
        instances_at_min = state_min.get("instances") if isinstance(state_min, dict) else getattr(state_min, "instances", None)
        self.assertEqual(instances_at_min, min_capacity, "Simulator must mutate state to exact min_instances boundary.")

        # Test boundary mutation to exact max_instances (8)
        if hasattr(sim, "execute_action"):
            sim.execute_action(
                action=InfrastructureAction.SCALE_UP,
                target_service_id=service_id,
                target_instances=max_capacity,
            )
        state_max = sim.get_service(service_id) if hasattr(sim, "get_service") else getattr(sim, "services", {}).get(service_id)
        instances_at_max = state_max.get("instances") if isinstance(state_max, dict) else getattr(state_max, "instances", None)
        self.assertEqual(instances_at_max, max_capacity, "Simulator must mutate state to exact max_instances boundary.")

    def test_no_action_preserves_state_and_cost(self) -> None:
        """
        7. NO ACTION
        If the simulator/action layer supports no_action:
        - execute no_action
        - verify service instance count is unchanged
        - verify no unintended cost/state mutation occurs
        """
        fixture = load_fixture("underutilized_service.json")
        service_data = fixture["service"]
        service_id = service_data["service_id"]
        initial_instances = service_data["instances"]
        initial_cost = service_data["cost_per_hour"]

        sim = self._require_simulator()

        if hasattr(sim, "set_service"):
            sim.set_service(service_data)

        if hasattr(sim, "execute_action"):
            result = sim.execute_action(
                action=InfrastructureAction.NO_ACTION,
                target_service_id=service_id,
            )
        else:
            self.fail("Production Gap: Simulator lacks execute_action method.")

        state = sim.get_service(service_id) if hasattr(sim, "get_service") else getattr(sim, "services", {}).get(service_id)
        current_instances = state.get("instances") if isinstance(state, dict) else getattr(state, "instances", None)
        current_cost = state.get("cost_per_hour") if isinstance(state, dict) else getattr(state, "cost_per_hour", None)

        self.assertEqual(current_instances, initial_instances, "Instance count must be unchanged by no_action.")
        if current_cost is not None:
            self.assertEqual(current_cost, initial_cost, "Cost per hour must not change during no_action.")


if __name__ == "__main__":
    unittest.main()
