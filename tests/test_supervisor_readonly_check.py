"""The follow-up probe must never turn a read into submission or cancellation."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.helpers import ROOT
from studio.checkpoints import digest
from studio.supervisor_setup import connection_config

SPEC = importlib.util.spec_from_file_location("supervisor_connection_check", ROOT / "tools/dev/supervisor_connection_check.py")
CHECK = importlib.util.module_from_spec(SPEC)
with patch.object(sys, "path", [str(ROOT / "tools/dev"), *sys.path]):
    SPEC.loader.exec_module(CHECK)


class ReadonlyCheck(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="studio-readonly-check-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / "data/tasks").mkdir(parents=True)
        self.task = {"id":"T0001", "project":"studio-docs", "created_by":"supervisor:soyun",
            "status":"cancelled", "brief":"private-fixture-record-do-not-publish",
            "extra":{"submission":{"key_hash":digest(["soyun","studio-docs",CHECK.PROBE_KEY])}}}
        self.card = self.root / "data/tasks/T0001.json"
        self.card.write_text(json.dumps(self.task), encoding="utf-8")
        self.scope = patch.object(CHECK, "ROOT", self.root)
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def test_only_reads_existing_probe_and_never_publishes_record(self):
        calls = []
        class Client:
            version = "fixture"
            tool_count = 6
            closed = False
            def call(self, name, **args):
                if name not in {"task_status", "task_events", "task_result"}:
                    raise AssertionError("write operation")
                calls.append(name)
                if name == "task_events": return {"events":[{}]}
                return {"task":{"status":"cancelled"}, "runs":[], "implemented":False, "approved":False}
            def close(self): self.closed = True
        client = Client()
        config = self.root / "config.toml"
        credential = self.root / "private.credential"
        settings = connection_config(self.root, credential, 8765)
        config.write_text('[mcp_servers.ai_studio]\n'+'\n'.join(
            key+' = '+json.dumps(value) for key,value in settings.items()), encoding="utf-8")
        before = self.card.read_bytes()
        with patch("studio.supervisor_credentials.load", side_effect=AssertionError("parent token read")), \
                patch.object(CHECK,"default_paths",return_value=(config,credential)), \
                patch.object(CHECK,"CodexMcpClient",return_value=client), \
                patch.object(CHECK.http.client,"HTTPConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.read.return_value = json.dumps({"mode":"connection-only", "workers":0,
                "model_generation_calls":0,
                "company_id":hashlib.sha256(str(self.root).encode()).hexdigest()}).encode()
            result = CHECK.run(8765, read_only=True)
        self.assertEqual(calls, ["task_status", "task_events", "task_result"])
        self.assertTrue(client.closed)
        self.assertEqual(self.card.read_bytes(), before)
        self.assertNotIn(self.task["id"], json.dumps(result))
        self.assertNotIn(self.task["brief"], json.dumps(result))
        self.assertEqual(result["new_tasks_submitted"], 0)
        self.assertFalse(result["dot_native_mcp_registration_verified"])

    def test_missing_changed_or_ambiguous_probe_never_creates_task(self):
        for field, value in (("status","ready"), ("created_by","supervisor:other"), ("project","other")):
            with self.subTest(field=field):
                changed = {**self.task, field:value}
                self.card.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError): CHECK.existing_probe()
                self.assertEqual(len(list(self.card.parent.glob("*.json"))), 1)
        self.card.write_text(json.dumps(self.task), encoding="utf-8")
        other = self.card.parent / "T0002.json"
        other.write_text(json.dumps({**self.task,"id":"T0002"}), encoding="utf-8")
        with self.assertRaises(ValueError): CHECK.existing_probe()
        other.unlink()
        self.card.unlink()
        with self.assertRaises(ValueError): CHECK.existing_probe()
        self.assertEqual(list(self.card.parent.glob("*.json")), [])

    def test_configuration_conflict_stops_before_client_or_credential(self):
        path = self.root / "config.toml"
        path.write_text('[mcp_servers.ai_studio]\ncommand="other"\n', encoding="utf-8")
        with patch.object(CHECK,"default_paths",return_value=(path,self.root/"private.credential")), \
                patch.object(CHECK,"CodexMcpClient") as client, \
                patch.object(CHECK.http.client,"HTTPConnection") as connection:
            with self.assertRaises(ValueError): CHECK.run(8765, read_only=True)
            client.assert_not_called()
            connection.assert_not_called()

    def test_readonly_cli_hides_failure_and_does_not_run_write_mode(self):
        with patch.object(sys,"argv",["check","--read-only"]), \
                patch.object(CHECK,"run",side_effect=OSError("secret-value-and-private-path")) as run:
            output = io.StringIO()
            with contextlib.redirect_stdout(output): exit_code = CHECK.main()
            run.assert_called_once_with(8765, read_only=True)
            self.assertEqual(exit_code,1)
            self.assertNotIn("secret-value-and-private-path", output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["status"],"blocked")
