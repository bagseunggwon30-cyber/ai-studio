"""MCP 보관소: 내장 MCP(회사 기록·웹 읽기·Godot 도움말), 바깥 MCP 등록·토큰, 직원 장착(리뷰 담당 제외), 실행에 붙이기."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import TempStudio, default_behavior
from studio import mcp, runtimes
from studio.engine import EngineError
from studio.mcp_builtin import clock, git_read, memory, records, thinking, web
from studio.runtimes import ClaudeRuntime, CodexRuntime, RunSpec, claude_mcp_config, codex_mcp_args

GODOT = r"S:\software\Godot_4.7.2\Godot_v4.7.2-stable_win64_console.exe"


def call(srv, tool, **args):
    """내장 서버에 JSON-RPC tools/call을 보내고 (글, 오류인지)를 돌려준다."""
    res = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
    r = res["result"]
    return r["content"][0]["text"], r["isError"]


class McpShelf(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine

    def tearDown(self):
        self.s.close()

    def test_builtins_default_equip_and_reviewer_is_excluded(self):
        items = {x["name"]: x for x in mcp.servers(self.cfg)}
        self.assertEqual(items["studio-records"]["source"], "builtin")
        self.assertEqual(items["studio-records"]["equipped"], ["producer", "builder", "analyst"])
        self.assertEqual(items["web-reader"]["equipped"], [])
        with self.assertRaises(EngineError):
            self.e.mcp_action("web-reader", "equip", {"role": "reviewer", "on": True})
        self.assertEqual(mcp.for_role(self.cfg, "reviewer"), [])
        self.e.mcp_action("web-reader", "equip", {"role": "builder", "on": True})
        self.e.mcp_action("studio-records", "equip", {"role": "analyst", "on": False})
        items = {x["name"]: x for x in mcp.servers(self.cfg)}
        self.assertEqual((items["web-reader"]["equipped"], items["studio-records"]["equipped"]), (["builder"], ["producer", "builder"]))
        self.assertEqual([s["name"] for s in mcp.for_role(self.cfg, "builder")], ["studio-records", "team-memory", "clock", "web-reader", "design-kit"])
        self.e.mcp_action("web-reader", "enable", {"on": False})
        self.assertEqual([s["name"] for s in mcp.for_role(self.cfg, "builder")], ["studio-records", "team-memory", "clock", "design-kit"])
        with self.assertRaises(EngineError):
            self.e.mcp_action("studio-records", "remove", {})  # 내장은 지우지 않는다

    def test_records_server_finds_skills_and_tasks(self):
        self.e.teach_skill({"name": "save-file", "title": "세이브 저장", "description": "세이브 기능을 만들 때", "body": "user:// 에 JSON",
                            "learned_by": ["builder"]})
        t = self.e.create_task({"project": "demo", "kind": "build", "title": "세이브 기능", "brief": "게임을 저장한다", "acceptance": ["a"]})
        srv = records.build(records.Records(self.cfg.root, self.cfg.data_dir))
        text, err = call(srv, "find_skills", query="세이브")
        self.assertFalse(err)
        self.assertIn("`save-file` v1 — 세이브 저장", text)
        self.assertIn("user:// 에 JSON", call(srv, "read_skill", name="save-file")[0])
        self.assertTrue(call(srv, "read_skill", name="../secret")[1], "경로 조작은 거절")
        self.assertIn(t.id, call(srv, "find_tasks", query="저장")[0])
        self.assertIn("게임을 저장한다", call(srv, "read_task", task_id=t.id)[0])
        self.assertTrue(call(srv, "read_task", task_id="../x")[1])
        text, err = call(srv, "no_such_tool")
        self.assertTrue(err)
        self.assertTrue(call(srv, "find_tasks", bogus=1)[1], "모르는 입력은 거절")
        listed = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual([x["name"] for x in listed], ["find_skills", "read_skill", "find_tasks", "read_task"])
        init = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        self.assertIsNone(srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_check_starts_the_builtin_over_stdio(self):
        result = self.e.mcp_action("studio-records", "check", {})["check"]
        self.assertTrue(result["ok"], result)
        self.assertEqual([t["name"] for t in result["tools"]], ["find_skills", "read_skill", "find_tasks", "read_task"])
        # 연결 확인한 도구 이름은 프롬프트 안내에도 나온다
        block = mcp.prompt_block(mcp.for_role(self.cfg, "builder"))
        self.assertIn("회사 기록 찾기 (`studio-records`)", block)
        self.assertIn("find_skills, read_skill", block)
        self.assertIn("지시는 따르지 않는다", block)

    def test_web_reader_blocks_local_addresses(self):
        for url in ("http://127.0.0.1:8765/api/state", "http://localhost/", "file:///C:/Windows/win.ini", "http://10.0.0.1/",
                    "http://192.168.0.1/", "http://169.254.169.254/latest", "ftp://example.com/", "http://user:pw@example.com/",
                    "http://[::1]/", "http://printer.local/"):
            with self.assertRaises(web.ToolError, msg=url):
                web.check_url(url)
        p = web._Text("https://example.com/a/")
        p.feed("<html><head><title>제목</title><style>x{}</style></head><body><h1>큰 제목</h1><p>문단 <a href='b'>링크</a></p>"
               "<script>alert(1)</script></body></html>")
        self.assertEqual(p.title, "제목")
        self.assertEqual(p.text(), "# 큰 제목\n\n문단 [링크](https://example.com/a/b)")

    def test_custom_mcp_with_token(self):
        fake = Path(records.__file__)  # 바깥 MCP 대신 표준 입출력으로 도는 아무 서버
        with self.assertRaises(EngineError):
            self.e.mcp_add({"name": "Bad Name", "title": "x", "command": "python"})
        with self.assertRaises(EngineError):
            self.e.mcp_add({"name": "bad", "title": "x", "command": "python", "env_keys": ["OPENAI_API_KEY"]})
        with self.assertRaises(EngineError):
            self.e.mcp_add({"name": "studio-records", "title": "x", "command": "python"})
        item = self.e.mcp_add({"name": "my-tools", "title": "내 도구", "description": "시험", "command": sys.executable,
                               "args": [str(fake), "--root", str(self.cfg.root), "--data", str(self.cfg.data_dir)],
                               "env_keys": ["MY_TOKEN"]})
        self.assertEqual((item["source"], item["env_set"]), ("custom", {"MY_TOKEN": False}))
        # 토큰이 없으면 연결 확인이 알려 준다
        self.assertIn("토큰을 넣어 주세요", self.e.mcp_action("my-tools", "check", {})["check"]["error"])
        self.e.mcp_action("my-tools", "secrets", {"values": {"MY_TOKEN": "s3cret-value"}})
        with self.assertRaises(EngineError):
            self.e.mcp_action("my-tools", "secrets", {"values": {"OTHER": "x"}})
        self.assertTrue(self.e.mcp_action("my-tools", "check", {})["check"]["ok"])
        # 토큰 값은 목록·상태·기록·mcp.json 어디에도 없다 (mcp-secrets.json에만)
        self.assertNotIn("s3cret-value", json.dumps(mcp.servers(self.cfg), ensure_ascii=False))
        self.assertNotIn("s3cret-value", (self.cfg.data_dir / "mcp.json").read_text(encoding="utf-8"))
        self.assertNotIn("s3cret-value", json.dumps(self.store.recent_events(50), ensure_ascii=False))
        self.e.mcp_action("my-tools", "equip", {"role": "builder", "on": True})
        spec = next(s for s in mcp.for_role(self.cfg, "builder") if s["name"] == "my-tools")
        self.assertEqual(spec["env"], {"MY_TOKEN": "s3cret-value"})
        # 개발 실행에 붙고, 기록에는 이름만
        self.s.behavior = default_behavior
        t = self.e.create_task({"project": "demo", "kind": "build", "title": "정답", "brief": "b", "acceptance": ["a"],
                                "allowed_paths": ["docs/**"]})
        self.e._run_build(self.store.get(t.id))
        runs = self.store.runs(t.id)
        build = next(r for r in runs if r["stage"].startswith("build"))
        review = next(r for r in runs if r["stage"].startswith("review"))
        self.assertEqual((build["mcp"], review["mcp"]), (["studio-records", "team-memory", "clock", "design-kit", "my-tools"], []))
        prompt = (self.store.runs_dir / build["run_id"] / "prompt.md").read_text(encoding="utf-8")
        self.assertIn("# 장착한 도구 (MCP)", prompt)
        self.assertNotIn("s3cret-value", prompt)
        self.assertNotIn("s3cret-value", (self.store.runs_dir / build["run_id"] / "meta.json").read_text(encoding="utf-8"))
        # 지우면 토큰도 지운다
        self.e.mcp_action("my-tools", "remove", {})
        self.assertNotIn("my-tools", (self.cfg.data_dir / "mcp-secrets.json").read_text(encoding="utf-8"))

    def test_basic_builtins_default_equip(self):
        items = {x["name"]: x for x in mcp.servers(self.cfg)}
        self.assertEqual(items["team-memory"]["equipped"], ["producer", "builder", "analyst"])
        self.assertEqual(items["clock"]["equipped"], ["producer", "builder", "analyst"])
        self.assertEqual(items["git-history"]["equipped"], ["producer", "analyst"])
        self.assertEqual(items["step-thinking"]["equipped"], [])
        self.assertEqual(items["design-kit"]["equipped"], ["producer", "builder"])
        self.assertEqual((items["design-kit"]["source"], items["design-kit"]["title"]), ("builtin", "디자인 도구"))
        self.assertLessEqual(len(items["design-kit"]["description"]), mcp.MAX_DESC)
        self.assertEqual([s["name"] for s in mcp.for_role(self.cfg, "analyst")], ["studio-records", "team-memory", "clock", "git-history"], "분석가에게는 디자인 도구를 붙이지 않는다")
        spec = next(s for s in mcp.for_role(self.cfg, "builder") if s["name"] == "team-memory")
        self.assertEqual(spec["args"][-2:], ["--who", self.cfg.roles["builder"].name or "builder"])
        self.assertIn(str(self.cfg.data_dir / "mcp" / "memory.json"), spec["args"])
        git_spec = next(s for s in mcp.for_role(self.cfg, "producer") if s["name"] == "git-history")
        self.assertIn(f"demo={self.s.repo.resolve()}", git_spec["args"])
        kit_spec = next(s for s in mcp.for_role(self.cfg, "producer") if s["name"] == "design-kit")
        self.assertEqual(kit_spec["args"][1:], ["--allow", str(self.s.repo.resolve()), "--allow", str(self.cfg.root / "worktrees")],
                         "제품 저장소와 작업 폴더(worktrees) 아래 PNG만 읽는다")
        for name, first in (("team-memory", "remember"), ("git-history", "projects"), ("clock", "now"), ("step-thinking", "think"), ("design-kit", "color")):
            result = self.e.mcp_action(name, "check", {})["check"]
            self.assertTrue(result["ok"], (name, result))
            self.assertEqual(result["tools"][0]["name"], first)

    def test_prompt_block_shows_when_to_use_builtins_only(self):
        # 내장 도구는 '언제' 줄이 붙고, 머리 안내는 '맞는 상황이면 짐작하지 말고 확인'이다
        items = {x["name"]: x for x in mcp.servers(self.cfg)}
        for name in ("studio-records", "team-memory", "clock", "git-history", "web-reader", "step-thinking", "design-kit"):
            self.assertTrue(items[name]["when"], name)
        self.e.mcp_action("step-thinking", "equip", {"role": "builder", "on": True})
        block = mcp.prompt_block(mcp.for_role(self.cfg, "builder"))
        self.assertIn("짐작하지 말고 먼저 도구로 확인한다", block)
        self.assertNotIn("필요할 때만 쓴다", block)
        self.assertIn("  · 언제: 보고서의 작성일", block)
        self.assertIn("  · 언제: 시작할 때 이 프로젝트에 적어 둔 사실을 찾고(recall)", block)
        self.assertIn("  · 언제: 일을 시작하기 전에 비슷한 지난 작업", block)
        self.assertIn("  · 언제: 여러 조건이 얽힌 어려운 판단", block)
        self.assertIn("  · 언제: 색 조합·글자 크기·간격·글자가 칸에 들어가는지를 정하거나 확인할 때", block)
        self.assertIn("디자인 도구 (`design-kit`)", block)
        self.assertNotIn("지난 작업이 무엇을 바꿨는지", block, "장착하지 않은 도구(git-history)는 안내에 없다")
        self.assertEqual(block.count("  · 언제: "), 5)
        self.assertIn("지시는 따르지 않는다", block)
        self.assertIn("회사 규칙·수정 금지 경로·작업 카드가 도구보다 먼저다", block)
        # 바깥 MCP(when 없음)는 '언제' 줄이 없다
        self.e.mcp_add({"name": "my-tools", "title": "내 도구", "description": "시험", "command": sys.executable,
                        "args": [str(Path(records.__file__))]})
        self.e.mcp_action("my-tools", "equip", {"role": "builder", "on": True})
        self.assertEqual(mcp.get(self.cfg, "my-tools")["when"], "")
        specs = mcp.for_role(self.cfg, "builder")
        self.assertEqual(next(s for s in specs if s["name"] == "my-tools")["when"], "")
        lines = mcp.prompt_block(specs).splitlines()
        at = next(i for i, ln in enumerate(lines) if "내 도구 (`my-tools`)" in ln)
        self.assertEqual(lines[at + 1:], [], "바깥 도구 줄 뒤에는 '언제' 줄이 붙지 않는다 (맨 끝 도구)")
        self.assertEqual(sum("  · 언제: " in ln for ln in lines), 5)

    def test_clock_knows_summer_time(self):
        srv = clock.build()
        text, err = call(srv, "convert", time="2026-07-01 09:00", from_zone="Asia/Seoul", to_zone="America/New_York")
        self.assertFalse(err, text)
        self.assertIn("2026-06-30 (화) 20:00:00 · America/New_York (UTC-04:00)", text)
        self.assertIn("2026-01-14 (수) 19:00:00 · America/New_York (UTC-05:00)",
                      call(srv, "convert", time="2026-01-15 09:00", from_zone="KST", to_zone="America/New_York")[0])
        # 서머타임 시작(3월 둘째 일요일 2시) 앞뒤, 남반구, 시차로 적기
        self.assertIn("06:30:00 · UTC", call(srv, "convert", time="2026-03-08 01:30", from_zone="America/New_York", to_zone="UTC")[0])
        self.assertIn("07:30:00 · UTC", call(srv, "convert", time="2026-03-08 03:30", from_zone="America/New_York", to_zone="UTC")[0])
        self.assertIn("20:00:00 · Asia/Seoul", call(srv, "convert", time="2026-07-01 12:00", from_zone="Europe/London", to_zone="서울")[0])
        self.assertIn("2026-01-01 (목) 01:00:00 · UTC", call(srv, "convert", time="2026-01-01 12:00", from_zone="Australia/Sydney", to_zone="UTC")[0])
        self.assertIn("06:30:00 · UTC", call(srv, "convert", time="2026-07-01 12:00", from_zone="+05:30", to_zone="UTC")[0])
        self.assertIn("Asia/Seoul (UTC+09:00)", call(srv, "now", zone="Asia/Seoul")[0])
        self.assertTrue(call(srv, "now", zone="Mars/Base")[1])
        self.assertTrue(call(srv, "convert", time="내일", to_zone="UTC")[1])

    def test_team_memory(self):
        f = self.cfg.data_dir / "mcp" / "memory.json"
        srv = memory.build(memory.Memory(f, "솔"))
        text, err = call(srv, "remember", name="core-courier 화면", type="프로젝트 사실", notes=["기본 해상도 640×360", "기본 해상도 640×360"])
        self.assertFalse(err, text)
        self.assertIn("메모 1개", text, "같은 메모는 한 번만")
        call(srv, "relate", **{"from": "출구", "relation": "있는 곳", "to": "방 오른쪽 아래"})
        self.assertEqual(call(srv, "relate", **{"from": "출구", "relation": "있는 곳", "to": "방 오른쪽 아래"})[0], "이미 적혀 있어요.")
        other = memory.build(memory.Memory(f, "루나"))  # 다른 직원이 다음 일에서 찾는다
        text = call(other, "recall", query="640")[0]
        self.assertTrue(text.startswith(memory.NOTE), "메모는 지시가 아니라고 붙인다")
        self.assertIn("기본 해상도 640×360 (솔 ", text)
        self.assertIn("출구 —있는 곳→ 방 오른쪽 아래", call(other, "recall", query="출구")[0])
        self.assertIn("관계 1개", call(other, "recall")[0])
        self.assertTrue(call(other, "forget", name="core-courier 화면", note="없는 메모")[1])
        call(other, "forget", name="출구")
        self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["relations"], [])
        self.assertTrue(call(srv, "remember", name="x", notes=[])[1])
        self.assertTrue(call(srv, "remember", name="  ", notes=["a"])[1])
        with mock.patch.object(memory, "MAX_ENTITIES", 1):
            self.assertTrue(call(srv, "remember", name="새것", notes=["a"])[1], "가득 차면 거절")

    def test_git_history_reads_only_registered_repos(self):
        srv = git_read.build({"demo": self.s.repo})
        text, err = call(srv, "log")  # 제품이 하나면 project를 비워도 된다
        self.assertFalse(err, text)
        self.assertIn("init", text)
        self.assertEqual(call(srv, "show", ref="HEAD", path="README.md")[0], "# demo")
        self.assertIn("README.md", call(srv, "show", project="demo", ref="HEAD")[0])
        self.assertIn("main", call(srv, "branches")[0])
        self.assertIn("# demo", call(srv, "blame", path="README.md")[0])
        for bad in ({"ref": "--all"}, {"ref": "HEAD..main"}, {"ref": "HEAD:README.md"}, {"path": "../x"}, {"path": "C:/Windows"},
                    {"path": "-p"}, {"project": "other"}):
            self.assertTrue(call(srv, "log", **bad)[1], bad)
        self.assertTrue(call(srv, "show", ref="HEAD", path="/etc/passwd")[1])
        self.assertTrue(all(t.read_only for t in srv.tools.values()))

    def test_step_thinking(self):
        srv = thinking.build()
        self.assertIn("1/3", call(srv, "think", thought="나눈다", step=1, total=3)[0])
        self.assertIn("갈래 b", call(srv, "think", thought="다른 길", step=2, total=3, branch="b", branch_from=1)[0])
        self.assertIn("생각 끝", call(srv, "think", thought="고침", step=3, total=3, revises=1, done=True)[0])
        self.assertIn("3/3 (고침→1): 고침", call(srv, "review")[0])
        self.assertTrue(call(srv, "think", thought="x", step=4, total=4, revises=9)[1])
        call(srv, "reset")
        self.assertEqual(call(srv, "review")[0], "아직 적은 생각이 없어요.")

    def test_dismissed_staff_is_unequipped(self):
        self.e.mcp_action("web-reader", "equip", {"role": "builder", "on": True})
        mcp.forget_role(self.cfg, "builder")
        self.assertNotIn("builder", next(x for x in mcp.servers(self.cfg) if x["name"] == "web-reader")["equipped"])

    @unittest.skipUnless(Path(GODOT).is_file(), "Godot가 없는 PC")
    def test_godot_docs(self):
        from studio.mcp_builtin import godot
        with tempfile.TemporaryDirectory(prefix="ais-gd-") as cache:
            srv = godot.build(godot.Docs(GODOT, Path(cache)))
            text, err = call(srv, "godot_class", name="CharacterBody2D", member="move_and_slide")
            self.assertFalse(err, text)
            self.assertIn("move_and_slide() -> bool", text)
            self.assertIn("CharacterBody2D.move_and_slide() -> bool", call(srv, "godot_search", query="move_and_sli")[0])
            self.assertTrue(call(srv, "godot_class", name="NoSuchClass")[1])
            self.assertTrue(call(srv, "godot_class", name="../x")[1])


ECHO_CODE = '''import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_base import Server, ToolError, setup_stdio

srv = Server("echo-tool", "1.0", "글을 그대로 돌려준다.")


@srv.tool("echo", "받은 글을 그대로 돌려준다.", {"text": {"type": "string"}}, ["text"])
def echo(text: str) -> str:
    return text


if __name__ == "__main__":
    setup_stdio()
    srv.serve()
'''
TOOL = {"name": "echo-tool", "title": "메아리", "description": "글을 그대로 돌려줘요.", "code": ECHO_CODE,
        "tools": [{"name": "echo", "description": "받은 글을 그대로"}], "reason": "시험용", "change": "", "skills_used": []}


class StaffTools(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine
        self.prompts = []
        self.answers = [TOOL]
        self.verdicts = ["approve"]

    def tearDown(self):
        self.s.close()

    def behavior(self, spec, runtime=None):
        self.prompts.append((spec.run_id, spec.prompt))
        if "-tool" in spec.run_id:
            return {"structured": self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]}
        if spec.run_id.endswith("-review"):
            v = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
            finding = [] if v == "approve" else [{"severity": "blocking", "file": "server.py:3", "issue": "위험", "suggestion": "고쳐"}]
            return {"structured": {"verdict": v, "summary": "좋음" if v == "approve" else "위험한 곳", "findings": finding, "skills_used": []}}
        return default_behavior(spec)

    def test_order_review_approve_install(self):
        with self.assertRaises(EngineError):
            self.e.order_tool("reviewer", "도구", "demo")
        with self.assertRaises(EngineError):
            self.e.order_tool("builder", " ", "demo")
        self.s.behavior = self.behavior
        task = self.e.order_tool("builder", "글을 그대로 돌려주는 도구", "demo")
        self.assertEqual((task.kind, task.status), ("tool", "queued"))
        self.assertEqual(self.e._next_job().id, task.id)
        self.e._run_tool(self.store.get(task.id))
        task = self.store.get(task.id)
        self.assertEqual(task.status, "awaiting_approval", task.blocked_reason)
        self.assertEqual((task.proposal["name"], task.review["verdict"]), ("echo-tool", "approve"))
        self.assertIn("MCP 만들기", self.prompts[0][1])
        self.assertIn("server.py", self.prompts[1][1])  # 리뷰는 코드를 읽는다
        self.assertFalse((mcp.staff_dir(self.cfg) / "echo-tool").exists(), "승인 전에는 설치(실행)하지 않는다")
        texts = [a["text"] for a in __import__("studio.company", fromlist=["alerts"]).alerts(self.cfg, self.store, self.store.list())]
        self.assertIn("새 도구(MCP)를 만들어 왔어요! 확인해 주세요", texts)
        self.e.approve(task.id, {"equip": ["builder", "reviewer"]})
        task = self.store.get(task.id)
        self.assertEqual(task.status, "done")
        item = mcp.get(self.cfg, "echo-tool")
        self.assertEqual((item["source"], item["equipped"], item["check"]["ok"]), ("staff", ["builder"], True))
        self.assertEqual([t["name"] for t in item["check"]["tools"]], ["echo"])
        self.assertTrue((mcp.staff_dir(self.cfg) / "echo-tool" / "mcp_base.py").is_file())
        self.assertIn("echo-tool", [s["name"] for s in mcp.for_role(self.cfg, "builder")])
        # 고쳐 오기: 옛 코드를 보여 주고, 설치하면 옛 판은 history로
        again = self.e.order_tool("analyst", "", "demo", target="echo-tool")
        self.e._run_tool(self.store.get(again.id))
        self.assertIn("## 고칠 도구: `echo-tool`", self.prompts[-2][1])
        self.assertIn('srv = Server("echo-tool"', self.prompts[-2][1])
        self.e.approve(again.id)
        self.assertEqual(len(list((self.cfg.data_dir / "mcp" / "history").iterdir())), 1)
        self.assertEqual(mcp.get(self.cfg, "echo-tool")["equipped"], ["builder"], "고쳐도 장착은 그대로")

    def test_review_rejects_twice_blocks(self):
        self.s.behavior = self.behavior
        self.verdicts = ["changes_requested"]
        task = self.e.order_tool("builder", "도구", "demo")
        self.e._run_tool(self.store.get(task.id))
        task = self.store.get(task.id)
        self.assertEqual(task.status, "blocked")
        self.assertIn("리뷰를 2번 통과하지 못했어요", task.blocked_reason)
        tool_prompts = [p for rid, p in self.prompts if "-tool" in rid]
        self.assertEqual(len(tool_prompts), 2)
        self.assertIn("위험 → 고쳐", tool_prompts[1], "두 번째에는 리뷰 지적을 고친다")
        self.assertEqual([x["kind"] for x in task.troubles], ["review", "review"])

    def test_bad_code_is_not_accepted(self):
        self.s.behavior = self.behavior
        self.answers = [{**TOOL, "code": "def broken(:\n"}]
        task = self.e.order_tool("builder", "도구", "demo")
        self.e._run_tool(self.store.get(task.id))
        task = self.store.get(task.id)
        self.assertEqual(task.status, "blocked")
        self.assertIn("문법 오류", task.blocked_reason)
        self.assertFalse(any(rid.endswith("-review") for rid, _ in self.prompts), "문법이 틀리면 리뷰도 부르지 않는다")

    def test_scan_and_clean(self):
        flags = mcp.scan_code("import subprocess\nx = open('a', 'w')\nprint(os.environ['GITHUB_TOKEN'])\n")
        self.assertTrue(flags[0].startswith("server.py:1 다른 프로그램 실행"))
        self.assertTrue(any("server.py:2 파일 쓰기" in f for f in flags))
        self.assertTrue(any("환경변수 읽기" in f for f in flags))
        clean, problems = mcp.clean_tool(self.cfg, {**TOOL, "name": "studio-records"})
        self.assertEqual(clean["name"], "studio-records-2")  # 내장과 겹치면 번호
        self.assertTrue(problems)
        self.assertIsNone(mcp.clean_tool(self.cfg, {**TOOL, "title": ""})[0])


class RuntimeWiring(unittest.TestCase):
    SPECS = [
        {"name": "files", "transport": "stdio", "command": r"C:\tools\npx.cmd", "args": ["-y", "pkg"], "url": "",
         "env": {"GH_TOKEN": "tok-1"}, "bearer_key": ""},
        {"name": "remote", "transport": "http", "command": "", "args": [], "url": "https://mcp.example.com/mcp",
         "env": {"API_TOKEN": "tok-2"}, "bearer_key": "API_TOKEN"},
    ]

    def test_codex_args_keep_tokens_off_the_command_line(self):
        args, env = codex_mcp_args(self.SPECS)
        joined = " ".join(args)
        self.assertNotIn("tok-1", joined)
        self.assertNotIn("tok-2", joined)
        self.assertEqual(env, {"GH_TOKEN": "tok-1", "API_TOKEN": "tok-2"})
        self.assertIn('mcp_servers.files.command="C:\\\\tools\\\\npx.cmd"', args)
        self.assertIn('mcp_servers.files.args=["-y", "pkg"]', args)
        self.assertIn('mcp_servers.files.env_vars=["GH_TOKEN"]', args)
        self.assertIn('mcp_servers.remote.url="https://mcp.example.com/mcp"', args)
        self.assertIn('mcp_servers.remote.bearer_token_env_var="API_TOKEN"', args)
        self.assertIn('shell_environment_policy.exclude=["API_TOKEN", "GH_TOKEN"]', args)
        self.assertEqual(codex_mcp_args([]), ([], {}))

    def _run(self, runtime, specs):
        seen = {}

        def fake_run(args, **kw):
            seen["args"], seen["env"] = list(args), kw.get("env") or {}
            if "--mcp-config" in args:
                path = args[args.index("--mcp-config") + 1]
                seen["config"] = json.loads(Path(path).read_text(encoding="utf-8"))
                seen["path"] = path
            return 0, None, 0.1

        runtime.info = {"found": True, "cmd": ["agent"]}
        with tempfile.TemporaryDirectory(prefix="ais-rt-") as d, mock.patch.object(runtimes, "run_process", fake_run):
            spec = RunSpec(run_id="R1-T1-build1", role="builder", prompt="p", cwd=Path(d), run_dir=Path(d) / "run", mcp=specs)
            runtime.run(spec, lambda: False)
        return seen

    def test_codex_gets_tokens_only_in_env(self):
        seen = self._run(CodexRuntime({}), self.SPECS)
        self.assertIn("--ignore-user-config", seen["args"])
        self.assertEqual((seen["env"]["GH_TOKEN"], seen["env"]["API_TOKEN"]), ("tok-1", "tok-2"))
        self.assertNotIn("tok-1", " ".join(seen["args"]))
        self.assertNotIn("OPENAI_API_KEY", seen["env"])

    def test_claude_gets_temp_config_that_is_deleted(self):
        seen = self._run(ClaudeRuntime({}), self.SPECS)
        self.assertIn("--strict-mcp-config", seen["args"])
        self.assertEqual(seen["args"][seen["args"].index("--allowedTools") + 1], "mcp__files,mcp__remote")
        self.assertEqual(seen["config"]["mcpServers"]["files"]["env"], {"GH_TOKEN": "tok-1"})
        self.assertEqual(seen["config"]["mcpServers"]["remote"]["headers"], {"Authorization": "Bearer tok-2"})
        self.assertFalse(os.path.exists(seen["path"]), "토큰이 든 임시 설정은 실행 뒤 지운다")
        self.assertNotIn("--mcp-config", self._run(ClaudeRuntime({}), [])["args"])
        self.assertEqual(claude_mcp_config([])["mcpServers"], {})


if __name__ == "__main__":
    unittest.main()
