"""Accounts, verification, encrypted keys and the actual ASGI session boundary."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import AccountGateway, AccountStore, AuthError, COOKIE, SMTPMailer, account_context, current_account_api_key, set_current_account_api_key
from backend.data_paths import workspace_directory
from backend.identity import current_identity


class FakeMailer:
    enabled = True

    def __init__(self):
        self.messages = []

    def send_code(self, email, code):
        self.messages.append((email, code))


class AccountFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.owner = self.root / "owner"
        self.owner.mkdir()
        self.now = 1700000000.0
        self.key = Fernet.generate_key()
        self.mailer = FakeMailer()
        self.store = AccountStore(self.root / "accounts", self.owner, encryption_key=self.key,
                                  mailer=self.mailer, clock=lambda: self.now)

    def code(self, email="a@example.com"):
        self.store.send_email_code(email, "127.0.0.1")
        return self.mailer.messages[-1][1]

    def register(self, username="learner", email="a@example.com"):
        code = self.code(email)
        return self.store.register(username, email, code, "test-password-123", "sk-user-test-key", "127.0.0.1")


class AccountTests(AccountFixture):

    def test_registration_stores_hashes_and_encrypted_key_only(self):
        token, user, expires = self.register()
        self.assertEqual(user["role"], "user")
        self.assertTrue(user["api_key_configured"])
        self.assertNotIn("api_key", user)
        self.assertEqual(self.store.resolve_session(token), (user, expires))
        with sqlite3.connect(self.store.db_path) as conn:
            password, key = conn.execute("SELECT password_hash,api_key_encrypted FROM users").fetchone()
            session = conn.execute("SELECT token_hash FROM login_sessions").fetchone()[0]
            code_hash = conn.execute("SELECT code_hash FROM email_challenges").fetchone()[0]
        self.assertNotIn("test-password-123", password)
        self.assertNotIn(b"sk-user-test-key", key)
        self.assertNotEqual(session, token)
        self.assertNotEqual(code_hash, self.mailer.messages[-1][1])
        self.assertEqual(self.store.get_api_key(user["id"]), "sk-user-test-key")

    def test_sessions_survive_restart_logout_and_expire(self):
        token, user, _ = self.register()
        restarted = AccountStore(self.store.root, self.owner, encryption_key=self.key, mailer=self.mailer, clock=lambda: self.now)
        self.assertEqual(restarted.resolve_session(token)[0], user)
        restarted.logout(token)
        self.assertIsNone(self.store.resolve_session(token))
        token, _, expires = self.store.login("learner", "test-password-123", "127.0.0.2")
        self.now = expires
        self.assertIsNone(restarted.resolve_session(token))

    def test_code_is_expiring_single_use_and_wrong_attempts_persist(self):
        code = self.code()
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.store.register("learner", "a@example.com", "000000" if code != "000000" else "111111", "test-password-123", "sk-user-test-key", "127.0.0.1")
        with self.assertRaises(AuthError):
            self.store.register("learner", "a@example.com", code, "test-password-123", "sk-user-test-key", "127.0.0.1")
        self.now += 61
        code = self.code()
        self.now += 300
        with self.assertRaises(AuthError):
            self.store.register("learner", "a@example.com", code, "test-password-123", "sk-user-test-key", "127.0.0.1")
        self.now += 1
        self.register()
        with self.assertRaises(AuthError):
            self.store.register("second", "a@example.com", self.mailer.messages[-1][1], "test-password-123", "sk-user-test-key", "127.0.0.1")

    def test_send_cooldown_and_existing_email_have_identical_responses(self):
        initial = self.store.send_email_code("a@example.com", "127.0.0.1")
        again = self.store.send_email_code("a@example.com", "127.0.0.1")
        self.assertEqual(initial, again)
        self.assertEqual(len(self.mailer.messages), 1)
        self.now += 61
        self.register()
        existing = self.store.send_email_code("a@example.com", "127.0.0.1")
        self.assertEqual(existing, initial)
        self.assertEqual(len(self.mailer.messages), 2)

    def test_code_atomic_consumption(self):
        code = self.code()
        def attempt(name):
            try:
                return self.store.register(name, "a@example.com", code, "test-password-123", "sk-user-test-key", name)[1]
            except AuthError:
                return None
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(attempt, ("learnerone", "learnertwo")))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_reserved_owner_is_bootstrap_only_and_reset_revokes_sessions(self):
        for name in ("studyadmin", "StudyAdmin", "STUDYADMIN"):
            with self.assertRaisesRegex(AuthError, "保留"):
                self.store.register(name, "a@example.com", "123456", "test-password-123", "sk-user-test-key", "127.0.0.1")
        self.store.bootstrap_owner("owner-password-123")
        token, user, _ = self.store.login("StudyAdmin", "owner-password-123", "127.0.0.1")
        self.assertEqual(user["id"], "studyadmin")
        self.assertEqual(user["role"], "owner")
        self.assertEqual(self.store.workspace_for(user), self.owner.resolve())
        with self.assertRaises(AuthError):
            self.store.bootstrap_owner("new-password-123")
        self.store.bootstrap_owner("new-password-123", replace_password=True)
        self.assertIsNone(self.store.resolve_session(token))

    def test_login_failure_is_generic_and_limited(self):
        self.register()
        for attempt in range(10):
            with self.assertRaises(AuthError) as caught:
                self.store.login("missing", "wrong-password", "127.0.0.3")
            self.assertEqual(caught.exception.code, "invalid_login")
        with self.assertRaises(AuthError) as caught:
            self.store.login("missing", "wrong-password", "127.0.0.3")
        self.assertEqual(caught.exception.status, 429)
        self.now += 901
        token, user, _ = self.store.login("a@example.com", "test-password-123", "127.0.0.3")
        self.assertEqual(self.store.resolve_session(token)[0], user)

    def test_account_context_never_exposes_other_credentials(self):
        _, a, _ = self.register()
        _, b, _ = self.register("second", "b@example.com")
        self.store.set_api_key(b["id"], "sk-other-user-key")
        self.assertEqual(current_account_api_key(), "")
        with account_context(self.store, a):
            self.assertEqual(current_account_api_key(), "sk-user-test-key")
            with account_context(self.store, b):
                self.assertEqual(current_account_api_key(), "sk-other-user-key")
            self.assertEqual(current_account_api_key(), "sk-user-test-key")
            set_current_account_api_key("sk-updated-user-key")
        self.assertEqual(current_account_api_key(), "")
        self.assertEqual(self.store.get_api_key(a["id"]), "sk-updated-user-key")

    def test_email_header_injection_and_plaintext_smtp_are_rejected(self):
        with self.assertRaises(AuthError):
            self.store.send_email_code("a@example.com\r\nBcc: stolen@example.com", "127.0.0.1")
        with self.assertRaises(RuntimeError):
            SMTPMailer({"STUDY_SMTP_SECURITY": "none"})
        self.assertFalse(SMTPMailer({}).enabled)

    def test_smtp_is_tls_only_and_failed_delivery_invalidates_code(self):
        config = {"STUDY_SMTP_HOST": "smtp.example.com", "STUDY_SMTP_USERNAME": "app", "STUDY_SMTP_PASSWORD": "app-password", "STUDY_SMTP_FROM": "noreply@example.com"}
        with patch("backend.auth.smtplib.SMTP_SSL") as ssl_client, patch("backend.auth.smtplib.SMTP") as plain:
            SMTPMailer(config).send_code("a@example.com", "123456")
            ssl_client.assert_called_once()
            plain.assert_not_called()
        config["STUDY_SMTP_SECURITY"] = "starttls"
        config["STUDY_SMTP_PORT"] = "587"
        with patch("backend.auth.smtplib.SMTP") as client:
            SMTPMailer(config).send_code("a@example.com", "123456")
            methods = client.return_value.method_calls
            names = [item[0] for item in methods]
            self.assertLess(names.index("starttls"), names.index("login"))
        with patch.object(self.mailer, "send_code", side_effect=RuntimeError("sensitive SMTP details")):
            with self.assertRaises(AuthError) as caught:
                self.code()
        self.assertNotIn("sensitive", str(caught.exception))
        with sqlite3.connect(self.store.db_path) as conn:
            self.assertEqual(conn.execute("SELECT consumed FROM email_challenges").fetchone()[0], 1)

    def test_newest_session_is_retained_even_when_timestamps_match(self):
        _, user, _ = self.register()
        tokens = [self.store.create_session(user["id"])[0] for _ in range(11)]
        self.assertIsNone(self.store.resolve_session(tokens[0]))
        self.assertIsNotNone(self.store.resolve_session(tokens[-1]))

    def test_encryption_key_is_mandatory_and_wrong_key_fails_closed(self):
        with patch.dict("os.environ", {"STUDY_AUTH_ENCRYPTION_KEY": ""}):
            with self.assertRaises(RuntimeError):
                AccountStore(self.root / "other", self.owner, mailer=self.mailer)
        _, user, _ = self.register()
        other = AccountStore(self.store.root, self.owner, encryption_key=Fernet.generate_key(), mailer=self.mailer)
        with self.assertRaises(AuthError) as caught:
            other.get_api_key(user["id"])
        self.assertEqual(caught.exception.code, "credential_unavailable")


class AccountGatewayTests(AccountFixture):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        @app.get("/scope")
        def scope():
            return {"identity": current_identity(), "directory": workspace_directory(), "has_key": bool(current_account_api_key())}
        @app.post("/write")
        def write():
            return {"identity": current_identity()}
        self.gateway = AccountGateway(app, self.store, origin="https://study.test")
        self.client = TestClient(self.gateway, base_url="https://study.test")
        self.headers = {"Origin": "https://study.test"}

    def registered(self, client=None, username="learner", email="a@example.com"):
        client = client or self.client
        result = client.post("/auth/email-code", json={"email": email}, headers=self.headers)
        self.assertEqual(result.status_code, 202)
        response = client.post("/auth/register", json={"username": username, "email": email, "code": self.mailer.messages[-1][1],
                               "password": "test-password-123", "api_key": "sk-user-test-key"}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_cookie_is_httponly_secure_and_token_is_not_in_json(self):
        response = self.registered()
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn("Path=/", cookie)
        self.assertNotIn("token", response.json())
        self.assertNotIn("sk-user-test-key", response.text)
        me = self.client.get("/auth/me").json()
        self.assertTrue(me["authenticated"])
        self.assertEqual(me["user"]["role"], "user")

    def test_workspace_is_persistent_private_and_not_seeded_from_owner(self):
        self.owner.joinpath("private-sentinel").write_text("owner-private")
        a = self.registered().json()["user"]
        response = self.client.get("/scope")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["identity"]["id"], a["id"])
        directory = Path(response.json()["directory"])
        self.assertFalse((directory / "private-sentinel").exists())
        self.assertFalse((directory / ".env").exists())
        with sqlite3.connect(directory / "study_agent.db") as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM questions").fetchone()[0], 0)
        self.assertEqual(json.loads((directory / "account.json").read_text()), {"user_id": a["id"]})
        second = TestClient(self.gateway, base_url="https://study.test")
        b = self.registered(second, "second", "b@example.com").json()["user"]
        self.assertNotEqual(second.get("/scope").json()["directory"], str(directory))
        self.assertNotEqual(a["id"], b["id"])
        self.assertIsNone(current_identity())
        self.assertIsNone(workspace_directory())

    def test_origin_is_required_for_auth_and_all_account_writes(self):
        self.assertEqual(self.client.post("/auth/email-code", json={"email": "a@example.com"}).status_code, 403)
        self.assertEqual(self.client.post("/auth/login", json={}, headers={"Origin": "https://evil.test"}).status_code, 403)
        self.registered()
        self.assertEqual(self.client.post("/write", json={}).status_code, 403)
        self.assertEqual(self.client.post("/write", json={}, headers=self.headers).status_code, 200)

    def test_anonymous_never_defaults_to_owner_or_auto_enters_guest(self):
        self.assertEqual(self.client.get("/scope").status_code, 401)
        response = self.client.get("/home.html", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login.html")

    def test_logout_and_key_update_require_identity_and_never_return_key(self):
        self.registered()
        response = self.client.put("/auth/api-key", json={"api_key": "sk-new-user-key"}, headers=self.headers)
        self.assertEqual(response.json(), {"api_key_configured": True})
        old_token = self.client.cookies.get(COOKIE)
        self.assertEqual(self.client.post("/auth/logout", json={}, headers=self.headers).status_code, 200)
        self.assertIsNone(self.store.resolve_session(old_token))
        self.assertFalse(self.client.get("/auth/me").json()["authenticated"])
        self.assertEqual(self.client.get("/scope").status_code, 401)
        self.assertEqual(self.client.put("/auth/api-key", json={"api_key": "sk-new-user-key"}, headers=self.headers).status_code, 401)

    def test_registration_disabled_and_sms_explicitly_unavailable(self):
        self.mailer.enabled = False
        self.assertFalse(self.client.get("/auth/config").json()["registration_enabled"])
        self.assertEqual(self.client.post("/auth/email-code", json={"email": "a@example.com"}, headers=self.headers).status_code, 503)
        self.assertEqual(self.client.post("/auth/sms-code", json={}, headers=self.headers).status_code, 503)

    def test_auth_body_has_independent_strict_limit(self):
        response = self.client.post("/auth/login", content=b"{" + b"x" * 17000, headers={**self.headers, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.post("/auth/login", content="{}", headers=self.headers).status_code, 415)


if __name__ == "__main__":
    unittest.main()
