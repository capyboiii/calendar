"""Nhận diện thông báo hết lượt / quá tải / từ chối của ChatGPT - dùng chung cho chat chữ và gen ảnh.

Ba nguồn tín hiệu (bất kỳ nguồn nào báo là đủ):
1. Chữ trên trang: lượt trả lời cuối + mọi hộp thoại / banner / toast (role=dialog|alert|status, toast...).
2. Mạng: phản hồi HTTP 429 (quá nhiều request) hoặc 503 (quá tải) từ máy chủ ChatGPT, hoặc JSON lỗi
   có mã rate_limit / usage_limit - không phụ thuộc câu chữ, ChatGPT đổi câu thông báo vẫn bắt được.
3. Gửi tin nhắn không đi mà trang đang hiện thông báo giới hạn -> coi là hết lượt, không phải lỗi tạm.

Phân loại:
- "ip_refused": từ chối vì quyền bên thứ ba / nhãn hiệu / bản quyền, hoặc vì quy định về ảnh khỏa thân / tình dục /
  khiêu dâm -> bỏ hẳn cuốn, không thử lại.
- "quota": tài khoản hết lượt / bị giới hạn tốc độ / hệ thống quá tải -> tài khoản NGHỈ; hết cả 5 tài khoản thì
  batch tạm dừng, chờ rồi thử lại (calforge/pipeline.py _wait_for_quota). Không tính vào số lần thử của ảnh.
- "refused": nội dung bị từ chối -> ảnh đó hỏng, không thử lại trên tài khoản khác.
- "error": lỗi tạm (mạng, lỗi sinh ảnh) -> thử lại, tối đa max_attempts.
"""
from __future__ import annotations

import re
import time
import unicodedata

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
    "quá tải", "máy chủ đang bận", "hệ thống đang bận",
)

# Câu mơ hồ: chỉ tính là hết lượt khi KHÔNG phải câu từ chối (vd "I can't create that... try again in a new chat")
QUOTA_WEAK = ("try again in", "please try again in", "come back later", "come back after", "wait until",
              "thử lại sau vài", "quay lại sau")

# Từ chối vì quyền sở hữu trí tuệ của bên thứ ba. Kiểm tra nhóm này trước REFUSE_PAT để workflow
# phân biệt được lỗi kết thúc vĩnh viễn của cuốn với một lời từ chối nội dung chung.
IP_REFUSE_PAT = (
    # English
    "third-party content", "third party content", "third-party intellectual property",
    "third party intellectual property", "third-party ip", "third party ip", "third-party rights",
    "third party rights", "copyrighted character", "copyrighted characters", "copyright-protected",
    "protected by copyright", "copyright infringement", "infringe copyright", "infringes copyright",
    "may infringe", "trademarked character", "trademarked characters", "trademark infringement",
    "protected trademark", "registered trademark", "intellectual property rights", "someone else's ip",
    "another party's intellectual property", "rights of others", "licensed character", "licensed characters",
    # Vietnamese
    "nội dung của bên thứ ba", "quyền của bên thứ ba", "quyền sở hữu trí tuệ của bên thứ ba",
    "sở hữu trí tuệ của bên thứ ba", "tài sản trí tuệ của bên thứ ba", "vi phạm bản quyền",
    "xâm phạm bản quyền", "được bảo hộ bản quyền", "nhân vật có bản quyền", "nhân vật được bảo hộ",
    "vi phạm nhãn hiệu", "xâm phạm nhãn hiệu", "nhãn hiệu đã đăng ký", "thương hiệu đã đăng ký",
    "vi phạm thương hiệu", "xâm phạm thương hiệu", "quyền sở hữu trí tuệ", "nhân vật được cấp phép",
)

IP_TERMS = (
    "third party", "copyright", "trademark", "intellectual property", "licensed character",
    "rights of others", "someone else's ip", "another party's", "ben thu ba", "ban quyen",
    "nhan hieu", "thuong hieu", "so huu tri tue", "tai san tri tue", "nhan vat duoc cap phep",
)

IP_REFUSAL_SIGNALS = (
    "can't", "cannot", "unable", "won't", "not able", "not permitted", "not allowed", "decline",
    "refuse", "sorry", "may violate", "might violate", "could violate", "violates", "violation",
    "infringe", "infringement", "policy", "policies", "protected", "restricted", "avoid creating",
    "rat tiec", "khong the", "khong duoc", "tu choi", "co the vi pham", "vi pham", "xam pham",
    "chinh sach", "quy dinh", "duoc bao ho", "khong ho tro", "khong the giup", "khong the tao",
)


def _normalized(text: str) -> tuple[str, str]:
    """Trả về bản thường đã gộp dấu câu và bản không dấu để chịu được mọi locale/UI của ChatGPT."""
    low = unicodedata.normalize("NFKC", text or "").lower().replace("’", "'").replace("`", "'")
    low = re.sub(r"[‐‑‒–—−-]+", " ", low)
    low = " ".join(low.split())
    ascii_text = "".join(c for c in unicodedata.normalize("NFKD", low) if not unicodedata.combining(c))
    return low, ascii_text.replace("đ", "d")


def is_ip_refusal(text: str) -> bool:
    """Có cả chủ đề IP/TM và ngữ cảnh từ chối/vi phạm; tránh loại nhầm câu nhắc IP trung tính."""
    low, plain = _normalized(text)
    if any(p in low for p in IP_REFUSE_PAT):
        # Các cụm IP trực tiếp vẫn cần ngữ cảnh lỗi. Ví dụ "use licensed third-party content" không phải từ chối.
        return any(s in low or s in plain for s in IP_REFUSAL_SIGNALS)
    return (any(term in low or term in plain for term in IP_TERMS)
            and any(signal in low or signal in plain for signal in IP_REFUSAL_SIGNALS))

# Từ chối vì quy định về ảnh khỏa thân / tình dục / khiêu dâm: cũng bỏ hẳn cuốn như IP/TM (ý tưởng cuốn đó không
# gen được, thử lại chỉ tốn lượt). So trên bản không dấu.
ADULT_TERMS = (
    "khoa than", "khieu dam", "noi dung tinh duc", "ve tinh duc", "tinh duc hoac",
    "nudity", "sexual content", "sexually explicit", "sexuality", "erotic", "pornograph",
)


def is_adult_refusal(text: str) -> bool:
    """Có cả chủ đề khỏa thân/tình dục và ngữ cảnh từ chối/vi phạm."""
    low, plain = _normalized(text)
    return (any(term in plain for term in ADULT_TERMS)
            and any(signal in low or signal in plain for signal in IP_REFUSAL_SIGNALS))


# Tài khoản bị khoá / vô hiệu hoá (so trên bản không dấu): không thử lại, nghỉ hẳn, báo người dùng thay tài khoản.
BANNED_PAT = (
    "account has been deactivated", "account was deactivated", "account deactivated", "account has been suspended",
    "account suspended", "account has been disabled", "account has been banned", "your account was flagged",
    "access terminated", "deleted or deactivated", "tai khoan cua ban da bi vo hieu", "tai khoan da bi vo hieu",
    "tai khoan cua ban da bi dinh chi", "tai khoan da bi dinh chi", "tai khoan cua ban da bi khoa",
)


def is_banned(text: str) -> bool:
    _low, plain = _normalized(text)
    return any(p in plain for p in BANNED_PAT)


# Từ chối nội dung
REFUSE_PAT = (
    "i can't help with that", "i cannot help with that", "i'm unable to create", "i can't create",
    "i cannot create", "i'm not able to generate", "i can't generate", "i cannot generate",
    "content policy", "content policies", "usage policies", "violates", "may violate our", "might violate our",
    "not able to help with", "i won't be able to",
    "tôi không thể tạo", "vi phạm chính sách",
)

# Lỗi tạm: thử lại
TEMP_PAT = (
    "something went wrong", "an error occurred", "error generating", "network error", "error in message stream",
    "there was an error", "hmm...something seems to have gone wrong", "something seems to have gone wrong",
    "conversation not found", "failed to fetch", "request timed out", "bad gateway", "gateway timeout",
    "please try again", "try again later", "unable to generate", "wasn't able to generate", "could not generate",
    "đã xảy ra lỗi", "có lỗi xảy ra", "thử lại sau",
    # lỗi phía server / mạng của ChatGPT (soát 06/10/2026): nhận ngay là lỗi tạm thay vì chờ 45s im lặng
    "internal server error", "server error", "server had an error", "status code 5", "error in body stream",
    "unable to load conversation", "trouble connecting", "issue generating", "problem generating",
    "generation failed", "lỗi mạng", "lỗi máy chủ", "đã xảy ra sự cố", "gặp sự cố",
)

# Mọi khối thông báo ngoài lượt trả lời: hộp thoại, banner, toast
NOTICE_SELECTOR = ('[role="dialog"], [role="alert"], [role="status"], .toast-root, [data-testid*="toast" i], '
                   '[class*="toast" i], [data-testid*="limit" i]')
NOTICE_JS = f"""() => Array.from(document.querySelectorAll('{NOTICE_SELECTOR}'))
  .filter((e) => e.getBoundingClientRect().width > 0).map((e) => e.innerText).join(' ').slice(-1500)"""


def quota_hint(text: str) -> str:
    """Câu nào trên trang khiến classify() kết luận hết lượt - ghi vào log để soát bắt nhầm."""
    low, _plain = _normalized(text)
    for p in QUOTA_PAT + QUOTA_WEAK:
        if p in low:
            i = low.find(p)
            return low[max(0, i - 60):i + len(p) + 60].strip()
    return ""


def classify(text: str) -> str:
    """Chữ trên trang -> "ip_refused" | "quota" | "refused" | "error" | ""."""
    low, _plain = _normalized(text)
    if is_ip_refusal(text) or is_adult_refusal(text):
        return "ip_refused"                       # cả hai loại đều là lỗi kết thúc của cuốn
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
