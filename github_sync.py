"""GitHub sync helper — auto-commits and pushes OI snapshots.

Git repo is at the project root (options_scanner/), so both code
and OI snapshots live in the same repository.
"""

from __future__ import annotations

import os
import subprocess
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(PROJECT_ROOT, "output", "oi_history")


def _run(cmd: list[str], cwd: str = PROJECT_ROOT) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=30,
        )
        out = result.stdout.strip() + "\n" + result.stderr.strip()
        return result.returncode == 0, out.strip()
    except Exception as e:
        return False, str(e)


def is_git_repo() -> bool:
    return os.path.isdir(os.path.join(PROJECT_ROOT, ".git"))


def has_remote() -> bool:
    ok, out = _run(["git", "remote", "get-url", "origin"])
    return ok and bool(out)


def set_remote(url: str) -> bool:
    if not url.strip():
        return False
    if has_remote():
        _run(["git", "remote", "remove", "origin"])
    ok, out = _run(["git", "remote", "add", "origin", url])
    if ok:
        logger.info("Git remote set to %s", url)
    return ok


def get_status() -> dict:
    info = {
        "is_repo": is_git_repo(),
        "has_remote": has_remote(),
        "branch": "",
        "last_push": "",
    }
    if not info["is_repo"]:
        return info

    ok, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    info["branch"] = branch if ok else "main"

    ok, out = _run(["git", "log", "-1", "--format=%ci", "origin/" + info.get("branch", "main")])
    if ok and out:
        info["last_push"] = out.split("\n")[0]

    return info


def commit_and_push(message: str | None = None, include_code: bool = False) -> tuple[bool, str]:
    if not is_git_repo():
        return False, "Not a git repo."

    if not has_remote():
        return False, "No remote configured. Add a GitHub repo URL in Settings."

    msg = message or f"OI snapshot {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"

    # Stage snapshot JSON files
    ok, out = _run(["git", "add", os.path.relpath(HISTORY_DIR, PROJECT_ROOT) + "/*.json"])
    if not ok:
        return False, f"git add failed: {out}"

    # Optionally stage code changes
    if include_code:
        _run(["git", "add", "*.py", "*.txt", "*.md", ".env.example"])

    # Check if there's anything to commit
    ok, out = _run(["git", "diff", "--cached", "--quiet"])
    if ok:
        return True, "Nothing to commit"

    ok, out = _run(["git", "commit", "-m", msg])
    if not ok:
        return False, f"git commit failed: {out}"

    branch = get_status()["branch"] or "main"
    ok, out = _run(["git", "push", "-u", "origin", branch])
    if not ok:
        return False, f"git push failed: {out}"

    return True, "Pushed to GitHub"
