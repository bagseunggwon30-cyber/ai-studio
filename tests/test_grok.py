"""Grok 그림 실행기 (CEO 요청 E, 2026-09-29): 가짜 grok 프로그램으로 확인한다 (진짜 Grok 사용량을 쓰지 않는다).

진짜 grok 1.0.40에서 확인한 동작을 흉내 낸다: --output-format json의 text·sessionId, 그림은
<sessions>/<작업 폴더 인코딩>/<sessionId>/images/1.jpg. 여기서는 PNG로 둔다 (JPG→PNG는 wardrobe.to_png가 Godot으로).
"""

import json
import sys
import textwrap
import unittest
from pathlib import Path

from tests.helpers import TempStudio
from studio import wardrobe
from studio.runtimes import GROK_IMAGE_TOOLS, GrokRuntime, RunSpec
from studio.util import API_KEY_VARS, clean_child_env

FAKE_GROK = textwrap.dedent('''
    import json, os, shutil, sys, uuid
    from pathlib import Path
    args = sys.argv[1:]
    get = lambda flag: args[args.index(flag) + 1] if flag in args else ""
    log = Path(os.environ["FAKE_GROK_LOG"])
    log.write_text(json.dumps({"args": args, "xai": os.environ.get("XAI_API_KEY"), "cwd": os.getcwd(),
                               "prompt": Path(get("--prompt-file")).read_text(encoding="utf-8"),
                               "files": sorted(os.listdir(get("--cwd")))}), encoding="utf-8")
    if os.environ.get("FAKE_GROK_MODE") == "login":
        print("You are not authenticated.", file=sys.stderr)
        sys.exit(5)
    session = str(uuid.uuid4())
    if os.environ.get("FAKE_GROK_MODE") != "noimage":
        images = Path(os.environ["FAKE_GROK_SESSIONS"]) / "C%3A%5Cwork" / session / "images"
        images.mkdir(parents=True)
        ref = Path(get("--cwd")) / "ref-1.png"
        shutil.copyfile(ref, images / "1.png")
    print(json.dumps({"text": "done", "stopReason": "end_turn", "sessionId": session, "num_turns": 2}))
''')


class Grok(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.root = self.s.root
        self.script = self.root / "fake_grok.py"
        self.script.write_text(FAKE_GROK, encoding="utf-8")
        self.sessions = self.root / "grok-sessions"
        self.log = self.root / "grok-log.json"
        self.ref = self.root / "ref.png"
        self.ref.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def tearDown(self):
        self.s.close()

    def runtime(self) -> GrokRuntime:
        rt = GrokRuntime({"sessions_dir": str(self.sessions)})
        rt.info = {"found": True, "cmd": [sys.executable, str(self.script)], "version": "grok 0.0.0 (가짜)"}
        return rt

    def spec(self, **kw) -> RunSpec:
        base = {"run_id": "T0001-look-sheet", "role": "builder", "prompt": "Draw it.", "cwd": self.root,
                "run_dir": self.root / "runs" / "r1", "images": [self.ref], "want_image": True, "timeout_s": 60}
        return RunSpec(**{**base, **kw})

    def env(self, mode=""):
        import os
        os.environ.update({"FAKE_GROK_LOG": str(self.log), "FAKE_GROK_SESSIONS": str(self.sessions), "FAKE_GROK_MODE": mode,
                           "XAI_API_KEY": "should-not-pass"})
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("FAKE_GROK_LOG", "FAKE_GROK_SESSIONS", "FAKE_GROK_MODE", "XAI_API_KEY")])

    def test_image_run_finds_session_image_and_limits_tools(self):
        self.env()
        result = self.runtime().run(self.spec(), lambda: False)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(result.images), 1)
        self.assertTrue(result.images[0].endswith("1.png"))
        seen = json.loads(self.log.read_text(encoding="utf-8"))
        args = seen["args"]
        self.assertEqual(args[args.index("--tools") + 1], GROK_IMAGE_TOOLS, "그림 도구와 파일 읽기만")
        self.assertEqual(args[args.index("--output-format") + 1], "json")
        for bad in ("--always-approve", "--yolo", "bypassPermissions", "--permission-mode"):
            self.assertNotIn(bad, args, "승인 우회 플래그를 쓰지 않는다")
        self.assertIsNone(seen["xai"], "API 키는 넘기지 않는다")
        self.assertEqual(seen["files"], ["ref-1.png"], "참고 그림은 작업 폴더에 복사")
        self.assertIn("ref-1.png (FIRST)", seen["prompt"])
        self.assertTrue(Path(seen["cwd"]).name == "grok")

    def test_login_and_missing_image(self):
        self.env("login")
        result = self.runtime().run(self.spec(), lambda: False)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "login")
        self.env("noimage")
        result = self.runtime().run(self.spec(run_dir=self.root / "runs" / "r2"), lambda: False)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "그림이 만들어지지 않았습니다.")

    def test_text_work_is_refused_and_session_ids_are_checked(self):
        result = self.runtime().run(self.spec(want_image=False), lambda: False)
        self.assertFalse(result.ok)
        rt = self.runtime()
        self.assertEqual(rt.session_images("../../etc"), [])
        self.assertEqual(rt.session_images("*"), [])

    def test_keys_are_stripped_and_draw_ai_is_checked(self):
        self.assertIn("XAI_API_KEY", API_KEY_VARS)
        import os
        os.environ["XAI_API_KEY"] = "x"
        self.addCleanup(lambda: os.environ.pop("XAI_API_KEY", None))
        self.assertNotIn("XAI_API_KEY", clean_child_env())
        self.assertEqual([wardrobe.draw_ai(x) for x in ("grok", "codex", "gpt", None)], ["grok", "codex", "codex", "codex"])
        (self.root / "tools" / "sprites").mkdir(parents=True, exist_ok=True)
        (self.root / "tools" / "sprites" / "sheets.json").write_text(
            (Path(__file__).resolve().parents[1] / "tools" / "sprites" / "sheets.json").read_text(encoding="utf-8"), encoding="utf-8")
        t = self.s.engine.order_outfit("builder", "코트", "코트", draw="grok")
        self.assertEqual(t.extra["draw"], "grok")
        # 막힌 그림 작업은 Codex로 다시 그릴 수 있다
        self.s.store.block(self.s.store.get(t.id), "Grok 그림을 자르지 못했어요")
        again = self.s.engine.redraw_with(t.id, "codex")
        self.assertEqual((again.extra["draw"], again.status), ("codex", "queued"))


if __name__ == "__main__":
    unittest.main()
