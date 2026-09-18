"""
Unit tests for the Agent Contract Layer.

Goal:
Verify that the agent produces and accepts only structurally valid, safe-to-consume
decision outputs, and protect against direct infrastructure execution bypassing safety.

Scope of Agent Contract Testing (Phase 7):
  - Valid scale-down decision structure (underutilized_service scenario)
  - Valid scale-up / rising-traffic decision structure (rising_traffic scenario)
  - No-action decision structure
  - Malformed agent output rejection (missing fields, wrong types, invalid shapes)
  - Unsupported/invalid action rejection (terminate_cluster, drop_db)
  - Invalid target capacity handling & production schema gap documentation
  - Confidence field validation (required, range [0.0, 1.0], type check, low-confidence behavior)
  - LLM failure handling & LLM adapter discovery (exposing Member 1 production gaps)
  - Extra/unknown field behavior documentation
  - Safety handoff contract: proposals require deterministic Safety Engine approval before execution
  - Truthfulness: agent proposals must NEVER claim execution success

Constraints:
  - Deterministic tests: no real LLM API calls, no network calls, no system clock, no sleep
  - No hidden reasoning tests: test structural contracts, not model intelligence
  - Do NOT modify production code (backend/, frontend/, agent/)
  - Expose production gaps honestly rather than creating mock implementations
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

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
# Deterministic constants — NO system clock usage anywhere
# ─────────────────────────────────────────────────────────────────────────────
T_OBSERVATION = datetime(2026, 9, 17, 10, 30, 0, tzinfo=timezone.utc)
STATE_VERSION_V1 = "v1.0.0"


def load_fixture(filename: str) -> Dict[str, Any]:
    """Load JSON fixture from canonical tests/fixtures directory."""
    filepath = FIXTURES_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Fixture not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Agent implementation discovery helpers (Member 1 production ownership)
# ─────────────────────────────────────────────────────────────────────────────

def get_agent_module() -> Optional[Any]:
    """
    Attempt to discover Member 1's agent decision module or class.
    Returns the agent class/module if found, None if missing.
    """
    candidate_modules = [
        "backend.agents.decision",
        "backend.agents.decision_agent",
        "backend.agents.investigation",
        "backend.agents.investigation_agent",
        "backend.agents.agent",
        "backend.agents.base",
        "backend.agents.core",
    ]
    for mod_name in candidate_modules:
        try:
            mod = __import__(mod_name, fromlist=["*"])
            return mod
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_llm_adapter() -> Optional[Any]:
    """
    Attempt to discover Member 1's LLM adapter or client interface.
    Returns the adapter class/module if found, None if missing.
    """
    candidate_modules = [
        "backend.agents.llm",
        "backend.agents.llm_adapter",
        "backend.agents.client",
        "backend.agents.adapter",
        "backend.services.llm",
    ]
    for mod_name in candidate_modules:
        try:
            mod = __import__(mod_name, fromlist=["*"])
            return mod
        except (ImportError, ModuleNotFoundError):
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Valid Scale-Down Decision
# ─────────────────────────────────────────────────────────────────────────────

class TestValidScaleDownDecision(unittest.TestCase):
    """
    Contract test: Agent produces a structurally valid scale-down decision
    matching the underutilized_service scenario.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("underutilized_service.json")
        obs_data = self.fixture["observation"]
        self.observation = ServiceObservation(
            service_id=obs_data["service_id"],
            cpu_utilization_percent=obs_data["cpu_utilization_percent"],
            memory_utilization_percent=obs_data["memory_utilization_percent"],
            traffic_rpm=obs_data["traffic_rpm"],
            latency_ms=obs_data["latency_ms"],
            cost_per_hour=obs_data["cost_per_hour"],
            observation_timestamp=T_OBSERVATION,
            state_version=obs_data["state_version"],
        )

    def test_valid_scale_down_parses_against_schema(self) -> None:
        """A valid scale-down proposal dictionary must parse cleanly into ActionProposal."""
        raw_proposal = {
            "action": "scale_down",
            "target_service_id": "reports-worker",
            "reason": "CPU utilization is 9% with 0 RPM traffic. Service is idle and candidate for scale-down.",
            "expected_effect": "Reduce instance count to 1, lowering hourly cost from $11.00 to $2.75.",
            "observation_version": "v1.0.0",
            "confidence": 0.95,
        }
        proposal = ActionProposal.model_validate(raw_proposal)
        self.assertIsInstance(proposal, ActionProposal)
        self.assertEqual(proposal.action, InfrastructureAction.SCALE_DOWN)
        self.assertEqual(proposal.target_service_id, "reports-worker")
        self.assertEqual(proposal.observation_version, "v1.0.0")
        self.assertEqual(proposal.confidence, 0.95)

    def test_valid_scale_down_action_enum(self) -> None:
        """The proposed action must resolve to InfrastructureAction.SCALE_DOWN enum."""
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id=self.fixture["service"]["service_id"],
            reason="Underutilized batch service.",
            expected_effect="Scale down instances to reduce cost.",
            observation_version=self.fixture["observation"]["state_version"],
            confidence=0.90,
        )
        self.assertEqual(proposal.action.value, "scale_down")
        self.assertIn(proposal.action, list(InfrastructureAction))

    def test_valid_scale_down_target_service(self) -> None:
        """Target service must match the observed underutilized service."""
        expected_service = self.fixture["service"]["service_id"]
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id=expected_service,
            reason="Service is idle.",
            expected_effect="Scale down to min instances.",
            observation_version="v1.0.0",
            confidence=0.88,
        )
        self.assertEqual(proposal.target_service_id, "reports-worker")

    def test_valid_scale_down_decision_result_structure(self) -> None:
        """The full DecisionResult wrapping investigation and proposal must be valid."""
        investigation = InvestigationResult(
            observation=self.observation,
            identified_issues=["underutilization", "idle_service"],
            summary="Service reports-worker is idle at 9% CPU and 0 RPM.",
        )
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Safe scale down under low load.",
            expected_effect="Reduce instances from 4 to 1.",
            observation_version="v1.0.0",
            confidence=0.95,
        )
        decision = DecisionResult(
            investigation=investigation,
            proposal=proposal,
        )
        self.assertEqual(decision.proposal.action, InfrastructureAction.SCALE_DOWN)
        self.assertEqual(decision.investigation.observation.service_id, "reports-worker")
        self.assertIn("underutilization", decision.investigation.identified_issues)

    def test_valid_scale_down_does_not_assert_hidden_reasoning(self) -> None:
        """
        Contract rule: tests must NOT judge whether the reasoning text is 'smart',
        only that reason and expected_effect strings exist and are non-empty.
        """
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Minimal valid reasoning string.",
            expected_effect="Minimal valid expected effect string.",
            observation_version="v1.0.0",
            confidence=0.75,
        )
        self.assertTrue(len(proposal.reason) > 0)
        self.assertTrue(len(proposal.expected_effect) > 0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Valid Scale-Up / Rising-Traffic Decision
# ─────────────────────────────────────────────────────────────────────────────

class TestValidScaleUpDecision(unittest.TestCase):
    """
    Contract test: Agent produces a structurally valid scale-up or no_action decision
    matching the rising_traffic scenario.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("rising_traffic.json")
        obs_data = self.fixture["observation"]
        self.observation = ServiceObservation(
            service_id=obs_data["service_id"],
            cpu_utilization_percent=obs_data["cpu_utilization_percent"],
            memory_utilization_percent=obs_data["memory_utilization_percent"],
            traffic_rpm=obs_data["traffic_rpm"],
            latency_ms=obs_data["latency_ms"],
            cost_per_hour=obs_data["cost_per_hour"],
            observation_timestamp=T_OBSERVATION,
            state_version=obs_data["state_version"],
        )

    def test_valid_scale_up_parses_against_schema(self) -> None:
        """A valid scale_up proposal for orders-api must parse cleanly."""
        raw_proposal = {
            "action": "scale_up",
            "target_service_id": "orders-api",
            "reason": "Traffic increased 2x to 4200 RPM, latency reached 260ms near 300ms ceiling.",
            "expected_effect": "Increase instances from 4 to 6 to restore latency headroom.",
            "observation_version": "v1.0.0",
            "confidence": 0.92,
        }
        proposal = ActionProposal.model_validate(raw_proposal)
        self.assertEqual(proposal.action, InfrastructureAction.SCALE_UP)
        self.assertEqual(proposal.target_service_id, "orders-api")
        self.assertEqual(proposal.confidence, 0.92)

    def test_valid_no_action_for_rising_traffic_parses(self) -> None:
        """
        In rising traffic, conservative no_action is also structurally valid per fixture
        acceptable_actions: ['scale_up', 'no_action'].
        """
        raw_proposal = {
            "action": "no_action",
            "target_service_id": "orders-api",
            "reason": "Traffic is rising but instances are within acceptable bounds; holding capacity.",
            "expected_effect": "Maintain current 4 instances without risking scale-down.",
            "observation_version": "v1.0.0",
            "confidence": 0.85,
        }
        proposal = ActionProposal.model_validate(raw_proposal)
        self.assertEqual(proposal.action, InfrastructureAction.NO_ACTION)
        self.assertEqual(proposal.target_service_id, "orders-api")

    def test_rising_traffic_decision_result_valid(self) -> None:
        """Full DecisionResult for rising traffic is structurally compliant."""
        investigation = InvestigationResult(
            observation=self.observation,
            identified_issues=["rising_traffic", "approaching_latency_ceiling"],
            summary="Traffic doubled to 4200 RPM with latency at 260ms.",
        )
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_UP,
            target_service_id="orders-api",
            reason="Capacity protection needed under rising load.",
            expected_effect="Scale up to absorb incoming traffic.",
            observation_version="v1.0.0",
            confidence=0.91,
        )
        decision = DecisionResult(
            investigation=investigation,
            proposal=proposal,
        )
        self.assertEqual(decision.proposal.action, InfrastructureAction.SCALE_UP)
        self.assertEqual(decision.investigation.observation.service_id, "orders-api")


# ─────────────────────────────────────────────────────────────────────────────
# 3. No-Action Output
# ─────────────────────────────────────────────────────────────────────────────

class TestNoActionDecision(unittest.TestCase):
    """
    Contract test: Verify a valid no_action response is accepted and all
    required fields remain structurally valid.
    """

    def test_no_action_enum_accepted(self) -> None:
        """InfrastructureAction.NO_ACTION must be a member of the action enum."""
        self.assertIn("no_action", [a.value for a in InfrastructureAction])
        self.assertEqual(InfrastructureAction.NO_ACTION.value, "no_action")

    def test_no_action_proposal_complete(self) -> None:
        """A complete no_action proposal must validate without error."""
        proposal = ActionProposal(
            action=InfrastructureAction.NO_ACTION,
            target_service_id="reports-worker",
            reason="System metrics within steady-state envelope. No cost optimization action required.",
            expected_effect="Zero changes to infrastructure; state remains unchanged.",
            observation_version="v1.0.0",
            confidence=1.0,
        )
        self.assertEqual(proposal.action, InfrastructureAction.NO_ACTION)
        self.assertEqual(proposal.target_service_id, "reports-worker")
        self.assertEqual(proposal.confidence, 1.0)

    def test_no_action_required_fields_retained(self) -> None:
        """no_action proposal must not omit reason, expected_effect, observation_version, or confidence."""
        with self.assertRaises(ValidationError):
            # Missing reason and expected_effect
            ActionProposal.model_validate({
                "action": "no_action",
                "target_service_id": "reports-worker",
                "observation_version": "v1.0.0",
                "confidence": 0.9,
            })


# ─────────────────────────────────────────────────────────────────────────────
# 4. Malformed Output Rejection
# ─────────────────────────────────────────────────────────────────────────────

class TestMalformedOutput(unittest.TestCase):
    """
    Contract test: Parser/validator rejects malformed agent output and never
    silently converts it into a valid infrastructure action proposal.
    """

    def test_missing_action_rejected(self) -> None:
        """Missing 'action' field must raise ValidationError."""
        raw = {
            "target_service_id": "reports-worker",
            "reason": "Idle service",
            "expected_effect": "Save money",
            "observation_version": "v1.0.0",
            "confidence": 0.9,
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_missing_target_service_rejected(self) -> None:
        """Missing 'target_service_id' field must raise ValidationError."""
        raw = {
            "action": "scale_down",
            "reason": "Idle service",
            "expected_effect": "Save money",
            "observation_version": "v1.0.0",
            "confidence": 0.9,
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_missing_reason_rejected(self) -> None:
        """Missing 'reason' field must raise ValidationError."""
        raw = {
            "action": "scale_down",
            "target_service_id": "reports-worker",
            "expected_effect": "Save money",
            "observation_version": "v1.0.0",
            "confidence": 0.9,
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_missing_expected_effect_rejected(self) -> None:
        """Missing 'expected_effect' field must raise ValidationError."""
        raw = {
            "action": "scale_down",
            "target_service_id": "reports-worker",
            "reason": "Idle service",
            "observation_version": "v1.0.0",
            "confidence": 0.9,
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_missing_observation_version_rejected(self) -> None:
        """Missing 'observation_version' field must raise ValidationError."""
        raw = {
            "action": "scale_down",
            "target_service_id": "reports-worker",
            "reason": "Idle service",
            "expected_effect": "Save money",
            "confidence": 0.9,
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_non_dict_payload_rejected(self) -> None:
        """Non-dictionary payloads (strings, lists, ints, None) must raise ValidationError."""
        for invalid_payload in ["scale_down", 12345, ["scale_down", "reports-worker"], None]:
            with self.subTest(payload=invalid_payload):
                with self.assertRaises(ValidationError):
                    ActionProposal.model_validate(invalid_payload)

    def test_incorrect_field_types_rejected(self) -> None:
        """Passing non-numeric confidence or invalid action types must raise ValidationError."""
        raw = {
            "action": 99999,
            "target_service_id": "reports-worker",
            "reason": "Idle service",
            "expected_effect": "Save money",
            "observation_version": "v1.0.0",
            "confidence": "extremely_high",
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Invalid Action Rejection
# ─────────────────────────────────────────────────────────────────────────────

class TestInvalidAction(unittest.TestCase):
    """
    Contract test: Unsupported actions (e.g. terminate_cluster) are rejected
    and cannot become executable infrastructure actions.
    """

    def test_terminate_cluster_rejected(self) -> None:
        """'terminate_cluster' is not an allowed action and must be rejected."""
        raw = {
            "action": "terminate_cluster",
            "target_service_id": "reports-worker",
            "reason": "Save maximum cost by destroying everything.",
            "expected_effect": "Zero cost.",
            "observation_version": "v1.0.0",
            "confidence": 1.0,
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_drop_database_rejected(self) -> None:
        """'drop_database' is not an allowed action and must be rejected."""
        raw = {
            "action": "drop_database",
            "target_service_id": "reports-worker",
            "reason": "Unsafe deletion action.",
            "expected_effect": "Destroy data.",
            "observation_version": "v1.0.0",
            "confidence": 0.99,
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_reboot_host_rejected(self) -> None:
        """'reboot_host' is not an allowed action and must be rejected."""
        raw = {
            "action": "reboot_host",
            "target_service_id": "reports-worker",
            "reason": "Host maintenance.",
            "expected_effect": "Host reboot.",
            "observation_version": "v1.0.0",
            "confidence": 0.8,
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_arbitrary_string_action_cannot_become_enum(self) -> None:
        """Arbitrary strings cannot be coerced into InfrastructureAction."""
        with self.assertRaises(ValueError):
            InfrastructureAction("random_unsupported_action")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Invalid Target Capacity & Production Schema Gap
# ─────────────────────────────────────────────────────────────────────────────

class TestTargetCapacityContract(unittest.TestCase):
    """
    Contract test: Verify that invalid target capacity cannot be silently normalized
    by the agent contract layer, and expose the schema-level capacity binding gap.
    """

    def test_action_proposal_schema_lacks_target_capacity_field(self) -> None:
        """
        PRODUCTION SCHEMA GAP:
        ActionProposal defines (action, target_service_id, reason, expected_effect,
        observation_version, confidence). It currently lacks a numeric `target_instances`
        or `target_capacity` field to bind and validate instance counts directly at the schema level.
        Document this gap clearly.
        """
        fields = ActionProposal.model_fields.keys()
        self.assertNotIn(
            "target_instances",
            fields,
            "ActionProposal does not define a 'target_instances' field; capacity is free-text in reason/expected_effect."
        )
        self.assertNotIn(
            "target_capacity",
            fields,
            "ActionProposal does not define a 'target_capacity' field."
        )

    def test_out_of_bounds_target_capacity_not_silently_normalized(self) -> None:
        """
        If a model outputs target capacity via extra fields (e.g. target_instances=0 below min=1),
        the schema must not silently coerce it to a valid instance count.
        """
        raw = {
            "action": "scale_down",
            "target_service_id": "reports-worker",
            "reason": "Scale to 0 instances",
            "expected_effect": "Save all cost",
            "observation_version": "v1.0.0",
            "confidence": 0.9,
            "target_instances": 0,  # Below min_instances=1 in underutilized_service fixture
        }
        proposal = ActionProposal.model_validate(raw)
        # Verify proposal did NOT create or normalize an attribute
        if hasattr(proposal, "target_instances"):
            self.assertNotEqual(
                getattr(proposal, "target_instances"),
                1,
                "Schema must not silently normalize invalid target 0 into valid target 1"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Confidence Field Contract
# ─────────────────────────────────────────────────────────────────────────────

class TestConfidenceContract(unittest.TestCase):
    """
    Contract test: Confidence field validation: required, range [0.0, 1.0],
    float type check, and preservation of low-confidence values.
    """

    def test_missing_confidence_rejected(self) -> None:
        """Confidence is a required field in ActionProposal; omitting it must fail."""
        raw = {
            "action": "scale_down",
            "target_service_id": "reports-worker",
            "reason": "Idle service",
            "expected_effect": "Save cost",
            "observation_version": "v1.0.0",
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_non_numeric_confidence_rejected(self) -> None:
        """String confidence like 'high' or 'medium' must be rejected."""
        raw = {
            "action": "scale_down",
            "target_service_id": "reports-worker",
            "reason": "Idle service",
            "expected_effect": "Save cost",
            "observation_version": "v1.0.0",
            "confidence": "high",
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_negative_confidence_rejected(self) -> None:
        """Confidence < 0.0 must raise ValidationError (ge=0.0 constraint)."""
        raw = {
            "action": "scale_down",
            "target_service_id": "reports-worker",
            "reason": "Idle service",
            "expected_effect": "Save cost",
            "observation_version": "v1.0.0",
            "confidence": -0.1,
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_confidence_above_one_rejected(self) -> None:
        """Confidence > 1.0 must raise ValidationError (le=1.0 constraint)."""
        raw = {
            "action": "scale_down",
            "target_service_id": "reports-worker",
            "reason": "Idle service",
            "expected_effect": "Save cost",
            "observation_version": "v1.0.0",
            "confidence": 1.01,
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(raw)

    def test_boundary_confidence_values_accepted(self) -> None:
        """Confidence values exactly 0.0 and 1.0 must be accepted."""
        for val in [0.0, 1.0]:
            with self.subTest(confidence=val):
                p = ActionProposal(
                    action=InfrastructureAction.SCALE_DOWN,
                    target_service_id="reports-worker",
                    reason="Boundary test",
                    expected_effect="Test effect",
                    observation_version="v1.0.0",
                    confidence=val,
                )
                self.assertEqual(p.confidence, val)

    def test_low_confidence_preserved_not_inflated(self) -> None:
        """
        Low confidence (e.g. 0.05) must parse faithfully without being artificially inflated.
        The production schema accepts 0.05, but downstream orchestrator/safety should flag it.
        """
        p = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Uncertain recommendation",
            expected_effect="Potential savings",
            observation_version="v1.0.0",
            confidence=0.05,
        )
        self.assertEqual(p.confidence, 0.05)


# ─────────────────────────────────────────────────────────────────────────────
# 8. LLM Failure Handling & Adapter Discovery
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMAdapterContract(unittest.TestCase):
    """
    Contract test: Inspect LLM adapter / client abstraction and verify that
    LLM failure modes (timeout, provider error, unparseable output) cannot become
    successful infrastructure proposals.
    """

    def test_llm_adapter_module_discovery(self) -> None:
        """
        PRODUCTION GAP:
        Member 1 owns the LLM client / adapter implementation.
        Verify whether an LLM adapter module exists in backend.agents.
        Fails explicitly if missing so the production gap is exposed.
        """
        adapter = get_llm_adapter()
        if adapter is None:
            self.fail(
                "Production Gap: LLM adapter interface not implemented in backend.agents. "
                "Candidate modules (backend.agents.llm, backend.agents.llm_adapter, backend.agents.client) "
                "do not exist. Member 1 must implement the LLM adapter."
            )

    def test_llm_timeout_cannot_produce_action(self) -> None:
        """Simulated LLM timeout exception cannot be converted into an ActionProposal."""
        timeout_payload = {"error": "TimeoutError: LLM provider timed out after 30s"}
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(timeout_payload)

    def test_llm_provider_error_cannot_produce_action(self) -> None:
        """Simulated LLM HTTP 500 / provider failure payload cannot produce an ActionProposal."""
        provider_error_payload = {
            "error": {
                "code": 500,
                "message": "Internal server error from upstream model provider",
            }
        }
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate(provider_error_payload)

    def test_llm_empty_response_cannot_produce_action(self) -> None:
        """Empty or blank model response cannot produce an ActionProposal."""
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({})


# ─────────────────────────────────────────────────────────────────────────────
# 9. Extra / Unknown Fields
# ─────────────────────────────────────────────────────────────────────────────

class TestExtraFieldsContract(unittest.TestCase):
    """
    Contract test: Inspect extra / unexpected fields behavior in production schemas.
    Pydantic v2 default allows extra fields (ignores them) unless extra='forbid' is configured.
    """

    def test_extra_fields_behavior_documented(self) -> None:
        """
        Document extra fields handling in ActionProposal:
        Passing unexpected fields like 'bypass_safety' or 'execute_immediately'
        must NOT become recognized attributes on the ActionProposal model.
        """
        raw = {
            "action": "scale_down",
            "target_service_id": "reports-worker",
            "reason": "Idle service",
            "expected_effect": "Save cost",
            "observation_version": "v1.0.0",
            "confidence": 0.9,
            "bypass_safety": True,
            "execute_immediately": True,
        }
        proposal = ActionProposal.model_validate(raw)
        # Extra fields are ignored by default in Pydantic v2 without extra='forbid'
        # Crucially, they must NOT attach as model fields or override behavior
        self.assertFalse(
            hasattr(proposal, "bypass_safety") and getattr(proposal, "bypass_safety") is True,
            "Extra field 'bypass_safety' must not be an active attribute on ActionProposal"
        )
        self.assertFalse(
            hasattr(proposal, "execute_immediately") and getattr(proposal, "execute_immediately") is True,
            "Extra field 'execute_immediately' must not be an active attribute on ActionProposal"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 10. Safety Handoff Contract
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyHandoffContract(unittest.TestCase):
    """
    Contract test: Protect against an architecture where agent output -> direct
    infrastructure execution without a Safety Engine stage.
    Verify that an ActionProposal is distinct from execution and requires SafetyCheckResult.
    """

    def test_proposal_distinct_from_execution_result(self) -> None:
        """An ActionProposal cannot be treated as an ExecutionResult."""
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Scale down idle service",
            expected_effect="Save cost",
            observation_version="v1.0.0",
            confidence=0.9,
        )
        self.assertNotIsInstance(proposal, ExecutionResult)

    def test_workflow_requires_safety_check_before_execution(self) -> None:
        """
        VerificationResult contract strictly requires both `decision` and `safety_check`.
        Direct execution without a safety check is rejected at the workflow schema level.
        """
        observation = ServiceObservation(
            service_id="reports-worker",
            cpu_utilization_percent=9.0,
            memory_utilization_percent=15.0,
            traffic_rpm=0,
            latency_ms=0.0,
            cost_per_hour=11.0,
            observation_timestamp=T_OBSERVATION,
            state_version="v1.0.0",
        )
        decision = DecisionResult(
            investigation=InvestigationResult(
                observation=observation,
                identified_issues=["idle"],
                summary="Idle service",
            ),
            proposal=ActionProposal(
                action=InfrastructureAction.SCALE_DOWN,
                target_service_id="reports-worker",
                reason="Scale down",
                expected_effect="Save cost",
                observation_version="v1.0.0",
                confidence=0.95,
            ),
        )

        # Attempting to construct VerificationResult without safety_check must fail
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
                verification_notes="Invalid bypass",
            )

    def test_agent_runner_handoff_discovery(self) -> None:
        """
        PRODUCTION GAP:
        Member 1 owns the agent runner / decision module that hands proposals to the safety engine.
        Verify whether an agent module exists in backend.agents.
        Fails explicitly if missing so the production gap is exposed.
        """
        agent_mod = get_agent_module()
        if agent_mod is None:
            self.fail(
                "Production Gap: Agent runner / decision module not implemented in backend.agents. "
                "Candidate modules (backend.agents.decision, backend.agents.decision_agent, "
                "backend.agents.investigation) do not exist. Member 1 must implement the agent classes."
            )


# ─────────────────────────────────────────────────────────────────────────────
# 11. Agent Output Must Not Claim Execution Success
# ─────────────────────────────────────────────────────────────────────────────

class TestProposalDoesNotClaimExecution(unittest.TestCase):
    """
    Contract test: An ActionProposal produces a decision/proposal only.
    It must NOT itself claim or fabricate that infrastructure execution has succeeded.
    """

    def test_action_proposal_has_no_execution_status(self) -> None:
        """ActionProposal must NOT have a 'status' attribute indicating execution state."""
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Idle worker",
            expected_effect="Cost reduction",
            observation_version="v1.0.0",
            confidence=0.9,
        )
        self.assertFalse(hasattr(proposal, "status"), "ActionProposal must not have 'status' attribute")
        self.assertNotIn("status", ActionProposal.model_fields.keys())

    def test_action_proposal_has_no_new_state_version(self) -> None:
        """
        'new_state_version' belongs exclusively to ExecutionResult (produced by Simulator/API).
        An ActionProposal only references 'observation_version' (input state), not resulting state.
        """
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_UP,
            target_service_id="orders-api",
            reason="High traffic",
            expected_effect="Restore headroom",
            observation_version="v1.0.0",
            confidence=0.9,
        )
        self.assertFalse(hasattr(proposal, "new_state_version"))
        self.assertNotIn("new_state_version", ActionProposal.model_fields.keys())

    def test_action_proposal_docstring_truthfulness(self) -> None:
        """ActionProposal docstring must explicitly confirm it is NOT an executed action."""
        doc = ActionProposal.__doc__ or ""
        self.assertIn(
            "NOT an executed action",
            doc,
            "ActionProposal docstring must state it is NOT an executed action"
        )

    def test_proposal_cannot_be_equated_with_execution_success(self) -> None:
        """
        ExecutionResult requires ExecutionStatus.SUCCESS to represent actual execution.
        An ActionProposal cannot satisfy a check for execution status.
        """
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Idle worker",
            expected_effect="Cost reduction",
            observation_version="v1.0.0",
            confidence=0.9,
        )

        def verify_execution(result: ExecutionResult) -> bool:
            return result.status == ExecutionStatus.SUCCESS

        with self.assertRaises(Exception):
            verify_execution(proposal)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
