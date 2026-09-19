"""Giao diện chung cho nơi "hỏi ChatGPT".

Pipeline không quan tâm hỏi bằng cách nào: tự động qua ChatGPT web (Playwright) hay thủ công
(dán tay). Mọi lượt hỏi/đáp đều ghi xuống ổ đĩa (`Ledger`), nên chạy lại thì câu nào đã có
câu trả lời được dùng lại luôn, không hỏi lại, không tốn lượt.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol


class AwaitingResponse(Exception):
    """Backend thủ công: đã ghi prompt ra file, đang chờ người dán câu trả lời."""

    def __init__(self, prompt_path: Path, response_path: Path):
        super().__init__(f"Chờ câu trả lời: dán vào {response_path}")
        self.prompt_path = prompt_path
        self.response_path = response_path


class ChatSession(Protocol):
    def ask(self, prompt: str, label: str) -> str: ...


class Backend(Protocol):
    def session(self, workdir: Path) -> AbstractContextManager[ChatSession]: ...


class Ledger:
    """Sổ hỏi/đáp trên ổ đĩa: <dir>/<label>.prompt.md và <label>.response.md."""

    def __init__(self, directory: Path):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def prompt_path(self, label: str) -> Path:
        return self.dir / f"{label}.prompt.md"

    def response_path(self, label: str) -> Path:
        return self.dir / f"{label}.response.md"

    def cached(self, label: str) -> str | None:
        p = self.response_path(label)
        if p.exists() and p.read_text(encoding="utf-8").strip():
            return p.read_text(encoding="utf-8")
        return None

    def record(self, label: str, prompt: str, response: str | None = None) -> None:
        self.prompt_path(label).write_text(prompt, encoding="utf-8")
        if response is not None:
            self.response_path(label).write_text(response, encoding="utf-8")


class LazyChat:
    """Chỉ mở phiên chat thật (bật Chrome...) khi có câu hỏi chưa được trả lời trong sổ."""

    def __init__(self, backend: Backend, ledger: Ledger):
        self.backend = backend
        self.ledger = ledger
        self._cm = None
        self._session: ChatSession | None = None

    def ask(self, prompt: str, label: str) -> str:
        cached = self.ledger.cached(label)
        if cached is not None:
            return cached
        self.ledger.record(label, prompt)
        if self._session is None:
            self._cm = self.backend.session(self.ledger.dir)
            self._session = self._cm.__enter__()
        answer = self._session.ask(prompt, label)
        self.ledger.record(label, prompt, answer)
        return answer

    def close(self) -> None:
        if self._cm is not None:
            self._cm.__exit__(None, None, None)
            self._cm = self._session = None

    def __enter__(self) -> "LazyChat":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
