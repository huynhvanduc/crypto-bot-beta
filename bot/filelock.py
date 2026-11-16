from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path


class LockTimeout(RuntimeError):
    pass


@contextmanager
def file_lock(path: str | Path = "live/git.lock", wait: float = 300.0, stale: float = 1800.0,
              poll: float = 0.5):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + wait
    while True:
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - p.stat().st_mtime > stale:
                    p.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() >= deadline:
                raise LockTimeout(f"Chờ khóa {p} quá {wait:.0f} giây")
            time.sleep(poll)
            continue
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        break
    try:
        yield
    finally:
        p.unlink(missing_ok=True)
