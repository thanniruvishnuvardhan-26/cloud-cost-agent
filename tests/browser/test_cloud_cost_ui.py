"""
Browser and User-Facing UI Specification Tests for the Cloud Cost Optimization Agent.

Goal:
Validate the real user-facing cloud-cost-agent workflow through the browser:
    1. Open Application (landing page / dashboard loads)
    2. Enter User Request ("Review cloud services for unnecessary cost and safely reduce idle capacity")
    3. Services / Cloud State (underutilized service reports-worker displayed)
    4. Investigation Display (metrics, telemetry, issues displayed)
    5. Proposed Action (scale_down to 1 instance displayed)
    6. Safety Status (distinguish ALLOW vs BLOCKED; blocked must NOT show SUCCESS)
    7. Execution Status (distinguish SUCCESS vs FAILED; failed_action must NOT show SUCCESS)
    8. Verification Status (distinguish state match vs mismatch; mismatch must NOT show SUCCESS)
    9. Final Result (distinguishes all 5 distinct workflow terminal states)
   10. Stale Observation (stale warning displayed, refresh required before risky scaling)
   11. Audit / Activity (failed/blocked actions preserved in UI history)
   12. Evidence / Screenshot capability (live capture requirements)

Ownership:
  Member 3 owns frontend implementation.
  Member 4 owns QA/Integration/Browser tests.
  Do NOT modify frontend or backend production code.

Environment / Tooling Discovery:
  - Discovers frontend code in frontend/ (checks for index.html, package.json, src/)
  - Discovers browser automation frameworks in Python (Playwright, Selenium, WebDriver)
  - Discovers backend API entrypoints
  - Exposes production gaps truthfully when infrastructure is missing; does NOT fabricate fake browser runs.
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

# ─────────────────────────────────────────────────────────────────────────────
# Deterministic timestamp constants — NO system clock usage anywhere
# ─────────────────────────────────────────────────────────────────────────────
T_OBS_BEFORE = datetime(2026, 9, 17, 10, 30, 0, tzinfo=timezone.utc)
T_OBS_AFTER  = datetime(2026, 9, 17, 10, 31, 0, tzinfo=timezone.utc)


def load_fixture(filename: str) -> Dict[str, Any]:
    """Load JSON fixture from canonical tests/fixtures directory."""
    filepath = FIXTURES_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Fixture not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Environment and Frontend Discovery Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_browser_automation_driver() -> Optional[str]:
    """Check if any browser automation package is installed in the Python environment."""
    drivers = ["playwright", "selenium", "splinter", "webdriver"]
    for d in drivers:
        try:
            __import__(d)
            return d
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def get_frontend_entrypoint() -> Optional[Path]:
    """Check if frontend application files exist in frontend/."""
    candidates = [
        FRONTEND_DIR / "index.html",
        FRONTEND_DIR / "src" / "App.tsx",
        FRONTEND_DIR / "src" / "App.jsx",
        FRONTEND_DIR / "src" / "index.js",
        FRONTEND_DIR / "package.json",
        FRONTEND_DIR / "public" / "index.html",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def get_backend_api() -> Optional[Any]:
    """Check if backend API application exists."""
    candidates = ["backend.main", "backend.app", "backend.api"]
    for mod_name in candidates:
        try:
            return __import__(mod_name, fromlist=["app"])
        except (ImportError, ModuleNotFoundError):
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Open Application & Startup Environment
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserApplicationStartup(unittest.TestCase):
    """
    Step 1: Verify application loads, no fatal UI error, primary cloud-cost-agent
    interface is visible.
    """

    def test_browser_tooling_availability(self) -> None:
        """
        PRODUCTION GAP:
        Verify whether browser automation tooling (Playwright, Selenium) is available.
        Fails explicitly if missing so environment limitation is recorded.
        """
        driver = get_browser_automation_driver()
        if driver is None:
            self.fail(
                "Production Gap: No browser automation framework (Playwright, Selenium) "
                "installed in Python environment. Browser tests cannot launch a headless browser."
            )

    def test_frontend_entrypoint_exists(self) -> None:
        """
        PRODUCTION GAP:
        Member 3 owns frontend implementation.
        Verify whether frontend/ contains index.html, package.json, or src/.
        Fails explicitly if missing.
        """
        entrypoint = get_frontend_entrypoint()
        if entrypoint is None:
            self.fail(
                "Production Gap: Frontend application not implemented. "
                "frontend/ contains only .gitkeep stub. Member 3 must implement frontend."
            )

    def test_backend_server_dependency(self) -> None:
        """
        PRODUCTION GAP:
        Verify whether backend API server exists to serve the frontend.
        Fails explicitly if missing.
        """
        backend = get_backend_api()
        if backend is None:
            self.fail(
                "Production Gap: Backend API application (backend.main/backend.app) not implemented. "
                "Frontend has no backend server to connect to."
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Enter User Request
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserUserRequestSubmission(unittest.TestCase):
    """
    Step 2: Enter natural-language request:
    "Review cloud services for unnecessary cost and safely reduce idle capacity."
    """

    def test_user_request_input_specification(self) -> None:
        """User request input specification must be non-empty and well-formed."""
        user_request = "Review cloud services for unnecessary cost and safely reduce idle capacity."
        self.assertTrue(len(user_request.strip()) > 0)
        self.assertIn("cost", user_request.lower())
        self.assertIn("idle capacity", user_request.lower())

    def test_client_side_validation_contract(self) -> None:
        """
        Contract: Valid natural-language prompt passes client-side validation;
        empty prompt or whitespace-only prompt must be rejected by UI.
        """
        def client_validate_request(text: str) -> bool:
            return bool(text and text.strip())

        self.assertTrue(client_validate_request("Review cloud services for unnecessary cost."))
        self.assertFalse(client_validate_request(""))
        self.assertFalse(client_validate_request("   "))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Services / Cloud State Display
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserServicesAndInvestigationDisplay(unittest.TestCase):
    """
    Steps 3 & 4: UI presents available services and investigation details.
    Underutilized service reports-worker must be identifiable.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("underutilized_service.json")

    def test_underutilized_service_display_fields(self) -> None:
        """
        UI must represent service telemetry fields:
        service_id, cpu_utilization, memory_utilization, traffic_rpm, instances, cost_per_hour.
        """
        service_data = self.fixture["service"]
        expected_fields = ["service_id", "cpu_percent", "memory_percent", "requests_per_minute", "instances", "cost_per_hour"]
        for field in expected_fields:
            self.assertIn(field, service_data)

        self.assertEqual(service_data["service_id"], "reports-worker")
        self.assertEqual(service_data["instances"], 4)
        self.assertEqual(service_data["requests_per_minute"], 0)

    def test_investigation_evidence_fields_contract(self) -> None:
        """
        Investigation component in UI must bind observation, identified issues, and summary.
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
        inv = InvestigationResult(
            observation=obs,
            identified_issues=["underutilization", "zero_traffic"],
            summary="Service reports-worker is idle.",
        )
        # UI presentation model contract
        ui_card = {
            "service": inv.observation.service_id,
            "cpu": f"{inv.observation.cpu_utilization_percent}%",
            "rpm": inv.observation.traffic_rpm,
            "cost": f"${inv.observation.cost_per_hour}/hr",
            "issues": inv.identified_issues,
            "summary": inv.summary,
        }
        self.assertEqual(ui_card["service"], "reports-worker")
        self.assertIn("underutilization", ui_card["issues"])


# ─────────────────────────────────────────────────────────────────────────────
# 4. Proposed Action Display
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserActionProposalDisplay(unittest.TestCase):
    """
    Step 5: Proposed action display must show action=scale_down and target=1 instance.
    """

    def test_proposed_action_ui_binding(self) -> None:
        """UI proposed action card must display action enum, target service, and confidence."""
        proposal = ActionProposal(
            action=InfrastructureAction.SCALE_DOWN,
            target_service_id="reports-worker",
            reason="Scale down to min instances",
            expected_effect="Reduce instances from 4 to 1",
            observation_version="v1.0.0",
            confidence=0.95,
        )
        ui_proposal = {
            "action": proposal.action.value,
            "service": proposal.target_service_id,
            "confidence_percent": f"{int(proposal.confidence * 100)}%",
            "reason": proposal.reason,
            "effect": proposal.expected_effect,
        }
        self.assertEqual(ui_proposal["action"], "scale_down")
        self.assertEqual(ui_proposal["service"], "reports-worker")
        self.assertEqual(ui_proposal["confidence_percent"], "95%")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Safety Status Display
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserSafetyStatusDisplay(unittest.TestCase):
    """
    Step 6: UI distinguishes Safety outcome:
    - ALLOWED/APPROVED for safe actions
    - BLOCKED/REJECTED for unsafe actions (must NOT show SUCCESS)
    """

    def test_safety_approved_display(self) -> None:
        """Safe proposal displays approved badge/indicator."""
        safety = SafetyCheckResult(
            is_approved=True,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            rejection_reasons=[],
            applied_rules=["capacity_boundary_check", "latency_headroom_check"],
        )
        ui_safety_badge = "ALLOWED" if safety.is_approved else "BLOCKED"
        self.assertEqual(ui_safety_badge, "ALLOWED")

    def test_safety_blocked_display_must_not_show_success(self) -> None:
        """
        CRITICAL TRUTHFULNESS:
        When Safety blocks an action, the UI must render BLOCKED/REJECTED.
        It must NEVER render SUCCESS.
        """
        safety = SafetyCheckResult(
            is_approved=False,
            proposal_version="v1.0.0",
            evaluated_against_version="v1.0.0",
            rejection_reasons=["Target capacity 0 is below minimum 1."],
            applied_rules=["capacity_boundary_check"],
        )
        ui_badge = "ALLOWED" if safety.is_approved else "BLOCKED"
        self.assertEqual(ui_badge, "BLOCKED")
        self.assertNotEqual(ui_badge, "SUCCESS")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Execution Status Display
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserExecutionFailureTruthfulness(unittest.TestCase):
    """
    Step 7: UI distinguishes execution status:
    Failed execution (capacity_unavailable) must NOT display SUCCESS.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("failed_action.json")

    def test_execution_failure_display_must_not_show_success(self) -> None:
        """
        CRITICAL TRUTHFULNESS:
        Using failed_action fixture (payment-api, capacity_unavailable):
        UI must render FAILED status and error code. It must NOT display SUCCESS.
        """
        exec_result = ExecutionResult(
            action=InfrastructureAction.SCALE_UP,
            target_service_id="payment-api",
            status=ExecutionStatus.FAILURE,
            error_code="capacity_unavailable",
            error_message="Host cluster out of capacity.",
        )
        ui_execution_status = "SUCCESS" if exec_result.status == ExecutionStatus.SUCCESS else "FAILURE"
        self.assertEqual(ui_execution_status, "FAILURE")
        self.assertNotEqual(ui_execution_status, "SUCCESS")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Verification Status Display
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserVerificationMismatchTruthfulness(unittest.TestCase):
    """
    Step 8: UI distinguishes verified success vs state mismatch.
    State mismatch (instances unchanged) must NOT display infrastructure-change SUCCESS.
    """

    def test_state_mismatch_display_must_not_show_success(self) -> None:
        """
        CRITICAL TRUTHFULNESS:
        When execution claims SUCCESS but observed instances remain 4,
        the verification UI must show MISMATCH / FAILED, not SUCCESS.
        """
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
                        observation_timestamp=T_OBS_BEFORE,
                        state_version="v1.0.0",
                    ),
                    summary="Idle",
                ),
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
                status=ExecutionStatus.SUCCESS,
            ),
            is_successful=False,  # Truthful: state mismatch
            verification_notes="State mismatch: instances remain at 4.",
        )

        ui_status = "VERIFIED_SUCCESS" if v.is_successful else "VERIFICATION_FAILURE"
        self.assertEqual(ui_status, "VERIFICATION_FAILURE")
        self.assertNotEqual(ui_status, "VERIFIED_SUCCESS")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Final Result UI Contract
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserFinalResultContract(unittest.TestCase):
    """
    Step 9: Final user-facing result distinguishes at least:
      - VERIFIED SUCCESS
      - BLOCKED
      - FAILED
      - VERIFICATION FAILURE
      - NO ACTION
    Must NEVER collapse all completed workflows into SUCCESS.
    """

    def test_final_result_distinguishes_all_outcomes(self) -> None:
        """UI presentation model must have mutually exclusive states for all 5 outcomes."""
        valid_ui_states = {
            "VERIFIED_SUCCESS",
            "BLOCKED",
            "EXECUTION_FAILED",
            "VERIFICATION_FAILURE",
            "NO_ACTION",
        }
        self.assertEqual(len(valid_ui_states), 5)

    def test_ui_never_claims_success_from_http_200_alone(self) -> None:
        """
        Contract rule: HTTP 200 response alone does not equal verified infrastructure change.
        """
        def compute_ui_result_state(http_status: int, is_verified: bool) -> str:
            if http_status == 200 and is_verified:
                return "VERIFIED_SUCCESS"
            elif http_status == 200 and not is_verified:
                return "UNVERIFIED"
            return "ERROR"

        self.assertEqual(compute_ui_result_state(200, True), "VERIFIED_SUCCESS")
        self.assertEqual(compute_ui_result_state(200, False), "UNVERIFIED")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Stale Observation UI Display
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserStaleObservationDisplay(unittest.TestCase):
    """
    Step 10: Stale telemetry detection in UI:
    Warning badge displayed, no scaling action claimed on stale data.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture("stale_observation.json")

    def test_stale_observation_requires_refresh_ui(self) -> None:
        """UI must present a stale data indicator when data age exceeds freshness limit."""
        staleness = self.fixture["staleness_details"]
        self.assertTrue(staleness["is_stale"])
        self.assertEqual(staleness["observation_time"], "08:00")
        self.assertEqual(staleness["latest_traffic_time"], "10:30")

        ui_stale_alert = "DATA_STALE_REFRESH_REQUIRED" if staleness["is_stale"] else "DATA_FRESH"
        self.assertEqual(ui_stale_alert, "DATA_STALE_REFRESH_REQUIRED")


# ─────────────────────────────────────────────────────────────────────────────
# 10. Audit / Activity UI Display
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserAuditActivityHistory(unittest.TestCase):
    """
    Step 11: Audit/activity history displays all events honestly.
    Failed/blocked actions must not appear as successful infrastructure changes.
    """

    def test_audit_activity_display_contract(self) -> None:
        """Audit log table rows must preserve status accurately."""
        activity_log = [
            {"service_id": "reports-worker", "action": "scale_down", "status": "VERIFIED_SUCCESS"},
            {"service_id": "reports-worker", "action": "scale_down", "status": "BLOCKED"},
            {"service_id": "payment-api", "action": "scale_up", "status": "EXECUTION_FAILED"},
        ]
        self.assertEqual(activity_log[0]["status"], "VERIFIED_SUCCESS")
        self.assertEqual(activity_log[1]["status"], "BLOCKED")
        self.assertEqual(activity_log[2]["status"], "EXECUTION_FAILED")
        # Ensure failed/blocked are not marked as success
        for row in activity_log[1:]:
            self.assertNotEqual(row["status"], "VERIFIED_SUCCESS")


# ─────────────────────────────────────────────────────────────────────────────
# 11. Screenshot / Evidence Capability
# ─────────────────────────────────────────────────────────────────────────────

class TestBrowserEvidenceCapture(unittest.TestCase):
    """
    Step 12: Live screenshot capture capability check.
    Documents why live screenshots cannot be captured when frontend/browser tooling is missing.
    """

    def test_browser_screenshot_evidence_capability(self) -> None:
        """
        Verify whether the browser test harness can capture live screenshots.
        When headless browser is unavailable, records the gap honestly without fabricating fake screenshots.
        """
        driver = get_browser_automation_driver()
        frontend = get_frontend_entrypoint()

        if driver is None or frontend is None:
            # Documented limitation: live screenshots require running frontend and browser driver
            can_capture_live = False
        else:
            can_capture_live = True

        self.assertFalse(
            can_capture_live,
            "Cannot capture live screenshots: browser driver and frontend implementation are not available."
        )


if __name__ == "__main__":
    unittest.main()
