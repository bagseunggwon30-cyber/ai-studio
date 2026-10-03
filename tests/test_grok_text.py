"""Text isolation and process tests use a local Python CLI fixture, never a model."""
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from studio.grok_text import IsolationError, validate
from studio.runtimes import GrokTextRuntime, RunSpec


FAKE = textwrap.dedent('''
import json,os,sys,time
from pathlib import Path
args=sys.argv[1:]
home=Path(os.environ.get('GROK_HOME','fixture-help-home'))
if '--help' in args:
    print('--prompt-file --output-format --model --tools --disallowed-tools --deny --permission-mode --no-subagents --disable-web-search --max-turns --json-schema')
elif 'inspect' in args:
    blocked=os.environ.get('FAKE_TEXT_GROK_MODE')=='unsafe'
    print(json.dumps({'mcpServers':[{'name':'inherited'}] if blocked else [],'hooks':[],'plugins':[],
        'lspServers':[],'projectInstructions':[],'skills':[],
        'permissions':{'mcpServerAllowlist':[],'mcpLockdownSources':[{'source':str(home/'requirements.toml'),'advisory':False}]},
        'loginPolicy':{'apiKeyAuthDisabled':True}}))
else:
    Path(os.environ['FAKE_TEXT_GROK_LOG']).write_text(json.dumps({'args':args,'home':str(home),'cwd':str(Path.cwd()),
        'api_key_present':bool(os.environ.get('XAI_API_KEY')),'auth_link':(home/'auth.json').exists(),
        'supervisor_token_present':bool(os.environ.get('STUDIO_SUPERVISOR_TOKEN'))}),encoding='utf-8')
    mode=os.environ.get('FAKE_TEXT_GROK_MODE','')
    if mode=='login':
        print('not logged in; fixture-private-detail',file=sys.stderr)
        sys.exit(5)
    if mode=='delay':time.sleep(30)
    text=json.dumps({'verdict':'approve','summary':'checked','findings':[],'skills_used':[]})
    if mode=='tool':print(json.dumps({'type':'tool_call','toolName':'run_terminal_cmd'}))
    elif mode=='catalog':print(json.dumps({'type':'available_commands','tools':[{'name':'read_file'}]}))
    elif mode=='malformed':print('not json')
    if mode=='single':print(json.dumps({'text':text,'usage':{'input_tokens':21,'output_tokens':4},'modelUsage':{'requested-only':{}}}))
    else:
        print(json.dumps({'type':'text','data':text}))
        print(json.dumps({'type':'end','stopReason':'end_turn','usage':{'input_tokens':21,'output_tokens':4}}))
''')


class GrokText(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-text-fixture-")
        self.root = Path(self.temp.name)
        self.user = self.root / "user"
        (self.user / ".grok").mkdir(parents=True)
        (self.user / ".grok/auth.json").write_text("fixture-only-not-a-credential")
        self.script = self.root / "cli.py"
        self.script.write_text(FAKE,encoding="utf-8")
        self.info = {"found":True,"cmd":[sys.executable,str(self.script)],"version":"grok fixture"}
        self.log = self.root / "seen.json"
        self.env = mock.patch.dict(os.environ,{"FAKE_TEXT_GROK_LOG":str(self.log),"FAKE_TEXT_GROK_MODE":"",
                                  "XAI_API_KEY":"must-not-pass","STUDIO_SUPERVISOR_TOKEN":"must-not-pass"})
        self.home = mock.patch("studio.grok_text.Path.home",return_value=self.user)
        self.env.start(); self.home.start()
        self.addCleanup(self.temp.cleanup); self.addCleanup(self.home.stop); self.addCleanup(self.env.stop)
        with mock.patch("studio.runtimes.find_grok",return_value=self.info):
            self.runtime = GrokTextRuntime({})
        self.spec = RunSpec("R-text-review","reviewer","review this supplied text",self.root,self.root/"run",
                            model="requested-only",timeout_s=5,output_schema={"type":"object"})

    def test_text_process_is_isolated_and_identity_is_not_inferred(self):
        result = self.runtime.run(self.spec,lambda:False)
        self.assertTrue(result.ok,result.error)
        self.assertEqual(result.structured["verdict"],"approve")
        self.assertIsNone(result.provider_model)
        self.assertEqual(result.usage["input_tokens"],21)
        self.assertIsNone(result.usage["cache_read_input_tokens"])
        seen=json.loads(self.log.read_text())
        self.assertTrue(seen["auth_link"])
        self.assertFalse(seen["api_key_present"])
        self.assertFalse(seen["supervisor_token_present"])
        self.assertNotEqual(seen["cwd"],str(self.root))
        self.assertFalse(Path(seen["home"]).exists())
        args=seen["args"]
        self.assertEqual(args[args.index("--permission-mode")+1],"dontAsk")
        self.assertEqual(args[args.index("--deny")+1],"*")
        self.assertEqual(args[args.index("--disallowed-tools")+1],"read_file,search_tool,use_tool")
        self.assertNotIn("--always-approve",args)
        self.assertEqual((self.user/".grok/auth.json").read_text(),"fixture-only-not-a-credential")

    def test_native_schema_single_json_is_supported(self):
        os.environ["FAKE_TEXT_GROK_MODE"]="single"
        result=self.runtime.run(self.spec,lambda:False)
        self.assertTrue(result.ok,result.error)
        self.assertIsNone(result.provider_model,"modelUsage request keys are not response identity")

    def test_unsafe_inherited_surface_prevents_inference(self):
        os.environ["FAKE_TEXT_GROK_MODE"]="unsafe"
        result=self.runtime.run(self.spec,lambda:False)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind,"policy")
        self.assertFalse(self.log.exists())

    def test_login_failure_is_classified_without_exposing_cli_details(self):
        os.environ["FAKE_TEXT_GROK_MODE"]="login"
        result=self.runtime.run(self.spec,lambda:False)
        self.assertEqual(result.error_kind,"login")
        self.assertNotIn("fixture-private-detail",result.error)
        self.assertIsNone(result.provider_model)
        self.assertIsNone(result.usage["input_tokens"])

    def test_tool_exposure_or_malformed_output_is_not_accepted(self):
        for mode in ("tool","catalog","malformed"):
            os.environ["FAKE_TEXT_GROK_MODE"]=mode
            result=self.runtime.run(self.spec,lambda:False)
            self.assertFalse(result.ok,mode)
            self.assertIn(result.error_kind,("policy","schema"))

    def test_timeout_reaps_process_and_removes_login_link(self):
        os.environ["FAKE_TEXT_GROK_MODE"]="delay"
        self.spec.timeout_s=.2
        result=self.runtime.run(self.spec,lambda:False)
        self.assertEqual(result.error_kind,"timeout")
        seen=json.loads(self.log.read_text())
        self.assertFalse(Path(seen["home"]).exists())

    def test_cancellation_removes_private_login_link(self):
        os.environ["FAKE_TEXT_GROK_MODE"]="delay"
        result=self.runtime.run(self.spec,lambda:self.log.exists())
        self.assertEqual(result.error_kind,"stopped")
        seen=json.loads(self.log.read_text())
        self.assertFalse(Path(seen["home"]).exists())
        self.assertTrue((self.user/".grok/auth.json").exists())

    def test_mcp_and_write_permissions_are_refused(self):
        for changes in ({"sandbox":"workspace-write"},{"mcp":[{"name":"outside"}]},{"web_search":True}):
            spec=RunSpec(**{**self.spec.__dict__,**changes})
            result=self.runtime.run(spec,lambda:False)
            self.assertEqual(result.error_kind,"policy")
            self.assertFalse(self.log.exists())

    def test_missing_inspection_contract_fails_closed(self):
        with self.assertRaises(IsolationError):validate({},self.root)


if __name__ == "__main__":unittest.main()
