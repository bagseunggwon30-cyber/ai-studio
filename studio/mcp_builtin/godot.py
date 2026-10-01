"""내장 MCP 'Godot 도움말' (godot-docs): 이 PC의 Godot가 만든 API 목록에서 클래스·함수를 찾는다. 읽기만 한다.

처음 쓸 때 `godot --headless --doctool <캐시>`로 API 목록(XML)을 만든다 (내려받기 없음, 4초쯤). 이 Godot 판에 실제로 있는
클래스·함수·속성·시그널 이름과 인자만 돌려준다 (배포판이라 설명 문장은 비어 있을 수 있다) — 없는 함수를 지어내지 않게.
실행: python godot.py --godot <Godot 실행 파일> --cache <캐시 폴더>
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from studio.mcp_builtin.base import Server, ToolError, setup_stdio  # noqa: E402

NAME_RE = re.compile(r"^[A-Za-z_@][A-Za-z0-9_]{0,80}$")


def _clean(text: str | None, n: int = 400) -> str:
    s = " ".join(str(text or "").split())
    s = re.sub(r"\[/?(?:b|i|code|codeblock|codeblocks|gdscript|csharp|kbd|url[^\]]*)\]", "", s)
    s = re.sub(r"\[(?:method|member|signal|constant|enum|class|param|annotation|theme_item|operator|constructor) ([^\]]+)\]", r"\1", s)
    return s if len(s) <= n else s[: n - 1] + "…"


class Docs:
    def __init__(self, godot: str, cache: Path):
        self.godot, self.cache = godot, cache
        self._files: dict[str, Path] | None = None

    def folder(self) -> Path:
        exe = Path(self.godot)
        try:
            stamp = f"{exe.resolve()}|{exe.stat().st_size}|{exe.stat().st_mtime_ns}"
        except OSError as e:
            raise ToolError(f"Godot 실행 파일을 찾지 못했습니다: {self.godot}") from e
        return self.cache / hashlib.sha1(stamp.encode()).hexdigest()[:12]

    def files(self) -> dict[str, Path]:
        if self._files is not None:
            return self._files
        out = self.folder()
        if not (out / "ok").is_file():
            tmp = out.with_name(out.name + ".tmp")
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True, exist_ok=True)
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0  # type: ignore[attr-defined]
            try:
                subprocess.run([self.godot, "--headless", "--doctool", str(tmp)], cwd=str(tmp), stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180, check=False, creationflags=flags)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise ToolError(f"Godot API 목록을 만들지 못했습니다: {e}") from e
            if not any(tmp.rglob("*.xml")):
                raise ToolError("Godot API 목록을 만들지 못했습니다 (XML이 없음).")
            shutil.rmtree(out, ignore_errors=True)
            tmp.rename(out)
            (out / "ok").write_text("ok", encoding="utf-8")
        self._files = {f.stem: f for f in sorted(out.rglob("*.xml")) if NAME_RE.match(f.stem)}
        return self._files

    def index(self) -> list[tuple[str, str]]:
        """찾기용 목록: (멤버 이름 소문자, 보여 줄 한 줄). 처음 한 번만 모든 XML을 읽는다."""
        if getattr(self, "_index", None) is None:
            rows: list[tuple[str, str]] = []
            for name, f in self.files().items():
                root = ET.parse(f).getroot()
                rows += [((m.get("name") or "").lower(), f"{name}.{_sig(m)}") for m in root.iter("method")]
                for tag, label in (("member", "속성"), ("signal", "시그널"), ("constant", "상수")):
                    rows += [((m.get("name") or "").lower(),
                              f"{name}.{m.get('name')} ({label}{': ' + m.get('type') if m.get('type') else ''})") for m in root.iter(tag)]
            self._index = rows
        return self._index

    def load(self, name: str) -> ET.Element:
        f = self.files().get(name) or next((p for n, p in self.files().items() if n.lower() == name.lower()), None)
        if not f:
            raise ToolError(f"'{name}' 클래스가 없습니다. godot_search로 이름을 찾아 보세요.")
        return ET.parse(f).getroot()


def _sig(m: ET.Element) -> str:
    ret = m.find("return")
    params = []
    for p in sorted(m.findall("param"), key=lambda x: int(x.get("index", "0"))):
        s = f"{p.get('name')}: {p.get('type')}"
        if p.get("default") is not None:
            s += f" = {p.get('default')}"
        params.append(s)
    q = f" {m.get('qualifiers')}" if m.get("qualifiers") else ""
    return f"{m.get('name')}({', '.join(params)}) -> {ret.get('type') if ret is not None else 'void'}{q}"


def build(docs: Docs) -> Server:
    srv = Server("godot-docs", "1.0", "이 PC의 Godot 판에 실제로 있는 클래스·함수·속성·시그널을 찾는다. GDScript를 쓰기 전에 이름과 인자를 확인할 때 쓴다.")

    @srv.tool("godot_search", "클래스 이름이나 멤버(함수·속성·시그널·상수) 이름에 query가 든 것을 찾는다 (대소문자 무시).",
              {"query": {"type": "string", "description": "찾을 이름 조각 (예: move_and_slide, Tween, timeout)"}}, ["query"])
    def godot_search(query: str) -> str:
        q = str(query).strip().lower()
        if len(q) < 2:
            raise ToolError("두 글자 이상으로 찾아 주세요.")
        hits = [f"클래스 {n}" for n in docs.files() if q in n.lower()][:15]
        hits += [text for name, text in docs.index() if q in name][: 60 - len(hits)]
        return "\n".join(hits) or "찾은 것이 없습니다."

    @srv.tool("godot_class", "클래스 하나의 API: 부모 클래스, 함수(인자·반환), 속성(타입·기본값), 시그널, 상수. member를 주면 그것만.",
              {"name": {"type": "string", "description": "클래스 이름 (예: CharacterBody2D)"},
               "member": {"type": "string", "description": "멤버 이름 (비우면 전체)"}}, ["name"])
    def godot_class(name: str, member: str = "") -> str:
        if not NAME_RE.match(str(name)):
            raise ToolError("클래스 이름이 올바르지 않습니다.")
        root = docs.load(name)
        member = str(member or "").strip()
        lines = [f"# {root.get('name')}" + (f" (부모: {root.get('inherits')})" if root.get("inherits") else "")]
        brief = _clean(root.findtext("brief_description"))
        if brief:
            lines.append(brief)
        sections = (("methods/method", "함수"), ("members/member", "속성"), ("signals/signal", "시그널"), ("constants/constant", "상수"))
        for path, label in sections:
            items = [m for m in root.findall(path) if not member or m.get("name") == member]
            if not items:
                continue
            lines.append(f"\n## {label}")
            for m in items[:120]:
                if label in ("함수", "시그널"):
                    text = _sig(m) if label == "함수" else f"{m.get('name')}({', '.join(p.get('name', '') + ': ' + p.get('type', '') for p in m.findall('param'))})"
                elif label == "속성":
                    text = f"{m.get('name')}: {m.get('type')}" + (f" = {m.get('default')}" if m.get("default") is not None else "")
                else:
                    text = f"{m.get('name')} = {m.get('value')}" + (f" ({m.get('enum')})" if m.get("enum") else "")
                desc = _clean(m.findtext("description") if label != "속성" else m.text, 200 if not member else 1500)
                lines.append(f"- {text}" + (f" — {desc}" if desc else ""))
            if len(items) > 120:
                lines.append(f"- …(그 밖 {len(items) - 120}개)")
        if member and len(lines) <= 2:
            raise ToolError(f"{root.get('name')}에 '{member}'가 없습니다. 부모 클래스({root.get('inherits') or '없음'})도 확인해 보세요.")
        return "\n".join(lines)

    return srv


def main() -> None:
    setup_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--godot", required=True)
    ap.add_argument("--cache", required=True)
    a = ap.parse_args()
    build(Docs(a.godot, Path(a.cache))).serve()


if __name__ == "__main__":
    main()
