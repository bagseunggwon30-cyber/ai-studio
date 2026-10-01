"""업무 카드와 스킬 성적표 (CEO 요청 B, 2026-09-29): 무슨 일을 하는 에이전트인지, 스킬이 얼마나 효과 있는지 (실제 기록만)."""

import unittest

from tests.helpers import TempStudio
from studio import company, skills
from studio.model import Task


def done_task(tid: str, role: str, at: str, *, trouble: bool = False, ceo: bool = False) -> Task:
    t = Task(id=tid, title=tid, kind="build", role=role, project="p", status="done")
    t.history = [{"to": "done", "at": at}]
    if trouble:
        t.troubles = [{"kind": "qa"}]
    if ceo:
        t.feedback = [{"by": "ceo", "text": "고쳐 주세요"}]
    return t


class JobCard(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine

    def tearDown(self):
        self.s.close()

    def test_card_comes_from_role_doc_and_settings(self):
        (self.cfg.root / "company" / "roles").mkdir(parents=True, exist_ok=True)
        (self.cfg.root / "company" / "roles" / "builder.md").write_text("## 개발\n\n**임무:** 작업 카드 하나를 `허용된 경로` 안에서 구현한다.\n", encoding="utf-8")
        self.cfg.roles["builder"].sandbox = "workspace-write"
        self.cfg.roles["builder"].web_search = False
        card = company.job_card(self.cfg, "builder")
        self.assertEqual(card["mission"], "작업 카드 하나를 허용된 경로 안에서 구현한다.")
        self.assertIn("프로젝트 파일을 고칠 수 있어요 (작업마다 허용된 폴더만)", card["can"])
        self.assertIn("인터넷 검색은 하지 않아요", card["can"])
        self.assertTrue(any("acceptance" in x for x in card["cannot"]))
        self.cfg.roles["reviewer"].sandbox = "read-only"
        self.assertIn("파일은 읽기만 해요", company.job_card(self.cfg, "reviewer")["can"])
        team = {m["key"]: m for m in company.team(self.cfg, self.store, [], None)}
        self.assertEqual(team["builder"]["card"]["mission"], card["mission"])

    def test_skill_report_splits_before_and_after_learning(self):
        sk = self.e.teach_skill({"name": "tidy", "title": "정리", "description": "정리할 때", "body": "짧게", "learned_by": ["builder"]})
        since = next(e for e in self.store.recent_events(10) if e["type"] == "skill.learned")["at"]
        early, late = "2000-01-01T00:00:00", "2999-01-01T00:00:00"
        tasks = [
            done_task("A", "builder", early, trouble=True), done_task("B", "builder", early), done_task("C", "builder", early, ceo=True),
            done_task("D", "builder", late), done_task("E", "builder", late), done_task("F", "builder", late, trouble=True),
            done_task("G", "analyst", late),
        ]
        # 따른 스킬: D는 따랐다고 알림, E는 안 따랐다고 알림, G는 설명만 붙었는데 따랐다고 알림, 옛 기록은 알림 없음(None)
        runs = [{"task": "D", "role": "builder", "skills": [f"{sk.slug}@1"], "skills_applied": [sk.slug]},
                {"task": "E", "role": "builder", "skills": [sk.slug], "skills_applied": []},
                {"task": "G", "role": "analyst", "skills": [], "skills_brief": [f"{sk.slug}@1"], "skills_applied": [sk.slug]},
                {"task": "Z", "role": "builder", "skills": [], "skills_brief": [f"{sk.slug}@1"], "skills_applied": None}]
        report = company.skill_report(self.cfg, self.store, skills.list_skills(self.cfg), tasks, runs)
        self.assertEqual(len(report), 1)
        row = report[0]
        self.assertEqual(row["usage"], {"runs": 2, "told": 3, "applied": 2, "tasks": 2, "smooth": 2})
        (who,) = row["learners"]
        self.assertEqual((who["role"], who["since"]), ("builder", since[:10]))
        self.assertEqual(who["before"], {"tasks": 3, "smooth": 1}, "A는 걸림, C는 CEO 수정 요청")
        self.assertEqual(who["after"], {"tasks": 3, "smooth": 2})


if __name__ == "__main__":
    unittest.main()
