from __future__ import annotations

import subprocess


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")


def push() -> subprocess.CompletedProcess:
    git("pull", "--rebase", "--autostash", "-q")
    return git("push")
