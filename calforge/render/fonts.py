"""Tìm và đăng ký font cho ReportLab.

Ưu tiên font thật (Google Fonts, bản static TTF) đặt trong fonts/<Tên Family>/, vd
fonts/Lora/Lora-Regular.ttf. Chưa có thì dùng font Windows gần giống nhất và GHI LẠI là đang
dùng font dự phòng, để báo cáo render nhắc người duyệt.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = ROOT / "fonts"
WIN_FONTS = Path("C:/Windows/Fonts")

STYLE_SUFFIX = {
    "regular": ["Regular"],
    "semibold": ["SemiBold", "Medium", "Bold"],
    "bold": ["Bold", "SemiBold"],
    "italic": ["Italic", "MediumItalic"],
}

# Font Windows gần giống (chỉ để xem trước; bản bán thật nên dùng font thật trong fonts/)
WIN_FALLBACK = {
    "Cormorant Garamond": ("GARA.TTF", "GARABD.TTF", "GARAIT.TTF"),
    "EB Garamond": ("GARA.TTF", "GARABD.TTF", "GARAIT.TTF"),
    "Cinzel": ("GARA.TTF", "GARABD.TTF", "GARAIT.TTF"),
    "Playfair Display": ("BOD_R.TTF", "BOD_B.TTF", "BOD_I.TTF"),
    "Libre Baskerville": ("BASKVILL.TTF", "palab.ttf", "palai.ttf"),
    "Lora": ("pala.ttf", "palab.ttf", "palai.ttf"),
    "Montserrat": ("GOTHIC.TTF", "GOTHICB.TTF", "GOTHICI.TTF"),
    "Josefin Sans": ("GOTHIC.TTF", "GOTHICB.TTF", "GOTHICI.TTF"),
    "Raleway": ("GOTHIC.TTF", "GOTHICB.TTF", "GOTHICI.TTF"),
    "Nunito Sans": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf"),
}
DEFAULT_FALLBACK = ("georgia.ttf", "georgiab.ttf", "georgiai.ttf")

fallbacks_used: set[str] = set()


def _real_font_file(family: str, style: str) -> Path | None:
    folder = FONT_DIR / family
    if not folder.is_dir():
        return None
    base = family.replace(" ", "")
    for suffix in STYLE_SUFFIX[style]:
        for f in (folder / f"{base}-{suffix}.ttf", folder / "static" / f"{base}-{suffix}.ttf"):
            if f.exists():
                return f
    return None


def font(family: str, style: str = "regular") -> str:
    """Tên font đã đăng ký với ReportLab cho (family, style)."""
    name = f"{family.replace(' ', '')}-{style}"
    if name in pdfmetrics.getRegisteredFontNames():
        return name
    path = _real_font_file(family, style)
    if path is None:
        files = WIN_FALLBACK.get(family, DEFAULT_FALLBACK)
        pick = {"regular": files[0], "semibold": files[1], "bold": files[1], "italic": files[2]}[style]
        path = WIN_FONTS / pick
        fallbacks_used.add(f"{family} → {pick}")
    pdfmetrics.registerFont(TTFont(name, str(path)))
    return name
