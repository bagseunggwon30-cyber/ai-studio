"""신뢰 검사: reports/*.md 보고서의 형식과 출처 표기를 확인한다.

감독 프로그램이 후보 스냅샷에서 실행한다. 내용이 맞는지는 리뷰어와 CEO가 판단하고,
여기서는 '출처 없는 주장', '빠진 섹션', '미완성 표시' 같은 형식 문제만 잡는다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED = ["## 결론 요약", "## 핵심 주장", "## 출처", "## 미확인·한계"]
# - [S1] 제목 — https://… (확인 2026-09-28)
SOURCE_RE = re.compile(r"\[(S\d+)\][^\n]*?(https?://[^\s)]+)[^\n]*?(\d{4}-\d{2}-\d{2})")


def section(text: str, heading: str) -> str:
    if heading not in text:
        return ""
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def check(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    name = path.name
    tests: list[dict] = []

    def add(test: str, ok: bool, msg: str = "") -> None:
        tests.append({"name": f"{name}: {test}", "ok": ok, "message": "" if ok else msg})

    add("제목", text.lstrip().startswith("# "), "첫 줄은 '# 제목'이어야 합니다.")
    missing = [h for h in REQUIRED if h not in text]
    add("필수 섹션", not missing, "빠진 섹션: " + ", ".join(missing))
    sources = {m.group(1): m.group(2) for m in SOURCE_RE.finditer(section(text, "## 출처"))}
    add("출처 3개 이상", len(sources) >= 3, f"형식에 맞는 출처가 {len(sources)}개입니다. 형식: '- [S1] 제목 — URL (확인 YYYY-MM-DD)'")
    cited = set(re.findall(r"\[(S\d+)\]", section(text, "## 핵심 주장")))
    add("핵심 주장에 출처 번호", bool(cited), "핵심 주장마다 [S1] 같은 출처 번호를 붙이세요.")
    unknown = sorted(cited - set(sources))
    add("출처 번호 일치", not unknown, "출처 목록에 없는 번호: " + ", ".join(unknown))
    leftovers = [w for w in ("TODO", "TBD", "lorem ipsum") if w.lower() in text.lower()]
    add("미완성 표시 없음", not leftovers, "남은 표시: " + ", ".join(leftovers))
    return tests


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    reports = sorted(p for p in (Path(args.root) / "reports").glob("*.md") if p.name.lower() != "readme.md")
    tests: list[dict] = []
    if not reports:
        tests.append({"name": "보고서 있음", "ok": False, "message": "reports/*.md 보고서가 없습니다."})
    for r in reports:
        tests += check(r)
    Path(args.out).write_text(
        json.dumps({"suite": "studio-docs/reports", "engine": f"python {sys.version.split()[0]}", "tests": tests}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0 if all(t["ok"] for t in tests) else 1


if __name__ == "__main__":
    sys.exit(main())
