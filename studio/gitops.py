"""git 작업: 작업별 worktree, 변경 범위 검사, 후보 커밋, 병합.

작업자는 git을 쓰지 말라고 지시받지만, 지시를 어겨도 결과가 틀어지지 않게
감독 프로그램이 기준 커밋(expected)과 비교해서 모든 변경을 직접 정리한다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from .util import no_window_flags

STUDIO_AUTHOR = ("AI Studio", "studio@ai-studio.local")


class GitError(RuntimeError):
    pass


def git(args: list[str], cwd: Path, *, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
    cmd = ["git", "-c", "core.quotepath=false", "-c", "core.longpaths=true", *args]
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, timeout=timeout, creationflags=no_window_flags())
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args[:3])} 실패 ({p.returncode}): {(err or out).strip()[:500]}")
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def is_repo(path: Path) -> bool:
    return (Path(path) / ".git").exists()


def init_repo(path: Path, main_branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(["init", "-q", "-b", main_branch], path)


def head(cwd: Path, ref: str = "HEAD") -> str:
    return git(["rev-parse", ref], cwd).stdout.strip()


def current_branch(cwd: Path) -> str:
    return git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).stdout.strip()


def ref_exists(cwd: Path, ref: str) -> bool:
    return git(["rev-parse", "--verify", "--quiet", ref], cwd, check=False).returncode == 0


def commit_all(cwd: Path, message: str, author: tuple[str, str] = STUDIO_AUTHOR) -> str | None:
    git(["add", "-A"], cwd)
    if not git(["status", "--porcelain"], cwd).stdout.strip():
        return None
    git(["-c", f"user.name={author[0]}", "-c", f"user.email={author[1]}", "commit", "-q", "--no-verify", "-m", message], cwd)
    return head(cwd)


def is_clean(cwd: Path) -> bool:
    return not git(["status", "--porcelain", "--untracked-files=no"], cwd).stdout.strip()


# ---- worktree ----

def add_worktree(repo: Path, path: Path, branch: str, base: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    git(["worktree", "prune"], repo, check=False)
    if ref_exists(repo, f"refs/heads/{branch}"):
        git(["worktree", "add", "-f", str(path), branch], repo)
    else:
        git(["worktree", "add", "-b", branch, str(path), base], repo)


def remove_worktree(repo: Path, path: Path) -> None:
    if path.exists():
        git(["worktree", "remove", "--force", str(path)], repo, check=False)
    git(["worktree", "prune"], repo, check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


# ---- 경로 규칙 ----

def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """'src/core/**', '*.md', 'docs/' 같은 패턴을 정규식으로. '**'는 여러 폴더를 뜻한다."""
    pat = pattern.strip().replace("\\", "/")
    while pat.startswith("./"):
        pat = pat[2:]
    if pat.endswith("/"):
        pat += "**"
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pat.startswith("**", i):
            out += ".*"
            i += 2
        elif pat[i] == "*":
            out += "[^/]*"
            i += 1
        elif pat[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pat[i])
            i += 1
    return re.compile("^" + out + "$", re.IGNORECASE)


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(glob_to_regex(p).match(path) for p in patterns if p.strip())


def normalize_rel(path: str) -> str | None:
    """저장소 안의 상대경로만 허용한다. 절대경로·상위경로·드라이브 문자는 None."""
    p = path.replace("\\", "/").strip()
    if not p or p.startswith("/") or re.match(r"^[A-Za-z]:", p):
        return None
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if any(x == ".." for x in parts):
        return None
    return "/".join(parts)


def check_paths(paths: list[str], allowed: list[str], protected: list[str]) -> list[dict]:
    """허용 범위를 벗어난 변경을 찾는다."""
    violations = []
    for raw in paths:
        rel = normalize_rel(raw)
        if rel is None:
            violations.append({"path": raw, "reason": "저장소 밖 경로"})
        elif matches_any(rel, protected):
            violations.append({"path": rel, "reason": "보호된 경로"})
        elif not matches_any(rel, allowed):
            violations.append({"path": rel, "reason": "허용 경로 밖"})
    return violations


# ---- 작업 결과 정리 ----

def staged_changes(cwd: Path, expected: str) -> list[str]:
    """작업자가 커밋까지 했든 안 했든, 기준 커밋 대비 바뀐 모든 경로를 돌려준다."""
    if head(cwd) != expected:
        git(["reset", "-q", "--soft", expected], cwd)
    git(["add", "-A"], cwd)
    out = git(["diff", "--cached", "--name-only", "--no-renames", "-z", expected], cwd).stdout
    return sorted({p for p in out.split("\0") if p})


def discard_paths(cwd: Path, expected: str, paths: list[str]) -> None:
    """허용 범위 밖 변경을 기준 커밋 상태로 되돌린다."""
    for p in paths:
        exists_in_expected = git(["cat-file", "-e", f"{expected}:{p}"], cwd, check=False).returncode == 0
        if exists_in_expected:
            git(["restore", f"--source={expected}", "--staged", "--worktree", "--", p], cwd, check=False)
        else:
            git(["rm", "-q", "-r", "-f", "--cached", "--ignore-unmatch", "--", p], cwd, check=False)
            fp = cwd / p
            if fp.is_file() or fp.is_symlink():
                fp.unlink(missing_ok=True)
            elif fp.is_dir():
                shutil.rmtree(fp, ignore_errors=True)


def commit_staged(cwd: Path, message: str, author: tuple[str, str] = STUDIO_AUTHOR) -> str | None:
    if not git(["diff", "--cached", "--name-only"], cwd).stdout.strip():
        return None
    git(["-c", f"user.name={author[0]}", "-c", f"user.email={author[1]}", "commit", "-q", "--no-verify", "-m", message], cwd)
    return head(cwd)


# ---- 비교·내보내기·병합 ----

def diff_text(cwd: Path, base: str, target: str, max_chars: int = 60000) -> tuple[str, bool]:
    out = git(["diff", "--no-color", "--no-ext-diff", base, target], cwd).stdout
    if len(out) > max_chars:
        return out[:max_chars], True
    return out, False


def diff_numstat(cwd: Path, base: str, target: str) -> list[dict]:
    out = git(["diff", "--numstat", "--no-renames", base, target], cwd).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            added, deleted, path = parts
            rows.append({
                "path": path,
                "added": int(added) if added.isdigit() else None,
                "deleted": int(deleted) if deleted.isdigit() else None,
            })
    return rows


def changed_paths(cwd: Path, base: str, target: str) -> list[str]:
    """base와 target 사이에 추가·수정된 파일 경로 (지워진 파일은 뺀다)."""
    out = git(["diff", "--name-only", "--no-renames", "--diff-filter=d", "-z", base, target], cwd).stdout
    return sorted({p for p in out.split("\x00") if p})


def export_snapshot(repo: Path, sha: str, dest: Path) -> None:
    """후보 커밋의 파일만 깨끗한 폴더로 꺼낸다 (.git 없음)."""
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest.parent / f"{dest.name}.zip"
    git(["archive", "--format=zip", "-o", str(zip_path), sha], repo)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)
    zip_path.unlink(missing_ok=True)


def fast_forward_main(repo: Path, main_branch: str, target: str) -> str:
    if current_branch(repo) != main_branch:
        raise GitError(f"제품 저장소가 '{main_branch}' 브랜치가 아닙니다.")
    if not is_clean(repo):
        raise GitError("제품 저장소 main에 커밋되지 않은 변경이 있습니다.")
    git(["merge", "-q", "--ff-only", target], repo)
    return head(repo)
