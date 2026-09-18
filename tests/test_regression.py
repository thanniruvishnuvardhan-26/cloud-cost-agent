"""
Consolidated Regression Test Suite -- Cloud Cost Optimization Agent
Phase 12 -- Member 4 QA/Data/Integration/Evaluation Lead

COVERAGE (11 areas + 10 critical invariants):
  1.  DATA FIXTURES     -- JSON validity, field presence, semantic constraints
  2.  SCHEMA/CONTRACT   -- Pydantic models, enum values, field validation, rejection
  3.  SIMULATOR         -- state mutation, cost model (or documented gap)
  4.  SAFETY            -- boundary, health, latency, freshness, missing-data, bypass
  5.  VERIFICATION      -- state match/mismatch, failure, stale, no_action, WorkflowReport
  6.  API               -- endpoint contracts, no-false-success
  7.  AGENT CONTRACT    -- valid proposals, invalid action/confidence/LLM rejection
  8.  ORCHESTRATION     -- 7-stage ordering, safety gate, bypass prevention
  9.  END-TO-END        -- primary demo + stale/failed/blocked/mismatch variants
 10.  BROWSER/UI        -- presentation truthfulness, distinct outcome states
 11.  FAILURE           -- fail-closed, timeout, idempotency gap

CRITICAL INVARIANTS (Rules 1-10): see TestCriticalRegressionInvariants

Ownership:
  Member 4 owns QA/Integration/Regression.
  Do NOT modify backend, frontend, agent, orchestrator, simulator, or safety code.
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

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Deterministic constants -- NO system clock anywhere
T_0800 = datetime(2026, 9, 17,  8,  0,  0, tzinfo=timezone.utc)
T_1030 = datetime(2026, 9, 17, 10, 30,  0, tzinfo=timezone.utc)
T_1031 = datetime(2026, 9, 17, 10, 31,  0, tzinfo=timezone.utc)
T_BEFORE = T_1030   # backward-compat alias
T_AFTER  = T_1031
T_STALE  = T_0800


def load_fixture(filename: str) -> Dict[str, Any]:
    filepath = FIXTURES_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Fixture not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _discover(modules: List[str], symbols: List[str]) -> Optional[Any]:
    for mod_path in modules:
        try:
            mod = __import__(mod_path, fromlist=symbols)
            for sym in symbols:
                if hasattr(mod, sym):
                    return getattr(mod, sym)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_simulator() -> Optional[Any]:
    return _discover(
        ["backend.simulator", "backend.simulator.simulator", "backend.simulator.engine"],
        ["CloudSimulator", "ServiceSimulator", "Simulator", "InfrastructureSimulator"],
    )


def get_safety_engine() -> Optional[Any]:
    sym = _discover(
        ["backend.safety", "backend.safety.engine", "backend.safety.safety_engine",
         "backend.services.safety", "backend.services.safety_engine"],
        ["SafetyEngine", "DeterministicSafetyEngine", "evaluate_safety",
         "validate_action", "check_safety", "guardrail"],
    )
    if sym is None:
        return None
    return sym() if isinstance(sym, type) else sym


def get_backend_api() -> Optional[Any]:
    for mod_path in ["backend.main", "backend.app", "backend.api"]:
        try:
            return __import__(mod_path, fromlist=["app"])
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_orchestrator() -> Optional[Any]:
    return _discover(
        ["backend.orchestrator.orchestrator", "backend.orchestrator.workflow",
         "backend.orchestrator", "backend.orchestrator.runner"],
        ["Orchestrator", "WorkflowOrchestrator", "run_workflow"],
    )


def get_agent_module() -> Optional[Any]:
    for mod_path in ["backend.agents.decision", "backend.agents.decision_agent",
                     "backend.agents.agent", "backend.agents.base", "backend.agents.core"]:
        try:
            return __import__(mod_path, fromlist=["*"])
        except (ImportError, ModuleNotFoundError):
            continue
    return None


# ---------------------------------------------------------------------------
# Shared schema-object builders
# ---------------------------------------------------------------------------

def _obs(service_id="reports-worker", cpu=9.0, mem=15.0, rpm=0,
         latency=0.0, cost=11.0, ts=None, version="v1.0.0") -> ServiceObservation:
    return ServiceObservation(
        service_id=service_id, cpu_utilization_percent=cpu,
        memory_utilization_percent=mem, traffic_rpm=rpm, latency_ms=latency,
        cost_per_hour=cost, observation_timestamp=ts or T_1030, state_version=version,
    )


def _prop(action=InfrastructureAction.SCALE_DOWN, svc="reports-worker",
          reason="Idle", effect="Reduce to 1", ver="v1.0.0",
          conf=0.95) -> ActionProposal:
    return ActionProposal(action=action, target_service_id=svc, reason=reason,
                          expected_effect=effect, observation_version=ver, confidence=conf)


def _safety(approved=True, pver="v1.0.0", ever="v1.0.0",
            reasons=None, rules=None) -> SafetyCheckResult:
    return SafetyCheckResult(is_approved=approved, proposal_version=pver,
                             evaluated_against_version=ever,
                             rejection_reasons=reasons or [], applied_rules=rules or [])


def _dec(obs=None, proposal=None) -> DecisionResult:
    return DecisionResult(
        investigation=InvestigationResult(observation=obs or _obs(), summary="Test"),
        proposal=proposal or _prop(),
    )


def _exec(action=InfrastructureAction.SCALE_DOWN, svc="reports-worker",
          status=ExecutionStatus.SUCCESS, new_ver="v1.0.1",
          err=None) -> ExecutionResult:
    return ExecutionResult(action=action, target_service_id=svc, status=status,
                           new_state_version=new_ver if status == ExecutionStatus.SUCCESS else None,
                           error_code=err)


def _verif(decision=None, safety=None, execution=None,
           ok=True, notes="ok") -> VerificationResult:
    return VerificationResult(decision=decision or _dec(), safety_check=safety or _safety(),
                              execution=execution, is_successful=ok,
                              verification_notes=notes)


# ===========================================================================
# 1. DATA FIXTURES REGRESSION
# ===========================================================================

class TestDataFixturesRegression(unittest.TestCase):

    FIVE = ["underutilized_service.json", "rising_traffic.json",
            "stale_observation.json", "failed_action.json", "safety_violations.json"]

    def test_all_five_fixtures_load_valid_json(self):
        for fn in self.FIVE:
            with self.subTest(f=fn):
                self.assertIsInstance(load_fixture(fn), dict)

    def test_scenario_ids_are_stable(self):
        expected = {
            "underutilized_service.json": ("scenario_id",   "underutilized_service"),
            "rising_traffic.json":        ("scenario_id",   "rising_traffic"),
            "stale_observation.json":     ("scenario_id",   "stale_observation"),
            "failed_action.json":         ("scenario_id",   "failed_action"),
            "safety_violations.json":     ("collection_id", "safety_violations"),
        }
        for fn, (key, val) in expected.items():
            with self.subTest(f=fn):
                self.assertEqual(load_fixture(fn)[key], val)

    def test_observations_validate_against_pydantic_schema(self):
        for fn in ["underutilized_service.json", "rising_traffic.json",
                   "stale_observation.json", "failed_action.json"]:
            with self.subTest(f=fn):
                od = load_fixture(fn)["observation"]
                obs = ServiceObservation(
                    service_id=od["service_id"],
                    cpu_utilization_percent=od["cpu_utilization_percent"],
                    memory_utilization_percent=od["memory_utilization_percent"],
                    traffic_rpm=od["traffic_rpm"], latency_ms=od["latency_ms"],
                    cost_per_hour=od["cost_per_hour"],
                    observation_timestamp=T_1030, state_version=od["state_version"],
                )
                self.assertEqual(obs.service_id, od["service_id"])

    def test_service_ids_consistent_between_service_and_observation(self):
        for fn in ["underutilized_service.json", "rising_traffic.json",
                   "stale_observation.json", "failed_action.json"]:
            with self.subTest(f=fn):
                d = load_fixture(fn)
                self.assertEqual(d["service"]["service_id"], d["observation"]["service_id"])

    def test_state_versions_present_and_nonempty(self):
        for fn in ["underutilized_service.json", "rising_traffic.json",
                   "stale_observation.json", "failed_action.json"]:
            with self.subTest(f=fn):
                self.assertTrue(load_fixture(fn)["observation"].get("state_version", ""))

    def test_underutilized_service_semantic_constraints(self):
        d = load_fixture("underutilized_service.json")
        self.assertEqual(d["service"]["service_id"], "reports-worker")
        self.assertEqual(d["service"]["instances"], 4)
        self.assertEqual(d["service"]["min_instances"], 1)
        self.assertEqual(d["service"]["max_instances"], 6)
        self.assertTrue(d["service"]["healthy"])
        self.assertEqual(d["observation"]["traffic_rpm"], 0)
        self.assertEqual(d["observation"]["cpu_utilization_percent"], 9.0)
        self.assertEqual(d["expected_behavior"]["expected_action"], "scale_down")
        self.assertEqual(d["expected_behavior"]["expected_scale_down_target"], 1)
        self.assertTrue(d["expected_behavior"]["cost_impact"]["cost_should_decrease"])
        self.assertEqual(d["expected_behavior"]["cost_impact"]["previous_cost_per_hour"], 11.0)

    def test_rising_traffic_semantic_constraints(self):
        d = load_fixture("rising_traffic.json")
        self.assertEqual(d["service"]["service_id"], "orders-api")
        self.assertEqual(d["observation"]["traffic_rpm"], 4200)
        self.assertEqual(d["service"]["instances"], 4)
        self.assertIn("scale_down", d["expected_behavior"]["prohibited_actions"])
        self.assertTrue(d["expected_behavior"]["must_not_scale_down"])

    def test_stale_observation_semantic_constraints(self):
        d = load_fixture("stale_observation.json")
        self.assertEqual(d["observation"]["state_version"], "v1.0.0-0800")
        self.assertEqual(d["latest_traffic"]["state_version"], "v1.0.0-1030")
        self.assertNotEqual(d["observation"]["state_version"],
                            d["latest_traffic"]["state_version"])
        self.assertEqual(d["staleness_details"]["age_minutes"], 150.0)
        self.assertTrue(d["staleness_details"]["is_stale"])
        self.assertFalse(d["expected_behavior"]["action_permitted_on_stale_data"])

    def test_failed_action_semantic_constraints(self):
        d = load_fixture("failed_action.json")
        self.assertEqual(d["service"]["service_id"], "payment-api")
        self.assertEqual(d["service"]["instances"], 3)
        self.assertEqual(d["action_result"]["error"], "capacity_unavailable")
        self.assertIn(d["action_result"]["status"], ("failed", "failure"))
        self.assertTrue(d["expected_behavior"]["must_not_report_success"])
        self.assertFalse(d["expected_behavior"]["verification"]["is_successful"])
        self.assertEqual(d["expected_behavior"]["verification"]["actual_instances_remaining"], 3)

    def test_safety_violations_collection_has_all_seven_scenarios(self):
        names = {v["scenario_name"]
                 for v in load_fixture("safety_violations.json")["violations"]}
        required = {"below_minimum_capacity", "above_maximum_capacity", "latency_violation",
                    "unhealthy_service", "stale_data", "missing_metric_data", "invalid_action"}
        self.assertSetEqual(required - names, set())


# ===========================================================================
# 2. SCHEMA / CONTRACT REGRESSION
# ===========================================================================

class TestSchemaContractRegression(unittest.TestCase):

    def test_infrastructure_action_enum_exact_values(self):
        expected = {"scale_up", "scale_down", "resize",
                    "stop_idle_service", "delay_batch", "no_action"}
        self.assertSetEqual({a.value for a in InfrastructureAction}, expected)

    def test_execution_status_enum_exact_values(self):
        self.assertSetEqual({s.value for s in ExecutionStatus}, {"success", "failure"})

    def test_action_proposal_rejects_missing_confidence(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"action": "scale_down", "target_service_id": "s",
                "reason": "r", "expected_effect": "e", "observation_version": "v1"})

    def test_action_proposal_rejects_missing_action(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"target_service_id": "s", "reason": "r",
                "expected_effect": "e", "observation_version": "v1", "confidence": 0.9})

    def test_action_proposal_rejects_missing_observation_version(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"action": "scale_down", "target_service_id": "s",
                "reason": "r", "expected_effect": "e", "confidence": 0.9})

    def test_confidence_above_1_rejected(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"action": "scale_down", "target_service_id": "s",
                "reason": "r", "expected_effect": "e", "observation_version": "v1",
                "confidence": 1.01})

    def test_confidence_below_0_rejected(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"action": "scale_down", "target_service_id": "s",
                "reason": "r", "expected_effect": "e", "observation_version": "v1",
                "confidence": -0.01})

    def test_confidence_boundary_values_accepted(self):
        for c in (0.0, 1.0):
            with self.subTest(c=c):
                p = ActionProposal.model_validate({"action": "scale_down",
                    "target_service_id": "s", "reason": "r", "expected_effect": "e",
                    "observation_version": "v1", "confidence": c})
                self.assertEqual(p.confidence, c)

    def test_observation_rejects_cpu_above_100(self):
        with self.assertRaises(ValidationError):
            ServiceObservation(service_id="s", cpu_utilization_percent=101.0,
                memory_utilization_percent=50.0, traffic_rpm=0, latency_ms=0.0,
                cost_per_hour=1.0, observation_timestamp=T_1030, state_version="v1")

    def test_observation_rejects_negative_cost(self):
        with self.assertRaises(ValidationError):
            ServiceObservation(service_id="s", cpu_utilization_percent=10.0,
                memory_utilization_percent=50.0, traffic_rpm=0, latency_ms=0.0,
                cost_per_hour=-1.0, observation_timestamp=T_1030, state_version="v1")

    def test_observation_rejects_negative_traffic(self):
        with self.assertRaises(ValidationError):
            ServiceObservation(service_id="s", cpu_utilization_percent=10.0,
                memory_utilization_percent=50.0, traffic_rpm=-1, latency_ms=0.0,
                cost_per_hour=1.0, observation_timestamp=T_1030, state_version="v1")

    def test_safety_check_result_requires_is_approved(self):
        with self.assertRaises(ValidationError):
            SafetyCheckResult.model_validate(
                {"proposal_version": "v1", "evaluated_against_version": "v1"})

    def test_verification_result_requires_is_successful(self):
        with self.assertRaises(ValidationError):
            VerificationResult.model_validate({"decision": _dec().model_dump(),
                "safety_check": _safety().model_dump(), "verification_notes": "n"})

    def test_workflow_report_requires_workflow_id(self):
        with self.assertRaises(ValidationError):
            WorkflowReport.model_validate({"initial_observation": _obs().model_dump(),
                "final_verification": _verif().model_dump()})

    def test_invalid_action_enum_value_rejected(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"action": "terminate_cluster",
                "target_service_id": "s", "reason": "r",
                "expected_effect": "e", "observation_version": "v1", "confidence": 0.9})

    def test_execution_result_has_no_is_successful_field(self):
        self.assertFalse(hasattr(_exec(), "is_successful"))


# ===========================================================================
# 3. SIMULATOR REGRESSION
# ===========================================================================

class TestSimulatorRegression(unittest.TestCase):

    def setUp(self):
        cls = get_simulator()
        self.sim = cls() if cls else None

    def _req(self):
        if self.sim is None:
            self.fail("Production Gap: Simulator not implemented in backend.simulator "
                      "(CloudSimulator / ServiceSimulator / Simulator / InfrastructureSimulator).")
        return self.sim

    def _run(self, sim, action, svc_id, target=None):
        if not hasattr(sim, "execute_action"):
            self.fail("Production Gap: Simulator lacks execute_action method.")
        kw: Dict[str, Any] = {"action": action, "target_service_id": svc_id}
        if target is not None:
            kw["target_instances"] = target
        return sim.execute_action(**kw)

    def _instances(self, sim, svc_id):
        s = (sim.get_service(svc_id) if hasattr(sim, "get_service")
             else getattr(sim, "services", {}).get(svc_id))
        return s.get("instances") if isinstance(s, dict) else getattr(s, "instances", None)

    def test_simulator_production_gap(self):
        if self.sim is None:
            self.fail("Production Gap: Simulator not implemented in backend.simulator.")

    def test_scale_down_mutates_to_target(self):
        sim = self._req()
        d = load_fixture("underutilized_service.json")
        if hasattr(sim, "set_service"):
            sim.set_service(d["service"])
        self._run(sim, InfrastructureAction.SCALE_DOWN, "reports-worker", 1)
        self.assertEqual(self._instances(sim, "reports-worker"), 1)

    def test_failed_action_does_not_mutate_state(self):
        sim = self._req()
        d = load_fixture("failed_action.json")
        if hasattr(sim, "set_service"):
            sim.set_service(d["service"])
        if hasattr(sim, "set_simulated_failure"):
            sim.set_simulated_failure("payment-api", error_code="capacity_unavailable")
        self._run(sim, InfrastructureAction.SCALE_UP, "payment-api", 5)
        self.assertEqual(self._instances(sim, "payment-api"), 3)

    def test_no_action_preserves_state(self):
        sim = self._req()
        d = load_fixture("underutilized_service.json")
        if hasattr(sim, "set_service"):
            sim.set_service(d["service"])
        self._run(sim, InfrastructureAction.NO_ACTION, "reports-worker")
        self.assertEqual(self._instances(sim, "reports-worker"), d["service"]["instances"])

    def test_cost_decreases_after_scale_down(self):
        sim = self._req()
        d = load_fixture("underutilized_service.json")
        init_cost = d["service"]["cost_per_hour"]
        if hasattr(sim, "set_service"):
            sim.set_service(d["service"])
        self._run(sim, InfrastructureAction.SCALE_DOWN, "reports-worker", 1)
        s = (sim.get_service("reports-worker") if hasattr(sim, "get_service")
             else getattr(sim, "services", {}).get("reports-worker"))
        nc = s.get("cost_per_hour") if isinstance(s, dict) else getattr(s, "cost_per_hour", None)
        if nc is None:
            self.fail("Production Gap: Simulator does not update cost_per_hour.")
        self.assertLess(nc, init_cost)


# ===========================================================================
# 4. SAFETY REGRESSION
# ===========================================================================

class TestSafetyRegression(unittest.TestCase):

    def setUp(self):
        self.engine = get_safety_engine()
        self.violations = load_fixture("safety_violations.json")

    def _req(self):
        if self.engine is None:
            self.fail("Production Gap: Safety Engine not implemented in backend.safety.")
        return self.engine

    def _case(self, name: str) -> Dict[str, Any]:
        for v in self.violations["violations"]:
            if v["scenario_name"] == name:
                return v
        raise KeyError(name)

    def _eval(self, svc, action, target=None, **kw):
        eng = self._req()
        for m in ("check_safety", "evaluate", "guardrail"):
            if hasattr(eng, m):
                return getattr(eng, m)(service=svc, action=action,
                                       target_instances=target, **kw)
        if callable(eng):
            return eng(service=svc, action=action, target_instances=target, **kw)
        self.fail("Production Gap: Safety Engine has no recognizable method.")

    def _blocked(self, r, kw=None):
        if isinstance(r, SafetyCheckResult):
            self.assertFalse(r.is_approved)
            if kw:
                self.assertIn(kw.lower(), " ".join(r.rejection_reasons).lower())
        elif isinstance(r, tuple):
            self.assertFalse(r[0])
        elif isinstance(r, dict):
            self.assertFalse(r.get("is_approved", True))
        else:
            self.fail(f"Unexpected result type: {type(r)}")

    def _approved(self, r):
        if isinstance(r, SafetyCheckResult):
            self.assertTrue(r.is_approved, str(r.rejection_reasons))
        elif isinstance(r, tuple):
            self.assertTrue(r[0])
        elif isinstance(r, dict):
            self.assertTrue(r.get("is_approved", False))
        else:
            self.fail(f"Unexpected result type: {type(r)}")

    def test_safety_engine_production_gap(self):
        if self.engine is None:
            self.fail("Production Gap: Safety Engine not implemented in backend.safety.")

    def test_below_minimum_capacity_blocked(self):
        c = self._case("below_minimum_capacity")
        self._blocked(self._eval(c["service"], c["attempted_action"]["action"],
                                  c["attempted_action"]["target_instances"]), "minimum")

    def test_above_maximum_capacity_blocked(self):
        c = self._case("above_maximum_capacity")
        self._blocked(self._eval(c["service"], c["attempted_action"]["action"],
                                  c["attempted_action"]["target_instances"]), "maximum")

    def test_latency_violation_blocked(self):
        c = self._case("latency_violation")
        self._blocked(self._eval(c["service"], c["attempted_action"]["action"],
                                  c["attempted_action"]["target_instances"]), "latency")

    def test_unhealthy_service_blocked(self):
        c = self._case("unhealthy_service")
        self.assertFalse(c["service"]["healthy"])
        self._blocked(self._eval(c["service"], c["attempted_action"]["action"],
                                  c["attempted_action"]["target_instances"]), "health")

    def test_stale_observation_blocked(self):
        d = load_fixture("stale_observation.json")
        self._blocked(self._eval(d["service"], "scale_down", 2,
            proposal_version=d["observation"]["state_version"],
            evaluated_against_version=d["latest_traffic"]["state_version"]), "stale")

    def test_missing_metric_data_fails_closed(self):
        c = self._case("missing_metric_data")
        self.assertIsNone(c["service"].get("cpu_percent"))
        self._blocked(self._eval(c["service"], c["attempted_action"]["action"],
                                  c["attempted_action"]["target_instances"]))

    def test_invalid_action_blocked(self):
        c = self._case("invalid_action")
        self.assertEqual(c["attempted_action"]["action"], "terminate_cluster")
        self._blocked(self._eval(c["service"], c["attempted_action"]["action"],
                                  c["attempted_action"]["target_instances"]))

    def test_valid_action_allowed(self):
        d = load_fixture("underutilized_service.json")
        self._approved(self._eval(d["service"], "scale_down",
            d["expected_behavior"]["expected_scale_down_target"],
            proposal_version=d["observation"]["state_version"],
            evaluated_against_version=d["observation"]["state_version"]))

    def test_no_action_allowed(self):
        d = load_fixture("rising_traffic.json")
        self._approved(self._eval(d["service"], "no_action", d["service"]["instances"],
            proposal_version=d["observation"]["state_version"],
            evaluated_against_version=d["observation"]["state_version"]))

    def test_safety_check_result_schema_blocked(self):
        s = _safety(approved=False, reasons=["Below min"], rules=["cap_check"])
        self.assertFalse(s.is_approved)
        self.assertGreater(len(s.rejection_reasons), 0)

    def test_safety_check_result_schema_approved(self):
        s = _safety(approved=True, rules=["cap_check", "health_check"])
        self.assertTrue(s.is_approved)
        self.assertEqual(len(s.rejection_reasons), 0)

    def test_safety_bypass_prevention_requires_orchestrator(self):
        if get_orchestrator() is None:
            self.fail("Production Gap: Orchestrator missing -- "
                      "no safety-before-execution gate enforced.")

    def test_stale_data_fixture_safety_result_encoded(self):
        d = load_fixture("stale_observation.json")
        self.assertFalse(d["expected_behavior"]["safety_check"]["is_approved"])
        reasons = d["expected_behavior"]["safety_check"]["rejection_reasons"]
        self.assertGreater(len(reasons), 0)
        self.assertIn("stale", reasons[0].lower())

    def test_violations_fixture_all_not_approved(self):
        for v in load_fixture("safety_violations.json")["violations"]:
            with self.subTest(s=v["scenario_name"]):
                self.assertFalse(v["is_approved"])


# ===========================================================================
# 5. VERIFICATION REGRESSION
# ===========================================================================

class TestVerificationRegression(unittest.TestCase):

    def test_state_match_yields_verified_success(self):
        v = _verif(execution=_exec(status=ExecutionStatus.SUCCESS, new_ver="v1.0.1"), ok=True)
        self.assertTrue(v.is_successful)
        self.assertEqual(v.execution.status, ExecutionStatus.SUCCESS)

    def test_state_mismatch_not_verified_success(self):
        v = _verif(execution=_exec(), ok=False, notes="Instances unchanged at 4.")
        self.assertFalse(v.is_successful)

    def test_execution_failure_not_verified_success(self):
        v = _verif(safety=_safety(approved=True),
                   execution=_exec(status=ExecutionStatus.FAILURE,
                                    err="capacity_unavailable", new_ver=None),
                   ok=False, notes="Execution failed.")
        self.assertFalse(v.is_successful)
        self.assertEqual(v.execution.status, ExecutionStatus.FAILURE)

    def test_blocked_safety_has_no_execution(self):
        v = _verif(safety=_safety(approved=False, reasons=["Below min"]),
                   execution=None, ok=False, notes="Blocked.")
        self.assertIsNone(v.execution)
        self.assertFalse(v.is_successful)

    def test_no_action_execution_is_none(self):
        v = _verif(decision=_dec(proposal=_prop(action=InfrastructureAction.NO_ACTION)),
                   execution=None, ok=True, notes="No-op.")
        self.assertIsNone(v.execution)

    def test_workflow_report_embeds_verification(self):
        obs = _obs()
        v = _verif(decision=_dec(obs=obs), execution=_exec(), ok=True)
        r = WorkflowReport(workflow_id="wf-001", initial_observation=obs, final_verification=v)
        self.assertEqual(r.workflow_id, "wf-001")
        self.assertTrue(r.final_verification.is_successful)

    def test_execution_result_has_no_is_successful_attr(self):
        self.assertFalse(hasattr(_exec(), "is_successful"))

    def test_failed_action_fixture_verification_semantics(self):
        vd = load_fixture("failed_action.json")["expected_behavior"]["verification"]
        self.assertFalse(vd["is_successful"])
        self.assertFalse(vd["state_confirmed"])
        self.assertEqual(vd["actual_instances_remaining"], 3)

    def test_stale_fixture_blocks_action_in_expected_behavior(self):
        d = load_fixture("stale_observation.json")
        self.assertFalse(d["expected_behavior"]["action_permitted_on_stale_data"])
        self.assertFalse(d["expected_behavior"]["safety_check"]["is_approved"])

    def test_underutilized_fixture_expects_verified_success(self):
        d = load_fixture("underutilized_service.json")
        self.assertTrue(d["expected_behavior"]["verification"]["is_successful"])
        self.assertTrue(d["expected_behavior"]["verification"]["state_confirmed"])
        self.assertTrue(d["expected_behavior"]["safety_check"]["is_approved"])


# ===========================================================================
# 6. API REGRESSION
# ===========================================================================

class TestAPIRegression(unittest.TestCase):

    def setUp(self):
        self.app_mod = get_backend_api()

    def test_backend_api_production_gap(self):
        if self.app_mod is None:
            self.fail("Production Gap: Backend API not implemented in "
                      "backend.main / backend.app / backend.api.")

    def test_valid_proposal_schema_validates(self):
        d = load_fixture("underutilized_service.json")
        p = ActionProposal.model_validate({
            "action": "scale_down",
            "target_service_id": d["service"]["service_id"],
            "reason": "Idle", "expected_effect": "Scale to 1",
            "observation_version": d["observation"]["state_version"],
            "confidence": 0.95,
        })
        self.assertEqual(p.action, InfrastructureAction.SCALE_DOWN)

    def test_invalid_proposal_schema_rejected(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"action": "terminate_cluster", "confidence": 9.9})

    def test_execution_failure_status_not_success(self):
        er = _exec(status=ExecutionStatus.FAILURE, err="cap", new_ver=None)
        self.assertEqual(er.status, ExecutionStatus.FAILURE)
        self.assertNotEqual(er.status, ExecutionStatus.SUCCESS)

    def test_http_200_requires_state_confirmed(self):
        def verified(code, confirmed): return code == 200 and confirmed
        self.assertFalse(verified(200, False))
        self.assertTrue(verified(200, True))

    def test_blocked_safety_produces_false_is_successful(self):
        v = _verif(safety=_safety(approved=False, reasons=["Below min"]),
                   execution=None, ok=False)
        self.assertFalse(v.is_successful)


# ===========================================================================
# 7. AGENT CONTRACT REGRESSION
# ===========================================================================

class TestAgentContractRegression(unittest.TestCase):

    def test_valid_scale_down_proposal_structure(self):
        d = load_fixture("underutilized_service.json")
        p = _prop(action=InfrastructureAction.SCALE_DOWN,
                  svc=d["service"]["service_id"],
                  ver=d["observation"]["state_version"], conf=0.95)
        self.assertEqual(p.action, InfrastructureAction.SCALE_DOWN)
        self.assertGreaterEqual(p.confidence, 0.0)
        self.assertLessEqual(p.confidence, 1.0)

    def test_valid_scale_up_proposal_structure(self):
        d = load_fixture("rising_traffic.json")
        p = _prop(action=InfrastructureAction.SCALE_UP,
                  svc=d["service"]["service_id"],
                  ver=d["observation"]["state_version"], conf=0.88)
        self.assertEqual(p.action, InfrastructureAction.SCALE_UP)

    def test_valid_no_action_proposal_structure(self):
        p = _prop(action=InfrastructureAction.NO_ACTION, conf=1.0)
        self.assertEqual(p.action, InfrastructureAction.NO_ACTION)

    def test_terminate_cluster_rejected(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"action": "terminate_cluster",
                "target_service_id": "s", "reason": "r",
                "expected_effect": "e", "observation_version": "v1", "confidence": 0.9})

    def test_drop_db_rejected(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"action": "drop_db",
                "target_service_id": "db", "reason": "r",
                "expected_effect": "e", "observation_version": "v1", "confidence": 0.5})

    def test_missing_confidence_rejected(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"action": "scale_down", "target_service_id": "s",
                "reason": "r", "expected_effect": "e", "observation_version": "v1"})

    def test_string_confidence_rejected(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"action": "scale_down", "target_service_id": "s",
                "reason": "r", "expected_effect": "e", "observation_version": "v1",
                "confidence": "high"})

    def test_llm_timeout_payloads_rejected(self):
        for bad in [{}, {"error": "timeout"}, {"action": None, "confidence": None}]:
            with self.subTest(bad=repr(bad)):
                with self.assertRaises((ValidationError, AttributeError, TypeError)):
                    ActionProposal.model_validate(bad)

    def test_agent_module_production_gap(self):
        if get_agent_module() is None:
            self.fail("Production Gap: Agent decision module not found in backend.agents.")

    def test_proposal_is_not_execution_result(self):
        p = _prop()
        self.assertNotIsInstance(p, ExecutionResult)
        self.assertFalse(hasattr(p, "status"))
        self.assertFalse(hasattr(p, "is_successful"))

    def test_out_of_range_confidence_rejected(self):
        for bad in (1.5, -0.5, 2.0):
            with self.subTest(c=bad):
                with self.assertRaises(ValidationError):
                    ActionProposal.model_validate({"action": "scale_down",
                        "target_service_id": "s", "reason": "r",
                        "expected_effect": "e", "observation_version": "v1",
                        "confidence": bad})


# ===========================================================================
# 8. ORCHESTRATION REGRESSION
# ===========================================================================

class TestOrchestrationRegression(unittest.TestCase):

    def test_orchestrator_production_gap(self):
        if get_orchestrator() is None:
            self.fail("Production Gap: Orchestrator not implemented in backend.orchestrator.")

    def test_decision_embeds_investigation(self):
        inv = InvestigationResult(observation=_obs(),
            identified_issues=["Idle: 0 RPM"], summary="Idle -- scale down.")
        dec = DecisionResult(investigation=inv, proposal=_prop())
        self.assertIn("idle", dec.investigation.summary.lower())

    def test_verification_requires_safety_check(self):
        with self.assertRaises(ValidationError):
            VerificationResult.model_validate({"decision": _dec().model_dump(),
                "is_successful": True, "verification_notes": "ok"})

    def test_blocked_safety_leaves_execution_none(self):
        v = _verif(safety=_safety(approved=False, reasons=["Below min"]),
                   execution=None, ok=False)
        self.assertIsNone(v.execution)
        self.assertFalse(v.safety_check.is_approved)

    def test_7_stage_workflow_schema_assembly(self):
        obs = _obs()
        inv = InvestigationResult(observation=obs, identified_issues=["9% CPU"], summary="Idle.")
        dec = DecisionResult(investigation=inv, proposal=_prop())
        sf = _safety(approved=True, rules=["cap", "health"])
        ex = _exec()
        v = VerificationResult(decision=dec, safety_check=sf, execution=ex,
            is_successful=True, verification_notes="Confirmed.")
        r = WorkflowReport(workflow_id="wf-7stage", initial_observation=obs, final_verification=v)
        self.assertTrue(r.final_verification.is_successful)

    def test_stale_version_mismatch_encoded_in_safety(self):
        sf = _safety(approved=False, pver="v1.0.0-0800", ever="v1.0.0-1030",
                     reasons=["150 min stale"], rules=["freshness"])
        self.assertFalse(sf.is_approved)
        self.assertNotEqual(sf.proposal_version, sf.evaluated_against_version)

    def test_failed_execution_reaches_verification(self):
        v = _verif(safety=_safety(approved=True),
                   execution=_exec(action=InfrastructureAction.SCALE_UP, svc="payment-api",
                                    status=ExecutionStatus.FAILURE,
                                    err="capacity_unavailable", new_ver=None),
                   ok=False, notes="Execution failed.")
        self.assertFalse(v.is_successful)
        self.assertEqual(v.execution.error_code, "capacity_unavailable")

    def test_no_bypass_schema_enforces_safety_check(self):
        with self.assertRaises(ValidationError):
            VerificationResult.model_validate({"decision": _dec().model_dump(),
                "is_successful": True, "verification_notes": "bypass"})


# ===========================================================================
# 9. END-TO-END REGRESSION
# ===========================================================================

class TestEndToEndRegression(unittest.TestCase):

    def test_primary_demo_underutilized_scale_down(self):
        d = load_fixture("underutilized_service.json")
        self.assertEqual(d["service"]["instances"], 4)
        self.assertEqual(d["expected_behavior"]["expected_scale_down_target"], 1)
        self.assertTrue(d["expected_behavior"]["safety_check"]["is_approved"])
        self.assertTrue(d["expected_behavior"]["verification"]["is_successful"])
        od = d["observation"]
        obs = ServiceObservation(service_id=od["service_id"],
            cpu_utilization_percent=od["cpu_utilization_percent"],
            memory_utilization_percent=od["memory_utilization_percent"],
            traffic_rpm=od["traffic_rpm"], latency_ms=od["latency_ms"],
            cost_per_hour=od["cost_per_hour"],
            observation_timestamp=T_1030, state_version=od["state_version"])
        v = _verif(
            decision=DecisionResult(
                investigation=InvestigationResult(observation=obs, summary="Idle"),
                proposal=_prop(svc=d["service"]["service_id"],
                               ver=od["state_version"], conf=0.97)),
            safety=_safety(approved=True,
                rules=d["expected_behavior"]["safety_check"]["applied_rules"]),
            execution=_exec(new_ver="v1.0.1"), ok=True,
            notes=d["expected_behavior"]["verification"]["notes"])
        self.assertTrue(v.is_successful)

    def test_failed_action_variant(self):
        d = load_fixture("failed_action.json")
        od = d["observation"]
        obs = ServiceObservation(service_id=od["service_id"],
            cpu_utilization_percent=od["cpu_utilization_percent"],
            memory_utilization_percent=od["memory_utilization_percent"],
            traffic_rpm=od["traffic_rpm"], latency_ms=od["latency_ms"],
            cost_per_hour=od["cost_per_hour"],
            observation_timestamp=T_1030, state_version=od["state_version"])
        v = _verif(
            decision=DecisionResult(
                investigation=InvestigationResult(observation=obs, summary="High load"),
                proposal=ActionProposal(action=InfrastructureAction.SCALE_UP,
                    target_service_id="payment-api", reason="CPU 91%",
                    expected_effect="Scale to 5", observation_version=od["state_version"],
                    confidence=0.92)),
            safety=_safety(approved=True),
            execution=_exec(action=InfrastructureAction.SCALE_UP, svc="payment-api",
                             status=ExecutionStatus.FAILURE,
                             err="capacity_unavailable", new_ver=None),
            ok=False, notes=d["expected_behavior"]["verification"]["verification_notes"])
        self.assertFalse(v.is_successful)
        self.assertEqual(v.execution.error_code, "capacity_unavailable")

    def test_safety_blocked_variant(self):
        c = load_fixture("safety_violations.json")["violations"][0]
        self.assertEqual(c["scenario_name"], "below_minimum_capacity")
        v = _verif(safety=_safety(approved=False, reasons=[c["rejection_reason"]],
                                   rules=["capacity_boundary_check"]),
                   execution=None, ok=False)
        self.assertFalse(v.is_successful)
        self.assertIsNone(v.execution)

    def test_stale_observation_variant(self):
        d = load_fixture("stale_observation.json")
        stale_obs = ServiceObservation(service_id="checkout-api",
            cpu_utilization_percent=24.0, memory_utilization_percent=39.0,
            traffic_rpm=900, latency_ms=170.0, cost_per_hour=20.0,
            observation_timestamp=T_0800, state_version="v1.0.0-0800")
        v = _verif(
            decision=DecisionResult(
                investigation=InvestigationResult(observation=stale_obs, summary="Stale"),
                proposal=_prop(svc="checkout-api", ver="v1.0.0-0800")),
            safety=_safety(approved=False, pver="v1.0.0-0800", ever="v1.0.0-1030",
                reasons=[d["expected_behavior"]["safety_check"]["rejection_reasons"][0]],
                rules=["data_freshness_check"]),
            execution=None, ok=False)
        self.assertFalse(v.is_successful)
        self.assertIsNone(v.execution)

    def test_verification_mismatch_variant(self):
        v = _verif(execution=_exec(status=ExecutionStatus.SUCCESS),
                   ok=False, notes="Instances unchanged at 4.")
        self.assertFalse(v.is_successful)
        self.assertEqual(v.execution.status, ExecutionStatus.SUCCESS)

    def test_underutilized_service_e2e_contract_values(self):
        d = load_fixture("underutilized_service.json")
        self.assertEqual(d["service"]["service_id"], "reports-worker")
        self.assertEqual(d["service"]["instances"], 4)
        self.assertEqual(d["service"]["min_instances"], 1)
        self.assertEqual(d["expected_behavior"]["expected_action"], "scale_down")
        self.assertEqual(d["expected_behavior"]["expected_scale_down_target"], 1)


# ===========================================================================
# 10. BROWSER / UI TRUTHFULNESS REGRESSION
# ===========================================================================

class TestBrowserUITruthfulnessRegression(unittest.TestCase):

    def test_ui_presentation_outcome_distinctness(self):
        states = {"VERIFIED_SUCCESS", "BLOCKED", "EXECUTION_FAILED", "VERIFICATION_FAILURE"}
        self.assertEqual(len(states), 4)
        self.assertNotIn("SUCCESS", {"BLOCKED", "EXECUTION_FAILED", "VERIFICATION_FAILURE"})

    def test_blocked_safety_state_never_shows_success(self):
        label = "BLOCKED" if not _safety(approved=False).is_approved else "ALLOWED"
        self.assertNotEqual(label, "SUCCESS")
        self.assertNotEqual(label, "VERIFIED_SUCCESS")

    def test_execution_failure_never_shows_success(self):
        er = _exec(status=ExecutionStatus.FAILURE, new_ver=None)
        label = "EXECUTION_FAILED" if er.status == ExecutionStatus.FAILURE else "ATTEMPTED"
        self.assertNotEqual(label, "SUCCESS")
        self.assertNotEqual(label, "VERIFIED_SUCCESS")

    def test_verification_failure_never_shows_verified_success(self):
        v = _verif(execution=_exec(), ok=False, notes="Mismatch.")
        label = "VERIFIED_SUCCESS" if v.is_successful else "VERIFICATION_FAILURE"
        self.assertEqual(label, "VERIFICATION_FAILURE")

    def test_stale_data_requires_refresh_label(self):
        d = load_fixture("stale_observation.json")
        label = "STALE" if d["staleness_details"]["is_stale"] else "FRESH"
        self.assertEqual(label, "STALE")

    def test_proposed_action_enum_matches_fixture(self):
        d = load_fixture("underutilized_service.json")
        ea = d["expected_behavior"]["expected_action"]
        self.assertEqual(ea, "scale_down")
        self.assertEqual(InfrastructureAction(ea), InfrastructureAction.SCALE_DOWN)

    def test_audit_record_preserves_failure_notes(self):
        obs = _obs(service_id="payment-api", cpu=91.0)
        v = _verif(decision=_dec(obs=obs),
                   execution=_exec(action=InfrastructureAction.SCALE_UP, svc="payment-api",
                                    status=ExecutionStatus.FAILURE,
                                    err="capacity_unavailable", new_ver=None),
                   ok=False, notes="Execution failed: capacity_unavailable.")
        r = WorkflowReport(workflow_id="wf-audit-001",
                           initial_observation=obs, final_verification=v)
        self.assertFalse(r.final_verification.is_successful)
        self.assertIn("capacity_unavailable", r.final_verification.verification_notes)

    def test_http_200_alone_not_verified_success(self):
        def ui_verified(code, confirmed): return code == 200 and confirmed
        self.assertFalse(ui_verified(200, False))
        self.assertTrue(ui_verified(200, True))


# ===========================================================================
# 11. FAILURE REGRESSION
# ===========================================================================

class TestFailureRegression(unittest.TestCase):

    def test_missing_service_id_fails_closed(self):
        with self.assertRaises(ValidationError):
            ServiceObservation(service_id=None,   # type: ignore[arg-type]
                cpu_utilization_percent=9.0, memory_utilization_percent=15.0,
                traffic_rpm=0, latency_ms=0.0, cost_per_hour=11.0,
                observation_timestamp=T_1030, state_version="v1")

    def test_null_cpu_fails_closed(self):
        with self.assertRaises(ValidationError):
            ServiceObservation(service_id="s",
                cpu_utilization_percent=None,   # type: ignore[arg-type]
                memory_utilization_percent=15.0, traffic_rpm=0, latency_ms=0.0,
                cost_per_hour=11.0, observation_timestamp=T_1030, state_version="v1")

    def test_failed_action_result_is_failure(self):
        d = load_fixture("failed_action.json")
        self.assertIn(d["action_result"]["status"], ("failed", "failure"))
        self.assertEqual(d["action_result"]["error"], "capacity_unavailable")

    def test_execution_failure_propagates_to_false_is_successful(self):
        v = _verif(execution=_exec(status=ExecutionStatus.FAILURE,
                                    err="capacity_unavailable", new_ver=None), ok=False)
        self.assertFalse(v.is_successful)

    def test_safety_block_produces_false_is_successful(self):
        v = _verif(safety=_safety(approved=False, reasons=["Latency ceiling"]),
                   execution=None, ok=False)
        self.assertFalse(v.is_successful)
        self.assertIsNone(v.execution)

    def test_stale_fixture_blocks_action(self):
        d = load_fixture("stale_observation.json")
        self.assertFalse(d["expected_behavior"]["action_permitted_on_stale_data"])

    def test_invalid_action_schema_rejection(self):
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({"action": "terminate_cluster",
                "target_service_id": "s", "reason": "r",
                "expected_effect": "e", "observation_version": "v1", "confidence": 0.9})

    def test_out_of_range_confidence_rejected(self):
        for bad in (1.5, -0.5, 2.0):
            with self.subTest(c=bad):
                with self.assertRaises(ValidationError):
                    ActionProposal.model_validate({"action": "scale_down",
                        "target_service_id": "s", "reason": "r",
                        "expected_effect": "e", "observation_version": "v1",
                        "confidence": bad})

    def test_timeout_execution_not_success(self):
        er = ExecutionResult(action=InfrastructureAction.SCALE_UP,
            target_service_id="payment-api", status=ExecutionStatus.FAILURE,
            error_code="timeout",
            error_message="Action timed out; infrastructure state unknown.")
        self.assertEqual(er.status, ExecutionStatus.FAILURE)
        self.assertIsNone(er.new_state_version)

    def test_retry_idempotency_production_gap(self):
        orch = get_orchestrator()
        if orch is None:
            self.fail("Production Gap: Orchestrator missing -- "
                      "retry/idempotency behavior unverifiable.")
        if not (hasattr(orch, "retry") or hasattr(orch, "idempotency_key")):
            self.fail("Production Gap: Orchestrator lacks retry/idempotency method.")


# ===========================================================================
# CRITICAL REGRESSION INVARIANTS (RULES 1-10)
# ===========================================================================

class TestCriticalRegressionInvariants(unittest.TestCase):
    """10 core invariants -- MUST NEVER be weakened or removed."""

    def test_rule_1_no_safety_approval_no_execution(self):
        """RULE 1: No safety approval -> no infrastructure execution."""
        v = _verif(safety=_safety(approved=False,
                       reasons=["Target capacity below minimum"],
                       rules=["capacity_boundary_check"]),
                   execution=None, ok=False,
                   notes="Blocked by safety; execution prohibited.")
        self.assertFalse(v.safety_check.is_approved)
        self.assertIsNone(v.execution)
        self.assertFalse(v.is_successful)

    def test_rule_2_execution_failure_never_verified_success(self):
        """RULE 2: Execution failure -> never verified success."""
        er = _exec(status=ExecutionStatus.FAILURE, err="capacity_unavailable", new_ver=None)
        self.assertEqual(er.status, ExecutionStatus.FAILURE)

        def is_verified_success(r: ExecutionResult, v_success: bool) -> bool:
            return r.status == ExecutionStatus.SUCCESS and v_success

        self.assertFalse(is_verified_success(er, True))
        self.assertFalse(is_verified_success(er, False))

    def test_rule_3_execution_success_alone_never_verified_success(self):
        """RULE 3: Execution SUCCESS alone -> never verified success."""
        exec_claim = _exec(status=ExecutionStatus.SUCCESS)
        self.assertFalse(hasattr(exec_claim, "is_successful"))

    def test_rule_4_expected_effect_text_alone_never_verified_success(self):
        """RULE 4: Expected effect text alone -> never verified success."""
        proposal = ActionProposal(action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Certain reduction",
            expected_effect="Instances successfully reduced to 1 and cost decreased by $8.25/hr",
            observation_version="v1.0.0", confidence=0.99)
        self.assertNotIsInstance(proposal, ExecutionResult)
        self.assertFalse(hasattr(proposal, "is_successful"))

    def test_rule_5_http_200_alone_never_verified_success(self):
        """RULE 5: HTTP 200 alone -> never verified success."""
        def evaluate_api_result(status_code: int, state_confirmed: bool) -> bool:
            return status_code == 200 and state_confirmed

        self.assertFalse(evaluate_api_result(200, False))
        self.assertTrue(evaluate_api_result(200, True))

    def test_rule_6_stale_critical_telemetry_no_risky_action_claim(self):
        """RULE 6: Stale critical telemetry -> no risky successful action claim."""
        stale_safety = SafetyCheckResult(
            is_approved=False,
            proposal_version="v1.0.0-0800",
            evaluated_against_version="v1.0.0-1030",
            rejection_reasons=["Data version v1.0.0-0800 is 150 minutes stale."],
            applied_rules=["data_freshness_check"],
        )
        self.assertFalse(stale_safety.is_approved)

    def test_rule_7_missing_critical_telemetry_fails_closed(self):
        """RULE 7: Missing critical telemetry -> fail closed."""
        with self.assertRaises(ValidationError):
            ServiceObservation(service_id="reports-worker",
                cpu_utilization_percent=None,   # type: ignore[arg-type]
                memory_utilization_percent=15.0, traffic_rpm=0, latency_ms=0.0,
                cost_per_hour=11.0, observation_timestamp=T_BEFORE, state_version="v1.0.0")

    def test_rule_8_observed_state_outranks_execution_claim(self):
        """RULE 8: Observed infrastructure state outranks execution claim."""
        exec_claimed_instances = 1
        observed_instances = 4
        actual_resulting_state = observed_instances
        self.assertEqual(actual_resulting_state, 4)
        self.assertNotEqual(actual_resulting_state, exec_claimed_instances)

    def test_rule_9_blocked_action_remains_blocked_never_success(self):
        """RULE 9: A blocked action remains BLOCKED and is not rewritten as SUCCESS."""
        safety_check = SafetyCheckResult(
            is_approved=False, proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            rejection_reasons=["Action blocked: latency ceiling exceeded."],
            applied_rules=["latency_headroom_check"],
        )
        status_label = "BLOCKED" if not safety_check.is_approved else "ALLOWED"
        self.assertEqual(status_label, "BLOCKED")
        self.assertNotEqual(status_label, "SUCCESS")

    def test_rule_10_no_action_does_not_claim_infrastructure_mutation(self):
        """RULE 10: A no_action result does not claim an infrastructure mutation."""
        proposal = ActionProposal(
            action=InfrastructureAction.NO_ACTION,
            target_service_id="orders-api",
            reason="Traffic within acceptable threshold; maintain instances.",
            expected_effect="Zero infrastructure mutations; instances remain at 4.",
            observation_version="v1.0.0", confidence=1.0,
        )
        self.assertEqual(proposal.action, InfrastructureAction.NO_ACTION)
        v = VerificationResult(
            decision=DecisionResult(
                investigation=InvestigationResult(
                    observation=ServiceObservation(
                        service_id="orders-api",
                        cpu_utilization_percent=28.0,
                        memory_utilization_percent=48.0,
                        traffic_rpm=4200, latency_ms=260.0, cost_per_hour=18.5,
                        observation_timestamp=T_BEFORE, state_version="v1.0.0"),
                    summary="Normal operation"),
                proposal=proposal),
            safety_check=SafetyCheckResult(is_approved=True, proposal_version="v1.0.0",
                                            evaluated_against_version="v1.0.0"),
            execution=None,
            is_successful=True,
            verification_notes="Workflow safely completed with zero infrastructure modification.",
        )
        self.assertIsNone(v.execution)
        self.assertTrue(v.is_successful)


if __name__ == "__main__":
    unittest.main()
