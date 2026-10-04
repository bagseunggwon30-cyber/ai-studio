"""Acceptance-level evidence tied to the current candidate and trusted suite."""
from __future__ import annotations
import hashlib
from pathlib import Path, PurePosixPath
from .qa import suite_hash
from .checkpoints import digest, files_digest
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
    valid = valid and all(receipt.get(key) == qa.get(key) for key in
                          ("qa_id", "candidate_sha", "verdict", "suite_hash", "tests", "passed", "total"))
    if qa.get("evidence_digest"):
        valid = valid and digest(receipt) == qa["evidence_digest"]
    if valid:
        try:
            valid = (not qdir.is_symlink() and not (qdir / "snapshot").is_symlink()
                     and bool(qa.get("snapshot_digest")) and qa["snapshot_digest"] == files_digest(qdir / "snapshot"))
        except (ValueError,OSError):
            valid = False
    items = []
    requirements = task.extra.get("requirements")
    strict = requirements is not None or bool(task.extra.get("workflow_run"))
    fallback = [{"id": "A"+str(i+1), "text": text, "evidence": []} for i,text in enumerate(task.acceptance)]
    criteria_match = isinstance(requirements, list) and bool(requirements) and all(
        isinstance(r, dict) and isinstance(r.get("id"), str) and bool(r["id"]) and isinstance(r.get("evidence"), list)
        and all(isinstance(ref, dict) and ref.get("type") in ("test", "file", "screenshot", "source") for ref in r["evidence"])
        for r in requirements)
    criteria_match = criteria_match and [r.get("text") for r in requirements] == task.acceptance
    requirements = requirements if criteria_match else fallback
    tests_raw = receipt.get("tests", [])
    if not isinstance(tests_raw, list) or any(not isinstance(t, dict) for t in tests_raw):
        valid = False; tests_raw = []
    tests = {t.get("name"):t for t in tests_raw}
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
    complete = valid and bool(items) and all(r["status"] == "verified" for r in items) and (not strict or criteria_match)
    reasons = []
    if not valid:
        reasons.append("현재 후보의 신뢰 검증 기록·파일이 없거나 변경됐습니다.")
    if strict and not criteria_match:
        reasons.append("저장된 완료 기준마다 근거를 지정해야 합니다. 이전 작업의 기록은 보존됩니다.")
    reasons.extend(f"{r['id']}: {r['text']} — 충족 근거가 없습니다." for r in items if r["status"] != "verified")
    return {"candidate_sha":task.candidate_sha, "qa_id":qa.get("qa_id"), "suite_current":valid, "strict":strict,
            "items":items, "complete":complete, "reasons":reasons}
