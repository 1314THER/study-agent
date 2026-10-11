import json
import unittest
from unittest.mock import patch

from backend import routine_codex as codex


class FakeProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.killed = False

    def communicate(self, input=None, timeout=None):
        self.input = input
        self.timeout = timeout
        return self.stdout, self.stderr

    def kill(self):
        self.killed = True


class SlowProcess(FakeProcess):
    def __init__(self):
        super().__init__()
        self.inputs = []

    def communicate(self, input=None, timeout=None):
        self.inputs.append(input)
        if timeout is not None:
            raise codex.subprocess.TimeoutExpired("codex", timeout)
        return "", ""


class CancelDuringWorkProcess(FakeProcess):
    def __init__(self):
        super().__init__()
        self.inputs = []

    def communicate(self, input=None, timeout=None):
        self.inputs.append(input)
        if timeout is not None:
            raise codex.subprocess.TimeoutExpired("codex", timeout)
        return "", ""


class RoutineCodexTests(unittest.TestCase):
    def test_env_inherits_system_http_proxies_without_api_keys(self):
        with patch.dict(codex.os.environ, {
            "OPENAI_API_KEY": "private-api-key", "CODEX_API_KEY": "private-codex-key",
        }, clear=True), patch.object(codex, "getproxies", return_value={
            "http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897",
            "socks": "socks5://127.0.0.1:7897",
        }):
            env = codex._env()
        self.assertEqual(env["HTTP_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:7897")
        self.assertNotIn("ALL_PROXY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CODEX_API_KEY", env)

    def test_env_preserves_explicit_proxy_settings_including_disabled_proxy(self):
        with patch.dict(codex.os.environ, {
            "HTTP_PROXY": "http://127.0.0.1:8080", "https_proxy": "",
        }, clear=True), patch.object(codex, "getproxies", return_value={
            "http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897",
        }):
            env = codex._env()
        self.assertEqual(env["HTTP_PROXY"], "http://127.0.0.1:8080")
        self.assertEqual(env["https_proxy"], "")
        self.assertNotIn("HTTPS_PROXY", env)

    def test_env_proxy_discovery_failure_keeps_normal_environment(self):
        with patch.dict(codex.os.environ, {"PATH": "/usr/bin"}, clear=True), \
             patch.object(codex, "getproxies", side_effect=OSError("unavailable")):
            self.assertEqual(codex._env(), {"PATH": "/usr/bin"})

    def test_only_chatgpt_login_is_accepted(self):
        with patch.object(codex, "_codex_path", return_value="/usr/bin/codex"), \
             patch.object(codex.subprocess, "run", return_value=type("R", (), {
                 "returncode": 0, "stdout": "Logged in using ChatGPT", "stderr": ""})()):
            self.assertTrue(codex.check_available())
        with patch.object(codex, "_codex_path", return_value="/usr/bin/codex"), \
             patch.object(codex.subprocess, "run", return_value=type("R", (), {
                 "returncode": 0, "stdout": "Logged in using API key", "stderr": "secret"})()):
            with self.assertRaises(codex.CodexUnavailable) as caught:
                codex.check_available()
        self.assertEqual(caught.exception.status_code, 401)
        self.assertNotIn("secret", str(caught.exception))

    def test_jsonl_final_message_and_usage_callback(self):
        output = "\n".join([
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "old"}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":true}'}}),
            json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 120, "cached_input_tokens": 70, "output_tokens": 9}}),
        ])
        proc = FakeProcess(stdout=output)
        seen = []
        with patch.object(codex, "_codex_path", return_value="/usr/bin/codex"), \
             patch.object(codex, "check_available", return_value=True), \
             patch.object(codex.subprocess, "Popen", return_value=proc) as popen, \
             patch.object(codex, "_private_cwd", return_value="/private/tmp/routine-codex-test"):
            caller = codex.make_codex_caller(usage_callback=lambda *args: seen.append(args))
            answer = caller("system rules", '{"stage":"retrieved_match"}', {"id": 5})
        self.assertEqual(answer, '{"ok":true}')
        self.assertIn("<SYSTEM>\nsystem rules", proc.input)
        self.assertIn("<USER_DATA>\n{\"stage\":\"retrieved_match\"}", proc.input)
        args, kwargs = popen.call_args
        self.assertIn("--sandbox", args[0])
        self.assertIn("read-only", args[0])
        self.assertIn("--ephemeral", args[0])
        self.assertIn("--ignore-user-config", args[0])
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
        self.assertNotIn("CODEX_API_KEY", kwargs["env"])
        self.assertEqual(len(seen), 1)
        item, stage, usage = seen[0]
        self.assertEqual((item, stage), ({"id": 5}, "retrieved_match"))
        self.assertEqual(usage["prompt_tokens"], 120)
        self.assertEqual(usage["prompt_cache_hit_tokens"], 70)
        self.assertEqual(usage["prompt_cache_miss_tokens"], 50)
        self.assertEqual(usage["completion_tokens"], 9)

    def test_provider_failure_is_sanitized_and_classified(self):
        proc = FakeProcess(returncode=1, stdout="QUOTA secret-account-id", stderr="token=secret")
        with patch.object(codex, "_codex_path", return_value="/usr/bin/codex"), \
             patch.object(codex, "check_available", return_value=True), \
             patch.object(codex.subprocess, "Popen", return_value=proc), \
             patch.object(codex, "_private_cwd", return_value="/private/tmp/routine-codex-test"):
            with self.assertRaises(codex.CodexUnavailable) as caught:
                codex.make_codex_caller()("s", "u", {})
        self.assertEqual(caught.exception.status_code, 429)
        self.assertNotIn("secret", str(caught.exception))

    def test_ensure_active_exception_propagates(self):
        error = RuntimeError("job stopped")
        with patch.object(codex, "check_available") as check:
            def stop():
                raise error
            with self.assertRaisesRegex(RuntimeError, "job stopped"):
                codex.make_codex_caller(ensure_active=stop)("s", "u", {})
        check.assert_not_called()

    def test_timeout_polls_then_kills_and_returns_400(self):
        proc = SlowProcess()
        with patch.object(codex, "_codex_path", return_value="/usr/bin/codex"), \
             patch.object(codex, "check_available", return_value=True), \
             patch.object(codex.subprocess, "Popen", return_value=proc), \
             patch.object(codex, "_private_cwd", return_value="/private/tmp/routine-codex-test"):
            with self.assertRaises(codex.CodexUnavailable) as caught:
                codex.make_codex_caller(timeout=0.02)("s", "u", {})
        self.assertEqual(caught.exception.status_code, 400)
        self.assertTrue(proc.killed)
        self.assertIsNotNone(proc.inputs[0])
        self.assertIn(None, proc.inputs[1:])

    def test_model_unavailable_uses_400(self):
        proc = FakeProcess(returncode=1, stderr="model gpt-6-luna unavailable")
        with patch.object(codex, "_codex_path", return_value="/usr/bin/codex"), \
             patch.object(codex, "check_available", return_value=True), \
             patch.object(codex.subprocess, "Popen", return_value=proc), \
             patch.object(codex, "_private_cwd", return_value="/private/tmp/routine-codex-test"):
            with self.assertRaises(codex.CodexUnavailable) as caught:
                codex.make_codex_caller()("s", "u", {})
        self.assertEqual(caught.exception.status_code, 400)

    def test_cancel_during_communicate_kills_drains_and_propagates(self):
        proc = CancelDuringWorkProcess()
        stopped = RuntimeError("job stopped")
        calls = []

        def ensure_active():
            calls.append(True)
            # call 1 is before preflight, call 2 is the first communicate poll;
            # call 3 happens after the process reports its first timeout.
            if len(calls) == 3:
                raise stopped

        with patch.object(codex, "_codex_path", return_value="/usr/bin/codex"), \
             patch.object(codex, "check_available", return_value=True), \
             patch.object(codex.subprocess, "Popen", return_value=proc), \
             patch.object(codex, "_private_cwd", return_value="/private/tmp/routine-codex-test"):
            with self.assertRaisesRegex(RuntimeError, "job stopped"):
                codex.make_codex_caller(ensure_active=ensure_active)("s", "u", {})
        self.assertTrue(proc.killed)
        self.assertEqual(len(proc.inputs), 2)  # timed out poll and drain
        self.assertIsNotNone(proc.inputs[0])
        self.assertIsNone(proc.inputs[1])


if __name__ == "__main__":
    unittest.main()
