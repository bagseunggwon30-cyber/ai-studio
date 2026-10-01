import unittest

from tests.helpers import ROOT  # noqa: F401  (sys.path 설정)
from studio.gitops import check_paths, matches_any, normalize_rel


class PathRules(unittest.TestCase):
    def test_globs(self):
        self.assertTrue(matches_any("src/core/run_state.gd", ["src/core/**"]))
        self.assertTrue(matches_any("src/core/a/b.gd", ["src/core/**"]))
        self.assertFalse(matches_any("src/player/p.gd", ["src/core/**"]))
        self.assertTrue(matches_any("docs/INTERFACES.md", ["docs/"]))
        self.assertTrue(matches_any("README.md", ["*.md"]))
        self.assertFalse(matches_any("docs/x.md", ["*.md"]))
        self.assertTrue(matches_any("a/b/c.md", ["**/*.md"]))
        self.assertTrue(matches_any("c.md", ["**/*.md"]))
        self.assertTrue(matches_any("AGENTS.md", ["agents.md"]))  # Windows는 대소문자 무시

    def test_normalize(self):
        self.assertEqual(normalize_rel("src\\core\\x.gd"), "src/core/x.gd")
        self.assertEqual(normalize_rel("./docs//a.md"), "docs/a.md")
        self.assertIsNone(normalize_rel("../outside.txt"))
        self.assertIsNone(normalize_rel("src/../../x"))
        self.assertIsNone(normalize_rel("C:/Windows/x"))
        self.assertIsNone(normalize_rel("/etc/passwd"))
        self.assertIsNone(normalize_rel(""))

    def test_check_paths(self):
        protected = [".git/**", "acceptance/**", "AGENTS.md"]
        v = check_paths(
            ["src/core/a.gd", "src/player/p.gd", "acceptance/run.gd", "AGENTS.md", "../x"],
            ["src/core/**", "acceptance/**"],
            protected,
        )
        reasons = {x["path"]: x["reason"] for x in v}
        self.assertNotIn("src/core/a.gd", reasons)
        self.assertEqual(reasons["src/player/p.gd"], "허용 경로 밖")
        self.assertEqual(reasons["acceptance/run.gd"], "보호된 경로")  # 허용 목록에 있어도 보호가 이긴다
        self.assertEqual(reasons["AGENTS.md"], "보호된 경로")
        self.assertEqual(reasons["../x"], "저장소 밖 경로")


if __name__ == "__main__":
    unittest.main()
