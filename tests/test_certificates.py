"""Codex TLS trust and permanent connection failures, without model requests."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import ROOT, TempStudio  # noqa: F401
from studio import runtimes
from studio.runtimes import CertificateSetupError, RunResult, RunSpec
from studio.util import clean_child_env


CERT_ERROR = "stream disconnected before completion: invalid peer certificate: UnknownIssuer"


class WindowsTrust(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_exports_trusted_roots_and_removes_bundle_after_failure(self):
        context = mock.Mock()
        context.get_ca_certs.return_value = [b"fixture-root"]
        with mock.patch.object(runtimes, "IS_WINDOWS", True), \
                mock.patch.object(runtimes.ssl, "create_default_context", return_value=context), \
                mock.patch.object(runtimes.ssl, "DER_cert_to_PEM_cert", return_value="fixture-pem\n"):
            with self.assertRaisesRegex(RuntimeError, "process failure"):
                with runtimes.codex_child_env() as env:
                    path = Path(env["CODEX_CA_CERTIFICATE"])
                    self.assertEqual(path.read_text(), "fixture-pem\n")
                    context.get_ca_certs.assert_called_once_with(binary_form=True)
                    raise RuntimeError("process failure")
            self.assertFalse(path.exists())
            self.assertNotIn("CODEX_CA_CERTIFICATE", os.environ)

    def test_preserves_explicit_ca_and_non_windows_environment(self):
        for values, windows in (({"CODEX_CA_CERTIFICATE": "configured.pem"}, True),
                                ({"SSL_CERT_FILE": "configured.pem"}, True), ({}, False)):
            with self.subTest(values=values, windows=windows), \
                    mock.patch.dict(os.environ, values, clear=True), \
                    mock.patch.object(runtimes, "IS_WINDOWS", windows), \
                    mock.patch.object(runtimes.ssl, "create_default_context") as context:
                with runtimes.codex_child_env() as env:
                    self.assertEqual({k: env[k] for k in values}, values)
                    if "CODEX_CA_CERTIFICATE" not in values:
                        self.assertNotIn("CODEX_CA_CERTIFICATE", env)
                context.assert_not_called()

    def test_empty_trust_store_fails_before_dispatch(self):
        context = mock.Mock()
        context.get_ca_certs.return_value = []
        with mock.patch.object(runtimes, "IS_WINDOWS", True), \
                mock.patch.object(runtimes.ssl, "create_default_context", return_value=context):
            with self.assertRaises(CertificateSetupError):
                with runtimes.codex_child_env():
                    self.fail("must not dispatch with an empty trust store")


class CertificateFailures(unittest.TestCase):
    def test_auth_diagnostics_are_not_login_failures(self):
        self.assertIsNone(runtimes.classify_error("auth.retry_after_unauthorized=false authentication_mode=chatgpt"))
        self.assertEqual(runtimes.classify_error("HTTP 401 Unauthorized"), "login")
        self.assertEqual(runtimes.classify_error(CERT_ERROR + " auth.retry_after_unauthorized=false"), "certificate")

    def test_only_cli_certificate_errors_trigger_stop(self):
        events = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": CERT_ERROR}},
            {"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": CERT_ERROR}},
            {"type": "error", "message": "Reconnecting... waiting for network (error sending request)"},
            {"type": "turn.failed", "error": []},
            {"type": "item.completed", "item": []},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            for event in events:
                path.write_text(json.dumps(event) + "\n", encoding="utf-8")
                self.assertIsNone(runtimes.codex_certificate_failure(path), event)
            for event in ({"type": "error", "message": CERT_ERROR},
                          {"type": "turn.failed", "error": {"message": CERT_ERROR}},
                          {"type": "item.completed", "item": {"type": "error", "message": CERT_ERROR}}):
                path.write_text("partial-json\n" + json.dumps(event) + "\n", encoding="utf-8")
                self.assertEqual(runtimes.codex_certificate_failure(path), "certificate")
        self.assertEqual(runtimes.classify_error(CERT_ERROR), "certificate")

    def test_permanent_certificate_failure_terminates_waiting_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            events = folder / "events.jsonl"
            code = "import json,time; print(json.dumps({'type':'error','message':" + repr(CERT_ERROR) + "}),flush=True); time.sleep(30)"
            _, reason, duration = runtimes.run_process(
                [sys.executable, "-c", code], cwd=folder, stdin_text="", stdout_path=events,
                stderr_path=folder / "stderr.txt", timeout_s=10, should_stop=lambda: False,
                env=clean_child_env(), failure_probe=lambda: runtimes.codex_certificate_failure(events))
            self.assertEqual(reason, "certificate")
            self.assertLess(duration, 5)

    def test_runtime_uses_bundle_only_during_child_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            spec = RunSpec("certificate-test", "producer", "p", folder, folder / "run")
            with mock.patch.object(runtimes, "find_codex", return_value={"found": True, "cmd": ["fixture"]}):
                runtime = runtimes.CodexRuntime({"block_host_skills": False})
            context = mock.Mock()
            context.get_ca_certs.return_value = [b"fixture"]
            seen = {}
            def process(args, **kw):
                seen["path"] = Path(kw["env"]["CODEX_CA_CERTIFICATE"])
                self.assertTrue(seen["path"].is_file())
                self.assertNotIn("OPENAI_API_KEY", kw["env"])
                self.assertIn("--ignore-user-config", args)
                self.assertEqual(args[args.index("-s") + 1], "read-only")
                self.assertIsNone(kw["failure_probe"]())
                return 1, "certificate", 0.3
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}, clear=True), \
                    mock.patch.object(runtimes, "IS_WINDOWS", True), \
                    mock.patch.object(runtimes.ssl, "create_default_context", return_value=context), \
                    mock.patch.object(runtimes.ssl, "DER_cert_to_PEM_cert", return_value="pem"), \
                    mock.patch.object(runtimes, "run_process", side_effect=process):
                result = runtime.run(spec, lambda: False)
            self.assertFalse(result.ok)
            self.assertEqual(result.error_kind, "certificate")
            self.assertFalse(seen["path"].exists())

    def test_task_reports_certificate_failure_without_login_or_size_advice(self):
        studio = TempStudio()
        self.addCleanup(studio.close)
        task = studio.engine.submit_directive("기획", "demo")
        studio.engine._fail_run(task, RunResult(False, "codex", "fixture", 1, 0.3,
                                              error_kind="certificate"), "producer")
        task = studio.store.get(task.id)
        self.assertEqual(task.status, "blocked")
        self.assertIn("인증서", task.blocked_reason)
        self.assertNotIn("작게", task.blocked_reason)
        self.assertFalse(studio.engine.status()["stopped"])
        self.assertIsNone(studio.engine.status()["needs_login"])


if __name__ == "__main__":
    unittest.main()
