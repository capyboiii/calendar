"""Nhận diện thông báo hết lượt / quá tải / từ chối của ChatGPT - dùng chung cho chat chữ và gen ảnh.

Ba nguồn tín hiệu (bất kỳ nguồn nào báo là đủ):
1. Chữ trên trang: lượt trả lời cuối + mọi hộp thoại / banner / toast (role=dialog|alert|status, toast...).
2. Mạng: phản hồi HTTP 429 (quá nhiều request) hoặc 503 (quá tải) từ máy chủ ChatGPT, hoặc JSON lỗi
   có mã rate_limit / usage_limit - không phụ thuộc câu chữ, ChatGPT đổi câu thông báo vẫn bắt được.
3. Gửi tin nhắn không đi mà trang đang hiện thông báo giới hạn -> coi là hết lượt, không phải lỗi tạm.

Phân loại:
- "quota": tài khoản hết lượt / bị giới hạn tốc độ / hệ thống quá tải -> tài khoản NGHỈ; hết cả 5 tài khoản thì
  batch tạm dừng, chờ rồi thử lại (calforge/pipeline.py _wait_for_quota). Không tính vào số lần thử của ảnh.
- "refused": nội dung bị từ chối -> ảnh đó hỏng, không thử lại trên tài khoản khác.
- "error": lỗi tạm (mạng, lỗi sinh ảnh) -> thử lại, tối đa max_attempts.
"""
from __future__ import annotations

import time

# Hết lượt / giới hạn tốc độ / quá tải. Viết thường, khoảng trắng đã gộp. Thêm câu mới vào đây khi gặp.
QUOTA_PAT = (
    # hết lượt theo gói
    "you've reached your limit", "you have reached your limit", "reached the limit", "reached our limit",
    "reached your limit", "hit your limit", "hit the limit", "hit the free plan limit", "hit the plus plan limit",
    "plan limit", "usage limit", "usage cap", "current usage cap", "limit resets", "until your limit resets",
    "resets in", "you've used all", "used up your", "upgrade to plus to continue", "upgrade to continue",
    # KHÔNG thêm "get plus" / "upgrade your plan": banner quảng cáo trên tài khoản free luôn hiện
    # hết lượt tạo ảnh
    "limit for image", "image generation limit", "image generation rate limit", "image limit",
    "image creation limit", "you can create more images", "able to create images again", "create more images in",
    "generate more images", "out of image generation", "out of image", "no more images",
    # giới hạn tốc độ / quá nhiều request
    "rate limit", "rate_limit", "ratelimit", "too many requests", "too many messages", "messages per hour",
    "too many concurrent requests", "please slow down", "you're sending messages too quickly",
    # hệ thống quá tải (mọi tài khoản cùng lỗi -> nghỉ và chờ, đừng đốt số lần thử)
    "at capacity", "is at capacity", "high demand", "experiencing high", "overloaded", "server is busy",
    "servers are busy", "temporarily unavailable", "service unavailable",
    # chặn tạm vì hoạt động bất thường
    "unusual activity", "suspicious activity", "we've detected unusual", "detected unusual",
    # tiếng Việt (giao diện ChatGPT tiếng Việt)
    "đã đạt giới hạn", "đạt đến giới hạn", "đã đạt đến giới hạn", "hết lượt", "giới hạn tạo ảnh",
    "giới hạn sử dụng", "quá nhiều yêu cầu", "quá nhiều tin nhắn", "hoạt động bất thường", "nhu cầu cao",
    "quá tải",
)

# Câu mơ hồ: chỉ tính là hết lượt khi KHÔNG phải câu từ chối (vd "I can't create that... try again in a new chat")
QUOTA_WEAK = ("try again in", "please try again in", "come back later", "come back after", "wait until",
              "thử lại sau vài", "quay lại sau")

# Từ chối nội dung
REFUSE_PAT = (
    "i can't help with that", "i cannot help with that", "i'm unable to create", "i can't create",
    "i cannot create", "i'm not able to generate", "i can't generate", "i cannot generate",
    "content policy", "usage policies", "violates", "not able to help with", "i won't be able to",
    "tôi không thể tạo", "vi phạm chính sách",
)

# Lỗi tạm: thử lại
TEMP_PAT = (
    "something went wrong", "an error occurred", "error generating", "network error", "error in message stream",
    "there was an error", "hmm...something seems to have gone wrong", "something seems to have gone wrong",
    "conversation not found", "failed to fetch", "request timed out", "bad gateway", "gateway timeout",
    "please try again", "try again later", "unable to generate", "wasn't able to generate", "could not generate",
    "đã xảy ra lỗi", "có lỗi xảy ra", "thử lại sau",
)

# Mọi khối thông báo ngoài lượt trả lời: hộp thoại, banner, toast
NOTICE_SELECTOR = ('[role="dialog"], [role="alert"], [role="status"], .toast-root, [data-testid*="toast" i], '
                   '[class*="toast" i], [data-testid*="limit" i]')
NOTICE_JS = f"""() => Array.from(document.querySelectorAll('{NOTICE_SELECTOR}'))
  .filter((e) => e.getBoundingClientRect().width > 0).map((e) => e.innerText).join(' ').slice(-1500)"""


def classify(text: str) -> str:
    """Chữ trên trang -> "quota" | "refused" | "error" | ""."""
    low = " ".join((text or "").lower().split())
    for pats, kind in ((QUOTA_PAT, "quota"), (REFUSE_PAT, "refused"), (QUOTA_WEAK, "quota"), (TEMP_PAT, "error")):
        if any(p in low for p in pats):
            return kind
    return ""


class RateWatch:
    """Theo dõi phản hồi mạng của trang ChatGPT: nhớ lần gần nhất bị 429/503 hoặc JSON báo rate/usage limit."""

    HOSTS = ("chatgpt.com", "openai.com", "oaiusercontent.com")

    def __init__(self, page):
        self.hit: tuple[float, str] | None = None
        page.on("response", self._on_response)

    def _on_response(self, resp) -> None:
        try:
            url = resp.url
            if not any(h in url for h in self.HOSTS):
                return
            status = resp.status
            if not self._core(url, getattr(getattr(resp, "request", None), "method", "")):
                return
            if status in (429, 503):
                self.hit = (time.monotonic(), f"HTTP {status} {url.split('?')[0][-60:]}")
            elif status >= 400:
                body = ""
                try:
                    body = resp.text()[:400].lower()
                except Exception:  # noqa: BLE001 - body đã bị đọc/stream: bỏ qua
                    pass
                if any(k in body for k in ("rate_limit", "usage_limit", "too many requests", "limit_reached",
                                           "quota", "capacity")):
                    self.hit = (time.monotonic(), f"HTTP {status}: {body[:120]}")
        except Exception:  # noqa: BLE001 - không để việc theo dõi làm hỏng trang
            pass

    @staticmethod
    def _core(url: str, method: str = "POST") -> bool:
        """Chỉ request GỬI tin nhắn / tạo ảnh / tải file lên (POST). Bỏ request đọc (GET): danh sách chat ở thanh
        bên (/conversations), tải lại một chat (/conversation/<id>), thống kê, cài đặt... - ChatGPT hay trả 429
        cho các request đọc này khi mở nhiều tab, nhưng tài khoản vẫn gen bình thường (không phải hết lượt)."""
        if (method or "POST").upper() != "POST":
            return False
        path = url.split("?")[0]
        if "/backend-api/" not in path or "/conversations" in path:
            return False
        return any(k in path for k in ("/conversation", "image", "/files", "/f/"))

    def recent(self, since: float) -> str | None:
        """Lý do nếu bị giới hạn sau mốc `since` (time.monotonic())."""
        if self.hit and self.hit[0] >= since:
            return self.hit[1]
        return None


def page_notice(page) -> str:
    """Chữ của mọi hộp thoại/banner/toast đang hiện."""
    try:
        return page.evaluate(NOTICE_JS) or ""
    except Exception:  # noqa: BLE001
        return ""
