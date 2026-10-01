"""신뢰 검증: 바뀐 글 파일 맨 앞의 보이지 않는 BOM(EF BB BF)을 찾아 알린다 (검증 결과 자체는 바꾸지 않는다).

실제 사고 (T0013, 2026-09-30): 직원이 쓴 보고서 맨 앞에 BOM이 붙어 검사가 '첫 줄은 # 제목이어야 합니다'로 두 번 떨어졌고,
메시지만 본 직원은 이유를 몰라 제목을 글자 그대로 '# 제목'으로 바꿨다.
"""

import tempfile
import unittest
from pathlib import Path

from studio import gitops
from studio.qa import BOM_MAX_FILES, find_bom_files, run_qa
from tests.helpers import TempStudio

BOM = "﻿"


def utf8(text: str) -> bytes:
    return text.encode("utf-8")  # 줄바꿈을 바꾸지 않고 바이트 그대로 (윈도우에서 write_text는 \n을 \r\n으로 바꾼다)


class BomFiles(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.repo = self.s.repo
        self.cfg = self.s.cfg
        self.project = self.cfg.projects["demo"]
        # 기준 커밋: BOM이 붙은 파일이 원래부터 둘 있다. 하나는 그대로 두고(안 바뀌면 알리지 않는다), 하나는 지운다.
        self.write("docs/old-bom.md", BOM + "# 옛 글\n")
        self.write("docs/gone.md", BOM + "# 지울 글\n")
        gitops.commit_all(self.repo, "base")
        self.base = gitops.head(self.repo)
        self.n = 0

    def tearDown(self):
        self.s.close()

    def write(self, rel: str, text: str | bytes) -> None:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text if isinstance(text, bytes) else utf8(text))

    def candidate(self, files: dict, delete: tuple = ()) -> str:
        for rel, text in files.items():
            self.write(rel, text)
        for rel in delete:
            (self.repo / rel).unlink()
        sha = gitops.commit_all(self.repo, "candidate")
        assert sha, "바뀐 것이 없다"
        return sha

    def qa(self, sha: str, **kw) -> dict:
        self.n += 1
        return run_qa(self.cfg, self.project, sha, self.s.root / "qa" / f"Q{self.n}", **kw)

    def test_reports_only_changed_text_files_with_a_bom(self):
        sha = self.candidate(
            {
                "docs/new-bom.md": BOM + "# 새 글\n",
                "docs/clean.md": "# BOM 없음\n",
                "docs/pic.png": b"\xef\xbb\xbf\x89PNG",  # 글 파일이 아니라서 보지 않는다
                "docs/sub/deep.gd": BOM + "extends Node\n",
                "docs/upper.MD": BOM + "# 대문자 확장자\n",
                "docs/한글 이름.md": BOM + "# 한글 파일\n",
                "docs/answer.txt": "42\n",
            },
            delete=("docs/gone.md",),
        )
        qa = self.qa(sha, base=self.base)
        self.assertEqual(qa["bom_files"], ["docs/new-bom.md", "docs/sub/deep.gd", "docs/upper.MD", "docs/한글 이름.md"])
        # 안 바뀐 파일(old-bom.md)·지운 파일(gone.md)·BOM 없는 파일·글 파일이 아닌 것은 안 들어간다
        self.assertNotIn("docs/old-bom.md", qa["bom_files"])
        self.assertNotIn("docs/gone.md", qa["bom_files"])

    def test_bom_does_not_change_the_verdict(self):
        good = self.qa(self.candidate({"docs/answer.txt": "42\n", "docs/note.md": BOM + "# 글\n"}), base=self.base)
        self.assertEqual(good["verdict"], "pass", good["reason"])
        self.assertEqual(good["bom_files"], ["docs/note.md"])
        bad = self.qa(self.candidate({"docs/answer.txt": "41\n"}), base=self.base)  # 앞 후보의 BOM 글도 아직 저장소에 있다
        self.assertEqual(bad["verdict"], "fail")
        self.assertEqual(bad["bom_files"], ["docs/note.md"], "실패한 검증에도 알림 정보는 실린다")

    def test_no_bom_means_no_key(self):
        qa = self.qa(self.candidate({"docs/answer.txt": "42\n", "docs/clean.md": "# 깨끗\n"}), base=self.base)
        self.assertEqual(qa["verdict"], "pass", qa["reason"])
        self.assertNotIn("bom_files", qa)

    def test_without_base_or_with_a_bad_base_it_stays_silent(self):
        sha = self.candidate({"docs/answer.txt": "42\n", "docs/new-bom.md": BOM + "# 새 글\n"})
        self.assertNotIn("bom_files", self.qa(sha), "기준 커밋을 모르면 보지 않는다")
        with tempfile.TemporaryDirectory() as snap:
            self.assertEqual(find_bom_files(self.repo, "0" * 40, sha, Path(snap)), [], "git이 못 읽는 기준이어도 조용히 빈 목록")
            self.assertEqual(find_bom_files(self.repo, None, sha, Path(snap)), [])
            self.assertEqual(find_bom_files(self.repo, self.base, "", Path(snap)), [])

    def test_selftest_overrides_skip_the_check(self):
        """자가 점검은 일부러 망가뜨린 파일을 끼워 넣어 돌린다: 그 파일들은 후보가 바꾼 것이 아니라서 BOM을 따지지 않는다."""
        sha = self.candidate({"docs/answer.txt": "42\n", "docs/new-bom.md": BOM + "# 새 글\n"})
        fixture = self.s.root / "fixture.txt"
        fixture.write_bytes(utf8(BOM + "41\n"))
        qa = self.qa(sha, base=self.base, overrides={"docs/answer.txt": fixture})
        self.assertNotIn("bom_files", qa)

    def test_at_most_twenty_files_are_listed(self):
        sha = self.candidate({f"docs/many/f{i:02d}.md": BOM + "# 글\n" for i in range(BOM_MAX_FILES + 5)})
        with tempfile.TemporaryDirectory() as snap:
            self.assertEqual(find_bom_files(self.repo, self.base, sha, Path(snap)), [], "스냅샷에 파일이 없으면 읽지 못해 건너뛴다")
        qa = self.qa(sha, base=self.base)
        self.assertEqual(len(qa["bom_files"]), BOM_MAX_FILES)
        self.assertEqual(qa["bom_files"][0], "docs/many/f00.md")


if __name__ == "__main__":
    unittest.main()
