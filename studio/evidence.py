"""Acceptance-level evidence tied to the current candidate and trusted suite."""
from __future__ import annotations
import hashlib
from pathlib import Path, PurePosixPath
from .qa import suite_hash
from .checkpoints import files_digest
from .util import read_json


def safe_file(root, rel):
    if not isinstance(rel, str) or not rel or "\\" in rel or ":" in rel:
        raise ValueError("상대 파일 경로가 필요합니다.")
    if PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
        raise ValueError("상대 파일 경로가 필요합니다.")
    root = Path(root).resolve()
    p = root / rel
    if p.is_symlink() or not p.resolve().is_relative_to(root) or not p.is_file():
        raise ValueError("근거 파일이 없거나 접근 범위를 벗어났습니다.")
    return p


def assess(cfg, store, task):
    qa = task.qa or {}
    project = cfg.projects[task.project]
    valid = bool(task.candidate_sha and qa.get("candidate_sha") == task.candidate_sha
                 and qa.get("verdict") in ("pass", "none") and qa.get("suite_hash") == suite_hash(cfg, project))
    qid = qa.get("qa_id", "")
    qdir = store.qa_dir / qid if isinstance(qid, str) and qid.startswith("Q") and "/" not in qid and "\\" not in qid else store.qa_dir / "missing"
    receipt = read_json(qdir / "evidence.json", {}) or {}
    valid = valid and receipt.get("candidate_sha") == task.candidate_sha and receipt.get("verdict") == qa.get("verdict")
    if valid:
        try:
            valid = bool(qa.get("snapshot_digest")) and qa["snapshot_digest"] == files_digest(qdir / "snapshot")
        except (ValueError,OSError):
            valid = False
    items = []
    requirements = task.extra.get("requirements")
    strict = requirements is not None
    requirements = requirements if strict else [{"id": "A"+str(i+1), "text": text, "evidence": []} for i,text in enumerate(task.acceptance)]
    tests = {t.get("name"):t for t in receipt.get("tests", [])}
    for req in requirements:
        refs = []
        for ref in req.get("evidence", []):
            r = {**ref, "verified": False}
            try:
                if ref["type"] == "test":
                    r["verified"] = valid and tests.get(ref["name"], {}).get("ok") is True
                elif ref["type"] in ("file", "screenshot"):
                    p = safe_file(qdir / "snapshot", ref["path"])
                    data = p.read_bytes()
                    r["sha256"] = hashlib.sha256(data).hexdigest()
                    r["verified"] = valid and bool(data)
                    if ref["type"] == "screenshot":
                        r["verified"] = r["verified"] and (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8"))
                elif ref["type"] == "source":
                    # Sources require a supervisor-owned capture, never an agent's assertion.
                    sid = ref["id"]
                    p = safe_file(store.dir / "sources" / task.id, sid + ".json")
                    source = read_json(p, {})
                    text = safe_file(store.dir / "sources" / task.id, sid + ".txt").read_bytes()
                    r["verified"] = valid and source.get("sha256") == hashlib.sha256(text).hexdigest() and source.get("ok") is True
                    r["url"] = source.get("url")
            except (OSError, ValueError, KeyError):
                pass
            refs.append(r)
        items.append({"id": req["id"], "text": req["text"], "status": "verified" if refs and all(r["verified"] for r in refs) else "missing", "evidence": refs})
    return {"candidate_sha":task.candidate_sha, "suite_current":valid, "strict":strict, "items":items,
            "complete":valid and all(r["status"] == "verified" for r in items)}
