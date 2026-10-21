"""Serialize local publish commands and enforce the chosen export channel."""
from contextlib import contextmanager
from functools import wraps
import os
from pathlib import Path

from . import r2


def crayonahub_blocked(state: dict) -> bool:
    return bool(state.get("exported_at") or state.get("exported_csv"))


def eligible_crayonahub(books, on_event):
    eligible, skipped = [], []
    for book in books:
        if crayonahub_blocked(r2.read_state(book)):
            skipped.append(book.name)
            on_event(f"Bỏ qua {book.name}: đã xuất Printify, không đẩy lại qua Crayonahub.")
        else:
            eligible.append(book)
    return eligible, skipped


@contextmanager
def publish_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".publish.lock").open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise r2.R2Error("Đang đẩy R2 / CSV ở tiến trình khác. Chờ lượt đó xong.") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def serialized(func):
    @wraps(func)
    def call(cfg, *args, **kwargs):
        with publish_lock(Path(cfg["projects_dir"])):
            return func(cfg, *args, **kwargs)
    return call
