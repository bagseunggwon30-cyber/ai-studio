"""AI 탑재: 직원마다 끼울 AI(실행기·모델·생각 깊이)를 CEO가 고른다. 목록 밖 값·규칙 위반은 거절한다."""

import unittest

from tests.helpers import TempStudio, default_behavior
from studio import ai
from studio.engine import Engine, EngineError

CATALOG = [
    {"slug": "gpt-6-sol", "name": "GPT-6-Sol", "efforts": ["low", "medium", "high", "ultra"], "default_effort": "medium", "desc": ""},
    {"slug": "gpt-6-luna", "name": "GPT-6-Luna", "efforts": ["low", "medium", "high"], "default_effort": "medium", "desc": ""},
]


class AILoading(unittest.TestCase):
    def setUp(self):
        ai._cache["codex"] = [dict(m) for m in CATALOG]  # 테스트에서는 CLI를 부르지 않는다
        self.s = TempStudio()
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine

    def tearDown(self):
        self.s.close()
        ai._cache.clear()

    def test_rules(self):
        with self.assertRaises(EngineError):
            self.e.set_ai("builder", {"runtime": "codex", "model": "gpt-9-made-up"})  # 목록에 없는 모델
        with self.assertRaises(EngineError) as ctx:
            self.e.set_ai("builder", {"runtime": "claude", "model": "opus"})  # 파일을 고치는 일에 Claude
        self.assertIn("Codex만", str(ctx.exception))
        with self.assertRaises(EngineError):
            self.e.set_ai("builder", {"runtime": "codex", "model": "gpt-6-luna", "effort": "ultra"})  # 모델이 못 쓰는 깊이
        with self.assertRaises(EngineError):
            self.e.set_ai("producer", {"runtime": "shell", "model": ""})
        with self.assertRaises(EngineError):
            self.e.set_ai("nobody", {"runtime": "codex", "model": ""})
        # 읽기만 하는 일(기획)에는 Claude를 끼울 수 있다. 샌드박스는 그대로
        self.s.cfg.runtimes.setdefault("claude", {})["enabled"] = True
        self.e.set_ai("producer", {"runtime": "claude", "model": "fable", "effort": "high"})
        r = self.cfg.roles["producer"]
        self.assertEqual((r.runtime, r.model, r.effort, r.sandbox), ("claude", "fable", "high", "read-only"))

    def test_saved_value_survives_restart_and_resets(self):
        before = ai.current(self.cfg, "builder")
        self.e.set_ai("builder", {"runtime": "codex", "model": "gpt-6-sol", "effort": "ultra"})
        self.assertEqual(self.store.read_doc("ai", {})["builder"]["effort"], "ultra")
        # 다시 켜면 (새 설정 + 새 엔진) 저장된 AI가 끼워진다
        from studio.config import load_config
        cfg2 = load_config(self.s.root)
        Engine(cfg2, self.store, runtime_factory=self.s._runtime)
        self.assertEqual(ai.current(cfg2, "builder"), {"runtime": "codex", "model": "gpt-6-sol", "effort": "ultra"})
        # 처음대로
        self.e.reset_ai("builder")
        self.assertEqual(ai.current(self.cfg, "builder"), before)
        self.assertNotIn("builder", self.store.read_doc("ai", {}))

    def test_run_uses_new_model(self):
        seen = []

        def behavior(spec, runtime=None):
            seen.append((spec.role, runtime, spec.model, spec.effort))
            return default_behavior(spec)

        self.s.behavior = behavior
        self.e.set_ai("builder", {"runtime": "codex", "model": "gpt-6-luna", "effort": "low"})
        t = self.e.create_task({"project": "demo", "kind": "build", "title": "정답", "brief": "42", "acceptance": ["a"], "allowed_paths": ["docs/**"]})
        self.e._run_build(self.store.get(t.id))
        self.assertIn(("builder", "codex", "gpt-6-luna", "low"), seen)
        runs = [r for r in self.store.runs(t.id) if r["role"] == "builder"]
        self.assertEqual(runs[0]["model"], "gpt-6-luna")

    def test_options(self):
        opts = ai.options(self.cfg)
        self.assertEqual([m["slug"] for m in opts["codex"]], ["gpt-6-sol", "gpt-6-luna"])
        self.assertEqual(opts["claude"], [])
        self.assertIn("claude",opts["unavailable"])
        self.assertEqual(opts["writes"], {"producer": False, "builder": True, "reviewer": False, "analyst": True})


if __name__ == "__main__":
    unittest.main()
