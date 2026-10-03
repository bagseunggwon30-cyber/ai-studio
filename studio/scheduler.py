"""Small, conservative resource scheduler; runtime leases live only while workers live."""
from __future__ import annotations
import re
from .model import ACTIVE, NO_BRANCH, OPEN_BRANCH


def prefix(pattern):
    return re.split(r"[?*\[]", pattern.replace("\\", "/").lower(), 1)[0].rstrip("/")


def overlaps(a, b):
    a, b = prefix(a), prefix(b)
    return not a or not b or a.startswith(b) or b.startswith(a)


def conflict(a, b):
    if a.id == b.id:
        return True
    if a.worktree and b.worktree and a.worktree.lower() == b.worktree.lower():
        return True
    # Non-code mutation tasks use shared asset/skill/settings directories.
    shared = {"skill", "look", "hire", "tool"}
    if a.kind in shared or b.kind in shared:
        return True
    if set(a.extra.get("resources", [])) & set(b.extra.get("resources", [])):
        return True
    if a.project != b.project:
        return False
    if a.kind == "plan" or b.kind == "plan":
        return False
    return any(overlaps(x, y) for x in (a.allowed_paths or ["**"]) for y in (b.allowed_paths or ["**"]))


def blocker(task, tasks, reserved=()):
    for other in tasks:
        if other.id == task.id:
            if other.id in reserved:
                return other.id
            continue
        if (other.id in reserved or other.status in ACTIVE or (other.status in OPEN_BRANCH and other.kind not in NO_BRANCH) or other.extra.get("uncertain")) and conflict(task, other):
            return other.id
    return None
