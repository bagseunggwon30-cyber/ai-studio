"""Local credential and registration tests use synthetic capabilities only."""
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import tomllib
import unittest

from tests.helpers import ROOT, TempStudio
from studio import supervisor_credentials as credentials
from studio.supervisor_setup import provision, TOOLS
from studio.server import StudioServer
from studio.util import atomic_write_json


@unittest.skipUnless(os.name == "nt", "Windows DPAPI registration")
class Registration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="studio-registration-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/"config.toml"
        self.secret=self.root/"private/client.credential"

    def test_dpapi_round_trip_never_stores_plaintext(self):
        token="fixture-only-credential-not-a-model-login-"+"x"*32
        credentials.save(self.secret,token)
        self.assertNotIn(token.encode(),self.secret.read_bytes())
        self.assertEqual(credentials.load(self.secret),token)
        self.secret.write_text("wrong format",encoding="utf-8")
        with self.assertRaises(credentials.CredentialError):credentials.load(self.secret)

    def test_registration_preserves_other_settings_and_reuses_token(self):
        original='model = "fixture-model"\n[mcp_servers.existing]\ncommand = "fixture"\n'
        self.config.write_text(original,encoding="utf-8")
        atomic_write_json(self.root/"data/supervisors.json",{"enabled":False,"clients":[
            {"id":"existing","enabled":False,"projects":{}}]})
        result=provision(self.root,self.config,self.secret,8765)
        saved=self.config.read_text(encoding="utf-8")
        token=credentials.load(self.secret)
        self.assertNotIn(token,saved)
        self.assertNotIn(token,json.dumps(result))
        parsed=tomllib.loads(saved)
        self.assertEqual(parsed["model"],"fixture-model")
        self.assertEqual(parsed["mcp_servers"]["existing"],{"command":"fixture"})
        self.assertEqual(parsed["mcp_servers"]["ai_studio"]["enabled_tools"],TOOLS)
        provision(self.root,self.config,self.secret,8765)
        self.assertEqual(self.config.read_text(),saved)
        self.assertEqual(credentials.load(self.secret),token)
        registry=json.loads((self.root/"data/supervisors.json").read_text())
        self.assertEqual(len(registry["clients"]),2)
        self.assertEqual(registry["clients"][1]["projects"],{"studio-docs":{
            "read":True,"write":True,"paths":["reports/connection-check/**"]}})

    def test_conflicting_mcp_is_not_overwritten_or_credential_issued(self):
        original='[mcp_servers.ai_studio]\ncommand="different"\n'
        self.config.write_text(original)
        with self.assertRaises(ValueError):provision(self.root,self.config,self.secret,8765)
        self.assertEqual(self.config.read_text(),original)
        self.assertFalse(self.secret.exists())
        self.assertFalse((self.root/"data/supervisors.json").exists())


class PassiveHost(unittest.TestCase):
    def test_host_reuses_supervisor_api_but_denies_dashboard_writes(self):
        spec=importlib.util.spec_from_file_location("supervisor_host",ROOT/"tools/supervisor-host.py")
        host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
        company=TempStudio();self.addCleanup(company.close)
        token="fixture-only-supervisor-"+"x"*40
        atomic_write_json(company.cfg.data_dir/"supervisors.json",{"enabled":True,"clients":[{
            "id":"fixture","enabled":True,"token_sha256":hashlib.sha256(token.encode()).hexdigest(),
            "projects":{"demo":{"read":True,"write":True,"paths":["docs/**"]}}}]})
        server=StudioServer(company.cfg,company.store,company.engine,0)
        server.RequestHandlerClass=host.ConnectionHandler
        port=server.server_address[1]
        server.allowed_hosts={f"127.0.0.1:{port}"}
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def finish():
            server.shutdown();server.server_close();thread.join(5)
        self.addCleanup(finish)
        conn=http.client.HTTPConnection("127.0.0.1",port,timeout=5)
        conn.request("GET","/supervisor/health")
        response=conn.getresponse();data=json.loads(response.read());conn.close()
        self.assertEqual(data["mode"],"connection-only")
        self.assertEqual(data["workers"],0)
        conn=http.client.HTTPConnection("127.0.0.1",port,timeout=5)
        conn.request("POST","/api/auto-run","{}",{"X-Studio-Token":server.token})
        response=conn.getresponse();response.read();conn.close()
        self.assertEqual(response.status,403)
        payload={"operation":"submit","project":"demo","key":"passive-test","payload":{
            "title":"fixture","requirements":[{"id":"A1","text":"fixture","evidence":[]}]}}
        conn=http.client.HTTPConnection("127.0.0.1",port,timeout=5)
        conn.request("POST","/supervisor/v1",json.dumps(payload),{"Content-Type":"application/json","Authorization":"Bearer "+token})
        response=conn.getresponse();data=json.loads(response.read());conn.close()
        self.assertEqual(response.status,200)
        self.assertEqual(data["data"]["task"]["status"],"ready")
        self.assertEqual(company.store.runs(),[])
        self.assertIsNone(company.engine._thread)
