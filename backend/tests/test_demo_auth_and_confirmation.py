import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, confirmation_store, tools
from app.rate_limiter import get_client_ip, limiter
from app.tools.confirmation import DEFAULT_CONFIRMATION_TTL_SECONDS, PendingConfirmation
from app.tools.permissions import Permission

TEST_KEY = "test-demo-secret-key-12345-very-long"


class TestDemoAuthSecurity(unittest.TestCase):
    """Phase 2 & Phase 5: Demo API Authentication Security Tests."""

    def setUp(self):
        os.environ["ORION_DEMO_KEY"] = TEST_KEY
        get_settings.cache_clear()
        limiter.clear()
        self.unauthed_client = TestClient(app, headers={})
        self.authed_client = TestClient(
            app,
            headers={"Authorization": f"Bearer {TEST_KEY}"},
        )
        self.bad_client = TestClient(
            app,
            headers={"Authorization": "Bearer invalid-wrong-demo-key"},
        )

    # 1. Health check and frontend shell work without authentication and leak no sensitive information
    def test_1_health_and_frontend_shell_public_no_secrets(self):
        # /health check
        resp = self.unauthed_client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("service", data)
        self.assertIn("version", data)

        # Frontend shell / root loads without bearer key so user can sign in
        root_resp = self.unauthed_client.get("/")
        self.assertEqual(root_resp.status_code, 200)

        # Check no secrets in either response
        for raw_text in (resp.text, root_resp.text):
            self.assertNotIn(TEST_KEY, raw_text)
            current_settings = get_settings()
            if current_settings.nebius_api_key:
                self.assertNotIn(current_settings.nebius_api_key, raw_text)
            if current_settings.hermes_gateway_token:
                self.assertNotIn(current_settings.hermes_gateway_token, raw_text)

    # 2. Every protected API route and documentation route rejects missing credentials with HTTP 401
    def test_2_protected_endpoints_reject_missing_credentials(self):
        endpoints = [
            ("GET", "/docs"),
            ("GET", "/redoc"),
            ("GET", "/openapi.json"),
            ("GET", "/api/providers"),
            ("POST", "/api/sessions"),
            ("GET", "/api/sessions"),
            ("GET", "/api/sessions/nonexistent/messages"),
            ("DELETE", "/api/sessions/nonexistent"),
            ("POST", "/api/chat"),
            ("POST", "/api/memory"),
            ("POST", "/api/memory/recall"),
            ("GET", "/api/memory/recent"),
            ("DELETE", "/api/memory/999"),
            ("GET", "/api/personal/snapshot"),
            ("GET", "/api/skills"),
            ("GET", "/api/tools"),
            ("POST", "/api/tools/plan"),
            ("POST", "/api/tools/list_directory"),
            ("POST", "/api/agent/run"),
            ("POST", "/api/agent/confirm"),
            ("POST", "/api/demo/reseed"),
        ]

        for method, path in endpoints:
            limiter.clear()  # Clear rate limiter between subtests
            with self.subTest(endpoint=path, method=method):
                if method == "GET":
                    resp = self.unauthed_client.get(path)
                elif method == "POST":
                    resp = self.unauthed_client.post(path, json={})
                elif method == "DELETE":
                    resp = self.unauthed_client.delete(path)
                self.assertEqual(
                    resp.status_code,
                    401,
                    f"Endpoint {method} {path} did not reject missing credentials with 401. Got {resp.status_code}: {resp.text}",
                )
                self.assertIn("WWW-Authenticate", resp.headers)
                self.assertIn("Bearer", resp.headers["WWW-Authenticate"])

    # 3. Every protected endpoint rejects invalid credentials with HTTP 401
    def test_3_protected_endpoints_reject_invalid_credentials(self):
        endpoints = [
            ("GET", "/docs"),
            ("GET", "/openapi.json"),
            ("GET", "/api/providers"),
            ("GET", "/api/sessions"),
            ("POST", "/api/chat"),
            ("GET", "/api/personal/snapshot"),
            ("GET", "/api/tools"),
            ("POST", "/api/agent/run"),
            ("POST", "/api/agent/confirm"),
            ("POST", "/api/demo/reseed"),
        ]

        for method, path in endpoints:
            limiter.clear()
            with self.subTest(endpoint=path, method=method):
                if method == "GET":
                    resp = self.bad_client.get(path)
                elif method == "POST":
                    resp = self.bad_client.post(path, json={})
                self.assertEqual(
                    resp.status_code,
                    401,
                    f"Endpoint {method} {path} did not reject invalid credentials with 401. Got {resp.status_code}",
                )

    # 4. Correct credentials permit legitimate workflows
    def test_4_correct_credentials_permit_legitimate_workflows(self):
        # Docs & OpenAPI
        docs_resp = self.authed_client.get("/docs")
        self.assertEqual(docs_resp.status_code, 200)

        openapi_resp = self.authed_client.get("/openapi.json")
        self.assertEqual(openapi_resp.status_code, 200)
        self.assertIn("paths", openapi_resp.json())

        # Providers
        resp = self.authed_client.get("/api/providers")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("providers", resp.json())

        # Session creation
        sess_resp = self.authed_client.post("/api/sessions?title=Test%20Auth%20Session")
        self.assertEqual(sess_resp.status_code, 200)
        sess_data = sess_resp.json()
        self.assertIn("id", sess_data)
        session_id = sess_data["id"]

        # List sessions
        list_resp = self.authed_client.get("/api/sessions")
        self.assertEqual(list_resp.status_code, 200)

        # Personal snapshot
        snap_resp = self.authed_client.get("/api/personal/snapshot")
        self.assertEqual(snap_resp.status_code, 200)

        # Tools list
        tools_resp = self.authed_client.get("/api/tools")
        self.assertEqual(tools_resp.status_code, 200)

        # Clean up session
        del_resp = self.authed_client.delete(f"/api/sessions/{session_id}")
        self.assertEqual(del_resp.status_code, 200)

    # 5. Credentials in query parameter or basic auth must be rejected
    def test_5_rejects_query_param_credentials_and_non_bearer_auth(self):
        # Query param credential attempt
        resp = self.unauthed_client.get(f"/api/providers?token={TEST_KEY}")
        self.assertEqual(resp.status_code, 401)

        # Basic auth attempt
        basic_client = TestClient(
            app,
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        resp2 = basic_client.get("/api/providers")
        self.assertEqual(resp2.status_code, 401)

    # 6. Production mode startup failure requires minimum 32 characters
    def test_6_production_mode_startup_validation_requires_32_chars(self):
        # Missing key in production mode
        with self.assertRaises(ValueError) as ctx:
            Settings(
                environment="production",
                orion_demo_key="",
                nebius_api_key="dummy-key-for-test",
            )
        self.assertIn("ORION_DEMO_KEY must be set in production mode", str(ctx.exception))

        # Under 32 characters key in production mode
        with self.assertRaises(ValueError) as ctx:
            Settings(
                environment="production",
                orion_demo_key="short-key-with-less-than-32-c",
                nebius_api_key="dummy-key-for-test",
            )
        self.assertIn("at least 32 characters", str(ctx.exception))

        # Exactly 32 characters key in production mode succeeds
        valid_32 = "a" * 32
        prod_settings = Settings(
            environment="production",
            orion_demo_key=valid_32,
            nebius_api_key="dummy-key-for-test",
        )
        self.assertEqual(prod_settings.environment, "production")
        self.assertEqual(len(prod_settings.orion_demo_key), 32)

        # Missing NEBIUS_API_KEY in production mode
        with self.assertRaises(ValueError) as ctx:
            Settings(
                environment="production",
                orion_demo_key=valid_32,
                nebius_api_key="",
            )
        self.assertIn("NEBIUS_API_KEY must be set in production mode", str(ctx.exception))

    # 7. Authentication failures never reveal secrets or sensitive info
    def test_7_authentication_failures_do_not_reveal_secrets(self):
        resp = self.bad_client.get("/api/personal/snapshot")
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn(TEST_KEY, resp.text)
        self.assertEqual(resp.json().get("detail"), "Invalid authentication credentials.")

    # 8. Rate limiting protects authentication attempts (HTTP 429)
    def test_8_rate_limiting_auth_failures(self):
        limiter.clear()
        client = TestClient(app, headers={"Authorization": "Bearer bad-key", "X-Forwarded-For": "198.51.100.10"})

        # First 10 failed auth attempts should return 401
        for i in range(10):
            res = client.get("/api/providers")
            self.assertEqual(res.status_code, 401)

        # 11th failed attempt exceeds threshold and must return 429 Too Many Requests
        res_blocked = client.get("/api/providers")
        self.assertEqual(res_blocked.status_code, 429)
        self.assertIn("Retry-After", res_blocked.headers)
        self.assertIn("Too many", res_blocked.json().get("detail", ""))

    # 9. Rate limiting protects expensive AI endpoints (HTTP 429)
    def test_9_rate_limiting_expensive_endpoints(self):
        limiter.clear()
        client = TestClient(
            app,
            headers={"Authorization": f"Bearer {TEST_KEY}", "X-Forwarded-For": "198.51.100.20"},
        )

        with patch("app.main.planner.plan", new_callable=AsyncMock) as mock_plan:
            mock_plan.return_value = {"action": "respond", "reason": "test"}

            # Send 20 plan requests
            for _ in range(20):
                res = client.post("/api/tools/plan", json={"message": "hello"})
                self.assertEqual(res.status_code, 200)

            # 21st request exceeds rate limit
            res_blocked = client.post("/api/tools/plan", json={"message": "hello"})
            self.assertEqual(res_blocked.status_code, 429)
            self.assertIn("Retry-After", res_blocked.headers)
            self.assertIn("Rate limit exceeded", res_blocked.json().get("detail", ""))


class TestConfirmationSecurity(unittest.TestCase):
    """Phase 4 & Phase 5: Confirmation Security and Bypass Elimination Tests."""

    def setUp(self):
        os.environ["ORION_DEMO_KEY"] = TEST_KEY
        get_settings.cache_clear()
        limiter.clear()
        self.client = TestClient(
            app,
            headers={"Authorization": f"Bearer {TEST_KEY}"},
        )
        confirmation_store.clear()

    # 10. Direct tool execution cannot bypass confirmation by submitting confirmed: true
    def test_10_direct_tool_execution_cannot_bypass_confirmation(self):
        # run_command
        resp = self.client.post(
            "/api/tools/run_command",
            json={"command": "echo bypass", "confirmed": True},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("requires confirmation", resp.json().get("detail", "").lower())

        # write_file
        resp2 = self.client.post(
            "/api/tools/write_file",
            json={"path": "test_bypass.txt", "content": "pwn", "confirmed": True},
        )
        self.assertEqual(resp2.status_code, 403)

        # delete_file
        resp3 = self.client.post(
            "/api/tools/delete_file",
            json={"path": "test_bypass.txt", "confirmed": True},
        )
        self.assertEqual(resp3.status_code, 403)

        # update_task
        resp4 = self.client.post(
            "/api/tools/update_task",
            json={"operation": "create", "title": "Bypass Task", "confirmed": True},
        )
        self.assertEqual(resp4.status_code, 403)

        # Unknown tool returns 404
        resp5 = self.client.post(
            "/api/tools/unknown_malicious_tool",
            json={"confirmed": True},
        )
        self.assertEqual(resp5.status_code, 404)

    # 11. An unapproved operation cannot execute
    def test_11_unapproved_operation_cannot_execute(self):
        pending = confirmation_store.create(
            tool="run_command",
            arguments={"command": "echo unapproved_test"},
            session_id="test-session-1",
        )
        self.assertEqual(pending.status, "pending")

        # Reject the operation
        resp = self.client.post(
            "/api/agent/confirm",
            json={
                "confirmation_id": pending.confirmation_id,
                "approved": False,
                "session_id": "test-session-1",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "rejected")
        self.assertFalse(data["executed"])

        # Check pending record status updated to rejected
        record = confirmation_store.get(pending.confirmation_id)
        self.assertEqual(record.status, "rejected")

        # Attempting to approve after rejection must fail
        resp2 = self.client.post(
            "/api/agent/confirm",
            json={
                "confirmation_id": pending.confirmation_id,
                "approved": True,
                "session_id": "test-session-1",
            },
        )
        self.assertEqual(resp2.status_code, 400)
        self.assertIn("cannot be reused", resp2.json().get("detail", ""))

    # 12. An invalid, expired or already-used confirmation cannot execute
    def test_12_invalid_expired_or_already_used_confirmation(self):
        # A. Non-existent confirmation ID -> 404
        resp_fake = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": "conf_does_not_exist", "approved": True},
        )
        self.assertEqual(resp_fake.status_code, 404)

        # B. Expired confirmation -> 400
        expired_pending = confirmation_store.create(
            tool="record_decision",
            arguments={"decision": "Test decision"},
            ttl_seconds=0,  # Expires immediately
        )
        resp_expired = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": expired_pending.confirmation_id, "approved": True},
        )
        self.assertEqual(resp_expired.status_code, 400)
        self.assertIn("expired", resp_expired.json().get("detail", "").lower())

        # C. Single-use: already-used confirmation cannot execute again -> 400
        valid_pending = confirmation_store.create(
            tool="record_decision",
            arguments={"decision": "Single use decision test"},
        )
        # First execution succeeds
        resp_first = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": valid_pending.confirmation_id, "approved": True},
        )
        self.assertEqual(resp_first.status_code, 200)
        self.assertTrue(resp_first.json()["executed"])

        # Second execution attempt must fail
        resp_second = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": valid_pending.confirmation_id, "approved": True},
        )
        self.assertEqual(resp_second.status_code, 400)
        self.assertIn("cannot be reused", resp_second.json().get("detail", ""))

    # 13. A confirmation belonging to a different session context cannot be approved
    def test_13_confirmation_session_binding(self):
        pending = confirmation_store.create(
            tool="record_decision",
            arguments={"decision": "Session Bound Decision"},
            session_id="session-user-alice",
        )

        # Attempt to approve with mismatched session context -> 403
        resp_wrong_session = self.client.post(
            "/api/agent/confirm",
            json={
                "confirmation_id": pending.confirmation_id,
                "approved": True,
                "session_id": "session-user-bob",
            },
        )
        self.assertEqual(resp_wrong_session.status_code, 403)
        self.assertIn("bound to session", resp_wrong_session.json().get("detail", "").lower())

        # Attempt to approve with omitted session_id (None) on session-bound confirmation -> 403
        resp_omitted_session = self.client.post(
            "/api/agent/confirm",
            json={
                "confirmation_id": pending.confirmation_id,
                "approved": True,
            },
        )
        self.assertEqual(resp_omitted_session.status_code, 403)
        self.assertIn("bound to session", resp_omitted_session.json().get("detail", "").lower())

        # Pending status must remain pending (not consumed by failed attempt)
        self.assertEqual(confirmation_store.get(pending.confirmation_id).status, "pending")

        # Legitimate session context succeeds
        resp_correct_session = self.client.post(
            "/api/agent/confirm",
            json={
                "confirmation_id": pending.confirmation_id,
                "approved": True,
                "session_id": "session-user-alice",
            },
        )
        self.assertEqual(resp_correct_session.status_code, 200)
        self.assertTrue(resp_correct_session.json()["executed"])

    # 14. Arguments stored for pending confirmation cannot be altered by client
    def test_14_stored_arguments_immutable(self):
        pending = confirmation_store.create(
            tool="record_decision",
            arguments={"decision": "Immutable original decision"},
        )

        # Caller sends extra/different fields in ConfirmRequest
        resp = self.client.post(
            "/api/agent/confirm",
            json={
                "confirmation_id": pending.confirmation_id,
                "approved": True,
                "arguments": {"decision": "Tampered decision"},
            },
        )
        self.assertEqual(resp.status_code, 200)
        result = resp.json()["result"]
        # The stored original argument was executed, not the tampered one
        dec_obj = result.get("decision", {})
        decision_text = dec_obj.get("decision") if isinstance(dec_obj, dict) else result.get("decision")
        self.assertEqual(decision_text, "Immutable original decision")

    # 15. Existing tool permission checks and workspace path restrictions remain intact
    def test_15_workspace_path_traversal_restricted(self):
        # Direct list_directory path traversal attempt is blocked
        resp = self.client.post(
            "/api/tools/list_directory",
            json={"path": "../../"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("workspace", resp.json().get("detail", "").lower())

        # Safe workspace relative path succeeds
        resp_safe = self.client.post(
            "/api/tools/list_directory",
            json={"path": "."},
        )
        self.assertEqual(resp_safe.status_code, 200)
        self.assertIn("entries", resp_safe.json()["result"])

    # 16. Reseed endpoint requires authentication and resets demo data
    def test_16_reseed_endpoint_workflow(self):
        try:
            unauthed = TestClient(app, headers={})
            resp_unauthed = unauthed.post("/api/demo/reseed")
            self.assertEqual(resp_unauthed.status_code, 401)

            resp_authed = self.client.post("/api/demo/reseed")
            self.assertEqual(resp_authed.status_code, 200)
            data = resp_authed.json()
            self.assertEqual(data.get("status"), "reseeded")
            self.assertIn("counts", data)
            self.assertGreater(data["counts"]["projects"], 0)
        finally:
            from app.memory.database import get_connection
            with get_connection() as conn:
                for tbl in ["projects", "goals", "tasks", "decisions", "skills", "memories"]:
                    conn.execute(f"DELETE FROM {tbl}")
                conn.commit()

    # 17. Static assets and favicon load without authentication
    def test_17_static_assets_public_access(self):
        unauthed = TestClient(app, headers={})
        resp_fav = unauthed.get("/favicon.svg")
        self.assertIn(resp_fav.status_code, (200, 404))  # 200 if file exists, 404 if not found, never 401
        self.assertNotEqual(resp_fav.status_code, 401)

        resp_asset = unauthed.get("/assets/nonexistent.js")
        self.assertEqual(resp_asset.status_code, 404)  # Missing asset gives 404, not 401


class TestForwardedIPSecurity(unittest.TestCase):
    """R2.2: Forwarded IP rate limit and header spoofing regression tests."""

    def setUp(self):
        os.environ["ORION_DEMO_KEY"] = TEST_KEY
        get_settings.cache_clear()
        limiter.clear()

    def test_direct_connection_spoofed_xff_ignored_and_rate_limited(self):
        """A public caller cannot manipulate X-Forwarded-For to bypass auth rate limits."""
        peer_ip = "203.0.113.88"

        # Attacker rotates X-Forwarded-For on 10 consecutive failed attempts
        for i in range(10):
            client = TestClient(
                app,
                headers={"Authorization": "Bearer bad-key", "X-Forwarded-For": f"192.0.2.{i}"},
                client=(peer_ip, 12345),
            )
            res = client.get("/api/providers")
            self.assertEqual(res.status_code, 401)

        # 11th request with yet another spoofed IP must be blocked (HTTP 429)
        client = TestClient(
            app,
            headers={"Authorization": "Bearer bad-key", "X-Forwarded-For": "192.0.2.99"},
            client=(peer_ip, 12345),
        )
        res_blocked = client.get("/api/providers")
        self.assertEqual(res_blocked.status_code, 429)
        self.assertIn("Retry-After", res_blocked.headers)

    def test_direct_connection_spoofed_cf_connecting_ip_ignored(self):
        """A direct public caller cannot forge CF-Connecting-IP to spoof identity."""
        peer_ip = "203.0.113.99"

        for i in range(10):
            client = TestClient(
                app,
                headers={"Authorization": "Bearer bad-key", "CF-Connecting-IP": f"10.0.0.{i}"},
                client=(peer_ip, 12345),
            )
            res = client.get("/api/providers")
            self.assertEqual(res.status_code, 401)

        # 11th request with forged CF-Connecting-IP must be blocked on the socket peer
        client = TestClient(
            app,
            headers={"Authorization": "Bearer bad-key", "CF-Connecting-IP": "10.0.0.99"},
            client=(peer_ip, 12345),
        )
        res_blocked = client.get("/api/providers")
        self.assertEqual(res_blocked.status_code, 429)

    def test_expensive_endpoint_cannot_be_bypassed_via_spoofed_xff(self):
        """A caller cannot bypass expensive AI endpoint rate limits via rotating XFF."""
        peer_ip = "203.0.113.77"

        with patch("app.main.planner.plan", new_callable=AsyncMock) as mock_plan:
            mock_plan.return_value = {"action": "respond", "reason": "test"}

            # Send 20 requests with rotating spoofed X-Forwarded-For headers
            for i in range(20):
                client = TestClient(
                    app,
                    headers={
                        "Authorization": f"Bearer {TEST_KEY}",
                        "X-Forwarded-For": f"198.51.100.{i}",
                    },
                    client=(peer_ip, 12345),
                )
                res = client.post("/api/tools/plan", json={"message": "hello"})
                self.assertEqual(res.status_code, 200)

            # 21st request with a new spoofed IP must be rate-limited
            client = TestClient(
                app,
                headers={
                    "Authorization": f"Bearer {TEST_KEY}",
                    "X-Forwarded-For": "198.51.100.200",
                },
                client=(peer_ip, 12345),
            )
            res_blocked = client.post("/api/tools/plan", json={"message": "hello"})
            self.assertEqual(res_blocked.status_code, 429)

    def test_render_trusted_proxy_prioritizes_cf_connecting_ip_over_spoofed_xff(self):
        """Behind Render's edge, Cloudflare CF-Connecting-IP is trusted over client-injected XFF."""
        client = TestClient(
            app,
            headers={
                "Authorization": f"Bearer {TEST_KEY}",
                "CF-Connecting-IP": "198.51.100.33",
                "X-Forwarded-For": "1.2.3.4, 5.6.7.8",
                "rndr-id": "test-render-req-12345",
            },
            client=("10.0.0.1", 12345),  # Render internal network
        )
        # Verify get_client_ip via endpoint behavior
        class FakeRequest:
            headers = {
                "CF-Connecting-IP": "198.51.100.33",
                "X-Forwarded-For": "1.2.3.4, 5.6.7.8",
            }
            client = type("Client", (), {"host": "10.0.0.1", "port": 12345})()

        self.assertEqual(get_client_ip(FakeRequest()), "198.51.100.33")

    def test_trusted_reverse_proxy_extracts_rightmost_untrusted_ip(self):
        """Behind a trusted proxy, right-to-left traversal selects the real connecting IP, not prepended spoofed IPs."""
        class FakeRequest:
            headers = {
                "X-Forwarded-For": "1.2.3.4, 5.6.7.8, 198.51.100.44",
            }
            client = type("Client", (), {"host": "127.0.0.1", "port": 12345})()

        self.assertEqual(get_client_ip(FakeRequest()), "198.51.100.44")

    def test_malformed_and_garbage_forwarded_headers_handled_safely(self):
        """Garbage / injection attempts in forwarded headers are rejected without errors."""
        class FakeRequest:
            headers = {
                "X-Forwarded-For": "<script>alert(1)</script>, not-an-ip, 999.999.999.999",
                "CF-Connecting-IP": "invalid-ip-string",
            }
            client = type("Client", (), {"host": "127.0.0.1", "port": 12345})()

        # Safely falls back to socket peer
        self.assertEqual(get_client_ip(FakeRequest()), "127.0.0.1")
