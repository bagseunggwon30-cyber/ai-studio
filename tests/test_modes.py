"""작업 모드(개발·디자인·소설 작성): 새 프로젝트 만들기, 파일 읽기, 모드별 작업 지침, 소설 스킬 조건, 시작 버튼, API."""
import json
import unittest
from pathlib import Path

from studio import gitops, modes, projects, prompts, skills
from studio.model import Task
from tests.helpers import TempStudio
from tests import test_server as server_tests


class ModeBasics(unittest.TestCase):
    def test_kinds_modes_labels_and_describe(self):
        self.assertEqual([modes.mode_of(k) for k in ("generic", "godot", "docs", "design", "novel", "", "알수없음")], ["dev", "dev", "dev", "design", "novel", "dev", "dev"])
        self.assertEqual(modes.task_label("novel", "build", "개발"), "집필")
        self.assertEqual(modes.task_label("design", "build", "개발"), "디자인")
        self.assertEqual(modes.task_label("godot", "build", "개발"), "개발", "개발 프로젝트는 이름을 바꾸지 않는다")
        d = modes.describe()
        self.assertEqual([m["id"] for m in d["modes"]], ["dev", "design", "novel"])
        self.assertEqual(set(d["kinds"]), set(modes.KINDS))
        self.assertEqual(set(d["templates"]), {"novel", "design"})
        self.assertTrue(all(k["creatable"] for kind, k in d["kinds"].items() if kind in ("novel", "design")))
        self.assertFalse(d["kinds"]["godot"]["creatable"])

    def test_guidance_only_for_novel_and_design(self):
        for kind in ("novel", "design"):
            for stage in ("plan", "build", "research", "review"):
                self.assertTrue(modes.guidance(kind, stage).strip(), (kind, stage))
        for kind in ("generic", "godot", "docs", ""):
            for stage in ("plan", "build", "research", "review"):
                self.assertEqual(modes.guidance(kind, stage), "")
        self.assertIn("notes/continuity.md", modes.guidance("novel", "build"))
        self.assertIn("4.5:1", modes.guidance("design", "build"))

    def test_templates_render_with_checks(self):
        text = modes.render_template("novel", "novel-next", {"length": "3000", "note": "주인공이 거짓말을 한다"})
        self.assertIn("3000", text)
        self.assertIn("주인공이 거짓말을 한다", text)
        self.assertIn("(정하지 않음", modes.render_template("novel", "novel-next", {"length": "3000"}), "빈 선택 칸은 알아서 정하게 한다")
        self.assertIn("{", modes.render_template("design", "design-brief", {"what": "포스터 {중괄호}"}), "입력한 글은 다시 해석하지 않는다")
        self.assertTrue(modes.render_template("novel", "novel-audit", {}))
        for kind, tid, values in (("novel", "novel-start", {}), ("novel", "novel-start", {"idea": "  "}), ("novel", "novel-start", {"idea": "x" * 1501}),
                                  ("novel", "nope", {}), ("godot", "novel-start", {"idea": "x"}), ("novel", "novel-next", {"length": "1", "bad": "x"}), ("novel", "novel-next", "글")):
            with self.assertRaises(ValueError, msg=(kind, tid, values)):
                modes.render_template(kind, tid, values)
        for kind in ("novel", "design"):
            for t in modes.templates(kind):
                fields = {f["key"]: (f.get("default") or "값") for f in t["fields"]}
                self.assertLessEqual(len(modes.render_template(kind, t["id"], fields)), 4000)

    def test_skeletons_use_plain_ascii_paths_and_cover_default_allowed_paths(self):
        for kind in ("novel", "design"):
            files = modes.skeleton(kind, "제목", "설명")
            self.assertTrue(all(p.isascii() and not p.startswith("/") and ".." not in p for p in files), kind)
            allowed = modes.DEFAULT_PATHS[kind]
            for path in files:
                self.assertTrue(gitops.matches_any(path, allowed), (kind, path))
            self.assertIn("제목", files["README.md"])
        with self.assertRaises(ValueError):
            modes.skeleton("godot", "x")


class ProjectCreation(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.cfg = self.s.cfg

    def tearDown(self):
        self.s.close()

    def make(self, key="my-novel", kind="novel", **extra):
        return self.s.engine.create_project({"key": key, "title": "비 오는 날의 서점", "kind": kind, "description": "동네 서점 이야기", **extra})

    def test_creates_registered_repo_with_skeleton_and_default_paths(self):
        project = self.make()
        self.assertEqual((project.key, project.kind), ("my-novel", "novel"))
        self.assertIn("my-novel", self.cfg.projects)
        self.assertEqual(project.default_allowed_paths, modes.DEFAULT_PATHS["novel"])
        self.assertTrue(gitops.is_repo(project.repo) and gitops.ref_exists(project.repo, "refs/heads/main"))
        self.assertTrue(gitops.is_clean(project.repo))
        self.assertTrue((project.repo / "bible" / "premise.md").is_file())
        toml = (self.s.root / "trusted" / "projects" / "my-novel.toml").read_text(encoding="utf-8")
        self.assertIn('kind = "novel"', toml)
        self.assertNotIn("[qa]", toml, "자동 검증 명령은 만들지 않는다")
        design = self.make("my-design", "design")
        self.assertTrue((design.repo / "brief" / "brief.md").is_file())

    def test_rejects_bad_input_and_duplicates(self):
        for data in ({"key": "A", "title": "x", "kind": "novel"}, {"key": "ok", "title": "", "kind": "novel"}, {"key": "ok", "title": "x" * 81, "kind": "novel"},
                     {"key": "ok", "title": "x", "kind": "godot"}, {"key": "ok", "title": "x", "kind": "novel", "description": "d" * 1001},
                     {"key": "ok", "title": "x", "kind": "novel", "repo": "S:/x"}, {"key": "ok", "title": "x", "kind": "novel", "qa": {}}, {"key": "demo", "title": "x", "kind": "novel"}, "문자열"):
            with self.assertRaises((ValueError, TypeError), msg=data):
                self.s.engine.create_project(data)
        self.make("dup")
        with self.assertRaises(ValueError):
            self.make("dup")
        (self.s.root / "projects" / "taken").mkdir()
        with self.assertRaises(ValueError):
            self.make("taken")
        self.assertNotIn("taken", self.cfg.projects)
        with self.assertRaises(Exception):
            self.s.engine.create_project({"key": "other", "title": "x", "kind": "novel"}, by="agent")

    def test_register_accepts_design_and_novel_kinds_for_existing_repos(self):
        repo = self.s.root / "projects" / "old-novel"
        gitops.init_repo(repo, "main")
        (repo / "chapters").mkdir()
        (repo / "chapters" / "001.md").write_text("# 제1장\n", encoding="utf-8")
        gitops.commit_all(repo, "init")
        project = self.s.engine.register_project({"key": "old-novel", "title": "옛 원고", "kind": "novel", "repo": str(repo), "main_branch": "main",
                                                  "allowed_paths": ["chapters/**"], "confirm_scope": True})
        self.assertEqual(project.kind, "novel")

    def test_tree_and_file_reading_are_limited_to_listed_text_and_images(self):
        project = self.make()
        repo = project.repo
        (repo / "bible" / "big.md").write_text("가" * (projects.MAX_TEXT_BYTES + 10), encoding="utf-8")
        (repo / "chapters" / "001.md").write_text("# 제1장 시작\n본문", encoding="utf-8")
        (repo / "assets").mkdir(exist_ok=True)
        (repo / "assets" / "cover.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", encoding="utf-8")
        (repo / "assets" / "tool.exe").write_bytes(b"MZ")
        (repo / "screens").mkdir(exist_ok=True)
        (repo / "screens" / "a.html").write_text("<script>x</script>", encoding="utf-8")
        gitops.commit_all(repo, "files")
        names = {r["path"]: r for r in projects.tree(self.cfg, "my-novel")}
        self.assertIn("chapters/001.md", names)
        self.assertEqual(names["assets/cover.svg"]["kind"], "text", "SVG는 글로도 읽히고")
        self.assertNotIn("assets/tool.exe", names)
        self.assertNotIn("bible/big.md", names, "너무 큰 글은 목록에서 뺀다")
        self.assertFalse(any(p.startswith(".git") for p in names))
        self.assertEqual(projects.read_text(self.cfg, "my-novel", "chapters/001.md")["text"], "# 제1장 시작\n본문")
        for bad in ("../x", "/etc/passwd", "C:/Windows/win.ini", "chapters/missing.md", "assets/tool.exe", "bible/big.md", ".git/config", "", None, "chapters/../README.md"):
            with self.assertRaises(ValueError, msg=bad):
                projects.read_text(self.cfg, "my-novel", bad)
        data, ctype = projects.read_raw(self.cfg, "my-novel", "assets/cover.svg")
        self.assertEqual(ctype, "image/svg+xml")
        for bad in ("screens/a.html", "chapters/001.md", "assets/tool.exe", "../README.md"):
            with self.assertRaises(ValueError, msg=bad):
                projects.read_raw(self.cfg, "my-novel", bad)
        for key in ("nope", "../demo", None):
            with self.assertRaises(ValueError):
                projects.tree(self.cfg, key)

    def test_reads_only_the_main_branch_not_uncommitted_files(self):
        project = self.make()
        (project.repo / "chapters" / "002.md").write_text("커밋 안 한 글", encoding="utf-8")
        self.assertNotIn("chapters/002.md", {r["path"] for r in projects.tree(self.cfg, "my-novel")})


class PromptsAndSkills(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.cfg = self.s.cfg

    def tearDown(self):
        self.s.close()

    def task(self, project, kind="build"):
        return Task(id="T0001", title="제1장 쓰기", kind=kind, role="builder", project=project, status="ready", brief="첫 장을 쓴다",
                    acceptance=["파일이 있다"], allowed_paths=["chapters/001.md"])

    def test_novel_and_design_projects_get_mode_guidance_in_every_stage(self):
        for key, kind, mark in (("n1", "novel", "소설"), ("d1", "design", "디자인")):
            project = self.s.engine.create_project({"key": key, "title": "작품", "kind": kind})
            plan = prompts.plan_prompt(self.cfg, self.task(key, "plan"), project, [])
            build = prompts.build_prompt(self.cfg, self.task(key), project, 1, "")
            research = prompts.build_prompt(self.cfg, self.task(key, "research"), project, 1, "", role="analyst")
            review = prompts.review_prompt(self.cfg, self.task(key), project, "diff", False, None)
            for stage, text in (("plan", plan), ("build", build), ("research", research), ("review", review)):
                guidance = modes.guidance(kind, stage).strip()
                self.assertIn(guidance[:30], text, (kind, stage))
                self.assertIn(mark, guidance)
            self.assertIn("README.md", plan)
        self.assertIn("한 줄 소개", prompts.project_context(self.cfg, self.cfg.projects["n1"]))

    def test_development_prompts_are_unchanged(self):
        project = self.cfg.projects["demo"]
        for text in (prompts.plan_prompt(self.cfg, self.task("demo", "plan"), project, []), prompts.build_prompt(self.cfg, self.task("demo"), project, 1, ""),
                     prompts.review_prompt(self.cfg, self.task("demo"), project, "diff", False, None)):
            for stage in ("plan", "build", "research", "review"):
                self.assertNotIn("이 프로젝트는 소설", text)
                self.assertNotIn("이 프로젝트는 디자인", text)

    def test_novel_skill_condition_applies_only_to_novel_projects(self):
        self.s.engine.create_project({"key": "n2", "title": "작품", "kind": "novel"})
        story = skills.Skill("story", "소설 요령", "설명", "본문", ["builder"], "ceo", "2026-10-06")
        story.kinds = ["build", "novel"]
        self.assertTrue(skills.in_scope(story, "n2", "build", "제1장 쓰기", "novel"))
        self.assertFalse(skills.in_scope(story, "demo", "build", "제1장 쓰기", "generic"), "개발 프로젝트에는 안 붙는다")
        self.assertTrue(skills.in_scope(story, "", "build", "제1장 쓰기"), "프로젝트를 모르면 보이는 대로")
        self.assertFalse(skills.in_scope(story, "n2", "plan", "제1장 쓰기", "novel"), "build만 골랐으니 기획에는 안 붙는다")
        only = skills.Skill("only", "조건만", "설명", "본문", ["builder"], "ceo", "2026-10-06")
        only.kinds = ["novel"]
        self.assertTrue(skills.in_scope(only, "n2", "review", "x", "novel"))
        self.assertFalse(skills.in_scope(only, "demo", "build", "x", "generic"))
        self.assertFalse(skills.in_scope(only, "n2", "study", "x", "novel"), "공부·MCP는 골라 둔 스킬만")

    def test_design_projects_count_every_task_as_design_work(self):
        design = skills.Skill("look", "디자인 요령", "설명", "본문", ["builder"], "ceo", "2026-10-06")
        design.kinds = ["build", "design"]
        self.assertFalse(skills.in_scope(design, "demo", "build", "문서 정리", "generic"), "개발 프로젝트는 글을 본다")
        self.assertTrue(skills.in_scope(design, "d2", "build", "문서 정리", "design"), "디자인 프로젝트의 일은 모두 디자인 일")
        self.assertTrue(skills.in_scope(design, "demo", "build", "화면 디자인 버튼 색", "generic"))

    def test_company_novel_skills_are_installed_and_scoped(self):
        root = Path(__file__).resolve().parents[1]
        from studio.config import load_config
        cfg = load_config(root)
        found = {s.slug: s for s in skills.list_skills(cfg) if "novel" in s.kinds}
        self.assertEqual(set(found), {"novel-planning", "chapter-drafting", "character-voice", "prose-editing", "continuity-ledger", "manuscript-review-checklist"})
        self.assertIn("producer", found["novel-planning"].learned_by)
        self.assertIn("reviewer", found["manuscript-review-checklist"].learned_by)
        for s in found.values():
            self.assertTrue(200 < len(s.body) <= skills.MAX_BODY and s.projects == [], s.slug)


class TrophyAndStart(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()

    def tearDown(self):
        self.s.close()

    def done_task(self, key):
        return self.s.store.create_task(title="제1장 쓰기", kind="build", role="builder", project=key, status="done", brief="b")

    def test_novel_trophy_only_for_novel_projects(self):
        self.s.engine.create_project({"key": "n3", "title": "작품", "kind": "novel"})
        ok, other = self.done_task("n3"), self.done_task("demo")
        self.assertEqual(self.s.engine.add_trophy(ok.id, "novel")["kind"], "novel")
        with self.assertRaises(Exception):
            self.s.engine.add_trophy(other.id, "novel")
        with self.assertRaises(Exception):
            self.s.engine.add_trophy(other.id, "poem")

    def test_start_button_becomes_a_plan_directive(self):
        self.s.engine.create_project({"key": "n4", "title": "작품", "kind": "novel"})
        text = modes.render_template("novel", "novel-start", {"idea": "서점에 책 주인이 찾아온다"})
        task = self.s.engine.submit_directive(text, "n4", extra={"template": "novel-start"})
        self.assertEqual((task.kind, task.status, task.project), ("plan", "queued", "n4"))
        self.assertIn("서점에 책 주인이 찾아온다", task.brief)


class ModeApi(unittest.TestCase):
    setUp = server_tests.ServerSecurity.setUp
    tearDown = server_tests.ServerSecurity.tearDown
    req = server_tests.ServerSecurity.req

    def post(self, path, body):
        return self.req("POST", path, body, {"X-Studio-Token": self.srv.token})

    def test_modes_endpoint_and_create_read_start_flow(self):
        res, raw = self.req("GET", "/api/modes")
        self.assertEqual(res.status, 200)
        self.assertEqual({m["id"] for m in json.loads(raw)["modes"]}, {"dev", "design", "novel"})
        body = {"key": "api-novel", "title": "API 작품", "kind": "novel", "description": "시험"}
        self.assertEqual(self.req("POST", "/api/projects/new", body)[0].status, 403, "토큰 없이는 못 만든다")
        res, raw = self.post("/api/projects/new", body)
        self.assertEqual(res.status, 200, raw)
        self.assertEqual(self.post("/api/projects/new", body)[0].status, 400, "같은 ID는 다시 못 만든다")
        self.assertEqual(self.post("/api/projects/new", {**body, "key": "api-dev", "kind": "godot"})[0].status, 400)
        res, raw = self.req("GET", "/api/projects/api-novel/tree")
        files = [f["path"] for f in json.loads(raw)["files"]]
        self.assertIn("bible/premise.md", files)
        res, raw = self.req("GET", "/api/projects/api-novel/file?path=bible/premise.md")
        self.assertEqual(res.status, 200)
        self.assertIn("한 줄 소개", json.loads(raw)["text"])
        for bad in ("/api/projects/api-novel/file?path=../trusted/projects/demo.toml", "/api/projects/api-novel/file?path=missing.md", "/api/projects/nope/tree", "/api/projects/api-novel/raw?path=bible/premise.md"):
            self.assertEqual(self.req("GET", bad)[0].status, 404, bad)
        repo = self.s.cfg.projects["api-novel"].repo
        (repo / "assets").mkdir(exist_ok=True)
        (repo / "assets" / "c.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", encoding="utf-8")
        gitops.commit_all(repo, "svg")
        res, raw = self.req("GET", "/api/projects/api-novel/raw?path=assets/c.svg")
        self.assertEqual(res.status, 200)
        self.assertEqual(res.getheader("Content-Type"), "image/svg+xml")
        csp = res.getheaders()
        self.assertTrue(any(k.lower() == "content-security-policy" and "sandbox" in v for k, v in csp), "SVG는 별도 제한 헤더로 내준다")
        self.assertEqual(self.post("/api/modes/start", {"project": "api-novel", "template": "novel-start", "values": {"idea": ""}})[0].status, 400)
        self.assertEqual(self.post("/api/modes/start", {"project": "demo", "template": "novel-start", "values": {"idea": "x"}})[0].status, 400, "소설 시작 버튼은 개발 프로젝트에 못 쓴다")
        self.assertEqual(self.post("/api/modes/start", {"project": "nope", "template": "novel-start", "values": {}})[0].status, 404)
        res, raw = self.post("/api/modes/start", {"project": "api-novel", "template": "novel-start", "values": {"idea": "서점 이야기"}})
        self.assertEqual(res.status, 200, raw)
        task = self.s.store.get(json.loads(raw)["task"])
        self.assertEqual((task.kind, task.project), ("plan", "api-novel"))
        self.assertIn("서점 이야기", task.brief)
        self.assertEqual(task.title, "작품 기획 시작", "시작 버튼은 버튼 이름을 일 제목으로 쓴다")
        state = json.loads(self.req("GET", "/api/state")[1])
        self.assertIn("novel", {p["kind"] for p in state["projects"]})


if __name__ == "__main__":
    unittest.main()
