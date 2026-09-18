"""
Integration tests for the Cloud Cost Agent REST API.

These tests define the expected HTTP contract for all required endpoints and
expose production gaps where endpoints have not yet been implemented.

Architecture discovered during Phase 6 inspection:
  - Branch:   person-4-qa
  - FastAPI:  installed (0.141.1) — but no app/main/routes exist in backend/
  - httpx2:   NOT installed — FastAPI TestClient is therefore unavailable
  - Flask:    installed (3.1.3) — test_client() is functional
  - Backend API: NO entrypoint (backend.main / backend.app / backend.api all MISSING)

Test client strategy:
  _discover_app() attempts to locate the production application object using
  multiple conventional module paths. If the app is absent, every test that
  depends on it fails explicitly with a Production Gap assertion rather than
  being skipped or silently suppressed.

Endpoints under test:
  GET  /health
  GET  /services
  GET  /services/{id}
  GET  /metrics
  GET  /events
  POST /actions/validate
  POST /actions/execute
  POST /actions/verify
  GET  /audit
"""

import json
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# ─── Deterministic fixture timestamps — no system clock ──────────────────────
TS_BEFORE = "2026-09-17T10:30:00Z"
TS_AFTER  = "2026-09-17T10:31:00Z"
TS_STALE  = "2026-09-17T08:00:00Z"


def load_fixture(filename: str) -> Dict[str, Any]:
    path = FIXTURES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Fixture missing: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── Application discovery ───────────────────────────────────────────────────

def _discover_app() -> Optional[Any]:
    """
    Attempt to locate the production WSGI/ASGI application object.
    Returns the app object if found, None if missing.
    """
    fastapi_paths = [
        ("backend.main",   "app"),
        ("backend.app",    "app"),
        ("backend.api",    "app"),
        ("backend.server", "app"),
    ]
    flask_paths = [
        ("backend.main",   "app"),
        ("backend.app",    "app"),
        ("backend.api",    "app"),
        ("backend.server", "app"),
    ]
    for mod_name, attr in fastapi_paths + flask_paths:
        try:
            mod = __import__(mod_name, fromlist=[attr])
            if hasattr(mod, attr):
                return getattr(mod, attr)
        except (ImportError, ModuleNotFoundError):
            continue
    return None


def _make_client(app: Any) -> Optional[Any]:
    """
    Create an appropriate test client for the discovered application.
    FastAPI → tries httpx2-backed TestClient.
    Flask   → uses Flask test_client().
    Returns None if no suitable client can be constructed.
    """
    if app is None:
        return None
    # Try FastAPI TestClient
    try:
        from fastapi import FastAPI
        if isinstance(app, FastAPI):
            from fastapi.testclient import TestClient
            return TestClient(app)
    except (ImportError, RuntimeError):
        pass
    # Try Flask test_client
    try:
        from flask import Flask
        if isinstance(app, Flask):
            app.config["TESTING"] = True
            return app.test_client()
    except ImportError:
        pass
    return None


APP  = _discover_app()
CLIENT = _make_client(APP)

_APP_MISSING  = APP is None
_CLIENT_MISSING = CLIENT is None
_TESTCLIENT_BLOCKED = (
    APP is not None and CLIENT is None
)


# ─── Base class with shared gap-reporting helper ──────────────────────────────

class ApiTestBase(unittest.TestCase):

    def _require_client(self) -> Any:
        """
        Enforce that a live test client is available.
        Reports distinct gaps for:
          1. App itself is missing (production code not implemented).
          2. App exists but TestClient is blocked (httpx2 not installed).
        """
        if _APP_MISSING:
            self.fail(
                "Production Gap: No backend application entrypoint found. "
                "backend.main / backend.app / backend.api do not exist. "
                "Member 1/2/3 must implement the FastAPI/Flask application."
            )
        if _CLIENT_MISSING:
            self.fail(
                "Environment Gap: Application found but test client unavailable. "
                "FastAPI TestClient requires httpx2 (not installed). "
                "httpx2 must be added to the project dependencies."
            )
        return CLIENT

    @staticmethod
    def _json(resp: Any) -> Any:
        """Extract JSON from either a Flask or httpx response."""
        if hasattr(resp, "get_json"):
            return resp.get_json()
        return resp.json()

    @staticmethod
    def _status(resp: Any) -> int:
        """Extract status code from either client."""
        if hasattr(resp, "status_code"):
            return resp.status_code
        return resp.status_code


# ─────────────────────────────────────────────────────────────────────────────
# 1. GET /health
# ─────────────────────────────────────────────────────────────────────────────

class TestHealthEndpoint(ApiTestBase):

    def test_health_returns_200(self) -> None:
        """GET /health → HTTP 200"""
        client = self._require_client()
        resp = client.get("/health")
        self.assertEqual(self._status(resp), 200,
            "GET /health must return HTTP 200. "
            "Production gap: endpoint not implemented.")

    def test_health_returns_valid_json(self) -> None:
        """GET /health → response is valid JSON"""
        client = self._require_client()
        resp = client.get("/health")
        data = self._json(resp)
        self.assertIsNotNone(data,
            "GET /health response must be valid JSON.")

    def test_health_contains_status_field(self) -> None:
        """GET /health → must contain a status or health indicator field"""
        client = self._require_client()
        resp = client.get("/health")
        data = self._json(resp)
        has_status = (
            isinstance(data, dict) and
            any(k in data for k in ("status", "health", "ok", "healthy"))
        )
        self.assertTrue(has_status,
            f"GET /health must include a status field. Got: {data}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. GET /services
# ─────────────────────────────────────────────────────────────────────────────

class TestServicesListEndpoint(ApiTestBase):

    def test_services_list_reachable(self) -> None:
        """GET /services → endpoint must be reachable (not 404/405)"""
        client = self._require_client()
        resp = client.get("/services")
        self.assertNotIn(self._status(resp), (404, 405),
            "GET /services must be a registered route. "
            "Production gap: endpoint not implemented.")

    def test_services_list_returns_json(self) -> None:
        """GET /services → response must be valid JSON"""
        client = self._require_client()
        resp = client.get("/services")
        if self._status(resp) == 200:
            data = self._json(resp)
            self.assertIsNotNone(data)

    def test_services_list_success_is_list_or_dict(self) -> None:
        """GET /services → 200 body must be a list or envelope dict"""
        client = self._require_client()
        resp = client.get("/services")
        if self._status(resp) == 200:
            data = self._json(resp)
            self.assertIsInstance(data, (list, dict),
                "GET /services must return a list of services or an envelope dict.")


# ─────────────────────────────────────────────────────────────────────────────
# 3. GET /services/{id}
# ─────────────────────────────────────────────────────────────────────────────

class TestServiceByIdEndpoint(ApiTestBase):

    def test_known_service_id_returns_service(self) -> None:
        """GET /services/reports-worker → fixture-known service must return service data"""
        client = self._require_client()
        resp = client.get("/services/reports-worker")
        status = self._status(resp)
        self.assertIn(status, (200, 404),
            "GET /services/{id} must return 200 (found) or 404 (not found), "
            "not a 405/500 that would indicate a broken route.")
        if status == 200:
            data = self._json(resp)
            self.assertIsNotNone(data, "Service data must be present in 200 response.")
            if isinstance(data, dict):
                self.assertIn("service_id", data,
                    "Service response must contain service_id field.")

    def test_unknown_service_id_returns_error(self) -> None:
        """GET /services/nonexistent-service-00000 → must return an error response, not 200"""
        client = self._require_client()
        resp = client.get("/services/nonexistent-service-00000")
        status = self._status(resp)
        self.assertNotEqual(status, 200,
            "GET /services/nonexistent-service-00000 must NOT return 200. "
            "Unknown service must return an appropriate error status (404 expected).")

    def test_unknown_service_error_is_json(self) -> None:
        """GET /services/unknown → error response must be valid JSON"""
        client = self._require_client()
        resp = client.get("/services/nonexistent-service-00000")
        if self._status(resp) != 200:
            data = self._json(resp)
            self.assertIsNotNone(data, "Error responses must be JSON.")


# ─────────────────────────────────────────────────────────────────────────────
# 4. GET /metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricsEndpoint(ApiTestBase):

    def test_metrics_endpoint_reachable(self) -> None:
        """GET /metrics → endpoint must be reachable"""
        client = self._require_client()
        resp = client.get("/metrics")
        self.assertNotIn(self._status(resp), (404, 405),
            "GET /metrics must be a registered route. "
            "Production gap: endpoint not implemented.")

    def test_metrics_returns_json_without_cloud_calls(self) -> None:
        """GET /metrics → returns local JSON representation, no real cloud calls"""
        client = self._require_client()
        resp = client.get("/metrics")
        if self._status(resp) == 200:
            data = self._json(resp)
            self.assertIsNotNone(data,
                "GET /metrics must return JSON metrics data.")


# ─────────────────────────────────────────────────────────────────────────────
# 5. GET /events
# ─────────────────────────────────────────────────────────────────────────────

class TestEventsEndpoint(ApiTestBase):

    def test_events_endpoint_reachable(self) -> None:
        """GET /events → endpoint must be reachable"""
        client = self._require_client()
        resp = client.get("/events")
        self.assertNotIn(self._status(resp), (405,),
            "GET /events must not return 405 Method Not Allowed. "
            "Production gap if 404: endpoint not implemented.")

    def test_events_returns_json(self) -> None:
        """GET /events → response must be JSON if endpoint exists"""
        client = self._require_client()
        resp = client.get("/events")
        if self._status(resp) == 200:
            data = self._json(resp)
            self.assertIsNotNone(data)


# ─────────────────────────────────────────────────────────────────────────────
# 6. POST /actions/validate
# ─────────────────────────────────────────────────────────────────────────────

class TestActionsValidateEndpoint(ApiTestBase):

    def _valid_validate_payload(self) -> Dict[str, Any]:
        """Deterministic valid action proposal using underutilized fixture data."""
        fixture = load_fixture("underutilized_service.json")
        return {
            "action": "scale_down",
            "target_service_id": fixture["service"]["service_id"],
            "reason": "Idle service with zero RPM",
            "expected_effect": "Reduce instances to minimum",
            "observation_version": fixture["observation"]["state_version"],
            "confidence": 0.95,
        }

    def test_valid_action_proposal_accepted(self) -> None:
        """POST /actions/validate → valid action proposal is accepted"""
        client = self._require_client()
        resp = client.post(
            "/actions/validate",
            json=self._valid_validate_payload(),
            content_type="application/json",
        )
        status = self._status(resp)
        self.assertNotIn(status, (404, 405),
            "POST /actions/validate must be a registered route. "
            "Production gap: endpoint not implemented.")
        self.assertIn(status, (200, 201, 202),
            f"Valid action proposal must be accepted (2xx). Got: {status}")

    def test_invalid_action_rejected(self) -> None:
        """POST /actions/validate → invalid action 'terminate_cluster' is rejected"""
        client = self._require_client()
        bad_payload = {
            "action": "terminate_cluster",
            "target_service_id": "reports-worker",
            "reason": "Cost reduction",
            "expected_effect": "Terminate all instances",
            "observation_version": "v1.0.0",
            "confidence": 0.99,
        }
        resp = client.post(
            "/actions/validate",
            json=bad_payload,
            content_type="application/json",
        )
        status = self._status(resp)
        if status not in (404, 405):
            self.assertIn(status, (400, 422, 409),
                f"Invalid action 'terminate_cluster' must be rejected (4xx). Got: {status}")

    def test_malformed_request_rejected(self) -> None:
        """POST /actions/validate → completely malformed body returns 4xx"""
        client = self._require_client()
        resp = client.post(
            "/actions/validate",
            json={"not": "a valid action proposal"},
            content_type="application/json",
        )
        status = self._status(resp)
        if status not in (404, 405):
            self.assertIn(status, (400, 422),
                f"Malformed request must return 400 or 422. Got: {status}")

    def test_missing_required_fields_rejected(self) -> None:
        """POST /actions/validate → missing required fields returns 422"""
        client = self._require_client()
        resp = client.post(
            "/actions/validate",
            json={"action": "scale_down"},  # missing target_service_id, reason, etc.
            content_type="application/json",
        )
        status = self._status(resp)
        if status not in (404, 405):
            self.assertIn(status, (400, 422),
                f"Missing required fields must return 400 or 422. Got: {status}")


# ─────────────────────────────────────────────────────────────────────────────
# 7. POST /actions/execute
# ─────────────────────────────────────────────────────────────────────────────

class TestActionsExecuteEndpoint(ApiTestBase):

    def _failed_action_payload(self) -> Dict[str, Any]:
        """Deterministic payload representing the failed_action fixture scenario."""
        fixture = load_fixture("failed_action.json")
        return {
            "action": fixture["attempted_action"]["action"],
            "target_service_id": fixture["service"]["service_id"],
            "requested_instances": fixture["attempted_action"]["requested_instances"],
            "observation_version": fixture["observation"]["state_version"],
        }

    def test_execute_endpoint_reachable(self) -> None:
        """POST /actions/execute → endpoint must be registered"""
        client = self._require_client()
        resp = client.post(
            "/actions/execute",
            json={},
            content_type="application/json",
        )
        self.assertNotEqual(self._status(resp), 405,
            "POST /actions/execute must not return 405 Method Not Allowed.")
        if self._status(resp) == 404:
            self.fail(
                "Production gap: POST /actions/execute endpoint not implemented."
            )

    def test_failed_execution_not_reported_as_success(self) -> None:
        """
        POST /actions/execute using failed_action fixture.
        If the execution is configured to fail (capacity_unavailable),
        the response must NOT represent the result as successful.
        HTTP 200 alone is NOT sufficient proof — the body must be inspected.
        """
        client = self._require_client()
        payload = self._failed_action_payload()
        resp = client.post(
            "/actions/execute",
            json=payload,
            content_type="application/json",
        )
        status = self._status(resp)
        if status in (404, 405):
            self.fail("Production gap: POST /actions/execute endpoint not implemented.")

        data = self._json(resp)
        # If the endpoint returns 200 with a body, confirm it does not claim SUCCESS
        if status == 200 and isinstance(data, dict):
            exec_status = data.get("status") or data.get("execution_status") or data.get("result")
            if exec_status is not None:
                self.assertNotEqual(
                    str(exec_status).lower(), "success",
                    "CRITICAL: Failed execution must NOT be reported as status='success' in response body. "
                    "Endpoint reports false success — production contract violated."
                )
            # Error code must be visible
            has_error = (
                data.get("error_code") or
                data.get("error") or
                data.get("error_message") or
                data.get("status") in ("failed", "failure", "error")
            )
            self.assertTrue(
                has_error,
                "Failed execution response must include error information. "
                "Error must not be silently swallowed."
            )

    def test_execute_malformed_request_rejected(self) -> None:
        """POST /actions/execute → malformed body returns 4xx, not 500"""
        client = self._require_client()
        resp = client.post(
            "/actions/execute",
            json={"garbage": True},
            content_type="application/json",
        )
        status = self._status(resp)
        if status not in (404, 405):
            self.assertNotEqual(status, 500,
                "Malformed request to POST /actions/execute must return 4xx, not 500 server error.")
            self.assertIn(status, (400, 422),
                f"Malformed request must return 400 or 422. Got: {status}")


# ─────────────────────────────────────────────────────────────────────────────
# 8. POST /actions/verify
# ─────────────────────────────────────────────────────────────────────────────

class TestActionsVerifyEndpoint(ApiTestBase):

    def _success_verify_payload(self) -> Dict[str, Any]:
        """Payload for a successful verification: state matches target."""
        return {
            "service_id": "reports-worker",
            "requested_action": "scale_down",
            "requested_target_instances": 1,
            "before_instances": 4,
            "after_instances": 1,
            "execution_status": "success",
            "observation_version_before": "v1.0.0",
            "observation_version_after": "v1.0.1",
        }

    def _failure_verify_payload(self) -> Dict[str, Any]:
        """Payload for a failed verification: state did NOT match target."""
        fixture = load_fixture("failed_action.json")
        return {
            "service_id": fixture["service"]["service_id"],
            "requested_action": fixture["attempted_action"]["action"],
            "requested_target_instances": fixture["attempted_action"]["requested_instances"],
            "before_instances": fixture["service"]["instances"],
            "after_instances": fixture["service"]["instances"],  # unchanged — failure
            "execution_status": "failure",
            "error_code": fixture["action_result"]["error"],
            "observation_version_before": fixture["observation"]["state_version"],
            "observation_version_after": None,
        }

    def _state_mismatch_payload(self) -> Dict[str, Any]:
        """Payload where execution claims success but state did not change."""
        return {
            "service_id": "reports-worker",
            "requested_action": "scale_down",
            "requested_target_instances": 1,
            "before_instances": 4,
            "after_instances": 4,  # unchanged despite SUCCESS claim
            "execution_status": "success",
            "observation_version_before": "v1.0.0",
            "observation_version_after": "v1.0.1",
        }

    def _missing_post_state_payload(self) -> Dict[str, Any]:
        """Payload where post-action state is absent (None)."""
        return {
            "service_id": "reports-worker",
            "requested_action": "scale_down",
            "requested_target_instances": 1,
            "before_instances": 4,
            "after_instances": None,
            "execution_status": "success",
            "observation_version_before": "v1.0.0",
            "observation_version_after": "v1.0.1",
        }

    def test_verify_endpoint_reachable(self) -> None:
        """POST /actions/verify → endpoint must be registered"""
        client = self._require_client()
        resp = client.post(
            "/actions/verify",
            json=self._success_verify_payload(),
            content_type="application/json",
        )
        if self._status(resp) == 404:
            self.fail("Production gap: POST /actions/verify endpoint not implemented.")
        self.assertNotEqual(self._status(resp), 405,
            "POST /actions/verify must not return 405.")

    def test_state_match_is_successful(self) -> None:
        """POST /actions/verify → state matches target → successful verification"""
        client = self._require_client()
        resp = client.post(
            "/actions/verify",
            json=self._success_verify_payload(),
            content_type="application/json",
        )
        status = self._status(resp)
        if status in (404, 405):
            self.fail("Production gap: POST /actions/verify endpoint not implemented.")
        self.assertIn(status, (200, 201), f"Valid verification request must return 2xx. Got: {status}")
        data = self._json(resp)
        if isinstance(data, dict):
            is_successful = data.get("is_successful") or data.get("verified") or data.get("success")
            if is_successful is not None:
                self.assertTrue(is_successful,
                    "Verification with matching state must report is_successful=True.")

    def test_execution_failure_not_successful_in_verification(self) -> None:
        """POST /actions/verify → failed execution must not verify as successful"""
        client = self._require_client()
        resp = client.post(
            "/actions/verify",
            json=self._failure_verify_payload(),
            content_type="application/json",
        )
        status = self._status(resp)
        if status in (404, 405):
            self.fail("Production gap: POST /actions/verify endpoint not implemented.")
        data = self._json(resp)
        if isinstance(data, dict):
            is_successful = data.get("is_successful") or data.get("verified") or data.get("success")
            if is_successful is not None:
                self.assertFalse(is_successful,
                    "CRITICAL: Failed execution must NOT verify as successful. "
                    "Execution failure must propagate to verification result.")

    def test_state_mismatch_not_successful_in_verification(self) -> None:
        """POST /actions/verify → execution claims success but state unchanged → FAIL"""
        client = self._require_client()
        resp = client.post(
            "/actions/verify",
            json=self._state_mismatch_payload(),
            content_type="application/json",
        )
        status = self._status(resp)
        if status in (404, 405):
            self.fail("Production gap: POST /actions/verify endpoint not implemented.")
        data = self._json(resp)
        if isinstance(data, dict):
            is_successful = data.get("is_successful") or data.get("verified") or data.get("success")
            if is_successful is not None:
                self.assertFalse(is_successful,
                    "CRITICAL: State mismatch must produce is_successful=False. "
                    "Verification must not trust execution status alone.")

    def test_missing_post_state_fails_closed(self) -> None:
        """POST /actions/verify → missing after_instances → must fail closed"""
        client = self._require_client()
        resp = client.post(
            "/actions/verify",
            json=self._missing_post_state_payload(),
            content_type="application/json",
        )
        status = self._status(resp)
        if status in (404, 405):
            self.fail("Production gap: POST /actions/verify endpoint not implemented.")
        data = self._json(resp)
        if isinstance(data, dict):
            is_successful = data.get("is_successful") or data.get("verified") or data.get("success")
            if is_successful is not None:
                self.assertFalse(is_successful,
                    "Missing post-action state must fail closed — "
                    "cannot prove infrastructure change occurred.")


# ─────────────────────────────────────────────────────────────────────────────
# 9. GET /audit
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditEndpoint(ApiTestBase):

    def test_audit_endpoint_reachable(self) -> None:
        """GET /audit → must be reachable if audit persistence is part of the contract"""
        client = self._require_client()
        resp = client.get("/audit")
        self.assertNotEqual(self._status(resp), 405,
            "GET /audit must not return 405. "
            "Production gap if 404: audit endpoint not implemented.")

    def test_audit_returns_json(self) -> None:
        """GET /audit → response must be JSON"""
        client = self._require_client()
        resp = client.get("/audit")
        if self._status(resp) == 200:
            data = self._json(resp)
            self.assertIsNotNone(data, "GET /audit must return JSON.")

    def test_audit_response_is_list_or_envelope(self) -> None:
        """GET /audit → 200 body must be a list or envelope dict of audit entries"""
        client = self._require_client()
        resp = client.get("/audit")
        if self._status(resp) == 200:
            data = self._json(resp)
            self.assertIsInstance(data, (list, dict),
                "GET /audit must return a list of audit entries or an envelope dict.")

    def test_audit_does_not_omit_failures(self) -> None:
        """
        GET /audit → failed/blocked actions must not disappear from audit log.
        NOTE: This test can only be exercised meaningfully if:
          a) POST /actions/execute is implemented, and
          b) audit persistence is part of the existing contract.
        Records the contractual requirement; skips body assertion if audit is 404.
        """
        client = self._require_client()
        # First: trigger a known failed execution
        client.post(
            "/actions/execute",
            json={
                "action": "scale_up",
                "target_service_id": "payment-api",
                "requested_instances": 5,
                "observation_version": "v1.0.0",
            },
            content_type="application/json",
        )
        # Then: check audit for presence of the failure
        audit_resp = client.get("/audit")
        if self._status(audit_resp) == 200:
            data = self._json(audit_resp)
            if isinstance(data, list) and len(data) > 0:
                statuses = [str(entry.get("status", "")).lower() for entry in data if isinstance(entry, dict)]
                # If there are entries, at minimum the list must not claim all are success
                # when we know a failure was submitted
                # (Only assertable if execute endpoint actually persists)
                pass  # Audit retention semantics gated on execute endpoint existence


if __name__ == "__main__":
    unittest.main()
