"""Bóc JSON khỏi câu trả lời của ChatGPT.

Ưu tiên khối ```json cuối cùng (ChatGPT đôi khi viết thêm chữ hoặc nhắc lại schema ở đầu).
Không có khối code thì thử đoạn {...} lớn nhất. Hỏng hẳn thì ném ValueError để pipeline gửi
prompt sửa lỗi thay vì nhận bừa.
"""
from __future__ import annotations

import json
import re

_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> dict:
    candidates = [m.group(1) for m in _FENCE.finditer(text or "")]
    if not candidates:
        start, end = (text or "").find("{"), (text or "").rfind("}")
        if start >= 0 and end > start:
            candidates = [text[start:end + 1]]
    last_error = None
    for raw in reversed(candidates):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = e
            continue
        if isinstance(data, dict):
            return data
    raise ValueError(f"Không tìm thấy JSON hợp lệ trong câu trả lời ({last_error or 'không có khối JSON'})")
