import os
import time

import pytest

from bot.filelock import LockTimeout, file_lock


def test_lock_created_and_removed(tmp_path):
    p = tmp_path / "x.lock"
    with file_lock(p, wait=1):
        assert p.exists()
    assert not p.exists()


def test_second_holder_times_out(tmp_path):
    p = tmp_path / "x.lock"
    with file_lock(p, wait=1):
        with pytest.raises(LockTimeout):
            with file_lock(p, wait=0.2, poll=0.05):
                pass
        assert p.exists()
    assert not p.exists()


def test_stale_lock_is_taken_over(tmp_path):
    p = tmp_path / "x.lock"
    p.write_text("123")
    old = time.time() - 3600
    os.utime(p, (old, old))
    with file_lock(p, wait=0.5, stale=60):
        assert p.read_text() == str(os.getpid())


def test_released_on_exception(tmp_path):
    p = tmp_path / "x.lock"
    with pytest.raises(ValueError):
        with file_lock(p, wait=1):
            raise ValueError
    assert not p.exists()
