"""Backend thủ công: tool ghi prompt ra file, người dùng dán vào ChatGPT app rồi lưu câu trả lời.

Dùng khi không muốn chạy Chrome tự động, hoặc để thử prompt. Chạy lại lệnh sau khi đã dán
câu trả lời thì pipeline đi tiếp từ đúng chỗ dừng (xem Ledger).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from .base import AwaitingResponse


class _ManualChat:
    def __init__(self, workdir: Path):
        self.workdir = workdir

    def ask(self, prompt: str, label: str) -> str:
        raise AwaitingResponse(self.workdir / f"{label}.prompt.md", self.workdir / f"{label}.response.md")


class ManualBackend:
    @contextmanager
    def session(self, workdir: Path):
        yield _ManualChat(workdir)
